# -*- coding: utf-8 -*-
"""Reporting limits (RL) and method detection limits (MDL) per method x matrix
x analyte, and the reporting unit, as the certificate and EDD read them.

Decided 2026-09-30 (DECISIONS): RL/MDL are configured in the METHOD PROFILE,
per analyte x matrix -- once, like every other criterion -- not carried per
result. Stored on the profile as

    reporting_limits = {matrix title: {analyte keyword: {"rl": float, "mdl": float}}}

and the unit comes from the profile's existing unit_map (method x matrix), so
the certificate never prints a limit without the unit it was set in.

No Zope imports: the editor, the certificate and the tests all use this.
"""
from __future__ import absolute_import, print_function, unicode_literals


def _num(raw):
    raw = ("%s" % (raw if raw is not None else "")).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError("not a number: {0!r}".format(raw))
    if value < 0:
        raise ValueError("a limit cannot be negative: {0!r}".format(raw))
    return value


def parse_form(form, matrices):
    """{matrix: {kw: {"rl", "mdl"}}} for the matrices this form carried.

    Field names: rlm.<i> = matrix title (marks matrix i as present),
    rl.<i>.<kw> and mdl.<i>.<kw>. A matrix the form did not carry is absent
    from the result, so merge() leaves it untouched -- a POST from another
    pane can never blank the limits (the partial-POST failure of GAPS §7).
    """
    out = {}
    for i, matrix in enumerate(matrices):
        if form.get("rlm.%d" % i) != matrix:
            continue
        prefix_rl, prefix_mdl = "rl.%d." % i, "mdl.%d." % i
        entries = {}
        keys = set(k[len(prefix_rl):] for k in form if k.startswith(prefix_rl))
        keys |= set(k[len(prefix_mdl):] for k in form if k.startswith(prefix_mdl))
        for kw in keys:
            rl = _num(form.get(prefix_rl + kw))
            mdl = _num(form.get(prefix_mdl + kw))
            if rl is not None and mdl is not None and mdl > rl:
                raise ValueError(
                    "{0} in {1}: the MDL ({2}) is above the RL ({3})".format(
                        kw, matrix, mdl, rl))
            if rl is not None or mdl is not None:
                entries[kw] = {"rl": rl, "mdl": mdl}
        out[matrix] = entries
    return out


def merge(existing, parsed):
    """Replace only the matrices the form carried."""
    merged = dict(existing or {})
    for matrix, entries in (parsed or {}).items():
        merged[matrix] = entries
    return merged


def limits_for(profile, matrix, keyword):
    """{"rl", "mdl", "unit"} for one analyte in one matrix; None where unset."""
    profile = profile or {}
    entry = ((profile.get("reporting_limits") or {}).get(matrix) or {}).get(keyword) or {}
    unit = (profile.get("unit_map") or {}).get(matrix) or None
    return {"rl": entry.get("rl"), "mdl": entry.get("mdl"), "unit": unit}


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
