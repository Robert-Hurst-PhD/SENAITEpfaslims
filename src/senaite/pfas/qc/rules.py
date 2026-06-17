# -*- coding: utf-8 -*-
"""
QC Rules Store.

Provides configurable acceptance criteria for every QC type.
Rules are stored as JSON at DEFAULT_RULES_PATH (same directory as the QC
SQLite DB so both the Zope browser and the Python-3 pipeline can read/write).

A Manager user edits rules via @@pfas-qc-rules.  The engine loads them at
run time so no code deploy is needed to tighten a window or add a new method.

Defaults are based on FDA PFAS in Food and Feed draft method criteria.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

logger = logging.getLogger("senaite.pfas.qc.rules")

DEFAULT_RULES_PATH = os.environ.get(
    "PFAS_QC_RULES", "/data/qc/qc_rules.json"
)

# ── Chart type constants ──────────────────────────────────────────────────────
CHART_LJ       = "levey_jennings"   # Levey-Jennings + Westgard
CHART_THRESHOLD = "threshold"       # flat threshold line only (blanks)

# ── Method identifiers ────────────────────────────────────────────────────────
METHODS = [
    {"id": "FDA_32PFAS", "label": "FDA 32-PFAS"},
    {"id": "EPA_537_1",  "label": "EPA 537.1"},
    {"id": "EPA_1633A",  "label": "EPA 1633A"},
]

# ── Method × Matrix → concentration unit map ─────────────────────────────────
# Defines the reported concentration unit for each method × matrix combination.
# Used for QC type field unit labels and result reporting.
# Confirmed by lab (2026-06-13): FDA_32PFAS solid matrices → ng/kg.
METHOD_MATRIX_UNIT_MAP = {
    "EPA_537_1": {
        "Drinking Water": "ng/L",
        "Ground Water":   "ng/L",
        "Surface Water":  "ng/L",
        "Aqueous":        "ng/L",
        "default":        "ng/L",
    },
    "EPA_1633A": {
        "Aqueous":        "ng/L",
        "Surface Water":  "ng/L",
        "Drinking Water": "ng/L",
        "Solid":          "ng/g",   # dry weight
        "Sediment":       "ng/g",   # dry weight
        "Soil":           "ng/g",   # dry weight
        "Tissue":         "ng/g",   # wet weight
        "Fish Tissue":    "ng/g",   # wet weight
        "default":        "ng/L",
    },
    "FDA_32PFAS": {
        "Meat":           "ng/kg",  # wet weight
        "Fish":           "ng/kg",  # wet weight
        "Fish Tissue":    "ng/kg",  # wet weight
        "Egg":            "ng/kg",  # wet weight
        "Feed":           "ng/kg",  # wet weight
        "Milk":           "ng/mL",
        "default":        "ng/kg",
    },
}


def get_unit_for_context(method, matrix):
    """Return concentration unit for the given method+matrix combination."""
    method_map = METHOD_MATRIX_UNIT_MAP.get(method, {})
    return method_map.get(matrix) or method_map.get("default") or ""

# ── Full library of evaluable QC rules ────────────────────────────────────────
# Each entry: key, label, and the limit parameter(s) to show in the detail editor.
RULE_LIBRARY = [
    {"key": "is_response",         "label": "IS Response",
     "params": [{"name": "is_response_pct", "label": "Max deviation (%)", "type": "number", "default": 50.0}]},
    {"key": "rrt_deviation",       "label": "RRT / RT Deviation",
     "params": [
         {"name": "rt_tolerance_pct", "label": "RT tolerance (% relative)", "type": "number", "default": 5.0},
         {"name": "rt_tolerance_min", "label": "RT tolerance (min absolute)", "type": "number", "default": 0.10},
     ]},
    {"key": "ion_ratio",           "label": "Ion Ratio",
     "params": [
         {"name": "qq_ratio_matching_pct", "label": "Isotopically matched (%)", "type": "number", "default": 20.0},
         {"name": "qq_ratio_key_pct",      "label": "Key analytes (%)",          "type": "number", "default": 25.0},
         {"name": "qq_ratio_non_iso_pct",  "label": "Non-iso-linked (%)",        "type": "number", "default": 30.0},
     ]},
    {"key": "cal_r2",              "label": u"Calibration r²",
     "params": [{"name": "cal_r2_min", "label": u"Minimum r²", "type": "number", "default": 0.995}]},
    {"key": "ccv_recovery",        "label": "CCV Recovery",
     "params": [
         {"name": "ccv_recovery_min", "label": "Min recovery (%)", "type": "number", "default": 70.0},
         {"name": "ccv_recovery_max", "label": "Max recovery (%)", "type": "number", "default": 130.0},
     ]},
    {"key": "ccv_frequency",       "label": "CCV Frequency",
     "params": [{"name": "ccv_frequency_n", "label": "CCV every N injections", "type": "integer", "default": 10}]},
    {"key": "lcs_recovery",        "label": "LCS Recovery",
     "params": [
         {"name": "lcs_recovery_min", "label": "Min recovery (%)", "type": "number", "default": 60.0},
         {"name": "lcs_recovery_max", "label": "Max recovery (%)", "type": "number", "default": 140.0},
     ]},
    {"key": "lfsm_recovery",       "label": "LFSM Recovery",
     "params": [
         {"name": "lfsm_recovery_min", "label": "Min recovery (%)", "type": "number", "default": 40.0},
         {"name": "lfsm_recovery_max", "label": "Max recovery (%)", "type": "number", "default": 140.0},
     ]},
    {"key": "lfsmd_rpd",           "label": "LFSMD RPD",
     "params": [{"name": "lfsmd_rpd_max", "label": "Max RPD (%)", "type": "number", "default": 30.0}]},
    {"key": "mb_blank",            "label": "MB / LRB Blank",
     "params": [{"name": "mb_max_conc", "label": "Max concentration (MDL multiplier)", "type": "number", "default": 3.0}]},
    {"key": "sn_min",              "label": "S/N Minimum",
     "params": [
         {"name": "sn_min",      "label": "Min S/N for detection",     "type": "number", "default": 3.0},
         {"name": "sn_quan_min", "label": "Min S/N for quantitation",  "type": "number", "default": 10.0},
     ]},
    {"key": "surrogate_recovery",  "label": "Surrogate Recovery",
     "params": [
         {"name": "surrogate_recovery_min", "label": "Min recovery (%)", "type": "number", "default": 50.0},
         {"name": "surrogate_recovery_max", "label": "Max recovery (%)", "type": "number", "default": 150.0},
     ]},
    {"key": "blank_contamination", "label": "Blank Contamination",
     "params": [{"name": "blank_max_conc", "label": "Max conc (ng/mL, 0 = none)", "type": "number", "default": 0.0}]},
    {"key": "mdl_check",           "label": "MDL Check",
     "params": [{"name": "mdl_n_min", "label": "Min replicate count", "type": "integer", "default": 7}]},
]

# ── Default toggle state per method ──────────────────────────────────────────
# True = rule is evaluated; False = rule is skipped.
DEFAULT_METHOD_RULE_TOGGLES = {
    "FDA_32PFAS": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "lcs_recovery": True, "lfsm_recovery": True, "lfsmd_rpd": True,
        "mb_blank": True, "sn_min": False,
        "surrogate_recovery": True, "blank_contamination": True,
        "mdl_check": False,
    },
    "EPA_537_1": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "lcs_recovery": True, "lfsm_recovery": True, "lfsmd_rpd": True,
        "mb_blank": True, "sn_min": False,
        "surrogate_recovery": True, "blank_contamination": False,
        "mdl_check": True,
    },
    "EPA_1633A": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "lcs_recovery": True, "lfsm_recovery": True, "lfsmd_rpd": True,
        "mb_blank": True, "sn_min": True,
        "surrogate_recovery": True, "blank_contamination": True,
        "mdl_check": True,
    },
}

# ── Default method-specific limit overrides ───────────────────────────────────
# These override global/qc_type defaults on a per-method basis.
# Empty by default; lab fills them in via the UI.
DEFAULT_METHOD_OVERRIDES = {
    "FDA_32PFAS": {},
    "EPA_537_1":  {},
    "EPA_1633A":  {},
}

# ── Mapping: RULE_LIBRARY key → engine review-check name(s) ──────────────────
# Used by the pipeline worker to gate auto_evaluate() blocks.
# Empty list = rule is UI-only; the toggle affects whether the check appears in
# the review queue but there is no automated engine flag-check for it yet.
LIBRARY_KEY_TO_ENGINE_CHECKS = {
    "is_response":         ["is_response"],
    "rrt_deviation":       ["rt_deviation"],
    "ion_ratio":           ["ion_ratio"],
    "cal_r2":              ["r_squared"],
    "ccv_recovery":        ["ccv_pct_dev"],
    "ccv_frequency":       [],   # UI only — CCV interval in InjectionSequenceBuilder
    "lcs_recovery":        ["recovery"],
    "lfsm_recovery":       ["lfsm_recovery"],
    "lfsmd_rpd":           ["lfsmd_rpd"],
    "mb_blank":            [],   # UI only — threshold set in blank_contamination check
    "sn_min":              ["signal_to_noise"],
    "surrogate_recovery":  [],   # UI only — surrogate check not yet auto-evaluated
    "blank_contamination": ["blank_contamination"],
    "mdl_check":           [],   # UI only — MDL assessment not auto-evaluated
}

# ── Default QC rule set ───────────────────────────────────────────────────────
# Values are editable through the browser UI; these serve as built-in fallback.

DEFAULT_RULES = {
    "version": 1,
    "updated_by": "",
    "updated_at": "",

    # Per-method rule toggle state.  True = rule is evaluated; False = skipped.
    # These are proposed starting defaults (UI-editable); see DECISIONS.md.
    "method_rule_toggles": DEFAULT_METHOD_RULE_TOGGLES,

    # Per-method parameter overrides.  Sparse: only keys that differ from global
    # are stored.  Missing keys fall through to global/qc_type defaults.
    "method_overrides": DEFAULT_METHOD_OVERRIDES,

    # Global instrument-level criteria (not per-QC-type)
    "global": {
        "cal_r2_min":           0.995,
        "is_response_pct":      50.0,   # ± % of batch mean before IS flag
        "rt_tolerance_min":     0.10,   # ± absolute minutes
        "rt_tolerance_pct":     5.0,    # ± % relative (wider of the two wins)
        "sn_min":               3.0,    # minimum S/N for detection
        "sn_quan_min":          10.0,   # minimum S/N for quantitation
        "rpd_max":              30.0,   # max RPD for duplicates
        "qq_ratio_matching_pct": 20.0,  # isotopically-linked analytes
        "qq_ratio_key_pct":      25.0,  # key analytes (PFOS/PFNA/PFHxS/PFOA)
        "qq_ratio_non_iso_pct":  30.0,  # non-isotopically linked analytes
        "cal_pct_deviation_default": 25.0,
        "cal_pct_deviation_tight":   20.0,
        "cal_pct_deviation_loose":   30.0,
    },

    # ── Salt adjustment factors ────────────────────────────────────────────────
    # Applied to reported concentrations: C_true = C_instrument × salt_factor
    #
    # These correct for the volume of water displaced during salting-out
    # (QuEChERS / LLE with MgSO4 + NaCl addition) in the extraction procedure.
    # Each matrix entry can also carry analyte-class overrides when partitioning
    # behavior differs significantly by chain length or functional group.
    #
    # Method reference: FDA PFAS in Food and Feed (draft), Section 7 (extraction)
    # Defaults of 1.00 are conservative starting points; confirm with spike
    # recovery data from your specific extraction volumes and sample mass.
    #
    # Formula (solid matrix):
    #   C_reported (ng/g ww) = C_instrument (ng/mL)
    #                          × (V_final_extract_mL / m_sample_g)
    #                          × salt_factor
    # Formula (aqueous matrix):
    #   C_reported (ng/L) = C_instrument (ng/mL) × 1000 × salt_factor
    "salt_factors": {
        # Matrix key must match the normalised matrix from parse_sample_description
        "milk": {
            "default":  1.00,
            "note":     "FDA §7: 5g sample, 10 mL ACN, 4g MgSO4 + 1g NaCl; confirm with lab spike data",
            "pfca_c4_c8":  1.00,   # short-chain PFCA
            "pfca_c9_plus": 1.00,  # long-chain PFCA (may concentrate in fat)
            "pfsa":        1.00,
            "fts":         1.00,
        },
        "egg": {
            "default":  1.00,
            "note":     "FDA §7: 2g homogenised egg, 10 mL ACN + salt; confirm with lab data",
            "pfca_c4_c8":  1.00,
            "pfca_c9_plus": 1.00,
            "pfsa":        1.00,
            "fts":         1.00,
        },
        "meat": {
            "default":  1.00,
            "note":     "FDA §7: 2g homogenised meat, 10 mL ACN + salt",
            "pfca_c4_c8":  1.00,
            "pfca_c9_plus": 1.00,
            "pfsa":        1.00,
            "fts":         1.00,
        },
        "fish": {
            "default":  1.00,
            "note":     "FDA §7 fish tissue; high-fat matrices may need fat-correction",
            "pfca_c4_c8":  1.00,
            "pfca_c9_plus": 1.00,
            "pfsa":        1.00,
            "fts":         1.00,
        },
        "feed": {
            "default":  1.00,
            "note":     "Animal feed; dry-weight correction may be needed separately",
        },
        "water": {
            "default":  1.00,
            "note":     "Aqueous; no salt partitioning correction needed",
        },
        "soil": {
            "default":  1.00,
            "note":     "Soil/sediment; dry-weight correction applied separately",
        },
        "other": {
            "default":  1.00,
            "note":     "Unknown matrix — no correction applied until confirmed",
        },
    },

    # Per-QC-type criteria.  Keys MUST match the shortcodes used in the CSV
    # (CAL, ICV, CCV, MB, MxB, LRB, LCS, LFSM, LFSMD).
    "qc_types": {
        "CAL": {
            "label":      "Calibration Standard",
            "chart_type": CHART_LJ,
            "pct_deviation_max": 25.0,
        },
        "ICV": {
            "label":      "Initial Calibration Verification",
            "chart_type": CHART_LJ,
            "pct_deviation_max": 20.0,
        },
        "CCV": {
            "label":      "Continuing Calibration Verification",
            "chart_type": CHART_LJ,
            "pct_deviation_max": 20.0,
            "pct_deviation_warn": 10.0,
        },
        "LCS": {
            "label":      "Laboratory Control Sample",
            "chart_type": CHART_LJ,
            "recovery_min":       40.0,
            "recovery_max":       140.0,
            "recovery_warn_low":  65.0,
            "recovery_warn_high": 135.0,
        },
        "MB": {
            "label":            "Method Blank",
            "chart_type":       CHART_THRESHOLD,
            "threshold":        None,   # null = use per-analyte reporting limit
            "threshold_units":  "ng/mL",
            "note": "Fail if result >= reporting limit; flag if > 1/2 RL",
        },
        "MxB": {
            "label":            "Matrix Blank",
            "chart_type":       CHART_THRESHOLD,
            "threshold":        None,
            "threshold_units":  "ng/mL",
        },
        "LRB": {
            "label":            "Lab Reagent Blank",
            "chart_type":       CHART_THRESHOLD,
            "threshold":        None,
            "threshold_units":  "ng/mL",
        },
        "LFSM": {
            "label":      "Lab Fortified Sample Matrix",
            "chart_type": CHART_LJ,
            "recovery_min":            40.0,
            "recovery_max":            140.0,
            # Tighter window for key analytes (PFOS/PFNA/PFHxS/PFOA) in
            # bio-matrices (Egg, Muscle, Fish, Meat)
            "recovery_min_key_matrix": 65.0,
            "recovery_max_key_matrix": 135.0,
        },
        "LFSMD": {
            "label":      "Lab Fortified Sample Matrix Duplicate",
            "chart_type": CHART_LJ,
            "recovery_min": 40.0,
            "recovery_max": 140.0,
            "rpd_max":      30.0,
        },
        "Dup": {
            "label":      "Sample Duplicate",
            "chart_type": CHART_LJ,
            "rpd_max":    30.0,
        },
    },
}

# ── File-based store ──────────────────────────────────────────────────────────

class QCRulesStore(object):
    """Load and persist QC rules from/to JSON on the shared QC volume."""

    def __init__(self, path=None):
        self.path = path or DEFAULT_RULES_PATH

    def _ensure_dir(self):
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d)
            except OSError:
                pass

    def load(self):
        """Return merged rules dict (defaults overridden by file if present)."""
        import copy
        rules = copy.deepcopy(DEFAULT_RULES)
        if not os.path.exists(self.path):
            return rules
        try:
            with open(self.path, "r") as fh:
                saved = json.load(fh)
            # Deep-merge saved values over defaults
            rules["version"] = saved.get("version", rules["version"])
            rules["updated_by"] = saved.get("updated_by", "")
            rules["updated_at"] = saved.get("updated_at", "")
            # Global overrides
            if "global" in saved:
                rules["global"].update(saved["global"])
            # Per-QC-type overrides
            if "qc_types" in saved:
                for qtype, overrides in saved["qc_types"].items():
                    if qtype not in rules["qc_types"]:
                        rules["qc_types"][qtype] = {}
                    rules["qc_types"][qtype].update(overrides)
            # Salt factor overrides (deep-merge per matrix)
            if "salt_factors" in saved:
                for matrix, overrides in saved["salt_factors"].items():
                    if matrix not in rules["salt_factors"]:
                        rules["salt_factors"][matrix] = {}
                    rules["salt_factors"][matrix].update(overrides)
            # Per-method rule toggle overrides (deep-merge per method)
            if "method_rule_toggles" in saved:
                for method_id, method_toggles in saved["method_rule_toggles"].items():
                    if method_id not in rules["method_rule_toggles"]:
                        rules["method_rule_toggles"][method_id] = {}
                    rules["method_rule_toggles"][method_id].update(method_toggles)
            # Per-method parameter overrides (deep-merge per method)
            if "method_overrides" in saved:
                for method_id, method_params in saved["method_overrides"].items():
                    if method_id not in rules["method_overrides"]:
                        rules["method_overrides"][method_id] = {}
                    rules["method_overrides"][method_id].update(method_params)
        except (ValueError, KeyError, IOError) as exc:
            logger.error("Could not load QC rules from %s: %s", self.path, exc)
        return rules

    def save(self, rules, updated_by=""):
        """Persist rules dict to JSON."""
        import datetime
        self._ensure_dir()
        rules["updated_by"] = updated_by
        rules["updated_at"] = datetime.datetime.utcnow().strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(rules, fh, indent=2, sort_keys=True)
            os.rename(tmp, self.path)
            logger.info("QC rules saved to %s by %s", self.path, updated_by)
        except (IOError, OSError) as exc:
            logger.error("Could not save QC rules: %s", exc)
            raise

    def get_qc_type_rules(self, qc_type, rules=None):
        """Return the rule dict for a single QC type shortcode."""
        if rules is None:
            rules = self.load()
        return rules["qc_types"].get(qc_type, {})

    def get_global(self, rules=None):
        if rules is None:
            rules = self.load()
        return rules.get("global", DEFAULT_RULES["global"])

    def get_salt_factors(self, rules=None):
        """Return the full salt_factors dict."""
        if rules is None:
            rules = self.load()
        return rules.get("salt_factors", DEFAULT_RULES["salt_factors"])

    def get_salt_factor(self, matrix, analyte_class=None, rules=None):
        """
        Return the scalar salt adjustment factor for a matrix + analyte class.

        matrix        : normalised matrix string (milk, egg, meat, fish, …)
        analyte_class : optional PFCA/PFSA/FTS key (pfca_c4_c8, pfsa, fts, …)
                        If None, the matrix 'default' value is returned.

        The factor is dimensionless.  Multiply the instrument concentration by
        this factor to get the corrected reported concentration.
        """
        sf = self.get_salt_factors(rules)
        mkey = (matrix or "other").lower()
        mdict = sf.get(mkey) or sf.get("other", {})
        if analyte_class:
            akey = analyte_class.lower()
            if akey in mdict:
                return float(mdict[akey])
        return float(mdict.get("default", 1.0))

    def matrix_names(self, rules=None):
        """Return sorted list of matrix keys in the salt_factors section."""
        return sorted(self.get_salt_factors(rules).keys())

    def chart_type(self, qc_type):
        """Return CHART_LJ or CHART_THRESHOLD for this QC type."""
        r = self.get_qc_type_rules(qc_type)
        return r.get("chart_type", CHART_LJ)

    def is_threshold_chart(self, qc_type):
        return self.chart_type(qc_type) == CHART_THRESHOLD


# ── Live criteria accessor (drop-in for QCCriteria class) ────────────────────

class LiveCriteria(object):
    """
    Provides the same interface as the static QCCriteria class but reads
    values from QCRulesStore at runtime.  Changes made via @@pfas-qc-rules
    take effect on the next engine run without a code deploy.

    Attribute access falls back to QCCriteria defaults if the rules file has
    not been customised or the store is unavailable.
    """

    def __init__(self, path=None):
        self._path = path

    def _g(self, key, default):
        """Look up a global criterion; return default if missing."""
        try:
            return get_store(self._path).get_global().get(key, default)
        except Exception:
            return default

    def _qt(self, qc_type, key, default):
        """Look up a per-QC-type criterion."""
        try:
            return get_store(self._path).get_qc_type_rules(qc_type).get(key, default)
        except Exception:
            return default

    # ── Calibration ───────────────────────────────────────────────────────
    @property
    def CAL_R2_MIN(self):
        return self._g("cal_r2_min", 0.995)

    @property
    def CAL_PCT_DEVIATION(self):
        return {
            "default": self._g("cal_pct_deviation_default", 25.0),
            "tight":   self._g("cal_pct_deviation_tight",   20.0),
            "loose":   self._g("cal_pct_deviation_loose",   30.0),
        }

    # ── IS response ───────────────────────────────────────────────────────
    @property
    def IS_RESPONSE_PCT(self):
        return self._g("is_response_pct", 50.0)

    # ── RT tolerance ──────────────────────────────────────────────────────
    @property
    def RT_TOLERANCE_MIN(self):
        return self._g("rt_tolerance_min", 0.10)

    @property
    def RT_TOLERANCE_PCT(self):
        return self._g("rt_tolerance_pct", 5.0)

    # ── Qual/Quan ion ratio ───────────────────────────────────────────────
    @property
    def QQ_RATIO_MATCHING_PCT(self):
        return self._g("qq_ratio_matching_pct", 20.0)

    @property
    def QQ_RATIO_KEY_PCT(self):
        return self._g("qq_ratio_key_pct", 25.0)

    @property
    def QQ_RATIO_NON_ISO_PCT(self):
        return self._g("qq_ratio_non_iso_pct", 30.0)

    # ── Signal to Noise ───────────────────────────────────────────────────
    @property
    def SN_MIN(self):
        return self._g("sn_min", 3.0)

    @property
    def SN_QUAN_MIN(self):
        return self._g("sn_quan_min", 10.0)

    # ── RPD ───────────────────────────────────────────────────────────────
    @property
    def RPD_MAX(self):
        return self._g("rpd_max", 30.0)

    # ── MDL (not configurable via UI — keep as constants) ─────────────────
    MDL_MIN_REPS     = 7
    MDL_T_CONFIDENCE = 0.99

    # ── LFSM/LFSMD recovery ───────────────────────────────────────────────
    @property
    def LFSM_RECOVERY_KEY_MATRIX(self):
        low  = self._qt("LFSM", "recovery_min_key_matrix", 65.0)
        high = self._qt("LFSM", "recovery_max_key_matrix", 135.0)
        return (low, high)

    @property
    def LFSM_RECOVERY_MATCHING(self):
        low  = self._qt("LFSM", "recovery_min", 40.0)
        high = self._qt("LFSM", "recovery_max", 140.0)
        return (low, high)

    @property
    def LFSM_RECOVERY_SUR(self):
        return (80.0, 120.0)

    # ── Methods matching QCCriteria class methods ─────────────────────────

    def lfsm_criteria(self, analyte, matrix):
        """Return (low, high) acceptance window for LFSM recovery."""
        from senaite.pfas.analytes import KEY_ANALYTES
        from senaite.pfas.analyte_reference import COMPOUND_NAME_TO_KEYWORD
        keyword = COMPOUND_NAME_TO_KEYWORD.get(analyte, analyte)
        matrix_upper = matrix.upper()
        # "TISSUE" covers "Aquatic Tissue"; pending canonical matrix vocabulary.
        is_bio = any(m in matrix_upper for m in ("EGG", "MUSCLE", "FISH", "MEAT", "TISSUE"))
        if keyword in KEY_ANALYTES and is_bio:
            return self.LFSM_RECOVERY_KEY_MATRIX
        return self.LFSM_RECOVERY_MATCHING

    def qq_criteria(self, analyte):
        """Return max % deviation for qual/quan ion ratio."""
        from senaite.pfas.analytes import KEY_ANALYTES, NON_ISO_ANALYTES
        from senaite.pfas.analyte_reference import COMPOUND_NAME_TO_KEYWORD
        keyword = COMPOUND_NAME_TO_KEYWORD.get(analyte, analyte)
        if keyword in NON_ISO_ANALYTES:
            return self.QQ_RATIO_NON_ISO_PCT
        if keyword in KEY_ANALYTES:
            return self.QQ_RATIO_KEY_PCT
        return self.QQ_RATIO_MATCHING_PCT


# ── Module-level singleton (lazy) ─────────────────────────────────────────────
_store = None


def get_store(path=None):
    global _store
    if _store is None or path is not None:
        _store = QCRulesStore(path)
    return _store


def get_rules(path=None):
    """Convenience: return merged rules dict."""
    return get_store(path).load()
