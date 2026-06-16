"""
Instrument data importer.
Reads the raw MassLynx / Analyst / Skyline CSV export into typed InstrumentRow
objects.  This is the Python equivalent of the DATA table in the xlsm.

Column mapping handles the exact headers used in the xlsm DATA table (table19).
"""

from __future__ import annotations
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from .models import InstrumentRow
from .constants import INJECTION_PATTERNS, STARLIMS_RE, QC_TYPES

# Software version regex (mirrors import_studio._detect_software_version)
_VERSION_RE = re.compile(r'\b(\d+\.\d+[\.\d]*)\b')

# ── Column header → internal name (matches table19.xml column list exactly) ──
_COL_MAP: dict[str, str] = {
    "Compound Name":              "compound_name",
    "Compound Type":              "compound_type",
    "Compound Group":             "compound_group",
    "Sample Description":         "sample_description",
    "Injection Name":             "injection_name",
    "Sample Group":               "sample_group",
    "Replicates":                 "replicates",
    "Replicate Index":            "replicate_index",
    "Injection Volume":           "injection_volume",
    "Sample Position":            "sample_position",
    "Sample Type":                "sample_type",
    "Included in Calibration":    "included_in_cal",
    "Level":                      "level",
    "Linked Internal Standard":   "linked_is",
    "Calibration Reference Compound": "cal_ref_compound",
    "Observed RT (min)":          "observed_rt",
    "RT Relative to IS":          "rt_relative_to_is",
    "Response":                   "response",
    "Manual Changes":             "manual_changes",
    "IS Response":                "is_response",
    "Response Ratio":             "response_ratio",
    "Expected Concentration":     "expected_conc",
    "Calculated Concentration":   "calculated_conc",
    "Concentration Units":        "conc_units",
    "Reporting Limit":            "reporting_limit",
    "% Deviation":                "pct_deviation",
    "% Recovery (IS)":            "pct_recovery_is",
    "Quan Ion Transition (m/z)":  "quan_ion",
    "Qual Ions Transitions (m/z)":"qual_ions",
    "Ion Ratios":                 "ion_ratios",
    "Expected Ion Ratios":        "expected_ion_ratios",
    "R2":                         "r2",
    "RF":                         "rf",
    "Signal to Noise":            "signal_to_noise",
    "Qual Ions Signal to Noise":  "qual_sn",
    "Quantitation Status":        "quant_status",
    "Measured Concentration":     "measured_conc",
    "Acquisition Date Time":      "acq_datetime_str",
    "Acquisition Date":           "acq_date_str",
    "Acquisition Time":           "acq_time_str",
    "Concat ID":                  "concat_id",
    "Sample Factor":              "sample_factor",
}

# Values treated as non-detect / missing
_ND_VALUES = {"ND", "N.D.", "N/A", "n/a", "", "NaN", "nan", "#N/A", "N.C.", "N.C"}

_FLOAT_COLS = {
    "observed_rt", "rt_relative_to_is", "response", "is_response",
    "response_ratio", "expected_conc", "calculated_conc", "reporting_limit",
    "pct_deviation", "pct_recovery_is", "ion_ratios", "r2", "rf",
    "signal_to_noise", "qual_sn", "measured_conc", "injection_volume",
    "sample_factor",
}


