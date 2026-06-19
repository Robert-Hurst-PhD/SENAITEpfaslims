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
# Derived from analyte_reference.py — single source of truth for is_key_analyte
# and no_labeled flags. Do not duplicate these lists here.

from senaite.pfas.analyte_reference import (
    NATIVE_ANALYTES as _NATIVE_ANALYTES,
    INTERNAL_STANDARDS as _INTERNAL_STANDARDS,
    get_surrogate_map_by_name as _get_surrogate_map_by_name,
)

# Native analyte (display name) → surrogate IS keyword — derived from
# analyte_reference.py. _fda_per_analyte() uses display names, so use the
# name-keyed map.
_FDA_SURROGATE_MAP_DICT = _get_surrogate_map_by_name()  # {display_name: M-keyword}
# M-keyword → 13C display name (for human-readable per_analyte.surrogate column).
_IS_KW_TO_NAME = {row[0]: row[1] for row in _INTERNAL_STANDARDS}


def _fda_per_analyte():
    # Build confirm-ion map from PFAS_ANALYTES (canonical MRM source, Decision A).
    from senaite.pfas.analytes import PFAS_ANALYTES as _pfas_a
    confirm_map = {name: qls[0] for name, _, qls in _pfas_a if qls}

    master_kws = frozenset(_FDA_MASTER_ANALYTE_KEYWORDS)
    rows = []
    for row in _NATIVE_ANALYTES:
        keyword = row[0]
        if keyword not in master_kws:
            continue
        analyte = row[1]   # display name (e.g. "lr-PFHxS", "GenX (HFPO-DA)")
        no_std = row[7]
        is_key = row[8]
        tier = 3 if no_std else (1 if is_key else 2)
        rows.append({
            "analyte":        analyte,
            "surrogate":      _IS_KW_TO_NAME.get(_FDA_SURROGATE_MAP_DICT.get(analyte, ""), ""),
            "no_labeled_std": no_std,
            "is_key_analyte": is_key,
            "recovery_tier":  tier,
            "confirm_ion_mz": confirm_map.get(analyte, ""),
            "notes": "",
        })
    return rows


# ── Spike levels helper ───────────────────────────────────────────────────────

def _per_matrix_spike_levels(matrices):
    """Return spike_levels in per-matrix format with all ppt values null."""
    levels = [
        {"label": "Low",  "ppt": None},
        {"label": "Mid",  "ppt": None},
        {"label": "High", "ppt": None},
    ]
    return {
        m: {
            "LFB":  copy.deepcopy(levels),
            "LFSM": copy.deepcopy(levels),
        }
        for m in matrices
    }


def _migrate_spike_levels(saved, dflt):
    """Upgrade old flat {LFB:[...], LFSM:[...]} to per-matrix format in-place."""
    sl = saved.get("spike_levels")
    if sl is None:
        return
    if not ("LFB" in sl or "LFSM" in sl):
        return  # already per-matrix
    matrices = (saved.get("supported_matrices")
                or (dflt or {}).get("supported_matrices")
                or [])
    saved["spike_levels"] = {m: copy.deepcopy(sl) for m in matrices}


# ── Relational model: canonical matrix vocabulary + analyte × matrix sets ─────

# Canonical FDA matrix names — must match SAMPLE_TYPES titles in analyte_reference.py
_FDA_MATRICES = [
    "Aquatic Tissue",
    "Meat / Muscle",
    "Eggs",
    "Fish / Seafood",
    "Milk",
    "Animal Feed",
]

# 32 reportable native analyte keywords for FDA_32PFAS.
# br-PFOS and br-PFHxS are EXCLUDED: they are always reported summed with their
# linear isomers via isomer_summation, never as independent rows in the report.
_FDA_MASTER_ANALYTE_KEYWORDS = [
    "PFBA", "PFPeA", "PFHxA", "PFHpA", "PFOA", "PFNA",
    "PFDA", "PFUDA", "PFDoA", "PFTrDA", "PFTeDA", "PFHxDA", "PFODA",
    "PFBS", "PFPeS", "PFHxS", "PFHpS", "PFOS", "PFNS", "PFDS", "PFDoS",
    "PFTrDS", "PFUnDS",
    "4:2FTS", "6:2FTS", "8:2FTS", "10:2FTS",
    "FOSA", "GenX", "DONA",
    "9ClPF3ONS", "11ClPF3OUdS",
]

