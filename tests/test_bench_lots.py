# -*- coding: utf-8 -*-
"""Bench phase 2 (DECISIONS 2026-10-02 "Bench phase 2"): a stage role offers
every usable lot, suggestions first, the lab's last pick preselected; the
inventory -- not the browser -- supplies name, lot and expiry; the stored kind
decides which FM-ENV-252 table a lot is filed in."""
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


def lot(uid, name, lot_no, expiry="2027-01-01", status="active", received="", kind="reagent"):
    return {"uid": uid, "kind": kind, "name": name, "lot_number": lot_no,
            "expiry": expiry, "status": status, "received": received}


def test_is_usable_agrees_with_the_bench_alerts():
    assert bq.is_usable(lot("a", "X", "1"), TODAY)
    assert bq.is_usable(lot("a", "X", "1", status="opened"), TODAY)
    assert bq.is_usable(lot("a", "X", "1", expiry="2026-10-02"), TODAY)      # expiring today
    assert bq.is_usable(lot("a", "X", "1", expiry=""), TODAY)               # no expiry stated
    for bad in (lot("a", "X", "1", expiry="2026-10-01"), lot("a", "X", "1", status="expired"),
                lot("a", "X", "1", status="quarantine"), lot("a", "X", "1", status="exhausted"),
                dict(lot("a", "X", "1"), is_archived=True)):
        assert not bq.is_usable(bad, TODAY), bad
    # every item the alerts call expired or quarantined is unusable, and back
    items = [lot("1", "A", "1", expiry="2026-10-01"), lot("2", "B", "2", expiry="2026-10-02"),
             lot("3", "C", "3", status="quarantine"), lot("4", "D", "4")]
    a = bq.inventory_alerts(items, TODAY)
    flagged = set(i["uid"] for i in a["expired"] + a["quarantined"])
    assert flagged == set(i["uid"] for i in items if not bq.is_usable(i, TODAY))


def test_names_fold_subscripts_and_noise_words():
    assert bq.match_score("Methanol (LC-MS grade)", "Methanol LC-MS Grade") == 1.0
    assert bq.match_score("MgSO₄ (anhydrous)", "MgSO4 anhydrous") == 1.0
    assert bq.match_score("Reagent Water", "Water LC-MS Grade") == 0.5
    assert bq.match_score("Acetonitrile", "Methanol") == 0.0
    # a stored field can come back as a byte string under Python 2
    assert bq.match_score("Ammonium Acetate", "Ammonium Acetate \u226599%".encode("utf-8")) == 1.0


LOTS = [lot("w1", "Water LC-MS Grade", "W-1", received="2026-05-10"),
        lot("m1", "Methanol LC-MS Grade", "M-1", received="2026-05-10"),
        lot("m2", "Methanol LC-MS Grade", "M-2", received="2026-08-01"),
        lot("d1", "DEMO Methanol (LC-MS)", "D-1"),
        lot("ps", "Mobile Phase A — 4 mM Ammonium Acetate in Water", "PS-A",
            kind="prepared_standard")]


def test_no_memory_preselects_only_a_clear_match():
    assert bq.default_pick(LOTS, "Methanol (LC-MS grade)")["lot_number"] == "M-2"   # newest
    assert bq.default_pick(LOTS, "Reagent Water") is None                         # half is a guess
    assert bq.default_pick(LOTS, "Acetonitrile (LC-MS grade)") is None
    assert bq.default_pick([], "Methanol") is None


def test_the_remembered_pick_wins_then_its_newest_sibling():
    rem = {"uid": "m1", "name": "Methanol LC-MS Grade"}
    assert bq.default_pick(LOTS, "Methanol (LC-MS grade)", rem)["uid"] == "m1"
    rem_water = {"uid": "w1", "name": "Water LC-MS Grade"}
    assert bq.default_pick(LOTS, "Reagent Water", rem_water)["uid"] == "w1"        # learned
    gone = [l for l in LOTS if l["uid"] != "m1"]                                 # m1 used up
    assert bq.default_pick(gone, "Methanol (LC-MS grade)", rem)["uid"] == "m2"
    # an unrelated remembered item does not hijack a clear name match
    assert bq.default_pick(LOTS, "Methanol (LC-MS grade)", {"uid": "zz", "name": "Gone"})["uid"] == "m2"


def test_ranking_tie_breaks():
    same = [lot("u", "Methanol LC-MS Grade", "U-0"),                      # undated
            lot("d", "Methanol LC-MS Grade", "D-0", received="2026-01-01")]
    assert bq.default_pick(same, "Methanol")["uid"] == "d", "a dated lot before an undated one"
    noisy = [lot("x", "DEMO Methanol LC-MS", "X-0", received="2026-09-01"),
             lot("e", "Methanol LC-MS Grade", "E-0", received="2026-01-01")]
    assert bq.default_pick(noisy, "Methanol (LC-MS grade)")["uid"] == "e", \
        "the name without extra words wins over a newer noisy one"
    rem = {"uid": "w1", "name": "Water LC-MS Grade"}
    lots = [lot("w2", "Water LC-MS Grade", "W-2", received="2026-09-01"),   # w1 used up
            lot("rw", "Reagent Water Deionized", "RW-1", received="2026-09-15")]
    assert bq.default_pick(lots, "Reagent Water", rem)["uid"] == "w2", \
        "the remembered item's next lot outranks a better name match"


