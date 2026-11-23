"""Value provenance: every judged value records what it was computed from.

A record names the value, the formula it came from, each
term with its value and its SOURCE (an imported row's cell by file and line,
a profile criterion by key, the extraction record, another recorded value),
the steps of a chain (the final sample value) and the rule with its verdict.
Data Review opens a value's record in a drawer and lights the imported rows
and the terms that made it; the records are the run's own, taken from the
same objects the checks judged, in the same process, before anything is
pushed. Nothing here changes a value.

Keys: "<kind>|<injection>|<analyte>", the same string a qc_results or
injection_results row carries in prov_key. Kinds: IS, RT, ION, CAL, CCV, ICV,
SUR, LFSM, LFSMD, LFSMD_REC, BLANK, LFB, LCS, DUP, RESULT, ID (a reviewer's
identity correction the run was judged with), EA (an extraction correction
the run was judged with) and "row" for an imported row
itself. A QC result's key and record name the analyte by its
keyword, as qc_results stores it (qc_analyte); the kinds a page opens from
an injection row (AS_RECORDED) keep the row's own name.

Python 3 (worker).
"""
from __future__ import annotations

import json
from datetime import datetime

from .models import reported_conc


# the kinds whose record a page opens by an injection row's own analyte name
# (Data Review builds RESULT / RT / ION keys from the row); every other kind
# is a QC result, keyed by the analyte's keyword as qc_results stores it
AS_RECORDED = frozenset(["RESULT", "RT", "ION", "SUR", "RUN", "row"])


def qc_analyte(name):
    """The name a QC result is stored and keyed under: the analyte's keyword
    (analyte_alias.keyword_for); an isomer peak (lr- / br-) keeps its own
    name, as it is reviewed, never reported as its summed analyte."""
    if not name:
        return name
    from .addon import load
    if load("isomers").is_peak_name(name):
        return name
    from .analyte_alias import keyword_for
    return keyword_for(name) or name


def _analyte_of(kind, analyte):
    return analyte if kind in AS_RECORDED else qc_analyte(analyte)


def key(kind, injection, analyte):
    return "%s|%s|%s" % (kind, injection or "", _analyte_of(kind, analyte) or "")


def term(symbol, label, value, unit="", source=None):
    return {"symbol": symbol, "label": label, "value": value, "unit": unit or "",
            "source": source or {}}


def peak_text(peak):
    """A raw row's peak as one line: where it was integrated, over which
    baseline, its area and how it was measured, and the settings."""
    rev = "(settings %s)" % (peak.get("settings_revision") or "not recorded")
    lo, hi = (peak.get("window") or [None, None])[:2]
    if peak.get("area") is None:
        sn = peak.get("sn")
        return "no peak in %.2f–%.2f min%s %s" % (
            lo, hi, " (signal-to-noise %.1f)" % sn if isinstance(sn, (int, float)) else "", rev)
    b0, b1 = peak.get("base_start"), peak.get("base_end")
    base = ("a flat baseline at {0:,.0f}".format(b0) if b0 == b1
            else "a straight baseline from {0:,.0f} to {1:,.0f}".format(b0, b1))
    return "apex %.2f min; integrated %.2f–%.2f min over %s; area %s by %s %s" % (
        peak["apex"], peak["start"], peak["end"], base, "{0:,.0f}".format(peak["area"]),
        peak.get("area_method") or "", rev)


def raw_terms(row):
    """(terms, steps) of a value the LIMS calculated from raw data: the
    peak's area over its labelled standard's, read on this run's curve;
    ([], []) for an imported value."""
    derived = getattr(row, "derived_from", "") or ""
    if not derived.startswith("raw:"):
        return [], []
    quant = (json.loads(derived[len("raw:"):]) or {}).get("quant") or {}
    curve = quant.get("curve") or {}
    if curve.get("quadratic") and quant.get("ratio") is not None:
        return _quadratic_terms(row, quant, curve)
    if quant.get("ratio") is None or not curve.get("slope"):
        return [], []
    terms = _area_terms(row, quant)
    terms += [
             term("m", "slope of this run's curve (%s, %s, origin %s, r² %s)" % (
                 curve.get("kind"), curve.get("weighting"), curve.get("origin"), curve.get("r2")),
                 curve.get("slope"), "", {"computed": True}),
             term("b", "intercept of this run's curve", curve.get("intercept"), "", {"computed": True})]
    steps = _mean_steps(quant) + [
             _ratio_step(quant),
             {"label": "read on this run's curve", "expression": "(R − b) ÷ m",
              "value": (quant["ratio"] - (curve.get("intercept") or 0.0)) / curve["slope"]}]
    return terms, steps


