# -*- coding: utf-8 -*-
"""Analysis Specifications grouped for reading (GAPS §96).

spec_sync writes one SENAITE AnalysisSpec per method x QC type x matrix -- so
the core list repeats the same recovery windows once per matrix (lab,
2026-10-03: "grouped together rather than repeated ... per matrix"). This
groups them back: matrices whose ranges are identical share one row, and a
row lists each distinct window once with the analytes it applies to.

    group(entries) -> [{"matrices", "specs", "windows"}]
        entries: [{"matrix", "url", "rows"}]   rows = a spec's ResultsRange
        windows: [{"min", "max", "text", "analytes"}]   widest share first

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas.spec_sync import same_ranges
except ImportError:                          # tests: modules on sys.path
    from spec_sync import same_ranges


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v):
    if v is None:
        return u"?"
    return (u"%d" % v) if v == int(v) else (u"%g" % v)


def windows(rows):
    """Distinct (min, max) windows in one spec, each with its analytes; the
    window most analytes share comes first."""
    by = {}
    order = []
    for r in rows or []:
        w = (_num(r.get("min")), _num(r.get("max")))
        if w not in by:
            by[w] = []
            order.append(w)
        by[w].append(r.get("keyword") or u"")
    order.sort(key=lambda w: -len(by[w]))
    return [{"min": w[0], "max": w[1], "analytes": sorted(by[w]),
             "text": u"%s–%s %%" % (_fmt(w[0]), _fmt(w[1]))} for w in order]


def group(entries):
    """Matrices with identical ranges together, in first-seen order."""
    out = []
    for e in entries or []:
        for g in out:
            if same_ranges(g["_rows"], e.get("rows")):
                g["matrices"].append(e["matrix"])
                g["specs"].append({"matrix": e["matrix"], "url": e.get("url")})
                break
        else:
            out.append({"_rows": e.get("rows") or [], "matrices": [e["matrix"]],
                        "specs": [{"matrix": e["matrix"], "url": e.get("url")}],
                        "windows": windows(e.get("rows"))})
    for g in out:
        del g["_rows"]
    return out
