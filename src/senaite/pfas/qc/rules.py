# -*- coding: utf-8 -*-
"""
Instrument Verification Rules Store.

Provides configurable acceptance criteria for instrument-level checks:
calibration (CAL, ICV, CCV), IS response, RT deviation, ion ratio, and S/N.

Extraction and matrix QC acceptance (LCS, LFB, LFSM, LFSMD, MB, LRB, MxB,
Dup recovery/RPD/blank windows) are defined per-method in
method_profile_store.py under qc_acceptance — no fallbacks, no global defaults.

Rules are stored as JSON at DEFAULT_RULES_PATH (shared QC volume so both the
Zope browser and the Python-3 pipeline can read/write).

A Manager user edits rules via @@pfas-qc-rules.  The engine loads them at
run time so no code deploy is needed to tighten a window.
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
# The METHOD ID LIST is single-sourced from analyte_reference.get_method_ids();
# the short labels below are presentation only. Adding a method to the master
# adds a QC-rules toggle-grid column here automatically (falls back to the id).
from senaite.pfas.analyte_reference import get_method_ids as _get_method_ids

_METHOD_SHORT_LABELS = {
    "FDA_32PFAS": "FDA 32-PFAS",
    "EPA_537_1":  "EPA 537.1",
    "EPA_1633A":  "EPA 1633A",
}
METHODS = [{"id": mid, "label": _METHOD_SHORT_LABELS.get(mid, mid)}
           for mid in _get_method_ids()]

# ── Instrument Verification rule library ─────────────────────────────────────
# Only instrument-level rules live here.  Extraction/matrix QC acceptance
# (LCS, LFB, LFSM, LFSMD, MB, LRB, Dup, MxB recovery/RPD/blank windows) are
# defined per-method in the Method Profile (method_profile_store.py qc_acceptance).
RULE_LIBRARY = [
    {"key": "is_response",   "label": "IS Response",
     "params": [{"name": "is_response_pct", "label": "Max deviation (%)", "type": "number", "default": 50.0}]},
    {"key": "rrt_deviation", "label": "RRT / RT Deviation",
     "params": [
         {"name": "rt_tolerance_pct", "label": "RT tolerance (% relative)", "type": "number", "default": 5.0},
         {"name": "rt_tolerance_min", "label": "RT tolerance (min absolute)", "type": "number", "default": 0.10},
     ]},
    {"key": "ion_ratio",     "label": "Ion Ratio",
     "params": [
         {"name": "qq_ratio_matching_pct", "label": "Isotopically matched (%)", "type": "number", "default": 20.0},
         {"name": "qq_ratio_key_pct",      "label": "Key analytes (%)",          "type": "number", "default": 25.0},
         {"name": "qq_ratio_non_iso_pct",  "label": "Non-iso-linked (%)",        "type": "number", "default": 30.0},
     ]},
    {"key": "cal_r2",        "label": u"Calibration r²",
     "params": [{"name": "cal_r2_min", "label": u"Minimum r²", "type": "number", "default": 0.995}]},
    {"key": "ccv_recovery",  "label": "CCV Recovery",
     "params": [
         {"name": "ccv_recovery_min", "label": "Min recovery (%)", "type": "number", "default": 70.0},
         {"name": "ccv_recovery_max", "label": "Max recovery (%)", "type": "number", "default": 130.0},
     ]},
    {"key": "ccv_frequency", "label": "CCV Frequency",
     "params": [{"name": "ccv_frequency_n", "label": "CCV every N injections", "type": "integer", "default": 10}]},
    {"key": "sn_min",        "label": "S/N Minimum",
     "params": [
         {"name": "sn_min",      "label": "Min S/N for detection",    "type": "number", "default": 3.0},
         {"name": "sn_quan_min", "label": "Min S/N for quantitation", "type": "number", "default": 10.0},
     ]},
    {"key": "mdl_check",     "label": "MDL Check",
     "params": [{"name": "mdl_n_min", "label": "Min replicate count", "type": "integer", "default": 7}]},
]

# ── Default toggle state per method ──────────────────────────────────────────
# True = rule is evaluated; False = rule is skipped.
DEFAULT_METHOD_RULE_TOGGLES = {
    "FDA_32PFAS": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "sn_min": False, "mdl_check": False,
    },
    "EPA_537_1": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "sn_min": False, "mdl_check": True,
    },
    "EPA_1633A": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "sn_min": True, "mdl_check": True,
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
    "is_response":   ["is_response"],
    "rrt_deviation": ["rt_deviation"],
    "ion_ratio":     ["ion_ratio"],
    "cal_r2":        ["r_squared"],
    "ccv_recovery":  ["ccv_pct_dev"],
    "ccv_frequency": [],   # UI only — CCV interval in InjectionSequenceBuilder
    "sn_min":        ["signal_to_noise"],
    "mdl_check":     [],   # UI only — MDL assessment not auto-evaluated
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

    # Instrument verification QC types only.
    # LCS, LFB, LFSM, LFSMD, MB, MxB, LRB, Dup acceptance criteria live in
    # method_profile_store.py qc_acceptance (per-method, tiered, no fallbacks).
    "qc_types": {
        "CAL": {
            "label":             "Calibration Standard",
            "chart_type":        CHART_LJ,
            "pct_deviation_max": 25.0,
        },
        "ICV": {
            "label":             "Initial Calibration Verification",
            "chart_type":        CHART_LJ,
            "pct_deviation_max": 20.0,
        },
        "CCV": {
            "label":             "Continuing Calibration Verification",
            "chart_type":        CHART_LJ,
            "pct_deviation_max": 20.0,
            "pct_deviation_warn": 10.0,
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
            # Per-QC-type overrides (instrument types only: CAL, ICV, CCV)
            if "qc_types" in saved:
                for qtype, overrides in saved["qc_types"].items():
                    if qtype not in rules["qc_types"]:
                        rules["qc_types"][qtype] = {}
                    rules["qc_types"][qtype].update(overrides)
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
            # Global engine defaults (D52: previously dropped on load — this is
            # why the Global Criteria tab always rendered empty).
            if isinstance(saved.get("global"), dict):
                rules.setdefault("global", {}).update(saved["global"])
            # NOTE (D53): salt_factors is intentionally NOT loaded here. Salt
            # adjustment is a CORE per-method sample correction (lives in the
            # method profile, applied to ALL samples), not a QC-engine concept.
            # The legacy qc_rules.salt_factors block is deprecated/dead.
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

    def chart_type(self, qc_type):
        """Return CHART_LJ or CHART_THRESHOLD for this QC type."""
        r = self.get_qc_type_rules(qc_type)
        return r.get("chart_type", CHART_LJ)

    def is_threshold_chart(self, qc_type):
        return self.chart_type(qc_type) == CHART_THRESHOLD


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
