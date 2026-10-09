"""
Per-injection detail persistence.

The QC engine computes rich per-injection values (retention time, ion ratios,
IS area, S/N) that the summary discards. This module persists them into the
`injection_results` table of the shared QC database so the multi-page Results
Review (retention times, qualifier ions, IS/surrogates, per-sample results) can
verify every result against its Method-Profile spec.

Schema MIRRORS src/senaite/pfas/qc/store.py `injection_results` (the Py2.7 UI
reads the same table). Python 3.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")

# Schema: the add-on's senaite.pfas.qc_schema, shared.

_ROLE_MAP = {"Target": "analyte", "IS": "is", "Qualifier": "qualifier"}


def _f(v):
    """Best-effort float (handles None and ratio strings like '0.98')."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def persist_injection_results(batch, db_path: str = None) -> int:
    """Write one row per injection × compound for a processed Batch. Replaces
    any existing rows for the same batch_id (idempotent re-import)."""
    path = db_path or DB_PATH
    from .importer import classify_injection, validate_injection_name
    from .models import reported_conc

    # index flags by (injection_name, analyte) → issue string
    flags = {}
    for fl in getattr(batch, "qc_flags", []) or []:
        key = (fl.injection_name, fl.analyte)
        flags.setdefault(key, []).append(fl.issue)

    dilutions = getattr(batch, "dilutions", None) or {}
    # : what the surrogate-recovery and IS-response checks judged
    is_by = dict(((x.injection_name, x.is_compound), x)
                 for x in getattr(batch, "is_results", None) or [])
    sur_by = dict(((x["injection_name"], x["compound"]), x)
                  for x in getattr(batch, "surrogate_results", None) or [])
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    method = getattr(batch, "method_id", "") or ""
    rows_out = []
    # what the run was judged with: "epa;3;pct0"; a certificate
    # drawn under another rule is refused until the run is reprocessed
    judged_rule = ""
    try:
        from .method_profiles import get_profile
        judged_rule = get_profile(method).judged_rule(getattr(batch, "matrix", "") or "") if method else ""
    except Exception:                                       # noqa: BLE001
        judged_rule = ""
    for r in getattr(batch, "injections", []) or []:
        inj = r.injection_name
        analyte = r.compound_name
        qc_type = classify_injection(inj, dilutions)
        # sample id: prefer the parsed STARLIMS/sample id, else the injection
        sample_id = inj
        try:
            v = validate_injection_name(inj)
            sample_id = v.get("starlims_id") or v.get("sample_id") or inj
        except Exception:
            pass
        issues = flags.get((inj, analyte), [])
        sur = sur_by.get((inj, analyte))
        isr = is_by.get((inj, analyte))
        resp_pct = (isr.pct_from_cal * 100.0 if isr is not None and isr.pct_from_cal is not None
                    else None)
        if isr is None or resp_pct is None:
            resp_status = ""
        elif not isr.configured:
            resp_status = "no criterion"
        else:
            # the check's JUDGED value (a whole percent by the method's rule), never a re-judgement of the raw percentage
            judged = isr.judged_pct if isr.judged_pct is not None else resp_pct
            resp_status = ("within" if isr.window_min <= judged <= isr.window_max
                           else "outside")
        rows_out.append((
            getattr(batch, "batch_id", "") or "",
            (r.acquisition_datetime.strftime("%Y-%m-%d")
             if getattr(r, "acquisition_datetime", None) else ""),
            sample_id, inj, qc_type, analyte,
            _ROLE_MAP.get(r.compound_type, (r.compound_type or "analyte").lower()),
            method,
            _f(r.observed_rt), _f(r.rt_relative_to_is),
            _f(r.ion_ratios), _f(r.expected_ion_ratios),
            _f(r.is_response), _f(r.signal_to_noise), _f(r.qual_sn),
            _f(r.response),
            reported_conc(r),
            getattr(r, "conc_qualifier", "") or "",
            sur["value"] if sur else None,          # surrogate % recovery
            "; ".join(i for i in issues if i),
            0 if issues else 1,
            now,
            (sur or {}).get("std_role") or (isr.std_role if isr is not None else ""),
            sur["window_min"] if sur else None, sur["window_max"] if sur else None,
            sur["status"] if sur else "", 1 if sur and sur["guidance"] else 0,
            resp_pct,
            isr.window_min if isr is not None and isr.configured else None,
            isr.window_max if isr is not None and isr.configured else None,
            resp_status,
            sur.get("judged") if sur else None,
            isr.judged_pct if isr is not None else None,
            judged_rule,
            getattr(r, "manual_changes", None) or "",
            (None if getattr(r, "manual_integration", None) is None
             else (1 if r.manual_integration else 0)),
        ))

    cols = ("batch_id,run_date,sample_id,injection_name,qc_type,analyte,role,"
            "method,rt,rrt,ion_ratio_obs,ion_ratio_exp,is_area,sn,qual_sn,"
            "response,calc_conc,conc_qualifier,recovery,flag,passed,created_at,"
            "std_role,rec_min,rec_max,rec_status,rec_guidance,"
            "resp_pct,resp_min,resp_max,resp_status,rec_judged,resp_judged,judged_rule,"
            "manual_raw,manual_integration")
    ph = ",".join(["?"] * 36)
    conn = sqlite3.connect(path)
    try:
        from .addon import load
        load("qc_schema").ensure(conn)       # tables + numbered migrations
        conn.execute("DELETE FROM injection_results WHERE batch_id=?",
                     (getattr(batch, "batch_id", "") or "",))
        conn.executemany(
            "INSERT INTO injection_results ({0}) VALUES ({1})".format(cols, ph),
            rows_out)
        conn.commit()
    finally:
        conn.close()
    return len(rows_out)
