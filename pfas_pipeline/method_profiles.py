"""
Method Profiles — per-method × per-analyte × per-matrix QC rule resolution.

Replaces the flat CRITERIA dict.  Every QC check resolves its limits through:

    profile = get_profile("FDA_32PFAS")
    rule = profile.qc_rules(analyte="PFOA", matrix="meat", qc_type="LFSM")
    rule.recovery_min, rule.recovery_max   # → 80.0, 120.0

Three shipped profiles:

  FDA_32PFAS — USDA/FDA 32-PFAS in Food (v10, 5/5/26) + AOAC SMPR 2023.003.
               Criteria transcribed directly from the method document
               (Sections 2024.10.1–10.3, Table 10-1, Table 9-1, 2024.8.4).

  EPA_537_1  — EPA 537.1 drinking water (EPA/600/R-20/006).
               IS areas 70–140% of most recent CCC and ±50% of ICAL average;
               surrogates 70–130%; low-level LFB 50–150%, mid/high 70–130%;
               lowest CCC 50–150%, others 70–130%; CCV every 10 samples.

  EPA_1633A  — EPA 1633A (aqueous/solid/biosolid/tissue, 40 analytes).
               EIS recovery limits vary per analyte AND per matrix
               (method Tables 6 & 8).  Defaults here are the common
               20–150% screen with per-analyte overrides; **VERIFY** against
               your purchased copy of the method before production use —
               flagged in each rule with verify_against_method=True.

Decision C (2026-06-17): All rule logic reads from the stored profile JSON
loaded at batch start via reload_from_profiles(). Python classes are
interpreters, not sources of hardcoded values. Module-level constants
_FDA_BIG4, _FDA_NO_LABELED_STD, _FDA_TIGHT_MATRICES have been removed.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

PROFILES_PATH = os.environ.get("PFAS_PROFILES_PATH", "/data/qc/method_profiles.json")


# ─────────────────────────────────────────────────────────────────────────────
# Rule containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QCRule:
    """Resolved limits for one (method, analyte, matrix, qc_type) lookup."""
    recovery_min:     Optional[float] = None   # %
    recovery_max:     Optional[float] = None   # %
    rsd_max:          Optional[float] = None   # % (repeatability RSDr)
    rpd_max:          Optional[float] = None   # % (duplicates)
    notes:            str = ""
    is_guidance_only: bool = False             # FDA surrogates: no hard req.
    verify_against_method: bool = False        # 1633A per-analyte tables


@dataclass(frozen=True)
class CalibrationRule:
    r2_min:             float = 0.99
    point_pct_dev_max:  Optional[float] = None  # ±% each point vs curve
    low_point_pct_dev_max: Optional[float] = None  # looser limit at/below MRL
    force_origin:       bool = False
    default_fit:        str = "linear"
    default_weighting:  str = "1/x"


@dataclass(frozen=True)
class CCVRule:
    recovery_min:  float
    recovery_max:  float
    frequency:     int            # one CCV per N analytical samples
    low_level_min: Optional[float] = None   # 537.1: lowest CCC 50–150%
    low_level_max: Optional[float] = None


@dataclass(frozen=True)
class ISRule:
    """Internal-standard / EIS response acceptance."""
    vs_ical_avg_min:  Optional[float] = None   # % of ICAL average
    vs_ical_avg_max:  Optional[float] = None
    vs_last_ccv_min:  Optional[float] = None   # % of most recent CCC/CCV
    vs_last_ccv_max:  Optional[float] = None
    notes: str = ""


@dataclass(frozen=True)
class ConfirmationRule:
    ion_ratio_tol_pct:    Optional[float] = None  # ± relative %
    rrt_tol_pct:          Optional[float] = None  # relative RT, % of std RT
    rt_tol_abs_min:       Optional[float] = None  # absolute minutes
    sn_min_quant:         Optional[float] = None
    sn_min_confirm:       Optional[float] = None
    single_transition_analytes: tuple = ()        # need orthogonal confirm
    confirm_pct_diff_max: Optional[float] = None  # HRMS vs MS/MS %diff
    notes: str = ""


@dataclass(frozen=True)
class SequenceRule:
    """How the injection sequence must be structured for this method."""
    opens_with_solvent_blank: bool = False
    blank_after_curve:        bool = False
    ccv_frequency:            int = 10
    closing_ccv:              bool = True
    cal_low_to_high:          bool = True


# ─────────────────────────────────────────────────────────────────────────────
# FDA display-name lists (instrument export format, MassLynx compound names).
# Moved here from constants.py so they are owned by the method layer.
#
# The ZODB store's analyte_matrix_inclusion uses KEYWORDS as dict keys
# (e.g. "PFHxS", "PFOS") while these lists use DISPLAY NAMES (e.g. "lr-PFHxS",
# "lr-PFOS") to match instrument export.  The map below bridges them.
# ─────────────────────────────────────────────────────────────────────────────

# Analyte keyword → instrument display name (only entries that differ)
_FDA_KW_TO_DISPLAY: dict = {
    "PFHxS":       "lr-PFHxS",
    "PFOS":        "lr-PFOS",
    "GenX":        "GenX (HFPO-DA)",
    "4:2FTS":      "4:2 FTS",
    "8:2FTS":      "8:2 FTS",
    "10:2FTS":     "10:2 FTS",
    "9ClPF3ONS":   "9Cl-PF3ONS",
    "11ClPF3OUdS": "11Cl-PF3OUdS",
}
# Reverse: display name → keyword (for inclusion-matrix lookup)
_FDA_DISPLAY_TO_KW: dict = {v: k for k, v in _FDA_KW_TO_DISPLAY.items()}

_FDA_DISPLAY_ANALYTES = [
    "10:2 FTS", "11Cl-PF3OUdS", "4:2 FTS", "6:2FTS", "8:2 FTS",
    "9Cl-PF3ONS", "DONA", "FOSA", "GenX (HFPO-DA)", "PFBA", "PFBS",
    "PFDA", "PFDoA", "PFDoS", "PFDS", "PFHpA", "PFHpS", "PFHxA",
    "PFHxDA", "lr-PFHxS", "PFNA", "PFNS", "PFOA", "PFODA", "lr-PFOS",
    "PFPeA", "PFPeS", "PFTeDA", "PFTrDA", "PFTrDS", "PFUDA", "PFUnDS",
    "br-PFOS", "br-PFHxS",
]

_FDA_IS_DISPLAY_NAMES = [
    "13C4-PFOA",
    "13C2,D4-10:2FTS", "13C2,D4-4:2FTS", "13C2,D4-6:2FTS", "13C2,D4-8:2FTS",
    "13C2-PFDA", "13C2-PFDoA", "13C2-PFHxDA", "13C2-PFTeDA", "13C2-PFUDA",
    "13C3-GenX (HFPO-DA)", "13C3-PFBA", "13C3-PFBS", "13C3-PFHxS", "13C3-PFPeA",
    "13C4-PFHpA", "13C5-PFHxA", "13C5-PFNA",
    "13C8-FOSA", "13C8-PFOA", "13C8-PFOS",
]

# ─────────────────────────────────────────────────────────────────────────────
# Profile data cache — populated from /data/qc/method_profiles.json at batch
# start via reload_from_profiles().  Initialized with inline defaults below so
# that the engine works before any manager has saved a profile.
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_PROFILE_CACHE = {
    "FDA_32PFAS": {
        "instrument_verification": {
            "calibration": {
                "r2_min": 0.990,
                "force_origin": False,
                "point_pct_dev_max": None,
                "low_point_pct_dev_max": None,
            },
            "ccv": {
                "frequency": 6,
                "recovery_min": 70.0,
                "recovery_max": 130.0,
                "low_level_min": None,
                "low_level_max": None,
            },
            "is_response": {
                "vs_ical_avg_min": 50.0,
                "vs_ical_avg_max": 150.0,
                "vs_last_ccv_min": None,
                "vs_last_ccv_max": None,
            },
            "confirmation": {
                "ion_ratio_tol_pct": 30.0,
                "rrt_tol_pct": 1.0,
                "rt_tol_abs_min": None,
                "sn_quan_min": 3.0,
                "sn_confirm_min": 3.0,
            },
            "sequence": {
                "cal_at_start": True,
                "ccv_frequency": 6,
                "blank_at_start": True,
                "blank_at_end": True,
            },
        },
        "qc_acceptance": {
            "MB":    {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "max_conc_x_rl": 1.0}]},
            "LRB":   {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "max_conc_x_rl": 1.0}]},
            "LCS":   {"tiers": [
                {"name": "tier1_key_tight",  "analyte_group": "key",    "matrix_scope": "tight", "recovery_min": 80.0, "recovery_max": 120.0, "rsd_max": 20.0},
                {"name": "tier2_linked",     "analyte_group": "linked", "matrix_scope": "all",   "recovery_min": 65.0, "recovery_max": 135.0, "rsd_max": 25.0},
                {"name": "tier3_no_std",     "analyte_group": "no_std", "matrix_scope": "all",   "recovery_min": 40.0, "recovery_max": 140.0, "rsd_max": 30.0},
            ]},
            "LFSM":  {"tiers": [
                {"name": "tier1_key_tight",  "analyte_group": "key",    "matrix_scope": "tight", "recovery_min": 80.0, "recovery_max": 120.0, "rsd_max": 20.0},
                {"name": "tier2_linked",     "analyte_group": "linked", "matrix_scope": "all",   "recovery_min": 65.0, "recovery_max": 135.0, "rsd_max": 25.0},
                {"name": "tier3_no_std",     "analyte_group": "no_std", "matrix_scope": "all",   "recovery_min": 40.0, "recovery_max": 140.0, "rsd_max": 30.0},
            ]},
            "LFSMD": {"tiers": [
                {"name": "tier1_key_tight",  "analyte_group": "key",    "matrix_scope": "tight", "recovery_min": 80.0, "recovery_max": 120.0, "rpd_max": 20.0},
                {"name": "tier2_linked",     "analyte_group": "linked", "matrix_scope": "all",   "recovery_min": 65.0, "recovery_max": 135.0, "rpd_max": 25.0},
                {"name": "tier3_no_std",     "analyte_group": "no_std", "matrix_scope": "all",   "recovery_min": 40.0, "recovery_max": 140.0, "rpd_max": 30.0},
            ]},
            "Dup":   {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "rpd_max": 20.0}]},
        },
        "associated_qc_types": ["MB", "LRB", "LCS", "LFSM", "LFSMD", "Dup"],
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
    },
    "EPA_537_1": {
        "instrument_verification": {
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
            "is_response": {
                "vs_ical_avg_min": 50.0,
                "vs_ical_avg_max": 150.0,
                "vs_last_ccv_min": 70.0,
                "vs_last_ccv_max": 140.0,
            },
            "confirmation": {
                "ion_ratio_tol_pct": None,
                "rrt_tol_pct": None,
                "rt_tol_abs_min": 0.05,
                "sn_quan_min": 3.0,
                "sn_confirm_min": None,
            },
            "sequence": {
                "cal_at_start": True,
                "ccv_frequency": 10,
                "blank_at_start": True,
                "blank_at_end": True,
            },
        },
        "qc_acceptance": {
            "MB":    {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "max_conc_x_rl": 1.0}]},
            "LRB":   {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "max_conc_x_rl": 1.0}]},
            "LFB":   {"tiers": [
                {"name": "low_level", "analyte_group": "all", "matrix_scope": "all", "recovery_min": 50.0, "recovery_max": 150.0, "rsd_max": None},
                {"name": "mid_high",  "analyte_group": "all", "matrix_scope": "all", "recovery_min": 70.0, "recovery_max": 130.0, "rsd_max": None},
            ]},
            "LFSM":  {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "recovery_min": 70.0, "recovery_max": 130.0, "rsd_max": None}]},
            "LFSMD": {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "recovery_min": 70.0, "recovery_max": 130.0, "rpd_max": 30.0}]},
            "Dup":   {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "rpd_max": 30.0}]},
        },
        "associated_qc_types": ["MB", "LRB", "LFB", "LFSM", "LFSMD", "Dup"],
        "matrix_factors": [],
    },
    "EPA_1633A": {
        "instrument_verification": {
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
            "is_response": {
                "vs_ical_avg_min": 50.0,
                "vs_ical_avg_max": 150.0,
                "vs_last_ccv_min": None,
                "vs_last_ccv_max": None,
            },
            "confirmation": {
                "ion_ratio_tol_pct": 50.0,
                "rrt_tol_pct": None,
                "rt_tol_abs_min": None,
                "sn_quan_min": 3.0,
                "sn_confirm_min": 1.0,
            },
            "sequence": {
                "cal_at_start": True,
                "ccv_frequency": 10,
                "blank_at_start": True,
                "blank_at_end": True,
            },
        },
        "qc_acceptance": {
            "MB":    {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "max_conc_x_rl": 1.0}]},
            "LRB":   {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "max_conc_x_rl": 1.0}]},
            "LFB":   {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "verify_against_method": True, "recovery_min": 40.0, "recovery_max": 130.0}]},
            "LFSM":  {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "verify_against_method": True, "recovery_min": 40.0, "recovery_max": 130.0}]},
            "LFSMD": {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "recovery_min": 40.0, "recovery_max": 130.0, "rpd_max": 30.0}]},
            "Dup":   {"tiers": [{"name": "default", "analyte_group": "all", "matrix_scope": "all", "rpd_max": 30.0}]},
        },
        "associated_qc_types": ["MB", "LRB", "LFB", "LFSM", "LFSMD", "Dup"],
        "eis_overrides": {
            "M2-4:2FTS":    {"recovery_min": 20.0, "recovery_max": 150.0},
            "M2-6:2FTS":    {"recovery_min": 20.0, "recovery_max": 150.0},
            "M2-8:2FTS":    {"recovery_min": 20.0, "recovery_max": 150.0},
            "d3-NMeFOSAA":  {"recovery_min": 20.0, "recovery_max": 150.0},
            "d5-NEtFOSAA":  {"recovery_min": 20.0, "recovery_max": 150.0},
            "M8FOSA":       {"recovery_min": 20.0, "recovery_max": 150.0},
        },
        "matrix_factors": [],
    },
}

_profile_data_cache = copy.deepcopy(_DEFAULT_PROFILE_CACHE)


def reload_from_profiles(profiles_path=None):
    """
    Reload _profile_data_cache from the exported method profile JSON.
    Called at the start of each batch run so changes made in the SENAITE
    Method Profile control panel take effect without a worker restart.
    Falls back to _DEFAULT_PROFILE_CACHE values for any key not in the file.
    """
    if profiles_path is None:
        profiles_path = PROFILES_PATH

    if not os.path.exists(profiles_path):
        return

    try:
        with open(profiles_path) as fh:
            all_profiles = json.load(fh)
    except (IOError, OSError, ValueError) as exc:
        logger.warning("reload_from_profiles: could not load %s: %s",
                       profiles_path, exc)
        return

    for method_id in list(_profile_data_cache.keys()):
        if method_id in all_profiles:
            data = all_profiles[method_id]
            # Phase B: normalize eis_overrides from store list format to dict.
            # Store saves [{analyte, recovery_min, recovery_max}, ...] (UI-friendly);
            # profile classes use {analyte: {recovery_min, recovery_max}} for fast lookup.
            eis = data.get("eis_overrides")
            if isinstance(eis, list):
                data = dict(data)
                data["eis_overrides"] = {
                    e["analyte"]: {
                        "recovery_min": e.get("recovery_min"),
                        "recovery_max": e.get("recovery_max"),
                    }
                    for e in eis if "analyte" in e
                }
            _profile_data_cache[method_id] = data
            logger.info("Loaded profile data for %s from %s",
                        method_id, profiles_path)
        else:
            logger.warning(
                "reload_from_profiles: %r not in %s; using defaults",
                method_id, profiles_path,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: resolve recovery tier from profile data
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_fda_tier(analyte, matrix, profile_data, qc_type="LFSM",
                      method_id="FDA_32PFAS"):
    """
    Resolve recovery tier for an FDA analyte × matrix combination.

    Reads from qc_acceptance.{qc_type}.tiers (new structure).
    Falls back to legacy recovery_tiers list for profiles not yet migrated.

    Tier resolution (new structure):
      analyte_group="no_std"  → tier3 window
      analyte_group="key" + matrix_scope="tight" → tier1 window if matrix matches
      analyte_group="linked"  → tier2 window (default)
    """
    qa = profile_data.get("qc_acceptance", {})
    qc_entry = qa.get(qc_type)
    if qc_entry is None or not qc_entry.get("enabled", True):
        return None
    tiers = qc_entry.get("tiers", [])

    # New structure: tiers have analyte_group and matrix_scope keys
    if tiers and "analyte_group" in tiers[0]:
        # Membership comes from the analyte reference table and the method's
        # own tight_matrices — not from lists hardcoded here. The hardcoded
        # sets disagreed with the reference table on DONA and PFHpS, so both
        # were judged at 65-135% when the method allows 40-140%.
        from .analyte_alias import no_labeled_names, key_analyte_names
        no_std = no_labeled_names()
        key = key_analyte_names()
        # Canonical titles, plus the profile's own alias list. Substring
        # matching had quietly narrowed this: "deer muscle" meets neither
        # "Meat / Muscle" nor any other title, so a key analyte there dropped
        # from tier 1 to tier 2. Aliases are lab-editable rather than a word
        # list buried in code.
        aliases = profile_data.get("matrix_aliases") or {}
        m = matrix.lower().strip()
        tight = set()
        for title in (profile_data.get("tight_matrices") or []):
            tight.add(title.lower().strip())
            for alias in (aliases.get(title) or []):
                tight.add(alias.lower().strip())

        is_no_std = analyte in no_std
        is_key = analyte in key
        is_tight = m in tight

        for tier in tiers:
            ag = tier.get("analyte_group", "all")
            ms = tier.get("matrix_scope", "all")
            if ag == "no_std" and is_no_std:
                return _tier_rule(
                    tier, "No matched labeled standard (Table 10-1 footnote a)",
                    method_id, analyte, matrix, qc_type)
            if ag == "key" and ms == "tight" and is_key and is_tight:
                return _tier_rule(
                    tier,
                    "PFOS/PFOA/PFHxS/PFNA in eggs/meat/seafood "
                    "(Table 10-1 tier 1)",
                    method_id, analyte, matrix, qc_type)
        # Fall through to the "linked" / default tier
        for tier in tiers:
            ag = tier.get("analyte_group", "all")
            if ag in ("linked", "all"):
                return _tier_rule(
                    tier,
                    "Table 10-1 tier 2 (other matrices / other analytes)",
                    method_id, analyte, matrix, qc_type)
        raise UnconfiguredCriterion(
            "No tier matches {0} / {1} / {2} / {3}: the configured tiers cover "
            "neither this analyte group nor a default. Add a tier with "
            "analyte_group 'all' in Method Profiles -> QC Types -> {3}.".format(
                method_id, analyte, matrix or "(no matrix)", qc_type))

    # The legacy `recovery_tiers` branch that stood here was retired by
    # migrate_profile_structure and could only ever mask a missing config with
    # a second, divergent copy of the tier logic -- the §1.3 duplication that
    # this session traced ten defects to. A profile that has not been migrated
    # now says so instead of quietly judging against stale numbers.
    raise UnconfiguredCriterion(
        "{0} has no qc_acceptance.{1}.tiers. This profile predates "
        "migrate_profile_structure; run the migration so its acceptance "
        "criteria are read from the structure the engine enforces.".format(
            method_id, qc_type))


# ─────────────────────────────────────────────────────────────────────────────
# Profile base
# ─────────────────────────────────────────────────────────────────────────────

class MethodProfile:
    """Base class.  Subclasses override the rule methods."""
    method_id: str = ""
    description: str = ""

    def qc_rules(self, analyte, matrix="", qc_type="LFSM"):
        raise NotImplementedError

    def calibration_rule(self, analyte=""):
        raise NotImplementedError

    def ccv_rule(self):
        raise NotImplementedError

    def is_rule(self):
        raise NotImplementedError

    def confirmation_rule(self):
        raise NotImplementedError

    def sequence_rule(self):
        raise NotImplementedError

    def sample_factor(self, matrix):
        return None

    def _profile_data(self):
        return _profile_data_cache.get(self.method_id, {})

    def _iv(self):
        """Return instrument_verification block, with old-key fallback."""
        p = self._profile_data()
        iv = p.get("instrument_verification")
        if iv is not None:
            return iv
        # Backward compat: old profiles have flat keys at top level
        return p

    def qc_acceptance_rule(self, qc_code, analyte="", matrix=""):
        """
        Return a QCRule for a specific QC type from qc_acceptance.
        Returns None when the QC type is not associated or is disabled.
        """
        qa = self._profile_data().get("qc_acceptance", {})
        entry = qa.get(qc_code)
        if entry is None or not entry.get("enabled", True):
            return None
        tiers = entry.get("tiers", [])
        if not tiers:
            return None
        # Return the first (most specific) matching tier; callers that need
        # full tiered resolution should call qc_rules() with the analyte+matrix.
        t = tiers[0]
        return QCRule(
            recovery_min=t.get("recovery_min"),
            recovery_max=t.get("recovery_max"),
            rsd_max=t.get("rsd_max"),
            rpd_max=t.get("rpd_max"),
            verify_against_method=bool(t.get("verify_against_method", False)),
        )

    def resolve_spike_ppt(self, qc_type, level_label, matrix=None):
        """Return configured spike ppt for qc_type+level+matrix, or None if not set.

        spike_levels may be in old flat format {LFB:[...], LFSM:[...]} or
        new per-matrix format {matrix: {LFB:[...], LFSM:[...]}}.
        """
        spike_levels = self._profile_data().get("spike_levels", {})
        # Detect old flat format
        if "LFB" in spike_levels or "LFSM" in spike_levels:
            levels = spike_levels.get(qc_type, [])
        elif matrix and matrix in spike_levels:
            levels = spike_levels[matrix].get(qc_type, [])
        else:
            # New format but matrix not matched; fall back to first available matrix
            first = next(iter(spike_levels.values()), {})
            levels = first.get(qc_type, []) if isinstance(first, dict) else []
        for entry in levels:
            if entry.get("label", "").strip().lower() == level_label.strip().lower():
                ppt = entry.get("ppt")
                return float(ppt) if ppt is not None else None
        return None


# ─────────────────────────────────────────────────────────────────────────────
# FDA 32-PFAS in Food  (from the uploaded method document)
# ─────────────────────────────────────────────────────────────────────────────

class FDA32PFASProfile(MethodProfile):
    method_id = "FDA_32PFAS"
    description = ("USDA/FDA 32-PFAS in Food v10 (5/5/26) + AOAC SMPR "
                   "2023.003; LC-MS/MS isotope dilution")

    def qc_rules(self, analyte, matrix="", qc_type="LFSM"):
        if qc_type in ("SUR", "surrogate"):
            return _method_text_rule(
                self._profile_data(), self.method_id,
                "Surrogate recovery is guidance only (FDA §2024.10.1(5))",
                50.0, 150.0, is_guidance_only=True)
        if qc_type in ("Dup", "duplicate"):
            return _resolve_fda_tier(analyte, matrix,
                                     self._profile_data(), qc_type="Dup",
                                     method_id=self.method_id)
        return _resolve_fda_tier(analyte, matrix,
                                 self._profile_data(), qc_type=qc_type,
                                 method_id=self.method_id)

    def calibration_rule(self, analyte=""):
        cal = _calibration(self._profile_data(), self.method_id)
        fit = ("mean_response_factor"
               if analyte.startswith(("M", "13C")) else "linear")
        return CalibrationRule(
            r2_min=float(_required(cal, "r2_min", self.method_id,
                                   "calibration", " -> Calibration & CCV")),
            point_pct_dev_max=cal.get("point_pct_dev_max"),
            low_point_pct_dev_max=cal.get("low_point_pct_dev_max"),
            force_origin=bool(cal.get("force_origin", False)),
            default_fit=fit,
            default_weighting="none" if fit != "linear" else "1/x",
        )

    def ccv_rule(self):
        return _ccv_rule(self._iv().get("ccv", {}), self.method_id)

    def is_rule(self):
        is_ = _is_section(self._profile_data(), self.method_id)
        req = lambda k: _required(is_, k, self.method_id, "is_response",
                                  " -> Calibration & CCV -> IS Response")
        return ISRule(
            vs_ical_avg_min=req("vs_ical_avg_min"),
            vs_ical_avg_max=req("vs_ical_avg_max"),
            vs_last_ccv_min=is_.get("vs_last_ccv_min"),
            vs_last_ccv_max=is_.get("vs_last_ccv_max"),
            notes="Lab SOP screen (Excel legacy); FDA method sets no numeric IS-area limit",
        )

    def confirmation_rule(self):
        conf = _confirmation(self._profile_data(), self.method_id)
        # single_transition_analytes and confirm_pct_diff_max are METHOD TEXT
        # (FDA: PFBA/PFPeA have one usable transition and positives need
        # orthogonal LC-HRMS confirmation within 20%), so they keep their cited
        # values rather than refusing -- but they are overridable, which they
        # were not.
        return ConfirmationRule(
            ion_ratio_tol_pct=_conf_value(conf, "ion_ratio_tol_pct", self.method_id),
            rrt_tol_pct=_conf_value(conf, "rrt_tol_pct", self.method_id),
            rt_tol_abs_min=conf.get("rt_tol_abs_min"),
            sn_min_quant=_conf_value(conf, "sn_quan_min", self.method_id),
            sn_min_confirm=_conf_value(conf, "sn_confirm_min", self.method_id),
            single_transition_analytes=tuple(
                conf.get("single_transition_analytes") or ("PFBA", "PFPeA")),
            confirm_pct_diff_max=conf.get("confirm_pct_diff_max", 20.0),
            notes="PFBA/PFPeA positives require LC-HRMS confirmation; "
                  "cholic acid (TDCA/TCDCA/TUDCA) interference transitions "
                  "monitored for PFOS (§2024.8.5)",
        )

    def sequence_rule(self):
        seq = self._iv().get("sequence", {})
        ccv = self._iv().get("ccv", {})
        return SequenceRule(
            opens_with_solvent_blank=True,
            blank_after_curve=True,
            ccv_frequency=int(seq.get("ccv_frequency",
                                      ccv.get("frequency", 6))),
            closing_ccv=True,
        )

    def sample_factor(self, matrix):
        # Matrix factors are keyed by the core SampleType title (D55). Match the
        # sample's matrix EXACTLY first; fall back to legacy substring matching
        # for any old-format entries that predate the core-type tie.
        m = (matrix or "").lower().strip()
        factors = self._profile_data().get("matrix_factors", [])
        for entry in factors:
            if (entry.get("matrix", "") or "").lower().strip() == m:
                return float(entry["factor"])
        for entry in factors:
            key = (entry.get("matrix", "") or "").lower().strip()
            if key and key in m:
                return float(entry["factor"])
        return None


# ─────────────────────────────────────────────────────────────────────────────
# EPA 537.1  (drinking water)
# ─────────────────────────────────────────────────────────────────────────────

class EPA537Profile(MethodProfile):
    method_id = "EPA_537_1"
    description = "EPA 537.1 PFAS in drinking water (EPA/600/R-20/006)"

    def qc_rules(self, analyte, matrix="", qc_type="LFSM"):
        qa = self._profile_data().get("qc_acceptance", {})
        if qc_type in ("SUR", "surrogate"):
            return _method_text_rule(
                self._profile_data(), self.method_id,
                "§9.3.5 surrogates 70–130%", 70.0, 130.0)
        entry = qa.get(qc_type)
        if entry is None or not entry.get("enabled", True):
            return None
        tiers = entry.get("tiers", [])
        if not tiers:
            raise UnconfiguredCriterion(
                "{0} has no tiers configured for {1}. Set them in Method "
                "Profiles -> QC Types -> {1}, or disable that QC type.".format(
                    self.method_id, qc_type))
        t = tiers[0]
        rule = _tier_rule(t, t.get("description", ""), self.method_id,
                          analyte, matrix, qc_type)
        return QCRule(
            recovery_min=rule.recovery_min,
            recovery_max=rule.recovery_max,
            rsd_max=rule.rsd_max,
            rpd_max=rule.rpd_max,
            notes=rule.notes,
        )

    def calibration_rule(self, analyte=""):
        cal = _calibration(self._profile_data(), self.method_id)
        req = lambda k: _required(cal, k, self.method_id, "calibration",
                                  " -> Calibration & CCV")
        return CalibrationRule(
            r2_min=float(req("r2_min")),
            point_pct_dev_max=req("point_pct_dev_max"),
            low_point_pct_dev_max=req("low_point_pct_dev_max"),
            force_origin=bool(cal.get("force_origin", True)),
        )

    def ccv_rule(self):
        return _ccv_rule(self._iv().get("ccv", {}), self.method_id,
                         default_frequency=10,
                         low_level_default=(50.0, 150.0))

    def is_rule(self):
        is_ = _is_section(self._profile_data(), self.method_id)
        req = lambda k: _required(is_, k, self.method_id, "is_response",
                                  " -> Calibration & CCV -> IS Response")
        return ISRule(
            vs_ical_avg_min=req("vs_ical_avg_min"),
            vs_ical_avg_max=req("vs_ical_avg_max"),
            vs_last_ccv_min=req("vs_last_ccv_min"),
            vs_last_ccv_max=req("vs_last_ccv_max"),
            notes="Both conditions must hold (§9.3.4); on failure "
                  "re-inject a second aliquot in a fresh vial",
        )

    def confirmation_rule(self):
        conf = _confirmation(self._profile_data(), self.method_id)
        return ConfirmationRule(
            rt_tol_abs_min=_conf_value(conf, "rt_tol_abs_min", self.method_id),
            sn_min_quant=conf.get("sn_quan_min"),
            notes="RT within ±0.05 min of expected; "
                  "no qual-ion ratio criterion in 537.1",
        )

    def sequence_rule(self):
        seq = self._iv().get("sequence", {})
        ccv = self._iv().get("ccv", {})
        return SequenceRule(
            ccv_frequency=int(seq.get("ccv_frequency",
                                      ccv.get("frequency", 10))),
            closing_ccv=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# EPA 1633A  (aqueous / solid / biosolid / tissue)
# ─────────────────────────────────────────────────────────────────────────────

class UnconfiguredCriterion(Exception):
    """No acceptance criterion is configured for this combination.

    Raised instead of substituting a plausible default. The resolver used to
    end with an unconditional QCRule(65.0, 135.0) and carried ~59 inline
    fallbacks of the form tier.get("recovery_min", 40.0), so a profile that was
    silent produced a believable limit and nothing said so. A criterion that
    nothing configured must not be quietly met -- that is the same failure as
    the CCV window, inverted: not a wrong number displayed, but a wrong
    criterion silently satisfied.

    The trade is deliberate and was chosen explicitly: this hard-blocks a run
    against a profile that is not fully populated. The message names what to
    configure and where.
    """


# Keys that describe WHICH rows a tier applies to, rather than what it judges.
_TIER_STRUCTURAL_KEYS = frozenset([
    "name", "analyte_group", "matrix_scope", "description",
    "verify_against_method", "tier", "key_analytes", "no_std_analytes",
    "tight_matrices",
])


def _tier_rule(tier, notes, method_id, analyte, matrix, qc_type):
    """Build a QCRule from a configured tier, or refuse.

    A tier is configured when it carries AT LEAST ONE criterion. Which one
    depends on the QC type and it is not this function's business to say:
    a duplicate is judged by RPD and legitimately has no recovery window, so
    demanding recovery limits everywhere refuses a correctly configured Dup
    tier. What must never happen is a tier that specifies nothing at all
    yielding a verdict anyway.

    Downstream already skips a check whose criterion is None
    (recovery_check_profiled returns early on recovery_min is None), so an
    absent criterion means "this QC type is not judged that way", while an
    empty tier now means "nobody configured this" and says so.
    """
    low = tier.get("recovery_min")
    high = tier.get("recovery_max")
    rsd = tier.get("rsd_max")
    rpd = tier.get("rpd_max")
    # "Configured" is the absence of nothing, not the presence of one of a
    # list I happened to think of. Enumerating recovery/RSD/RPD refused every
    # method blank, whose criterion is max_conc_x_rl -- a blank is judged
    # against the reporting limit, not against a recovery window. Anything
    # beyond the structural keys is a criterion.
    criteria = set(tier) - _TIER_STRUCTURAL_KEYS
    if not criteria:
        raise UnconfiguredCriterion(
            "No acceptance criteria configured for {0} / {1} / {2} / {3}: "
            "tier {4!r} specifies no recovery window, RSD or RPD limit. "
            "Set one in Method Profiles -> QC Types -> {3}, or disable that "
            "QC type.".format(
                method_id, analyte, matrix or "(no matrix)", qc_type,
                tier.get("name") or tier.get("analyte_group") or "default"))
    # A half-configured recovery window is a different failure: someone meant
    # to set a limit and left one end blank, which would judge against an open
    # interval.
    if (low is None) != (high is None):
        raise UnconfiguredCriterion(
            "Incomplete recovery window for {0} / {1} / {2} / {3}: "
            "only {4} is set. Set both ends, or neither.".format(
                method_id, analyte, matrix or "(no matrix)", qc_type,
                "recovery_min" if low is not None else "recovery_max"))
    return QCRule(
        None if low is None else float(low),
        None if high is None else float(high),
        rsd_max=rsd,
        rpd_max=rpd,
        notes=notes,
    )


def _method_text_rule(profile_data, method_id, citation, low, high, **kw):
    """A limit the METHOD TEXT states, overridable by the profile.

    Distinct from the substituted defaults this session removed. Those were
    invented when configuration was silent; these are published values with a
    citation, and §8 says never to fabricate a regulatory value -- so refusing
    would be wrong here. What was wrong was that they could not be overridden
    at all: a lab whose SOP is tighter than the method floor had nowhere to say
    so. `qc_acceptance.SUR` now wins when it is configured.
    """
    entry = (profile_data.get("qc_acceptance") or {}).get("SUR") or {}
    tiers = entry.get("tiers") or []
    if entry.get("enabled", True) and tiers:
        rule = _tier_rule(tiers[0], "Surrogate recovery (lab-configured)",
                          method_id, "", "", "SUR")
        if rule.recovery_min is not None:
            return QCRule(rule.recovery_min, rule.recovery_max,
                          rsd_max=rule.rsd_max, rpd_max=rule.rpd_max,
                          notes=rule.notes, **kw)
    return QCRule(low, high, notes=citation, **kw)


def _ccv_rule(ccv, method_id, default_frequency=6, low_level_default=(None, None)):
    """CCV limits from the profile, or refuse.

    The CCV window is the original instance of this whole class of defect: the
    editor saved 72-128% while every run was judged against a nested 70-130%,
    and nothing said so. Substituting 70/130 when the profile is silent is the
    same failure with the UI half removed.
    """
    low, high = ccv.get("recovery_min"), ccv.get("recovery_max")
    if low is None or high is None:
        raise UnconfiguredCriterion(
            "{0} has no CCV recovery window configured. Set it in Method "
            "Profiles -> Calibration & CCV.".format(method_id))
    return CCVRule(
        recovery_min=float(low),
        recovery_max=float(high),
        # Frequency and the low-level window are not verdicts on a result:
        # frequency governs sequence layout, and an absent low-level window
        # means the method sets no separate limit at the MRL.
        frequency=int(ccv.get("frequency", default_frequency)),
        low_level_min=ccv.get("low_level_min", low_level_default[0]),
        low_level_max=ccv.get("low_level_max", low_level_default[1]),
    )


def _iv_section(profile_data, method_id, section, aliases=(), where=""):
    """A configured instrument_verification section, or refuse.

    Generalised from the confirmation-only version: calibration (r2_min,
    per-point %dev), IS response (vs ICAL average, vs last CCV) and
    confirmation all carried the same inline fallbacks, and all three decide a
    verdict. r2_min in particular gates whether a calibration is acceptable at
    all.
    """
    iv = profile_data.get("instrument_verification") or {}
    data = iv.get(section)
    for alias in aliases:
        if not data:
            data = iv.get(alias)
    if not isinstance(data, dict) or not data:
        raise UnconfiguredCriterion(
            "{0} has no instrument_verification.{1} section. Configure it in "
            "Method Profiles{2}.".format(method_id, section, where))
    return data


def _required(section_data, key, method_id, section, where=""):
    """One criterion. Absent refuses; an explicit None means not applicable."""
    if key not in section_data:
        raise UnconfiguredCriterion(
            "{0} has no '{1}' configured under instrument_verification.{2}. "
            "Set it in Method Profiles{3}, or clear the field to record that "
            "this method has no such criterion.".format(
                method_id, key, section, where))
    return section_data[key]


def _confirmation(profile_data, method_id):
    """The configured chromatographic-confirmation section, or refuse.

    Same silent-substitution shape as the recovery limits: `conf.get(
    "ion_ratio_tol_pct", 30.0)` supplied a plausible window when the profile
    said nothing, and an ion-ratio check against a window nobody chose passes
    or fails on a number the lab never set.

    A key PRESENT with value None is not the same as a key ABSENT. EPA 537.1
    stores `ion_ratio_tol_pct: null` deliberately -- the method has no qual-ion
    ratio criterion at all -- and the editor always writes every key, so an
    absent key means the section was never configured. That is the same
    distinction the Dup and MB tiers turned on: a criterion the method does not
    use is configured, not missing.
    """
    return _iv_section(profile_data, method_id, "confirmation",
                       where=" -> Calibration & CCV -> Chromatographic "
                             "Confirmation")


def _conf_value(conf, key, method_id):
    return _required(conf, key, method_id, "confirmation",
                     " -> Calibration & CCV")


def _calibration(profile_data, method_id):
    return _iv_section(profile_data, method_id, "calibration",
                       where=" -> Calibration & CCV")


def _is_section(profile_data, method_id):
    return _iv_section(profile_data, method_id, "is_response", ("is",),
                       where=" -> Calibration & CCV -> IS Response")


def _1633a_matrix_class(matrix: str) -> str:
    """Map a 1633A matrix name to the EIS table class used in eis_matrix_overrides."""
    m = matrix.lower().strip()
    if "leachate" in m:
        return "leachate"
    if "tissue" in m:
        return "tissue"
    if "biosolid" in m:
        return "biosolid"
    if any(x in m for x in ("solid", "sediment", "soil")):
        return "solid"
    return "aqueous"


class EPA1633AProfile(MethodProfile):
    method_id = "EPA_1633A"
    description = ("EPA 1633A — 40 PFAS in aqueous, solid, biosolid, "
                   "tissue (Jan 2024 / 2024 update)")

    def qc_rules(self, analyte, matrix="", qc_type="LFSM"):
        profile = self._profile_data()
        eis_overrides = profile.get("eis_overrides", {})
        eis_matrix = profile.get("eis_matrix_overrides", {})

        # EIS/NIS surrogate recovery — still per-analyte × matrix
        if qc_type in ("EIS", "SUR", "surrogate"):
            qa = profile.get("qc_acceptance", {})
            lfsm_entry = qa.get("LFSM", {})
            tiers = lfsm_entry.get("tiers") or []
            if not tiers:
                raise UnconfiguredCriterion(
                    "{0} has no qc_acceptance.LFSM.tiers to base EIS recovery "
                    "on. Configure it in Method Profiles -> QC Types -> "
                    "LFSM.".format(self.method_id))
            # Refuse rather than substituting 40/130. This is the method whose
            # limits are explicitly placeholders pending a purchased-method
            # check, so it is the last place a silent default belongs.
            base = _tier_rule(tiers[0], "", self.method_id, analyte, matrix,
                              "EIS")
            if base.recovery_min is None:
                raise UnconfiguredCriterion(
                    "{0} / {1}: EIS recovery needs a recovery window on "
                    "qc_acceptance.LFSM, which specifies none.".format(
                        self.method_id, analyte))
            default_lo = float(base.recovery_min)
            default_hi = float(base.recovery_max)
            override = eis_overrides.get(analyte, {})
            lo = float(override.get("recovery_min", default_lo))
            hi = float(override.get("recovery_max", default_hi))
            if matrix:
                mat_class = _1633a_matrix_class(matrix)
                if mat_class != "aqueous":
                    mat_override = eis_matrix.get(mat_class, {}).get(analyte)
                    if mat_override:
                        lo = float(mat_override.get("recovery_min", lo))
                        hi = float(mat_override.get("recovery_max", hi))
            return QCRule(lo, hi,
                          verify_against_method=True,
                          notes="EIS limits per-analyte x matrix class "
                                "(1633A Tables 6/8, EPA 820-R-24-007) — VERIFY "
                                "against purchased method copy")

        qa = profile.get("qc_acceptance", {})
        # OPR (ongoing precision & recovery) maps to LFB code in the pool
        mapped = "LFB" if qc_type in ("OPR", "IPR") else qc_type
        entry = qa.get(mapped)
        if entry is None or not entry.get("enabled", True):
            return None
        tiers = entry.get("tiers", [])
        if not tiers:
            raise UnconfiguredCriterion(
                "{0} has no tiers configured for {1}. Set them in Method "
                "Profiles -> QC Types -> {1}, or disable that QC type.".format(
                    self.method_id, mapped))
        t = tiers[0]
        rule = _tier_rule(
            t, t.get("description",
                     "1633A per-analyte (verify against method)"),
            self.method_id, analyte, matrix, mapped)
        return QCRule(
            recovery_min=rule.recovery_min,
            recovery_max=rule.recovery_max,
            rsd_max=rule.rsd_max,
            rpd_max=rule.rpd_max,
            verify_against_method=bool(t.get("verify_against_method", False)),
            notes=rule.notes,
        )

    def calibration_rule(self, analyte=""):
        cal = _calibration(self._profile_data(), self.method_id)
        req = lambda k: _required(cal, k, self.method_id, "calibration",
                                  " -> Calibration & CCV")
        return CalibrationRule(
            r2_min=float(req("r2_min")),
            point_pct_dev_max=req("point_pct_dev_max"),
            low_point_pct_dev_max=req("low_point_pct_dev_max"),
            default_fit="linear",
            default_weighting="1/x",
        )

    def ccv_rule(self):
        return _ccv_rule(self._iv().get("ccv", {}), self.method_id,
                         default_frequency=10)

    def is_rule(self):
        is_ = _is_section(self._profile_data(), self.method_id)
        req = lambda k: _required(is_, k, self.method_id, "is_response",
                                  " -> Calibration & CCV -> IS Response")
        return ISRule(
            vs_ical_avg_min=req("vs_ical_avg_min"),
            vs_ical_avg_max=req("vs_ical_avg_max"),
            notes="NIS screen; EIS uses per-analyte limits",
        )

    def confirmation_rule(self):
        conf = _confirmation(self._profile_data(), self.method_id)
        return ConfirmationRule(
            ion_ratio_tol_pct=_conf_value(conf, "ion_ratio_tol_pct", self.method_id),
            sn_min_quant=_conf_value(conf, "sn_quan_min", self.method_id),
            sn_min_confirm=_conf_value(conf, "sn_confirm_min", self.method_id),
            notes="Ion-ratio window wider in 1633A (50–150% of expected typical)",
        )

    def sequence_rule(self):
        seq = self._iv().get("sequence", {})
        ccv = self._iv().get("ccv", {})
        return SequenceRule(
            ccv_frequency=int(seq.get("ccv_frequency",
                                      ccv.get("frequency", 10))),
            closing_ccv=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_PROFILES = {
    "FDA_32PFAS": FDA32PFASProfile(),
    "EPA_537_1":  EPA537Profile(),
    "EPA_1633A":  EPA1633AProfile(),
}

# Aliases accepted from batch metadata / injection names
_ALIASES = {
    "FDA": "FDA_32PFAS", "FDA32": "FDA_32PFAS", "C-010.04": "FDA_32PFAS",
    "537": "EPA_537_1", "537.1": "EPA_537_1", "EPA537": "EPA_537_1",
    "1633": "EPA_1633A", "1633A": "EPA_1633A", "EPA1633": "EPA_1633A",
}


def get_profile(method):
    key = method.strip().upper().replace(" ", "")
    key = _ALIASES.get(key, key)
    for pid, prof in _PROFILES.items():
        if pid.upper() == key:
            return prof
    raise KeyError(
        "Unknown method profile {!r}; available: {} (aliases: {})".format(
            method, sorted(_PROFILES), sorted(_ALIASES)))


def available_profiles():
    return {pid: p.description for pid, p in _PROFILES.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Analyte / IS list helpers — replace constants.ANALYTES / INTERNAL_STANDARDS
# ─────────────────────────────────────────────────────────────────────────────

def get_analyte_list(method_id: str = "FDA_32PFAS") -> list:
    """Display-name ordered analyte list for method_id.

    After a JSON profile load the cache may carry a ``display_analyte_set``
    field exported by the store; otherwise falls back to the inline defaults.
    """
    data = _profile_data_cache.get(method_id, {})
    explicit = data.get("display_analyte_set")
    if explicit is not None:
        return list(explicit)
    if method_id == "FDA_32PFAS":
        return list(_FDA_DISPLAY_ANALYTES)
    return []


def get_reporting_unit(method_id: str, matrix: str) -> str:
    """The unit results are reported in for this method x matrix, from the
    profile's unit_map (Animal Feed -> ng/kg, Milk -> ng/mL)."""
    data = _profile_data_cache.get(method_id, {}) or {}
    return (data.get("unit_map") or {}).get(matrix, "") or ""


