"""
Instrument data importer.
Reads the raw MassLynx / Analyst / Skyline CSV export into typed InstrumentRow
objects.  This is the Python equivalent of the DATA table in the xlsm.

Column mapping handles the exact headers used in the xlsm DATA table (table19).
"""

from __future__ import annotations
import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from .models import InstrumentRow, reported_conc  # noqa: F401 (re-export)
from .constants import INJECTION_PATTERNS, STARLIMS_RE, QC_TYPES
from .canonical_columns import NATIVE_COLUMN_MAP, duplicate_targets

logger = logging.getLogger(__name__)

# Software version regex (mirrors import_studio._detect_software_version)
_VERSION_RE = re.compile(r'\b(\d+\.\d+[\.\d]*)\b')

# ── Column header → internal name ────────────────────────────────────────────
# Sourced from the add-on's canonical vocabulary so Import Studio can express
# every field the importer consumes (CLAUDE.md §1.3). The extra entries below
# are columns the importer tolerates but does not surface on InstrumentRow, so
# they are not offered as mapping purposes.
_COL_MAP: dict[str, str] = dict(NATIVE_COLUMN_MAP)
_COL_MAP.update({
    "Replicates":                 "replicates",
    "Replicate Index":            "replicate_index",
    "Concentration Units":        "conc_units",
    "Quan Ion Transition (m/z)":  "quan_ion",
    "Qual Ions Transitions (m/z)": "qual_ions",
    "RF":                         "rf",
    "Concat ID":                  "concat_id",
})

# Values treated as non-detect / missing
_ND_VALUES = {"ND", "N.D.", "N/A", "n/a", "", "NaN", "nan", "#N/A", "N.C.", "N.C"}

# ── Concentration qualifier tokens ──────────────────────────────────────────
# Instruments write these into the concentration cell, either alone ("BLoQ")
# or as a suffix on a real number ("20.1268 (ALoQ)"). They are NOT noise: they
# are the instrument's own statement about the result, and collapsing them to
# None turned "detected below the quantitation limit" into "not detected" —
# a different claim entirely under FDA/EPA reporting.
_QUALIFIER_TOKENS = {
    "BLOQ":         "BLoQ",          # below limit of quantitation (detected)
    "<LOQ":         "BLoQ",
    "ALOQ":         "ALoQ",          # above limit of quantitation
    ">LOQ":         "ALoQ",
    "NOT DETECTED": "N.D.",
    "ND":           "N.D.",
    "N.D.":         "N.D.",
    "NOT CALCULATED": "N.C.",
    "N.C.":         "N.C.",
    "N.C":          "N.C.",
}

_SUFFIX_QUALIFIER_RE = re.compile(r'^\s*(?P<num>[-+0-9.eE]+)\s*\((?P<tok>[^)]+)\)\s*$')


def parse_conc(val: str) -> "tuple[float | None, str]":
    """Split a concentration cell into (value, qualifier).

    Handles the three shapes real exports use:
      "1.2345"            → (1.2345, "")
      "BLoQ"              → (None,   "BLoQ")
      "20.1268 (ALoQ)"    → (20.1268, "ALoQ")

    An unrecognised non-numeric string yields (None, "") exactly as before, so
    genuinely empty or junk cells behave unchanged.
    """
    if val is None:
        return None, ""
    text = str(val).strip()
    if not text or text in _ND_VALUES:
        # "N/A" and friends carry no information beyond absence
        return None, ""

    m = _SUFFIX_QUALIFIER_RE.match(text)
    if m:
        tok = _QUALIFIER_TOKENS.get(m.group("tok").strip().upper(), "")
        try:
            return float(m.group("num")), tok
        except (ValueError, TypeError):
            return None, tok

    tok = _QUALIFIER_TOKENS.get(text.upper())
    if tok:
        return None, tok

    try:
        return float(text.replace(",", "")), ""
    except (ValueError, TypeError):
        return None, ""

_FLOAT_COLS = {
    "observed_rt", "rt_relative_to_is", "response", "is_response",
    "response_ratio", "expected_conc", "calculated_conc", "reporting_limit",
    "pct_deviation", "pct_recovery_is", "ion_ratios", "r2", "rf",
    "signal_to_noise", "qual_sn", "measured_conc", "injection_volume",
    "sample_factor",
}


