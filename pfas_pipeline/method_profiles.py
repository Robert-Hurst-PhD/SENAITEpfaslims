"""
Method Profiles — per-method × per-analyte × per-matrix QC rule resolution.

Replaces the flat CRITERIA dict.  Every QC check resolves its limits through:

    profile = get_profile("FDA_32PFAS")
    rule = profile.qc_rules(analyte="PFOA", matrix="meat", qc_type="LFSM")
    rule.recovery_min, rule.recovery_max   # → 80.0, 120.0

Every method is ONE ConfiguredProfile(method_id) for each id in the exported
profiles. What differs between methods -- grouped recovery tiers, QC types
judged as another, the surrogate window the method text states, isotope-
dilution (EIS) limits per analyte and matrix class, which instrument
criteria must be configured, the notes each rule carries -- is the profile's
"Engine" section, read through senaite.pfas.method_engine (the add-on's own
module, loaded by path). A profile with no Engine settings has every feature
off.

Decision C: All rule logic reads from the stored profile JSON
loaded at batch start via reload_from_profiles(). Python classes are
interpreters, not sources of hardcoded values. Module-level constants
_FDA_BIG4, _FDA_NO_LABELED_STD, _FDA_TIGHT_MATRICES have been removed.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass
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
    fails_at_limit:   bool = False             # blanks: a result AT the limit fails


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
    frequency:     Optional[int]  # one CCV per N analytical samples (None: not set)
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


# ─────────────────────────────────────────────────────────────────────────────
# Keyword <-> display name (instrument export format, MassLynx compound names).
#
# The ZODB store's analyte_matrix_inclusion uses KEYWORDS as dict keys
# while the exported panel uses DISPLAY NAMES (e.g. "GenX (HFPO-DA)") to match
# instrument export.  The map below bridges them. PFOS/PFHxS are reported
# under their plain names since 2026-10-01; "lr-" names only their linear peak.
# ─────────────────────────────────────────────────────────────────────────────

# Analyte keyword → instrument display name (only entries that differ)
_KW_TO_DISPLAY: dict = {
    "GenX":        "GenX (HFPO-DA)",
    "4:2FTS":      "4:2 FTS",
    "8:2FTS":      "8:2 FTS",
    "10:2FTS":     "10:2 FTS",
    "9ClPF3ONS":   "9Cl-PF3ONS",
    "11ClPF3OUdS": "11Cl-PF3OUdS",
}
# Reverse: display name → keyword (for inclusion-matrix lookup)
_DISPLAY_TO_KW: dict = {v: k for k, v in _KW_TO_DISPLAY.items()}

# ─────────────────────────────────────────────────────────────────────────────
# Profile data cache — populated ONLY from the exported method profiles
# (/data/qc/method_profiles.json, written by SENAITE on every profile save) at
# batch start via reload_from_profiles(). There are NO built-in criteria: a
# method missing from the export is not configured, and run_pipeline refuses
# it rather than judging with numbers the lab never set (QC consolidation P1;
# the inline defaults that used to sit here carried an FDA LCS tier, 1633A
# FTS EIS limits and a retired QC-type list that no live profile had).
# ─────────────────────────────────────────────────────────────────────────────

_LOADED = set()          # methods whose data came from the export
# {method_id: the loaded data} exported before the Engine settings: refused
# while that data is what the cache holds
_STALE = {}


def profile_stale(method_id):
    """True when `method_id`'s loaded export predates the Engine settings."""
    data = _STALE.get(method_id)
    return data is not None and data is _profile_data_cache.get(method_id)


def profile_configured(method_id):
    """True when `method_id`'s criteria were loaded from the exported file."""
    return method_id in _LOADED


