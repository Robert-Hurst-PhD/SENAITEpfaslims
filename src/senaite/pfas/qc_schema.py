# -*- coding: utf-8 -*-
"""The QC results database schema (/data/qc/pfas_qc_results.db), in ONE place.


Both processes write this database: the add-on (senaite.pfas.qc.store) and
the pipeline worker (qc_store, injection_store, seed_calibrations). Each used
to carry its own CREATE TABLE and ALTER list; the worker's seed tool had a
qc_results without columns its own inserts used. Now all of them call
`ensure(conn)` here (the worker loads this file from the add-on mount).

Migrations are numbered and tracked in SQLite's `PRAGMA user_version`. A
database that predates the numbering (version 0, columns already present)
is brought to the current number without change: an ALTER that finds its
column is treated as done. No migration library fits both Python versions
under GPLv2 (Alembic needs SQLAlchemy on Py3; yoyo is Apache-2.0).

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import sqlite3

TABLES = [
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

    # Which worksheets a curve served: a curve is
    # stored once, keyed by its calibrators (calibrations.cal_key), and each
    # worksheet that used it has a row here. Approval belongs to the curve;
    # a rejection belongs to the worksheet that made it (status / notes).
    """CREATE TABLE IF NOT EXISTS calibration_uses (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id        TEXT    NOT NULL,
        calibration_id  INTEGER NOT NULL REFERENCES calibrations(id),
        run_date        TEXT    NOT NULL DEFAULT '',
        status          TEXT    NOT NULL DEFAULT '',
        notes           TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL DEFAULT ''
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_caluse_pair ON calibration_uses(batch_id, calibration_id)",

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

    # Per-injection chromatographic detail: one row per injection ×
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
        conc_qualifier  TEXT    NOT NULL DEFAULT '',
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

    # Control-chart review: a warning DISMISSED with a
    # reason, or a point REMOVED from the chart (and from its mean / SD) with a
    # reason. The QC result itself is never edited; undo deletes the row.
    # action = 'dismissed' (rule = the warning's rule) | 'excluded' (rule = '').
    """CREATE TABLE IF NOT EXISTS chart_annotations (
        result_id   INTEGER NOT NULL REFERENCES qc_results(id),
        action      TEXT    NOT NULL,
        rule        TEXT    NOT NULL DEFAULT '',
        reason      TEXT    NOT NULL,
        by_user     TEXT    NOT NULL,
        at          TEXT    NOT NULL,
        PRIMARY KEY (result_id, action, rule)
    )""",
]


