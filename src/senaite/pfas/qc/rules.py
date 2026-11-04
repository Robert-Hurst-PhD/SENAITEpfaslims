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

A Manager edits them on the method profile's tabs.  The engine loads them at
run time so no code deploy is needed to tighten a window.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

from senaite.pfas.qc_names import QC_NAMES

from senaite.pfas.blank_history import BLANK_TYPES

logger = logging.getLogger("senaite.pfas.qc.rules")

DEFAULT_RULES_PATH = os.environ.get(
    "PFAS_QC_RULES", "/data/qc/qc_rules.json"
)

# ── Chart type constants ──────────────────────────────────────────────────────
CHART_LJ       = "levey_jennings"   # Levey-Jennings + Westgard
CHART_THRESHOLD = "threshold"       # flat threshold line only (blanks)

# Which methods exist is the configured method profiles
# (configured_methods.choices); this module keeps no list of its own.

# ── Instrument Verification rule library ─────────────────────────────────────
# Only instrument-level rules live here (see the module docstring). A rule
# has one state (STATES below). Its LIMITS are the method profile's
# own fields (R2, CCV window, S/N, ion ratio, RT, IS response), never kept
# here.
# `scope` is what the rule's limits vary by (one of the SCOPE_ words, written
# out: the library is read as a literal); `editor` is where the QC criteria
# tab edits them: "drawer:<section id>:<group>" opens that group of the
# declared section from the rule's row, None when they are kept on another
# tab (the MDL on Analytes, the SUR limits on Isotope standards).
SCOPE_METHOD = u"Method"
SCOPE_WINDOWS = u"QC type \u00d7 analyte group \u00d7 matrix"
RULE_LIBRARY = [
    {"key": "is_response",   "label": "IS Response", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:IS / Surrogate Response",
     "note": u"Window: IS / Surrogate Response (QC criteria tab)."},
    # the IS response's second condition, its own switch: against the most
    # recent CCV (judged inside the IS response check, when that is on)
    {"key": "is_vs_ccv", "label": "IS response vs. the most recent CCV", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:IS / Surrogate Response",
     "note": u"Window: Compared to the most recent CCV (QC criteria tab)."},
    {"key": "rrt_deviation", "label": "RT Deviation", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:Chromatographic Confirmation & Signal Quality",
     "note": u"Tolerance: relative / absolute RT (QC criteria tab)."},
    {"key": "ion_ratio",     "label": "Ion Ratio", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:Chromatographic Confirmation & Signal Quality",
     "note": u"Ion Ratio Tolerance (QC criteria tab); blank = not judged."},
    {"key": "cal_r2",        "label": u"Calibration r²", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:Calibration",
     "note": u"R² Minimum (QC criteria tab)."},
    {"key": "ccv_recovery",  "label": "CCV Recovery", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:Continuing Calibration Verification (CCV)",
     "note": u"Recovery Min / Max (QC criteria tab)."},
    # N is the method profile's CCV frequency (Run Template), the value the
    # Run Builder brackets with
    {"key": "ccv_frequency", "label": "CCV Frequency", "params": [],
     "scope": u"Method", "editor": u"drawer:run_rules:Continuing Calibration Verification (CCV)",
     "note": u"N is the method's CCV frequency (QC criteria tab)."},
    {"key": "sn_min",        "label": "S/N Minimum", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:Chromatographic Confirmation & Signal Quality",
     "note": u"S/N minima, quantitation and confirmation (QC criteria tab)."},
    # flags a detected result below the analyte's MDL (Reporting Limits)
    {"key": "mdl_check",     "label": "MDL Check", "params": [],
     "scope": u"Method", "editor": None,
     "note": u"Flags detections below the MDL (Analytes tab)."},
    # every injection's labelled-surrogate recovery
    {"key": "surrogate_recovery", "label": "Surrogate Recovery", "params": [],
     "scope": u"Standard \u00d7 matrix class", "editor": None,
     "note": u"Windows from the method text or the SUR limits."},
    # Whether the system PROMPTS for confirmation of a single-transition
    # positive. The obligation is method text (FDA §10.2(4)); the prompt is
    # optional because a lab may confirm by another route (a second column,
    # another ionisation, another transition) and record it elsewhere.
    # WHICH analytes and WHICH technique live in the method profile's
    # `confirmation` block; this is the on/off switch only.
    {"key": "single_transition_confirm",
     "label": "Qualifier ion check", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:Single-Transition Confirmation",
     "note": u"A single-transition analyte's positive is confirmed by a second technique "
             u"(QC criteria tab)."},
    # A result above the method's top calibration level (the profile's
    # levels, in the matrix's reporting unit) reads ALoQ and is reported from
    # the dilution, whatever the instrument wrote (on by default).
    {"key": "over_range", "label": "Above the Calibration Range", "params": [],
     "scope": u"Method", "editor": u"drawer:cal:Calibration",
     "note": u"Top level: the highest calibration level (QC criteria tab)."},
]


