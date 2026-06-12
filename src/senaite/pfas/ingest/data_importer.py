"""
Instrument Data Importer
Loads raw mass-spectrometry CSV exports (MassLynx / Analyst / Skyline)
into a normalized pandas DataFrame matching the DATA table schema from
FDA_Sample_Calculator_V13.xlsm.

Column names are mapped from the exact headers in the xlsm sharedStrings.
"""
import re
import os

import pandas as pd
import numpy as np

# ── Column mapping: instrument export header → internal snake_case name ────────
# Left side = exact column name from xlsm DATA table (and typical instrument export)
COLUMN_MAP = {
    # ── Core identification ─────────────────────────────────────────────────
    "Compound Name":                "compound_name",
    "Compound Type":                "compound_type",
    "Composite Type":               "composite_type",
    "Compound Group":               "compound_group",
    "Included Internal Standards":  "included_is_list",
    "Sample Description":           "sample_description",
    "Injection Name":               "injection_name",
    "Sample Group":                 "sample_group",
    "Tag":                          "tag",
    "Replicates":                   "replicates",
    "Replicate Index":              "replicate_index",
    "Injection Volume":             "injection_volume",
    "Sample Position":              "sample_position",
    "Sample Type":                  "instrument_sample_type",   # Standard/QC/Unknown
    "Included in Calibration":      "included_in_calibration",
    "Level":                        "level",
    "Linked Internal Standard":     "linked_is",
    "Calibration Reference Compound": "cal_reference_compound",
    # ── Chromatography ──────────────────────────────────────────────────────
    "Expected RT (min)":            "expected_rt",
    "Observed RT (min)":            "observed_rt",
    "RT Relative to IS":            "rt_relative_to_is",
    # ── Response / signal ───────────────────────────────────────────────────
    "Response":                     "response",
    "Manual Changes":               "manual_changes",
    "IS Response":                  "is_response",
    "Response Ratio":               "response_ratio",
    "Corrected Response":           "corrected_response",
    "Average Grouped Response":     "avg_grouped_response",
    "SD Grouped Response":          "sd_grouped_response",
    "%RSD Grouped Response":        "pct_rsd_grouped_response",
    "Quan Ion Peak Height":         "quan_peak_height",
    "Qual Ions Peak Heights":       "qual_peak_heights",
    # ── Quantitation ────────────────────────────────────────────────────────
    "Expected Concentration":       "expected_concentration",
    "Calculated Concentration":     "calculated_concentration",
    "Measured Concentration":       "measured_concentration",
    "Concentration Units":          "concentration_units",
    "Reporting Limit":              "reporting_limit",
    "% Deviation":                  "pct_deviation",
    "% Recovery (IS)":              "recovery_is_pct",
    "% Recovery (Analyte)":         "recovery_analyte_pct",
    "Average % Recovery (Analyte)": "avg_recovery_analyte_pct",
    "SD % Recovery (Analyte)":      "sd_recovery_analyte_pct",
    "%RSD % Recovery (Analyte)":    "pct_rsd_recovery_analyte",
    "% Recovery Lower Limit":       "recovery_lower_limit",
    "% Recovery Upper Limit":       "recovery_upper_limit",
    "Cumulative Sample Factor":     "cumulative_sample_factor",
    "Sample Factor":                "sample_factor",
    "Quantitation Status":          "quant_status",
    # ── MRM / ion ratios ────────────────────────────────────────────────────
    "Quan Ion Transition (m/z)":    "quan_mrm",
    "Qual Ions Transitions (m/z)":  "qual_mrms",
    "Qual Ions Observed RTs (min)": "qual_observed_rts",
    "Qual Ions Responses":          "qual_responses",
    "Ion Ratios":                   "ion_ratios",
    "Expected Ion Ratios":          "expected_ion_ratios",
    "Method Expected Ion Ratios":   "method_expected_ion_ratios",
    "Quan Ref Expected Ion Ratios": "quan_ref_expected_ion_ratios",
    "Ion Ratio Tolerances (%)":     "ion_ratio_tolerances",
    "Ion Ratio Deviations (%)":     "ion_ratio_deviations",
    "Ion Ratio Check":              "ion_ratio_check",
    # ── Calibration fit ─────────────────────────────────────────────────────
    "R2":                           "r2",
    "RF":                           "rf",
    "Equation":                     "equation",
    "Fit Type":                     "fit_type",
    "Origin Type":                  "origin_type",
    "Weight Type":                  "weight_type",
    # ── Signal quality ──────────────────────────────────────────────────────
    "Signal to Noise":              "signal_to_noise",
    "Qual Ions Signal to Noise":    "qual_sn",
    "Qual Ion Signal to Noise":     "qual_sn",
    "Qual Ion Signal to Noise Secondary": "qual_sn_secondary",
    # ── Timestamps / IDs ────────────────────────────────────────────────────
    "Acquisition Date Time":        "acquisition_datetime",
    "Acquisition Date":             "acquisition_date",
    "Acquisition Time":             "acquisition_time",
    "Result Set Id":                "result_set_id",
    "Concat ID":                    "concat_id",
    # Alternate spellings from some instrument software
    "Concotonated ID":              "concat_id",
    "Sample Name":                  "injection_name",
    "RT":                           "observed_rt",
    "Area":                         "response",
    "ISTD Response":                "is_response",
}

