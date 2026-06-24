"""
Synthetic calibration data seeder / purger.

Usage:
  Seed:   docker compose exec pfas-worker python /app/pfas_pipeline/seed_calibrations.py
  Purge:  docker compose exec pfas-worker python /app/pfas_pipeline/seed_calibrations.py --purge

All synthetic rows use batch_id values prefixed with 'SYNTHETIC_' so they
can be cleanly separated from real data.  The purge command removes ALL
SYNTHETIC_ calibration records and their associated level rows.

One-command purge (raw SQLite, no Python needed):
  docker compose exec pfas-worker sqlite3 /data/qc/pfas_qc_results.db \
    "DELETE FROM calibration_levels WHERE calibration_id IN \
     (SELECT id FROM calibrations WHERE batch_id LIKE 'SYNTHETIC_%'); \
     DELETE FROM calibrations WHERE batch_id LIKE 'SYNTHETIC_%';"
"""

from __future__ import print_function

import os
import sqlite3
import sys
from datetime import date

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")

# ── Schema (mirrors QCResultStore._SCHEMA_STMTS) ──────────────────────────────

_SCHEMA = [
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
    """CREATE TABLE IF NOT EXISTS qc_results (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id        TEXT    NOT NULL,
        run_date        TEXT    NOT NULL,
        analyte         TEXT    NOT NULL,
        qc_type         TEXT    NOT NULL,
        injection_name  TEXT    NOT NULL DEFAULT '',
        value           REAL,
        lower_limit     REAL,
        upper_limit     REAL,
        passed          INTEGER NOT NULL DEFAULT 1,
        result_status   TEXT    NOT NULL DEFAULT 'active',
        instrument_id   TEXT    NOT NULL DEFAULT '',
        analyst         TEXT    NOT NULL DEFAULT '',
        method          TEXT    NOT NULL DEFAULT '',
        notes           TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_qcr_batch   ON qc_results(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_qcr_analyte ON qc_results(analyte)",
    "CREATE INDEX IF NOT EXISTS idx_qcr_status  ON qc_results(result_status)",
]


# ── Synthetic calibration records ─────────────────────────────────────────────
# Each entry: (batch_id, run_date, analyte, method, analyst, instrument_id,
#              r2, fit_type, weight_type, min_level, max_level, status, notes,
#              levels_list)
# levels_list: list of (level_index, expected_conc, pct_deviation)
#              calculated = expected * (1 + pct_deviation/100)
#              passed = abs(pct_deviation) <= 20.0

import random as _random
_random.seed(42)  # reproducible synthetic noise

def _levels(expected_list, deviations, slope=0.004, intercept=0.00005):
    """Build levels list from expected concentrations and % deviations.
    slope/intercept define a synthetic linear calibration for response_ratio.
    """
    result = []
    for i, (exp, dev) in enumerate(zip(expected_list, deviations)):
        calc = exp * (1.0 + dev / 100.0)
        # Realistic response_ratio: slope*expected + intercept + small noise
        noise = _random.gauss(0, slope * exp * abs(dev) * 0.01)
        rr = slope * exp + intercept + noise
        result.append({
            "level":          i + 1,
            "expected":       exp,
            "calculated":     round(calc, 4),
            "pct_deviation":  round(dev, 2),
            "passed":         abs(dev) <= 20.0,
            "response_ratio": round(max(rr, 0.0), 8),
        })
    return result


# Standard 8-point calibration levels (ng/L or ng/mL)
_STD_EXPECTED = [0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0]

# Good calibration: r2=0.9991, all levels within ±8%
_GOOD_DEVIATIONS = [-2.1, 3.4, -1.8, 5.2, -3.7, 2.0, 4.5, -6.1]

# Marginal calibration: r2=0.9972, some levels at ±12-15%
_MARGINAL_DEVIATIONS = [8.5, -12.3, 6.1, -14.8, 3.2, 11.0, -7.4, 13.5]

# Failing calibration: r2=0.9821, several levels exceed ±20%
_FAIL_DEVIATIONS = [4.2, -22.5, 17.8, -28.3, 9.1, 24.7, -15.2, 31.4]

# Second failing set (r2 ok but levels fail — tests that both criteria matter)
_FAIL_LEVELS_DEVIATIONS = [-5.0, 6.3, -21.7, 4.8, -19.2, 23.8, -3.4, 26.1]


SYNTHETIC_RECORDS = [
    # ── FDA 32-PFAS batch (SCIEX OS instrument) ──────────────────────────────
    ("SYNTHETIC_FDA_001", "2026-06-01", "PFOS",  "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9991, "linear", "1/x", 0.5, 100.0, "approved",
     "[SYNTHETIC] Good calibration — PFOS, FDA 32-PFAS",
     _levels(_STD_EXPECTED, _GOOD_DEVIATIONS)),

    ("SYNTHETIC_FDA_001", "2026-06-01", "PFOA",  "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9985, "linear", "1/x", 0.5, 100.0, "approved",
     "[SYNTHETIC] Good calibration — PFOA, FDA 32-PFAS",
     _levels(_STD_EXPECTED, _GOOD_DEVIATIONS)),

    ("SYNTHETIC_FDA_001", "2026-06-01", "PFNA",  "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9972, "linear", "1/x", 0.5, 100.0, "pending",
     "[SYNTHETIC] Marginal r2 (0.9972 < 0.995 threshold) — review required",
     _levels(_STD_EXPECTED, _MARGINAL_DEVIATIONS)),

    ("SYNTHETIC_FDA_001", "2026-06-01", "PFHxS", "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9993, "linear", "1/x^2", 0.5, 100.0, "approved",
     "[SYNTHETIC] Good calibration — PFHxS, 1/x2 weighting",
     _levels(_STD_EXPECTED, _GOOD_DEVIATIONS)),

    # FAILING — r2 below threshold AND levels out of spec
    ("SYNTHETIC_FDA_001", "2026-06-01", "PFBS",  "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9821, "linear", "1/x", 0.5, 100.0, "rejected",
     "[SYNTHETIC] INTENTIONAL FAILURE: r2=0.982, multiple levels >20% dev",
     _levels(_STD_EXPECTED, _FAIL_DEVIATIONS)),

    ("SYNTHETIC_FDA_001", "2026-06-01", "PFDA",  "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9967, "linear", "1/x", 0.5, 100.0, "pending",
     "[SYNTHETIC] Borderline r2 (0.9967); marginal levels",
     _levels(_STD_EXPECTED, _MARGINAL_DEVIATIONS)),

    # ── EPA 537.1 batch (Waters MassLynx instrument) ──────────────────────────
    ("SYNTHETIC_537_001", "2026-06-02", "PFOS",  "EPA_537_1", "M.Chen",
     "WATERS-001", 0.9988, "linear", "1/x", 1.0, 200.0, "approved",
     "[SYNTHETIC] Good calibration — PFOS, EPA 537.1",
     _levels([1.0, 2.0, 4.0, 10.0, 20.0, 50.0, 100.0, 200.0],
             _GOOD_DEVIATIONS)),

    ("SYNTHETIC_537_001", "2026-06-02", "PFOA",  "EPA_537_1", "M.Chen",
     "WATERS-001", 0.9994, "linear", "1/x", 1.0, 200.0, "approved",
     "[SYNTHETIC] Good calibration — PFOA, EPA 537.1",
     _levels([1.0, 2.0, 4.0, 10.0, 20.0, 50.0, 100.0, 200.0],
             [-1.5, 4.0, -2.2, 3.8, -5.1, 1.7, 3.3, -4.9])),

    ("SYNTHETIC_537_001", "2026-06-02", "PFHxS", "EPA_537_1", "M.Chen",
     "WATERS-001", 0.9976, "linear", "none", 1.0, 200.0, "pending",
     "[SYNTHETIC] Marginal — r2 borderline, some levels approaching limit",
     _levels([1.0, 2.0, 4.0, 10.0, 20.0, 50.0, 100.0, 200.0],
             _MARGINAL_DEVIATIONS)),

    # FAILING — r2 ok but levels out of spec
    ("SYNTHETIC_537_001", "2026-06-02", "PFBA",  "EPA_537_1", "M.Chen",
     "WATERS-001", 0.9956, "linear", "1/x", 1.0, 200.0, "rejected",
     "[SYNTHETIC] INTENTIONAL FAILURE: levels >20% deviation despite ok r2",
     _levels([1.0, 2.0, 4.0, 10.0, 20.0, 50.0, 100.0, 200.0],
             _FAIL_LEVELS_DEVIATIONS)),

    # ── EPA 1633A batch (Agilent MassHunter instrument) ───────────────────────
    ("SYNTHETIC_1633_001", "2026-06-03", "PFOS",  "EPA_1633A", "A.Kumar",
     "AGILENT-001", 0.9983, "linear", "1/x", 2.0, 500.0, "approved",
     "[SYNTHETIC] Good calibration — PFOS, EPA 1633A (tissue matrix)",
     _levels([2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0],
             _GOOD_DEVIATIONS)),

    ("SYNTHETIC_1633_001", "2026-06-03", "PFOA",  "EPA_1633A", "A.Kumar",
     "AGILENT-001", 0.9961, "linear", "1/x", 2.0, 500.0, "pending",
     "[SYNTHETIC] Marginal calibration — PFOA, EPA 1633A",
     _levels([2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0],
             _MARGINAL_DEVIATIONS)),

    # Second date — simulates a later run for trend analysis / control chart
    ("SYNTHETIC_FDA_002", "2026-06-08", "PFOS",  "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9987, "linear", "1/x", 0.5, 100.0, "approved",
     "[SYNTHETIC] Good calibration — PFOS run 2 (for trend data)",
     _levels(_STD_EXPECTED, [-3.0, 2.1, -4.5, 1.8, -6.2, 3.4, -2.9, 5.0])),

    ("SYNTHETIC_FDA_002", "2026-06-08", "PFOA",  "FDA_32PFAS", "J.Smith",
     "SCIEX-001", 0.9979, "linear", "1/x", 0.5, 100.0, "approved",
     "[SYNTHETIC] Good calibration — PFOA run 2 (for trend data)",
     _levels(_STD_EXPECTED, [1.3, -3.7, 2.8, -4.2, 1.5, -5.8, 3.2, -2.4])),
]


def _connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


_MIGRATIONS = [
    "ALTER TABLE calibrations ADD COLUMN approved_by      TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN approved_at      TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN fit_type_override  TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN weight_override    TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibrations ADD COLUMN origin_override    TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calibration_levels ADD COLUMN response_ratio REAL",
    "ALTER TABLE qc_results ADD COLUMN expected_value REAL",
    "ALTER TABLE qc_results ADD COLUMN response_ratio REAL",
]


def ensure_schema(conn):
    for stmt in _SCHEMA:
        conn.execute(stmt)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except Exception:
            pass  # column already exists
    conn.commit()


def seed(conn):
    """Insert all synthetic calibration records (idempotent via batch_id check)."""
    now = date.today().isoformat() + "T00:00:00Z"
    inserted = 0
    skipped = 0

    for rec in SYNTHETIC_RECORDS:
        (batch_id, run_date, analyte, method, analyst, instrument_id,
         r2, fit_type, weight_type, min_level, max_level, status, notes,
         levels) = rec

        # Skip if this exact batch/analyte already exists
        existing = conn.execute(
            "SELECT id FROM calibrations WHERE batch_id=? AND analyte=?",
            (batch_id, analyte),
        ).fetchone()
        if existing:
            skipped += 1
            continue

        cur = conn.execute(
            "INSERT INTO calibrations "
            "(batch_id,run_date,analyte,method,analyst,instrument_id,"
            " equation,fit_type,weight_type,r2,n_levels,min_level,"
            " max_level,status,notes,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, run_date, analyte, method, analyst, instrument_id,
             "y = mx + b", fit_type, weight_type, r2, len(levels),
             min_level, max_level, status, notes, now),
        )
        cal_id = cur.lastrowid
        for lv in levels:
            conn.execute(
                "INSERT INTO calibration_levels "
                "(calibration_id,level,expected,calculated,"
                " pct_deviation,passed,response_ratio) VALUES (?,?,?,?,?,?,?)",
                (cal_id, lv["level"], lv["expected"], lv["calculated"],
                 lv["pct_deviation"], int(lv["passed"]),
                 lv.get("response_ratio")),
            )
        inserted += 1

    conn.commit()

    # Seed synthetic QC check results (ICV/CCV/CCB) linked to the same batches
    _seed_qc_checks(conn, now)

    return inserted, skipped


def _seed_qc_checks(conn, now):
    """Seed ICV/CCV/CCB results using the QCResultStore qc_results schema."""
    # Uses store schema columns: qc_level, value, units, flag, passed, result_status,
    #   reanalysis_reason, expected_value, response_ratio
    for rec in SYNTHETIC_RECORDS:
        (batch_id, run_date, analyte, method, analyst, instrument_id,
         r2, fit_type, weight_type, min_level, max_level, status, notes, levels) = rec
        slope = 0.004
        intercept = 0.00005
        icv_exp = round((min_level + max_level) * 0.1, 3)
        ccv_exp = round((min_level + max_level) * 0.5, 3)
        for (qtype, qexp, qdv) in [
            ("ICV", icv_exp, _random.gauss(3.0, 3.0)),
            ("CCV", ccv_exp, _random.gauss(2.5, 4.0)),
            ("CCB", 0.0,     _random.gauss(0.5, 1.0)),
        ]:
            exists = conn.execute(
                "SELECT id FROM qc_results "
                "WHERE batch_id=? AND analyte=? AND qc_type=? AND result_status='active'",
                (batch_id, analyte, qtype),
            ).fetchone()
            if exists:
                continue
            qval = qexp * (1.0 + qdv / 100.0) if qexp > 0 else abs(_random.gauss(0, 0.01 * (min_level or 1)))
            qrr  = slope * qexp + intercept + _random.gauss(0, 0.0001) if qexp > 0 else None
            passed = abs(qdv) <= 20.0 if qexp > 0 else True
            conn.execute(
                "INSERT INTO qc_results "
                "(batch_id,run_date,analyte,qc_type,qc_level,"
                " method,analyst,instrument_id,"
                " value,units,flag,passed,result_status,parent_result_id,"
                " reanalysis_reason,created_at,expected_value,response_ratio) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, run_date, analyte, qtype, 'synth',
                 method, analyst, instrument_id,
                 round(qval, 5), 'ng/mL', '',
                 int(passed), 'active', None,
                 '', now,
                 qexp if qexp > 0 else None,
                 round(qrr, 8) if qrr is not None else None),
            )
    conn.commit()


def purge(conn):
    """Remove all SYNTHETIC_ calibration records, level rows, and QC checks."""
    conn.execute(
        "DELETE FROM calibration_levels WHERE calibration_id IN "
        "(SELECT id FROM calibrations WHERE batch_id LIKE 'SYNTHETIC_%')"
    )
    cur = conn.execute(
        "DELETE FROM calibrations WHERE batch_id LIKE 'SYNTHETIC_%'"
    )
    conn.execute(
        "DELETE FROM qc_results WHERE batch_id LIKE 'SYNTHETIC_%'"
    )
    conn.commit()
    return cur.rowcount


def main():
    do_purge = "--purge" in sys.argv

    print("DB path: {}".format(DB_PATH))
    conn = _connect(DB_PATH)
    ensure_schema(conn)

    if do_purge:
        n = purge(conn)
        print("Purged {} SYNTHETIC_ calibration record(s).".format(n))
    else:
        inserted, skipped = seed(conn)
        print("Seeded {} new calibration record(s) ({} already existed).".format(
            inserted, skipped))
        print("")
        print("To purge: python seed_calibrations.py --purge")
        print("Or (raw SQL):")
        print("  sqlite3 {} \"DELETE FROM calibration_levels WHERE calibration_id IN"
              " (SELECT id FROM calibrations WHERE batch_id LIKE 'SYNTHETIC_%');"
              " DELETE FROM calibrations WHERE batch_id LIKE 'SYNTHETIC_%';\"".format(DB_PATH))

    conn.close()


if __name__ == "__main__":
    main()
