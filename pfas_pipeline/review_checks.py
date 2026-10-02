"""The QC checks a reviewer must make on each injection role -- what the run
queue prompts for at review time.

Moved out of injection_builder.py (reuse review R10, 2026-10-02): that
module's sequence builder was used only by tests (production runs come from
the Run Builder in SENAITE) and is deleted; this table is live.
"""

from __future__ import annotations


# Map QC type → list of review checks the analyst must perform.
# This is what drives the "run queue prompts what QC to look for" requirement.
REVIEW_CHECKS: dict[str, list[str]] = {
    "CAL":    ["calibration_pct_dev", "r_squared", "rt_deviation", "ion_ratio"],
    "ICV":    ["ccv_pct_dev", "is_response", "rt_deviation"],
    "CCV":    ["ccv_pct_dev", "is_response", "rt_deviation", "ion_ratio"],
    "MB":     ["blank_contamination", "is_response", "lod_check",
              "surrogate_recovery", "identity_confirmation"],
    # The other blanks. Without these, classify_injection's new roles fell back
    # to REVIEW_CHECKS["Sample"] and a blank was given the CHECKS OF A CLIENT
    # SAMPLE — bloq/lod qualifiers instead of a contamination check.
    "MxB":    ["blank_contamination", "is_response", "surrogate_recovery"],
    "LRB":    ["blank_contamination", "is_response", "surrogate_recovery"],
    "CCB":    ["blank_contamination", "is_response"],
    "LFB":    ["recovery", "is_response", "surrogate_recovery"],
    "LFSM":   ["lfsm_recovery", "is_response", "ion_ratio", "rt_deviation",
               "surrogate_recovery", "identity_confirmation"],
    "LFSMD":  ["lfsmd_rpd", "lfsm_recovery", "is_response",
               "surrogate_recovery", "identity_confirmation"],
    "Dup":    ["duplicate_rpd", "is_response", "surrogate_recovery"],
    "Sample": ["is_response", "ion_ratio", "rt_deviation", "signal_to_noise",
               "bloq_check", "lod_check", "surrogate_recovery",
               "identity_confirmation"],
}
# `identity_confirmation` is on the four roles a RESULT is reported for -- the same
# set build_summary calls REPORTED_ROLES (Sample, MB, LFSM, LFSMD) -- because
# FDA §10.2(4) is an obligation about a reported positive identification. Not on
# Dup, which reports no result of its own, nor on any solvent injection.
#
# `surrogate_recovery` is on the EXTRACTED injections and only those. A
# surrogate is spiked into the sample before extraction, so its recovery
# measures the extraction; a calibrator, ICV, CCV or solvent blank (CCB) is
# never extracted, and a "recovery" computed on one would be a number with
# nothing behind it. MB/MxB/LRB and LFB ARE extracted, so they carry it.