# Values that represent non-detects / not applicable in most numeric columns.
# Note: "BLoQ" and "Not Detected" are handled explicitly in _apply_quant_status()
# so they should NOT be in ND_VALUES (we need to read them first).
ND_VALUES = frozenset({
    "ND", "N.D.", "N/A", "n/a", "", "NaN", "nan", "None",
    "Not calculated", "No Quan Ref Ion Ratio",
    "Not Calculated", "N.C.", "#N/A", "No level",
})

# Numeric columns (coerce to float after ND handling)
NUMERIC_COLS = [
    "injection_volume", "replicate_index", "replicates",
    "observed_rt", "rt_relative_to_is", "response", "is_response",
    "response_ratio", "expected_concentration", "calculated_concentration",
    "reporting_limit", "pct_deviation", "recovery_is_pct",
    "r2", "rf", "signal_to_noise", "qual_sn", "qual_sn_secondary",
    "measured_concentration", "sample_factor",
]


def load_instrument_export(path, encoding="utf-8-sig", sep=None):
    """
    Load a raw instrument CSV/TSV export into a normalised DataFrame.

    Parameters
    ----------
    path     : Path to CSV/TSV file from MassLynx, Analyst, or Skyline.
    encoding : File encoding (utf-8-sig handles BOM from Windows exports).
    sep      : Delimiter; None = auto-detect (comma or tab).

    Returns
    -------
    pd.DataFrame with snake_case column names, NaN for non-detects,
    numeric columns as float64, acquisition_datetime as datetime64.
    """
    path = str(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Instrument export not found: {path}")

    # Auto-detect delimiter
    if sep is None:
        with open(path, "r", encoding=encoding, errors="replace") as f:
            first_line = f.readline()
        sep = "\t" if first_line.count("\t") > first_line.count(",") else ","

    df = pd.read_csv(path, sep=sep, dtype=str, encoding=encoding, errors="replace")

    # Rename columns
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})

    # Normalise non-detect / empty values to NaN
    df = df.applymap(lambda x: np.nan if str(x).strip() in ND_VALUES else x)

    # Strip whitespace from strings
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # Cast numeric columns
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Parse BLoQ values — e.g. "1.04 (BLoQ)" → numeric 1.04 + flag column
    if "calculated_concentration" in df.columns:
        df = _parse_bloq_column(df, "calculated_concentration")

    # Parse result flags from concentration strings — e.g. "122 (RT)", "10.6 (BLoQ; SUR)"
    if "calculated_concentration" in df.columns:
        df["result_flags"] = df["calculated_concentration_raw"].apply(_extract_flags)

    # Build acquisition datetime
    df = _build_datetime(df)

    # Handle Quantitation Status: BLoQ and Not Detected require special treatment
    # Must run BEFORE ND_VALUES coercion on calculated_concentration
    df = _apply_quant_status(df)

    # Apply per-matrix salt adjustment factors from QC rules store
    df = _apply_salt_factors(df)

    # Classify QC type using shortcodes from Sample Description + Injection Name
    from senaite.pfas.analytes import classify_injection
    if "injection_name" in df.columns:
        desc_col = df.get("sample_description") if "sample_description" in df.columns else None
        if desc_col is not None:
            df["qc_type"] = [
                classify_injection(
                    str(inj) if pd.notna(inj) else "",
                    str(desc) if pd.notna(desc) else "",
                )
                for inj, desc in zip(df["injection_name"], desc_col)
            ]
        else:
            df["qc_type"] = df["injection_name"].apply(
                lambda n: classify_injection(str(n)) if pd.notna(n) else "Sample"
            )

    # Parse analyst + run_date from Sample Description
    if "sample_description" in df.columns:
        from senaite.pfas.analytes import parse_sample_description
        parsed = df["sample_description"].apply(
            lambda d: parse_sample_description(str(d)) if pd.notna(d) else {}
        )
        if "analyst" not in df.columns:
            df["analyst"] = parsed.apply(lambda p: p.get("analyst", ""))
        if "run_date_parsed" not in df.columns:
            df["run_date_parsed"] = parsed.apply(lambda p: p.get("run_date", ""))
        if "matrix" not in df.columns:
            df["matrix"] = parsed.apply(lambda p: p.get("matrix", ""))

    return df