def _members(quant):
    return [m for m in quant.get("members") or [] if isinstance(m, dict)]


def _area_terms(row, quant):
    """The peak's area and its standard's: a composite names each member's
    area in this injection, then their mean (the members are stored with the
    record, so it names them after the composite is edited or removed).
    Under the linked response ratio the standard is the surrogate (A_sur)
    and the internal standard it is linked to gives A_IS."""
    members = _members(quant)
    linked = quant.get("linked") or {}
    std = "A_sur" if linked else "A_IS"
    terms = [term("A", "area of the peak", getattr(row, "response", None), "counts", src_row(row, "response"))]
    if members:
        terms += [term("A_%d" % (i + 1), "area of %s" % (m.get("kw") or ""), m.get("area"), "counts",
                       {"computed": True}) for i, m in enumerate(members)]
        terms.append(term(std, "mean of its members' areas, %s" % _mean_of(m.get("kw") for m in members),
                          quant.get("is_area"), "counts", {"computed": True}))
    else:
        terms.append(term(std, "area of %s, its labelled standard" % (quant.get("is") or ""),
                          quant.get("is_area"), "counts", {"computed": True}))
    if linked:
        terms.append(term("A_IS", "area of %s, the internal standard %s is linked to" % (
            linked.get("is") or "", quant.get("is") or ""), linked.get("is_area"), "counts", {"computed": True}))
    return terms


def _ratio_step(quant):
    """R = A / A_IS, or, linked, R = A x A_IS / A_sur: C_sur and C_IS are one
    level in every injection, so they fold into the curve's slope."""
    if quant.get("linked"):
        return {"label": "linked response ratio (C_sur ÷ C_IS, one level in every injection, is in the slope)",
                "expression": "R = A × A_IS ÷ A_sur", "value": quant.get("ratio")}
    return {"label": "response ratio", "expression": "R = A ÷ A_IS", "value": quant.get("ratio")}


def _mean_steps(quant):
    """A composite's mean of its members' areas, as the first step."""
    members = _members(quant)
    if not members:
        return []
    return [{"label": "mean of the members' areas",
             "expression": "%s = (%s) ÷ %d" % ("A_sur" if quant.get("linked") else "A_IS",
                                                " + ".join("A_%d" % (i + 1) for i in range(len(members))),
                                                  len(members)),
             "value": quant.get("is_area")}]


def _quant_of(row):
    derived = getattr(row, "derived_from", "") or "" if row is not None else ""
    if not derived.startswith("raw:"):
        return {}
    return (json.loads(derived[len("raw:"):]) or {}).get("quant") or {}


def _sur_name(kw):
    """A labelled standard's name as its rows (and its SUR record) carry it."""
    try:
        from .analyte_alias import labelled_display_name
        return labelled_display_name(kw) or kw
    except Exception:                                       # noqa: BLE001
        return kw


SPIKED_FROM = {"spiked_conc": "the amount the run record states was added",
               "expected_conc": "the check standard's stated concentration",
               "calibrators": "the calibrators' level of it, the level every sample is spiked to"}
def recovery_terms(row):
    """(terms, steps) of a raw labelled standard's recovery on the standard
    it is linked to: the found amount's own readout (raw_terms), then
    R = C_found / C_spiked x 100; ([], []) when the row has none."""
    quant = _quant_of(row)
    rec = quant.get("recovery") or {}
    if rec.get("pct") is None:
        return [], []
    terms, steps = raw_terms(row)
    if quant.get("salt"):
        # both amounts are the acid form: the stated ones times the factor
        terms = terms + [term("f_salt", "salt factor of %s: its stated amounts as acid, found and spiked alike"
                              % (getattr(row, "compound_name", "") or ""), quant.get("salt"), "",
                              {"computed": True})]
    terms = terms + [
        term("C_found", "amount found on %s, its internal standard" % (rec.get("is") or ""), rec.get("found"),
             getattr(row, "conc_units", "") or "", {"computed": True}),
        term("C_spiked", SPIKED_FROM.get(rec.get("from"), "amount added"), rec.get("spiked"),
             getattr(row, "conc_units", "") or "", {"run_record": "injections[%s].%s" % (
                 getattr(row, "injection_name", "") or "", rec.get("from") or "")})]
    steps = steps + [{"label": "recovery on %s" % (rec.get("is") or "its internal standard"),
                      "expression": "R = C_found ÷ C_spiked × 100", "value": rec.get("pct")}]
    return terms, steps


