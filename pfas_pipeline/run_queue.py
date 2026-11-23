"""
Run Queue — the review workflow engine.

When a batch comes back from the instrument, the queue walks every injection
and PROMPTS the reviewer with exactly the QC checks required for that
injection type (LFSM recovery, duplicate RPD, matrix-blank contamination, …).

Each check is resolved automatically by the QC engine where possible; checks
that need human judgment are surfaced as pending prompts. The queue state is
persisted so review can resume elsewhere.
"""

from __future__ import annotations
import functools
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import re

from . import dilution_routes
from .addon import load as _load_addon
from .importer import classify_injection
from .models import Batch, QCFlag, LFSMResult, LFSMDResult, reported_conc

logger = logging.getLogger(__name__)


# Units that mean the same thing for a concentration in an extract.
_UNIT_FAMILIES = (
    {"ng/ml", "ug/l", "ppb", "ng/g", "ug/kg"},
    {"pg/ml", "ng/l", "ppt", "pg/g", "ng/kg"},
    {"ug/ml", "mg/l", "ppm", "ug/g", "mg/kg"},
)


def _units_compatible(a, b):
    """True when two unit strings denote the same concentration scale."""
    a = (a or "").strip().lower().replace("µ", "u")
    b = (b or "").strip().lower().replace("µ", "u")
    if not a or not b or a == b:
        return True
    return any(a in fam and b in fam for fam in _UNIT_FAMILIES)
from .qc_engine import (
    KIND_CALIBRATION, KIND_CCV, KIND_ION_RATIO, KIND_IS_RESPONSE,
    KIND_LFSM, KIND_LFSMD, KIND_RT, KIND_SN, KIND_SURROGATE,
    KIND_BLANK, KIND_LCS, KIND_CCV_FREQ, KIND_DUP,
    BLANK_ROLES, blank_check, ccv_frequency_check, mdl_check, dup_one_detected_flag,
    is_raw_check, qual_quan_check, calibration_check_profiled,
    ccv_check_profiled, icv_check_profiled, rrt_check_profiled, signal_to_noise_check, qualifier_deleted_check,
    recovery_check_profiled, rpd_check_profiled, raw_no_reading, no_reading_issue,
    RSD_MIN_SPIKES, rsd_check_profiled, rsd_pct,
)
from .method_profiles import (
    UnconfiguredCriterion,
    get_profile as _get_method_profile,
    get_analyte_list as _get_analytes,
    get_is_list as _get_is_list,
    get_injection_standards as _get_injection_standards,
    get_included_display_analytes as _get_included_analytes,
)


class CheckStatus(str, Enum):
    PENDING   = "pending"      # not yet evaluated
    AUTO_PASS = "auto_pass"    # QC engine found no flags
    AUTO_FAIL = "auto_fail"    # QC engine raised flags — needs review
    ACCEPTED  = "accepted"     # reviewer accepted (with or without flags)
    REJECTED  = "rejected"     # reviewer rejected → rerun required


@dataclass
class ReviewCheck:
    injection_name: str
    qc_type:        str
    check_name:     str           # e.g. "lfsm_recovery"
    status:         CheckStatus = CheckStatus.PENDING
    flags:          list[dict]  = field(default_factory=list)
    reviewer:       str         = ""
    reviewed_at:    Optional[str] = None
    comment:        str         = ""


# Human-readable prompts shown to the reviewer for each check type
CHECK_PROMPTS: dict[str, str] = {
    "calibration_pct_dev": "Verify each calibration point is within ±20% of curve",
    "r_squared":           "Verify R² ≥ 0.995 for every analyte",
    "ccv_pct_dev":         "Verify CCV recovery is within ±20% for every analyte",
    "is_response":         "Verify internal standard responses within ±50% of batch average",
    "rt_deviation":        "Verify retention times within ±0.10 min of average",
    "ion_ratio":           "Verify qual/quan ion ratios within ±30% of expected",
    "blank_contamination": "Verify the blank against the method's limit (QC Types: \u2264 N x RL)",
    "lod_check":           "Apply <LOD qualifier where blank ≥ sample",
    "bloq_check":          "Apply BLoQ qualifier for results below LOQ",
    "recovery":            "Verify LFB / LCS recovery against the method's tiers",
    "lfsm_recovery":       "Verify LFSM recovery 50–150% (select spike conc. if not set)",
    "lfsmd_rpd":           "Verify LFSM/LFSMD RPD ≤ 30%",
    "duplicate_rpd":       "Verify the sample duplicate RPD against the method's Dup limit",
    "signal_to_noise":     "Verify S/N ≥ 3 for reported analytes",
}


# A matrix spike's parent and level are never read from its name: the
# extraction's spike record is the only source.

_DUP_SUFFIX = re.compile(r"(?i)[\s;,_-]*\b(?:dup\.?|duplicate)\s*$")


def _dup_parent_name(dup_inj):
    """'DEMO Silage A Dup.' / '...; Duplicate' -> 'DEMO Silage A' (the name
    fallback when the extraction record does not name the parent)."""
    parent = _DUP_SUFFIX.sub("", dup_inj or "").rstrip(" ;,")
    return parent if parent and parent != dup_inj else ""


def _spike_amount(entry):
    """(value, unit) a spike record gives: `spike` in `spike_unit` (the
    matrix's reporting unit), or an older `spike_ppt`."""
    entry = entry or {}
    if entry.get("spike") not in (None, "", 0):
        return float(entry["spike"]), entry.get("spike_unit") or ""
    if entry.get("spike_ppt") not in (None, "", 0):
        return float(entry["spike_ppt"]), "ppt"
    return None, ""


def _get_conc(inj_name, analyte, lookup, sums=None):
    row = _summed_row(lookup.get(inj_name, []), analyte, sums)
    return reported_conc(row) if row is not None else None


def _summed_row(rows, analyte, sums=None):
    """The analyte's row in one injection. A summed analyte is the SUM of its
    components (lr- + br-), as the summary reports it, also when the export
    carries its own "Total" row: that row is never put on the sample basis
    (apply_extract_corrections converts native analytes only). `sums` =
    {keyword: [component names]}; the export's Total row is used only when no
    component is present."""
    comps = []
    if sums:
        from .analyte_alias import keyword_for
        comps = sums.get(keyword_for(analyte) or analyte) or sums.get(analyte) or []
    # a component asked for by its own name is its own row, never the whole sum
    parts = [] if analyte in comps else [r for r in rows if r.compound_name in comps]
    if not parts:
        for row in rows:
            if row.compound_name == analyte:
                return row
        # the export's own name for it (PFTA for PFTeDA, ADONA for DONA, a
        # display name for a keyword): the same compound by keyword, every
        # spelling the library knows on both sides
        from .analyte_alias import native_keyword_for
        want = native_keyword_for(analyte)
        for row in rows:
            if native_keyword_for(row.compound_name) == want:
                return row
        return None
    vals = [reported_conc(r) for r in parts]
    got = [v for v in vals if v is not None]
    import copy as _copy
    total = _copy.copy(parts[0])
    total.compound_name = analyte
    total.calculated_conc = total.measured_conc = (sum(got) if got else None)
    exps = [getattr(r, "expected_conc", None) for r in parts]
    total.expected_conc = sum(exps) if all(e is not None for e in exps) else None
    return total


def _load_rule_toggles(method_id: str, rules_path: str = None) -> dict:
    """{rule_library_key: bool or state} for method_id: the method profile's
    `rule_toggles` with its `rule_states` (enforced / evaluate / off) over
    them, and every library rule's state over its limit boxes over both.
    `rules_path` is accepted for old callers and ignored. An absent key is
    treated as enforced by _rule_state."""
    if not method_id:
        return {}
    from .method_profiles import _profile_data_cache, get_profile
    try:
        mid = get_profile(method_id).method_id         # aliases ("FDA", "537") resolved
    except KeyError:                                     # not exported: its id as given
        mid = method_id
    data = _profile_data_cache.get(mid) or {}
    out = dict(data.get("rule_toggles") or {})
    out.update(data.get("rule_states") or {})
    # a rule's state is read over its limit boxes (limit_states): a rule
    # whose boxes are all Off is not run
    from .addon import load
    out.update(load("limit_states").rule_states(data))
    return out


def _dilution_choice(method_id):
    """The method's dilution_recovery under the linked response ratio
    ("fold", "measured", "parent", or "" unset); None when the ratio is off
    (a dilution's surrogate is then judged only where it was added back)."""
    from .method_profiles import get_linked_response_ratio, get_dilution_recovery
    if not method_id or get_linked_response_ratio(method_id) != "on":
        return None
    return get_dilution_recovery(method_id)


def _field_dilution(name, dilutions):
    from .pipeline import field_dilution
    return field_dilution(name, dilutions)


def _takes_surrogate_recovery(injection_name: str,
                              dilutions: "dict | None" = None) -> bool:
    """Does a surrogate recovery criterion apply to this injection?

    Derived from REVIEW_CHECKS, which declares `surrogate_recovery` on the
    extracted injection types and omits it from those prepared in solvent
    (CAL, ICV, CCV, CCB), so the loop and the review queue agree.

    A dilution is excluded explicitly: it is the same extract re-injected at a
    known factor, its surrogate reads the diluted value, and the windows assume
    a neat extract. `classify_injection` returns "Dilution", which is not a
    REVIEW_CHECKS key. An unrecognised name falls back to Sample, the safe
    direction: a client sample mistaken for solvent would go unchecked.
    """
    from .importer import classify_injection
    from .review_checks import REVIEW_CHECKS
    role = classify_injection(injection_name or "", dilutions)
    if role == "Dilution":
        return False
    checks = REVIEW_CHECKS.get(role)
    if checks is None:
        checks = REVIEW_CHECKS["Sample"]
    return "surrogate_recovery" in checks


def _sur_unjudged_status(profile, compound: str, matrix: str) -> str:
    """The verdict recorded for a surrogate recovery no window judges: "not
    assessed" where the method marks the compound's matrix class so (the
    lab's decision), else "no criterion" (the method sets no window). The
    certificate prints the two differently."""
    marked = getattr(profile, "sur_not_assessed", None)
    return "not assessed" if marked is not None and marked(compound, matrix) else "no criterion"


RULE_STATES = ("enforced", "evaluate", "off")


def _rule_state(toggles: dict, library_key: str) -> str:
    """The rule's state: enforced, evaluate or off. A state is read as it is;
    an old on/off switch is enforced or off; a key that is absent is enforced."""
    value = toggles.get(library_key, "enforced")
    if value in RULE_STATES:
        return value
    return "enforced" if value else "off"


def _rule_enabled(toggles: dict, library_key: str) -> bool:
    """True if the rule is enabled: enforced or evaluate (default ON when key
    absent).

    Only for keys in `qc/rules.py RULE_LIBRARY`: a key absent everywhere looks
    permanently enabled. `tests/test_rule_toggles.py` pins the library, the
    defaults and the UI to agree.
    """
    return _rule_state(toggles, library_key) != "off"


