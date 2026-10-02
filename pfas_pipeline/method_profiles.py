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
import re
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
    max_conc_x_rl:    Optional[float] = None   # blanks: at most N x RL


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
    # HOW a single-transition positive is confirmed. FDA §10.2(4) cites LC-HRMS,
    # but it is not the only orthogonal route -- a second column, a different
    # ionisation mode or an alternative transition can also establish identity --
    # so the technique is the lab's to name and the prompt quotes whatever it
    # says. Hardcoding "LC-HRMS" told a lab to run an instrument it may not own.
    confirm_technique: str = "LC-HRMS"
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
# while these lists use DISPLAY NAMES (e.g. "GenX (HFPO-DA)") to match
# instrument export.  The map below bridges them. PFOS/PFHxS are reported
# under their plain names since 2026-10-01; "lr-" names only their linear peak.
# ─────────────────────────────────────────────────────────────────────────────

# Analyte keyword → instrument display name (only entries that differ)
_FDA_KW_TO_DISPLAY: dict = {
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
    "PFHxDA", "PFHxS", "PFNA", "PFNS", "PFOA", "PFODA", "PFOS",
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
# Profile data cache — populated ONLY from the exported method profiles
# (/data/qc/method_profiles.json, written by SENAITE on every profile save) at
# batch start via reload_from_profiles(). There are NO built-in criteria: a
# method missing from the export is not configured, and run_pipeline refuses
# it rather than judging with numbers the lab never set (QC consolidation P1;
# the inline defaults that used to sit here carried an FDA LCS tier, 1633A
# FTS EIS limits and a retired QC-type list that no live profile had).
# ─────────────────────────────────────────────────────────────────────────────

_METHOD_IDS = ("FDA_32PFAS", "EPA_537_1", "EPA_1633A")
_DEFAULT_PROFILE_CACHE = dict((m, {}) for m in _METHOD_IDS)
_LOADED = set()          # methods whose data came from the export


def profile_configured(method_id):
    """True when `method_id`'s criteria were loaded from the exported file."""
    return method_id in _LOADED


_profile_data_cache = copy.deepcopy(_DEFAULT_PROFILE_CACHE)


def reload_from_profiles(profiles_path=None, batch_id=None):
    """
    Reload _profile_data_cache from the exported method profile JSON.
    Called at the start of each batch run so changes made in the SENAITE
    Method Profile control panel take effect without a worker restart.
    A method missing from the file (or no file at all) is left EMPTY and
    unconfigured -- see profile_configured(); nothing falls back to defaults.

    `batch_id`, when given, additionally overlays that batch's RESOLVED
    criteria (senaite.pfas.resolved_criteria_store, project -> lab ->
    baseline) on top of whatever this reload just loaded from the global
    file. This module does NOT decide which tier wins -- that resolution
    already happened, in the add-on, before the file was written; this is
    plumbing the already-resolved numbers into the same cache shape the
    rest of this module reads, nothing more (see
    _apply_resolved_overlay()'s docstring).

    THE SAFETY PROPERTY: `batch_id=None` (every call site that predates
    project support, and every batch with no linked project) makes this
    function behave BYTE-FOR-BYTE as it did before batch_id existed --
    the overlay branch below is never entered. A batch_id with no resolved
    file on disk (the overwhelming common case even once batch_id IS
    passed, since the file only exists for a project-linked batch) is
    likewise a silent no-op: no warning, no fallback, nothing.
    """
    if profiles_path is None:
        profiles_path = PROFILES_PATH

    if not os.path.exists(profiles_path):
        logger.error("reload_from_profiles: %s does not exist -- no method is "
                     "configured until SENAITE exports its method profiles",
                     profiles_path)
        _LOADED.clear()
        return

    try:
        with open(profiles_path) as fh:
            all_profiles = json.load(fh)
    except (IOError, OSError, ValueError) as exc:
        logger.error("reload_from_profiles: could not load %s: %s",
                     profiles_path, exc)
        _LOADED.clear()
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
            _LOADED.add(method_id)
            logger.info("Loaded profile data for %s from %s",
                        method_id, profiles_path)
        else:
            _profile_data_cache[method_id] = {}
            _LOADED.discard(method_id)
            logger.error(
                "reload_from_profiles: %r not in %s; that method is not "
                "configured", method_id, profiles_path,
            )

    if batch_id:
        _apply_resolved_overlay(batch_id, profiles_path)


# ─────────────────────────────────────────────────────────────────────────────
# Per-batch resolved-criteria overlay (project QAPP -> lab -> baseline)
# ─────────────────────────────────────────────────────────────────────────────
#
# The add-on (senaite.pfas.ruleset) does the actual tier resolution and
# writes ONE JSON file per project-linked batch, alongside the global
# method_profiles.json this module already reads
# (senaite.pfas.resolved_criteria_store.export_resolved_criteria). This
# section reads that file back and injects each already-resolved value into
# _profile_data_cache at the same key paths reload_from_profiles() itself
# fills from the global file. It performs NO resolution of its own -- no
# tier comparison, no fallthrough logic -- only translates {key, value} rows
# into the profile-dict shape the rest of this module already expects. That
# tier logic living exactly once, in the add-on, is deliberate (a second
# copy here would be the "dead twin" shape this project has removed twice;
# see GAPS.md Sec2 A4 and Sec4).
#
# Key -> path mapping is a SMALL, DELIBERATE duplicate of
# senaite.pfas.ruleset.SHAPES_BY_KEY / _LAB_EXTRACTORS -- not a resolution
# copy, a location copy: "where does this key live in the profile dict",
# the exact same shape method_baselines.matrix_class() already keeps
# duplicated across this process boundary for the same reason (that module's
# comment explains it: the worker is Python-3-only pipeline code and must
# stay dependency-free of the Python-2.7 add-on package).
_OVERLAY_PATHS = {
    "cal_r2_min":  ("instrument_verification", "calibration", "r2_min"),
    "sn_quan_min": ("instrument_verification", "confirmation", "sn_quan_min"),
    "dup_rpd_max": ("qc_acceptance", "Dup", "tiers", 0, "rpd_max"),
}

# ── The CRITERIA wrinkle ─────────────────────────────────────────────────────
#
# `_profile_data_cache` is not the only live reader of cal_r2_min/sn_quan_min.
# constants.CRITERIA (a flat dict `reload_criteria()` builds by re-reading
# the global profiles file DIRECTLY, never through this cache) still has two
# real consumers that never migrated to the profiled path Decision C
# (2026-06-17, this module's own docstring) declared authoritative:
# qc_engine.signal_to_noise_check() reads CRITERIA["sn_quan_min"]
# unconditionally (there is no profiled variant to call instead), and
# qc_engine.calibration_check() -- the FALLBACK run_queue.py uses only when
# no profile resolved at all -- reads CRITERIA["cal_r2_min"]. Overlaying
# _profile_data_cache alone would leave those two consumers seeing the
# un-overridden lab value for a project-linked batch: the exact "merged
# half-way" inconsistency this feature's tests exist to rule out, one
# consumer layer down. So the resolved values for these two keys are ALSO
# written into CRITERIA here, from the same rows, no new resolution.
#
# Scope of this fix, and its limit: reload_criteria() is called with NO
# method_id argument anywhere in this codebase, so it ALWAYS builds CRITERIA
# from FDA_32PFAS's profile, regardless of the run's actual method -- a
# pre-existing behaviour, not introduced here (GAPS.md Sec20 records it).
# Overlaying CRITERIA is therefore only applied when the resolved payload's
# own method_id is "FDA_32PFAS", matching what CRITERIA already represents
# today; a resolved EPA_537_1/EPA_1633A payload does not touch CRITERIA; it
# already does not reflect the batch's real method regardless of any project
# link, which is that pre-existing gap, not this one.
_CRITERIA_METHOD_SCOPE = "FDA_32PFAS"

_CRITERIA_KEYS_BY_OVERLAY_KEY = {
    "cal_r2_min":  ("cal_r2_min",),
    "sn_quan_min": ("sn_quan_min", "sn_min"),   # sn_min is the back-compat alias
}


def _apply_resolved_criteria(rows, method_id):
    """Overlay the resolved cal_r2_min / sn_quan_min values (if any) onto
    constants.CRITERIA -- see "The CRITERIA wrinkle" above for why this is
    necessary at all and why it is scoped to method_id == FDA_32PFAS."""
    if method_id != _CRITERIA_METHOD_SCOPE:
        return 0
    from .constants import CRITERIA
    applied = 0
    for row in rows:
        key = row.get("key")
        value = row.get("value")
        if value is None or key not in _CRITERIA_KEYS_BY_OVERLAY_KEY:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        for criteria_key in _CRITERIA_KEYS_BY_OVERLAY_KEY[key]:
            CRITERIA[criteria_key] = value
        applied += 1
    return applied


def _set_path(data, path, value):
    cur = data
    for step in path[:-1]:
        if isinstance(step, int):
            while len(cur) <= step:
                cur.append({})
            cur = cur[step]
        else:
            cur = cur.setdefault(step, {})
    last = path[-1]
    if isinstance(last, int):
        while len(cur) <= last:
            cur.append({})
        cur[last] = value
    else:
        cur[last] = value


def _apply_resolved_row(data, row):
    """Inject one already-resolved criterion row into `data` (one method's
    entry in _profile_data_cache). Returns True if applied, False if the
    row's value is absent (nothing to overlay -- e.g. tier=baseline with no
    seeded baseline) or its key is not one this worker maps anywhere
    (forward-compatible: a criterion key ruleset.py registers that this
    worker does not yet consume for anything is a no-op here, not an
    error -- it simply is not applied, exactly as if the file never
    mentioned it)."""
    key = row.get("key")
    value = row.get("value")
    if value is None:
        return False
    if key == "ccv_recovery":
        if not isinstance(value, dict):
            return False
        iv = data.setdefault("instrument_verification", {})
        ccv = iv.setdefault("ccv", {})
        ccv["recovery_min"] = value.get("min")
        ccv["recovery_max"] = value.get("max")
        return True
    if key == "eis_recovery":
        analyte = row.get("analyte")
        if not analyte or not isinstance(value, dict):
            return False
        eis = data.setdefault("eis_overrides", {})
        if not isinstance(eis, dict):
            eis = {}
            data["eis_overrides"] = eis
        eis[analyte] = {"recovery_min": value.get("min"),
                        "recovery_max": value.get("max")}
        return True
    path = _OVERLAY_PATHS.get(key)
    if path is None:
        return False
    _set_path(data, path, value)
    return True


def _apply_profile_patch(data, ops):
    """Apply a project's path patch (senaite.pfas.project_specs.profile_patch)
    to one method's profile dict. The add-on did all the merging -- here each
    op only sets or deletes the value at its path."""
    applied = 0
    for op in ops:
        path = op.get("path") or []
        if not path:
            continue
        if op.get("delete"):
            cur = data
            for step in path[:-1]:
                cur = cur.get(step) if isinstance(cur, dict) else None
                if cur is None:
                    break
            if isinstance(cur, dict) and path[-1] in cur:
                cur.pop(path[-1])
                applied += 1
        else:
            _set_path(data, path, op.get("value"))
            applied += 1
    return applied


def _ops_are_well_formed(ops):
    return isinstance(ops, list) and all(
        isinstance(op, dict) and isinstance(op.get("path"), list) and op["path"]
        and ("value" in op or op.get("delete") is True) for op in ops)


def _row_is_well_formed(row):
    """Structural check only -- NOT a resolution check. A row is well-formed
    if it is a dict naming a criterion key; whether that key means anything
    to THIS worker (or its value is None) is decided per-row in
    _apply_resolved_row() and is not a validity question."""
    return isinstance(row, dict) and isinstance(row.get("key"), str) and row.get("key")


def _load_resolved_payload(batch_id, profiles_path):
    """The parsed, structurally-validated resolved-criteria payload for
    batch_id, or None for every case that must leave the global profile
    untouched: no file (the default for any batch with no linked project),
    an unreadable/corrupt file, or a file whose shape cannot be trusted.

    Deliberately all-or-nothing (GAPS.md Sec7.1's partial-write shape, one
    layer over): if the file's top-level shape is wrong, or ANY row in it is
    not even structurally a criterion row, the WHOLE file is rejected and
    logged once -- never applied row-by-row such that some criteria end up
    overridden and others silently do not because of what amounts to a
    corrupt record. A row that IS well-formed but names a key/value this
    worker does not apply anywhere is a normal per-row no-op, not a reason
    to reject the file (see _row_is_well_formed's docstring)."""
    if not batch_id:
        return None
    path = os.path.join(os.path.dirname(profiles_path), "resolved",
                         "%s.json" % batch_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            payload = json.load(fh)
    except (IOError, OSError, ValueError) as exc:
        logger.warning(
            "resolved criteria file %s is unreadable (%s) -- ignoring it "
            "entirely; batch %s runs on the lab-tier profile only",
            path, exc, batch_id)
        return None

    if not isinstance(payload, dict):
        logger.warning(
            "resolved criteria file %s is not a JSON object -- ignoring it "
            "entirely", path)
        return None
    method_id = payload.get("method_id")
    if not method_id or method_id not in _profile_data_cache:
        logger.warning(
            "resolved criteria file %s names method_id %r, not a known "
            "profile -- ignoring it entirely", path, method_id)
        return None
    criteria = payload.get("criteria")
    if not isinstance(criteria, list):
        logger.warning(
            "resolved criteria file %s has no 'criteria' list -- ignoring "
            "it entirely", path)
        return None
    if "profile_patch" in payload and not _ops_are_well_formed(payload["profile_patch"]):
        logger.warning(
            "resolved criteria file %s has a malformed profile_patch -- "
            "ignoring the WHOLE file rather than applying it half-way", path)
        return None
    if not all(_row_is_well_formed(row) for row in criteria):
        logger.warning(
            "resolved criteria file %s contains a malformed row -- "
            "ignoring the WHOLE file rather than applying it half-way",
            path)
        return None
    return payload


def _apply_resolved_overlay(batch_id, profiles_path):
    payload = _load_resolved_payload(batch_id, profiles_path)
    if payload is None:
        return
    method_id = payload["method_id"]
    data = _profile_data_cache[method_id]
    # the project's specs first (DECISIONS 2026-10-01), then the QAPP criteria
    patched = _apply_profile_patch(data, payload.get("profile_patch") or [])
    if patched:
        logger.info("Applied %d project-spec changes for batch %s (%s)",
                    patched, batch_id, method_id)
    applied = 0
    for row in payload["criteria"]:
        if _apply_resolved_row(data, row):
            applied += 1
    applied_criteria = _apply_resolved_criteria(payload["criteria"], method_id)
    logger.info(
        "Applied %d resolved (project-aware) criteria for batch %s (%s); "
        "%d also overlaid onto CRITERIA",
        applied, batch_id, method_id, applied_criteria)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: resolve recovery tier from profile data
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_fda_tier(analyte, matrix, profile_data, qc_type="LFSM",
                      method_id="FDA_32PFAS", conc=None, rl=None):
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
    all_tiers = qc_entry.get("tiers", [])
    tiers = _ordinary_tiers(all_tiers)
    where = "{0} / {1} / {2} / {3}".format(method_id, analyte, matrix or "(no matrix)", qc_type)

    def _rule(tier, notes, is_tight=False):
        group = tier.get("analyte_group", "all")
        tier = _low_level_tier(
            all_tiers, tier,
            lambda t: (t.get("analyte_group", "all") in ("all", group) and
                       (t.get("matrix_scope", "all") != "tight" or is_tight)),
            conc, rl, where)
        if tier.get(LOW_LEVEL_KEY):
            notes = tier.get("description") or "low-level window (<= {0:g} x RL)".format(
                float(tier[LOW_LEVEL_KEY]))
        return _tier_rule(tier, notes, method_id, analyte, matrix, qc_type)

    # New structure: tiers have analyte_group and matrix_scope keys
    if tiers and "analyte_group" in tiers[0]:
        # "No labelled standard" is derived from THIS method's surrogate links
        # (consolidation P4); tight matrices are the method's own list.
        from .analyte_alias import no_labelled_names_for, key_analyte_names
        no_std = no_labelled_names_for(profile_data)
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
        # Key analytes are the METHOD's own list (2026-10-01); a profile
        # without one falls back to the global flag, as before.
        own_keys = profile_data.get("key_analytes")
        if isinstance(own_keys, list):
            from .analyte_alias import keyword_for
            is_key = (keyword_for(analyte) or analyte) in set(own_keys) or analyte in set(own_keys)
        else:
            is_key = analyte in key
        is_tight = m in tight

        for tier in tiers:
            ag = tier.get("analyte_group", "all")
            ms = tier.get("matrix_scope", "all")
            if ag == "no_std" and is_no_std:
                return _rule(tier, "No matched labeled standard (Table 10-1 footnote a)", is_tight)
            if ag == "key" and ms == "tight" and is_key and is_tight:
                return _rule(tier,
                             "PFOS/PFOA/PFHxS/PFNA in eggs/meat/seafood "
                             "(Table 10-1 tier 1)", is_tight)
        # Fall through to the "linked" / default tier
        for tier in tiers:
            ag = tier.get("analyte_group", "all")
            if ag in ("linked", "all"):
                return _rule(tier, "Table 10-1 tier 2 (other matrices / other analytes)", is_tight)
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

    def qc_rules(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
        raise NotImplementedError

    def reporting_limits(self, analyte, matrix):
        """(rl, mdl, unit) for the analyte in `matrix`, in the matrix's
        reporting unit as configured; None for what is not set."""
        from .analyte_alias import keyword_for
        data = self._profile_data()
        kw = keyword_for(analyte) or analyte
        entry = ((data.get("reporting_limits") or {}).get(matrix) or {}).get(kw) or {}
        unit = (data.get("unit_map") or {}).get(matrix) or ""
        num = lambda v: None if v is None else float(v)       # noqa: E731
        rl = num(entry.get("rl"))
        if rl is None:
            # the analyte's lowest calibrator in this unit -- the add-on's own
            # rule, loaded from its file (DECISIONS 2026-10-02)
            rl = _cal().derived_rl(data, matrix, kw)
        return rl, num(entry.get("mdl")), unit

    def ccv_frequency(self):
        """The method's CCV interval (Calibration & CCV) -- the value the Run
        Builder brackets with -- or None when not set."""
        ccv = (self._profile_data().get("instrument_verification") or {}).get("ccv") or {}
        n = ccv.get("frequency")
        return int(n) if n not in (None, "", 0) else None

    def reporting_limit_ppt(self, analyte, matrix):
        """The analyte's RL for `matrix` in ppt (the spike-level unit), or
        None when no RL is set or its unit is not one this converts."""
        rl, _mdl, unit = self.reporting_limits(analyte, matrix)
        factor = _cal().PPT_PER_UNIT.get((unit or "").strip().lower())
        return rl * factor if rl is not None and factor else None

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

    def qc_type_enabled(self, qc_code):
        """Is this extraction/matrix QC type switched on for this method?

        `qc_acceptance[qc_code].enabled` is the lab's switch, set in the Method
        Profile UI beside the limits it governs. This method exists so the
        answer has ONE definition: `qc_acceptance_rule` below already applied
        the same flag, and `run_queue` used to gate LFSM/LFSMD on a
        `method_rule_toggles` key that appeared in no library, no defaults
        table and no UI — so the switch a lab was given did nothing.

        Absent defaults to True. A missing entry must not silently switch a
        check off; if its criteria are unconfigured the check refuses to judge,
        which is louder than skipping.
        """
        entry = (self._profile_data().get("qc_acceptance") or {}).get(qc_code)
        if not isinstance(entry, dict):
            return True
        return bool(entry.get("enabled", True))

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

    def qc_rules(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
        if qc_type in ("SUR", "surrogate"):
            return _method_text_rule(
                self._profile_data(), self.method_id,
                "Surrogate recovery is guidance only (FDA §2024.10.1(5))",
                50.0, 150.0, is_guidance_only=True)
        if qc_type in ("Dup", "duplicate"):
            return _resolve_fda_tier(analyte, matrix,
                                     self._profile_data(), qc_type="Dup",
                                     method_id=self.method_id, conc=conc, rl=rl)
        return _resolve_fda_tier(analyte, matrix,
                                 self._profile_data(), qc_type=qc_type,
                                 method_id=self.method_id, conc=conc, rl=rl)

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
            confirm_technique=(conf.get("confirm_technique")
                               or "LC-HRMS").strip(),
            notes="PFBA/PFPeA positives require LC-HRMS confirmation; "
                  "cholic acid (TDCA/TCDCA/TUDCA) interference transitions "
                  "monitored for PFOS (§2024.8.5)",
        )

    def sequence_rule(self):
        ccv = self._iv().get("ccv", {})
        return SequenceRule(
            opens_with_solvent_blank=True,
            blank_after_curve=True,
            ccv_frequency=int(ccv.get("frequency") or 6),   # the edited value (P1)
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

    def qc_rules(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
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
        # its FIRST ordinary tier, replaced by a low-level tier when one holds
        base = (_ordinary_tiers(tiers) or tiers)[0]
        t = _low_level_tier(tiers, base, lambda _t: True, conc, rl,
                            "{0} / {1} / {2} / {3}".format(self.method_id, analyte, matrix, qc_type))
        rule = _tier_rule(t, t.get("description", ""), self.method_id,
                          analyte, matrix, qc_type)
        return QCRule(
            recovery_min=rule.recovery_min,
            recovery_max=rule.recovery_max,
            rsd_max=rule.rsd_max,
            rpd_max=rule.rpd_max,
            notes=rule.notes,
            max_conc_x_rl=rule.max_conc_x_rl,
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
        ccv = self._iv().get("ccv", {})
        return SequenceRule(
            ccv_frequency=int(ccv.get("frequency") or 10),   # the edited value (P1)
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
    "tight_matrices", "low_level_x_rl", "citation",
])

# ── Low-level tiers (DECISIONS 2026-10-01) ───────────────────────────────────
# A tier carrying low_level_x_rl = N applies only when the fortified
# concentration is at or below N x the analyte's RL -- e.g. EPA 537.1 v2.0
# §9.3.6.3: LFSM 70-130%, but 50-150% "within a factor of 2-times the MRL".
# The ordinary tier is chosen exactly as before; a low-level tier replaces it
# only when its condition holds. Without the concentration or the RL the
# engine refuses: it never guesses which window a spike belongs to.
LOW_LEVEL_KEY = "low_level_x_rl"

def _cal():
    """senaite.pfas.calibration_levels, loaded from the add-on (pfas_pipeline
    .addon) -- the RL rule lives once."""
    from .addon import load
    return load("calibration_levels")


def _ordinary_tiers(tiers):
    return [t for t in tiers if not t.get(LOW_LEVEL_KEY)]


def _low_level_tier(tiers, base, applies, conc, rl, where):
    """The low-level tier whose condition holds (smallest N first), else
    `base`. Refuses when one could apply but conc/RL are unknown."""
    cond = [t for t in tiers if t.get(LOW_LEVEL_KEY) and applies(t)]
    if not cond:
        return base
    missing = [n for n, v in (("the fortified concentration", conc),
                              ("the analyte's RL for this matrix", rl)) if not v]
    if missing:
        raise UnconfiguredCriterion(
            "{0}: a low-level tier (applies at <= N x RL) is configured, so the "
            "window depends on the spike level, but {1} is not set. Enter it "
            "(Method Profiles -> Recovery Tiers spike levels / Reporting "
            "Limits) -- the engine does not guess.".format(where, " and ".join(missing)))
    for t in sorted(cond, key=lambda t: float(t[LOW_LEVEL_KEY])):
        if float(conc) <= float(t[LOW_LEVEL_KEY]) * float(rl):
            return t
    return base


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
    blank = tier.get("max_conc_x_rl")
    return QCRule(
        None if low is None else float(low),
        None if high is None else float(high),
        rsd_max=rsd,
        rpd_max=rpd,
        notes=notes,
        max_conc_x_rl=None if blank is None else float(blank),
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

    def qc_rules(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
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
            # `analyte` is the compound as the INSTRUMENT names it, which is
            # the compound the lab actually spiked. Tables 6/8 designate the
            # same position by EPA's own labelled form, and ten of the
            # twenty-four differ (13C4-PFBA vs the catalogue's 13C3-PFBA), so a
            # direct lookup missed ten compounds and silently applied the
            # generic window. Join through the native instead; see
            # eis_criteria_name. The flag keeps `analyte` unchanged, so a
            # certificate names the compound the lab has rather than EPA's.
            criteria_name = eis_criteria_name(self.method_id, analyte)
            override = eis_overrides.get(criteria_name, {})
            # A limit stored as null is UNSET: it falls back, never float(None)
            # (the editor now saves a blank as null, not 0 -- GAPS §51).
            lo = _limit_or(override.get("recovery_min"), default_lo)
            hi = _limit_or(override.get("recovery_max"), default_hi)
            if matrix:
                mat_class = _1633a_matrix_class(matrix)
                if mat_class != "aqueous":
                    mat_override = eis_matrix.get(mat_class, {}).get(
                        criteria_name)
                    if mat_override:
                        lo = _limit_or(mat_override.get("recovery_min"), lo)
                        hi = _limit_or(mat_override.get("recovery_max"), hi)
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
        base = (_ordinary_tiers(tiers) or tiers)[0]
        t = _low_level_tier(tiers, base, lambda _t: True, conc, rl,
                            "{0} / {1} / {2} / {3}".format(self.method_id, analyte, matrix, mapped))
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
            max_conc_x_rl=rule.max_conc_x_rl,
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
        ccv = self._iv().get("ccv", {})
        return SequenceRule(
            ccv_frequency=int(ccv.get("frequency") or 10),   # the edited value (P1)
            closing_ccv=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

def _limit_or(value, fallback):
    """A stored limit as float, or the fallback when it is unset (None)."""
    return fallback if value is None else float(value)


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
    # Derived from THIS method's surrogate links (consolidation P4), not a
    # global column: a link changed in one method moves the analyte there.
    from .analyte_alias import no_labelled_names_for
    try:
        data = get_profile(method_id)._profile_data()
    except KeyError:
        data = {}
    names = no_labelled_names_for(data)
    if not names:
        return frozenset()
    # Scope to the method's own panel so 1633A-only analytes do not leak in.
    panel = set(get_analyte_list(method_id) or [])
    return frozenset(names & panel) if panel else frozenset(names)


# Leading isotopic label on a labelled compound's name: "13C4-", "13C2,D4-",
# "D3-". Used ONLY to reach the native a published method's EIS designation
# refers to (see eis_criteria_name) -- never to decide that two labelled names
# mean the same compound.
_ISOTOPE_LABEL = re.compile(r"^(?:13C\d+|D\d+)(?:,\s*D\d+)?-")


def get_is_list(method_id: str = "FDA_32PFAS") -> list:
    """Display names of the labelled compounds this METHOD monitors.

    DERIVED, not stored. This used to read a profile key `internal_standards`
    that NOTHING has ever written -- no editor field, no seed, no migration --
    and fall back to an inline FDA list. So it returned the 21 FDA names for
    FDA_32PFAS and an EMPTY LIST for both EPA methods, which meant the IS
    Response loop in run_queue iterated nothing and no surrogate or internal
    standard was checked at all on EPA 537.1 or EPA 1633A (GAPS.md Sec19).

    The set is already recorded twice over, per method: `surrogate_map` names
    the labelled compound that quantifies each native in the method's panel, and
    the reference table marks which labelled compound is the injection standard.
    Both are method-scoped by construction, so the list is their union:

        {surrogate_map values} + {injection IS}   ->   display names

    Keywords are converted to display names because that is what the instrument
    exports and what `is_raw_check` matches rows on. Every name this returns
    therefore exists as an AnalysisService -- internal_standards.csv creates
    them from the same table -- which a list taken from a published method's own
    designations would NOT (see eis_criteria_name).

    Falls back to the inline FDA names only when no profile is loaded at all.
    """
    from .analyte_alias import injection_is_names, labelled_display_name

    data = _profile_data_cache.get(method_id, {})
    grid = data.get("labelled_standards")
    if isinstance(grid, dict) and grid:
        # The method's own grid (DECISIONS 2026-09-30): every standard it
        # USES. Map surrogates first (in map order), then the rest.
        order = []
        for row in data.get("surrogate_map") or []:
            kw = (row.get("surrogate_is") or "").strip()
            if kw in grid and kw not in order:
                order.append(kw)
        order += sorted(k for k in grid if k not in order)
        return [labelled_display_name(k) for k in order]
    rows = data.get("surrogate_map") or []
    names, seen = [], set()
    for row in rows:
        kw = (row.get("surrogate_is") or "").strip()
        if not kw:
            continue
        name = labelled_display_name(kw)
        if name not in seen:
            seen.add(name)
            names.append(name)
    # The injection standard quantifies the surrogates rather than a native, so
    # it appears in no surrogate_map row -- and its response is the one that
    # must NOT be dilution-corrected, which is precisely why it has to be in the
    # list rather than left out as "not a surrogate".
    for name in sorted(injection_is_names()):
        if name not in seen:
            seen.add(name)
            names.append(name)
    if names:
        return names
    if method_id == "FDA_32PFAS":
        return list(_FDA_IS_DISPLAY_NAMES)
    return []


def eis_criteria_name(method_id: str, compound: str) -> str:
    """The key under which `eis_overrides` holds `compound`'s recovery limits.

    Needed because a published method designates its extracted internal
    standards by ITS OWN spelling, and the lab's catalogue uses the spelling of
    the standard it actually buys. EPA 1633A Table 6 lists `13C4-PFBA`; the only
    thing that creates AnalysisServices (setupdata/internal_standards.csv)
    creates `13C3-PFBA`. Ten of the twenty-four diverge that way, so a lookup on
    the instrument's name found nothing for ten compounds and silently fell back
    to the generic window.

    The join is on the NATIVE the standard labels, never on the labelled name:

        instrument name -> keyword -> native (INTERNAL_STANDARDS row[2])
                        -> the Table 6 row whose designation labels that native

    That deliberately embeds NO claim that `13C3-PFBA` and `13C4-PFBA` are the
    same substance -- they are not, one carries three C-13 and the other four.
    It claims only that whatever the lab spikes as PFBA's extracted internal
    standard is judged against the method's limit FOR PFBA'S EIS, which is the
    relationship Table 6 actually states. Whether the lab should be buying the
    isotopologue EPA specifies is a purchasing question for the QA manager, and
    the ten names are listed in GAPS.md Sec30 for them to answer.

    Returns `compound` unchanged when no pairing is needed or possible: a method
    with no `eis_overrides` (FDA, 537.1) or a compound whose native has no
    Table 6 row. Never raises, and never invents a limit.
    """
    from .analyte_alias import (keyword_for, labeled_analog_map,
                                native_keyword_for)

    overrides = _profile_data_cache.get(method_id, {}).get("eis_overrides")
    if not overrides:
        return compound
    if isinstance(overrides, dict):
        if compound in overrides:
            return compound
        designations = list(overrides.keys())
    else:
        designations = [(r.get("analyte") or "") for r in overrides]
        if compound in designations:
            return compound

    analogs = labeled_analog_map()
    native = analogs.get(keyword_for(compound) or compound)
    if not native:
        return compound

    for designation in designations:
        if not designation:
            continue
        # Strip the isotopic label ("13C4-", "13C2,D4-", "D3-") to reach the
        # native the designation names, then normalise EPA's spelling of it.
        stripped = _ISOTOPE_LABEL.sub("", designation)
        if native_keyword_for(stripped) == native:
            return designation
    return compound


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
    """Return the active (summed) isomer groups for method_id.

    Each is ``{"linear", "branched", "branched_list", "reported", "enabled"}``:
    `reported` is the analyte KEYWORD the sum is imported under (the label a
    page shows may differ -- DECISIONS 2026-10-01); `branched_list` holds every
    branched peak, `branched` the first (for any reader still expecting one).

    Read from the method's `isomers` (the Isomers tab); a profile not yet
    migrated still carries the legacy `isomer_summation` pairs.
    """
    data = _profile_data_cache.get(method_id, {})
    groups = data.get("isomers")
    if isinstance(groups, dict):
        out = []
        for kw, e in groups.items():
            if not isinstance(e, dict):
                continue            # always summed: one analyte is reported
            branched = [b for b in (e.get("branched") or []) if b]
            if not (e.get("linear") or branched):
                continue
            out.append({"linear": e.get("linear") or "", "branched": branched[0] if branched else "",
                        "branched_list": branched, "reported": kw, "enabled": True})
        return out
    pairs = data.get("isomer_summation", []) or []
    out = []
    for p in pairs:
        if not p.get("enabled", True):
            continue
        p = dict(p)
        p["branched_list"] = [p["branched"]] if p.get("branched") else []
        out.append(p)
    return out


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


def get_labelled_roles(method_id: str = "FDA_32PFAS") -> dict:
    """{keyword: "surrogate" | "injection_is"} from the method's labelled-
    standards grid (DECISIONS 2026-09-30), or {} for a profile without one --
    callers then fall back to the global roles, as before the grid existed."""
    grid = _profile_data_cache.get(method_id, {}).get("labelled_standards")
    if not isinstance(grid, dict):
        return {}
    return dict((k, (v or {}).get("role")) for k, v in grid.items())


def get_injection_standards(method_id: str = "FDA_32PFAS") -> set:
    """Display names of this METHOD's injection standards (added after any
    dilution, so never dilution-corrected and not recovery-checked). The
    global roles are the fallback for a profile without a grid."""
    from .analyte_alias import injection_is_names, labelled_display_name
    roles = get_labelled_roles(method_id)
    if not roles:
        return injection_is_names()
    return set(labelled_display_name(k) for k, r in roles.items() if r == "injection_is")


def get_surrogate_is_chain(method_id: str = "FDA_32PFAS") -> dict:
    """Which standard each labelled standard is itself quantified against --
    its LINK in the method's grid (MS Quan style: any used standard may
    reference any other). Under FDA every surrogate links to M4PFOA.

    Read from `labelled_standards`; a profile not yet migrated still carries
    the legacy `surrogate_is_chain`."""
    data = _profile_data_cache.get(method_id, {})
    grid = data.get("labelled_standards")
    if isinstance(grid, dict):
        return dict((k, v["reference"]) for k, v in grid.items()
                    if isinstance(v, dict) and v.get("reference"))
    return dict(data.get("surrogate_is_chain", {}) or {})


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
        for name in [pair.get("linear")] + list(pair.get("branched_list") or []):
            if name:
                out[name] = factor
    return out


# Load profile data immediately if the export already exists
reload_from_profiles()
