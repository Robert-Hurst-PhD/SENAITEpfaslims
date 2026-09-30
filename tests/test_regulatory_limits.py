# -*- coding: utf-8 -*-
"""Regulatory notes on the certificate (GAPS §50, part B).

Rule (DECISIONS 2026-09-30): detected sum >= limit -> exceeds; a non-detect
whose RL alone reaches the limit -> cannot be determined; no comparable unit ->
no comparison; only VERIFIED limits are used. Runs the real module.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src", "senaite", "pfas"))

import regulatory_limits as rg   # noqa: E402

PFOA = {"id": "t", "program": "federal", "analytes": ["PFOA"], "matrices": ["Drinking Water"],
        "value": 4.0, "unit": "ng/L", "verified": True}
SUM6 = {"id": "s", "program": "maine_egad", "analytes": ["PFOA", "PFOS", "br-PFOS", "PFNA"],
        "matrices": ["Drinking Water"], "value": 20.0, "unit": "ng/L", "verified": True}


def test_seeds_are_never_verified():
    assert rg.SEED_LIMITS and all(l["verified"] is False for l in rg.SEED_LIMITS)
    assert all(l["citation"] and l["url"] for l in rg.SEED_LIMITS)


def test_only_verified_limits_of_the_clients_programs_apply():
    unverified = dict(PFOA, id="u", verified=False)
    other = dict(PFOA, id="o", program="nh_program")
    got = rg.applicable([PFOA, unverified, other, SUM6], ["federal", "maine_egad"], "drinking water")
    assert [l["id"] for l in got] == ["t", "s"]
    assert rg.applicable([PFOA], ["federal"], "Soil") == []


def test_detected_at_or_above_the_limit_exceeds():
    r = rg.evaluate(PFOA, {"PFOA": {"value": 4.0, "rl": 2.0}}, "ng/L")
    assert r["status"] == "exceeds" and r["total"] == 4.0


def test_detected_below_is_below():
    assert rg.evaluate(PFOA, {"PFOA": {"value": 3.9, "rl": 2.0}}, "ng/L")["status"] == "below"


def test_nondetect_with_rl_above_the_limit_is_undetermined_not_meets():
    assert rg.evaluate(PFOA, {"PFOA": {"value": None, "rl": 5.0}}, "ng/L")["status"] == "undetermined"
    assert rg.evaluate(PFOA, {"PFOA": {"value": None, "rl": 2.0}}, "ng/L")["status"] == "below"
    assert rg.evaluate(PFOA, {"PFOA": {"value": None, "rl": None}}, "ng/L")["status"] == "undetermined"


def test_sum_uses_detected_values_only():
    res = {"PFOA": {"value": 8.0, "rl": 2.0}, "PFOS": {"value": 7.0, "rl": 2.0},
           "br-PFOS": {"value": 6.0, "rl": 2.0}, "PFNA": {"value": None, "rl": 2.0}}
    r = rg.evaluate(SUM6, res, "ng/L")
    assert r["status"] == "exceeds" and r["total"] == 21.0 and r["detected"] == ["PFOA", "PFOS", "br-PFOS"]


def test_units_convert_within_a_dimension_only():
    beef = dict(PFOA, analytes=["PFOS"], value=3.4, unit="ng/g", matrices=["Beef"])
    assert rg.evaluate(beef, {"PFOS": {"value": 3500.0, "rl": 100.0}}, "ng/kg")["status"] == "exceeds"
    assert rg.evaluate(beef, {"PFOS": {"value": 3.0, "rl": 1.0}}, "ng/L")["status"] == "no_unit"


def test_not_reported_means_no_comparison():
    assert rg.evaluate(PFOA, {"PFOS": {"value": 1.0, "rl": 1.0}}, "ng/L") is None


def _form_for(limits):
    """The fields @@pfas-regulatory-limits renders: every record, then a blank row."""
    f = {}
    for i, l in enumerate(limits):
        f.update({"lim.%d.id" % i: l["id"], "lim.%d.program" % i: l["program"],
                  "lim.%d.label" % i: l["label"], "lim.%d.analytes" % i: ", ".join(l["analytes"]),
                  "lim.%d.matrices" % i: ", ".join(l["matrices"]), "lim.%d.value" % i: str(l["value"]),
                  "lim.%d.unit" % i: l["unit"], "lim.%d.kind" % i: l["kind"],
                  "lim.%d.citation" % i: l["citation"], "lim.%d.effective" % i: l["effective"],
                  "lim.%d.status_note" % i: l["status_note"], "lim.%d.url" % i: l["url"]})
        if l["verified"]:
            f["lim.%d.verified" % i] = "1"
    n = len(limits)
    f.update({"lim.%d.id" % n: "", "lim.%d.label" % n: "", "lim.%d.value" % n: ""})
    return f


def test_an_unchanged_save_returns_exactly_the_same_limits():
    """The first version's field getter closed over the loop counter and read
    the NEXT row: an unchanged save lost the first record and shifted the rest."""
    got = rg.parse_limits_form(_form_for(rg.SEED_LIMITS), rg.SEED_LIMITS, "u", "2026-09-30 12:00")
    assert got == rg.SEED_LIMITS, [l["id"] for l in got]


def test_links_must_be_http():
    form = _form_for(rg.SEED_LIMITS[:1])
    form["lim.0.url"] = "javascript:alert(1)"
    try:
        rg.parse_limits_form(form, [], "u", "now")
    except ValueError:
        pass
    else:
        raise AssertionError("javascript: link accepted")
    try:
        rg.parse_programs_form({"prog.federal.links": "EPA | javascript:x"}, ["federal"])
    except ValueError:
        return
    raise AssertionError("javascript: program link accepted")


def test_verifying_stamps_who_and_when_and_a_changed_value_restamps():
    seed = dict(rg.SEED_LIMITS[0])
    form = _form_for([dict(seed, verified=True)])
    first = rg.parse_limits_form(form, [seed], "qao", "2026-10-01 09:00")[0]
    assert (first["verified_by"], first["verified_at"]) == ("qao", "2026-10-01 09:00")
    again = rg.parse_limits_form(form, [first], "other", "2026-10-02 09:00")[0]
    assert again["verified_by"] == "qao", "an unchanged verified limit lost its stamp"
    form["lim.0.value"] = "3.0"
    changed = rg.parse_limits_form(form, [first], "other", "2026-10-02 09:00")[0]
    assert changed["verified_by"] == "other", "a changed value kept the old verification"


def test_bad_values_are_refused():
    for field, bad in (("value", "abc"), ("value", "0"), ("unit", "ppt"), ("analytes", "")):
        form = _form_for(rg.SEED_LIMITS[:1])
        form["lim.0.%s" % field] = bad
        try:
            rg.parse_limits_form(form, [], "u", "now")
        except ValueError:
            continue
        raise AssertionError("accepted %s=%r" % (field, bad))


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
