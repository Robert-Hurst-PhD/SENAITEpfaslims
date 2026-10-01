# -*- coding: utf-8 -*-
"""Calibration levels own the RL and suggest the spike levels
(DECISIONS 2026-10-02).

An analyte's RL in a matrix = its lowest calibration level in the matrix's
reporting unit, unless an RL is typed. Levels are in ppt (sample) or ng/mL
(extract); an ng/mL level becomes a sample value through the method's matrix
factor, the number the pipeline multiplies results by. An analyte may run a
multiple of the base ladder, capped at its highest standard (EPA 1633A Table
4). The add-on (report_limits.limits_for) and the worker
(MethodProfile.reporting_limits) load the same rule and must agree. No Zope.
"""
from __future__ import unicode_literals

import copy
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)
sys.path.insert(0, ROOT)

import calibration_levels as cl            # noqa: E402
import method_profile_sections as mps      # noqa: E402
import report_limits as rlim               # noqa: E402

LADDER_537 = [2.0, 4.0, 8.0, 16.0, 40.0, 80.0, 160.0]
PPT_PROFILE = {             # stored before the unit existed: rows keep "ppt"
    "method_id": "EPA_537_1",
    "supported_matrices": ["Drinking Water", "Soil"],
    "unit_map": {"Drinking Water": "ng/L", "Soil": "ng/g"},
    "instrument_verification": {"calibration": {"levels": [
        {"name": "CAL-%d" % (i + 1), "ppt": v} for i, v in enumerate(LADDER_537)]}},
    "reporting_limits": {"Drinking Water": {"PFOA": {"rl": 4.0, "mdl": 0.5}}},
}


def _seeded(mid, matrices, units, factors):
    p = {"method_id": mid, "supported_matrices": matrices, "unit_map": units,
         "matrix_factors": [{"matrix": m, "factor": f} for m, f in factors.items()]}
    assert cl.migrate(p, mid)
    return p


def _fda():
    return _seeded("FDA_32PFAS", ["Eggs", "Milk", "Animal Feed"],
                   {"Eggs": "ng/kg", "Milk": "ng/mL", "Animal Feed": "ng/kg"},
                   {"Eggs": 500.0, "Animal Feed": 2000.0})


def _1633a():
    return _seeded("EPA_1633A", ["Groundwater", "Soil"], {"Groundwater": "ng/L", "Soil": "ng/g"},
                   {"Groundwater": 20.0})


def test_ppt_levels_give_the_rl_in_each_matrix_unit():
    assert cl.unit(PPT_PROFILE) == "ppt" and cl.lowest(PPT_PROFILE) == 2.0
    assert cl.derived_rl(PPT_PROFILE, "Drinking Water") == 2.0
    assert abs(cl.derived_rl(PPT_PROFILE, "Soil") - 0.002) < 1e-12        # ng/g = 1000 ppt
    assert cl.derived_rl(PPT_PROFILE, "Unknown matrix") is None           # no unit, no guess


def test_a_typed_rl_overrides_and_the_source_says_which():
    typed = rlim.limits_for(PPT_PROFILE, "Drinking Water", "PFOA")
    assert (typed["rl"], typed["mdl"], typed["rl_source"]) == (4.0, 0.5, "override")
    derived = rlim.limits_for(PPT_PROFILE, "Drinking Water", "PFOS")
    assert (derived["rl"], derived["mdl"], derived["rl_source"]) == (2.0, None, "calibration")
    bare = rlim.limits_for({"unit_map": {"Drinking Water": "ng/L"}}, "Drinking Water", "PFOS")
    assert bare["rl"] is None and bare["rl_source"] is None


def test_fda_ladder_is_ten_doublings_to_20_and_the_matrix_factor_converts():
    p = _fda()
    assert cl.unit(p) == "ng/mL"
    lv = cl.levels(p)
    assert len(lv) == 10 and lv[-1] == 20.0 and abs(lv[0] - 0.0390625) < 1e-12
    assert all(abs(b / a - 2.0) < 1e-12 for a, b in zip(lv, lv[1:]))
    assert abs(cl.derived_rl(p, "Eggs") - 19.53125) < 1e-9                 # 0.0390625 x 500 ng/kg
    assert abs(cl.derived_rl(p, "Animal Feed") - 78.125) < 1e-9
    assert cl.derived_rl(p, "Milk") is None                                # no factor, no RL
    assert rlim.limits_for(p, "Milk", "PFOA")["rl_source"] is None


