# -*- coding: utf-8 -*-
"""Guided extraction ease of use (docs/EXTRACTION_REVIEW_REPORTING_PLAN.md):
what the page shows, the next stage after a correction, reopening a completed
stage with a reason (previous version kept, never after finalizing), and the
review summary shared with Data Review."""
from __future__ import unicode_literals

import copy
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import extraction_review as er    # noqa: E402

ORDERS = [1, 2, 3]
DEF = [{"order": 1, "name": "Setup"}, {"order": 2, "name": "Weigh"}, {"order": 3, "name": "Extract"}]


def sess(done, **kw):
    s = {"stages": dict(("%s" % o, {"completed_at": "2026-10-02T1%s:00:00Z" % o, "analyst": "AN1",
                                    "reagents": [], "warnings": []}) for o in done)}
    s.update(kw)
    return s


def test_mode():
    assert er.mode(sess([]), ORDERS) == "edit"
    assert er.mode(sess([1]), ORDERS) == "edit"
    assert er.mode(sess([1]), ORDERS, view_order=1) == "view"
    assert er.mode(sess([1]), ORDERS, view_order=2) == "edit"          # not completed: no view
    assert er.mode(sess([1, 2, 3]), ORDERS) == "review"
    assert er.mode(sess([1, 2, 3]), ORDERS, view_order=2) == "view"
    assert er.mode(sess([1, 2, 3], reopened=2), ORDERS) == "edit"
    assert er.mode(sess([1, 2, 3], finalized=True), ORDERS, view_order=2) == "done"
    assert er.mode(sess([]), []) == "edit"


def test_next_stage_after_a_correction_is_the_first_unfinished():
    assert er.next_stage(ORDERS, sess([])) == 1
    assert er.next_stage(ORDERS, sess([1, 3])) == 2
    assert er.next_stage(ORDERS, sess([1, 2, 3])) is None


def test_reopen_keeps_the_previous_version_and_the_reason():
    s0 = sess([1, 2, 3])
    s0["stages"]["2"]["deviations"] = "old note"
    s1, why = er.reopen(s0, 2, "  wrong lot picked ", "AN2", "2026-10-02T20:00:00Z")
    assert why == "" and s1["reopened"] == 2 and s1["current_stage"] == 2
    c = s1["stages"]["2"]["corrections"][0]
    assert c["reason"] == "wrong lot picked" and c["by"] == "AN2"
    assert c["previous"]["deviations"] == "old note" and "corrections" not in c["previous"]
    assert "reopened" not in s0 and "corrections" not in s0["stages"]["2"]      # input untouched
    s2, _ = er.reopen(s1, 2, "again", "AN2", "t")
    assert len(s2["stages"]["2"]["corrections"]) == 2
    assert "corrections" not in s2["stages"]["2"]["corrections"][1]["previous"]


def test_reopen_is_refused_without_reason_unfinished_or_finalized():
    for args, part in (((sess([1]), 1, "  "), "why"), ((sess([1]), 2, "x"), "not been completed"),
                       ((sess([1], finalized=True), 1, "x"), "deviation")):
        s, why = er.reopen(*(args + ("AN1", "t")))
        assert part in why, why
        assert "reopened" not in s


def test_review_summary():
    s = sess([1, 3])
    s["stages"]["1"]["reagents"] = [
        {"group": "reagent", "role": "Methanol", "name": "Methanol LC-MS", "lot": "M-1", "qty_used": "5 mL",
         "from_inventory": True},
        {"group": "consumable", "role": "Tubes", "name": "50 mL tubes", "lot": "T-9", "from_inventory": True},
        {"role": "Water", "name": "Water", "lot": "W-typed"}]
    s["stages"]["1"]["equipment_sns"] = {"Balance": "B-1"}
    s["stages"]["3"]["warnings"] = ["Water: no lot recorded"]
    s["stages"]["3"]["corrections"] = [{"at": "t", "by": "AN2", "reason": "r", "previous": {}}]
    r = er.review(s, DEF)
    assert [x["order"] for x in r["stages"]] == [1, 2, 3] and r["missing"] == [2]
    st1 = r["stages"][0]
    assert [x["lot"] for x in st1["reagents"]] == ["M-1", "W-typed"]
    assert st1["reagents"][1]["from_inventory"] is False
    assert [x["lot"] for x in st1["consumables"]] == ["T-9"] and st1["equipment"] == [("Balance", "B-1")]
    assert r["noted"] == 1 and r["unnoted"] == [3] and r["corrections"] == 1
    s["stages"]["3"]["deviations"] = "explained"
    assert er.review(s, DEF)["unnoted"] == []


def _src(*parts):
    with io.open(os.path.join(PKG, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    g = _src("browser", "extraction_guide.py")
    assert "int(round(100.0 * done / total))" in g, "Python 2 integer division froze the bar at 0 %"
    stage = g[g.index("def _handle_complete_stage"):]
    stage = stage[:stage.index("\n    def ", 1)]
    assert 'stage_data["corrections"] = previous["corrections"]' in stage
    assert 'sess.pop("reopened", None)' in stage and "next_stage(" in stage
    assert '"reopen_stage"' in g
    t = _src("browser", "templates", "extraction_guide.pt")
    assert "python: view.mode() == 'edit'" in t and 'value="reopen_stage"' in t
    assert "view.mode() in ('review', 'done')" in t, "dilutions only after the last stage"
    assert 'name="stage_analyst" id="stage-analyst-field"' in t and "<h3>Analyst</h3>" not in t
    assert "@media (max-width: 1100px)" in t and "position:sticky" in t


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