def linked_terms(row):
    """(terms, steps) naming how a native was quantified: on its injection
    standard (no linked ratio applies), or on a surrogate with the method's
    linked response ratio, on or off; an export's number is the
    instrument's and the LIMS recomputes nothing; a raw result whose linked
    ratio could not be formed is held, saying why."""
    of = getattr(row, "quantified_on", None) or {}
    mode = getattr(row, "linked_ratio", "") or ""
    if of.get("role") == "injection_is":
        return [term("LRR", "quantified on %s, its injection standard: no linked response ratio applies"
                     % of.get("standard"), None, "", {"computed": True})], []
    if not mode:
        return [], []
    raw = (getattr(row, "derived_from", "") or "").startswith("raw:")
    linked = _quant_of(row).get("linked") or {}
    if not raw:
        label = ("linked response ratio %s (the method's setting); the instrument quantified it on %s and "
                 "the LIMS recomputes nothing" % (mode, of.get("standard") or "its surrogate"))
    elif mode == "on":
        label = ("linked response ratio on (the method's setting): read on A × A_IS ÷ A_sur, A_IS the area "
                 "of %s, the internal standard %s is linked to" % (linked.get("is") or "its internal standard",
                                                                    of.get("standard") or "its surrogate"))
    else:
        label = "linked response ratio off (the method's setting): read on A ÷ A_sur"
    terms = [term("LRR", label, mode, "", {"profile_key": "linked_response_ratio"})]
    held = getattr(row, "ratio_held", "") or ""
    steps = [{"label": "held: " + held, "expression": "no number", "value": None}] if held else []
    return terms, steps


def _quadratic_terms(row, quant, curve):
    """A value read on a quadratic curve: the curve's three terms, and its
    reading on the rising branch, or that the ratio has none there."""
    from .addon import load
    terms = _area_terms(row, quant) + [
             term("a", "x² term of this run's curve (%s, %s, origin %s, r² %s)" % (
                 curve.get("kind"), curve.get("weighting"), curve.get("origin"), curve.get("r2")),
                 curve.get("quadratic"), "", {"computed": True}),
             term("m", "x term of this run's curve", curve.get("slope"), "", {"computed": True}),
             term("b", "intercept of this run's curve", curve.get("intercept"), "", {"computed": True})]
    steps = _mean_steps(quant) + [_ratio_step(quant)]
    if quant.get("below"):
        # a sample below the lowest calibrator: its reading on the rising
        # branch, a number only at or above the MDL (pipeline.raw_below_mdl)
        mdl = (" (the MDL %g on the sample basis)" % quant["mdl"]) if quant.get("mdl") is not None else ""
        steps.append({"label": "%s; %s%s" % (quant["below"], quant.get("below_mdl") or "no number", mdl),
                      "expression": "a·C² + m·C + b = R", "value": quant.get("below_reading")})
        return terms, steps
    steps.append({"label": ("read on this run's curve, where it rises" if not quant.get("no_reading")
                            else "no reading: " + quant["no_reading"]),
                  "expression": "a·C² + m·C + b = R",
                  "value": load("quant_fit").concentration(curve, quant["ratio"])})
    return terms, steps


def _mean_of(names):
    """"Mean of A and B", as the composite is named (composite_standards)."""
    from .addon import load
    return load("composite_standards").name_of(list(names))


def src_row(row, column):
    """A cell of an imported row: the file and line it was read from; a row
    integrated from raw data names its peak instead of a line."""
    if row is None:
        return {}
    derived = getattr(row, "derived_from", "") or ""
    out = {"file": getattr(row, "source_file", "") or "", "line": getattr(row, "source_row", None),
           "injection": getattr(row, "injection_name", "") or "",
           "compound": getattr(row, "compound_name", "") or "", "column": column,
           "derived_from": derived}
    if derived.startswith("raw:"):
        out["peak"] = peak_text(json.loads(derived[len("raw:"):]))
    return out


def src_profile(method_id, path, label=""):
    return {"profile": method_id or "", "key": path, "label": label}


def src_record(kind, injection, analyte):
    """A term that is itself a recorded value (the LFSMD RPD uses the LFSM recovery)."""
    return {"record": key(kind, injection, analyte)}


def src_extraction(path):
    return {"extraction": path}


