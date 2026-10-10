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

A method has an IDC when its profile holds an IDC spec (method_engine
.idc_spec): {"elements": [[key, label], ...], "asymmetry": [low, high]}.
The elements are chosen from the ones this module can judge (EVALUATED).
A new analyst (no approved IDC for the method) is due one; nothing else
prompts it. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# the elements this module can judge (the view computes each one)
EVALUATED = ("isomers", "lsb", "pa", "qcs", "asymmetry", "mrl")

PASS, FAIL, OPEN = u"pass", u"fail", u"not evaluated"


def spec_elements(spec):
    """[(key, label)] of a spec's elements ([key, label] pairs or
    {"key", "label"} dicts)."""
    out = []
    for el in (spec or {}).get("elements") or []:
        if isinstance(el, dict):
            key, label = el.get("key"), el.get("label")
        elif isinstance(el, (list, tuple)) and el:
            key, label = el[0], (el[1] if len(el) > 1 else None)
        else:
            key, label = el, None
        if key:
            out.append((key, label or key))
    return out


def spec_asymmetry(spec):
    """(low, high) from a spec ([low, high] or {"min", "max"}), else None."""
    raw = (spec or {}).get("asymmetry")
    if isinstance(raw, dict):
        raw = (raw.get("min"), raw.get("max"))
    try:
        lo, hi = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (lo, hi)


def not_evaluated(key):
    return {"verdict": OPEN, "reason": u"no evaluation for the element %s" % key}


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


def asymmetry(values, pdf_present, window=None):
    """`values` = the factors typed for the first two eluting peaks;
    `window` = the spec's (low, high)."""
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
    if window is None:
        return {"verdict": OPEN, "values": nums[:2],
                "reason": u"the method profile sets no asymmetry window"}
    lo, hi = window
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


def overall(elements, keys):
    """{element: result} -> pass only when every element of `keys` (the
    spec's, or an approved record's) passes."""
    keys = list(keys or [])
    if not keys:
        return OPEN
    vs = [(elements.get(k) or {}).get("verdict") for k in keys]
    if FAIL in vs:
        return FAIL
    return PASS if all(v == PASS for v in vs) else OPEN


def due(analysts, records, method):
    """[(user id, name)] of `analysts` with no approved IDC for `method`."""
    done = set(r.get("analyst") for r in records or []
               if r.get("kind") == "idc" and r.get("method") == method and r.get("status") == u"approved")
    return [(uid, name) for uid, name in analysts or [] if uid not in done]
