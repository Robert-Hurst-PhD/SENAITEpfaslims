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
    # N is the method profile's CCV frequency (Calibration & CCV) -- the value
    # the Run Builder brackets with; the duplicate "CCV every N" parameter that
    # stood here (10 everywhere, FDA's profile says 6) was retired 2026-10-01.
    {"key": "ccv_frequency", "label": "CCV Frequency", "params": [],
     "note": u"N is the method's CCV frequency (Calibration & CCV tab)."},
    {"key": "sn_min",        "label": "S/N Minimum",
     "params": [
         {"name": "sn_min",      "label": "Min S/N for detection",    "type": "number", "default": 3.0},
         {"name": "sn_quan_min", "label": "Min S/N for quantitation", "type": "number", "default": 10.0},
     ]},
    # Flags a detected result below the analyte's MDL (Reporting Limits). The
    # "min replicate count" parameter was dropped 2026-10-01: no MDL-study
    # record exists for it to be checked against.
    {"key": "mdl_check",     "label": "MDL Check", "params": [],
     "note": u"Flags detections below the MDL (Reporting Limits tab)."},
    # Every injection's labelled-surrogate recovery (wired 2026-10-01; the
    # check ran whatever this said before).
    {"key": "surrogate_recovery", "label": "Surrogate Recovery", "params": [],
     "note": u"Windows from the method text or the SUR limits."},
    # Whether the system PROMPTS for confirmation of a single-transition
    # positive. The obligation is method text (FDA §10.2(4)) and is not in
    # question; what is optional is this prompt, because a lab may confirm PFBA
    # by a route that is not LC-HRMS -- a second column, different ionisation,
    # an alternative transition -- and may be recording that elsewhere.
    #
    # WHICH analytes need confirming and WHICH technique is named live in the
    # method profile's `confirmation` block, beside the other confirmation
    # settings. This is the on/off switch only: one fact, one home.
    {"key": "single_transition_confirm",
     "label": "Single-Transition Confirmation",
     "params": []},
]

# ── Default toggle state per method ──────────────────────────────────────────
# True = rule is evaluated; False = rule is skipped.
DEFAULT_METHOD_RULE_TOGGLES = {
    "FDA_32PFAS": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "sn_min": False, "mdl_check": False,
        # ON for FDA: §10.2(4) names PFBA/PFPeA and the lab can switch the
        # prompt off if it confirms them another way.
        "single_transition_confirm": True,
        "surrogate_recovery": True,
    },
    "EPA_537_1": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "sn_min": False, "mdl_check": True,
        # Inert rather than off: 537.1 declares no single-transition analytes,
        # so the check finds nothing to confirm. Left ON so that a lab which
        # DOES declare one gets the prompt without also having to find a switch.
        "single_transition_confirm": True,
        "surrogate_recovery": True,
    },
    "EPA_1633A": {
        "is_response": True, "rrt_deviation": True, "ion_ratio": True,
        "cal_r2": True, "ccv_recovery": True, "ccv_frequency": True,
        "sn_min": True, "mdl_check": True,
        "single_transition_confirm": True,
        "surrogate_recovery": True,
    },
}

# Extraction / matrix QC is switched by the METHOD PROFILE's QC Types flag
# (qc_acceptance[CODE].enabled), beside its limits. The QC Rules grid shows
# these as switches that write that same flag -- one fact, two places
# (DECISIONS 2026-10-01). Never stored in method_rule_toggles.
QC_TYPE_SWITCHES = [
    ("LFSM", u"LFSM Recovery"), ("LFSMD", u"LFSMD RPD"),
    ("MB", u"Method Blank"), ("LRB", u"Reagent Blank (LRB)"), ("MxB", u"Matrix Blank"),
    ("LFB", u"LFB Recovery"), ("LCS", u"LCS Recovery"),
]
# Keys an earlier toggle grid stored that nothing reads (GAPS §73); removed by
# migrate_rule_store, as are the two retired parameters.
RETIRED_TOGGLES = ("blank_contamination", "mb_blank", "lcs_recovery",
                   "lfsm_recovery", "lfsmd_rpd")
RETIRED_PARAMS = ("ccv_frequency_n", "mdl_n_min")


def migrate_rule_store(rules):
    """True if `rules` lost retired toggles / parameters (in place, idempotent)."""
    changed = False
    for toggles in (rules.get("method_rule_toggles") or {}).values():
        for k in RETIRED_TOGGLES:
            if k in toggles:
                toggles.pop(k)
                changed = True
    for bucket in [rules.get("global") or {}] + list((rules.get("method_overrides") or {}).values()):
        for k in RETIRED_PARAMS:
            if k in bucket:
                bucket.pop(k)
                changed = True
    return changed


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
    "ccv_frequency": [],   # flags injections beyond the CCV bracket (no review item)
    "sn_min":        ["signal_to_noise"],
    "mdl_check":     [],   # flags detections below the MDL (no review item)
    "surrogate_recovery": ["surrogate_recovery"],
    "single_transition_confirm": ["identity_confirmation"],
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
        try:   # change history (R1)
            from senaite.pfas import config_history
            config_history.track(None, "qc_rules", "rules", self.load,
                                 label=u"QC rule toggles and parameters")
        except Exception:
            pass
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
