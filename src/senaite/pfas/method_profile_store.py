# -*- coding: utf-8 -*-
"""
PFAS Method Profile Store — ZODB-backed, file-exported per-method QC config.

Python 2.7 compatible.  No f-strings, no pathlib, no annotations.

Storage pattern
---------------
  portal.pfas_method_profiles[method_id].profile_json   (a MethodProfile)

The JSON string is replaced in its entirety on every save, which avoids
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

PROFILES_EXPORT_PATH = os.environ.get(
    "PFAS_PROFILES_PATH", "/data/qc/method_profiles.json"
)

# the install seed's surrogate links (analyte_reference.py), copied once
# into each shipped method's own Surrogate Map
from senaite.pfas.analyte_reference import derive_surrogate_map as _derive_surrogate_map



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


# keys the Isomers and Isotope standards tabs replaced: a profile holding
# one is refused at the save
RETIRED_KEYS = ("isomer_summation", "surrogate_is_chain", "surrogate_is")


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
# linear isomers (the method's isomers), never as independent rows in the report.
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
    # A carve-out not listed here is seeded True (included).
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
# br-PFHxS and br-PFOS are excluded here (summed by the method's isomers).
# EPA 1633A's extracted internal standards per native (EPA 820-R-24-007,
# Table 6), each a labelled compound of the library; a native with no
# designation of its own takes the method's "no labelled standard" tier.
# 13C8-FOSA is the library's keyword for Table 6's 13C8-PFOSA.
# EPA 1633A §14.9: the window the NIS areas are judged by
_EPA1633A_NIS_WINDOW_NOTE = (u"EPA 1633A §14.9: the NIS areas in field and QC samples within "
                             u"50 to 200 % of the mean area of the corresponding NIS in the most "
                             u"recent initial calibration.")
# Table 10, the target analytes with no EIS of their own: the EIS used for
# quantification, by the library's keywords (Table 10 spells ADONA and
# 9Cl-PF3ONS, the compounds' published names). PFTrDA is quantified on the
# average of 13C2-PFTeDA and 13C2-PFDoA, which one link cannot say, so it
# is left to the lab.
_EPA1633A_SHARED_EIS = [
    ("PFPeS", "13C3-PFHxS"), ("PFHpS", "13C8-PFOS"), ("PFNS", "13C8-PFOS"), ("PFDS", "13C8-PFOS"),
    ("PFDoS", "13C8-PFOS"), ("DONA", "13C3-HFPO-DA"), ("PFMPA", "13C5-PFPeA"), ("PFMBA", "13C5-PFPeA"),
    ("NFDHA", "13C5-PFHxA"), ("9ClPF3ONS", "13C3-HFPO-DA"), ("11ClPF3OUdS", "13C3-HFPO-DA"),
    ("PFEESA", "13C5-PFHxA"), ("3:3FTCA", "13C5-PFPeA"), ("5:3FTCA", "13C5-PFHxA"), ("7:3FTCA", "13C5-PFHxA"),
]

_EPA1633A_EIS = [
    ("PFBA", "13C4-PFBA"), ("PFPeA", "13C5-PFPeA"), ("PFHxA", "13C5-PFHxA"),
    ("PFHpA", "13C4-PFHpA"), ("PFOA", "13C8-PFOA"), ("PFNA", "13C9-PFNA"),
    ("PFDA", "13C6-PFDA"), ("PFUDA", "13C7-PFUnA"), ("PFDoA", "13C2-PFDoA"),
    ("PFTeDA", "13C2-PFTeDA"), ("PFBS", "13C3-PFBS"), ("PFHxS", "13C3-PFHxS"),
    ("PFOS", "13C8-PFOS"), ("4:2FTS", "13C2-4:2FTS"), ("6:2FTS", "13C2-6:2FTS"),
    ("8:2FTS", "13C2-8:2FTS"), ("FOSA", "13C8-FOSA"), ("NMeFOSA", "D3-NMeFOSA"),
    ("NEtFOSA", "D5-NEtFOSA"), ("NMeFOSAA", "D3-NMeFOSAA"), ("NEtFOSAA", "D5-NEtFOSAA"),
    ("NMeFOSE", "D7-NMeFOSE"), ("NEtFOSE", "D9-NEtFOSE"), ("GenX", "13C3-HFPO-DA"),
]

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


# ── Default profiles: the install seeds, edited by a manager in the UI ────────

DEFAULT_PROFILES = {
    "FDA_32PFAS": {
        "method_id": "FDA_32PFAS",
        "display_name": "FDA 32-PFAS in Food and Feed",
        "description": ("USDA/FDA 32-PFAS in Food v10 (5/5/26) + AOAC SMPR 2023.003; "
            "LC-MS/MS isotope dilution"),
        "instrument_verification": {
            "calibration": {
                # the lab's value (C-010.04)
                "r2_min": 0.990,
                "point_pct_dev_max": 20.0,
                "low_point_pct_dev_max": None,
                "level_unit": "ng/mL",
                "levels": [
                    {"conc": 0.0390625, "name": "CAL-1"},
                    {"conc": 0.078125, "name": "CAL-2"},
                    {"conc": 0.15625, "name": "CAL-3"},
                    {"conc": 0.3125, "name": "CAL-4"},
                    {"conc": 0.625, "name": "CAL-5"},
                    {"conc": 1.25, "name": "CAL-6"},
                    {"conc": 2.5, "name": "CAL-7"},
                    {"conc": 5.0, "name": "CAL-8"},
                    {"conc": 10.0, "name": "CAL-9"},
                    {"conc": 20.0, "name": "CAL-10"},
                ],
                "levels_source": "Lab instruction 2026-10-02: 0.039 to 20 ng/mL, each point double the last (10 points).",
                "origin": "exclude",
                "weighting": "1/x",
            },
            "ccv": {
                "frequency": 6,
                "recovery_min": 70.0,
                "recovery_max": 130.0,
                "low_level_min": None,
                "low_level_max": None,
                # a CCV (after the CCB) opens the bracket: every extracted
                # injection runs inside one
                "opens_run": "yes",
            },
            "is_response": {
                "vs_ical_avg_min": 50.0,
                "vs_ical_avg_max": 150.0,
                "vs_last_ccv_min": None,
                "vs_last_ccv_max": None,
                "notes": "Lab SOP screen; FDA method sets no numeric IS-area limit",
            },
            # VERIFY: the lab confirms these against C-010.04
            "surrogate_window": {"recovery_min": 50.0, "recovery_max": 150.0},
            "confirmation": {
                "rrt_tol_pct": 1.0,
                "rt_tol_abs_min": None,
                "ion_ratio_tol_pct": 30.0,
                "sn_quan_min": 3.0,
                "sn_confirm_min": 3.0,
                "require_confirm_ion_check": True,
                "single_transition_analytes": ["PFBA", "PFPeA"],   # keywords of the panel
                "confirm_pct_diff_max": 20.0,
            },
        },
        "qc_acceptance": {
            "MB": {
                "enabled": True,
                "tiers": [{"name": "default", "analyte_group": "all",
                           "matrix_scope": "all", "max_conc_x_rl": 1.0}],
            },
            "LRB": {
                "enabled": True,
                "tiers": [{"name": "default", "analyte_group": "all",
                           "matrix_scope": "all", "max_conc_x_rl": 1.0}],
            },
            # NB: PFAS-in-food/feed (FDA) does NOT use LFB/LCS — it relies on
            # matrix spikes (LFSM/LFSMD). The blank-spike QC type lives on the
            # EPA water-method profiles, not here.
            "LFSM": {
                "enabled": True,
                "tiers": [
                    {
                        "name": "tier1_key_tight",
                        "analyte_group": "key",
                        "matrix_scope": "listed",
                        "recovery_min": 80.0,
                        "recovery_max": 120.0,
                        "rsd_max": 20.0,
                        "matrices": [],
                    },
                    {"name": "tier2_linked", "analyte_group": "linked",
                     "matrix_scope": "all",
                     "recovery_min": 65.0, "recovery_max": 135.0, "rsd_max": 25.0},
                    {"name": "tier3_no_std", "analyte_group": "no_std",
                     "matrix_scope": "all",
                     "recovery_min": 40.0, "recovery_max": 140.0, "rsd_max": 30.0},
                ],
            },
            "LFSMD": {
                "enabled": True,
                "tiers": [
                    {
                        "name": "tier1_key_tight",
                        "analyte_group": "key",
                        "matrix_scope": "listed",
                        "recovery_min": 80.0,
                        "recovery_max": 120.0,
                        "rpd_max": 20.0,
                        "matrices": [],
                    },
                    {"name": "tier2_linked", "analyte_group": "linked",
                     "matrix_scope": "all",
                     "recovery_min": 65.0, "recovery_max": 135.0, "rpd_max": 25.0},
                    {"name": "tier3_no_std", "analyte_group": "no_std",
                     "matrix_scope": "all",
                     "recovery_min": 40.0, "recovery_max": 140.0, "rpd_max": 30.0},
                ],
            },
            "Dup": {
                "enabled": True,
                "tiers": [{"name": "default", "analyte_group": "all",
                           "matrix_scope": "all", "rpd_max": 20.0}],
            },
        },
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
        # the seed's surrogate links, copied once: each method owns its map
        "surrogate_map": _derive_surrogate_map(_FDA_MASTER_ANALYTE_KEYWORDS),
        "supported_matrices": list(_FDA_MATRICES),
        # 32 reportable target analytes (br-isomers excluded; summed by the method's isomers)
        "master_analyte_set": list(_FDA_MASTER_ANALYTE_KEYWORDS),
        # keyword → {matrix_name → bool}  — the inclusion checkbox grid
        # PFODA × Eggs = False; all other intersections = True
        "analyte_matrix_inclusion": _fda_analyte_matrix_inclusion(),
        # Milk → ng/mL (liquid matrix, per-volume); all other FDA matrices → ng/kg.
        # Unit is per-matrix and editable via the Method Profile UI.
        "unit_map": dict(
            [(m, "ng/mL" if m == "Milk" else "ng/kg") for m in _FDA_MATRICES]
        ),
        # Spike level options for LFSM (and LFB) injections — keyed by matrix.
        # ppt values left as null — the lab enters them via the Method Profile UI.
        "spike_levels": _per_matrix_spike_levels(_FDA_MATRICES),
        # Holding time (days, collection → extraction) deliberately UNSET: no
        # documented value, and none is invented. Unset refuses to judge, not
        # pass; the lab enters its own. See holding_time.py.
        "holding_times": {m: None for m in _FDA_MATRICES},
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
                "captures_samples": "",
                "consumables": [],
            },
            {
                "id": "weighing",
                "order": 2,
                "name": "Sample Weighing & Aliquoting",
                "description": "Weigh 1 g (±0.02 g) test portion into 50 mL centrifuge tube",
                "reagent_roles": [],
                "equipment": ["Analytical Balance"],
                "creates_solution": False,
                "capture_pedigree": False,
                "captures_samples": "amount",
                "confirmations": [],
                "consumables": ["50 mL Centrifuge Tubes"],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "final_volume",
                "consumables": [],
            },
            {
                "id": "transfer",
                "order": 8,
                "name": "QC Check & Transfer to Vial",
                "description": "Filter through PTFE syringe filter; transfer to LC vial",
                "reagent_roles": ["PTFE Syringe Filter (0.2 μm)"],
                "equipment": [],
                "creates_solution": False,
                "capture_pedigree": False,
                "captures_samples": "",
                "consumables": ["1 mL Syringe", "LC Vials"],
            },
        ],
        # Ordered logbooks required for a batch using this method.
        # 250 = Solvent/Reagent Prep, 252 = Extraction Log (Guided), 251 = Cal Prep, 253 = Sample Processing
        "required_logbooks": ["252", "253"],
        "blank_role_name": "MB",
        "engine": {
            "aliases": ["FDA", "FDA32", "C-010.04"],
            "eis_recovery_limits": False,
            "eis_verify_flag": False,
            "inclusion_needs_verification": False,
            "labelled_compound_fit": "mean_response_factor",
            "qc_type_aliases": {"duplicate": "Dup"},
            "required_keys": {
                "calibration": ["r2_min"],
                "confirmation": ["ion_ratio_tol_pct", "rrt_tol_pct", "sn_quan_min", "sn_confirm_min"],
                "is_response": ["vs_ical_avg_min", "vs_ical_avg_max"],
            },
            "rule_notes": {
                "confirmation_rule": "PFBA/PFPeA positives require LC-HRMS confirmation; cholic acid (TDCA/TCDCA/TUDCA) interference transitions monitored for PFOS (§2024.8.5)",
                "is_rule": "Lab SOP screen; the FDA method sets no numeric IS-area limit",
                "tier_default": "Table 10-1 tier 2 (other matrices / other analytes)",
                "tier_key_tight": "PFOS/PFOA/PFHxS/PFNA in eggs/meat/seafood (Table 10-1 tier 1)",
                "tier_low_level": "low-level window (<= {0:g} x RL)",
                "tier_no_std": "No matched labeled standard (Table 10-1 footnote a)",
            },
            "surrogate_fallback": {
                "citation": "Surrogate recovery is guidance only (FDA §2024.10.1(5))",
                "max": 150.0,
                "min": 50.0,
            },
            "surrogate_guidance_only": True,
        },
        "isomers": {
            "PFHxS": {"branched": ["br-PFHxS"], "linear": "lr-PFHxS", "reported": ""},
            "PFNA": {"branched": ["br-PFNA"], "linear": "lr-PFNA", "reported": ""},
            "PFOA": {"branched": ["br-PFOA"], "linear": "lr-PFOA", "reported": ""},
            "PFOS": {"branched": ["br-PFOS"], "linear": "lr-PFOS", "reported": ""},
        },
        "key_analytes": ["PFOA", "PFNA", "PFHxS", "PFOS"],
        "labelled_standards": {
            "13C2-D4-10:2FTS": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-D4-4:2FTS": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-D4-6:2FTS": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-D4-8:2FTS": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-PFDA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-PFDoA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-PFHxDA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-PFTeDA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C2-PFUDA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C3-HFPO-DA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C3-PFBA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C3-PFBS": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C3-PFHxS": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C3-PFPeA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C4-PFHpA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C4-PFOA": {"reference": "", "role": "injection_is"},
            "13C5-PFHxA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C5-PFNA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C8-FOSA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C8-PFOA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C8-PFOS": {"reference": "13C4-PFOA", "role": "surrogate"},
        },
        "matrix_codes": {
            "Animal Feed": "AF",
            "Aquatic Tissue": "AT",
            "Eggs": "EGG",
            "Fish / Seafood": "FS",
            "Meat / Muscle": "MM",
            "Milk": "MILK",
        },
        "qc_name_codes": {"METHOD": "FDA"},
        "report_format": {"*": {}},
        "rule_states": {
            "blank.LRB": "enforced",
            "blank.MB": "enforced",
            "cal_r2": "enforced",
            "ccv_frequency": "enforced",
            "ccv_recovery": "enforced",
            "ion_ratio": "enforced",
            "is_response": "enforced",
            "is_vs_ccv": "off",
            "mdl_check": "off",
            "over_range": "enforced",
            "qc_type.Dup": "enforced",
            "qc_type.LFSM": "enforced",
            "qc_type.LFSMD": "enforced",
            "rrt_deviation": "enforced",
            "single_transition_confirm": "enforced",
            "sn_min": "off",
            "surrogate_recovery": "enforced",
        },
        "rule_toggles": {
            "cal_r2": True,
            "ccv_frequency": True,
            "ccv_recovery": True,
            "ion_ratio": True,
            "is_response": True,
            "is_vs_ccv": False,
            "mdl_check": False,
            "over_range": True,
            "rrt_deviation": True,
            "single_transition_confirm": True,
            "sn_min": False,
            "surrogate_recovery": True,
        },
        "study_kinds": ["mdl", "pt"],
    },
    "EPA_537_1": {
        "method_id": "EPA_537_1",
        "display_name": "EPA 537.1 Drinking Water",
        "description": "EPA 537.1 PFAS in drinking water (EPA/600/R-20/006)",
        "instrument_verification": {
            "calibration": {
                "r2_min": 0.990,
                "point_pct_dev_max": 30.0,
                "low_point_pct_dev_max": 50.0,
                "level_unit": "ppt",
                "origin": "force",
                "weighting": "1/x",
            },
            "ccv": {
                "frequency": 10,
                "recovery_min": 70.0,
                "recovery_max": 130.0,
                "low_level_min": 50.0,
                "low_level_max": 150.0,
                #: only field samples count toward the ten
                "counts_extracted_qc": "no",
                "opens_run": "yes",
                "surrogate_recovery": "yes",
            },
            "is_response": {
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
            "icv": {"criteria": "ccv"},
        },
        "qc_acceptance": {
            "MB": {
                "enabled": True,
                "tiers": [{"name": "default", "analyte_group": "all",
                           "matrix_scope": "all", "max_conc_x_rl": 1.0}],
            },
            "LRB": {
                "enabled": True,
                # §9.3.1: background "must be below 1/3 of the MRL"; at or
                # above it the analyte's data for the batch are invalid
                "tiers": [{"name": "default", "analyte_group": "all",
                           "matrix_scope": "all", "max_conc_x_rl": 1.0 / 3,
                           "fails_at_limit": True,
                           "citation": "EPA 537.1 v2.0 §9.3.1"}],
            },
            "LFB": {
                "enabled": True,
                "tiers": [
                    {
                        "name": "low_level",
                        "analyte_group": "all",
                        "matrix_scope": "all",
                        "description": "Low level, no more than 2 x MRL (§9.3.3)",
                        "recovery_min": 50.0,
                        "recovery_max": 150.0,
                        "rsd_max": None,
                        "citation": "EPA 537.1 v2.0 (EPA/600/R-20/006, March 2020) §9.3.3",
                        "low_level_x_rl": 2.0,
                    },
                    {"name": "mid_high", "analyte_group": "all",
                     "matrix_scope": "all", "description": "Above MRL",
                     "recovery_min": 70.0, "recovery_max": 130.0, "rsd_max": None},
                ],
            },
            "LFSM": {
                "enabled": True,
                "tiers": [
                    {
                        "analyte_group": "all",
                        "matrix_scope": "all",
                        "name": "default",
                        "recovery_max": 130.0,
                        "recovery_min": 70.0,
                        "rsd_max": None,
                    },
                    {
                        "analyte_group": "all",
                        "citation": "EPA 537.1 v2.0 (EPA/600/R-20/006, March 2020) §9.3.6.3",
                        "description": "Within 2 x MRL (§9.3.6.3)",
                        "low_level_x_rl": 2.0,
                        "matrix_scope": "all",
                        "name": "low_level",
                        "recovery_max": 150.0,
                        "recovery_min": 50.0,
                    },
                ],
            },
            "LFSMD": {
                "enabled": True,
                "tiers": [
                    {
                        "analyte_group": "all",
                        "matrix_scope": "all",
                        "name": "default",
                        "recovery_max": 130.0,
                        "recovery_min": 70.0,
                        "rpd_max": 30.0,
                    },
                    {
                        "analyte_group": "all",
                        "citation": "EPA 537.1 v2.0 (EPA/600/R-20/006, March 2020) §9.3.7.4",
                        "description": "Within 2 x MRL (§9.3.7.4)",
                        "low_level_x_rl": 2.0,
                        "matrix_scope": "all",
                        "name": "low_level",
                        "rpd_max": 50.0,
                    },
                ],
            },
            "Dup": {
                "enabled": True,
                "tiers": [
                    {
                        "analyte_group": "all",
                        "matrix_scope": "all",
                        "name": "default",
                        "rpd_max": 30.0,
                    },
                    {
                        "analyte_group": "all",
                        "citation": "EPA 537.1 v2.0 (EPA/600/R-20/006, March 2020) §9.3.7.2",
                        "description": "Within 2 x MRL (§9.3.7.2, field duplicate)",
                        "low_level_x_rl": 2.0,
                        "matrix_scope": "all",
                        "name": "low_level",
                        "rpd_max": 50.0,
                    },
                ],
            },
        },
        "matrix_factors": [],
        "surrogate_map": [
            {"analyte": "11ClPF3OUdS", "surrogate_is": "13C4-PFOS"},
            {"analyte": "9ClPF3ONS", "surrogate_is": "13C4-PFOS"},
            {"analyte": "DONA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "GenX", "surrogate_is": "13C2-PFOA"},
            {"analyte": "NEtFOSAA", "surrogate_is": "D3-NMeFOSAA"},
            {"analyte": "NMeFOSAA", "surrogate_is": "D3-NMeFOSAA"},
            {"analyte": "PFBS", "surrogate_is": "13C4-PFOS"},
            {"analyte": "PFDA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFDoA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFHpA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFHxA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFHxS", "surrogate_is": "13C4-PFOS"},
            {"analyte": "PFNA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFOA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFOS", "surrogate_is": "13C4-PFOS"},
            {"analyte": "PFTeDA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFTrDA", "surrogate_is": "13C2-PFOA"},
            {"analyte": "PFUDA", "surrogate_is": "13C2-PFOA"},
        ],
        "supported_matrices": list(_EPA537_MATRICES),
        # EPA 537.1: 18 analytes per EPA/600/R-20/006 Table 1.1
        "master_analyte_set": list(_EPA537_ANALYTE_KEYWORDS),
        "analyte_matrix_inclusion": _all_included_matrix(
            _EPA537_ANALYTE_KEYWORDS, _EPA537_MATRICES
        ),
        "unit_map": {m: "ng/L" for m in _EPA537_MATRICES},
        # Holding time, days from collection to EXTRACTION: EPA 537.1 specifies
        # 14 days for drinking water PFAS. The only seeded holding time; an
        # unset limit refuses to judge instead of passing. See holding_time.py.
        "holding_times": {m: 14 for m in _EPA537_MATRICES},
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "amount",
                "confirmations": [],
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
            },
            {
                "id": "elution",
                "order": 7,
                "name": "Elution",
                "description": "Elute with 2 × 5 mL MeOH into PP tubes",
                "reagent_roles": ["Methanol (LC-MS grade)"],
                "equipment": ["SPE Manifold"],
                "creates_solution": False,
                "capture_pedigree": False,
                "captures_samples": "",
                "consumables": ["50 mL PP Tubes"],
            },
            {
                "id": "reconstitution",
                "order": 8,
                "name": "Concentration & Reconstitution",
                "description": "Evaporate under N₂ to ~0.5 mL; bring to 1 mL with reagent water",
                "reagent_roles": ["Reagent Water"],
                "equipment": ["N₂ Evaporator"],
                "creates_solution": False,
                "capture_pedigree": False,
                "captures_samples": "final_volume",
                "consumables": ["1 mL LC Vials"],
            },
        ],
        "required_logbooks": ["252", "253"],
        "blank_role_name": "LRB",
        "engine": {
            "aliases": ["537", "537.1", "EPA537"],
            "eis_recovery_limits": False,
            "eis_verify_flag": False,
            "inclusion_needs_verification": True,
            "required_keys": {
                "calibration": ["r2_min", "point_pct_dev_max", "low_point_pct_dev_max"],
                "confirmation": ["rt_tol_abs_min"],
                "is_response": ["vs_ical_avg_min", "vs_ical_avg_max", "vs_last_ccv_min", "vs_last_ccv_max"],
            },
            "rule_notes": {
                "confirmation_rule": "RT within ±0.05 min of expected; no qual-ion ratio criterion in 537.1",
                "is_rule": "Both conditions must hold (§9.3.4); on failure re-inject a second aliquot in a fresh vial",
            },
            "surrogate_fallback": {"citation": "§9.3.5 surrogates 70–130%", "max": 130.0, "min": 70.0},
            "surrogate_guidance_only": False,
        },
        "extract_holding_times": {"Drinking Water": 28, "Groundwater": 28, "Surface Water": 28},
        "idc": {
            "asymmetry": [0.8, 1.5],
            "elements": [
                ["isomers", "Branched / linear isomer profile (§9.2.1)"],
                ["lsb", "Low system background (§9.2.2)"],
                ["pa", "Precision and accuracy (§9.2.3, §9.2.4)"],
                ["qcs", "Calibration confirmation, QCS = the ICV (§9.2.7)"],
                ["asymmetry", "Peak asymmetry (§9.2.5)"],
                ["mrl", "MRL confirmation (§9.2.6)"],
            ],
        },
        "isomers": {
            "PFHxS": {"branched": ["br-PFHxS"], "linear": "lr-PFHxS", "reported": ""},
            "PFNA": {"branched": ["br-PFNA"], "linear": "lr-PFNA", "reported": ""},
            "PFOA": {"branched": ["br-PFOA"], "linear": "lr-PFOA", "reported": ""},
            "PFOS": {"branched": ["br-PFOS"], "linear": "lr-PFOS", "reported": ""},
        },
        "key_analytes": ["PFOA", "PFNA", "PFHxS", "PFOS"],
        "labelled_standards": {
            "13C2-PFDA": {"reference": "13C2-PFOA", "role": "surrogate"},
            "13C2-PFHxA": {"reference": "13C2-PFOA", "role": "surrogate"},
            "13C2-PFOA": {"reference": "", "role": "injection_is"},
            "13C3-HFPO-DA": {"reference": "13C2-PFOA", "role": "surrogate"},
            "13C4-PFOS": {"reference": "", "role": "injection_is"},
            "D3-NMeFOSAA": {"reference": "", "role": "injection_is"},
            "D5-NEtFOSAA": {"reference": "D3-NMeFOSAA", "role": "surrogate"},
        },
        "matrix_codes": {"Drinking Water": "DW", "Groundwater": "GW", "Surface Water": "SW"},
        "qc_name_codes": {"CCV": "CCC", "ICV": "QCS", "METHOD": "537"},
        "report_format": {"*": {}},
        "rule_states": {
            "blank.LRB": "enforced",
            "blank.MB": "enforced",
            "cal_r2": "enforced",
            "ccv_frequency": "enforced",
            "ccv_recovery": "enforced",
            "ion_ratio": "off",
            "is_response": "enforced",
            "is_vs_ccv": "enforced",
            "mdl_check": "enforced",
            "over_range": "enforced",
            "qc_type.Dup": "enforced",
            "qc_type.LFB": "enforced",
            "qc_type.LFSM": "enforced",
            "qc_type.LFSMD": "enforced",
            "rrt_deviation": "enforced",
            "single_transition_confirm": "enforced",
            "sn_min": "off",
            "surrogate_recovery": "enforced",
        },
        "rule_toggles": {
            "cal_r2": True,
            "ccv_frequency": True,
            "ccv_recovery": True,
            "ion_ratio": False,
            "is_response": True,
            "is_vs_ccv": True,
            "mdl_check": True,
            "over_range": True,
            "rrt_deviation": True,
            "single_transition_confirm": True,
            "sn_min": False,
            "surrogate_recovery": True,
        },
        "study_kinds": ["mdl", "pt", "pa", "mrl", "dl", "idc"],
        "surrogate_failure_scope": "sample",
    },
    "EPA_1633A": {
        "method_id": "EPA_1633A",
        "display_name": "EPA 1633A Multi-Matrix",
        "description": ("EPA 1633A — 40 PFAS in aqueous, solid, biosolid, tissue "
            "(Jan 2024 / 2024 update). EIS limits per-analyte and per-matrix "
            "(Tables 6/8) — VERIFY against method before production use."),
        "instrument_verification": {
            "calibration": {
                "r2_min": 0.990,
                "point_pct_dev_max": 30.0,
                "low_point_pct_dev_max": 50.0,
                "analyte_scale": {
                    "11ClPF3OUdS": {"factor": 4.0, "max": 250.0},
                    "3:3FTCA": {"factor": 5.0, "max": 312.0},
                    "4:2FTS": {"factor": 4.0, "max": 50.0},
                    "5:3FTCA": {"factor": 25.0, "max": 1560.0},
                    "6:2FTS": {"factor": 4.0, "max": 50.0},
                    "7:3FTCA": {"factor": 25.0, "max": 1560.0},
                    "8:2FTS": {"factor": 4.0, "max": 50.0},
                    "9ClPF3ONS": {"factor": 4.0, "max": 250.0},
                    "DONA": {"factor": 4.0, "max": 250.0},
                    "GenX": {"factor": 4.0, "max": 250.0},
                    "NEtFOSE": {"factor": 10.0, "max": 625.0},
                    "NFDHA": {"factor": 2.0, "max": 125.0},
                    "NMeFOSE": {"factor": 10.0, "max": 625.0},
                    "PFBA": {"factor": 4.0, "max": 250.0},
                    "PFEESA": {"factor": 2.0, "max": 125.0},
                    "PFMBA": {"factor": 2.0, "max": 125.0},
                    "PFMPA": {"factor": 2.0, "max": 125.0},
                    "PFPeA": {"factor": 2.0, "max": 125.0},
                },
                "level_unit": "ng/mL",
                "levels": [
                    {"conc": 0.2, "name": "CAL-1"},
                    {"conc": 0.4, "name": "CAL-2"},
                    {"conc": 0.8, "name": "CAL-3"},
                    {"conc": 1.6, "name": "CAL-4"},
                    {"conc": 3.2, "name": "CAL-5"},
                    {"conc": 6.4, "name": "CAL-6"},
                    {"conc": 12.8, "name": "CAL-7"},
                    {"conc": 25.6, "name": "CAL-8"},
                    {"conc": 51.2, "name": "CAL-9"},
                ],
                "levels_source": "EPA Method 1633A (December 2024) Table 4: each analyte from its CS1 to its highest listed standard, each point double the last (lab instruction 2026-10-02).",
                "origin": "exclude",
                "weighting": "1/x",
            },
            "ccv": {
                "frequency": 10,
                "recovery_min": 70.0,
                "recovery_max": 130.0,
                "low_level_min": None,
                "low_level_max": None,
            },
            "is_response": {
                # EPA 1633A §14.9: NIS areas within 50-200 % of the ICAL mean area
                "vs_ical_avg_min": 50.0,
                "vs_ical_avg_max": 200.0,
                "vs_last_ccv_min": None,
                "vs_last_ccv_max": None,
                "notes": _EPA1633A_NIS_WINDOW_NOTE,
            },
            "confirmation": {
                "rrt_tol_pct": None,
                "rt_tol_abs_min": None,
                "ion_ratio_tol_pct": 50.0,
                "sn_quan_min": 3.0,
                "sn_confirm_min": 1.0,
                "require_confirm_ion_check": True,
            },
            "icv": {"criteria": "ccv"},
        },
        "qc_acceptance": {
            "MB": {
                "enabled": True,
                "tiers": [{"name": "default", "analyte_group": "all",
                           "matrix_scope": "all", "max_conc_x_rl": 1.0}],
            },
            "LRB": {
                "enabled": True,
                "tiers": [{"name": "default", "analyte_group": "all",
                           "matrix_scope": "all", "max_conc_x_rl": 1.0}],
            },
            "LFB": {
                "enabled": True,
                "tiers": [
                    # EIS/NIS default aqueous window — VERIFY against 1633A Tables 6/8
                    {"name": "default", "analyte_group": "all",
                     "matrix_scope": "all", "verify_against_method": True,
                     "recovery_min": 40.0, "recovery_max": 130.0, "rsd_max": None},
                ],
            },
            "LFSM": {
                "enabled": True,
                "tiers": [
                    {
                        "name": "default",
                        "analyte_group": "all",
                        "matrix_scope": "all",
                        "recovery_min": 40.0,
                        "recovery_max": 130.0,
                        "rsd_max": None,
                        "citation": "The lab's value: EPA 1633A sets no matrix-spike or duplicate criterion (§9.7, §9.9).",
                    },
                ],
            },
            "LFSMD": {
                "enabled": True,
                "tiers": [
                    {
                        "name": "default",
                        "analyte_group": "all",
                        "matrix_scope": "all",
                        "recovery_min": 40.0,
                        "recovery_max": 130.0,
                        "rpd_max": 30.0,
                        "citation": "The lab's value: EPA 1633A sets no matrix-spike or duplicate criterion (§9.7, §9.9).",
                    },
                ],
            },
            "Dup": {
                "enabled": True,
                "tiers": [
                    {
                        "name": "default",
                        "analyte_group": "all",
                        "matrix_scope": "all",
                        "rpd_max": 30.0,
                        "citation": "The lab's value: EPA 1633A sets no matrix-spike or duplicate criterion (§9.7, §9.9).",
                    },
                ],
            },
        },
        # EIS recovery limits — from EPA 1633A (December 2024, EPA 820-R-24-007),
        # keyed by the labelled compound's keyword (Table 6's 13C8-PFOSA is
        # the library's 13C8-FOSA).
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
            {"analyte": "13C8-FOSA"  ,    "recovery_min": 40.0, "recovery_max": 130.0},
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
                "13C8-FOSA"  :  {"recovery_min": 40.0, "recovery_max": 130.0},
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
                "13C8-FOSA"  :  {"recovery_min": 25.0, "recovery_max": 180.0},
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
                "13C8-FOSA"  :  {"recovery_min": 20.0, "recovery_max": 140.0},
                "D3-NMeFOSA":  {"recovery_min": 20.0, "recovery_max": 130.0},
                "D5-NEtFOSA":  {"recovery_min": 20.0, "recovery_max": 130.0},
                "D3-NMeFOSAA": {"recovery_min": 30.0, "recovery_max": 150.0},
                "D5-NEtFOSAA": {"recovery_min": 20.0, "recovery_max": 140.0},
                "D7-NMeFOSE":  {"recovery_min": 25.0, "recovery_max": 130.0},
                "D9-NEtFOSE":  {"recovery_min": 20.0, "recovery_max": 130.0},
            },
        },
        "matrix_factors": [],
        # Table 10: each analyte's EIS, and the EIS used for one without its own
        "surrogate_map": [{"analyte": n, "surrogate_is": l}
                          for n, l in _EPA1633A_EIS + _EPA1633A_SHARED_EIS],
        "supported_matrices": list(_EPA1633A_MATRICES),
        # EPA 1633A: 40 analytes per EPA 820-R-24-007 Table 1, December 2024
        "master_analyte_set": list(_EPA1633A_ANALYTE_KEYWORDS),
        "analyte_matrix_inclusion": _all_included_matrix(
            _EPA1633A_ANALYTE_KEYWORDS, _EPA1633A_MATRICES
        ),
        "unit_map": dict(_EPA1633A_UNIT_MAP),
        # Holding time (days, collection → extraction) deliberately UNSET:
        # 1633A's limits differ by matrix and none is invented. Unset refuses
        # to judge. See holding_time.py.
        "holding_times": {m: None for m in _EPA1633A_MATRICES},
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "amount",
                "confirmations": [],
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
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
                "captures_samples": "",
                "consumables": [],
            },
            {
                "id": "reconstitution",
                "order": 7,
                "name": "Reconstitution & Final Check",
                "description": "Reconstitute in mobile phase A; vortex; transfer to LC vial",
                "reagent_roles": ["Mobile Phase A"],
                "equipment": ["Vortex Mixer"],
                "creates_solution": False,
                "capture_pedigree": False,
                "captures_samples": "final_volume",
                "consumables": ["LC Vials", "PTFE Syringe Filter"],
            },
        ],
        "required_logbooks": ["252", "253"],
        "blank_role_name": "MB",
        "engine": {
            "aliases": ["1633", "1633A", "EPA1633"],
            "eis_default_window": "lfsm_tier",
            "eis_recovery_limits": True,
            "eis_verify_flag": True,
            "inclusion_needs_verification": True,
            "qc_type_aliases": {"IPR": "LFB", "OPR": "LFB"},
            "required_keys": {
                "calibration": ["r2_min", "point_pct_dev_max", "low_point_pct_dev_max"],
                "confirmation": ["ion_ratio_tol_pct", "sn_quan_min", "sn_confirm_min"],
                "is_response": ["vs_ical_avg_min", "vs_ical_avg_max"],
            },
            "rule_notes": {
                "confirmation_rule": "Ion-ratio window wider in 1633A (50–150% of expected typical)",
                "eis": "EIS limits per-analyte x matrix class (1633A Tables 6/8, EPA 820-R-24-007) — VERIFY against purchased method copy",
                "is_rule": "NIS screen; EIS uses per-analyte limits",
                "tier": "1633A per-analyte (verify against method)",
            },
            "surrogate_fallback": None,
            "surrogate_guidance_only": False,
        },
        "isomers": {
            "NEtFOSAA": {"branched": ["br-NEtFOSAA"], "linear": "lr-NEtFOSAA", "reported": ""},
            "NMeFOSAA": {"branched": ["br-NMeFOSAA"], "linear": "lr-NMeFOSAA", "reported": ""},
            "PFHxS": {"branched": ["br-PFHxS"], "linear": "lr-PFHxS", "reported": ""},
            "PFNA": {"branched": ["br-PFNA"], "linear": "lr-PFNA", "reported": ""},
            "PFOA": {"branched": ["br-PFOA"], "linear": "lr-PFOA", "reported": ""},
            "PFOS": {"branched": ["br-PFOS"], "linear": "lr-PFOS", "reported": ""},
        },
        "key_analytes": ["PFOA", "PFNA", "PFHxS", "PFOS"],
        "labelled_standards": {
            "13C2-4:2FTS": {"reference": "18O2-PFHxS", "role": "surrogate"},
            "13C2-6:2FTS": {"reference": "18O2-PFHxS", "role": "surrogate"},
            "13C2-8:2FTS": {"reference": "18O2-PFHxS", "role": "surrogate"},
            "13C2-PFDA": {"reference": "", "role": "injection_is"},
            "13C2-PFDoA": {"reference": "13C2-PFDA", "role": "surrogate"},
            "13C2-PFHxA": {"reference": "", "role": "injection_is"},
            "13C2-PFTeDA": {"reference": "13C2-PFDA", "role": "surrogate"},
            "13C3-HFPO-DA": {"reference": "13C2-PFHxA", "role": "surrogate"},
            "13C3-PFBA": {"reference": "", "role": "injection_is"},
            "13C3-PFBS": {"reference": "18O2-PFHxS", "role": "surrogate"},
            "13C3-PFHxS": {"reference": "18O2-PFHxS", "role": "surrogate"},
            "13C4-PFBA": {"reference": "13C3-PFBA", "role": "surrogate"},
            "13C4-PFHpA": {"reference": "13C2-PFHxA", "role": "surrogate"},
            "13C4-PFOA": {"reference": "", "role": "injection_is"},
            "13C4-PFOS": {"reference": "", "role": "injection_is"},
            "13C5-PFHxA": {"reference": "13C2-PFHxA", "role": "surrogate"},
            "13C5-PFNA": {"reference": "", "role": "injection_is"},
            "13C5-PFPeA": {"reference": "13C2-PFHxA", "role": "surrogate"},
            "13C6-PFDA": {"reference": "13C2-PFDA", "role": "surrogate"},
            "13C7-PFUnA": {"reference": "13C2-PFDA", "role": "surrogate"},
            "13C8-FOSA": {"reference": "13C4-PFOS", "role": "surrogate"},
            "13C8-PFOA": {"reference": "13C4-PFOA", "role": "surrogate"},
            "13C8-PFOS": {"reference": "13C4-PFOS", "role": "surrogate"},
            "13C9-PFNA": {"reference": "13C5-PFNA", "role": "surrogate"},
            "18O2-PFHxS": {"reference": "", "role": "injection_is"},
            "D3-NMeFOSA": {"reference": "13C4-PFOS", "role": "surrogate"},
            "D3-NMeFOSAA": {"reference": "13C4-PFOS", "role": "surrogate"},
            "D5-NEtFOSA": {"reference": "13C4-PFOS", "role": "surrogate"},
            "D5-NEtFOSAA": {"reference": "13C4-PFOS", "role": "surrogate"},
            "D7-NMeFOSE": {"reference": "13C4-PFOS", "role": "surrogate"},
            "D9-NEtFOSE": {"reference": "13C4-PFOS", "role": "surrogate"},
        },
        "matrix_classes": {
            "Aquatic Tissue": "tissue",
            "Biosolid": "biosolid",
            "Drinking Water": "aqueous",
            "Groundwater": "aqueous",
            "Landfill Leachate": "leachate",
            "Sediment": "solid",
            "Soil": "solid",
            "Surface Water": "aqueous",
            "Wastewater": "aqueous",
        },
        "matrix_codes": {
            "Aquatic Tissue": "AT",
            "Biosolid": "BS",
            "Drinking Water": "DW",
            "Groundwater": "GW",
            "Landfill Leachate": "LL",
            "Sediment": "SED",
            "Soil": "SOIL",
            "Surface Water": "SW",
            "Wastewater": "WW",
        },
        "qc_name_codes": {"METHOD": "1633A"},
        "report_format": {"*": {}},
        "rule_states": {
            "blank.LRB": "enforced",
            "blank.MB": "enforced",
            "cal_r2": "enforced",
            "ccv_frequency": "enforced",
            "ccv_recovery": "enforced",
            "ion_ratio": "enforced",
            "is_response": "enforced",
            "is_vs_ccv": "off",
            "mdl_check": "enforced",
            "over_range": "enforced",
            "qc_type.Dup": "enforced",
            "qc_type.LFB": "enforced",
            "qc_type.LFSM": "enforced",
            "qc_type.LFSMD": "enforced",
            "rrt_deviation": "enforced",
            "single_transition_confirm": "enforced",
            "sn_min": "enforced",
            "surrogate_recovery": "enforced",
        },
        "rule_toggles": {
            "cal_r2": True,
            "ccv_frequency": True,
            "ccv_recovery": True,
            "ion_ratio": True,
            "is_response": True,
            "is_vs_ccv": False,
            "mdl_check": True,
            "over_range": True,
            "rrt_deviation": True,
            "single_transition_confirm": True,
            "sn_min": True,
            "surrogate_recovery": True,
        },
        "study_kinds": ["mdl", "pt"],
    },
}


# ── ZODB annotation store + Dexterity content path ────────────────────────────

def _get_profiles_folder(portal):
    """The pfas_method_profiles folder at the portal root, or None (a fresh
    install before its install step)."""
    return portal.get("pfas_method_profiles")


def _unknown_profile(method_id):
    """What to return when *method_id* names no configured method: an EMPTY
    dict, so every `if profile:` check is false and no criterion is applied
    by accident.

    The usual cause is a core Method's Zope id ("method-1") where profiles
    are keyed by its MethodID ("FDA_32PFAS"); the warning names the id.
    """
    logger.warning(
        "No method profile for %r — QC criteria will be empty. Profiles are "
        "keyed by Method.MethodID (e.g. FDA_32PFAS), not by the core Method's "
        "Zope id; use method_bridge.profile_id_for_method().", method_id)
    return {}


class ProfileUnreadable(RuntimeError):
    """A stored method profile that cannot be read. The shipped seed is never
    served in its place (criteria nobody configured); the lab restores it from
    Configuration History."""


def _load_saved(method_id, raw):
    try:
        saved = json.loads(raw)
    except (ValueError, TypeError):
        raise ProfileUnreadable(
            "The method profile %s cannot be read. Restore it from Configuration "
            "History (Configuration > Configuration History) before it is used." % method_id)
    _migrate_spike_levels(saved, DEFAULT_PROFILES.get(method_id))
    return saved


def get_profile(portal, method_id):
    """The stored profile dict for method_id (a fresh copy; mutations do not
    persist).

    What is stored is what applies: a section the profile does not hold is
    NOT filled in from the shipped seeds (the checks report it as not
    configured), and an unreadable profile raises ProfileUnreadable rather
    than serving the seed. The seeds are written once, at install; a new
    section for existing profiles comes with a migration.
    """
    folder = _get_profiles_folder(portal)
    if folder is None:
        # a fresh install reads the seeds until the install step writes them
        dflt = DEFAULT_PROFILES.get(method_id)
        return copy.deepcopy(dflt) if dflt is not None else _unknown_profile(method_id)
    if method_id in folder:
        raw = getattr(folder[method_id], "profile_json", None)
        if raw:
            return _load_saved(method_id, raw)
    return _unknown_profile(method_id)


def raw_profile(portal, method_id):
    """The profile exactly as stored (no default back-fill), or {}: what the
    change history diffs and a version stamp is taken from."""
    folder = _get_profiles_folder(portal)
    try:
        if folder is not None and method_id in folder:
            return json.loads(folder[method_id].profile_json or "{}")
    except (ValueError, TypeError):
        pass
    return {}


def service_index():
    """{keyword: {role, name, uid, url}} for every core
    AnalysisService that carries a pfas_role -- the one source for the
    analyte / surrogate / IS lists (the method editor's and the project
    specs' env)."""
    from bika.lims import api
    out = {}
    setup_cat = api.get_tool("senaite_catalog_setup")
    for b in setup_cat(portal_type="AnalysisService"):
        o = b.getObject()
        rf = o.getField("pfas_role")
        role = (rf.get(o) if rf is not None else "") or ""
        if not role:
            continue
        out[o.getKeyword()] = {
            "role": role,
            "name": o.Title() or o.getKeyword(),
            "uid": o.UID(),
            "url": o.absolute_url(),
        }
    return out


def save_profile(portal, method_id, data, label=None):
    """
    Persist data (dict) for method_id.  Replaces the entire entry atomically.
    `label`: what the change history shows for this save (default the
    method's name).
    Also exports /data/qc/method_profiles.json for the pipeline worker, once
    the save has committed.

    Create-on-demand: if method_id has no Dexterity object yet (e.g. wizard
    creating a new method), invokeFactory is called automatically.
    """
    # the id is stamped on purpose: nothing else supplies it for a new profile
    if isinstance(data, dict):
        legacy = [k for k in RETIRED_KEYS if data.get(k)]
        if legacy:
            raise ValueError(
                "The profile for %s holds %s, from before the Isomers and Isotope "
                "standards tabs; nothing reads them. Enter the method's isomers and "
                "isotope standards on those tabs instead." % (method_id, ", ".join(legacy)))
        data["method_id"] = method_id
        # the on/off switches follow the rule states, which are the truth;
        # each QC type's enabled flag follows its row's state; the projects'
        # patches take their tier lists before the method's Tier 1 list goes
        from senaite.pfas import project_specs
        project_specs.as_saved_with_projects(portal, method_id, data)
    # Change history: one entry per profile per transaction, recording who
    # changed which criterion from what to what. A strict store: when the
    # entry cannot be prepared, track() refuses and the save does not happen.
    from senaite.pfas import config_history
    config_history.track(portal, "method_profile", method_id,
                         lambda: raw_profile(portal, method_id),
                         label=label or (data or {}).get("display_name") or method_id)
    # matrix_uid_map: each matrix title -> its core SampleType UID;
    # supported_matrices stays a list of titles.
    try:
        # exact titles (the catalog's Title index is a text index, where
        # "Water" matches three Sample Types). The UIDs are what a core rename
        # follows (matrix_rename.py).
        from bika.lims import api as _api
        titles = dict((b.getObject().Title(), b.UID)
                      for b in _api.get_tool("senaite_catalog_setup")(portal_type="SampleType"))
        data["matrix_uid_map"] = dict((t, titles[t]) for t in (data.get("supported_matrices") or [])
                                      if t and not isinstance(t, dict) and t in titles)
    except Exception as exc:
        logger.warning("save_profile: matrix_uid_map build failed for %s: %s",
                       method_id, exc)

    # an EIS limit row typed under a published spelling is keyed by the
    # compound at once (the worker looks a row up by keyword)
    from senaite.pfas import compound_library, compound_library_store
    conflicts = []
    compound_library.rekey_eis_rows(data, compound_library_store.library(portal), conflicts)
    for where, name, kw in conflicts:
        logger.warning("%s: %s row %s names the compound of row %s; left as typed",
                       method_id, where, name, kw)

    folder = _get_profiles_folder(portal)
    if folder is None:
        raise RuntimeError("The method profiles folder (pfas_method_profiles) is "
                           "missing: run the add-on's install step.")
    if method_id not in folder:
        folder.invokeFactory("MethodProfile", id=method_id,
                             title=data.get("display_name") or method_id)
    obj = folder[method_id]
    obj.title = data.get("display_name") or method_id
    obj.profile_json = json.dumps(data)
    obj.reindexObject()

    # the profile is the only home of the QC criteria: no AnalysisSpec copy

    # Keep the profile ⇄ core SENAITE Method bridge (method_associations) fresh
    try:
        from senaite.pfas.method_bridge import link_one
        link_one(portal, method_id, profile=data)
    except Exception as exc:
        logger.warning(
            "Profile %s saved but method bridge link failed: %s", method_id, exc
        )

    # Core Sample Types show the holding time (retention_sync.py)
    try:
        from senaite.pfas.retention_sync import sync as _sync_retention
        for line in _sync_retention(portal):
            logger.info("retention: %s", line)
    except Exception as exc:                                        # noqa: BLE001
        logger.warning("Profile %s saved but Sample Type retention not synced: %s", method_id, exc)

    # Registration follows the method: one core Analysis Profile per method x
    # matrix from the Analyte x Matrix table
    try:
        from senaite.pfas.analysis_profiles import sync_method
        for line in sync_method(portal, method_id, profile=data):
            logger.info("analysis profiles %s: %s", method_id, line)
    except Exception as exc:                                        # noqa: BLE001
        logger.warning("Profile %s saved but its Analysis Profiles were not "
                       "written: %s", method_id, exc)

    # The worker's files follow the commit. Project-linked batches carry a
    # per-batch file resolved from this profile (lab-tier criteria, project
    # specs patch): re-exported with it so none goes stale.
    from senaite.pfas import after_commit
    from senaite.pfas.resolved_criteria_store import refresh_linked_batches
    after_commit.run_once("method profiles export", export_profiles_to_file, portal)
    after_commit.run_once("linked batches %s" % method_id, refresh_linked_batches, portal, method_id)


def list_method_ids(portal):
    """Return method IDs that have been explicitly saved (beyond defaults)."""
    folder = _get_profiles_folder(portal)
    return list(folder.objectIds()) if folder is not None else []


def export_profiles_to_file(portal, path=None, extra_service=None):
    """
    Write all profiles (stored overrides + defaults for any not yet edited)
    to a JSON file so the pipeline worker can read them, and the compound
    library the services hold beside it (compound_library.json, written
    first: a profile may name a compound added with it). `extra_service` is
    a service being saved, read from the object (it may not be catalogued
    yet).
    Atomic: writes to .tmp then renames.
    """
    if path is None:
        path = PROFILES_EXPORT_PATH
    from senaite.pfas.method_engine import NOT_BACKFILLED as _NOT_BACKFILLED
    from senaite.pfas import compound_library as _cl
    from senaite.pfas import compound_library_store as _cls
    _library = _cls.library(portal, extra=extra_service)
    _cls.write_export(_library, os.path.join(os.path.dirname(path), _cl.FILE_NAME))

    # what the profiles folder holds is what exists (get_profile serves
    # nothing else), so a deleted method is not exported again; a fresh
    # install before the folder exports the seeds
    all_profiles = {}
    folder = _get_profiles_folder(portal)
    if folder is None:
        for mid, dflt in DEFAULT_PROFILES.items():
            all_profiles[mid] = copy.deepcopy(dflt)
    else:
        for method_id in folder.objectIds():
            obj = folder[method_id]
            raw = getattr(obj, "profile_json", None)
            if not raw:
                continue
            try:
                profile = json.loads(raw)
                dflt = DEFAULT_PROFILES.get(method_id, {})
                for key, default_val in dflt.items():
                    if key not in profile and key not in _NOT_BACKFILLED:
                        profile[key] = copy.deepcopy(default_val)
                _migrate_spike_levels(profile, dflt)
                all_profiles[method_id] = profile
            except (ValueError, TypeError):
                pass

    # keyword -> display-name map, from the compound library the services
    # hold (the same export the worker reads names from)
    _kw_to_display = _cl.native_names(_library)

    # The worker judges every result and QC value ROUNDED and must
    # round exactly as the certificate prints: with the ISSUED reporting-
    # template revision's format, not the live Reporting tab. Before any
    # revision is issued nothing can be published, and the live format is
    # exported as it is (report_format_rev None says so).
    from senaite.pfas.report_templates import issued_snapshot
    _snap, _rev = issued_snapshot(portal)
    for method_id, profile in all_profiles.items():
        if _snap is not None:
            profile["report_format"] = copy.deepcopy(
                (_snap.get("report_formats") or {}).get(method_id) or {})
        profile["report_format_rev"] = _rev

    # Augment each exported profile with derived fields the pipeline expects.
    for method_id, profile in all_profiles.items():
        # master_analyte_set is exported as stored (refresh_analyte_sets keeps
        # it current). engine: exported even when empty (every feature off);
        # the worker refuses an export without it rather than misread it.
        # display_analyte_set: master_analyte_set in display names.
        if not isinstance(profile.get("engine"), dict):
            profile["engine"] = {}

        profile["display_analyte_set"] = [
            _kw_to_display.get(kw, kw)
            for kw in profile.get("master_analyte_set", [])
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


def get_master_analyte_set(portal, method_id, profile=None):
    """The method's native analyte panel: the CACHE of the services' Method
    links, in the method's own order (analyte_panel; refreshed by
    refresh_analyte_sets on every service save and at start). Nothing is
    derived or filled in here: a method no service carries has an empty
    panel, and the page says so."""
    if profile is None:
        profile = get_profile(portal, method_id)
    return [kw for kw in profile.get("master_analyte_set") or [] if kw]


def linked_analytes(portal, method_id):
    """(keyword, sort_key) of every analyte service (pfas_role "analyte")
    whose core Methods include this profile's core Method; None when the
    profile has no core Method."""
    from senaite.pfas.method_bridge import get_core_method
    from bika.lims import api
    method = get_core_method(portal, method_id)
    if method is None:
        return None
    method_uid = method.UID()
    out = []
    setup_cat = api.get_tool("senaite_catalog_setup")
    for brain in setup_cat(portal_type="AnalysisService"):
        svc = brain.getObject()
        rf = svc.getField("pfas_role")
        role = (rf.get(svc) if rf is not None else "") or ""
        if role != "analyte" or not hasattr(svc, "getMethods"):
            continue
        svc_method_uids = [m.UID() for m in (svc.getMethods() or [])]
        if method_uid not in svc_method_uids:
            continue
        sort_key = None
        try:
            sort_key = svc.getSortKey()
            sort_key = float(sort_key) if sort_key not in (None, "") else None
        except (TypeError, ValueError):
            sort_key = None
        out.append((svc.getKeyword(), sort_key))
    return out


ANALYTE_LINKS_V = 1          # the profile's stored list linked once, then the links own it


def refresh_analyte_sets(portal, method_ids=None):
    """Bring every profile's analyte panel to the services' Method links
    (analyte_panel.refresh) and save what changed, recorded in configuration
    history under "Analyte links: +a, -b". A profile seen for the first
    time first links the services of its stored list to its core Method,
    then the links own it. Returns {method_id: (dropped, added)} for the
    profiles that changed."""
    from senaite.pfas import analyte_panel
    changed = {}
    for mid in (method_ids or list_method_ids(portal)):
        profile = raw_profile(portal, mid)
        if not profile:
            continue
        first = profile.get("analyte_links_v") != ANALYTE_LINKS_V
        if first:
            # the version is stamped only on links that were written: a
            # failed link raises rather than letting the empty links own the panel
            from senaite.pfas.method_bridge import link_method_analytes
            link_method_analytes(portal, [mid])
        linked = linked_analytes(portal, mid)
        if linked is None:
            logger.warning("analyte links of %s not read: no core Method", mid)
            continue
        dropped, added = analyte_panel.refresh(profile, linked)
        if first:
            profile["analyte_links_v"] = ANALYTE_LINKS_V
        if dropped or added or first:
            label = analyte_panel.label(dropped, added) if (dropped or added) else None
            save_profile(portal, mid, profile, label=label)
            if dropped or added:
                changed[mid] = (dropped, added)
                logger.info("%s: %s", mid, label)
    return changed


def get_included_analytes(portal, method_id, matrix):
    """Return the ordered list of analyte keywords reportable for method × matrix.

    Reads analyte_matrix_inclusion from the stored profile.  Analytes where the
    checkbox is True (or absent — conservative default) are included.  PFODA in
    FDA × Eggs is excluded by default (seeded carve-out).

    Downstream callers (surrogate map, recovery tiers, QC engine, report, EDD)
    must use this function rather than reading master_analyte_set directly so
    that the Method × Matrix panel is always respected.  The master set itself
    is the cache of the services' Method links (get_master_analyte_set).
    """
    profile = get_profile(portal, method_id)
    master = get_master_analyte_set(portal, method_id, profile=profile)
    inclusion = profile.get("analyte_matrix_inclusion", {})
    if not inclusion:
        return list(master)
    # matrix (a SampleType title OR UID) resolves to the title used as the
    # inclusion key; a live title resolves to itself, an unknown string falls
    # through unchanged so nothing is orphaned.
    from senaite.pfas.matrix_ref import resolve
    matrix_key = resolve(portal, matrix).get("title") or matrix
    return [kw for kw in master
            if inclusion.get(kw, {}).get(matrix_key, True)]


def seed_default_profiles(portal):
    """A shipped method with no profile gets its seed: never over a profile,
    never restoring a deleted method. Then the worker's export. Before the
    install step creates the profiles folder there is nothing to seed into;
    get_profile reads the seeds as they are until then."""
    folder = _get_profiles_folder(portal)
    if folder is not None:
        from senaite.pfas.method_delete import deleted_ids
        deleted = deleted_ids(portal)
        for method_id, data in DEFAULT_PROFILES.items():
            if method_id in folder or method_id in deleted:
                continue
            display_name = data.get("display_name") or method_id
            folder.invokeFactory("MethodProfile", id=method_id, title=display_name)
            obj = folder[method_id]
            obj.title = display_name
            obj.profile_json = json.dumps(dict(data, _seeded=True))
            obj.reindexObject()
            logger.info("Seeded method profile %s", method_id)
    try:
        export_profiles_to_file(portal)
    except Exception as exc:
        logger.warning("Profiles seeded but export failed: %s", exc)


def _register_history():
    from senaite.pfas import config_history, qc_consolidation
    # a history entry for a rule switch reverts as that rule's state (the save
    # derives the switches from the states); a change to the one Tier 1 list is refused,
    # each tier listing its own
    config_history.register_store(
        "method_profile", raw_profile,
        lambda portal, key, value: save_profile(portal, key, value),
        title=u"Method profile",
        map_changes=qc_consolidation.history_changes,
        as_saved=qc_consolidation.as_saved)


_register_history()
