#!/usr/bin/env python3
"""
PFAS QC Control Chart — Synthetic test data seeder
=====================================================
Generates clearly-labeled, easily-purgeable test data for evaluating the
Levey-Jennings control charts and calibration review views.

Usage:
    python3 seed_test_data.py           # seed data (safe to run multiple times)
    python3 seed_test_data.py --purge   # remove ALL test data before go-live

All test records are tagged with flag='TEST_DATA' so they are trivially
identifiable. The --purge command deletes only records with that flag.

IMPORTANT: Run --purge before any production use.
"""

import argparse
import math
import os
import random
import sqlite3
import sys
from datetime import date, timedelta

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
TEST_FLAG = "TEST_DATA"

# Analytes to include (key analytes across methods)
ANALYTES = ["PFOA", "PFOS", "PFNA", "PFHxS", "PFBA", "PFHxA", "PFDA"]

# Methods and their matrix/unit context
METHODS = {
    "FDA_32PFAS": {"unit": "ng/kg", "ccv_mean": 100.0, "ccv_sd": 4.0,
                   "lfb_mean": 88.0,  "lfb_sd": 7.0},
    "EPA_537_1":  {"unit": "ng/L",  "ccv_mean": 100.0, "ccv_sd": 3.5,
                   "lfb_mean": 92.0,  "lfb_sd": 6.0},
    "EPA_1633A":  {"unit": "ng/g",  "ccv_mean": 100.0, "ccv_sd": 5.0,
                   "lfb_mean": 85.0,  "lfb_sd": 9.0},
}

ANALYSTS    = ["KCP", "JAR", "MEL"]
INSTRUMENTS = ["QTOF-1", "QTOF-2"]
N_WEEKS     = 32   # ~8 months of weekly runs

# Short slugs for batch_id generation — must be unique across methods
METHOD_SLUG = {
    "FDA_32PFAS": "FDA",
    "EPA_537_1":  "E537",
    "EPA_1633A":  "E163",
}

random.seed(42)   # reproducible


def _normal(mean, sd):
    """Box-Muller normal variate."""
    u1 = random.random() or 1e-9
    u2 = random.random()
    z  = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    return mean + sd * z


def _make_db(db_path):
    """Open (and schema-create if needed) the SQLite DB."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS batches (
        batch_id TEXT PRIMARY KEY, run_date TEXT NOT NULL,
        analyst TEXT NOT NULL DEFAULT '', instrument_id TEXT NOT NULL DEFAULT '',
        method TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
        notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS qc_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL, run_date TEXT NOT NULL,
        analyte TEXT NOT NULL, qc_type TEXT NOT NULL,
        qc_level TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '',
        analyst TEXT NOT NULL DEFAULT '', instrument_id TEXT NOT NULL DEFAULT '',
        value REAL, units TEXT NOT NULL DEFAULT '',
        flag TEXT NOT NULL DEFAULT '', passed INTEGER NOT NULL DEFAULT 1,
        result_status TEXT NOT NULL DEFAULT 'active',
        parent_result_id INTEGER, reanalysis_reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (batch_id) REFERENCES batches(batch_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS calibrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL DEFAULT '', run_date TEXT NOT NULL,
        analyte TEXT NOT NULL, method TEXT NOT NULL DEFAULT '',
        analyst TEXT NOT NULL DEFAULT '', instrument_id TEXT NOT NULL DEFAULT '',
        equation TEXT NOT NULL DEFAULT '', fit_type TEXT NOT NULL DEFAULT '',
        weight_type TEXT NOT NULL DEFAULT '', r2 REAL,
        n_levels INTEGER NOT NULL DEFAULT 0,
        min_level REAL, max_level REAL,
        status TEXT NOT NULL DEFAULT 'pending',
        notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS calibration_levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        calibration_id INTEGER NOT NULL REFERENCES calibrations(id),
        level INTEGER NOT NULL, expected REAL, calculated REAL,
        pct_deviation REAL, passed INTEGER NOT NULL DEFAULT 1)""")
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_qr_analyte ON qc_results(analyte)",
        "CREATE INDEX IF NOT EXISTS idx_qr_qc_type ON qc_results(qc_type)",
        "CREATE INDEX IF NOT EXISTS idx_qr_batch   ON qc_results(batch_id)",
        "CREATE INDEX IF NOT EXISTS idx_cal_analyte ON calibrations(analyte)",
        "CREATE INDEX IF NOT EXISTS idx_cal_run_date ON calibrations(run_date)",
    ]:
        conn.execute(idx_sql)
    conn.commit()
    return conn