# Analytes excluded from specific matrices (keyword → set of matrix names).
# All other analyte × matrix intersections default to True (included/reportable).
_FDA_MATRIX_EXCLUSIONS = {
    "PFODA": {"Eggs"},   # FDA carve-out: PFODA not reportable in egg matrix
    # Flag: additional carve-outs from the method document should be added here.
    # Any unknown carve-outs are seeded True (included) as a conservative default.
}

# EPA_537_1: drinking water only; no per-analyte matrix exclusions known.
_EPA537_MATRICES = ["Drinking Water", "Groundwater", "Surface Water"]

# EPA 537.1 — 18 analytes per EPA/600/R-20/006 Table 1.1 (Section 1.1)
_EPA537_ANALYTE_KEYWORDS = [
    # PFCAs (9)
    "PFHxA", "PFHpA", "PFOA", "PFNA", "PFDA",
    "PFUDA", "PFDoA", "PFTrDA", "PFTeDA",
    # PFSAs (3)
    "PFBS", "PFHxS", "PFOS",
    # Sulfonamidoacetic acids (2)
    "NMeFOSAA", "NEtFOSAA",
    # Ether acids / sulfonics (4)
    "GenX", "DONA", "9ClPF3ONS", "11ClPF3OUdS",
]

# EPA_1633A: multi-matrix; units differ by matrix class.
# Matrix names MUST exactly match SENAITE SampleType titles so that batch
# matrix → spike_levels / unit_map lookups resolve correctly.
_EPA1633A_MATRICES = [
    "Groundwater", "Drinking Water", "Surface Water",
    "Wastewater", "Landfill Leachate",
    "Sediment", "Soil", "Aquatic Tissue", "Biosolid",
]
_EPA1633A_UNIT_MAP = {
    "Groundwater":      "ng/L",
    "Drinking Water":   "ng/L",
    "Surface Water":    "ng/L",
    "Wastewater":       "ng/L",
    "Landfill Leachate":"ng/L",
    "Sediment":         "ng/g",
    "Soil":             "ng/g",
    "Aquatic Tissue":   "ng/g",
    "Biosolid":         "ng/g",
}

# EPA 1633A — 40 analytes per EPA 820-R-24-007 Table 1, December 2024.
# br-PFHxS and br-PFOS are excluded here (summed via isomer_summation).
_EPA1633A_ANALYTE_KEYWORDS = [
    # PFCAs (11)
    "PFBA", "PFPeA", "PFHxA", "PFHpA", "PFOA", "PFNA",
    "PFDA", "PFUDA", "PFDoA", "PFTrDA", "PFTeDA",
    # PFSAs (8)
    "PFBS", "PFPeS", "PFHxS", "PFHpS", "PFOS", "PFNS", "PFDS", "PFDoS",
    # Fluorotelomer sulfonics (3)
    "4:2FTS", "6:2FTS", "8:2FTS",
    # Sulfonamides (3)
    "FOSA", "NMeFOSA", "NEtFOSA",
    # Sulfonamidoacetic acids (2)
    "NMeFOSAA", "NEtFOSAA",
    # Sulfonamide ethanols (2)
    "NMeFOSE", "NEtFOSE",
    # Ether carboxylic acids (5)
    "GenX", "DONA", "PFMPA", "PFMBA", "NFDHA",
    # Ether sulfonics (3)
    "9ClPF3ONS", "11ClPF3OUdS", "PFEESA",
    # Fluorotelomer carboxylic acids (3)
    "3:3FTCA", "5:3FTCA", "7:3FTCA",
]


def _fda_analyte_matrix_inclusion():
    """Build the 32 × 6 analyte-matrix inclusion dict for FDA_32PFAS.

    Returns {keyword: {matrix_name: bool}} with all entries True except
    the known FDA carve-outs in _FDA_MATRIX_EXCLUSIONS.
    """
    result = {}
    for keyword in _FDA_MASTER_ANALYTE_KEYWORDS:
        excluded = _FDA_MATRIX_EXCLUSIONS.get(keyword, set())
        result[keyword] = {m: (m not in excluded) for m in _FDA_MATRICES}
    return result


