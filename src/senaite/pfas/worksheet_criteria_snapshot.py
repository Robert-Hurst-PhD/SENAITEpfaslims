# -*- coding: utf-8 -*-
"""
Write-once resolved-criteria snapshot, frozen on a Worksheet at the ISO
17025 Sec7.8.4 technical review (GAPS.md Sec26).

The problem (GAPS.md Sec24): resolved_criteria_store.write_resolved_file()
writes one file PER BATCH and overwrites it unconditionally every time a
project link is (re)assigned. A batch judged and reported under one set of
criteria, then re-linked to a different project, resolves afterwards to
whatever the criteria are NOW -- the certificate says one thing, the
system's record of why says another. CLAUDE.md Sec1 rule 6 requires a
result to name its parentage; a parent that can be edited after the fact is
not parentage.

The fix, same shape as qc_review_report.snapshot_for_publication (read that
docstring first -- this is the identical idea applied one step earlier in
the chain): freeze the resolved rows that governed a worksheet's batch onto
the WORKSHEET itself, at the moment a Manager approves it (Worksheet ->
verified). One ZODB annotation, written ONCE. A re-verification (retract,
fix something, re-submit, re-approve) must show what the FIRST approval saw,
not what criteria happen to resolve to today -- exactly the property
qc_review_report protects for the rendered report itself.

Per-object data (CLAUDE.md Sec7: one ZODB object -> annotate it) -- this is
the Worksheet's own record of what governed it, not a cross-object,
date-indexed table (that's SQLite) and not a binary artefact (that's the
filesystem). The per-batch file in resolved_criteria_store stays exactly
what it was: a freely regenerable working artefact for the Py3 pipeline
worker's NEXT run. It is never read for history after this change.

Three states, not two -- read before assuming "no snapshot" is the only
failure mode:

  * "frozen"     -- resolution succeeded; `criteria` carries the rows.
                    WRITE-ONCE: a second freeze attempt is a no-op that
                    returns the ORIGINAL payload unchanged. This is the
                    whole point; see store_snapshot().
  * "unresolved" -- resolution was never attempted because method_id or
                    matrix (or both) could not be determined for this
                    worksheet at verification time. Recording a payload
                    with an EMPTY criteria list under status "frozen" would
                    assert "this is what governed" when the truth is "we
                    could not tell" -- exactly the failure Sec15 already
                    named (UNKNOWN must never read as CONFORMS) in a new
                    costume. Mirrors export_resolved_criteria's own refusal
                    to write a partial/guessed file.
  * "failed"     -- method_id/matrix WERE known, resolution was attempted,
                    and it raised. Not judgement history (nothing was
                    judged), so unlike "frozen" it MAY be superseded by a
                    later attempt -- but it must never be silently retried
                    into invisibility: a "failed once, then froze" history
                    is carried forward under a `superseded` key so the first
                    attempt's failure is not erased by the second's success.

A reader asking "what governed this worksheet's batch?" calls
get_frozen_criteria() and gets back one of: a "frozen" payload (the answer),
or None / a non-"frozen" payload, which it MUST present as "not recorded" --
never fall back to resolving live criteria and presenting that as history.
That is Sec15's rule applied to history, and it is the exact failure this
module exists to prevent.

Failure handling (verification must never hang on record-keeping): freezing
NEVER raises out of freeze_resolved_criteria(). Any exception during
resolution is caught and turned into a "failed" marker; any exception
writing the annotation itself is caught by the caller (data_review.py) so a
storage failure can never block the workflow transition that already
happened.

Pure core / thin ZODB shell, same split as ruleset.py / resolved_criteria_
store.py: build_snapshot_payload(), build_unresolved_marker(),
build_failure_marker(), and store_snapshot()/read_snapshot() touch no
ZODB/Plone API and take a plain dict-like `store` so
tests/test_worksheet_criteria_snapshot.py exercises them directly under
plain Python 3. freeze_resolved_criteria()/get_frozen_criteria() are the
thin shells that resolve `store` to `IAnnotations(ws)` and are proven live
against the running instance (imports are local to the function bodies for
exactly the reason resolved_criteria_store.py's own shells keep theirs
local: zope.annotation is not importable outside the Zope container, and
must not be a module-level import here or this module could not be loaded
by path under plain python3 the way the test file loads it).

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

# The transition the freeze hangs on. Kept here, Zope-free, so the subscriber's
# guard has exactly one definition and can be tested without a Zope instance --
# data_review.on_after_transition imports Zope at module load and cannot be
# exercised by the standalone harness.
FREEZE_PORTAL_TYPE = u"Worksheet"
FREEZE_TRANSITION  = u"verify"


def should_freeze(portal_type, transition_id):
    """True only for a Worksheet completing `verify`.

    This is the reject-fast guard for a subscriber that runs on EVERY workflow
    transition in the site, so it must be cheap and it must be exact: freezing
    on the wrong transition would record a judgement that had not been made,
    and freezing on the wrong type would write the annotation onto an object
    whose criteria nobody asked about.
    """
    return (portal_type == FREEZE_PORTAL_TYPE
            and transition_id == FREEZE_TRANSITION)


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + u"Z"


# ── Pure: payload construction ───────────────────────────────────────────────

def build_snapshot_payload(batch_id, method_id, matrix, rows, frozen_at=None,
                            superseded=None):
    """The JSON-ready payload frozen onto a worksheet's annotations once
    resolution actually succeeded. Carries everything a later audit needs:
    the resolved rows themselves (value, tier, source_doc, source_rev,
    conformance, departure -- resolved_criteria_store._row_from_resolved's
    exact shape, unchanged) plus the batch/method/matrix this run was
    judged against and the moment it was frozen.

    `superseded`, when given, is a prior "failed"/"unresolved" marker this
    payload replaces -- carried forward so a "failed once, then froze on
    retry" history is never silently erased by the very fix that made it
    succeed (see store_snapshot's docstring; this is the SAME contract
    build_failure_marker's `superseded` parameter honours, applied to the
    success path too)."""
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
    both known at verification time -- resolution was never attempted, so
    there is nothing to enumerate, and an empty `criteria` list must never
    be dressed up as "this is what governed" (see module docstring)."""
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
    raised. Distinguishable from STATUS_UNRESOLVED (nothing to resolve) and
    from silence (no annotation at all -- "never attempted"). `superseded`,
    when given, is the marker this one replaces -- carried forward so a
    later successful freeze does not erase the evidence that an earlier
    attempt failed."""
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

    This is the write-once guarantee itself: a "frozen" snapshot is
    judgement history and must never be replaced, by design, no matter what
    is handed in (a second verification, a re-resolved value, anything). A
    "failed" or "unresolved" marker is NOT judgement history -- nothing was
    judged -- so a later attempt (frozen, failed, or unresolved) MAY replace
    it; when replacing a "failed" marker with anything, the old marker is
    carried forward under `superseded` on the NEW payload so the fact that
    an earlier attempt failed is never silently lost (see
    build_failure_marker's `superseded` parameter -- callers building a
    replacement payload should pass the prior marker there before calling
    this function, since this function itself never mutates a payload it is
    handed).

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
    frozen for this worksheet. Returns a DEEP COPY -- a write-once record
    must not be mutable through the hand a reader was given back."""
    payload = store.get(SNAPSHOT_KEY)
    if payload is None:
        return None
    return copy.deepcopy(payload)


