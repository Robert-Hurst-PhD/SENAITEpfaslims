# -*- coding: utf-8 -*-
"""Copy from method, for a method's tier lists: this method's tiers of each
QC type both methods run are replaced by the other's.

A tier list is a declared collection per QC type (profile_grids.
TIER_SECTIONS: LFSM, LFB, LFSMD RPD, SD RPD); it is read, checked and
written through that collection, so the copy holds exactly the fields the
editor holds. A listed tier keeps only the matrices this method has; the
ones dropped are named. The result is shown first as a list of differences;
nothing is written until the person confirms, and the collection's own
check refuses what the editor would refuse (a listed tier left with no
matrix, a second ordinary tier the engine would never use).

    plan(target, source)   -> {"types", "skipped", "errors", "profile"}

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy


def _modules():
    from senaite.pfas import config_forms, method_profile_sections, profile_grids
    return config_forms, method_profile_sections, profile_grids


def _text(v, choices=None):
    """A value as the editor shows it: a choice by its words, a list joined."""
    if v is None or v == u"" or v == []:
        return u"blank"
    if isinstance(v, (list, tuple)):
        return u", ".join(_text(x, choices) for x in v)
    if choices and v in choices:
        return choices[v]
    if isinstance(v, float):
        return (u"%.6f" % v).rstrip(u"0").rstrip(u".")
    return u"%s" % v


def _words(coll, profile):
    """{stored key: (the column's label, {choice: its words})} of a tier
    collection, as its editor heads and offers them."""
    out = {}
    for f in coll.fields():
        choices = f.choices(profile) if callable(f.choices) else f.choices
        out[f.path[0]] = (f.label, dict(choices or []))
    return out


def _clean(row, stored_key):
    return dict((k, v) for k, v in row.items() if k != stored_key)


def _differences(before, after, words=None):
    """Words for what changes, tier by tier, matched by name; each field by
    its column's label and each choice by its words (`words`, _words)."""
    words = words or {}
    old = dict((r["name"], r) for r in before)
    new = dict((r["name"], r) for r in after)
    out = []
    for r in after:
        name = r["name"]
        if name not in old:
            out.append(u"Adds tier %s" % name)
            continue
        for key in sorted(set(r) | set(old[name])):
            if key == u"name" or old[name].get(key) == r.get(key):
                continue
            label, choices = words.get(key, (key.replace(u"_", u" "), {}))
            out.append(u"%s, %s: %s \u2192 %s" % (name, label, _text(old[name].get(key), choices),
                                                   _text(r.get(key), choices)))
    for r in before:
        if r["name"] not in new:
            out.append(u"Removes tier %s" % r["name"])
    if [r["name"] for r in before if r["name"] in new] != [r["name"] for r in after if r["name"] in old]:
        out.append(u"Changes the order of the tiers")
    return out


def plan(target, source):
    """What copying `source`'s tiers onto `target` (both method profiles)
    would do: {"types": [{"qc", "label", "changes": [words], "dropped":
    [(tier, [matrices this method lacks])]}], "skipped": [(label, why)],
    "errors": [why it would be refused], "profile": the target with the
    tiers replaced (a copy; None when refused)}."""
    cf, mps, pg = _modules()
    labels = dict(pg.QC_TYPES)
    target = target or {}
    source = source or {}
    mine = set(target.get("supported_matrices") or [])
    out = copy.deepcopy(target)
    types, skipped, errors = [], [], []
    for qc, sid in pg.TIER_SECTIONS:
        label = labels.get(qc, qc)
        here, there = pg._runs(target, qc), pg._runs(source, qc)
        if not (here and there):
            if here or there:
                skipped.append((label, u"not run by this method" if not here else u"not run by the other method"))
            continue
        coll = mps.SECTIONS[sid]
        rows, dropped = [], []
        for r in coll.read(source):
            r = _clean(r, cf.STORED_KEY)
            listed = r.get("matrix_scope") == mps.LISTED
            if listed:
                lacks = [m for m in r.get("matrices") or [] if m not in mine]
                if lacks:
                    dropped.append((r["name"], lacks))
                r["matrices"] = [m for m in r.get("matrices") or [] if m in mine]
            rows.append(r)
        if not rows and not coll.allow_empty:
            errors.append(u"%s: the other method has no tiers, and this method needs one." % label)
        before = [_clean(r, cf.STORED_KEY) for r in coll.read(target)]
        # nothing of this method's tiers is carried over: their stored
        # extras (a citation, a verify flag) describe tiers that are replaced
        cleared = copy.deepcopy(out)
        entry = (cleared.get("qc_acceptance") or {}).get(qc)
        if isinstance(entry, dict):
            entry["tiers"] = []
        errors.extend(u"%s: %s" % (label, e) for e in coll.check(cleared, rows) or [])
        out = coll.write(cleared, rows)
        after = [_clean(r, cf.STORED_KEY) for r in coll.read(out)]
        types.append({"qc": qc, "label": label, "changes": _differences(before, after, _words(coll, target)), "dropped": dropped})
    return {"types": types, "skipped": skipped, "errors": errors, "profile": None if errors else out}
