# -*- coding: utf-8 -*-
"""Reporting limits (RL) and method detection limits (MDL) per method x matrix
x analyte, and the reporting unit, as the certificate and EDD read them.

Decided 2026-09-30 (DECISIONS): RL/MDL are configured in the METHOD PROFILE,
per analyte x matrix -- once, like every other criterion -- not carried per
result. Stored on the profile as

    reporting_limits = {matrix title: {analyte keyword: {"rl": float, "mdl": float}}}

and the unit comes from the profile's existing unit_map (method x matrix), so
the certificate never prints a limit without the unit it was set in.

Edited on the Method Profile's Reporting Limits tab, a declared table
(method_profile_sections.REPORTING_LIMITS, config_forms): parsing, the
MDL-not-above-RL check and the merge live there, once.

No Zope imports: the certificate and the tests use this.
"""
from __future__ import absolute_import, print_function, unicode_literals


def limits_for(profile, matrix, keyword):
    """{"rl", "mdl", "unit", "rl_source"} for one analyte in one matrix.

    RL = a typed value when there is one ("override"), else the method's
    lowest calibrator in the matrix's unit ("calibration"; DECISIONS
    2026-10-02); None where neither exists. MDLs are assessed: typed only."""
    profile = profile or {}
    entry = ((profile.get("reporting_limits") or {}).get(matrix) or {}).get(keyword) or {}
    unit = (profile.get("unit_map") or {}).get(matrix) or None
    rl, source = entry.get("rl"), u"override"
    if rl is None:
        try:
            from senaite.pfas import calibration_levels as _cl
        except Exception:          # tests: loaded without the package
            import calibration_levels as _cl
        rl = _cl.derived_rl(profile, matrix, keyword)
        source = u"calibration" if rl is not None else None
    return {"rl": rl, "mdl": entry.get("mdl"), "unit": unit, "rl_source": source}


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