# A rule is in one of three states: Enforced (a failure blocks), Evaluate
# (it is judged and filed as advisory, blocking nothing) or Off.
STATES = ("enforced", "evaluate", "off")


# A QC type's run row and a blank's row take the same three states, keyed
# by the type's stored spelling (qc_acceptance's key: "Dup", "MxB"). Only the
# lab's QC types (QC_NAMES) have a row; a blank is one of the blank kinds.
QC_TYPE_PREFIX, BLANK_PREFIX = "qc_type.", "blank."


def QC_TYPE_KEY(code):
    return QC_TYPE_PREFIX + code


def BLANK_KEY(code):
    return BLANK_PREFIX + code


def qc_row_key(code):
    """The rule-state key of a QC type's or blank's row; None for a type
    with no such row (an instrument check, the surrogates)."""
    if code not in QC_NAMES:
        return None
    return BLANK_KEY(code) if code in BLANK_TYPES else QC_TYPE_KEY(code)


def qc_row_code(key):
    """The QC type a QC-type or blank row's key names; None for a rule."""
    for prefix in (QC_TYPE_PREFIX, BLANK_PREFIX):
        if key.startswith(prefix):
            return key[len(prefix):]
    return None


def is_qc_row_key(key):
    return qc_row_code(key) is not None


# The Low-level recoveries row: whether a recovery judged against a
# low-level tier is judged (Enforced), filed as advisory (Evaluate) or not
# judged (Off). Extraction QC, owned by the method profile like a QC type's
# row, so it is no instrument rule of RULE_LIBRARY.
LOW_LEVEL_ROW = "low_level_recovery"


def is_profile_row_key(key):
    """A QC type's, a blank's or the Low-level recoveries row: a state the
    method profile holds that is no rule switch."""
    return key == LOW_LEVEL_ROW or is_qc_row_key(key)


def set_row_state(profile, key, state):
    """Store a row's state where it differs from the state the row reads
    (rule_state), so an untouched tab writes nothing. True if stored."""
    if state not in STATES or state == rule_state(profile, None, key):
        return False
    states = dict(profile.get("rule_states") or {})
    states[key] = state
    profile["rule_states"] = states
    return True


def qc_row_switched(profile, code, on):
    """The state an on / off switch gives a QC type's row: Off when off;
    when on, the state it holds, so a switch left on keeps Evaluate."""
    if not on:
        return "off"
    key = qc_row_key(code)
    held = rule_state(profile, None, key) if key else "enforced"
    return "enforced" if held == "off" else held


def set_qc_row_state(profile, code, state):
    """Set a QC type's or blank's row: where the state differs from the one
    the row reads (rule_state: a type the method does not hold reads
    Enforced), it is stored, whether or not the method holds the type, and a
    held type's `enabled` flag follows it (on unless Off), the flag being
    what older readers read. A state the row already reads writes nothing,
    so an untouched tab changes nothing; no `qc_acceptance` entry is ever
    created here. A type with no row only has its flag set. Returns the
    profile."""
    key = qc_row_key(code)
    entry = (profile.get("qc_acceptance") or {}).get(code)
    if key is None:
        if isinstance(entry, dict) and state in STATES:
            entry["enabled"] = state != "off"
        return profile
    if set_row_state(profile, key, state) and isinstance(entry, dict):
        entry["enabled"] = state != "off"
    return profile


def rule_state(profile, method_id, key):
    """One rule's state for one method: the profile's `rule_states`, then its
    `rule_toggles` (on = enforced); a rule the profile does not mention is
    enforced, as the worker judges it. A QC type's or blank's row with no
    state reads its type's `enabled` flag (absent = enforced). `method_id`
    is kept for the callers; the state never depends on it."""
    profile = profile or {}
    state = (profile.get("rule_states") or {}).get(key)
    if state in STATES:
        return state
    code = qc_row_code(key)
    if code is not None:
        entry = (profile.get("qc_acceptance") or {}).get(code)
        if isinstance(entry, dict) and not entry.get("enabled", True):
            return "off"
        return "enforced"
    toggles = profile.get("rule_toggles") or {}
    if key in toggles:
        return "enforced" if toggles[key] else "off"
    return "enforced"


