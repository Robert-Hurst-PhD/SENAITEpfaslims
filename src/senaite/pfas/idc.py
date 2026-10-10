# -*- coding: utf-8 -*-
"""Initial demonstration of capability, EPA 537.1 v2.0 §9.2 (one study per
analyst x method; lab, 2026-10-09). Each element's verdict, from data the
system already holds where it can:

  isomers      §9.2.1  the branched-isomer peaks the method profile sets for
                       PFOA (Isomers) -- identified by the method's own setting
  lsb          §9.2.2  the LRBs of the IDC's low-system-background part pass
                       the method's blank limit (§9.3.1: < 1/3 MRL), as judged
                       on the runs
  pa           §9.2.3/4 precision and accuracy (method_studies)
  qcs          §9.2.7  the method's ICV on the IDC's runs, as judged there
                       (the QCS is the ICV: same check, the method's criterion)
  asymmetry    §9.2.5  typed for the first two eluting peaks with a PDF of
                       the calculation (§9.3.9): 0.8 - 1.5
  mrl          §9.2.6  MRL confirmation (method_studies)

Only EPA 537.1 has an IDC here; FDA and EPA 1633A wait for their criteria.
A new analyst (no approved IDC for the method) is due one; nothing else
prompts it (lab, 2026-10-09). Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

METHODS = ("EPA_537_1",)
ELEMENTS = [
    ("isomers", u"Branched / linear isomer profile (§9.2.1)"),
    ("lsb", u"Low system background (§9.2.2)"),
    ("pa", u"Precision and accuracy (§9.2.3, §9.2.4)"),
    ("qcs", u"Calibration confirmation, QCS = the ICV (§9.2.7)"),
    ("asymmetry", u"Peak asymmetry (§9.2.5)"),
    ("mrl", u"MRL confirmation (§9.2.6)"),
]
ELEMENT_LABELS = dict(ELEMENTS)
ASYMMETRY = (0.8, 1.5)          # EPA 537.1 §9.2.5, factor per the §9.3.9 equation
PASS, FAIL, OPEN = u"pass", u"fail", u"not evaluated"


def judged_rows(rows):
    """The verdict of rows the runs already judged ([{"passed": 0 | 1}])."""
    rows = list(rows or [])
    if not rows:
        return {"verdict": OPEN, "reason": u"no result yet", "n": 0}
    failed = [r for r in rows if not r.get("passed")]
    return {"verdict": FAIL if failed else PASS, "n": len(rows), "failed": len(failed)}


def isomers(profile, analyte=u"PFOA"):
    entry = ((profile or {}).get("isomers") or {}).get(analyte) or {}
    branched = [b for b in entry.get("branched") or [] if b]
    if not branched:
        return {"verdict": OPEN,
                "reason": u"no branched isomer peaks set for %s (Method Profile > Isomers)" % analyte}
    return {"verdict": PASS, "linear": entry.get("linear") or u"", "branched": branched}


def asymmetry(values, pdf_present):
    """`values` = the factors typed for the first two eluting peaks."""
    nums = []
    for v in values or []:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            pass
    if len(nums) < 2:
        return {"verdict": OPEN, "reason": u"type the factor of the first two eluting peaks"}
    if not pdf_present:
        return {"verdict": OPEN, "values": nums[:2], "reason": u"attach the calculation (PDF)"}
    lo, hi = ASYMMETRY
    ok = all(lo <= v <= hi for v in nums[:2])
    return {"verdict": PASS if ok else FAIL, "values": nums[:2], "window": [lo, hi]}


def per_analyte(results):
    """One verdict from {keyword: {"verdict"}} (precision and accuracy, MRL):
    every analyte passes; one not evaluated leaves it open."""
    verdicts = [r.get("verdict") for r in (results or {}).values()]
    if not verdicts:
        return {"verdict": OPEN, "reason": u"no replicates yet"}
    if FAIL in verdicts:
        return {"verdict": FAIL, "failed": sorted(k for k, r in results.items() if r.get("verdict") == FAIL)}
    if any(v != PASS for v in verdicts):
        return {"verdict": OPEN, "reason": u"some analytes are not evaluated"}
    return {"verdict": PASS}


def overall(elements):
    """{element: result} -> pass only when every element passes."""
    vs = [(elements.get(k) or {}).get("verdict") for k, _l in ELEMENTS]
    if FAIL in vs:
        return FAIL
    return PASS if all(v == PASS for v in vs) else OPEN


def due(analysts, records, method):
    """[(user id, name)] of `analysts` with no approved IDC for `method`."""
    done = set(r.get("analyst") for r in records or []
               if r.get("kind") == "idc" and r.get("method") == method and r.get("status") == u"approved")
    return [(uid, name) for uid, name in analysts or [] if uid not in done]