def get_matrix_factor(method_id: str, matrix: str) -> "float | None":
    """The method's configured multiplier for this matrix, or None.

    Converts the concentration the instrument reports in the EXTRACT to the
    concentration reported for the SAMPLE. It is per matrix because the
    sample-size-to-final-volume ratio is, and it is configured in the Method
    Profile rather than derived, because that ratio is the lab's SOP.

    ``MethodProfile.sample_factor`` has resolved this correctly all along and
    had no caller: the factor was configured, resolvable, and never applied.
    """
    try:
        profile = get_profile(method_id)
    except KeyError:
        return None
    try:
        return profile.sample_factor(matrix)
    except Exception:
        return None


def get_non_iso_set(method_id: str = "FDA_32PFAS") -> frozenset:
    """Return the frozenset of analyte display names that have no labeled std.

    Reads ``no_std_analytes`` from tier 3 of the method's recovery_tiers.
    Falls back to tier 3 of the inline FDA default if the profile isn't loaded.
    """
    # Membership is a property of the ANALYTE, not of a QC profile, so it is
    # read from the analyte reference table. This used to read the retired
    # `recovery_tiers` key — retired by migrate_profile_structure, hence always
    # empty — so the N.C. qualifier never fired from this path at all.
    from .analyte_alias import no_labeled_names
    names = no_labeled_names()
    if not names:
        return frozenset()
    # Scope to the method's own panel so 1633A-only analytes do not leak in.
    panel = set(get_analyte_list(method_id) or [])
    return frozenset(names & panel) if panel else frozenset(names)


