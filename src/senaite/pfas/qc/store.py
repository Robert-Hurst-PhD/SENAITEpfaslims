# -*- coding: utf-8 -*-
"""
QC Result Store — SQLite-backed persistent storage for control charting.

Written Python 2/3 compatible so both the pipeline (Py3) and the SENAITE
browser view (Py2.7 Zope) can import and use it.

DB path defaults to /data/qc/pfas_qc_results.db (override via PFAS_QC_DB env var).

Schema overview
---------------
batches      — one row per instrument run; tracks analyst, instrument, status
qc_results   — one row per analyte × QC type per batch run; supports reanalysis

result_status values:
  active               — current result; used in control charts
  flagged_reanalysis   — analyst has flagged this result; awaiting new run
  superseded           — replaced by a reanalysis result (audit trail retained)
  voided               — entire batch or result cancelled; excluded from charts

batch_status values:
  pending      — data received, QC review not yet complete
  reviewed     — QC review passed; no items flagged
  partial_fail — one or more results flagged for reanalysis
  failed       — entire batch failed; all results voided
  complete     — all reanalyses resolved; batch closed
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging
import os
import sqlite3

logger = logging.getLogger("senaite.pfas.qc.store")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")


class DuplicateBatchError(Exception):
    """Raised when active results for a batch already exist."""


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA_STMTS = [
    # Calibration curves — one row per analyte per run date
    """CREATE TABLE IF NOT EXISTS calibrations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id        TEXT    NOT NULL DEFAULT '',
        run_date        TEXT    NOT NULL,
        analyte         TEXT    NOT NULL,
        method          TEXT    NOT NULL DEFAULT '',
        analyst         TEXT    NOT NULL DEFAULT '',
        instrument_id   TEXT    NOT NULL DEFAULT '',
        equation        TEXT    NOT NULL DEFAULT '',
        fit_type        TEXT    NOT NULL DEFAULT '',
        weight_type     TEXT    NOT NULL DEFAULT '',
        r2              REAL,
        n_levels        INTEGER NOT NULL DEFAULT 0,
        min_level       REAL,
        max_level       REAL,
        status          TEXT    NOT NULL DEFAULT 'pending',
        notes           TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    )""",

    # Per-level calibration points
    """CREATE TABLE IF NOT EXISTS calibration_levels (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        calibration_id  INTEGER NOT NULL REFERENCES calibrations(id),
        level           INTEGER NOT NULL,
        expected        REAL,
        calculated      REAL,
        pct_deviation   REAL,
        passed          INTEGER NOT NULL DEFAULT 1
    )""",

    "CREATE INDEX IF NOT EXISTS idx_cal_analyte  ON calibrations(analyte)",
    "CREATE INDEX IF NOT EXISTS idx_cal_run_date ON calibrations(run_date)",
    "CREATE INDEX IF NOT EXISTS idx_cal_batch    ON calibrations(batch_id)",

    # Batch-level metadata
    """CREATE TABLE IF NOT EXISTS batches (
        batch_id      TEXT    PRIMARY KEY,
        run_date      TEXT    NOT NULL,
        analyst       TEXT    NOT NULL DEFAULT '',
        instrument_id TEXT    NOT NULL DEFAULT '',
        method        TEXT    NOT NULL DEFAULT '',
        status        TEXT    NOT NULL DEFAULT 'pending',
        notes         TEXT    NOT NULL DEFAULT '',
        created_at    TEXT    NOT NULL,
        updated_at    TEXT    NOT NULL
    )""",

    # Per-analyte QC results with reanalysis support
    """CREATE TABLE IF NOT EXISTS qc_results (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id        TEXT    NOT NULL,
        run_date        TEXT    NOT NULL,
        analyte         TEXT    NOT NULL,
        qc_type         TEXT    NOT NULL,
        qc_level        TEXT    NOT NULL DEFAULT '',
        method          TEXT    NOT NULL DEFAULT '',
        analyst         TEXT    NOT NULL DEFAULT '',
        instrument_id   TEXT    NOT NULL DEFAULT '',
        value           REAL,
        units           TEXT    NOT NULL DEFAULT '',
        flag            TEXT    NOT NULL DEFAULT '',
        passed          INTEGER NOT NULL DEFAULT 1,
        result_status   TEXT    NOT NULL DEFAULT 'active',
        parent_result_id INTEGER REFERENCES qc_results(id),
        reanalysis_reason TEXT  NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL,
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
    )""",

    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_qr_analyte   ON qc_results(analyte)",
    "CREATE INDEX IF NOT EXISTS idx_qr_qc_type   ON qc_results(qc_type)",
    "CREATE INDEX IF NOT EXISTS idx_qr_batch     ON qc_results(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_qr_run_date  ON qc_results(run_date)",
    "CREATE INDEX IF NOT EXISTS idx_qr_status    ON qc_results(result_status)",
    "CREATE INDEX IF NOT EXISTS idx_qr_analyst   ON qc_results(analyst)",
    "CREATE INDEX IF NOT EXISTS idx_qr_inst      ON qc_results(instrument_id)",

    # Partial unique index: only one active result per (batch, analyte, qc_type, qc_level)
    # SQLite supports WHERE clauses on indexes (3.8.9+)
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_active_result
       ON qc_results(batch_id, analyte, qc_type, qc_level)
       WHERE result_status = 'active'""",

    # Per-injection chromatographic detail (D59): one row per injection ×
    # analyte, carrying the per-injection values the QC engine computes but the
    # summary discards. Feeds the multi-page Results Review (qualifier ions,
    # retention times, IS/surrogates, per-sample results).
    """CREATE TABLE IF NOT EXISTS injection_results (
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
        recovery        REAL,
        flag            TEXT    NOT NULL DEFAULT '',
        passed          INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT    NOT NULL
    )""",

    "CREATE INDEX IF NOT EXISTS idx_inj_batch    ON injection_results(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_inj_run_date ON injection_results(run_date)",
    "CREATE INDEX IF NOT EXISTS idx_inj_analyte  ON injection_results(analyte)",
    "CREATE INDEX IF NOT EXISTS idx_inj_qc_type  ON injection_results(qc_type)",
    "CREATE INDEX IF NOT EXISTS idx_inj_sample   ON injection_results(sample_id)",
]

