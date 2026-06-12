"""
Vendor mapping profiles — make the instrument CSV importer vendor-agnostic.

Each profile maps a vendor's export column headers onto the canonical
internal field names used by InstrumentRow.  Add a new instrument by adding
a dict here (or loading a YAML file via load_vendor_profile_yaml) — no code
changes to importer.py.

Canonical field names (targets) match importer._COL_MAP values:
  compound_name, compound_type, sample_description, injection_name,
  sample_type, observed_rt, response, is_response, response_ratio,
  expected_conc, calculated_conc, measured_conc, pct_deviation, r2,
  signal_to_noise, qual_sn, reporting_limit, linked_is, ion_ratios,
  acq_date_str, acq_time_str, concat_id, level, quant_status

The FDA method uses SCIEX OS; 537.1/1633A labs commonly use Waters
(MassLynx/TargetLynx) or Agilent (MassHunter Quant).
"""

from __future__ import annotations
from pathlib import Path


# ── Waters MassLynx / TargetLynx (Quanpedia / QuanLynx summary export) ───────
WATERS_MASSLYNX = {
    "vendor": "Waters MassLynx/TargetLynx",
    "delimiter": ",",
    "map": {
        "Name":                 "compound_name",
        "Compound":             "compound_name",
        "Type":                 "compound_type",
        "Sample Text":          "sample_description",
        "Sample Name":          "injection_name",
        "Sample Type":          "sample_type",
        "RT":                   "observed_rt",
        "Area":                 "response",
        "IS Area":              "is_response",
        "Response":             "response_ratio",
        "Std. Conc":            "expected_conc",
        "Conc.":                "calculated_conc",
        "ng/mL":                "measured_conc",
        "%Dev":                 "pct_deviation",
        "R2":                   "r2",
        "S/N":                  "signal_to_noise",
        "Primary Flags":        "quant_status",
        "Sample ID":            "level",
        "Acq.Date":             "acq_date_str",
        "Acq.Time":             "acq_time_str",
    },
    # TargetLynx often exports per-compound blocks; importer handles long form.
    "notes": "QuanLynx 'Complete Summary' long-format export recommended",
}

# ── Agilent MassHunter Quantitative (CSV results export) ─────────────────────
AGILENT_MASSHUNTER = {
    "vendor": "Agilent MassHunter Quant",
    "delimiter": ",",
    "map": {
        "Name":                 "compound_name",
        "Compound Name":        "compound_name",
        "Data File":            "injection_name",
        "Sample Name":          "sample_description",
        "Type":                 "sample_type",
        "Sample Type":          "sample_type",
        "RT":                   "observed_rt",
        "Area":                 "response",
        "ISTD Resp":            "is_response",
        "Resp. Ratio":          "response_ratio",
        "Exp. Conc.":           "expected_conc",
        "Final Conc.":          "calculated_conc",
        "Calc. Conc.":          "measured_conc",
        "Accuracy":             "pct_deviation",
        "R^2":                  "r2",
        "S/N":                  "signal_to_noise",
        "Qualifier S/N":        "qual_sn",
        "Qualifier Ratio":      "ion_ratios",
        "MI":                   "quant_status",
        "Level":                "level",
        "Acq. Date-Time":       "acq_datetime_str",
        "ISTD":                 "linked_is",
    },
    "notes": "Export from MassHunter Quant 'Results at a Glance' as CSV",
}

# ── SCIEX OS (Analytics results table export) — FDA method's platform ────────
SCIEX_OS = {
    "vendor": "SCIEX OS",
    "delimiter": ",",
    "map": {
        "Component Name":       "compound_name",
        "Component Type":       "compound_type",
        "Sample Name":          "injection_name",
        "Sample ID":            "sample_description",
        "Sample Type":          "sample_type",
        "Retention Time":       "observed_rt",
        "Area":                 "response",
        "IS Area":              "is_response",
        "Area Ratio":           "response_ratio",
        "Expected Concentration": "expected_conc",
        "Calculated Concentration": "calculated_conc",
        "Concentration":        "measured_conc",
        "Accuracy":             "pct_deviation",
        "R":                    "r2",                # SCIEX reports r; squared in QC
        "R^2":                  "r2",
        "Signal / Noise":       "signal_to_noise",
        "Used":                 "included_in_cal",
        "Actual Concentration": "expected_conc",
        "IS Name":              "linked_is",
        "Ion Ratio":            "ion_ratios",
        "Acquisition Date":     "acq_date_str",
        "Acquisition Time":     "acq_time_str",
        "Dilution Factor":      "sample_factor",
    },
    "notes": "SCIEX OS Analytics 'Results Table' export; r is squared in QC "
             "engine when comparing to r² criteria",
}

# ── Native format already matching internal names (the original Excel DATA) ──
NATIVE_FDA_CALCULATOR = {
    "vendor": "FDA Sample Calculator (native)",
    "delimiter": ",",
    "map": {},   # headers already canonical via importer._COL_MAP
    "notes": "Pass-through; columns already match the Excel DATA table",
}


VENDOR_PROFILES: dict[str, dict] = {
    "waters":     WATERS_MASSLYNX,
    "masslynx":   WATERS_MASSLYNX,
    "targetlynx": WATERS_MASSLYNX,
    "agilent":    AGILENT_MASSHUNTER,
    "masshunter": AGILENT_MASSHUNTER,
    "sciex":      SCIEX_OS,
    "sciex_os":   SCIEX_OS,
    "native":     NATIVE_FDA_CALCULATOR,
    "fda":        NATIVE_FDA_CALCULATOR,
}


def get_vendor_profile(vendor: str) -> dict:
    key = vendor.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in VENDOR_PROFILES:
        raise KeyError(
            f"Unknown vendor {vendor!r}; available: "
            f"{sorted(set(p['vendor'] for p in VENDOR_PROFILES.values()))}")
    return VENDOR_PROFILES[key]


def detect_vendor(headers: list[str]) -> str:
    """
    Best-effort auto-detection from a CSV's header row.
    Returns a vendor key; defaults to 'native' if no strong signal.
    """
    h = set(headers)
    if {"Component Name", "Area Ratio"} & h or "Component Name" in h:
        return "sciex"
    if {"Data File", "ISTD Resp"} & h or "Final Conc." in h:
        return "agilent"
    if {"Sample Text", "IS Area"} & h or "Acq.Date" in h:
        return "waters"
    if "Injection Name" in h and "Compound Name" in h:
        return "native"
    return "native"


def load_vendor_profile_yaml(path: str | Path) -> dict:
    """
    Load a custom vendor mapping from a YAML file so labs can add instruments
    without editing code.  Expected structure:

        vendor: "My Instrument"
        delimiter: ","
        map:
          "Their Column": internal_field_name
          ...
    """
    import yaml  # optional dependency; only needed for custom profiles
    data = yaml.safe_load(Path(path).read_text())
    if "map" not in data:
        raise ValueError("YAML vendor profile must contain a 'map' key")
    return data
