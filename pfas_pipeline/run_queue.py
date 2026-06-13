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
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .models import Batch, QCFlag
from .qc_engine import (
    is_raw_check, rt_deviation_check, qual_quan_check,
    calibration_check, signal_to_noise_check,
)
from .constants import INTERNAL_STANDARDS, ANALYTES, CRITERIA


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
        rows = self.batch.injections
        flags_by_injection: dict[str, list[QCFlag]] = {}
        toggles = _load_rule_toggles(self.method_id)

        # 1. IS Raw (is_response rule)
        if _rule_enabled(toggles, "is_response"):
            for is_cmp in INTERNAL_STANDARDS:
                for res in is_raw_check(rows, is_cmp):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                        self.batch.is_results.append(res)

        # 2. RT Deviation (rrt_deviation rule)
        rt_enabled  = _rule_enabled(toggles, "rrt_deviation")
        # 3. Qual-Quan (ion_ratio rule)
        iq_enabled  = _rule_enabled(toggles, "ion_ratio")
        # 4. Calibration (cal_r2 OR ccv_recovery — run if either is on)
        cal_enabled = _rule_enabled(toggles, "cal_r2") or _rule_enabled(toggles, "ccv_recovery")
        # 5. Signal-to-Noise (sn_min rule)
        sn_enabled  = _rule_enabled(toggles, "sn_min")

        for analyte in ANALYTES:
            if rt_enabled:
                for res in rt_deviation_check(rows, analyte):
                    if res.flag:
                        flags_by_injection.setdefault(res.injection_name, []).append(res.flag)
                    self.batch.rt_results.append(res)
            if iq_enabled:
                for res in qual_quan_check(rows, analyte):
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
