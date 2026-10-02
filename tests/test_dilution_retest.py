# -*- coding: utf-8 -*-
"""A dilution is appended over the above-LOQ neat value with its own analysis
time, as a SENAITE retest (DECISIONS 2026-10-02). Worker: the summary carries
both analysis times; the analysis gets the NEAT reading and the dilution goes
to the add-on. Add-on: kept on the analysis, appended as a retest at Data
Review submission, reported by the retest on the certificate and the EDD."""
from __future__ import unicode_literals

import io
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import dilution_retest as drt      # noqa: E402

BODY = {"analysis_uid": "u1", "result": 48.2, "qualifier": "", "flags": ["SUR"],
        "factor": 10.0, "injection": "Egg-9 1:10", "analysed_at": "2026-03-14T09:30:00",
        "neat_result": 512.0, "neat_qualifier": "ALoQ", "neat_injection": "Egg-9",
        "neat_analysed_at": "2026-03-13T17:05:00"}


def test_record_requires_injection_time_and_result():
    rec, why = drt.record(BODY, "now")
    assert why == "" and rec["result"] == 48.2 and rec["retest_uid"] == ""
    for k in ("injection", "analysed_at"):
        assert drt.record(dict(BODY, **{k: ""}), "now")[0] is None, k
    assert drt.record(dict(BODY, result=None, qualifier=""), "now")[0] is None
    assert drt.record(dict(BODY, result=None, qualifier="BLoQ"), "now")[0]["qualifier"] == "BLoQ"


def test_the_retest_carries_the_dilution_and_its_own_time():
    rec = drt.record(BODY, "now")[0]
    plan = drt.retest_plan(rec)
    assert plan["result"] == "48.2" and plan["captured"] == "2026-03-14T09:30:00"
    assert plan["remarks"] == ("Dilution 10-fold (Egg-9 1:10) analysed 2026-03-14T09:30:00; "
                               "replaces neat 512 (ALoQ) (Egg-9) analysed 2026-03-13T17:05:00; SUR")
    q = drt.retest_plan(drt.record(dict(BODY, result=None, qualifier="BLoQ"), "now")[0])
    assert q["result"] == "BLoQ"


def _worker():
    if sys.version_info[0] < 3:
        return None
    sys.path.insert(0, ROOT)
    from pfas_pipeline.models import Batch, InstrumentRow
    from pfas_pipeline.pipeline import build_summary
    return Batch, InstrumentRow, build_summary


def _row(InstrumentRow, inj, calc, qual, when):
    return InstrumentRow(
        compound_name="PFOA", compound_type="Analyte", compound_group="", sample_description="",
        injection_name=inj, sample_group="", sample_type="Unknown", included_in_cal=False,
        level=None, linked_is=None, cal_ref_compound=None, observed_rt=10.0, rt_relative_to_is=1.0,
        response=1000.0, is_response=1000.0, response_ratio=1.0, expected_conc=None,
        calculated_conc=calc, pct_deviation=None, pct_recovery_is=None, ion_ratios=None,
        expected_ion_ratios=None, r2=None, signal_to_noise=50.0, qual_sn=50.0,
        quant_status="Successful", reporting_limit=0.039, measured_conc=calc,
        acquisition_datetime=when, concat_id=inj, conc_qualifier=qual)


