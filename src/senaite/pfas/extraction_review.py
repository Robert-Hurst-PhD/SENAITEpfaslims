# -*- coding: utf-8 -*-
"""What the guided extraction shows, and the summary of what it recorded
(docs/EXTRACTION_REVIEW_REPORTING_PLAN.md; DECISIONS 2026-10-02 "Extraction
UI, Data Review, reporting template").

    mode(session, orders, view_order)  -> "edit" | "view" | "review" | "done"
    next_stage(orders, session)        -> the first stage not yet completed
    reopen(session, order, reason, by, at) -> (session, "") or (session, why)
    stage_summary(order, name, data)   -> one stage as the review shows it
    review(session, stages_def)        -> every stage, in order

A completed stage is corrected by reopening it with a reason: the previous
version is kept under "corrections" and travels with the stage (logbook PDF,
Data Review). After finalizing, a stage is never reopened here -- that is a
deviation. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy


def _done(session):
    return set(u"%s" % k for k in ((session or {}).get("stages") or {}))


def next_stage(orders, session):
    done = _done(session)
    for o in sorted(orders or []):
        if u"%s" % o not in done:
            return o
    return None


def mode(session, orders, view_order=None):
    session = session or {}
    if session.get("finalized"):
        return u"done"
    if session.get("reopened") is not None:
        return u"edit"
    if view_order is not None and u"%s" % view_order in _done(session):
        return u"view"
    return u"review" if orders and next_stage(orders, session) is None else u"edit"


def reopen(session, order, reason, by, at):
    """Reopen a completed stage for correction, keeping what it held."""
    session = copy.deepcopy(session or {})
    key = u"%s" % order
    stage = (session.get("stages") or {}).get(key)
    if session.get("finalized"):
        return session, u"The extraction is finalized: record a deviation instead."
    if stage is None:
        return session, u"That stage has not been completed."
    if not (reason or u"").strip():
        return session, u"Say why the stage is being corrected."
    previous = dict((k, v) for k, v in stage.items() if k != "corrections")
    stage.setdefault("corrections", []).append(
        {"at": at, "by": by, "reason": reason.strip(), "previous": previous})
    session["reopened"] = order
    session["current_stage"] = order
    return session, u""


def _rows(data, group):
    return [r for r in (data.get("reagents") or [])
            if isinstance(r, dict) and (r.get("group") or u"reagent") == group]


def stage_summary(order, name, data):
    data = data or {}
    lot = lambda r: {"role": r.get("role") or u"", "name": r.get("name") or u"",  # noqa: E731
                     "lot": r.get("lot") or u"", "qty": r.get("qty_used") or u"",
                     "from_inventory": bool(r.get("from_inventory"))}
    return {
        "order": order, "name": name or u"Stage %s" % order,
        "completed_at": data.get("completed_at") or u"",
        "analyst": data.get("analyst") or u"",
        "reagents": [lot(r) for r in _rows(data, u"reagent")],
        "consumables": [lot(r) for r in _rows(data, u"consumable")],
        "equipment": sorted((k, v) for k, v in (data.get("equipment_sns") or {}).items()),
        "samples": [{"sample_id": s.get("sample_id") or u"", "value": s.get("value") or u"",
                     "unit": s.get("unit") or u""} for s in data.get("samples") or []],
        "deviations": data.get("deviations") or u"",
        "warnings": list(data.get("warnings") or []),
        "corrections": [{"at": c.get("at") or u"", "by": c.get("by") or u"",
                         "reason": c.get("reason") or u""}
                        for c in data.get("corrections") or []],
    }


def review(session, stages_def):
    """Every stage in order: recorded ones summarised, the rest marked
    missing; plus the counts the review screen and Data Review flag."""
    done = (session or {}).get("stages") or {}
    out = []
    for st in sorted(stages_def or [], key=lambda s: s.get("order", 0)):
        data = done.get(u"%s" % st.get("order"))
        row = stage_summary(st.get("order"), st.get("name"), data)
        row["recorded"] = data is not None
        out.append(row)
    return {
        "stages": out,
        "missing": [s["order"] for s in out if not s["recorded"]],
        "noted": sum(1 for s in out if s["warnings"]),
        "unnoted": [s["order"] for s in out if s["warnings"] and not s["deviations"]],
        "corrections": sum(len(s["corrections"]) for s in out),
    }
