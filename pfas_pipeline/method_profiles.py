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
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


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
# Profile base
# ─────────────────────────────────────────────────────────────────────────────

# FDA Table 10-1 "big four" with tighter limits in animal-protein matrices
_FDA_BIG4 = frozenset({"PFOS", "PFOA", "PFHxS", "PFNA",
                       "lr-PFOS", "br-PFOS", "lr-PFHxS", "br-PFHxS"})
_FDA_TIGHT_MATRICES = frozenset({
    "egg", "eggs", "meat", "muscle", "beef", "pork", "poultry", "deer",
    "seafood", "fish", "shellfish",
})

# Analytes without commercially available matched labeled standards
# (FDA Table 10-1 footnote a; matches NON_ISO_ANALYTES in constants.py)
_FDA_NO_LABELED_STD = frozenset({
    "9Cl-PF3ONS", "11Cl-PF3OUdS", "PFDoS", "PFDS",
    "PFNS", "PFODA", "PFPeS", "PFTrDA", "PFTrDS", "PFUnDS",
})

# FDA Table 9-1: native analyte → surrogate used as its IS (Linear, 1/x)
FDA_NATIVE_SURROGATE_MAP = {
    "PFBA": "M3PFBA",   "PFPeA": "M3PFPeA", "PFHxA": "M5PFHxA",
    "PFHpA": "M4PFHpA", "PFOA": "M8PFOA",   "PFNA": "M5PFNA",
    "PFDA": "M2PFDA",   "PFUDA": "MPFUdA",  "PFDoA": "MPFDoA",
    "PFTrDA": "MPFDoA", "PFTeDA": "M2PFTeDA", "PFHxDA": "M2PFHxDA",
    "PFBS": "M3PFBS",   "lr-PFHxS": "M3PFHxS", "br-PFHxS": "M3PFHxS",
    "lr-PFOS": "M8PFOS", "br-PFOS": "M8PFOS",
    "GenX (HFPO-DA)": "M3HFPO", "FOSA": "M8FOSA",
    "4:2 FTS": "13C2,D4 4:2 FTS", "6:2FTS": "13C2,D4 6:2 FTS",
    "8:2 FTS": "13C2,D4 8:2 FTS", "10:2 FTS": "13C2,D4 10:2 FTS",
}
# All FDA surrogates quantified against M4PFOA via mean response factor
FDA_SURROGATE_IS = "M4PFOA"

# FDA per-matrix sample factor: instrument ng/mL → food ng/g
# (method Section 2024.9: muscle/fish/eggs ×0.5, milk ×0.2, feed ×2)
FDA_SAMPLE_FACTORS = {
    "muscle": 0.5, "meat": 0.5, "deer": 0.5, "beef": 0.5, "pork": 0.5,
    "poultry": 0.5, "fish": 0.5, "seafood": 0.5, "egg": 0.5, "eggs": 0.5,
    "milk": 0.2,
    "feed": 2.0, "animal feed": 2.0,
}


class MethodProfile:
    """Base class.  Subclasses override the rule methods."""
    method_id: str = ""
    description: str = ""

    def qc_rules(self, analyte: str, matrix: str = "",
                 qc_type: str = "LFSM") -> QCRule:
        raise NotImplementedError

    def calibration_rule(self, analyte: str = "") -> CalibrationRule:
        raise NotImplementedError

    def ccv_rule(self) -> CCVRule:
        raise NotImplementedError

    def is_rule(self) -> ISRule:
        raise NotImplementedError

    def confirmation_rule(self) -> ConfirmationRule:
        raise NotImplementedError

    def sequence_rule(self) -> SequenceRule:
        raise NotImplementedError

    def sample_factor(self, matrix: str) -> Optional[float]:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# FDA 32-PFAS in Food  (from the uploaded method document)
# ─────────────────────────────────────────────────────────────────────────────