def _parse_bloq_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    Splits "1.04 (BLoQ)" style values into numeric + bloq_flag.
    Preserves the raw string in {col}_raw.
    """
    df[f"{col}_raw"] = df[col].copy()

    def _extract_num(val):
        if pd.isna(val):
            return np.nan
        s = str(val)
        m = re.match(r"^([\d.]+)", s)
        return float(m.group(1)) if m else np.nan

    df[col] = df[f"{col}_raw"].apply(_extract_num)
    df["bloq_flag"] = df[f"{col}_raw"].apply(
        lambda v: "BLoQ" in str(v) if pd.notna(v) else False
    )
    return df


def _apply_quant_status(df):
    """
    Resolve Quantitation Status into result_qualifier and a clean
    reported_concentration column.

    Quantitation Status values observed in MassLynx exports:
      Successful         — detected above LOQ; use Calculated Concentration as-is
      Successful BLoQ    — instrument found signal but value < LOQ (has numeric conc)
      BLoQ               — below LOQ; Calculated Concentration is literal "BLoQ"
      Not Detected       — no signal; Calculated Concentration is "Not Detected"

    Rules (per user spec):
      BLoQ / Successful BLoQ → qualifier = "<LOQ", reported value = 0.0 (detected)
      Not Detected            → qualifier = "ND",   reported value = None
      Successful              → qualifier = "",      reported value = numeric conc
    """
    if "quant_status" not in df.columns:
        return df

    def _qualifier(status):
        s = str(status).strip() if pd.notna(status) else ""
        if s in ("Not Detected",):
            return "ND"
        if "BLoQ" in s:
            return "<LOQ"
        return ""

    df["result_qualifier"] = df["quant_status"].apply(_qualifier)

    if "calculated_concentration" not in df.columns:
        return df

    # Fix the calculated_concentration column:
    # - ND rows → None (non-detect, no numerical value)
    # - BLoQ rows → 0.0  (detected but below quantitation limit)
    # - Successful rows → keep numeric (already coerced by later pd.to_numeric)
    def _reported_conc(row):
        q = row.get("result_qualifier", "")
        raw = row.get("calculated_concentration")
        if q == "ND":
            return np.nan
        if q == "<LOQ":
            return 0.0
        # Normal detected — coerce to float; non-numeric → NaN
        try:
            v = float(raw)
            return v if not (np.isinf(v) or np.isnan(v)) else np.nan
        except (TypeError, ValueError):
            return np.nan

    df["reported_concentration"] = df.apply(_reported_conc, axis=1)
    return df


def _apply_salt_factors(df):
    """
    Multiply reported_concentration by the per-matrix salt adjustment factor.

    The factor corrects for the volume of water displaced during salting-out
    (QuEChERS / LLE with MgSO4 + NaCl) in the extraction procedure.
    Factors are loaded from the QC rules store (qc_rules.json).

    - ND rows (NaN reported_concentration) are left unchanged.
    - BLoQ rows (reported_concentration == 0.0) stay 0.0.
    - Numeric results are multiplied by the factor.

    The compound_name column is used to determine the analyte class (PFCA,
    PFSA, FTS …) for analyte-class-specific overrides.
    """
    if "reported_concentration" not in df.columns:
        return df

    # Load salt factors from QC rules store (with default fallback)
    try:
        from senaite.pfas.qc.rules import get_store as _get_rules_store
        _store = _get_rules_store()
    except ImportError:
        return df

    # Build a quick class lookup for known analytes
    _ANALYTE_CLASSES = {}
    try:
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
        for row in NATIVE_ANALYTES:
            # row: (keyword, name, cas, full_name, klass, chain, surrogate_is, no_labeled)
            klass = row[4].lower()   # PFCA / PFSA / FTS / FOSA / PFECA / Cl-PFAES
            chain = row[5]           # integer chain length
            name_key = row[1].lower()
            kwd_key = row[0].lower()
            for k in (name_key, kwd_key):
                _ANALYTE_CLASSES[k] = (klass, chain)
    except Exception:
        pass

    def _salt_class(compound_name, klass, chain):
        """Map analyte class + chain length to a rules-store class key."""
        if klass == "pfca":
            return "pfca_c4_c8" if chain <= 8 else "pfca_c9_plus"
        if klass == "pfsa":
            return "pfsa"
        if klass == "fts":
            return "fts"
        return None

    def _factor_for_row(row):
        matrix = str(row.get("matrix") or "").strip().lower() or "other"
        raw_conc = row.get("reported_concentration")

        # Don't touch ND (NaN) or BLoQ (0.0) — they carry no magnitude to adjust
        if raw_conc is None or (isinstance(raw_conc, float) and np.isnan(raw_conc)):
            return raw_conc
        if isinstance(raw_conc, float) and raw_conc == 0.0:
            return raw_conc

        # Resolve analyte class for sub-factor lookup
        cname = str(row.get("compound_name") or "").strip().lower()
        klass_info = _ANALYTE_CLASSES.get(cname)
        analyte_class = None
        if klass_info:
            analyte_class = _salt_class(cname, klass_info[0], klass_info[1])

        factor = _store.get_salt_factor(matrix, analyte_class=analyte_class)
        if factor == 1.0:
            return raw_conc
        try:
            return float(raw_conc) * factor
        except (TypeError, ValueError):
            return raw_conc

    df["reported_concentration"] = df.apply(_factor_for_row, axis=1)
    return df


def _extract_flags(val):
    """Extract QC flags from result strings: BLoQ, RT, SUR, N.C., REC."""
    if pd.isna(val):
        return []
    s = str(val)
    return [flag for flag in ("BLoQ", "RT", "SUR", "N.C.", "REC", "IS", "CAL", "MDL")
            if flag in s]


def normalize_date(val: str | None, us_locale: bool = True) -> str | None:
    """
    Parse a date string in any common lab format and return ISO-8601 YYYY-MM-DD.

    Handles:
      2026-06-11            ISO (pass-through)
      20260611              Compact ISO
      06/11/2026            US (MM/DD/YYYY) — default when ambiguous
      11/06/2026            UK (DD/MM/YYYY) — if us_locale=False
      11-Jun-2026           Day-Month-Year with abbreviated month
      Jun 11, 2026          Long US format
      June 11 2026          Long US without comma
      11 June 2026          Long EU
      2026.06.11            Dot-separated ISO
      2026/06/11            Slash-separated ISO
      Wed Jun 11 09:30:00   ctime-style (strips weekday/time)

    Ambiguous two-digit year is treated as 20xx if xx <= 50, else 19xx.
    When day and month are both ≤ 12 and us_locale=True, month is assumed first.

    Returns None if the value cannot be parsed.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "n/a", ""):
        return None

    import re
    from datetime import datetime

    # Strip leading weekday (e.g. "Wed ")
    s = re.sub(r"^[A-Za-z]{3},?\s+", "", s)

    MONTH_NAMES = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
    }

    def _fix_year(y: int) -> int:
        if y < 100:
            return 2000 + y if y <= 50 else 1900 + y
        return y

    def _to_iso(year: int, month: int, day: int) -> str | None:
        try:
            dt = datetime(year, month, day)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    # ── Try pandas first (handles most formats including ctime) ─────────
    try:
        dt = pd.to_datetime(s, dayfirst=not us_locale)
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    # ── Compact ISO: 20260611 ────────────────────────────────────────────
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # ── YYYY[-./]MM[-./]DD ───────────────────────────────────────────────
    m = re.match(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # ── DD[-./]MM[-./]YYYY or MM[-./]DD[-./]YYYY ────────────────────────
    m = re.match(r"^(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), _fix_year(int(m.group(3)))
        if us_locale:
            month, day = a, b   # MM/DD
        else:
            day, month = a, b   # DD/MM
        # If month >12 it must be the day regardless of locale
        if month > 12:
            month, day = day, month
        return _to_iso(year, month, day)

    # ── "Jun 11, 2026" / "11 June 2026" / "June 11 2026" ────────────────
    m = re.match(
        r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{2,4})", s
    )
    if m:
        mon_str = m.group(2).lower()[:3]
        month = MONTH_NAMES.get(mon_str)
        if month:
            return _to_iso(_fix_year(int(m.group(3))), month, int(m.group(1)))

    m = re.match(
        r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{2,4})", s
    )
    if m:
        mon_str = m.group(1).lower()[:3]
        month = MONTH_NAMES.get(mon_str)
        if month:
            return _to_iso(_fix_year(int(m.group(3))), month, int(m.group(2)))

    return None