def _qc_type_state(profile, qc_type: str) -> str:
    """This method's extraction/matrix QC type's state: enforced, evaluate
    or off.

    Extraction and matrix QC (LFSM, LFSMD, MB, Dup, ...) is owned by the method
    profile, not by the instrument RULE_LIBRARY. `profile` is a MethodProfile
    object, NOT a dict — it holds the answer, this is a None-safe wrapper. No
    profile means no configuration to consult, so the check runs, enforced.
    """
    if profile is None:
        return "enforced"
    try:
        return profile.qc_type_state(qc_type)
    except AttributeError:                       # a profile predating the method
        return "enforced"


def _low_level_gate(profile, flag, window):
    """A recovery filed by the state of the tier that judged it
    (window["state"], limit_states.tier_state; a low-level tier's state
    takes the Low-level recoveries row's): (flag, advisory, judged). Off:
    not judged -- no flag, and the window says so; Evaluate: a failure is
    advisory; Enforced passes as it is."""
    from .qc_engine import TIER_OFF_BASIS
    state = (window or {}).get("state") or "enforced"
    if state == "off":
        if window is not None:
            window.update(lo=None, hi=None, basis=TIER_OFF_BASIS)
        return None, False, False
    return flag, state == "evaluate", True


def _qc_type_enabled(profile, qc_type: str) -> bool:
    """True if this method's extraction/matrix QC type is run: its state is
    Enforced or Evaluate."""
    return _qc_type_state(profile, qc_type) != "off"


