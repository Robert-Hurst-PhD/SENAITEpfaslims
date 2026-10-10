# -*- coding: utf-8 -*-
"""Which acceptance tier of a method profile applies: ONE function for the
worker's run QC (pfas_pipeline.method_profiles, loaded by path) and the
studies (method studies, Study Designer). A study's recovery and RSD / RPD
limits are therefore the method's, chosen exactly as a run's are.

    select_tier(profile_data, qc_type, analyte, matrix, conc=None, rl=None,
                is_key=False, is_no_std=False, where="")
        -> (tier dict, branch) or None (the QC type is off); raises
           Unconfigured when nothing applies or a needed value is missing.
           branch: "no_std" | "key_tight" | "default"
    spread_limit(tier)  the tier's RSD / RPD limit (one limit: rsd_max, else
                        rpd_max)
    study_limits(...)   a study's recovery window and spread limit, or the
                        problem that leaves them unset

A tier: {"analyte_group": "all" | "key" | "linked" | "no_std" (missing =
"all"), "matrix_scope": "all" | "tight", "low_level_x_rl": N (applies at
or below N x RL), criteria...}. Selection: a "no labelled standard" tier
for such an analyte; a key-analyte tier in a tight matrix (the profile's
tight_matrices and their aliases); else the first ordinary "linked" / "all"
tier. A low-level tier of the same group and scope replaces it when the
spiked concentration is at or below N x RL. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

LOW_LEVEL_KEY = "low_level_x_rl"


class Unconfigured(ValueError):
    """The profile does not say: the caller reports a gap, never guesses."""


def ordinary_tiers(tiers):
    return [t for t in tiers or [] if not t.get(LOW_LEVEL_KEY)]


def low_level_tier(tiers, base, applies, conc, rl, where):
    """The low-level tier whose condition holds (smallest N first), else
    `base`. Refuses when one could apply but conc / RL are unknown."""
    cond = [t for t in tiers or [] if t.get(LOW_LEVEL_KEY) and applies(t)]
    if not cond:
        return base
    missing = [n for n, v in (("the fortified concentration", conc),
                              ("the analyte's RL for this matrix", rl)) if not v]
    if missing:
        raise Unconfigured(
            "{0}: a low-level tier (applies at <= N x RL) is configured, so the "
            "window depends on the spike level, but {1} is not set. Enter it "
            "(Method Profiles -> Recovery Tiers spike levels / Reporting "
            "Limits) -- the engine does not guess.".format(where, " and ".join(missing)))
    for t in sorted(cond, key=lambda t: float(t[LOW_LEVEL_KEY])):
        if float(conc) <= float(t[LOW_LEVEL_KEY]) * float(rl):
            return t
    return base


def is_tight_matrix(profile_data, matrix):
    aliases = (profile_data or {}).get("matrix_aliases") or {}
    tight = set()
    for title in (profile_data or {}).get("tight_matrices") or []:
        tight.add(title.lower().strip())
        for alias in aliases.get(title) or []:
            tight.add(alias.lower().strip())
    return (matrix or "").lower().strip() in tight


def _qa_entry(profile_data, qc_type):
    entry = ((profile_data or {}).get("qc_acceptance") or {}).get(qc_type)
    return None if entry is None or not entry.get("enabled", True) else entry


def base_tier(profile_data, qc_type, matrix, is_key=False, is_no_std=False, where=""):
    """The ORDINARY tier (before any low-level replacement) and its branch,
    or None (the QC type is off); raises Unconfigured."""
    entry = _qa_entry(profile_data, qc_type)
    if entry is None:
        return None
    all_tiers = entry.get("tiers") or []
    where = where or "{0} / {1}".format(matrix or "(no matrix)", qc_type)
    if not all_tiers:
        raise Unconfigured(
            "{0}: no tiers are configured. Set them in Method Profiles -> QC "
            "Types -> {1}, or disable that QC type.".format(where, qc_type))
    tiers = ordinary_tiers(all_tiers) or all_tiers
    tight = is_tight_matrix(profile_data, matrix)
    for tier in tiers:
        ag = tier.get("analyte_group", "all")
        ms = tier.get("matrix_scope", "all")
        if ag == "no_std" and is_no_std:
            return tier, "no_std"
        if ag == "key" and ms == "tight" and is_key and tight:
            return tier, "key_tight"
    for tier in tiers:
        if tier.get("analyte_group", "all") in ("linked", "all"):
            return tier, "default"
    raise Unconfigured(
        "No tier matches {0}: the configured tiers cover neither this analyte "
        "group nor a default. Add a tier with analyte_group 'all' in Method "
        "Profiles -> QC Types -> {1}.".format(where, qc_type))


def low_level_candidates(profile_data, qc_type, base, matrix):
    """The low-level tiers that may replace `base`, smallest N first."""
    entry = _qa_entry(profile_data, qc_type)
    if entry is None or base is None:
        return []
    tight = is_tight_matrix(profile_data, matrix)
    group = base.get("analyte_group", "all")
    out = [t for t in entry.get("tiers") or [] if t.get(LOW_LEVEL_KEY) and
           t.get("analyte_group", "all") in ("all", group) and
           (t.get("matrix_scope", "all") != "tight" or tight)]
    return sorted(out, key=lambda t: float(t[LOW_LEVEL_KEY]))


def select_tier(profile_data, qc_type, analyte, matrix, conc=None, rl=None,
                is_key=False, is_no_std=False, where=""):
    where = where or "{0} / {1} / {2}".format(analyte, matrix or "(no matrix)", qc_type)
    chosen = base_tier(profile_data, qc_type, matrix, is_key, is_no_std, where)
    if chosen is None:
        return None
    tier, branch = chosen
    lows = low_level_candidates(profile_data, qc_type, tier, matrix)
    return low_level_tier(lows, tier, lambda _t: True, conc, rl, where), branch


def spread_limit(tier):
    """One RSD / RPD limit: the two are treated the same."""
    for k in ("rsd_max", "rpd_max"):
        v = (tier or {}).get(k)
        if v not in (None, ""):
            return float(v)
    return None


def study_limits(profile_data, qc_type, analyte, matrix, conc=None, rl=None,
                 is_key=False, is_no_std=False):
    """{"recovery_min", "recovery_max", "spread", "problem"}: a study's limits
    for one analyte at one level -- the run's tier, never a typed copy."""
    where = "{0} / {1} / {2}".format(analyte, matrix or "(no matrix)", qc_type)
    try:
        chosen = select_tier(profile_data, qc_type, analyte, matrix, conc, rl,
                             is_key, is_no_std, where)
    except Unconfigured as e:
        return {"problem": "{0}".format(e)}
    if chosen is None:
        return {"problem": "{0}: the method profile does not judge {1} (that QC "
                           "type is off or absent).".format(where, qc_type)}
    tier = chosen[0]
    return {"recovery_min": _f(tier.get("recovery_min")),
            "recovery_max": _f(tier.get("recovery_max")),
            "spread": spread_limit(tier), "problem": None}


def _f(v):
    return None if v in (None, "") else float(v)
