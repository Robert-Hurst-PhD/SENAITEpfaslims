# -*- coding: utf-8 -*-
"""How a result is written on the compact certificate (GAPS §50).

One place for the reporting conventions the lab chose 2026-09-30:

* A non-detect prints as "< RL" with the RL value and a U qualifier
  (coa_nd_format "lt_rl"; "nd" prints "ND"; "raw" keeps the stored text).
* A numeric result below its RL is reported as a non-detect at the RL. No J
  (estimated) flag is applied between MDL and RL: that convention was not
  chosen, and a certificate must not invent one.
* Detected values are rounded to the configured significant figures without
  switching to exponent notation.
* A result with no configured RL prints as measured (or "ND" for a text
  non-detect) -- never a made-up limit.

No Zope imports: the certificate view and the tests both use this.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import math

# Text results the pipeline and manual entry use for "not detected".
NONDETECT_TEXT = ("bloq", "lod", "<lod", "loq", "<loq", "nd", "n.d.", "bdl",
                  "<rl", "<mrl", "not detected", "u")

ND_FORMATS = ("lt_rl", "nd", "raw")


def _to_float(value):
    try:
        f = float(("%s" % value).strip())
    except (TypeError, ValueError):
        return None
    return None if (math.isinf(f) or math.isnan(f)) else f   # py2.7: no isfinite


def sig_figs(value, n=3):
    """Round to n significant figures, fixed notation: 30.17 -> '30.2',
    0.18935 -> '0.189', 104.43 -> '104', 12345 -> '12300'."""
    n = max(1, int(n))
    if value == 0:
        return "0"
    magnitude = int(math.floor(math.log10(abs(value))))
    decimals = n - 1 - magnitude
    rounded = round(value, decimals)
    if decimals <= 0:
        return "%d" % int(round(rounded))
    return "%.*f" % (decimals, rounded)


def format_limit(value):
    """A limit prints as the lab configured it: 0.5 -> '0.5', 2.0 -> '2'."""
    if value is None:
        return ""
    return ("%.6f" % value).rstrip("0").rstrip(".") or "0"


def format_result(raw, rl=None, nd_format="lt_rl", n=3):
    """{'text', 'qualifiers', 'detected'} for one result.

    raw: the stored result (number or text); rl: the configured reporting
    limit in the reporting unit, or None.
    """
    if nd_format not in ND_FORMATS:
        nd_format = "lt_rl"
    text = ("%s" % (raw if raw is not None else "")).strip()
    value = _to_float(text)
    nondetect = (value is None and text.lower() in NONDETECT_TEXT) or (
        value is not None and rl is not None and value < rl)
    if value is None and not nondetect:
        # free text we do not recognise: print it as entered, unqualified
        return {"text": text, "qualifiers": [], "detected": None}
    if nondetect:
        if nd_format == "raw":
            return {"text": text if value is None else sig_figs(value, n),
                    "qualifiers": ["U"], "detected": False}
        if nd_format == "lt_rl" and rl is not None:
            return {"text": "< " + format_limit(rl), "qualifiers": ["U"],
                    "detected": False}
        return {"text": "ND", "qualifiers": ["U"], "detected": False}
    return {"text": sig_figs(value, n), "qualifiers": [], "detected": True}


def build_rows(analyses, profile, matrix, settings, cas_by_keyword=None):
    """Certificate rows in the method's analyte order.

    analyses: [{"keyword", "title", "result", "codes": [..], "dilution"}];
    profile: the method profile; matrix: the profile's matrix title;
    settings: the print settings (coa_nd_format, coa_sig_figs).
    Analytes outside the method's master set follow, alphabetically -- a
    result is never dropped for being unexpected.
    """
    try:                                  # in Plone
        from senaite.pfas.report_limits import limits_for
    except Exception:                     # tests: module loaded without the package
        from report_limits import limits_for
    cas_by_keyword = cas_by_keyword or {}
    order = dict((kw, i) for i, kw in enumerate((profile or {}).get("master_analyte_set") or []))
    nd_format = (settings or {}).get("coa_nd_format") or "lt_rl"
    try:
        n = int((settings or {}).get("coa_sig_figs") or 3)
    except (TypeError, ValueError):
        n = 3
    rows = []
    for a in analyses:
        kw = a.get("keyword") or ""
        lim = limits_for(profile, matrix, kw)
        res = format_result(a.get("result"), lim["rl"], nd_format, n)
        quals = list(res["qualifiers"]) + [c for c in (a.get("codes") or []) if c]
        rows.append({
            "keyword": kw,
            "title": a.get("title") or kw,
            "cas": cas_by_keyword.get(kw, ""),
            "result": res["text"],
            "detected": res["detected"],
            "qualifiers": ", ".join(quals),
            "rl": format_limit(lim["rl"]),
            "mdl": format_limit(lim["mdl"]),
            "unit": lim["unit"] or "",
            "dilution": a.get("dilution") or "",
            "_sort": (0, order[kw]) if kw in order else (1, (a.get("title") or kw).lower()),
        })
    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        del r["_sort"]
    return rows
