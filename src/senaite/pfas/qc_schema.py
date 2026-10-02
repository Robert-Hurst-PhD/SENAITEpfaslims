# -*- coding: utf-8 -*-
"""The QC results database schema (/data/qc/pfas_qc_results.db), in ONE place
(docs/REUSE_REVIEW.md U6).

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

    # Control-chart review (DECISIONS 2026-10-02): a warning DISMISSED with a
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
]

VERSION = MIGRATIONS[-1][0]


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
