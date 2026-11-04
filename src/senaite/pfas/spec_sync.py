# -*- coding: utf-8 -*-
"""
QC acceptance windows per method x QC type x matrix, as ranges (pure).

No SENAITE AnalysisSpec is written from these: a spec judges an analysis's
RESULT (a concentration) against its range, and these ranges are recovery
percentages. The method profile (with a project's specs applied) is the only
home of the criteria; the method profile's Recovery Tiers tab reads them
from there.

This module gives which tier each analyte is in and a QC type's limits per
tier (_build_kw_to_tier, _tier_limits), read by Setup references.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.spec_sync")

def _build_kw_to_tier(profile):
    """Return {keyword: tier_int(1|2|3)} for every analyte in master_analyte_set.

    Tier values: 1=key (tight), 2=linked (standard), 3=no-labeled-std.
    "No labelled standard" is derived from the method's own surrogate links
    and key analytes are the method's own list -- the
    engine's rule, so the specs match what results are judged by.
    """
    from senaite.pfas.method_profile_sections import key_analytes, no_std_set
    keys, no_std = set(key_analytes(profile)), no_std_set(profile)
    return dict((kw, 3 if kw in no_std else (1 if kw in keys else 2))
                for kw in profile.get("master_analyte_set", []))


def _tier_limits(qc_acceptance, qc_type):
    """Return {1: {min,max}, 2: {min,max}, 3: {min,max}} for a QC type.

    Returns None when the QC type is disabled or has no recovery tiers.
    """
    qca = qc_acceptance.get(qc_type, {})
    if not qca.get("enabled"):
        return None

    tier_limits = {1: None, 2: None, 3: None}
    fallback = None

    for t in qca.get("tiers", []):
        r_min = t.get("recovery_min")
        r_max = t.get("recovery_max")
        if r_min is None and r_max is None:
            continue
        # A low-level tier (low_level_x_rl) applies only to spikes at or
        # below N x RL, a condition a range cannot hold: it is skipped, never
        # read as "all" (it would become every analyte's window).
        if t.get("low_level_x_rl") is not None:
            continue
        lims = {"min": r_min, "max": r_max}
        ag = t.get("analyte_group", "all")
        if ag == "key":
            tier_limits[1] = lims
        elif ag == "linked":
            tier_limits[2] = lims
        elif ag == "no_std":
            tier_limits[3] = lims
        else:
            fallback = lims

    # Apply fallback to tiers that have no specific entry
    for n in (1, 2, 3):
        if tier_limits[n] is None and fallback:
            tier_limits[n] = fallback

    has_recovery = any(v for v in tier_limits.values())
    return tier_limits if has_recovery else None
