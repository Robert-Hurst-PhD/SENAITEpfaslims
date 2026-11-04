# -*- coding: utf-8 -*-
"""
Write-once resolved-criteria snapshot, frozen on a Worksheet at the ISO
17025 Sec7.8.4 technical review.

resolved_criteria_store.write_resolved_file() rewrites one file PER BATCH
whenever a project link is (re)assigned, so it cannot say what governed a
batch already judged. A result must name its parentage, and a parent
editable after the fact is not parentage. So the resolved rows that
governed a worksheet's batch are frozen onto the WORKSHEET when a Manager
approves it (Worksheet -> verified): one ZODB annotation, written
ONCE. A re-verification shows what the FIRST approval saw. Same idea as
qc_review_report.snapshot_for_publication, one step earlier in the chain.
The per-batch file stays a regenerable working file for the worker's next
run and is never read for history.

Three states:

  * "frozen"     -- resolution succeeded; `criteria` carries the rows.
                    WRITE-ONCE: a second freeze returns the ORIGINAL
                    payload unchanged (store_snapshot()).
  * "unresolved" -- method_id or matrix could not be determined at
                    verification time, so nothing was resolved. An empty
                    "frozen" list would read "this governed" when the truth
                    is "we could not tell": UNKNOWN never reads as
                    CONFORMS.
  * "failed"     -- method_id/matrix were known and resolution raised.
                    Nothing was judged, so a later attempt MAY supersede
                    it, carrying it forward under `superseded`.

A reader calls get_frozen_criteria() and presents anything but a "frozen"
payload as "not recorded", never live criteria as history.

Freezing NEVER raises out of freeze_resolved_criteria(): a resolution error
becomes a "failed" marker, and the caller (data_review.py) catches a
storage error, so record-keeping never blocks the transition.

Pure core / thin ZODB shell: the build_* functions, store_snapshot() and
read_snapshot() take a plain dict-like `store` and run under plain Python 3
(tests/test_worksheet_criteria_snapshot.py). freeze_resolved_criteria() and
get_frozen_criteria() resolve `store` to IAnnotations(ws); zope.annotation
is imported inside them so the module loads by path outside Zope.

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import datetime
import logging

logger = logging.getLogger("senaite.pfas.worksheet_criteria_snapshot")

SNAPSHOT_KEY = u"senaite.pfas.worksheet_criteria_snapshot"

STATUS_FROZEN     = u"frozen"
STATUS_UNRESOLVED = u"unresolved"
STATUS_FAILED     = u"failed"

# The transition the freeze hangs on, Zope-free so the subscriber's guard has
# one definition testable without Zope.
FREEZE_PORTAL_TYPE = u"Worksheet"
FREEZE_TRANSITION  = u"verify"


def should_freeze(portal_type, transition_id):
    """True only for a Worksheet completing `verify`: the cheap, exact guard
    of a subscriber that runs on EVERY workflow transition."""
    return (portal_type == FREEZE_PORTAL_TYPE
            and transition_id == FREEZE_TRANSITION)


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + u"Z"


# ── Pure: payload construction ───────────────────────────────────────────────

def build_snapshot_payload(batch_id, method_id, matrix, rows, frozen_at=None,
                            superseded=None):
    """The JSON-ready payload frozen onto a worksheet's annotations once
    resolution succeeded: the resolved rows (value, tier, source_doc,
    source_rev, conformance, departure, as
    resolved_criteria_store._row_from_resolved shapes them), the
    batch/method/matrix judged against and the moment it was frozen.

    `superseded`, when given, is the prior "failed"/"unresolved" marker this
    payload replaces, carried forward so the earlier failure is not erased."""
    payload = {
        u"status":     STATUS_FROZEN,
        u"batch_id":   batch_id,
        u"method_id":  method_id,
        u"matrix":     matrix,
        u"frozen_at":  frozen_at or _now_iso(),
        u"criteria":   rows,
    }
    if superseded is not None:
        payload[u"superseded"] = superseded
    return payload


def build_unresolved_marker(batch_id, method_id, matrix, reason,
                             attempted_at=None):
    """Recorded instead of a "frozen" payload when method_id/matrix were not
    both known at verification time: nothing was resolved, and an empty
    `criteria` list must never read as "this is what governed"."""
    return {
        u"status":       STATUS_UNRESOLVED,
        u"batch_id":     batch_id,
        u"method_id":    method_id,
        u"matrix":       matrix,
        u"reason":       reason,
        u"attempted_at": attempted_at or _now_iso(),
    }


def build_failure_marker(batch_id, method_id, matrix, error,
                          attempted_at=None, superseded=None):
    """Recorded when method_id/matrix WERE known but resolving the rows
    raised, distinct from STATUS_UNRESOLVED (nothing to resolve) and from no
    annotation ("never attempted"). `superseded`, when given, is the marker
    this one replaces, carried forward."""
    payload = {
        u"status":       STATUS_FAILED,
        u"batch_id":     batch_id,
        u"method_id":    method_id,
        u"matrix":       matrix,
        u"error":        u"{0}".format(error),
        u"attempted_at": attempted_at or _now_iso(),
    }
    if superseded is not None:
        payload[u"superseded"] = superseded
    return payload


# ── Pure: write-once store, operating on any dict-like `store` ──────────────

def store_snapshot(store, payload):
    """Write SNAPSHOT_KEY on `store` (IAnnotations(ws) in production, a
    plain dict in tests) -- UNLESS a "frozen" payload is already there.

    The write-once guarantee: a "frozen" snapshot is judgement history and
    is never replaced, whatever is handed in. A "failed" or "unresolved"
    marker judged nothing, so any later payload MAY replace it; the caller
    passes the prior marker as the new payload's `superseded` (this
    function never mutates a payload).

    Returns (written, effective_payload): `written` is False only when an
    existing "frozen" payload blocked the write, in which case
    `effective_payload` is that ORIGINAL, untouched. Otherwise `written` is
    True and `effective_payload` is the `payload` just stored."""
    existing = store.get(SNAPSHOT_KEY)
    if existing and existing.get(u"status") == STATUS_FROZEN:
        return False, existing
    store[SNAPSHOT_KEY] = payload
    return True, payload


def read_snapshot(store):
    """The payload stored under SNAPSHOT_KEY, or None if nothing was ever
    frozen for this worksheet. A DEEP COPY: a write-once record is never
    handed out mutable."""
    payload = store.get(SNAPSHOT_KEY)
    if payload is None:
        return None
    return copy.deepcopy(payload)


# ── Thin ZODB shells (not run by the plain-Python-3 tests) ──────────────────

def freeze_resolved_criteria(portal, ws, batch, method_id, matrix):
    """The write-once freeze point: called from data_review.py's
    _handle_approve_release(), the ISO 17025 Sec7.8.4 technical review,
    immediately after a Worksheet's analyses and the Worksheet itself
    transition to `verified`.

    NEVER raises: a failure must never block a transition that has
    happened. Every failure still leaves a marker distinct from "never
    attempted" (the module docstring's three states).

    `batch` may be None (no linked Batch found); `method_id`/`matrix` may be
    empty. Returns the payload stored (frozen, unresolved or failed), or
    None if writing the annotation failed (data_review.py's own try/except
    covers that case).
    """
    try:
        from zope.annotation.interfaces import IAnnotations
        ann = IAnnotations(ws)
    except Exception as exc:
        logger.error(
            "freeze_resolved_criteria: could not obtain annotations for "
            "%s -- nothing recorded, not even a failure marker: %s",
            getattr(ws, "getId", lambda: "?")(), exc)
        return None

    ws_id = ws.getId()
    existing = ann.get(SNAPSHOT_KEY)
    if existing and existing.get(u"status") == STATUS_FROZEN:
        logger.info(
            "freeze_resolved_criteria: %s already frozen at %s -- keeping "
            "the original, not re-resolving", ws_id, existing.get(u"frozen_at"))
        # a deep copy, as read_snapshot(): never handed out mutable
        return copy.deepcopy(existing)

    batch_id = getattr(batch, u"getId", lambda: None)() if batch is not None else None
    prior_marker = existing if existing else None

    if not method_id or not matrix:
        logger.info(
            "freeze_resolved_criteria: %s -- method_id/matrix not both known "
            "(%r/%r) -- recording 'unresolved', not a guessed snapshot",
            ws_id, method_id, matrix)
        payload = build_unresolved_marker(
            batch_id, method_id, matrix,
            reason=u"method_id/matrix not both known at verification time")
    else:
        try:
            from senaite.pfas import resolved_criteria_store
            rows = resolved_criteria_store.resolve_rows_for_batch(
                portal, batch, method_id, matrix)
            # a prior failed/unresolved attempt is carried forward so a
            # successful retry does not erase it
            payload = build_snapshot_payload(batch_id, method_id, matrix, rows,
                                              superseded=prior_marker)
        except Exception as exc:
            logger.error(
                "freeze_resolved_criteria: %s -- resolving criteria raised: %s",
                ws_id, exc)
            payload = build_failure_marker(
                batch_id, method_id, matrix, exc, superseded=prior_marker)

    try:
        written, effective = store_snapshot(ann, payload)
    except Exception as exc:
        logger.error(
            "freeze_resolved_criteria: %s -- writing the annotation itself "
            "raised: %s", ws_id, exc)
        return None

    if written:
        logger.info(
            "freeze_resolved_criteria: %s -> status=%s (%d criteria)",
            ws_id, effective.get(u"status"), len(effective.get(u"criteria") or []))
    return effective


def get_frozen_criteria(ws):
    """What governed this worksheet's batch at the moment it was verified.

    Returns the frozen payload dict (status "frozen", "unresolved", or
    "failed"), or None if no snapshot was written. NEVER falls back to
    resolving live criteria: anything but a "frozen" payload reads as "not
    recorded": UNKNOWN never reads as CONFORMS."""
    from zope.annotation.interfaces import IAnnotations
    return read_snapshot(IAnnotations(ws))
