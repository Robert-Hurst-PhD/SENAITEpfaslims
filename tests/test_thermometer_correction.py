# -*- coding: utf-8 -*-
"""Thermometer correction factors (GAPS §101). Lab, 2026-10-03: "Correction
factors are applied to thermometers. They in theory correct the reading to a
NIST reference thermometer. A temperature study is done over two days and the
difference in average between the two probes, 4 readings over two days becomes
the correction factor. This is performed quarterly."

Runs against a scratch database (PFAS_FACILITY_QC_DB)."""
import importlib.util
import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "src", "senaite", "pfas", "facility_qc.py")


def _fq():
    path = os.path.join(tempfile.mkdtemp(prefix="pfas_tc_"), "facility.db")
    os.environ["PFAS_FACILITY_QC_DB"] = path
    spec = importlib.util.spec_from_file_location("pfas_facility_qc_tc", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.ensure_schema()
    return m


def _fridge(fq, lo=2.0, hi=8.0):
    return fq.save_unit({"unit_type": "refrigerator", "name": "Fridge", "location": "Lab",
                         "serial_number": "", "sensor_id": "", "temp_min": lo, "temp_max": hi})


PAIRS = [("2026-07-01T09:00", 4.0, 4.4), ("2026-07-01T16:00", 4.2, 4.5),
         ("2026-07-02T09:00", 3.9, 4.3), ("2026-07-02T16:00", 4.1, 4.4)]   # NIST - probe avg = +0.35


def _study(fq, unit, pairs=PAIRS, date_="2026-07-01", tol=1.0):
    sid = fq.create_study(unit, "AN1", "NIST-DEMO-1", study_date=date_, tolerance=tol)
    for i, (at, probe, nist) in enumerate(pairs, 1):
        fq.save_study_point(sid, i, probe, nist, recorded_at=at)
    return sid


def test_a_study_is_four_pairs_over_two_days():
    fq = _fq()
    unit = _fridge(fq)
    one_day = [("2026-07-01T0%d:00" % (i + 1), 4.0, 4.4) for i in range(4)]
    sid = _study(fq, unit, one_day)
    assert fq.get_study(sid)["study"]["status"] == "pending", "four readings in ONE day is not a study"
    assert len(fq.get_study(sid)["points"]) == 4
    sid = _study(fq, unit, PAIRS[:3])
    assert fq.get_study(sid)["study"]["status"] == "pending", "three readings are not enough"
    sid = _study(fq, unit)
    assert fq.get_study(sid)["study"]["status"] == "pass"


def test_the_factor_is_nist_average_minus_probe_average():
    fq = _fq()
    unit = _fridge(fq)
    sid = _study(fq, unit)
    assert fq.study_correction(fq.get_study(sid)["points"]) == 0.35
    cur = fq.current_correction(unit, "2026-07-10")
    assert cur["correction"] == 0.35 and cur["study_id"] == sid
    assert fq.current_correction(unit, "2026-06-30") is None, "no study yet on that day"


def test_readings_are_judged_corrected_and_stored_raw():
    """8.2 on the probe reads 8.55 corrected: out of a 2-8 range only with the
    correction; 7.8 corrected is 8.15, also out. 7.5 -> 7.85 in."""
    fq = _fq()
    unit = _fridge(fq)
    _study(fq, unit)
    assert fq.record_temperature(unit, "", 7.5, ts="2026-07-10T08:00:00") == 1
    assert fq.record_temperature(unit, "", 7.8, ts="2026-07-10T09:00:00") == 0
    r = fq.latest_reading(unit)
    assert r["temperature"] == 7.8 and r["correction"] == 0.35 and r["corrected"] == 8.15


def test_a_failed_study_does_not_correct_and_none_means_uncorrected():
    fq = _fq()
    unit = _fridge(fq)
    bad = [(at, probe, nist + 2.0) for at, probe, nist in PAIRS]          # 2 degC off: fails tol 1.0
    _study(fq, unit, bad)
    assert fq.current_correction(unit, "2026-07-10") is None
    assert fq.record_temperature(unit, "", 7.8, ts="2026-07-10T09:00:00") == 1   # raw 7.8 in range
    assert fq.latest_reading(unit)["correction"] is None


def test_the_quarterly_study_is_the_internal_check():
    """A pending study is not a check; a completed one is."""
    fq = _fq()
    unit = _fridge(fq)
    _study(fq, unit, PAIRS[:3], date_="2026-09-01")
    assert fq.last_check_date(unit, "refrigerator") is None
    _study(fq, unit, date_="2026-07-01")
    assert fq.last_check_date(unit, "refrigerator") == "2026-07-01"
