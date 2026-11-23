# -*- coding: utf-8 -*-
"""How a result is written on the certificate.

One place for the reporting conventions the lab chose:

* A non-detect prints as "< RL" with the RL value and a U qualifier
  (coa_nd_format "lt_rl"; "nd" prints "ND"; "raw" keeps the stored text).
* A numeric result at or above the MDL and below the RL prints its value,
  rounded like any result, with J (estimated): the method x matrix setting
  coa_between_mdl_rl "j", the default. With "lt_rl" it prints "< RL" with U.
  Below the MDL it prints "< RL" with U whatever the non-detect setting, and
  "ND" is only for an analyte that was not detected. With no MDL set no J is
  possible: below the RL is "< RL" with U.
* A result from a dilution retest (fold above 1) carries D (rule
  coa_dilution_code); its RL and its MDL are the method's times the fold,
  printed so and used so for the J decision (rule coa_mdl_dilution). Both
  rules are "yes" unless an issued revision records otherwise.
* Detected values are rounded to the configured significant figures without
  switching to exponent notation, by the method x matrix rounding rule
  (rounding.py: ISO half to even; EPA / FDA half up). The RL and
  MDL are rounded the same way, so "< RL" and the RL column agree; whether a
  result is below the RL or the MDL is decided on the ROUNDED value, the
  value the certificate states.
* A result with no configured RL prints as measured (or "ND" for a text
  non-detect): never a made-up limit.
* A result not quantified (N.Q.: its isotope standard's peak deleted) prints
  so with its own code, never as a non-detect.
* A result above the calibration range reported from no dilution (its
  Result ALoQ) is never printed extrapolated: it prints "> " and the top of
  the range on the sample basis (above_range's limit) with E, rounded like
  the RL; a detection. Its reading stays on the record and in Data Review.

No Zope imports: the certificate view and the tests both use this.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import math

from senaite.pfas import rounding as _rounding

# Text results the pipeline and manual entry use for "not detected".
NONDETECT_TEXT = ("bloq", "lod", "<lod", "loq", "<loq", "nd", "n.d.", "bdl",
                  "<rl", "<mrl", "not detected", "u")

ND_FORMATS = ("lt_rl", "nd", "raw")
# coa_between_mdl_rl: a value at or above the MDL and below the RL prints
# with J ("j") or as "< RL" with U ("lt_rl")
BETWEEN_FORMATS = ("j", "lt_rl")
J_CODE = "J"            # estimated: at or above the MDL, below the RL
D_CODE = "D"            # reported from a diluted extract
# not quantified: a native whose isotope standard's peak was deleted, neither
# detected nor not detected; its text prints as stored and its code goes with it
NQ_CODE = "N.Q."
NOT_QUANTIFIED_TEXT = ("n.q.",)
# above the calibration range with no dilution: "> the top of the range"
E_CODE = "E"
ABOVE_RANGE_TEXT = ("aloq",)


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


def _fold(value):
    f = _to_float(value)
    return f if f is not None and f > 1 else None


def format_result(raw, rl=None, nd_format="lt_rl", n=3, rule=_rounding.DEFAULT_RULE,
                  mdl=None, between="j", fold=None, above=None):
    """{'text', 'qualifiers', 'detected'} for one result.

    raw: the stored result (number or text); rl: the configured reporting
    limit in the reporting unit (already scaled by any dilution), or None;
    mdl: the method detection limit, or None; between: coa_between_mdl_rl;
    fold: the dilution's total fold, or None; above: the top of the
    calibration range on the sample basis of a result written ALoQ, or None.
    A J value is detected, and so is an E one.
    """
    if nd_format not in ND_FORMATS:
        nd_format = "lt_rl"
    if between not in BETWEEN_FORMATS:
        between = "j"
    mdl = _to_float(mdl)
    tail = [D_CODE] if _fold(fold) is not None else []
    text = ("%s" % (raw if raw is not None else "")).strip()
    value = _to_float(text)
    # judged on the ROUNDED result, the value the certificate states: 1.995
    # at 3 significant figures is 2.00, at the RL of 2
    judged = _rounding.judged_conc(text, n, rule) if value is not None else None
    nondetect = (value is None and text.lower() in NONDETECT_TEXT) or (
        judged is not None and rl is not None and judged < rl)
    if value is None and text.lower() in NOT_QUANTIFIED_TEXT:
        return {"text": NQ_CODE, "qualifiers": [NQ_CODE] + tail, "detected": None}
    if value is None and text.lower() in ABOVE_RANGE_TEXT:
        # never the extrapolated reading: above the top of the range, with E
        top = _to_float(above)
        return {"text": ("> " + format_rl(top, n, rule)) if top is not None else text,
                "qualifiers": [E_CODE] + tail, "detected": True}
    if value is None and not nondetect:
        # free text we do not recognise: print it as entered, unqualified
        return {"text": text, "qualifiers": [], "detected": None}
    if nondetect and value is not None and rl is not None:
        if between == "j" and mdl is not None and judged >= mdl:
            # at or above the MDL, below the RL: the value, estimated
            return {"text": sig_figs(text, n, rule), "qualifiers": [J_CODE] + tail,
                    "detected": True}
        # below the MDL, or no MDL, or the format reports "< RL": "< RL"
        # under every non-detect setting
        return {"text": "< " + format_rl(rl, n, rule), "qualifiers": ["U"] + tail,
                "detected": False}
    if nondetect:
        if nd_format == "raw":
            return {"text": text if value is None else sig_figs(text, n, rule),
                    "qualifiers": ["U"] + tail, "detected": False}
        if nd_format == "lt_rl" and rl is not None:
            return {"text": "< " + format_rl(rl, n, rule), "qualifiers": ["U"] + tail,
                    "detected": False}
        return {"text": "ND", "qualifiers": ["U"] + tail, "detected": False}
    return {"text": sig_figs(text, n, rule), "qualifiers": tail, "detected": True}


def format_params(settings):
    """(nd_format, n, rule) the certificate prints with, from its print
    settings merged with the method x matrix report format."""
    nd_format = (settings or {}).get("coa_nd_format") or "lt_rl"
    rule = (settings or {}).get("coa_rounding") or _rounding.DEFAULT_RULE
    try:
        n = int((settings or {}).get("coa_sig_figs") or 3)
    except (TypeError, ValueError):
        n = 3
    return nd_format, n, rule


def between_format(settings):
    """coa_between_mdl_rl of the certificate's settings ("j" by default)."""
    value = (settings or {}).get("coa_between_mdl_rl") or "j"
    return value if value in BETWEEN_FORMATS else "j"


