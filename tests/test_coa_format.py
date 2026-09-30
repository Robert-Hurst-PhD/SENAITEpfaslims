# -*- coding: utf-8 -*-
"""The compact certificate's reporting conventions (GAPS §50, part A).

Decided 2026-09-30: RL/MDL come from the method profile per analyte x matrix;
a non-detect prints "< RL" with a U qualifier; limits print with the matrix's
unit. These tests run the real coa_format / report_limits modules (no Zope).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src", "senaite", "pfas"))

import coa_format as cf        # noqa: E402
import report_limits as rl     # noqa: E402


def test_significant_figures_never_use_exponents():
    assert cf.sig_figs(30.1745785496) == "30.2"
    assert cf.sig_figs(0.189353845648) == "0.189"
    assert cf.sig_figs(104.432) == "104"
    assert cf.sig_figs(12345) == "12300"
    assert cf.sig_figs(0.0000123, 2) == "0.000012"
    assert cf.sig_figs(0) == "0"


def test_limits_print_as_configured():
    assert cf.format_limit(0.5) == "0.5"
    assert cf.format_limit(2.0) == "2"
    assert cf.format_limit(None) == ""


def test_nondetect_prints_less_than_rl_with_u():
    for raw in ("BLoQ", "LOD", "ND", "<LOQ"):
        r = cf.format_result(raw, 0.5)
        assert r == {"text": "< 0.5", "qualifiers": ["U"], "detected": False}, (raw, r)


def test_numeric_below_rl_is_a_nondetect_not_a_j_value():
    r = cf.format_result("0.2", 0.5)
    assert r["text"] == "< 0.5" and r["qualifiers"] == ["U"]


def test_without_an_rl_nothing_is_invented():
    assert cf.format_result("BLoQ", None)["text"] == "ND"
    assert cf.format_result("0.2", None) == {"text": "0.200", "qualifiers": [], "detected": True}


def test_other_nondetect_formats():
    assert cf.format_result("BLoQ", 0.5, "nd")["text"] == "ND"
    assert cf.format_result("BLoQ", 0.5, "raw")["text"] == "BLoQ"
    assert cf.format_result("BLoQ", 0.5, "bogus")["text"] == "< 0.5"   # falls back


def test_unrecognised_text_prints_as_entered():
    assert cf.format_result("see remarks", 0.5) == {
        "text": "see remarks", "qualifiers": [], "detected": None}


def test_parse_form_takes_only_the_matrices_it_carried():
    form = {"rlm.0": "Drinking Water", "rl.0.PFOA": "4", "mdl.0.PFOA": "1.2",
            "rl.0.PFOS": "", "mdl.0.PFOS": "",
            "rl.1.PFOA": "99"}                       # matrix 1 not marked present
    out = rl.parse_form(form, ["Drinking Water", "Groundwater"])
    assert out == {"Drinking Water": {"PFOA": {"rl": 4.0, "mdl": 1.2}}}


def test_parse_form_refuses_bad_values():
    for bad in ({"rlm.0": "W", "rl.0.PFOA": "abc"},
                {"rlm.0": "W", "rl.0.PFOA": "-1"},
                {"rlm.0": "W", "rl.0.PFOA": "1", "mdl.0.PFOA": "2"}):   # MDL above RL
        try:
            rl.parse_form(bad, ["W"])
        except ValueError:
            continue
        raise AssertionError("accepted {0}".format(bad))


def test_merge_keeps_matrices_the_form_did_not_carry():
    existing = {"A": {"PFOA": {"rl": 1.0, "mdl": None}}, "B": {"PFOS": {"rl": 2.0, "mdl": None}}}
    merged = rl.merge(existing, {"A": {}})
    assert "A" not in merged and merged["B"] == existing["B"]   # emptied -> dropped
    assert rl.merge({}, {"A": {}, "B": {}}) == {}                # nothing entered -> nothing stored


def test_limits_come_with_the_matrix_unit():
    profile = {"unit_map": {"Drinking Water": "ng/L"},
               "reporting_limits": {"Drinking Water": {"PFOA": {"rl": 4.0, "mdl": 1.0}}}}
    assert rl.limits_for(profile, "Drinking Water", "PFOA") == {"rl": 4.0, "mdl": 1.0, "unit": "ng/L"}
    assert rl.limits_for(profile, "Drinking Water", "PFNA") == {"rl": None, "mdl": None, "unit": "ng/L"}


def test_matrix_aliases_resolve():
    profile = {"supported_matrices": ["Drinking Water"],
               "matrix_aliases": {"Drinking Water": ["DW", "Potable water"]}}
    assert rl.canonical_matrix(profile, "potable water") == "Drinking Water"
    assert rl.canonical_matrix(profile, "Drinking Water") == "Drinking Water"
    assert rl.canonical_matrix(profile, "Soil") == "Soil"


def test_rows_follow_method_order_and_keep_unexpected_results():
    profile = {"master_analyte_set": ["PFBA", "PFOA"], "unit_map": {"W": "ng/L"},
               "reporting_limits": {"W": {"PFOA": {"rl": 2.0, "mdl": 0.5}}}}
    rows = cf.build_rows([{"keyword": "ZZZ", "result": "1"},
                          {"keyword": "PFOA", "result": "12.74", "codes": ["M"]},
                          {"keyword": "PFBA", "result": "BLoQ"}],
                         profile, "W", {"coa_sig_figs": "3"}, {"PFOA": "335-67-1"})
    assert [r["keyword"] for r in rows] == ["PFBA", "PFOA", "ZZZ"]
    pfoa = rows[1]
    assert (pfoa["result"], pfoa["qualifiers"], pfoa["rl"], pfoa["mdl"], pfoa["unit"], pfoa["cas"]) == (
        "12.7", "M", "2", "0.5", "ng/L", "335-67-1")
    assert rows[0]["qualifiers"] == "U"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
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