class FDA32PFASProfile(MethodProfile):
    method_id = "FDA_32PFAS"
    description = ("USDA/FDA 32-PFAS in Food v10 (5/5/26) + AOAC SMPR "
                   "2023.003; LC-MS/MS isotope dilution")

    def qc_rules(self, analyte, matrix="", qc_type="LFSM") -> QCRule:
        m = matrix.lower().strip()

        if qc_type in ("SUR", "surrogate"):
            # §10.1(5): 50–150% guidance; no hard requirement in method/SMPR
            return QCRule(50.0, 150.0,
                          notes="Surrogate recovery is guidance only "
                                "(FDA §2024.10.1(5))",
                          is_guidance_only=True)

        if qc_type in ("Dup", "duplicate"):
            # §10.3: regulatory duplicates %difference < 20%
            return QCRule(rpd_max=20.0,
                          notes="Regulatory duplicate %diff < 20% "
                                "(FDA §2024.10.3)")

        # MS/MSD/LFSM recovery — Table 10-1, three tiers
        if analyte in _FDA_NO_LABELED_STD:
            return QCRule(40.0, 140.0, rsd_max=30.0,
                          notes="No matched labeled standard "
                                "(Table 10-1 footnote a)")
        if analyte in _FDA_BIG4 and any(t in m for t in _FDA_TIGHT_MATRICES):
            return QCRule(80.0, 120.0, rsd_max=20.0,
                          notes="PFOS/PFOA/PFHxS/PFNA in eggs/meat/seafood "
                                "(Table 10-1 tier 1)")
        return QCRule(65.0, 135.0, rsd_max=25.0,
                      notes="Table 10-1 tier 2 (other matrices / "
                            "other analytes)")

    def calibration_rule(self, analyte="") -> CalibrationRule:
        # §10.1(1): r² ≥ 0.990.  Table 9-1: Linear, 1/x (natives).
        fit = "mean_response_factor" if analyte.startswith(("M", "13C")) \
              else "linear"
        return CalibrationRule(r2_min=0.990, point_pct_dev_max=None,
                               default_fit=fit,
                               default_weighting="none" if fit != "linear"
                               else "1/x")

    def ccv_rule(self) -> CCVRule:
        # §10.1(3) 70–130%; §2024.8.4 run template: CCV every 6 samples
        return CCVRule(70.0, 130.0, frequency=6)

    def is_rule(self) -> ISRule:
        # Method has no numeric IS-area criterion; lab SOP retains the
        # legacy ±50%-of-batch-average screen from the Excel workbook.
        return ISRule(vs_ical_avg_min=50.0, vs_ical_avg_max=150.0,
                      notes="Lab SOP screen (Excel legacy); FDA method "
                            "sets no numeric IS-area limit")

    def confirmation_rule(self) -> ConfirmationRule:
        return ConfirmationRule(
            ion_ratio_tol_pct=30.0,          # §10.2(1)
            rrt_tol_pct=1.0,                 # §10.2(2): RRT ≤1% relative
            sn_min_quant=3.0,
            sn_min_confirm=3.0,              # §10.2(3) at 0.039; else 0.078
            single_transition_analytes=("PFBA", "PFPeA"),
            confirm_pct_diff_max=20.0,       # §10.2(4): HRMS vs QqQ
            notes="PFBA/PFPeA positives require LC-HRMS confirmation; "
                  "cholic acid (TDCA/TCDCA/TUDCA) interference transitions "
                  "monitored for PFOS (§2024.8.5)",
        )

    def sequence_rule(self) -> SequenceRule:
        # §2024.8.4: MeOH blank → curve → MeOH blank → samples; CCV/6
        return SequenceRule(opens_with_solvent_blank=True,
                            blank_after_curve=True,
                            ccv_frequency=6, closing_ccv=True)

    def sample_factor(self, matrix: str) -> Optional[float]:
        m = matrix.lower().strip()
        for key, f in FDA_SAMPLE_FACTORS.items():
            if key in m:
                return f
        return None


# ─────────────────────────────────────────────────────────────────────────────
# EPA 537.1  (drinking water)
# ─────────────────────────────────────────────────────────────────────────────

class EPA537Profile(MethodProfile):
    method_id = "EPA_537_1"
    description = "EPA 537.1 PFAS in drinking water (EPA/600/R-20/006)"

    def qc_rules(self, analyte, matrix="", qc_type="LFSM") -> QCRule:
        if qc_type in ("SUR", "surrogate"):
            return QCRule(70.0, 130.0, notes="§9.3.5 surrogates 70–130%")
        if qc_type in ("LFB", "LCS"):
            # §9.3.3: low-level (≤MRL) 50–150%; mid/high 70–130%
            return QCRule(70.0, 130.0,
                          notes="Mid/high LFB 70–130%; use 50–150% when "
                                "fortified at/below MRL (§9.3.3)")
        if qc_type in ("Dup", "duplicate", "LFSMD"):
            return QCRule(70.0, 130.0, rpd_max=30.0,
                          notes="LFSMD: recoveries 70–130%, RPD ≤30% "
                                "(lab-typical; method defers to §9.3.6)")
        # LFSM
        return QCRule(70.0, 130.0,
                      notes="LFSM 70–130% (50–150% near MRL) §9.3.6")

    def calibration_rule(self, analyte="") -> CalibrationRule:
        # §10.2: each CAL point 70–130% of true (50–150% at/below MRL);
        # IS calibration technique, forcing through origin required.
        return CalibrationRule(r2_min=0.99, point_pct_dev_max=30.0,
                               low_point_pct_dev_max=50.0,
                               force_origin=True)

    def ccv_rule(self) -> CCVRule:
        # CCC: lowest level 50–150%, others 70–130%; every 10 field samples
        return CCVRule(70.0, 130.0, frequency=10,
                       low_level_min=50.0, low_level_max=150.0)

    def is_rule(self) -> ISRule:
        # §9.3.4: 70–140% of most recent CCC AND within ±50% of ICAL average
        return ISRule(vs_ical_avg_min=50.0, vs_ical_avg_max=150.0,
                      vs_last_ccv_min=70.0, vs_last_ccv_max=140.0,
                      notes="Both conditions must hold (§9.3.4); on failure "
                            "re-inject a second aliquot in a fresh vial")

    def confirmation_rule(self) -> ConfirmationRule:
        return ConfirmationRule(rt_tol_abs_min=0.05,
                                notes="RT within ±0.05 min of expected; "
                                      "no qual-ion ratio criterion in 537.1")

    def sequence_rule(self) -> SequenceRule:
        return SequenceRule(ccv_frequency=10, closing_ccv=True)


