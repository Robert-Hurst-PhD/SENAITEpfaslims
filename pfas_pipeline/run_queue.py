"""
Run Queue — the review workflow engine.

When a batch comes back from the instrument, the queue walks every injection
and PROMPTS the reviewer with exactly the QC checks required for that
injection type (LFSM recovery, duplicate RPD, matrix-blank contamination, …).

Each check is resolved automatically by the QC engine where possible; checks
that need human judgment are surfaced as pending prompts. The queue state is
persisted so review can resume from home (your remote-review requirement).
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import re

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
    KIND_BLANK, KIND_LCS, KIND_CCV_FREQ, KIND_MDL, KIND_DUP,
    BLANK_ROLES, blank_check, ccv_frequency_check, mdl_check, dup_one_detected_flag,
    is_raw_check, rt_deviation_check, qual_quan_check,
    calibration_check, calibration_check_profiled,
    ccv_check_profiled, icv_check_profiled, rrt_check_profiled, signal_to_noise_check,
    recovery_check_profiled, rpd_check_profiled,
)
from .constants import CRITERIA
from .method_profiles import (
    UnconfiguredCriterion,
    get_profile as _get_method_profile,
    get_analyte_list as _get_analytes,
    get_is_list as _get_is_list,
    get_injection_standards as _get_injection_standards,
    get_non_iso_set as _get_non_iso_set,
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
    "blank_contamination": "Verify the blank against the method's limit (QC Types: at most N x RL)",
    "lod_check":           "Apply <LOD qualifier where blank ≥ sample",
    "bloq_check":          "Apply BLoQ qualifier for results below LOQ",
    "recovery":            "Verify LFB / LCS recovery against the method's tiers",
    "lfsm_recovery":       "Verify LFSM recovery 50–150% (select spike conc. if not set)",
    "lfsmd_rpd":           "Verify LFSM/LFSMD RPD ≤ 30%",
    "duplicate_rpd":       "Verify the sample duplicate RPD against the method's Dup limit",
    "signal_to_noise":     "Verify S/N ≥ 3 for reported analytes",
}


# ── Sample-duplicate name helper ─────────────────────────────────────────────
# (A matrix spike's parent and level are never read from its name: the
# extraction's spike record is the only source, .)

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
    components (lr- + br-), as the summary reports it -- also when the export
    carries its own "Total" row: that row is never put on the sample basis
    (apply_extract_corrections converts native analytes only), so an FDA egg
    LFSM read its total in ng/mL against a spike in ng/kg and recovered
    "0 %" (replay of the lab's FDA export). Without a summed
    analyte its spike recovery was skipped in silence (end-to-end fast tier). `sums` = {keyword: [component names]}; the export's
    Total row is used only when no component is present."""
    comps = []
    if sums:
        from .analyte_alias import keyword_for
        comps = sums.get(keyword_for(analyte) or analyte) or sums.get(analyte) or []
    parts = [r for r in rows if r.compound_name in comps]
    if not parts:
        for row in rows:
            if row.compound_name == analyte:
                return row
        # the export's own name for it (PFTA for PFTeDA, ADONA for DONA): a
        # check found no row and was skipped in silence
        from .analyte_alias import native_keyword_for
        for row in rows:
            if native_keyword_for(row.compound_name) == analyte:
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
    """{rule_library_key: bool} for method_id -- the METHOD PROFILE's own
    `rule_toggles` (QC consolidation P2; they used to sit in qc_rules.json).
    `rules_path` is accepted for old callers and ignored. An absent key is
    treated as on by _rule_enabled."""
    if not method_id:
        return {}
    from .method_profiles import _profile_data_cache, get_profile
    try:
        mid = get_profile(method_id).method_id         # aliases ("FDA", "537") resolved
    except Exception:                                    # noqa: BLE001
        mid = method_id
    return dict((_profile_data_cache.get(mid) or {}).get("rule_toggles") or {})