# {method_id: profile data}: every method in the export, no built-in one
_profile_data_cache = {}


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

    if not isinstance(all_profiles, dict):
        logger.error("reload_from_profiles: %s is not a JSON object", profiles_path)
        _LOADED.clear()
        return
    # every method in the export, whatever its id; a method no longer in it
    # is no longer configured
    exported = [m for m, d in all_profiles.items() if isinstance(d, dict)]
    for method_id in list(_profile_data_cache.keys()):
        if method_id not in all_profiles:
            _profile_data_cache.pop(method_id, None)
            _STALE.pop(method_id, None)
            if method_id in _LOADED:
                _LOADED.discard(method_id)
                logger.error(
                    "reload_from_profiles: %r not in %s; that method is not "
                    "configured", method_id, profiles_path)
    for method_id in exported:
        data = all_profiles[method_id]
        # Phase B: normalize eis_overrides from store list format to dict.
        # Store saves [{analyte, recovery_min, recovery_max}, ...] (UI-friendly);
        # the engine uses {analyte: {recovery_min, recovery_max}} for fast lookup.
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
        # SENAITE exports every profile with its Engine section (empty =
        # every feature off). A profile without one was exported before the
        # Engine settings existed: it is not judged with its features
        # silently off, it is refused until SENAITE re-exports it.
        if "engine" not in data:
            _STALE[method_id] = data
            _LOADED.discard(method_id)
            logger.error("reload_from_profiles: %s in %s predates the Engine "
                         "settings; it is not configured until SENAITE is "
                         "restarted and exports it again", method_id, profiles_path)
            continue
        _STALE.pop(method_id, None)
        _LOADED.add(method_id)
        logger.info("Loaded profile data for %s from %s",
                    method_id, profiles_path)

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
# copy here would be the "dead twin" shape this project has removed twice;.
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
# (this module's own docstring) declared authoritative:
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
# pre-existing behaviour, not introduced here (records it).
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

    Deliberately all-or-nothing ('s partial-write shape, one
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
    # the project's specs first, then the QAPP criteria
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
        # the Reporting Limits entry, else the lowest calibrator -- the
        # add-on's own rule, loaded from its file
        return _cal().reporting_limit(data, matrix, kw), num(entry.get("mdl")), unit

    # ── the judged value ────────────────────────────────────────
    # every result and QC check judges the ROUNDED value, the
    # value the report states. The rule and significant figures are the
    # method x matrix Reporting format (exported from the ISSUED reporting-
    # template revision); QC percentages are judged as whole percents.
    # rounding.py and report_format.py are the add-on's own files.

    def rounding(self, matrix=""):
        """(rule, significant figures) for this method x matrix."""
        from .addon import load
        data = self._profile_data()
        # the matrix as the certificate names it (report_limits.canonical_
        # matrix: exact title, then the profile's aliases), so a per-matrix
        # rule is the same row on both sides
        matrix = load("report_limits").canonical_matrix(data, matrix or "")
        fmt = load("report_format").resolve(data, matrix)
        try:
            n = int(fmt.get("coa_sig_figs") or 3)
        except (TypeError, ValueError):
            n = 3
        return (fmt.get("coa_rounding") or load("rounding").DEFAULT_RULE), n

    def judged_rule(self, matrix=""):
        """What a run records it was judged with: "epa;3;pct0"."""
        from .addon import load
        rule, n = self.rounding(matrix)
        return load("rounding").judged_rule(rule, n)

    def judged_pct(self, value, matrix=""):
        """A QC percentage as judged: a whole percent by the rule (None stays
        None)."""
        from .addon import load
        if value is None:
            return None
        return load("rounding").judged_pct(value, self.rounding(matrix)[0])

    def judged_conc(self, value, matrix=""):
        """A measured concentration as judged: the reported significant
        figures by the rule (None stays None)."""
        from .addon import load
        if value is None:
            return None
        rule, n = self.rounding(matrix)
        return load("rounding").judged_conc(value, n, rule)

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

    def sample_factor(self, matrix):
        return None

    def _profile_data(self):
        return _profile_data_cache.get(self.method_id, {})

    def ccv_opens_run(self):
        """True when a CCV must come before the run's first counting
        injection (EPA 537.1 §10.3). Calibration & CCV; off = as before."""
        return (self._iv().get("ccv") or {}).get("opens_run") in (True, "yes")

    def ccv_counts_extracted_qc(self):
        """True (as before) when extracted QC counts toward the "CCV every N"
        interval; False when only field samples do (EPA 537.1 §10.3).
        Calibration & CCV."""
        return (self._iv().get("ccv") or {}).get("counts_extracted_qc") != "no"

    def lfsmd_rpd_from_concentrations(self):
        """True when the LFSM/LFSMD RPD is of the two measured concentrations
        (EPA 537.1 §9.3.7.3); otherwise of their recoveries, as before.
        Recovery Tiers, LFSMD RPD."""
        return self._profile_data().get("lfsmd_rpd_basis") == "concentration"

    def surrogate_recovery_in_ccv(self):
        """True when the method's CCVs carry the surrogates and their recovery
        is judged there (EPA 537.1 §9.3.5.1). Calibration & CCV."""
        return (self._iv().get("ccv") or {}).get("surrogate_recovery") in (True, "yes")

    def icv_same_as_ccv(self):
        """True when the method judges its ICV / QCS with the CCV's window
        (EPA 537.1 §9.3.10: "acceptance criteria for the QCS are identical to
        the CCCs";). Calibration & CCV, ICV criteria."""
        return (self._iv().get("icv") or {}).get("criteria") == "ccv"

    def icv_pct_dev_max(self):
        """The ICV's (EPA 537.1: QCS) allowed deviation from its expected
        concentration, % (Calibration & CCV); None when not set. Read by
        nothing until 2026-10-07: no check judged an ICV at all."""
        v = (self._iv().get("icv") or {}).get("pct_dev_max")
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

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

    def resolve_spike(self, qc_type, level_label, matrix=None):
        """(value, unit): the method's spike level for qc_type + level in the
        matrix's reporting unit (2026-10-06: levels are entered in it),
        or (None, unit) when not set. Never another matrix's level.

        spike_levels may be in the old flat format {LFB:[...], LFSM:[...]}
        (method-wide, stored in ppt) or per matrix {matrix: {LFB:[...]}}."""
        data = self._profile_data()
        spike_levels = data.get("spike_levels", {})
        unit = (data.get("unit_map") or {}).get(matrix or "", "") or ""
        if "LFB" in spike_levels or "LFSM" in spike_levels:
            levels = spike_levels.get(qc_type, [])
        elif matrix and matrix in spike_levels:
            levels = spike_levels[matrix].get(qc_type, [])
        else:
            # Never another matrix's level: it used to fall
            # back to the first matrix listed, so a batch could be judged at a
            # level set for a different matrix without anyone seeing it.
            levels = []
        for entry in levels:
            if entry.get("label", "").strip().lower() == (level_label or "").strip().lower():
                return _cal().level_value(entry, unit), unit
        return None, unit


# ─────────────────────────────────────────────────────────────────────────────
# Refusal, and the rule helpers every method shares
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
    "tight_matrices", "low_level_x_rl", "citation", "fails_at_limit",
])

