# -*- coding: utf-8 -*-
"""
PFAS Method Profile Store — ZODB-backed, file-exported per-method QC config.

Python 2.7 compatible.  No f-strings, no pathlib, no annotations.

Storage pattern
---------------
  IAnnotations(portal)[PFAS_METHOD_PROFILES_KEY]
      → PersistentMapping { method_id: json_string, ... }

JSON strings are replaced in their entirety on every save, which avoids
nested-persistence dirty-marking issues in ZODB.  Callers always receive
a fresh dict (via json.loads or copy.deepcopy), never a live reference to
stored data.

File bridge for the worker
--------------------------
On every save, export_profiles_to_file() writes
  /data/qc/method_profiles.json
The pipeline worker reads this file at the start of each batch run so
changes made in the UI are picked up without a worker restart.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import json
import logging
import os

logger = logging.getLogger("senaite.pfas.method_profile_store")

PFAS_METHOD_PROFILES_KEY = "senaite.pfas.method_profiles"
PROFILES_EXPORT_PATH = os.environ.get(
    "PFAS_PROFILES_PATH", "/data/qc/method_profiles.json"
)

# ── Constants used to seed the FDA_32PFAS per-analyte table ───────────────────

_FDA_NO_LABELED_STD = frozenset([
    "9Cl-PF3ONS", "11Cl-PF3OUdS", "PFDoS", "PFDS",
    "PFNS", "PFODA", "PFPeS", "PFTrDA", "PFTrDS", "PFUnDS",
])

_FDA_BIG4 = frozenset([
    "PFOS", "PFOA", "PFHxS", "PFNA",
    "lr-PFOS", "br-PFOS", "lr-PFHxS", "br-PFHxS",
])

_FDA_ANALYTE_ORDER = [
    "10:2 FTS", "11Cl-PF3OUdS", "4:2 FTS", "6:2FTS", "8:2 FTS",
    "9Cl-PF3ONS", "DONA", "FOSA", "GenX (HFPO-DA)", "PFBA", "PFBS",
    "PFDA", "PFDoA", "PFDoS", "PFDS", "PFHpA", "PFHpS", "PFHxA",
    "PFHxDA", "lr-PFHxS", "PFNA", "PFNS", "PFOA", "PFODA", "lr-PFOS",
    "PFPeA", "PFPeS", "PFTeDA", "PFTrDA", "PFTrDS", "PFUDA", "PFUnDS",
    "br-PFOS", "br-PFHxS",
]

# Native analyte → surrogate IS  (FDA Table 9-1, abbreviated names — see Q-001)
_FDA_SURROGATE_MAP_DICT = {
    "PFBA": "M3PFBA",   "PFPeA": "M3PFPeA",  "PFHxA": "M5PFHxA",
    "PFHpA": "M4PFHpA", "PFOA": "M8PFOA",    "PFNA": "M5PFNA",
    "PFDA": "M2PFDA",   "PFUDA": "MPFUdA",   "PFDoA": "MPFDoA",
    "PFTrDA": "MPFDoA", "PFTeDA": "M2PFTeDA", "PFHxDA": "M2PFHxDA",
    "PFBS": "M3PFBS",   "lr-PFHxS": "M3PFHxS", "br-PFHxS": "M3PFHxS",
    "lr-PFOS": "M8PFOS", "br-PFOS": "M8PFOS",
    "GenX (HFPO-DA)": "M3HFPO",  "FOSA": "M8FOSA",
    "4:2 FTS": "13C2,D4 4:2 FTS",  "6:2FTS": "13C2,D4 6:2 FTS",
    "8:2 FTS": "13C2,D4 8:2 FTS",  "10:2 FTS": "13C2,D4 10:2 FTS",
}

# Primary qualifier MRM transition per analyte (from analytes.py PFAS_ANALYTES)
# PFBA / PFPeA use the 18.99 fluoride fragment — no HRMS required (see DECISIONS.md)
_CONFIRM_ION_MZ = {
    "10:2 FTS": "626.83>606.92",  "11Cl-PF3OUdS": "630.92>83.06",
    "4:2 FTS":  "326.94>306.97",  "6:2FTS":        "426.92>406.99",
    "8:2 FTS":  "527.03>507.07",  "9Cl-PF3ONS":    "530.93>82.96",
    "GenX (HFPO-DA)": "285.00>119.00",
    "PFBA":     "213.04>18.99",   "PFBS":   "299.00>98.99",
    "PFDA":     "512.96>268.98",  "PFDoA":  "612.94>168.97",
    "PFDoS":    "698.86>98.96",   "PFDS":   "598.99>98.92",
    "PFHpA":    "362.90>169.02",  "PFHpS":  "448.90>98.96",
    "PFHxA":    "312.97>119.03",  "PFHxDA": "812.96>168.88",
    "PFHxS":    "398.85>98.97",   "PFNA":   "462.86>269.02",
    "PFNS":     "549.01>98.92",   "PFOA":   "376.86>85.02",
    "PFODA":    "912.93>218.94",  "PFOS":   "498.92>98.94",
    "PFPeA":    "263.01>18.99",   "PFPeS":  "348.94>98.92",
    "PFTeDA":   "712.75>218.91",  "PFTrDA": "662.79>218.93",
    "PFTrDS":   "748.73>98.94",   "PFUnDS": "562.85>269.00",
    "PFUDA":    "648.82>98.91",   "DONA":   "412.91>219.01",
    "FOSA":     "498.92>98.94",
    "br-PFHxS": "398.85>98.97",   "br-PFOS": "498.92>98.94",
    "lr-PFHxS": "398.85>98.97",   "lr-PFOS": "498.92>98.94",
}


def _fda_per_analyte():
    rows = []
    for analyte in _FDA_ANALYTE_ORDER:
        no_std = analyte in _FDA_NO_LABELED_STD
        is_key = analyte in _FDA_BIG4
        if no_std:
            tier = 3
        elif is_key:
            tier = 1   # Tier 1 in tight matrices; Tier 2 in others
        else:
            tier = 2
        rows.append({
            "analyte": analyte,
            "surrogate": _FDA_SURROGATE_MAP_DICT.get(analyte, ""),
            "no_labeled_std": no_std,
            "is_key_analyte": is_key,
            "recovery_tier": tier,
            "confirm_ion_mz": _CONFIRM_ION_MZ.get(analyte, ""),
            "notes": "",
        })
    return rows


# ── Default profiles (seeded from all current hardcoded values) ───────────────
# Behavior is unchanged until a manager edits and saves via the UI.

DEFAULT_PROFILES = {
    "FDA_32PFAS": {
        "method_id": "FDA_32PFAS",
        "display_name": "FDA 32-PFAS in Food and Feed",
        "description": (
            "USDA/FDA 32-PFAS in Food v10 (5/5/26) + AOAC SMPR 2023.003; "
            "LC-MS/MS isotope dilution"
        ),
        "calibration": {
            # 0.995 matches the legacy CRITERIA default (preserves current behaviour).
            # The FDA method document specifies 0.990 — see QUESTIONS.md Q-005.
            "r2_min": 0.995,
            "force_origin": False,
            "point_pct_dev_max": 20.0,
            "low_point_pct_dev_max": None,
        },
        "ccv": {
            "frequency": 6,
            "recovery_min": 70.0,
            "recovery_max": 130.0,
            "low_level_min": None,
            "low_level_max": None,
        },
        "is": {
            "vs_ical_avg_min": 50.0,
            "vs_ical_avg_max": 150.0,
            "vs_last_ccv_min": None,
            "vs_last_ccv_max": None,
            "notes": "Lab SOP screen; FDA method sets no numeric IS-area limit",
        },
        "confirmation": {
            "rrt_tol_pct": 1.0,
            "rt_tol_abs_min": None,
            "ion_ratio_tol_pct": 30.0,
            "sn_quan_min": 3.0,
            "sn_confirm_min": 3.0,
            "require_confirm_ion_check": True,
        },
        "duplicate": {
            "rpd_max": 20.0,
        },
        "recovery_tiers": [
            {
                "tier": 1,
                "description": (
                    "Key analytes (PFOS/PFOA/PFHxS/PFNA + isomers) in tight "
                    "matrices (eggs/meat/seafood)"
                ),
                "key_analytes": [
                    "PFOS", "PFOA", "PFHxS", "PFNA",
                    "lr-PFOS", "br-PFOS", "lr-PFHxS", "br-PFHxS",
                ],
                "tight_matrices": [
                    "egg", "eggs", "meat", "muscle", "beef", "pork",
                    "poultry", "deer", "seafood", "fish", "shellfish",
                ],
                "recovery_min": 80.0,
                "recovery_max": 120.0,
                "rsd_max": 20.0,
            },
            {
                "tier": 2,
                "description": (
                    "Isotopically linked analytes (all not in Tier 1 or 3), "
                    "or key analytes in non-tight matrices"
                ),
                "key_analytes": [],
                "tight_matrices": [],
                "recovery_min": 65.0,
                "recovery_max": 135.0,
                "rsd_max": 25.0,
            },
            {
                "tier": 3,
                "description": "No labeled standard (Table 10-1 footnote a)",
                "no_std_analytes": [
                    "9Cl-PF3ONS", "11Cl-PF3OUdS", "PFDoS", "PFDS",
                    "PFNS", "PFODA", "PFPeS", "PFTrDA", "PFTrDS", "PFUnDS",
                ],
                "recovery_min": 40.0,
                "recovery_max": 140.0,
                "rsd_max": 30.0,
            },
        ],
        "matrix_factors": [
            {"matrix": "muscle",      "factor": 0.5},
            {"matrix": "meat",        "factor": 0.5},
            {"matrix": "deer",        "factor": 0.5},
            {"matrix": "beef",        "factor": 0.5},
            {"matrix": "pork",        "factor": 0.5},
            {"matrix": "poultry",     "factor": 0.5},
            {"matrix": "fish",        "factor": 0.5},
            {"matrix": "seafood",     "factor": 0.5},
            {"matrix": "egg",         "factor": 0.5},
            {"matrix": "eggs",        "factor": 0.5},
            {"matrix": "milk",        "factor": 0.2},
            {"matrix": "feed",        "factor": 2.0},
            {"matrix": "animal feed", "factor": 2.0},
        ],
        "surrogate_map": [
            {"analyte": "PFBA",           "surrogate_is": "M3PFBA"},
            {"analyte": "PFPeA",          "surrogate_is": "M3PFPeA"},
            {"analyte": "PFHxA",          "surrogate_is": "M5PFHxA"},
            {"analyte": "PFHpA",          "surrogate_is": "M4PFHpA"},
            {"analyte": "PFOA",           "surrogate_is": "M8PFOA"},
            {"analyte": "PFNA",           "surrogate_is": "M5PFNA"},
            {"analyte": "PFDA",           "surrogate_is": "M2PFDA"},
            {"analyte": "PFUDA",          "surrogate_is": "MPFUdA"},
            {"analyte": "PFDoA",          "surrogate_is": "MPFDoA"},
            {"analyte": "PFTrDA",         "surrogate_is": "MPFDoA"},
            {"analyte": "PFTeDA",         "surrogate_is": "M2PFTeDA"},
            {"analyte": "PFHxDA",         "surrogate_is": "M2PFHxDA"},
            {"analyte": "PFBS",           "surrogate_is": "M3PFBS"},
            {"analyte": "lr-PFHxS",       "surrogate_is": "M3PFHxS"},
            {"analyte": "br-PFHxS",       "surrogate_is": "M3PFHxS"},
            {"analyte": "lr-PFOS",        "surrogate_is": "M8PFOS"},
            {"analyte": "br-PFOS",        "surrogate_is": "M8PFOS"},
            {"analyte": "GenX (HFPO-DA)", "surrogate_is": "M3HFPO"},
            {"analyte": "FOSA",           "surrogate_is": "M8FOSA"},
            {"analyte": "4:2 FTS",        "surrogate_is": "13C2,D4 4:2 FTS"},
            {"analyte": "6:2FTS",         "surrogate_is": "13C2,D4 6:2 FTS"},
            {"analyte": "8:2 FTS",        "surrogate_is": "13C2,D4 8:2 FTS"},
            {"analyte": "10:2 FTS",       "surrogate_is": "13C2,D4 10:2 FTS"},
        ],
        "surrogate_is": "M4PFOA",
        "per_analyte": _fda_per_analyte(),
    },

    "EPA_537_1": {
        "method_id": "EPA_537_1",
        "display_name": "EPA 537.1 Drinking Water",
        "description": "EPA 537.1 PFAS in drinking water (EPA/600/R-20/006)",
        "calibration": {
            "r2_min": 0.990,
            "force_origin": True,
            "point_pct_dev_max": 30.0,
            "low_point_pct_dev_max": 50.0,
        },
        "ccv": {
            "frequency": 10,
            "recovery_min": 70.0,
            "recovery_max": 130.0,
            "low_level_min": 50.0,
            "low_level_max": 150.0,
        },
        "is": {
            "vs_ical_avg_min": 50.0,
            "vs_ical_avg_max": 150.0,
            "vs_last_ccv_min": 70.0,
            "vs_last_ccv_max": 140.0,
            "notes": "Both ICAL avg AND last CCV conditions must hold (§9.3.4)",
        },
        "confirmation": {
            "rrt_tol_pct": None,
            "rt_tol_abs_min": 0.05,
            "ion_ratio_tol_pct": None,
            "sn_quan_min": 3.0,
            "sn_confirm_min": None,
            "require_confirm_ion_check": False,
        },
        "duplicate": {
            "rpd_max": 30.0,
        },
        "recovery_tiers": [
            {
                "tier": 1,
                "description": "Low-level LFB (at or below MRL): 50-150%",
                "recovery_min": 50.0,
                "recovery_max": 150.0,
                "rsd_max": None,
            },
            {
                "tier": 2,
                "description": "Mid/high LFB and LFSM: 70-130%",
                "recovery_min": 70.0,
                "recovery_max": 130.0,
                "rsd_max": None,
            },
        ],
        "matrix_factors": [],
        "surrogate_map": [],
        "surrogate_is": "",
        "per_analyte": [],
    },

    "EPA_1633A": {
        "method_id": "EPA_1633A",
        "display_name": "EPA 1633A Multi-Matrix",
        "description": (
            "EPA 1633A — 40 PFAS in aqueous, solid, biosolid, tissue "
            "(Jan 2024 / 2024 update). EIS limits per-analyte and per-matrix "
            "(Tables 6/8) — VERIFY against method before production use."
        ),
        "calibration": {
            "r2_min": 0.990,
            "force_origin": False,
            "point_pct_dev_max": 30.0,
            "low_point_pct_dev_max": 50.0,
        },
        "ccv": {
            "frequency": 10,
            "recovery_min": 70.0,
            "recovery_max": 130.0,
            "low_level_min": None,
            "low_level_max": None,
        },
        "is": {
            "vs_ical_avg_min": 50.0,
            "vs_ical_avg_max": 150.0,
            "vs_last_ccv_min": None,
            "vs_last_ccv_max": None,
            "notes": "NIS screen; EIS uses per-analyte limits (see eis_overrides)",
        },
        "confirmation": {
            "rrt_tol_pct": None,
            "rt_tol_abs_min": None,
            "ion_ratio_tol_pct": 50.0,
            "sn_quan_min": 3.0,
            "sn_confirm_min": 1.0,
            "require_confirm_ion_check": True,
        },
        "duplicate": {
            "rpd_max": 30.0,
        },
        "recovery_tiers": [
            {
                "tier": 1,
                "description": (
                    "EIS/NIS default aqueous window — VERIFY against "
                    "1633A Tables 6/8 for per-analyte limits"
                ),
                "recovery_min": 40.0,
                "recovery_max": 130.0,
                "rsd_max": None,
                "verify_against_method": True,
            },
        ],
        "eis_overrides": [
            {"analyte": "M2-4:2FTS",   "recovery_min": 20.0, "recovery_max": 150.0},
            {"analyte": "M2-6:2FTS",   "recovery_min": 20.0, "recovery_max": 150.0},
            {"analyte": "M2-8:2FTS",   "recovery_min": 20.0, "recovery_max": 150.0},
            {"analyte": "d3-NMeFOSAA", "recovery_min": 20.0, "recovery_max": 150.0},
            {"analyte": "d5-NEtFOSAA", "recovery_min": 20.0, "recovery_max": 150.0},
            {"analyte": "M8FOSA",      "recovery_min": 20.0, "recovery_max": 150.0},
        ],
        "matrix_factors": [],
        "surrogate_map": [],
        "surrogate_is": "",
        "per_analyte": [],
    },
}


# ── ZODB annotation store ──────────────────────────────────────────────────────

def get_profile_store(portal):
    """Return the PersistentMapping {method_id: json_string} for this portal."""
    from zope.annotation.interfaces import IAnnotations
    from persistent.mapping import PersistentMapping
    annotations = IAnnotations(portal)
    if PFAS_METHOD_PROFILES_KEY not in annotations:
        annotations[PFAS_METHOD_PROFILES_KEY] = PersistentMapping()
    return annotations[PFAS_METHOD_PROFILES_KEY]


def get_profile(portal, method_id):
    """
    Return the profile dict for method_id.  Falls back to DEFAULT_PROFILES if
    not yet customised.  Always returns a fresh dict; mutations do not persist.
    """
    store = get_profile_store(portal)
    raw = store.get(method_id)
    if raw is None:
        dflt = DEFAULT_PROFILES.get(method_id)
        if dflt is None:
            return {"method_id": method_id}
        return copy.deepcopy(dflt)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Corrupt profile JSON for %s; returning default", method_id)
        return copy.deepcopy(DEFAULT_PROFILES.get(method_id, {"method_id": method_id}))


def save_profile(portal, method_id, data):
    """
    Persist data (dict) for method_id.  Replaces the entire entry atomically.
    Also exports /data/qc/method_profiles.json for the pipeline worker.
    """
    store = get_profile_store(portal)
    store[method_id] = json.dumps(data)
    try:
        export_profiles_to_file(portal)
    except Exception as exc:
        logger.warning(
            "Profile %s saved to ZODB but file export failed: %s", method_id, exc
        )


def list_method_ids(portal):
    """Return method IDs that have been explicitly saved (beyond defaults)."""
    store = get_profile_store(portal)
    return list(store.keys())


def export_profiles_to_file(portal, path=None):
    """
    Write all profiles (stored overrides + defaults for any not yet edited)
    to a JSON file so the pipeline worker can read them.
    Atomic: writes to .tmp then renames.
    """
    if path is None:
        path = PROFILES_EXPORT_PATH
    store = get_profile_store(portal)

    all_profiles = {}
    for mid, dflt in DEFAULT_PROFILES.items():
        all_profiles[mid] = copy.deepcopy(dflt)
    for method_id, raw in store.items():
        try:
            all_profiles[method_id] = json.loads(raw)
        except (ValueError, TypeError):
            pass

    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d)
        except OSError:
            pass

    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(all_profiles, f, indent=2, sort_keys=True)
        os.rename(tmp, path)
        logger.info("Exported %d method profiles to %s", len(all_profiles), path)
    except (IOError, OSError) as exc:
        logger.error("Failed to export method profiles to %s: %s", path, exc)
        raise


def seed_default_profiles(portal):
    """
    Seed defaults into ZODB.  Idempotent — never overwrites customised profiles.
    Called from setup_handler on install/re-install.
    """
    store = get_profile_store(portal)
    seeded = 0
    for method_id, data in DEFAULT_PROFILES.items():
        if method_id not in store:
            seeded_data = dict(data)
            seeded_data["_seeded"] = True  # cleared when a user saves their own values
            store[method_id] = json.dumps(seeded_data)
            seeded += 1
    if seeded:
        logger.info("Seeded %d default method profiles into ZODB", seeded)
    try:
        export_profiles_to_file(portal)
    except Exception as exc:
        logger.warning("Profiles seeded but export failed: %s", exc)
