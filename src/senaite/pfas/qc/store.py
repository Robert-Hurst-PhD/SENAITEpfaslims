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

from senaite.pfas.qc.qc_types import normalize_qc_type

logger = logging.getLogger("senaite.pfas.qc.store")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")


class DuplicateBatchError(Exception):
    """Raised when active results for a batch already exist."""


# ── Schema ─────────────────────────────────────────────────────────────────────

# The schema (tables + numbered migrations) lives in senaite.pfas.qc_schema,
# shared with the pipeline worker.


def _now_iso():
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ── Store ───────────────────────────────────────────────────────────────────────

# the measures an LFSMD row carries in its qc_level ("RPD <injection>")
MEASURE_LEVELS = ("RPD", "Recovery")


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
        try:
            from senaite.pfas import qc_schema
        except ImportError:                     # loaded by path (tests)
            import qc_schema
        conn = self._connect()
        try:
            # a database already at this schema needs no DDL: every page built
            # a store per call and re-ran the whole schema and a commit (62
            # times on the Manager's landing)
            if conn.execute("PRAGMA user_version").fetchone()[0] >= qc_schema.VERSION:
                return
            qc_schema.ensure(conn)
        finally:
            conn.close()

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

    # ── Per-injection detail ──────────────────────────────────────────

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

    def get_injection_rows(self, batch_ids, names):
        """Per-injection rows of these runs (worksheet ids) whose injection
        name or parsed sample id is one of `names` -- what the certificate's
        surrogate / internal-standard sub-table chooses from."""
        batch_ids = [b for b in batch_ids or [] if b]
        names = [n for n in names or [] if n]
        if not batch_ids or not names:
            return []
        sql = ("SELECT * FROM injection_results WHERE batch_id IN ({0}) "
               "AND (injection_name IN ({1}) OR sample_id IN ({1})) ORDER BY injection_name, analyte"
               .format(",".join("?" * len(batch_ids)), ",".join("?" * len(names))))
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, batch_ids + names + names).fetchall()]

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
                # Single normalization point: every QC type entering the store
                # is folded to its canonical code (uppercase, LCS -> LFB, ...)
                # so the stored text is always uniform. See qc/qc_types.py.
                qtype   = normalize_qc_type(r.get("qc_type", ""))
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

    def clear_result(self, batch_id, result_id, by, note):
        """A reviewer clears one run-plan gap with a note. Only an UNEVALUATED "Run plan" row of this batch can be
        cleared; the gate reads active and unevaluated rows only. True if a
        row changed."""
        from senaite.pfas.qc_schema import ensure
        if not (note or u"").strip():
            return False
        with self._connect() as conn:
            ensure(conn)
            cur = conn.execute(
                "UPDATE qc_results SET result_status='cleared', cleared_by=?, "
                "cleared_at=?, cleared_note=? WHERE id=? AND batch_id=? "
                "AND qc_type='Run plan' AND result_status='unevaluated'",
                (by, _now_iso(), note.strip(), int(result_id), batch_id))
            return cur.rowcount > 0

    def run_plan_rows(self, batch_id):
        """Every run-plan gap of a batch, open or cleared, for Data Review."""
        with self._connect() as conn:
            have = [r[1] for r in conn.execute("PRAGMA table_info(qc_results)")]
            if "cleared_note" not in have:
                return []
            rows = conn.execute(
                "SELECT * FROM qc_results WHERE batch_id=? AND qc_type='Run plan' "
                "AND result_status IN ('unevaluated', 'cleared') ORDER BY id",
                (batch_id,)).fetchall()
        return [dict(r) for r in rows]

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

    # ── Control-chart review (dismiss a warning / remove a point) ───────────

    def annotate(self, result_id, action, reason, by_user, rule=u""):
        """Record a dismissal ('dismissed', with the warning's rule) or a removal
        ('excluded'). A reason is required: it is the audit record."""
        if action not in ("dismissed", "excluded"):
            raise ValueError("unknown chart action %r" % action)
        reason = (reason or u"").strip()
        if not reason:
            raise ValueError("a reason is required")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chart_annotations "
                "(result_id, action, rule, reason, by_user, at) VALUES (?,?,?,?,?,?)",
                (int(result_id), action, rule if action == "dismissed" else u"",
                 reason, by_user or u"", _now_iso()))

    def unannotate(self, result_id, action, rule=u""):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chart_annotations WHERE result_id=? AND action=? AND rule=?",
                (int(result_id), action, rule if action == "dismissed" else u""))

    def get_annotations(self, result_ids):
        """[{result_id, action, rule, reason, by_user, at}] for these results."""
        ids = [int(i) for i in result_ids or [] if i is not None]
        if not ids:
            return []
        out = []
        with self._connect() as conn:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                rows = conn.execute(
                    "SELECT result_id, action, rule, reason, by_user, at FROM chart_annotations "
                    "WHERE result_id IN (%s) ORDER BY at" % ",".join("?" * len(chunk)), chunk)
                out.extend(dict(r) for r in rows)
        return out

    # ── Read (chart data) ───────────────────────────────────────────────────

    def get_chart_data(self, analyte, qc_type, qc_level=None, method=None,
                       analyst=None, instrument_id=None, limit=20,
                       include_superseded=False, include_test=False,
                       date_from=None, date_to=None):
        """
        Return ordered list of dicts for Levey-Jennings charting.

        Only returns result_status='active' rows by default.
        Set include_superseded=True to show the full historical record
        (useful for analyst performance review).

        date_from / date_to (inclusive, 'YYYY-MM-DD') restrict to a run-date
        window; run_date is stored as ISO text so string comparison sorts
        chronologically.

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

        sql = ("SELECT r.id, r.run_date, r.value, r.expected_value, r.flag, r.passed, r.batch_id, "
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

        if qc_level is not None:
            # an LFSMD measure ("RPD", "Recovery") across runs: stored per
            # duplicate injection since 2026-10-09 ("RPD WS-1-LFSMD1")
            sql += " AND (r.qc_level=? OR r.qc_level LIKE ?)"
            params.extend([qc_level, qc_level + " %" if qc_level in MEASURE_LEVELS else qc_level])
        if method is not None:
            sql += " AND r.method=?"
            params.append(method)
        if analyst is not None:
            sql += " AND (r.analyst=? OR b.analyst=?)"
            params.extend([analyst, analyst])
        if instrument_id is not None:
            sql += " AND r.instrument_id=?"
            params.append(instrument_id)
        if date_from:
            sql += " AND r.run_date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND r.run_date <= ?"
            params.append(date_to)

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

    def date_bounds(self):
        """Return (min_run_date, max_run_date) across active QC results as
        ISO 'YYYY-MM-DD' strings, or (None, None) when empty. Used to bound
        the control-chart date-range picker to what the database actually
        holds."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(run_date), MAX(run_date) FROM qc_results "
                "WHERE result_status='active' AND run_date != ''"
            ).fetchone()
        if not row or row[0] is None:
            return (None, None)
        return (str(row[0])[:10], str(row[1])[:10])

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
            levels = [r[0] for r in conn.execute(sql, params).fetchall()]
        # the LFSMD's two measures, not one entry per duplicate injection
        out = []
        for lv in levels:
            head = (lv or u"").split(u" ")[0]
            lv = head if head in MEASURE_LEVELS else lv
            if lv not in out:
                out.append(lv)
        return out

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
            # the worksheet that ran it uses it
            conn.execute("INSERT OR IGNORE INTO calibration_uses (batch_id, calibration_id, run_date, "
                         "created_at) VALUES (?,?,?,?)", (batch_id, cal_id, run_date, now))
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

    def calibration_archive_runs(self, method=None, analyte=None, limit=30):
        """The calibration runs on record, newest first: one per worksheet
        that RAN a curve set ({run_date, batch_id, method, n}); a worksheet
        that only re-used a curve is not a run of its own."""
        sql = ("SELECT run_date, batch_id, method, COUNT(*) AS n, MAX(id) AS last_id "
               "FROM calibrations WHERE batch_id NOT LIKE 'SYNTHETIC_%'")
        params = []
        if method:
            sql += " AND method=?"
            params.append(method)
        if analyte:
            sql += " AND analyte=?"
            params.append(analyte)
        # newest recorded first (a test run may carry a future date)
        sql += " GROUP BY run_date, batch_id, method ORDER BY last_id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def calibration_run_curves(self, run_date, batch_id):
        """The curves one worksheet ran on one date."""
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM calibrations WHERE run_date=? AND batch_id=? ORDER BY analyte",
                (run_date, batch_id)).fetchall()]

    def calibration_facets(self, method=None):
        """(methods, analytes) on record; analytes of `method` when given."""
        with self._connect() as conn:
            methods = [r[0] for r in conn.execute(
                "SELECT DISTINCT method FROM calibrations WHERE method != '' ORDER BY method")]
            sql, params = "SELECT DISTINCT analyte FROM calibrations WHERE analyte != ''", []
            if method:
                sql += " AND method=?"
                params.append(method)
            analytes = [r[0] for r in conn.execute(sql + " ORDER BY analyte", params)]
        return methods, analytes

    def get_calibration_levels_many(self, calibration_ids):
        """{calibration id: [level rows]} for many curves in one query (the
        archive asked once per curve)."""
        ids = sorted(set(i for i in calibration_ids if i is not None))
        out = dict((i, []) for i in ids)
        if not ids:
            return out
        with self._connect() as conn:
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                rows = conn.execute(
                    "SELECT * FROM calibration_levels WHERE calibration_id IN (%s) "
                    "ORDER BY calibration_id, level ASC" % ",".join("?" * len(chunk)), chunk).fetchall()
                for r in rows:
                    out[r["calibration_id"]].append(dict(r))
        return out

    def get_calibration_levels(self, calibration_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM calibration_levels WHERE calibration_id=? "
                "ORDER BY level ASC",
                (calibration_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_calibrations_for_run(self, run_date, method=None, batch_id=None):
        """Return all calibrations for a run date, optionally filtered. With a
        worksheet: the curves it used, whatever date they were run on (a
        re-used curve keeps its own)."""
        if batch_id:
            rows = self.calibrations_for_batch(batch_id)
            return [r for r in rows if not method or r.get("method") == method]
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

    def import_problems(self, batch_id):
        """The worksheet's run files the worker has not imported: retrying
        or failed, with the attempts and the last error (pfas_pipeline.
        import_log). [] when every delivery imported."""
        if not batch_id:
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT file, status, attempts, error, updated_at FROM run_imports "
                    "WHERE batch_id=? AND status != 'imported' ORDER BY updated_at DESC",
                    (batch_id,)).fetchall()
            except Exception:                               # noqa: BLE001
                return []
        return [dict(r) for r in rows]

    def get_qc_for_run(self, run_date, analyte=None, batch_id=None,
                       qc_types=None, statuses=None):
        """QC results for a run date, optionally filtered.

        `statuses` defaults to active AND unevaluated. An unevaluated row
        records a criterion the method never configured; hiding it behind an
        'active'-only filter is what made the whole hold-the-report path inert
        — the row was written, and the only reader could not see it.
        """
        statuses = list(statuses or ("active", "unevaluated"))
        # run_date None with a worksheet: its results whatever the date (a
        # re-used curve's date is not the worksheet's)
        sql = ("SELECT * FROM qc_results "
               "WHERE (? IS NULL OR run_date=?) AND result_status IN ({0})".format(
                   ",".join("?" * len(statuses))))
        params = [run_date, run_date] + statuses
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
        """Approve the calibrations of a run date (a worksheet's, with
        batch_id): who, when, and status "approved" -- a curve rejected and
        then approved must not keep reading as rejected."""
        import datetime
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        if batch_id:
            # the curves the worksheet used (approved once, wherever they were
            # run); its own rejection of them is lifted
            sql = ("UPDATE calibrations SET approved_by=?, approved_at=?, status='approved' "
                   "WHERE id IN (SELECT calibration_id FROM calibration_uses WHERE batch_id=?)")
            params = [approved_by, now, batch_id]
        else:
            sql = ("UPDATE calibrations SET approved_by=?, approved_at=?, status='approved' "
                   "WHERE run_date=?")
            params = [approved_by, now, run_date]
        if method:
            sql += " AND method=?"
            params.append(method)
        with self._connect() as conn:
            conn.execute(sql, params)
            affected = conn.execute("SELECT changes()").fetchone()[0]
            if batch_id:
                conn.execute("UPDATE calibration_uses SET status='', notes='' WHERE batch_id=?",
                             (batch_id,))
        logger.info("approve_run: approved %d calibrations for %s by %s",
                    affected, run_date, approved_by)
        return affected

    def reject_run(self, batch_id, rejected_by, note):
        """Reject a worksheet's calibration with a note (Data Review). The rejection is the worksheet's: it holds
        that worksheet only; another that used the same curve keeps its
        approval. True if a row changed."""
        if not (note or u"").strip():
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE calibration_uses SET status='rejected', notes=? WHERE batch_id=?",
                (u"rejected by %s: %s" % (rejected_by, note.strip()), batch_id))
            return cur.rowcount > 0

    def calibrations_for_batch(self, batch_id):
        """The curves the worksheet used (its own and any it re-used), each
        with `used_from` (the worksheet that ran it) and the worksheet's own
        rejection laid over the curve's state."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.*, u.status AS use_status, u.notes AS use_notes "
                "FROM calibration_uses u JOIN calibrations c ON c.id = u.calibration_id "
                "WHERE u.batch_id=? ORDER BY c.analyte", (batch_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["used_from"] = d.get("batch_id")
            if d.pop("use_status", u"") == u"rejected":
                d["status"], d["notes"] = u"rejected", d.get("use_notes") or u""
                d["approved_by"], d["approved_at"] = u"", u""
            d.pop("use_notes", None)
            out.append(d)
        return out

    def uses_of(self, calibration_ids):
        """{calibration_id: [worksheet ids]} that used each curve."""
        out = {}
        ids = list(calibration_ids or [])
        if not ids:
            return out
        with self._connect() as conn:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                for r in conn.execute(
                        "SELECT calibration_id, batch_id FROM calibration_uses WHERE calibration_id IN "
                        "(%s) ORDER BY batch_id" % ",".join("?" * len(chunk)), chunk):
                    out.setdefault(r[0], []).append(r[1])
        return out

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