def format_for_settings(raw, rl, settings, mdl=None, fold=None, above=None):
    """format_result under exactly the certificate's settings."""
    nd_format, n, rule = format_params(settings)
    return format_result(raw, rl, nd_format, n, rule, mdl=mdl,
                         between=between_format(settings), fold=fold, above=above)


def build_rows(analyses, profile, matrix, settings, cas_by_keyword=None):
    """Certificate rows in the method's analyte order.

    analyses: [{"keyword", "title", "result", "codes": [..], "dilution",
    "frozen_rl": the RL kept at verification (verified_rl), or None,
    "acid_basis": True where its run's standards state it as the acid,
    "above": the top of the calibration range of a result written ALoQ}];
    profile: the method profile; matrix: the profile's matrix title;
    settings: the print settings merged with the method x matrix format
    (coa_nd_format, coa_sig_figs, coa_rounding, coa_between_mdl_rl).
    Analytes outside the method's master set follow, alphabetically: a
    result is never dropped for being unexpected. "estimated" marks a J
    value (detected, below the RL); "rule_codes" are the codes the reporting
    rules gave (U, J, D) and "qc_codes" the QC qualifications (carried_codes),
    kept apart so the EDD can tell the rule's D from a lab code D. An
    analysis' "statements" ({code: [the lab's wording]}) stay on its row as
    "qc_statements", and its "separate" (the codes whose wordings print
    apart) as "qc_separate": the qualification text is read from the rows
    (qualifications).
    """
    from senaite.pfas.report_limits import limits_with_frozen, scaled_rl
    cas_by_keyword = cas_by_keyword or {}
    order = dict((kw, i) for i, kw in enumerate((profile or {}).get("master_analyte_set") or []))
    nd_format, n, rule = format_params(settings)
    between = between_format(settings)
    mdl_scales = (settings or {}).get("coa_mdl_dilution", "yes") != "no"
    d_code = (settings or {}).get("coa_dilution_code", "yes") != "no"
    rows = []
    for a in analyses:
        kw = a.get("keyword") or ""
        # a verified result prints the RL frozen at its verification; else
        # the default, with no salt factor where its run's standards state
        # it as the acid (a.acid_basis)
        lim = limits_with_frozen(profile, matrix, kw, a.get("frozen_rl"),
                                 acid_basis=[kw] if a.get("acid_basis") else None)
        # a diluted analyte's RL scales with the dilution (a.dilution = fold)
        rl = scaled_rl(lim["rl"], a.get("dilution"))
        # and its MDL, as the RL
        mdl = scaled_rl(lim["mdl"], a.get("dilution")) if mdl_scales else lim["mdl"]
        res = format_result(a.get("result"), rl, nd_format, n, rule, mdl=mdl,
                            between=between, fold=a.get("dilution") if d_code else None,
                            above=a.get("above"))
        qc = [c for c in (a.get("codes") or []) if c]
        quals = list(res["qualifiers"]) + [c for c in qc if c not in res["qualifiers"]]
        rows.append({
            "keyword": kw,
            "title": a.get("title") or kw,
            "cas": cas_by_keyword.get(kw, ""),
            "result": res["text"],
            "detected": res["detected"],
            "estimated": J_CODE in res["qualifiers"],
            "qualifiers": ", ".join(quals),
            "rule_codes": list(res["qualifiers"]),
            "qc_codes": qc,
            "qc_statements": dict((c, [t for t in (a.get("statements") or {}).get(c) or [] if t])
                                  for c in qc),
            "qc_separate": [c for c in a.get("separate") or [] if c in qc],
            "rl": format_rl(rl, n, rule),
            "mdl": format_rl(mdl, n, rule),
            "unit": lim["unit"] or "",
            "dilution": format_limit(a.get("dilution")) if a.get("dilution") else "",
            "_sort": (0, order[kw]) if kw in order else (1, (a.get("title") or kw).lower()),
        })
    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        del r["_sort"]
    return rows


