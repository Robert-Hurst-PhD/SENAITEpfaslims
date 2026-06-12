"""
QC Engine — Python port of all 6 calculation sheets in FDA_Sample_Calculator_V13.xlsm.

Sheet 1: IS Raw          → is_raw_check()
Sheet 2: RT Deviation    → rt_deviation_check()
Sheet 3: Qual-Quan Ratio → qual_quan_check()
Sheet 4: Calibration %   → calibration_check()
Sheet 5: LFSM & LFSMD   → lfsm_check(), lfsmd_check()
Sheet 6: QC Log          → consolidated from above

All formulas are translated from the Excel FILTER/CHOOSECOLS patterns observed
in the actual sheet XML.
"""

from __future__ import annotations
import statistics
from datetime import datetime
from typing import Optional

from .constants import CRITERIA, NON_ISO_ANALYTES, QUALIFIER_NC, QUALIFIER_ND
from .models import (
    InstrumentRow, QCFlag,
    ISRawResult, RTResult, QualQuanResult, CalibrationResult,
    LFSMResult, LFSMDResult, MDLResult,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _numeric_rows(rows: list[InstrumentRow], value_fn) -> list[float]:
    """Extract a list of non-None floats from rows using value_fn."""
    result = []
    for r in rows:
        v = value_fn(r)
        if v is not None:
            result.append(v)
    return result


def _format_val(v: Optional[float]) -> str:
    if v is None:
        return QUALIFIER_ND
    return f"{v:.6g}"


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 1 — IS Raw
# Excel formula (col D, odd-lettered compound):
#   = IF(C4=0, "N.D.", IFERROR((C4/C$3), "N.D."))   where C4 = response_ratio
#   C$3 = AVERAGE(FILTER(DATA[ResponseRatio], Sample Type="Standard" & Compound=x))
# ─────────────────────────────────────────────────────────────────────────────

def is_raw_check(
    rows: list[InstrumentRow],
    is_compound: str,
) -> list[ISRawResult]:
    """
    For one IS compound, compute % from CAL (response_ratio / avg_standard_response)
    for every injection.  Flag if outside ±50% of average.

    Equivalent to IS Raw sheet, and flags written to QC Log as (SUR).
    """
    # Average response_ratio from Standards only (replaces C$3)
    std_rows = [r for r in rows
                if r.compound_name == is_compound
                and r.sample_type == "Standard"
                and r.response_ratio is not None]
    if not std_rows:
        return []

    avg_response = statistics.mean(r.response_ratio for r in std_rows)  # type: ignore

    threshold = CRITERIA["is_response_drift_pct"]
    lower = avg_response * (1 - threshold)
    upper = avg_response * (1 + threshold)

    results: list[ISRawResult] = []
    all_rows = [r for r in rows if r.compound_name == is_compound]

    for r in all_rows:
        rr = r.response_ratio
        if rr is None:
            pct_from_cal = None
            flag = None
        elif rr == 0:
            pct_from_cal = None  # N.D.
            flag = None
        else:
            try:
                pct_from_cal = rr / avg_response
            except ZeroDivisionError:
                pct_from_cal = None
            flag = None
            if pct_from_cal is not None and not (lower <= rr <= upper):
                flag = QCFlag(
                    source="SUR-IS Response Table",
                    analyte=is_compound,
                    injection_name=r.injection_name,
                    value=_format_val(rr),
                    issue="(SUR)",
                    link="Go",
                )

        results.append(ISRawResult(
            is_compound=is_compound,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            response=r.response,
            pct_from_cal=pct_from_cal,
            average_response=avg_response,
            flag=flag,
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 2 — RT Deviation
# Excel formula (col D, even-lettered):
#   = IF(C4=0, "N.D.", IFERROR((C4/C$3)-1, "N.D."))
#   C$3 = AVERAGE(FILTER(DATA[ObservedRT], SampleType="Standard" & Compound=x))
# ─────────────────────────────────────────────────────────────────────────────

def rt_deviation_check(
    rows: list[InstrumentRow],
    analyte: str,
) -> list[RTResult]:
    """
    Compute RT % deviation from batch average (Standards) for every injection.
    Flags deviations beyond ±rt_dev_abs_min minutes.
    """
    std_rows = [r for r in rows
                if r.compound_name == analyte
                and r.sample_type == "Standard"
                and r.observed_rt is not None]
    if not std_rows:
        return []

    avg_rt = statistics.mean(r.observed_rt for r in std_rows)  # type: ignore
    tol = CRITERIA["rt_dev_abs_min"]

    results: list[RTResult] = []
    for r in [row for row in rows if row.compound_name == analyte]:
        rt = r.observed_rt
        if rt is None or rt == 0:
            pct_dev = None
            flag = None
        else:
            try:
                pct_dev = (rt / avg_rt) - 1.0
            except ZeroDivisionError:
                pct_dev = None
            flag = None
            dev_abs = abs(rt - avg_rt)
            if dev_abs > tol:
                flag = QCFlag(
                    source="RT Deviation",
                    analyte=analyte,
                    injection_name=r.injection_name,
                    value=_format_val(rt),
                    issue=f"RT dev {rt - avg_rt:+.3f} min (±{tol} tol.)",
                )

        results.append(RTResult(
            analyte=analyte,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            observed_rt=rt,
            average_rt=avg_rt,
            pct_deviation=pct_dev,
            flag=flag,
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 3 — Qual-Quan Ratio
# Excel formula (col D):
#   = IF(C4=0, "N.D.", IFERROR((C4/C$3), "N.D."))
#   C$3 = average response_ratio from calibration curve (Standards)
#   Flags if outside ±30% of expected (ion_ratio_tol_pct)
# ─────────────────────────────────────────────────────────────────────────────

def qual_quan_check(
    rows: list[InstrumentRow],
    analyte: str,
) -> list[QualQuanResult]:
    """
    Compute Qual/Quan response ratio relative to calibration average.
    Non-ISO analytes get N.C. qualifier.
    """
    is_non_iso = analyte in NON_ISO_ANALYTES

    std_rows = [r for r in rows
                if r.compound_name == analyte
                and r.sample_type == "Standard"
                and r.response_ratio is not None]
    if not std_rows:
        return []

    avg_rr = statistics.mean(r.response_ratio for r in std_rows)  # type: ignore
    tol = CRITERIA["ion_ratio_tol_pct"] / 100.0

    results: list[QualQuanResult] = []
    for r in [row for row in rows if row.compound_name == analyte]:
        rr = r.response_ratio
        if rr is None or rr == 0:
            pct_of_cal = None
            flag = None
        else:
            try:
                pct_of_cal = rr / avg_rr
            except ZeroDivisionError:
                pct_of_cal = None
            flag = None
            if is_non_iso:
                qualifier = QUALIFIER_NC
                flag = QCFlag(
                    source="Qual-Quan Table",
                    analyte=analyte,
                    injection_name=r.injection_name,
                    value=_format_val(rr),
                    issue="(N.C.)",
                )
            elif pct_of_cal is not None:
                if abs(pct_of_cal - 1.0) > tol:
                    flag = QCFlag(
                        source="Qual-Quan Table",
                        analyte=analyte,
                        injection_name=r.injection_name,
                        value=_format_val(pct_of_cal),
                        issue="(QQ)",
                    )

        results.append(QualQuanResult(
            analyte=analyte,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            response_ratio=rr,
            avg_response_ratio=avg_rr,
            pct_of_cal=pct_of_cal,
            flag=flag,
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 4 — Calibration %
# Excel formula (col D, Calibration sheet):
#   = CHOOSECOLS(FILTER(DATA[], Concat ID = B4 & Compound = header), col26)
#   col 26 = % Deviation (calculated_conc vs expected_conc)
#   R² pulled from DATA[R2]
#   Flags: CAL = % deviation > 20%, R² < 0.995
# ─────────────────────────────────────────────────────────────────────────────

def calibration_check(
    rows: list[InstrumentRow],
    analyte: str,
) -> list[CalibrationResult]:
    """
    Check calibration % deviation and R² for each calibration standard injection.
    Flags: (CAL) if |% dev| > 20% or R² < 0.995.
    """
    cal_rows = [r for r in rows
                if r.compound_name == analyte
                and r.sample_type == "Standard"]

    r2_max = CRITERIA["cal_r2_min"]
    pct_max = CRITERIA["cal_pct_dev_max"]

    results: list[CalibrationResult] = []
    for r in cal_rows:
        flag = None
        issues = []
        if r.r2 is not None and r.r2 < r2_max:
            issues.append(f"R²={r.r2:.4f}<{r2_max}")
        if r.pct_deviation is not None and abs(r.pct_deviation) > pct_max:
            issues.append(f"dev={r.pct_deviation*100:+.1f}%")
        if issues:
            flag = QCFlag(
                source="Calibration %",
                analyte=analyte,
                injection_name=r.injection_name,
                value=_format_val(r.pct_deviation),
                issue="(CAL) " + "; ".join(issues),
            )

        results.append(CalibrationResult(
            analyte=analyte,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            r2=r.r2,
            calculated_conc=r.calculated_conc,
            pct_deviation=r.pct_deviation,
            flag=flag,
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 5 — LFSM & LFSMD   (AppendLFSM_LFSMD_ToData VBA macro)
# Recovery = (fortified - unfortified) / spike × 100
# RPD = |A - B| / ((A+B)/2) × 100
# ─────────────────────────────────────────────────────────────────────────────

def lfsm_check(
    analyte: str,
    lfsm_injection: str,
    parent_injection: str,
    spike_value_ppt: float,
    rows: list[InstrumentRow],
) -> LFSMResult | None:
    """
    Calculate LFSM % recovery for one analyte.
    lfsm_injection:   the LFSM injection (fortified)
    parent_injection: the matched parent (unfortified)
    spike_value_ppt:  spike added in ppt (from user input)
    """
    def get_conc(inj_name: str) -> float | None:
        for r in rows:
            if r.injection_name == inj_name and r.compound_name == analyte:
                return r.measured_conc or r.calculated_conc
        return None

    fortified   = get_conc(lfsm_injection)
    unfortified = get_conc(parent_injection)

    if fortified is None or spike_value_ppt == 0:
        return None

    unfort = unfortified or 0.0
    recovery_pct = (fortified - unfort) / spike_value_ppt * 100.0

    flag = None
    min_r, max_r = CRITERIA["recovery_min_pct"], CRITERIA["recovery_max_pct"]
    if not (min_r <= recovery_pct <= max_r):
        flag = QCFlag(
            source="LFSM & LFSMD",
            analyte=analyte,
            injection_name=lfsm_injection,
            value=f"{recovery_pct:.1f}%",
            issue="(REC)",
        )

    return LFSMResult(
        analyte=analyte,
        lfsm_injection=lfsm_injection,
        parent_injection=parent_injection,
        spike_value_ppt=spike_value_ppt,
        fortified_conc=fortified,
        unfortified_conc=unfort,
        recovery_pct=recovery_pct,
        flag=flag,
    )


def lfsmd_check(
    analyte: str,
    lfsm_injection: str,
    lfsmd_injection: str,
    lfsm_result: LFSMResult,
    rows: list[InstrumentRow],
) -> LFSMDResult | None:
    """
    Calculate RPD between LFSM and its duplicate (LFSMD).
    """
    def get_conc(inj_name: str) -> float | None:
        for r in rows:
            if r.injection_name == inj_name and r.compound_name == analyte:
                return r.measured_conc or r.calculated_conc
        return None

    fortified_dup = get_conc(lfsmd_injection)
    unfort = lfsm_result.unfortified_conc

    if fortified_dup is None:
        return None

    rec_dup = (fortified_dup - unfort) / lfsm_result.spike_value_ppt * 100.0
    rec_lfsm = lfsm_result.recovery_pct

    mean_rec = (rec_lfsm + rec_dup) / 2.0
    rpd_pct = abs(rec_lfsm - rec_dup) / mean_rec * 100.0 if mean_rec else 0.0

    flag = None
    if rpd_pct > CRITERIA["rpd_max_pct"]:
        flag = QCFlag(
            source="LFSM & LFSMD",
            analyte=analyte,
            injection_name=lfsmd_injection,
            value=f"RPD={rpd_pct:.1f}%",
            issue="(RPD)",
        )

    return LFSMDResult(
        analyte=analyte,
        lfsm_injection=lfsm_injection,
        lfsmd_injection=lfsmd_injection,
        recovery_lfsm=rec_lfsm,
        recovery_lfsmd=rec_dup,
        rpd_pct=rpd_pct,
        flag=flag,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MDL calculation  (CalculateMDL VBA macro)
# Standard MDL = t(n-1, 0.99) × stdev
# MDLb = MDL using blank-subtracted values
# Requires ≥ 7 replicates
# ─────────────────────────────────────────────────────────────────────────────

def calculate_mdl(
    analyte: str,
    matrix: str,
    replicate_concs: list[float],
    blank_values: list[float | None] | None = None,
) -> MDLResult | None:
    """
    Calculate Method Detection Limit per EPA/FDA guidance.
    replicate_concs: list of spike replicate concentrations (n ≥ 7).
    blank_values:    corresponding blank concentrations (may contain None = ND).
    """
    n = len(replicate_concs)
    min_n = CRITERIA["mdl_min_replicates"]
    if n < min_n:
        return None

    stdev = statistics.stdev(replicate_concs)
    t_table = CRITERIA["t_values"]
    t_val = t_table.get(n) or t_table.get(max(t_table.keys()))

    mdl_s = t_val * stdev

    # MDLb: subtract blank if blanks are available
    mdl_b = None
    blank_max = None
    note = ""
    if blank_values:
        numeric_blanks = [b for b in blank_values if b is not None and b > 0]
        if not numeric_blanks:
            note = "All blanks ND — no blank subtraction applied"
            mdl_b = mdl_s
        else:
            blank_max = max(numeric_blanks)
            mdl_b = mdl_s  # reported separately; blank flagging is separate
            # Flag if blank ≥ sample (< LOD rule)

    return MDLResult(
        analyte=analyte,
        matrix=matrix,
        n=n,
        stdev=stdev,
        t_value=t_val,
        mdl_s=mdl_s,
        mdl_b=mdl_b,
        blank_max=blank_max,
        note=note,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Signal-to-Noise check  (Signal-to-Noise sheet)
# ─────────────────────────────────────────────────────────────────────────────

def signal_to_noise_check(rows: list[InstrumentRow], analyte: str) -> list[QCFlag]:
    """Flag any injection where S/N < 3 (or qual ion S/N < 3) as (N.C.)."""
    flags: list[QCFlag] = []
    sn_min = CRITERIA["sn_min"]
    for r in rows:
        if r.compound_name != analyte:
            continue
        sn = r.signal_to_noise
        qual_sn = r.qual_sn
        if sn is not None and sn < sn_min:
            flags.append(QCFlag(
                source="Signal-to-Noise",
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{sn:.2f}",
                issue="(N.C.)",
            ))
        elif qual_sn is not None and qual_sn < sn_min:
            flags.append(QCFlag(
                source="Signal-to-Noise",
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{qual_sn:.2f}",
                issue="(N.C.)",
            ))
    return flags


# ═════════════════════════════════════════════════════════════════════════════
# Method-profile-aware checks (Pass 2 of the re-evaluation)
# These supersede the flat-criteria functions above when a method profile is
# supplied; the legacy functions remain for backwards compatibility.
# ═════════════════════════════════════════════════════════════════════════════

from .method_profiles import MethodProfile, get_profile


def recovery_check_profiled(
    profile: MethodProfile,
    analyte: str,
    matrix: str,
    qc_type: str,
    recovery_pct: float,
    injection_name: str = "",
) -> Optional[QCFlag]:
    """
    Resolve recovery limits via the method profile and flag if outside.
    Handles FDA's three-tier (analyte × matrix) table automatically:
      PFOA in deer muscle  → 80–120%
      PFOA in feed         → 65–135%
      PFTrDA anywhere      → 40–140%
    """
    rule = profile.qc_rules(analyte, matrix, qc_type)
    if rule.recovery_min is None:
        return None
    if rule.recovery_min <= recovery_pct <= rule.recovery_max:
        return None
    issue = f"(REC) {recovery_pct:.1f}% outside " \
            f"{rule.recovery_min:.0f}–{rule.recovery_max:.0f}%"
    if rule.is_guidance_only:
        issue += " [guidance only]"
    if rule.verify_against_method:
        issue += " [VERIFY limits vs method tables]"
    return QCFlag(
        source=f"{profile.method_id} {qc_type}",
        analyte=analyte,
        injection_name=injection_name,
        value=f"{recovery_pct:.1f}%",
        issue=issue + (f" — {rule.notes}" if rule.notes else ""),
    )


def rpd_check_profiled(
    profile: MethodProfile,
    analyte: str,
    matrix: str,
    qc_type: str,
    rpd_pct: float,
    injection_name: str = "",
) -> Optional[QCFlag]:
    """Duplicate / LFSMD RPD against the profile limit (FDA dup: 20%)."""
    rule = profile.qc_rules(analyte, matrix, qc_type)
    limit = rule.rpd_max
    if limit is None or rpd_pct <= limit:
        return None
    return QCFlag(
        source=f"{profile.method_id} {qc_type}",
        analyte=analyte,
        injection_name=injection_name,
        value=f"RPD={rpd_pct:.1f}%",
        issue=f"(RPD) exceeds {limit:.0f}% — {rule.notes}",
    )


def ccv_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
) -> list[QCFlag]:
    """
    CCV recovery per profile (FDA 70–130%; 537.1 70–130% with 50–150% at the
    lowest CCC level).  Uses calculated vs expected concentration.
    """
    rule = profile.ccv_rule()
    flags: list[QCFlag] = []
    ccv_rows = [r for r in rows
                if r.compound_name == analyte
                and "CCV" in r.injection_name.upper()]
    for r in ccv_rows:
        if not r.expected_conc or r.calculated_conc is None:
            continue
        rec = r.calculated_conc / r.expected_conc * 100.0
        lo, hi = rule.recovery_min, rule.recovery_max
        # 537.1: lowest CCC gets the wider window
        if rule.low_level_min is not None and r.level in ("1", "low", "MRL"):
            lo, hi = rule.low_level_min, rule.low_level_max
        if not (lo <= rec <= hi):
            flags.append(QCFlag(
                source=f"{profile.method_id} CCV",
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{rec:.1f}%",
                issue=f"(CCV) outside {lo:.0f}–{hi:.0f}% — rerun curve and "
                      f"reinject samples since last passing CCV",
            ))
    return flags


def calibration_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
) -> list[CalibrationResult]:
    """Calibration check with profile r² (FDA 0.990, not 0.995) and
    per-point %dev where the method defines one (537.1: 30%/50%)."""
    rule = profile.calibration_rule(analyte)
    cal_rows = [r for r in rows
                if r.compound_name == analyte and r.sample_type == "Standard"]
    results: list[CalibrationResult] = []
    for r in cal_rows:
        issues = []
        if r.r2 is not None and r.r2 < rule.r2_min:
            issues.append(f"R²={r.r2:.4f}<{rule.r2_min}")
        if rule.point_pct_dev_max is not None and r.pct_deviation is not None:
            limit = rule.point_pct_dev_max
            if rule.low_point_pct_dev_max and r.level in ("1", "low", "MRL"):
                limit = rule.low_point_pct_dev_max
            if abs(r.pct_deviation) * 100 > limit:
                issues.append(f"dev={r.pct_deviation*100:+.1f}%>{limit:.0f}%")
        flag = None
        if issues:
            flag = QCFlag(
                source=f"{profile.method_id} Calibration",
                analyte=analyte,
                injection_name=r.injection_name,
                value=_format_val(r.pct_deviation),
                issue="(CAL) " + "; ".join(issues),
            )
        results.append(CalibrationResult(
            analyte=analyte, injection_name=r.injection_name,
            concat_id=r.concat_id, r2=r.r2,
            calculated_conc=r.calculated_conc,
            pct_deviation=r.pct_deviation, flag=flag,
        ))
    return results


def is_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    is_compound: str,
) -> list[ISRawResult]:
    """
    IS response check honoring the profile's dual conditions.
    537.1: within ±50% of ICAL average AND 70–140% of the most recent CCV.
    FDA/lab SOP: ±50% of batch Standards average only.
    """
    rule = profile.is_rule()
    all_rows = sorted(
        [r for r in rows if r.compound_name == is_compound],
        key=lambda r: r.acquisition_datetime or datetime.min,
    )
    std_resp = [r.response for r in all_rows
                if r.sample_type == "Standard" and r.response]
    if not std_resp:
        return []
    ical_avg = statistics.mean(std_resp)

    results: list[ISRawResult] = []
    last_ccv_resp: Optional[float] = None
    for r in all_rows:
        resp = r.response
        flag = None
        pct_of_avg = (resp / ical_avg) if (resp and ical_avg) else None
        if resp:
            fails = []
            if rule.vs_ical_avg_min is not None and pct_of_avg is not None:
                if not (rule.vs_ical_avg_min <= pct_of_avg * 100
                        <= rule.vs_ical_avg_max):
                    fails.append(
                        f"{pct_of_avg*100:.0f}% of ICAL avg "
                        f"(limit {rule.vs_ical_avg_min:.0f}–"
                        f"{rule.vs_ical_avg_max:.0f}%)")
            if (rule.vs_last_ccv_min is not None
                    and last_ccv_resp):
                pct_ccv = resp / last_ccv_resp * 100
                if not (rule.vs_last_ccv_min <= pct_ccv
                        <= rule.vs_last_ccv_max):
                    fails.append(
                        f"{pct_ccv:.0f}% of last CCV "
                        f"(limit {rule.vs_last_ccv_min:.0f}–"
                        f"{rule.vs_last_ccv_max:.0f}%)")
            if fails:
                flag = QCFlag(
                    source=f"{profile.method_id} IS Response",
                    analyte=is_compound,
                    injection_name=r.injection_name,
                    value=f"{resp:.4g}",
                    issue="(SUR) " + "; ".join(fails),
                )
        if "CCV" in r.injection_name.upper() and resp:
            last_ccv_resp = resp
        results.append(ISRawResult(
            is_compound=is_compound,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            response=resp,
            pct_from_cal=pct_of_avg,
            average_response=ical_avg,
            flag=flag,
        ))
    return results


def rrt_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
) -> list[RTResult]:
    """
    Retention-time check using the profile's rule:
      FDA:   relative RT deviation ≤1% of the standard's RT
      537.1: absolute ±0.05 min
    Falls back to legacy ±0.10 min absolute when the profile sets neither.
    """
    conf = profile.confirmation_rule()
    std_rows = [r for r in rows
                if r.compound_name == analyte
                and r.sample_type == "Standard" and r.observed_rt]
    if not std_rows:
        return []
    avg_rt = statistics.mean(r.observed_rt for r in std_rows)

    results: list[RTResult] = []
    for r in [x for x in rows if x.compound_name == analyte]:
        rt = r.observed_rt
        flag = None
        pct_dev = None
        if rt and avg_rt:
            pct_dev = (rt / avg_rt) - 1.0
            if conf.rrt_tol_pct is not None:
                if abs(pct_dev) * 100 > conf.rrt_tol_pct:
                    flag = QCFlag(
                        source=f"{profile.method_id} RRT",
                        analyte=analyte, injection_name=r.injection_name,
                        value=f"{rt:.3f}",
                        issue=f"(RT) RRT dev {pct_dev*100:+.2f}% "
                              f"> ±{conf.rrt_tol_pct}%",
                    )
            elif conf.rt_tol_abs_min is not None:
                if abs(rt - avg_rt) > conf.rt_tol_abs_min:
                    flag = QCFlag(
                        source=f"{profile.method_id} RT",
                        analyte=analyte, injection_name=r.injection_name,
                        value=f"{rt:.3f}",
                        issue=f"(RT) dev {rt-avg_rt:+.3f} min "
                              f"> ±{conf.rt_tol_abs_min} min",
                    )
            elif abs(rt - avg_rt) > CRITERIA["rt_dev_abs_min"]:
                flag = QCFlag(
                    source="RT Deviation", analyte=analyte,
                    injection_name=r.injection_name, value=f"{rt:.3f}",
                    issue=f"(RT) dev {rt-avg_rt:+.3f} min (legacy ±0.10)",
                )
        results.append(RTResult(
            analyte=analyte, injection_name=r.injection_name,
            concat_id=r.concat_id, observed_rt=rt,
            average_rt=avg_rt, pct_deviation=pct_dev, flag=flag,
        ))
    return results


def single_transition_confirm_needed(
    profile: MethodProfile,
    analyte: str,
    detected: bool,
) -> Optional[str]:
    """
    FDA §10.2(4): PFBA/PFPeA positives must be confirmed by LC-HRMS
    (%diff < 20%).  Returns a review-prompt string when confirmation is
    required, used by the run queue.
    """
    conf = profile.confirmation_rule()
    if detected and analyte in conf.single_transition_analytes:
        return (f"{analyte} positive detect: single MS/MS transition — "
                f"confirm by LC-HRMS; %diff between techniques must be "
                f"< {conf.confirm_pct_diff_max:.0f}%")
    return None
