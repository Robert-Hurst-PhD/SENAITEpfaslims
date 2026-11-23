# -*- coding: utf-8 -*-
"""Composite isotope standards: an analyte quantified on the mean of two or
more of the method's own labelled standards' areas, per injection (EPA
Method 1633A, EPA 820-R-24-007, §15.2 Note and Table 10 footnote 3: PFTrDA
on the average of the areas of 13C2-PFTeDA and 13C2-PFDoA).

    composite_standards = {id: {"members": [keyword, ...], "averaged": "area"}}

The id is generated once ("composite-" and eight hex characters), never
shown and never a compound-library keyword. The surrogate map's row stores
the id in `surrogate_is`, so one relation still says what quantifies an
analyte. Only the members are stored: the composite's role and reference
are its members' own (they must share both), and its name is built from
them, so neither can drift from the grid.

Every reader of the surrogate map resolves a value through members() before
it treats it as a compound; keyword_for and the library lookups are never
asked about an id. The worker loads this module by path (addon.load), as it
loads quant_fit. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import re
import uuid

KEY = "composite_standards"
PREFIX = "composite-"
# the one way a composite is averaged: the members' areas in each injection
AVERAGED = ("area",)
AVERAGED_WORDS = {"area": "Mean of the areas"}
_ID = re.compile(r"^composite-[0-9a-f]{8}$")
LABELLED_KEY = "labelled_standards"


def _t(v):
    return ("%s" % (v if v is not None else "")).strip()


def entries(profile):
    """{id: {"members": [...], "averaged": "area"}} as stored, entries that
    are not a dict left out."""
    table = (profile or {}).get(KEY)
    if not isinstance(table, dict):
        return {}
    return dict((k, v) for k, v in table.items() if isinstance(v, dict))


def ordered(profile):
    """The composite ids in the order they are drawn: by name."""
    table = entries(profile)
    return sorted(table, key=lambda cid: (name(profile, cid).lower(), cid))


def is_id(value):
    """Whether `value` has the shape of a composite id (whether or not the
    profile holds it)."""
    return bool(_ID.match(_t(value)))


def is_composite(profile, value):
    return _t(value) in entries(profile)


def members(profile, value):
    """The member keywords of the composite `value`, in the lab's order;
    [value] for a plain standard; [] for nothing. An id the profile does not
    hold is no compound either: [] (a reader then has no standard to read)."""
    v = _t(value)
    if not v:
        return []
    table = entries(profile)
    if v in table:
        return [m for m in (_t(x) for x in table[v].get("members") or []) if m]
    if is_id(v):
        return []
    return [v]


def members_map(profile):
    """{id: [member keywords]} for every composite: what the worker's raw
    run divides by."""
    return dict((cid, members(profile, cid)) for cid in entries(profile))


def name_of(member_names):
    """"Mean of A and B", "Mean of A, B and C"."""
    names = [_t(n) for n in member_names if _t(n)]
    if not names:
        return "Mean of no standard"
    if len(names) == 1:
        return "Mean of " + names[0]
    return "Mean of " + ", ".join(names[:-1]) + " and " + names[-1]


def name(profile, value, display=None):
    """A composite's name, built from its members (`display(keyword)` their
    shown names, else the keywords); a plain standard's own (shown) name."""
    v = _t(value)
    show = display or (lambda k: k)
    if v in entries(profile):
        return name_of([show(m) or m for m in members(profile, v)])
    return show(v) or v if v else ""


def holding(profile, keyword):
    """The ids of the composites `keyword` is a member of, in drawn order."""
    kw = _t(keyword)
    return [cid for cid in ordered(profile) if kw and kw in members(profile, cid)]


def natives_on(profile, keyword):
    """The natives the surrogate map quantifies on `keyword`: on it alone,
    then on each composite holding it, each native once in the map's order."""
    held = set(holding(profile, keyword))
    out = []
    for row in (profile or {}).get("surrogate_map") or []:
        if not isinstance(row, dict) or not row.get("analyte"):
            continue
        v = _t(row.get("surrogate_is"))
        if (v == _t(keyword) or v in held) and row["analyte"] not in out:
            out.append(row["analyte"])
    return out


def natives_of(profile, cid):
    """The natives whose Quantified by names the composite `cid`."""
    out = []
    for row in (profile or {}).get("surrogate_map") or []:
        if isinstance(row, dict) and row.get("analyte") and _t(row.get("surrogate_is")) == cid \
                and row["analyte"] not in out:
            out.append(row["analyte"])
    return out


def role(profile, value):
    """The role of a standard or a composite (its members' one role), or ""."""
    grid = (profile or {}).get(LABELLED_KEY) or {}
    roles = set(_t((grid.get(m) or {}).get("role")) for m in members(profile, value))
    return roles.pop() if len(roles) == 1 else ""


