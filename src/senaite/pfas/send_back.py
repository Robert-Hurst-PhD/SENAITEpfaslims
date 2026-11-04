# -*- coding: utf-8 -*-
"""A lot rejected after the run was built sends the run back to the stage
that can fix it: the Run Builder for a lot the instrument was loaded with
(a calibration level, the ICV or CCV, an LC solvent channel, or a parent of
one), the guided extraction for a lot the extraction used. Release waits
until the run is rebuilt.

The run's manifest carries "sent_back" ({"stage", "reason", "lot", "by",
"at"}) until a rebuild replaces it; before a run is built there is none to
mark, and the reopened extraction holds release. For an extraction lot, the stage whose
rows used the lot is reopened with the reason (extraction_review.reopen),
even after the extraction was finalized: the finalizing is kept in the
session's "sent_back" list, and the extraction is finalized again once
corrected.

    stage_for(source_or_slot)                       -> "run" | "extraction"
    stage_using(session, uid)                       -> stage order or None
    apply(manifest, session, stage, reason, lot, who, at, uid=None)
                                                    -> (manifest, session)
    blocks_release(manifest)                        -> bool
    clear(manifest)                                 -> manifest

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy

from senaite.pfas import extraction_review

RUN, EXTRACTION = u"run", u"extraction"
_RUN_SLOTS = (u"ICV", u"CCV")


def stage_for(source_or_slot):
    s = u"%s" % (source_or_slot or u"")
    if s == RUN or s.startswith(u"run.") or s in _RUN_SLOTS \
            or s.startswith(u"CAL-") or s.startswith(u"LC:"):
        return RUN
    return EXTRACTION


def stage_using(session, uid):
    """The first stage whose recorded lots include the inventory item."""
    if not uid:
        return None
    stages = (session or {}).get("stages") or {}
    for order in sorted(stages, key=lambda k: (len(u"%s" % k), u"%s" % k)):
        for row in (stages[order] or {}).get("reagents") or []:
            if isinstance(row, dict) and row.get("inventory_uid") == uid:
                return u"%s" % order
    return None


def apply(manifest, session, stage, reason, lot, who, at, uid=None):
    manifest = dict(manifest or {})
    if manifest.get("built_at"):            # no run built yet: nothing to mark
        manifest["sent_back"] = {"stage": stage, "reason": reason, "lot": lot, "by": who, "at": at}
    session = copy.deepcopy(session or {})
    order = stage_using(session, uid) if stage == EXTRACTION else None
    if order is None:
        return manifest, session
    record = {"reason": reason, "lot": lot, "by": who, "at": at, "stage": order,
              "was_finalized_at": session.get("finalized_at") or u"",
              "was_finalized_by": session.get("finalized_by") or u""}
    session["finalized"] = False
    session, why = extraction_review.reopen(session, order, reason, who, at)
    if why:
        raise ValueError(why)
    session.setdefault("sent_back", []).append(record)
    return manifest, session


def blocks_release(manifest):
    return bool((manifest or {}).get("sent_back"))


def clear(manifest):
    return dict((k, v) for k, v in (manifest or {}).items() if k != "sent_back")