def test_the_summary_carries_both_analysis_times():
    w = _worker()
    if w is None:
        return
    Batch, InstrumentRow, build_summary = w
    neat_t, dil_t = datetime(2026, 3, 13, 17, 5), datetime(2026, 3, 14, 9, 30)
    rows = [_row(InstrumentRow, "Egg-9", 512.0, "ALoQ", neat_t),
            _row(InstrumentRow, "Egg-9 1:10", 48.2, "", dil_t)]
    b = Batch(batch_id="T", analyst="T", date=neat_t, matrix="Animal Feed", method_id="FDA_32PFAS",
              instrument_file="t.csv", injections=rows,
              dilutions={"Egg-9 1:10": {"parent": "Egg-9", "factor": 10.0}})
    s = [x for x in build_summary(b) if x.analyte == "PFOA" and x.sample_injection == "Egg-9"][0]
    assert s.source_injection == "Egg-9 1:10" and s.neat_qualifier == "ALoQ"
    assert s.analysed_at == dil_t.isoformat() and s.neat_analysed_at == neat_t.isoformat()
    import pfas_pipeline.pipeline as pl
    saved = pl._get_sample_correction
    try:
        pl._get_sample_correction = lambda m: "instrument"     # the MS software applied it
        s3 = [x for x in build_summary(b) if x.analyte == "PFOA" and x.sample_injection == "Egg-9"][0]
        assert s3.result_ppt == 48.2, s3.result_ppt
        pl._get_sample_correction = lambda m: ""
        assert abs([x for x in build_summary(b) if x.analyte == "PFOA"
                    and x.sample_injection == "Egg-9"][0].result_ppt - 482.0) < 1e-9
        b.dilutions = {"Egg-9 1:10": {"parent": "Egg-9", "factor": None}}   # no usable fold
        s4 = [x for x in build_summary(b) if x.analyte == "PFOA" and x.sample_injection == "Egg-9"][0]
        assert s4.qualifier == "ALoQ" and s4.source_injection == "Egg-9", "not substituted"
        b.dilutions = {"Egg-9 1:10": {"parent": "Egg-9", "factor": 10.0}}
    finally:
        pl._get_sample_correction = saved
    # in range: the neat stands, with its own time and no neat time
    rows2 = [_row(InstrumentRow, "Egg-9", 5.0, "", neat_t), rows[1]]
    b.injections = rows2
    s2 = [x for x in build_summary(b) if x.analyte == "PFOA" and x.sample_injection == "Egg-9"][0]
    assert s2.analysed_at == neat_t.isoformat() and s2.neat_analysed_at == ""


def test_the_worker_pushes_the_neat_reading_and_hands_over_the_dilution():
    if sys.version_info[0] < 3:
        return
    sys.path.insert(0, ROOT)
    from pfas_pipeline.models import SummaryResult
    from pfas_pipeline.senaite_connector import SenaiteConnector

    class Resp(object):
        def __init__(self, data):
            self.data, self.text = data, json.dumps(data)

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class Session(object):
        def __init__(self):
            self.posts = []

        def post(self, url, json=None, timeout=None):
            self.posts.append((url, json))
            return Resp({"ok": True} if "dilution-result" in url else {"items": []})

    c = SenaiteConnector.__new__(SenaiteConnector)
    c.session, c.api, c.base, c.timeout = Session(), "http://x/api", "http://x", 5
    c.search = lambda **kw: [{"uid": "u1"}]
    s = SummaryResult(analyte="PFOA", sample_injection="Egg-9", result_ppt=48.2, qualifier="",
                      source_injection="Egg-9 1:10", neat_result=512.0, neat_qualifier="ALoQ",
                      dilution_factor=10.0, analysed_at="2026-03-14T09:30:00",
                      neat_analysed_at="2026-03-13T17:05:00")
    assert c.push_result("ar1", "PFOA", s)
    (u1, update), (u2, dil) = c.session.posts
    assert u1.endswith("update/u1") and update["Result"] == 512.0, update
    assert u2.endswith("@@pfas-dilution-result")
    assert (dil["result"], dil["factor"], dil["analysed_at"], dil["neat_analysed_at"]) == \
        (48.2, 10.0, "2026-03-14T09:30:00", "2026-03-13T17:05:00")
    # no dilution: one update with the result, nothing handed over
    c.session = Session()
    plain = SummaryResult(analyte="PFOA", sample_injection="Egg-9", result_ppt=5.0, qualifier="",
                          source_injection="Egg-9")
    assert c.push_result("ar1", "PFOA", plain) and len(c.session.posts) == 1
    assert c.session.posts[0][1]["Result"] == 5.0


def _src(*parts):
    with io.open(os.path.join(PKG, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    dr = _src("browser", "data_review.py")
    sub = dr[dr.index("def _handle_submit_for_review"):] if "def _handle_submit_for_review" in dr else dr
    i = sub.index('wf_tool.doActionFor(analysis, "submit")')
    assert "append_dilution_retest(analysis, wf_tool)" in sub[i:i + 600], \
        "the retest is appended right after the neat analysis is submitted"
    mod = _src("browser", "dilution_retests.py")
    assert "create_retest(analysis)" in mod and 'doActionFor(retest, "submit")' in mod
    assert 'setResultCaptureDate(DateTime(plan["captured"]))' in mod
    assert "checkPermission(EDIT_RESULT, analysis)" in mod
    assert mod.index("checkPermission(EDIT_RESULT") < mod.index("IDisableCSRFProtection")
    assert "isRetested()" in _src("browser", "coa_sections.py")
    eg = _src("egad_builder.py")
    assert "isRetested()" in eg and '"dilution_factor": dilution_factor' in eg
    assert 'name="pfas-dilution-result"' in _src("browser", "configure.zcml")


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
