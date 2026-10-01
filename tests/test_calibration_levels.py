# -*- coding: utf-8 -*-
"""Calibration levels own the RL and suggest the spike levels
(DECISIONS 2026-10-02).

The lowest calibrator is every analyte's RL in every matrix, in the matrix's
reporting unit, unless an RL is typed; the add-on (report_limits.limits_for)
and the worker (MethodProfile.reporting_limits) must give the same answer.
Spike suggestions: lowest, nearest the midpoint, highest -- 2, 80, 160 for
the EPA 537.1 curve. Levels are seeded once, and only from a ladder that is
already sample-equivalent ppt. No Zope.
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
PROFILE = {
    "method_id": "EPA_537_1",
    "supported_matrices": ["Drinking Water", "Soil"],
    "unit_map": {"Drinking Water": "ng/L", "Soil": "ng/g"},
    "instrument_verification": {"calibration": {"levels": [
        {"name": "CAL-%d" % (i + 1), "ppt": v} for i, v in enumerate(LADDER_537)]}},
    "reporting_limits": {"Drinking Water": {"PFOA": {"rl": 4.0, "mdl": 0.5}}},
}


def test_the_lowest_calibrator_is_the_rl_in_each_matrix_unit():
    assert cl.lowest(PROFILE) == 2.0
    assert cl.derived_rl(PROFILE, "Drinking Water") == 2.0
    assert abs(cl.derived_rl(PROFILE, "Soil") - 0.002) < 1e-12        # ng/g = 1000 ppt
    assert cl.derived_rl(PROFILE, "Unknown matrix") is None           # no unit, no guess
    assert cl.derived_rl({"unit_map": {"Drinking Water": "ng/L"}}, "Drinking Water") is None


def test_a_typed_rl_overrides_and_the_source_says_which():
    typed = rlim.limits_for(PROFILE, "Drinking Water", "PFOA")
    assert (typed["rl"], typed["mdl"], typed["rl_source"]) == (4.0, 0.5, "override")
    derived = rlim.limits_for(PROFILE, "Drinking Water", "PFOS")
    assert (derived["rl"], derived["mdl"], derived["rl_source"]) == (2.0, None, "calibration")
    bare = rlim.limits_for({"unit_map": {"Drinking Water": "ng/L"}}, "Drinking Water", "PFOS")
    assert bare["rl"] is None and bare["rl_source"] is None


def test_recommended_spikes_follow_the_curve():
    assert cl.recommended_spikes(PROFILE) == {"Low": 2.0, "Mid": 80.0, "High": 160.0}
    # unordered input, and a tie at the midpoint goes to the higher level
    tie = {"instrument_verification": {"calibration": {"levels": [
        {"ppt": 10.0}, {"ppt": 1.0}, {"ppt": 4.0}, {"ppt": 7.0}]}}}
    assert cl.recommended_spikes(tie) == {"Low": 1.0, "Mid": 7.0, "High": 10.0}
    one = {"instrument_verification": {"calibration": {"levels": [{"ppt": 5.0}]}}}
    assert cl.recommended_spikes(one) == {}


def test_levels_are_seeded_once_and_only_from_a_ppt_ladder():
    p = {}
    assert cl.seed_from_ladder(p, LADDER_537[::-1], unit_is_ppt=True)
    assert [r["ppt"] for r in cl.rows(p)] == LADDER_537
    assert cl.rows(p)[0]["name"] == "CAL-1"
    p["instrument_verification"]["calibration"]["levels"] = []          # the lab clears them
    assert not cl.seed_from_ladder(p, LADDER_537, unit_is_ppt=True)
    assert cl.rows(p) == []
    extract = {}
    assert cl.seed_from_ladder(extract, [20.0, 10.0], unit_is_ppt=False)
    assert cl.rows(extract) == []                                        # never converted


def test_the_collection_round_trips_lowest_first_and_checks():
    p = copy.deepcopy(PROFILE)
    rows = mps.read_cal_levels(p)
    assert [r["ppt"] for r in rows] == LADDER_537
    mps.write_cal_levels(p, [{"name": "B", "ppt": 50.0}, {"name": "A", "ppt": 1.0}])
    assert [r["name"] for r in cl.rows(p)] == ["A", "B"]
    assert mps.check_cal_levels(p, [{"name": "A", "ppt": 1.0}, {"name": "B", "ppt": 1.0}])
    assert mps.check_cal_levels(p, [{"name": "A", "ppt": None}])
    assert mps.check_cal_levels(p, [{"name": "A", "ppt": 1.0}, {"name": "B", "ppt": 2.0}]) == []
    assert "cal_levels" in mps.SECTIONS


def test_the_mdl_check_uses_the_derived_rl():
    row = {"sublabel": "PFOS", "group": "Drinking Water", "derived_rl": 2.0}
    assert mps._mdl_not_above_rl(row, {"f__rl": None, "f__mdl": 3.0})
    assert mps._mdl_not_above_rl(row, {"f__rl": None, "f__mdl": 1.0}) is None
    assert mps._mdl_not_above_rl(row, {"f__rl": 5.0, "f__mdl": 3.0}) is None    # typed RL wins


def test_the_worker_gives_the_same_rl():
    if sys.version_info[0] < 3:
        return                                   # the worker is Python 3
    from pfas_pipeline import method_profiles as mp
    old = mp._profile_data_cache.get("EPA_537_1")
    mp._profile_data_cache["EPA_537_1"] = copy.deepcopy(PROFILE)
    try:
        prof = mp.get_profile("EPA_537_1")
        for matrix in ("Drinking Water", "Soil"):
            for kw in ("PFOA", "PFOS"):
                ours = rlim.limits_for(PROFILE, matrix, kw)
                rl, mdl, unit = prof.reporting_limits(kw, matrix)
                assert (rl, mdl, unit) == (ours["rl"], ours["mdl"], ours["unit"]), (matrix, kw)
        assert prof.reporting_limit_ppt("PFOS", "Soil") == 2.0
    finally:
        if old is None:
            mp._profile_data_cache.pop("EPA_537_1", None)
        else:
            mp._profile_data_cache["EPA_537_1"] = old


def test_the_settings_report_prints_the_levels_and_derived_rls():
    import settings_report as sr
    p = copy.deepcopy(PROFILE)
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
    assert "section_groups('cal_levels')" in tpl and 'value="cal,cal_levels"' in tpl
    assert "section_stamp__cal_levels" in tpl and "view/recommended_spikes" in tpl


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
