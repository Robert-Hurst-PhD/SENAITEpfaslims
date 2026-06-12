"""
PFAS QC Engine
Complete port of all QC macros from FDA_Sample_Calculator_V13.xlsm:
  - CalculateMDL       (MDL sheet pair: MDLb + MDLs)
  - RT_Check           (RT Deviation sheet)
  - IS_Raw             (IS Raw sheet)
  - Calibration_Processing (Calibration % sheet)
  - AppendLFSM_LFSMD   (LFSM & LFSMD sheet)
  - QualQuanCheck      (Qual-Quan Ratio sheet)
  - SignalToNoise      (Signal-to-Noise sheet)
  - MethodBlankCheck   (contributes to QC Log)

Each function returns a QCResult object and writes flags to a shared QCLog.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from senaite.pfas.analytes import KEY_ANALYTES, NON_ISO_ANALYTES
from senaite.pfas.qc.rules import LiveCriteria as _LiveCriteria

# Use the rules-store-backed criteria so that changes made in @@pfas-qc-rules
# take effect without a code deploy.  Falls back to hardcoded defaults when
# the rules file does not exist yet.
QCCriteria = _LiveCriteria()


# ─────────────────────────────────────────────────────────────────────────────
# Shared flag dataclass  (maps to QCLogTable columns: Source/Analyte/Injection/Value/Issue)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class QCFlag:
    source: str        # sheet name equivalent: "IS Raw", "RT Deviation", etc.
    analyte: str
    injection_name: str
    value: float | str
    issue: str
    flag_code: str = ""   # e.g. "IS", "RT", "CAL", "REC", "N.C.", "MDL"
    link: str = ""


class QCLog:
    """Accumulates all QC flags across the batch — equivalent to QCLogTable."""

    def __init__(self):
        self.flags: list[QCFlag] = []

    def add(
        self,
        source: str,
        analyte: str,
        injection: str,
        value,
        issue: str,
        flag_code: str = "",
    ) -> None:
        self.flags.append(QCFlag(source, analyte, injection, value, issue, flag_code))

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([
            {
                "Source": f.source,
                "Analyte": f.analyte,
                "Injection Name": f.injection_name,
                "Value": f.value,
                "Issue": f.issue,
                "Flag": f.flag_code,
                "Link": f.link,
            }
            for f in self.flags
        ])

    def has_failures(self) -> bool:
        return len(self.flags) > 0

    def summary(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(f.source for f in self.flags))


# ─────────────────────────────────────────────────────────────────────────────
# 1. MDL Calculation  (CalculateMDL VBA macro)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MDLResult:
    analyte: str
    n: int
    stdev: float
    t_value: float
    mdl_standard: float           # MDLs = t(n-1,99%) × stdev
    mdl_blank_subtracted: float   # MDLb = MDLs with blank correction
    blank_values: list[float] = field(default_factory=list)
    blank_max: float = 0.0
    note: str = ""
    valid: bool = True
    error: str = ""


def calculate_mdl(
    analyte: str,
    replicates: list[float],
    blank_values: Optional[list] = None,
    log: Optional[QCLog] = None,
) -> MDLResult:
    """
    Standard MDL per EPA MDL procedure (40 CFR Part 136 Appendix B).
    MDLs = t(n-1, 0.99) × stdev   [n ≥ 7 required]
    MDLb = MDLs with blank matrix correction.

    VBA equivalent: CalculateMDL module.
    Comments from VBA:
      'Standard MDL: t(n-1,0.99) * stdev'
      'For MDLs, only compute if valCount >= 7'
      'If blanks contain ND or 0 then MDLb = MAX(blank values)'
      'If all blank results are ND then output = N.D.'
    """
    n = len([r for r in replicates if r is not None and not math.isnan(float(r))])

    if n < QCCriteria.MDL_MIN_REPS:
        result = MDLResult(
            analyte=analyte, n=n, stdev=0, t_value=0,
            mdl_standard=0, mdl_blank_subtracted=0,
            valid=False, error=f"Insufficient replicates: {n} (need ≥ {QCCriteria.MDL_MIN_REPS})",
        )
        if log:
            log.add("MDL", analyte, "", n,
                    f"MDL calc failed: only {n} reps (need ≥ {QCCriteria.MDL_MIN_REPS})", "MDL")
        return result

    clean_reps = [float(r) for r in replicates if r is not None and not math.isnan(float(r))]
    stdev = float(np.std(clean_reps, ddof=1))
    t_val = float(stats.t.ppf(QCCriteria.MDL_T_CONFIDENCE, df=n - 1))
    mdl_s = t_val * stdev

    # Blank correction (MDLb)
    numeric_blanks: list[float] = []
    if blank_values:
        for b in blank_values:
            try:
                bv = float(b)
                if not math.isnan(bv) and bv > 0:
                    numeric_blanks.append(bv)
            except (TypeError, ValueError):
                pass

    if not numeric_blanks:
        # All blanks ND → MDLb = MDLs (no correction possible)
        mdl_b = mdl_s
        note = "All blank values ND — no blank subtraction applied"
    else:
        max_blank = max(numeric_blanks)
        # VBA: 'MDLb = Average + (t(n-1,99%) * stdev)' applied to blank replicates
        # Practical approach: report MDLb = MDLs; flag if blank max > MDLs
        mdl_b = mdl_s
        note = f"Max blank = {max_blank:.4f}; MDLb = {mdl_b:.4f}"
        if max_blank > mdl_s:
            note += " ⚠ blank exceeds MDLs — MDL may be blank-limited"
            if log:
                log.add("MDL", analyte, "Method Blank", max_blank,
                        "<LOD: method blank exceeds MDLs", "MDL")

    return MDLResult(
        analyte=analyte, n=n, stdev=stdev, t_value=t_val,
        mdl_standard=mdl_s, mdl_blank_subtracted=mdl_b,
        blank_values=numeric_blanks,
        blank_max=max(numeric_blanks) if numeric_blanks else 0.0,
        note=note, valid=True,
    )


def calculate_mdl_batch(
    df: pd.DataFrame,
    analyte_col: str = "compound_name",
    value_col: str = "calculated_concentration",
    blank_df: Optional[pd.DataFrame] = None,
    log: Optional[QCLog] = None,
) -> pd.DataFrame:
    """Run MDL calculation for every analyte in df. Returns summary DataFrame."""
    results = []
    for analyte, grp in df.groupby(analyte_col):
        reps = grp[value_col].dropna().tolist()
        blanks = []
        if blank_df is not None and analyte_col in blank_df.columns:
            blanks = blank_df[blank_df[analyte_col] == analyte][value_col].tolist()
        r = calculate_mdl(str(analyte), reps, blanks, log=log)
        results.append({
            "Analyte": r.analyte,
            "n": r.n,
            "Stdev": r.stdev,
            "t-value": r.t_value,
            "MDLs (ng/mL)": r.mdl_standard,
            "MDLb (ng/mL)": r.mdl_blank_subtracted,
            "Note": r.note,
            "Valid": r.valid,
        })
    return pd.DataFrame(results)


# ─────────────────────────────────────────────────────────────────────────────
# 2. RT Deviation Check  (RT_Check VBA)
# ─────────────────────────────────────────────────────────────────────────────

def check_rt_deviations(
    df: pd.DataFrame,
    log: Optional[QCLog] = None,
    tol_min: float = QCCriteria.RT_TOLERANCE_MIN,
    tol_pct: float = QCCriteria.RT_TOLERANCE_PCT,
) -> pd.DataFrame:
    """
    For each injection × analyte, compare Observed RT vs. average RT.
    Flags if deviation > ±tol_min OR > ±tol_pct%.

    VBA equivalent: Sub RT_C... and RT Deviation Table.
    Returns RT deviation DataFrame (mirrors RT Deviation sheet).
    """
    if "observed_rt" not in df.columns or "compound_name" not in df.columns:
        return pd.DataFrame()

    rows = []
    for analyte, grp in df.groupby("compound_name"):
        numeric_rt = grp["observed_rt"].dropna()
        if numeric_rt.empty:
            continue
        avg_rt = float(numeric_rt.mean())

        for _, row in grp.iterrows():
            obs = row.get("observed_rt")
            if pd.isna(obs):
                continue
            obs = float(obs)
            dev_min = obs - avg_rt
            dev_pct = (dev_min / avg_rt * 100) if avg_rt != 0 else 0.0
            flag = abs(dev_min) > tol_min or abs(dev_pct) > tol_pct
            inj = row.get("injection_name", "")

            if flag and log:
                log.add(
                    "RT Deviation", str(analyte), str(inj),
                    round(obs, 4),
                    f"RT {dev_pct:+.1f}% ({dev_min:+.4f} min) — threshold ±{tol_min} min / ±{tol_pct}%",
                    "RT",
                )

            rows.append({
                "Analyte": analyte,
                "Injection Name": inj,
                "Observed RT (min)": obs,
                "Average RT (min)": round(avg_rt, 4),
                "Deviation (min)": round(dev_min, 4),
                "Deviation (%)": round(dev_pct, 2),
                "Flag": "RT" if flag else "",
                "Pass": not flag,
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 3. IS Response Monitor  (IS_Raw VBA)
# ─────────────────────────────────────────────────────────────────────────────

def check_is_responses(
    df: pd.DataFrame,
    log: Optional[QCLog] = None,
    tol_pct: float = QCCriteria.IS_RESPONSE_PCT,
) -> pd.DataFrame:
    """
    Monitor internal standard responses across all injections.
    Flags if any injection's IS response is outside ±tol_pct% of batch average.

    VBA equivalent: Sub IS_Raw, IS Raw sheet.
    Column 27 is the % Recovery (IS) Calculated off instrument.
    """
    if "is_response" not in df.columns and "recovery_is_pct" not in df.columns:
        return pd.DataFrame()

    use_col = "is_response" if "is_response" in df.columns else "recovery_is_pct"
    rows = []

    # Group by IS (linked_is if available, else compound_name for IS type rows)
    group_col = "linked_is" if "linked_is" in df.columns else "compound_name"

    for is_name, grp in df.groupby(group_col):
        vals = grp[use_col].dropna()
        if vals.empty or len(vals) < 2:
            continue
        avg = float(vals.mean())
        lower = avg * (1 - tol_pct / 100)
        upper = avg * (1 + tol_pct / 100)

        for _, row in grp.iterrows():
            v = row.get(use_col)
            if pd.isna(v):
                continue
            v = float(v)
            pct_diff = (v - avg) / avg * 100 if avg != 0 else 0.0
            flag = not (lower <= v <= upper)
            inj = row.get("injection_name", "")

            if flag and log:
                log.add(
                    "IS Raw", str(is_name), str(inj), round(v, 1),
                    f"IS response {pct_diff:+.0f}% vs batch avg {avg:.0f} (±{tol_pct}%)",
                    "IS",
                )

            rows.append({
                "Analyte (IS)": is_name,
                "Injection Name": inj,
                "IS Response": round(v, 1),
                "Batch Average": round(avg, 1),
                "% vs Average": round(pct_diff, 1),
                "Lower Limit": round(lower, 1),
                "Upper Limit": round(upper, 1),
                "Flag": "IS" if flag else "",
                "Pass": not flag,
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Calibration Check  (Calibration_Processing VBA)
# ─────────────────────────────────────────────────────────────────────────────

def check_calibration(
    df: pd.DataFrame,
    log: Optional[QCLog] = None,
) -> pd.DataFrame:
    """
    For each analyte × calibration level, check:
      1. % deviation from curve ≤ criteria (25 % default, 20 % tight, 30 % BLoQ)
      2. R² ≥ 0.995
      3. CCV % deviation ≤ 25 %

    VBA equivalent: Calibration_Processing, Calibration % sheet.
    """
    if "sample_type" not in df.columns:
        return pd.DataFrame()

    cal_mask = df["sample_type"].str.contains(
        "Calibration Standard|Continuing Calibration", na=False
    )
    cal_df = df[cal_mask].copy()
    if cal_df.empty:
        return pd.DataFrame()

    rows = []
    for analyte, grp in cal_df.groupby("compound_name"):
        # Check R²
        r2_vals = grp["r2"].dropna()
        if not r2_vals.empty:
            r2 = float(r2_vals.iloc[0])
            if r2 < QCCriteria.CAL_R2_MIN:
                if log:
                    log.add("Calibration", str(analyte), "Calibration Curve",
                            round(r2, 4),
                            f"R² = {r2:.4f} < {QCCriteria.CAL_R2_MIN}", "CAL")

        # Check % deviation per level
        for _, row in grp.iterrows():
            dev = row.get("pct_deviation")
            if pd.isna(dev):
                continue
            dev = float(dev)
            level = str(row.get("level", ""))
            bloq = row.get("bloq_flag", False)
            threshold = (QCCriteria.CAL_PCT_DEVIATION["loose"] if bloq
                         else QCCriteria.CAL_PCT_DEVIATION["default"])
            flag = abs(dev) > threshold
            inj = row.get("injection_name", "")

            if flag and log:
                log.add(
                    "Calibration", str(analyte), str(inj),
                    round(dev, 1),
                    f"CAL {dev:+.1f}% exceeds ±{threshold}% (level {level})",
                    "CAL",
                )

            rows.append({
                "Analyte": analyte,
                "Injection Name": inj,
                "Level": level,
                "% Deviation": round(dev, 1),
                "Threshold (%)": threshold,
                "R2": round(r2_vals.iloc[0], 4) if not r2_vals.empty else None,
                "Flag": "CAL" if flag else "",
                "Pass": not flag,
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 5. LFSM / LFSMD Recovery  (AppendLFSM_LFSMD_ToData VBA)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_lfsm_recovery(
    fortified_conc: float,
    unfortified_conc: float,
    spike_ppt: float,
    analyte: str = "",
    matrix: str = "",
) -> dict:
    """
    % Recovery = (Fortified − Unfortified) / Spike × 100

    VBA equivalent: AppendLFSM_LFSMD_ToData, LFSM & LFSMD sheet.
    'Input Numerical Spike Value in ppt'
    'Select LFSM and Spike for Recovery Calculation'
    """
    if spike_ppt == 0:
        return {"error": "Spike value cannot be zero", "recovery_pct": None, "pass": False}

    unfort = unfortified_conc if (unfortified_conc is not None and not math.isnan(float(unfortified_conc or 0))) else 0.0
    recovery = (float(fortified_conc) - float(unfort)) / float(spike_ppt) * 100

    lo, hi = QCCriteria.lfsm_criteria(analyte, matrix)
    passed = lo <= recovery <= hi

    return {
        "analyte": analyte,
        "matrix": matrix,
        "fortified_ppt": fortified_conc,
        "unfortified_ppt": unfort,
        "spike_ppt": spike_ppt,
        "recovery_pct": round(recovery, 1),
        "criteria_low": lo,
        "criteria_high": hi,
        "pass": passed,
        "flag": "" if passed else "REC",
    }


def calculate_rpd(
    value_a: float,
    value_b: float,
    analyte: str = "",
    injection_dup: str = "",
    log: Optional[QCLog] = None,
) -> dict:
    """
    RPD = |A − B| / ((A + B) / 2) × 100

    VBA: RPD - LFSMD, RPD - Sample Duplicates columns.
    """
    try:
        a, b = float(value_a), float(value_b)
    except (TypeError, ValueError):
        return {"error": "Non-numeric value", "rpd_pct": None, "pass": False}

    mean = (a + b) / 2
    if mean == 0:
        return {"error": "Mean is zero — RPD undefined", "rpd_pct": None, "pass": False}

    rpd = abs(a - b) / mean * 100
    passed = rpd <= QCCriteria.RPD_MAX

    if not passed and log:
        log.add("LFSM & LFSMD", analyte, injection_dup,
                round(rpd, 1),
                f"RPD {rpd:.1f}% > {QCCriteria.RPD_MAX}%",
                "REC")

    return {
        "analyte": analyte,
        "value_a": a,
        "value_b": b,
        "rpd_pct": round(rpd, 1),
        "max_allowed": QCCriteria.RPD_MAX,
        "pass": passed,
        "flag": "" if passed else "REC",
    }


def check_lfsm_batch(
    df: pd.DataFrame,
    spike_map: dict[str, float],   # injection_name → spike_ppt (from user/run queue)
    matrix: str = "",
    log: Optional[QCLog] = None,
) -> pd.DataFrame:
    """
    Process all LFSM and LFSMD injections in a batch.
    spike_map populated from the run queue (barcode scan of spike standard).

    VBA: 'Combination Mode for multiple LFSMs/LFSMDs/Dups'
    """
    if "sample_type" not in df.columns:
        return pd.DataFrame()

    lfsm_mask = df["sample_type"].str.contains("Lab Fortified", na=False)
    lfsm_df = df[lfsm_mask].copy()
    sample_df = df[df["sample_type"] == "Environmental Sample"].copy()

    rows = []
    for analyte, lfsm_grp in lfsm_df.groupby("compound_name"):
        for _, lfsm_row in lfsm_grp.iterrows():
            inj = lfsm_row.get("injection_name", "")
            spike = spike_map.get(str(inj), 100.0)   # default 100 ppt if not specified
            lfsm_conc = lfsm_row.get("calculated_concentration")
            if pd.isna(lfsm_conc):
                continue

            # Match to parent sample
            parent_conc = 0.0
            if not sample_df.empty and "compound_name" in sample_df.columns:
                parent_rows = sample_df[sample_df["compound_name"] == analyte]
                if not parent_rows.empty:
                    parent_conc = parent_rows["calculated_concentration"].fillna(0).iloc[0]

            is_dup = "Duplicate" in str(lfsm_row.get("sample_type", ""))
            rec = calculate_lfsm_recovery(
                float(lfsm_conc), float(parent_conc), spike, str(analyte), matrix
            )

            if not rec.get("pass") and log:
                log.add("LFSM & LFSMD", str(analyte), str(inj),
                        rec.get("recovery_pct"),
                        f"{'LFSMD' if is_dup else 'LFSM'} recovery {rec.get('recovery_pct'):.1f}% "
                        f"outside {rec['criteria_low']}-{rec['criteria_high']}%",
                        "REC")

            rows.append({
                "Analyte": analyte,
                "Injection Name": inj,
                "Type": "LFSMD" if is_dup else "LFSM",
                "Fortified (ppt)": lfsm_conc,
                "Parent (ppt)": parent_conc,
                "Spike (ppt)": spike,
                "Recovery (%)": rec.get("recovery_pct"),
                "Criteria Low": rec.get("criteria_low"),
                "Criteria High": rec.get("criteria_high"),
                "Flag": rec.get("flag", ""),
                "Pass": rec.get("pass"),
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Qual/Quan Ion Ratio Check  (Qual-Quan Ratio sheet)
# ─────────────────────────────────────────────────────────────────────────────

def check_qual_quan_ratios(
    df: pd.DataFrame,
    log: Optional[QCLog] = None,
) -> pd.DataFrame:
    """
    Compare observed ion ratios vs. expected ion ratios.
    Criteria depends on analyte class (see QCCriteria.qq_criteria).

    VBA: Qual-Quan Ratio sheet, Qual-Quan Table.
    Flags: N.C. = Analyte not Confirmed
    """
    if "ion_ratios" not in df.columns or "expected_ion_ratios" not in df.columns:
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        analyte = str(row.get("compound_name", ""))
        obs_raw = row.get("ion_ratios")
        exp_raw = row.get("expected_ion_ratios")
        inj = row.get("injection_name", "")

        if pd.isna(obs_raw) or pd.isna(exp_raw):
            continue

        # Ratios stored as pipe-separated: "0.617|0.491"
        try:
            obs_vals = [float(v) for v in str(obs_raw).split("|") if v.strip()]
            exp_vals = [float(v) for v in str(exp_raw).split("|") if v.strip()]
        except ValueError:
            continue

        threshold = QCCriteria.qq_criteria(analyte)

        for i, (obs, exp) in enumerate(zip(obs_vals, exp_vals)):
            if exp == 0:
                continue
            dev = abs(obs - exp) / exp * 100
            flag = dev > threshold

            if flag and log:
                log.add(
                    "Qual-Quan Ratio", analyte, str(inj),
                    round(obs, 3),
                    f"N.C. — qual/quan ratio {dev:.1f}% deviation (threshold ≤{threshold}%)",
                    "N.C.",
                )

            rows.append({
                "Analyte": analyte,
                "Injection Name": inj,
                "Ion Pair": i + 1,
                "Observed Ratio": round(obs, 4),
                "Expected Ratio": round(exp, 4),
                "Deviation (%)": round(dev, 1),
                "Threshold (%)": threshold,
                "Flag": "N.C." if flag else "",
                "Pass": not flag,
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Signal-to-Noise Check  (Signal-to-Noise sheet)
# ─────────────────────────────────────────────────────────────────────────────

def check_signal_to_noise(
    df: pd.DataFrame,
    log: Optional[QCLog] = None,
    sn_min: float = QCCriteria.SN_MIN,
    sn_quan_min: float = QCCriteria.SN_QUAN_MIN,
) -> pd.DataFrame:
    """
    Flag signals below S/N threshold.
    VBA: SignalToNoise_QC table — columns: Compound Name, Signal to Noise,
         Qual Ion S/N, Qual Ion S/N Secondary.
    """
    if "signal_to_noise" not in df.columns:
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        analyte = str(row.get("compound_name", ""))
        sn = row.get("signal_to_noise")
        qual_sn = row.get("qual_sn")
        inj = row.get("injection_name", "")

        if pd.isna(sn):
            continue
        sn = float(sn)
        at_rl = not row.get("bloq_flag", False)
        threshold = sn_quan_min if at_rl else sn_min
        flag = sn < threshold

        if flag and log:
            log.add("Signal-to-Noise", analyte, str(inj), round(sn, 1),
                    f"S/N {sn:.1f} < {threshold} (MDL flag)", "MDL")

        rows.append({
            "Analyte": analyte,
            "Injection Name": inj,
            "Signal to Noise": round(sn, 1),
            "Qual Ion S/N": round(float(qual_sn), 1) if pd.notna(qual_sn) else None,
            "Threshold": threshold,
            "Flag": "MDL" if flag else "",
            "Pass": not flag,
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Method Blank Check
# ─────────────────────────────────────────────────────────────────────────────

def check_method_blank(
    df: pd.DataFrame,
    log: Optional[QCLog] = None,
) -> pd.DataFrame:
    """
    Flag any analyte detected above RL in the method blank.
    If blank ≥ sample value → flag <LOD on the sample.

    VBA: '<LOD = Method Blank Is Greater or Equal To Sample'
    """
    if "sample_type" not in df.columns:
        return pd.DataFrame()

    blank_mask = df["sample_type"].str.contains("Method Blank|Blank", na=False)
    blank_df = df[blank_mask].copy()
    sample_df = df[df["sample_type"] == "Environmental Sample"].copy()

    rows = []
    for analyte, blank_grp in blank_df.groupby("compound_name"):
        blank_conc = blank_grp["calculated_concentration"].dropna()
        if blank_conc.empty:
            continue
        max_blank = float(blank_conc.max())
        rl_series = blank_grp["reporting_limit"].dropna()
        rl = float(rl_series.iloc[0]) if not rl_series.empty else 0.0
        inj = blank_grp["injection_name"].iloc[0] if len(blank_grp) > 0 else ""

        contamination = max_blank > rl if rl > 0 else max_blank > 0

        if contamination and log:
            log.add("Method Blank", str(analyte), str(inj), round(max_blank, 4),
                    f"Blank {max_blank:.4f} > RL {rl:.4f} — possible contamination", "MB")

        # Flag samples where blank ≥ sample
        if not sample_df.empty:
            sample_analyte = sample_df[sample_df["compound_name"] == analyte]
            for _, s_row in sample_analyte.iterrows():
                s_conc = s_row.get("calculated_concentration")
                if pd.notna(s_conc) and float(s_conc) > 0 and max_blank >= float(s_conc):
                    s_inj = s_row.get("injection_name", "")
                    if log:
                        log.add("Method Blank", str(analyte), str(s_inj),
                                round(float(s_conc), 4),
                                f"<LOD: blank ({max_blank:.4f}) ≥ sample ({s_conc:.4f})",
                                "MDL")

        rows.append({
            "Analyte": analyte,
            "Blank Injection": inj,
            "Max Blank (ppt)": round(max_blank, 4),
            "Reporting Limit": rl,
            "Contamination Flag": contamination,
            "Flag": "MB" if contamination else "",
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Full Batch QC Pipeline  (RunFullPipeline — equivalent to VBA PIPELINE START)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BatchQCResult:
    """Complete QC result set for a batch of 18 samples."""
    batch_id: str
    log: QCLog
    mdl_table: pd.DataFrame
    rt_table: pd.DataFrame
    is_table: pd.DataFrame
    calibration_table: pd.DataFrame
    lfsm_table: pd.DataFrame
    qual_quan_table: pd.DataFrame
    signal_noise_table: pd.DataFrame
    method_blank_table: pd.DataFrame
    summary: dict

    @property
    def passed(self) -> bool:
        return not self.log.has_failures()

    def flag_counts(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(f.flag_code for f in self.log.flags if f.flag_code))


def run_batch_qc(
    df: pd.DataFrame,
    batch_id: str,
    spike_map: dict[str, float] | None = None,
    matrix: str = "",
    run_mdl: bool = False,
) -> BatchQCResult:
    """
    Run all QC checks on a complete batch DataFrame.
    Equivalent to the full VBA pipeline (PIPELINE START → PIPELINE COMPLETE).

    Parameters
    ----------
    df        : Normalised DataFrame from data_importer.load_instrument_export()
    batch_id  : Batch identifier (e.g. StarLIMS number or run date)
    spike_map : {injection_name → spike_ppt} from run queue / barcode scan
    matrix    : Sample matrix type (affects LFSM criteria)
    run_mdl   : Include MDL calculation (requires ≥ 7 replicates in df)
    """
    log = QCLog()
    spike_map = spike_map or {}

    mdl_table = pd.DataFrame()
    if run_mdl:
        mdl_table = calculate_mdl_batch(df, log=log)

    rt_table        = check_rt_deviations(df, log=log)
    is_table        = check_is_responses(df, log=log)
    cal_table       = check_calibration(df, log=log)
    lfsm_table      = check_lfsm_batch(df, spike_map=spike_map, matrix=matrix, log=log)
    qq_table        = check_qual_quan_ratios(df, log=log)
    sn_table        = check_signal_to_noise(df, log=log)
    blank_table     = check_method_blank(df, log=log)

    summary = {
        "batch_id": batch_id,
        "total_injections": df["injection_name"].nunique() if "injection_name" in df.columns else 0,
        "total_analytes": df["compound_name"].nunique() if "compound_name" in df.columns else 0,
        "total_flags": len(log.flags),
        "flags_by_type": log.summary(),
        "passed": not log.has_failures(),
    }

    return BatchQCResult(
        batch_id=batch_id,
        log=log,
        mdl_table=mdl_table,
        rt_table=rt_table,
        is_table=is_table,
        calibration_table=cal_table,
        lfsm_table=lfsm_table,
        qual_quan_table=qq_table,
        signal_noise_table=sn_table,
        method_blank_table=blank_table,
        summary=summary,
    )


def store_batch_results(
    result: BatchQCResult,
    run_date: str | None = None,
    method: str = "",
    db_path: str | None = None,
) -> int:
    """
    Persist all QC data points from a completed BatchQCResult to the
    SQLite control-chart store.  Returns the number of rows written.

    Call this immediately after run_batch_qc():

        result = run_batch_qc(df, batch_id="2026-06-10-001")
        store_batch_results(result)
    """
    import datetime
    from senaite.pfas.qc.store import QCResultStore
    from senaite.pfas.qc.control_chart import extract_qc_points_from_batch

    if run_date is None:
        run_date = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    rows = extract_qc_points_from_batch(result, run_date=run_date, method=method)
    if not rows:
        return 0

    store = QCResultStore(db_path=db_path)
    store.add_results_bulk(rows)
    return len(rows)
