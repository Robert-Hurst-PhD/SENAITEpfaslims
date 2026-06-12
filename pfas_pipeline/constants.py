"""
Compound lists and acceptance criteria extracted directly from
FDA_Sample_Calculator_V13.xlsm (verified against actual sheet data).

Sheet 1  = IS Raw         → INTERNAL_STANDARDS
Sheet 2  = RT Deviation   → ANALYTES (native)
Sheet 3  = Qual-Quan      → same analyte list
Sheet 4  = Calibration %  → same analyte list
Sheet 5  = Summary Sheet  → actual result output seen in real data
Sheet 6  = QC Log         → QC flag format
"""

import json
import logging
import os
import re

logger = logging.getLogger("pfas_pipeline.constants")

PROFILES_PATH = os.environ.get("PFAS_PROFILES_PATH", "/data/qc/method_profiles.json")

# ── Internal Standards & Surrogates (Sheet 1, row 1, odd columns C→AQ) ───────
INTERNAL_STANDARDS = [
    "13C4-PFOA",
    "13C2,D4-10:2FTS",
    "13C2,D4-4:2FTS",
    "13C2,D4-6:2FTS",
    "13C2,D4-8:2FTS",
    "13C2-PFDA",
    "13C2-PFDoA",
    "13C2-PFHxDA",
    "13C2-PFTeDA",
    "13C2-PFUDA",
    "13C3-GenX (HFPO-DA)",
    "13C3-PFBA",
    "13C3-PFBS",
    "13C3-PFHxS",
    "13C3-PFPeA",
    "13C4-PFHpA",
    "13C5-PFHxA",
    "13C5-PFNA",
    "13C8-FOSA",
    "13C8-PFOA",
    "13C8-PFOS",
]

# ── Native PFAS analytes (Sheet 2, row 1, confirmed from real batch data) ────
ANALYTES = [
    "10:2 FTS",
    "11Cl-PF3OUdS",
    "4:2 FTS",
    "6:2FTS",
    "8:2 FTS",
    "9Cl-PF3ONS",
    "DONA",
    "FOSA",
    "GenX (HFPO-DA)",
    "PFBA",
    "PFBS",
    "PFDA",
    "PFDoA",
    "PFDoS",
    "PFDS",
    "PFHpA",
    "PFHpS",
    "PFHxA",
    "PFHxDA",
    "lr-PFHxS",
    "PFNA",
    "PFNS",
    "PFOA",
    "PFODA",
    "lr-PFOS",
    "PFPeA",
    "PFPeS",
    "PFTeDA",
    "PFTrDA",
    "PFTrDS",
    "PFUDA",
    "PFUnDS",
    "br-PFOS",
    "br-PFHxS",
]

# ── Non-isotopically linked analytes (no dedicated IS; flagged as N.C.) ───────
NON_ISO_ANALYTES = frozenset({
    "9Cl-PF3ONS", "11Cl-PF3OUdS", "PFDoS", "PFDS",
    "PFNS", "PFODA", "PFPeS", "PFTrDA", "PFTrDS", "PFUnDS",
})

ALL_COMPOUNDS = INTERNAL_STANDARDS + ANALYTES

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

# ── Result qualifier flags (matching Summary Sheet output) ────────────────────
QUALIFIER_ND   = "N.D."     # non-detect (below MDL)
QUALIFIER_LOD  = "< LOD"    # below limit of detection
QUALIFIER_BLOQ = "BLoQ"     # below limit of quantitation
QUALIFIER_NC   = "N.C."     # not calculated (no IS)
QUALIFIER_SUR  = "SUR"      # surrogate flag
QUALIFIER_REC  = "REC"      # review recovery

# ── Default acceptance criteria (FDA 32-PFAS baseline) ───────────────────────
# These values are used when no exported method profile JSON file is found.
# When /data/qc/method_profiles.json exists, reload_criteria() loads the FDA_32PFAS
# profile values at the start of each batch run, keeping the engine in sync with
# changes made by managers in the SENAITE Method Profile control panel.
# The seeded FDA_32PFAS profile defaults match these values, so behaviour is
# unchanged on first install — see QUESTIONS.md Q-005 for the FDA 0.990 vs 0.995 open question.

_DEFAULT_CRITERIA = {
    # Calibration curve
    "cal_r2_min":            0.995,
    "cal_pct_dev_max":       0.20,    # ±20% as fraction
    # CCV / ICV
    "ccv_pct_dev_max":       0.20,    # ±20% as fraction (not yet used by basic engine)
    # IS / surrogate response (vs. average of Standards in batch)
    "is_response_drift_pct": 0.50,    # ±50% of batch average → flag SUR (as fraction)
    # LFSM / LCS percent recovery
    "recovery_min_pct":      50.0,
    "recovery_max_pct":     150.0,
    # LFSMD RPD
    "rpd_max_pct":           30.0,
    # RT deviation from batch average
    "rt_dev_abs_min":         0.10,   # ±0.10 min
    # Signal-to-noise
    "sn_min":                 3.0,
    # Qual/Quan ion ratio tolerance (±30% of expected ratio)
    "ion_ratio_tol_pct":     30.0,
    # MDL — EPA 40 CFR Part 136 Appendix B statistical constants, NOT lab choices.
    # These stay hardcoded; they are not exposed in the Method Profile UI.
    "mdl_min_replicates":     7,
    "t_values": {
        7:  3.143, 8:  2.998, 9:  2.896, 10: 2.821,
        11: 2.764, 12: 2.718, 13: 2.681, 14: 2.650,
        15: 2.624, 16: 2.602, 17: 2.583, 18: 2.567,
        19: 2.552, 20: 2.539,
    },
}


