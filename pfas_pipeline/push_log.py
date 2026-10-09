"""The push log: every result the worker wrote onto a core SENAITE analysis,
or could not (core integration).

One row per summary result of a run; a re-import replaces the run's rows.
Data Review reads them (data_review.result_checks): a result the worker could
not write (no sample with that Client Sample ID, or the sample has no analysis
for the analyte), and a core result that differs from what the worker wrote
(typed by hand on Manage Results, so never judged by the pipeline).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
COLS = ("batch_id", "run_at", "injection", "sample_uid", "analysis_uid", "analyte",
        "keyword", "value", "ok", "reason", "acquired_at")


def save_pushes(batch_id: str, rows: list, db_path: str = None) -> int:
    path = db_path or DB_PATH
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    values = [(batch_id or "", now, r.get("injection", ""), r.get("sample_uid", ""),
               r.get("analysis_uid", ""), r.get("analyte", ""), r.get("keyword", ""),
               r.get("value", ""), 1 if r.get("ok") else 0, r.get("reason", ""),
               r.get("acquired_at", ""))
              for r in rows]
    conn = sqlite3.connect(path)
    try:
        from .addon import load
        load("qc_schema").ensure(conn)
        conn.execute("DELETE FROM result_pushes WHERE batch_id=?", (batch_id or "",))
        conn.executemany("INSERT INTO result_pushes (%s) VALUES (%s)"
                         % (",".join(COLS), ",".join("?" * len(COLS))), values)
        conn.commit()
    finally:
        conn.close()
    return len(values)

