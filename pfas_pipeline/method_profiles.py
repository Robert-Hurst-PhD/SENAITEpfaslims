"""
Method Profiles — per-method × per-analyte × per-matrix QC rule resolution.

Every QC check resolves its limits through:

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

All rule logic reads the stored profile JSON loaded at batch start via
reload_from_profiles(). The classes interpret it; they hold no lab values.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
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
    # the tier's own state (limit_states): enforced, evaluate or off
    state:            str = "enforced"


@dataclass(frozen=True)
class CalibrationRule:
    r2_min:             Optional[float] = 0.99   # None: the method sets no r2 criterion
    point_pct_dev_max:  Optional[float] = None  # ±% each point vs curve
    low_point_pct_dev_max: Optional[float] = None  # looser limit at/below MRL
    force_origin:       bool = False         # origin == "force"
    default_fit:        str = "linear"
    default_weighting:  str = "1/x"
    origin:             str = "exclude"      # exclude | include | force (the method profile's)


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
    # How a single-transition positive is confirmed. FDA §10.2(4) cites LC-HRMS,
    # but a second column, another ionisation mode or another transition also
    # establish identity, so the lab names the technique and the prompt quotes it.
    confirm_technique: str = "LC-HRMS"
    confirm_pct_diff_max: Optional[float] = None  # HRMS vs MS/MS %diff
    notes: str = ""


# Keyword <-> display name (instrument export format, MassLynx compound names):
# the ZODB store's analyte_matrix_inclusion uses KEYWORDS as dict keys while
# the exported panel uses DISPLAY NAMES (e.g. "GenX (HFPO-DA)") to match the
# instrument export; the compound library's native names bridge them
# (analyte_alias.native_name_to_keyword).

# ─────────────────────────────────────────────────────────────────────────────
# Profile data cache: filled ONLY from the exported method profiles
# (/data/qc/method_profiles.json, written by SENAITE on every profile save) at
# batch start via reload_from_profiles(). There are NO built-in criteria: a
# method missing from the export is not configured, and run_pipeline refuses
# it rather than judging with numbers the lab never set.
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


def _eis_keyed(pairs, where):
    """{keyword: limits} from (name, limits) pairs: a name spelled as the
    library's published name or alias is keyed by its compound; when two
    names spell one compound the row under the keyword itself stands and the
    other is logged, never applied by dict order."""
    from .analyte_alias import LibraryUnavailable, keyword_of
    out, spelled = {}, {}
    for name, limits in pairs:
        try:
            kw = keyword_of(name) or name
        except LibraryUnavailable:        # a run without a library is refused at its start
            kw = name
        if kw == name:
            if name in spelled:
                logger.warning("%s: EIS rows %s and %s name one compound; %s applies",
                               where, spelled[name], name, name)
            out[kw] = limits
        elif kw in out:
            logger.warning("%s: EIS rows %s and %s name one compound; %s applies",
                           where, name, kw, kw)
        else:
            out[kw] = limits
            spelled[kw] = name
    return out


def reload_from_profiles(profiles_path=None, batch_id=None):
    """
    Reload _profile_data_cache from the exported method profile JSON.
    Called at the start of each batch run so changes made in the SENAITE
    Method Profile control panel take effect without a worker restart.
    A method missing from the file (or no file at all) is left EMPTY and
    unconfigured -- see profile_configured(); nothing falls back to defaults.

    `batch_id`, when given, overlays that batch's RESOLVED criteria
    (senaite.pfas.resolved_criteria_store, project -> lab -> baseline) on
    what the global file loaded. The add-on resolved the tiers before
    writing the file; this only copies the numbers into the cache shape
    (_apply_resolved_overlay).

    `batch_id=None`, or a batch with no resolved file on disk, never enters
    the overlay branch: no warning, no fallback.
    """
    if profiles_path is None:
        profiles_path = PROFILES_PATH

    # the compound library SENAITE exports with the profiles (beside them,
    # or PFAS_LIBRARY_PATH); a run refuses when it cannot be used
    from .analyte_alias import reload_library
    why = reload_library(profiles_path=profiles_path)
    if why:
        logger.error("reload_from_profiles: %s", why)

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
    # every method in the export, whatever its id; a method missing from it
    # is not configured
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
        # an export written before the rules held their flags: the Engine's
        # notes read from the rules that carry them (rule_flags.migrate)
        _rule_flags().migrate(data)
        # eis_overrides: the store's list [{analyte, recovery_min,
        # recovery_max}] becomes {keyword: {...}} for the lookup, every name
        # keyed by the compound it spells (_eis_keyed); the matrix classes
        # the same way.
        eis = data.get("eis_overrides")
        if isinstance(eis, list):
            data = dict(data)
            data["eis_overrides"] = _eis_keyed(
                [(e["analyte"], {"recovery_min": e.get("recovery_min"),
                                 "recovery_max": e.get("recovery_max")})
                 for e in eis if isinstance(e, dict) and "analyte" in e], method_id)
        classes = data.get("eis_matrix_overrides")
        if isinstance(classes, dict):
            data = dict(data)
            data["eis_matrix_overrides"] = dict(
                (cls, _eis_keyed(list(table.items()), "%s/%s" % (method_id, cls)))
                for cls, table in classes.items() if isinstance(table, dict))
        _profile_data_cache[method_id] = data
        # SENAITE exports every profile with its Engine section (empty =
        # every feature off). A profile without one is refused until SENAITE
        # re-exports it, never judged with its features silently off.
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
# The add-on (senaite.pfas.ruleset) resolves the tiers and writes ONE JSON
# file per project-linked batch beside method_profiles.json
# (senaite.pfas.resolved_criteria_store.export_resolved_criteria). This
# section injects each resolved value into _profile_data_cache at the key
# paths reload_from_profiles() fills. It resolves nothing: the tier logic
# lives once, in the add-on.
#
# The key -> path map mirrors senaite.pfas.ruleset.SHAPES_BY_KEY /
# _LAB_EXTRACTORS as a location copy only: the Python 3 worker must not
# import the Python 2.7 add-on package (as method_baselines.matrix_class()).
_OVERLAY_PATHS = {
    "cal_r2_min":  ("instrument_verification", "calibration", "r2_min"),
    "sn_quan_min": ("instrument_verification", "confirmation", "sn_quan_min"),
    "dup_rpd_max": ("qc_acceptance", "Dup", "tiers", 0, "rpd_max"),
}

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
    entry in _profile_data_cache). True if applied; False if the row has
    no value or its key is one this worker does not map, which is a no-op,
    not an error."""
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
    """A dict naming a criterion key. Structural only: whether the key means
    anything here is decided per row in _apply_resolved_row()."""
    return isinstance(row, dict) and isinstance(row.get("key"), str) and row.get("key")


def _load_resolved_payload(batch_id, profiles_path):
    """The parsed, structurally-validated resolved-criteria payload for
    batch_id, or None for every case that must leave the global profile
    untouched: no file (any batch with no linked project), an unreadable or
    corrupt file, or a file whose shape cannot be trusted.

    All or nothing: a wrong top-level shape or ANY malformed row rejects
    the WHOLE file, logged once, so no corrupt record leaves some criteria
    overridden and others not. A well-formed row with a key this worker
    does not map is a per-row no-op."""
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
    logger.info("Applied %d resolved (project-aware) criteria for batch %s (%s)",
                applied, batch_id, method_id)


# ─────────────────────────────────────────────────────────────────────────────
# Profile base
# ─────────────────────────────────────────────────────────────────────────────