def get_is_list(method_id: str = "FDA_32PFAS") -> list:
    """Display-name IS / surrogate list for method_id.

    After a JSON profile load the cache may carry ``internal_standards``
    exported by the store; otherwise falls back to the inline FDA defaults.
    """
    data = _profile_data_cache.get(method_id, {})
    explicit = data.get("internal_standards")
    if explicit is not None:
        return list(explicit)
    if method_id == "FDA_32PFAS":
        return list(_FDA_IS_DISPLAY_NAMES)
    return []


def get_included_display_analytes(method_id: str, matrix: str) -> list:
    """Return display-name analyte list filtered by the Method × Matrix panel.

    Reads ``analyte_matrix_inclusion`` from the profile cache (keyword-keyed
    dict exported from the ZODB store).  If the cache has no inclusion data
    yet (profile JSON not loaded), falls back to the full analyte list so
    the pipeline continues to work before first configuration.

    Keyword keys that differ from display names are handled via
    _FDA_DISPLAY_TO_KW / _FDA_KW_TO_DISPLAY.  Default: included (True) when a
    keyword is not found in the inclusion dict (conservative — never silently
    drop an analyte due to missing config data).
    """
    data = _profile_data_cache.get(method_id, {})
    inclusion = data.get("analyte_matrix_inclusion")
    full_list = get_analyte_list(method_id)
    if not inclusion:
        return full_list

    result = []
    for display_name in full_list:
        keyword = _FDA_DISPLAY_TO_KW.get(display_name, display_name)
        matrix_map = inclusion.get(keyword, {})
        if matrix_map.get(matrix, True):
            result.append(display_name)
    return result


