# -*- coding: utf-8 -*-
"""Reporting limits (RL) and method detection limits (MDL) per method x matrix
x analyte, and the reporting unit, as the certificate and EDD read them.

RL/MDL are configured in the method profile, per analyte x matrix -- once,
like every other criterion -- not carried per result. Stored on the profile as

    reporting_limits = {matrix title: {analyte keyword: {"rl": float, "mdl": float}}}

and the unit comes from the profile's existing unit_map (method x matrix), so
the certificate never prints a limit without the unit it was set in.

Edited on the Method Profile's Reporting Limits tab, a declared table
(method_profile_sections.REPORTING_LIMITS, config_forms): parsing, the
MDL-not-above-RL check and the merge live there, once.

No Zope imports: the certificate and the tests use this.
"""
from __future__ import absolute_import, print_function, unicode_literals


def limits_for(profile, matrix, keyword, acid_basis=None):
    """{"rl", "mdl", "unit", "rl_source"} for one analyte in one matrix.

    RL = a typed value when there is one ("override"), else its default:
    the method's lowest calibrator in the matrix's unit times the analyte's
    salt factor ("calibration", calibration_levels.derived_rl); None where
    neither exists. `acid_basis`: the analytes the result's run calibrated
    from standards stated as the acid; their default takes no salt factor,
    as their results take none (calibration_levels.derived_rl_for_run).
    This is the RL the certificate prints, and the one that decides below
    quantitation everywhere. MDLs are assessed: typed only."""
    profile = profile or {}
    entry = ((profile.get("reporting_limits") or {}).get(matrix) or {}).get(keyword) or {}
    unit = (profile.get("unit_map") or {}).get(matrix) or None
    rl, source = entry.get("rl"), u"override"
    if rl is None:
        from senaite.pfas import calibration_levels as _cl
        rl = _cl.derived_rl_for_run(profile, matrix, keyword, acid_basis)
        source = u"calibration" if rl is not None else None
    return {"rl": rl, "mdl": entry.get("mdl"), "unit": unit, "rl_source": source}


def limits_with_frozen(profile, matrix, keyword, frozen, acid_basis=None):
    """limits_for, with the RL, the MDL and the unit a verified result kept
    (verified_rl: frozen when its worksheet was verified; "rl_source"
    "verified"); limits_for as it is when nothing was frozen, on the run's
    acid basis (acid_basis: the analytes its standards state as the acid).
    A frozen MDL of None stays None; a payload frozen before the MDL was
    kept (no "mdl") takes the live MDL."""
    lim = limits_for(profile, matrix, keyword, acid_basis=acid_basis)
    if not frozen:
        return lim
    out = dict(lim, rl=frozen.get("rl"), rl_source=u"verified")
    if "mdl" in frozen:
        out["mdl"] = frozen["mdl"]
    if frozen.get("unit"):
        out["unit"] = frozen["unit"]
    return out


def scaled_rl(rl, fold):
    """A diluted analyte's reporting limit: RL x the dilution's total fold
    (2 ppt diluted 2-fold reports an RL of 4), however results are put on
    the sample basis. No fold, or a fold of 1 or less, leaves the RL as it
    is."""
    try:
        f = float(fold)
    except (TypeError, ValueError):
        return rl
    if rl is None or f <= 1:
        return rl
    return rl * f


def canonical_matrix(profile, title):
    """The profile's matrix title for a sample type title: exact match first,
    then the profile's matrix_aliases {canonical: [alias, ...]} ignoring case.
    Unknown titles come back unchanged, so a lookup simply finds no limit."""
    profile = profile or {}
    title = (title or u"").strip()
    matrices = profile.get("supported_matrices") or []
    if title in matrices:
        return title
    low = title.lower()
    for canonical, aliases in (profile.get("matrix_aliases") or {}).items():
        if canonical.lower() == low or low in [(a or u"").lower() for a in (aliases or [])]:
            return canonical
    return title
