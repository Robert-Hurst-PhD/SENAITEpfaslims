"""
Per-injection detail persistence (D59).

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

_SCHEMA = """CREATE TABLE IF NOT EXISTS injection_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        TEXT    NOT NULL DEFAULT '',
    run_date        TEXT    NOT NULL DEFAULT '',
    sample_id       TEXT    NOT NULL DEFAULT '',
    injection_name  TEXT    NOT NULL DEFAULT '',
    qc_type         TEXT    NOT NULL DEFAULT '',
    analyte         TEXT    NOT NULL DEFAULT '',
    role            TEXT    NOT NULL DEFAULT 'analyte',
    method          TEXT    NOT NULL DEFAULT '',
    rt              REAL,
    rrt             REAL,
    ion_ratio_obs   REAL,
    ion_ratio_exp   REAL,
    is_area         REAL,
    sn              REAL,
    qual_sn         REAL,
    response        REAL,
    calc_conc       REAL,
    conc_qualifier  TEXT    NOT NULL DEFAULT '',
    recovery        REAL,
    flag            TEXT    NOT NULL DEFAULT '',
    passed          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL
)"""

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

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    method = getattr(batch, "method_id", "") or ""
    rows_out = []
    for r in getattr(batch, "injections", []) or []:
        inj = r.injection_name
        analyte = r.compound_name
        qc_type = classify_injection(inj)
        # sample id: prefer the parsed STARLIMS/sample id, else the injection
        sample_id = inj
        try:
            v = validate_injection_name(inj)
            sample_id = v.get("starlims_id") or v.get("sample_id") or inj
        except Exception:
            pass
        issues = flags.get((inj, analyte), [])
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
            None,                         # recovery — QC-type specific, filled later
            "; ".join(i for i in issues if i),
            0 if issues else 1,
            now,
        ))

    cols = ("batch_id,run_date,sample_id,injection_name,qc_type,analyte,role,"
            "method,rt,rrt,ion_ratio_obs,ion_ratio_exp,is_area,sn,qual_sn,"
            "response,calc_conc,conc_qualifier,recovery,flag,passed,created_at")
    ph = ",".join(["?"] * 22)
    conn = sqlite3.connect(path)
    try:
        conn.execute(_SCHEMA)
        # Older databases predate conc_qualifier; add it rather than requiring
        # a rebuild, so an existing QC database keeps its history.
        have = {row[1] for row in conn.execute(
            "PRAGMA table_info(injection_results)")}
        if "conc_qualifier" not in have:
            conn.execute("ALTER TABLE injection_results "
                         "ADD COLUMN conc_qualifier TEXT NOT NULL DEFAULT ''")
        conn.execute("DELETE FROM injection_results WHERE batch_id=?",
                     (getattr(batch, "batch_id", "") or "",))
        conn.executemany(
            "INSERT INTO injection_results ({0}) VALUES ({1})".format(cols, ph),
            rows_out)
        conn.commit()
    finally:
        conn.close()
    return len(rows_out)
