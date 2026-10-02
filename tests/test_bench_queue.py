# -*- coding: utf-8 -*-
"""Bench landing (docs/BENCH_WORKFLOW_REVIEW.md phase 1): where each batch's
extraction is, and which inventory items need attention before work starts.
Also pins the guided extraction's defaults: method from the batch, analyst
from the login, method list from the LIVE profiles."""
from __future__ import unicode_literals

import io
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import bench_queue as bq  # noqa: E402

TODAY = date(2026, 10, 2)


def test_extraction_state_not_started_in_progress_finished():
    orders = [1, 2, 3, 4]
    assert bq.extraction_state(None, orders)["state"] == bq.NOT_STARTED
    s = bq.extraction_state({"stages": {"1": {}, "2": {}}}, orders)
    assert s["state"] == bq.IN_PROGRESS and s["done"] == 2 and s["label"] == "Stage 3 of 4"
    assert bq.extraction_state({"stages": {}}, orders)["label"] == "Stage 1 of 4"
    done = bq.extraction_state({"stages": dict((str(o), {}) for o in orders)}, orders)
    assert done["state"] == bq.FINISHED
    assert bq.extraction_state({"stages": {}, "finalized": True}, orders)["state"] == bq.FINISHED
    # a stage key not in the method's stages does not count
    assert bq.extraction_state({"stages": {"9": {}}}, orders)["done"] == 0


def test_inventory_alerts_buckets():
    items = [
        {"name": "MeOH", "status": "active", "expiry": "2026-09-30"},
        {"name": "NH4OH", "status": "opened", "expiry": "2026-10-20"},
        {"name": "AcOH", "status": "active", "expiry": "2027-06-01"},
        {"name": "Q", "status": "quarantine", "expiry": "2020-01-01"},
        {"name": "Old", "status": "expired", "expiry": ""},
        {"name": "Gone", "status": "exhausted", "expiry": "2020-01-01"},
        {"name": "Arch", "status": "active", "expiry": "2020-01-01", "is_archived": True},
        {"name": "Low", "status": "active", "expiry": "2027-06-01",
         "quantity_value": "0.5", "low_stock_level": 1},
        {"name": "Fine", "status": "active", "expiry": "2027-06-01",
         "quantity_value": 4, "low_stock_level": 1},
        {"name": "AtLevel", "status": "active", "expiry": "2027-06-01",
         "quantity_value": 1, "low_stock_level": "1"},
        {"name": "NoLevel", "status": "active", "expiry": "2027-06-01", "quantity_value": 0},
    ]
    a = bq.inventory_alerts(items, TODAY)
    names = lambda k: [i["name"] for i in a[k]]  # noqa: E731
    assert names("expired") == ["MeOH", "Old"]          # dated first, undated last
    assert names("expiring") == ["NH4OH"]
    assert names("quarantined") == ["Q"]
    assert names("low") == ["AtLevel", "Low"]   # at the level counts as low


def test_expiry_today_is_expiring_not_expired():
    a = bq.inventory_alerts([{"name": "X", "status": "active", "expiry": "2026-10-02"}], TODAY)
    assert not a["expired"] and [i["name"] for i in a["expiring"]] == ["X"]


def _src(*parts):
    with io.open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def test_guide_defaults_come_from_batch_login_and_live_profiles():
    g = _src(PKG, "browser", "extraction_guide.py")
    start = g[g.index("def _handle_start"):]
    start = start[:start.index("\n    def ", 1)]
    assert "batch_method_id(" in start, "method must default to the batch method"
    assert "current_user_name(" in start or "getAuthenticatedMember" in start
    avail = g[g.index("def available_methods"):]
    avail = avail[:avail.index("\n    def ", 1)]
    assert "DEFAULT_PROFILES" not in avail and "list_method_ids" in avail
    t = _src(PKG, "browser", "templates", "extraction_guide.pt")
    assert "batch_choices" in t, "no batch picker when the guide opens without a batch"


def test_bench_landing_shows_queue_and_alerts():
    t = _src(PKG, "browser", "templates", "pfas_bench.pt")
    assert "view/extractions" in t and "view/alerts" in t and "view/balances_today" in t
    assert "<style" not in t, "page-local style block: use pfas_macros.pt shared styles"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
