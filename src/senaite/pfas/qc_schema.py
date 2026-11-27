# -*- coding: utf-8 -*-
"""The QC results database schema (/data/qc/pfas_qc_results.db), in ONE place.

Both processes write this database: the add-on (senaite.pfas.qc.store) and
the pipeline worker (qc_store, injection_store); all of them call
`ensure(conn)` here (the worker loads this file from the add-on mount).

TABLES is the current shape and VERSION its number in SQLite's
`PRAGMA user_version`: a new database is created at it, a database at it
is left alone, one at a number UPGRADES names is brought up to it, one step
at a time under a write lock, and one at another number is refused.

A run imported again before it is verified keeps the earlier import's rows
(SUPERSEDED: its injection results, the unreported side, value
provenance, raw traces and calibration) in the superseded_* tables, each
row stamped with when and by which import it was superseded; import_identity
names the import whose rows are current, per worksheet and side: the
reported side, or the side kept for the comparison (begin_import).

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# Configuration History (config_history_db): one row per entry, the entry
# itself as the JSON text it was written as; newest first by id
CONFIG_HISTORY = [
    'CREATE TABLE IF NOT EXISTS config_history (id TEXT PRIMARY KEY, at TEXT NOT NULL, '
    "who TEXT NOT NULL DEFAULT '', store TEXT NOT NULL DEFAULT '', "
    "key TEXT NOT NULL DEFAULT '', entry TEXT NOT NULL)",
    'CREATE INDEX IF NOT EXISTS idx_config_history_store ON config_history (store, key, id)',
    'CREATE INDEX IF NOT EXISTS idx_config_history_at ON config_history (at)',
    'CREATE INDEX IF NOT EXISTS idx_config_history_who ON config_history (who)',
]

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
] + CONFIG_HISTORY

# the stores an import replaces, kept as superseded copies: (table, archive)
SUPERSEDED = (("injection_results", "superseded_injection_results"),
              ("alt_results", "superseded_alt_results"),
              ("value_provenance", "superseded_value_provenance"),
              ("raw_traces", "superseded_raw_traces"),
              ("calibration_uses", "superseded_calibration_uses"),
              ("calibrations", "superseded_calibrations"),
              ("calibration_levels", "superseded_calibration_levels"))

# what makes the rows superseded: when, and the import that superseded them
ARCHIVE_STAMPS = ("superseded_at", "superseded_by")

ARCHIVE_TABLES = [
    # the import whose rows are current, per worksheet: its file and checksum
    "CREATE TABLE IF NOT EXISTS import_identity (batch_id TEXT NOT NULL, "
    "side TEXT NOT NULL DEFAULT 'reported', "
    "source TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '', "
    "imported_at TEXT NOT NULL DEFAULT '', PRIMARY KEY (batch_id, side))",
] + [
    # each archive has its table's columns and the two stamps
    "CREATE TABLE IF NOT EXISTS %s AS SELECT *, '' AS superseded_at, '' AS superseded_by "
    "FROM %s WHERE 0" % (archive, table) for table, archive in SUPERSEDED
] + [
    "CREATE INDEX IF NOT EXISTS idx_%s ON %s (%s)" % (archive, archive,
                                                     "calibration_id" if table == "calibration_levels"
                                                     else "id" if table == "calibrations" else "batch_id")
    for table, archive in SUPERSEDED
]
TABLES = TABLES + ARCHIVE_TABLES



# check verdict statuses (rec_status / resp_status)
STATUS_WITHIN = "within"
STATUS_OUTSIDE = "outside"
STATUS_NO_CRITERION = "no criterion"
# a surrogate whose matrix class the method marks not assessed (the lab's decision)
STATUS_NOT_ASSESSED = "not assessed"

# The schema's number in SQLite's user_version. A change to the schema is a
# new number and the statement that brings a database at the previous one up
# to it; TABLES is always the current shape.
VERSION = 73

# number -> the statements that bring a database at that number to the next
UPGRADES = {
    71: CONFIG_HISTORY,
    72: ARCHIVE_TABLES,
}


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
    """Create the tables and indexes of a new database; bring one at an
    earlier number up through UPGRADES (once, under a write lock, so the
    two processes never both do it); a database at any other schema number
    is refused, never altered. Returns VERSION."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current == VERSION:
        return VERSION
    if current in UPGRADES:
        return _upgrade(conn)
    if current or conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                               "AND name NOT LIKE 'sqlite_%'").fetchone():
        raise RuntimeError("The QC database is at schema %d, not %d: it was made by "
                           "another version of the add-on." % (current, VERSION))
    for stmt in TABLES:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = %d" % VERSION)
    conn.commit()
    return VERSION


