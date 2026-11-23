"""
Instrument data importer.
Reads an instrument CSV export into typed InstrumentRow objects, using the
column mapping saved in Import Studio for that instrument and software version
(an export with no saved mapping is refused).
"""

from __future__ import annotations
import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from .models import InstrumentRow
from .constants import INJECTION_PATTERNS, STARLIMS_RE, QC_TYPES
from .canonical_columns import NATIVE_COLUMN_MAP, duplicate_targets
from .analyte_alias import canonical_labelled_name

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r'\b(\d+\.\d+[\.\d]*)\b')

# ── Column header → internal name ────────────────────────────────────────────
# The add-on's canonical vocabulary, so Import Studio can map every field the
# importer reads. The extra entries are columns the importer tolerates but
# InstrumentRow does not carry: they are not offered as mapping purposes.
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
# Instruments write these into the concentration cell, alone ("BLoQ") or as a
# suffix on a number ("20.1268 (ALoQ)"). They are the instrument's statement
# about the result and are kept: "detected below the quantitation limit" is
# not "not detected" under FDA/EPA reporting.
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

    An unrecognised non-numeric string yields (None, "").
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
    "observed_rt", "rt_relative_to_is", "response", "is_response", "is_observed_rt",
    "response_ratio", "expected_conc", "calculated_conc", "reporting_limit",
    "pct_deviation", "pct_recovery_is", "ion_ratios", "r2", "rf",
    "signal_to_noise", "qual_sn", "measured_conc", "injection_volume",
    "sample_factor",
}