def carried_codes(stamped, planned):
    """The QC codes one result prints: those stamped on it at release, then
    those the worksheet's quality control puts on it now, each once. A
    result drawn before release carries its codes, and a stamped code stays
    when the summary no longer lists it."""
    out = []
    for code in list(stamped or []) + list(planned or []):
        if code and code not in out:
            out.append(code)
    return out


def qc_codes(rows):
    """Every QC code the rows carry, sorted."""
    return sorted(set(c for r in rows or [] for c in r.get("qc_codes") or []))


# "Affected analytes:" when every row carries the code
ALL_ANALYTES = "all"


def qualifications(rows):
    """[{"code", "statement", "analytes"}]: the qualification text's lines,
    read from the rows themselves, so the text names a code for exactly the
    rows that print it. One line per code, with the first wording the rows
    give it; a code a row marks separate (qc_separate: its wording names
    what failed) prints one line per wording, each with its own results.
    Ordered by code; the analytes are the rows' reported names in row
    order, or ALL_ANALYTES when every row carries the line. A code with no
    wording is still listed."""
    rows = rows or []
    separate = set(c for r in rows for c in r.get("qc_separate") or [])
    grouped, order = {}, []
    for r in rows:
        for code in r.get("qc_codes") or []:
            statements = [t for t in (r.get("qc_statements") or {}).get(code) or [] if t]
            for statement in (statements or [""]) if code in separate else [""]:
                key = (code, statement)
                if key not in grouped:
                    grouped[key] = {"names": [], "statement": statement}
                    order.append(key)
                line = grouped[key]
                if not line["statement"] and statements:
                    line["statement"] = statements[0]
                if r.get("title") not in line["names"]:
                    line["names"].append(r.get("title"))
    out = []
    for key in sorted(order):
        line = grouped[key]
        whole = len(rows) > 1 and len(line["names"]) == len(rows)
        out.append({"code": key[0], "statement": line["statement"],
                    "analytes": ALL_ANALYTES if whole else ", ".join(n or "" for n in line["names"])})
    return out