def _upgrade(conn):
    """An earlier number up to VERSION through UPGRADES, step by step, in one
    transaction: the statements are idempotent, and the number is read again
    under the lock, so a process that waited finds the work done."""
    conn.commit()
    level = conn.isolation_level
    conn.isolation_level = None              # the transaction is this function's own
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            while current in UPGRADES:
                for stmt in UPGRADES[current]:
                    conn.execute(stmt)
                current += 1
                conn.execute("PRAGMA user_version = %d" % current)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = level
    if current != VERSION:
        raise RuntimeError("The QC database stopped at schema %d, not %d." % (current, VERSION))
    return VERSION


def _columns(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]


def _copy(conn, table, archive, where, params, stamps):
    """Copy `table`'s rows matching `where` into `archive`, the columns both
    hold, stamped. Returns how many rows were copied."""
    have = set(_columns(conn, archive))
    cols = [c for c in _columns(conn, table) if c in have and c not in ARCHIVE_STAMPS]
    cur = conn.execute("INSERT INTO %s (%s, superseded_at, superseded_by) SELECT %s, ?, ? FROM %s WHERE %s"
                       % (archive, ", ".join(cols), ", ".join(cols), table, where),
                       tuple(stamps) + tuple(params))
    return cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0


# the side an import is reported on; any other is the side kept for the
# comparison ("vendor" or "raw", the alt_results side)
REPORTED = "reported"
CALIBRATION = ("calibration_uses", "calibrations", "calibration_levels")


def stores_of(side, raw):
    """(tables, alt side): the stores an import of `side` writes. The side
    kept for the comparison writes its own alt rows and, a raw run, its
    traces; the reported side the injection results, the provenance, the
    calibration, the alt rows of its own kind and, a raw run, the traces."""
    traces = ("raw_traces",) if raw else ()
    if side and side != REPORTED:
        return ("alt_results",) + traces, side
    return (("injection_results", "alt_results", "value_provenance") + traces + CALIBRATION,
            "raw" if raw else "vendor")


def _where(table, batch_id, alt_side):
    if table == "calibrations":
        return "id IN (SELECT calibration_id FROM calibration_uses WHERE batch_id=?)", (batch_id,)
    if table == "calibration_levels":
        return ("calibration_id IN (SELECT calibration_id FROM calibration_uses WHERE batch_id=?)",
                (batch_id,))
    if table == "alt_results" and alt_side:
        return "batch_id=? AND side=?", (batch_id, alt_side)
    return "batch_id=?", (batch_id,)


def supersede(conn, batch_id, at, by, tables=None, alt_side=None):
    """Keep the worksheet's current rows of the SUPERSEDED stores
    (`tables`, all when None; the alt rows of `alt_side` only when given)
    as superseded copies, stamped `at` and `by` (the import that supersedes
    them): its calibration uses and the curves they name, with their
    points, as they stand. Nothing is deleted here: each store replaces its
    rows as before. Returns {table: rows copied}. No commit."""
    out = {}
    stamps = (at or "", by or "")
    for table, archive in SUPERSEDED:
        if tables is not None and table not in tables:
            continue
        where, params = _where(table, batch_id, alt_side)
        out[table] = _copy(conn, table, archive, where, params, stamps)
    return out