def _all_included_matrix(keywords, matrices):
    """Return all-True inclusion dict for methods with no known exclusions."""
    return {kw: {m: True for m in matrices} for kw in keywords}


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
        # surrogate_is_chain: which injection IS each labeled surrogate quantifies against
        # For FDA 32-PFAS all 20 surrogates quantify against M4PFOA (FDA Table 9-1)
        "surrogate_is_chain": {
            "M3PFBA":    "M4PFOA",
            "M3PFPeA":   "M4PFOA",
            "M5PFHxA":   "M4PFOA",
            "M4PFHpA":   "M4PFOA",
            "M8PFOA":    "M4PFOA",
            "M5PFNA":    "M4PFOA",
            "M2PFDA":    "M4PFOA",
            "MPFUdA":    "M4PFOA",
            "MPFDoA":    "M4PFOA",
            "M2PFTeDA":  "M4PFOA",
            "M2PFHxDA":  "M4PFOA",
            "M3PFBS":    "M4PFOA",
            "M3PFHxS":   "M4PFOA",
            "M8PFOS":    "M4PFOA",
            "M3HFPO":    "M4PFOA",
            "M8FOSA":    "M4PFOA",
            "M2-4:2FTS": "M4PFOA",
            "M2-6:2FTS": "M4PFOA",
            "M2-8:2FTS": "M4PFOA",
            "M2-10:2FTS":"M4PFOA",
        },
        "per_analyte": _fda_per_analyte(),
        "salt_adjustment_factors": [],
        "isomer_summation": [
            {"linear": "lr-PFOA",  "branched": "br-PFOA",  "reported": "PFOA",  "enabled": True},
            {"linear": "lr-PFNA",  "branched": "br-PFNA",  "reported": "PFNA",  "enabled": True},
            {"linear": "lr-PFOS",  "branched": "br-PFOS",  "reported": "PFOS",  "enabled": True},
            {"linear": "lr-PFHxS", "branched": "br-PFHxS", "reported": "PFHxS", "enabled": True},
        ],
        # ── Relational data model (Round 9) ──────────────────────────────────
        "supported_matrices": list(_FDA_MATRICES),
        # 32 reportable target analytes (br-isomers excluded; summed via isomer_summation)
        "master_analyte_set": list(_FDA_MASTER_ANALYTE_KEYWORDS),
        # keyword → {matrix_name → bool}  — the inclusion checkbox grid
        # PFODA × Eggs = False; all other intersections = True
        "analyte_matrix_inclusion": _fda_analyte_matrix_inclusion(),
        # Milk → ng/mL (liquid matrix, per-volume); all other FDA matrices → ng/kg.
        # Unit is per-matrix and editable via the Method Profile UI (Q-013).
        "unit_map": dict(
            [(m, "ng/mL" if m == "Milk" else "ng/kg") for m in _FDA_MATRICES]
        ),
        # Spike level options for LFSM (and LFB) injections — keyed by matrix.
        # ppt values left as null — the lab enters them via the Method Profile UI.
        "spike_levels": _per_matrix_spike_levels(_FDA_MATRICES),
        "extraction_stages": [
            {
                "id": "pre_setup",
                "order": 1,
                "name": "Pre-Extraction Setup",
                "description": "Verify reagents, standards, equipment; log balance S/N",
                "reagent_roles": ["Mobile Phase A (water+5mM AmAc)", "Mobile Phase B (MeOH+5mM AmAc)",
                                  "Acetonitrile (LC-MS grade)", "Ammonium Acetate"],
                "equipment": ["Analytical Balance", "Centrifuge", "Vortex Mixer"],
                "creates_solution": True,
                "capture_pedigree": False,
            },
            {
                "id": "weighing",
                "order": 2,
                "name": "Sample Weighing & Aliquoting",
                "description": "Weigh 1 g (±0.02 g) test portion into 50 mL centrifuge tube",
                "reagent_roles": [],
                "equipment": ["Analytical Balance", "50 mL Centrifuge Tubes"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "spike",
                "order": 3,
                "name": "Surrogate & IS Spike Addition",
                "description": "Add surrogate/IS spike solution; vortex 30 s",
                "reagent_roles": ["Surrogate IS Spike Solution"],
                "equipment": ["Pipette (100-1000 μL)", "Vortex Mixer"],
                "creates_solution": False,
                "capture_pedigree": True,
            },
            {
                "id": "extraction",
                "order": 4,
                "name": "Extraction",
                "description": "Add ACN; cap, vortex 2 min, centrifuge 5 min at 3000 rpm",
                "reagent_roles": ["Acetonitrile (LC-MS grade)"],
                "equipment": ["Centrifuge", "Vortex Mixer"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "dspe",
                "order": 5,
                "name": "Dispersive SPE Cleanup",
                "description": "Transfer extract to tube containing dSPE material; vortex, centrifuge",
                "reagent_roles": ["Primary Secondary Amine (PSA)", "MgSO₄ (anhydrous)",
                                  "C18 (if lipid matrix)"],
                "equipment": ["Centrifuge", "Vortex Mixer"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "concentration",
                "order": 6,
                "name": "Concentration",
                "description": "Evaporate under N₂ at 40°C to near dryness",
                "reagent_roles": [],
                "equipment": ["Turbovap / N₂ Evaporator", "Water Bath (40°C)"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "reconstitution",
                "order": 7,
                "name": "Reconstitution & Injection IS Addition",
                "description": "Reconstitute in 1 mL Mobile Phase A; add injection IS",
                "reagent_roles": ["Mobile Phase A (water+5mM AmAc)", "Injection IS Solution"],
                "equipment": ["Vortex Mixer", "Analytical Balance"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "transfer",
                "order": 8,
                "name": "QC Check & Transfer to Vial",
                "description": "Filter through PTFE syringe filter; transfer to LC vial",
                "reagent_roles": ["PTFE Syringe Filter (0.2 μm)"],
                "equipment": ["1 mL Syringe", "LC Vials"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
        ],
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
        "salt_adjustment_factors": [],
        "isomer_summation": [
            {"linear": "lr-PFOA",  "branched": "br-PFOA",  "reported": "PFOA",  "enabled": True},
            {"linear": "lr-PFNA",  "branched": "br-PFNA",  "reported": "PFNA",  "enabled": True},
            {"linear": "lr-PFOS",  "branched": "br-PFOS",  "reported": "PFOS",  "enabled": True},
            {"linear": "lr-PFHxS", "branched": "br-PFHxS", "reported": "PFHxS", "enabled": True},
        ],
        # ── Relational data model (Round 9) ──────────────────────────────────
        "supported_matrices": list(_EPA537_MATRICES),
        # EPA 537.1: 18 analytes per EPA/600/R-20/006 Table 1.1
        "master_analyte_set": list(_EPA537_ANALYTE_KEYWORDS),
        "analyte_matrix_inclusion": _all_included_matrix(
            _EPA537_ANALYTE_KEYWORDS, _EPA537_MATRICES
        ),
        "unit_map": {m: "ng/L" for m in _EPA537_MATRICES},
        "spike_levels": _per_matrix_spike_levels(_EPA537_MATRICES),
        "extraction_stages": [
            {
                "id": "pre_setup",
                "order": 1,
                "name": "Pre-Extraction Setup",
                "description": "Check SPE cartridges (ENVI-18 or equivalent), reagents, pH meter",
                "reagent_roles": ["Methanol (LC-MS grade)", "Reagent Water", "Ammonium Acetate"],
                "equipment": ["pH Meter", "SPE Manifold", "Analytical Balance"],
                "creates_solution": True,
                "capture_pedigree": False,
            },
            {
                "id": "ph_adjust",
                "order": 2,
                "name": "Sample pH Adjustment",
                "description": "Adjust pH to 5.5–6.5 with ammonium acetate buffer; measure and log pH",
                "reagent_roles": ["Ammonium Acetate Buffer (0.1 M)", "Acetic Acid"],
                "equipment": ["pH Meter", "Magnetic Stir Plate"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "spike",
                "order": 3,
                "name": "Isotope Spike Addition",
                "description": "Add isotopically labelled IS spike to sample; mix gently",
                "reagent_roles": ["EPA 537.1 IS Spike Mix"],
                "equipment": ["Pipette"],
                "creates_solution": False,
                "capture_pedigree": True,
            },
            {
                "id": "spe_condition",
                "order": 4,
                "name": "SPE Cartridge Conditioning",
                "description": "Condition cartridge: 5 mL MeOH, then 10 mL reagent water",
                "reagent_roles": ["Methanol (LC-MS grade)", "Reagent Water"],
                "equipment": ["SPE Manifold", "Vacuum Pump"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "loading",
                "order": 5,
                "name": "Sample Loading",
                "description": "Load spiked sample at ≤5 mL/min; do not allow cartridge to dry",
                "reagent_roles": [],
                "equipment": ["SPE Manifold", "Vacuum Pump"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "drying",
                "order": 6,
                "name": "Cartridge Drying",
                "description": "Apply vacuum for 15 min to dry cartridge",
                "reagent_roles": [],
                "equipment": ["SPE Manifold", "Vacuum Pump"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "elution",
                "order": 7,
                "name": "Elution",
                "description": "Elute with 2 × 5 mL MeOH into PP tubes",
                "reagent_roles": ["Methanol (LC-MS grade)"],
                "equipment": ["SPE Manifold", "50 mL PP Tubes"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "reconstitution",
                "order": 8,
                "name": "Concentration & Reconstitution",
                "description": "Evaporate under N₂ to ~0.5 mL; bring to 1 mL with reagent water",
                "reagent_roles": ["Reagent Water"],
                "equipment": ["N₂ Evaporator", "1 mL LC Vials"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
        ],
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
        # EIS recovery limits — from EPA 1633A (December 2024, EPA 820-R-24-007)
        # eis_overrides: per-analyte aqueous defaults (Table 6, non-leachate column).
        # eis_matrix_overrides: per-analyte limits by matrix class from Tables 6 and 8.
        # Matrix class key: "aqueous" (Table 6 col 1), "leachate" (Table 6 col 2),
        #                   "solid" (Table 8 col 1), "tissue" (Table 8 col 2),
        #                   "biosolid" (Table 8 col 3).
        # NIS compounds all use 50–200% across all matrix classes.
        "eis_overrides": [
            {"analyte": "13C4-PFBA",     "recovery_min":  5.0, "recovery_max": 130.0},
            {"analyte": "13C5-PFPeA",    "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C5-PFHxA",    "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C4-PFHpA",    "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C8-PFOA",     "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C9-PFNA",     "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C6-PFDA",     "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C7-PFUnA",    "recovery_min": 30.0, "recovery_max": 130.0},
            {"analyte": "13C2-PFDoA",    "recovery_min": 10.0, "recovery_max": 130.0},
            {"analyte": "13C2-PFTeDA",   "recovery_min": 10.0, "recovery_max": 130.0},
            {"analyte": "13C3-PFBS",     "recovery_min": 40.0, "recovery_max": 135.0},
            {"analyte": "13C3-PFHxS",    "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C8-PFOS",     "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "13C2-4:2FTS",   "recovery_min": 40.0, "recovery_max": 200.0},
            {"analyte": "13C2-6:2FTS",   "recovery_min": 40.0, "recovery_max": 200.0},
            {"analyte": "13C2-8:2FTS",   "recovery_min": 40.0, "recovery_max": 300.0},
            {"analyte": "13C8-PFOSA",    "recovery_min": 40.0, "recovery_max": 130.0},
            {"analyte": "D3-NMeFOSA",    "recovery_min": 10.0, "recovery_max": 130.0},
            {"analyte": "D5-NEtFOSA",    "recovery_min": 10.0, "recovery_max": 130.0},
            {"analyte": "D3-NMeFOSAA",   "recovery_min": 40.0, "recovery_max": 170.0},
            {"analyte": "D5-NEtFOSAA",   "recovery_min": 25.0, "recovery_max": 135.0},
            {"analyte": "D7-NMeFOSE",    "recovery_min": 10.0, "recovery_max": 130.0},
            {"analyte": "D9-NEtFOSE",    "recovery_min": 10.0, "recovery_max": 130.0},
            {"analyte": "13C3-HFPO-DA",  "recovery_min": 40.0, "recovery_max": 130.0},
        ],
        # Per-matrix-class EIS limits (Tables 6 and 8). Only compounds whose
        # limits differ from the aqueous default above are listed here.
        "eis_matrix_overrides": {
            "leachate": {
                "13C7-PFUnA":  {"recovery_min": 40.0, "recovery_max": 130.0},
                "13C2-PFDoA":  {"recovery_min": 35.0, "recovery_max": 130.0},
                "13C2-PFTeDA": {"recovery_min": 25.0, "recovery_max": 130.0},
                "13C3-PFBS":   {"recovery_min": 40.0, "recovery_max": 130.0},
                "13C2-4:2FTS": {"recovery_min": 40.0, "recovery_max": 220.0},
                "13C2-6:2FTS": {"recovery_min": 40.0, "recovery_max": 170.0},
                "13C2-8:2FTS": {"recovery_min": 40.0, "recovery_max": 145.0},
                "D3-NMeFOSA":  {"recovery_min": 40.0, "recovery_max": 130.0},
                "D5-NEtFOSA":  {"recovery_min": 35.0, "recovery_max": 130.0},
                "D3-NMeFOSAA": {"recovery_min": 35.0, "recovery_max": 130.0},
                "D5-NEtFOSAA": {"recovery_min": 30.0, "recovery_max": 130.0},
                "D7-NMeFOSE":  {"recovery_min": 20.0, "recovery_max": 130.0},
                "D9-NEtFOSE":  {"recovery_min": 20.0, "recovery_max": 130.0},
            },
            "solid": {
                "13C4-PFBA":   {"recovery_min":  8.0, "recovery_max": 130.0},
                "13C5-PFPeA":  {"recovery_min": 35.0, "recovery_max": 130.0},
                "13C2-PFTeDA": {"recovery_min": 20.0, "recovery_max": 130.0},
                "13C2-4:2FTS": {"recovery_min": 40.0, "recovery_max": 165.0},
                "13C2-6:2FTS": {"recovery_min": 40.0, "recovery_max": 215.0},
                "13C2-8:2FTS": {"recovery_min": 40.0, "recovery_max": 275.0},
                "13C8-PFOSA":  {"recovery_min": 40.0, "recovery_max": 130.0},
                "D3-NMeFOSAA": {"recovery_min": 40.0, "recovery_max": 135.0},
                "D5-NEtFOSAA": {"recovery_min": 40.0, "recovery_max": 150.0},
                "D7-NMeFOSE":  {"recovery_min": 20.0, "recovery_max": 130.0},
                "D9-NEtFOSE":  {"recovery_min": 15.0, "recovery_max": 130.0},
            },
            "tissue": {
                "13C4-PFBA":   {"recovery_min":  5.0, "recovery_max": 130.0},
                "13C5-PFPeA":  {"recovery_min": 10.0, "recovery_max": 185.0},
                "13C5-PFHxA":  {"recovery_min": 25.0, "recovery_max": 170.0},
                "13C4-PFHpA":  {"recovery_min": 25.0, "recovery_max": 150.0},
                "13C8-PFOA":   {"recovery_min": 25.0, "recovery_max": 150.0},
                "13C9-PFNA":   {"recovery_min": 35.0, "recovery_max": 185.0},
                "13C6-PFDA":   {"recovery_min": 30.0, "recovery_max": 150.0},
                "13C7-PFUnA":  {"recovery_min": 30.0, "recovery_max": 180.0},
                "13C2-PFDoA":  {"recovery_min": 35.0, "recovery_max": 180.0},
                "13C2-PFTeDA": {"recovery_min": 20.0, "recovery_max": 160.0},
                "13C3-PFBS":   {"recovery_min": 25.0, "recovery_max": 190.0},
                "13C3-PFHxS":  {"recovery_min": 35.0, "recovery_max": 175.0},
                "13C8-PFOS":   {"recovery_min": 40.0, "recovery_max": 160.0},
                "13C2-4:2FTS": {"recovery_min": 30.0, "recovery_max": 300.0},
                "13C2-6:2FTS": {"recovery_min": 35.0, "recovery_max": 300.0},
                "13C2-8:2FTS": {"recovery_min": 40.0, "recovery_max": 365.0},
                "13C8-PFOSA":  {"recovery_min": 25.0, "recovery_max": 180.0},
                "D3-NMeFOSA":  {"recovery_min":  5.0, "recovery_max": 130.0},
                "D5-NEtFOSA":  {"recovery_min":  5.0, "recovery_max": 130.0},
                "D3-NMeFOSAA": {"recovery_min": 30.0, "recovery_max": 250.0},
                "D5-NEtFOSAA": {"recovery_min": 30.0, "recovery_max": 235.0},
                "D7-NMeFOSE":  {"recovery_min":  5.0, "recovery_max": 160.0},
                "D9-NEtFOSE":  {"recovery_min":  5.0, "recovery_max": 130.0},
                "13C3-HFPO-DA":{"recovery_min": 20.0, "recovery_max": 185.0},
            },
            "biosolid": {
                "13C4-PFBA":   {"recovery_min":  5.0, "recovery_max": 130.0},
                "13C5-PFPeA":  {"recovery_min": 35.0, "recovery_max": 130.0},
                "13C9-PFNA":   {"recovery_min": 40.0, "recovery_max": 145.0},
                "13C2-PFTeDA": {"recovery_min": 10.0, "recovery_max": 160.0},
                "13C3-PFBS":   {"recovery_min": 40.0, "recovery_max": 150.0},
                "13C3-PFHxS":  {"recovery_min": 40.0, "recovery_max": 140.0},
                "13C2-4:2FTS": {"recovery_min": 40.0, "recovery_max": 300.0},
                "13C2-6:2FTS": {"recovery_min": 40.0, "recovery_max": 300.0},
                "13C2-8:2FTS": {"recovery_min": 40.0, "recovery_max": 300.0},
                "13C8-PFOSA":  {"recovery_min": 20.0, "recovery_max": 140.0},
                "D3-NMeFOSA":  {"recovery_min": 20.0, "recovery_max": 130.0},
                "D5-NEtFOSA":  {"recovery_min": 20.0, "recovery_max": 130.0},
                "D3-NMeFOSAA": {"recovery_min": 30.0, "recovery_max": 150.0},
                "D5-NEtFOSAA": {"recovery_min": 20.0, "recovery_max": 140.0},
                "D7-NMeFOSE":  {"recovery_min": 25.0, "recovery_max": 130.0},
                "D9-NEtFOSE":  {"recovery_min": 20.0, "recovery_max": 130.0},
            },
        },
        "matrix_factors": [],
        "surrogate_map": [],
        "surrogate_is": "",
        "per_analyte": [],
        "salt_adjustment_factors": [],
        "isomer_summation": [
            {"linear": "lr-PFOA",      "branched": "br-PFOA",      "reported": "PFOA",      "enabled": True},
            {"linear": "lr-PFNA",      "branched": "br-PFNA",      "reported": "PFNA",      "enabled": True},
            {"linear": "lr-PFOS",      "branched": "br-PFOS",      "reported": "PFOS",      "enabled": True},
            {"linear": "lr-PFHxS",     "branched": "br-PFHxS",     "reported": "PFHxS",     "enabled": True},
            {"linear": "lr-NEtFOSAA",  "branched": "br-NEtFOSAA",  "reported": "NEtFOSAA",  "enabled": True},
            {"linear": "lr-NMeFOSAA",  "branched": "br-NMeFOSAA",  "reported": "NMeFOSAA",  "enabled": True},
        ],
        # ── Relational data model (Round 9) ──────────────────────────────────
        "supported_matrices": list(_EPA1633A_MATRICES),
        # EPA 1633A: 40 analytes per EPA 820-R-24-007 Table 1, December 2024
        "master_analyte_set": list(_EPA1633A_ANALYTE_KEYWORDS),
        "analyte_matrix_inclusion": _all_included_matrix(
            _EPA1633A_ANALYTE_KEYWORDS, _EPA1633A_MATRICES
        ),
        "unit_map": dict(_EPA1633A_UNIT_MAP),
        "spike_levels": _per_matrix_spike_levels(_EPA1633A_MATRICES),
        "extraction_stages": [
            {
                "id": "pre_setup",
                "order": 1,
                "name": "Pre-Extraction Setup",
                "description": "Check Oasis WAX cartridges, homogenizer, reagents; log S/Ns",
                "reagent_roles": ["Methanol (LC-MS grade)", "Ammonium Formate Buffer"],
                "equipment": ["Homogenizer/Blender", "Analytical Balance", "SPE Manifold"],
                "creates_solution": True,
                "capture_pedigree": False,
            },
            {
                "id": "homogenization",
                "order": 2,
                "name": "Sample Homogenization",
                "description": "Homogenize solid / semi-solid matrices; record aliquot mass",
                "reagent_roles": [],
                "equipment": ["Homogenizer/Blender", "Analytical Balance"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "spike",
                "order": 3,
                "name": "EIS Spike Addition",
                "description": "Add EIS spike solution; mix well; allow equilibration ≥15 min",
                "reagent_roles": ["EPA 1633A EIS Spike Mix"],
                "equipment": ["Pipette", "Vortex Mixer"],
                "creates_solution": False,
                "capture_pedigree": True,
            },
            {
                "id": "extraction",
                "order": 4,
                "name": "Extraction",
                "description": "Add MeOH (or ACN for solids); shake, centrifuge; collect supernatant",
                "reagent_roles": ["Methanol (LC-MS grade)", "Acetonitrile (LC-MS grade)"],
                "equipment": ["Centrifuge", "Orbital Shaker"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "spe_cleanup",
                "order": 5,
                "name": "Oasis WAX SPE Cleanup",
                "description": "Condition WAX cartridge; load extract; wash; elute with MeOH",
                "reagent_roles": ["Methanol (LC-MS grade)", "Reagent Water",
                                  "0.3% NH₄OH in MeOH"],
                "equipment": ["SPE Manifold", "Vacuum Pump"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "concentration",
                "order": 6,
                "name": "Concentration",
                "description": "Evaporate under N₂ at 40°C to ~0.5 mL",
                "reagent_roles": [],
                "equipment": ["N₂ Evaporator", "Water Bath (40°C)"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
            {
                "id": "reconstitution",
                "order": 7,
                "name": "Reconstitution & Final Check",
                "description": "Reconstitute in mobile phase A; vortex; transfer to LC vial",
                "reagent_roles": ["Mobile Phase A"],
                "equipment": ["Vortex Mixer", "LC Vials", "PTFE Syringe Filter"],
                "creates_solution": False,
                "capture_pedigree": False,
            },
        ],
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

    When a saved profile exists, top-level keys present in DEFAULT_PROFILES but
    absent from the saved copy are back-filled from the default.  This lets new
    fields added to DEFAULT_PROFILES (e.g. extraction_stages) appear in existing
    saved profiles without requiring a manual re-save.
    """
    store = get_profile_store(portal)
    raw = store.get(method_id)
    if raw is None:
        dflt = DEFAULT_PROFILES.get(method_id)
        if dflt is None:
            return {"method_id": method_id}
        return copy.deepcopy(dflt)
    try:
        saved = json.loads(raw)
        dflt = DEFAULT_PROFILES.get(method_id)
        if dflt:
            for key, default_val in dflt.items():
                if key not in saved:
                    saved[key] = copy.deepcopy(default_val)
        _migrate_spike_levels(saved, dflt)
        return saved
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
            profile = json.loads(raw)
            dflt = DEFAULT_PROFILES.get(method_id, {})
            # Back-fill new default keys absent from the stored profile
            for key, default_val in dflt.items():
                if key not in profile:
                    profile[key] = copy.deepcopy(default_val)
            # Apply shape-migration so exported file always has new-format spike_levels
            _migrate_spike_levels(profile, dflt)
            all_profiles[method_id] = profile
        except (ValueError, TypeError):
            pass

    # Augment each exported profile with derived fields the pipeline expects.
    for profile in all_profiles.values():
        # display_analyte_set: display names in analyte order, derived from
        # per_analyte rows.  The pipeline's get_analyte_list() checks this
        # first so it does not need to fall back to a hardcoded list.
        per_a = profile.get("per_analyte", [])
        if per_a and "display_analyte_set" not in profile:
            profile["display_analyte_set"] = [
                r["analyte"] for r in per_a if r.get("analyte")
            ]

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


def get_included_analytes(portal, method_id, matrix):
    """Return the ordered list of analyte keywords reportable for method × matrix.

    Reads analyte_matrix_inclusion from the stored profile.  Analytes where the
    checkbox is True (or absent — conservative default) are included.  PFODA in
    FDA × Eggs is excluded by default (seeded carve-out).

    Downstream callers (surrogate map, recovery tiers, QC engine, report, EDD)
    must use this function rather than reading master_analyte_set directly so
    that the Method × Matrix panel is always respected.
    """
    profile = get_profile(portal, method_id)
    master = profile.get("master_analyte_set", [])
    inclusion = profile.get("analyte_matrix_inclusion", {})
    if not inclusion:
        return list(master)
    return [kw for kw in master
            if inclusion.get(kw, {}).get(matrix, True)]


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
