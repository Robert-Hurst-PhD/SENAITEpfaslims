"""
QC acceptance criteria and pipeline constants.

Analyte display names and IS lists have been moved to method_profiles.py
(get_analyte_list / get_is_list / get_non_iso_set) so they are owned by
the method profile rather than hard-coded here.
"""

import json
import logging
import os
import re

logger = logging.getLogger("pfas_pipeline.constants")

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

# ── Result qualifier flags (matching Summary Sheet output) ────────────────────
QUALIFIER_ND   = "N.D."     # non-detect (below MDL)
QUALIFIER_LOD  = "< LOD"    # below limit of detection
QUALIFIER_BLOQ = "BLoQ"     # below limit of quantitation (detected)
QUALIFIER_ALOQ = "ALoQ"     # above limit of quantitation — report the dilution
QUALIFIER_NC   = "N.C."     # not calculated (no IS)
QUALIFIER_SUR  = "SUR"      # surrogate flag
QUALIFIER_REC  = "REC"      # review recovery
QUALIFIER_CONF = "CONF"     # identity needs orthogonal confirmation (FDA §10.2(4))

# ── Default acceptance criteria (FDA 32-PFAS baseline) ───────────────────────
# These values are used when no exported method profile JSON file is found.
# When /data/qc/method_profiles.json exists, reload_criteria() loads the FDA_32PFAS
# profile values at the start of each batch run, keeping the engine in sync with
# changes made by managers in the SENAITE Method Profile control panel.
# The seeded FDA_32PFAS profile defaults match these values, so behaviour is
# unchanged on first install — see QUESTIONS.md Q-005 for the FDA 0.990 vs 0.995 open question.

_DEFAULT_CRITERIA = {
    # Calibration curve
    # No global default: Q-005 established r2 is per-method, set in the Method
    # Profile UI. 0.990 is FDA 32-PFAS's value and is only a floor for a
    # profile that somehow carries none.
    "cal_r2_min":            0.990,
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
    "sn_min":                 3.0,   # alias of sn_quan_min
    # Minimum S/N for QUANTITATION -- below it a result is estimated (J).
    "sn_quan_min":            3.0,
    # Minimum S/N on the CONFIRMATION (qualifier) ion -- below it the
    # identification is not confirmed (N.C.). None = not configured, and
    # the qualifier-ion branch then refuses to judge rather than borrowing
    # the quantitation threshold, which is what it used to do.
    "sn_confirm_min":         None,
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

    # Read the NESTED instrument_verification structure first. The flat keys
    # (calibration, is, confirmation) were retired by
    # migrate_profile_structure and are all null on a migrated profile, so
    # every threshold silently fell back to _DEFAULT_CRITERIA — which happened
    # to carry the same numbers, masking the disconnect. Editing the value in
    # the Method Profile UI had no effect on the engine at all.
    iv = profile.get("instrument_verification") or {}

    cal = iv.get("calibration") or profile.get("calibration", {})
    if cal.get("r2_min") is not None:
        crit["cal_r2_min"] = float(cal["r2_min"])
    if cal.get("point_pct_dev_max") is not None:
        # Profile stores %, engine expects fraction
        crit["cal_pct_dev_max"] = float(cal["point_pct_dev_max"]) / 100.0

    is_ = iv.get("is_response") or profile.get("is", {})
    if is_.get("vs_ical_avg_max") is not None and is_.get("vs_ical_avg_min") is not None:
        # Engine uses a symmetric ±drift fraction; derive from the wider bound
        avg_max = float(is_["vs_ical_avg_max"])
        crit["is_response_drift_pct"] = (avg_max - 100.0) / 100.0

    conf = iv.get("confirmation") or profile.get("confirmation", {})
    if conf.get("ion_ratio_tol_pct") is not None:
        crit["ion_ratio_tol_pct"] = float(conf["ion_ratio_tol_pct"])
    if conf.get("rt_tol_abs_min") is not None:
        crit["rt_dev_abs_min"] = float(conf["rt_tol_abs_min"])
    elif conf.get("rrt_tol_pct") is not None:
        # RRT % tolerance used by the profiled check; legacy engine uses abs minutes
        # Keep the default abs value — the profiled check supersedes it for matched batches
        pass
    # Two DIFFERENT signal-to-noise thresholds, and they answer different
    # questions. `sn_quan_min` is the minimum S/N for QUANTITATION -- below it a
    # peak is detected but its value is only an estimate, which is why the
    # `sn` failure type carries code J ("estimated"). `sn_confirm_min` is the
    # minimum S/N on the CONFIRMATION (qualifier) ion -- below it the
    # identification itself is not confirmed.
    #
    # Only the first was mapped, into a key named `sn_min`, and BOTH branches of
    # signal_to_noise_check then compared against it -- so the qualifier ion was
    # judged against the quantitation threshold. On EPA 1633A, the one method
    # with the check enabled, that is 3.0 against a configured confirmation
    # limit of 1.0: qualifier ions between 1 and 3 were failed by a criterion
    # the method does not apply to them.
    if conf.get("sn_quan_min") is not None:
        crit["sn_quan_min"] = float(conf["sn_quan_min"])
        crit["sn_min"] = crit["sn_quan_min"]   # back-compat alias, same value
    if conf.get("sn_confirm_min") is not None:
        crit["sn_confirm_min"] = float(conf["sn_confirm_min"])

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
