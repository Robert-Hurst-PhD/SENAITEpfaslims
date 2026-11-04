# -*- coding: utf-8 -*-
"""The QC results database schema (/data/qc/pfas_qc_results.db), in ONE place.

Both processes write this database: the add-on (senaite.pfas.qc.store) and
the pipeline worker (qc_store, injection_store); all of them call
`ensure(conn)` here (the worker loads this file from the add-on mount).

TABLES is the current shape and VERSION its number in SQLite's
`PRAGMA user_version`: a new database is created at it, a database at it
is left alone, and one at another number is refused.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

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
        created_at      TEXT    NOT NULL,
        approved_by TEXT NOT NULL DEFAULT '',
        approved_at TEXT NOT NULL DEFAULT '',
        fit_type_override TEXT NOT NULL DEFAULT '',
        weight_override TEXT NOT NULL DEFAULT '',
        origin_override TEXT NOT NULL DEFAULT '',
        cal_key TEXT NOT NULL DEFAULT ''
    )""",

    # Per-level calibration points
    """CREATE TABLE IF NOT EXISTS calibration_levels (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        calibration_id  INTEGER NOT NULL REFERENCES calibrations(id),
        level           INTEGER NOT NULL,
        expected        REAL,
        calculated      REAL,
        pct_deviation   REAL,
        passed          INTEGER NOT NULL DEFAULT 1,
        response_ratio REAL,
        limit_pct REAL,
        prov_key TEXT NOT NULL DEFAULT ''
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
        updated_at    TEXT    NOT NULL,
        matrix TEXT NOT NULL DEFAULT ''
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
        expected_value REAL,
        response_ratio REAL,
        applies_to TEXT NOT NULL DEFAULT '',
        cleared_by TEXT NOT NULL DEFAULT '',
        cleared_at TEXT NOT NULL DEFAULT '',
        cleared_note TEXT NOT NULL DEFAULT '',
        limit_low REAL,
        limit_high REAL,
        limit_basis TEXT NOT NULL DEFAULT '',
        prov_key TEXT NOT NULL DEFAULT '',
        advisory INTEGER NOT NULL DEFAULT 0,
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
        created_at      TEXT    NOT NULL,
        std_role TEXT NOT NULL DEFAULT '',
        rec_min REAL,
        rec_max REAL,
        rec_status TEXT NOT NULL DEFAULT '',
        rec_guidance INTEGER NOT NULL DEFAULT 0,
        resp_pct REAL,
        resp_min REAL,
        resp_max REAL,
        resp_status TEXT NOT NULL DEFAULT '',
        rec_judged REAL,
        resp_judged REAL,
        judged_rule TEXT NOT NULL DEFAULT '',
        manual_raw TEXT NOT NULL DEFAULT '',
        manual_integration INTEGER,
        source_file TEXT NOT NULL DEFAULT '',
        source_row INTEGER,
        raw_conc REAL,
        measured_conc REAL,
        raw_measured_conc REAL,
        dilution REAL,
        expected_conc REAL,
        reporting_limit REAL,
        ion_ratio_text TEXT NOT NULL DEFAULT '',
        acquired_at TEXT NOT NULL DEFAULT '',
        salt_factor REAL,
        matrix_factor REAL,
        derived_from TEXT NOT NULL DEFAULT '',
        prov_key TEXT NOT NULL DEFAULT '',
        advisory INTEGER NOT NULL DEFAULT 0
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

    # every result the worker wrote onto a core analysis, or could not, per
    # run: Data Review lists the misses and the results changed by hand
    # afterwards
    'CREATE TABLE IF NOT EXISTS result_pushes (id INTEGER PRIMARY KEY AUTOINCREMENT, '
    'batch_id TEXT NOT NULL, run_at TEXT, injection TEXT, sample_uid TEXT, '
    'analysis_uid TEXT, analyte TEXT, keyword TEXT, value TEXT, ok INTEGER NOT NULL, '
    "reason TEXT NOT NULL DEFAULT '', acquired_at TEXT NOT NULL DEFAULT '')",

    'CREATE INDEX IF NOT EXISTS idx_result_pushes_batch ON result_pushes (batch_id)',

    # a curve's points by curve, so a point lookup does not scan the table
    'CREATE INDEX IF NOT EXISTS idx_callev_cal ON calibration_levels (calibration_id)',

    'CREATE TABLE IF NOT EXISTS run_imports (file TEXT NOT NULL, '
    "batch_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, "
    "attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', "
    'updated_at TEXT NOT NULL, PRIMARY KEY (file, batch_id))',

    'CREATE TABLE IF NOT EXISTS value_provenance (id INTEGER PRIMARY KEY AUTOINCREMENT, '
    "batch_id TEXT NOT NULL DEFAULT '', key TEXT NOT NULL, kind TEXT NOT NULL DEFAULT '', "
    "analyte TEXT NOT NULL DEFAULT '', injection TEXT NOT NULL DEFAULT '', value REAL, "
    "value_text TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL DEFAULT '', "
    "verdict TEXT NOT NULL DEFAULT '', formula TEXT NOT NULL DEFAULT '', "
    "terms_json TEXT NOT NULL DEFAULT '[]', steps_json TEXT NOT NULL DEFAULT '[]', "
    "rule_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)",

    'CREATE UNIQUE INDEX IF NOT EXISTS idx_prov_batch_key ON value_provenance (batch_id, key)',

    'CREATE INDEX IF NOT EXISTS idx_prov_inj ON value_provenance (batch_id, injection, '
    'analyte)',

    # a raw run's chromatograms and peaks for review (raw_traces.py)
    'CREATE TABLE IF NOT EXISTS raw_traces (id INTEGER PRIMARY KEY AUTOINCREMENT, '
    "batch_id TEXT NOT NULL DEFAULT '', injection TEXT NOT NULL DEFAULT '', "
    "analyte TEXT NOT NULL DEFAULT '', transition TEXT NOT NULL DEFAULT '', "
    "role TEXT NOT NULL DEFAULT '', t BLOB, y BLOB, peak TEXT NOT NULL DEFAULT '', "
    "created_at TEXT NOT NULL DEFAULT '')",

    'CREATE INDEX IF NOT EXISTS idx_raw_traces_inj ON raw_traces (batch_id, injection)',

    # the side of a run that is not reported, kept for Validation's comparison
    'CREATE TABLE IF NOT EXISTS alt_results (id INTEGER PRIMARY KEY AUTOINCREMENT, '
    "batch_id TEXT NOT NULL DEFAULT '', side TEXT NOT NULL DEFAULT '', "
    "injection_name TEXT NOT NULL DEFAULT '', analyte TEXT NOT NULL DEFAULT '', "
    "data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT '')",

    'CREATE INDEX IF NOT EXISTS idx_alt_results ON alt_results (batch_id, side)',

    # every review act on the QC store, appended, never edited: a chart
    # annotation set, replaced or removed, a worksheet's calibration rejected
    # or approved, a fit override changed (kind, ref, action; detail = JSON
    # of what it replaced and why)
    'CREATE TABLE IF NOT EXISTS qc_review_log (id INTEGER PRIMARY KEY AUTOINCREMENT, '
    "at TEXT NOT NULL, by_user TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, "
    "ref TEXT NOT NULL DEFAULT '', action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}')",

    'CREATE INDEX IF NOT EXISTS idx_qc_review_log ON qc_review_log (kind, ref)',
]



# check verdict statuses (rec_status / resp_status)
STATUS_WITHIN = "within"
STATUS_OUTSIDE = "outside"
STATUS_NO_CRITERION = "no criterion"
# a surrogate whose matrix class the method marks not assessed (the lab's decision)
STATUS_NOT_ASSESSED = "not assessed"

# The schema's number in SQLite's user_version. A change to the schema is a
# new number and the statement that brings a database at the previous one up
# to it; TABLES is always the current shape.
VERSION = 71


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
    """Create the tables and indexes of a new database; a database at another
    schema number is refused, never altered. Returns VERSION."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current == VERSION:
        return VERSION
    if current or conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                               "AND name NOT LIKE 'sqlite_%'").fetchone():
        raise RuntimeError("The QC database is at schema %d, not %d: it was made by "
                           "another version of the add-on." % (current, VERSION))
    for stmt in TABLES:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = %d" % VERSION)
    conn.commit()
    return VERSION