def purge(db_path):
    """Delete all records tagged as TEST_DATA."""
    if not os.path.exists(db_path):
        print("DB not found at {} — nothing to purge.".format(db_path))
        return

    conn = sqlite3.connect(db_path)
    # Get batch_ids associated with test data
    test_batches = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT batch_id FROM qc_results WHERE flag LIKE ?",
            (TEST_FLAG + "%",)
        )
    }
    test_batches |= {
        row[0]
        for row in conn.execute(
            "SELECT batch_id FROM batches WHERE notes LIKE ?", ("%TEST_DATA%",)
        )
    }

    conn.execute(
        "DELETE FROM calibration_levels WHERE calibration_id IN "
        "(SELECT id FROM calibrations WHERE notes LIKE ?)", ("%TEST_DATA%",)
    )
    conn.execute(
        "DELETE FROM calibrations WHERE notes LIKE ?", ("%TEST_DATA%",)
    )
    conn.execute("DELETE FROM qc_results WHERE flag LIKE ?", (TEST_FLAG + "%",))
    if test_batches:
        conn.execute(
            "DELETE FROM batches WHERE batch_id IN ({})".format(
                ",".join("?" * len(test_batches))
            ),
            list(test_batches),
        )
    conn.commit()
    conn.close()
    print("Purged all TEST_DATA records from {}.".format(db_path))


