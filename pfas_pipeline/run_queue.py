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
    is_raw_check, rt_deviation_check, qual_quan_check,
    calibration_check, signal_to_noise_check,
    recovery_check_profiled, rpd_check_profiled,
)
from .constants import CRITERIA
from .method_profiles import (
    get_profile as _get_method_profile,
    get_analyte_list as _get_analytes,
    get_is_list as _get_is_list,
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
    "blank_contamination": "Verify method blank shows no analyte above ½ LOQ",
    "lod_check":           "Apply <LOD qualifier where blank ≥ sample",
    "bloq_check":          "Apply BLoQ qualifier for results below LOQ",
    "recovery":            "Verify LCS recovery 50–150%",
    "lfsm_recovery":       "Verify LFSM recovery 50–150% (select spike conc. if not set)",
    "lfsmd_rpd":           "Verify LFSM/LFSMD RPD ≤ 30%",
    "duplicate_rpd":       "Verify sample duplicate RPD ≤ 30%",
    "signal_to_noise":     "Verify S/N ≥ 3 for reported analytes",
}


# ── LFSM/LFSMD injection name helpers ────────────────────────────────────────

def _lfsm_parent_name(lfsm_inj):
    """'KCP ... ; LFSM High' → 'KCP ...'  (strip the LFSM suffix)."""
    idx = lfsm_inj.find("; LFSM ")
    return lfsm_inj[:idx] if idx >= 0 else lfsm_inj


def _lfsm_level_label(lfsm_inj):
    """'KCP ... ; LFSM High' → 'High'."""
    idx = lfsm_inj.find("; LFSM ")
    return lfsm_inj[idx + 7:].strip() if idx >= 0 else ""


def _lfsmd_to_lfsm_name(lfsmd_inj):
    """'KCP ... ; LFSM High Dup.' → 'KCP ... ; LFSM High'."""
    if lfsmd_inj.endswith(" Dup."):
        return lfsmd_inj[:-5].rstrip()
    return lfsmd_inj


def _get_conc(inj_name, analyte, lookup):
    for row in lookup.get(inj_name, []):
        if row.compound_name == analyte:
            return reported_conc(row)
    return None


def _load_rule_toggles(method_id: str, rules_path: str = "/data/qc/qc_rules.json") -> dict:
    """Return {rule_library_key: bool} for method_id.  Default all True on error."""
    if not method_id:
        return {}
    try:
        import os
        if not os.path.exists(rules_path):
            return {}
        with open(rules_path) as f:
            rules = json.load(f)
        return rules.get("method_rule_toggles", {}).get(method_id, {})
    except Exception:
        return {}


def _rule_enabled(toggles: dict, library_key: str) -> bool:
    """True if the rule is enabled (default ON when key absent)."""
    return bool(toggles.get(library_key, True))


