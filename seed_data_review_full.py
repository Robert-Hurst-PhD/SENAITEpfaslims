# -*- coding: utf-8 -*-
"""
Full Data Review seed: WS-0001 with reagents, prepared standards,
logbook annotations (CoC, FM-ENV-251, FM-ENV-252), and QC SQLite data.

Run inside the container:
    docker exec senaite_pfas-senaite-1 \
        bin/instance run /addon/seed_data_review_full.py

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
import json
import os
import sqlite3
import sys
import uuid

import transaction
from zope.annotation.interfaces import IAnnotations

DB_PATH    = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
WS_ID      = "WS-0001"
RUN_DATE   = "2026-06-24"
ANALYST    = "J. Smith"
INSTRUMENT = "Sciex 6500+ QTRAP"
METHOD     = "fda-32-pfas"

ANALYTES = [
    "PFBA", "PFPeA", "PFHxA", "PFHpA", "PFOA", "PFNA", "PFDA",
    "PFUnDA", "PFDoDA", "PFTeDA",
    "PFBS", "PFPeS", "PFHxS", "PFHpS", "PFOS", "PFDS",
    "HFPO-DA", "ADONA", "9Cl-PF3ONS", "11Cl-PF3OUdS",
]

# ── Inventory: certified reference materials (parent reagents for PSs) ────────

_CRMS = [
    {
        "lot": "WGN-PFAS32-2026",
        "name": "Wellington PFAS 32-Mix Native Standard",
        "supplier": "Wellington Laboratories",
        "cat_number": "PFAS-MXB",
        "received_date": "2026-01-15",
        "expiry_date": "2027-01-15",
        "storage_location": "Freezer A-2",
        "quantity": "1",
        "unit": "mL",
    },
    {
        "lot": "WGN-IS-2026",
        "name": "Wellington PFAS IS/Surrogate Mix",
        "supplier": "Wellington Laboratories",
        "cat_number": "PFAS-IS-MXB",
        "received_date": "2026-01-15",
        "expiry_date": "2027-01-15",
        "storage_location": "Freezer A-2",
        "quantity": "1",
        "unit": "mL",
    },
]

# ── Inventory: extraction reagents (referenced in FM-ENV-252 logbook) ─────────

_REAGENTS = [
    {
        "lot": "FISHER-MEOH-260510",
        "name": "Methanol LC-MS Grade",
        "supplier": "Fisher Scientific",
        "cat_number": "A456-4",
        "received_date": "2026-05-10",
        "expiry_date": "2028-01-01",
        "storage_location": "Flammables Cabinet B",
        "quantity": "4",
        "unit": "L",
    },
    {
        "lot": "SIGMA-AA-260601",
        "name": "Ammonium Acetate ≥99%",
        "supplier": "Sigma-Aldrich",
        "cat_number": "73594",
        "received_date": "2026-06-01",
        "expiry_date": "2027-12-31",
        "storage_location": "Chemicals Shelf C-1",
        "quantity": "100",
        "unit": "g",
    },
    {
        "lot": "FISHER-H2O-260510",
        "name": "Water LC-MS Grade",
        "supplier": "Fisher Scientific",
        "cat_number": "W6-4",
        "received_date": "2026-05-10",
        "expiry_date": "2028-01-01",
        "storage_location": "Reagent Shelf A",
        "quantity": "4",
        "unit": "L",
    },
    {
        "lot": "SIGMA-AC-260301",
        "name": "Acetic Acid LC-MS Grade",
        "supplier": "Sigma-Aldrich",
        "cat_number": "49199",
        "received_date": "2026-03-01",
        "expiry_date": "2027-06-01",
        "storage_location": "Acids Cabinet",
        "quantity": "100",
        "unit": "mL",
    },
    {
        "lot": "WAX-260501",
        "name": "Oasis WAX SPE (1 cc/30 mg)",
        "supplier": "Waters Corporation",
        "cat_number": "186004616",
        "received_date": "2026-05-01",
        "expiry_date": "2027-05-01",
        "storage_location": "SPE Storage Room",
        "quantity": "96",
        "unit": "cartridges",
    },
]

# ── Prepared standards (lot numbers referenced in FM-ENV-251 / FM-ENV-252) ────

_PREP_STANDARDS = [
    {
        "lot": "PS-FDA-2026-A",
        "title": "FDA Native PDS-A (1000 ng/mL)",
        "ps_type": "Calibration Standard",
        "prepared_by": ANALYST,
        "prepared_date": "2026-06-22",
        "expiry_date": "2026-09-22",
        "parent_reagents": [
            {"name": "Wellington PFAS 32-Mix Native Standard",
             "supplier": "Wellington Laboratories",
             "lot": "WGN-PFAS32-2026",
             "qty": "50", "unit": "uL"},
            {"name": "Methanol LC-MS Grade",
             "supplier": "Fisher Scientific",
             "lot": "FISHER-MEOH-260510",
             "qty": "950", "unit": "uL"},
        ],
    },
    {
        "lot": "PS-FDA-2026-B",
        "title": "FDA Native PDS-B (500 ng/mL)",
        "ps_type": "Calibration Standard",
        "prepared_by": ANALYST,
        "prepared_date": "2026-06-22",
        "expiry_date": "2026-09-22",
        "parent_reagents": [
            {"name": "Wellington PFAS 32-Mix Native Standard",
             "supplier": "Wellington Laboratories",
             "lot": "WGN-PFAS32-2026",
             "qty": "25", "unit": "uL"},
            {"name": "Methanol LC-MS Grade",
             "supplier": "Fisher Scientific",
             "lot": "FISHER-MEOH-260510",
             "qty": "975", "unit": "uL"},
        ],
    },
    {
        "lot": "PS-FDA-2026-C",
        "title": "FDA Native PDS-C (250 ng/mL)",
        "ps_type": "Calibration Standard",
        "prepared_by": ANALYST,
        "prepared_date": "2026-06-22",
        "expiry_date": "2026-09-22",
        "parent_reagents": [
            {"name": "Wellington PFAS 32-Mix Native Standard",
             "supplier": "Wellington Laboratories",
             "lot": "WGN-PFAS32-2026",
             "qty": "12.5", "unit": "uL"},
            {"name": "Methanol LC-MS Grade",
             "supplier": "Fisher Scientific",
             "lot": "FISHER-MEOH-260510",
             "qty": "987.5", "unit": "uL"},
        ],
    },
    {
        "lot": "PS-SRG-2026-001",
        "title": "FDA IS/Surrogate Mix (500 ng/mL)",
        "ps_type": "Surrogate Mix",
        "prepared_by": ANALYST,
        "prepared_date": "2026-06-22",
        "expiry_date": "2026-08-15",
        "parent_reagents": [
            {"name": "Wellington PFAS IS/Surrogate Mix",
             "supplier": "Wellington Laboratories",
             "lot": "WGN-IS-2026",
             "qty": "50", "unit": "uL"},
            {"name": "Methanol LC-MS Grade",
             "supplier": "Fisher Scientific",
             "lot": "FISHER-MEOH-260510",
             "qty": "950", "unit": "uL"},
        ],
    },
    {
        "lot": "PS-CAL-2026-A",
        "title": "FDA CAL-A Stock (200 ng/mL)",
        "ps_type": "Calibration Standard",
        "prepared_by": ANALYST,
        "prepared_date": "2026-06-22",
        "expiry_date": "2026-07-30",
        "parent_reagents": [
            {"name": "Wellington PFAS 32-Mix Native Standard",
             "supplier": "Wellington Laboratories",
             "lot": "WGN-PFAS32-2026",
             "qty": "10", "unit": "uL"},
            {"name": "Methanol LC-MS Grade",
             "supplier": "Fisher Scientific",
             "lot": "FISHER-MEOH-260510",
             "qty": "990", "unit": "uL"},
        ],
    },
]

# ── Logbook annotations ───────────────────────────────────────────────────────

_COC = {
    "client_name":            "Maine DHHS Toxicology Lab",
    "project_name":           "2025 Dietary PFAS Surveillance",
    "project_number":         "ME-TOX-2025-047",
    "sample_collection_date": "2026-06-20",
    "sampler_name":           "R. Hartwell",
    "sample_preservation":    "Frozen (-20°C), amber HDPE",
    "containers": [
        {"sample_id": "ME-047-001", "container_type": "50 mL PP tube",   "volume_ml": 45, "temp_c": -20, "condition": "Good"},
        {"sample_id": "ME-047-002", "container_type": "50 mL PP tube",   "volume_ml": 47, "temp_c": -20, "condition": "Good"},
        {"sample_id": "ME-047-003", "container_type": "50 mL PP tube",   "volume_ml": 43, "temp_c": -20, "condition": "Good"},
        {"sample_id": "ME-047-004", "container_type": "50 mL PP tube",   "volume_ml": 46, "temp_c": -20, "condition": "Slight condensation on lid"},
        {"sample_id": "ME-047-005", "container_type": "50 mL PP tube",   "volume_ml": 44, "temp_c": -20, "condition": "Good"},
        {"sample_id": "QC-LFB-001", "container_type": "20 mL glass vial","volume_ml": 18, "temp_c": -20, "condition": "Good"},
    ],
    "transfers": [
        {"relinquished_by": "R. Hartwell", "relinquished_at": "2026-06-20 14:30",
         "received_by": "FedEx", "received_at": "2026-06-20 15:00",
         "method": "Courier (FedEx Priority Overnight)"},
        {"relinquished_by": "FedEx", "relinquished_at": "2026-06-21 09:15",
         "received_by": "Lab Intake", "received_at": "2026-06-21 09:15",
         "method": "Courier delivery"},
    ],
    "lab_received_by":    "K. Chen",
    "lab_received_date":  "2026-06-21",
    "seals_intact":       True,
    "labels_legible":     True,
    "holding_time_ok":    True,
    "condition_notes":    "All samples received frozen. ME-047-004 had slight condensation on lid; confirmed -20°C on receipt. Acceptable.",
    "reviewed_by":        "Dr. M. Okafor",
    "reviewed_date":      "2026-06-23",
}

_LB_251 = {
    "analyst":           ANALYST,
    "prepared_date":     "2026-06-22",
    "reviewed_by":       "K. Chen",
    "reviewed_date":     "2026-06-22",
    "pds_a_lot":         "PS-FDA-2026-A",
    "pds_b_lot":         "PS-FDA-2026-B",
    "analyte_pds_lot":   "PS-FDA-2026-C",
    "analyte_spike_lot": "PS-SRG-2026-001",
    "cal_a_lot":         "PS-CAL-2026-A",
    "icv_conc_ng_ml":    50.0,
    "ccv_conc_ng_ml":    50.0,
    "notes":             "All prepared standards within holding time. IS spike confirmed at 50 µL per extract.",
    "standards": [
        {"name": "FDA Mixed Native PDS",  "lot": "PS-FDA-2026-A",   "conc_ng_ml": 1000, "volume_ul": 50,  "expiry": "2026-09-22"},
        {"name": "FDA IS/SRG Mix",        "lot": "PS-SRG-2026-001", "conc_ng_ml": 500,  "volume_ul": 50,  "expiry": "2026-08-15"},
        {"name": "FDA CAL-A Stock",       "lot": "PS-CAL-2026-A",   "conc_ng_ml": 200,  "volume_ul": 200, "expiry": "2026-07-30"},
    ],
}

_LB_252 = {
    "analyst":         ANALYST,
    "extraction_date": "2026-06-23",
    "reviewed_by":     "K. Chen",
    "reviewed_date":   "2026-06-23",
    "balance_sn":      "Mettler XS205 SN-001",
    "instrument_id":   INSTRUMENT,
    "notes":           "Extraction per FDA 2020 SOP Rev 4. All spike recoveries within 70-130%.",
    "reagents": [
        {"name": "Methanol LC-MS",      "lot": "FISHER-MEOH-260510", "supplier": "Fisher Scientific",  "volume": "500 mL",  "expiry": "2028-01-01"},
        {"name": "Ammonium Acetate",    "lot": "SIGMA-AA-260601",    "supplier": "Sigma-Aldrich",       "volume": "3.854 g", "expiry": "2027-12-31"},
        {"name": "Water LC-MS",         "lot": "FISHER-H2O-260510",  "supplier": "Fisher Scientific",  "volume": "500 mL",  "expiry": "2028-01-01"},
        {"name": "Acetic Acid LCMS",    "lot": "SIGMA-AC-260301",    "supplier": "Sigma-Aldrich",       "volume": "2 mL",    "expiry": "2027-06-01"},
        {"name": "Oasis WAX SPE (1cc)", "lot": "WAX-260501",         "supplier": "Waters Corporation", "volume": "24 ctg",  "expiry": "2027-05-01"},
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

# ── SQLite QC data ────────────────────────────────────────────────────────────

def _qc_rows(batch_id, run_date):
    import random
    random.seed(99)
    rows = []

    def _add(qc_type, qc_level, analyte, value, expected, passed, flag="", status="active"):
        rows.append({
            "batch_id": batch_id, "run_date": run_date,
            "analyte": analyte, "qc_type": qc_type, "qc_level": qc_level,
            "method": METHOD, "analyst": ANALYST, "instrument_id": INSTRUMENT,
            "value": value, "expected_value": expected,
            "units": "ng/kg", "flag": flag,
            "passed": 1 if passed else 0, "result_status": status,
        })

    for analyte in ANALYTES:
        base = 85.0 + random.uniform(-8.0, 15.0)
        exp  = 100.0

        # LCS
        rec = base + random.uniform(-5.0, 5.0)
        _add("LCS", "LCS-1", analyte, round(exp * rec / 100.0, 2), exp, 70 <= rec <= 130)

        # LFB
        rec = base + random.uniform(-6.0, 6.0)
        _add("LFB", "LFB-1", analyte, round(exp * rec / 100.0, 2), exp, 70 <= rec <= 130)

        # CCV
        rec = 96.0 + random.uniform(-6.0, 6.0)
        _add("CCV", "CCV-1", analyte, round(exp * rec / 100.0, 2), exp, 80 <= rec <= 120)

        # CCB — near-zero
        val = round(random.uniform(0.0, 0.08), 4)
        _add("CCB", "CCB-1", analyte, val, None, val < 0.5)

        # MB — method blank
        val = round(random.uniform(0.0, 0.05), 4)
        _add("MB",  "MB-1",  analyte, val, None, val < 0.5)

    # One realistic near-limit flag on PFOS LCS
    for r in rows:
        if r["analyte"] == "PFOS" and r["qc_type"] == "LCS":
            r["value"] = 127.5
            r["passed"] = 1
            r["flag"] = "Near upper limit (127.5%)"

    return rows


def _seed_sqlite(batch_id, run_date):
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

    conn = sqlite3.connect(DB_PATH)
    for ddl in [
        """CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY, run_date TEXT NOT NULL,
            analyst TEXT NOT NULL DEFAULT '', instrument_id TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
            notes TEXT NOT NULL DEFAULT '', created_at TEXT, updated_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS qc_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL, run_date TEXT NOT NULL,
            analyte TEXT NOT NULL, qc_type TEXT NOT NULL,
            qc_level TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '',
            analyst TEXT NOT NULL DEFAULT '', instrument_id TEXT NOT NULL DEFAULT '',
            value REAL, expected_value REAL, units TEXT NOT NULL DEFAULT '',
            flag TEXT NOT NULL DEFAULT '', passed INTEGER NOT NULL DEFAULT 1,
            result_status TEXT NOT NULL DEFAULT 'active',
            parent_id INTEGER, created_at TEXT)""",
    ]:
        conn.execute(ddl)
    conn.commit()

    now = datetime.datetime.utcnow().isoformat()
    conn.execute("DELETE FROM qc_results WHERE batch_id=?", (batch_id,))
    conn.execute("DELETE FROM batches   WHERE batch_id=?", (batch_id,))
    conn.execute(
        "INSERT INTO batches (batch_id,run_date,analyst,instrument_id,method,status,notes,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (batch_id, run_date, ANALYST, INSTRUMENT, METHOD, "open",
         "Seeded mock data — Data Review demo", now, now),
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
    print("SQLite: 1 batch + %d QC rows for %s" % (len(rows), batch_id))


# ── Reagent / PreparedStandard creation ───────────────────────────────────────

def _str_to_date(s):
    if not s:
        return None
    try:
        parts = [int(x) for x in s.split("-")]
        return datetime.date(parts[0], parts[1], parts[2])
    except Exception:
        return None


def _create_reagent(folder, spec):
    lot  = spec["lot"]
    name = spec["name"]
    # Find existing by lot number
    for obj in folder.objectValues():
        if getattr(obj, "lot_number", "") == lot:
            print("  Reagent already exists: %s (%s)" % (lot, name))
            return obj

    uid = uuid.uuid4().hex
    folder.invokeFactory("Reagent", id=uid, title=name)
    obj = folder[uid]
    obj.supplier          = spec.get("supplier", u"")
    obj.cat_number        = spec.get("cat_number", u"")
    obj.lot_number        = lot
    obj.storage_location  = spec.get("storage_location", u"")
    obj.quantity          = spec.get("quantity", u"")
    obj.unit              = spec.get("unit", u"")
    obj.received_date     = _str_to_date(spec.get("received_date"))
    obj.expiry_date       = _str_to_date(spec.get("expiry_date"))
    try:
        obj.reindexObject()
    except Exception:
        pass
    print("  Created Reagent: %s (%s)" % (lot, name))
    return obj


def _create_ps(folder, spec):
    lot   = spec["lot"]
    title = spec["title"]
    for obj in folder.objectValues():
        if getattr(obj, "lot_number", "") == lot:
            print("  PreparedStandard already exists: %s" % lot)
            return obj

    uid = uuid.uuid4().hex
    folder.invokeFactory("PreparedStandard", id=uid, title=title)
    obj = folder[uid]
    obj.lot_number    = lot
    obj.ps_type       = spec.get("ps_type", u"Calibration Standard")
    obj.prepared_by   = spec.get("prepared_by", u"")
    obj.prepared_date = _str_to_date(spec.get("prepared_date"))
    obj.expiry_date   = _str_to_date(spec.get("expiry_date"))
    IAnnotations(obj)[u"senaite.pfas.prepstd.parent_reagents"] = \
        json.dumps(spec.get("parent_reagents") or [], ensure_ascii=False)
    try:
        obj.reindexObject()
    except Exception:
        pass
    print("  Created PreparedStandard: %s (%s)" % (lot, title))
    return obj


def _seed_inventory(portal):
    reagent_folder = portal.get("pfas_reagents")
    if reagent_folder is None:
        print("ERROR: pfas_reagents folder missing — run addon reinstall first.")
        sys.exit(1)
    ps_folder = portal.get("pfas_prepared_standards")
    if ps_folder is None:
        print("ERROR: pfas_prepared_standards folder missing — run addon reinstall first.")
        sys.exit(1)

    print("\n-- Reagents (CRMs) --")
    for spec in _CRMS:
        _create_reagent(reagent_folder, spec)

    print("\n-- Reagents (extraction solvents/consumables) --")
    for spec in _REAGENTS:
        _create_reagent(reagent_folder, spec)

    print("\n-- Prepared Standards --")
    for spec in _PREP_STANDARDS:
        _create_ps(ps_folder, spec)


# ── Logbook annotations ───────────────────────────────────────────────────────

def _seed_logbooks(portal, ws_id):
    ws_folder = getattr(portal, "worksheets", None)
    if ws_folder is None:
        print("ERROR: No 'worksheets' folder in portal.")
        sys.exit(1)
    ws = ws_folder.get(ws_id)
    if ws is None:
        print("ERROR: Worksheet '%s' not found. Available: %s"
              % (ws_id, list(ws_folder.objectIds())[:10]))
        sys.exit(1)
    print("\n-- Logbooks on %s --" % ws.absolute_url())
    ann = IAnnotations(ws)
    ann[u"senaite.pfas.logbook.coc"] = json.dumps(_COC, ensure_ascii=False)
    ann[u"senaite.pfas.logbook.251"] = json.dumps(_LB_251, ensure_ascii=False)
    ann[u"senaite.pfas.logbook.252"] = json.dumps(_LB_252, ensure_ascii=False)
    print("  Written: CoC, FM-ENV-251, FM-ENV-252")


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

    print("=== Seeding full Data Review dataset for %s ===" % WS_ID)

    _seed_inventory(portal)
    transaction.commit()
    print("\nInventory committed.")

    _seed_logbooks(portal, WS_ID)
    transaction.commit()
    print("Logbooks committed.")

    _seed_sqlite(WS_ID, RUN_DATE)

    print("\n=== Done ===")
    print("Open: http://localhost:8080/senaite/worksheets/%s/@@pfas-data-review" % WS_ID)
    print("Or:   http://localhost:8080/senaite/@@pfas-data-review?batch_id=%s" % WS_ID)


if __name__ == "__main__":
    run(app)  # noqa: F821 — app injected by bin/instance run