def _takes_surrogate_recovery(injection_name: str,
                              dilutions: "dict | None" = None) -> bool:
    """Does a surrogate recovery criterion apply to this injection?

    Named for the question it answers rather than "is it extracted", because the
    two differ in one case that matters. Derived from REVIEW_CHECKS rather than
    from a second list of QC codes: the catalogue already declares
    `surrogate_recovery` on exactly the extracted injection types and omits it
    from the ones prepared in solvent (CAL, ICV, CCV, CCB), so the loop and the
    review queue cannot disagree about which injections have a recovery.

    A DILUTION is the exception. It is made from an extract, so it is
    "extracted" — but it is the same extract re-injected at a known factor, and
    its surrogate reads the diluted value. A 1:10 dilution's surrogate recovers
    at roughly a tenth of nominal and would fail every window, against a
    criterion this module already says does not apply to a dilution ("its
    retention times, ion ratios, calibration agreement AND RECOVERY would all be
    judged against criteria that assume a neat extract"). `classify_injection`
    returns "Dilution", which is not a REVIEW_CHECKS key, so this has to be
    explicit — falling through to the Sample default would fail every diluted
    injection in the batch.

    An unrecognised name does fall back to Sample, which is the safe direction:
    a client sample mistaken for solvent would go unchecked.
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


def _rule_enabled(toggles: dict, library_key: str) -> bool:
    """True if the rule is enabled (default ON when key absent).

    Only for keys that exist in `qc/rules.py RULE_LIBRARY`. The default-ON
    fallback means a key that is absent EVERYWHERE looks permanently enabled
    and is indistinguishable from one a lab deliberately switched on, which is
    how `lfsm_recovery` and `lfsmd_rpd` survived with no library entry, no
    default and no UI. `tests/test_rule_toggles.py` pins the three-way
    agreement so it cannot recur.
    """
    return bool(toggles.get(library_key, True))


def _qc_type_enabled(profile, qc_type: str) -> bool:
    """True if this method's extraction/matrix QC type is switched on.

    Extraction and matrix QC (LFSM, LFSMD, MB, Dup, ...) is owned by the method
    profile, not by the instrument RULE_LIBRARY. `profile` is a MethodProfile
    object, NOT a dict — it holds the answer, this is a None-safe wrapper. No
    profile means no configuration to consult, so the check runs.
    """
    if profile is None:
        return True
    try:
        return profile.qc_type_enabled(qc_type)
    except AttributeError:                       # a profile predating the method
        return True


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

        FDA §10.2(4) applies only to a POSITIVE of a single-transition analyte,
        and whether an analyte was detected is decided in
        `pipeline.build_summary` -- which runs AFTER auto_evaluate() and cannot
        be reordered before it, because the summary consumes the is_results that
        auto_evaluate produces. So this is a second, later pass rather than part
        of the main evaluation.

        `identity_confirmation` is deliberately absent from auto_evaluate's
        _CHECK_KINDS, which leaves it PENDING there -- the documented default for
        a check no engine block resolves. Without this pass it would stay PENDING
        on every injection of every batch forever, which is the noise defect
        records: a check that is always pending is one nobody reads.

        So: PENDING where a confirmation is genuinely owed, with the prompt
        attached; AUTO_PASS where nothing was detected that needs confirming.
        AUTO_PASS here means "§10.2(4) does not apply to this injection", NOT
        "the confirmation was done" -- an owed confirmation is closed by a human
        accepting the check with the LC-HRMS result, which is what
        `accept()` already exists for.

        Idempotent: calling it twice reaches the same answer.
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
    def auto_evaluate(self):
        """
        Run the full QC engine and mark checks AUTO_PASS / AUTO_FAIL.
        Runs every automatic check once, in one pass.

        Rule toggles are loaded from /data/qc/qc_rules.json for self.method_id.
        LIBRARY_KEY → engine block mapping (rules.py LIBRARY_KEY_TO_ENGINE_CHECKS):
          is_response   → is_raw_check
          rrt_deviation → rt_deviation_check
          ion_ratio     → qual_quan_check
          cal_r2        → calibration_check (also covers ccv_recovery checks)
          ccv_recovery  → calibration_check (run block if EITHER cal_r2 or ccv_recovery enabled)
          sn_min        → signal_to_noise_check
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

        _method = self.method_id or "FDA_32PFAS"
        _matrix = self.batch.matrix or ""
        _analytes = (_get_included_analytes(_method, _matrix)
                     if _matrix else _get_analytes(_method))
        _non_iso = _get_non_iso_set(_method)

        # The components of a summed analyte are measured and go into the
        # reported result, but are not reportable themselves — so the QC loop,
        # which walks the REPORTABLE panel, never visited them. On this run
        # that left 49 ion-ratio failures on br-PFOS/br-PFHxS invisible while
        # br-PFOS still contributed a fifth of the reported PFOS. Check them..
        # ..but a component is not spiked, nor given an MDL, on its own: the
        # spike level and the MDL are the SUMMED analyte's, so spike recovery
        # (LFB/LCS, LFSM, LFSMD) and the MDL check judge the summed analyte
        # only (found 2026-10-07, synthetic EPA 537.1 runs: br-PFOS judged
        # against the whole PFOS spike read 22 % recovery).
        _components = set()
        _sums = {}                    # reported keyword -> its components
        try:
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
        except Exception as exc:                       # noqa: BLE001
            logger.warning("could not add isomer components to QC: %s", exc)

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

            Split out of _guard because a check whose result is a single flag
            (or None) cannot use _guard's "return []" convention: [] is falsy
            but is not None, so "unconfigured" and "passed" would be
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

        # 1. IS Raw (is_response rule)
        if _rule_enabled(toggles, "is_response"):
            for is_cmp in _get_is_list(_method):
                # unfiltered: dilutions ARE checked for IS consistency
                for res in _guard_is(all_rows, is_cmp, dilutions, _method):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    # Record EVERY result, not only the failures. The RT,
                    # ion-ratio and calibration checks all do; IS did not, so
                    # the QC Summary's IS row could only ever contain failures
                    # and the gate could never pass however good the run was.
                    self.batch.is_results.append(res)

        # The METHOD PROFILE drives the per-analyte checks below. Until
        # 2026-08-04 four of them called the non-profiled variants, which judge
        # against the hardcoded CRITERIA table: the CCV window, calibration r2,
        # the IS response window and the RT tolerance were all configurable in
        # the UI and enforced from code. The numbers coincided with the FDA
        # profile, which is why it went unseen -- but EPA 537.1 §9.3.4 requires
        # the IS to hold against BOTH the ICAL average and the last CCV, and the
        # second condition was never evaluated.
        profile = None
        if self.method_id:
            try:
                profile = _get_method_profile(self.method_id)
            except KeyError:
                logger.warning("no method profile for %s — per-analyte checks "
                               "fall back to the legacy criteria table",
                               self.method_id)

        # 2. RT Deviation (rrt_deviation rule)
        rt_enabled  = _rule_enabled(toggles, "rrt_deviation")
        # 3. Qual-Quan (ion_ratio rule)
        iq_enabled  = _rule_enabled(toggles, "ion_ratio")
        # 4. Calibration (cal_r2 OR ccv_recovery — run if either is on)
        cal_enabled  = _rule_enabled(toggles, "cal_r2") or _rule_enabled(toggles, "ccv_recovery")
        # 5. Signal-to-Noise (sn_min rule)
        sn_enabled   = _rule_enabled(toggles, "sn_min")
        # 6. LFSM/LFSMD. These gate on the METHOD PROFILE's qc_acceptance
        # entry, not on a rule toggle. `RULE_LIBRARY` is explicitly
        # instrument-level -- its own header says extraction and matrix QC
        # (LCS, LFB, LFSM, LFSMD, MB, LRB, Dup, MxB) is owned by the method
        # profile -- and `qc_acceptance.LFSM.enabled` already exists, is
        # editable in the Method Profile UI, and is where the limits live.
        #
        # Until 2026-08-06 this read `_rule_enabled(toggles, "lfsm_recovery")`
        # against keys that appear in NO library, NO defaults table and NO UI.
        # `_rule_enabled` defaults absent keys to True, so both checks always
        # ran and a lab that switched LFSM off in the Method Profile was
        # ignored: the switch it was given did nothing, and the switch that
        # worked did not exist.
        lfsm_enabled  = _qc_type_enabled(profile, "LFSM")
        lfsmd_enabled = _qc_type_enabled(profile, "LFSMD")
        if lfsmd_enabled and not lfsm_enabled:
            # The spike/duplicate RPD is computed FROM the LFSM recovery
            # (lfsm_res.recovery_pct, .unfortified_conc, .spike_value_ppt), so
            # with LFSM off there is nothing to compare the duplicate against
            # and LFSMD silently evaluates nothing. Say so rather than leave the
            # Method Profile showing an enabled check that can never fire.
            logger.warning(
                "%s: LFSMD is enabled but LFSM is disabled in the method "
                "profile. The spike/duplicate RPD is derived from the LFSM "
                "recovery, so NO LFSMD result will be evaluated. Enable LFSM "
                "or disable LFSMD.", self.method_id or "method")

        for analyte in _analytes:
            if rt_enabled:
                for res in (_guard("RT", analyte, rrt_check_profiled,
                                   profile, rows, analyte)
                            if profile else rt_deviation_check(rows, analyte)):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.rt_results.append(res)
            if iq_enabled:
                for res in qual_quan_check(rows, analyte, _non_iso):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.qual_quan_results.append(res)
            if cal_enabled:
                for res in (_guard("Calibration", analyte,
                                   calibration_check_profiled,
                                   profile, rows, analyte)
                            if profile else calibration_check(rows, analyte)):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.cal_results.append(res)
                # CCV recovery is a separate criterion from calibration
                # linearity and had no check of its own: the lab's configured
                # 72-128% window was enforced by nothing.
                if profile and _rule_enabled(toggles, "ccv_recovery"):
                    for flag in _guard("CCV", analyte, ccv_check_profiled,
                                       profile, rows, analyte, _matrix,
                                       self.batch.ccv_results):
                        flags_by_injection.setdefault(
                            flag.injection_name, []).append(flag)
                    # the ICV (QCS) verifies the curve: same switch, the
                    # method's own ICV deviation
                    for flag in _guard("ICV", analyte, icv_check_profiled,
                                       profile, rows, analyte, _matrix,
                                       self.batch.ccv_results):
                        flags_by_injection.setdefault(
                            flag.injection_name, []).append(flag)
            if sn_enabled:
                for flag in signal_to_noise_check(rows, analyte):
                    flags_by_injection.setdefault(flag.injection_name, []).append(flag)

        # 5b. SURROGATE / extracted-internal-standard RECOVERY.
        #
        # Both halves of this check already existed and had never met. The
        # instrument reports each labelled compound's % recovery in column 30;
        # `importer` parses it and `InstrumentRow.pct_recovery_is` carries it on
        # every row -- and NOTHING read that field, anywhere. On the other side,
        # every method profile resolves a surrogate-recovery window through
        # `qc_rules(..., "SUR")` (FDA guidance-only 50-150% per
        # Sec2024.10.1(5), EPA 537.1 Sec9.3.5 70-130%, EPA 1633A per-analyte x
        # matrix-class from Tables 6/8), reachable through all three resolution
        # tiers, exported across the process boundary and overlaid per batch.
        #
        # `recovery_check_profiled` had exactly ONE call site, passing the
        # literal "LFSM". So no call ever asked for a surrogate window, and the
        # entire 1633A EIS branch -- limits, matrix overrides, the QAPP tier
        # above it -- was unreachable from a live run.
        eis_evaluated = set()
        eis_advisory = set()
        # the Rule Toggles switch (wired 2026-10-01; it used to change nothing)
        if profile is not None and _rule_enabled(toggles, "surrogate_recovery"):
            # the METHOD's injection standards (its labelled-standards grid)
            _injection_is = _get_injection_standards(_method)
            # a method whose CCCs carry the surrogates judges them there too
            # (EPA 537.1 §9.3.5.1: "a sample, blank, or CCC"; F4)
            sur_in_ccv = bool(getattr(profile, "surrogate_recovery_in_ccv", lambda: False)())
            for compound in _get_is_list(_method):
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
                def _verdicts():
                    """Record, for the certificate's QC sub-table, the recoveries of a compound whose method sets NO
                    window: "no criterion", never a pass."""
                    for row in rows:
                        if ((row.compound_name or "").strip() != compound
                                or row.pct_recovery_is is None
                                or not _takes_surrogate_recovery(row.injection_name, dilutions)):
                            continue
                        value = float(row.pct_recovery_is)
                        entry = {"injection_name": row.injection_name, "compound": compound,
                                 "value": value, "judged": profile.judged_pct(value, _matrix),
                                 "window_min": None, "window_max": None,
                                 "guidance": False, "status": "no criterion",
                                 "std_role": "surrogate"}
                        self.batch.surrogate_results.append(entry)

                try:
                    rule = profile.qc_rules(compound, _matrix, "SUR")
                except UnconfiguredCriterion as exc:
                    _record_gap("Surrogate Recovery", compound, exc)
                    _verdicts()
                    continue
                if rule is None or rule.recovery_min is None:
                    _verdicts()
                    continue
                # `rows`, not `all_rows`: dilutions are excluded for the same
                # reason RT, ion-ratio and calibration exclude them. is_raw_check
                # above is the deliberate exception, and it corrects for the
                # recorded factor internally; a recovery does not.
                for row in rows:
                    if (row.compound_name or "").strip() != compound:
                        continue
                    if row.pct_recovery_is is None:
                        continue
                    if not (_takes_surrogate_recovery(row.injection_name, dilutions)
                            or (sur_in_ccv and classify_injection(row.injection_name, dilutions) == "CCV")):
                        continue
                    raw_flag = recovery_check_profiled(
                        profile, compound, _matrix, "SUR",
                        float(row.pct_recovery_is), row.injection_name)
                    # the check's own verdict, for the certificate
                    self.batch.surrogate_results.append({
                        "injection_name": row.injection_name, "compound": compound,
                        "value": float(row.pct_recovery_is),
                        "window_min": rule.recovery_min, "window_max": rule.recovery_max,
                        "judged": profile.judged_pct(float(row.pct_recovery_is), _matrix),
                        "guidance": bool(rule.is_guidance_only),
                        "status": "within" if raw_flag is None else "outside",
                        "std_role": "surrogate"})
                    if raw_flag is None:
                        eis_evaluated.add(row.injection_name)
                        continue
                    if rule.is_guidance_only:
                        # FDA §2024.10.1(5) makes surrogate recovery ADVISORY.
                        # It is recorded so the QC log and the reviewer see it,
                        # and carries NO check_kind, so it cannot AUTO_FAIL a
                        # release gate — a criterion the method calls guidance
                        # must not block a batch. The check is left PENDING
                        # rather than passed: a human should read an advisory
                        # exceedance, and AUTO_PASS beside a flag would say the
                        # opposite.
                        flags_by_injection.setdefault(
                            row.injection_name, []).append(QCFlag(
                                source="{0} surrogate recovery "
                                       "(guidance)".format(_method),
                                analyte=raw_flag.analyte,
                                injection_name=raw_flag.injection_name,
                                value=raw_flag.value,
                                issue=raw_flag.issue,
                            ))
                        eis_advisory.add(row.injection_name)
                        continue
                    eis_evaluated.add(row.injection_name)
                    flags_by_injection.setdefault(
                        row.injection_name, []).append(QCFlag(
                            source="{0} surrogate recovery".format(_method),
                            check_kind=KIND_SURROGATE,
                            analyte=raw_flag.analyte,
                            injection_name=raw_flag.injection_name,
                            value=raw_flag.value,
                            issue=raw_flag.issue,
                        ))

        # 6. LFSM recovery + LFSMD RPD (per-analyte tiered limits from method profile)
        lfsm_evaluated  = set()   # injection names where spike was resolved + check ran
        lfsmd_evaluated = set()
        unevaluated_lfsm = {}     # lfsm_inj -> why it could not be judged
        # the extraction's spike record: the only source of spikes
        spikes = getattr(self.batch, "spikes", None) or {}

        if lfsm_enabled or lfsmd_enabled:
            # profile is resolved once above; re-fetching here used to shadow it
            matrix = self.batch.matrix or ""
            conc_lookup = {}
            for row in rows:
                conc_lookup.setdefault(row.injection_name, []).append(row)

            # Identify unique LFSM injection names (not duplicates)
            # The extraction pedigree says which injections are matrix spikes
            # and what they were fortified from. Falling back to the name only
            # when there is no pedigree: matching the literal substring
            # "; LFSM " meant that a lab whose names read
            # 'DEMO Silage "Egg-2" LFSM Mid' had no LFSM evaluated at all.
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
                    if spike_val is None or spike_val == 0:
                        logger.info("No spike level for %s — LFSM recovery "
                                    "stays pending", lfsm_inj)
                        unevaluated_lfsm[lfsm_inj] = (
                            "no spike level for {0} / {1} (Recovery Tiers: spike "
                            "levels)".format(level_label or "this level", matrix or "this matrix"))
                        continue

                    # The spike level and the results must be in the same
                    # units before a recovery means anything. The level is
                    # recorded in ppt while this export reports ng/mL, and
                    # dividing one by the other produced recoveries near zero
                    # — every analyte failing, which reads as a catastrophic
                    # batch rather than as a units problem. Converting needs
                    # the aliquot mass and final extract volume, which is a
                    # modelling decision, so the check reports that it could
                    # NOT be evaluated instead of asserting a false failure.
                    result_units = ""
                    for row in conc_lookup.get(lfsm_inj, []):
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

                    for analyte in _analytes:
                        if analyte in _components:
                            continue          # spiked / limited as its summed analyte
                        fortified = _get_conc(lfsm_inj, analyte, conc_lookup, _sums)
                        if fortified is None:
                            continue
                        unfort = _get_conc(parent_inj, analyte, conc_lookup, _sums) or 0.0
                        recovery_pct = (fortified - unfort) / spike_val * 100.0
                        lfsm_win = {}

                        if profile.judged_pct(recovery_pct, matrix) < 0:
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
                                    rl=profile.reporting_limits(analyte, matrix)[0],
                                    window=lfsm_win)
                            except UnconfiguredCriterion as exc:
                                _record_gap("LFSM", analyte, exc)
                                continue
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
                        self.batch.lfsm_results.append(lfsm_result)
                        lfsm_results_by_inj[lfsm_inj][analyte] = lfsm_result

                    lfsm_evaluated.add(lfsm_inj)

            # LFSMD RPD evaluation (requires matching LFSM result)
            if lfsmd_enabled and profile is not None:
                # Pair the duplicate with its LFSM through the extraction
                # pedigree — they are the two spiked injections sharing a
                # parent. Matching the literal '"; LFSM " … " Dup."' naming
                # meant a lab writing 'LFSM Mid Duplicate' had no RPD evaluated
                # at all, the same way it had no LFSM evaluated.
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
                    # pair by the shared parent
                    if entry.get("lfsm") in lfsm_inj_names:
                        lfsm_inj = entry["lfsm"]
                    else:
                        for candidate in lfsm_inj_names:
                            if (spikes.get(candidate) or {}).get("parent") == entry.get("parent"):
                                lfsm_inj = candidate
                                break
                    if lfsm_inj is None:
                        logger.info("No recorded LFSM pairs with %s — "
                                    "RPD stays pending", name)
                        continue
                    lfsm_entry = spikes.get(lfsm_inj) or {}
                    if ((entry.get("level") or "") != (lfsm_entry.get("level") or "")
                            or (_spike_amount(entry)[0] not in (None, _spike_amount(lfsm_entry)[0]))):
                        # the duplicate is spiked at its LFSM's level
                        _record_gap("LFSMD", "", UnconfiguredCriterion(
                            "{0}: recorded at level {1} / {2} ppt, its LFSM {3} at {4} / {5} ppt "
                            "-- the duplicate must match its LFSM".format(
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
                        if fortified_dup is None:
                            continue

                        rec_dup  = ((fortified_dup - lfsm_res.unfortified_conc)
                                    / lfsm_res.spike_value_ppt * 100.0)

                        # The duplicate's OWN recovery, against the LFSM
                        # window at the LFSM's spike level -- the duplicate is
                        # spiked at the same level (2026-10-06: it was
                        # computed for the RPD and never judged).
                        rec_flag, rec_judged = None, False
                        rec_win, rpd_win = {}, {}
                        try:
                            raw_rec = recovery_check_profiled(
                                profile, analyte, matrix, "LFSM", rec_dup, name,
                                conc=lfsm_res.spike_value_ppt,
                                rl=profile.reporting_limits(analyte, matrix)[0],
                                window=rec_win)
                            rec_judged = True
                        except UnconfiguredCriterion as exc:
                            _record_gap("LFSMD", analyte, exc)
                            raw_rec = None
                        if raw_rec is not None:
                            rec_flag = QCFlag(
                                source="LFSM & LFSMD", check_kind=KIND_LFSM,
                                analyte=raw_rec.analyte,
                                injection_name=raw_rec.injection_name,
                                value=raw_rec.value, issue=raw_rec.issue)
                            flags_by_injection.setdefault(name, []).append(rec_flag)
                        if rec_judged:
                            lfsm_evaluated.add(name)      # its lfsm_recovery check
                        # the RPD of the two MEASURED concentrations (EPA 537.1
                        # §9.3.7.3). From their
                        # recoveries it differed whenever the parent held
                        # the analyte: a pair inside 30 % was failed.
                        # per method: EPA 537.1 is of the concentrations;
                        # otherwise of the recoveries, as before
                        if getattr(profile, "lfsmd_rpd_from_concentrations", lambda: False)():
                            a_c, b_c = lfsm_res.fortified_conc, fortified_dup
                        else:
                            a_c, b_c = lfsm_res.recovery_pct, rec_dup
                        mean_c = (a_c + b_c) / 2.0
                        rpd_pct = abs(a_c - b_c) / mean_c * 100.0 if mean_c else 0.0

                        try:
                            raw_flag = rpd_check_profiled(
                                profile, analyte, matrix, "LFSMD", rpd_pct, name,
                                conc=lfsm_res.spike_value_ppt,
                                rl=profile.reporting_limits(analyte, matrix)[0],
                                window=rpd_win)
                        except UnconfiguredCriterion as exc:
                            _record_gap("LFSMD", analyte, exc)
                            continue
                        flag = None
                        if raw_flag is not None:
                            flag = QCFlag(
                                source="LFSM & LFSMD",
                                check_kind=KIND_LFSMD,
                                analyte=raw_flag.analyte,
                                injection_name=raw_flag.injection_name,
                                value=raw_flag.value,
                                issue=raw_flag.issue,
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
                        ))

                    lfsmd_evaluated.add(name)

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
            for inj in order:
                role = classify_injection(inj, dilutions)
                # a field reagent blank is a client sample judged against the
                # method blank's limit
                frb = inj in frbs
                # a solvent blank (CCB) is reviewed on its chromatogram; it is
                # judged only where the method sets it a limit (Blank limits)
                if role not in BLANK_ROLES and not frb:
                    continue
                rule_role, role = ("MB", "FRB") if frb else (role, role)
                judged = False
                for analyte in _analytes:
                    row = _row(inj, analyte)
                    if row is None:
                        continue
                    try:
                        rule = profile.qc_rules(analyte, _bmatrix, rule_role)
                        if frb and rule is None:
                            # the method's own method blank: EPA 537.1 calls
                            # it LRB and switches MB off (synthetic runs,
                            # 2026-10-07: no FRB was ever judged)
                            rule = profile.qc_rules(analyte, _bmatrix, "LRB")
                    except UnconfiguredCriterion as exc:
                        _record_gap(role, analyte, exc)
                        continue
                    if rule is None:
                        continue                     # the QC type is switched off
                    if rule.max_conc_x_rl is None:
                        # a solvent blank is reviewed on its chromatogram and a
                        # matrix blank compared with its lot; a method blank
                        # with no limit is a gap, never a pass (it used to be
                        # stored passing)
                        if rule_role in ("MB", "LRB"):
                            _record_gap(role, analyte, UnconfiguredCriterion(
                                "{0} / {1}: no blank limit is set for the {2} "
                                "(Method Profiles -> QC Types -> Blank limits).".format(
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
                            prl = profile.reporting_limits(analyte, _bmatrix)[0]
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
                            flags_by_injection.setdefault(inj, []).append(flag)
                        continue
                    rl, _mdl, rl_unit = profile.reporting_limits(analyte, _bmatrix)
                    if rl is None:
                        _record_gap(role, analyte, UnconfiguredCriterion(
                            "{0} / {1} / {2}: the blank limit is {3:g} x RL but no RL is "
                            "set (Method Profiles -> Reporting Limits).".format(
                                self.method_id, analyte, _bmatrix, rule.max_conc_x_rl)))
                        continue
                    if not _units_compatible(_unit(row), rl_unit):
                        _record_gap(role, analyte, UnconfiguredCriterion(
                            "{0}: blank result in {1}, RL in {2} -- not compared.".format(
                                analyte, _unit(row), rl_unit)))
                        continue
                    # the blank result as reported: rounded
                    # a field reagent blank borrows the method blank's limit
                    # but fails only ABOVE it (EPA 537.1 §9.3.8 "greater
                    # than"), whatever the borrowed type says at the limit
                    flag = blank_check(analyte, inj,
                                       profile.judged_conc(reported_conc(row), _bmatrix), rl,
                                       rule.max_conc_x_rl, rl_unit, role,
                                       rule.fails_at_limit and not frb)
                    blank_limits[(inj, analyte)] = {
                        "limit": rule.max_conc_x_rl * rl, "unit": rl_unit,
                        "x_rl": rule.max_conc_x_rl,
                        "at_limit": rule.fails_at_limit and not frb,
                        "covers": _covers(inj, analyte, row),
                        "value": profile.judged_conc(reported_conc(row), _bmatrix)}
                    judged = True
                    if flag is not None:
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
                # recorded in the guided extraction like the matrix spikes
                # : its level is never read from the name
                pedigree = (getattr(self.batch, "spikes", None) or {}).get(inj) or {}
                level = pedigree.get("level") or ""
                spike, spike_unit = _spike_amount(pedigree)
                if spike is None and level:
                    spike, spike_unit = profile.resolve_spike(qc, level, matrix=_bmatrix)
                if spike in (None, 0):
                    _record_gap(qc, "", UnconfiguredCriterion(
                        "{0}: {1} recovery not judged -- {2}".format(
                            inj, qc, ("no spike level for {0} / {1} (Recovery Tiers: spike "
                                      "levels)".format(level, _bmatrix)) if level else
                            "not recorded under Spikes in the guided extraction")))
                    continue
                judged = False
                for analyte in _analytes:
                    if analyte in _components:
                        continue          # spiked / limited as its summed analyte
                    row = _row(inj, analyte)
                    conc = reported_conc(row) if row is not None else None
                    if conc is None:
                        continue
                    if not _units_compatible(spike_unit, _unit(row)):
                        _record_gap(qc, analyte, UnconfiguredCriterion(
                            "{0}: spike in {1}, result in {2} -- not compared.".format(
                                inj, spike_unit, _unit(row))))
                        continue
                    win = {}
                    try:
                        flag = recovery_check_profiled(
                            profile, analyte, _bmatrix, qc, conc / spike * 100.0, inj,
                            conc=spike, rl=profile.reporting_limits(analyte, _bmatrix)[0],
                            window=win)
                    except UnconfiguredCriterion as exc:
                        _record_gap(qc, analyte, exc)
                        continue
                    judged = True
                    # every LFB / LCS judged, for the QC results the gate
                    # reads (it lived only in the review queue)
                    self.batch.lcs_results.append({
                        "qc_type": qc, "analyte": analyte, "injection_name": inj,
                        "recovery": conc / spike * 100.0, "passed": flag is None,
                        "lo": win.get("lo"), "hi": win.get("hi"), "basis": win.get("basis", ""),
                        "issue": flag.issue if flag is not None else ""})
                    if flag is not None:
                        flags_by_injection.setdefault(inj, []).append(QCFlag(
                            source=qc, check_kind=KIND_LCS, analyte=flag.analyte,
                            injection_name=inj, value=flag.value, issue=flag.issue))
                if judged:
                    lcs_evaluated.add(inj)

        # 9. CCV FREQUENCY: bracketing every N counting injections, N = the
        # method's CCV frequency (what the Run Builder uses). Switch: ccv_frequency.
        if profile is not None and _rule_enabled(toggles, "ccv_frequency"):
            n = profile.ccv_frequency() if hasattr(profile, "ccv_frequency") else None
            if not n:
                _record_gap("CCV frequency", "", UnconfiguredCriterion(
                    "{0}: no CCV frequency set (Method Profiles -> Calibration & CCV).".format(
                        self.method_id)))
            else:
                opens = bool(getattr(profile, "ccv_opens_run", lambda: False)())
                counts_qc = bool(getattr(profile, "ccv_counts_extracted_qc", lambda: True)())
                frbs = set(getattr(self.batch, "field_blanks", None) or [])
                fds = set(getattr(self.batch, "field_duplicates", None) or [])
                for flag in ccv_frequency_check(
                        [(i, "FRB" if i in frbs else "FD" if i in fds else classify_injection(i, dilutions))
                         for i in order],
                        n, opens, counts_qc):
                    flags_by_injection.setdefault(flag.injection_name, []).append(flag)

        # 10. MDL: a reported detection below the analyte's MDL. Switch: mdl_check.
        if profile is not None and _rule_enabled(toggles, "mdl_check"):
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
                    _rl, mdl, unit = profile.reporting_limits(analyte, _bmatrix)
                    if mdl is None:
                        _record_gap("MDL", analyte, UnconfiguredCriterion(
                            "{0} / {1}: no MDL set (Method Profiles -> Reporting "
                            "Limits).".format(analyte, _bmatrix)))
                        continue
                    if not _units_compatible(_unit(row), unit):
                        _record_gap("MDL", analyte, UnconfiguredCriterion(
                            "{0}: result in {1}, MDL in {2} -- not compared.".format(
                                analyte, _unit(row), unit)))
                        continue
                    flag = mdl_check(analyte, inj, conc, mdl, unit)
                    if flag is not None:
                        flags_by_injection.setdefault(inj, []).append(flag)

        # 11. SAMPLE DUPLICATE RPD (switched by the method's Dup QC type). Pair by the extraction record, else the name
        # "<sample> Dup"; judge only where both results reach the RL; one
        # detected and one not is flagged for review.
        dup_evaluated = set()
        if profile is not None and _qc_type_enabled(profile, "Dup"):
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
                    r1, r2 = _row(parent, analyte), _row(inj, analyte)
                    if r1 is None or r2 is None:
                        continue
                    rl, _mdl, rl_unit = profile.reporting_limits(analyte, _bmatrix)
                    if rl is None:
                        _record_gap("Dup", analyte, UnconfiguredCriterion(
                            "{0} / {1}: duplicate RPD is judged at or above the RL, and no RL "
                            "is set (Method Profiles -> Reporting Limits).".format(analyte, _bmatrix)))
                        continue
                    if not (_units_compatible(_unit(r1), rl_unit) and _units_compatible(_unit(r2), rl_unit)):
                        _record_gap("Dup", analyte, UnconfiguredCriterion(
                            "{0}: results in {1}/{2}, RL in {3} -- not compared.".format(
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
                                          value=raw.value, issue=raw.issue + " (parent %s)" % parent)
                        judged = True
                    elif d1 != d2:
                        flag = dup_one_detected_flag(analyte, inj, parent, j1, j2, rl, rl_unit)
                        win = {"lo": None, "hi": None,
                               "basis": "Dup: detected in both or in neither (at the RL)"}
                        judged = True
                    if flag is not None:
                        flags_by_injection.setdefault(inj, []).append(flag)
                    # written to the QC results so Data Review's gate sees it
                    # (a failing duplicate never reached it). Both below the
                    # RL: they agree, the RPD is not calculated.
                    self.batch.dup_results.append({
                        "analyte": analyte, "injection_name": inj, "parent": parent,
                        "rpd": rpd if (d1 and d2) else None,
                        "passed": flag is None,
                        "lo": win.get("lo"), "hi": win.get("hi"), "basis": win.get("basis", ""),
                        "issue": (flag.issue if flag is not None else
                                  "" if (d1 or d2) else "both below the RL -- RPD not calculated")})
                if judged:
                    dup_evaluated.add(inj)

        # Consolidate the QC Log (Sheet 6 equivalent)
        self.batch.qc_flags = [
            f for fl in flags_by_injection.values() for f in fl
        ]

        # Map flags onto review checks BY CHECK IDENTITY, not by display text.
        #
        # This matched `QCFlag.source` exactly until 2026-08-05. Wiring the
        # profiled checks changed those strings to carry the method id, so
        # calibration, r2, CCV and RT silently stopped matching and every one of
        # them reported AUTO_PASS while the run carried their flags. Only
        # is_response and LFSM/LFSMD escaped, because someone had hand-
        # normalised those two source strings.
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
                    # else: stays PENDING — spike not configured yet
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
                    # Advisory wins over evaluated: one compound can be in
                    # range on an injection while another exceeds a
                    # guidance-only window, and the exceedance is the thing a
                    # reviewer has to see.
                    if chk.injection_name in eis_advisory:
                        pass          # advisory exceedance — stays PENDING
                    # Otherwise the LFSM rule: AUTO_PASS only where the check
                    # actually ran. An injection whose export carried no %
                    # recovery column, or whose method could not resolve a
                    # window, stays PENDING so a reviewer sees it -- a silent
                    # pass would be indistinguishable from a good result.
                    elif chk.injection_name in eis_evaluated:
                        chk.status = CheckStatus.AUTO_PASS
                    # else: stays PENDING
                else:
                    chk.status = CheckStatus.AUTO_PASS
            # checks not auto-resolvable (blank_contamination, bloq_check, …)
            # remain PENDING for the human

            # A matrix spike the method switched on that the pipeline could
            # not judge HOLDS the release, naming why (it sat
            # "pending" in a queue SENAITE never reads, so the gate passed on
            # silence). Filed like an unconfigured criterion: qc_store writes
            # it as an unevaluated QC result, which Data Review's gate holds.
            if chk.status == CheckStatus.PENDING:
                # (an LFSMD's own lfsm_recovery is judged with its RPD; when
                # it is not, the LFSMD gap below names why)
                if (chk.check_name == "lfsm_recovery" and lfsm_enabled
                        and chk.qc_type == "LFSM"):
                    _record_gap("LFSM", "", UnconfiguredCriterion(
                        "{0}: LFSM recovery not judged -- {1}".format(
                            chk.injection_name, unevaluated_lfsm.get(chk.injection_name)
                            or ("not recorded under Matrix spikes in the guided extraction"
                                if chk.injection_name not in spikes else "not judged"))))
                elif chk.check_name == "lfsmd_rpd" and lfsmd_enabled:
                    _record_gap("LFSMD", "", UnconfiguredCriterion(
                        "{0}: LFSMD not judged -- {1}".format(
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
    def is_complete(self) -> bool:
        return all(
            c.status in (CheckStatus.AUTO_PASS, CheckStatus.ACCEPTED)
            for c in self.checks
        )

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
