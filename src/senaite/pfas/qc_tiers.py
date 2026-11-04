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

    tier_matrices(profile, tier)   the matrices a tier applies in: every
                        matrix the method supports, or the tier's own list
    in_scope(profile, tier, matrix)  does the tier apply in `matrix` (its
                        own list and those matrices' aliases)

A tier: {"analyte_group": "all" | "key" | "linked" | "no_std" (missing =
"all"), "matrix_scope": "all" | "listed", "matrices": [matrix titles] (a
"listed" tier's own list), "low_level_x_rl": N (applies at or below N x
RL), criteria...}. Selection: a "no labelled standard" tier for such an
analyte; a key-analyte tier listing the matrix; else the first ordinary
"linked" / "all" tier. A low-level tier of the same group whose matrices
include the matrix replaces it when the spiked concentration is at or below
N x RL. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

LOW_LEVEL_KEY = "low_level_x_rl"
ALL = "all"


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
            "{0}: a low-level tier is configured, so the window depends on the "
            "spike level, but {1} is not set. Set the spike level on the "
            "method's QC criteria tab and the reporting limit on its Analytes "
            "tab; the engine does not guess.".format(where, " and ".join(missing)))
    for t in sorted(cond, key=lambda t: float(t[LOW_LEVEL_KEY])):
        if float(conc) <= float(t[LOW_LEVEL_KEY]) * float(rl):
            return t
    return base


def is_listed(tier):
    """Does `tier` apply in matrices it lists (any scope but all)?"""
    return ((tier or {}).get("matrix_scope") or ALL) != ALL


def key_tier_lists(profile_data, matrix, qc_type=None):
    """Does an ordinary key-analyte tier (of `qc_type`, else of any QC type)
    list `matrix` -- its own list or an alias of a listed matrix?"""
    qca = (profile_data or {}).get("qc_acceptance") or {}
    entries = [qca.get(qc_type)] if qc_type else list(qca.values())
    for entry in entries:
        for t in (entry.get("tiers") or []) if isinstance(entry, dict) else []:
            if (isinstance(t, dict) and t.get("analyte_group") == "key" and not t.get(LOW_LEVEL_KEY)
                    and is_listed(t) and in_scope(profile_data, t, matrix)):
                return True
    return False


def _own_list(profile_data, tier):
    """A listed tier's own matrices. A profile not yet migrated (an export
    written before each tier listed its own: scope "tight", no list) still
    names them in its one top-level Tier 1 list, which is read for such a
    tier alone -- never a looser window for want of the migration."""
    if "matrices" not in tier and tier.get("matrix_scope") == "tight":
        return list((profile_data or {}).get("tight_matrices") or [])
    return list(tier.get("matrices") or [])


def tier_matrices(profile_data, tier):
    """The matrices `tier` applies in: every matrix the method supports for
    a tier of all matrices, else the tier's own list."""
    if not is_listed(tier):
        return list((profile_data or {}).get("supported_matrices") or [])
    return _own_list(profile_data, tier)


def in_scope(profile_data, tier, matrix):
    """Does `tier` apply in `matrix`? A tier of all matrices applies in any;
    a listed tier where its own list, or an alias of a listed matrix, names
    it."""
    if not is_listed(tier):
        return True
    aliases = (profile_data or {}).get("matrix_aliases") or {}
    named = set()
    for title in _own_list(profile_data, tier):
        named.add(title.lower().strip())
        for alias in aliases.get(title) or []:
            named.add(alias.lower().strip())
    return (matrix or "").lower().strip() in named


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
            "{0}: no tiers are configured. Set the {1} tiers on the method's QC "
            "criteria tab, or switch that QC type off.".format(where, qc_type))
    tiers = ordinary_tiers(all_tiers) or all_tiers
    for tier in tiers:
        ag = tier.get("analyte_group", "all")
        if ag == "no_std" and is_no_std:
            return tier, "no_std"
        # a key-analyte tier applies where its own list names the matrix
        if ag == "key" and is_listed(tier) and is_key and in_scope(profile_data, tier, matrix):
            return tier, "key_tight"
    for tier in tiers:
        if tier.get("analyte_group", "all") in ("linked", "all"):
            return tier, "default"
    raise Unconfigured(
        "No tier matches {0}: the configured tiers cover neither this analyte "
        "group nor a default. Add a {1} tier for all analytes on the method's "
        "QC criteria tab.".format(where, qc_type))


def low_level_candidates(profile_data, qc_type, base, matrix):
    """The low-level tiers that may replace `base`, smallest N first."""
    entry = _qa_entry(profile_data, qc_type)
    if entry is None or base is None:
        return []
    group = base.get("analyte_group", "all")
    out = [t for t in entry.get("tiers") or [] if t.get(LOW_LEVEL_KEY) and
           t.get("analyte_group", "all") in ("all", group) and
           in_scope(profile_data, t, matrix)]
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
