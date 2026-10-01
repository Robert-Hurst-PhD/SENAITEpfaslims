# -*- coding: utf-8 -*-
"""Per-method isotopically labelled standards (DECISIONS 2026-09-30).

One grid per method, MS Quan style: every labelled standard the method uses,
its ROLE in this method, and the standard it is LINKED to (its reference):

    labelled_standards = {keyword: {"role": "surrogate" | "injection_is",
                                    "reference": keyword | ""}}

  surrogate     extracted standard (surrogate / EIS): added before extraction,
                diluted with the sample, recovery-checked
  injection_is  injection standard (NIS): added at reconstitution, after any
                dilution, so its response is compared as measured

It replaces the old top-level `surrogate_is` field (read by nothing in the
pipeline) and `surrogate_is_chain` (surrogate -> injection IS). The pipeline
reads the same key (pfas_pipeline.method_profiles). Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

KEY = "labelled_standards"
ROLES = ("surrogate", "injection_is")
ROLE_LABELS = [("surrogate", "Surrogate (SUR)"),
               ("injection_is", "Internal standard (IS)")]


def _map_surrogates(profile):
    out = []
    for row in profile.get("surrogate_map") or []:
        kw = (row.get("surrogate_is") or "").strip() if isinstance(row, dict) else ""
        if kw and kw not in out:
            out.append(kw)
    return out


def from_legacy(profile, global_injection):
    """The grid that reproduces what the pipeline decided from the legacy keys.

    `global_injection` = keywords globally marked injection_is (what the
    pipeline fell back to when a method had no chain). Returns a new dict.
    """
    chain = dict(profile.get("surrogate_is_chain") or {})
    old_is = (profile.get("surrogate_is") or "").strip()
    if chain:
        injection = [v for v in chain.values() if v]
    else:
        injection = list(global_injection or [])
    if old_is:
        injection.append(old_is)
    out = {}
    for kw in _map_surrogates(profile) + [k for k in chain if k]:
        if kw not in out:
            out[kw] = {"role": "surrogate", "reference": chain.get(kw) or ""}
    for kw in injection:
        if kw not in out:           # a compound that is a chain KEY stays a surrogate
            out[kw] = {"role": "injection_is", "reference": ""}
    return out


def migrate(profile, global_injection):
    """True if `profile` was migrated in place (idempotent)."""
    if KEY in profile:
        changed = False
    else:
        profile[KEY] = from_legacy(profile, global_injection)
        changed = True
    for legacy in ("surrogate_is", "surrogate_is_chain"):
        if legacy in profile:
            profile.pop(legacy)
            changed = True
    return changed


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


def check(profile):
    """Refusals for a whole saved profile: links, loops, and agreement with the
    surrogate map (checked after both are applied, so one save can tick a new
    standard AND map a native to it)."""
    g = grid(profile)
    errors = []
    for kw in sorted(g):
        role, ref = g[kw].get("role"), g[kw].get("reference") or ""
        if role not in ROLES:
            errors.append("%s: choose its role (extracted or injection)." % kw)
        if ref == kw:
            errors.append("%s cannot be linked to itself." % kw)
        elif ref and ref not in g:
            errors.append("%s is linked to %s, which this method does not use "
                          "(tick Used for it, or change the link)." % (kw, ref))
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
                    errors.append("Links loop: %s." % " -> ".join(members + [cur]))
                break
            seen.append(cur)
            cur = g[cur].get("reference")
    for kw in _map_surrogates(profile):
        if kw not in g:
            errors.append("%s quantifies natives in the surrogate map but is not "
                          "ticked Used." % kw)
        elif g[kw].get("role") != "surrogate":
            errors.append("%s quantifies natives in the surrogate map, so its role "
                          "must be extracted, not injection." % kw)
    return errors
