# -*- coding: utf-8 -*-
"""Per-method isotopically labelled standards.

One grid per method, MS Quan style: every labelled standard the method uses,
its ROLE in this method, and the standard it is LINKED to (its reference):

    labelled_standards = {keyword: {"role": "surrogate" | "injection_is",
                                    "reference": keyword | ""}}

  surrogate     extracted standard (surrogate / EIS): added before extraction,
                diluted with the sample, recovery-checked
  injection_is  injection standard (NIS): added at reconstitution, after any
                dilution, so its response is compared as measured

The pipeline reads the same key (pfas_pipeline.method_profiles). Pure;
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import composite_standards as _cmp

KEY = "labelled_standards"
ROLES = ("surrogate", "injection_is")
ROLE_LABELS = [("surrogate", "Surrogate (SUR)"),
               ("injection_is", "Internal standard (IS)")]


def _map_surrogates(profile):
    """The standards the surrogate map quantifies on, a composite's members
    for the composite (its own refusals are composite_standards.check's)."""
    out = []
    for row in profile.get("surrogate_map") or []:
        kw = (row.get("surrogate_is") or "").strip() if isinstance(row, dict) else ""
        if _cmp.is_composite(profile, kw) or _cmp.is_id(kw):
            continue
        if kw and kw not in out:
            out.append(kw)
    return out


# A SUR's limits for a matrix class (eis_matrix_overrides[class][keyword])
# may hold the marker "none" at both ends: recovery is not assessed in that
# class -- no window, never the aqueous one. Every reader of a class limit
# asks not_assessed() before reading a number.
NOT_ASSESSED = "none"


def not_assessed(lim):
    """Whether a class limit ({recovery_min, recovery_max}) is the marker."""
    return isinstance(lim, dict) and NOT_ASSESSED in (lim.get("recovery_min"), lim.get("recovery_max"))


def grid(profile):
    return dict((k, v) for k, v in (profile.get(KEY) or {}).items() if isinstance(v, dict))


def roles(profile):
    """{keyword: role} for every used standard."""
    return dict((k, v.get("role")) for k, v in grid(profile).items())


def chain(profile):
    """{standard: reference} for every used standard that links to another."""
    return dict((k, v["reference"]) for k, v in grid(profile).items() if v.get("reference"))


def injection(profile):
    return sorted(k for k, r in roles(profile).items() if r == "injection_is")


def removal_blocked_by(profile, keyword):
    """The natives the surrogate map quantifies against `keyword`, in the
    map's order: while any is left, the standard cannot leave the method
    (whatever its role: either may quantify natives)."""
    out = []
    for row in profile.get("surrogate_map") or []:
        if not isinstance(row, dict) or not row.get("analyte"):
            continue
        if (row.get("surrogate_is") or "").strip() == keyword and row["analyte"] not in out:
            out.append(row["analyte"])
    return out


def composites_holding(profile, keyword):
    """The names of the composites `keyword` is a member of: while any holds
    it, the standard cannot leave the method (the composite would average a
    compound the method no longer measures)."""
    return [_cmp.name(profile, cid) for cid in _cmp.holding(profile, keyword)]


def check(profile, keywords=None):
    """Refusals for a whole saved profile: links, loops, and agreement with the
    surrogate map (checked on the whole profile after each save, so a new
    standard and a native mapped to it may come from different saves); then
    the composites' own (`keywords`: the compound library's, which no
    composite id may be)."""
    g = grid(profile)
    errors = []
    for kw in sorted(g):
        role, ref = g[kw].get("role"), g[kw].get("reference") or ""
        if role not in ROLES:
            errors.append("%s: choose its role (extracted or injection)." % kw)
        if ref == kw:
            errors.append("%s cannot be linked to itself." % kw)
        elif ref and (_cmp.is_composite(profile, ref) or _cmp.is_id(ref)):
            # a composite is never a link target: its members each carry their own
            errors.append("%s: link it to an internal standard, not a composite." % kw)
        elif ref and ref not in g:
            errors.append("%s is linked to %s, which this method does not use: "
                          "add %s, or change the link." % (kw, ref, ref))
    loops = set()
    for kw in sorted(g):                       # A -> B -> ... -> A
        seen, cur = [kw], g[kw].get("reference")
        if cur == kw:
            continue                           # reported above as a self-link
        while cur and cur in g:
            if cur in seen:
                members = seen[seen.index(cur):]
                if frozenset(members) not in loops:
                    loops.add(frozenset(members))
                    errors.append("Links loop: %s." % " \u2192 ".join(members + [cur]))
                break
            seen.append(cur)
            cur = g[cur].get("reference")
    # Either role may quantify natives: isotope dilution (FDA, EPA 1633A)
    # quantifies against the extracted standard, internal-standard
    # calibration (EPA 537.1 §7.2.1, Table 3) against the injection standard.
    for kw in _map_surrogates(profile):
        if kw not in g:
            errors.append("%s quantifies natives in the surrogate map but is not "
                          "one of this method's standards: add it, or quantify them by "
                          "another." % kw)
    return errors + _cmp.check(profile, keywords)
