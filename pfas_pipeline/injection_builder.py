"""
Injection Sequence Builder
Python port of Sample_Injection_List.xlsm VBA macros:
  BuildPFASRun, AddBatchSamples, AddBatchLFBs, AddRotatingCCV,
  AddFinalSample, CreateCSV (export to MS autosampler).

Builds the full MS injection sequence for a PFAS batch (18 samples)
with QC bracketing rules enforced automatically, and tells the run queue
exactly which QC checks each injection will require at review time.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import csv

from .constants import QC_TYPES


# ── Calibration ladders (extracted from VBA string constants) ─────────────────
# FDA PFAS in Food & Feed method (ng/mL)
FDA_CAL_LEVELS = [
    ("FDA-CAL-1",  20.0),
    ("FDA-CAL-2",  10.0),
    ("FDA-CAL-3",   5.0),
    ("FDA-CAL-4",   2.5),
    ("FDA-CAL-5",   1.25),
    ("FDA-CAL-6",   0.625),
    ("FDA-CAL-7",   0.313),
    ("FDA-CAL-8",   0.156),
    ("FDA-CAL-9",   0.078),
    ("FDA-CAL-10",  0.039),
]
FDA_ICV_CONC = 1.25   # ng/mL
FDA_CCV_CONC = 1.25   # ng/mL

# EPA 537-style drinking water ladder (ppt)
EPA537_CAL_LEVELS = [
    ("537-CAL-1",   2.0),
    ("537-CAL-2",   4.0),
    ("537-CAL-3",   8.0),
    ("537-CAL-4",  16.0),
    ("537-CAL-5",  40.0),
    ("537-CAL-6",  80.0),
    ("537-CAL-7", 160.0),
]
EPA537_QCS = [("537-QCS-1", "80/320 ppt"), ("537-QCS-2", "20/80 ppt")]


@dataclass
class Injection:
    """One row of the final injection sequence."""
    position:        int                # autosampler vial position
    injection_name:  str
    sample_type:     str                # "Standard", "QC", "Unknown"
    qc_type:         str                # CAL / ICV / CCV / MB / LFSM / LFSMD / Sample
    description:     str = ""
    expected_conc:   str = ""           # e.g. "1.25 ng/mL"
    parent_sample:   str = ""           # for LFSM/LFSMD/Dup
    spike_ppt:       float | None = None
    starlims_id:     str = ""
    # QC checks the reviewer must perform on this injection (drives run queue)
    review_checks:   list[str] = field(default_factory=list)


# Map QC type → list of review checks the analyst must perform.
# This is what drives the "run queue prompts what QC to look for" requirement.
REVIEW_CHECKS: dict[str, list[str]] = {
    "CAL":    ["calibration_pct_dev", "r_squared", "rt_deviation", "ion_ratio"],
    "ICV":    ["ccv_pct_dev", "is_response", "rt_deviation"],
    "CCV":    ["ccv_pct_dev", "is_response", "rt_deviation", "ion_ratio"],
    "MB":     ["blank_contamination", "is_response", "lod_check"],
    # The other blanks. Without these, classify_injection's new roles fell back
    # to REVIEW_CHECKS["Sample"] and a blank was given the CHECKS OF A CLIENT
    # SAMPLE — bloq/lod qualifiers instead of a contamination check.
    "MxB":    ["blank_contamination", "is_response"],
    "LRB":    ["blank_contamination", "is_response"],
    "CCB":    ["blank_contamination", "is_response"],
    "LFB":    ["recovery", "is_response"],
    "LFSM":   ["lfsm_recovery", "is_response", "ion_ratio", "rt_deviation"],
    "LFSMD":  ["lfsmd_rpd", "lfsm_recovery", "is_response"],
    "Dup":    ["duplicate_rpd", "is_response"],
    "Sample": ["is_response", "ion_ratio", "rt_deviation", "signal_to_noise",
               "bloq_check", "lod_check"],
}


class InjectionSequenceBuilder:
    """
    Replicates BuildPFASRun from the VBA:

      1. Full calibration curve (CAL 10 → CAL 1, low to high or as configured)
      2. ICV
      3. Method Blank
      4. Batch samples in groups, with rotating CCV every `ccv_interval` injections
      5. LFSM + LFSMD pairs adjacent to their parent sample
      6. Closing CCV (AddFinalSample → final bracket)
    """

    def __init__(
        self,
        batch_date: date,
        analyst_initials: str,
        matrix: str,
        method: str = "FDA",            # "FDA" or "537"
        ccv_interval: int | None = None, # None → take from method profile
    ):
        self.batch_date = batch_date
        self.initials = analyst_initials.upper()
        self.matrix = matrix
        self.method = method
        # Resolve sequence rules from the method profile so CCV frequency and
        # the opening/curve blanks match the method (FDA: CCV/6 + MeOH blanks;
        # 537.1: CCV/10).  Falls back gracefully if profile unavailable.
        self._seq_rule = None
        try:
            from .method_profiles import get_profile
            self._seq_rule = get_profile(method).sequence_rule()
        except Exception:
            pass
        if ccv_interval is not None:
            self.ccv_interval = ccv_interval
        elif self._seq_rule is not None:
            self.ccv_interval = self._seq_rule.ccv_frequency
        else:
            self.ccv_interval = 10
        self._seq: list[Injection] = []
        self._pos = 0
        self._ccv_count = 0
        self._date_code = batch_date.strftime("%y%m%d")       # 260226
        self._date_iso = batch_date.strftime("%Y-%m-%d")      # 2026-02-26
        self._sample_counter = 0
        self._since_last_ccv = 0

    # ── internal helpers ──────────────────────────────────────────────────────
    def _next_pos(self) -> int:
        self._pos += 1
        return self._pos

    def _add(self, inj: Injection):
        self._seq.append(inj)
        if inj.qc_type not in ("CAL", "ICV"):
            self._since_last_ccv += 1

    def _maybe_rotating_ccv(self):
        """AddRotatingCCV: insert a CCV every ccv_interval analytical injections."""
        if self._since_last_ccv >= self.ccv_interval:
            self.add_ccv()

    # ── public build steps (mirror the VBA subs) ─────────────────────────────
    def add_calibration_curve(self, low_to_high: bool = True):
        """AddCAL: insert full calibration ladder."""
        levels = FDA_CAL_LEVELS if self.method == "FDA" else EPA537_CAL_LEVELS
        ordered = list(reversed(levels)) if low_to_high else levels
        unit = "ng/mL" if self.method == "FDA" else "ppt"
        for name, conc in ordered:
            self._add(Injection(
                position=self._next_pos(),
                injection_name=f"{name}-{self._date_code}",
                sample_type="Standard",
                qc_type="CAL",
                expected_conc=f"{conc} {unit}",
                description=f"Calibration level {name.split('-')[-1]}",
                review_checks=REVIEW_CHECKS["CAL"],
            ))

    def add_icv(self):
        prefix = "FDA" if self.method == "FDA" else "537"
        self._add(Injection(
            position=self._next_pos(),
            injection_name=f"{prefix}-ICV-{self._date_code}",
            sample_type="QC",
            qc_type="ICV",
            expected_conc=f"{FDA_ICV_CONC} ng/mL",
            description="Initial calibration verification",
            review_checks=REVIEW_CHECKS["ICV"],
        ))

    def add_ccv(self):
        """AddCCV: numbered continuing calibration verification."""
        self._ccv_count += 1
        prefix = "FDA" if self.method == "FDA" else "537"
        self._add(Injection(
            position=self._next_pos(),
            injection_name=f"{prefix}-CCV-{self._date_code}-{self._ccv_count:02d}",
            sample_type="QC",
            qc_type="CCV",
            expected_conc=f"{FDA_CCV_CONC} ng/mL",
            description=f"Continuing calibration verification #{self._ccv_count}",
            review_checks=REVIEW_CHECKS["CCV"],
        ))
        self._since_last_ccv = 0

    def add_solvent_blank(self, label: str = "MeOH"):
        """FDA §2024.8.4: solvent (MeOH) blank injections that open the run
        and follow the calibration curve."""
        self._add(Injection(
            position=self._next_pos(),
            injection_name=f"{self.initials} {label} Blank "
                           f"{self._date_iso}-{self._pos:02d}",
            sample_type="Blank",
            qc_type="SolventBlank",
            description=f"{label} solvent blank",
            review_checks=["blank_contamination"],
        ))

    def add_method_blank(self, blank_number: int = 1):
        """AddBatchLFBs equivalent for MB; Pattern-3 naming."""
        self._add(Injection(
            position=self._next_pos(),
            injection_name=(
                f"{self.initials} {self.matrix} MB "
                f"{self._date_iso}-{blank_number:02d}"
            ),
            sample_type="QC",
            qc_type="MB",
            description="Method blank",
            review_checks=REVIEW_CHECKS["MB"],
        ))

    def add_sample(self, description: str, starlims_id: str = ""):
        """AddBatchSamples: one environmental sample."""
        self._maybe_rotating_ccv()
        self._sample_counter += 1
        name = f'{self.initials} {self.matrix} Sample "{description}"'
        if starlims_id:
            name = f"{self.initials} {self.matrix} Sample {starlims_id}"
        self._add(Injection(
            position=self._next_pos(),
            injection_name=name,
            sample_type="Unknown",
            qc_type="Sample",
            description=description,
            starlims_id=starlims_id,
            review_checks=REVIEW_CHECKS["Sample"],
        ))

    def add_lfsm_pair(
        self,
        parent_description: str,
        spike_ppt: float,
        level: str = "High",
        include_duplicate: bool = True,
    ):
        """
        AppendLFSM_LFSMD: spike pair adjacent to the parent sample.
        Naming matches real data: 'KCP Deer Sample "Deer Hamburger"; LFSM High'
        """
        self._maybe_rotating_ccv()
        parent = f'{self.initials} {self.matrix} Sample "{parent_description}"'
        self._add(Injection(
            position=self._next_pos(),
            injection_name=f"{parent}; LFSM {level}",
            sample_type="QC",
            qc_type="LFSM",
            description=f"LFSM of {parent_description} @ {spike_ppt} ppt",
            parent_sample=parent,
            spike_ppt=spike_ppt,
            review_checks=REVIEW_CHECKS["LFSM"],
        ))
        if include_duplicate:
            self._add(Injection(
                position=self._next_pos(),
                injection_name=f"{parent}; LFSM {level} Dup.",
                sample_type="QC",
                qc_type="LFSMD",
                description=f"LFSMD of {parent_description} @ {spike_ppt} ppt",
                parent_sample=parent,
                spike_ppt=spike_ppt,
                review_checks=REVIEW_CHECKS["LFSMD"],
            ))

    def finalize(self):
        """AddFinalSample / BuildFinalRun: closing CCV bracket."""
        if self._seq and self._seq[-1].qc_type != "CCV":
            self.add_ccv()
        return self._seq

    # ── full pipeline shortcut ────────────────────────────────────────────────
    def build_standard_pfas_run(
        self,
        samples: list[dict],     # [{"description": ..., "starlims_id": ...}, ...]
        lfsm_parent: str,        # description of the sample to spike
        spike_ppt: float,
        n_blanks: int = 1,
    ) -> list[Injection]:
        """
        BuildPFASRun: the complete one-call recipe, now method-aware.

        FDA template (§2024.8.4):
          MeOH blank → CAL curve → MeOH blank → ICV → samples
          (CCV every 6) → LFSM/LFSMD → closing CCV
        537.1 / 1633A template:
          CAL curve → ICV → opening CCV → MB → samples (CCV every 10)
          → LFSM/LFSMD → closing CCV
        """
        sr = self._seq_rule
        fda_style = bool(sr and sr.opens_with_solvent_blank)

        if fda_style:
            self.add_solvent_blank()                 # opening MeOH blank
            self.add_calibration_curve(low_to_high=sr.cal_low_to_high)
            if sr.blank_after_curve:
                self.add_solvent_blank()             # blank after curve
            self.add_icv()
        else:
            self.add_calibration_curve()
            self.add_icv()
            self.add_ccv()                           # opening bracket

        for i in range(n_blanks):
            self.add_method_blank(i + 1)

        for s in samples:
            self.add_sample(s["description"], s.get("starlims_id", ""))
            if s["description"] == lfsm_parent:
                self.add_lfsm_pair(lfsm_parent, spike_ppt)
        return self.finalize()

    # ── exports ───────────────────────────────────────────────────────────────
    def to_csv(self, path: str | Path) -> Path:
        """CreateCSV: export sequence for the MS autosampler."""
        path = Path(path)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "Position", "Injection Name", "Sample Type", "QC Type",
                "Expected Conc", "Parent Sample", "Spike (ppt)",
                "StarLIMS ID", "Description",
            ])
            for inj in self._seq:
                w.writerow([
                    inj.position, inj.injection_name, inj.sample_type,
                    inj.qc_type, inj.expected_conc, inj.parent_sample,
                    inj.spike_ppt or "", inj.starlims_id, inj.description,
                ])
        return path

    def review_queue(self) -> list[dict]:
        """
        Produce the run-queue payload: for every injection, the list of QC
        checks the reviewer must perform.  This is consumed by run_queue.py
        and pushed to SENAITE as Remarks/InterimFields.
        """
        return [
            {
                "position": inj.position,
                "injection_name": inj.injection_name,
                "qc_type": inj.qc_type,
                "qc_label": QC_TYPES.get(inj.qc_type, inj.qc_type),
                "checks": inj.review_checks,
            }
            for inj in self._seq
        ]