def record(batch, kind, injection, analyte, value, formula, terms, unit="", verdict="",
           steps=None, rule=None, value_text=""):
    """Append one record to batch.provenance (replacing one of the same key)."""
    recs = getattr(batch, "provenance", None)
    if recs is None:
        recs = batch.provenance = []
    k = key(kind, injection, analyte)
    rec = {"key": k, "kind": kind, "injection": injection or "",
           "analyte": _analyte_of(kind, analyte) or "",
           "value": value, "value_text": value_text or "", "unit": unit or "", "verdict": verdict or "",
           "formula": formula, "terms": list(terms or []), "steps": list(steps or []),
           "rule": dict(rule or {})}
    for i, old in enumerate(recs):
        if old["key"] == k:
            recs[i] = rec
            return rec
    recs.append(rec)
    return rec


def _window(w):
    w = w or {}
    return {k: w.get(k) for k in ("lo", "hi", "basis") if w.get(k) is not None}


def _verdict(flag):
    return "outside" if flag else "within"


def _rows_by(batch):
    by = {}
    for r in getattr(batch, "injections", None) or []:
        by[(r.injection_name, r.compound_name)] = r
    return by


def _calibrators(rows, compound):
    return [r for r in rows if r.compound_name == compound and r.included_in_cal]


# ── the run's checks ─────────────────────────────────────────────────────────

