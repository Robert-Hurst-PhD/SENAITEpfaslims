# -*- coding: utf-8 -*-
"""How a result is written on the compact certificate.

One place for the reporting conventions the lab chose 2026-09-30:

* A non-detect prints as "< RL" with the RL value and a U qualifier
  (coa_nd_format "lt_rl"; "nd" prints "ND"; "raw" keeps the stored text).
* A numeric result below its RL always prints "< RL" with U, whatever the
  non-detect setting: values between the MDL and the RL are not reported,
  and "ND" is only for an analyte that was not detected.
  No J (estimated) flag is applied between MDL and RL: that convention was
  not chosen, and a certificate must not invent one.
* Detected values are rounded to the configured significant figures without
  switching to exponent notation, by the method x matrix rounding rule
  (rounding.py: ISO half to even; EPA / FDA half up). The RL and
  MDL are rounded the same way, so "< RL" and the RL column agree; whether a
  result is a non-detect is decided on the UNROUNDED value.
* A result with no configured RL prints as measured (or "ND" for a text
  non-detect) -- never a made-up limit.

No Zope imports: the certificate view and the tests both use this.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import math

try:                                  # in Plone
    from senaite.pfas import rounding as _rounding
except Exception:                     # tests: module loaded without the package
    import rounding as _rounding

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


def sig_figs(value, n=3, rule=_rounding.DEFAULT_RULE):
    """Round to n significant figures by `rule`, fixed notation: 30.17 ->
    '30.2', 0.18935 -> '0.189', 104.43 -> '104', 12345 -> '12300'. `value`
    may be the stored text (preferred: rounded exactly as written)."""
    return _rounding.round_sig(value, n, rule)


def format_rl(value, n=3, rule=_rounding.DEFAULT_RULE):
    """An RL / MDL on the certificate: rounded like the results."""
    if value is None:
        return ""
    return _rounding.round_sig(value, n, rule) or ""


def format_limit(value):
    """A limit prints as the lab configured it: 0.5 -> '0.5', 2.0 -> '2'."""
    if value is None:
        return ""
    return ("%.6f" % value).rstrip("0").rstrip(".") or "0"


def format_result(raw, rl=None, nd_format="lt_rl", n=3, rule=_rounding.DEFAULT_RULE):
    """{'text', 'qualifiers', 'detected'} for one result.

    raw: the stored result (number or text); rl: the configured reporting
    limit in the reporting unit, or None.
    """
    if nd_format not in ND_FORMATS:
        nd_format = "lt_rl"
    text = ("%s" % (raw if raw is not None else "")).strip()
    value = _to_float(text)
    # judged on the ROUNDED result, the value the certificate states: 1.995 at 3 significant figures is 2.00, at the RL of 2
    judged = _rounding.judged_conc(text, n, rule) if value is not None else None
    nondetect = (value is None and text.lower() in NONDETECT_TEXT) or (
        judged is not None and rl is not None and judged < rl)
    if value is None and not nondetect:
        # free text we do not recognise: print it as entered, unqualified
        return {"text": text, "qualifiers": [], "detected": None}
    if nondetect and value is not None and rl is not None:
        # a measured value below the RL: "< RL" under every setting
        return {"text": "< " + format_rl(rl, n, rule), "qualifiers": ["U"],
                "detected": False}
    if nondetect:
        if nd_format == "raw":
            return {"text": text if value is None else sig_figs(text, n, rule),
                    "qualifiers": ["U"], "detected": False}
        if nd_format == "lt_rl" and rl is not None:
            return {"text": "< " + format_rl(rl, n, rule), "qualifiers": ["U"],
                    "detected": False}
        return {"text": "ND", "qualifiers": ["U"], "detected": False}
    return {"text": sig_figs(text, n, rule), "qualifiers": [], "detected": True}


def build_rows(analyses, profile, matrix, settings, cas_by_keyword=None):
    """Certificate rows in the method's analyte order.

    analyses: [{"keyword", "title", "result", "codes": [..], "dilution"}];
    profile: the method profile; matrix: the profile's matrix title;
    settings: the print settings (coa_nd_format, coa_sig_figs).
    Analytes outside the method's master set follow, alphabetically -- a
    result is never dropped for being unexpected.
    """
    try:                                  # in Plone
        from senaite.pfas.report_limits import limits_for, scaled_rl
    except Exception:                     # tests: module loaded without the package
        from report_limits import limits_for, scaled_rl
    cas_by_keyword = cas_by_keyword or {}
    order = dict((kw, i) for i, kw in enumerate((profile or {}).get("master_analyte_set") or []))
    nd_format = (settings or {}).get("coa_nd_format") or "lt_rl"
    rule = (settings or {}).get("coa_rounding") or _rounding.DEFAULT_RULE
    try:
        n = int((settings or {}).get("coa_sig_figs") or 3)
    except (TypeError, ValueError):
        n = 3
    rows = []
    for a in analyses:
        kw = a.get("keyword") or ""
        lim = limits_for(profile, matrix, kw)
        # a diluted analyte's RL scales with the dilution (a.dilution = fold)
        rl = scaled_rl(lim["rl"], a.get("dilution"))
        res = format_result(a.get("result"), rl, nd_format, n, rule)
        quals = list(res["qualifiers"]) + [c for c in (a.get("codes") or []) if c]
        rows.append({
            "keyword": kw,
            "title": a.get("title") or kw,
            "cas": cas_by_keyword.get(kw, ""),
            "result": res["text"],
            "detected": res["detected"],
            "qualifiers": ", ".join(quals),
            "rl": format_rl(rl, n, rule),
            "mdl": format_rl(lim["mdl"], n, rule),
            "unit": lim["unit"] or "",
            "dilution": format_limit(a.get("dilution")) if a.get("dilution") else "",
            "_sort": (0, order[kw]) if kw in order else (1, (a.get("title") or kw).lower()),
        })
    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        del r["_sort"]
    return rows
