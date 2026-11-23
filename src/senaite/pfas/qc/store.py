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

import json
import logging
import os
import re
import sqlite3


logger = logging.getLogger("senaite.pfas.qc.store")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")


# ── Schema ─────────────────────────────────────────────────────────────────────

# The schema (tables + numbered migrations) lives in senaite.pfas.qc_schema,
# shared with the pipeline worker.


def _now_iso():
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _names(analyte):
    """The stored names a chart query reads for one analyte: a name, or
    every spelling it was stored under (a list)."""
    if isinstance(analyte, (list, tuple)):
        return [a for a in analyte if a] or [u""]
    return [analyte]


# ── Store ───────────────────────────────────────────────────────────────────────

# the measures an LFSMD row carries in its qc_level ("RPD <injection>")
MEASURE_LEVELS = ("RPD", "Recovery")

# A check standard's qc_level is its injection's key; a level is what the
# injections share: the expected concentration of a CCV / ICV, the CAL-n of
# a calibrator.
LEVEL_BY_EXPECTED = ("CCV", "ICV")
_CAL_LEVEL = re.compile(r"-CAL-(\d+)-")


def _g(x):
    return u"%g" % float(x)


def level_options(qc_type, rows):
    """[(value, label)] for the QC level filter from rows of (qc_level,
    expected_value, count). Values: "exp:<expected>", "cal:<n>", or an LFSMD
    measure; a type whose qc_level names injections offers none."""
    if qc_type in LEVEL_BY_EXPECTED:
        counts = {}
        for _lv, exp, n in rows:
            if exp is not None:
                counts[float(exp)] = counts.get(float(exp), 0) + int(n)
        return [(u"exp:%s" % _g(e), u"Expected %s \u00b7 %d %s%s" % (_g(e), n, qc_type, u"" if n == 1 else u"s"))
                for e, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    if qc_type == "Calibration":
        counts = {}
        for lv, _exp, n in rows:
            m = _CAL_LEVEL.search(lv or u"")
            if m:
                counts[int(m.group(1))] = counts.get(int(m.group(1)), 0) + int(n)
        return [(u"cal:%d" % k, u"CAL-%d \u00b7 %d injection%s" % (k, n, u"" if n == 1 else u"s"))
                for k, n in sorted(counts.items())]
    out = []
    for lv, _exp, _n in rows:
        head = (lv or u"").split(u" ")[0]
        if head in MEASURE_LEVELS and (head, head) not in out:
            out.append((head, head))
    return out


class QCResultStore(object):
    """
    Persistent QC result store with batch lifecycle tracking.

    The worker writes the results (pfas_pipeline/qc_store.persist_qc_results);
    the add-on reads them and records the review acts.
    """

    def _ensure_dir(self):
        d = os.path.dirname(self.db_path)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d)
            except OSError:
                pass

    def __init__(self, db_path=None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._ensure_dir()
        self._ensure_schema()


    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self):
        from senaite.pfas import qc_schema
        conn = self._connect()
        try:
            qc_schema.ensure(conn)       # a database at the schema: one PRAGMA read
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


    def has_qc_results(self, batch_id):
        """True when the run of `batch_id` stored a QC row: a batch
        registered with none is not a run imported."""
        if not batch_id:
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM qc_results WHERE batch_id=? LIMIT 1", (batch_id,)).fetchone()
        return row is not None

    # ── Reanalysis workflow ─────────────────────────────────────────────────

    def clear_result(self, batch_id, result_id, by, note):
        """A reviewer clears one run-plan gap with a note. Only an UNEVALUATED
        "Run plan" row of this batch can be cleared; the gate reads active and
        unevaluated rows only. True if a row changed."""
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

    def annotate(self, result_id, action, reason, by_user, rule=u""):
        """Record a dismissal ('dismissed', with the warning's rule) or a removal
        ('excluded'). A reason is required: it is the audit record."""
        if action not in ("dismissed", "excluded"):
            raise ValueError("unknown chart action %r" % action)
        reason = (reason or u"").strip()
        if not reason:
            raise ValueError("a reason is required")
        rule = rule if action == "dismissed" else u""
        with self._connect() as conn:
            prev = self._annotation(conn, result_id, action, rule)
            conn.execute(
                "INSERT OR REPLACE INTO chart_annotations "
                "(result_id, action, rule, reason, by_user, at) VALUES (?,?,?,?,?,?)",
                (int(result_id), action, rule, reason, by_user or u"", _now_iso()))
            self._log(conn, "chart_annotation", result_id, action, by_user,
                      {"rule": rule, "reason": reason, "replaced": prev})

    def unannotate(self, result_id, action, rule=u"", by_user=u""):
        """Undo a dismissal or removal: the current row goes, the review log
        keeps it with who undid it and when."""
        rule = rule if action == "dismissed" else u""
        with self._connect() as conn:
            prev = self._annotation(conn, result_id, action, rule)
            conn.execute(
                "DELETE FROM chart_annotations WHERE result_id=? AND action=? AND rule=?",
                (int(result_id), action, rule))
            if prev:
                self._log(conn, "chart_annotation", result_id, "undo " + action, by_user,
                          {"rule": rule, "removed": prev})

    @staticmethod
    def _annotation(conn, result_id, action, rule):
        row = conn.execute("SELECT reason, by_user, at FROM chart_annotations "
                           "WHERE result_id=? AND action=? AND rule=?",
                           (int(result_id), action, rule)).fetchone()
        return dict(zip(("reason", "by_user", "at"), row)) if row else None

    @staticmethod
    def _log(conn, kind, ref, action, by_user, detail):
        """Append one review act to qc_review_log (never edited or deleted)."""
        conn.execute("INSERT INTO qc_review_log (at, by_user, kind, ref, action, detail) "
                     "VALUES (?,?,?,?,?,?)",
                     (_now_iso(), by_user or u"", kind, u"%s" % ref, action, json.dumps(detail, sort_keys=True)))

    # a run rejected at review as invalid: its batch status, and the QC
    # statuses it voids (every row a gate, chart or comparison reads)
    VOIDED_RUN = "failed"
    VOIDABLE = ("active", "unevaluated", "cleared", "flagged_reanalysis")

    def void_run(self, batch_id, by_user, reason):
        """A run rejected as invalid leaves the control charts, the
        Calibration Archive and the blank comparisons: its QC rows are voided
        and the run is marked failed ("all results voided"). The act is
        logged; nothing is deleted. Returns the rows voided."""
        with self._connect() as conn:
            n = conn.execute(
                "UPDATE qc_results SET result_status='voided' WHERE batch_id=? AND result_status IN (%s)"
                % ",".join("?" * len(self.VOIDABLE)), (batch_id,) + self.VOIDABLE).rowcount
            conn.execute("UPDATE batches SET status=?, notes=?, updated_at=? WHERE batch_id=?",
                         (self.VOIDED_RUN, u"voided: %s" % (reason or u""), _now_iso(), batch_id))
            self._log(conn, "run", batch_id, "voided", by_user, {"reason": reason or u"", "rows": n})
        return n

    # the calibration archive's runs leave out a voided run's curves
    NOT_VOIDED = " AND batch_id NOT IN (SELECT batch_id FROM batches WHERE status='failed')"

    def review_log(self, kind, ref):
        """[{at, by_user, action, detail}] of one record's review acts, oldest first."""
        with self._connect() as conn:
            rows = conn.execute("SELECT at, by_user, action, detail FROM qc_review_log "
                                "WHERE kind=? AND ref=? ORDER BY id", (kind, u"%s" % ref)).fetchall()
        return [{"at": r[0], "by_user": r[1], "action": r[2], "detail": json.loads(r[3])} for r in rows]

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
                       date_from=None, date_to=None, exclude_batches=()):
        """
        Return ordered list of dicts for Levey-Jennings charting.

        Only returns result_status='active' rows by default.
        Set include_superseded=True to show the full historical record.

        date_from / date_to (inclusive, 'YYYY-MM-DD') restrict to a run-date
        window; run_date is stored as ISO text so string comparison sorts
        chronologically.

        Default limit=20 matches one month of weekly batches; set limit=200+
        for annual review. Each row carries the window the worker judged it
        in (limit_low / limit_high), when it recorded one.
        """
        where, params = self._chart_where(
            analyte, qc_type, qc_level, method, analyst, instrument_id,
            include_superseded, include_test, date_from, date_to, exclude_batches)
        sql = ("SELECT r.id, r.run_date, r.value, r.expected_value, r.flag, r.passed, r.batch_id, "
               "       r.analyst, r.instrument_id, r.result_status, r.prov_key, r.qc_level, r.method, "
               "       r.limit_low, r.limit_high, "
               "       b.analyst AS batch_analyst " + where)

        # Wrap in subquery to get the N most-recent then return in chart order
        inner = sql + " ORDER BY r.run_date DESC, r.id DESC LIMIT ?"
        params.append(limit)
        outer = "SELECT * FROM ({}) ORDER BY run_date ASC, id ASC".format(inner)

        with self._connect() as conn:
            rows = conn.execute(outer, params).fetchall()
        return [dict(r) for r in rows]

    def count_chart_data(self, analyte, qc_type, qc_level=None, method=None,
                         analyst=None, instrument_id=None,
                         include_superseded=False, include_test=False,
                         date_from=None, date_to=None, exclude_batches=(), drawn=None):
        """How many results get_chart_data's filters hold with no limit, the
        points removed from the chart left out: what "of N recorded" says.
        `drawn` counts only the rows the chart can draw: "value" (a value
        stored), "recovery" (a value and an expected value that is not 0);
        None every row."""
        where, params = self._chart_where(
            analyte, qc_type, qc_level, method, analyst, instrument_id,
            include_superseded, include_test, date_from, date_to, exclude_batches)
        if drawn in ("value", "recovery"):
            where += " AND r.value IS NOT NULL"
        if drawn == "recovery":
            where += " AND r.expected_value IS NOT NULL AND r.expected_value != 0"
        sql = ("SELECT COUNT(*) " + where +
               " AND r.id NOT IN (SELECT result_id FROM chart_annotations WHERE action='excluded')")
        with self._connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    @staticmethod
    def _chart_where(analyte, qc_type, qc_level, method, analyst, instrument_id,
                     include_superseded, include_test, date_from, date_to, exclude_batches):
        """The chart's FROM / WHERE and its parameters, one for the fetch and
        the count."""
        if include_superseded:
            status_clause = ("result_status IN "
                             "('active','superseded','flagged_reanalysis')")
        else:
            status_clause = "result_status='active'"

        names = _names(analyte)
        sql = ("FROM qc_results r "
               "LEFT JOIN batches b ON r.batch_id = b.batch_id "
               "WHERE r.analyte IN (%s) AND r.qc_type=? AND " % ",".join("?" * len(names))
               + status_clause)
        params = names + [qc_type]

        if not include_test:
            # control charts show real runs only: no TEST_DATA* flags, no
            # SYNTHETIC_ batches
            sql += (" AND r.flag NOT LIKE 'TEST_DATA%'"
                    " AND r.batch_id NOT LIKE 'SYNTHETIC_%'")
        hidden = sorted(set(exclude_batches or ()))
        if hidden:
            # study runs a study has not opted into the charts
            sql += " AND r.batch_id NOT IN (%s)" % ",".join("?" * len(hidden))
            params.extend(hidden)

        if qc_level is not None and qc_level.startswith("exp:"):
            # a check standard's level: its expected concentration
            sql += " AND r.expected_value=?"
            params.append(float(qc_level[4:]))
        elif qc_level is not None and qc_level.startswith("cal:"):
            sql += " AND r.qc_level LIKE ?"
            params.append("%%-CAL-%d-%%" % int(qc_level[4:]))
        elif qc_level is not None:
            # an LFSMD measure ("RPD", "Recovery") across runs, stored per
            # duplicate injection ("RPD WS-1-LFSMD1")
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
        return sql, params

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

    def get_level_options(self, qc_type=None, analyte=None, method=None):
        """[(value, label)]: the QC level filter's options (level_options)."""
        if not qc_type:
            return []
        sql = ("SELECT qc_level, expected_value, COUNT(*) FROM qc_results "
               "WHERE result_status='active' AND qc_type=?")
        params = [qc_type]
        if analyte:
            names = _names(analyte)
            sql += " AND analyte IN (%s)" % ",".join("?" * len(names))
            params.extend(names)
        if method:
            sql += " AND method=?"
            params.append(method)
        sql += " GROUP BY qc_level, expected_value"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return level_options(qc_type, rows)

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


    def get_calibrations(self, analyte=None, method=None, limit=50):
        """Return recent calibration records, newest first.
        Synthetic/seeded batches are always excluded (same policy as
        get_chart_data) so the calibration pane reflects real runs only."""
        sql = ("SELECT * FROM calibrations WHERE 1=1"
               " AND batch_id NOT LIKE 'SYNTHETIC_%'" + self.NOT_VOIDED)
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
        that only re-used a curve is not a run of its own, and a voided run
        (void_run) is not listed."""
        sql = ("SELECT run_date, batch_id, method, COUNT(*) AS n, MAX(id) AS last_id "
               "FROM calibrations WHERE batch_id NOT LIKE 'SYNTHETIC_%'" + self.NOT_VOIDED)
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
                "SELECT DISTINCT method FROM calibrations WHERE method != ''" + self.NOT_VOIDED
                + " ORDER BY method")]
            sql, params = "SELECT DISTINCT analyte FROM calibrations WHERE analyte != ''" + self.NOT_VOIDED, []
            if method:
                sql += " AND method=?"
                params.append(method)
            analytes = [r[0] for r in conn.execute(sql + " ORDER BY analyte", params)]
        return methods, analytes

    def get_calibration_levels_many(self, calibration_ids):
        """{calibration id: [level rows]} for many curves in one query."""
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
                    # dict first: under Python 2 a sqlite3.Row refuses a
                    # unicode key (this module has unicode_literals)
                    d = dict(r)
                    out[d["calibration_id"]].append(d)
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

    def import_problems(self, batch_id, refused=False):
        """The worksheet's run files the worker has not imported: retrying
        or failed, with the attempts and the last error (pfas_pipeline.
        import_log). [] when every delivery imported. A delivery refused
        for a worksheet that takes no further run is no problem of the
        record that stands: listed only with `refused`."""
        if not batch_id:
            return []
        skip = ("imported",) if refused else ("imported", "refused")
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT file, status, attempts, error, updated_at FROM run_imports "
                    "WHERE batch_id=? AND status NOT IN (%s) ORDER BY updated_at DESC"
                    % ",".join("?" * len(skip)), (batch_id,) + skip).fetchall()
            except sqlite3.Error:
                return []
        return [dict(r) for r in rows]

    def import_log(self, batch_id):
        """Every run file delivered for the worksheet and what became of it
        (pfas_pipeline.import_log): [{file, status, attempts, error,
        updated_at}], newest first; [] when none is on record."""
        if not batch_id:
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT file, status, attempts, error, updated_at FROM run_imports "
                    "WHERE batch_id=? ORDER BY updated_at DESC", (batch_id,)).fetchall()
            except sqlite3.Error:
                return []
        return [dict(r) for r in rows]

    def get_qc_for_run(self, run_date, analyte=None, batch_id=None,
                       qc_types=None, statuses=None):
        """QC results for a run date, optionally filtered.

        `statuses` defaults to active AND unevaluated: an unevaluated row
        records a criterion the method never configured, and it holds the
        report, so it is read too.
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
            lifted = []
            if batch_id:
                lifted = [dict(zip(("calibration_id", "status", "notes"), r)) for r in conn.execute(
                    "SELECT calibration_id, status, notes FROM calibration_uses WHERE batch_id=? AND status!=''",
                    (batch_id,))]
                conn.execute("UPDATE calibration_uses SET status='', notes='' WHERE batch_id=?",
                             (batch_id,))
            self._log(conn, "calibration", batch_id or run_date, "approved", approved_by,
                      {"run_date": run_date, "method": method, "curves": affected, "lifted": lifted})
        logger.info("approve_run: approved %d calibrations for %s by %s",
                    affected, run_date, approved_by)
        return affected

    def reject_run(self, batch_id, rejected_by, note):
        """Reject a worksheet's calibration with a note (Data Review). The
        rejection holds that worksheet only; another that used the same curve
        keeps its approval. True if a row changed."""
        if not (note or u"").strip():
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE calibration_uses SET status='rejected', notes=? WHERE batch_id=?",
                (u"rejected by %s: %s" % (rejected_by, note.strip()), batch_id))
            if cur.rowcount > 0:
                self._log(conn, "calibration", batch_id, "rejected", rejected_by, {"note": note.strip()})
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
                                    weight_override="", origin_override="", by_user=u""):
        """Persist reviewer-selected fit overrides on a calibration row; the
        review log keeps who, when and what they replaced."""
        with self._connect() as conn:
            row = conn.execute("SELECT fit_type_override, weight_override, origin_override "
                               "FROM calibrations WHERE id=?", (calibration_id,)).fetchone()
            before = dict(zip(("fit", "weight", "origin"), row)) if row else None
            self._log(conn, "calibration_override", calibration_id, "override", by_user,
                      {"before": before, "after": {"fit": fit_type_override, "weight": weight_override,
                                                   "origin": origin_override}})
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
