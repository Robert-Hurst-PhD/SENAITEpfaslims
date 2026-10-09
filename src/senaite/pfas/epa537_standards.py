# -*- coding: utf-8 -*-
"""EPA 537.1's labelled standards, seeded once into its method profile.


Source: EPA Method 537.1 Version 2.0, EPA/600/R-20/006 (March 2020):
  §7.2.1   internal standards 13C2-PFOA (IS#1), 13C4-PFOS (IS#2),
           d3-NMeFOSAA (IS#3)
  §7.2.2   surrogates 13C2-PFHxA, 13C3-HFPO-DA, 13C2-PFDA, d5-NEtFOSAA
  Table 3  each analyte's and surrogate's IS# reference
  §9.3.5.3 a surrogate failing on re-extraction: "report all data for that
           sample as suspect/SUR recovery" -> the whole sample is qualified

The profile held EPA 1633A's set (13C5-PFHxA, 13C8-PFOA... with 13C4-PFOA as
the only injection standard), so two of the method's three internal
standards were never judged (synthetic runs). Seeded ONCE and
marked, so an edit the lab makes afterwards is never overwritten.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

VERSION_KEY = "labelled_standards_537_v"

IS1, IS2, IS3 = "13C2-PFOA", "13C4-PFOS", "D3-NMeFOSAA"

# keyword -> its IS (Table 3); natives by the library's keywords
NATIVE_IS = {
    "PFBS": IS2, "PFHxA": IS1, "GenX": IS1, "PFHpA": IS1, "PFHxS": IS2,
    "DONA": IS1, "PFOA": IS1, "PFOS": IS2, "PFNA": IS1, "9ClPF3ONS": IS2,
    "PFDA": IS1, "NMeFOSAA": IS3, "PFUDA": IS1, "NEtFOSAA": IS3,
    "11ClPF3OUdS": IS2, "PFDoA": IS1, "PFTrDA": IS1, "PFTeDA": IS1,
}
SURROGATE_IS = {
    "13C2-PFHxA": IS1, "13C3-HFPO-DA": IS1, "13C2-PFDA": IS1, "D5-NEtFOSAA": IS3,
}


QCS_KEY = "qcs_criteria_537_v"


def seed_qcs(profile, method_id):
    """Once, for EPA 537.1: the QCS judged with the CCC's window (§9.3.10)
    and surrogate recovery judged in CCCs (§9.3.5.1).
    The ICV's own % deviation (carried over from the old rules file) goes:
    the CCC window replaces it."""
    if method_id != "EPA_537_1" or profile.get(QCS_KEY) == 1:
        return False
    iv = profile.setdefault("instrument_verification", {})
    icv = iv.setdefault("icv", {})
    icv["criteria"] = "ccv"
    icv.pop("pct_dev_max", None)
    iv.setdefault("ccv", {})["surrogate_recovery"] = "yes"
    profile[QCS_KEY] = 1
    return True


BRACKET_RPD_KEY = "bracket_rpd_537_v"


def seed_bracket_rpd(profile, method_id):
    """Once, for EPA 537.1: a CCC opens the run (§10.3) and the LFSMD RPD is
    of the measured concentrations (§9.3.7.3). Per method: FDA and EPA 1633A
    keep their earlier behaviour until the lab says."""
    if method_id != "EPA_537_1" or profile.get(BRACKET_RPD_KEY) == 1:
        return False
    iv = profile.setdefault("instrument_verification", {})
    iv.setdefault("ccv", {})["opens_run"] = "yes"
    profile["lfsmd_rpd_basis"] = "concentration"
    profile[BRACKET_RPD_KEY] = 1
    return True


EXTRACT_HT_KEY = "extract_holding_537_v"


def seed_extract_holding(profile, method_id):
    """Once, for EPA 537.1: extracts analysed within 28 days of extraction
    (§8.5), for each of its matrices."""
    if method_id != "EPA_537_1" or profile.get(EXTRACT_HT_KEY) == 1:
        return False
    ext = profile.setdefault("extract_holding_times", {})
    for m in profile.get("supported_matrices") or []:
        ext.setdefault(m, 28)
    profile[EXTRACT_HT_KEY] = 1
    return True


def grid():
    out = dict((kw, {"role": "injection_is", "reference": ""}) for kw in (IS1, IS2, IS3))
    for kw, ref in SURROGATE_IS.items():
        out[kw] = {"role": "surrogate", "reference": ref}
    return out


def seed(profile, method_id):
    """Once, for EPA 537.1: the grid, each native's quantifying IS and the
    whole-sample surrogate scope. True if the profile changed."""
    if method_id != "EPA_537_1" or profile.get(VERSION_KEY) == 1:
        return False
    profile["labelled_standards"] = grid()
    panel = set(profile.get("master_analyte_set") or NATIVE_IS)
    profile["surrogate_map"] = [{"analyte": kw, "surrogate_is": NATIVE_IS[kw]}
                                for kw in sorted(NATIVE_IS) if kw in panel]
    profile["surrogate_failure_scope"] = "sample"
    profile[VERSION_KEY] = 1
    return True