def test_suggestions_list_matches_first_and_skip_unrelated():
    s = [l["uid"] for l in bq.suggested(LOTS, "Methanol (LC-MS grade)")]
    assert s[:2] == ["m2", "m1"] and "d1" in s and "ps" not in s and "w1" not in s
    s2 = [l["uid"] for l in bq.suggested(LOTS, "Mobile Phase A (water+5mM AmAc)")]
    assert s2[0] == "ps"


def test_resolve_rows_takes_the_inventory_record_not_the_browser():
    index = {("reagent", "m1"): {"name": "Methanol LC-MS Grade", "lot_number": "M-1",
                                 "expiry": "2027-01-01", "status": "opened",
                                 "category": "Mobile Phase / Solvent", "supplier": "Fisher",
                                 "cat_number": "A456"},
             ("prepared_standard", "ps"): {"name": "Mobile Phase A", "lot_number": "PS-A",
                                           "expiry": "2026-10-20", "status": "active",
                                           "category": "Solvent / Reagent", "supplier": "In-house",
                                           "cat_number": ""}}
    rows = [{"role": "Methanol", "inventory_uid": "m1", "kind": "reagent",
             "name": "edited", "lot": "typed", "expiry": "2099-01-01", "qty_used": "5 mL"},
            {"role": "MPA", "inventory_uid": "ps", "kind": "prepared_standard", "lot": "x"},
            {"role": "Old", "inventory_uid": "m1", "lot": "M-1"},          # pre-phase-2: no kind
            {"role": "Typed", "lot": "L9", "expiry": "2026-01-01"},
            {"role": "Deleted", "inventory_uid": "gone", "kind": "reagent", "lot": "G"}]
    out = bq.resolve_rows(index, rows)
    assert (out[0]["name"], out[0]["lot"], out[0]["expiry"], out[0]["status_at_use"]) == \
        ("Methanol LC-MS Grade", "M-1", "2027-01-01", "opened")
    assert out[0]["qty_used"] == "5 mL" and out[0]["from_inventory"]
    assert out[1]["lot"] == "PS-A" and out[1]["supplier"] == "In-house"
    assert out[2]["kind"] == "reagent" and out[2]["from_inventory"]
    assert out[3]["from_inventory"] is False and out[3]["lot"] == "L9"
    assert out[4]["from_inventory"] is False and out[4]["inventory_missing"]
    assert rows[0]["lot"] == "typed"                                     # input not mutated


def test_kind_decides_the_252_table():
    assert bq.is_standard_row({"kind": "prepared_standard", "name": "Mobile Phase A",
                               "from_inventory": True})
    assert not bq.is_standard_row({"kind": "reagent", "from_inventory": True,
                                   "name": "Spike-free methanol standard grade",
                                   "category": "Mobile Phase / Solvent"})
    assert bq.is_standard_row({"kind": "reagent", "from_inventory": True,
                               "name": "Native PFAS Mix", "category": "Standard / Reference Material"})
    assert bq.is_standard_row({"name": "Surrogate spike"})               # old rows: name test
    assert not bq.is_standard_row({"name": "Methanol"})


def test_stage_warnings_db4():
    rows = [{"role": "Methanol", "lot": "M-1", "from_inventory": True, "status_at_use": "active",
             "expiry": "2027-01-01"},
            {"role": "Water", "lot": "", "from_inventory": False},
            {"role": "Acid", "lot": "T-9", "from_inventory": False},
            {"role": "Gone", "lot": "G-1", "from_inventory": False, "inventory_missing": True},
            {"role": "Old", "lot": "O-1", "from_inventory": True, "status_at_use": "active",
             "expiry": "2026-10-01"},
            {"role": "Today", "lot": "T-1", "from_inventory": True, "status_at_use": "opened",
             "expiry": "2026-10-02"},
            {"role": "Q", "lot": "Q-1", "from_inventory": True, "status_at_use": "quarantine"},
            {"role": "Used", "lot": "U-1", "from_inventory": True, "status_at_use": "exhausted"}]
    balances = [{"label": "Analytical Balance", "serial": "", "unit_name": None},
                {"label": "Balance 2", "serial": "X9", "unit_name": None},
                {"label": "Balance 3", "serial": "B3", "unit_name": "XPR205", "verified": False},
                {"label": "Balance 4", "serial": "B4", "unit_name": "XS64", "verified": True}]
    w = bq.stage_warnings(rows, balances, TODAY)
    assert w == [
        "Water: no lot recorded",
        "Acid: lot T-9 was typed, not picked from the inventory",
        "Gone: lot G-1 is no longer in the inventory",
        "Old: lot O-1 is expired (2026-10-01)",
        "Q: lot Q-1 is quarantined",
        "Used: lot U-1 is used up",
        "Analytical Balance: no serial number recorded",
        "Balance 2: no registered balance has serial X9 (register it in Facility QC)",
        "Balance 3 (XPR205): not verified today"], w
    assert bq.stage_warnings(rows[:1] + rows[5:6], balances[3:], TODAY) == []