def test_1633a_runs_each_analyte_inside_its_published_range():
    p = _1633a()
    expect = {"PFOA": (0.2, 51.2, 9), "PFBA": (0.8, 204.8, 9), "PFPeA": (0.4, 102.4, 9),
              "6:2FTS": (0.8, 25.6, 6), "NMeFOSE": (2.0, 512.0, 9), "3:3FTCA": (1.0, 256.0, 9),
              "5:3FTCA": (5.0, 1280.0, 9), "GenX": (0.8, 204.8, 9)}
    for kw, (lo, hi, n) in expect.items():
        lv = cl.levels(p, kw)
        assert (round(lv[0], 9), round(lv[-1], 9), len(lv)) == (lo, hi, n), (kw, lv)
    assert abs(cl.derived_rl(p, "Groundwater", "PFBA") - 16.0) < 1e-9      # 0.8 ng/mL x 20 ng/L
    assert abs(cl.derived_rl(p, "Groundwater", "PFOA") - 4.0) < 1e-9
    assert cl.derived_rl(p, "Soil", "PFOA") is None                        # no factor yet
    assert "Table 4" in cl._calib(p)["levels_source"]


def test_migration_runs_once_and_never_replaces_levels():
    p = _fda()
    before = copy.deepcopy(p)
    assert not cl.migrate(p, "FDA_32PFAS") and p == before                 # marker: level_unit
    legacy = copy.deepcopy(PPT_PROFILE)
    assert cl.migrate(legacy, "EPA_537_1")
    calib = legacy["instrument_verification"]["calibration"]
    assert calib["level_unit"] == "ppt" and [r["conc"] for r in calib["levels"]] == LADDER_537
    lab = {"instrument_verification": {"calibration": {"levels": [{"name": "L1", "ppt": 50.0}]}}}
    assert cl.migrate(lab, "FDA_32PFAS")                                    # lab entered ppt
    assert cl.unit(lab) == "ppt" and cl.levels(lab) == [50.0]
    other = {}
    assert cl.migrate(other, "SOMETHING") and cl.levels(other) == [] and cl.unit(other) == "ppt"


def test_matrix_factor_lookup_matches_the_pipeline():
    p = {"matrix_factors": [{"matrix": "Meat", "factor": 500.0},
                            {"matrix": "Meat / Muscle", "factor": 250.0}]}
    assert cl.matrix_factor(p, "Meat / Muscle") == 250.0                   # exact first
    assert cl.matrix_factor(p, "meat trim") == 500.0                       # then key-in-matrix
    assert cl.matrix_factor(p, "Eggs") is None


def test_recommended_spikes_follow_the_curve():
    assert cl.recommended_spikes(PPT_PROFILE) == {"Low": 2.0, "Mid": 80.0, "High": 160.0}
    assert cl.recommended_spikes_ppt(PPT_PROFILE, "Drinking Water") == {"Low": 2.0, "Mid": 80.0,
                                                                        "High": 160.0}
    fda = _fda()
    rec = cl.recommended_spikes(fda)
    assert rec["Mid"] == 10.0 and rec["High"] == 20.0
    eggs = cl.recommended_spikes_ppt(fda, "Eggs")
    assert (round(eggs["Low"], 5), eggs["Mid"], eggs["High"]) == (19.53125, 5000.0, 10000.0)
    assert cl.recommended_spikes_ppt(fda, "Milk") == {}
    tie = {"instrument_verification": {"calibration": {"levels": [
        {"conc": 10.0}, {"conc": 1.0}, {"conc": 4.0}, {"conc": 7.0}]}}}
    assert cl.recommended_spikes(tie) == {"Low": 1.0, "Mid": 7.0, "High": 10.0}
    assert cl.recommended_spikes({"instrument_verification": {"calibration": {
        "levels": [{"conc": 5.0}]}}}) == {}


def test_numbers_print_without_exponents():
    assert [cl.fmt(v) for v in (10000.0, 2e6, 0.0390625, 19.53125, 2.0, None)] == [
        "10000", "2000000", "0.03906", "19.53", "2", ""]


def test_the_collections_round_trip_and_check():
    p = _fda()
    assert [r["conc"] for r in mps.read_cal_levels(p)] == cl.levels(p)
    mps.write_cal_levels(p, [{"name": "B", "conc": 50.0}, {"name": "A", "conc": 1.0}])
    assert [r["name"] for r in cl.rows(p)] == ["A", "B"]
    assert mps.check_cal_levels(p, [{"name": "A", "conc": 1.0}, {"name": "B", "conc": 1.0}])
    assert mps.check_cal_levels(p, [{"name": "A", "conc": None}])
    assert mps.check_cal_levels(p, [{"name": "A", "conc": 1.0}, {"name": "B", "conc": 2.0}]) == []
    for sid in ("cal_levels", "cal_scale"):
        assert sid in mps.SECTIONS
    q = _1633a()
    q["master_analyte_set"] = ["PFOA", "PFBA"]
    _g, rows = mps.analyte_scale_rows(q)
    assert [r["note"] for r in rows] == ["0.2 to 51.2 (9 points)", "0.8 to 204.8 (9 points)"]


