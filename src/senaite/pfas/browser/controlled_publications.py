# -*- coding: utf-8 -*-
"""
Controlled publication register (D65, Phase B).

Every issuance of a Certificate of Analysis is a controlled documentation
publication. The issuance event is the sample's `publish` / `publish_immediately`
workflow transition (the confirmed authorization event, D45/D65 — NOT ARReport
creation, which also fires on a plain "Save" draft).

On each publish transition we APPEND an immutable entry to a publication log
annotated on the sample. The log is authoritative for revision numbering and
supersede chains; it REFERENCES the core ARReport artifact (for the live PDF /
recipients / date) rather than duplicating it (Golden Rule 3).

  revision      = position in the log (1 = original issue, 2+ = amended reissue)
  issued_at     = ISO timestamp of the publish transition
  authorizer    = the publishing user (= the CoA "Authorized by" actor)
  report_uid    = the sample's most-recent ARReport at issue time (best-effort)
  amendment_reason / reason_missing = per the best-effort policy (D65): a reissue
                  (revision >= 2) with no reason captured is FLAGGED, not blocked.
  Status is COMPUTED (latest revision = current; earlier = superseded) — never
  stored, so the historical entries are never mutated.

Python 2.7 compatible.
"""
from __future__ import absolute_import

import logging

from bika.lims import api
from DateTime import DateTime
from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.controlled_publications")

# Publication log lives on the sample (AnalysisRequest).
PUBLICATION_LOG_KEY = u"senaite.pfas.controlled_pub_log"
# Transient amendment reason, set by the PFAS "Generate COA" path just before a
# reissue and consumed (cleared) by the publish subscriber.
PENDING_REASON_KEY = u"senaite.pfas.pending_amendment_reason"

PUBLISH_TRANSITIONS = ("publish", "publish_immediately")


# ── event subscriber (mirrors egad_publish.on_after_transition) ─────────────

def on_after_transition(instance, event):
    """Record a controlled publication on every CoA issuance."""
    if getattr(event, "transition", None) is None:
        return
    if instance.portal_type != "AnalysisRequest":
        return
    if event.transition.id not in PUBLISH_TRANSITIONS:
        return
    try:
        record_publication(instance)
    except Exception as exc:  # never break the publish transition
        logger.error("controlled-pub: failed to record for %s: %s",
                     api.get_id(instance), exc)


def record_publication(ar):
    """Append an immutable issuance entry to the sample's publication log."""
    ann = IAnnotations(ar)
    log = list(ann.get(PUBLICATION_LOG_KEY, []))
    revision = len(log) + 1

    reason = _pop_pending_reason(ar)
    reason_missing = bool(revision >= 2 and not reason)

    prev = log[-1] if log else None
    entry = {
        "revision": revision,
        "report_id": u"{0}-R{1}".format(api.get_id(ar), revision),
        "issued_at": DateTime().ISO(),
        "authorizer": _current_userid(),
        "report_uid": _latest_arreport_uid(ar),
        "amendment_reason": reason or u"",
        "reason_missing": reason_missing,
        "supersedes": prev["report_id"] if prev else None,
    }
    log.append(entry)
    ann[PUBLICATION_LOG_KEY] = log
    logger.info("controlled-pub: %s issued (rev %s%s)",
                entry["report_id"], revision,
                ", reason not recorded" if reason_missing else "")
    return entry


# ── read side (register view + report header) ───────────────────────────────

def get_publication_log(ar):
    """Return the sample's issuance entries, newest first, with computed
    status ('current' for the latest revision, else 'superseded')."""
    ann = IAnnotations(ar)
    log = list(ann.get(PUBLICATION_LOG_KEY, []))
    if not log:
        return []
    top = len(log)
    out = []
    for entry in log:
        row = dict(entry)
        row["status"] = "current" if entry["revision"] == top else "superseded"
        out.append(row)
    out.reverse()
    return out


def get_current_publication(ar):
    """Return the current (latest) issuance entry for the sample, or None."""
    log = get_publication_log(ar)
    return log[0] if log else None


def set_pending_amendment_reason(ar, reason):
    """Stash a reissue reason to be consumed by the next publish transition."""
    ann = IAnnotations(ar)
    if reason:
        ann[PENDING_REASON_KEY] = api.safe_unicode(reason)
    elif PENDING_REASON_KEY in ann:
        del ann[PENDING_REASON_KEY]


# ── helpers ─────────────────────────────────────────────────────────────────

def _pop_pending_reason(ar):
    ann = IAnnotations(ar)
    reason = ann.get(PENDING_REASON_KEY)
    if PENDING_REASON_KEY in ann:
        del ann[PENDING_REASON_KEY]
    return reason

def _current_userid():
    try:
        return api.get_current_user().getId()
    except Exception:
        return u""

def _latest_arreport_uid(ar):
    """The sample's most-recent ARReport by creation (container traversal, not
    a catalog query — the report may have just been created)."""
    reports = [o for o in ar.objectValues() if o.portal_type == "ARReport"]
    if not reports:
        return None
    reports.sort(key=lambda o: o.created(), reverse=True)
    return api.get_uid(reports[0])
