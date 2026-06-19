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
        "recovery_tiers": [
            {
                "tier": 1,
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
                "recovery_min": 65.0,
                "recovery_max": 135.0,
                "rsd_max": 25.0,
            },
            {
                "tier": 3,
                "no_std_analytes": [
                    "9Cl-PF3ONS", "11Cl-PF3OUdS", "PFDoS", "PFDS",
                    "PFNS", "PFODA", "PFPeS", "PFTrDA", "PFTrDS", "PFUnDS",
                ],
                "recovery_min": 40.0,
                "recovery_max": 140.0,
                "rsd_max": 30.0,
            },
        ],
        "ccv": {
            "frequency": 6,
            "recovery_min": 70.0,
            "recovery_max": 130.0,
            "low_level_min": None,
            "low_level_max": None,
        },
        "calibration": {
            # FDA method document specifies 0.990; stored profile may use 0.995
            # (lab SOP legacy) — see QUESTIONS.md Q-005.
            "r2_min": 0.990,
            "force_origin": False,
            "point_pct_dev_max": None,
            "low_point_pct_dev_max": None,
        },
        "confirmation": {
            "ion_ratio_tol_pct": 30.0,
            "rrt_tol_pct": 1.0,
            "rt_tol_abs_min": None,
            "sn_quan_min": 3.0,
            "sn_confirm_min": 3.0,
        },
        "is": {
            "vs_ical_avg_min": 50.0,
            "vs_ical_avg_max": 150.0,
            "vs_last_ccv_min": None,
            "vs_last_ccv_max": None,
        },
        "duplicate": {"rpd_max": 20.0},
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
        "recovery_tiers": [
            {
                "tier": 1,
                "description": "Low-level LFB (at or below MRL)",
                "recovery_min": 50.0,
                "recovery_max": 150.0,
                "rsd_max": None,
            },
            {
                "tier": 2,
                "description": "Mid/high LFB and LFSM",
                "recovery_min": 70.0,
                "recovery_max": 130.0,
                "rsd_max": None,
            },
        ],
        "ccv": {
            "frequency": 10,
            "recovery_min": 70.0,
            "recovery_max": 130.0,
            "low_level_min": 50.0,
            "low_level_max": 150.0,
        },
        "calibration": {
            "r2_min": 0.990,
            "force_origin": True,
            "point_pct_dev_max": 30.0,
            "low_point_pct_dev_max": 50.0,
        },
        "confirmation": {
            "ion_ratio_tol_pct": None,
            "rrt_tol_pct": None,
            "rt_tol_abs_min": 0.05,
            "sn_quan_min": 3.0,
            "sn_confirm_min": None,
        },
        "is": {
            "vs_ical_avg_min": 50.0,
            "vs_ical_avg_max": 150.0,
            "vs_last_ccv_min": 70.0,
            "vs_last_ccv_max": 140.0,
        },
        "duplicate": {"rpd_max": 30.0},
        "matrix_factors": [],
    },
    "EPA_1633A": {
        "recovery_tiers": [
            {
                "tier": 1,
                "recovery_min": 40.0,
                "recovery_max": 130.0,
                "rsd_max": None,
            },
        ],
        "eis_overrides": {
            "M2-4:2FTS":    {"recovery_min": 20.0, "recovery_max": 150.0},
            "M2-6:2FTS":    {"recovery_min": 20.0, "recovery_max": 150.0},
            "M2-8:2FTS":    {"recovery_min": 20.0, "recovery_max": 150.0},
            "d3-NMeFOSAA":  {"recovery_min": 20.0, "recovery_max": 150.0},
            "d5-NEtFOSAA":  {"recovery_min": 20.0, "recovery_max": 150.0},
            "M8FOSA":       {"recovery_min": 20.0, "recovery_max": 150.0},
        },
        "ccv": {
            "frequency": 10,
            "recovery_min": 70.0,
            "recovery_max": 130.0,
            "low_level_min": None,
            "low_level_max": None,
        },
        "calibration": {
            "r2_min": 0.990,
            "force_origin": False,
            "point_pct_dev_max": 30.0,
            "low_point_pct_dev_max": 50.0,
        },
        "confirmation": {
            "ion_ratio_tol_pct": 50.0,
            "rrt_tol_pct": None,
            "rt_tol_abs_min": None,
            "sn_quan_min": 3.0,
            "sn_confirm_min": 1.0,
        },
        "is": {
            "vs_ical_avg_min": 50.0,
            "vs_ical_avg_max": 150.0,
            "vs_last_ccv_min": None,
            "vs_last_ccv_max": None,
        },
        "duplicate": {"rpd_max": 30.0},
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

def _resolve_fda_tier(analyte, matrix, profile_data):
    """
    Resolve recovery tier for an FDA analyte × matrix combination from
    the profile's recovery_tiers list.  Returns a QCRule.

    Tier resolution order:
      1. Tier 3: analyte in no_std_analytes list → 40–140% + RSDr≤30%
      2. Tier 1: analyte in key_analytes AND matrix contains a tight-matrix term
      3. Tier 2: everything else
    """
    tiers = profile_data.get("recovery_tiers", [])

    tier3_analytes = set()
    tier1_analytes = set()
    tight_matrices = set()
    t1 = {"recovery_min": 80.0, "recovery_max": 120.0, "rsd_max": 20.0}
    t2 = {"recovery_min": 65.0, "recovery_max": 135.0, "rsd_max": 25.0}
    t3 = {"recovery_min": 40.0, "recovery_max": 140.0, "rsd_max": 30.0}

    for tier in tiers:
        n = tier.get("tier")
        if n == 1:
            tier1_analytes = set(tier.get("key_analytes", []))
            tight_matrices = set(tier.get("tight_matrices", []))
            t1 = tier
        elif n == 2:
            t2 = tier
        elif n == 3:
            tier3_analytes = set(tier.get("no_std_analytes", []))
            t3 = tier

    m = matrix.lower().strip()

    if analyte in tier3_analytes:
        return QCRule(
            t3.get("recovery_min", 40.0),
            t3.get("recovery_max", 140.0),
            rsd_max=t3.get("rsd_max", 30.0),
            notes="No matched labeled standard (Table 10-1 footnote a)",
        )
    if analyte in tier1_analytes and any(t in m for t in tight_matrices):
        return QCRule(
            t1.get("recovery_min", 80.0),
            t1.get("recovery_max", 120.0),
            rsd_max=t1.get("rsd_max", 20.0),
            notes="PFOS/PFOA/PFHxS/PFNA in eggs/meat/seafood (Table 10-1 tier 1)",
        )
    return QCRule(
        t2.get("recovery_min", 65.0),
        t2.get("recovery_max", 135.0),
        rsd_max=t2.get("rsd_max", 25.0),
        notes="Table 10-1 tier 2 (other matrices / other analytes)",
    )


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
        profile = self._profile_data()

        if qc_type in ("SUR", "surrogate"):
            return QCRule(50.0, 150.0,
                          notes="Surrogate recovery is guidance only "
                                "(FDA §2024.10.1(5))",
                          is_guidance_only=True)

        if qc_type in ("Dup", "duplicate"):
            rpd = profile.get("duplicate", {}).get("rpd_max", 20.0)
            return QCRule(rpd_max=rpd,
                          notes="Regulatory duplicate %diff < 20% "
                                "(FDA §2024.10.3)")

        return _resolve_fda_tier(analyte, matrix, profile)

    def calibration_rule(self, analyte=""):
        cal = self._profile_data().get("calibration", {})
        fit = ("mean_response_factor"
               if analyte.startswith(("M", "13C")) else "linear")
        return CalibrationRule(
            r2_min=float(cal.get("r2_min", 0.990)),
            point_pct_dev_max=cal.get("point_pct_dev_max"),
            low_point_pct_dev_max=cal.get("low_point_pct_dev_max"),
            force_origin=bool(cal.get("force_origin", False)),
            default_fit=fit,
            default_weighting="none" if fit != "linear" else "1/x",
        )

    def ccv_rule(self):
        ccv = self._profile_data().get("ccv", {})
        return CCVRule(
            recovery_min=float(ccv.get("recovery_min", 70.0)),
            recovery_max=float(ccv.get("recovery_max", 130.0)),
            frequency=int(ccv.get("frequency", 6)),
            low_level_min=ccv.get("low_level_min"),
            low_level_max=ccv.get("low_level_max"),
        )

    def is_rule(self):
        is_ = self._profile_data().get("is", {})
        return ISRule(
            vs_ical_avg_min=is_.get("vs_ical_avg_min", 50.0),
            vs_ical_avg_max=is_.get("vs_ical_avg_max", 150.0),
            vs_last_ccv_min=is_.get("vs_last_ccv_min"),
            vs_last_ccv_max=is_.get("vs_last_ccv_max"),
            notes="Lab SOP screen (Excel legacy); FDA method sets no numeric IS-area limit",
        )

    def confirmation_rule(self):
        conf = self._profile_data().get("confirmation", {})
        return ConfirmationRule(
            ion_ratio_tol_pct=conf.get("ion_ratio_tol_pct", 30.0),
            rrt_tol_pct=conf.get("rrt_tol_pct", 1.0),
            rt_tol_abs_min=conf.get("rt_tol_abs_min"),
            sn_min_quant=conf.get("sn_quan_min", 3.0),
            sn_min_confirm=conf.get("sn_confirm_min", 3.0),
            single_transition_analytes=("PFBA", "PFPeA"),
            confirm_pct_diff_max=20.0,
            notes="PFBA/PFPeA positives require LC-HRMS confirmation; "
                  "cholic acid (TDCA/TCDCA/TUDCA) interference transitions "
                  "monitored for PFOS (§2024.8.5)",
        )

    def sequence_rule(self):
        ccv = self._profile_data().get("ccv", {})
        return SequenceRule(
            opens_with_solvent_blank=True,
            blank_after_curve=True,
            ccv_frequency=int(ccv.get("frequency", 6)),
            closing_ccv=True,
        )

    def sample_factor(self, matrix):
        m = matrix.lower().strip()
        for entry in self._profile_data().get("matrix_factors", []):
            if entry.get("matrix", "") in m:
                return float(entry["factor"])
        return None


# ─────────────────────────────────────────────────────────────────────────────
# EPA 537.1  (drinking water)
# ─────────────────────────────────────────────────────────────────────────────

class EPA537Profile(MethodProfile):
    method_id = "EPA_537_1"
    description = "EPA 537.1 PFAS in drinking water (EPA/600/R-20/006)"

    def qc_rules(self, analyte, matrix="", qc_type="LFSM"):
        profile = self._profile_data()
        tiers = profile.get("recovery_tiers", [])
        # Default to mid/high tier limits if no tiers loaded
        lo, hi = 70.0, 130.0
        lo_low, hi_low = 50.0, 150.0
        for tier in tiers:
            if tier.get("tier") == 2:
                lo = float(tier.get("recovery_min", 70.0))
                hi = float(tier.get("recovery_max", 130.0))
            elif tier.get("tier") == 1:
                lo_low = float(tier.get("recovery_min", 50.0))
                hi_low = float(tier.get("recovery_max", 150.0))

        if qc_type in ("SUR", "surrogate"):
            return QCRule(lo, hi, notes="§9.3.5 surrogates 70–130%")
        if qc_type in ("LFB", "LCS"):
            return QCRule(lo, hi,
                          notes="Mid/high LFB 70–130%; use 50–150% when "
                                "fortified at/below MRL (§9.3.3)")
        if qc_type in ("Dup", "duplicate", "LFSMD"):
            rpd = profile.get("duplicate", {}).get("rpd_max", 30.0)
            return QCRule(lo, hi, rpd_max=rpd,
                          notes="LFSMD: recoveries 70–130%, RPD ≤30% "
                                "(lab-typical; method defers to §9.3.6)")
        return QCRule(lo, hi,
                      notes="LFSM 70–130% (50–150% near MRL) §9.3.6")

    def calibration_rule(self, analyte=""):
        cal = self._profile_data().get("calibration", {})
        return CalibrationRule(
            r2_min=float(cal.get("r2_min", 0.990)),
            point_pct_dev_max=cal.get("point_pct_dev_max", 30.0),
            low_point_pct_dev_max=cal.get("low_point_pct_dev_max", 50.0),
            force_origin=bool(cal.get("force_origin", True)),
        )

    def ccv_rule(self):
        ccv = self._profile_data().get("ccv", {})
        return CCVRule(
            recovery_min=float(ccv.get("recovery_min", 70.0)),
            recovery_max=float(ccv.get("recovery_max", 130.0)),
            frequency=int(ccv.get("frequency", 10)),
            low_level_min=ccv.get("low_level_min", 50.0),
            low_level_max=ccv.get("low_level_max", 150.0),
        )

    def is_rule(self):
        is_ = self._profile_data().get("is", {})
        return ISRule(
            vs_ical_avg_min=is_.get("vs_ical_avg_min", 50.0),
            vs_ical_avg_max=is_.get("vs_ical_avg_max", 150.0),
            vs_last_ccv_min=is_.get("vs_last_ccv_min", 70.0),
            vs_last_ccv_max=is_.get("vs_last_ccv_max", 140.0),
            notes="Both conditions must hold (§9.3.4); on failure "
                  "re-inject a second aliquot in a fresh vial",
        )

    def confirmation_rule(self):
        conf = self._profile_data().get("confirmation", {})
        return ConfirmationRule(
            rt_tol_abs_min=conf.get("rt_tol_abs_min", 0.05),
            notes="RT within ±0.05 min of expected; "
                  "no qual-ion ratio criterion in 537.1",
        )

    def sequence_rule(self):
        ccv = self._profile_data().get("ccv", {})
        return SequenceRule(
            ccv_frequency=int(ccv.get("frequency", 10)),
            closing_ccv=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# EPA 1633A  (aqueous / solid / biosolid / tissue)
# ─────────────────────────────────────────────────────────────────────────────

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
        tiers = profile.get("recovery_tiers", [])
        eis_overrides = profile.get("eis_overrides", {})
        eis_matrix = profile.get("eis_matrix_overrides", {})

        default_lo, default_hi = 40.0, 130.0
        for tier in tiers:
            if tier.get("tier") == 1:
                default_lo = float(tier.get("recovery_min", 40.0))
                default_hi = float(tier.get("recovery_max", 130.0))

        if qc_type in ("EIS", "SUR", "surrogate"):
            # Aqueous default from eis_overrides
            override = eis_overrides.get(analyte, {})
            lo = float(override.get("recovery_min", default_lo))
            hi = float(override.get("recovery_max", default_hi))
            # Apply matrix-class-specific override when available (Tables 6/8)
            if matrix:
                mat_class = _1633a_matrix_class(matrix)
                if mat_class != "aqueous":
                    mat_override = eis_matrix.get(mat_class, {}).get(analyte)
                    if mat_override:
                        lo = float(mat_override.get("recovery_min", lo))
                        hi = float(mat_override.get("recovery_max", hi))
            return QCRule(lo, hi,
                          notes="EIS limits per-analyte x matrix class "
                                "(1633A Tables 6/8, EPA 820-R-24-007)")
        if qc_type in ("OPR", "LCS", "LFB"):
            return QCRule(70.0, 130.0, verify_against_method=True,
                          notes="OPR/IPR limits are per-analyte "
                                "(1633A Table 5 et seq.) — verify")
        if qc_type in ("Dup", "duplicate", "LFSMD", "MSD"):
            rpd = profile.get("duplicate", {}).get("rpd_max", 30.0)
            return QCRule(rpd_max=rpd,
                          notes="Lab duplicate/MSD RPD typical ≤30%")
        return QCRule(70.0, 130.0, verify_against_method=True,
                      notes="MS recovery per-analyte (1633A) — verify")

    def calibration_rule(self, analyte=""):
        cal = self._profile_data().get("calibration", {})
        return CalibrationRule(
            r2_min=float(cal.get("r2_min", 0.990)),
            point_pct_dev_max=cal.get("point_pct_dev_max", 30.0),
            low_point_pct_dev_max=cal.get("low_point_pct_dev_max", 50.0),
            default_fit="linear",
            default_weighting="1/x",
        )

    def ccv_rule(self):
        ccv = self._profile_data().get("ccv", {})
        return CCVRule(
            recovery_min=float(ccv.get("recovery_min", 70.0)),
            recovery_max=float(ccv.get("recovery_max", 130.0)),
            frequency=int(ccv.get("frequency", 10)),
        )

    def is_rule(self):
        is_ = self._profile_data().get("is", {})
        return ISRule(
            vs_ical_avg_min=is_.get("vs_ical_avg_min", 50.0),
            vs_ical_avg_max=is_.get("vs_ical_avg_max", 150.0),
            notes="NIS screen; EIS uses per-analyte limits",
        )

    def confirmation_rule(self):
        conf = self._profile_data().get("confirmation", {})
        return ConfirmationRule(
            ion_ratio_tol_pct=conf.get("ion_ratio_tol_pct", 50.0),
            sn_min_quant=conf.get("sn_quan_min", 3.0),
            sn_min_confirm=conf.get("sn_confirm_min", 1.0),
            notes="Ion-ratio window wider in 1633A (50–150% of expected typical)",
        )

    def sequence_rule(self):
        ccv = self._profile_data().get("ccv", {})
        return SequenceRule(
            ccv_frequency=int(ccv.get("frequency", 10)),
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


def get_non_iso_set(method_id: str = "FDA_32PFAS") -> frozenset:
    """Return the frozenset of analyte display names that have no labeled std.

    Reads ``no_std_analytes`` from tier 3 of the method's recovery_tiers.
    Falls back to tier 3 of the inline FDA default if the profile isn't loaded.
    """
    tiers = _profile_data_cache.get(method_id, {}).get("recovery_tiers", [])
    if not tiers and method_id == "FDA_32PFAS":
        tiers = _DEFAULT_PROFILE_CACHE["FDA_32PFAS"]["recovery_tiers"]
    for tier in tiers:
        if tier.get("tier") == 3:
            return frozenset(tier.get("no_std_analytes", []))
    return frozenset()


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


# Load profile data immediately if the export already exists
reload_from_profiles()