def record_run(batch, rows, profile, matrix):
    """Records for every judged QC value of the run, from the result objects
    auto_evaluate collected. Called once at the end of auto_evaluate."""
    by = _rows_by(batch)
    method = getattr(batch, "method_id", "") or ""
    m = matrix or ""

    for res in getattr(batch, "is_results", None) or []:
        row = by.get((res.injection_name, res.is_compound))
        cals = _calibrators(rows, res.is_compound)
        pct = res.pct_from_cal * 100.0 if res.pct_from_cal is not None else None
        terms = [term("A", "area of the labelled standard in this injection", res.response, "counts",
                      src_row(row, "is_response" if row is not None and row.is_response is not None else "response")),
                 term("Ā", "mean area over the %d calibrators" % len(cals), res.average_response, "counts",
                      {"rows": [src_row(c, "response") for c in cals]})]
        if res.configured:
            terms.append(term("W", "the method's response window", "%s–%s %%" % (res.window_min, res.window_max), "",
                              src_profile(method, "is_response", res.std_role or "")))
        record(batch, "IS", res.concat_id or res.injection_name, res.is_compound, pct, "R = A ÷ Ā × 100", terms, "%",
               _verdict(res.flag) if res.configured else "no criterion",
               rule={"text": res.flag.issue if res.flag else "", "judged": res.judged_pct,
                     "window": [res.window_min, res.window_max] if res.configured else None})

    for res in getattr(batch, "rt_results", None) or []:
        row = by.get((res.injection_name, res.analyte))
        cals = _calibrators(rows, res.analyte)
        dev = res.pct_deviation * 100.0 if res.pct_deviation is not None else None
        record(batch, "RT", res.concat_id or res.injection_name, res.analyte, res.observed_rt,
               "Δ = (RT ÷ RT̄ − 1) × 100", [
                   term("RT", "retention time in this injection", res.observed_rt, "min", src_row(row, "rt")),
                   term("RT̄", "mean retention time over the %d calibrators" % len(cals), res.average_rt, "min",
                        {"rows": [src_row(c, "rt") for c in cals]}),
                   term("Δ", "deviation", dev, "%", {"computed": True}),
                   term("T", "the method's retention-time tolerance", "", "", src_profile(method, "rt_tolerance"))],
               "min", _verdict(res.flag), rule={"text": res.flag.issue if res.flag else ""})

    for res in getattr(batch, "qual_quan_results", None) or []:
        row = by.get((res.injection_name, res.analyte))
        cals = _calibrators(rows, res.analyte)
        pct = res.pct_of_cal * 100.0 if res.pct_of_cal is not None else None
        record(batch, "ION", res.concat_id or res.injection_name, res.analyte, res.response_ratio,
               "ratio ÷ ratio̅ × 100", [
                   term("ratio", "qualifier ÷ quantifier response (the export's ion ratio, else the two responses)",
                        res.response_ratio, "", src_row(row, "ion_ratios")),
                   term("ratio̅", "expected ratio (the export's, else the mean over %d calibrators)" % len(cals),
                        res.avg_response_ratio, "", {"rows": [src_row(c, "ion_ratios") for c in cals],
                                                     "column": "expected_ion_ratios"}),
                   term("%", "of the expected ratio", pct, "%", {"computed": True}),
                   term("T", "the method's ion-ratio tolerance", "", "%", src_profile(method, "ion_ratio_tol_pct"))],
               "", _verdict(res.flag), rule={"text": res.flag.issue if res.flag else ""})

    for res in getattr(batch, "cal_results", None) or []:
        row = by.get((res.injection_name, res.analyte))
        exp = getattr(row, "expected_conc", None) if row is not None else None
        pct = res.pct_deviation * 100.0 if res.pct_deviation is not None else None
        record(batch, "CAL", res.concat_id or res.injection_name, res.analyte, pct, "D = (C − E) ÷ E × 100", [
                   term("C", "calculated concentration of the calibrator", res.calculated_conc, "",
                        src_row(row, "calc_conc")),
                   term("E", "expected concentration of the level", exp, "", src_row(row, "expected_conc")),
                   term("L", "the method's %s deviation limit" % ("lowest-level" if res.lowest else "point"),
                        res.limit, "%", src_profile(method, "calibration.point_deviation"))],
               "%", _verdict(res.flag), rule={"text": res.flag.issue if res.flag else ""})

    for d in getattr(batch, "ccv_results", None) or []:
        inj = d.get("injection_name") or (d.get("concat_id") or "").split("|")[0]
        kind = "ICV" if (d.get("qc_type") or "").upper() in ("ICV", "QCS") else "CCV"
        row = by.get((inj, d.get("analyte")))
        record(batch, kind, d.get("concat_id") or inj, d.get("analyte"), d.get("recovery"), "R = C ÷ E × 100", [
                   term("C", "calculated concentration", d.get("calculated"), "", src_row(row, "calc_conc")),
                   term("E", "the level's expected concentration", d.get("expected"), "",
                        src_row(row, "expected_conc")),
                   term("W", "the method's %s window" % kind, "", "%",
                        src_profile(method, "ccv.recovery" if kind == "CCV" else "icv.deviation"))],
               "%", "within" if d.get("passed") else "outside", rule={"text": d.get("issue") or ""})

    for e in getattr(batch, "surrogate_results", None) or []:
        inj, comp = e.get("injection_name"), e.get("compound")
        row = by.get((inj, comp))
        # a raw run's recovery is this LIMS's own: its amounts and readout
        terms, steps = recovery_terms(row)
        formula = "R = C_found ÷ C_spiked × 100, judged rounded" if terms else "R (as exported), judged rounded"
        if not terms:
            terms = [term("R", "recovery reported by the instrument for the labelled standard",
                          e.get("measured", e.get("value")), "%", src_row(row, "pct_recovery_is"))]
        if e.get("dilution"):
            # a diluted field sample's recovery, taken as the method chose
            terms.append(term("DR", "a dilution's recovery: its own, corrected for its fold" if e.get("fold")
                              else "a dilution's recovery: its own, as measured", e.get("dilution"), "",
                              {"profile_key": "dilution_recovery"}))
            if e.get("fold"):
                terms.append(term("DF", "the dilution's fold (the extraction record)", e.get("fold"), "",
                                  src_extraction("dilutions[%s]" % inj)))
                steps = list(steps) + [{"label": "corrected for the dilution's fold", "expression": "R × DF",
                                        "value": e.get("value")}]
        if e.get("window_min") is not None:
            terms.append(term("W", "the method's surrogate window%s" % (" (guidance)" if e.get("guidance") else ""),
                              "%s–%s %%" % (e.get("window_min"), e.get("window_max")), "",
                              src_profile(method, "qc_acceptance.SUR", e.get("std_role") or "")))
        record(batch, "SUR", inj, comp, e.get("value"), formula, terms, "%",
               e.get("status") or "", steps=steps,
               rule={"judged": e.get("judged"), "guidance": bool(e.get("guidance"))})

    spikes = getattr(batch, "spikes", None) or {}
    for res in getattr(batch, "lfsm_results", None) or []:
        frow = by.get((res.lfsm_injection, res.analyte))
        urow = by.get((res.parent_injection, res.analyte))
        ped = spikes.get(res.lfsm_injection) or {}
        record(batch, "LFSM", res.lfsm_injection, res.analyte, res.recovery_pct,
               "R = (F − U) ÷ S × 100", [
                   term("F", "fortified sample result", res.fortified_conc, "", src_row(frow, "calc_conc")),
                   term("U", "unfortified parent result (0 when not detected)", res.unfortified_conc, "",
                        src_row(urow, "calc_conc")),
                   term("S", "spike added (the extraction record%s)" % (
                       ", level %s" % ped.get("level") if ped.get("level") else ""), res.spike_value_ppt, "",
                        src_extraction("spikes[%s]" % res.lfsm_injection)),
                   term("W", "the recovery window at this level", "", "%",
                        src_profile(method, "qc_acceptance.LFSM.tiers"))],
               "%", _verdict(res.flag), rule=dict(_window(res.window), text=res.flag.issue if res.flag else ""))

    for res in getattr(batch, "lfsmd_results", None) or []:
        drow = by.get((res.lfsmd_injection, res.analyte))
        # an RPD not judged has no value to trace
        if getattr(res, "rpd_judged", True):
            record(batch, "LFSMD", res.lfsmd_injection, res.analyte, res.rpd_pct,
                   "RPD = |a − b| ÷ ((a + b) ÷ 2) × 100, of the two concentrations", [
                       term("a", "LFSM concentration", res.conc_lfsm, "",
                            src_record("LFSM", res.lfsm_injection, res.analyte)),
                       term("b", "LFSMD concentration", res.conc_lfsmd, "",
                            src_row(drow, "calc_conc")),
                       term("W", "the RPD limit at this level", "", "%",
                            src_profile(method, "qc_acceptance.LFSMD.tiers"))],
                   "%", _verdict(res.flag), rule=dict(_window(res.window), text=res.flag.issue if res.flag else ""))
        if getattr(res, "recovery_judged", False):
            record(batch, "LFSMD_REC", res.lfsmd_injection, res.analyte, res.recovery_lfsmd,
                   "R = (F − U) ÷ S × 100 (the duplicate, at the LFSM's spike)", [
                       term("F", "fortified duplicate result", None, "", src_row(drow, "calc_conc")),
                       term("U, S", "the LFSM's unfortified result and spike", None, "",
                            src_record("LFSM", res.lfsm_injection, res.analyte))],
                   "%", _verdict(res.recovery_flag),
                   rule=dict(_window(res.recovery_window), text=res.recovery_flag.issue if res.recovery_flag else ""))

    for d in getattr(batch, "lcs_results", None) or []:
        inj, an = d.get("injection_name"), d.get("analyte")
        row = by.get((inj, an))
        record(batch, d.get("qc_type") or "LFB", inj, an, d.get("recovery"), "R = C ÷ S × 100", [
                   term("C", "measured concentration", reported_conc(row) if row is not None else None, "",
                        src_row(row, "calc_conc")),
                   term("S", "the lot's reference value" if d.get("qc_type") == "MxB"
                        else "spike added (the extraction record, else the method's level)",
                        d.get("spike"), d.get("spike_unit") or "", src_extraction("spikes[%s]" % inj)),
                   term("W", d.get("basis") or "the recovery window", "%s–%s" % (d.get("lo"), d.get("hi")), "%",
                        src_profile(method, "qc_acceptance.%s.tiers" % (d.get("qc_type") or "LFB")))],
               "%", "within" if d.get("passed") else "outside", rule={"text": d.get("issue") or ""})

    for d in getattr(batch, "dup_results", None) or []:
        inj, an = d.get("injection_name"), d.get("analyte")
        r1, r2 = by.get((d.get("parent"), an)), by.get((inj, an))
        record(batch, "DUP", inj, an, d.get("rpd"), "RPD = |c₁ − c₂| ÷ ((c₁ + c₂) ÷ 2) × 100", [
                   term("c₁", "parent sample result", reported_conc(r1) if r1 is not None else None, "",
                        src_row(r1, "calc_conc")),
                   term("c₂", "duplicate result", reported_conc(r2) if r2 is not None else None, "",
                        src_row(r2, "calc_conc")),
                   term("W", d.get("basis") or "the RPD limit", "%s–%s" % (d.get("lo"), d.get("hi")), "%",
                        src_profile(method, "qc_acceptance.Dup"))],
               "%", "within" if d.get("passed") else "outside", rule={"text": d.get("issue") or ""})

    failed = set((f.injection_name, f.analyte) for f in (getattr(batch, "qc_flags", None) or [])
                 if getattr(f, "check_kind", "") == "blank")
    for (inj, an), lim in (getattr(batch, "blank_limits", None) or {}).items():
        row = by.get((inj, an))
        record(batch, "BLANK", inj, an, lim.get("value"), "C ≤ x × RL", [
                   term("C", "blank result as reported (rounded)", lim.get("value"), lim.get("unit") or "",
                        src_row(row, "calc_conc")),
                   term("x", "the method's blank limit, in multiples of the RL", lim.get("x_rl"), "",
                        src_profile(method, "qc_acceptance.blank_limits")),
                   term("RL", "the reporting limit", (lim.get("limit") / lim.get("x_rl"))
                        if lim.get("limit") is not None and lim.get("x_rl") else None, lim.get("unit") or "",
                        src_profile(method, "reporting_limits"))],
               lim.get("unit") or "", "outside" if (inj, an) in failed else "within",
               rule={"limit": lim.get("limit"), "fails_at_limit": bool(lim.get("at_limit")),
                     "covers": list(lim.get("covers") or [])})
    return getattr(batch, "provenance", None) or []