def test_rl_rows_and_the_mdl_check_use_the_analytes_own_rl():
    q = _1633a()
    q["master_analyte_set"] = ["PFOA", "PFBA"]
    _g, rows = mps.reporting_limit_rows(q)
    gw = dict((r["sublabel"], r) for r in rows if r["group"] == "Groundwater")
    assert gw["PFBA"]["placeholders"]["rl"] == "16 (lowest cal.)" and gw["PFOA"]["derived_rl"] == 4.0
    assert not any("placeholders" in r for r in rows if r["group"] == "Soil")
    row = {"sublabel": "PFOS", "group": "Drinking Water", "derived_rl": 2.0}
    assert mps._mdl_not_above_rl(row, {"f__rl": None, "f__mdl": 3.0})
    assert mps._mdl_not_above_rl(row, {"f__rl": None, "f__mdl": 1.0}) is None
    assert mps._mdl_not_above_rl(row, {"f__rl": 5.0, "f__mdl": 3.0}) is None    # typed RL wins


def test_the_worker_gives_the_same_rl():
    if sys.version_info[0] < 3:
        return                                   # the worker is Python 3
    from pfas_pipeline import method_profiles as mp
    cases = [("EPA_537_1", copy.deepcopy(PPT_PROFILE), ("Drinking Water", "Soil"), ("PFOA", "PFOS")),
             ("FDA_32PFAS", _fda(), ("Eggs", "Milk"), ("PFOA",)),
             ("EPA_1633A", _1633a(), ("Groundwater", "Soil"), ("PFOA", "PFBA", "6:2FTS"))]
    for mid, profile, matrices, kws in cases:
        old = mp._profile_data_cache.get(mid)
        mp._profile_data_cache[mid] = profile
        try:
            prof = mp.get_profile(mid)
            for matrix in matrices:
                for kw in kws:
                    ours = rlim.limits_for(profile, matrix, kw)
                    rl, mdl, unit = prof.reporting_limits(kw, matrix)
                    assert (rl, mdl, unit) == (ours["rl"], ours["mdl"], ours["unit"]), (mid, matrix, kw)
        finally:
            if old is None:
                mp._profile_data_cache.pop(mid, None)
            else:
                mp._profile_data_cache[mid] = old
    assert mp._cal() is mp._cal() and hasattr(mp._cal(), "derived_rl")


def test_the_settings_report_prints_the_levels_and_derived_rls():
    import settings_report as sr
    p = copy.deepcopy(PPT_PROFILE)
    p["master_analyte_set"] = ["PFOA", "PFOS"]
    p["analyte_matrix_inclusion"] = {"Drinking Water": {"PFOA": True, "PFOS": True}}
    rep = sr.method_report(p)
    by = dict((d["title"], d) for d in rep["sections"])
    assert [r[1] for r in by["Calibration levels"]["rows"]][:2] == ["2", "4"]
    rl = by["Reporting Limits"]["rows"]
    assert any("PFOS" in r[0] and r[1] == "2 (lowest cal.)" for r in rl), rl
    assert any("PFOA" in r[0] and r[1] == "4" for r in rl), rl


def test_the_demo_reseed_picks_the_method_written_for_the_matrix():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import reseed_demo_methods as rd
    sup = {"EPA_537_1": ["Drinking Water", "Groundwater"],
           "EPA_1633A": ["Drinking Water", "Groundwater", "Soil", "Biosolid"],
           "FDA_32PFAS": ["Eggs"], "X": ["Tie"], "Y": ["Tie"]}
    assert rd.choose("Drinking Water", None, sup)[0] == "EPA_537_1"
    assert rd.choose("Soil", None, sup)[0] == "EPA_1633A"
    assert rd.choose("Drinking Water", "EPA_1633A", sup)[0] == "EPA_1633A"    # the worksheet wins
    assert rd.choose("Tie", None, sup)[0] is None
    assert rd.choose("Milk", None, sup)[0] is None


def test_the_editor_shows_the_levels_and_the_suggestion():
    with io.open(os.path.join(PKG, "browser", "templates", "method_profile_edit.pt"), encoding="utf-8") as fh:
        tpl = fh.read()
    assert "section_groups('cal_levels')" in tpl and 'value="cal,cal_levels,cal_scale"' in tpl
    assert "section_stamp__cal_scale" in tpl and "section_groups('cal_scale')" in tpl
    assert "view/recommended_spikes" in tpl and "data-rec" in tpl


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
