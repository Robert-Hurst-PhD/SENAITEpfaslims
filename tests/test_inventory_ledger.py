# -*- coding: utf-8 -*-
"""Bench phase 3 (DECISIONS 2026-10-02 DB3): every use of a lot is recorded
per extraction stage, a recall search finds it by lot number, and what is
left is DERIVED (received less every use) so a stage completed twice is not
counted twice."""
from __future__ import unicode_literals

import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import bench_queue as bq            # noqa: E402
import inventory_ledger as L        # noqa: E402


def test_amounts():
    assert L.parse_amount("5 mL") == (5.0, "mL")
    assert L.parse_amount("5mL") == (5.0, "mL")
    assert L.parse_amount("3", "g") == (3.0, "g")
    assert L.parse_amount("10 x 1 mL") == (10.0, "mL")
    assert L.parse_amount(".5 L") == (0.5, "L")
    assert L.parse_amount("2 µL", "mL") == (2.0, "µL")
    assert L.parse_amount("3") is None and L.parse_amount("") is None
    assert L.parse_amount("about half") is None
    assert L.convert(250, "uL", "mL") == 0.25 and L.convert(2, "µL", "mL") == 0.002
    assert L.convert(1.5, "kg", "g") == 1500.0
    assert L.convert(1, "L", "g") is None                      # volume is not mass
    assert L.convert(3, "ea", "cartridges") == 3.0             # any count word is one item
    assert L.convert(1, "case", "ea") is None


def test_remaining_is_derived_and_says_what_it_could_not_count():
    uses = [{"amount_value": 500, "amount_unit": "mL"}, {"amount_value": 0.25, "amount_unit": "L"},
            {"amount_value": 2, "amount_unit": "g"}, {"amount_value": None, "amount_unit": None}]
    r = L.remaining("4", "L", uses)
    assert (r["value"], r["unit"], r["used"], r["unconverted"]) == (3.25, "L", 0.75, 1)
    assert L.remaining("1 case", "", uses) is None              # free text: shown, not counted
    assert L.remaining("", "L", uses) is None
    assert L.remaining("10 x 1 mL", "", [{"amount_value": 2, "amount_unit": "mL"}])["value"] == 8.0


def test_the_ledger_replaces_a_stage_and_finds_lots():
    d = tempfile.mkdtemp()
    try:
        db = os.path.join(d, "usage.db")
        rows = [{"from_inventory": True, "inventory_uid": "m1", "kind": "reagent", "lot": "MEOH-1",
                 "name": "Methanol", "role": "Methanol", "qty_used": "5"},
                {"from_inventory": True, "inventory_uid": "ps", "kind": "prepared_standard",
                 "lot": "PS-A", "name": "Mobile Phase A", "qty_used": "2 mL"},
                {"from_inventory": False, "lot": "TYPED", "qty_used": "1 mL"},     # not recorded
                {"from_inventory": True, "inventory_uid": "x", "lot": ""}]          # no lot
        L.record_stage(db, "B-UID", "B-1", 3, "Extraction", rows, "DEMO", "2026-10-02T14:00:00Z",
                       stock_units={("reagent", "m1"): "mL"})
        uses = L.uses_of(db, "reagent", "m1")
        assert [(u["batch_id"], u["stage_name"], u["amount_value"], u["amount_unit"]) for u in uses] \
            == [("B-1", "Extraction", 5.0, "mL")]
        assert len(L.uses_for_items(db)) == 2
        # the same stage completed again REPLACES its rows
        L.record_stage(db, "B-UID", "B-1", 3, "Extraction", rows[:1], "DEMO", "2026-10-02T15:00:00Z",
                       stock_units={("reagent", "m1"): "mL"})
        assert len(L.uses_of(db, "reagent", "m1")) == 1 and L.uses_of(db, "prepared_standard", "ps") == []
        # another stage adds
        L.record_stage(db, "B-UID", "B-1", 5, "Cleanup", rows[:1], "DEMO", "2026-10-02T16:00:00Z")
        assert len(L.uses_of(db, "reagent", "m1")) == 2
        assert [u["stage_order"] for u in L.uses_by_lot(db, "meoh")] == ["5", "3"]   # recall, newest first
        assert L.uses_by_lot(db, "nothing") == []
    finally:
        shutil.rmtree(d)


def test_low_stock_reaches_the_bench_through_remaining():
    a = bq.inventory_alerts([{"name": "Methanol", "status": "active", "expiry": "2027-01-01",
                              "quantity_value": 0.4, "low_stock_level": 0.5}],
                            __import__("datetime").date(2026, 10, 2))
    assert [i["name"] for i in a["low"]] == ["Methanol"]


def _src(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    g = _src("src", "senaite", "pfas", "browser", "extraction_guide.py")
    stage = g[g.index("def _handle_complete_stage"):]
    stage = stage[:stage.index("\n    def ", 1)]
    assert stage.index("_save_session(b, sess)\n        # Phase 3") < stage.index("record_stage(")
    refuse = stage[stage.index("if warnings and not deviations:"):stage.index("remember_picks(")]
    assert "record_stage(" not in refuse, "a refused stage records no use"
    inv = _src("src", "senaite", "pfas", "browser", "bench_inventory.py")
    assert "remaining(" in inv and "uses_for_items()" in inv
    zcml = _src("src", "senaite", "pfas", "browser", "configure.zcml")
    assert 'name="pfas-lot-usage"' in zcml
    for t in ("reagents.pt", "prep_standards.pt", "pfas_sidebar.pt"):
        assert "@@pfas-lot-usage" in _src("src", "senaite", "pfas", "browser", "templates", t), t
    r = _src("src", "senaite", "pfas", "browser", "reagents.py")
    assert '"low_stock_level":    getattr(obj, "low_stock_level", None)' in r
    assert 'obj.low_stock_level = data.get("low_stock_level")' in r


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
