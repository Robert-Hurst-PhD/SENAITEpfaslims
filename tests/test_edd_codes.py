# -*- coding: utf-8 -*-
"""EDD identifiers (Maine EGAD), checked against the rules that can be checked
offline (DECISIONS 2026-10-01).

* Every CAS in the analyte master table carries a valid check digit -- PFMBA
  was held as 863090-85-5 (invalid; Maine EGAD CAS_LUP and the check digit
  both give 863090-89-5).
* No analyte exports with a blank EGAD parameter name; the summed PFOS/PFHxS
  export under the plain-acid entries Maine lists (1763231 PFOS_A, 355464
  PFHXS_A), never the -LINEAR codes.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "senaite", "pfas"))

import analyte_reference as ar   # noqa: E402


def _cas_ok(cas):
    digits = cas.replace("-", "")
    body, check = digits[:-1], int(digits[-1])
    return sum(int(c) * (i + 1) for i, c in enumerate(reversed(body))) % 10 == check


def test_every_master_cas_has_a_valid_check_digit():
    bad = [(r[0], r[2]) for r in ar.NATIVE_ANALYTES
           if re.match(r"^\d{2,7}-\d{2}-\d$", r[2] or "") and not _cas_ok(r[2])]
    assert not bad, bad


def _overlay():
    """The EGAD overlay, read without importing the Plone package."""
    with open(os.path.join(ROOT, "src", "senaite", "pfas", "egad_store.py")) as fh:
        body = fh.read()
    start = body.index("_EGAD_ANALYTE_OVERLAY = {")
    end = body.index("\n}\n", start)
    return eval(body[start + len("_EGAD_ANALYTE_OVERLAY = "):end + 2])   # a literal dict


def test_no_blank_parameter_names_and_the_summed_acids():
    ov = _overlay()
    natives = [r[0] for r in ar.NATIVE_ANALYTES if not r[0].startswith("br-")]
    missing = [kw for kw in natives if not (ov.get(kw) or {}).get("parameter_name")]
    assert not missing, "no EGAD parameter name for %s" % missing
    assert ov["PFOS"]["parameter_name"] == "PFOS_A" and "cas_override" not in ov["PFOS"]
    assert ov["PFHxS"]["parameter_name"] == "PFHXS_A" and "cas_override" not in ov["PFHxS"]
    cas = dict((r[0], r[2]) for r in ar.NATIVE_ANALYTES)
    assert cas["PFOS"] == "1763-23-1" and cas["PFHxS"] == "355-46-4"


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