# what a processing of the same import keeps: the run's ion-ratio records it
# replaces, stamped this (superseded_by), so the review can say which
# samples changed verdict; the other stores and kinds are not kept
REPROCESS = "reprocess"


def keep_on_reprocess(conn, batch_id, at):
    """Before a processing of the worksheet replaces its value records: its
    ion-ratio records (kind ION) kept as superseded copies stamped `at` and
    REPROCESS, beside every earlier processing's: what each change did to
    the ion-ratio verdicts stays on record. Returns the rows copied. No
    commit."""
    return _copy(conn, "value_provenance", "superseded_value_provenance", "batch_id=? AND kind='ION'",
                 (batch_id,), (at or "", REPROCESS))


def _has_rows(conn, batch_id, tables, alt_side):
    for table, _archive in SUPERSEDED:
        if table not in tables or table in ("calibrations", "calibration_levels"):
            continue
        where, params = _where(table, batch_id, alt_side)
        if conn.execute("SELECT 1 FROM %s WHERE %s LIMIT 1" % (table, where), params).fetchone():
            return True
    return False


def begin_import(conn, batch_id, source, sha256, at, side=REPORTED, raw=False):
    """Before an import writes a worksheet's rows on `side` (REPORTED, or
    the side kept for the comparison; `raw`, a raw run): when the rows that
    side's stores hold came from another import (another file, or the same
    file changed; rows stored before imports were named count as another),
    they are kept as superseded copies (supersede). Processing the same
    import again, as an analyst's raw edit does, keeps nothing. Records this
    import as that side's current one and commits. Returns {table: rows
    copied}, {} when nothing was kept."""
    side = side or REPORTED
    tables, alt_side = stores_of(side, raw)
    row = conn.execute("SELECT source, sha256 FROM import_identity WHERE batch_id=? AND side=?",
                       (batch_id, side)).fetchone()
    same = row is not None and tuple(row) == (source or "", sha256 or "")
    kept = {}
    if not same and _has_rows(conn, batch_id, tables, alt_side):
        kept = supersede(conn, batch_id, at, "%s %s" % (source or "", (sha256 or "")[:12]),
                         tables=tables, alt_side=alt_side)
    conn.execute("INSERT OR REPLACE INTO import_identity (batch_id, side, source, sha256, imported_at) "
                 "VALUES (?,?,?,?,?)", (batch_id, side, source or "", sha256 or "", at or ""))
    conn.commit()
    return kept


def superseded_imports(conn, batch_id):
    """[{"at", "by", "rows"}]: each earlier import of the worksheet kept as
    superseded, newest first, with how many injection results it held."""
    out = []
    for at, by, n in conn.execute(
            "SELECT superseded_at, superseded_by, COUNT(*) FROM superseded_injection_results "
            "WHERE batch_id=? GROUP BY superseded_at, superseded_by ORDER BY superseded_at DESC",
            (batch_id,)):
        out.append({"at": at, "by": by, "rows": n})
    return out


def drop_superseded(conn, batch_ids):
    """Forget the worksheets' superseded copies and their import identity
    (a purge of the worksheets). No commit."""
    for b in batch_ids or []:
        for table, archive in SUPERSEDED:
            if table in ("calibrations", "calibration_levels"):
                continue
            conn.execute("DELETE FROM %s WHERE batch_id=?" % archive, (b,))
        conn.execute("DELETE FROM import_identity WHERE batch_id=?", (b,))
    # the curves and points no kept use names any more
    conn.execute("DELETE FROM superseded_calibration_levels WHERE calibration_id NOT IN "
                 "(SELECT calibration_id FROM superseded_calibration_uses)")
    conn.execute("DELETE FROM superseded_calibrations WHERE id NOT IN "
                 "(SELECT calibration_id FROM superseded_calibration_uses)")