def _build_criteria_from_profile(profile):
    """Map a method profile dict onto the flat CRITERIA keys the engine uses."""
    crit = dict(_DEFAULT_CRITERIA)

    cal = profile.get("calibration", {})
    if cal.get("r2_min") is not None:
        crit["cal_r2_min"] = float(cal["r2_min"])
    if cal.get("point_pct_dev_max") is not None:
        # Profile stores %, engine expects fraction
        crit["cal_pct_dev_max"] = float(cal["point_pct_dev_max"]) / 100.0

    is_ = profile.get("is", {})
    if is_.get("vs_ical_avg_max") is not None and is_.get("vs_ical_avg_min") is not None:
        # Engine uses a symmetric ±drift fraction; derive from the wider bound
        avg_max = float(is_["vs_ical_avg_max"])
        crit["is_response_drift_pct"] = (avg_max - 100.0) / 100.0

    conf = profile.get("confirmation", {})
    if conf.get("ion_ratio_tol_pct") is not None:
        crit["ion_ratio_tol_pct"] = float(conf["ion_ratio_tol_pct"])
    if conf.get("rt_tol_abs_min") is not None:
        crit["rt_dev_abs_min"] = float(conf["rt_tol_abs_min"])
    elif conf.get("rrt_tol_pct") is not None:
        # RRT % tolerance used by the profiled check; legacy engine uses abs minutes
        # Keep the default abs value — the profiled check supersedes it for matched batches
        pass
    if conf.get("sn_quan_min") is not None:
        crit["sn_min"] = float(conf["sn_quan_min"])

    # NOTE: recovery_min_pct / recovery_max_pct / rpd_max_pct are intentionally
    # NOT mapped here. The lfsm_check / lfsmd_check functions that use those keys
    # are not yet wired into auto_evaluate. Keeping the generic defaults avoids a
    # silent behaviour change on install. Wire these when the profiled checks land.

    return crit


def reload_criteria(profiles_path=None, method_id="FDA_32PFAS"):
    """
    Reload CRITERIA in-place from the exported method profile JSON.
    Called at the top of run_pipeline() so each batch picks up the latest
    values without a worker restart.

    Falls back to _DEFAULT_CRITERIA if the file is absent or unreadable.
    The MDL constants (mdl_min_replicates, t_values) are never overridden.
    """
    if profiles_path is None:
        profiles_path = PROFILES_PATH

    if not os.path.exists(profiles_path):
        return  # keep current values (defaults on first run)

    try:
        with open(profiles_path) as fh:
            all_profiles = json.load(fh)
        profile = all_profiles.get(method_id)
        if profile is None:
            logger.warning(
                "reload_criteria: method %r not in %s; keeping current values",
                method_id, profiles_path,
            )
            return
        new_crit = _build_criteria_from_profile(profile)
        # Preserve MDL constants — they are not UI-configurable
        new_crit["mdl_min_replicates"] = _DEFAULT_CRITERIA["mdl_min_replicates"]
        new_crit["t_values"] = _DEFAULT_CRITERIA["t_values"]
        CRITERIA.clear()
        CRITERIA.update(new_crit)
        logger.info("Loaded CRITERIA from %s (method=%s)", profiles_path, method_id)
    except (IOError, OSError, ValueError) as exc:
        logger.warning("reload_criteria: could not load %s: %s", profiles_path, exc)


# Mutable dict — updated in-place by reload_criteria() so that the engine
# functions that already imported CRITERIA see the refreshed values.
CRITERIA = dict(_DEFAULT_CRITERIA)

# Load from file immediately if the export already exists
reload_criteria()

# ── Injection name validation patterns (VBA ValidateInjectionNames) ───────────
# Pattern 1: FDA-CAL-10-260226
# Pattern 2: FDA-ICV-260226, FDA-CCV-260226-01
# Pattern 3: KCP Water MB 2026-03-13-01  /  KCP Deer Sample "x"; LFSM High
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
    re.compile(r'^[A-Z][A-Z0-9]+ .+ Sample ".+"$'),  # KCP Deer Sample "Deer Hamburger"
    re.compile(r'^[A-Z][A-Z0-9]+ .+ Sample \d{7}$'), # KCP Deer Sample 1234567
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
    "response_ratio":       24,   # = col 18 in VBA CHOOSECOLS calls
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
