"""The import log: what became of each run file delivered to the worker.
A run the worker could not import -- SENAITE
timed out or was restarting -- used to be marked processed and never tried
again, and SENAITE said nothing; a push stopped partway left samples
half-filled. Now the watcher retries it (RETRY_DELAYS) and records here
`imported`, `retrying` or `failed` with the last error; Data Review and the
Run Builder show anything not imported.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
# seconds before each retry; after the last the file is recorded `failed`
RETRY_DELAYS = (60, 300, 900)


def record(file_name: str, batch_id: str, status: str, attempts: int = 0,
           error: str = "", db_path: str = None) -> None:
    conn = sqlite3.connect(db_path or DB_PATH)
    try:
        from .addon import load
        load("qc_schema").ensure(conn)
        conn.execute(
            "INSERT OR REPLACE INTO run_imports (file, batch_id, status, attempts, error, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (file_name, batch_id or "", status, int(attempts), (error or "")[:500],
             datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")))
        conn.commit()
    finally:
        conn.close()


def sidecar_batch_id(sidecar_path) -> str:
    """The run's worksheet id from its extraction sidecar ('' if unknown)."""
    import json
    try:
        with open(str(sidecar_path), encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("batch_id") or ""
    except Exception:                                       # noqa: BLE001
        return ""
