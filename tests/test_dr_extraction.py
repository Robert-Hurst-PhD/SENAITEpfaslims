# -*- coding: utf-8 -*-
"""Data Review shows the guided extraction (docs/EXTRACTION_REVIEW_REPORTING_PLAN.md
B1-B4): an Extraction tab from the same summary the guide's review uses,
Overview flags that inform but never gate, form numbers instead of storage
slugs in traceability messages, and which value is reported in Final Data."""
from __future__ import unicode_literals

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")


def _src(*parts):
    with io.open(os.path.join(PKG, *parts), encoding="utf-8") as fh:
        return fh.read()


DR = _src("browser", "data_review.py")
T = _src("browser", "templates", "data_review.pt")


def _fn(name):
    body = DR[DR.index("    def %s(" % name):]
    return body[:body.index("\n    def ", 1)]


def test_the_extraction_tab_uses_the_shared_summary():
    rec = _fn("extraction_record")
    assert "from senaite.pfas.extraction_review import review" in rec
    assert "sample_table.dilutions(rows)" in rec and "_load_session(batch)" in rec
    assert 'href="?tab=extraction"' in T and "view.active_tab() == 'extraction'" in T
    assert "@@pfas-lot-usage?q=" in T, "each lot links to where it was used"


def test_the_overview_informs_and_never_gates():
    assert "view/extraction_flags" in T
    gate = _fn("all_items_pass") if "    def all_items_pass(" in DR else ""
    assert "extraction" not in gate.lower(), "the 5-item checklist is unchanged (DECISIONS 2026-10-02)"
    flags = _fn("extraction_flags")
    for phrase in ("not finalized", "not recorded", "no deviation note", "correction", "not recorded as a fold"):
        assert phrase in flags, phrase


def test_traceability_shows_form_numbers_not_slugs():
    assert "view.source_label(u['source'])" in T and 'tal:replace="u/source"' not in T
    lab = _fn("source_label")
    assert "self._fc(key)" in lab and "Extraction Log" in DR


def test_final_data_marks_the_reported_value():
    fd = _fn("get_final_data")
    assert "isRetested()" in fd and "isRetest()" in fd and '"reported":' in fd
    assert "row/reported" in T


def test_the_checklist_is_computed_once_per_request_and_refreshed_on_save():
    cs = _fn("checklist_status")
    assert "_checklist_status_uncached()" in cs and "copy.deepcopy(cached)" in cs
    save = _fn("_save_checklist")
    assert "self._checklist_cache = None" in save, "a save must not leave a stale checklist"


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