def get_isomer_summation(method_id: str = "FDA_32PFAS") -> list:
    """Return the active isomer summation pairs for method_id.

    Each pair is ``{"linear": ..., "branched": ..., "reported": ..., "enabled": bool}``.
    Only enabled pairs are returned.
    """
    pairs = _profile_data_cache.get(method_id, {}).get("isomer_summation", [])
    return [p for p in pairs if p.get("enabled", True)]


def get_surrogate_map(method_id: str = "FDA_32PFAS") -> dict:
    """Which labeled surrogate quantifies each native analyte, per METHOD.

    §3 makes this the method's own relation ("SURROGATE MAP native ->
    quantifying IS ... QUANTIFICATION link"), and the profile has always stored
    it. Nothing read it: the analysis took the relationship from the instrument
    file's `linked_is` column instead, falling back to a global alias table
    that is not method-scoped. So a lab editing the drag-and-drop surrogate map
    changed nothing, and the method's notation never reached the analysis.

    Keyed by BOTH the display name and the keyword, because the profile stores
    whichever spelling the editor was given and the instrument exports display
    names -- the mismatch that silently N.D.'d six analytes earlier.
    """
    out = {}
    rows = _profile_data_cache.get(method_id, {}).get("surrogate_map", []) or []
    try:
        from .analyte_alias import keyword_for, NAME_TO_KEYWORD
    except ImportError:
        keyword_for, NAME_TO_KEYWORD = None, {}
    # Both directions. The profile stores keywords ("8:2FTS") while the
    # instrument exports display names ("8:2 FTS"); keying one way only left
    # the spaced spellings unresolved -- the same gap that silently reported
    # six analytes as N.D.
    by_keyword = {}
    for name, kw in (NAME_TO_KEYWORD or {}).items():
        by_keyword.setdefault(kw, []).append(name)
    for row in rows:
        analyte = (row.get("analyte") or "").strip()
        surrogate = (row.get("surrogate_is") or "").strip()
        if not analyte or not surrogate:
            continue
        out[analyte] = surrogate
        kw = keyword_for(analyte) if keyword_for else analyte
        if kw:
            out[kw] = surrogate
        for alias in by_keyword.get(kw, ()):
            out[alias] = surrogate
    return out