def method_toggles(profile, method_id):
    """{rule key: on} for one method: a rule is on in the state Enforced and
    in the state Evaluate, off only when Off. The one reader of rule
    switches. The QC-type and blank rows are not rule
    switches: their on / off is their type's `enabled` flag."""
    keys = set(r["key"] for r in RULE_LIBRARY)
    keys.update((profile or {}).get("rule_toggles") or {})
    keys.update((profile or {}).get("rule_states") or {})
    return dict((k, rule_state(profile, method_id, k) != "off") for k in keys
                if not is_profile_row_key(k))


# qc_rules.json values that are QC CRITERIA, not chart presentation: the
# method profile owns them, and they are stripped from the file.
CRITERIA_KEYS = ("pct_deviation_max", "pct_deviation_warn", "recovery_min",
                 "recovery_max", "recovery_warn_low", "recovery_warn_high",
                 "recovery_min_key_matrix", "recovery_max_key_matrix", "rpd_max")


def strip_moved_sections(saved):
    """Remove what the method profiles own from a qc_rules.json dict (in
    place): rule toggles, method overrides, global defaults, and the criteria
    half of qc_types. True if anything was removed."""
    changed = False
    for k in ("method_rule_toggles", "method_overrides", "global"):
        if k in saved:
            saved.pop(k)
            changed = True
    for qt in (saved.get("qc_types") or {}).values():
        for k in CRITERIA_KEYS:
            if isinstance(qt, dict) and k in qt:
                qt.pop(k)
                changed = True
    return changed

# ── Mapping: RULE_LIBRARY key → engine review-check name(s) ──────────────────
# Used by the pipeline worker to gate auto_evaluate() blocks.
# An empty list: no review check of its own; the rule acts where its comment
# says.
LIBRARY_KEY_TO_ENGINE_CHECKS = {
    "is_response":   ["is_response"],
    "is_vs_ccv":     [],   # gated inside the IS response check (qc_engine)
    "rrt_deviation": ["rt_deviation"],
    "ion_ratio":     ["ion_ratio"],
    "cal_r2":        ["r_squared"],
    "ccv_recovery":  ["ccv_pct_dev"],
    "ccv_frequency": [],   # flags injections beyond the CCV bracket (no review item)
    "sn_min":        ["signal_to_noise"],
    "mdl_check":     [],   # flags detections below the MDL (no review item)
    "surrogate_recovery": ["surrogate_recovery"],
    "single_transition_confirm": ["identity_confirmation"],
    "over_range":    [],   # the result reads ALoQ; the dilution reports (no review item)
}

# ── Default QC rule set ───────────────────────────────────────────────────────
# Values are editable through the browser UI; these serve as built-in fallback.

DEFAULT_RULES = {
    "version": 1,
    "updated_by": "",
    "updated_at": "",

    # instrument verification QC types only (see the module docstring)
    "qc_types": {
        "CAL": {"label": "Calibration Standard", "chart_type": CHART_LJ},
        "ICV": {"label": "Initial Calibration Verification", "chart_type": CHART_LJ},
        "CCV": {"label": "Continuing Calibration Verification", "chart_type": CHART_LJ},
    },
}

# ── File-based store ──────────────────────────────────────────────────────────

class QCRulesStore(object):
    """Load and persist QC rules from/to JSON on the shared QC volume."""

    def __init__(self, path=None):
        self.path = path or DEFAULT_RULES_PATH


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
            # control-chart presentation per instrument QC type (CAL, ICV,
            # CCV); criteria, rule toggles, method overrides and global
            # defaults are NOT loaded: the method profile owns them
            if "qc_types" in saved:
                for qtype, overrides in saved["qc_types"].items():
                    if qtype not in rules["qc_types"]:
                        rules["qc_types"][qtype] = {}
                    rules["qc_types"][qtype].update(
                        (k, v) for k, v in overrides.items() if k not in CRITERIA_KEYS)
            # salt_factors is NOT loaded: salt adjustment is a per-method
            # sample correction on the method profile, applied to ALL
            # samples, not a QC-engine concept
        except (ValueError, KeyError, IOError) as exc:
            logger.error("Could not load QC rules from %s: %s", self.path, exc)
        return rules

    def _ensure_dir(self):
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d)
            except OSError:
                pass

    def save(self, rules, updated_by=""):
        """Persist rules dict to JSON."""
        # change history: track() itself decides whether a failure blocks the save
        from senaite.pfas import config_history
        config_history.track(None, "qc_rules", "rules", self.load,
                             label=u"QC chart settings")
        import datetime
        self._ensure_dir()
        # the file holds chart presentation only; what the method profiles
        # own is never written back (e.g. by reverting an old entry)
        strip_moved_sections(rules)
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


