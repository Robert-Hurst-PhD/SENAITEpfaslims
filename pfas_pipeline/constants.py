"""
Pipeline constants: QC type codes, result qualifiers and the instrument
export's layout. Every acceptance criterion is the method profile's
(method_profiles.py); the worker holds none of its own.
"""

import os
import re

PROFILES_PATH = os.environ.get("PFAS_PROFILES_PATH", "/data/qc/method_profiles.json")

# ── QC type codes parsed from injection names ─────────────────────────────────
QC_TYPES = {
    "CAL":     "Calibration Standard",
    "ICV":     "Initial Calibration Verification",
    "CCV":     "Continuing Calibration Verification",
    "MB":      "Method Blank",
    "LCS":     "Laboratory Control Sample",
    "LFSM":    "Lab Fortified Sample Matrix",
    "LFSMD":   "Lab Fortified Sample Matrix Duplicate",
    "Dup":     "Sample Duplicate",
    "SpikeCB": "Combined Spike Blank",
    "Sample":  "Environmental Sample",
}

# ── Result qualifier flags ────────────────────────────────────────────────────
QUALIFIER_ND   = "N.D."     # non-detect (below MDL)
QUALIFIER_LOD  = "< LOD"    # below limit of detection
QUALIFIER_BLOQ = "BLoQ"     # below limit of quantitation (detected)
QUALIFIER_ALOQ = "ALoQ"     # above limit of quantitation — report the dilution
QUALIFIER_NC   = "N.C."     # not calculated (no IS)
QUALIFIER_SATURATED = "Saturated"  # detected, but the apex overflowed: no number; shown as "Overflow"

# a peak the analyst deleted in a raw run, and the reasons a calibrator comes
# off its curve for one: its own quantifier's peak, or its isotope
# standard's. Only these are calibrators dropped by hand.
PEAK_DELETED = "peak deleted"
IS_PEAK_DELETED = "isotope standard peak deleted"
MANUAL_DROP_REASONS = (PEAK_DELETED, IS_PEAK_DELETED)
QUALIFIER_SUR = "SUR"      # surrogate flag
QUALIFIER_REC  = "REC"      # review recovery
QUALIFIER_CONF = "CONF"     # identity needs orthogonal confirmation (FDA §10.2(4))

# ── Built-in injection-name patterns (debug-level check only) ───────────────────
# Pattern 1: FDA-CAL-10-260226
# Pattern 2: FDA-ICV-260226, FDA-CCV-260226-01
# Pattern 3: DEMO Water MB 2026-03-13-01  /  DEMO Deer Sample "x"; LFSM High
# Pattern 4/5: Initials Matrix QCtype #######  (7-digit StarLIMS)
INJECTION_PATTERNS = [
    re.compile(r'^FDA-CAL-\d+-\d{6}$'),
    re.compile(r'^FDA-(?:ICV|CCV)-\d{6}(?:-\d+)?$'),
    re.compile(
        r'^[A-Z][A-Z0-9]+ .+ '
        r'(?:MB|LCS|CCV|LFSM|LFSMD|Dup|CAL|SpikeCB|Sample|ICV)'
        r'(?: (?:High|Low|Mid))?(?: Dup\.?)? \d{4}-\d{2}-\d{2}-\d+$'
    ),
    re.compile(
        r'^[A-Z]{2,3} [A-Za-z ]+ '
        r'(?:MB|LCS|CCV|LFSM|LFSMD|Dup|CAL) \d{7}$'
    ),
    re.compile(r'^.+; LFSM.*(?:Dup\.?)?$'),   # parent; LFSM High Dup.
    re.compile(r'^[A-Z][A-Z0-9]+ .+ Sample ".+"$'),  # DEMO Deer Sample "Deer Hamburger"
    re.compile(r'^[A-Z][A-Z0-9]+ .+ Sample \d{7}$'), # DEMO Deer Sample 1234567
]

# StarLIMS 7-digit sample ID (Section 4 of injection name)
STARLIMS_RE = re.compile(r'\b(\d{7})\b')

# ── DATA table column index mapping (1-based, from table19.xml) ──────────────
DATA_COLS = {
    "compound_name":         1,
    "compound_type":         2,
    "compound_group":        5,
    "sample_description":    6,
    "injection_name":        7,
    "sample_group":          8,
    "replicates":            9,
    "replicate_index":      10,
    "injection_volume":     11,
    "sample_position":      12,
    "sample_type":          13,
    "included_in_cal":      14,
    "level":                15,
    "linked_is":            16,
    "cal_ref_compound":     17,
    "observed_rt":          19,
    "rt_relative_to_is":    20,
    "response":             21,
    "manual_changes":       22,
    "is_response":          23,
    "response_ratio":       24,
    "expected_conc":        25,
    "calculated_conc":      26,   # = col 26 in Calibration % sheet
    "conc_units":           27,
    "reporting_limit":      28,
    "pct_deviation":        29,   # = col 27 in IS Raw % from CAL
    "pct_recovery_is":      30,
    "quan_ion":             31,
    "qual_ions":            32,
    "qual_ions_rt":         33,
    "qual_ions_responses":  34,
    "ion_ratios":           37,
    "r2":                   38,
    "rf":                   39,
    "equation":             40,
    "fit_type":             41,
    "origin_type":          42,
    "weight_type":          43,
    "signal_to_noise":      44,
    "qual_sn":              45,
    "quant_status":         50,
    "sample_factor":        72,
    "measured_conc":        52,
    "acq_datetime":         53,
    "result_set_id":        54,
    "expected_ion_ratios":  66,
    "acq_date":             73,
    "acq_time":             74,
    "concat_id":            75,
}