# ALTER TABLE migrations — run once; silently ignored if column already exists.
_MIGRATION_STMTS = [
    # calibrations: per-run approval + fit overrides
    "ALTER TABLE calibrations ADD COLUMN approved_by      TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN approved_at      TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN fit_type_override  TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN weight_override    TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN origin_override    TEXT NOT NULL DEFAULT ''",
    # calibration_levels: raw response ratio for Plot 1 (response vs concentration)
    "ALTER TABLE calibration_levels ADD COLUMN response_ratio REAL",
    # qc_results: expected concentration so % deviation can be computed in the UI
    "ALTER TABLE qc_results ADD COLUMN expected_value REAL",
    # qc_results: response ratio for overlaying instrument checks on calibration curve
    "ALTER TABLE qc_results ADD COLUMN response_ratio REAL",
]


def _now_iso():
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ── Store ───────────────────────────────────────────────────────────────────────

class QCResultStore(object):
    """
    Persistent QC result store with batch lifecycle tracking.

    Typical write flow
    ------------------
    1. register_batch(batch_id, ...)       — called before inserting results
    2. add_results_bulk(rows)              — insert all QC results for the batch
    3. update_batch_status(batch_id, 'reviewed')

    Reanalysis flow
    ---------------
    4. flag_for_reanalysis(batch_id, analyte, qc_type, qc_level, reason)
    5. update_batch_status(batch_id, 'partial_fail')
    6. add_results_bulk([...], reanalysis=True)  — supersedes flagged results
    7. update_batch_status(batch_id, 'complete')

    Failed batch
    ------------
    void_batch(batch_id, reason)  — marks all results as voided, batch as failed
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._ensure_dir()
        self._ensure_schema()

    def _ensure_dir(self):
        d = os.path.dirname(self.db_path)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d)
            except OSError:
                pass

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self):
        with self._connect() as conn:
            for stmt in _SCHEMA_STMTS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "already exists" not in str(e):
                        raise
            for stmt in _MIGRATION_STMTS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # column already exists — idempotent

    # ── Batch registration ──────────────────────────────────────────────────

    def register_batch(self, batch_id, run_date, analyst="", instrument_id="",
                       method="", status="pending", notes=""):
        """
        Register a batch before inserting its QC results.
        If the batch_id already exists the call is a no-op (idempotent).
        """
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO batches "
                "(batch_id,run_date,analyst,instrument_id,method,status,notes,"
                " created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (batch_id, run_date, analyst, instrument_id, method,
                 status, notes, now, now),
            )

    def update_batch_status(self, batch_id, status, notes=""):
        """Update batch lifecycle status. Appends notes if provided."""
        now = _now_iso()
        with self._connect() as conn:
            if notes:
                conn.execute(
                    "UPDATE batches SET status=?, notes=notes||? ||?,"
                    " updated_at=? WHERE batch_id=?",
                    (status, "\n" if notes else "", notes, now, batch_id),
                )
            else:
                conn.execute(
                    "UPDATE batches SET status=?, updated_at=? WHERE batch_id=?",
                    (status, now, batch_id),
                )

    # ── Per-injection detail (D59) ──────────────────────────────────────────

    _INJ_COLS = ("batch_id", "run_date", "sample_id", "injection_name",
                 "qc_type", "analyte", "role", "method", "rt", "rrt",
                 "ion_ratio_obs", "ion_ratio_exp", "is_area", "sn", "qual_sn",
                 "response", "calc_conc", "recovery", "flag", "passed")

    def add_injection_results(self, rows, replace_batch=None):
        """Bulk-insert per-injection detail rows (list of dicts keyed by
        _INJ_COLS; missing keys default to NULL/'' /1). If replace_batch is
        given, existing rows for that batch_id are deleted first (idempotent
        re-import)."""
        if not rows:
            return 0
        now = _now_iso()
        cols = self._INJ_COLS
        placeholders = ",".join(["?"] * (len(cols) + 1))  # +created_at
        sql = ("INSERT INTO injection_results ({0},created_at) VALUES ({1})"
               .format(",".join(cols), placeholders))
        payload = []
        for r in rows:
            vals = []
            for c in cols:
                v = r.get(c)
                if c == "passed":
                    v = 1 if (v is None or v) else 0
                elif c in ("batch_id", "run_date", "sample_id",
                           "injection_name", "qc_type", "analyte", "role",
                           "method", "flag"):
                    v = v or ""
                vals.append(v)
            vals.append(now)
            payload.append(tuple(vals))
        with self._connect() as conn:
            if replace_batch is not None:
                conn.execute("DELETE FROM injection_results WHERE batch_id=?",
                             (replace_batch,))
            conn.executemany(sql, payload)
        return len(payload)

    def get_injection_results(self, batch_id=None, run_date=None, analyte=None,
                              qc_type=None, role=None):
        """Fetch per-injection detail rows filtered by any of the given keys."""
        sql = "SELECT * FROM injection_results WHERE 1=1"
        params = []
        for col, val in (("batch_id", batch_id), ("run_date", run_date),
                         ("analyte", analyte), ("qc_type", qc_type),
                         ("role", role)):
            if val is not None:
                sql += " AND {0}=?".format(col)
                params.append(val)
        sql += " ORDER BY sample_id, analyte"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_batch(self, batch_id):
        """Return batch metadata dict or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_recent_batches(self, limit=50, status=None):
        sql = "SELECT * FROM batches"
        params = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY run_date DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── Write results ───────────────────────────────────────────────────────

    def add_results_bulk(self, rows, reanalysis=False):
        """
        Insert QC result rows for a batch.

        Parameters
        ----------
        rows       : list of dicts with keys: batch_id, run_date, analyte,
                     qc_type, qc_level, method, analyst, instrument_id,
                     value, units, flag, passed
        reanalysis : if False (default), raises DuplicateBatchError when any
                     active result for the same (batch_id, analyte, qc_type,
                     qc_level) already exists.
                     if True, supersedes any flagged_reanalysis results and
                     inserts the new result as active.

        Returns
        -------
        int — number of rows inserted
        """
        if not rows:
            return 0

        now = _now_iso()

        with self._connect() as conn:
            inserted = 0
            for r in rows:
                bid     = r.get("batch_id", "")
                analyte = r.get("analyte", "")
                qtype   = r.get("qc_type", "")
                qlevel  = r.get("qc_level", "")

                # Check for existing active result
                existing = conn.execute(
                    "SELECT id, result_status FROM qc_results "
                    "WHERE batch_id=? AND analyte=? AND qc_type=? AND qc_level=? "
                    "AND result_status='active'",
                    (bid, analyte, qtype, qlevel),
                ).fetchone()

                if existing:
                    if not reanalysis:
                        raise DuplicateBatchError(
                            "Active result already exists for batch={} analyte={} "
                            "type={} level={}. Use reanalysis=True to supersede, "
                            "or call flag_for_reanalysis() first.".format(
                                bid, analyte, qtype, qlevel)
                        )
                    # Supersede the existing active result
                    conn.execute(
                        "UPDATE qc_results SET result_status='superseded' "
                        "WHERE id=?",
                        (existing["id"],),
                    )
                    parent_id = existing["id"]
                else:
                    # For reanalysis mode, check if a flagged result exists to link to
                    flagged = conn.execute(
                        "SELECT id FROM qc_results "
                        "WHERE batch_id=? AND analyte=? AND qc_type=? AND qc_level=? "
                        "AND result_status='flagged_reanalysis'",
                        (bid, analyte, qtype, qlevel),
                    ).fetchone()
                    parent_id = flagged["id"] if flagged else None

                conn.execute(
                    "INSERT INTO qc_results "
                    "(batch_id,run_date,analyte,qc_type,qc_level,method,"
                    " analyst,instrument_id,value,units,flag,passed,"
                    " result_status,parent_result_id,reanalysis_reason,created_at,"
                    " expected_value,response_ratio) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bid,
                     r.get("run_date", ""),
                     analyte,
                     qtype,
                     qlevel,
                     r.get("method", ""),
                     r.get("analyst", ""),
                     r.get("instrument_id", ""),
                     r.get("value"),
                     r.get("units", ""),
                     r.get("flag", ""),
                     int(bool(r.get("passed", True))),
                     "active",
                     parent_id,
                     r.get("reanalysis_reason", ""),
                     now,
                     r.get("expected_value"),
                     r.get("response_ratio")),
                )
                inserted += 1

        logger.info("add_results_bulk: inserted %d rows (reanalysis=%s)",
                    inserted, reanalysis)
        return inserted

    def add_result(self, batch_id, run_date, analyte, qc_type, qc_level="",
                   value=None, units="", flag="", passed=True, method="",
                   analyst="", instrument_id="", reanalysis=False):
        """Single-row convenience wrapper around add_results_bulk."""
        return self.add_results_bulk([dict(
            batch_id=batch_id, run_date=run_date, analyte=analyte,
            qc_type=qc_type, qc_level=qc_level, method=method,
            analyst=analyst, instrument_id=instrument_id,
            value=value, units=units, flag=flag, passed=passed,
        )], reanalysis=reanalysis)

    # ── Reanalysis workflow ─────────────────────────────────────────────────

    def flag_for_reanalysis(self, batch_id, analyte, qc_type, qc_level="",
                            reason=""):
        """
        Mark a specific result as requiring reanalysis.

        The result remains visible in the audit trail but is excluded from
        control charts until a reanalysis result supersedes it.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE qc_results "
                "SET result_status='flagged_reanalysis', "
                "    reanalysis_reason=? "
                "WHERE batch_id=? AND analyte=? AND qc_type=? AND qc_level=? "
                "AND result_status='active'",
                (reason, batch_id, analyte, qc_type, qc_level),
            )
            affected = conn.execute("SELECT changes()").fetchone()[0]

        if affected:
            logger.info("Flagged for reanalysis: %s %s %s %s — %s",
                        batch_id, analyte, qc_type, qc_level, reason)
        else:
            logger.warning("flag_for_reanalysis: no active result found for "
                           "%s %s %s %s", batch_id, analyte, qc_type, qc_level)
        return affected

    def void_batch(self, batch_id, reason=""):
        """
        Void all active and flagged results for a batch (entire batch failure).
        Updates batch status to 'failed'.
        """
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE qc_results SET result_status='voided', "
                "reanalysis_reason=? "
                "WHERE batch_id=? AND result_status IN ('active','flagged_reanalysis')",
                (reason, batch_id),
            )
        self.update_batch_status(batch_id, "failed", notes=reason)
        logger.info("Voided batch %s: %s", batch_id, reason)

    def get_flagged_results(self, batch_id=None):
        """Return all results currently flagged for reanalysis."""
        sql = ("SELECT * FROM qc_results WHERE result_status='flagged_reanalysis'")
        params = []
        if batch_id:
            sql += " AND batch_id=?"
            params.append(batch_id)
        sql += " ORDER BY batch_id, analyte"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_result_history(self, batch_id, analyte, qc_type, qc_level=""):
        """Return full audit trail for a specific result (all statuses)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM qc_results "
                "WHERE batch_id=? AND analyte=? AND qc_type=? AND qc_level=? "
                "ORDER BY created_at ASC",
                (batch_id, analyte, qc_type, qc_level),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Read (chart data) ───────────────────────────────────────────────────

    def get_chart_data(self, analyte, qc_type, qc_level=None, method=None,
                       analyst=None, instrument_id=None, limit=20,
                       include_superseded=False, include_test=False):
        """
        Return ordered list of dicts for Levey-Jennings charting.

        Only returns result_status='active' rows by default.
        Set include_superseded=True to show the full historical record
        (useful for analyst performance review).

        Default limit=20 matches one month of weekly batches; set limit=200+
        for annual review.
        """
        if include_superseded:
            # Include original failing results (flagged_reanalysis) and
            # superseded rows in addition to current active results
            status_clause = ("result_status IN "
                             "('active','superseded','flagged_reanalysis')")
        else:
            status_clause = "result_status='active'"

        sql = ("SELECT r.id, r.run_date, r.value, r.flag, r.passed, r.batch_id, "
               "       r.analyst, r.instrument_id, r.result_status, "
               "       b.analyst AS batch_analyst "
               "FROM qc_results r "
               "LEFT JOIN batches b ON r.batch_id = b.batch_id "
               "WHERE r.analyte=? AND r.qc_type=? AND " + status_clause)
        params = [analyte, qc_type]

        if not include_test:
            # Control charts must reflect REAL runs only — exclude seeded /
            # synthetic rows (TEST_DATA* flags, SYNTHETIC_ batches).
            sql += (" AND r.flag NOT LIKE 'TEST_DATA%'"
                    " AND r.batch_id NOT LIKE 'SYNTHETIC_%'")

        if not include_test:
            # Control charts must reflect REAL runs only — exclude seeded /
            # synthetic rows (TEST_DATA* flags, SYNTHETIC_ batches).
            sql += (" AND r.flag NOT LIKE 'TEST_DATA%'"
                    " AND r.batch_id NOT LIKE 'SYNTHETIC_%'")

        if qc_level is not None:
            sql += " AND r.qc_level=?"
            params.append(qc_level)
        if method is not None:
            sql += " AND r.method=?"
            params.append(method)
        if analyst is not None:
            sql += " AND (r.analyst=? OR b.analyst=?)"
            params.extend([analyst, analyst])
        if instrument_id is not None:
            sql += " AND r.instrument_id=?"
            params.append(instrument_id)

        # Wrap in subquery to get the N most-recent then return in chart order
        inner = sql + " ORDER BY r.run_date DESC, r.id DESC LIMIT ?"
        params.append(limit)
        outer = "SELECT * FROM ({}) ORDER BY run_date ASC, id ASC".format(inner)

        with self._connect() as conn:
            rows = conn.execute(outer, params).fetchall()
        return [dict(r) for r in rows]

    def get_methods(self):
        """Return distinct method identifiers stored in qc_results."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT method FROM qc_results "
                "WHERE result_status='active' AND method != '' "
                "ORDER BY method"
            ).fetchall()
        return [r[0] for r in rows]

    def get_analytes(self, qc_type=None, method=None):
        sql = ("SELECT DISTINCT analyte FROM qc_results "
               "WHERE result_status='active'")
        params = []
        if qc_type:
            sql += " AND qc_type=?"
            params.append(qc_type)
        if method:
            sql += " AND method=?"
            params.append(method)
        sql += " ORDER BY analyte"
        with self._connect() as conn:
            return [r[0] for r in conn.execute(sql, params).fetchall()]

    def get_qc_types(self):
        with self._connect() as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT qc_type FROM qc_results "
                "WHERE result_status='active' ORDER BY qc_type"
            ).fetchall()]

    def get_qc_levels(self, qc_type=None, analyte=None):
        sql = ("SELECT DISTINCT qc_level FROM qc_results "
               "WHERE result_status='active'")
        params = []
        if qc_type:
            sql += " AND qc_type=?"
            params.append(qc_type)
        if analyte:
            sql += " AND analyte=?"
            params.append(analyte)
        sql += " ORDER BY qc_level"
        with self._connect() as conn:
            return [r[0] for r in conn.execute(sql, params).fetchall()]

    def get_analysts(self):
        """Return distinct analyst names from both batches and results."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT analyst FROM ("
                "  SELECT analyst FROM batches WHERE analyst != '' "
                "  UNION "
                "  SELECT analyst FROM qc_results WHERE analyst != ''"
                ") ORDER BY analyst"
            ).fetchall()
        return [r[0] for r in rows]

    def get_instruments(self):
        """Return distinct instrument IDs."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT instrument_id FROM ("
                "  SELECT instrument_id FROM batches WHERE instrument_id != '' "
                "  UNION "
                "  SELECT instrument_id FROM qc_results WHERE instrument_id != ''"
                ") ORDER BY instrument_id"
            ).fetchall()
        return [r[0] for r in rows]

    # ── Calibration tracking ────────────────────────────────────────────────

    def add_calibration(self, batch_id, run_date, analyte, r2, n_levels,
                        equation="", fit_type="", weight_type="",
                        min_level=None, max_level=None, method="",
                        analyst="", instrument_id="", status="pending",
                        notes="", levels=None):
        """
        Record a calibration curve result.

        levels: optional list of dicts with keys:
                level, expected, calculated, pct_deviation, passed
        Returns the inserted calibration id.
        """
        now = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO calibrations "
                "(batch_id,run_date,analyte,method,analyst,instrument_id,"
                " equation,fit_type,weight_type,r2,n_levels,min_level,"
                " max_level,status,notes,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, run_date, analyte, method, analyst, instrument_id,
                 equation, fit_type, weight_type, r2, n_levels, min_level,
                 max_level, status, notes, now),
            )
            cal_id = cur.lastrowid
            if levels:
                for lv in levels:
                    conn.execute(
                        "INSERT INTO calibration_levels "
                        "(calibration_id,level,expected,calculated,"
                        " pct_deviation,passed,response_ratio) VALUES (?,?,?,?,?,?,?)",
                        (cal_id,
                         lv.get("level"), lv.get("expected"),
                         lv.get("calculated"), lv.get("pct_deviation"),
                         int(bool(lv.get("passed", True))),
                         lv.get("response_ratio")),
                    )
        return cal_id

    def get_calibrations(self, analyte=None, method=None, limit=50):
        """Return recent calibration records, newest first.
        Synthetic/seeded batches are always excluded (same policy as
        get_chart_data) so the calibration pane reflects real runs only."""
        sql = ("SELECT * FROM calibrations WHERE 1=1"
               " AND batch_id NOT LIKE 'SYNTHETIC_%'")
        params = []
        if analyte:
            sql += " AND analyte=?"
            params.append(analyte)
        if method:
            sql += " AND method=?"
            params.append(method)
        sql += " ORDER BY run_date DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_calibration_levels(self, calibration_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM calibration_levels WHERE calibration_id=? "
                "ORDER BY level ASC",
                (calibration_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_calibrations_for_run(self, run_date, method=None, batch_id=None):
        """Return all calibrations for a run date, optionally filtered."""
        sql = "SELECT * FROM calibrations WHERE run_date=?"
        params = [run_date]
        if method:
            sql += " AND method=?"
            params.append(method)
        if batch_id:
            sql += " AND batch_id=?"
            params.append(batch_id)
        sql += " ORDER BY analyte ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_qc_for_run(self, run_date, analyte=None, batch_id=None,
                       qc_types=None):
        """Return active QC results for a run date, optionally filtered."""
        sql = ("SELECT * FROM qc_results "
               "WHERE run_date=? AND result_status='active'")
        params = [run_date]
        if analyte:
            sql += " AND analyte=?"
            params.append(analyte)
        if batch_id:
            sql += " AND batch_id=?"
            params.append(batch_id)
        if qc_types:
            placeholders = ",".join("?" * len(qc_types))
            sql += " AND qc_type IN ({0})".format(placeholders)
            params.extend(qc_types)
        sql += " ORDER BY qc_type ASC, qc_level ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_run_dates(self, method=None, limit=30):
        """Return distinct run_dates (newest first) that have calibration data."""
        sql = "SELECT DISTINCT run_date FROM calibrations WHERE 1=1"
        params = []
        if method:
            sql += " AND method=?"
            params.append(method)
        sql += " ORDER BY run_date DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [r[0] for r in rows]

    def approve_run(self, run_date, approved_by, method=None, batch_id=None):
        """Set approved_by + approved_at on all calibrations for a run date."""
        import datetime
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        sql = ("UPDATE calibrations SET approved_by=?, approved_at=? "
               "WHERE run_date=?")
        params = [approved_by, now, run_date]
        if method:
            sql += " AND method=?"
            params.append(method)
        if batch_id:
            sql += " AND batch_id=?"
            params.append(batch_id)
        with self._connect() as conn:
            conn.execute(sql, params)
            affected = conn.execute("SELECT changes()").fetchone()[0]
        logger.info("approve_run: approved %d calibrations for %s by %s",
                    affected, run_date, approved_by)
        return affected

    def update_calibration_override(self, calibration_id, fit_type_override="",
                                    weight_override="", origin_override=""):
        """Persist reviewer-selected fit overrides on a calibration row."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE calibrations SET fit_type_override=?, "
                "weight_override=?, origin_override=? WHERE id=?",
                (fit_type_override, weight_override, origin_override,
                 calibration_id),
            )
        logger.info("calibration %s override: fit=%s weight=%s origin=%s",
                    calibration_id, fit_type_override, weight_override,
                    origin_override)

    def get_summary(self):
        """Return per-qc_type counts and failure counts (active results only)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT qc_type, COUNT(*) AS n, "
                "SUM(CASE WHEN passed=0 THEN 1 ELSE 0 END) AS failures "
                "FROM qc_results WHERE result_status='active' "
                "GROUP BY qc_type ORDER BY qc_type"
            ).fetchall()
        return [dict(r) for r in rows]
