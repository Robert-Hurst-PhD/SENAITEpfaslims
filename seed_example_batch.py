# -*- coding: utf-8 -*-
"""
Seed script: create one realistic FDA_32PFAS example batch with all four
logbooks (FM-ENV-250 through 253) fully populated.

Run with:
    docker compose exec senaite bin/instance run /home/app/senaite_pfas/seed_example_batch.py

The batch is tagged "EXAMPLE-BATCH" so it can be removed by running this
script again with --clear (or by deleting it manually via the SENAITE UI).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import sys
import transaction

from zope.annotation.interfaces import IAnnotations

# ── Logbook data ───────────────────────────────────────────────────────────────

_BATCH_TITLE = u"EXAMPLE-BATCH-FDA32"

_LOGBOOK_KEY_PREFIX = u"senaite.pfas.logbook."

_LB_250 = {
    "prepared_by": "J. Smith",
    "prepared_date": "2026-06-01",
    "reviewed_by": "K. Doe",
    "reviewed_date": "2026-06-01",
    "ammonium_acetate_weight_g": "3.854",
    "balance_sn": "SN-BAL-001",
    "notes": "Example batch — delete before production use.",
    "solutions": [
        {"name": "FDA-MPH2O",     "volume_ml": 500, "lot_number": "FDA-MPH2O-260601",     "expiry": "2026-06-08"},
        {"name": "FDA-MPMeOH",    "volume_ml": 500, "lot_number": "FDA-MPMEOH-260601",    "expiry": "2026-06-08"},
        {"name": "FDA-Pre-Ex-I",  "volume_ml": 100, "lot_number": "FDA-PRE-EX-I-260601",  "expiry": "2027-06-01"},
        {"name": "FDA-Pre-Ex-II", "volume_ml": 100, "lot_number": "FDA-PRE-EX-II-260601", "expiry": "2027-06-01"},
    ],
    "chemicals": [
        {"material": "Ammonium Acetate", "vendor": "Sigma-Aldrich", "part_num": "A1542",  "lot_num": "BCCD1234", "expiry": "2027-12-31"},
        {"material": "Methanol LC-MS",   "vendor": "Fisher",        "part_num": "A456-4", "lot_num": "214567",   "expiry": "2028-01-01"},
        {"material": "Water LC-MS",      "vendor": "Fisher",        "part_num": "W6-4",   "lot_num": "198321",   "expiry": "2028-01-01"},
    ],
}

_LOGBOOK_KEY_250 = _LOGBOOK_KEY_PREFIX + "250"

_CAL_POINTS = [
    {"level": "CAL-1",  "name": "FDA-CAL-1",  "conc_ng_ml": 20.0},
    {"level": "CAL-2",  "name": "FDA-CAL-2",  "conc_ng_ml": 10.0},
    {"level": "CAL-3",  "name": "FDA-CAL-3",  "conc_ng_ml": 5.0},
    {"level": "CAL-4",  "name": "FDA-CAL-4",  "conc_ng_ml": 2.5},
    {"level": "CAL-5",  "name": "FDA-CAL-5",  "conc_ng_ml": 1.25},
    {"level": "CAL-6",  "name": "FDA-CAL-6",  "conc_ng_ml": 0.625},
    {"level": "CAL-7",  "name": "FDA-CAL-7",  "conc_ng_ml": 0.3125},
    {"level": "CAL-8",  "name": "FDA-CAL-8",  "conc_ng_ml": 0.15625},
    {"level": "CAL-9",  "name": "FDA-CAL-9",  "conc_ng_ml": 0.078125},
    {"level": "CAL-10", "name": "FDA-CAL-10", "conc_ng_ml": 0.0390625},
]

_LB_251 = {
    "method": "FDA_32PFAS",
    "prepared_by": "J. Smith",
    "prepared_date": "2026-06-01",
    "reviewed_by": "K. Doe",
    "reviewed_date": "2026-06-01",
    "pds_a_lot":       "WXFDA-IS-LOT-260101",
    "pds_b_lot":       "WXFDA-SUR-LOT-260101",
    "analyte_pds_lot": "WXFDA-NAT-LOT-260101",
    "analyte_spike_lot": "WXFDA-SPK-LOT-260101",
    "cal_a_lot":       "WXFDA-CAL-LOT-260101",
    "cal_points":      _CAL_POINTS,
    "ccv_conc_ng_ml":  "1.25",
    "icv_conc_ng_ml":  "1.25",
    "diluent_is_conc": "1.0",
    "notes": "Default FDA 32-PFAS 10-level calibration ladder.",
}

_LB_252 = {
    "method": "FDA_32PFAS",
    "analyst": "J. Smith",
    "extraction_date": "2026-06-02",
    "reviewed_by": "K. Doe",
    "reviewed_date": "2026-06-03",
    "needle_cleaned": True,
    "notes": "Example extraction — 5 field samples + MB + LFSM + LFSMD + Dup.",
    "samples": [
        {"sample_id": "EX-001", "matrix_type": "Food",  "sample_type": "Sample", "spike_amount_ng": None, "dilution_factor": None},
        {"sample_id": "EX-002", "matrix_type": "Food",  "sample_type": "Sample", "spike_amount_ng": None, "dilution_factor": None},
        {"sample_id": "EX-003", "matrix_type": "Meat",  "sample_type": "Sample", "spike_amount_ng": None, "dilution_factor": None},
        {"sample_id": "EX-004", "matrix_type": "Meat",  "sample_type": "Dup",    "spike_amount_ng": None, "dilution_factor": None},
        {"sample_id": "EX-005", "matrix_type": "Milk",  "sample_type": "Sample", "spike_amount_ng": None, "dilution_factor": None},
        {"sample_id": "EX-MB1", "matrix_type": "Food",  "sample_type": "MB",     "spike_amount_ng": None, "dilution_factor": None},
        {"sample_id": "EX-LFM1","matrix_type": "Food",  "sample_type": "LFSM",   "spike_amount_ng": 2.0,  "dilution_factor": None},
        {"sample_id": "EX-LFD1","matrix_type": "Food",  "sample_type": "LFSMD",  "spike_amount_ng": 2.0,  "dilution_factor": None},
    ],
    "reagents": [
        {"reagent": "MeOH (LC-MS)", "vendor": "Fisher", "lot_num": "214567", "expiry": "2028-01-01"},
        {"reagent": "NH4OAc 4 mM",  "vendor": "Lab",    "lot_num": "FDA-MPH2O-260601", "expiry": "2026-06-08"},
    ],
    "standards": [
        {"name": "IS PDS B",     "vendor": "Wellington", "lot_num": "WXFDA-IS-LOT-260101",  "expiry": "2027-01-01"},
        {"name": "SUR PDS B",    "vendor": "Wellington", "lot_num": "WXFDA-SUR-LOT-260101", "expiry": "2027-01-01"},
        {"name": "Analyte Spike","vendor": "Wellington", "lot_num": "WXFDA-SPK-LOT-260101", "expiry": "2027-01-01"},
    ],
    "extraction_materials": [
        {"material": "Oasis WAX 6cc cartridge", "lot_num": "WAX-LOT-2024-001"},
        {"material": "15 mL polypropylene tube", "lot_num": "PP-LOT-2025-009"},
    ],
}

_LB_253 = {
    "analyst": "J. Smith",
    "processing_date": "2026-06-02",
    "balance_sn": "SN-BAL-001",
    "grinder_cleaned": True,
    "notes": "All food samples weighed to ±0.0001 g.",
    "samples": [
        {"sample_id": "EX-001", "matrix": "Food",  "split": False, "split_count": None,
         "dry_ice_composite": False, "dry_ice_weight_g": None, "spoiled": False,
         "aliquot_mass_g": 2.5001, "sample_factor": 1.0},
        {"sample_id": "EX-002", "matrix": "Food",  "split": False, "split_count": None,
         "dry_ice_composite": False, "dry_ice_weight_g": None, "spoiled": False,
         "aliquot_mass_g": 2.4998, "sample_factor": 1.0},
        {"sample_id": "EX-003", "matrix": "Meat",  "split": True,  "split_count": 2,
         "dry_ice_composite": True,  "dry_ice_weight_g": 1.232,  "spoiled": False,
         "aliquot_mass_g": 2.5012, "sample_factor": 1.0},
        {"sample_id": "EX-004", "matrix": "Meat",  "split": True,  "split_count": 2,
         "dry_ice_composite": True,  "dry_ice_weight_g": 1.198,  "spoiled": False,
         "aliquot_mass_g": 2.4995, "sample_factor": 1.0},
        {"sample_id": "EX-005", "matrix": "Milk",  "split": False, "split_count": None,
         "dry_ice_composite": False, "dry_ice_weight_g": None, "spoiled": False,
         "aliquot_mass_g": 2.5008, "sample_factor": 1.0},
        {"sample_id": "EX-MB1", "matrix": "Food",  "split": False, "split_count": None,
         "dry_ice_composite": False, "dry_ice_weight_g": None, "spoiled": False,
         "aliquot_mass_g": 2.5000, "sample_factor": 1.0},
        {"sample_id": "EX-LFM1","matrix": "Food",  "split": False, "split_count": None,
         "dry_ice_composite": False, "dry_ice_weight_g": None, "spoiled": False,
         "aliquot_mass_g": 2.5003, "sample_factor": 1.0},
        {"sample_id": "EX-LFD1","matrix": "Food",  "split": False, "split_count": None,
         "dry_ice_composite": False, "dry_ice_weight_g": None, "spoiled": False,
         "aliquot_mass_g": 2.5006, "sample_factor": 1.0},
    ],
    "processing_materials": [
        {"material": "Dry ice", "lot_num": "N/A"},
        {"material": "Stainless steel grinder blades", "lot_num": "GRD-2025-003"},
    ],
}


def _save_lb(batch, slug, data):
    key = _LOGBOOK_KEY_PREFIX + str(slug)
    IAnnotations(batch)[key] = json.dumps(data)


def _clear_lb(batch, slug):
    key = _LOGBOOK_KEY_PREFIX + str(slug)
    ann = IAnnotations(batch)
    if key in ann:
        del ann[key]


def _find_or_create_batch(portal, clear=False):
    """Return an existing example batch or create one."""
    from bika.lims.content.batch import Batch
    batches_folder = getattr(portal, "batches", None)
    if batches_folder is None:
        print("ERROR: No 'batches' folder in portal. Is SENAITE set up?")
        sys.exit(1)

    existing = None
    for obj in batches_folder.objectValues():
        if getattr(obj, "Title", lambda: "")() == _BATCH_TITLE:
            existing = obj
            break

    if clear and existing is not None:
        print("Clearing existing logbook data on %s" % existing.getId())
        for slug in (250, 251, 252, 253):
            _clear_lb(existing, slug)
        transaction.commit()
        print("Logbooks cleared.")
        return None

    if existing is not None:
        print("Found existing batch: %s" % existing.getId())
        return existing

    # Create new batch using direct invokeFactory (plone.api needs full traversal context)
    batches_folder.invokeFactory("Batch", "example-batch-fda32", title=_BATCH_TITLE)
    batch = batches_folder["example-batch-fda32"]
    batch.setTitle(_BATCH_TITLE)
    batch.reindexObject()
    print("Created new batch: %s" % batch.getId())
    return batch


def run(app):
    from zope.site.hooks import setSite, setHooks
    setHooks()  # install traversal hooks before any site access

    # Direct attribute access + explicit setSite — same pattern that works in
    # interactive bin/instance run scripts for Plone 4/5.
    portal = app.senaite
    setSite(portal)

    from AccessControl.SecurityManagement import newSecurityManager
    user = app.acl_users.getUser("admin")
    if user is None:
        print("ERROR: admin user not found")
        sys.exit(1)
    newSecurityManager(None, user.__of__(app.acl_users))

    clear = "--clear" in sys.argv

    batch = _find_or_create_batch(portal, clear=clear)
    if batch is None:
        return

    _save_lb(batch, 250, _LB_250)
    _save_lb(batch, 251, _LB_251)
    _save_lb(batch, 252, _LB_252)
    _save_lb(batch, 253, _LB_253)

    transaction.commit()
    print("All four logbooks seeded on batch '%s'." % batch.getId())
    print("Access at: /senaite/batches/%s/@@pfas-logbook-index" % batch.getId())


if __name__ == "__main__":
    run(app)  # noqa: F821 — 'app' injected by `instance run`
