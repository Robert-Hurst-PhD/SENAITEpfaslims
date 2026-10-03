# -*- coding: utf-8 -*-
"""Equipment in the Settings Report (GAPS §102): the statements it makes about
how equipment rules are applied are built from the constants the code uses,
so the audit record cannot describe a rule the code does not run."""
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import equipment_report as er  # noqa: E402
import equipment_types as et   # noqa: E402


def _fq():
    os.environ["PFAS_FACILITY_QC_DB"] = os.path.join(tempfile.mkdtemp(prefix="pfas_er_"), "f.db")
    spec = importlib.util.spec_from_file_location("pfas_fq_er", os.path.join(PKG, "facility_qc.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.ensure_schema()
    return m


def test_the_statements_follow_the_code_constants():
    fq = _fq()
    text = dict(er.application(fq.STUDY_POINTS, fq.STUDY_MIN_DAYS))
    assert "%d paired readings" % fq.STUDY_POINTS in text["Thermometer correction factor"]
    assert "at least %d days" % fq.STUDY_MIN_DAYS in text["Thermometer correction factor"]
    assert "NIST average minus the probe average" in text["Thermometer correction factor"]
    assert "0.2 % of nominal" in text["Balance verification"]
    assert "in g" in text["Balance verification"]
    assert "%d days is 'due soon'" % et.DUE_SOON_DAYS in text["Internal checks and due dates"]
    assert "%d days (quarterly)" % et.STUDY_EVERY_DAYS in text["Internal checks and due dates"]


def test_the_statements_match_what_the_code_does():
    """Behavioural counterpart: the rule as stated is the rule as run."""
    fq = _fq()
    unit = fq.save_unit({"unit_type": "refrigerator", "name": "F", "location": "L",
                         "serial_number": "", "sensor_id": "", "temp_min": 2.0, "temp_max": 8.0})
    sid = fq.create_study(unit, "AN1", "NIST-1", study_date="2026-07-01")
    assert len(fq.get_study(sid)["points"]) == fq.STUDY_POINTS
    for i, at in enumerate(("2026-07-01T09:00", "2026-07-01T16:00", "2026-07-02T09:00",
                            "2026-07-02T16:00"), 1):
        fq.save_study_point(sid, i, 4.0, 4.5, recorded_at=at, entered_by="AN1")
    assert fq.current_correction(unit, "2026-07-03")["correction"] == 0.5     # NIST - probe
    assert et.within(10, 10 + 10 * et.BALANCE_TOLERANCE_PCT / 100.0, et.BALANCE_TOLERANCE_PCT)


def test_a_changed_study_reading_keeps_its_previous_value():
    fq = _fq()
    unit = fq.save_unit({"unit_type": "freezer", "name": "Z", "location": "L",
                         "serial_number": "", "sensor_id": ""})
    sid = fq.create_study(unit, "AN1", "NIST-1", study_date="2026-07-01")
    fq.save_study_point(sid, 1, -20.0, -19.6, recorded_at="2026-07-01T09:00", entered_by="AN1")
    fq.save_study_point(sid, 1, -20.0, -19.6, recorded_at="2026-07-01T09:00", entered_by="AN1")
    assert fq.study_point_changes(sid) == [], "re-saving the same values is not a change"
    fq.save_study_point(sid, 1, -20.2, -19.6, recorded_at="2026-07-01T09:00", entered_by="AN2")
    ch = fq.study_point_changes(sid)
    assert len(ch) == 1 and ch[0]["old_sensor"] == -20.0 and ch[0]["old_entered_by"] == "AN1"
    assert ch[0]["changed_by"] == "AN2"
    assert fq.get_study(sid)["points"][0]["entered_by"] == "AN2"


def test_the_instrument_rows_say_what_is_and_is_not_corrected():
    req_t = et.seed("refrigerator")
    rows = er.instrument_rows([
        {"unit": {"name": "F1", "requirements": req_t}, "due": {"status": "ok"},
         "correction": {"correction": 0.35, "study_date": "2026-07-01"},
         "study": {"study": {"nist_serial": "N1", "operator": "AN1"}, "changes": 1}},
        {"unit": {"name": "F2", "requirements": req_t}, "due": {"status": "missing"}},
        {"unit": {"name": "B1", "requirements": et.seed("balance_prep")}, "due": {"status": "not_set"}}])
    assert rows[0]["correction"].startswith(u"+0.350 °C, study of 2026-07-01 (NIST N1, AN1)")
    assert "1 reading(s) changed" in rows[0]["correction"]
    assert rows[1]["correction"].startswith("none: no passed study")
    assert rows[2]["correction"] == "not required" and rows[1]["status"] == "No record"


def test_the_fingerprint_moves_with_equipment_configuration():
    import settings_report as sr
    types = [{"uid": "t1", "title": "Fridge", "req": et.seed("refrigerator")}]
    a = sr.fingerprint(er.config(types, []))
    types[0]["req"] = dict(types[0]["req"], cal_frequency_days=30)
    assert sr.fingerprint(er.config(types, [])) != a