# (number, statement) -- append only; never renumber or edit a shipped one.
# A NEW table or index comes as a migration too, not only in TABLES: SENAITE
# skips the schema once the database is at VERSION (qc/store.py).
MIGRATIONS = [
    (1, "ALTER TABLE calibrations ADD COLUMN approved_by      TEXT NOT NULL DEFAULT ''"),
    (2, "ALTER TABLE calibrations ADD COLUMN approved_at      TEXT NOT NULL DEFAULT ''"),
    (3, "ALTER TABLE calibrations ADD COLUMN fit_type_override  TEXT NOT NULL DEFAULT ''"),
    (4, "ALTER TABLE calibrations ADD COLUMN weight_override    TEXT NOT NULL DEFAULT ''"),
    (5, "ALTER TABLE calibrations ADD COLUMN origin_override    TEXT NOT NULL DEFAULT ''"),
    (6, "ALTER TABLE calibration_levels ADD COLUMN response_ratio REAL"),
    (7, "ALTER TABLE qc_results ADD COLUMN expected_value REAL"),
    (8, "ALTER TABLE qc_results ADD COLUMN response_ratio REAL"),
    # injection_results rows written before conc_qualifier existed (was a
    # private patch in the worker's injection_store)
    (9, "ALTER TABLE injection_results ADD COLUMN conc_qualifier TEXT NOT NULL DEFAULT ''"),
    # : what the surrogate-recovery and internal-standard-response
    # checks JUDGED, per injection x labelled standard, for the certificate's
    # QC sub-table. Status: within | outside | no criterion (never a pass);
    # std_role from the method's labelled-standards grid at the check.
    (10, "ALTER TABLE injection_results ADD COLUMN std_role TEXT NOT NULL DEFAULT ''"),
    (11, "ALTER TABLE injection_results ADD COLUMN rec_min REAL"),
    (12, "ALTER TABLE injection_results ADD COLUMN rec_max REAL"),
    (13, "ALTER TABLE injection_results ADD COLUMN rec_status TEXT NOT NULL DEFAULT ''"),
    (14, "ALTER TABLE injection_results ADD COLUMN rec_guidance INTEGER NOT NULL DEFAULT 0"),
    (15, "ALTER TABLE injection_results ADD COLUMN resp_pct REAL"),
    (16, "ALTER TABLE injection_results ADD COLUMN resp_min REAL"),
    (17, "ALTER TABLE injection_results ADD COLUMN resp_max REAL"),
    (18, "ALTER TABLE injection_results ADD COLUMN resp_status TEXT NOT NULL DEFAULT ''"),
    # the value each check JUDGED (a whole percent by the method's rule) and
    # the rule / precision the run was judged with
    (19, "ALTER TABLE injection_results ADD COLUMN rec_judged REAL"),
    (20, "ALTER TABLE injection_results ADD COLUMN resp_judged REAL"),
    (21, "ALTER TABLE injection_results ADD COLUMN judged_rule TEXT NOT NULL DEFAULT ''"),
    # manual integration: the export's raw cell and the decision;
    # NULL = the export carried no manual-integration column (not captured)
    (22, "ALTER TABLE injection_results ADD COLUMN manual_raw TEXT NOT NULL DEFAULT ''"),
    (23, "ALTER TABLE injection_results ADD COLUMN manual_integration INTEGER"),
    # every result the worker wrote onto a core analysis, or could not, per
    # run (core integration): Data Review lists the
    # misses and the results changed by hand afterwards
    (24, "CREATE TABLE IF NOT EXISTS result_pushes ("
         "id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, run_at TEXT, "
         "injection TEXT, sample_uid TEXT, analysis_uid TEXT, analyte TEXT, keyword TEXT, "
         "value TEXT, ok INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '')"),
    (25, "CREATE INDEX IF NOT EXISTS idx_result_pushes_batch ON result_pushes (batch_id)"),
    # the injection whose SAMPLE a QC result qualifies: a surrogate / IS
    # result its own injection, a matrix spike or duplicate its parent; ''
    # = the whole run
    (26, "ALTER TABLE qc_results ADD COLUMN applies_to TEXT NOT NULL DEFAULT ''"),
    # a run-shape gap the reviewer cleared with a note:
    # result_status "cleared", who, when and why
    (27, "ALTER TABLE qc_results ADD COLUMN cleared_by TEXT NOT NULL DEFAULT ''"),
    (28, "ALTER TABLE qc_results ADD COLUMN cleared_at TEXT NOT NULL DEFAULT ''"),
    (29, "ALTER TABLE qc_results ADD COLUMN cleared_note TEXT NOT NULL DEFAULT ''"),
    # the run's matrix: a blank is compared with the previous blank of the
    # same method AND matrix (blank history)
    (30, "ALTER TABLE batches ADD COLUMN matrix TEXT NOT NULL DEFAULT ''"),
    # a curve is identified by its calibrators: injection names and
    # acquisition times; '' = not identifiable (kept
    # per worksheet, as before)
    (31, "ALTER TABLE calibrations ADD COLUMN cal_key TEXT NOT NULL DEFAULT ''"),
    # every existing curve served the worksheet that wrote it; a rejection
    # recorded on the curve stays there (one worksheet per curve before this)
    (32, "INSERT OR IGNORE INTO calibration_uses (batch_id, calibration_id, run_date, created_at) "
         "SELECT batch_id, id, run_date, created_at FROM calibrations"),
    # the window each ICV / CCV was judged in (recovery %, low and high) and
    # each calibrator's allowed deviation (±%): the charts draw what the
    # worker judged, never a limit of their own
    (33, "ALTER TABLE qc_results ADD COLUMN limit_low REAL"),
    (34, "ALTER TABLE qc_results ADD COLUMN limit_high REAL"),
    (35, "ALTER TABLE calibration_levels ADD COLUMN limit_pct REAL"),
    # the rule a QC result was judged by, as a reader sees it ("LFSM recovery
    # 70-130 %"): Data Review numbers criteria by it, not every value
    (36, "ALTER TABLE qc_results ADD COLUMN limit_basis TEXT NOT NULL DEFAULT ''"),
    # every delivered run file's import: imported / retrying / failed, how
    # many attempts and the last error. A run the worker could not import
    # (SENAITE slow or restarting) was dropped with nothing shown in SENAITE;
    # Data Review and the Run Builder read it.
    (37, "CREATE TABLE IF NOT EXISTS run_imports ("
         "file TEXT PRIMARY KEY, batch_id TEXT NOT NULL DEFAULT '', "
         "status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
         "error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)"),
    # a curve's points by curve: every point lookup scanned the table, once
    # per curve on the Calibration Archive
    (38, "CREATE INDEX IF NOT EXISTS idx_callev_cal ON calibration_levels (calibration_id)"),
    # statistics for the planner: without them it chose the status index
    # (99.8 % of rows) for every chart and blank query, 8-9x slower; the
    # worker keeps them current with PRAGMA optimize after each import
    (39, "ANALYZE"),
    # when each pushed result's injection was acquired: the EDD's analysis
    # date (it carried the release time)
    (40, "ALTER TABLE result_pushes ADD COLUMN acquired_at TEXT NOT NULL DEFAULT ''"),
    # the import log keyed by file AND worksheet: another worksheet's file of
    # the same name erased a failed import's hold
    (41, "ALTER TABLE run_imports RENAME TO run_imports_v1"),
    (42, "CREATE TABLE IF NOT EXISTS run_imports ("
         "file TEXT NOT NULL, batch_id TEXT NOT NULL DEFAULT '', "
         "status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
         "error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, "
         "PRIMARY KEY (file, batch_id))"),
    (43, "INSERT OR IGNORE INTO run_imports SELECT file, batch_id, status, attempts, error, updated_at "
         "FROM run_imports_v1"),
    (44, "DROP TABLE run_imports_v1"),
]

