# -*- coding: utf-8 -*-
"""The calibration a run is reviewed on, and whether it may be released
(Part 1).

    review_state(own_rows, manifest, reused_rows, ws_id) -> {
        "source":  "run"      the run calibrated (its own curves)
                   "reused"   the run used an earlier approved curve
                   "none"     no curve found for it
        "status":  "approved" | "pending" | "rejected" | "missing",
        "run_date": the curve's run date,
        "approved_by", "approved_at", "note", "pending": [analytes]}

  own_rows     the curves the worksheet used (store.calibrations_for_batch:
               its own and any it re-used, each with `used_from`)
  manifest     the Run Builder's run manifest ({} for a run built without it)
  reused_rows  the calibration rows of the curve the manifest says it reused
               (only when the worksheet has no curve of its own on record)
  ws_id        the worksheet: a curve run on another one is "reused"

The data decides which curve a run used: the
manifest only matters for a run with no curve on record.

A curve is approved when every analyte's row is approved (status approved,
or approved_by recorded by the older page); one rejected analyte makes the
run's curve rejected. Release waits for "approved".

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

APPROVED, PENDING, REJECTED, MISSING = "approved", "pending", "rejected", "missing"


def row_state(row):
    st = (row.get("status") or u"pending").lower()
    if st == REJECTED:
        return REJECTED
    if st == APPROVED or row.get("approved_by"):
        return APPROVED
    return PENDING


def _summary(rows, source):
    """The state of a set of curve rows (see review_state)."""
    states = [row_state(r) for r in rows]
    if REJECTED in states:
        status = REJECTED
    elif states and all(s == APPROVED for s in states):
        status = APPROVED
    else:
        status = PENDING
    first = rows[0] if rows else {}
    approved = [r for r in rows if r.get("approved_by")]
    return {"source": source, "status": status,
            "run_date": (u"%s" % (first.get("run_date") or u""))[:10],
            "approved_by": approved[0].get("approved_by") if approved else u"",
            "approved_at": (u"%s" % (approved[0].get("approved_at") or u""))[:19] if approved else u"",
            "note": u"; ".join(sorted(set(r.get("notes") or u"" for r in rows if r.get("notes")))),
            "pending": sorted(r.get("analyte") or u"" for r, s in zip(rows, states) if s != APPROVED),
            "from": u", ".join(sorted(set(r.get("used_from") or u"" for r in rows) - set([u""]))),
            "n": len(rows)}


def review_state(own_rows, manifest, reused_rows, ws_id=None):
    own_rows = list(own_rows or [])
    if own_rows:
        elsewhere = ws_id and any((r.get("used_from") or ws_id) != ws_id for r in own_rows)
        return _summary(own_rows, u"reused" if elsewhere else u"run")
    cal = (manifest or {}).get("calibration") or {}
    if cal and not cal.get("new_curve") and reused_rows:
        return _summary(list(reused_rows), u"reused")
    return {"source": u"none", "status": MISSING, "run_date": u"", "approved_by": u"",
            "approved_at": u"", "note": u"", "pending": [], "from": u"", "n": 0}


def reused_run_date(manifest):
    """The run date of the curve a reused-curve run relied on, or ""."""
    cal = (manifest or {}).get("calibration") or {}
    if cal.get("new_curve"):
        return u""
    return (u"%s" % ((cal.get("last_curve") or {}).get("run_date") or u""))[:10]


def gate_reason(state):
    """(verdict, reason) the QC Summary gate adds for the run's calibration;
    (None, "") when it is approved."""
    st = state.get("status")
    if st == APPROVED:
        return None, u""
    if st == REJECTED:
        return "fail", u"the run's calibration was rejected%s" % (
            (u": %s" % state["note"]) if state.get("note") else u"")
    if st == MISSING:
        return "blocked", u"no calibration found for this run"
    return "blocked", u"the run's calibration is not approved yet (Calibration tab)"