def library_statement(library, code):
    """The QC Qualifiers library's wording for a code, when the library
    gives that code exactly one wording; "" when it gives none or several
    (a failure type is never asserted from the letter alone)."""
    found = set((entry or {}).get("statement") or "" for entry in (library or {}).values()
                if code and isinstance(entry, dict) and entry.get("code") == code)
    found.discard("")
    return found.pop() if len(found) == 1 else ""


def rule_codes(rows, wording):
    """[{"code", "line"}] for the legend: J, D, N.Q. and E, in that order,
    when a row carries the rule, each with the lab's wording ({code:
    statement}). Read from the rule itself (a J value; the D the dilution
    rule gave, the N.Q. of a result not quantified and the E of a result
    above the calibration range, its rule_codes), never from the qualifier
    text: a QC qualification may stamp the same letter for another reason."""
    carried = set()
    for r in rows or []:
        if r.get("estimated"):
            carried.add(J_CODE)
        for code in (D_CODE, NQ_CODE, E_CODE):
            if code in (r.get("rule_codes") or []):
                carried.add(code)
    out = []
    for code in (J_CODE, D_CODE, NQ_CODE, E_CODE):
        text = ((wording or {}).get(code) or "").strip()
        if code in carried and text:
            out.append({"code": code, "line": "%s = %s." % (code, text.rstrip("."))})
    return out


# the legend line of a code the batch or report carries (rule_flags, place
# "batch"): printed once for the report, so its line says what it covers
BATCH_LEGEND = "Applies to every result on this certificate."
# a code on the page with no wording in QC Qualifiers
NO_WORDING = "see Quality control qualifications"
# the codes the legend's fixed lines explain (U), never a line of their own
FIXED_LEGEND_CODES = ("U",)


def legend_lines(rows, wording, batch=None):
    """[{"code", "line"}]: the legend, one line per code the page carries,
    in code order, "CODE = wording.": the reporting rules' J, D, N.Q. and E
    when a row carries the rule (read from the rule, as rule_codes), every
    QC code a row carries, and each code the batch or report carries
    (`batch` [(code, wording)], its line saying it covers every result).
    The wording is the lab's: the rule's ({code: statement}), the rows' own
    statements, the batch's; several are joined. A code not on the page
    adds nothing."""
    said, order = {}, []

    def add(code, text):
        code = (code or "").strip()
        if not code or code in FIXED_LEGEND_CODES:
            return
        if code not in said:
            said[code] = []
            order.append(code)
        text = (text or "").strip().rstrip(".").strip()
        if text and text not in said[code]:
            said[code].append(text)
    for r in rows or []:
        if r.get("estimated"):
            add(J_CODE, (wording or {}).get(J_CODE))
        for code in (D_CODE, NQ_CODE, E_CODE):
            if code in (r.get("rule_codes") or []):
                add(code, (wording or {}).get(code))
    for r in rows or []:
        for code in r.get("qc_codes") or []:
            texts = [t for t in (r.get("qc_statements") or {}).get(code) or [] if t] or [""]
            for t in texts:
                add(code, t)
    whole = []
    for code, text in batch or []:
        add(code, text)
        if code not in whole:
            whole.append(code)
    out = []
    for code in sorted(order, key=lambda c: (c.lower(), c)):
        line = "%s = %s." % (code, "; ".join(said[code]) if said[code] else NO_WORDING)
        if code in whole:
            line += " " + BATCH_LEGEND
        out.append({"code": code, "line": line})
    return out