# ─────────────────────────────────────────────────────────────────────────────
# EPA 1633A  (aqueous / solid / biosolid / tissue)
# ─────────────────────────────────────────────────────────────────────────────

# Representative EIS recovery limits (aqueous).  The method's Tables 6 & 8
# carry the authoritative per-analyte, per-matrix values (some as low as
# 5%, some to 365% depending on matrix) — VERIFY against your method copy.
_1633A_EIS_AQUEOUS_DEFAULT = (40.0, 130.0)
_1633A_EIS_OVERRIDES_AQUEOUS = {
    # analyte: (min%, max%) — commonly published wider windows
    "M2-4:2FTS": (20.0, 150.0),
    "M2-6:2FTS": (20.0, 150.0),
    "M2-8:2FTS": (20.0, 150.0),
    "d3-NMeFOSAA": (20.0, 150.0),
    "d5-NEtFOSAA": (20.0, 150.0),
    "M8FOSA": (20.0, 150.0),
}


class EPA1633AProfile(MethodProfile):
    method_id = "EPA_1633A"
    description = ("EPA 1633A — 40 PFAS in aqueous, solid, biosolid, "
                   "tissue (Jan 2024 / 2024 update)")

    def qc_rules(self, analyte, matrix="", qc_type="LFSM") -> QCRule:
        if qc_type in ("EIS", "SUR", "surrogate"):
            lo, hi = _1633A_EIS_OVERRIDES_AQUEOUS.get(
                analyte, _1633A_EIS_AQUEOUS_DEFAULT)
            return QCRule(lo, hi, verify_against_method=True,
                          notes="EIS limits are per-analyte AND per-matrix "
                                "(1633A Tables 6/8) — verify against method")
        if qc_type in ("OPR", "LCS", "LFB"):
            return QCRule(70.0, 130.0, verify_against_method=True,
                          notes="OPR/IPR limits are per-analyte "
                                "(1633A Table 5 et seq.) — verify")
        if qc_type in ("Dup", "duplicate", "LFSMD", "MSD"):
            return QCRule(rpd_max=30.0,
                          notes="Lab duplicate/MSD RPD typical ≤30%")
        # MS/LFSM
        return QCRule(70.0, 130.0, verify_against_method=True,
                      notes="MS recovery per-analyte (1633A) — verify")

    def calibration_rule(self, analyte="") -> CalibrationRule:
        return CalibrationRule(r2_min=0.99, point_pct_dev_max=30.0,
                               low_point_pct_dev_max=50.0,
                               default_fit="linear",
                               default_weighting="1/x")

    def ccv_rule(self) -> CCVRule:
        return CCVRule(70.0, 130.0, frequency=10)

    def is_rule(self) -> ISRule:
        # NIS (injection IS) typically 50–150% of ICAL average;
        # EIS handled per-analyte through qc_rules(qc_type="EIS")
        return ISRule(vs_ical_avg_min=50.0, vs_ical_avg_max=150.0,
                      notes="NIS screen; EIS uses per-analyte limits")

    def confirmation_rule(self) -> ConfirmationRule:
        return ConfirmationRule(ion_ratio_tol_pct=50.0,
                                sn_min_quant=3.0, sn_min_confirm=1.0,
                                notes="Ion-ratio window wider in 1633A "
                                      "(50–150% of expected typical)")

    def sequence_rule(self) -> SequenceRule:
        return SequenceRule(ccv_frequency=10, closing_ccv=True)


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_PROFILES: dict[str, MethodProfile] = {
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


def get_profile(method: str) -> MethodProfile:
    key = method.strip().upper().replace(" ", "")
    key = _ALIASES.get(key, key)
    # normalise to registry casing
    for pid, prof in _PROFILES.items():
        if pid.upper() == key:
            return prof
    raise KeyError(
        f"Unknown method profile {method!r}; available: "
        f"{sorted(_PROFILES)} (aliases: {sorted(_ALIASES)})")


def available_profiles() -> dict[str, str]:
    return {pid: p.description for pid, p in _PROFILES.items()}