# ── the final sample values ──────────────────────────────────────────────────

def record_summary(batch, profile=None):
    """One RESULT record per summary row: the chain from the imported
    concentration to the reported value and its qualifier."""
    by = _rows_by(batch)
    method = getattr(batch, "method_id", "") or ""
    matrix = getattr(batch, "matrix", "") or ""
    dilutions = getattr(batch, "dilutions", None) or {}
    for s in getattr(batch, "summary", None) or []:
        row = by.get((s.source_injection or s.sample_injection, s.analyte))
        neat = by.get((s.sample_injection, s.analyte))
        steps, terms = [], []
        src = row if row is not None else neat
        # a summed analyte (lr- + br- isomers): its components' rows are the
        # imported values; the sum is the first step
        parts = [] if src is not None else [
            r for (inj, name), r in by.items()
            if inj == (s.source_injection or s.sample_injection)
            and name.lower().endswith("-" + s.analyte.lower()) and name.split("-")[0].lower() in ("lr", "br", "l", "b")]
        if parts:
            src = parts[0]
            total = 0.0
            for i, pr in enumerate(sorted(parts, key=lambda r: r.compound_name)):
                v = reported_conc(pr)
                total += v or 0.0
                terms.append(term("c%s" % chr(0x2081 + i), "%s as the instrument reported it" % pr.compound_name, v,
                                  getattr(pr, "conc_units", "") or "", src_row(pr, "calc_conc")))
            steps.append({"label": "isomers summed under %s" % s.analyte,
                          "expression": " + ".join("c%s" % chr(0x2081 + i) for i in range(len(parts))), "value": total})
        raw = getattr(src, "raw_calculated_conc", None) if src is not None else None
        conc = reported_conc(src) if src is not None else None
        if raw is None and conc is not None:
            raw = conc
        if not parts:
            raw_t, raw_s = raw_terms(src) if src is not None else ([], [])
            terms.extend(raw_t)
            steps.extend(raw_s)
            terms.append(term("c₀", "concentration this LIMS calculated from the raw data" if raw_t
                              else "concentration the instrument reported", raw,
                              getattr(src, "conc_units", "") if src is not None else "", src_row(src, "calc_conc")))
            steps.append({"label": "as calculated" if raw_t else "as imported", "expression": "c₀", "value": raw})
        value = raw
        if src is not None and getattr(src, "salt_factor", None):
            terms.append(term("f_salt", "salt (counter-ion) factor", src.salt_factor, "",
                              src_profile(method, "salt_factors.%s" % s.analyte)))
            value = value * src.salt_factor if value is not None else None
            steps.append({"label": "salt correction", "expression": "c₀ × f_salt", "value": value})
        elif src is not None and getattr(src, "salt_basis", None) == "acid":
            terms.append(term("f_salt", "salt factor not applied: the calibration standards are stated as acid",
                              None, "", src_profile(method, "salt_factors.%s" % s.analyte)))
        if src is not None and getattr(src, "matrix_factor", None):
            terms.append(term("f_m", "matrix / per-sample factor (sample amount and final volume)", src.matrix_factor,
                              "", src_extraction("samples[%s]" % s.sample_injection)))
            value = value * src.matrix_factor if value is not None else None
            steps.append({"label": "to the sample basis", "expression": "× f_m", "value": conc})
        if src is not None:
            # how it was quantified: the method's linked response ratio
            lrr_t, lrr_s = linked_terms(src)
            terms.extend(lrr_t)
            steps.extend(lrr_s)
        if s.neat_result is not None or s.dilution_factor:
            terms.append(term("d", "dilution fold (the extraction record)", s.dilution_factor, "",
                              src_extraction("dilutions[%s]" % (s.source_injection or ""))))
            steps.append({"label": "neat reading above the top calibrator: the dilution %s is reported"
                                   % (s.source_injection or ""), "expression": "c_dil × d",
                          "value": s.result_ppt if s.blank_subtracted is None else None})
        if s.qualifier == "< LOD":
            steps.append({"label": "the method blank reads at or above the sample: < LOD", "expression": "blank ≥ c",
                          "value": None})
        if s.blank_subtracted is not None:
            terms.append(term("b", "method blank subtracted", s.blank_subtracted, "",
                              src_record("BLANK", getattr(batch, "subtraction_blank", "") or "", s.analyte)))
            steps.append({"label": "blank subtraction", "expression": "c − b", "value": s.result_ppt})
        rl = getattr(src, "reporting_limit", None) if src is not None else None
        if rl is not None:
            terms.append(term("RL", "reporting limit on the sample basis", rl, "", src_row(src, "reporting_limit")))
        judged = None
        if profile is not None and s.result_ppt is not None:
            judged = profile.judged_conc(s.result_ppt, matrix)
        if judged is not None:
            steps.append({"label": "rounded by the method's rule", "expression": "round(c)", "value": judged})
        text = s.display() if hasattr(s, "display") else ""
        steps.append({"label": "reported", "expression": "c" + (" (%s)" % s.qualifier if s.qualifier else ""),
                      "value": s.result_ppt})
        record(batch, "RESULT", s.sample_injection, s.analyte, s.result_ppt,
               " → ".join(st["expression"] for st in steps), terms,
               getattr(src, "conc_units", "") if src is not None else "",
               s.qualifier or ("detected" if s.result_ppt is not None else ""),
               steps=steps, rule={"qualifier": s.qualifier, "flags": list(s.flags or []),
                                  "dilution_in_software": bool(dilutions) and s.dilution_factor is None},
               value_text=text)
    return getattr(batch, "provenance", None) or []