def test_the_record_says_what_needed_a_note():
    import extraction_sidecar as es
    r = es.build_sidecar({"stages": {"1": {"deviations": "No water lot on the bench",
                                           "warnings": ["Water: no lot recorded"]}}}, {"1": "Prep"})
    assert r["steps"][0]["detail"] == \
        "No water lot on the bench [needed a note: Water: no lot recorded]"


def test_equipment_family_and_units():
    assert bq.equipment_family("Analytical Balance") == "balance"
    assert bq.equipment_family("Pipette (100-1000 \u03bcL)") == "pipette"
    assert bq.equipment_family("Pipettor 10 uL") == "pipette"
    for other in ("Vortex Mixer", "Centrifuge", "SPE Manifold", "Turbovap / N\u2082 Evaporator"):
        assert bq.equipment_family(other) == "", other
    units = [{"unit_type": "balance_analytical", "name": "XPR205", "active": 1},
             {"unit_type": "balance_prep", "name": "PB3002", "active": 1},
             {"unit_type": "balance_analytical", "name": "Retired", "active": 0},
             {"unit_type": "pipette", "name": "P1000", "active": 1},
             {"unit_type": "refrigerator", "name": "Fridge 1", "active": 1}]
    assert [u["name"] for u in bq.units_for("Analytical Balance", units)] == ["XPR205", "PB3002"]
    assert [u["name"] for u in bq.units_for("Pipette", units)] == ["P1000"]
    assert bq.units_for("Vortex Mixer", units) == []


def test_a_lot_on_file_is_never_received_twice():
    items = [lot("a", "Methanol", "M-1", status="expired"), lot("b", "Water", "W-1")]
    assert bq.lot_on_file(items, " m-1 ")["uid"] == "a"            # any status, any case
    assert bq.lot_on_file(items, "W-1")["uid"] == "b"
    assert bq.lot_on_file(items, "X-9") is None and bq.lot_on_file(items, "") is None


def _src(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_the_guide_reads_and_resolves_through_the_inventory():
    g = _src("src", "senaite", "pfas", "browser", "extraction_guide.py")
    stage = g[g.index("def _handle_complete_stage"):]
    stage = stage[:stage.index("\n    def ", 1)]
    assert stage.index("resolve_rows(") < stage.index("stage_data = {"), \
        "rows must be resolved against the inventory before the stage is stored"
    assert "remember_picks(" in stage
    assert "is_standard_row(rg)" in g and '"standard" in entry["name"]' not in g
    t = _src("src", "senaite", "pfas", "browser", "templates", "extraction_guide.pt")
    assert "view/stage_lots_json" in t and "reagent-lot-sel" in t
    assert "reagent-exp-field" not in t, "expiry must not be typed"
    # DB4: checked BEFORE anything changes (picks remembered, lots flagged),
    # and a refusal keeps the entries as a draft instead of discarding them
    assert stage.index("stage_warnings(") < stage.index("remember_picks(")
    assert stage.index("stage_warnings(") < stage.index("_save_reagent(")
    refuse = stage[stage.index("if warnings and not deviations:"):stage.index("remember_picks(")]
    assert '"drafts"' in refuse and "_save_session(" in refuse and "reagents" in refuse
    assert '"warnings":            warnings' in stage
    assert "DRAFT.reagents" in t and "stageWarnings()" in t
    assert "view/stage_equipment_json" in t and "function pickUnit(" in t
    # DB2 + R9: GS1 labels parsed by the vendored MIT parser; an unknown lot
    # is received in the stage through the server action, never twice
    assert "gs1-barcode-parser-mod-1.2.1.js" in t and "parseBarcode(" in t
    assert "openReceive(i, label)" in t and "'receive_lot'" in t
    rec = g[g.index("def _handle_receive_lot"):]
    rec = rec[:rec.index("\n    def ", 1)]
    assert rec.index("lot_on_file(") < rec.index("_save_reagent("), "check the file before creating"
    vend = os.path.join(ROOT, "src", "senaite", "pfas", "browser", "static", "vendor")
    assert os.path.exists(os.path.join(vend, "gs1-barcode-parser-mod-LICENSE.txt"))
    h = _src("src", "senaite", "pfas", "browser", "workspace_home.py")
    assert '.startswith("balance")' in h and '== "balance"' not in h, \
        "unit types are balance_analytical / balance_prep"
    assert "inventory_items(" in h, "the Bench alerts and the picker read one inventory"


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
