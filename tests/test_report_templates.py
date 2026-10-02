# -*- coding: utf-8 -*-
"""The certificate template as a controlled document (DECISIONS 2026-10-02):
a revision freezes the Print Settings, every method's report format and the
layout; certificates are drawn from the ISSUED revision, record it, and are
not published before one is issued."""
from __future__ import unicode_literals

import copy
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import report_templates as rt   # noqa: E402

PS = {"lab_name": "Lab", "coa_note": "n", "updated_at": "t1", "updated_by": "a"}
FMT = {"FDA_32PFAS": {"All matrices": {"coa_sig_figs": "3"}}}


def test_snapshot_ignores_save_stamps_and_is_a_copy():
    s = rt.snapshot(PS, FMT, "L1")
    assert "updated_at" not in s["print_settings"] and s["layout"] == "L1"
    s["report_formats"]["FDA_32PFAS"]["All matrices"]["coa_sig_figs"] = "4"
    assert FMT["FDA_32PFAS"]["All matrices"]["coa_sig_figs"] == "3"
    assert rt.fingerprint(rt.snapshot(PS, FMT, "L1")) == rt.fingerprint(
        rt.snapshot(dict(PS, updated_at="t2"), FMT, "L1")), "a save stamp is not a change"


def test_fingerprint_and_changes_see_every_part():
    base = rt.snapshot(PS, FMT, "L1")
    f0 = rt.fingerprint(base)
    for draft, expect in (
            (rt.snapshot(dict(PS, lab_name="Lab 2"), FMT, "L1"), "Print setting lab_name"),
            (rt.snapshot(PS, {"FDA_32PFAS": {"All matrices": {"coa_sig_figs": "2"}}}, "L1"), "Report format of FDA_32PFAS"),
            (rt.snapshot(PS, dict(FMT, EPA_537_1={}), "L1"), "Report format of EPA_537_1"),
            (rt.snapshot(PS, FMT, "L2"), "Certificate layout (the template files changed)")):
        assert rt.fingerprint(draft) != f0, expect
        assert rt.changes(base, draft) == [expect], rt.changes(base, draft)
    assert rt.changes(base, copy.deepcopy(base)) == []


def test_status_and_numbering():
    assert rt.status([], "f") == {"rev": None, "issued_at": "", "unissued": True, "none_issued": True}
    recs = [{"rev": 1, "fingerprint": "a", "issued_at": "t1"}, {"rev": 2, "fingerprint": "b", "issued_at": "t2"}]
    assert rt.next_number(recs) == 3 and rt.next_number([]) == 1
    assert rt.current(list(reversed(recs)))["rev"] == 2
    assert rt.status(recs, "b")["unissued"] is False and rt.status(recs, "a")["unissued"] is True


def _src(*parts):
    with io.open(os.path.join(PKG, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    coa = _src("browser", "coa_sections.py")
    assert "issued_snapshot(api.get_portal())" in coa and "snapshot_override" in coa
    settings = coa[coa.index("    def settings(self):"):]
    settings = settings[:settings.index("\n    def ", 1)]
    assert 'snap.get("print_settings")' in settings, "the certificate reads the issued settings"
    assert '(snap.get("report_formats") or {}).get(method_id)' in coa
    g = _src("browser", "guards.py")
    assert "class ReportTemplateGuard" in g and "return snap is not None" in g
    z = _src("browser", "configure.zcml")
    assert ".guards.ReportTemplateGuard" in z and 'name="pfas-report-template"' in z
    assert '"template_rev": _template_rev()' in _src("browser", "controlled_publications.py")
    v = _src("browser", "report_template.py")
    assert "if not self.can_issue():" in v and v.index("if not self.can_issue():") < v.index("rt.issue(")
    assert "Nothing to issue" in v
    t = _src("browser", "templates", "data_review.pt")
    assert "view/template_status" in t and "Issue certificate" in t
    assert "meta/template_rev" in _src("browser", "templates", "coa_sections.pt")


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
