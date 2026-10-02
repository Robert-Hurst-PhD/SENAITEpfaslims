# -*- coding: utf-8 -*-
"""The extraction logbook PDF (docs/REUSE_REVIEW.md U1): WeasyPrint, which is
installed, instead of ReportLab, which never was. The data step is pure."""
from __future__ import unicode_literals

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import extraction_logbook as el      # noqa: E402

PROFILE = {"display_name": "EPA 1633A", "extraction_stages": [
    {"order": 2, "name": "SPE"}, {"order": 1, "name": "Spike"}, {"order": 3, "name": "Concentrate"}]}
SESSION = {"method_id": "EPA_1633A", "analyst": "DEMO", "started_at": "2026-10-01 09:00",
           "finalized_at": "", "finalized_by": None,
           "stages": {"1": {"completed_at": "2026-10-01 09:30", "analyst": "DEMO",
                            "equipment_sns": {"Balance": "B-114", "Pipette": ""},
                            "reagents": [{"name": "Methanol, LC-MS", "lot": "M1",
                                          "supplier": "Fisher Scientific", "volume": "50 mL"}],
                            "solutions_prepared": [{"name": "Spike mix", "lot": "SP-1", "conc": "10 ng/mL",
                                                    "volume_ml": 5, "expiry": "2026-11-01"}],
                            "deviations": "Late start"},
                      "2": {"completed_at": "2026-10-01 11:00", "analyst": "DEMO"}},
           # the stored shape: one spike record per spiked QC sample
           "pedigree": {"Egg-2 LFSM Mid": {"spike_volume_ul": "50", "spike_lot": "PS-SPK-1",
                                           "spike_source": "reviewer-entered", "spike_ppt": 100.0,
                                           "spike_entered_at": "2026-08-03 17:45",
                                           "parent_sample": "Egg-2", "spike_entered_by": "admin"},
                        "Cal A": [{"level": "CRM", "lot": "W1", "cert_conc": 50,
                                   "supplier": "Wellington", "cert_date": "2026-01-01",
                                   "coa": "C-1"}]}}


def test_stages_in_order_with_pending_ones_listed():
    d = el.logbook_data("B-1", "Batch 1", SESSION, PROFILE, "now")
    assert [s["order"] for s in d["summary"]] == ["1", "2", "3"]
    assert d["summary"][2]["completed"] == el.DASH                         # not done yet
    assert [x["title"] for x in d["details"]] == ["Stage 1: Spike", "Stage 2: SPE"]


def test_details_carry_every_record():
    st = el.logbook_data("B-1", "Batch 1", SESSION, PROFILE, "now")["details"][0]
    assert st["equipment"] == [("Balance", "B-114"), ("Pipette", el.DASH)]
    assert st["reagents"] == [["Methanol, LC-MS", "M1", "Fisher Scientific", "50 mL", el.DASH]]
    assert st["solutions"][0] == ["Spike mix", "SP-1", "10 ng/mL", "5", "2026-11-01"]
    assert st["deviations"] == "Late start"


def test_header_pedigree_and_signoff():
    d = el.logbook_data("B-1", "Batch 1", SESSION, PROFILE, "2026-10-02 08:00 UTC")
    h = dict(d["header"])
    assert h["Batch ID"] == "B-1" and h["Method"] == "EPA 1633A" and h["Finalized"] == el.DASH
    assert h["PDF Generated"] == "2026-10-02 08:00 UTC"
    assert d["spikes"] == [["Egg-2 LFSM Mid", "Egg-2", "PS-SPK-1", "50", "100.0", "admin",
                            "2026-08-03 17:45", "reviewer-entered"]]
    assert d["pedigree"] == [{"name": "Cal A", "rows": [["CRM", "W1", "50", "Wellington",
                                                          "2026-01-01", "C-1"]]}]
    assert dict(d["signoff"])["Reviewing Analyst"] == el.DASH


def test_the_view_uses_weasyprint_and_no_reportlab():
    with io.open(os.path.join(PKG, "browser", "extraction_pdf.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "from weasyprint import HTML" in src
    assert "from reportlab" not in src and "import reportlab" not in src
    tpl = os.path.join(PKG, "browser", "templates", "extraction_pdf.pt")
    with io.open(tpl, encoding="utf-8") as fh:
        t = fh.read()
    for key in ("d/header", "d/summary", "d/details", "d/spikes", "d/pedigree", "d/signoff"):
        assert key in t, key


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
