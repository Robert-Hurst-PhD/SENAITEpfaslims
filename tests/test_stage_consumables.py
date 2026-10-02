# -*- coding: utf-8 -*-
"""Consumables are recorded by lot, from the inventory (DECISIONS 2026-10-02
"Bench phase 2"): the stage equipment entries that are consumables move to a
by-lot list once, the guide records them like reagents, finalize files them
in FM-ENV-252 extraction_materials[], and the stage editor keeps the key."""
from __future__ import unicode_literals

import copy
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import bench_queue as bq            # noqa: E402
import extraction_logbook as el     # noqa: E402
import stage_consumables as sc      # noqa: E402


def test_only_consumables_are_moved():
    yes = ["50 mL Centrifuge Tubes", "LC Vials", "1 mL Syringe", "PTFE Syringe Filter",
           "50 mL PP Tubes", "1 mL LC Vials"]
    no = ["Analytical Balance", "Pipette (100-1000 μL)", "Vortex Mixer", "SPE Manifold",
          "Turbovap / N₂ Evaporator", "Water Bath (40°C)", "Centrifuge",
          "Homogenizer/Blender", "pH Meter", "Vacuum Pump", "Orbital Shaker",
          "Magnetic Stir Plate"]
    assert all(sc.is_consumable(n) for n in yes)
    assert not any(sc.is_consumable(n) for n in no)


def test_split_is_ordered_and_idempotent():
    p = {"extraction_stages": [
        {"order": 1, "equipment": ["Analytical Balance", "50 mL Centrifuge Tubes", "LC Vials"]},
        {"order": 2, "equipment": ["Centrifuge"]},
        {"order": 3, "equipment": ["1 mL Syringe", "LC Vials"], "consumables": ["LC Vials"]}]}
    assert sc.split_consumables(p)
    st = p["extraction_stages"]
    assert st[0]["equipment"] == ["Analytical Balance"]
    assert st[0]["consumables"] == ["50 mL Centrifuge Tubes", "LC Vials"]
    assert st[1] == {"order": 2, "equipment": ["Centrifuge"], "consumables": []}
    assert st[2]["consumables"] == ["LC Vials", "1 mL Syringe"]
    snap = copy.deepcopy(p)
    assert not sc.split_consumables(p) and p == snap


def test_every_shipped_profile_keeps_its_instruments():
    path = os.environ.get("PFAS_PROFILES_PATH",
                          os.path.join(ROOT, "data", "qc", "method_profiles.json"))
    if not os.path.exists(path):
        return
    with io.open(path, encoding="utf-8") as fh:
        profiles = json.load(fh)
    for mid, p in profiles.items():
        before = [(s.get("order"), list(s.get("equipment") or []))
                  for s in p.get("extraction_stages") or []]
        sc.split_consumables(p)
        for (order, eq), st in zip(before, p.get("extraction_stages") or []):
            assert sorted(st["equipment"] + st["consumables"]) == sorted(set(eq) | set(st["consumables"])), (mid, order)
            assert not any(sc.is_consumable(e) for e in st["equipment"]), (mid, order)


def test_consumable_rows_go_to_extraction_materials():
    assert bq.is_consumable_row({"group": "consumable", "name": "LC Vials"})
    assert bq.is_consumable_row({"from_inventory": True, "category": "Consumable", "name": "Filter"})
    assert not bq.is_consumable_row({"category": "Consumable", "name": "typed"})   # not resolved
    assert not bq.is_consumable_row({"from_inventory": True, "category": "Salt", "name": "MgSO4"})


def test_the_logbook_pdf_lists_consumables_and_what_needed_a_note():
    sess = {"stages": {"1": {"completed_at": "x", "deviations": "Vials from a new box",
                             "warnings": ["LC Vials: no lot recorded"],
                             "reagents": [{"group": "reagent", "name": "Methanol", "lot": "M-1"},
                                          {"group": "consumable", "name": "LC Vials", "lot": "V-7"}]}}}
    d = el.logbook_data("B-1", "t", sess, {"extraction_stages": [{"order": 1, "name": "Prep"}]}, "now")
    st = d["details"][0]
    assert [r[0] for r in st["reagents"]] == ["Methanol"]
    assert [r[:2] for r in st["consumables"]] == [["LC Vials", "V-7"]]
    assert st["warnings"] == ["LC Vials: no lot recorded"]


def _src(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    js = _src("src", "senaite", "pfas", "browser", "static", "method_profile_edit.js")
    assert 'data-field="consumables"' in js and "consumables:      splitCsv(get('consumables'))" in js, \
        "a stage key without both the input and the save line is dropped on the next save"
    store = _src("src", "senaite", "pfas", "method_profile_store.py")
    assert "split_consumables(profile)" in store
    g = _src("src", "senaite", "pfas", "browser", "extraction_guide.py")
    fin = g[g.index("def _handle_finalize"):]
    assert "is_consumable_row(rg)" in fin and 'data["extraction_materials"] = materials' in fin
    assert fin.index("is_consumable_row(rg)") < fin.index("is_standard_row(rg)")
    t = _src("src", "senaite", "pfas", "browser", "templates", "extraction_guide.pt")
    assert "consumable_order" in t and 'id="consumable-rows"' in t
    assert "u\"Consumable\"" in _src("src", "senaite", "pfas", "content", "reagent.py")


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
