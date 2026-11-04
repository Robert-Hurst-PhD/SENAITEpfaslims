# -*- coding: utf-8 -*-
"""Effective QC: every check of one method in one matrix, with the limits
that apply and the level that set each.

    effective_rows(profile, matrix)
        -> [{"check", "analyte", "limits", "set_by", "href"}]
    effective_sheet(profile, matrix, only_overrides=False)
        -> the read-only grid (profile_grids.Sheet) the page draws

`set_by` is "method" (the method's own value), "tier:<name>" (a tier the
profile chooses for a group of analytes or a spike level), "analyte" (an
analyte's own override), "class:<name>" (a matrix class's override),
"project" or "default" (the published method's value, or none). Instrument
limits and labelled-standard windows are resolved by resolved_criteria_store
(the run's own resolution); acceptance tiers are chosen by qc_tiers (the
run's own selection); nothing is resolved a second way here. Each href opens
the editor tab that owns the value. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from urllib import quote
except ImportError:        # Py3
    from urllib.parse import quote

from senaite.pfas import qc_tiers, resolved_criteria_store as rcs
from senaite.pfas import profile_grids as pg

EDITOR = "@@pfas-method-profile-edit"
TAB_QC = "pane-qc"
TAB_STANDARDS = "pane-standards"
EN = "–"

# the run-wide checks: key -> (label, unit, always listed)
_RUN_CHECKS = (
    ("cal_r2_min", "Calibration r2 minimum", "", True),
    ("sn_quan_min", "Quantifier S/N minimum", "", True),
    ("ccv_recovery", "CCV recovery", "%", True),
    ("ccv_frequency", "CCV frequency", "", True),
    ("lfsm_frequency", "LFSM frequency", "", False),
    ("duplicate_all_samples", "Duplicate every sample", "", False),
)
_GROUPS = (
    ("default", "All analytes", False, False),
    ("key_tight", "Key analytes", True, False),
    ("no_std", "Analytes with no isotope standard", False, True),
)
_SET_BY_WORDS = {"method": "Method", "analyte": "Analyte override", "project": "Project",
                 "default": "Published default"}


def _num(v):
    return "{0:g}".format(float(v))


def _href(method_id, tab):
    return "{0}?method_id={1}#{2}".format(EDITOR, quote(("%s" % method_id).encode("utf-8")), tab)


def set_by_words(set_by):
    """The level in words, as the Set by column shows it."""
    if set_by.startswith("tier:"):
        return "Tier: " + set_by[5:]
    if set_by.startswith("class:"):
        return "Matrix class: " + set_by[6:]
    return _SET_BY_WORDS.get(set_by, set_by)


def is_override(set_by):
    """True when something more specific than the method or its published
    default set the limit."""
    return set_by not in ("method", "default")


def _window(value, unit="%"):
    lo, hi = value.get("min"), value.get("max")
    if lo is None and hi is None:
        return ""
    if lo is None:
        return "up to {0}{1}".format(_num(hi), unit)
    if hi is None:
        return "from {0}{1}".format(_num(lo), unit)
    return "{0} {1} {2}{3}".format(_num(lo), EN, _num(hi), unit)


def _limits(value, unit):
    if value is None:
        return "Not set"
    if isinstance(value, dict) and value.get("assessed") is False:
        return "Not assessed"
    if isinstance(value, dict):
        return _window(value, unit) or "Not set"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "{0}{1}".format(_num(value), unit)


def _row(check, analyte, limits, set_by, href):
    return {"check": check, "analyte": analyte, "limits": limits, "set_by": set_by, "href": href}


def _run_rows(profile, matrix, method_id):
    href = _href(method_id, TAB_QC)
    rows = {}
    for r in rcs.build_resolved_rows(method_id, matrix, profile=profile):
        if r["analyte"] is None:
            rows[r["key"]] = r
    out = []
    for key, label, unit, always in _RUN_CHECKS:
        r = rows.get(key)
        if r is None or (r["value"] is None and not always):
            continue
        out.append(_row(label, "All analytes", _limits(r["value"], unit), r["set_by"], href))
    return out


def _tier_label(tier):
    return tier.get("name") or tier.get("analyte_group") or "unnamed tier"


def _tier_checks(qc_type, tier):
    """[(check, limits)] a tier states."""
    out = []
    lo, hi = tier.get("recovery_min"), tier.get("recovery_max")
    if lo is not None or hi is not None:
        out.append(("{0} recovery".format(qc_type), _window({"min": lo, "max": hi})))
    spread = qc_tiers.spread_limit(tier)
    if spread is not None:
        out.append(("{0} spread".format(qc_type), "up to {0}%".format(_num(spread))))
    blank = tier.get("max_conc_x_rl")
    if blank not in (None, ""):
        out.append(("{0} blank limit".format(qc_type), "up to {0} x RL".format(_num(blank))))
    return out


def _tier_rows(profile, matrix, method_id):
    href = _href(method_id, TAB_QC)
    out = []
    for qc_type in sorted((profile.get("qc_acceptance") or {})):
        seen = []
        for branch, group, is_key, no_std in _GROUPS:
            try:
                chosen = qc_tiers.base_tier(profile, qc_type, matrix, is_key, no_std)
            except qc_tiers.Unconfigured:
                if branch == "default":
                    out.append(_row("{0} limits".format(qc_type), group, "Not set", "default", href))
                continue
            if chosen is None or any(chosen[0] is t for t in seen):
                continue
            tier = chosen[0]
            seen.append(tier)
            set_by = "method" if chosen[1] == "default" else "tier:" + _tier_label(tier)
            for check, limits in _tier_checks(qc_type, tier):
                out.append(_row(check, group, limits, set_by, href))
            for low in qc_tiers.low_level_candidates(profile, qc_type, tier, matrix):
                words = "Spiked at or below {0} x RL".format(_num(low[qc_tiers.LOW_LEVEL_KEY]))
                for check, limits in _tier_checks(qc_type, low):
                    out.append(_row(check, words, limits, "tier:" + _tier_label(low), href))
    return out


def _sur_rows(profile, matrix, method_id):
    href = _href(method_id, TAB_STANDARDS)
    found = dict((r["analyte"], r) for r in rcs.build_resolved_rows(method_id, matrix, profile=profile)
                 if r["key"] == "eis_recovery" and r["analyte"])
    mclass = rcs.ruleset.method_baselines.matrix_class(matrix, profile) if matrix else "aqueous"
    for analyte in (profile.get("eis_matrix_overrides") or {}).get(mclass, {}):
        if analyte not in found:
            found[analyte] = rcs.resolve_row(method_id, matrix, "eis_recovery", analyte, profile)
    return [_row("SUR recovery", analyte, _limits(found[analyte]["value"], "%"), found[analyte]["set_by"], href)
            for analyte in sorted(found)]


def effective_rows(profile, matrix):
    profile = profile or {}
    method_id = profile.get("method_id") or ""
    return (_run_rows(profile, matrix, method_id) + _tier_rows(profile, matrix, method_id) +
            _sur_rows(profile, matrix, method_id))


def effective_sheet(profile, matrix, only_overrides=False):
    """The read-only grid: no cell is named, so the page posts nothing."""
    columns = [pg.Column("analyte", "Analytes", "text"), pg.Column("limits", "Limits", "text"),
               pg.Column("set_by", "Set by", "text")]
    rows = []
    for r in effective_rows(profile, matrix):
        if only_overrides and not is_override(r["set_by"]):
            continue
        words = set_by_words(r["set_by"])
        rows.append(pg.Row("r{0}".format(len(rows)), r["check"], {
            "analyte": pg.Cell(r["analyte"], state="readonly"),
            "limits": pg.Cell(r["limits"], state="readonly"),
            "set_by": pg.Cell(words, state="readonly", links=[(words, r["href"])]),
        }, selectable=False))
    return pg.Sheet("effective-qc", columns, rows, selection=False, picker=False)