class RunQueue:
    """
    Stateful review queue for one batch.

    Workflow:
        q = RunQueue(batch, review_plan)   # plan: REVIEW_CHECKS per injection role
        q.auto_evaluate()                  # run QC engine on everything
        q.pending()                        # what the human still needs to look at
        q.accept(injection, check, "AN2", "looks fine, matrix effect")
        q.save("batch_260226_queue.json")  # resume later / from home
    """

    def __init__(self, batch: Batch, review_plan: list[dict],
                 method_id: Optional[str] = None):
        self.batch = batch
        self.method_id = method_id or ""
        self.checks: list[ReviewCheck] = []
        for entry in review_plan:
            for check_name in entry["checks"]:
                self.checks.append(ReviewCheck(
                    injection_name=entry["injection_name"],
                    qc_type=entry["qc_type"],
                    check_name=check_name,
                ))

    def resolve_confirmations(self):
        """Settle the `identity_confirmation` checks once detection is known.

        FDA §10.2(4) applies only to a POSITIVE of a single-transition analyte.
        Detection is decided in `pipeline.build_summary`, which runs after
        auto_evaluate() and consumes its is_results, so this is a later pass;
        auto_evaluate leaves the check PENDING: it is not in _CHECK_KINDS.

        PENDING where a confirmation is owed, with the prompt attached;
        AUTO_PASS where nothing detected needs confirming. AUTO_PASS means the
        rule does not apply to this injection, not that the confirmation was
        done: an owed confirmation is closed by a reviewer accepting the check
        with the LC-HRMS result through `accept()`.

        Idempotent.
        """
        owed = {}
        for entry in getattr(self.batch, "confirmations_required", None) or []:
            owed.setdefault(entry.get("sample_injection"), []).append(entry)

        for chk in self.checks:
            if chk.check_name != "identity_confirmation":
                continue
            entries = owed.get(chk.injection_name)
            if not entries:
                chk.status = CheckStatus.AUTO_PASS
                chk.flags = []
                continue
            chk.status = CheckStatus.PENDING
            chk.flags = [{
                "Source": "FDA §10.2(4) confirmation",
                "Analyte": e.get("analyte"),
                "Injection Name": chk.injection_name,
                "Value": "positive detect",
                "Issue": e.get("prompt"),
                "Link": "",
            } for e in entries]
        return sum(len(v) for v in owed.values())

    # ── automatic evaluation ──────────────────────────────────────────────────
    def _scaled_spike(self, inj, spike):
        """(expected spike, problem). Spike levels entered before the amount
        adjustment are scaled by the portion's nominal / actual amount; with
        no ratio (no nominal amount, no recorded amount) it is not judged."""
        if spike is None or getattr(self.batch, "spike_basis", "") != "before":
            return spike, ""
        ratio = (getattr(self.batch, "spike_scales", None) or {}).get(inj)
        if ratio is None:
            return None, ("{0}: spike levels are entered before the amount adjustment, but "
                          "the portion's amount or the matrix's nominal amount (Sample "
                          "correction) is not recorded".format(inj))
        return spike * ratio, ""

    def _mxb_by_reference(self, profile, inj, analyte, row, matrix, flags_by_injection, _record_gap,
                          advisory=False):
        """A matrix blank whose lot carries a reference value for `analyte`,
        in a method that judges it so (Matrix blanks): its recovery against
        that value, with the LFSM recovery tolerances; `advisory` when its row
        is in the state Evaluate.
        False when it is to be judged against the blank limit instead."""
        from .method_profiles import get_mxb_reference_recovery
        if not get_mxb_reference_recovery(self.method_id):
            return False
        ref = (getattr(self.batch, "mxb_references", None) or {}).get(inj) or {}
        assigned = (ref.get("levels") or {}).get(analyte)
        if assigned in (None, "", 0):
            return False
        conc = reported_conc(row)
        unit = (getattr(row, "conc_units", "") or "").strip()
        if conc is None:
            return False
        # the matrix-blank rule: compared only in the same unit, never
        # converted (matrix_blank.same_unit)
        if not unit or (ref.get("unit") or "").strip().lower() != unit.lower():
            _record_gap("MxB", analyte, UnconfiguredCriterion(
                "{0}: reference value in {1}, result in {2}: not compared.".format(
                    inj, ref.get("unit") or "no unit", unit or "no unit")))
            return True
        win = {}
        try:
            flag = recovery_check_profiled(profile, analyte, matrix, "LFSM",
                                           conc / float(assigned) * 100.0, inj,
                                           conc=float(assigned), window=win)
        except UnconfiguredCriterion as exc:
            _record_gap("MxB", analyte, exc)
            return True
        self.batch.lcs_results.append({
            "qc_type": "MxB", "analyte": analyte, "injection_name": inj,
            "recovery": conc / float(assigned) * 100.0, "passed": flag is None,
            "spike": float(assigned), "spike_unit": ref.get("unit") or "",
            "lo": win.get("lo"), "hi": win.get("hi"), "basis": win.get("basis", ""),
            "issue": flag.issue if flag is not None else "",
            "advisory": flag is not None and advisory})
        if flag is not None:
            flags_by_injection.setdefault(inj, []).append(QCFlag(
                source="MxB", check_kind=KIND_BLANK, analyte=flag.analyte,
                injection_name=inj, value=flag.value, issue=flag.issue, advisory=advisory))
        return True

    def auto_evaluate(self):
        """
        Run the full QC engine and mark checks AUTO_PASS / AUTO_FAIL.
        Runs every automatic check once, in one pass.

        Rule toggles come from the method profile (_load_rule_toggles).
        LIBRARY_KEY → engine block mapping (rules.py LIBRARY_KEY_TO_ENGINE_CHECKS):
          is_response   → is_raw_check
          rrt_deviation → rrt_check_profiled
          ion_ratio     → qual_quan_check
          cal_r2        → calibration_check_profiled (also covers ccv_recovery checks)
          ccv_recovery  → calibration_check_profiled (run if EITHER cal_r2 or ccv_recovery is on)
          sn_min        → signal_to_noise_check
        A criterion an enabled rule needs and the method leaves unset is a gap:
        not judged, and filed so that it holds release.
        """
        all_rows = self.batch.injections

        # A dilution is the same extract re-injected at a known factor, run to
        # bring an over-range analyte back onto the curve. It is not an
        # independent measurement, so the acceptance rules do not apply to it:
        # its retention times, ion ratios, calibration agreement and recovery
        # would all be judged against criteria that assume a neat extract.
        #
        # The ONE thing a dilution must still demonstrate is that the internal
        # standard behaved — that is what shows the dilution itself was made
        # correctly — so is_raw_check below is given the unfiltered rows.
        dilutions = getattr(self.batch, "dilutions", None) or {}
        rows = [r for r in all_rows
                if classify_injection(r.injection_name, dilutions) != "Dilution"]
        if dilutions:
            skipped = len({r.injection_name for r in all_rows}) - \
                len({r.injection_name for r in rows})
            logger.info("QC rules skip %d dilution injection(s); internal "
                        "standard consistency is still checked on them",
                        skipped)

        flags_by_injection: dict[str, list[QCFlag]] = {}
        toggles = _load_rule_toggles(self.method_id)

        def _advisory(*keys):
            """True when the rules behind a flag are all in the state
            Evaluate over their boxes (a rule that is off files nothing)."""
            states = [_rule_state(toggles, k) for k in keys]
            states = [st for st in states if st != "off"]
            return bool(states) and all(st == "evaluate" for st in states)

        if not self.method_id:
            # never another method's panel and criteria
            raise ValueError("This run names no method, so its QC cannot be "
                             "judged. Give the run its method.")
        _method = self.method_id
        _matrix = self.batch.matrix or ""
        _analytes = (_get_included_analytes(_method, _matrix)
                     if _matrix else _get_analytes(_method))

        # The components of a summed analyte are measured and go into the
        # reported result but are not reportable, so they are added to the
        # panel here. A component is not spiked nor given an MDL on its own:
        # spike recovery (LFB/LCS, LFSM, LFSMD) and the MDL check judge the
        # summed analyte only.
        _components = set()
        _sums = {}                    # reported keyword -> its components
        from .method_profiles import get_isomer_summation
        for pair in (get_isomer_summation(_method) or []):
            if not pair.get("enabled", True):
                continue
            _sums[pair.get("reported") or ""] = [n for n in [pair.get("linear")] + list(
                pair.get("branched_list") or []) if n]
            for name in [pair.get("linear")] + list(pair.get("branched_list") or []):
                if name:
                    _components.add(name)
                if name and name not in _analytes:
                    _analytes = list(_analytes) + [name]

        # A criterion the method never configured must not be silently skipped
        # and must not stop the run: the batch still imports, the gap is
        # recorded against the QC type it belongs to, and Data Review holds the
        # report until someone sets the value. `unconfigured` is read by
        # qc_store (which files it as an `unevaluated` QC result) and by the
        # deviation raised on the worksheet.
        if not hasattr(self.batch, "unconfigured"):
            self.batch.unconfigured = []
        # every CCV judged, for the QC results (qc_store)
        self.batch.ccv_results = []
        # every sample duplicate judged, for the QC results
        self.batch.dup_results = []
        self.batch.lcs_results = []          # every LFB / LCS judged, likewise
        seen_gaps = set()

        def _record_gap(qc_type, analyte, exc):
            """File an unconfigured-criterion gap, once per distinct reason.

            Separate from _guard because a check whose result is a single
            flag (or None) cannot use _guard's "return []" convention: [] is
            falsy but is not None, so "unconfigured" and "passed" would be
            indistinguishable at the call site.
            """
            key = (qc_type, str(exc))
            if key in seen_gaps:
                return
            seen_gaps.add(key)
            self.batch.unconfigured.append({
                "qc_type": qc_type,
                "analyte": analyte,
                "method_id": self.method_id or "",
                "reason": str(exc),
            })
            logger.error("%s not evaluated — %s", qc_type, exc)

        def _guard(qc_type, analyte, fn, *args):
            """Run a profiled check; record rather than raise when unconfigured."""
            try:
                return fn(*args)
            except UnconfiguredCriterion as exc:
                _record_gap(qc_type, analyte, exc)
                return []

        def _guard_is(rows_, is_cmp, dils, method):
            return _guard("IS Response", is_cmp, is_raw_check,
                          rows_, is_cmp, dils, method, _matrix)

        def _monitored(qc_type):
            """The method's labelled standards; a method naming none is a gap
            recorded against `qc_type`, never an empty, silent check."""
            try:
                return _get_is_list(_method)
            except UnconfiguredCriterion as exc:
                _record_gap(qc_type, "", exc)
                return []

        # The method profile drives every check below through the profiled
        # variants, never the flat CRITERIA table. A method with no exported
        # profile is refused.
        try:
            profile = _get_method_profile(self.method_id)
        except KeyError as exc:
            raise RuntimeError("%s The run's QC is not judged without it." % (
                exc.args[0] if exc.args else exc))

        # Every limit box carries its own state (limit_states). A box judged
        # with no limit is filed here once: Enforced holds release as an
        # unconfigured criterion; Evaluate lets the run go on, filed as an
        # advisory "no limit set"; Off is not judged.
        if not hasattr(self.batch, "advisory_gaps"):
            self.batch.advisory_gaps = []
        _pdata = getattr(profile, "_profile_data", lambda: {})()
        _limits = _load_addon("limit_states")
        # the ICV's own deviation is owed only by a run that holds an ICV
        _has_icv = any(classify_injection(r.injection_name, dilutions) == "ICV" for r in all_rows)
        for _box, _state in _limits.empty_boxes(_pdata):
            if _box["key"] == "icv" and not _has_icv:
                continue
            _gap = UnconfiguredCriterion("{0}: {1}".format(self.method_id, _limits.no_limit_words(_box)))
            _type = _limits.GAP_TYPES.get(_box["key"], _box["label"])
            if _state == "enforced":
                _record_gap(_type, "", _gap)
            else:
                self.batch.advisory_gaps.append({"qc_type": _limits.ADVISORY_GAP_TYPE, "analyte": "",
                                                 "method_id": self.method_id or "", "reason": str(_gap)})

        def _box(key):
            return profile.limit_state(key)

        def _judged(key):
            return profile.limit_judged(key)

        # 1. IS Raw (is_response rule: its two windows, each its own box)
        if _judged("is_response") or _judged("is_vs_ccv"):
            for is_cmp in _monitored("IS Response"):
                # unfiltered: dilutions ARE checked for IS consistency
                for res in _guard_is(all_rows, is_cmp, dilutions, _method):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    # Record every result, not only the failures: the QC
                    # Summary's IS row and its gate need the passes too.
                    self.batch.is_results.append(res)

        # 2. RT Deviation (rrt_deviation rule): either tolerance's box
        rt_enabled  = _judged("rrt_deviation.relative") or _judged("rrt_deviation.absolute")
        # 3. Qual-Quan (ion_ratio rule)
        iq_enabled  = _judged("ion_ratio")
        # 4. Calibration (cal_r2 OR ccv_recovery — run if either is on)
        cal_enabled  = _rule_enabled(toggles, "cal_r2") or _rule_enabled(toggles, "ccv_recovery")
        # r2 itself only under its own box (the point deviations by theirs)
        r2_enabled   = _judged("cal_r2")
        # 5. Signal-to-Noise (sn_min rule): the quantifier's and the
        # confirmation ion's boxes
        sn_enabled   = _judged("sn_min.quan") or _judged("sn_min.confirm")
        # the method's own quantifier and confirmation-ion S/N limits: the
        # S/N check judges samples on them, and the calibration check holds
        # the lowest calibrator of a raw run's curve to them. Both are the
        # requirement of a method that judges S/N: with its S/N rule Off
        # neither runs, whatever limits it holds, and no limit is owed.
        # An empty limit was filed above, once; a box that is Off reads None.
        sn_limits = {}
        if sn_enabled:
            try:
                _conf = profile.confirmation_rule()
                sn_limits = {"quan_min": _conf.sn_min_quant, "confirm_min": _conf.sn_min_confirm}
            except UnconfiguredCriterion as exc:
                _record_gap("Signal-to-Noise", "", exc)
        if sn_enabled and not sn_limits:
            sn_enabled = False              # the gap is filed: not judged
        ion_tol = None
        if iq_enabled:
            try:
                ion_tol = profile.confirmation_rule().ion_ratio_tol_pct
            except UnconfiguredCriterion as exc:
                _record_gap("Ion Ratio", "", exc)
            iq_enabled = ion_tol is not None
        _calibration_check = functools.partial(calibration_check_profiled,
                                               sn_quan_min=sn_limits.get("quan_min"),
                                               sn_confirm_min=sn_limits.get("confirm_min"))
        # 6. LFSM/LFSMD gate on the method profile's qc_acceptance entry, not
        # on a rule toggle: RULE_LIBRARY is instrument-level, and extraction
        # and matrix QC (LCS, LFB, LFSM, LFSMD, MB, LRB, Dup, MxB) is owned by
        # the method profile, where its switch and limits live.
        lfsm_enabled  = _qc_type_enabled(profile, "LFSM")
        lfsmd_enabled = _qc_type_enabled(profile, "LFSMD")
        # a QC type in the state Evaluate is judged, and what it files is
        # advisory: Data Review shows it and nothing is held on it
        # (each tier's own state then files its failures: _low_level_gate)
        lfsm_advisory = _qc_type_state(profile, "LFSM") == "evaluate"
        lfsmd_advisory = _qc_type_state(profile, "LFSMD") == "evaluate"
        if lfsmd_enabled and not lfsm_enabled:
            # The spike/duplicate RPD is computed from the LFSM recovery
            # (lfsm_res.recovery_pct, .unfortified_conc, .spike_value_ppt), so
            # with LFSM off LFSMD has nothing to compare against. Say so rather
            # than show an enabled check that can never fire.
            logger.warning(
                "%s: LFSMD is enabled but LFSM is disabled in the method "
                "profile. The spike/duplicate RPD is derived from the LFSM "
                "recovery, so NO LFSMD result will be evaluated. Enable LFSM "
                "or disable LFSMD.", self.method_id or "method")

        for analyte in _analytes:
            if rt_enabled:
                for res in _guard("RT", analyte, rrt_check_profiled, profile, rows, analyte):
                    if res.flag:
                        # advisory as the box of the tolerance used (rrt_check_profiled)
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.rt_results.append(res)
            if iq_enabled:
                for res in qual_quan_check(rows, analyte, ion_tol):
                    if res.flag:
                        res.flag.advisory = _box("ion_ratio") == "evaluate"
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.qual_quan_results.append(res)
            if cal_enabled:
                for res in _guard("Calibration", analyte, _calibration_check,
                                  profile, rows, analyte, r2_enabled):
                    if res.flag:
                        # advisory as the boxes that failed (calibration_check_profiled)
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.cal_results.append(res)
                # CCV recovery is a criterion separate from calibration
                # linearity, with its own check.
                # each CCV and ICV is filed by the box whose window judged
                # it (ccv_check_profiled, icv_check_profiled)
                if profile and _judged("ccv_recovery"):
                    for flag in _guard("CCV", analyte, ccv_check_profiled,
                                       profile, rows, analyte, _matrix,
                                       self.batch.ccv_results):
                        flags_by_injection.setdefault(
                            flag.injection_name, []).append(flag)
                # the ICV (QCS) verifies the curve: its own box, or the CCV's
                # window where the method judges it so
                icv_box = "ccv_recovery" if profile.icv_same_as_ccv() else "icv"
                if profile and _judged(icv_box):
                    for flag in _guard("ICV", analyte, icv_check_profiled,
                                       profile, rows, analyte, _matrix,
                                       self.batch.ccv_results):
                        flags_by_injection.setdefault(
                            flag.injection_name, []).append(flag)
            if sn_enabled:
                for flag in signal_to_noise_check(rows, analyte, sn_limits["quan_min"],
                                                  sn_limits["confirm_min"]):
                    # J is the quantifier's box, N.C. the confirmation ion's
                    flag.advisory = _box("sn_min.quan" if flag.issue == "(J)" else "sn_min.confirm") == "evaluate"
                    flags_by_injection.setdefault(flag.injection_name, []).append(flag)
            # a qualifier the analyst deleted confirms nothing: N.C. whatever
            # the S/N rule's switch or state, never advisory, on a dilution
            # too, filed under the sample it was diluted from
            for flag in qualifier_deleted_check(all_rows, analyte):
                flag.advisory = False
                flags_by_injection.setdefault(
                    dilution_routes.file_under(flag.injection_name, dilutions), []).append(flag)

        # 5b. Surrogate / extracted-internal-standard recovery. The
        # instrument reports each labelled compound's % recovery in column 30
        # (`InstrumentRow.pct_recovery_is`); the method resolves its window
        # through `qc_rules(..., "SUR")` (FDA guidance-only 50-150% per
        # Sec2024.10.1(5), EPA 537.1 Sec9.3.5 70-130%, EPA 1633A per-analyte x
        # matrix-class from Tables 6/8).
        eis_evaluated = set()
        # the Rule Toggles switch
        if profile is not None and _rule_enabled(toggles, "surrogate_recovery"):
            # the METHOD's injection standards (its labelled-standards grid)
            _injection_is = _get_injection_standards(_method)
            # a method whose CCCs carry the surrogates judges them there too
            # (EPA 537.1 §9.3.5.1: "a sample, blank, or CCC")
            sur_in_ccv = bool(getattr(profile, "surrogate_recovery_in_ccv", lambda: False)())
            for compound in _monitored("SUR"):
                # The injection standard goes in at reconstitution, AFTER
                # extraction, so it has no recovery to measure -- what its area
                # tests is instrument response, which is KIND_IS_RESPONSE's job.
                # It is in the monitored list for that check, not for this one.
                if compound in _injection_is:
                    continue
                # Resolve the window ONCE per compound. A compound whose method
                # configures no window must not mark its injections evaluated:
                # that is the difference between "recovery was acceptable" and
                # "nobody said what acceptable is", and AUTO_PASS may only mean
                # the first.
                def _verdicts(status="no criterion"):
                    """Record, for the certificate's QC sub-table, the recoveries of a compound no window judges:
                    `status` ("no criterion", or "not assessed" for a class the method marks so), never a pass."""
                    for row in rows:
                        if ((row.compound_name or "").strip() != compound
                                or row.pct_recovery_is is None
                                or not _takes_surrogate_recovery(row.injection_name, dilutions)):
                            continue
                        value = float(row.pct_recovery_is)
                        entry = {"injection_name": row.injection_name, "compound": compound,
                                 "value": value, "judged": profile.judged_recovery(value, _matrix),
                                 "window_min": None, "window_max": None,
                                 "guidance": False, "status": status,
                                 "std_role": "surrogate"}
                        self.batch.surrogate_results.append(entry)

                try:
                    rule = profile.qc_rules(compound, _matrix, "SUR")
                except UnconfiguredCriterion as exc:
                    # no window: Enforced holds release, Evaluate advises
                    if _box("surrogate_recovery") == "evaluate":
                        self.batch.advisory_gaps.append({"qc_type": _limits.ADVISORY_GAP_TYPE,
                                                         "analyte": compound,
                                                         "method_id": self.method_id or "", "reason": str(exc)})
                    else:
                        _record_gap("Surrogate Recovery", compound, exc)
                    _verdicts()
                    continue
                if rule is None or rule.recovery_min is None:
                    _verdicts(_sur_unjudged_status(profile, compound, _matrix))
                    continue
                # in a CCV, the method's own CCV window when it sets one
                # (Calibration & CCV); half set is a gap for the CCVs only
                ccv_rule = rule
                if sur_in_ccv:
                    try:
                        ccv_rule = getattr(profile, "ccv_recovery_rule", lambda r: r)(rule)
                    except UnconfiguredCriterion as exc:
                        _record_gap("Surrogate Recovery", compound, exc)
                        ccv_rule = None
                # the CCV's own window is its own box (Surrogate recovery in
                # CCVs): in Evaluate its failure is advisory
                ccv_own = ccv_rule is not None and ccv_rule is not rule
                # `rows`, not `all_rows`: dilutions are excluded for the same
                # reason RT, ion-ratio and calibration exclude them. is_raw_check
                # above is the deliberate exception, and it corrects for the
                # recorded factor internally; a recovery does not. The other
                # exception: a dilution the surrogate was ADDED to (re-spiked,
                # or added / topped up when it was made) is judged against
                # the method's window, its low end the method's lowest EIS
                # recovery in a diluted extract when set.
                _dil_settings = dilution_routes.settings_of(getattr(profile, "_profile_data", lambda: {})())
                # Under the linked response ratio the method's one choice
                # (dilution_recovery) says how a diluted field sample's
                # recovery is taken: its own times its fold, its own as
                # measured, or its parent's (judged on the parent already);
                # unset, none is judged (pipeline.dilution_recovery_flags
                # flags the dilution). Extracted QC is never diluted.
                _linked_dil = _dilution_choice(_method)
                if _linked_dil is None:
                    _respiked = [r for r in all_rows
                                 if classify_injection(r.injection_name, dilutions) == "Dilution"
                                 and dilution_routes.surrogate_added(dilutions.get(r.injection_name))]
                else:
                    _respiked = [r for r in all_rows if _linked_dil in ("fold", "measured")
                                 and classify_injection(r.injection_name, dilutions) == "Dilution"
                                 and _field_dilution(r.injection_name, dilutions)]
                for row in rows + _respiked:
                    if (row.compound_name or "").strip() != compound:
                        continue
                    if row.pct_recovery_is is None:
                        continue
                    diluted = row in _respiked
                    pct = float(row.pct_recovery_is)
                    fold = None
                    if diluted and _linked_dil == "fold":
                        try:
                            fold = float((dilutions.get(row.injection_name) or {}).get("factor"))
                        except (TypeError, ValueError):
                            fold = None
                        if not fold or fold <= 0:
                            continue             # no fold recorded: nothing to correct it with
                        pct = pct * fold
                    in_ccv = sur_in_ccv and classify_injection(row.injection_name, dilutions) == "CCV"
                    if not (diluted or _takes_surrogate_recovery(row.injection_name, dilutions) or in_ccv):
                        continue
                    # the box that judges this row: Off, it is not judged.
                    # A CCV's labelled standards are judged by Surrogate
                    # recovery in CCVs: Off, none of them is judged; empty,
                    # the sample window judges them in the sample box's state.
                    if in_ccv and _box("surrogate_ccv") == "off":
                        continue
                    box = "surrogate_ccv" if (in_ccv and ccv_own) else "surrogate_recovery"
                    if _box(box) == "off":
                        continue
                    floor_state = _box("dilution_eis_floor") if diluted else "off"
                    row_rule = (dilution_routes.dilution_rule(rule, _dil_settings, floor_state != "off")
                                if diluted else ccv_rule if in_ccv else rule)
                    if row_rule is None:
                        continue                     # its gap is filed above
                    evaluate = _box(box) == "evaluate"
                    raw_flag = recovery_check_profiled(
                        profile, compound, _matrix, "SUR",
                        pct, row.injection_name, rule=row_rule)
                    # the check's own verdict, for the certificate, with
                    # whether its box was Evaluate (lab only: the
                    # certificate prints no verdict for it)
                    self.batch.surrogate_results.append(dict({
                        "injection_name": row.injection_name, "compound": compound,
                        "value": pct,
                        "window_min": row_rule.recovery_min, "window_max": row_rule.recovery_max,
                        "judged": profile.judged_recovery(pct, _matrix),
                        "guidance": evaluate,
                        "status": "within" if raw_flag is None else "outside",
                        "std_role": "surrogate"},
                        **({"dilution": _linked_dil, "measured": float(row.pct_recovery_is),
                            "fold": fold} if diluted and _linked_dil else {})))
                    # a dilution's result is filed on the sample it was diluted
                    # from (it has no checks of its own); its own pass decides
                    # nothing about that sample
                    file_as = dilution_routes.file_under(row.injection_name, dilutions) if diluted \
                        else row.injection_name
                    if raw_flag is None:
                        # the lowest EIS recovery in a diluted extract in the
                        # state Evaluate: a result between the floor and the
                        # window's own low end passes, filed as an advisory
                        # for the lab (no check kind: the check still passes)
                        band = (floor_state == "evaluate" and rule.recovery_min is not None
                                and profile.judged_recovery(pct, _matrix) < rule.recovery_min)
                        if band:
                            flags_by_injection.setdefault(file_as, []).append(QCFlag(
                                source="{0} surrogate recovery in a diluted extract".format(_method),
                                analyte=compound, injection_name=row.injection_name,
                                value="{0}%".format(profile.recovery_text(profile.judged_recovery(pct, _matrix))),
                                issue="(REC) {0}% below the method's window {1:g}\u2013{2:g}%, above the lowest "
                                      "EIS recovery in a diluted extract {3:g}%".format(
                                          profile.recovery_text(profile.judged_recovery(pct, _matrix)),
                                          rule.recovery_min, rule.recovery_max, row_rule.recovery_min),
                                advisory=True))
                        if not diluted:
                            eis_evaluated.add(row.injection_name)
                        continue
                    # a failure fails the check; in Evaluate it is advisory
                    # (Data Review shows it, it holds nothing, prints nothing)
                    eis_evaluated.add(file_as)
                    flags_by_injection.setdefault(
                        file_as, []).append(QCFlag(
                            source="{0} surrogate recovery".format(_method),
                            check_kind=KIND_SURROGATE,
                            analyte=raw_flag.analyte,
                            injection_name=raw_flag.injection_name,
                            value=raw_flag.value,
                            issue=raw_flag.issue,
                            advisory=evaluate,
                        ))

        # 6. LFSM recovery + LFSMD RPD (per-analyte tiered limits from method profile)
        lfsm_evaluated  = set()   # injection names where spike was resolved + check ran
        lfsmd_evaluated = set()
        unevaluated_lfsm = {}     # lfsm_inj -> why it could not be judged
        unevaluated_lfsmd = {}    # lfsmd_inj -> why an RPD could not be judged
        lfsm_no_reading = set()   # (lfsm_inj, analyte): a raw spike with no reading
        # LFSM injections whose every recovery was a low-level one with the
        # Low-level recoveries row Off: nothing judged, by the lab's choice --
        # the check stays PENDING and files no gap, as a QC type set Off does
        low_level_off_lfsm = set()
        # the extraction's spike record: the only source of spikes
        spikes = getattr(self.batch, "spikes", None) or {}

        if lfsm_enabled or lfsmd_enabled:
            # profile is resolved once above; never re-fetch it here
            matrix = self.batch.matrix or ""
            conc_lookup = {}
            for row in rows:
                conc_lookup.setdefault(row.injection_name, []).append(row)
            from .pipeline import _has_sample_basis, _is_native, _isomer_parts
            _parts = _isomer_parts(self.method_id)

            # Unique LFSM injection names (not duplicates), from the
            # extraction's spike record.
            spikes = getattr(self.batch, "spikes", None) or {}
            seen_lfsm = set()
            lfsm_inj_names = []
            for row in rows:
                name = row.injection_name
                if name in seen_lfsm:
                    continue
                # The extraction's spike record is the ONLY source: no parent or level is read from a name. A
                # spike missing from it is held, named, by the gap below.
                if name not in spikes:
                    continue
                if (spikes[name].get("qc_type") or classify_injection(name, dilutions)) != "LFSM":
                    continue
                seen_lfsm.add(name)
                lfsm_inj_names.append(name)

            # Per-LFSM-injection evaluation
            lfsm_results_by_inj = {}   # lfsm_inj → {analyte: LFSMResult}

            if lfsm_enabled and profile is not None:
                for lfsm_inj in lfsm_inj_names:
                    pedigree = spikes.get(lfsm_inj) or {}
                    level_label = pedigree.get("level") or ""
                    # What was actually spiked beats the nominal level; both
                    # are in the matrix's reporting unit.
                    spike_val, spike_units = _spike_amount(pedigree)
                    if spike_val is None:
                        spike_val, spike_units = profile.resolve_spike(
                            "LFSM", level_label, matrix=matrix)
                    spike_val, scale_problem = self._scaled_spike(lfsm_inj, spike_val)
                    if scale_problem:
                        unevaluated_lfsm[lfsm_inj] = scale_problem
                        continue
                    if spike_val is None or spike_val == 0:
                        logger.info("No spike level for %s — LFSM recovery "
                                    "stays pending", lfsm_inj)
                        unevaluated_lfsm[lfsm_inj] = (
                            "no spike level for {0} / {1} (Recovery Tiers: spike "
                            "levels)".format(level_label or "this level", matrix or "this matrix"))
                        continue

                    # The spike level and the results must be in the same
                    # units before a recovery means anything. Converting needs
                    # the aliquot mass and final extract volume, a modelling
                    # decision, so the check reports that it could NOT be
                    # evaluated rather than assert a false failure.
                    # the unit of the spike's native analytes on the sample
                    # basis: an isotope standard's or surrogate's row stays
                    # in the extract's unit and never sets it
                    result_units = ""
                    for row in conc_lookup.get(lfsm_inj, []):
                        if not (_is_native(row, _parts) and _has_sample_basis(row)):
                            continue
                        unit = (getattr(row, "conc_units", "") or "").strip()
                        if unit and unit.lower() != "nan":
                            result_units = unit
                            break
                    if result_units and not _units_compatible(spike_units,
                                                              result_units):
                        logger.warning(
                            "LFSM %s not evaluated: spike recorded in %s but "
                            "results are in %s. Record the spike in the result "
                            "units, or configure the extract conversion.",
                            lfsm_inj, spike_units, result_units)
                        unevaluated_lfsm[lfsm_inj] = (
                            "spike level is in {0}, results are in {1}".format(
                                spike_units, result_units))
                        continue

                    parent_inj = pedigree.get("parent") or ""
                    lfsm_results_by_inj[lfsm_inj] = {}
                    lfsm_judged = lfsm_low_off = False

                    for analyte in _analytes:
                        if analyte in _components:
                            continue          # spiked / limited as its summed analyte
                        fortified = _get_conc(lfsm_inj, analyte, conc_lookup, _sums)
                        # a raw spike with no reading is judged at 0 % recovery
                        missing = (raw_no_reading(_summed_row(conc_lookup.get(lfsm_inj, []), analyte, _sums))
                                   if fortified is None else None)
                        if fortified is None and missing is None:
                            continue
                        unfort = _get_conc(parent_inj, analyte, conc_lookup, _sums) or 0.0
                        if missing:
                            fortified, recovery_pct = 0.0, 0.0
                            lfsm_no_reading.add((lfsm_inj, analyte))
                        else:
                            recovery_pct = (fortified - unfort) / spike_val * 100.0
                        lfsm_win = {}

                        if profile.judged_recovery(recovery_pct, matrix) < 0:
                            # Physically impossible: the fortified sample
                            # measured LESS than the unfortified one. Reporting
                            # it as "outside 65-135%" sends a reviewer to look
                            # at recovery when the real question is whether the
                            # spike went in, or whether the LFSM is paired with
                            # the right parent.
                            raw_flag = QCFlag(
                                source="LFSM & LFSMD", analyte=analyte,
                                check_kind=KIND_LFSM,
                                injection_name=lfsm_inj,
                                value="{0:.1f}%".format(recovery_pct),
                                issue=("(REC) negative recovery — the spiked "
                                       "sample measured lower than its "
                                       "unspiked parent {0}".format(parent_inj)),
                            )
                        else:
                            try:
                                raw_flag = recovery_check_profiled(
                                    profile, analyte, matrix, "LFSM",
                                    recovery_pct, lfsm_inj, conc=spike_val,
                                    rl=profile.reporting_limits(analyte, matrix, getattr(self.batch, "acid_basis", None))[0],
                                    window=lfsm_win)
                            except UnconfiguredCriterion as exc:
                                _record_gap("LFSM", analyte, exc)
                                continue
                            if missing:
                                raw_flag = QCFlag(
                                    source="LFSM & LFSMD", analyte=analyte, check_kind=KIND_LFSM,
                                    injection_name=lfsm_inj, value="0%",
                                    issue=no_reading_issue("REC", missing))
                        raw_flag, low_advisory, low_judged = _low_level_gate(profile, raw_flag, lfsm_win)
                        lfsm_judged = lfsm_judged or low_judged
                        lfsm_low_off = lfsm_low_off or not low_judged
                        flag = None
                        if raw_flag is not None:
                            # The source string is for the reader; check_kind is
                            # what the review queue matches on.
                            flag = QCFlag(
                                source="LFSM & LFSMD",
                                check_kind=KIND_LFSM,
                                analyte=raw_flag.analyte,
                                injection_name=raw_flag.injection_name,
                                value=raw_flag.value,
                                issue=raw_flag.issue,
                                advisory=lfsm_advisory or low_advisory,
                            )
                            flags_by_injection.setdefault(lfsm_inj, []).append(flag)

                        lfsm_result = LFSMResult(
                            window=lfsm_win or None,
                            analyte=analyte,
                            lfsm_injection=lfsm_inj,
                            parent_injection=parent_inj,
                            spike_value_ppt=spike_val,
                            fortified_conc=fortified,
                            unfortified_conc=unfort,
                            recovery_pct=recovery_pct,
                            flag=flag,
                        )
                        if low_judged:      # a low-level recovery, its row Off: not filed
                            self.batch.lfsm_results.append(lfsm_result)
                        # still the LFSMD's pair: its RPD is no low-level recovery
                        lfsm_results_by_inj[lfsm_inj][analyte] = lfsm_result

                    if lfsm_low_off and not lfsm_judged:
                        low_level_off_lfsm.add(lfsm_inj)
                    else:
                        lfsm_evaluated.add(lfsm_inj)

            # Three or more LFSMs at one spike level: their precision is the
            # RSD of the recoveries of the spikes at that level, the LFSMDs'
            # with the LFSMs', judged against the method's LFSMD RPD limit
            # after the duplicates are read (below); their duplicates' RPD
            # is not judged
            rsd_levels = {}
            rsd_dups = {}                        # (level, analyte) -> [(LFSMD, its result)]
            if lfsmd_enabled and profile is not None:
                by_level = {}
                for inj in lfsm_inj_names:
                    level = (spikes.get(inj) or {}).get("level") or ""
                    if level and lfsm_results_by_inj.get(inj):
                        by_level.setdefault(level, []).append(inj)
                rsd_levels = dict((lv, injs) for lv, injs in by_level.items() if len(injs) >= RSD_MIN_SPIKES)

            # LFSMD RPD evaluation (requires matching LFSM result)
            if lfsmd_enabled and profile is not None:
                # Pair the duplicate with its LFSM through the extraction
                # pedigree: the two spiked injections sharing a parent.
                seen_lfsmd = set()
                for row in rows:
                    name = row.injection_name
                    if name in seen_lfsmd:
                        continue
                    lfsm_inj = None
                    if name not in spikes:
                        continue
                    entry = spikes[name] or {}
                    if (entry.get("qc_type") or classify_injection(name, dilutions)) != "LFSMD":
                        continue
                    # the LFSM it duplicates, as recorded; older records
                    # pair by the shared parent, only where one LFSM has it:
                    # with several, the pair is never guessed
                    if entry.get("lfsm") in lfsm_inj_names:
                        lfsm_inj = entry["lfsm"]
                    else:
                        same = [c for c in lfsm_inj_names
                                if (spikes.get(c) or {}).get("parent") == entry.get("parent")]
                        if len(same) > 1:
                            _record_gap("LFSMD", "", UnconfiguredCriterion(
                                "{0}: the LFSM it duplicates is not recorded, and {1} LFSMs share its "
                                "parent {2} ({3}): record its LFSM on the extraction batch".format(
                                    name, len(same), entry.get("parent") or "?", ", ".join(same))))
                            continue
                        lfsm_inj = same[0] if same else None
                    if lfsm_inj is None:
                        logger.info("No recorded LFSM pairs with %s — "
                                    "RPD stays pending", name)
                        continue
                    lfsm_entry = spikes.get(lfsm_inj) or {}
                    if ((entry.get("level") or "") != (lfsm_entry.get("level") or "")
                            or (_spike_amount(entry)[0] not in (None, _spike_amount(lfsm_entry)[0]))):
                        # the duplicate is spiked at its LFSM's level
                        _record_gap("LFSMD", "", UnconfiguredCriterion(
                            "{0}: recorded at level {1} / {2} ppt, its LFSM {3} at {4} / {5} ppt; "
                            "the duplicate must match its LFSM".format(
                                name, entry.get("level") or "?", _spike_amount(entry)[0],
                                lfsm_inj, lfsm_entry.get("level") or "?",
                                _spike_amount(lfsm_entry)[0])))
                        continue
                    seen_lfsmd.add(name)
                    inj_lfsm_results = lfsm_results_by_inj.get(lfsm_inj, {})
                    if not inj_lfsm_results:
                        continue  # LFSM not evaluated → stays PENDING

                    for analyte in _analytes:
                        if analyte in _components:
                            continue          # spiked / limited as its summed analyte
                        lfsm_res = inj_lfsm_results.get(analyte)
                        if lfsm_res is None:
                            continue
                        fortified_dup = _get_conc(name, analyte, conc_lookup, _sums)
                        # a raw duplicate with no reading is judged at 0 % recovery
                        missing_dup = (raw_no_reading(_summed_row(conc_lookup.get(name, []), analyte, _sums))
                                       if fortified_dup is None else None)
                        if fortified_dup is None and missing_dup is None:
                            continue
                        if missing_dup:
                            fortified_dup, rec_dup = 0.0, 0.0
                        else:
                            rec_dup = ((fortified_dup - lfsm_res.unfortified_conc)
                                       / lfsm_res.spike_value_ppt * 100.0)

                        # The duplicate's own recovery, against the LFSM
                        # window at the LFSM's spike level: the duplicate is
                        # spiked at the same level.
                        rec_flag, rec_judged = None, False
                        rec_win, rpd_win = {}, {}
                        try:
                            raw_rec = recovery_check_profiled(
                                profile, analyte, matrix, "LFSM", rec_dup, name,
                                conc=lfsm_res.spike_value_ppt,
                                rl=profile.reporting_limits(analyte, matrix, getattr(self.batch, "acid_basis", None))[0],
                                window=rec_win)
                            rec_judged = True
                        except UnconfiguredCriterion as exc:
                            _record_gap("LFSMD", analyte, exc)
                            raw_rec = None
                        if missing_dup and rec_judged:
                            raw_rec = QCFlag(
                                source="LFSM & LFSMD", analyte=analyte, check_kind=KIND_LFSM,
                                injection_name=name, value="0%", issue=no_reading_issue("REC", missing_dup))
                        raw_rec, rec_low_advisory, rec_low_judged = _low_level_gate(profile, raw_rec, rec_win)
                        rec_judged = rec_judged and rec_low_judged    # Off: its lfsm_recovery stays PENDING
                        if raw_rec is not None:
                            rec_flag = QCFlag(
                                source="LFSM & LFSMD", check_kind=KIND_LFSM,
                                analyte=raw_rec.analyte,
                                injection_name=raw_rec.injection_name,
                                value=raw_rec.value, issue=raw_rec.issue,
                                advisory=lfsmd_advisory or rec_low_advisory)
                            flags_by_injection.setdefault(name, []).append(rec_flag)
                        if rec_judged:
                            lfsm_evaluated.add(name)      # its lfsm_recovery check
                        # the RPD of the two MEASURED concentrations (EPA 537.1
                        # §9.3.7.3), for every method, never of their recoveries.
                        a_c, b_c = lfsm_res.fortified_conc, fortified_dup
                        # a raw side with no reading has no concentration to
                        # compare: the RPD is not judged, and its gap says so
                        # its level judged by the spikes' RSD: no RPD of its own;
                        # its recovery joins the RSD set (a reading on both
                        # sides), and the RSD's failure is its precision check's
                        by_rsd = (lfsm_entry.get("level") or "") in rsd_levels
                        if by_rsd and not missing_dup and (lfsm_inj, analyte) not in lfsm_no_reading:
                            rsd_dups.setdefault((lfsm_entry.get("level") or "", analyte), []).append(
                                (name, LFSMResult(analyte=analyte, lfsm_injection=name,
                                                  parent_injection=lfsm_res.parent_injection,
                                                  spike_value_ppt=lfsm_res.spike_value_ppt,
                                                  fortified_conc=fortified_dup,
                                                  unfortified_conc=lfsm_res.unfortified_conc,
                                                  recovery_pct=rec_dup)))
                        rpd_judged = not (by_rsd or missing_dup or (lfsm_inj, analyte) in lfsm_no_reading)
                        raw_flag, rpd_pct = None, None
                        if rpd_judged:
                            mean_c = (a_c + b_c) / 2.0
                            rpd_pct = abs(a_c - b_c) / mean_c * 100.0 if mean_c else 0.0
                            try:
                                raw_flag = rpd_check_profiled(
                                    profile, analyte, matrix, "LFSMD", rpd_pct, name,
                                    conc=lfsm_res.spike_value_ppt,
                                    rl=profile.reporting_limits(analyte, matrix, getattr(self.batch, "acid_basis", None))[0],
                                    window=rpd_win)
                            except UnconfiguredCriterion as exc:
                                _record_gap("LFSMD", analyte, exc)
                                continue
                        elif not by_rsd:
                            unevaluated_lfsmd[name] = "no reading"
                            a_c = None if (lfsm_inj, analyte) in lfsm_no_reading else a_c
                            b_c = None if missing_dup else b_c
                        flag = None
                        if raw_flag is not None:
                            flag = QCFlag(
                                source="LFSM & LFSMD",
                                check_kind=KIND_LFSMD,
                                analyte=raw_flag.analyte,
                                injection_name=raw_flag.injection_name,
                                value=raw_flag.value,
                                issue=raw_flag.issue,
                                advisory=lfsmd_advisory or raw_flag.advisory,
                            )
                            flags_by_injection.setdefault(name, []).append(flag)

                        self.batch.lfsmd_results.append(LFSMDResult(
                            analyte=analyte,
                            lfsm_injection=lfsm_inj,
                            lfsmd_injection=name,
                            recovery_lfsm=lfsm_res.recovery_pct,
                            recovery_lfsmd=rec_dup,
                            rpd_pct=rpd_pct,
                            flag=flag,
                            recovery_flag=rec_flag,
                            recovery_judged=rec_judged,
                            window=rpd_win or None,
                            recovery_window=rec_win or None,
                            conc_lfsm=a_c,
                            conc_lfsmd=b_c,
                            rpd_judged=rpd_judged,
                        ))

                    if name not in unevaluated_lfsmd:
                        lfsmd_evaluated.add(name)

            for level, injs in sorted(rsd_levels.items()):
                for analyte in _analytes:
                    if analyte in _components:
                        continue
                    got = [(inj, lfsm_results_by_inj[inj].get(analyte)) for inj in injs]
                    got = [(inj, res) for inj, res in got
                           if res is not None and (inj, analyte) not in lfsm_no_reading]
                    if len(got) < RSD_MIN_SPIKES:
                        continue
                    # the duplicates at the level count with their spikes
                    got += rsd_dups.get((level, analyte), [])
                    rsd = rsd_pct([res.recovery_pct for _inj, res in got])
                    if rsd is None:
                        continue
                    win = {}
                    try:
                        raw_flag = rsd_check_profiled(
                            profile, analyte, matrix, "LFSM", "LFSMD", rsd, level,
                            conc=got[0][1].spike_value_ppt,
                            rl=profile.reporting_limits(analyte, matrix, getattr(self.batch, "acid_basis", None))[0], window=win)
                    except UnconfiguredCriterion as exc:
                        _record_gap("LFSMD", analyte, exc)
                        continue
                    if not win:
                        continue                  # no RPD limit: precision not judged
                    flag = None
                    if raw_flag is not None:
                        # the QC log names each spike the RSD judged, a duplicate too
                        for inj, _res in got:
                            flag = QCFlag(source="LFSM & LFSMD", check_kind=KIND_LFSMD,
                                          analyte=raw_flag.analyte, injection_name=inj,
                                          value=raw_flag.value, issue=raw_flag.issue,
                                          advisory=lfsmd_advisory or raw_flag.advisory)
                            flags_by_injection.setdefault(inj, []).append(flag)
                    self.batch.lfsm_rsd_results.append({
                        "analyte": analyte, "level": level, "injections": [inj for inj, _r in got],
                        "parents": [res.parent_injection or "" for _i, res in got],
                        "rsd_pct": rsd, "flag": flag, "window": win})

        # ── Checks behind the rule switches (every switch changes something)
        blank_evaluated, lcs_evaluated = set(), set()
        blank_limits = {}
        self.batch.blank_limits = blank_limits
        order = []                                   # injection names, run order
        for r in sorted(all_rows, key=lambda r: (r.acquisition_datetime is None,
                                                 r.acquisition_datetime or 0)) \
                if all_rows and all(getattr(r, "acquisition_datetime", None) for r in all_rows) \
                else all_rows:
            if r.injection_name not in order:
                order.append(r.injection_name)
        by_inj = {}
        for row in rows:
            by_inj.setdefault(row.injection_name, []).append(row)
        _bmatrix = self.batch.matrix or ""

        def _row(inj, analyte):
            return _summed_row(by_inj.get(inj, []), analyte, _sums)

        def _covers(inj, analyte, row):
            """The export's rows a judged analyte stands for: its components
            when summed (lr- + br-), else the one row (under its own name)."""
            from .analyte_alias import keyword_for
            comps = set((_sums or {}).get(keyword_for(analyte) or analyte) or (_sums or {}).get(analyte) or [])
            names = [r.compound_name for r in by_inj.get(inj, []) if r.compound_name in comps]
            return names or [row.compound_name]

        def _unit(row):
            u = (getattr(row, "conc_units", "") or "").strip()
            return "" if u.lower() == "nan" else u

        # 7. METHOD BLANK: each MB / LRB / MxB analyte against its QC Types
        # tier (max x RL). Switched by the QC type's own flag (qc_rules returns
        # None for a disabled type), like LFSM -- extraction QC is owned by the
        # method profile, beside its limits.
        if profile is not None:
            frbs = set(getattr(self.batch, "field_blanks", None) or [])
            tbs = set(getattr(self.batch, "trip_blanks", None) or [])
            # a field reagent blank is judged against its own row on Blank
            # limits alone (its limit and its own "fails at the limit");
            # without one it is flagged not judged, never judged against
            # another blank's row
            frb_own = bool(getattr(profile, "has_blank_limit", lambda _q: False)("FRB"))
            self.batch.field_blank_own_row = frb_own
            for inj in order:
                role = classify_injection(inj, dilutions)
                # a field reagent blank is a client sample judged against its
                # own limit; none set is a gap the reviewer sees
                frb = inj in frbs
                # a trip blank is a client sample judged against the method's
                # own trip blank limit (Blank limits); none set is a gap
                tb = inj in tbs and not frb
                # a solvent blank (CCB) is reviewed on its chromatogram; it is
                # judged only where the method sets it a limit (Blank limits)
                if role not in BLANK_ROLES and not frb and not tb:
                    continue
                if frb:
                    rule_role, role = "FRB", "FRB"
                elif tb:
                    rule_role, role = "TB", "TB"
                else:
                    rule_role = role
                blank_state = _qc_type_state(profile, rule_role)
                if blank_state == "off":
                    continue          # the blank's row is Off: nothing is judged or filed, no gap
                if frb and not frb_own:
                    _record_gap("FRB", "", UnconfiguredCriterion(
                        "{0}: the field reagent blank is not judged: no field reagent blank "
                        "limit is set for {1} (the method's QC criteria tab, Blank limit); "
                        "it is never judged against another blank's limit.".format(
                            inj, self.method_id)))
                    continue
                # in the state Evaluate a blank is judged and its failure advisory
                blank_advisory = blank_state == "evaluate"
                judged = False
                for analyte in _analytes:
                    if analyte in _components:
                        # judged once, as its summed analyte: a component
                        # exceeding the limit was a second finding of the same
                        # exceedance (its stored row carries the sum's verdict)
                        continue
                    row = _row(inj, analyte)
                    if row is None:
                        continue
                    try:
                        rule = profile.qc_rules(analyte, _bmatrix, rule_role)
                    except UnconfiguredCriterion as exc:
                        _record_gap(role, analyte, exc)
                        continue
                    if tb and (rule is None or rule.max_conc_x_rl is None):
                        # never another blank's limit, never passed in silence
                        _record_gap(role, "", UnconfiguredCriterion(
                            "{0}: the trip blank is not judged: no trip blank limit is set "
                            "for {1} (the method's QC criteria tab, Blank limit).".format(
                                inj, self.method_id)))
                        break
                    if rule is None:
                        continue                     # the QC type is switched off
                    if role == "MxB" and self._mxb_by_reference(profile, inj, analyte, row, _bmatrix,
                                                                flags_by_injection, _record_gap,
                                                                blank_advisory):
                        judged = True                # its recovery against the lot
                        continue
                    if rule.max_conc_x_rl is None:
                        # a solvent blank is reviewed on its chromatogram and a
                        # matrix blank compared with its lot; a method blank
                        # with no limit is a gap, never a pass
                        if rule_role in ("MB", "LRB"):
                            _record_gap(role, analyte, UnconfiguredCriterion(
                                "{0} / {1}: no blank limit is set for the {2} "
                                "(the method's QC criteria tab, Blank limit).".format(
                                    self.method_id, analyte, rule_role)))
                        continue
                    if role == "CCB":
                        # solvent, not a sample: no sample basis, so the
                        # export's own (extract-basis) RL is the reference
                        rl, rl_unit = row.reporting_limit, _unit(row)
                        if rl is None:
                            # (a summed analyte's peaks carry no RL in the
                            # export) the method's RL taken back to the extract
                            # basis by the matrix factor it was raised by
                            from .method_profiles import get_matrix_factor, get_sample_correction
                            prl = profile.reporting_limits(analyte, _bmatrix, getattr(self.batch, "acid_basis", None))[0]
                            factor = get_matrix_factor(self.method_id, _bmatrix) \
                                if get_sample_correction(self.method_id) != "instrument" else 1.0
                            rl = prl / factor if prl and factor else None
                        if rl is None:
                            _record_gap(role, analyte, UnconfiguredCriterion(
                                "{0}: the solvent blank limit is {1:g} x RL but the export "
                                "gives no RL for {2}.".format(inj, rule.max_conc_x_rl, analyte)))
                            continue
                        flag = blank_check(analyte, inj, reported_conc(row), rl,
                                           rule.max_conc_x_rl, rl_unit, role,
                                           rule.fails_at_limit)
                        blank_limits[(inj, analyte)] = {
                            "limit": rule.max_conc_x_rl * rl, "unit": rl_unit,
                            "x_rl": rule.max_conc_x_rl, "at_limit": rule.fails_at_limit,
                            "covers": _covers(inj, analyte, row), "value": reported_conc(row)}
                        judged = True
                        if flag is not None:
                            flag.advisory = blank_advisory or rule.state == "evaluate"
                            flags_by_injection.setdefault(inj, []).append(flag)
                        continue
                    rl, _mdl, rl_unit = profile.reporting_limits(analyte, _bmatrix, getattr(self.batch, "acid_basis", None))
                    if rl is None:
                        _record_gap(role, analyte, UnconfiguredCriterion(
                            "{0} / {1} / {2}: the blank limit is {3:g} x RL but no RL is "
                            "set (the method's Analytes tab).".format(
                                self.method_id, analyte, _bmatrix, rule.max_conc_x_rl)))
                        continue
                    if not _units_compatible(_unit(row), rl_unit):
                        _record_gap(role, analyte, UnconfiguredCriterion(
                            "{0}: blank result in {1}, RL in {2}: not compared.".format(
                                analyte, _unit(row), rl_unit)))
                        continue
                    # the blank result as reported: rounded; at the limit
                    # its own row's switch says
                    flag = blank_check(analyte, inj,
                                       profile.judged_conc(reported_conc(row), _bmatrix), rl,
                                       rule.max_conc_x_rl, rl_unit, role,
                                       rule.fails_at_limit)
                    blank_limits[(inj, analyte)] = {
                        "limit": rule.max_conc_x_rl * rl, "unit": rl_unit,
                        "x_rl": rule.max_conc_x_rl,
                        "at_limit": rule.fails_at_limit,
                        "covers": _covers(inj, analyte, row),
                        "value": profile.judged_conc(reported_conc(row), _bmatrix)}
                    judged = True
                    if flag is not None:
                        flag.advisory = blank_advisory or rule.state == "evaluate"
                        flags_by_injection.setdefault(inj, []).append(flag)
                if judged:
                    blank_evaluated.add(inj)

        # 8. LFB / LCS RECOVERY: measured / spike x 100 against the LFB (or
        # LCS) tiers, low-level tier included. Switched by the QC type's flag.
        if profile is not None:
            qca = (getattr(profile, "_profile_data", lambda: {})() or {}).get("qc_acceptance") or {}
            for inj in order:
                code = classify_injection(inj, dilutions)
                if code not in ("LFB", "LCS"):
                    continue
                # each against its OWN criteria: LCS is its own QC type, never judged by the LFB tiers or the reverse
                qc = code if code in qca else None
                if qc is None or not _qc_type_enabled(profile, qc):
                    continue
                # in the state Evaluate it is judged and its failure advisory
                lcs_advisory = _qc_type_state(profile, qc) == "evaluate"
                # recorded in the guided extraction like the matrix spikes
                # its level is never read from the name
                pedigree = (getattr(self.batch, "spikes", None) or {}).get(inj) or {}
                level = pedigree.get("level") or ""
                spike, spike_unit = _spike_amount(pedigree)
                if spike is None and level:
                    spike, spike_unit = profile.resolve_spike(qc, level, matrix=_bmatrix)
                spike, scale_problem = self._scaled_spike(inj, spike)
                if scale_problem:
                    _record_gap(qc, "", UnconfiguredCriterion(scale_problem))
                    continue
                if spike in (None, 0):
                    _record_gap(qc, "", UnconfiguredCriterion(
                        "{0}: {1} recovery not judged: {2}".format(
                            inj, qc, ("no spike level for {0} / {1} (the method's QC "
                                      "criteria tab, Spike levels)".format(level, _bmatrix)) if level else
                            "not recorded under Spikes in the guided extraction")))
                    continue
                judged = False
                for analyte in _analytes:
                    if analyte in _components:
                        continue          # spiked / limited as its summed analyte
                    row = _row(inj, analyte)
                    conc = reported_conc(row) if row is not None else None
                    # a raw spike with no reading is judged at 0 % recovery
                    missing = raw_no_reading(row) if conc is None else None
                    if conc is None and missing is None:
                        continue
                    if missing:
                        conc = 0.0
                    if not _units_compatible(spike_unit, _unit(row)):
                        _record_gap(qc, analyte, UnconfiguredCriterion(
                            "{0}: spike in {1}, result in {2}: not compared.".format(
                                inj, spike_unit, _unit(row))))
                        continue
                    win = {}
                    try:
                        flag = recovery_check_profiled(
                            profile, analyte, _bmatrix, qc, conc / spike * 100.0, inj,
                            conc=spike, rl=profile.reporting_limits(analyte, _bmatrix, getattr(self.batch, "acid_basis", None))[0],
                            window=win)
                    except UnconfiguredCriterion as exc:
                        _record_gap(qc, analyte, exc)
                        continue
                    if missing:
                        flag = QCFlag(source=qc, analyte=analyte, injection_name=inj, value="0%",
                                      issue=no_reading_issue("REC", missing), check_kind=KIND_LCS)
                    flag, low_advisory, low_judged = _low_level_gate(profile, flag, win)
                    if not low_judged:
                        continue          # a low-level recovery, its row Off: not judged
                    advisory = lcs_advisory or low_advisory
                    judged = True
                    # every LFB / LCS judged, for the QC results the gate
                    # reads
                    self.batch.lcs_results.append({
                        "qc_type": qc, "analyte": analyte, "injection_name": inj,
                        "recovery": conc / spike * 100.0, "passed": flag is None,
                        "spike": spike, "spike_unit": spike_unit,
                        "lo": win.get("lo"), "hi": win.get("hi"), "basis": win.get("basis", ""),
                        "issue": flag.issue if flag is not None else "",
                        "advisory": flag is not None and advisory})
                    if flag is not None:
                        flags_by_injection.setdefault(inj, []).append(QCFlag(
                            source=qc, check_kind=KIND_LCS, analyte=flag.analyte,
                            injection_name=inj, value=flag.value, issue=flag.issue,
                            advisory=advisory))
                if judged:
                    lcs_evaluated.add(inj)

        # 9. CCV FREQUENCY: bracketing every N counting injections, N = the
        # method's CCV frequency (what the Run Builder uses). Switch: ccv_frequency.
        # its box: Off is not judged; empty, it was filed above (Enforced
        # holds, Evaluate advises)
        if profile is not None and _rule_enabled(toggles, "ccv_frequency") and _box("ccv_frequency") != "off":
            n = profile.ccv_frequency() if hasattr(profile, "ccv_frequency") else None
            if n:
                opens = bool(getattr(profile, "ccv_opens_run", lambda: False)())
                counts_qc = bool(getattr(profile, "ccv_counts_extracted_qc", lambda: True)())
                frbs = set(getattr(self.batch, "field_blanks", None) or [])
                fds = set(getattr(self.batch, "field_duplicates", None) or [])
                for flag in ccv_frequency_check(
                        [(i, "FRB" if i in frbs else "FD" if i in fds else classify_injection(i, dilutions))
                         for i in order],
                        n, opens, counts_qc):
                    flag.advisory = _box("ccv_frequency") == "evaluate"
                    flags_by_injection.setdefault(flag.injection_name, []).append(flag)

        # 9a. THE RUN CLOCK: a CCV, sample or spiked QC the instrument stamps
        # before the run's first calibrator was not bracketed by that curve,
        # whatever order the export lists it in. It fails as a bracketing
        # failure. Every run, whatever the switches.
        from .run_shape import time_order_injections
        for inj, when, start in time_order_injections(
                all_rows, lambda n: classify_injection(n, dilutions)):
            flags_by_injection.setdefault(inj, []).append(QCFlag(
                source="CCV frequency", check_kind=KIND_CCV_FREQ, analyte="",
                injection_name=inj, value="before the first calibrator",
                issue="(CCV) acquired %s, before the run's first calibrator (%s): "
                      "not bracketed by its curve" % (when.strftime("%Y-%m-%d %H:%M"),
                                                     start.strftime("%Y-%m-%d %H:%M"))))

        # 10. MDL: a reported detection below the analyte's MDL. Switch: mdl_check.
        if profile is not None and _rule_enabled(toggles, "mdl_check") and _box("mdl_check") != "off":
            for inj in order:
                if classify_injection(inj, dilutions) not in ("Sample", "MB", "LFSM", "LFSMD"):
                    continue
                for analyte in _analytes:
                    if analyte in _components:
                        continue          # spiked / limited as its summed analyte
                    row = _row(inj, analyte)
                    # the result as reported: rounded
                    conc = profile.judged_conc(reported_conc(row), _bmatrix) if row is not None else None
                    if conc is None or conc <= 0:
                        continue
                    _rl, mdl, unit = profile.reporting_limits(analyte, _bmatrix, getattr(self.batch, "acid_basis", None))
                    if mdl is None:
                        _record_gap("MDL", analyte, UnconfiguredCriterion(
                            "{0} / {1}: no MDL set (the method's Analytes "
                            "tab).".format(analyte, _bmatrix)))
                        continue
                    if not _units_compatible(_unit(row), unit):
                        _record_gap("MDL", analyte, UnconfiguredCriterion(
                            "{0}: result in {1}, MDL in {2}: not compared.".format(
                                analyte, _unit(row), unit)))
                        continue
                    flag = mdl_check(analyte, inj, conc, mdl, unit)
                    if flag is not None:
                        flag.advisory = _box("mdl_check") == "evaluate"
                        flags_by_injection.setdefault(inj, []).append(flag)

        # 11. SAMPLE DUPLICATE RPD (switched by the method's Dup QC type). Pair by the extraction record, else the name
        # "<sample> Dup"; judge only where both results reach the RL; one
        # detected and one not is flagged for review.
        dup_evaluated = set()
        if profile is not None and _qc_type_enabled(profile, "Dup"):
            # in the state Evaluate it is judged and its failure advisory
            dup_advisory = _qc_type_state(profile, "Dup") == "evaluate"
            pedigrees = getattr(self.batch, "spikes", None) or {}
            for inj in order:
                if classify_injection(inj, dilutions) != "Dup":
                    continue
                parent = (pedigrees.get(inj) or {}).get("parent") or _dup_parent_name(inj)
                if not parent or parent not in by_inj:
                    _record_gap("Dup", "", UnconfiguredCriterion(
                        "{0}: no sample to pair this duplicate with (expected {1!r}; record "
                        "the parent on the extraction record).".format(inj, parent)))
                    continue
                judged = False
                for analyte in _analytes:
                    if analyte in _components:
                        continue          # judged once, as its summed analyte
                    r1, r2 = _row(parent, analyte), _row(inj, analyte)
                    if r1 is None or r2 is None:
                        continue
                    rl, _mdl, rl_unit = profile.reporting_limits(analyte, _bmatrix, getattr(self.batch, "acid_basis", None))
                    if rl is None:
                        _record_gap("Dup", analyte, UnconfiguredCriterion(
                            "{0} / {1}: duplicate RPD is judged at or above the RL, and no RL "
                            "is set (the method's Analytes tab).".format(analyte, _bmatrix)))
                        continue
                    if not (_units_compatible(_unit(r1), rl_unit) and _units_compatible(_unit(r2), rl_unit)):
                        _record_gap("Dup", analyte, UnconfiguredCriterion(
                            "{0}: results in {1}/{2}, RL in {3}: not compared.".format(
                                analyte, _unit(r1), _unit(r2), rl_unit)))
                        continue
                    c1, c2 = reported_conc(r1), reported_conc(r2)
                    # detected at the RL as REPORTED (rounded); the RPD itself
                    # comes from the unrounded values and is judged rounded
                    j1, j2 = profile.judged_conc(c1, _bmatrix), profile.judged_conc(c2, _bmatrix)
                    d1 = j1 is not None and j1 >= rl
                    d2 = j2 is not None and j2 >= rl
                    flag = None
                    win = {}
                    if d1 and d2:
                        mean = (c1 + c2) / 2.0
                        rpd = abs(c1 - c2) / mean * 100.0 if mean else 0.0
                        try:
                            raw = rpd_check_profiled(profile, analyte, _bmatrix, "Dup", rpd, inj,
                                                     conc=mean, rl=rl, window=win)
                        except UnconfiguredCriterion as exc:
                            _record_gap("Dup", analyte, exc)
                            continue
                        if raw is not None:
                            flag = QCFlag(source="Sample duplicate", check_kind=KIND_DUP,
                                          analyte=raw.analyte, injection_name=inj,
                                          value=raw.value, issue=raw.issue + " (parent %s)" % parent,
                                          advisory=raw.advisory)
                        # its tier Off: not judged
                        judged = win.get("state") != "off"
                    elif d1 != d2:
                        flag = dup_one_detected_flag(analyte, inj, parent, j1, j2, rl, rl_unit)
                        win = {"lo": None, "hi": None,
                               "basis": "Dup: detected in both or in neither (at the RL)"}
                        judged = True
                    if flag is not None:
                        flag.advisory = dup_advisory or flag.advisory
                        flags_by_injection.setdefault(inj, []).append(flag)
                    # written to the QC results so Data Review's gate sees it.
                    # Both below the RL: they agree, the RPD is not calculated.
                    self.batch.dup_results.append({
                        "analyte": analyte, "injection_name": inj, "parent": parent,
                        "rpd": rpd if (d1 and d2) else None,
                        "passed": flag is None,
                        "advisory": flag is not None and flag.advisory,
                        "lo": win.get("lo"), "hi": win.get("hi"), "basis": win.get("basis", ""),
                        "issue": (flag.issue if flag is not None else
                                  "" if (d1 or d2) else "both below the RL: RPD not calculated")})
                if judged:
                    dup_evaluated.add(inj)

        # Value provenance: what every judged value above was computed from,
        # taken from the result objects in this same pass. A failure here is
        # a gap the reviewer sees, never a silent one.
        from . import provenance as _prov
        try:
            _prov.record_run(self.batch, rows, profile, _matrix)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("value provenance could not be recorded for %s", self.batch.batch_id)
            _record_gap("Provenance", "", UnconfiguredCriterion(
                "the run's value provenance could not be recorded (%s): the drawer will show "
                "no terms for this run until it is reprocessed" % exc))

        # Consolidate the QC Log (Sheet 6 equivalent)
        self.batch.qc_flags = [
            f for fl in flags_by_injection.values() for f in fl
        ]

        # Map flags onto review checks by check identity (check_kind), never
        # by display text: the source strings carry the method id.
        _CHECK_KINDS = {
            "is_response":         {KIND_IS_RESPONSE},
            "rt_deviation":        {KIND_RT},
            "ion_ratio":           {KIND_ION_RATIO},
            "calibration_pct_dev": {KIND_CALIBRATION},
            "r_squared":           {KIND_CALIBRATION},
            "ccv_pct_dev":         {KIND_CCV},
            "signal_to_noise":     {KIND_SN},
            "lfsm_recovery":       {KIND_LFSM},
            "lfsmd_rpd":           {KIND_LFSMD},
            "surrogate_recovery":  {KIND_SURROGATE},
            "blank_contamination": {KIND_BLANK},
            "recovery":            {KIND_LCS},
            "duplicate_rpd":       {KIND_DUP},
        }

        for chk in self.checks:
            inj_flags = flags_by_injection.get(chk.injection_name, [])
            relevant_kinds = _CHECK_KINDS.get(chk.check_name, set())
            relevant = [f for f in inj_flags
                        if getattr(f, "check_kind", "") in relevant_kinds
                        and getattr(f, "check_kind", "")]
            if relevant:
                chk.status = CheckStatus.AUTO_FAIL
                chk.flags = [f.as_dict() for f in relevant]
            elif chk.check_name in _CHECK_KINDS:
                # LFSM/LFSMD checks: only AUTO_PASS if the engine actually ran them.
                # If the toggle is ON but spike ppt is not yet configured, stay PENDING
                # so the reviewer sees the check rather than a silent pass.
                if chk.check_name == "lfsm_recovery" and lfsm_enabled:
                    if chk.injection_name in lfsm_evaluated:
                        chk.status = CheckStatus.AUTO_PASS
                elif chk.check_name == "lfsmd_rpd" and lfsmd_enabled:
                    if chk.injection_name in lfsmd_evaluated:
                        chk.status = CheckStatus.AUTO_PASS
                elif chk.check_name == "blank_contamination":
                    # only where the blank was judged (an RL and a tier); a
                    # CCB or a blank with no RL stays PENDING for a reviewer
                    if chk.injection_name in blank_evaluated:
                        chk.status = CheckStatus.AUTO_PASS
                elif chk.check_name == "recovery":
                    if chk.injection_name in lcs_evaluated:
                        chk.status = CheckStatus.AUTO_PASS
                elif chk.check_name == "duplicate_rpd":
                    if chk.injection_name in dup_evaluated:
                        chk.status = CheckStatus.AUTO_PASS
                elif chk.check_name == "surrogate_recovery":
                    # The LFSM rule: AUTO_PASS only where the check
                    # actually ran. An injection whose export carried no %
                    # recovery column, or whose method could not resolve a
                    # window, stays PENDING so a reviewer sees it -- a silent
                    # pass would be indistinguishable from a good result.
                    if chk.injection_name in eis_evaluated:
                        chk.status = CheckStatus.AUTO_PASS
                else:
                    chk.status = CheckStatus.AUTO_PASS
            # checks not auto-resolvable (blank_contamination, bloq_check, …)
            # remain PENDING for the human

            # A matrix spike the method switched on that the pipeline could
            # not judge holds the release, naming why. Filed like an
            # unconfigured criterion: qc_store writes it as an unevaluated QC
            # result, which Data Review's gate holds.
            if chk.status == CheckStatus.PENDING:
                # (an LFSMD's own lfsm_recovery is judged with its RPD; when
                # it is not, the LFSMD gap below names why)
                if (chk.check_name == "lfsm_recovery" and lfsm_enabled
                        and chk.qc_type == "LFSM" and chk.injection_name not in low_level_off_lfsm):
                    _record_gap("LFSM", "", UnconfiguredCriterion(
                        "{0}: LFSM recovery not judged: {1}".format(
                            chk.injection_name, unevaluated_lfsm.get(chk.injection_name)
                            or ("not recorded under Matrix spikes in the guided extraction"
                                if chk.injection_name not in spikes else "not judged"))))
                elif chk.check_name == "lfsmd_rpd" and lfsmd_enabled:
                    if chk.injection_name in unevaluated_lfsmd:
                        _record_gap("LFSMD", "", UnconfiguredCriterion("{0}: LFSMD RPD not judged: {1}".format(
                            chk.injection_name, unevaluated_lfsmd[chk.injection_name])))
                    else:
                        _record_gap("LFSMD", "", UnconfiguredCriterion(
                            "{0}: LFSMD not judged: {1}".format(
                                chk.injection_name,
                                "not recorded under Matrix spikes in the guided extraction"
                                if chk.injection_name not in spikes
                                else "its LFSM recovery was not judged")))

    # ── reviewer interaction ──────────────────────────────────────────────────
    def pending(self) -> list[dict]:
        """All checks needing human attention, with their prompt text."""
        return [
            {
                "injection": c.injection_name,
                "qc_type": c.qc_type,
                "check": c.check_name,
                "prompt": CHECK_PROMPTS.get(c.check_name, c.check_name),
                "status": c.status.value,
                "flags": c.flags,
            }
            for c in self.checks
            if c.status in (CheckStatus.PENDING, CheckStatus.AUTO_FAIL)
        ]

    def accept(self, injection: str, check: str, reviewer: str, comment: str = ""):
        self._set(injection, check, CheckStatus.ACCEPTED, reviewer, comment)

    def reject(self, injection: str, check: str, reviewer: str, comment: str = ""):
        self._set(injection, check, CheckStatus.REJECTED, reviewer, comment)

    def _set(self, injection, check, status, reviewer, comment):
        for c in self.checks:
            if c.injection_name == injection and c.check_name == check:
                c.status = status
                c.reviewer = reviewer
                c.comment = comment
                c.reviewed_at = datetime.now().isoformat()
                return
        raise KeyError(f"No check {check!r} for injection {injection!r}")


    @property
    def rejected(self) -> list[ReviewCheck]:
        return [c for c in self.checks if c.status == CheckStatus.REJECTED]

    # ── persistence (review from home) ────────────────────────────────────────
    def save(self, path: str | Path):
        payload = {
            "batch_id": self.batch.batch_id,
            "saved_at": datetime.now().isoformat(),
            "checks": [
                {**asdict(c), "status": c.status.value} for c in self.checks
            ],
        }
        Path(path).write_text(json.dumps(payload, indent=2, default=str))

    @classmethod
    def load(cls, batch: Batch, path: str | Path) -> "RunQueue":
        payload = json.loads(Path(path).read_text())
        q = cls.__new__(cls)
        q.batch = batch
        q.checks = [
            ReviewCheck(
                injection_name=c["injection_name"],
                qc_type=c["qc_type"],
                check_name=c["check_name"],
                status=CheckStatus(c["status"]),
                flags=c.get("flags", []),
                reviewer=c.get("reviewer", ""),
                reviewed_at=c.get("reviewed_at"),
                comment=c.get("comment", ""),
            )
            for c in payload["checks"]
        ]
        return q