def get_surrogate_is_chain(method_id: str = "FDA_32PFAS") -> dict:
    """Which injection IS each labeled SURROGATE is itself quantified against.

    The second half of the chain: native -> surrogate (get_surrogate_map) ->
    injection IS. Under FDA every surrogate quantifies against M4PFOA. This is
    what distinguishes a surrogate, which is diluted with the sample, from the
    injection IS, which is added after the dilution and must not be scaled.
    """
    return dict(_profile_data_cache.get(
        method_id, {}).get("surrogate_is_chain", {}) or {})


def get_salt_factors(method_id: str = "FDA_32PFAS") -> dict:
    """Per-analyte salt (counter-ion) correction, keyed by analyte.

    §3 lists SALT FACTOR as a core method relation: "per analyte x method
    (decimal < 1, from CoA)". The Method Profile editor has always collected it,
    complete with the reference-standard lot it came from -- and nothing applied
    it. The string "salt" did not appear anywhere in this package. FDA_32PFAS
    carries 0.9636 for PFOA against lot MXA-2453-A; every PFOA result issued so
    far was 3.6% high.

    `salt_adjustment_factors` is the authoritative key -- it is what the editor
    writes and where the data is. `extraction_corrections.salt_factors` is a
    seeded empty list read only by the QC Rules pane, and
    `qc_rules.salt_factors` was deprecated by D53; neither is consulted here.
    """
    rows = _profile_data_cache.get(
        method_id, {}).get("salt_adjustment_factors", []) or []
    try:
        from .analyte_alias import keyword_for, NAME_TO_KEYWORD
    except ImportError:
        keyword_for, NAME_TO_KEYWORD = None, {}
    by_keyword = {}
    for name, kw in (NAME_TO_KEYWORD or {}).items():
        by_keyword.setdefault(kw, []).append(name)

    out = {}
    for row in rows:
        analyte = (row.get("analyte") or "").strip()
        try:
            factor = float(row.get("factor"))
        except (TypeError, ValueError):
            continue
        # 1.0 is "no correction"; storing it is how the editor records that a
        # lot was linked without a numeric adjustment.
        if not analyte or factor == 1.0 or factor <= 0:
            continue
        out[analyte] = factor
        kw = keyword_for(analyte) if keyword_for else analyte
        if kw:
            out[kw] = factor
        for alias in by_keyword.get(kw, ()):
            out[alias] = factor

    # An isomer pair is quantified from the same salt-form standard as the
    # analyte it sums to, but the instrument reports it as lr-/br- rows. Naming
    # only the reported analyte would leave both components uncorrected and the
    # sum along with them.
    for pair in get_isomer_summation(method_id):
        factor = out.get(pair.get("reported"))
        if not factor:
            continue
        for part in ("linear", "branched"):
            name = pair.get(part)
            if name:
                out[name] = factor
    return out


# Load profile data immediately if the export already exists
reload_from_profiles()