# ── Low-level tiers ───────────────────────────────────
# A tier carrying low_level_x_rl = N applies only when the fortified
# concentration is at or below N x the analyte's RL -- e.g. EPA 537.1 v2.0
# §9.3.6.3: LFSM 70-130%, but 50-150% "within a factor of 2-times the MRL".
# The ordinary tier is chosen exactly as before; a low-level tier replaces it
# only when its condition holds. Without the concentration or the RL the
# engine refuses: it never guesses which window a spike belongs to.
LOW_LEVEL_KEY = "low_level_x_rl"

def _cal():
    """senaite.pfas.calibration_levels, loaded from the add-on (pfas_pipeline.
    addon) -- the RL rule lives once."""
    from .addon import load
    return load("calibration_levels")


def _qc_tiers():
    """senaite.pfas.qc_tiers: which tier applies, chosen once for the run QC
    here and for the method studies in the add-on."""
    from .addon import load
    return load("qc_tiers")


def _ordinary_tiers(tiers):
    return _qc_tiers().ordinary_tiers(tiers)


def _low_level_tier(tiers, base, applies, conc, rl, where):
    """The low-level tier whose condition holds (smallest N first), else
    `base`. Refuses when one could apply but conc/RL are unknown."""
    qt = _qc_tiers()
    try:
        return qt.low_level_tier(tiers, base, applies, conc, rl, where)
    except qt.Unconfigured as e:
        raise UnconfiguredCriterion(str(e))


def _select_tier(profile_data, qc_type, analyte, matrix, conc, rl,
                 is_key, is_no_std, where):
    qt = _qc_tiers()
    try:
        return qt.select_tier(profile_data, qc_type, analyte, matrix, conc, rl,
                              is_key, is_no_std, where)
    except qt.Unconfigured as e:
        raise UnconfiguredCriterion(str(e))