def reference(profile, value):
    """The standard a composite's members are linked to (their one
    reference), or a plain standard's own; "" when none or they differ."""
    grid = (profile or {}).get(LABELLED_KEY) or {}
    refs = set(_t((grid.get(m) or {}).get("reference")) for m in members(profile, value))
    return refs.pop() if len(refs) == 1 else ""


def new_id(taken):
    """A fresh id: "composite-" and eight hex characters, none of `taken`
    (the profile's ids and every library keyword)."""
    taken = set(_t(t).lower() for t in taken or ())
    while True:
        cid = PREFIX + uuid.uuid4().hex[:8]
        if cid.lower() not in taken:
            return cid


def check(profile, keywords=None):
    """Refusals for a whole saved profile's composites: an id not of the
    generated shape or one the compound library holds (`keywords`), fewer
    than two members, a member twice, a member the method's grid does not
    hold, members of different roles or linked to different standards, two
    composites of the same members, an averaging other than the areas; and
    a surrogate-map row naming a composite the method does not have (the
    composite was removed while it quantified natives)."""
    grid = (profile or {}).get(LABELLED_KEY) or {}
    grid = grid if isinstance(grid, dict) else {}
    lib = set(_t(k).lower() for k in keywords or ())
    errors, seen = [], {}
    for cid in ordered(profile):
        entry = entries(profile)[cid]
        mem = [_t(m) for m in entry.get("members") or []]
        title = name_of(mem)
        if not is_id(cid) or cid.lower() in lib:
            errors.append("%s: its id %s is not one this page made; remove it and combine the "
                          "standards again." % (title, cid))
        if (entry.get("averaged") or "area") not in AVERAGED:
            errors.append("%s: a composite is averaged on its members' areas only." % title)
        if len([m for m in mem if m]) < 2:
            errors.append("%s: a composite needs two or more members." % title)
            continue
        twice = sorted(set(m for m in mem if mem.count(m) > 1))
        if twice:
            errors.append("%s: %s is listed twice." % (title, ", ".join(twice)))
        absent = [m for m in mem if m not in grid]
        if absent:
            errors.append("%s: %s %s not one of this method's standards: add %s, or edit its members."
                          % (title, ", ".join(absent), "is" if len(absent) == 1 else "are",
                             "it" if len(absent) == 1 else "them"))
            continue
        roles = sorted(set(_t((grid.get(m) or {}).get("role")) for m in mem))
        if len(roles) > 1:
            errors.append("%s: its members have different roles; a composite's members share one role."
                          % title)
        refs = sorted(set(_t((grid.get(m) or {}).get("reference")) for m in mem))
        if len(refs) > 1:
            errors.append("%s: its members are linked to different standards (%s); a composite's "
                          "members share one link." % (title, ", ".join(r or "none" for r in refs)))
        same = frozenset(mem)
        if same in seen:
            errors.append("%s is combined twice." % title)
        seen[same] = cid
    table = entries(profile)
    orphan = []
    for row in (profile or {}).get("surrogate_map") or []:
        v = _t(row.get("surrogate_is")) if isinstance(row, dict) else ""
        if is_id(v) and v not in table and row.get("analyte") and row["analyte"] not in orphan:
            orphan.append(row["analyte"])
    if orphan:
        errors.append("Cannot remove the composite: it quantifies %s. Change their Quantified by "
                      "first." % _and(orphan))
    return errors


def _and(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def unequal_members(profile, expected):
    """For one calibrator or check standard: [(composite name, [(member,
    concentration)])] for each composite whose members `expected`
    ({compound: concentration}) states at different concentrations. The mean
    of the members' areas stands for one amount only when they are added at
    one amount, as EPA 1633A Table 4 has 13C2-PFDoA and 13C2-PFTeDA."""
    out = []
    for cid in ordered(profile):
        mem = members(profile, cid)
        stated = [(m, expected.get(m)) for m in mem if expected.get(m) is not None]
        values = set(round(float(c), 9) for _m, c in stated)
        if len(values) > 1:
            out.append((name(profile, cid), stated))
    return out


def quantified_by(profile, display=None):
    """{native keyword: the standard that quantifies it, in words}: the
    standard's shown name (`display(keyword)`), or a composite's name built
    from its members' (the EDD's analysis.quantified_by)."""
    out = {}
    for row in (profile or {}).get("surrogate_map") or []:
        if not isinstance(row, dict) or not row.get("analyte"):
            continue
        v = _t(row.get("surrogate_is"))
        if v and (v in entries(profile) or not is_id(v)):
            out[row["analyte"]] = name(profile, v, display)
    return out
