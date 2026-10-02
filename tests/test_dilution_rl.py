# -*- coding: utf-8 -*-
"""A diluted analyte's reporting limit scales with the dilution: RL x the
total fold (DECISIONS 2026-10-02 — 2 ppt diluted 2-fold reports 4), on the
certificate rows, the certificate's regulatory comparison and the EDD;
independent of the per-sample correction."""
from __future__ import unicode_literals

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import coa_format as cf        # noqa: E402
import report_limits as rl     # noqa: E402

PROFILE = {"master_analyte_set": ["PFOA", "PFOS"], "unit_map": {"Water": "ng/L"},
           "reporting_limits": {"Water": {"PFOA": {"rl": 2.0}, "PFOS": {"rl": 2.0}}}}


def test_scaled_rl():
    assert rl.scaled_rl(2.0, 2) == 4.0 and rl.scaled_rl(2.0, "10") == 20.0
    for fold in (None, "", 1, 0.5, "x"):
        assert rl.scaled_rl(2.0, fold) == 2.0, fold
    assert rl.scaled_rl(None, 2) is None


def test_the_certificate_row_reports_the_scaled_rl_and_the_fold():
    rows = cf.build_rows([{"keyword": "PFOA", "result": "48.2", "dilution": 2.0},
                          {"keyword": "PFOS", "result": "5.1"},
                          {"keyword": "PFOS", "result": "ND", "dilution": 10.0}],
                         PROFILE, "Water", {"coa_nd_format": "lt_rl", "coa_sig_figs": 3})
    pfoa = [r for r in rows if r["keyword"] == "PFOA"][0]
    assert pfoa["rl"] == "4" and pfoa["dilution"] == "2"
    neat = [r for r in rows if r["keyword"] == "PFOS" and not r["dilution"]][0]
    assert neat["rl"] == "2"
    nd = [r for r in rows if r["dilution"] == "10"][0]
    assert nd["rl"] == "20" and "20" in nd["result"], nd     # "< 20": not below the neat RL


def _src(*parts):
    with io.open(os.path.join(PKG, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    coa = _src("browser", "coa_sections.py")
    assert '"dilution": dilution_fold(an)' in coa
    assert 'lim["rl"] = report_limits.scaled_rl(lim["rl"], d.get("dilution"))' in coa
    dr = _src("browser", "dilution_retests.py")
    assert "if not analysis.isRetest():" in dr and "getRetestOf()" in dr
    eg = _src("egad_builder.py")
    i = eg.index("rl = rl * dilution_factor")
    assert eg.index("dilution_factor = rec.get(") < i < eg.index('"reporting_limit": rl,')


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