def record_file(batch, file_name, import_profile):
    """The run file and the import layout it was read with (kind RUN): what
    the drawer needs to find a term's column in the export."""
    p = import_profile or {}
    return record(batch, "RUN", file_name or "", "", None, "", [], rule={
        "layout": p.get("name") or "", "map": dict(p.get("map") or {}),
        "reader": dict(p.get("reader") or {})})


def identity_step(c):
    """The step a corrected injection's every record carries: what it was
    judged as, what the reviewer corrected it to, who, when and why."""
    return {"label": "identity corrected at review from %s to %s by %s at %s: %s" % (
                c.get("from") or "?", c.get("to") or c.get("role") or "?", c.get("by") or "?",
                c.get("at") or "?", c.get("reason") or ""),
            "expression": "role", "value": None}


def record_identity(batch, applied):
    """For each injection a reviewer corrected the identity of ({injection:
    the correction as the run applied it}): one record of kind ID (key
    "ID|<injection>|", the correction's id as its text, the correction as
    its rule; what Data Review reads to know the run was judged with it),
    and its step first on every other record of that injection."""
    for inj, c in sorted((applied or {}).items()):
        step = identity_step(c)
        for rec in getattr(batch, "provenance", None) or []:
            name = rec.get("injection") or ""
            if rec.get("kind") != "ID" and (name == inj or name.startswith(inj + "|")):
                rec["steps"] = [step] + [s for s in rec.get("steps") or [] if s != step]
        record(batch, "ID", inj, "", None, "role", [], verdict="corrected",
               steps=[step], value_text=c.get("id") or "",
               rule=dict((k, c.get(k) or "") for k in ("id", "from", "to", "role", "level", "by",
                                                        "at", "reason")))
    return getattr(batch, "provenance", None) or []


