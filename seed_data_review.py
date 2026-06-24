# -*- coding: utf-8 -*-
"""
Seed script: populate a mock Data Review batch for WS-0001.

Creates:
  - CoC logbook annotation on WS-0001
  - FM-ENV-251 (Cal Prep) annotation on WS-0001
  - FM-ENV-252 (Extraction) annotation on WS-0001
  - QC results in SQLite for WS-0001 (LCS, CCV, CCB, MB, Dup)
  - Batch row in SQLite linking WS-0001 to run_date 2026-06-24

Run with:
    docker compose exec senaite bin/instance run \
        /home/app/senaite_pfas/seed_data_review.py

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import os
import sqlite3
import sys
import transaction

from zope.annotation.interfaces import IAnnotations

DB_PATH   = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
WS_ID     = "WS-0001"
RUN_DATE  = "2026-06-24"
ANALYST   = "J. Smith"
INSTRUMENT= "Sciex 6500+ QTRAP"
METHOD    = "fda-32-pfas"
FLAG      = "SEED_DATA_REVIEW"

# Analytes to include
ANALYTES = [
    "PFBA", "PFPeA", "PFHxA", "PFHpA", "PFOA", "PFNA", "PFDA",
    "PFUnDA", "PFDoDA", "PFTeDA",
    "PFBS", "PFPeS", "PFHxS", "PFHpS", "PFOS", "PFDS",
    "HFPO-DA", "ADONA", "9Cl-PF3ONS", "11Cl-PF3OUdS",
]

# ── Logbook data ──────────────────────────────────────────────────────────────

_COC = {
    "client_name":            "Maine DHHS Toxicology Lab",
    "project_name":           "2025 Dietary PFAS Surveillance",
    "project_number":         "ME-TOX-2025-047",
    "sample_collection_date": "2026-06-20",
    "sampler_name":           "R. Hartwell",
    "sample_preservation":    "Frozen (-20C), amber HDPE",
    "containers": [
        {"sample_id": "ME-047-001", "container_type": "50 mL PP tube",  "volume_ml": 45, "temp_c": -20, "condition": "Good"},
        {"sample_id": "ME-047-002", "container_type": "50 mL PP tube",  "volume_ml": 47, "temp_c": -20, "condition": "Good"},
        {"sample_id": "ME-047-003", "container_type": "50 mL PP tube",  "volume_ml": 43, "temp_c": -20, "condition": "Good"},
        {"sample_id": "ME-047-004", "container_type": "50 mL PP tube",  "volume_ml": 46, "temp_c": -20, "condition": "Slight condensation on lid"},
        {"sample_id": "ME-047-005", "container_type": "50 mL PP tube",  "volume_ml": 44, "temp_c": -20, "condition": "Good"},
        {"sample_id": "QC-LFB-001", "container_type": "20 mL glass vial","volume_ml": 18, "temp_c": -20, "condition": "Good"},
    ],
    "transfers": [
        {"relinquished_by": "R. Hartwell",  "relinquished_at": "2026-06-20 14:30",
         "received_by":     "FedEx",        "received_at":     "2026-06-20 15:00",  "method": "Courier (FedEx Priority Overnight)"},
        {"relinquished_by": "FedEx",        "relinquished_at": "2026-06-21 09:15",
         "received_by":     "Lab Intake",   "received_at":     "2026-06-21 09:15",  "method": "Courier delivery"},
    ],
    "lab_received_by":    "K. Chen",
    "lab_received_date":  "2026-06-21",
    "seals_intact":       True,
    "labels_legible":     True,
    "holding_time_ok":    True,
    "condition_notes":    "All samples received frozen. Sample ME-047-004 had slight condensation on lid; sample temperature confirmed at -20C on receipt. Acceptable.",
    "reviewed_by":        "Dr. M. Okafor",
    "reviewed_date":      "2026-06-23",
}

_LB_251 = {
    "analyst":            ANALYST,
    "prepared_date":      "2026-06-22",
    "reviewed_by":        "K. Chen",
    "reviewed_date":      "2026-06-22",
    "pds_a_lot":          "PS-FDA-2026-A",
    "pds_b_lot":          "PS-FDA-2026-B",
    "analyte_pds_lot":    "PS-FDA-2026-C",
    "analyte_spike_lot":  "PS-SRG-2026-001",
    "cal_a_lot":          "PS-CAL-2026-A",
    "notes":              "All prepared standards within holding time. IS spike confirmed at 50 uL per extract.",
    "standards": [
        {"name": "FDA Mixed Native PDS",    "lot": "PS-FDA-2026-A",   "conc_ng_ml": 1000, "volume_ul": 50,  "expiry": "2026-09-22"},
        {"name": "FDA IS/SRG Mix",          "lot": "PS-SRG-2026-001", "conc_ng_ml": 500,  "volume_ul": 50,  "expiry": "2026-08-15"},
        {"name": "FDA CAL-A Stock",         "lot": "PS-CAL-2026-A",   "conc_ng_ml": 200,  "volume_ul": 200, "expiry": "2026-07-30"},
    ],
}

_LB_252 = {
    "analyst":          ANALYST,
    "extraction_date":  "2026-06-23",
    "reviewed_by":      "K. Chen",
    "reviewed_date":    "2026-06-23",
    "balance_sn":       "Mettler XS205 SN-001",
    "instrument_id":    INSTRUMENT,
    "notes":            "Extraction per FDA 2020 SOP Rev 4. All spike recoveries within 70-130%.",
    "reagents": [
        {"name": "Methanol LC-MS",      "lot": "FISHER-MEOH-260510", "supplier": "Fisher Scientific",    "volume": "500 mL",   "expiry": "2028-01-01"},
        {"name": "Ammonium Acetate",    "lot": "SIGMA-AA-260601",    "supplier": "Sigma-Aldrich",         "volume": "3.854 g",  "expiry": "2027-12-31"},
        {"name": "Water LC-MS",         "lot": "FISHER-H2O-260510",  "supplier": "Fisher Scientific",    "volume": "500 mL",   "expiry": "2028-01-01"},
        {"name": "Acetic Acid LCMS",    "lot": "SIGMA-AC-260301",    "supplier": "Sigma-Aldrich",         "volume": "2 mL",     "expiry": "2027-06-01"},
        {"name": "Oasis WAX SPE (1cc)", "lot": "WAX-260501",         "supplier": "Waters Corporation",   "volume": "24 ctg",   "expiry": "2027-05-01"},
    ],
    "standards": [
        {"name": "FDA Mixed Native PDS", "lot": "PS-FDA-2026-A",   "conc": "1000 ng/mL", "volume": "50 uL"},
        {"name": "FDA IS/SRG Mix",       "lot": "PS-SRG-2026-001", "conc": "500 ng/mL",  "volume": "50 uL"},
    ],
    "samples": [
        {"sample_id": "ME-047-001", "weight_g": 2.013, "matrix": "Meat (beef)", "notes": ""},
        {"sample_id": "ME-047-002", "weight_g": 2.008, "matrix": "Meat (beef)", "notes": ""},
        {"sample_id": "ME-047-003", "weight_g": 2.001, "matrix": "Egg",         "notes": ""},
        {"sample_id": "ME-047-004", "weight_g": 1.998, "matrix": "Egg",         "notes": "Slight condensation on receipt; sample OK"},
        {"sample_id": "ME-047-005", "weight_g": 2.010, "matrix": "Seafood",     "notes": ""},
        {"sample_id": "MB-001",     "weight_g": 0.0,   "matrix": "Method Blank","notes": "No sample material"},
        {"sample_id": "LFB-001",    "weight_g": 2.005, "matrix": "Meat (beef)", "notes": "Lab-fortified blank"},
    ],
}


# ── SQLite QC rows ────────────────────────────────────────────────────────────

def _qc_rows(batch_id, run_date):
    """Generate realistic QC result rows for all analytes."""
    import random
    random.seed(99)  # reproducible

    rows = []

    def _add(qc_type, qc_level, analyte, value, expected, passed, flag=""):
        rows.append({
            "batch_id":      batch_id,
            "run_date":      run_date,
            "analyte":       analyte,
            "qc_type":       qc_type,
            "qc_level":      qc_level,
            "method":        METHOD,
            "analyst":       ANALYST,
            "instrument_id": INSTRUMENT,
            "value":         value,
            "expected_value":expected,
            "units":         "ng/kg",
            "flag":          flag,
            "passed":        1 if passed else 0,
            "result_status": "active",
        })

    for analyte in ANALYTES:
        base_recovery = 85.0 + random.uniform(-8.0, 15.0)  # 77-100%
        expected_conc = 100.0

        # LCS — Lab Control Sample (native spike into clean matrix)
        lcs_rec = base_recovery + random.uniform(-5.0, 5.0)
        lcs_val = expected_conc * (lcs_rec / 100.0)
        lcs_pass = 70.0 <= lcs_rec <= 130.0
        _add("LCS", "LCS-1", analyte, round(lcs_val, 2), expected_conc, lcs_pass)

        # LFB — Lab Fortified Blank
        lfb_rec = base_recovery + random.uniform(-6.0, 6.0)
        lfb_val = expected_conc * (lfb_rec / 100.0)
        lfb_pass = 70.0 <= lfb_rec <= 130.0
        _add("LFB", "LFB-1", analyte, round(lfb_val, 2), expected_conc, lfb_pass)

        # CCV — Continuing Calibration Verification
        ccv_rec = 96.0 + random.uniform(-6.0, 6.0)
        ccv_val = expected_conc * (ccv_rec / 100.0)
        ccv_pass = 80.0 <= ccv_rec <= 120.0
        _add("CCV", "CCV-1", analyte, round(ccv_val, 2), expected_conc, ccv_pass)

        # CCB — Continuing Calibration Blank (near-zero)
        ccb_val = random.uniform(0.0, 0.08)  # below MDL
        ccb_pass = ccb_val < 0.5
        _add("CCB", "CCB-1", analyte, round(ccb_val, 4), None, ccb_pass)

        # MB — Method Blank
        mb_val = random.uniform(0.0, 0.05)
        mb_pass = mb_val < 0.5
        _add("MB", "MB-1", analyte, round(mb_val, 4), None, mb_pass)

    # Add one intentional PFOS LCS warning (high recovery edge case)
    for r in rows:
        if r["analyte"] == "PFOS" and r["qc_type"] == "LCS":
            r["value"]  = 127.5
            r["passed"] = 1  # passes but near limit
            r["flag"]   = "Near upper limit (127.5%)"

    return rows


# ── SQLite write ──────────────────────────────────────────────────────────────

def _seed_sqlite(batch_id, run_date):
    if not os.path.exists(DB_PATH):
        print("WARNING: SQLite DB not found at %s — creating fresh DB." % DB_PATH)
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Ensure tables exist
    _SCHEMA = [
        """CREATE TABLE IF NOT EXISTS batches (
            batch_id      TEXT PRIMARY KEY,
            run_date      TEXT NOT NULL,
            analyst       TEXT NOT NULL DEFAULT '',
            instrument_id TEXT NOT NULL DEFAULT '',
            method        TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'open',
            notes         TEXT NOT NULL DEFAULT '',
            flag          TEXT NOT NULL DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS qc_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id      TEXT NOT NULL,
            run_date      TEXT NOT NULL,
            analyte       TEXT NOT NULL,
            qc_type       TEXT NOT NULL,
            qc_level      TEXT NOT NULL DEFAULT '',
            method        TEXT NOT NULL DEFAULT '',
            analyst       TEXT NOT NULL DEFAULT '',
            instrument_id TEXT NOT NULL DEFAULT '',
            value         REAL,
            units         TEXT NOT NULL DEFAULT '',
            flag          TEXT NOT NULL DEFAULT '',
            passed        INTEGER NOT NULL DEFAULT 1,
            result_status TEXT NOT NULL DEFAULT 'active',
            parent_id     INTEGER,
            created_at    TEXT,
            expected_value REAL
        )""",
    ]
    for ddl in _SCHEMA:
        conn.execute(ddl)
    conn.commit()

    # Add expected_value column if missing (migration)
    try:
        conn.execute("SELECT expected_value FROM qc_results LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE qc_results ADD COLUMN expected_value REAL")
        conn.commit()

    # Check if this batch already seeded
    existing = conn.execute(
        "SELECT batch_id FROM batches WHERE batch_id=?", (batch_id,)
    ).fetchone()

    if existing:
        print("Batch %s already exists in SQLite — removing old QC rows." % batch_id)
        conn.execute("DELETE FROM qc_results WHERE batch_id=?", (batch_id,))
        conn.execute("DELETE FROM batches WHERE batch_id=?", (batch_id,))
        conn.commit()

    import datetime
    now = datetime.datetime.utcnow().isoformat()

    conn.execute(
        "INSERT INTO batches (batch_id,run_date,analyst,instrument_id,method,"
        "status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (batch_id, run_date, ANALYST, INSTRUMENT, METHOD,
         "open", "Seeded mock data for Data Review demo [%s]" % FLAG, now, now),
    )

    rows = _qc_rows(batch_id, run_date)
    for r in rows:
        conn.execute(
            "INSERT INTO qc_results "
            "(batch_id,run_date,analyte,qc_type,qc_level,method,analyst,"
            "instrument_id,value,expected_value,units,flag,passed,result_status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["batch_id"], r["run_date"], r["analyte"], r["qc_type"],
             r["qc_level"], r["method"], r["analyst"], r["instrument_id"],
             r["value"], r["expected_value"], r["units"], r["flag"],
             r["passed"], r["result_status"], now),
        )

    conn.commit()
    conn.close()
    print("SQLite: inserted 1 batch + %d QC rows for %s." % (len(rows), batch_id))


# ── ZODB / SENAITE writes ─────────────────────────────────────────────────────

def _save_ann(ws, key, data):
    IAnnotations(ws)[key] = json.dumps(data, ensure_ascii=False)


def _seed_senaite(portal, ws_id):
    ws_folder = getattr(portal, "worksheets", None)
    if ws_folder is None:
        print("ERROR: No 'worksheets' folder in portal.")
        sys.exit(1)

    ws = ws_folder.get(ws_id)
    if ws is None:
        print("ERROR: Worksheet '%s' not found." % ws_id)
        print("Available: %s" % list(ws_folder.objectIds())[:10])
        sys.exit(1)
    print("Found worksheet: %s" % ws.absolute_url())

    _save_ann(ws, u"senaite.pfas.logbook.coc", _COC)
    _save_ann(ws, u"senaite.pfas.logbook.251", _LB_251)
    _save_ann(ws, u"senaite.pfas.logbook.252", _LB_252)

    print("Logbook annotations written (coc, 251, 252).")
    transaction.commit()
    print("Transaction committed.")


# ── Entry point ───────────────────────────────────────────────────────────────

def run(app):
    from zope.site.hooks import setSite, setHooks
    setHooks()
    portal = app.senaite
    setSite(portal)

    from AccessControl.SecurityManagement import newSecurityManager
    user = app.acl_users.getUser("admin")
    if user is None:
        print("ERROR: admin user not found")
        sys.exit(1)
    newSecurityManager(None, user.__of__(app.acl_users))

    print("=== Seeding Data Review mock data for %s ===" % WS_ID)

    # 1. Write logbook annotations into SENAITE
    _seed_senaite(portal, WS_ID)

    # 2. Write QC results into SQLite (no ZODB transaction needed)
    _seed_sqlite(WS_ID, RUN_DATE)

    print("")
    print("Done. Open the Data Review at:")
    print("  http://localhost:8080/senaite/worksheets/%s/@@pfas-data-review" % WS_ID)


if __name__ == "__main__":
    run(app)  # noqa: F821 — 'app' injected by `bin/instance run`
