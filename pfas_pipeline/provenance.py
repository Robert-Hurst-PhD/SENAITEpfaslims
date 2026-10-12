"""Value provenance: every judged value records what it was computed from.

Decided 2026-10-11. A record names the value, the formula it came from, each
term with its value and its SOURCE (an imported row's cell by file and line,
a profile criterion by key, the extraction record, another recorded value),
the steps of a chain (the final sample value) and the rule with its verdict.
Data Review opens a value's record in a drawer and lights the imported rows
and the terms that made it; the records are the run's own, taken from the
same objects the checks judged, in the same process, before anything is
pushed. Nothing here changes a value: the golden masters stay at 0 differ.

Keys: "<kind>|<injection>|<analyte>", the same string a qc_results or
injection_results row carries in prov_key. Kinds: IS, RT, ION, CAL, CCV, ICV,
SUR, LFSM, LFSMD, LFSMD_REC, BLANK, LFB, LCS, DUP, RESULT (and "row" for an
imported row itself).

Python 3 (worker).
"""
from __future__ import annotations

import json
from datetime import datetime

from .models import reported_conc


def key(kind, injection, analyte):
    return "%s|%s|%s" % (kind, injection or "", analyte or "")


def term(symbol, label, value, unit="", source=None):
    return {"symbol": symbol, "label": label, "value": value, "unit": unit or "",
            "source": source or {}}


def src_row(row, column):
    """A cell of an imported row: the file and line it was read from."""
    if row is None:
        return {}
    return {"file": getattr(row, "source_file", "") or "", "line": getattr(row, "source_row", None),
            "injection": getattr(row, "injection_name", "") or "",
            "compound": getattr(row, "compound_name", "") or "", "column": column,
            "derived_from": getattr(row, "derived_from", "") or ""}


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
    rec = {"key": k, "kind": kind, "injection": injection or "", "analyte": analyte or "",
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
        terms = [term("R", "recovery reported by the instrument for the labelled standard", e.get("value"), "%",
                      src_row(row, "pct_recovery_is"))]
        if e.get("window_min") is not None:
            terms.append(term("W", "the method's surrogate window%s" % (" (guidance)" if e.get("guidance") else ""),
                              "%s–%s %%" % (e.get("window_min"), e.get("window_max")), "",
                              src_profile(method, "qc_acceptance.SUR", e.get("std_role") or "")))
        record(batch, "SUR", inj, comp, e.get("value"), "R (as exported), judged rounded", terms, "%",
               e.get("status") or "", rule={"judged": e.get("judged"), "guidance": bool(e.get("guidance"))})

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
        basis = "concentrations" if getattr(profile, "lfsmd_rpd_from_concentrations", lambda: False)() else "recoveries"
        record(batch, "LFSMD", res.lfsmd_injection, res.analyte, res.rpd_pct,
               "RPD = |a − b| ÷ ((a + b) ÷ 2) × 100, of the two %s" % basis, [
                   term("a", "LFSM %s" % basis[:-1], res.recovery_lfsm, "%" if basis == "recoveries" else "",
                        src_record("LFSM", res.lfsm_injection, res.analyte)),
                   term("b", "LFSMD %s" % basis[:-1], res.recovery_lfsmd, "%" if basis == "recoveries" else "",
                        src_row(drow, "calc_conc")),
                   term("W", "the RPD limit at this level", "", "%", src_profile(method, "qc_acceptance.LFSMD.tiers"))],
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
                   term("S", "spike added (the extraction record, else the method's level)", None, "",
                        src_extraction("spikes[%s]" % inj)),
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
            terms.append(term("c₀", "concentration the instrument reported", raw,
                              getattr(src, "conc_units", "") if src is not None else "", src_row(src, "calc_conc")))
            steps.append({"label": "as imported", "expression": "c₀", "value": raw})
        if src is not None and getattr(src, "salt_factor", None):
            terms.append(term("f_salt", "salt (counter-ion) factor", src.salt_factor, "",
                              src_profile(method, "salt_factors.%s" % s.analyte)))
            steps.append({"label": "salt correction", "expression": "c₀ × f_salt",
                          "value": (raw or 0) * src.salt_factor if raw is not None else None})
        if src is not None and getattr(src, "matrix_factor", None):
            terms.append(term("f_m", "matrix / per-sample factor (sample amount and final volume)", src.matrix_factor,
                              "", src_extraction("samples[%s]" % s.sample_injection)))
            steps.append({"label": "to the sample basis", "expression": "× f_m", "value": conc})
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
            try:
                judged = profile.judged_conc(s.result_ppt, matrix)
            except Exception:                                   # noqa: BLE001
                judged = None
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
