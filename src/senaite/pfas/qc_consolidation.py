# -*- coding: utf-8 -*-
"""QC profile consolidation migrations (docs/QC_PROFILE_CONSOLIDATION.md,
DECISIONS 2026-10-02 "P1 + P2 approved"). Pure; Python 2.7 and 3.

P1 `drop_dead_keys`: profile keys no code reads any more --
  * instrument_verification.sequence  (ccv.frequency is the one CCV interval;
    the Run Builder builds runs from run_template)
  * extraction_corrections            (salt factors live in
    salt_adjustment_factors)
  * spec_overrides                    (SENAITE specs are a read-only copy);
    a NON-empty one is kept and reported, never silently dropped.

P2 `move_from_rules`: what qc_rules.json held per method moves INTO the
profile, once (marker: `rule_toggles` present) --
  * the method's rule on/off switches  -> profile["rule_toggles"]
  * the ICV % deviation limit          -> instrument_verification.icv.pct_dev_max
  * the CCV warning line               -> instrument_verification.ccv.pct_dev_warn
    (both from qc_types, the values the Calibrations page used; a value the
    profile already has is never replaced).
The other qc_rules.json criteria (global / method_overrides) are NOT copied:
the profile already holds those facts and its values win (D1).
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.qc_consolidation")


def drop_dead_keys(profile, method_id=u""):
    """Remove the retired keys; True if anything changed."""
    changed = False
    iv = profile.get("instrument_verification")
    if isinstance(iv, dict) and "sequence" in iv:
        iv.pop("sequence")
        changed = True
    if "extraction_corrections" in profile:
        ec = profile.get("extraction_corrections") or {}
        if any(v for v in ec.values()) if isinstance(ec, dict) else ec:
            logger.warning("%s: extraction_corrections is not empty (%r); kept -- "
                           "salt factors belong in salt_adjustment_factors", method_id, ec)
        else:
            profile.pop("extraction_corrections")
            changed = True
    if "spec_overrides" in profile:
        if profile.get("spec_overrides"):
            logger.warning("%s: spec_overrides holds per-analyte edits made on SENAITE's "
                           "spec screen; kept for review -- the QC engine never read them",
                           method_id)
        else:
            profile.pop("spec_overrides")
            changed = True
    return changed


def drop_derived_per_analyte(profile):
    """P4: per_analyte rows lose what is now derived -- no_labeled_std (from
    the surrogate links), is_key_analyte and recovery_tier (from the key
    list + links). confirm_ion_mz and notes stay. True if changed."""
    changed = False
    for row in profile.get("per_analyte") or []:
        for k in ("no_labeled_std", "is_key_analyte", "recovery_tier"):
            if isinstance(row, dict) and k in row:
                row.pop(k)
                changed = True
    return changed


def move_from_rules(profile, method_id, saved_rules, defaults=None):
    """Copy this method's slice of a RAW qc_rules.json dict into the profile;
    True if changed. `defaults` = {rule: on} for this method (the library's);
    the stored switches are COMPLETE, so the worker needs no defaults of its
    own. Idempotent: does nothing once `rule_toggles` exists."""
    if "rule_toggles" in profile:
        return False
    saved_rules = saved_rules or {}
    toggles = dict(defaults or {})
    toggles.update((saved_rules.get("method_rule_toggles") or {}).get(method_id) or {})
    profile["rule_toggles"] = dict((k, bool(v)) for k, v in toggles.items())
    qt = saved_rules.get("qc_types") or {}
    iv = profile.setdefault("instrument_verification", {})
    icv_max = (qt.get("ICV") or {}).get("pct_deviation_max")
    if icv_max is not None and (iv.get("icv") or {}).get("pct_dev_max") is None:
        iv.setdefault("icv", {})["pct_dev_max"] = float(icv_max)
    ccv_warn = (qt.get("CCV") or {}).get("pct_deviation_warn")
    if ccv_warn is not None and (iv.get("ccv") or {}).get("pct_dev_warn") is None:
        iv.setdefault("ccv", {})["pct_dev_warn"] = float(ccv_warn)
    return True