def _build_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build acquisition_datetime (datetime64) and acquisition_date_iso (str
    YYYY-MM-DD) from whatever date columns the instrument export provides.
    The ISO string column is stable for storage in the QC results database.
    """
    if "acquisition_datetime" in df.columns:
        df["acquisition_datetime"] = pd.to_datetime(
            df["acquisition_datetime"].apply(
                lambda v: normalize_date(str(v)) if pd.notna(v) else None
            ),
            errors="coerce",
        )
    elif "acquisition_date" in df.columns:
        cleaned = df["acquisition_date"].apply(
            lambda v: normalize_date(str(v)) if pd.notna(v) else None
        )
        time_part = ""
        if "acquisition_time" in df.columns:
            time_part = df["acquisition_time"].fillna("").astype(str)
            combined = cleaned.fillna("").astype(str) + " " + time_part
        else:
            combined = cleaned.fillna("").astype(str)
        df["acquisition_datetime"] = pd.to_datetime(combined, errors="coerce")

    # Always produce a stable ISO date string column for DB storage
    if "acquisition_datetime" in df.columns:
        df["acquisition_date_iso"] = df["acquisition_datetime"].apply(
            lambda dt: dt.strftime("%Y-%m-%d") if pd.notna(dt) else None
        )

    return df


def pivot_by_injection(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot to wide format: one row per injection, one column per analyte.
    Used for QC checks that compare across injections.
    """
    if "injection_name" not in df.columns or "compound_name" not in df.columns:
        return df
    return df.pivot_table(
        index="injection_name",
        columns="compound_name",
        values="calculated_concentration",
        aggfunc="first",
    )


