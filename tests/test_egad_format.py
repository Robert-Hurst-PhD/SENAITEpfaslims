# -*- coding: utf-8 -*-
"""Maine EGAD EDD v6.0 row format in ONE place (docs/REUSE_REVIEW.md U5):
egad_format, used by egad_builder; the Python 3 twin is gone."""
from __future__ import unicode_literals

import io
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import egad_format as ef      # noqa: E402


def _row(**over):
    row = dict((c, "x") for c in ef.EDD_COLUMNS)
    row.update(over)
    return [row[c] for c in ef.EDD_COLUMNS]


def test_53_columns_in_template_order():
    assert len(ef.EDD_COLUMNS) == 53 and len(set(ef.EDD_COLUMNS)) == 53
    assert ef.EDD_COLUMNS[:4] == ["PROJECT/SITE", "SAMPLE_POINT_NAME", "SAMPLE_ID", "LAB_SAMPLE_ID"]
    assert ef.EDD_COLUMNS[-1] == "SAMPLE_COMMENT"
    assert ef._QC_REQUIRED < ef._LAB_REQUIRED             # QC rows need a subset
    assert "CONCENTRATION" in ef._LAB_REQUIRED and "CONCENTRATION" not in ef._QC_REQUIRED


def test_dates_are_mm_dd_yyyy_and_times_hh_mm():
    d = datetime(2026, 3, 5, 7, 9)
    assert ef._fmt_date(d) == "03/05/2026" and ef._fmt_time(d) == "07:09"
    assert ef._fmt_date(None) == "" and ef._fmt_date("already") == "already"


def test_row_checks():
    assert ef._validate_row(_row(), 1, False) == []
    blank = ef._validate_row(_row(CONCENTRATION=""), 2, False)
    assert [(e["field"], e["type"]) for e in blank] == [("CONCENTRATION", "Lab")]
    assert ef._validate_row(_row(CONCENTRATION="", LAB_QUALIFIER="U"), 3, False) == []   # non-detect
    assert ef._validate_row(_row(CONCENTRATION=""), 4, True) == []                       # QC row
    ph = ef._validate_row(_row(CAS_NO="PLACEHOLDER"), 5, False)
    assert [e["type"] for e in ph] == ["BLOCKING"]
    empty = ef._validate_row(_row(CAS_NO=""), 6, False)
    assert "BLOCKING" in [e["type"] for e in empty]


def test_units_follow_solid_or_water():
    cfg = {"units_solid": "NG/G", "units_water": "NG/L"}
    assert ef._get_units("EPA_1633A", "SL", cfg) == "NG/G"
    assert ef._get_units("EPA_1633A", "WG", cfg) == "NG/L"


def test_one_copy():
    assert not os.path.exists(os.path.join(ROOT, "pfas_pipeline", "egad_edd.py"))
    with io.open(os.path.join(PKG, "egad_builder.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "from senaite.pfas.egad_format import" in src
    assert "EDD_COLUMNS = [" not in src and "def _validate_row" not in src
    assert len(ef._row_to_list({})) == 53


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