class RunQueue:
    """
    Stateful review queue for one batch.

    Workflow:
        q = RunQueue(batch, review_plan)   # plan comes from InjectionSequenceBuilder
        q.auto_evaluate()                  # run QC engine on everything
        q.pending()                        # what the human still needs to look at
        q.accept(injection, check, "KP", "looks fine, matrix effect")
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

    # ── automatic evaluation ──────────────────────────────────────────────────
    def auto_evaluate(self):
        """
        Run the full QC engine and mark checks AUTO_PASS / AUTO_FAIL.
        Equivalent to pressing every macro button in the xlsm at once.

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
        # br-PFOS still contributed a fifth of the reported PFOS. Check them.
        try:
            from .method_profiles import get_isomer_summation
            for pair in (get_isomer_summation(_method) or []):
                if not pair.get("enabled", True):
                    continue
                for part in ("linear", "branched"):
                    name = pair.get(part)
                    if name and name not in _analytes:
                        _analytes = list(_analytes) + [name]
        except Exception as exc:                       # noqa: BLE001
            logger.warning("could not add isomer components to QC: %s", exc)

        # 1. IS Raw (is_response rule)
        if _rule_enabled(toggles, "is_response"):
            for is_cmp in _get_is_list(_method):
                # unfiltered: dilutions ARE checked for IS consistency
                for res in is_raw_check(all_rows, is_cmp, dilutions,
                                        method_id=_method):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    # Record EVERY result, not only the failures. The RT,
                    # ion-ratio and calibration checks all do; IS did not, so
                    # the QC Summary's IS row could only ever contain failures
                    # and the gate could never pass however good the run was.
                    self.batch.is_results.append(res)

        # 2. RT Deviation (rrt_deviation rule)
        rt_enabled  = _rule_enabled(toggles, "rrt_deviation")
        # 3. Qual-Quan (ion_ratio rule)
        iq_enabled  = _rule_enabled(toggles, "ion_ratio")
        # 4. Calibration (cal_r2 OR ccv_recovery — run if either is on)
        cal_enabled  = _rule_enabled(toggles, "cal_r2") or _rule_enabled(toggles, "ccv_recovery")
        # 5. Signal-to-Noise (sn_min rule)
        sn_enabled   = _rule_enabled(toggles, "sn_min")
        # 6. LFSM/LFSMD (lfsm_recovery / lfsmd_rpd rules)
        lfsm_enabled  = _rule_enabled(toggles, "lfsm_recovery")
        lfsmd_enabled = _rule_enabled(toggles, "lfsmd_rpd")

        for analyte in _analytes:
            if rt_enabled:
                for res in rt_deviation_check(rows, analyte):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.rt_results.append(res)
            if iq_enabled:
                for res in qual_quan_check(rows, analyte, _non_iso):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.qual_quan_results.append(res)
            if cal_enabled:
                for res in calibration_check(rows, analyte):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.cal_results.append(res)
            if sn_enabled:
                for flag in signal_to_noise_check(rows, analyte):
                    flags_by_injection.setdefault(flag.injection_name, []).append(flag)

        # 6. LFSM recovery + LFSMD RPD (per-analyte tiered limits from method profile)
        lfsm_evaluated  = set()   # injection names where spike was resolved + check ran
        lfsmd_evaluated = set()

        if lfsm_enabled or lfsmd_enabled:
            profile = None
            if self.method_id:
                try:
                    profile = _get_method_profile(self.method_id)
                except KeyError:
                    pass

            matrix = self.batch.matrix or ""
            conc_lookup = {}
            for row in rows:
                conc_lookup.setdefault(row.injection_name, []).append(row)

            # Identify unique LFSM injection names (not duplicates)
            # The extraction pedigree says which injections are matrix spikes
            # and what they were fortified from. Falling back to the name only
            # when there is no pedigree: matching the literal substring
            # "; LFSM " meant that a lab whose names read
            # 'KCP Silage "Egg-2" LFSM Mid' had no LFSM evaluated at all.
            spikes = getattr(self.batch, "spikes", None) or {}
            seen_lfsm = set()
            lfsm_inj_names = []
            for row in rows:
                name = row.injection_name
                if name in seen_lfsm:
                    continue
                if spikes:
                    if name not in spikes:
                        continue
                    if classify_injection(name, dilutions) != "LFSM":
                        continue
                elif "; LFSM " not in name or name.rstrip().endswith(" Dup."):
                    continue
                seen_lfsm.add(name)
                lfsm_inj_names.append(name)

            # Per-LFSM-injection evaluation
            lfsm_results_by_inj = {}   # lfsm_inj → {analyte: LFSMResult}
            unevaluated_lfsm = {}      # lfsm_inj → why it could not be judged

            if lfsm_enabled and profile is not None:
                for lfsm_inj in lfsm_inj_names:
                    pedigree = spikes.get(lfsm_inj) or {}
                    level_label = (pedigree.get("level")
                                   or _lfsm_level_label(lfsm_inj))
                    # What was actually spiked beats the nominal level.
                    spike_ppt = pedigree.get("spike_ppt")
                    if spike_ppt in (None, 0):
                        spike_ppt = profile.resolve_spike_ppt(
                            "LFSM", level_label, matrix=matrix)
                    if spike_ppt is None or spike_ppt == 0:
                        logger.info("No spike level for %s — LFSM recovery "
                                    "stays pending", lfsm_inj)
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
                    spike_units = pedigree.get("spike_units") or "ppt"
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

                    parent_inj = (pedigree.get("parent")
                                  or _lfsm_parent_name(lfsm_inj))
                    lfsm_results_by_inj[lfsm_inj] = {}

                    for analyte in _analytes:
                        fortified = _get_conc(lfsm_inj, analyte, conc_lookup)
                        if fortified is None:
                            continue
                        unfort = _get_conc(parent_inj, analyte, conc_lookup) or 0.0
                        recovery_pct = (fortified - unfort) / spike_ppt * 100.0

                        if recovery_pct < 0:
                            # Physically impossible: the fortified sample
                            # measured LESS than the unfortified one. Reporting
                            # it as "outside 65-135%" sends a reviewer to look
                            # at recovery when the real question is whether the
                            # spike went in, or whether the LFSM is paired with
                            # the right parent.
                            raw_flag = QCFlag(
                                source="LFSM & LFSMD", analyte=analyte,
                                injection_name=lfsm_inj,
                                value="{0:.1f}%".format(recovery_pct),
                                issue=("(REC) negative recovery — the spiked "
                                       "sample measured lower than its "
                                       "unspiked parent {0}".format(parent_inj)),
                            )
                        else:
                            raw_flag = recovery_check_profiled(
                                profile, analyte, matrix, "LFSM",
                                recovery_pct, lfsm_inj
                            )
                        flag = None
                        if raw_flag is not None:
                            # Normalise source so _CHECK_SOURCES mapping picks it up
                            flag = QCFlag(
                                source="LFSM & LFSMD",
                                analyte=raw_flag.analyte,
                                injection_name=raw_flag.injection_name,
                                value=raw_flag.value,
                                issue=raw_flag.issue,
                            )
                            flags_by_injection.setdefault(lfsm_inj, []).append(flag)

                        lfsm_result = LFSMResult(
                            analyte=analyte,
                            lfsm_injection=lfsm_inj,
                            parent_injection=parent_inj,
                            spike_value_ppt=spike_ppt,
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
                    if spikes:
                        if name not in spikes:
                            continue
                        if classify_injection(name, dilutions) != "LFSMD":
                            continue
                        dup_parent = (spikes[name] or {}).get("parent")
                        for candidate in lfsm_inj_names:
                            if (spikes.get(candidate) or {}).get(
                                    "parent") == dup_parent:
                                lfsm_inj = candidate
                                break
                        if lfsm_inj is None:
                            logger.info("No LFSM shares a parent with %s — "
                                        "RPD stays pending", name)
                            continue
                    elif "; LFSM " in name and name.rstrip().endswith(" Dup."):
                        lfsm_inj = _lfsmd_to_lfsm_name(name)
                    else:
                        continue
                    seen_lfsmd.add(name)
                    inj_lfsm_results = lfsm_results_by_inj.get(lfsm_inj, {})
                    if not inj_lfsm_results:
                        continue  # LFSM not evaluated → stays PENDING

                    for analyte in _analytes:
                        lfsm_res = inj_lfsm_results.get(analyte)
                        if lfsm_res is None:
                            continue
                        fortified_dup = _get_conc(name, analyte, conc_lookup)
                        if fortified_dup is None:
                            continue

                        rec_dup  = ((fortified_dup - lfsm_res.unfortified_conc)
                                    / lfsm_res.spike_value_ppt * 100.0)
                        mean_rec = (lfsm_res.recovery_pct + rec_dup) / 2.0
                        rpd_pct  = (abs(lfsm_res.recovery_pct - rec_dup)
                                    / mean_rec * 100.0 if mean_rec else 0.0)

                        raw_flag = rpd_check_profiled(
                            profile, analyte, matrix, "LFSMD", rpd_pct, name
                        )
                        flag = None
                        if raw_flag is not None:
                            flag = QCFlag(
                                source="LFSM & LFSMD",
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
                        ))

                    lfsmd_evaluated.add(name)

        # Consolidate the QC Log (Sheet 6 equivalent)
        self.batch.qc_flags = [
            f for fl in flags_by_injection.values() for f in fl
        ]

        # Map flags onto review checks
        _CHECK_SOURCES = {
            "is_response":         {"SUR-IS Response Table"},
            "rt_deviation":        {"RT Deviation"},
            "ion_ratio":           {"Qual-Quan Table"},
            "calibration_pct_dev": {"Calibration %"},
            "r_squared":           {"Calibration %"},
            "ccv_pct_dev":         {"Calibration %"},
            "signal_to_noise":     {"Signal-to-Noise"},
            "lfsm_recovery":       {"LFSM & LFSMD"},
            "lfsmd_rpd":           {"LFSM & LFSMD"},
        }

        for chk in self.checks:
            inj_flags = flags_by_injection.get(chk.injection_name, [])
            relevant_sources = _CHECK_SOURCES.get(chk.check_name, set())
            relevant = [f for f in inj_flags if f.source in relevant_sources]
            if relevant:
                chk.status = CheckStatus.AUTO_FAIL
                chk.flags = [f.as_dict() for f in relevant]
            elif chk.check_name in _CHECK_SOURCES:
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
                    # else: stays PENDING
                else:
                    chk.status = CheckStatus.AUTO_PASS
            # checks not auto-resolvable (blank_contamination, bloq_check, …)
            # remain PENDING for the human

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