def detect_software_version(path: "str | Path",
                            header_line_index: int = 0) -> str:
    """Read a software version out of the export's PREAMBLE — the lines ABOVE
    the header row. Returns "" when the file starts with its header: that file
    declares no version. Data rows are never read: a number in them would give
    each file a different key.
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


# Accepted acquisition-timestamp formats, most specific first. SCIEX OS and
# several Waters builds write month names ("Oct 08, 2025 17:55:21"); an
# unparsed time leaves the control charts and time-based CCV bracketing empty.
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
    # 12-hour clocks: a profile's date format (Import Studio) says which
    # order day and month are in; these are the last resort
    "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
)


def _parse_datetime(date_str: str, time_str: str = "", first: str = "") -> datetime | None:
    """The acquisition time; `first` is the import profile's own date format,
    tried before the list."""
    raw = f"{date_str} {time_str}".strip()
    if not raw:
        return None
    for fmt in ((first,) if first else ()) + _DATETIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    logger.warning("Unparsed acquisition timestamp %r — add its format to "
                   "importer._DATETIME_FORMATS", raw)
    return None


def _build_concat_id(row: dict) -> str:
    """
    Builds the unique key:
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

    vendor: one of waters/agilent/sciex/native, read only when *profile* is
            None and PFAS_ALLOW_LEGACY_VENDOR_MAP=1 (tests only).
    """
    if profile is not None:
        if "error" in profile:
            raise ImportError(profile["error"])

    path = Path(path)
    rows: list[InstrumentRow] = []

    if profile is not None and profile.get("reader"):
        # the layout the profile describes (Import Studio): the same reader
        # the Studio's preview used
        df = read_layout(path, profile)
    else:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")

    if profile is not None:
        col_map = profile.get("map", {})
        if col_map:
            # Refuse rather than lose data: pandas' rename makes two columns of
            # one name and to_dict() keeps only the last. Checked here for
            # every profile, whatever the Studio validated when it was saved.
            dupes = duplicate_targets(col_map)
            if dupes:
                detail = "; ".join(
                    "{0} <- {1}".format(target, ", ".join(cols))
                    for target, cols in sorted(dupes.items()))
                raise ImportError(
                    "Import mapping assigns more than one column to the same "
                    "field, which would silently discard data: {0}. Fix the "
                    "mapping in Import Studio.".format(detail))
            if profile.get("reader"):
                # the layout's columns found in this file by name, else by
                # their key (case, spacing, punctuation, a unit in brackets)
                from .addon import load as _load
                col_map = _load("import_layouts").resolve_map(profile, list(df.columns))
            df = df.rename(columns=col_map)
    else:
        # §7: Import Studio is the single source of instrument mappings: refuse
        # rather than guess. vendor_profiles.py is for the tests, behind an
        # explicit opt-in.
        import os
        if os.environ.get("PFAS_ALLOW_LEGACY_VENDOR_MAP") != "1":
            raise ImportError(
                "No Import Studio column-mapping profile provided — refusing "
                "to auto-guess vendor columns. Save a profile "
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

    # Manual integration: decided once, by the add-on's rule, with
    # the import profile's markers. No manual column in the export = not
    # captured (None), never "not manual".
    from .addon import load as _load_addon
    _mi = _load_addon("manual_integration")
    _mi_captured = "manual_changes" in df.columns
    _mi_markers = _mi.parse_markers((profile or {}).get("manual_markers") or "")
    # the profile's value maps and scales (a word or a scale the export uses
    # -> the platform's), applied to the mapped fields
    _values = bool((profile or {}).get("value_maps") or (profile or {}).get("scales"))
    _date_format = (profile or {}).get("date_format") or ""

    _file_name = Path(path).name
    for _, raw in df.iterrows():
        r: dict = raw.to_dict()
        if _values:
            r = _load_addon("import_layouts").apply_values(r, profile)
        # the file line the layout reader read this row from (value provenance)
        _line = r.pop("__line", None)
        try:
            _line = int(_line) if _line is not None and _line == _line else None
        except (TypeError, ValueError):
            _line = None

        dt = _parse_datetime(
            r.get("acq_date_str", "") or r.get("acq_datetime_str", ""),
            r.get("acq_time_str", ""),
            _date_format,
        )
        r["_dt"] = dt

        if not r.get("concat_id") or r["concat_id"].strip() in _ND_VALUES:
            r["concat_id"] = _build_concat_id(r)

        parsed_floats: dict[str, float | None] = {}
        for col in _FLOAT_COLS:
            val = r.get(col, "")
            parsed_floats[col] = _parse_float(str(val)) if val else None

        # The concentration columns may carry the instrument's verdict
        # ("BLoQ", "20.13 (ALoQ)", "Not Detected"): kept, as a number alone
        # cannot tell "below quantitation" from "absent".
        calc_val, calc_qual = parse_conc(r.get("calculated_conc"))
        meas_val, meas_qual = parse_conc(r.get("measured_conc"))
        parsed_floats["calculated_conc"] = calc_val
        parsed_floats["measured_conc"] = meas_val

        # A calibrator's deviation as a fraction (what the checks use), from its
        # expected and calculated concentrations: software writes "% Deviation"
        # in percent (Waters: 2.74 = 2.74 %). The column is used only when the
        # two concentrations are not there.
        _exp, _calc = parsed_floats.get("expected_conc"), parsed_floats.get("calculated_conc")
        if _exp not in (None, 0) and _calc is not None:
            parsed_floats["pct_deviation"] = (_calc - _exp) / _exp

        rows.append(InstrumentRow(
            conc_qualifier      = calc_qual or meas_qual,
            conc_units          = str(r.get("conc_units", "") or "").strip(),
            compound_name       = canonical_labelled_name(str(r.get("compound_name", "")).strip()),
            compound_type       = str(r.get("compound_type", "")).strip(),
            compound_group      = str(r.get("compound_group", "")).strip(),
            sample_description  = str(r.get("sample_description", "")).strip(),
            injection_name      = str(r.get("injection_name", "")).strip(),
            sample_group        = str(r.get("sample_group", "")).strip(),
            sample_type         = str(r.get("sample_type", "")).strip(),
            included_in_cal     = str(r.get("included_in_cal", "")).strip().lower() in ("true", "1", "yes", "y"),
            level               = r.get("level") or None,
            linked_is           = canonical_labelled_name(str(r.get("linked_is") or "").strip()) or None,
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
            quan_ref_expected_ion_ratios = r.get("quan_ref_expected_ion_ratios") or None,
            method_expected_ion_ratios = r.get("method_expected_ion_ratios") or None,
            qual_ions_responses = r.get("qual_ions_responses") or None,
            r2                  = parsed_floats.get("r2"),
            signal_to_noise     = parsed_floats.get("signal_to_noise"),
            qual_sn             = parsed_floats.get("qual_sn"),
            quant_status        = r.get("quant_status") or None,
            reporting_limit     = parsed_floats.get("reporting_limit"),
            measured_conc       = parsed_floats.get("measured_conc"),
            acquisition_datetime = dt,
            concat_id           = r["concat_id"],
            manual_changes      = _mi._text(r.get("manual_changes")) or None,
            manual_integration  = (_mi.is_manual(r.get("manual_changes"), _mi_markers)
                                   if _mi_captured else None),
            injection_volume    = parsed_floats.get("injection_volume"),
            sample_position     = r.get("sample_position") or None,
            is_observed_rt      = parsed_floats.get("is_observed_rt"),
            source_file         = _file_name,
            source_row          = _line,
        ))

    suffix = (profile or {}).get("qualifier_suffix") or ""
    if suffix:
        rows = qualifier_rows(rows, suffix)
    return rows


def read_layout(path, profile):
    """The export read with the import profile's layout (senaite.pfas.
    import_layouts, the reader Import Studio uses), as a frame of text cells;
    an empty cell is NaN, as pandas reads one."""
    import numpy as np
    from .addon import load
    lay = load("import_layouts")
    reader = profile.get("reader") or {}
    text = lay.decode(Path(path).read_bytes(), reader.get("encoding"))
    try:
        got = lay.read(text, reader)
    except ValueError as exc:
        raise ImportError("The import layout %r cannot read %s: %s"
                          % (profile.get("name") or "", Path(path).name, exc))
    # the reader's line number rides along as a column the mapping never
    # names (dropped from the row before the fields are read)
    df = pd.DataFrame(got["rows"], columns=list(got["headers"]) + ["__line"], dtype=object)
    return df.replace({"": np.nan})


def file_head(path) -> str:
    """The first lines of an export, as text: what its import layout is
    matched on (senaite.pfas.import_layouts.match)."""
    from .addon import load
    lay = load("import_layouts")
    with Path(path).open("rb") as fh:
        raw = fh.read(1 << 20)
    return lay.head(lay.decode(raw))


def qualifier_rows(rows, suffix):
    """A row named <compound><suffix> in an injection is that compound's
    qualifier transition (the import profile's qualifier-row suffix): its
    response becomes the compound's qualifier response, where the compound's
    own row gives none, and it is not read as a compound of its own."""
    by = dict(((r.concat_id, r.compound_name), r) for r in rows)
    out = []
    for r in rows:
        name = r.compound_name or ""
        base = (by.get((r.concat_id, name[:-len(suffix)]))
                if name.endswith(suffix) and len(name) > len(suffix) else None)
        if base is None:
            out.append(r)
            continue
        if not base.qual_ions_responses and r.response is not None:
            base.qual_ions_responses = repr(r.response)
    return out


# ── Injection name validator ──────────────────────────────────────────────────
def validate_injection_name(name: str) -> dict:
    """
    Validate an injection name against the built-in naming patterns
    (constants.INJECTION_PATTERNS; debug-level only, see pipeline step 2).
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


# The extraction batch's members (senaite.pfas.extraction_batch): {injection
# name: role}. For a run built from it the LIMS record, not the name, says what
# an injection is. Set once per run (run_pipeline).
_MEMBER_ROLES = {}


def set_member_roles(roles):
    """Replace the run's member roles ({injection: role}); {} clears them."""
    _MEMBER_ROLES.clear()
    _MEMBER_ROLES.update(dict(roles or {}))


# The levels a reviewer's identity correction fixes a CCV at
# (senaite.pfas.injection_identity): {injection name: "low" | "standard"}.
# Set once per run with the member roles (run_pipeline).
_LEVEL_OVERRIDES = {}


def set_level_overrides(levels):
    """Replace the run's corrected CCV levels; {} clears them."""
    _LEVEL_OVERRIDES.clear()
    _LEVEL_OVERRIDES.update(dict((k, v) for k, v in (levels or {}).items() if v in ("low", "standard")))


def level_override(name):
    """"low" or "standard" for an injection a reviewer's correction fixes
    the CCV level of, else None (its level column and expected
    concentration decide)."""
    return _LEVEL_OVERRIDES.get(name)


def classify_injection(name: str, dilutions: "dict | None" = None) -> str:
    """
    Return the QC type code for an injection name.
    Used to classify each row in the DATA table without re-running full validation.

    *dilutions* is the map recorded on FM-ENV-003 (see
    senaite.pfas.dilution_ref). An injection listed there is a dilution of
    another sample, not a sample of its own: it is not counted or reported
    twice, and QC rules can skip it. The relationship is never inferred from
    the name.
    """
    if dilutions and name in dilutions:
        return "Dilution"
    if name in _MEMBER_ROLES:
        return _MEMBER_ROLES[name]
    role, _rule = _classify(name)
    return role


# Control material, recognised positively and in this order. All of it is
# laboratory-prepared: one missed is treated as client material, never judged
# as a blank, never used for blank subtraction, and its failures qualified as
# a matrix effect instead of holding the batch.
# Order: LFSMD before LFSM (the longer token contains the shorter), both
# before Dup (a sample duplicate is not a matrix-spike duplicate).
_ROLE_PATTERNS = [
    # "LFSM Mid Duplicate": the Dup marker may sit any distance after LFSM
    ("LFSMD", re.compile(r"(?i)\bLFSMD\b|\bLFSM\b.*\bDup")),
    ("LFSM",  re.compile(r"(?i)\bLFSM\b")),
    ("MxB",   re.compile(r"(?i)\bMxB\b|\bmatrix\s+blank\b")),
    ("LRB",   re.compile(r"(?i)\bLRB\b|\b(?:lab(?:oratory)?\s+)?reagent\s+blank\b")),
    ("CCB",   re.compile(r"(?i)\bCCB\b|\bcontinuing\s+calibration\s+blank\b")),
    # LCS is its own QC type, judged only by a method that
    # runs it -- never folded into LFB
    ("LCS",   re.compile(r"(?i)\bLCS\b|\b(?:lab(?:oratory)?\s+)?control\s+sample\b")),
    ("LFB",   re.compile(r"(?i)\bLFB\b|\b(?:lab(?:oratory)?\s+)?"
                         r"fortified\s+(?:blank|sample)\b")),
    ("MB",    re.compile(r"(?i)\bMB\b|\bmethod\s+blank\b")),
    ("CCV",   re.compile(r"(?i)\bCCV\b")),
    ("ICV",   re.compile(r"(?i)\bICV\b")),
    ("CAL",   re.compile(r"(?i)\bCAL\b|-CAL-")),
    ("Dup",   re.compile(r"(?i)\bDup\.?\b|\bduplicate\b")),
]


def _classify(name):
    """(role, rule) for an injection name. rule is "" when nothing matched.

    A client sample has no positive marker, so the fallback is "Sample". The
    safety is in recognising control material exhaustively (_ROLE_PATTERNS)
    and naming the injections that fall through without matching a SENAITE
    sample.
    """
    # "_" separates the parts of a name (537_CCV_261006_02), but regex
    # word boundaries treat it as a letter: read it as a space
    text = (name or "").replace("_", " ")
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(text):
            return role, role
    return "Sample", ""


def classification_rule(name, dilutions=None):
    """Which rule classified this injection, or "" if it fell through.

    Tells a positively identified injection from one that defaulted.
    """
    if dilutions and name in dilutions:
        return "Dilution"
    if name in _MEMBER_ROLES:
        return "LIMS record (extraction batch or run plan)"
    return _classify(name)[1]


# ── Group rows by injection ───────────────────────────────────────────────────
def group_by_injection(rows: list[InstrumentRow]) -> dict[str, list[InstrumentRow]]:
    """Group instrument rows by concat_id (unique injection key)."""
    groups: dict[str, list[InstrumentRow]] = {}
    for r in rows:
        groups.setdefault(r.concat_id, []).append(r)
    return groups


