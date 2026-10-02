# -*- coding: utf-8 -*-
"""What the Bench landing shows a chemist first (docs/BENCH_WORKFLOW_REVIEW.md
phase 1, DECISIONS 2026-10-02): which batches need extracting, where each one
is, and which inventory items need attention. Pure; Python 2.7 and 3.

    extraction_state(session, stage_orders) -> {"state", "done", "total", "label"}
    inventory_alerts(items, today, soon_days=30) -> {"expired", "expiring",
                                                     "quarantined", "low"}

`items` = dicts with "name", "lot_number", "status", "expiry" (YYYY-MM-DD)
and, when quantities are tracked, "quantity_value" / "low_stock_level".
"""
from __future__ import absolute_import, division, unicode_literals

from datetime import datetime, timedelta

NOT_STARTED, IN_PROGRESS, FINISHED = u"not_started", u"in_progress", u"finished"
_UNUSABLE = (u"exhausted", u"archived")


def extraction_state(session, stage_orders):
    """Where a batch's extraction is: not started / stage N of M / finished."""
    total = len(stage_orders or [])
    if not session:
        return {"state": NOT_STARTED, "done": 0, "total": total, "label": u"Not started"}
    done = len([o for o in stage_orders or []
                if u"%s" % o in (session.get("stages") or {})])
    if session.get("finalized") or (total and done >= total):
        return {"state": FINISHED, "done": done, "total": total, "label": u"Finished"}
    return {"state": IN_PROGRESS, "done": done, "total": total,
            "label": u"Stage %d of %d" % (min(done + 1, total), total) if total else u"Started"}


def _date(s):
    try:
        return datetime.strptime((s or u"")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def inventory_alerts(items, today, soon_days=30):
    """The items a chemist should know about before starting work."""
    out = {"expired": [], "expiring": [], "quarantined": [], "low": []}
    soon = today + timedelta(days=soon_days)
    for it in items or []:
        status = (it.get("status") or u"").lower()
        if status in _UNUSABLE or it.get("is_archived"):
            continue
        if status == u"quarantine":
            out["quarantined"].append(it)
            continue
        exp = _date(it.get("expiry"))
        if status == u"expired" or (exp is not None and exp < today):
            out["expired"].append(it)
        elif exp is not None and exp <= soon:
            out["expiring"].append(it)
        qty, low = _num(it.get("quantity_value")), _num(it.get("low_stock_level"))
        if qty is not None and low is not None and qty <= low:
            out["low"].append(it)
    for key in out:
        out[key].sort(key=lambda i: (i.get("expiry") or u"9999", i.get("name") or u""))
    return out
