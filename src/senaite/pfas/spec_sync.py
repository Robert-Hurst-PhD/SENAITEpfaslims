# -*- coding: utf-8 -*-
"""
QC acceptance windows per method x QC type x matrix, as ranges (pure).

RETIRED as a sync: this module used to write one
SENAITE AnalysisSpec per method x QC type x matrix after every profile save,
and spec_reverse wrote core edits back. No sample ever used one, and they
could not be used: a spec judges an analysis's RESULT (a concentration)
against its range, and these ranges are recovery percentages. The method
profile (with a project's specs applied) is the only home of the criteria;
@@pfas-specifications reads them from there.

What stays: how a QC type's tiers become per-analyte ranges for one matrix
(ranges_for), shared by the Specifications page and Setup references.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.spec_sync")

PFAS_SPEC_AUDIT_KEY = "senaite.pfas.spec_sync_audit"   # kept: old audit entries

# QC type → human label used in SampleType / AnalysisSpec titles
_QC_LABELS = {
    "LCS":   "Laboratory Control Sample",
    "LFSM":  "Lab Fortified Sample Matrix",
    "LFB":   "Laboratory Fortified Blank",
    "LFSMD": "Lab Fortified Sample Matrix Dup",
    "MB":    "Method Blank",
    "LRB":   "Laboratory Reagent Blank",
}

# ── Internal helpers ──────────────────────────────────────────────────────────

def _current_user():
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        uid = user.getId()
        return uid or "system"
    except Exception:
        return "system"


def _build_kw_to_tier(profile):
    """Return {keyword: tier_int(1|2|3)} for every analyte in master_analyte_set.

    Tier values: 1=key (tight), 2=linked (standard), 3=no-labeled-std.
    "No labelled standard" is derived from the method's own surrogate links
    and key analytes are the method's own list (consolidation P4) -- the
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
        # A low-level tier (low_level_x_rl) applies only to spikes
        # at or below N x RL -- a condition a SENAITE spec cannot hold. It used
        # to fall through as "all" and, listed after the ordinary tier, became
        # every analyte's window (EPA 537.1 LFSM showed 50-150 % for every
        # result, not 70-130 %).
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


# FDA Table 10-1: key analytes are held to the tight range (80–120) only in
# these matrices; elsewhere they fall to the linked/all range. Seed default per
# ("egg/meat/seafood"); a profile may override via its own
# `tight_matrices` list (configurable, not hardcoded — golden rule #1).
_DEFAULT_TIGHT_MATRICES = ("Eggs", "Meat / Muscle", "Fish / Seafood")


def get_tight_matrices(profile):
    """Matrix titles where matrix_scope='tight' tiers apply, from the profile
    (falls back to the seed trio)."""
    tm = profile.get("tight_matrices")
    if isinstance(tm, (list, tuple)) and tm:
        return list(tm)
    return list(_DEFAULT_TIGHT_MATRICES)


def effective_tier(tier, is_tight_matrix):
    """FDA matrix-dependent tier: tier 1 (key/tight 80–120) applies only in
    tight matrices; elsewhere key analytes use the tier-2 (all) range."""
    if tier == 1 and not is_tight_matrix:
        return 2
    return tier


def matrix_slug(title):
    """Stable id fragment for a matrix title (e.g. 'Meat / Muscle' -> 'meat-muscle')."""
    out = []
    for ch in (title or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def same_ranges(old_rows, new_rows):
    """True when two ResultsRange lists set the same limits per analyte
    (numbers compared as numbers; row order and comments ignored)."""
    def norm(rows):
        out = {}
        for r in rows or []:
            vals = []
            for k in ("min", "max"):
                v = r.get(k)
                try:
                    vals.append(round(float(v), 6))
                except (TypeError, ValueError):
                    vals.append(None)
            out[r.get("keyword", "")] = tuple(vals)
        return out
    return norm(old_rows) == norm(new_rows)


def _build_results_range(kw_to_tier, tier_lims, overrides=None, is_tight=True):
    """Build the ResultsRange list for setResultsRange() for ONE matrix.

    Per-analyte overrides win over the analyte's (matrix-effective) tier
    default — the write-through target of reverse sync. Tier 1 collapses to
    tier 2 outside tight matrices (FDA Table 10-1).
    """
    overrides = overrides or {}
    rows = []
    for kw in sorted(kw_to_tier):
        tier = effective_tier(kw_to_tier[kw], is_tight)
        lims = tier_lims.get(tier) or tier_lims.get(2) or {}
        ov = overrides.get(kw)
        if ov:
            r_min, r_max = ov.get("min"), ov.get("max")
            comment = "Per-analyte override (PFAS)"
        else:
            r_min, r_max = lims.get("min"), lims.get("max")
            comment = "Tier %d recovery limit (PFAS auto-sync)" % tier
        rows.append({
            "keyword":      kw,
            "min_operator": "geq",
            "min":          str(r_min if r_min is not None else ""),
            "max_operator": "leq",
            "max":          str(r_max if r_max is not None else ""),
            "warn_min":     "",
            "warn_max":     "",
            "hidemin":      "0",
            "hidemax":      "0",
            "rangecomment": comment,
        })
    return rows


# NOTE: the old _get_or_create_sample_type (synthetic "{method} {QC}" sample
# types) was REMOVED — specs now link to the real matrix SampleTypes. See
# migrations/cleanup_synthetic_qc_sampletypes.py for the data cleanup.


def spec_id_for(method_id, qc_type, matrix_title):
    """Deterministic spec id for method × QC type × matrix — shared with the
    reverse-sync identifier so both sides agree."""
    return "{0}-{1}-{2}-recovery".format(
        method_id, qc_type, matrix_slug(matrix_title)).lower().replace("_", "-")


def ranges_for(profile, qc_type, matrix_title):
    """[{"keyword", "min", "max", ...}] -- the QC type's recovery window per
    analyte in `matrix_title`, from `profile` (the method's, or a batch's
    effective profile with its project's specs applied). [] when the QC type
    is disabled or sets no recovery window."""
    tier_lims = _tier_limits(profile.get("qc_acceptance") or {}, qc_type)
    if tier_lims is None:
        return []
    kw_to_tier = _build_kw_to_tier(profile)
    is_tight = matrix_title in set(get_tight_matrices(profile))
    return _build_results_range(kw_to_tier, tier_lims, None, is_tight=is_tight)