def get_injection_sequence(df: pd.DataFrame) -> list[dict]:
    """
    Return ordered list of unique injections with metadata.
    Used to build the run queue and validate injection order.
    """
    if "injection_name" not in df.columns:
        return []

    cols = ["injection_name", "sample_type", "sample_description",
            "acquisition_datetime", "sample_position"]
    available = [c for c in cols if c in df.columns]

    seq = (
        df[available]
        .drop_duplicates(subset=["injection_name"])
        .sort_values("acquisition_datetime" if "acquisition_datetime" in available else "injection_name")
    )
    return seq.to_dict("records")


def validate_batch_structure(df: pd.DataFrame) -> list[dict]:
    """
    Check that a batch has the required QC sample types.
    Returns list of issues. Empty list = batch is structurally valid.
    """
    issues = []
    if "sample_type" not in df.columns:
        return [{"issue": "No sample_type column — cannot validate batch structure"}]

    types = set(df["sample_type"].dropna().unique())

    required = {
        "Method Blank":                     "MB",
        "Continuing Calibration Verification": "CCV",
        "Lab Fortified Sample Matrix":       "LFSM",
        "Calibration Standard":             "CAL",
    }
    for label, code in required.items():
        if label not in types and not any(code in t for t in types):
            issues.append({
                "level": "ERROR",
                "issue": f"Missing required QC type: {label} ({code})",
            })

    # Check calibration count
    cal_count = len(df[df["sample_type"].str.contains("Calibration Standard", na=False)]
                    ["injection_name"].unique())
    if cal_count < 6:
        issues.append({
            "level": "WARNING",
            "issue": f"Only {cal_count} calibration levels found (expect ≥ 6)",
        })

    return issues