# ── Thin ZODB shells (not exercised by the plain-Python-3 test harness — ────
# proven live, like resolved_criteria_store.export_resolved_criteria()) ──────

def freeze_resolved_criteria(portal, ws, batch, method_id, matrix):
    """The write-once freeze point: called from data_review.py's
    _handle_approve_release(), the ISO 17025 Sec7.8.4 technical review,
    immediately after a Worksheet's analyses and the Worksheet itself
    transition to `verified`.

    NEVER raises -- a failure here must never block a workflow transition
    that has already happened (GAPS.md Sec26). Every failure mode still
    leaves a marker distinguishable from "never attempted": see the module
    docstring's three states.

    `batch` may be None (no linked SENAITE Batch could be found for this
    worksheet); `method_id`/`matrix` may be empty strings. Returns the
    effective payload (whatever ends up stored -- frozen, unresolved, or
    failed), or None if even writing the annotation itself failed (the
    outer caller's own try/except is the last line of defence for that
    case; see data_review.py).
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
        # A deep copy, same as read_snapshot() -- a write-once record must
        # never be handed out mutable from ANY entry point, including this
        # early return (get_frozen_criteria() is not the only caller who can
        # ask "what's there already").
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
            # A prior "failed"/"unresolved" attempt is not judgement history,
            # but its EVIDENCE is -- carry it forward so a retry that
            # succeeds does not erase the fact that an earlier one did not
            # (GAPS.md Sec26; the same reasoning build_failure_marker's
            # `superseded` already applies to a failed->failed retry, here
            # applied to failed/unresolved->frozen).
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
    "failed"), or None if no snapshot was ever written -- e.g. every
    worksheet verified before this module existed. NEVER falls back to
    resolving live criteria. A caller asking "what governed these results?"
    must treat anything other than a "frozen" payload as "not recorded" --
    see the module docstring; this is Sec15's rule (UNKNOWN never reads as
    CONFORMS) applied to history."""
    from zope.annotation.interfaces import IAnnotations
    return read_snapshot(IAnnotations(ws))