class MethodProfile:
    """Base class.  Subclasses override the rule methods."""
    method_id: str = ""
    description: str = ""

    def qc_rules(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
        raise NotImplementedError

    def reporting_limits(self, analyte, matrix, acid_basis=None):
        """(rl, mdl, unit) for the analyte in `matrix`, in the matrix's
        reporting unit as configured; None for what is not set. `acid_basis`:
        the run's analytes calibrated from standards stated as the acid,
        whose default RL takes no salt factor."""
        from .analyte_alias import keyword_for
        data = self._profile_data()
        kw = keyword_for(analyte) or analyte
        entry = ((data.get("reporting_limits") or {}).get(matrix) or {}).get(kw) or {}
        unit = (data.get("unit_map") or {}).get(matrix) or ""
        num = lambda v: None if v is None else float(v)       # noqa: E731
        # the Reporting Limits entry, else the lowest calibrator -- the
        # add-on's own rule, loaded from its file
        return _cal().reporting_limit_for_run(data, matrix, kw, acid_basis), num(entry.get("mdl")), unit

    # ── the judged value ────────────────────────────────────────
    # every result and QC check judges the ROUNDED value, the
    # value the report states. The rule and significant figures are the
    # method x matrix Reporting format (exported from the ISSUED reporting-
    # template revision); QC percentages are judged as whole percents, a
    # recovery at the method's decimal places for recoveries (its Engine
    # setting, read from this profile). rounding.py, report_format.py and
    # method_engine.py are the add-on's own files.

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
        """What a run records it was judged with: "epa;3;pct0", the last
        part the places recoveries are judged at."""
        from .addon import load
        rule, n = self.rounding(matrix)
        return load("rounding").judged_rule(rule, n, self.recovery_places())

    def recovery_places(self):
        """The decimal places a recovery is judged and printed at: the
        Engine's recovery_decimals in this profile (method_engine), whole
        percent when unset."""
        from .addon import load
        return load("method_engine").recovery_decimals(self._profile_data())

    def judged_pct(self, value, matrix=""):
        """A QC percentage that is not a recovery (an RPD, an IS response)
        as judged: a whole percent by the rule (None stays None)."""
        from .addon import load
        if value is None:
            return None
        return load("rounding").judged_pct(value, self.rounding(matrix)[0])

    def judged_recovery(self, value, matrix=""):
        """A recovery (a spike, a surrogate, a CCV or ICV) as judged: at the
        method's decimal places for recoveries by the rule, so 69.6 at one
        place is judged as 69.6, not 70 (None stays None)."""
        from .addon import load
        if value is None:
            return None
        return load("rounding").judged_pct(value, self.rounding(matrix)[0], self.recovery_places())

    def recovery_text(self, judged):
        """A judged recovery as an issue text prints it: "69.6"."""
        return "{0:.{1}f}".format(judged, self.recovery_places())

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

    def max_cal_dropped(self):
        """The most calibrators of one analyte's curve the analyst may drop by
        deleting a peak in a raw run (Calibration & CCV); None: no limit."""
        return None

    def limit_state(self, key):
        """A limit box's state (limit_states.box_state): enforced, evaluate
        or off."""
        return _limits_module().box_state(self._profile_data(), key)

    def limit_judged(self, key):
        """Whether box `key` is judged: not Off, applying to the method and
        holding a limit."""
        ls = _limits_module()
        data, box = self._profile_data(), ls.BOX[key]
        return (ls.box_state(data, key) != "off" and ls.applies(data, box)
                and not ls.is_empty(data, box))

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
 injection (EPA 537.1 §10.3). Calibration & CCV."""
        return (self._iv().get("ccv") or {}).get("opens_run") in (True, "yes")

    def ccv_counts_extracted_qc(self):
        """True (the default) when extracted QC counts toward the "CCV every N"
 interval; False when only field samples do (EPA 537.1 §10.3).
        Calibration & CCV."""
        return (self._iv().get("ccv") or {}).get("counts_extracted_qc") != "no"

    def lfsmd_rpd_from_concentrations(self):
        """Always True: the LFSM/LFSMD RPD is of the two measured
        concentrations for every method (EPA 537.1 §9.3.7.3). Recovery
        Tiers, LFSMD RPD."""
        return True

    def surrogate_recovery_in_ccv(self):
        """True when the method's CCVs carry the surrogates and their recovery
        is judged there (EPA 537.1 §9.3.5.1). Calibration & CCV."""
        return (self._iv().get("ccv") or {}).get("surrogate_recovery") in (True, "yes")

    def has_blank_limit(self, qc_type):
        """True when the method sets this blank type a limit of its own
        (Blank limits: an enabled type with a tier carrying x RL). A row the
        grid cleared keeps its tier without a limit: that is no row."""
        entry = (self._profile_data().get("qc_acceptance") or {}).get(qc_type)
        if not isinstance(entry, dict) or self.qc_type_state(qc_type) == "off":
            return False
        return any(isinstance(t, dict) and t.get("max_conc_x_rl") not in (None, "")
                   for t in entry.get("tiers") or [])

    def ccv_surrogate_window(self):
        """(min, max) % the labelled standards' recovery is judged by in a
        CCV when the method gives them a window of their own there
        (Calibration & CCV); None when neither end is set, so the sample
        window applies. One end set without the other is refused,
        never an open interval and never a fall back to the sample window."""
        ccv = self._iv().get("ccv") or {}
        if self.limit_state("surrogate_ccv") == "off":
            return None                  # its own window is not judged: the sample window applies
        lo, hi = ccv.get("surrogate_window_min"), ccv.get("surrogate_window_max")
        lo = None if lo in (None, "") else float(lo)
        hi = None if hi in (None, "") else float(hi)
        if lo is None and hi is None:
            return None
        if lo is None or hi is None:
            raise UnconfiguredCriterion(
                "{0}: the CCV window for labelled standards has only one end set. "
                "Set both on the method's QC criteria tab (CCV Recovery, Surrogate "
                "recovery min and max in CCVs), or clear both to judge CCVs with the sample "
                "window.".format(self.method_id))
        return lo, hi

    def ccv_recovery_rule(self, rule):
        """The rule a labelled standard's recovery in a CCV is judged by: the
        sample rule with the CCV window when one is set, else the sample rule
        itself. Raises UnconfiguredCriterion for a half-set window."""
        window = self.ccv_surrogate_window()
        if window is None or rule is None:
            return rule
        return dataclasses.replace(rule, recovery_min=window[0], recovery_max=window[1],
                                   notes=_CCV_SURROGATE_WINDOW_NOTE)

    def icv_same_as_ccv(self):
        """True when the method judges its ICV / QCS with the CCV's window
        (EPA 537.1 §9.3.10: "acceptance criteria for the QCS are identical to
        the CCCs"). Calibration & CCV, ICV criteria."""
        return (self._iv().get("icv") or {}).get("criteria") == "ccv"

    def icv_pct_dev_max(self):
        """The ICV's (EPA 537.1: QCS) allowed deviation from its expected
        concentration, % (Calibration & CCV); None when not set."""
        v = (self._iv().get("icv") or {}).get("pct_dev_max")
        if self.limit_state("icv") == "off":
            return None
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _iv(self):
        """The instrument_verification block; a profile without one keeps
        those keys at its top level."""
        p = self._profile_data()
        iv = p.get("instrument_verification")
        if iv is not None:
            return iv
        return p

    def qc_type_enabled(self, qc_code):
        """Is this extraction/matrix QC type switched on for this method?

        The ONE definition of the lab's switch, set in the Method Profile UI
        beside the limits it governs. On unless its row's state
        (qc_type_state) is Off. A missing entry is on: an unconfigured check
        refuses to judge, which is louder than skipping.
        """
        return self.qc_type_state(qc_code) != "off"

    def qc_type_state(self, qc_code):
        """The state of this QC type's row: enforced, evaluate or off. The
        profile's `rule_states` under the type's row key (`qc_type.<CODE>`,
        or `blank.<CODE>` for a blank, the type's stored spelling), else its
        `enabled` flag (on = enforced, off = off); absent is enforced. A type
        in Evaluate is judged and a failure files as advisory."""
        data = self._profile_data()
        ls = _limits_module()
        if not isinstance((data.get("qc_acceptance") or {}).get(qc_code), dict):
            # a type the method does not hold reads its row as stored, else
            # Enforced: an unconfigured check refuses to judge, which is
            # louder than skipping
            key = ls._rules().qc_row_key(qc_code)
            return ls._legacy(data, key) if key else "enforced"
        return ls.qc_type_state(data, qc_code)

    def low_level_state(self):
        """The Low-level recoveries row's state: enforced, evaluate or off,
        the profile's `rule_states["low_level_recovery"]`; absent is
        enforced. It decides how a recovery judged against a low-level tier
        is filed: Enforced holds, Evaluate is advisory, Off judges nothing."""
        data = self._profile_data()
        ls = _limits_module()
        lows = [ls.tier_state(data, code, t)
                for code, entry in sorted((data.get("qc_acceptance") or {}).items()) if isinstance(entry, dict)
                for t in entry.get("tiers") or [] if isinstance(t, dict) and t.get(LOW_LEVEL_KEY)]
        return ls.either(lows) if lows else "enforced"

    def qc_acceptance_rule(self, qc_code, analyte="", matrix=""):
        """
        Return a QCRule for a specific QC type from qc_acceptance.
        Returns None when the QC type is not associated or is disabled.
        """
        qa = self._profile_data().get("qc_acceptance", {})
        entry = qa.get(qc_code)
        if entry is None or self.qc_type_state(qc_code) == "off":
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
        matrix's reporting unit, the unit levels are entered in, or
        (None, unit) when not set. Never another matrix's level.

        spike_levels is flat {LFB:[...], LFSM:[...]} (method-wide, stored in
        ppt) or per matrix {matrix: {LFB:[...]}}."""
        data = self._profile_data()
        spike_levels = data.get("spike_levels", {})
        unit = (data.get("unit_map") or {}).get(matrix or "", "") or ""
        if "LFB" in spike_levels or "LFSM" in spike_levels:
            levels = spike_levels.get(qc_type, [])
        elif matrix and matrix in spike_levels:
            levels = spike_levels[matrix].get(qc_type, [])
        else:
            # never another matrix's level
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

    Raised instead of substituting a plausible default: a criterion nothing
    configured must not be quietly met. It hard-blocks a run against a
    profile that is not fully populated; the message names what to
    configure and where.
    """


# Keys that describe WHICH rows a tier applies to, rather than what it judges.
_TIER_STRUCTURAL_KEYS = frozenset([
    "name", "analyte_group", "matrix_scope", "description",
    "verify_against_method", "tier", "key_analytes", "no_std_analytes",
    "tight_matrices", "matrices", "low_level_x_rl", "citation", "fails_at_limit",
    # the tier's flag (rule_flags): its code, place and note, never a criterion
    "flag",
    # the tier's own state (limit_states), never a criterion
    "state",
])

# ── Low-level tiers ───────────────────────────────────
# A tier carrying low_level_x_rl = N applies only when the fortified
# concentration is at or below N x the analyte's RL -- e.g. EPA 537.1 v2.0
# §9.3.6.3: LFSM 70-130%, but 50-150% "within a factor of 2-times the MRL".
# A low-level tier replaces the ordinary tier only when its condition holds. Without the concentration or the RL the
# engine refuses: it never guesses which window a spike belongs to.
LOW_LEVEL_KEY = "low_level_x_rl"

def _cal():
    """senaite.pfas.calibration_levels, loaded from the add-on (pfas_pipeline.
    addon) -- the RL rule lives once."""
    from .addon import load
    return load("calibration_levels")


def _rule_flags():
    """senaite.pfas.rule_flags: each rule's flag, read as the add-on reads it."""
    from .addon import load
    return load("rule_flags")


def _qc_tiers():
    """senaite.pfas.qc_tiers: which tier applies, chosen once for the run QC
    here and for the method studies in the add-on."""
    from .addon import load
    return load("qc_tiers")


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
    """The tier a run judges `analyte` (as the instrument names it) by; a
    setting on one analyte's cell is found by the analyte's keyword."""
    from .analyte_alias import keyword_for
    try:
        keyword = keyword_for(analyte) or analyte
    except Exception:                       # noqa: BLE001  (no library: a run refuses at its start)
        keyword = analyte
    qt = _qc_tiers()
    try:
        return qt.select_tier(profile_data, qc_type, analyte, matrix, conc, rl,
                              is_key, is_no_std, where, keyword=keyword)
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

    A tier is configured when it carries AT LEAST ONE criterion; which one
    depends on the QC type (a duplicate has only an RPD, a blank only
    max_conc_x_rl). A tier that specifies nothing never yields a verdict.
    An absent criterion means "not judged that way": downstream skips a
    check whose criterion is None.
    """
    low = tier.get("recovery_min")
    high = tier.get("recovery_max")
    rsd = tier.get("rsd_max")
    rpd = tier.get("rpd_max")
    # anything beyond the structural keys is a criterion
    criteria = set(tier) - _TIER_STRUCTURAL_KEYS
    if not criteria:
        raise UnconfiguredCriterion(
            "No acceptance criteria configured for {0} / {1} / {2} / {3}: "
            "tier {4!r} specifies no recovery window, RSD or RPD limit. "
            "Set one in the {3} tiers on the method's QC criteria tab, or switch "
            "that QC type off.".format(
                method_id, analyte, matrix or "(no matrix)", qc_type,
                tier.get("name") or tier.get("analyte_group") or "default"))
    # one end of a recovery window set alone would judge an open interval
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


def _with_tier_state(rule, profile_data, qc_type, tier):
    """The rule with its tier's own state (limit_states.tier_state)."""
    if rule is None:
        return rule
    return dataclasses.replace(rule, state=_limits_module().tier_state(profile_data, qc_type, tier))


def _name_list(value):
    """A list setting typed as text ("PFBA, PFPeA") or stored as a list."""
    if isinstance(value, (list, tuple)):
        return tuple(v.strip() for v in value if v and v.strip())
    return tuple(v.strip() for v in (value or "").replace(";", ",").split(",") if v.strip())


def _ccv_rule(ccv, method_id):
    """CCV limits from the profile, or refuse: no code window stands in for
    a silent profile."""
    low, high = ccv.get("recovery_min"), ccv.get("recovery_max")
    if low is None or high is None:
        raise UnconfiguredCriterion(
            "{0} has no CCV recovery window configured. Set it on the method's "
            "QC criteria tab (CCV Recovery).".format(method_id))
    return CCVRule(
        recovery_min=float(low),
        recovery_max=float(high),
        # not verdicts on a result: an unset frequency is None (the
        # CCV-frequency check reports it); an unset low-level window means
        # the method sets no separate limit at the MRL
        frequency=int(ccv["frequency"]) if ccv.get("frequency") not in (None, "", 0) else None,
        low_level_min=ccv.get("low_level_min"),
        low_level_max=ccv.get("low_level_max"),
    )


def _iv_section(profile_data, method_id, section, aliases=(), where=""):
    """A configured instrument_verification section (calibration, IS
    response, confirmation), or refuse: each decides a verdict."""
    iv = profile_data.get("instrument_verification") or {}
    data = iv.get(section)
    for alias in aliases:
        if not data:
            data = iv.get(alias)
    if not isinstance(data, dict) or not data:
        raise UnconfiguredCriterion(
            "{0} has no instrument_verification.{1} section. Configure it on "
            "the method's QC criteria tab{2}.".format(method_id, section, where))
    return data


def _confirmation(profile_data, method_id):
    """The configured chromatographic-confirmation section, or refuse.

    A key PRESENT with value None is not a key ABSENT. EPA 537.1 stores
    `ion_ratio_tol_pct: null`: the method has no qual-ion ratio criterion.
    The editor writes every key, so an absent key means never configured.
    """
    return _iv_section(profile_data, method_id, "confirmation",
                       where=" (Ion Ratio, RT Deviation, S/N Minimum)")


def _calibration(profile_data, method_id):
    return _iv_section(profile_data, method_id, "calibration",
                       where=" (Calibration r\u00b2)")


def _is_section(profile_data, method_id):
    return _iv_section(profile_data, method_id, "is_response", ("is",),
                       where=" (IS Response)")


def _engine_module():
    """senaite.pfas.method_engine: a method's Engine settings, read the same
    way here and in the add-on."""
    from .addon import load
    return load("method_engine")


def _limits_module():
    """senaite.pfas.limit_states: each limit box's state, read the same way
    here and in the add-on."""
    from .addon import load
    return load("limit_states")


def _calibration_fit_module():
    """senaite.pfas.calibration_fit: the method's curve fit, read the same
    way here, on QC criteria and on the curve card."""
    from .addon import load
    return load("calibration_fit")


# a matrix class's SUR limits holding this marker: not assessed in that class
NOT_ASSESSED = "none"


def _not_assessed(lim):
    """Whether a class limit ({recovery_min, recovery_max}) is the marker."""
    return isinstance(lim, dict) and NOT_ASSESSED in (lim.get("recovery_min"), lim.get("recovery_max"))


def _limit_or(value, fallback):
    """A stored limit as float, or the fallback when it is unset (None)."""
    return fallback if value is None else float(value)


_SURROGATE_WINDOW_NOTE = "Surrogate recovery (method profile)"
# the window the method text states: its source is on the Help page, never
# stored beside the window
_METHOD_TEXT_WINDOW_NOTE = "Surrogate recovery (method text)"
_CCV_SURROGATE_WINDOW_NOTE = "Surrogate recovery in CCVs (method profile)"


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
        return self.qc_rules_with_level(analyte, matrix, qc_type, conc=conc, rl=rl)[0]

    def low_level_tier_applies(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
        """Whether qc_rules judges this recovery against a low-level tier
        (the spike at or below N x RL), which the method's Low-level
        recoveries row then files (low_level_state)."""
        try:
            return self.qc_rules_with_level(analyte, matrix, qc_type, conc=conc, rl=rl)[1]
        except UnconfiguredCriterion:
            return False

    def qc_rules_with_level(self, analyte, matrix="", qc_type="LFSM", conc=None, rl=None):
        """(qc_rules' rule, whether it is a low-level tier's)."""
        data = self._profile_data()
        eng = _engine_module().engine(data)
        if eng["eis_recovery_limits"] and qc_type in ("EIS", "SUR", "surrogate"):
            return self._eis_rule(data, eng, analyte, matrix), False
        if qc_type in ("SUR", "surrogate"):
            return self._surrogate_rule(data, eng), False
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
            return None, False
        tier, branch = chosen
        rule = _tier_rule(tier, self._tier_notes(eng, tier, branch, _rule_flags().type_note(data, mapped)),
                          self.method_id, analyte, matrix, mapped)
        rule = _with_tier_state(rule, data, mapped, tier)
        if tier.get("verify_against_method"):
            rule = dataclasses.replace(rule, verify_against_method=True)
        return rule, bool(tier.get(LOW_LEVEL_KEY))

    @staticmethod
    def _tier_notes(eng, tier, branch, type_note=""):
        """The note a tier's rule carries: the note on the tier's own flag
        (it stands in for a grouped tier's missing description), else the
        Engine's note for the tier's branch (a profile not yet migrated),
        else the tier's own description, else the general tier note (the
        Engine's, or its QC type's own row's: `type_note`). A low-level
        tier: its description, else the Low-level recoveries note with its
        N."""
        notes = eng["rule_notes"]
        own = ((tier.get("flag") or {}).get("note") or "").strip() \
            if isinstance(tier.get("flag"), dict) else ""
        if own and not tier.get(LOW_LEVEL_KEY):
            return own
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
        return tier.get("description", notes.get("tier", "") or type_note or "")

    def _surrogate_rule(self, data, eng):
        """The method's one surrogate window (method_engine.surrogate_window:
        the profile's own, else the window the method text states), else a
        refusal."""
        kw = {"is_guidance_only": True} if self.limit_state("surrogate_recovery") == "evaluate" else {}
        win = _engine_module().surrogate_window(data)
        if win is None:
            raise UnconfiguredCriterion(
                "{0} has no surrogate recovery window. Set it on the method's "
                "Isotope standards tab (Recovery limits, on any surrogate's "
                "row).".format(self.method_id))
        notes = _SURROGATE_WINDOW_NOTE if win["source"] == "profile" else _METHOD_TEXT_WINDOW_NOTE
        return QCRule(win["min"], win["max"], notes=notes, **kw)

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
                    "on. Set the LFSM tiers on the method's QC criteria "
                    "tab.".format(self.method_id))
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
                    "which is not set. Set it on the method's Isotope standards "
                    "tab (Surrogates: Surrogate recovery min and max).".format(
                        self.method_id, analyte))
            return float(win["recovery_min"]), float(win["recovery_max"])
        raise UnconfiguredCriterion(
            "{0}: isotope-dilution (EIS) limits are on, but no default EIS window "
            "is chosen. Choose one on the method's Engine tab.".format(self.method_id))

    def _eis_class_limit(self, data, analyte, matrix):
        """The SUR's limits for the matrix's class, as stored (or None)."""
        mat_class = _engine_module().matrix_class(data, matrix) if matrix else None
        if not mat_class:
            return None
        table = (data.get("eis_matrix_overrides") or {}).get(mat_class) or {}
        return table.get(eis_criteria_name(self.method_id, analyte))

    def sur_not_assessed(self, analyte, matrix=""):
        """Whether the method marks this SUR's matrix class not assessed
        (the class limits hold "none") while it judges SURs per class."""
        data = self._profile_data()
        if not _engine_module().engine(data)["eis_recovery_limits"]:
            return False
        return _not_assessed(self._eis_class_limit(data, analyte, matrix))

    def _eis_rule(self, data, eng, analyte, matrix):
        """EIS / surrogate recovery per analyte x matrix class; None where
        the standard's class holds the marker "none" (not assessed there:
        no window, never the aqueous one)."""
        eis_overrides = data.get("eis_overrides", {})
        # `analyte` is the compound as the INSTRUMENT names it, which is the
        # compound the lab actually spiked. A published method may designate
        # the same position by its own labelled form, so the lookup joins
        # through the native (eis_criteria_name). The rule keeps `analyte`
        # unchanged, so a certificate names the compound the lab has.
        criteria_name = eis_criteria_name(self.method_id, analyte)
        mat_override = self._eis_class_limit(data, analyte, matrix)
        if _not_assessed(mat_override):
            return None
        default_lo, default_hi = self._eis_window(data, eng, analyte, matrix)
        override = eis_overrides.get(criteria_name, {})
        # A limit stored as null is UNSET: it falls back, never float(None).
        lo = _limit_or(override.get("recovery_min"), default_lo)
        hi = _limit_or(override.get("recovery_max"), default_hi)
        if mat_override:
            lo = _limit_or(mat_override.get("recovery_min"), lo)
            hi = _limit_or(mat_override.get("recovery_max"), hi)
        return QCRule(lo, hi, verify_against_method=eng["eis_verify_flag"],
                      notes=eng["rule_notes"].get("eis", ""),
                      is_guidance_only=self.limit_state("surrogate_recovery") == "evaluate")

    # ── instrument criteria ─────────────────────────────────────
    def _criterion(self, eng, rule, section, key, where):
        """One instrument criterion as stored (absent = None); None while its
        box is Off. An empty box is filed once by the run queue
        (limit_states.empty_boxes): Enforced refuses, Evaluate advises."""
        box = _limits_module().box_for_field(rule, key)
        if box is not None and self.limit_state(box) == "off":
            return None
        return section.get(key)

    def calibration_rule(self, analyte=""):
        data = self._profile_data()
        eng = _engine_module().engine(data)
        cal = _calibration(data, self.method_id)
        where = " (Calibration r\u00b2)"
        # r2_min: its box decides; empty, the run queue files it once
        # (Enforced refuses, Evaluate advises)
        r2 = self._criterion(eng, "calibration", cal, "r2_min", where)
        point = self._criterion(eng, "calibration", cal, "point_pct_dev_max", where)
        low_point = self._criterion(eng, "calibration", cal, "low_point_pct_dev_max", where)
        # Origin and Weighting (calibration_fit.py in the add-on); a profile
        # without `origin` reads its force_origin switch
        origin = cal.get("origin") if cal.get("origin") in ("exclude", "include", "force") else (
            "force" if cal.get("force_origin") else "exclude")
        weighting = cal.get("weighting") if cal.get("weighting") in ("none", "1/x", "1/x2") else "1/x"
        # the fit: a labelled compound on its mean response factor where the
        # Engine says so, else the method's curve fit, else linear
        fit = _calibration_fit_module().fit(cal)
        if eng["labelled_compound_fit"] == "mean_response_factor" and analyte:
            from .analyte_alias import is_labelled
            # the fit follows the library: without one this raises, never
            # falls back to the method's fit
            if is_labelled(analyte):
                fit = "mean_response_factor"
        return CalibrationRule(
            r2_min=None if r2 is None else float(r2),
            point_pct_dev_max=point,
            low_point_pct_dev_max=low_point,
            force_origin=origin == "force",
            default_fit=fit,
            # a mean-response-factor fit has no weighting; a linear or
            # quadratic one is weighted as the method profile says (the
            # lab's 1/x by default)
            default_weighting="none" if fit == "mean_response_factor" else weighting,
            origin=origin,
        )

    def max_cal_dropped(self):
        value = ((self._iv().get("calibration") or {}).get("max_cal_dropped"))
        if _unset(value) or self.limit_state("cal_dropped") == "off":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            raise UnconfiguredCriterion(
                "{0}: Calibration has a most calibrators dropped of {1!r}, which is not a whole "
                "number.".format(self.method_id, value))

    def ccv_rule(self):
        ccv = self._iv().get("ccv", {})
        if self.limit_state("ccv_low_level") == "off":
            # the low-level window is not judged: the Recovery window judges
            # those CCVs, as it does where the method sets none
            ccv = dict(ccv, low_level_min=None, low_level_max=None)
        return _ccv_rule(ccv, self.method_id)

    def is_rule(self):
        data = self._profile_data()
        eng = _engine_module().engine(data)
        is_ = _is_section(data, self.method_id)
        where = " (IS Response)"
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
        where = " (Ion Ratio, RT Deviation, S/N Minimum)"
        get = lambda k: self._criterion(eng, "confirmation", conf, k, where)  # noqa: E731
        # evaluated in this order: the first missing criterion is the one named
        ion_ratio = get("ion_ratio_tol_pct")
        rrt = get("rrt_tol_pct")
        rt_abs = get("rt_tol_abs_min")
        sn_quant = get("sn_quan_min")
        sn_confirm = get("sn_confirm_min")
        # single_transition_analytes (keywords, as a list or as text),
        # confirm_pct_diff_max and the
        # technique are the lab's settings, on the profile (Calibration & CCV)
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
        # keyed by the core SampleType title: exact first, then a substring
        # (calibration_levels.matrix_factor, the add-on's one rule)
        return _cal().matrix_factor(self._profile_data(), matrix)


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
# Analyte / IS list helpers
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


LINKED_RESPONSE_RATIOS = ("off", "on")


def get_linked_response_ratio(method_id: str) -> str:
    """Whether an analyte quantified on a surrogate is read on the response
    ratio linked to the surrogate's own internal standard (its Linked to):
    "on", RR = A x C_sur / RR_sur with RR_sur = A_sur x C_IS / A_IS; "off"
    (the default), RR = A x C_sur / A_sur. Missing, blank or anything else
    reads "off"; a profile still holding the earlier key surrogate_amount
    reads its "measured" as "on"."""
    data = _profile_data_cache.get(method_id, {}) or {}
    value = data.get("linked_response_ratio")
    value = value.strip() if isinstance(value, str) else ""
    if value in LINKED_RESPONSE_RATIOS:
        return value
    old = data.get("surrogate_amount")
    if not value and isinstance(old, str) and old.strip() == "measured":
        return "on"
    return "off"


DILUTION_RECOVERIES = ("fold", "measured", "parent")


def get_dilution_recovery(method_id: str) -> str:
    """How a diluted field sample's surrogate recovery is judged under the
    linked response ratio, one choice for every analyte of the method:
    "fold" (the dilution's own, corrected for its fold: C_found x DF /
    C_spiked), "measured" (the dilution's own as measured: C_found /
    C_spiked) or "parent" (the parent sample's, for a dilution the surrogate
    was added back to). "" when not set: nothing is preset; the dilution's
    recovery is then not judged and its results are flagged."""
    data = _profile_data_cache.get(method_id, {}) or {}
    value = data.get("dilution_recovery")
    value = value.strip() if isinstance(value, str) else ""
    return value if value in DILUTION_RECOVERIES else ""


def get_blank_subtraction(method_id: str) -> bool:
    """Whether the method subtracts the batch's method blank from each result
    (a per-method switch; off by default)."""
    data = _profile_data_cache.get(method_id, {}) or {}
    return bool(data.get("blank_subtraction"))


def get_spike_basis(method_id: str) -> str:
    """"before" when spike levels are entered before the per-sample amount
    adjustment (scaled by nominal / actual amount), else "" (as entered).
 Sample correction tab."""
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
    """
    try:
        profile = get_profile(method_id)
    except KeyError:
        return None
    return profile.sample_factor(matrix)


def get_non_iso_set(method_id: str) -> frozenset:
    """Return the frozenset of analyte display names that have no labeled std.

    Derived from THIS method's surrogate links, never a global column,
    limited to its reported panel.
    """
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


def get_is_list(method_id: str) -> list:
    """Display names of the labelled compounds this METHOD monitors.

    DERIVED, not stored: the method's labelled_standards grid when set,
    else the union of its surrogate_map values and the injection IS, both
    method-scoped:

        {surrogate_map values} + {injection IS}   ->   display names

    Display names, because the instrument exports them and `is_raw_check`
    matches rows on them; each exists as an AnalysisService (see
    eis_criteria_name).

    Refuses when the method names no labelled standard: an empty list would
    check no surrogate or internal standard and say nothing.
    """
    from .analyte_alias import injection_is_names, labelled_display_name

    data = _profile_data_cache.get(method_id, {})
    grid = data.get("labelled_standards")
    if isinstance(grid, dict) and grid:
        # the method's own grid: every standard it USES, map surrogates
        # first (in map order), then the rest
        order = []
        for row in data.get("surrogate_map") or []:
            kw = (row.get("surrogate_is") or "").strip()
            if kw in grid and kw not in order:
                order.append(kw)
        order += sorted(k for k in grid if k not in order)
        return [labelled_display_name(k) for k in order]
    rows = data.get("surrogate_map") or []
    names, seen = [], set()
    cmp = _composites_module()
    for row in rows:
        # a composite is no compound: its members are the standards checked
        for kw in cmp.members(data, (row.get("surrogate_is") or "").strip()):
            name = labelled_display_name(kw)
            if name not in seen:
                seen.add(name)
                names.append(name)
    # the injection standard quantifies the surrogates, so it is in no
    # surrogate_map row; it is listed because its response must NOT be
    # dilution-corrected
    for name in sorted(injection_is_names()):
        if name not in seen:
            seen.add(name)
            names.append(name)
    if names:
        return names
    raise UnconfiguredCriterion(
        "{0} names no isotope standard (SUR or IS). Set "
        "them on the method's Isotope standards tab.".format(
            method_id or "(no method)"))


def eis_criteria_name(method_id: str, compound: str) -> str:
    """The key under which `eis_overrides` holds `compound`'s recovery limits:
    the compound's keyword. A published method designates its extracted
    internal standards by isotopologue, and each designation is a labelled
    compound of the library (13C4-PFBA is not 13C3-PFBA), so the row is the
    compound's own; a published spelling of a compound the catalogue holds
    under another name (13C8-PFOSA for 13C8-FOSA) reaches that compound's
    row. A compound with no row is judged on the method's default window.
    Returns `compound` unchanged when the library does not know it."""
    from .analyte_alias import keyword_of
    return keyword_of(compound) or compound


def get_included_display_analytes(method_id: str, matrix: str) -> list:
    """Return display-name analyte list filtered by the Method × Matrix panel.

    Reads ``analyte_matrix_inclusion`` from the profile cache (keyword-keyed
    dict exported from the ZODB store). With no inclusion data, the full
    analyte list.

    Display names map to keywords through the compound library's native
    names. A keyword missing from the inclusion dict is included: missing
    config never silently drops an analyte.
    """
    data = _profile_data_cache.get(method_id, {})
    inclusion = data.get("analyte_matrix_inclusion")
    full_list = get_analyte_list(method_id)
    if not inclusion:
        return full_list

    from .analyte_alias import native_name_to_keyword
    display_to_kw = native_name_to_keyword()
    result = []
    for display_name in full_list:
        keyword = display_to_kw.get(display_name, display_name)
        matrix_map = inclusion.get(keyword, {})
        if matrix_map.get(matrix, True):
            result.append(display_name)
    return result


def get_isomer_summation(method_id: str) -> list:
    """Return the active (summed) isomer groups for method_id.

    Each is ``{"linear", "branched", "branched_list", "reported", "enabled"}``:
    `reported` is the analyte KEYWORD the sum is imported under (the label a
    page shows may differ); `branched_list` holds every branched peak,
    `branched` the first.

    Read from the method's `isomers` (the Isomers tab).
    """
    groups = _profile_data_cache.get(method_id, {}).get("isomers") or {}
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


def get_surrogate_map(method_id: str) -> dict:
    """Which labeled surrogate quantifies each native analyte, per METHOD.

    §3 makes this the method's own relation ("SURROGATE MAP native ->
    quantifying IS ... QUANTIFICATION link"); the analysis reads it here,
    not from the instrument file's `linked_is` column.

    Keyed by BOTH the display name and the keyword: the profile stores
    whichever spelling the editor was given and the instrument exports
    display names.
    """
    rows = _profile_data_cache.get(method_id, {}).get("surrogate_map", []) or []
    return _by_every_name(((row.get("analyte") or "").strip(), (row.get("surrogate_is") or "").strip())
                          for row in rows)


def _composites_module():
    """The add-on's composite_standards (one rule for both processes)."""
    from .addon import load
    return load("composite_standards")


def get_composites(method_id: str) -> dict:
    """{composite id: [member keywords]} for the method's composite
    standards: an analyte whose surrogate map names one is quantified on
    the mean of its members' areas (composite_standards)."""
    return _composites_module().members_map(_profile_data_cache.get(method_id, {}) or {})


def quantifying_members(method_id: str, value: str) -> list:
    """The standards a surrogate-map value stands for: a composite's
    members, else [value]; [] for nothing."""
    return _composites_module().members(_profile_data_cache.get(method_id, {}) or {}, value)


def composite_name(method_id: str, value: str) -> str:
    """A composite's name built from its members ("Mean of A and B"); a
    plain standard's own name."""
    return _composites_module().name(_profile_data_cache.get(method_id, {}) or {}, value)


def _by_every_name(pairs):
    """{every spelling of the analyte: value} for (analyte, value) pairs: the
    profile stores keywords while the instrument exports display names."""
    try:
        from .analyte_alias import keyword_for, expand
    except ImportError:
        keyword_for, expand = None, None
    out = {}
    for analyte, value in pairs:
        if not analyte or value in (None, ""):
            continue
        out[analyte] = value
        kw = keyword_for(analyte) if keyword_for else analyte
        if not kw:
            continue
        names = expand(kw) if expand else [kw]
        for name in names:
            out[name] = value
    return out


_INTEGRATION_LABELS = {"smooth_points": "smoothing", "baseline": "baseline", "area": "area",
                       "min_sn": "smallest signal-to-noise reported", "mz_tolerance": "m/z tolerance",
                       "sensitivity": "sensitivity", "shoulder_pct": "shoulder split",
                       "qual_apex_tol": "qualifier apex tolerance", "fit_max_dev_pct": "largest fit deviation",
                       "rt_anchor": "relative retention"}

# the settings each engine needs, in the order a refusal names them; an
# unset engine is classic
_INTEGRATION_SETTINGS = {
    "classic": ("smooth_points", "baseline", "area", "min_sn", "mz_tolerance"),
    "adaptive": ("smooth_points", "area", "min_sn", "mz_tolerance", "sensitivity", "shoulder_pct",
                 "qual_apex_tol")}
# the settings a fitted area (gaussian, emg) needs besides, under either
# engine: past the largest fit deviation it falls back to the trapezoid
_FIT_SETTINGS = ("fit_max_dev_pct",)

# the settings a block names whatever its engine: always in the revision
_REVISION_KEYS = ("smooth_points", "baseline", "area", "min_sn")
# in the revision only when set, so a method that sets none keeps its revision
_REVISION_KEYS_WHEN_SET = ("engine", "mz_tolerance", "sensitivity", "shoulder_pct", "qual_apex_tol",
                           "fit_max_dev_pct", "rt_anchor", "min_manual_change_pct", "min_manual_sn",
                           "edge_points", "min_peak_points", "edge_sigma", "drop_valley_max_pct",
                           "skim_ratio_pct", "search_slope", "search_amp_sn", "search_smooth_pct",
                           "candidate_min_points", "candidate_min_fwhm_pct", "fit_noise_multiple",
                           "fit_accept_score")
# the limits on an analyst's manual change: not the engine's, a refusal of
# the edit when it is made (raw_preview.edit_problem)
_MANUAL_LIMITS = (("min_manual_change_pct", "a smallest manual change"),
                  ("min_manual_sn", "a smallest S/N for a manual peak"))

def _unset(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _transition(value):
    return (float(value[0]), float(value[1]))


def _smoothing(value):
    """"auto" (any case) or the whole number of points; ValueError otherwise."""
    if isinstance(value, str) and value.strip().lower() == "auto":
        return "auto"
    if isinstance(value, bool):
        raise ValueError(value)
    number = float(value)
    if number != int(number):
        raise ValueError(value)
    return int(number)


def _points(value):
    """A whole number of points; ValueError otherwise."""
    if isinstance(value, bool):
        raise ValueError(value)
    number = float(value)
    if number != int(number):
        raise ValueError(value)
    return int(number)


_COMPOUND_SETTINGS = (("smooth_points", _smoothing, "smoothing"), ("area", str, None),
                      ("min_sn", float, "a smallest signal-to-noise"), ("sensitivity", float, "a sensitivity"),
                      ("min_qual_sn", float, "a smallest confirmation signal-to-noise"),
                      ("rt_anchor", str, None)) + tuple((key, float, what) for key, what in _MANUAL_LIMITS) + (
    ("edge_points", _points, "edge points"), ("min_peak_points", _points, "a fewest points in a peak"),
    ("edge_sigma", float, "edges past the tail"), ("drop_valley_max_pct", float, "a valley limit"),
    ("skim_ratio_pct", float, "a tangent skim ratio"), ("search_amp_sn", float, "a peak search amplitude"),
    ("candidate_min_points", _points, "a fewest points in a candidate"),
    ("candidate_min_fwhm_pct", float, "a smallest candidate width"))


def _compound_settings(keyword, row):
    """The settings a compound sets for itself on its Integration row: only
    those entered (a blank is the method's), smoothing as "auto" or a whole
    number, the rest as numbers. A value that is no number is refused naming
    the compound; a number out of range is refused where it is applied
    (raw_run.settings_for)."""
    out = {}
    for key, cast, what in _COMPOUND_SETTINGS:
        value = row.get(key)
        if value is None or str(value).strip() == "":
            continue
        try:
            out[key] = cast(str(value).strip()) if cast is str else cast(value)
        except (TypeError, ValueError):
            raise UnconfiguredCriterion(
                "Integration: {0} has {1} {2!r}, which is not a number.".format(keyword, what, value))
    return out


def _method_settings(method_id, engine, intg):
    """The engine's settings object from the method's Integration block; a
    value the engine refuses is refused naming the method. The classic
    engine's edge points are the block's, 6 when unset."""
    from .raw_integrate import EDGE_POINTS, AdaptiveSettings, Settings, method_baseline
    try:
        edge_points = EDGE_POINTS if _unset(intg.get("edge_points")) else _points(intg["edge_points"])
    except (TypeError, ValueError):
        edge_points = intg.get("edge_points")
    try:
        smooth = _smoothing(intg["smooth_points"])
    except (TypeError, ValueError):
        smooth = None
    fit = intg.get("fit_max_dev_pct")
    try:
        if engine == "classic":
            if not isinstance(smooth, int):
                raise ValueError("smoothing is an odd number of points, 5 or more; auto is Adaptive's")
            return Settings(smooth_points=smooth, baseline=method_baseline(intg["baseline"]), area=intg["area"],
                            min_sn=float(intg["min_sn"]), fit_max_dev_pct=None if _unset(fit) else float(fit),
                            edge_points=edge_points)
        if smooth is None or (smooth != "auto" and (smooth < 3 or smooth % 2 == 0)):
            raise ValueError("smoothing is auto or an odd number of points, 3 or more")
        anchor = intg.get("rt_anchor")
        # unset relative retention is fixed
        return AdaptiveSettings(smooth=smooth if smooth == "auto" else (smooth - 1) // 2, area=intg["area"],
                                min_sn=float(intg["min_sn"]), sensitivity=float(intg["sensitivity"]),
                                shoulder_pct=float(intg["shoulder_pct"]),
                                qual_apex_tol=float(intg["qual_apex_tol"]),
                                fit_max_dev_pct=None if _unset(fit) else float(fit),
                                rt_anchor="fixed" if _unset(anchor) else anchor)
    except (TypeError, ValueError) as exc:
        raise UnconfiguredCriterion(
            "{0} cannot be integrated from raw data: Integration {1}. Set it in the Integration "
            "section of the method's Run & reporting tab.".format(method_id, exc))


def get_integration(method_id: str) -> dict:
    """The method's Integration tab, for a run imported from raw data:
    {"engine": "classic" | "adaptive", "method": raw_integrate.Settings
    (classic) or raw_integrate.AdaptiveSettings (adaptive), "analytes":
    {keyword: {"quant": (q1, q3), "quals": [(q1, q3)], "rt", "window", "mode",
    "partner", "expected_ion_ratio", "labelled", "panel": a native or isomer
    peak of the method's panel, "settings": the compound's
    own smooth_points, area, min_sn, sensitivity, min_qual_sn, rt_anchor,
    min_manual_change_pct and min_manual_sn, those entered, "processing":
    the compound's processing entry, {"quant": change, "quals": {transition
    label: change}} countersigned from a run (method_proposals), less
    what the compound can no longer take (fitting_entry), {} for none}},
    "mode",
    "revision", "mz_tolerance", "sn_confirm_min": the method's
    confirmation-ion limit, a qualifier's floor where its compound sets none
    (None when unset), "min_manual_change_pct", "min_manual_sn": the
    method's limits on a manual change (raw_preview.manual_limits: the
    change defaults to 5 %, an unset S/N is no limit), "review_rules": {the
    ten settings for a dropped baseline and the candidates offered, as
    raw_preview.review_limits reads them for the method: edge_points,
    min_peak_points, edge_sigma, drop_valley_max_pct, skim_ratio_pct,
    search_slope, search_amp_sn, search_smooth_pct, candidate_min_points and
    candidate_min_fwhm_pct, each its default where unset; a compound's own,
    entered, are in its "settings")}, "fit_noise_multiple": the largest
    residual of a fit of overlapping peaks, its RMS as a multiple of the
    trace's baseline noise (None when unset: no fit is made; it has no
    default). Nothing is seeded
    but the m/z tolerance and relative retention, unset meaning fixed: an unset setting of the engine, a fitted area
    under either engine without its largest fit deviation, or an analyte or labelled standard of
    the method with no transition, time and window, is refused, naming
    every one. An analyte with isomers (the Isomers tab) is integrated as
    its linear and branched peaks, each partnered with the other, a
    branched peak summed; the analyte's own row is not used. Each
    compound's "window" is the one rule's (the add-on's rt_window): its
    time plus or minus the method's Retention time tolerance, in % or min,
    else, while that is unset, the window stored with its row, which is
    then required; the tolerance is in the fingerprint only when set."""
    from .raw_run import DEFAULT_MZ_TOLERANCE
    data = _profile_data_cache.get(method_id, {}) or {}
    intg = dict(data.get("integration") or {})
    # an unset m/z tolerance reads the default
    if _unset(intg.get("mz_tolerance")):
        intg["mz_tolerance"] = DEFAULT_MZ_TOLERANCE
    engine = intg.get("engine")
    engine = "classic" if _unset(engine) else engine
    if engine not in _INTEGRATION_SETTINGS:
        raise UnconfiguredCriterion(
            "{0} cannot be integrated from raw data: Integration names the engine {1!r}, which is "
            "neither classic nor adaptive.".format(method_id, engine))
    grid = data.get("labelled_standards") if isinstance(data.get("labelled_standards"), dict) else {}
    rows = intg.get("analytes") or {}
    # the method's one retention-time tolerance (rt_window): set, it gives
    # every compound's window; unset, each transition's stored window stands
    from .addon import load
    rtw = load("rt_window")
    try:
        tol = rtw.tolerance(intg)
    except (TypeError, ValueError):
        raise UnconfiguredCriterion(
            "{0} cannot be integrated from raw data: Integration has the Retention time tolerance {1!r} {2!r}, "
            "which is not a number above 0 in % or min. Set it in the Integration section of the method's "
            "Run & reporting tab.".format(method_id, intg.get(rtw.TOL_KEY), intg.get(rtw.UNIT_KEY)))
    row_fields = ("quant", "rt") if tol is not None else ("quant", "rt", "window")
    needed_keys = list(_INTEGRATION_SETTINGS[engine])
    if intg.get("area") in ("gaussian", "emg"):
        needed_keys.extend(_FIT_SETTINGS)
    unset = [_INTEGRATION_LABELS[key] for key in needed_keys if _unset(intg.get(key))]
    # an analyte with isomers is integrated as its peaks, each its own
    # analyte; its own row is not used
    from .addon import load
    iso_mod, iso = load("isomers"), data
    panel = list(data.get("master_analyte_set") or [])
    split = dict((kw, iso_mod.peaks_of(iso, kw)) for kw in panel if iso_mod.peaks_of(iso, kw))
    on_panel = iso_mod.integration_names(iso, panel)
    needed = on_panel + sorted(grid)
    missing = [k for k in needed
               if not all((rows.get(k) or {}).get(f) not in (None, "", []) for f in row_fields)]
    if unset or missing:
        parts = []
        if unset:
            parts.append("the settings " + ", ".join(unset))
        if missing:
            parts.append(("a transition and retention time for " if tol is not None else
                          "a transition, retention time and window for ") + ", ".join(missing))
        unused = ["{0} is integrated as {1}: its own row is not used.".format(kw, " and ".join(split[kw]))
                  for kw in sorted(split) if kw in rows and any(p in missing for p in split[kw])]
        raise UnconfiguredCriterion(
            "{0} cannot be integrated from raw data: Integration has no {1}. {2}Set them in "
            "the Integration section of the method's Run & reporting tab.".format(
                method_id, "; no ".join(parts), "".join(u + " " for u in unused)))
    settings = _method_settings(method_id, engine, intg)
    try:
        manual_change, manual_sn = load("raw_preview").manual_limits(
            dict((key, intg.get(key)) for key, _what in _MANUAL_LIMITS), None)
    except (TypeError, ValueError):
        raise UnconfiguredCriterion(
            "{0}: Integration has {1}, which is not a number.".format(
                method_id, " or ".join("{0} {1!r}".format(what, intg.get(key)) for key, what in _MANUAL_LIMITS
                                       if not _unset(intg.get(key)))))
    partners, branched = iso_mod.partners(iso), iso_mod.branched_peaks(iso)
    analytes = {}
    for k, row in rows.items():
        if not row.get("quant") or k in split:
            continue
        ratio = row.get("expected_ion_ratio")
        analytes[k] = {"quant": _transition(row["quant"]),
                       "quals": [_transition(q) for q in row.get("quals") or []],
                       "rt": float(row["rt"]), "window": rtw.half_width(row["rt"], row.get("window"), tol)[0],
                       "mode": row.get("mode") or "single", "partner": row.get("partner") or None,
                       "expected_ion_ratio": None if ratio in (None, "") else float(ratio),
                       "labelled": k in grid, "panel": k in on_panel,
                       "settings": _compound_settings(k, row),
                       # the processing changes countersigned from a run as the
                       # method's own: applied where a run has none of its own;
                       # one the compound can no longer take is left out, never
                       # refusing the run (Data Review says so)
                       "processing": load("method_proposals").fitting_entry(data, k)}
        # an isomer peak's partner comes from the Isomers tab; a branched
        # peak is the sum of the peaks in its window
        if k in partners:
            analytes[k]["partner"] = partners[k]
        if k in branched:
            analytes[k]["mode"] = "summed"
    # the largest residual of a fit of overlapping peaks, in times the
    # trace's baseline noise: the lab's, never a default
    fit_limit = intg.get("fit_noise_multiple")
    if _unset(fit_limit):
        fit_limit = None
    else:
        try:
            fit_limit = float(fit_limit)
            if isinstance(intg["fit_noise_multiple"], bool) or not fit_limit > 0 or fit_limit == float("inf"):
                raise ValueError(fit_limit)
        except (TypeError, ValueError):
            raise UnconfiguredCriterion(
                "{0}: Integration has the largest fit residual {1!r}, which is not a number above 0.".format(
                    method_id, intg.get("fit_noise_multiple")))
    # the score a fit must reach to be accepted: whole, 1 to 100, or blank
    # for the lab's. It only colours the review's badge and gates nothing, so
    # a value that is not one reads as unset and is logged, never stopping
    # the run
    accept = intg.get("fit_accept_score")
    if _unset(accept):
        accept = None
    else:
        accept = load("fit_accept").whole(accept)
        if accept is None:
            logger.warning("%s: Integration has the score to accept a fit %r, which is not a whole number from 1 "
                           "to 100: the lab's is used", method_id, intg.get("fit_accept_score"))
    # the rules for a dropped baseline, the method's and each compound's own
    review = load("raw_preview").review_limits
    try:
        review_rules = review(intg, None)
    except (TypeError, ValueError) as exc:
        raise UnconfiguredCriterion("{0}: Integration {1}.".format(method_id, exc))
    for k in analytes:
        try:
            # the compound's own, as the review resolves them when an edit is made
            analytes[k]["review"] = review(intg, k)
        except (TypeError, ValueError) as exc:
            raise UnconfiguredCriterion("{0}: Integration, {1}: {2}.".format(method_id, k, exc))
    # the Adaptive engine fits no pair: a pair would be integrated as the
    # nearest single peak, so it is refused, naming it
    pairs = sorted(k for k in analytes if analytes[k]["mode"] == "pair")
    if engine == "adaptive" and pairs:
        raise UnconfiguredCriterion(
            "{0} cannot be integrated from raw data: {1} {2} a co-eluting pair, which the Adaptive engine "
            "does not fit. Make {3} a single peak, or choose Classic, in the Integration section of the "
            "method's Run & reporting tab.".format(method_id, ", ".join(pairs),
                                                    "is" if len(pairs) == 1 else "are",
                                                    "it" if len(pairs) == 1 else "each"))
    # the settings' fingerprint, named on every peak (not the results
    # source: it changes no peak)
    import hashlib
    import json as _json
    stored = data.get("integration") or {}
    kept = dict((k, stored.get(k)) for k in _REVISION_KEYS)
    kept.update((k, stored[k]) for k in _REVISION_KEYS_WHEN_SET if not _unset(stored.get(k)))
    # an empty processing entry is no setting: in the revision only when set
    kept["analytes"] = load("method_proposals").without_empty_processing(rows)
    # the tolerance, as it reads, only when set: an unset method keeps its revision
    if tol is not None:
        kept["rt_window"] = list(tol)
    # the isomer peaks decide partners and the branched peak's mode: part of
    # the fingerprint when the method has any
    if split:
        kept["isomer_peaks"] = split
    confirm = (((data.get("instrument_verification") or {}).get("confirmation") or {})
               .get("sn_confirm_min"))
    confirm = None if _unset(confirm) else float(confirm)
    # the qualifier floor changes the qualifier peaks: part of the fingerprint when set
    if confirm is not None:
        kept["sn_confirm_min"] = confirm
    revision = hashlib.sha1(_json.dumps(kept, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return {"engine": engine, "method": settings, "analytes": analytes, "mode": intg.get("mode") or "vendor",
            "revision": revision, "mz_tolerance": float(intg["mz_tolerance"]), "sn_confirm_min": confirm,
            "min_manual_change_pct": manual_change, "min_manual_sn": manual_sn, "review_rules": review_rules,
            "fit_noise_multiple": fit_limit, "fit_accept_score": accept}


def integration_mode(method_id: str) -> str:
    """Where the method's results come from (Integration): "vendor" (the
    default), "validation" or "lims"."""
    intg = (_profile_data_cache.get(method_id, {}) or {}).get("integration") or {}
    return intg.get("mode") if intg.get("mode") in ("vendor", "validation", "lims") else "vendor"


def get_labelled_links(method_id: str) -> dict:
    """{labelled standard: the standard it is linked to} from the method's
    labelled-standards grid (a surrogate quantified on its injection standard)."""
    grid = _profile_data_cache.get(method_id, {}).get("labelled_standards")
    if not isinstance(grid, dict):
        return {}
    return dict((k, (v or {}).get("reference")) for k, v in grid.items() if (v or {}).get("reference"))


def get_labelled_roles(method_id: str) -> dict:
    """{keyword: "surrogate" | "injection_is"} from the method's labelled-
    standards grid, or {} for a profile without one; callers then use the
    global roles."""
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

    Read from `labelled_standards`."""
    grid = _profile_data_cache.get(method_id, {}).get("labelled_standards") or {}
    return dict((k, v["reference"]) for k, v in grid.items()
                if isinstance(v, dict) and v.get("reference"))


def get_salt_factors(method_id: str) -> dict:
    """Per-analyte salt (counter-ion) correction, keyed by analyte.

    §3 lists SALT FACTOR as a core method relation: "per analyte x method
    (decimal < 1, from CoA)", entered with the reference-standard lot it
    came from.

    `salt_adjustment_factors` is the key the editor writes;
    `extraction_corrections.salt_factors` and `qc_rules.salt_factors` are
    not consulted here.
    """
    rows = _profile_data_cache.get(
        method_id, {}).get("salt_adjustment_factors", []) or []
    pairs = []
    for row in rows:
        analyte = (row.get("analyte") or "").strip()
        try:
            factor = float(row.get("factor"))
        except (TypeError, ValueError):
            continue
        # 1.0 is "no correction": the editor stores it for a lot linked
        # without a numeric adjustment
        if not analyte or factor == 1.0 or factor <= 0:
            continue
        pairs.append((analyte, factor))
    out = _by_every_name(pairs)

    # an isomer pair is quantified from the salt-form standard of the analyte
    # it sums to, and reported as lr-/br- rows: each component takes its factor
    for pair in get_isomer_summation(method_id):
        factor = out.get(pair.get("reported"))
        if not factor:
            continue
        for name in [pair.get("linear")] + list(pair.get("branched_list") or []):
            if name:
                out[name] = factor
    return out


def get_labelled_salt_factors(method_id: str) -> dict:
    """{labelled standard: its salt (counter-ion) factor}: each labelled
    standard of the method's grid whose row in `salt_adjustment_factors`
    (the list an analyte's factor is kept in, keyed the same way) holds a
    factor that changes something. It turns the standard's stated amounts,
    its level in the calibrators and the amount spiked, to the acid form
    (raw_run.load_raw_run); unset reads 1.0, so nothing changes."""
    data = _profile_data_cache.get(method_id, {}) or {}
    grid = data.get("labelled_standards") if isinstance(data.get("labelled_standards"), dict) else {}
    out = {}
    for row in data.get("salt_adjustment_factors") or []:
        if not isinstance(row, dict):
            continue
        name = (row.get("analyte") or "").strip()
        try:
            factor = float(row.get("factor"))
        except (TypeError, ValueError):
            continue
        if name in grid and factor > 0 and factor != 1.0:
            out[name] = factor
    return out


# Load profile data immediately if the export already exists
reload_from_profiles()