# check verdict statuses (rec_status / resp_status)
STATUS_WITHIN = "within"
STATUS_OUTSIDE = "outside"
STATUS_NO_CRITERION = "no criterion"

VERSION = MIGRATIONS[-1][0]


def drop_unused_calibrations(conn):
    """Delete the curves (and their points) no worksheet uses any more."""
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM calibrations WHERE id NOT IN (SELECT calibration_id FROM calibration_uses)")]
    for i in ids:
        conn.execute("DELETE FROM calibration_levels WHERE calibration_id=?", (i,))
        conn.execute("DELETE FROM calibrations WHERE id=?", (i,))
    return len(ids)


def drop_batch_calibrations(conn, batch_ids):
    """Forget the worksheets' calibrations: their uses, then every curve no
    other worksheet still uses (a curve another run shares stays)."""
    for b in batch_ids or []:
        conn.execute("DELETE FROM calibration_uses WHERE batch_id=?", (b,))
    return drop_unused_calibrations(conn)


def ensure(conn):
    """Create missing tables and apply pending migrations; returns the
    schema version the database is now at."""
    for stmt in TABLES:
        conn.execute(stmt)
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, stmt in MIGRATIONS:
        if number <= current:
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
    if current < VERSION:
        conn.execute("PRAGMA user_version = %d" % VERSION)
    conn.commit()
    return VERSION
