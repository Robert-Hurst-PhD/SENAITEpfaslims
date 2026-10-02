# -*- coding: utf-8 -*-
"""P3 (DECISIONS 2026-10-02): Project Specs is the one way a project
overrides criteria. It covers everything the retired Projects-page editor
could -- Calibration & CCV, QC composition, SUR (EIS) limits -- and the
certificate names what a project loosens there too."""
from __future__ import unicode_literals

import copy
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import config_forms as cf                  # noqa: E402
import method_profile_sections as mps      # noqa: E402
import project_specs as ps                 # noqa: E402

PROFILE = {
    "method_id": "EPA_1633A", "supported_matrices": ["Groundwater", "Soil"],
    "master_analyte_set": [], "unit_map": {"Groundwater": "ng/L", "Soil": "ng/g"},
    "instrument_verification": {
        "calibration": {"r2_min": 0.99, "point_pct_dev_max": 30.0, "force_origin": False},
        "ccv": {"frequency": 10, "recovery_min": 70.0, "recovery_max": 130.0},
        "confirmation": {"sn_quan_min": 3.0, "ion_ratio_tol_pct": 50.0},
        "icv": {"pct_dev_max": 20.0}},
    "qc_acceptance": {"LFSM": {"enabled": True, "tiers": []},
                      "Dup": {"enabled": True, "tiers": [{"name": "default", "rpd_max": 30.0}]}},
    "eis_overrides": [{"analyte": "13C4-PFBA", "recovery_min": 5.0, "recovery_max": 130.0}],
    "eis_matrix_overrides": {"solid": {"13C4-PFBA": {"recovery_min": 5.0, "recovery_max": 130.0}}},
}


def test_project_specs_cover_what_the_old_editor_could():
    ids = [s.id for s in mps.PROJECT_SECTIONS]
    for sid in ("cal", "qc_comp", "eis_grid", "dup", "rl"):
        assert sid in ids, sid
    keys = {"cal_r2_min": "cal", "sn_quan_min": "cal", "ccv_recovery": "cal",
            "ccv_frequency": "cal", "dup_rpd_max": "dup", "eis_recovery": "eis_grid",
            "lfsm_frequency": "qc_comp", "duplicate_all_samples": "qc_comp"}
    assert set(keys.values()) <= set(ids)


def test_a_calibration_and_eis_patch_round_trips():
    new = copy.deepcopy(PROFILE)
    new["instrument_verification"]["calibration"]["r2_min"] = 0.995
    new["instrument_verification"]["ccv"]["frequency"] = 5
    new["eis_overrides"][0]["recovery_min"] = 10.0
    for sid in ("cal", "eis_grid"):
        sec = mps.SECTIONS[sid]
        patch = ps.diff(sec, PROFILE, new)
        assert patch, sid
    eff = ps.apply_patch(mps.SECTIONS["cal"], PROFILE, ps.diff(mps.SECTIONS["cal"], PROFILE, new))[0]
    assert eff["instrument_verification"]["calibration"]["r2_min"] == 0.995
    assert eff["instrument_verification"]["ccv"]["frequency"] == 5


def test_qc_composition_fields_store_cleanly():
    sec = mps.SECTIONS["qc_comp"]
    stored = copy.deepcopy(PROFILE)
    form = {"f__LFSM__frequency": "", "f__Dup__duplicate_all_samples": ""}
    updates, errors = cf.parse(sec, form, stored)
    after = cf.apply(sec, stored, updates)
    assert not errors
    assert "duplicate_all_samples" not in after["qc_acceptance"]["Dup"]    # blank removes
    assert after["qc_acceptance"]["LFSM"].get("frequency") is None
    form = {"f__LFSM__frequency": "5", "f__Dup__duplicate_all_samples": "yes"}
    after = cf.apply(sec, stored, cf.parse(sec, form, stored)[0])
    assert after["qc_acceptance"]["LFSM"]["frequency"] == 5
    assert after["qc_acceptance"]["Dup"]["duplicate_all_samples"] == "yes"
    _u, errs = cf.parse(sec, {"f__LFSM__frequency": "0"}, stored)
    assert errs


def test_the_certificate_names_a_loosened_instrument_criterion():
    eff = copy.deepcopy(PROFILE)
    eff["instrument_verification"]["calibration"]["r2_min"] = 0.98         # looser
    eff["instrument_verification"]["ccv"]["frequency"] = 20                 # looser
    eff["instrument_verification"]["ccv"]["recovery_max"] = 125.0           # tighter: not listed
    eff["eis_overrides"][0]["recovery_min"] = 2.0                           # looser
    eff["eis_matrix_overrides"]["solid"]["13C4-PFBA"]["recovery_max"] = 150.0
    whats = [d["what"] for d in ps.departures(PROFILE, eff, "EPA_1633A")]
    assert u"Calibration R² min" in whats and u"CCV every N samples" in whats
    assert u"CCV recovery max %" not in whats
    assert u"SUR 13C4-PFBA recovery min %" in whats
    assert any(d["what"] == u"SUR 13C4-PFBA recovery max %" and d["where"] == "solid"
               for d in ps.departures(PROFILE, eff, "EPA_1633A"))
    dup = copy.deepcopy(PROFILE)
    dup["qc_acceptance"]["Dup"]["duplicate_all_samples"] = "yes"
    assert u"Duplicate every field sample" in [
        d["what"] for d in ps.departures(dup, PROFILE, "EPA_1633A")]
    assert ps.departures(PROFILE, copy.deepcopy(PROFILE), "EPA_1633A") == []


def test_the_old_editor_is_gone_and_eis_shows_only_where_used():
    with io.open(os.path.join(PKG, "browser", "projects.py"), encoding="utf-8") as fh:
        src = fh.read()
    for gone in ("CRITERIA_DEFS", "_handle_save_criteria", "set_project_criterion", "ruleset"):
        assert gone not in src, gone
    with io.open(os.path.join(PKG, "browser", "templates", "projects.pt"), encoding="utf-8") as fh:
        tpl = fh.read()
    assert "criteria_uid" not in tpl and "@@pfas-project-specs" in tpl
    with io.open(os.path.join(PKG, "browser", "project_specs_view.py"), encoding="utf-8") as fh:
        view = fh.read()
    assert '"eis_overrides" not in self.method_profile()' in view
    assert 'return [t for t in tabs if t["sections"]]' in view


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