def record_amendments(batch, ids):
    """For each extraction correction the run was judged with (its id,
    "EA-n", extraction_amendments): one record of kind EA (key
    "EA|<id>|"), what Data Review reads to know the stored run applied it
    and release need not wait for it."""
    for i in sorted(set(ids or ())):
        record(batch, "EA", i, "", None, "extraction record", [], verdict="applied", value_text=i)
    return getattr(batch, "provenance", None) or []


# ── persistence ──────────────────────────────────────────────────────────────

def rows_for_persist(batch):
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    for r in getattr(batch, "provenance", None) or []:
        v = r.get("value")
        try:
            v = float(v) if v is not None else None
        except (TypeError, ValueError):
            v = None
        out.append((getattr(batch, "batch_id", "") or "", r["key"], r["kind"], r["analyte"], r["injection"],
                    v, str(r.get("value_text") or ""), r.get("unit") or "", r.get("verdict") or "",
                    r.get("formula") or "", json.dumps(r.get("terms") or [], default=str),
                    json.dumps(r.get("steps") or [], default=str), json.dumps(r.get("rule") or {}, default=str),
                    now))
    return out


PERSIST_COLUMNS = ("batch_id,key,kind,analyte,injection,value,value_text,unit,verdict,formula,"
                   "terms_json,steps_json,rule_json,created_at")