def seed(db_path):
    """Insert synthetic QC + calibration test data."""
    conn = _make_db(db_path)
    now  = "2026-06-13T00:00:00"
    start_date = date(2025, 10, 1)

    # For each method, generate N_WEEKS of weekly batches
    for mid, cfg in METHODS.items():
        unit      = cfg["unit"]
        ccv_mean  = cfg["ccv_mean"]
        ccv_sd    = cfg["ccv_sd"]
        lfb_mean  = cfg["lfb_mean"]
        lfb_sd    = cfg["lfb_sd"]

        # Decide which runs will be outlier runs (2σ warning, 3σ reject)
        # For each analyte, pick 2 warning points and 1 reject point
        outlier_schedule = {}
        for analyte in ANALYTES:
            weeks = random.sample(range(4, N_WEEKS - 4), 3)
            outlier_schedule[(mid, analyte)] = {
                weeks[0]: "warn2",  # 2-3σ warning
                weeks[1]: "warn2",
                weeks[2]: "rej3",   # >3σ reject
            }

        for week_idx in range(N_WEEKS):
            run_date   = (start_date + timedelta(weeks=week_idx)).isoformat()
            batch_id   = "TEST-{}-W{:02d}".format(METHOD_SLUG.get(mid, mid[:4]), week_idx + 1)
            analyst    = ANALYSTS[week_idx % len(ANALYSTS)]
            instrument = INSTRUMENTS[week_idx % len(INSTRUMENTS)]

            # Insert batch record
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO batches "
                    "(batch_id,run_date,analyst,instrument_id,method,status,notes,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (batch_id, run_date, analyst, instrument, mid,
                     "complete",
                     "SYNTHETIC TEST DATA - PURGE BEFORE GO-LIVE (TEST_DATA)",
                     now, now),
                )
            except Exception:
                pass

            for analyte in ANALYTES:
                schedule = outlier_schedule.get((mid, analyte), {})
                outlier_type = schedule.get(week_idx, "normal")

                for qc_type, base_mean, base_sd in [
                    ("CCV", ccv_mean, ccv_sd),
                    ("LFB", lfb_mean, lfb_sd),
                ]:
                    if outlier_type == "warn2":
                        # 2-3σ from mean (warning zone)
                        sign = 1 if random.random() > 0.5 else -1
                        val = base_mean + sign * (2.3 + random.random() * 0.6) * base_sd
                    elif outlier_type == "rej3":
                        # >3σ (reject zone)
                        sign = 1 if random.random() > 0.5 else -1
                        val = base_mean + sign * (3.2 + random.random() * 0.5) * base_sd
                    else:
                        val = _normal(base_mean, base_sd)

                    # Clamp to plausible range
                    val = max(5.0, min(200.0, val))
                    passed = abs(val - base_mean) < 3 * base_sd
                    flag   = TEST_FLAG
                    if outlier_type in ("warn2", "rej3"):
                        flag = TEST_FLAG + "_OUTLIER"

                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO qc_results "
                            "(batch_id,run_date,analyte,qc_type,qc_level,method,"
                            "analyst,instrument_id,value,units,flag,passed,result_status,created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (batch_id, run_date, analyte, qc_type, "L5", mid,
                             analyst, instrument, round(val, 2), unit,
                             flag, 1 if passed else 0, "active", now),
                        )
                    except Exception as exc:
                        print("  skip {}: {}".format(batch_id, exc))

            # Calibration record (one per analyte per run)
            for analyte in ANALYTES:
                r2 = round(0.9950 + random.random() * 0.0048, 4)
                r2 = min(r2, 0.9999)
                cal_passed = r2 >= 0.990

                conn.execute(
                    "INSERT INTO calibrations "
                    "(batch_id,run_date,analyte,method,analyst,instrument_id,"
                    "equation,fit_type,weight_type,r2,n_levels,min_level,max_level,"
                    "status,notes,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (batch_id, run_date, analyte, mid, analyst, instrument,
                     "y = {:.4f}x + {:.4f}".format(
                         0.0012 + random.random() * 0.0003,
                         -0.001 + random.random() * 0.002),
                     "linear", "1/x", r2, 7,
                     0.5, 200.0,
                     "approved" if cal_passed else "rejected",
                     "SYNTHETIC TEST DATA - PURGE BEFORE GO-LIVE (TEST_DATA)",
                     now),
                )
                cal_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                # Calibration levels
                levels = [0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 200.0]
                for lv_idx, expected in enumerate(levels):
                    calc = expected * (1 + (random.random() - 0.5) * 0.04)
                    pct_dev = (calc - expected) / expected * 100
                    lv_passed = abs(pct_dev) <= 20
                    conn.execute(
                        "INSERT INTO calibration_levels "
                        "(calibration_id,level,expected,calculated,pct_deviation,passed) "
                        "VALUES (?,?,?,?,?,?)",
                        (cal_id, lv_idx + 1, expected, round(calc, 4),
                         round(pct_dev, 2), 1 if lv_passed else 0),
                    )

    conn.commit()
    conn.close()

    # Count what we seeded
    conn2 = sqlite3.connect(db_path)
    n_qc  = conn2.execute(
        "SELECT COUNT(*) FROM qc_results WHERE flag LIKE ?", (TEST_FLAG + "%",)
    ).fetchone()[0]
    n_cal = conn2.execute(
        "SELECT COUNT(*) FROM calibrations WHERE notes LIKE ?", ("%TEST_DATA%",)
    ).fetchone()[0]
    conn2.close()

    print("Seeded {} QC result rows and {} calibration rows into {}.".format(
        n_qc, n_cal, db_path))
    print("Analytes: {}".format(", ".join(ANALYTES)))
    print("Methods:  {}".format(", ".join(METHODS.keys())))
    print("QC types: CCV, LFB  |  {} weeks of data each".format(N_WEEKS))
    print()
    print("To purge before go-live:")
    print("  python3 seed_test_data.py --purge")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purge", action="store_true",
                        help="Remove all TEST_DATA records from the database")
    parser.add_argument("--db", default=DB_PATH,
                        help="Path to the SQLite QC database (default: {})".format(DB_PATH))
    args = parser.parse_args()

    if args.purge:
        purge(args.db)
    else:
        seed(args.db)


if __name__ == "__main__":
    main()