def detect_software_version(path: "str | Path",
                            header_line_index: int = 0) -> str:
    """Read a software version out of the export's PREAMBLE — the lines ABOVE
    the header row. Returns "" when the file starts with its header, which is
    the honest answer: that file declares no version.

    Mirrors import_studio._detect_software_version deliberately; the two must
    agree, because the value becomes half of the saved profile's lookup key.

    Previously this scanned the first 20 lines unconditionally, so it read DATA:
    on a real FDA export it returned "0.039", a concentration from row 1's
    sample description. Every file whose first row held a different number
    produced a different key and silently stopped matching its own profile.
    """
    if header_line_index <= 0:
        return ""
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= header_line_index:
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


# Accepted acquisition-timestamp formats, most specific first.
# The month-name forms matter: SCIEX OS and several Waters builds write
# "Oct 08, 2025 17:55:21". Only numeric formats were accepted before, so every
# row of a real export parsed to None — which emptied injection_results.run_date
# and left the control charts and time-based CCV bracketing with nothing.
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",    "%d/%m/%Y %H:%M",    "%m/%d/%Y %H:%M",
    "%b %d, %Y %H:%M:%S", "%B %d, %Y %H:%M:%S",
    "%b %d, %Y %H:%M",    "%B %d, %Y %H:%M",
    "%d %b %Y %H:%M:%S",  "%d %B %Y %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",  "%Y/%m/%d %H:%M",
    "%d-%b-%Y %H:%M:%S",  "%d-%b-%y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%b %d, %Y",          "%B %d, %Y",
    "%Y-%m-%d",           "%d/%m/%Y",          "%m/%d/%Y",
    "%Y/%m/%d",           "%d-%b-%Y",
)


def _parse_datetime(date_str: str, time_str: str = "") -> datetime | None:
    raw = f"{date_str} {time_str}".strip()
    if not raw:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    logger.warning("Unparsed acquisition timestamp %r — add its format to "
                   "importer._DATETIME_FORMATS", raw)
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
            # Refuse rather than lose data. pandas' rename happily produces two
            # columns with the same name and to_dict() then keeps only the last,
            # so a mapping that points three columns at observed_rt discards two
            # of them without a word. Guarding here protects every profile,
            # including ones saved before the Studio validated them.
            dupes = duplicate_targets(col_map)
            if dupes:
                detail = "; ".join(
                    "{0} <- {1}".format(target, ", ".join(cols))
                    for target, cols in sorted(dupes.items()))
                raise ImportError(
                    "Import mapping assigns more than one column to the same "
                    "field, which would silently discard data: {0}. Fix the "
                    "mapping in Import Studio.".format(detail))
            df = df.rename(columns=col_map)
    else:
        # §7: Import Studio is the SINGLE source of instrument mappings — the
        # importer must refuse rather than auto-guess. The hardcoded
        # vendor_profiles.py path is retained for the test-suite only, behind
        # an explicit opt-in.
        import os
        if os.environ.get("PFAS_ALLOW_LEGACY_VENDOR_MAP") != "1":
            raise ImportError(
                "No Import Studio column-mapping profile provided — refusing "
                "to auto-guess vendor columns (CLAUDE.md §7). Save a profile "
                "in Import Studio, or set PFAS_ALLOW_LEGACY_VENDOR_MAP=1 "
                "(tests/dev only).")
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

        # The two concentration columns may carry the instrument's own verdict
        # ("BLoQ", "20.13 (ALoQ)", "Not Detected"). Keep it — the numeric
        # columns alone cannot distinguish "below quantitation" from "absent".
        calc_val, calc_qual = parse_conc(r.get("calculated_conc"))
        meas_val, meas_qual = parse_conc(r.get("measured_conc"))
        parsed_floats["calculated_conc"] = calc_val
        parsed_floats["measured_conc"] = meas_val

        rows.append(InstrumentRow(
            conc_qualifier      = calc_qual or meas_qual,
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
        return "LFB"   # LCS folds into the canonical LFB code
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