def detect_software_version(path: "str | Path") -> str:
    """Scan the first 20 lines of *path* for a version string like X.Y.Z."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= 20:
                    break
                m = _VERSION_RE.search(line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def _parse_float(val: str) -> float | None:
    if not val or val.strip() in _ND_VALUES:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_datetime(date_str: str, time_str: str = "") -> datetime | None:
    raw = f"{date_str} {time_str}".strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",    "%d/%m/%Y %H:%M",    "%m/%d/%Y %H:%M",
        "%Y-%m-%d",          "%d/%m/%Y",           "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _build_concat_id(row: dict) -> str:
    """
    Replicates the Excel formula:
      = [@Injection Name] & "|" & TEXT([@Acquisition Date] + [@Acquisition Time],
                                        "yyyymmddhhmmss")
    """
    inj = row.get("injection_name", "")
    dt = row.get("_dt")
    if dt:
        return f"{inj}|{dt.strftime('%Y%m%d%H%M%S')}"
    return inj


def load_instrument_csv(
    path: str | Path,
    vendor: str | None = None,
    profile: "dict | None" = None,
) -> list[InstrumentRow]:
    """
    Load a MassLynx / MassHunter / SCIEX OS / native instrument export CSV.
    Returns a list of InstrumentRow objects (one per compound × injection).

    profile: column-mapping profile dict from the Import Studio REST bridge
             ({"map": {vendor_col: canonical_col}, ...}).  When provided,
             this takes precedence over vendor_profiles.py.  If the dict
             contains an "error" key, ImportError is raised immediately.

    vendor: legacy fallback — one of waters/agilent/sciex/native.  Ignored
            when *profile* is provided.  Only used when profile is None AND
            vendor_profiles.py is still available (deprecated path).
    """
    if profile is not None:
        if "error" in profile:
            raise ImportError(profile["error"])

    path = Path(path)
    rows: list[InstrumentRow] = []

    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")

    if profile is not None:
        # Use Import Studio profile map exclusively
        col_map = profile.get("map", {})
        if col_map:
            df = df.rename(columns=col_map)
    else:
        # Legacy path: hardcoded vendor_profiles.py (only runs when no profile)
        from .vendor_profiles import get_vendor_profile, detect_vendor
        vkey = vendor or detect_vendor(list(df.columns))
        vprofile = get_vendor_profile(vkey)
        if vprofile["map"]:
            df = df.rename(columns=vprofile["map"])

    # Normalise header names (canonical → internal)
    rename = {c: _COL_MAP[c] for c in df.columns if c in _COL_MAP}
    df = df.rename(columns=rename)

    for _, raw in df.iterrows():
        r: dict = raw.to_dict()

        # Parse datetime
        dt = _parse_datetime(
            r.get("acq_date_str", "") or r.get("acq_datetime_str", ""),
            r.get("acq_time_str", ""),
        )
        r["_dt"] = dt

        # Build concat_id if not present
        if not r.get("concat_id") or r["concat_id"].strip() in _ND_VALUES:
            r["concat_id"] = _build_concat_id(r)

        # Parse floats
        parsed_floats: dict[str, float | None] = {}
        for col in _FLOAT_COLS:
            val = r.get(col, "")
            parsed_floats[col] = _parse_float(str(val)) if val else None

        rows.append(InstrumentRow(
            compound_name       = str(r.get("compound_name", "")).strip(),
            compound_type       = str(r.get("compound_type", "")).strip(),
            compound_group      = str(r.get("compound_group", "")).strip(),
            sample_description  = str(r.get("sample_description", "")).strip(),
            injection_name      = str(r.get("injection_name", "")).strip(),
            sample_group        = str(r.get("sample_group", "")).strip(),
            sample_type         = str(r.get("sample_type", "")).strip(),
            included_in_cal     = str(r.get("included_in_cal", "")).strip().lower() in ("true", "1", "yes", "y"),
            level               = r.get("level") or None,
            linked_is           = r.get("linked_is") or None,
            cal_ref_compound    = r.get("cal_ref_compound") or None,
            observed_rt         = parsed_floats.get("observed_rt"),
            rt_relative_to_is   = parsed_floats.get("rt_relative_to_is"),
            response            = parsed_floats.get("response"),
            is_response         = parsed_floats.get("is_response"),
            response_ratio      = parsed_floats.get("response_ratio"),
            expected_conc       = parsed_floats.get("expected_conc"),
            calculated_conc     = parsed_floats.get("calculated_conc"),
            pct_deviation       = parsed_floats.get("pct_deviation"),
            pct_recovery_is     = parsed_floats.get("pct_recovery_is"),
            ion_ratios          = r.get("ion_ratios") or None,
            expected_ion_ratios = r.get("expected_ion_ratios") or None,
            r2                  = parsed_floats.get("r2"),
            signal_to_noise     = parsed_floats.get("signal_to_noise"),
            qual_sn             = parsed_floats.get("qual_sn"),
            quant_status        = r.get("quant_status") or None,
            reporting_limit     = parsed_floats.get("reporting_limit"),
            measured_conc       = parsed_floats.get("measured_conc"),
            acquisition_datetime = dt,
            concat_id           = r["concat_id"],
            manual_changes      = r.get("manual_changes") or None,
            injection_volume    = parsed_floats.get("injection_volume"),
            sample_position     = r.get("sample_position") or None,
        ))

    return rows


# ── Injection name validator ──────────────────────────────────────────────────
def validate_injection_name(name: str) -> dict:
    """
    Validate injection name against patterns from VBA ValidateInjectionNames.
    Returns {"valid": bool, "pattern": int, "qc_type": str, "starlims_id": str|None,
             "error": str|None}
    """
    for i, pat in enumerate(INJECTION_PATTERNS, 1):
        if pat.match(name):
            # Detect QC type from name
            qc_type = "Unknown"
            for code, label in QC_TYPES.items():
                if code in name.upper() or code in name:
                    qc_type = label
                    break
            starlims = STARLIMS_RE.search(name)
            return {
                "valid": True,
                "pattern": i,
                "qc_type": qc_type,
                "starlims_id": starlims.group(1) if starlims else None,
                "error": None,
            }
    return {
        "valid": False,
        "pattern": None,
        "qc_type": None,
        "starlims_id": None,
        "error": f"Injection name does not match required pattern: {name!r}",
    }


def classify_injection(name: str) -> str:
    """
    Return the QC type code for an injection name.
    Used to classify each row in the DATA table without re-running full validation.
    """
    upper = name.upper()
    if "LFSMD" in name or "DUP" in upper:
        return "LFSMD"
    if "LFSM" in name:
        return "LFSM"
    if "MB" in name.split():
        return "MB"
    if "CCV" in upper:
        return "CCV"
    if "ICV" in upper:
        return "ICV"
    if "-CAL-" in upper or " CAL " in upper:
        return "CAL"
    if "LCS" in upper:
        return "LCS"
    return "Sample"


# ── Group rows by injection ───────────────────────────────────────────────────
def group_by_injection(rows: list[InstrumentRow]) -> dict[str, list[InstrumentRow]]:
    """Group instrument rows by concat_id (unique injection key)."""
    groups: dict[str, list[InstrumentRow]] = {}
    for r in rows:
        groups.setdefault(r.concat_id, []).append(r)
    return groups


def group_by_compound(rows: list[InstrumentRow]) -> dict[str, list[InstrumentRow]]:
    """Group instrument rows by compound name."""
    groups: dict[str, list[InstrumentRow]] = {}
    for r in rows:
        groups.setdefault(r.compound_name, []).append(r)
    return groups