def _analyte_groups(analyte, profile_data):
    """(is_key, is_no_std) for this method. "No labelled standard" comes from
    the method's own surrogate links; key analytes are the method's own list,
    else the global flag."""
    from .analyte_alias import no_labelled_names_for, key_analyte_names, keyword_for
    own_keys = profile_data.get("key_analytes")
    if isinstance(own_keys, list):
        keys = set(own_keys)
        is_key = (keyword_for(analyte) or analyte) in keys or analyte in keys
    else:
        is_key = analyte in key_analyte_names()
    return is_key, analyte in no_labelled_names_for(profile_data)


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
        fails_at_limit=bool(tier.get("fails_at_limit")),
    )


def _name_list(value):
    """A list setting typed as text ("PFBA, PFPeA") or stored as a list."""
    if isinstance(value, (list, tuple)):
        return tuple(v.strip() for v in value if v and v.strip())
    return tuple(v.strip() for v in (value or "").replace(";", ",").split(",") if v.strip())


def _ccv_rule(ccv, method_id):
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
        # no code value stands in for the profile's: an unset frequency is
        # None (the CCV-frequency check reports it), an unset low-level
        # window means the method sets none
        frequency=int(ccv["frequency"]) if ccv.get("frequency") not in (None, "", 0) else None,
        low_level_min=ccv.get("low_level_min"),
        low_level_max=ccv.get("low_level_max"),
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


def _engine_module():
    """senaite.pfas.method_engine: a method's Engine settings, read the same
    way here and in the add-on."""
    from .addon import load
    return load("method_engine")


def _limit_or(value, fallback):
    """A stored limit as float, or the fallback when it is unset (None)."""
    return fallback if value is None else float(value)


_SURROGATE_WINDOW_NOTE = "Surrogate recovery (method profile)"
_LABELLED_PREFIXES = ("M", "13C")


