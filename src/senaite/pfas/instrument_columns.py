# -*- coding: utf-8 -*-
"""
Canonical instrument-column vocabulary — the SINGLE definition of what an
instrument export column can mean (CLAUDE.md §1.3).

Three consumers, one source:

  * ``pfas_pipeline/importer.py`` (Python 3) renames incoming CSV headers onto
    these field names and builds ``InstrumentRow`` from them.
  * ``senaite.pfas.browser.import_studio`` (Python 2.7) offers them as the
    "purpose" vocabulary in the column-mapping grid.
  * saved Import Studio profiles map a vendor's header onto one of these names.

Before this module existed the two lists had drifted: Import Studio's PURPOSES
was a strict SUBSET of the importer's column map, so an analyst literally could
not map ``Reporting Limit`` or ``Expected Ion Ratios`` — the two columns the
BLoQ qualifier and the ion-ratio check depend on. Any field added here becomes
mappable and consumable at the same moment.

The module is deliberately dependency-free and syntax-compatible with BOTH
Python 2.7 (Zope) and Python 3 (worker): plain dicts and tuples only, no
annotations, no f-strings. The worker bind-mounts it (see docker-compose.yml).
"""
from __future__ import absolute_import, unicode_literals

# ── Canonical field name → human label shown in the mapping grid ─────────────
# Order is the order the mapping grid offers them in; grouped by purpose.
CANONICAL_FIELDS = [
    ("ignore",              "Ignore"),

    # Identifiers
    ("compound_name",       "Analyte / Compound Name"),
    ("compound_type",       "Compound Type (native analyte / IS flag)"),
    ("compound_group",      "Compound Group (isomer family, e.g. PFOS)"),
    ("injection_name",      "Injection / Run Name (data file / vial label)"),
    ("sample_description",  "Sample Description (free-text bench annotation)"),
    ("sample_id",           "Sample Identifier (client-facing ID or barcode)"),
    ("sample_group",        "Sample Group"),
    ("sample_type",         "Sample Type (Cal / QC / Unknown / Blank)"),
    ("level",               "Calibration Level"),
    ("included_in_cal",     "Included in Calibration (yes/no)"),

    # Concentrations
    # measured_conc   = straight off the calibration curve, BEFORE sample-prep
    #                   corrections (dilution, matrix, salt, weight).
    # calculated_conc = the REPORTED value, AFTER those adjustments. This is
    #                   the one that carries the sample factor.
    ("measured_conc",       "Measured Conc. (pre-adjustment, direct from cal. curve)"),
    ("calculated_conc",     "Calculated / Final Conc. (post-adjustment, reported value)"),
    ("expected_conc",       "Expected / Standard Concentration (cal. standard target)"),
    ("reporting_limit",     "Reporting Limit (drives the BLoQ qualifier)"),
    ("conc_units",          "Concentration Units (what the results are reported in)"),
    ("sample_factor",       "Sample Dilution / Weight Factor"),

    # Instrument response
    ("response",            "Raw Peak Area (native analyte)"),
    ("is_response",         "IS Peak Area"),
    ("response_ratio",      "Area Ratio (native / IS)"),
    ("pct_recovery_is",     "% Recovery (Internal Standard)"),
    ("linked_is",           "Linked Internal Standard"),
    ("cal_ref_compound",    "Calibration Reference Compound"),

    # Chromatography
    ("observed_rt",         "Observed Retention Time (RT)"),
    ("rt_relative_to_is",   "RT Relative to IS (RRT)"),
    ("signal_to_noise",     "Signal / Noise (S/N)"),
    ("qual_sn",             "Qualifier Ion S/N"),
    ("ion_ratios",          "Observed Ion Ratio (qualifier / quantifier)"),
    ("expected_ion_ratios", "Expected Ion Ratio (the acceptance target)"),

    # QC & calibration
    ("pct_deviation",       "% Deviation / Accuracy"),
    ("r2",                  "Calibration r or r squared"),
    ("quant_status",        "Quantitation Status / Flags (pass, fail, review)"),

    # Metadata
    ("acq_datetime_str",    "Acquisition Date + Time (single column)"),
    ("acq_date_str",        "Acquisition Date"),
    ("acq_time_str",        "Acquisition Time"),
    ("injection_volume",    "Injection Volume"),
    ("sample_position",     "Sample Position / Vial"),
    ("manual_changes",      "Manual Changes / Integration Edits"),
]

FIELD_LABELS = dict(CANONICAL_FIELDS)

# Fields it never makes sense to have two source columns for. Mapping two
# columns onto one of these silently destroyed data, because pandas' rename
# collapses duplicate targets and only the last one survives.
SINGLE_VALUED_FIELDS = frozenset(
    name for name, _ in CANONICAL_FIELDS if name != "ignore")


# ── Native header → canonical field ──────────────────────────────────────────
# The FDA Sample Calculator / SCIEX OS "native" export already uses these exact
# header strings, so a native file needs no vendor mapping at all: the importer
# applies this table directly. Import Studio uses it to suggest a clean
# pass-through mapping instead of guessing with regexes.
NATIVE_COLUMN_MAP = {
    "Compound Name":                  "compound_name",
    "Compound Type":                  "compound_type",
    "Compound Group":                 "compound_group",
    "Sample Description":             "sample_description",
    "Injection Name":                 "injection_name",
    "Sample Group":                   "sample_group",
    "Injection Volume":               "injection_volume",
    "Sample Position":                "sample_position",
    "Sample Type":                    "sample_type",
    "Included in Calibration":        "included_in_cal",
    "Level":                          "level",
    "Linked Internal Standard":       "linked_is",
    "Calibration Reference Compound": "cal_ref_compound",
    "Observed RT (min)":              "observed_rt",
    "RT Relative to IS":              "rt_relative_to_is",
    "Response":                       "response",
    "Manual Changes":                 "manual_changes",
    "IS Response":                    "is_response",
    "Response Ratio":                 "response_ratio",
    "Expected Concentration":         "expected_conc",
    "Calculated Concentration":       "calculated_conc",
    "Reporting Limit":                "reporting_limit",
    "Concentration Units":            "conc_units",
    "% Deviation":                    "pct_deviation",
    "% Recovery (IS)":                "pct_recovery_is",
    "Ion Ratios":                     "ion_ratios",
    "Expected Ion Ratios":            "expected_ion_ratios",
    "R2":                             "r2",
    "Signal to Noise":                "signal_to_noise",
    "Qual Ions Signal to Noise":      "qual_sn",
    "Quantitation Status":            "quant_status",
    "Measured Concentration":         "measured_conc",
    "Acquisition Date Time":          "acq_datetime_str",
    "Acquisition Date":               "acq_date_str",
    "Acquisition Time":               "acq_time_str",
    "Sample Factor":                  "sample_factor",
}


def duplicate_targets(column_map):
    """Return {canonical_field: [source columns]} for every field claimed more
    than once, ignoring "ignore".

    A mapping with duplicates is not merely untidy: pandas' ``rename`` produces
    two columns with the same name and ``to_dict()`` keeps only the last, so
    one of the source columns is discarded without a word.
    """
    seen = {}
    for source, target in (column_map or {}).items():
        if not target or target == "ignore":
            continue
        if target not in SINGLE_VALUED_FIELDS:
            continue
        seen.setdefault(target, []).append(source)
    return dict((t, sorted(cols)) for t, cols in seen.items() if len(cols) > 1)
