# -*- coding: utf-8 -*-
"""Per-sample correction is a per-method choice (DECISIONS 2026-10-02):
nominal matrix factor, already done in the MS software (no factor here, so
never twice), or back-calculated per sample from the amount and final volume
logged in the guided extraction -- a sample without both falls back to the
nominal factor and is flagged, never guessed."""
from __future__ import unicode_literals

import io
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import sample_correction as sc      # noqa: E402
import dilution_ref as dr           # noqa: E402


def close(a, b):
    return a is not None and abs(a - b) < 1e-9


def test_factor_for():
    egg = {"amount": "1.02", "amount_unit": "g", "final_volume_ml": "1"}
    assert close(sc.factor_for(egg, "ng/kg"), 1000.0 / 1.02)
    assert close(sc.factor_for(egg, "ng/g"), 1 / 1.02)
    assert close(sc.factor_for(egg, "mg/kg"), 0.001 / 1.02)
    water = {"amount": "250", "amount_unit": "mL", "final_volume_ml": "1"}
    assert close(sc.factor_for(water, "ng/L"), 4.0)
    assert close(sc.factor_for(water, "NG/ML"), 0.004)
    assert sc.factor_for(egg, "ng/L") is None and sc.factor_for(water, "ng/kg") is None
    assert sc.factor_for(dict(egg, amount=""), "ng/kg") is None
    assert sc.factor_for(dict(egg, final_volume_ml="0"), "ng/kg") is None
    assert sc.factor_for(dict(egg, amount="-1"), "ng/kg") is None
    assert sc.factor_for(dict(egg, amount_unit="cup"), "ng/kg") is None
    assert sc.factor_for(dict(water, amount_unit="cup"), "ng/L") is None
    assert sc.factor_for(egg, "") is None


def test_amounts_served_to_the_worker():
    rows = [{"sample_id": "EGG-1", "amount": "1.02", "amount_unit": "g", "final_volume_ml": "1"},
            {"sample_id": "MEAT-1", "amount": ""},
            {"sample_id": "EGG-1 1:10", "dilution_of": "EGG-1", "amount": "9"},
            {"sample_id": "DW-1", "final_volume_ml": "1"}]
    out = dr.sample_amounts_from_rows(rows)
    assert sorted(out) == ["DW-1", "EGG-1"]
    assert out["EGG-1"] == {"amount": "1.02", "amount_unit": "g", "final_volume_ml": "1"}
    assert out["DW-1"]["amount_unit"] == "g" and out["DW-1"]["amount"] == ""


def _pipeline():
    if sys.version_info[0] < 3:
        return None
    sys.path.insert(0, ROOT)
    import pfas_pipeline.pipeline as pl
    from pfas_pipeline.models import InstrumentRow
    return pl, InstrumentRow


def _row(InstrumentRow, inj, calc):
    return InstrumentRow(
        compound_name="PFOA", compound_type="Analyte", compound_group="", sample_description="",
        injection_name=inj, sample_group="", sample_type="Unknown", included_in_cal=False,
        level=None, linked_is=None, cal_ref_compound=None, observed_rt=10.0, rt_relative_to_is=1.0,
        response=1000.0, is_response=1000.0, response_ratio=1.0, expected_conc=None,
        calculated_conc=calc, pct_deviation=None, pct_recovery_is=None, ion_ratios=None,
        expected_ion_ratios=None, r2=None, signal_to_noise=50.0, qual_sn=50.0,
        quant_status="Successful", reporting_limit=None, measured_conc=calc,
        acquisition_datetime=datetime(2026, 3, 13), concat_id=inj)


def _run(mode, amounts):
    w = _pipeline()
    if w is None:
        return None
    pl, InstrumentRow = w
    saved = (pl._get_sample_correction, pl._get_matrix_factor, pl._get_unit, pl._get_salt_factors)
    pl._get_sample_correction = lambda m: mode
    pl._get_matrix_factor = lambda m, x: 1000.0
    pl._get_unit = lambda m, x: "ng/kg"
    pl._get_salt_factors = lambda m: {}
    try:
        rows = [_row(InstrumentRow, "EGG-1", 2.0), _row(InstrumentRow, "EGG-1 1:10", 0.5),
                _row(InstrumentRow, "MB-1", 0.1)]
        fallbacks = []
        out = pl.apply_extract_corrections(rows, "FDA_32PFAS", "Eggs", sample_amounts=amounts,
                                           dilutions={"EGG-1 1:10": {"parent": "EGG-1"}},
                                           fallbacks=fallbacks)
        return dict((r.injection_name, (r.calculated_conc, r.conc_units)) for r in out), fallbacks
    finally:
        (pl._get_sample_correction, pl._get_matrix_factor, pl._get_unit, pl._get_salt_factors) = saved


AMOUNTS = {"EGG-1": {"amount": "1.25", "amount_unit": "g", "final_volume_ml": "1"}}


def test_back_calculated_in_the_lims():
    r = _run("lims", AMOUNTS)
    if r is None:
        return
    got, fallbacks = r
    assert close(got["EGG-1"][0], 2.0 * 1000 / 1.25) and got["EGG-1"][1] == "ng/kg"
    assert close(got["EGG-1 1:10"][0], 0.5 * 1000 / 1.25), "a dilution takes its parent's amounts"
    assert close(got["MB-1"][0], 0.1 * 1000.0) and fallbacks == ["MB-1"], \
        "no logged amounts: nominal factor, and said so"


def test_in_the_ms_software_nothing_is_applied_twice():
    r = _run("instrument", AMOUNTS)
    if r is None:
        return
    got, fallbacks = r
    assert got["EGG-1"] == (2.0, "ng/kg") and got["MB-1"][0] == 0.1 and fallbacks == []


def test_nominal_is_unchanged():
    r = _run("", AMOUNTS)
    if r is None:
        return
    got, fallbacks = r
    assert close(got["EGG-1"][0], 2000.0) and close(got["MB-1"][0], 100.0) and fallbacks == []


def _src(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    sec = _src("src", "senaite", "pfas", "method_profile_sections.py")
    assert "SAMPLE_CORRECTION = cf.Section(" in sec and "SALT, SAMPLE_CORRECTION, MATRIX_FACTORS" in sec
    t = _src("src", "senaite", "pfas", "browser", "templates", "method_profile_edit.pt")
    assert 'value="salt,scorr,mf"' in t and "section_groups('scorr')" in t and "section_stamp__scorr" in t
    mp = _src("pfas_pipeline", "method_profiles.py")
    assert 'return mode if mode in ("instrument", "lims") else ""' in mp
    pl = _src("pfas_pipeline", "pipeline.py")
    assert pl.index('logged_amounts = prep.pop("_samples"') < pl.index("rows = apply_extract_corrections(")
    assert 'check_kind="sample_correction"' in pl
    i = pl.index("queue.auto_evaluate()")
    assert i < pl.index('check_kind="sample_correction"'), "the flag must not change automatic verdicts"
    assert 'payload["_samples"] = amounts' in _src("src", "senaite", "pfas", "browser", "logbooks.py")


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