class ConfiguredProfile(MethodProfile):
    """Every method's rules, from its exported profile. What differs between
    methods is the profile's Engine section (senaite.pfas.method_engine);
    with none, every feature is off and nothing is borrowed from another
    method."""

    def __init__(self, method_id):
        self.method_id = method_id

    @property
    def description(self):
        data = self._profile_data()
        return (data.get("description") or data.get("display_name")
                or data.get("title") or self.method_id)

    def engine(self):
        return _engine_module().engine(self._profile_data())

    # ── recovery / blank / duplicate QC ─────────────────────────
    def qc_rules(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
        data = self._profile_data()
        eng = _engine_module().engine(data)
        if eng["eis_recovery_limits"] and qc_type in ("EIS", "SUR", "surrogate"):
            return self._eis_rule(data, eng, analyte, matrix)
        if qc_type in ("SUR", "surrogate"):
            return self._surrogate_rule(data, eng)
        mapped = eng["qc_type_aliases"].get(qc_type, qc_type)
        grouped = eng["grouped_recovery_tiers"]
        if grouped:
            is_key, is_no_std = _analyte_groups(analyte, data)
            shown = matrix or "(no matrix)"
        else:
            is_key, is_no_std = False, False
            shown = matrix
        where = "{0} / {1} / {2} / {3}".format(self.method_id, analyte, shown, mapped)
        chosen = _select_tier(data, mapped, analyte, matrix, conc, rl,
                              is_key, is_no_std, where)
        if chosen is None:
            return None
        tier, branch = chosen
        rule = _tier_rule(tier, self._tier_notes(eng, tier, branch), self.method_id,
                          analyte, matrix, mapped)
        if tier.get("verify_against_method"):
            rule = dataclasses.replace(rule, verify_against_method=True)
        return rule

    @staticmethod
    def _tier_notes(eng, tier, branch):
        """The note a tier's rule carries: the Engine's note for the tier's
        branch when it sets one (grouped tiers), else the tier's own
        description, else the Engine's general tier note."""
        notes = eng["rule_notes"]
        if tier.get(LOW_LEVEL_KEY):
            if "tier_low_level" in notes:
                text = notes["tier_low_level"]
                try:
                    text = text.format(float(tier[LOW_LEVEL_KEY]))
                except (IndexError, KeyError, ValueError):
                    pass
                return tier.get("description") or text
        elif "tier_" + branch in notes:
            return notes["tier_" + branch]
        return tier.get("description", notes.get("tier", ""))

    def _surrogate_rule(self, data, eng):
        """The profile's surrogate window (Calibration & CCV), else the window
        the method text states (Engine), else a refusal."""
        kw = {"is_guidance_only": True} if eng["surrogate_guidance_only"] else {}
        win = (data.get("instrument_verification") or {}).get("surrogate_window") or {}
        if win.get("recovery_min") is not None and win.get("recovery_max") is not None:
            return QCRule(float(win["recovery_min"]), float(win["recovery_max"]),
                          notes=_SURROGATE_WINDOW_NOTE, **kw)
        fallback = eng["surrogate_fallback"]
        if fallback is None:
            raise UnconfiguredCriterion(
                "{0} has no surrogate recovery window. Set it in Method Profiles "
                "-> Calibration & CCV (Surrogate recovery min / max), or the "
                "method text's window in Method Profiles -> Engine.".format(self.method_id))
        return QCRule(fallback["min"], fallback["max"], notes=fallback["citation"], **kw)

    def _eis_window(self, data, eng, analyte, matrix):
        """(low, high) every extracted standard starts from, before its own
        and its matrix class's limits."""
        window = eng["eis_default_window"]
        if window == "lfsm_tier":
            qa = data.get("qc_acceptance") or {}
            tiers = (qa.get("LFSM") or {}).get("tiers") or []
            if not tiers:
                raise UnconfiguredCriterion(
                    "{0} has no qc_acceptance.LFSM.tiers to base EIS recovery "
                    "on. Configure it in Method Profiles -> QC Types -> "
                    "LFSM.".format(self.method_id))
            # Refuse rather than substituting a window: the method's own LFSM
            # tier is the base, or nothing is
            base = _tier_rule(tiers[0], "", self.method_id, analyte, matrix, "EIS")
            if base.recovery_min is None:
                raise UnconfiguredCriterion(
                    "{0} / {1}: EIS recovery needs a recovery window on "
                    "qc_acceptance.LFSM, which specifies none.".format(
                        self.method_id, analyte))
            return float(base.recovery_min), float(base.recovery_max)
        if window == "surrogate_window":
            win = (data.get("instrument_verification") or {}).get("surrogate_window") or {}
            if win.get("recovery_min") is None or win.get("recovery_max") is None:
                raise UnconfiguredCriterion(
                    "{0} / {1}: EIS recovery starts from the surrogate window, "
                    "which is not set. Set it in Method Profiles -> Calibration "
                    "& CCV (Surrogate recovery min / max).".format(self.method_id, analyte))
            return float(win["recovery_min"]), float(win["recovery_max"])
        raise UnconfiguredCriterion(
            "{0}: isotope-dilution (EIS) limits are on, but no default EIS window "
            "is chosen. Choose one in Method Profiles -> Engine.".format(self.method_id))

    def _eis_rule(self, data, eng, analyte, matrix):
        """EIS / surrogate recovery per analyte x matrix class."""
        default_lo, default_hi = self._eis_window(data, eng, analyte, matrix)
        eis_overrides = data.get("eis_overrides", {})
        eis_matrix = data.get("eis_matrix_overrides", {})
        # `analyte` is the compound as the INSTRUMENT names it, which is the
        # compound the lab actually spiked. A published method may designate
        # the same position by its own labelled form, so the lookup joins
        # through the native (eis_criteria_name). The rule keeps `analyte`
        # unchanged, so a certificate names the compound the lab has.
        criteria_name = eis_criteria_name(self.method_id, analyte)
        override = eis_overrides.get(criteria_name, {})
        # A limit stored as null is UNSET: it falls back, never float(None).
        lo = _limit_or(override.get("recovery_min"), default_lo)
        hi = _limit_or(override.get("recovery_max"), default_hi)
        if matrix:
            mat_class = _engine_module().matrix_class(data, matrix)
            if mat_class:
                mat_override = (eis_matrix.get(mat_class) or {}).get(criteria_name)
                if mat_override:
                    lo = _limit_or(mat_override.get("recovery_min"), lo)
                    hi = _limit_or(mat_override.get("recovery_max"), hi)
        return QCRule(lo, hi, verify_against_method=eng["eis_verify_flag"],
                      notes=eng["rule_notes"].get("eis", ""))

    # ── instrument criteria ─────────────────────────────────────
    def _criterion(self, eng, rule, section, key, where):
        """One instrument criterion: refused when the Engine requires it and
        it is absent, else as stored (absent = None)."""
        if key in (eng["required_keys"].get(rule) or ()):
            return _required(section, key, self.method_id, rule, where)
        return section.get(key)

    def calibration_rule(self, analyte=""):
        data = self._profile_data()
        eng = _engine_module().engine(data)
        cal = _calibration(data, self.method_id)
        where = " -> Calibration & CCV"
        # r2_min decides whether a curve is acceptable at all: a rule cannot
        # be built without it, whatever the Engine lists
        r2 = _required(cal, "r2_min", self.method_id, "calibration", where)
        point = self._criterion(eng, "calibration", cal, "point_pct_dev_max", where)
        low_point = self._criterion(eng, "calibration", cal, "low_point_pct_dev_max", where)
        fit = "linear"
        if (eng["labelled_compound_fit"] == "mean_response_factor"
                and (analyte or "").startswith(_LABELLED_PREFIXES)):
            fit = "mean_response_factor"
        return CalibrationRule(
            r2_min=float(r2),
            point_pct_dev_max=point,
            low_point_pct_dev_max=low_point,
            force_origin=bool(cal.get("force_origin", False)),
            default_fit=fit,
            default_weighting="none" if fit != "linear" else "1/x",
        )

    def ccv_rule(self):
        return _ccv_rule(self._iv().get("ccv", {}), self.method_id)

    def is_rule(self):
        data = self._profile_data()
        eng = _engine_module().engine(data)
        is_ = _is_section(data, self.method_id)
        where = " -> Calibration & CCV -> IS Response"
        get = lambda k: self._criterion(eng, "is_response", is_, k, where)  # noqa: E731
        return ISRule(
            vs_ical_avg_min=get("vs_ical_avg_min"),
            vs_ical_avg_max=get("vs_ical_avg_max"),
            vs_last_ccv_min=get("vs_last_ccv_min"),
            vs_last_ccv_max=get("vs_last_ccv_max"),
            notes=eng["rule_notes"].get("is_rule", ""),
        )

    def confirmation_rule(self):
        data = self._profile_data()
        eng = _engine_module().engine(data)
        conf = _confirmation(data, self.method_id)
        where = " -> Calibration & CCV"
        get = lambda k: self._criterion(eng, "confirmation", conf, k, where)  # noqa: E731
        # evaluated in this order: the first missing criterion is the one named
        ion_ratio = get("ion_ratio_tol_pct")
        rrt = get("rrt_tol_pct")
        rt_abs = get("rt_tol_abs_min")
        sn_quant = get("sn_quan_min")
        sn_confirm = get("sn_confirm_min")
        # single_transition_analytes, confirm_pct_diff_max and the technique
        # are the lab's settings, on the profile (Calibration & CCV)
        return ConfirmationRule(
            ion_ratio_tol_pct=ion_ratio,
            rrt_tol_pct=rrt,
            rt_tol_abs_min=rt_abs,
            sn_min_quant=sn_quant,
            sn_min_confirm=sn_confirm,
            single_transition_analytes=_name_list(conf.get("single_transition_analytes")),
            confirm_pct_diff_max=conf.get("confirm_pct_diff_max"),
            confirm_technique=(conf.get("confirm_technique") or "LC-HRMS").strip(),
            notes=eng["rule_notes"].get("confirmation_rule", ""),
        )

    def sample_factor(self, matrix):
        # Matrix factors are keyed by the core SampleType title. Match the
        # sample's matrix EXACTLY first; fall back to legacy substring matching
        # for any old-format entries that predate the core-type tie.
        m = (matrix or "").lower().strip()
        factors = self._profile_data().get("matrix_factors", []) or []
        for entry in factors:
            if (entry.get("matrix", "") or "").lower().strip() == m:
                return float(entry["factor"])
        for entry in factors:
            key = (entry.get("matrix", "") or "").lower().strip()
            if key and key in m:
                return float(entry["factor"])
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Registry: every method in the export, by its id or one of its aliases
# ─────────────────────────────────────────────────────────────────────────────

def _id_key(name):
    return (name or "").strip().upper().replace(" ", "")


def resolve_method_id(method):
    """The exported method id `method` names (its id, any case, or one of its
    Engine aliases), or None."""
    key = _id_key(method)
    if not key:
        return None
    for pid in _profile_data_cache:
        if _id_key(pid) == key:
            return pid
    eng = _engine_module()
    for pid, data in _profile_data_cache.items():
        if key in [_id_key(a) for a in eng.engine(data)["aliases"]]:
            return pid
    return None


def get_profile(method):
    pid = resolve_method_id(method)
    if pid is None:
        raise KeyError(
            "No method profile {!r} among the exported method profiles ({}). "
            "Save the method's profile in SENAITE (Method Profiles) so it is "
            "exported, or give the run its method's id.".format(
                method, ", ".join(sorted(_profile_data_cache)) or "none"))
    if profile_stale(pid):
        raise KeyError(
            "The exported method profile {0} predates the Engine settings; it is "
            "not used until SENAITE is restarted and exports it again.".format(pid))
    return ConfiguredProfile(pid)


def available_profiles():
    return dict((pid, ConfiguredProfile(pid).description) for pid in _profile_data_cache)


# ─────────────────────────────────────────────────────────────────────────────
# Analyte / IS list helpers — replace constants.ANALYTES / INTERNAL_STANDARDS
# ─────────────────────────────────────────────────────────────────────────────

def get_analyte_list(method_id: str) -> list:
    """Display-name ordered analyte list for method_id: the reported panel
    the export writes (``display_analyte_set``). Refuses when the export
    carries none -- no other method's panel stands in for it."""
    data = _profile_data_cache.get(method_id, {})
    explicit = data.get("display_analyte_set")
    if explicit is not None:
        return list(explicit)
    raise UnconfiguredCriterion(
        "{0} has no reported analyte panel (display_analyte_set) in the exported "
        "method profiles. Save the method's profile in SENAITE (Method Profiles) "
        "so it is exported with its analytes.".format(method_id or "(no method)"))


def get_sample_correction(method_id: str) -> str:
    """Where results are put on the sample basis:
    "" nominal matrix factor, "instrument" already done in the MS software,
    "lims" back-calculated per sample from the logged amount and volume."""
    data = _profile_data_cache.get(method_id, {}) or {}
    mode = (data.get("sample_correction") or "").strip()
    return mode if mode in ("instrument", "lims") else ""


def get_blank_subtraction(method_id: str) -> bool:
    """Whether the method subtracts the batch's method blank from each result
    (2026-10-08: a per-method switch; off by default)."""
    data = _profile_data_cache.get(method_id, {}) or {}
    return bool(data.get("blank_subtraction"))


def get_spike_basis(method_id: str) -> str:
    """"before" when spike levels are entered before the per-sample amount
    adjustment (scaled by nominal / actual amount), else "" (as entered).
    Sample correction tab; lab, 2026-10-10."""
    data = _profile_data_cache.get(method_id, {}) or {}
    return "before" if data.get("spike_basis") == "before" else ""


def get_nominal_amount(method_id: str, matrix: str):
    """(amount, unit) the matrix's spike levels assume, or (None, "")."""
    data = _profile_data_cache.get(method_id, {}) or {}
    v = (data.get("nominal_amounts") or {}).get(matrix) or {}
    try:
        amount = float(v.get("amount"))
    except (TypeError, ValueError):
        return None, ""
    return (amount, v.get("unit") or "g") if amount > 0 else (None, "")


def spike_scale(nominal, nominal_unit, actual_row):
    """nominal / actual amount for one spiked portion, or None (no recorded
    amount, or another unit)."""
    if not nominal or not actual_row:
        return None
    try:
        actual = float(actual_row.get("amount"))
    except (TypeError, ValueError):
        return None
    unit = (actual_row.get("amount_unit") or "g").strip().lower()
    if actual <= 0 or unit != (nominal_unit or "g").strip().lower():
        return None
    return nominal / actual


def get_mxb_reference_recovery(method_id: str) -> bool:
    """Whether a matrix blank whose lot carries reference values is judged as
    a recovery against them with the LFSM recovery tolerances (Method
    Profile > QC composition > Matrix blanks; off by default)."""
    data = _profile_data_cache.get(method_id, {}) or {}
    return bool(data.get("mxb_reference_recovery"))


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


def get_non_iso_set(method_id: str) -> frozenset:
    """Return the frozenset of analyte display names that have no labeled std.

    Derived from the method's surrogate links, limited to its reported panel.
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
    # Scope to the method's own panel so another method's analytes do not
    # leak in (no exported panel: the names as derived)
    try:
        panel = set(get_analyte_list(method_id) or [])
    except UnconfiguredCriterion:
        panel = set()
    return frozenset(names & panel) if panel else frozenset(names)


# Leading isotopic label on a labelled compound's name: "13C4-", "13C2,D4-",
# "D3-". Used ONLY to reach the native a published method's EIS designation
# refers to (see eis_criteria_name) -- never to decide that two labelled names
# mean the same compound.
_ISOTOPE_LABEL = re.compile(r"^(?:13C\d+|D\d+)(?:,\s*D\d+)?-")


def get_is_list(method_id: str) -> list:
    """Display names of the labelled compounds this METHOD monitors.

    DERIVED, not stored. This used to read a profile key `internal_standards`
    that NOTHING has ever written -- no editor field, no seed, no migration --
    and fall back to an inline FDA list. So it returned the 21 FDA names for
    FDA_32PFAS and an EMPTY LIST for both EPA methods, which meant the IS
    Response loop in run_queue iterated nothing and no surrogate or internal
    standard was checked at all on EPA 537.1 or EPA 1633A.

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

    Refuses when the method names no labelled standard at all: an empty list
    would check no surrogate or internal standard and say nothing.
    """
    from .analyte_alias import injection_is_names, labelled_display_name

    data = _profile_data_cache.get(method_id, {})
    grid = data.get("labelled_standards")
    if isinstance(grid, dict) and grid:
        # The method's own grid: every standard it
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
    raise UnconfiguredCriterion(
        "{0} names no labelled standard (surrogate or internal standard). Set "
        "them in Method Profiles -> Labelled Standards / Surrogate Map.".format(
            method_id or "(no method)"))


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
    the ten names are listed in for them to answer.

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
    _DISPLAY_TO_KW / _KW_TO_DISPLAY.  Default: included (True) when a
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
        keyword = _DISPLAY_TO_KW.get(display_name, display_name)
        matrix_map = inclusion.get(keyword, {})
        if matrix_map.get(matrix, True):
            result.append(display_name)
    return result


def get_isomer_summation(method_id: str) -> list:
    """Return the active (summed) isomer groups for method_id.

    Each is ``{"linear", "branched", "branched_list", "reported", "enabled"}``:
    `reported` is the analyte KEYWORD the sum is imported under (the label a
    page shows may differ --); `branched_list` holds every
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


def get_surrogate_map(method_id: str) -> dict:
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


def get_labelled_roles(method_id: str) -> dict:
    """{keyword: "surrogate" | "injection_is"} from the method's labelled-
    standards grid, or {} for a profile without one --
    callers then fall back to the global roles, as before the grid existed."""
    grid = _profile_data_cache.get(method_id, {}).get("labelled_standards")
    if not isinstance(grid, dict):
        return {}
    return dict((k, (v or {}).get("role")) for k, v in grid.items())


def get_injection_standards(method_id: str) -> set:
    """Display names of this METHOD's injection standards (added after any
    dilution, so never dilution-corrected and not recovery-checked). The
    global roles are the fallback for a profile without a grid."""
    from .analyte_alias import injection_is_names, labelled_display_name
    roles = get_labelled_roles(method_id)
    if not roles:
        return injection_is_names()
    return set(labelled_display_name(k) for k, r in roles.items() if r == "injection_is")


def get_surrogate_is_chain(method_id: str) -> dict:
    """Which standard each labelled standard is itself quantified against --
    its LINK in the method's grid (MS Quan style: any used standard may
    reference any other). Under FDA every surrogate links to 13C4-PFOA.

    Read from `labelled_standards`; a profile not yet migrated still carries
    the legacy `surrogate_is_chain`."""
    data = _profile_data_cache.get(method_id, {})
    grid = data.get("labelled_standards")
    if isinstance(grid, dict):
        return dict((k, v["reference"]) for k, v in grid.items()
                    if isinstance(v, dict) and v.get("reference"))
    return dict(data.get("surrogate_is_chain", {}) or {})


def get_salt_factors(method_id: str) -> dict:
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
