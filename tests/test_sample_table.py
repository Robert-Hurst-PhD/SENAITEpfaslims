# -*- coding: utf-8 -*-
"""Per-sample amounts, final volumes and dilutions are recorded in the guided
extraction into FM-ENV-003's samples rows -- the table the pipeline reads --
and dilutions are appended, never edited (DECISIONS 2026-10-02)."""
from __future__ import unicode_literals

import copy
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import sample_table as st      # noqa: E402
import dilution_ref as dr      # noqa: E402

ROWS = [{"sample_id": "EGG-1", "matrix_type": "Egg", "sample_type": "Sample", "spike_amount_ng": "2"},
        {"sample_id": "EGG-1 1:10", "dilution_of": "EGG-1", "dilution_factor": "1:10"}]
BATCH = [{"sample_id": "EGG-1", "matrix": "Egg"}, {"sample_id": "DW-1", "matrix": "Drinking Water"}]


def test_stage_column_and_seed():
    assert st.capture_column({"captures_samples": "amount"}) == "amount"
    assert st.capture_column({"captures_samples": "final_volume"}) == "final_volume_ml"
    assert st.capture_column({}) == "" and st.capture_column({"captures_samples": "x"}) == ""
    p = {"extraction_stages": [
        {"order": 1, "name": "Pre-Extraction Setup", "description": "log balance S/N"},
        {"order": 2, "name": "Sample Weighing & Aliquoting", "description": "Weigh 1 g"},
        {"order": 5, "name": "Sample Loading", "description": "Load spiked sample"},
        {"order": 7, "name": "Reconstitution & Final Check", "description": ""},
        {"order": 8, "name": "Kept", "description": "", "captures_samples": "amount"}]}
    assert st.seed_sample_capture(p)
    assert [s["captures_samples"] for s in p["extraction_stages"]] == ["", "amount", "amount", "final_volume", "amount"]
    snap = copy.deepcopy(p)
    assert not st.seed_sample_capture(p) and p == snap


def test_rows_for_card_lists_recorded_then_batch_samples_never_dilutions():
    rows = st.rows_for_card(ROWS, BATCH)
    assert [r["sample_id"] for r in rows] == ["EGG-1", "DW-1"]
    assert rows[1]["amount_unit"] == "mL" and rows[0].get("spike_amount_ng") == "2"
    assert st.rows_for_card([{"sample_id": "M-1", "matrix": "Meat"}], [])[0]["matrix_type"] == "Meat"


def test_merge_records_one_column_and_keeps_everything_else():
    out = st.merge_samples(ROWS, [{"sample_id": "EGG-1", "value": "1.02", "unit": "g"},
                                  {"sample_id": "DW-1", "value": "250", "unit": "mL", "matrix_type": "Drinking Water"},
                                  {"sample_id": "BAD", "value": "abc"}], "amount")
    egg = [r for r in out if r["sample_id"] == "EGG-1"][0]
    assert (egg["amount"], egg["amount_unit"], egg["spike_amount_ng"]) == ("1.02", "g", "2")
    assert [r for r in out if r["sample_id"] == "DW-1"][0]["amount"] == "250"
    assert [r for r in out if r["sample_id"] == "BAD"][0]["amount"] == ""        # not a number
    assert [r for r in out if r.get("dilution_of")] == [ROWS[1]]                  # dilution untouched
    out2 = st.merge_samples(out, [{"sample_id": "EGG-1", "value": "1.0"}], "final_volume_ml")
    egg2 = [r for r in out2 if r["sample_id"] == "EGG-1"][0]
    assert egg2["amount"] == "1.02" and egg2["final_volume_ml"] == "1.0"
    assert st.merge_samples(ROWS, [{"sample_id": "EGG-1", "value": "1"}], "nonsense") == ROWS
    # a dilution's injection name never gets an amount, nor a second row
    assert st.merge_samples(ROWS, [{"sample_id": "EGG-1 1:10", "value": "5"}], "amount") == ROWS
    assert ROWS[0].get("amount") is None                                          # input not mutated


def test_missing():
    assert st.missing(None, [{"sample_id": "A", "value": ""}, {"sample_id": "B", "value": "1"},
                             {"sample_id": "C", "value": "x"}, {"sample_id": "", "value": ""}], "amount") == ["A", "C"]


def test_dilutions_are_appended_checked_and_read_by_the_pipeline_contract():
    rows, err = st.append_dilution(ROWS, "EGG-1", "EGG-1 1:50", "1:50", "KCP", "2026-10-02T15:00:00Z")
    assert err == "" and len(rows) == 3
    new = rows[-1]
    assert (new["dilution_of"], new["sample_id"], new["dilution_factor"], new["logged_by"]) == \
        ("EGG-1", "EGG-1 1:50", "1:50", "KCP")
    for args, why in (((ROWS, "", "X", "10"), "sample"), ((ROWS, "EGG-1", "", "10"), "injection"),
                      ((ROWS, "EGG-1", "X", "ten"), "factor"), ((ROWS, "EGG-1", "X", "0"), "factor"),
                      ((ROWS, "EGG-1", "X", "0:10"), "factor"), ((ROWS, "EGG-1", "X", "1:0"), "factor"),
                      ((ROWS, "EGG-1", "EGG-1 1:10", "10"), "already")):
        r, e = st.append_dilution(*(args + ("KCP", "t")))
        assert e and r == ROWS, (args, e)
        assert why.split()[0] in e.lower() or why == "sample", e
    # what dilution_ref (the pipeline's contract) reads from the appended row
    assert dr.parse_factor(new["dilution_factor"]) == 50.0
    assert [d["sample_id"] for d in st.dilutions(rows)] == ["EGG-1 1:10", "EGG-1 1:50"]


def _src(*parts):
    with io.open(os.path.join(PKG, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_wiring():
    g = _src("browser", "extraction_guide.py")
    stage = g[g.index("def _handle_complete_stage"):]
    stage = stage[:stage.index("\n    def ", 1)]
    refuse = stage[stage.index("if warnings and not deviations:"):stage.index("remember_picks(")]
    assert '"samples": sample_edits' in refuse, "a refused stage keeps the sample entries"
    assert "_save_samples(" not in refuse and "_save_samples(" in stage
    assert stage.index("sample_table.missing(") < stage.index("if warnings and not deviations:")
    assert '"log_dilution"' in g and "append_dilution(" in g
    t = _src("browser", "templates", "extraction_guide.pt")
    assert 'value="log_dilution"' in t and "view/sample_card_json" in t
    dil = t[t.index("<tal:dil "):t.index("</tal:dil>")]
    assert 'tal:condition="view/session"' in dil, "dilutions can be logged after finalizing too"
    js = _src("browser", "static", "method_profile_edit.js")
    assert 'data-field="captures_samples"' in js and "captures_samples: get('captures_samples')" in js
    assert "seed_sample_capture(profile)" in _src("method_profile_store.py")


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
