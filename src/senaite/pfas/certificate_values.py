# -*- coding: utf-8 -*-
"""Certificate values on a purchased standard lot.

The supplier's certificate states each analyte's concentration, usually as
the acid even when the neat material was a salt, sometimes as the salt.
Typed exactly as stated (it already allows for purity); a salt is converted
to the acid with the molecular weights the lab enters (recipe_calc.as_acid,
EPA 537.1 §7.2.3); recipes calculate from the acid.

Whoever enters certificate values may correct them at any time; a
correction needs a reason and keeps the value it replaced. Saving one flags
every lot made from the lot -- and the lots made from those -- and every run
that used them, for review; nothing is recalculated until a reviewer does.

    from_form(form)                    -> (cert, [error])
    rows(cert)                         -> analytes with "as_acid"
    correct(before, after, reason, who, at) -> (cert with corrections, error)
    made_from(uid, entries)            -> [lot uid] made from it, at any depth
    branched_source(lot, keyword, parents_of, certificate_of) -> {fraction, from} or None

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.recipe_calc import as_acid

KEY = "senaite.pfas.reagent.certificate"
STATED = (u"acid", u"salt")
# no CAS: the compound library (the analyte service) owns it
FIELDS = ((u"certified", u"Certified"), (u"plusminus", u"±"),
          (u"stated_as", u"Stated as"), (u"branched_pct", u"Branched"),
          (u"mw_acid", u"MW acid"), (u"mw_salt", u"MW salt"))


def _t(form, key):
    return (u"%s" % (form.get(key) or u"")).strip()


def _num(text):
    if text in (None, u""):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        raise ValueError(text)


def from_form(form, known=None):
    """(cert, [error]) from the certificate dialog; a row with no analyte is
    no row. `known`: the methods' analyte keywords -- a name must be one
    (stored as the keyword), since the worker's salt rule matches by it."""
    keyword = dict(((k or u"").upper(), k) for k in known or []) if known is not None else None
    cert = {"certified_on": _t(form, "certified_on"), "solvent": _t(form, "solvent"),
            "unit": _t(form, "unit") or u"ug/mL", "analytes": []}
    errors, seen = [], set()
    idx = sorted(set(int(k.split(".", 1)[1]) for k in form if k.startswith("an.") and k.split(".", 1)[1].isdigit()))
    for i in idx:
        name = _t(form, "an.%d" % i)
        if not name:
            continue
        if keyword is not None:
            if name.upper() not in keyword:
                errors.append(u"%s is not an analyte of any method: use its keyword." % name)
                continue
            name = keyword[name.upper()]
        if name in seen:
            errors.append(u"%s is listed twice." % name)
            continue
        seen.add(name)
        row = {"analyte": name,
               "stated_as": _t(form, "stated.%d" % i) if _t(form, "stated.%d" % i) in STATED else u"acid"}
        try:
            for key, field in ((u"certified", "certified"), (u"plusminus", "pm"), (u"branched_pct", "branched"),
                               (u"mw_acid", "mw_acid"), (u"mw_salt", "mw_salt")):
                row[key] = _num(_t(form, "%s.%d" % (field, i)))
        except ValueError as exc:
            errors.append(u"%s: %r is not a number." % (name, u"%s" % exc))
            continue
        if row["certified"] is None:
            errors.append(u"%s: give the certified value." % name)
            continue
        cert["analytes"].append(row)
    return cert, errors


def rows(cert):
    """Each analyte with its value as acid (None: a salt whose molecular
    weights are not entered)."""
    return [dict(a, as_acid=as_acid(a.get("certified"), a.get("stated_as"), a.get("mw_acid"), a.get("mw_salt")))
            for a in (cert or {}).get("analytes") or []]


def _changes(before, after):
    out = []
    old = dict((a.get("analyte"), a) for a in (before or {}).get("analytes") or [])
    new = dict((a.get("analyte"), a) for a in (after or {}).get("analytes") or [])
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name) or {}, new.get(name) or {}
        for key, label in FIELDS:
            if a.get(key) != b.get(key) and (name in old):
                out.append({"analyte": name, "field": label, "before": a.get(key), "after": b.get(key)})
    for key, label in ((u"certified_on", u"Certified on"), (u"solvent", u"Solvent"), (u"unit", u"Unit")):
        if (before or {}).get("analytes") and (before or {}).get(key) != (after or {}).get(key):
            out.append({"analyte": u"", "field": label, "before": before.get(key), "after": after.get(key)})
    return out


def correct(before, after, reason, who, at):
    """(cert, error): the values saved, each change to a value already on
    file kept with its reason; the first entry and an unchanged save need
    none."""
    changes = _changes(before, after)
    if changes and not (reason or u"").strip():
        return before, u"Give the reason for the correction."
    out = dict(after)
    out["corrections"] = list((before or {}).get("corrections") or []) + [
        dict(c, at=at, by=who, reason=reason.strip()) for c in changes]
    return out, u""


FLAG_KEY = "senaite.pfas.review_flags"


def flag_entry(why, who, at):
    """One review flag on a lot or a run: why, by whom, when."""
    return {"why": why, "by": who, "at": at}


def add_flag(obj, entry):
    """Append a review flag to a lot or a worksheet (annotation)."""
    import json
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(obj)
    try:
        flags = json.loads(ann.get(FLAG_KEY) or "[]")
    except (TypeError, ValueError):
        flags = []
    flags.append(entry)
    ann[FLAG_KEY] = json.dumps(flags)


def flags_of(obj):
    import json
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(obj).get(FLAG_KEY) or "[]")
    except (TypeError, ValueError):
        return []


def made_from(uid, entries):
    """Every lot made from the lot `uid`, through every prep sitting (a stock
    made from it, the working levels made from the stock)."""
    out, todo = set(), [uid]
    while todo:
        cur = todo.pop()
        for e in (entries or {}).values():
            if any(p.get("uid") == cur for p in e.get("parents") or []):
                for lot in e.get("lots") or []:
                    if lot not in out:
                        out.add(lot)
                        todo.append(lot)
    return sorted(out)


def branched_source(lot, keyword, parents_of, certificate_of, label=None):
    """{"fraction": 0-1, "from": [the lots whose certificates state it]}
    for `keyword` in `lot`: the branched % stated on the certificates of the
    lot and of every lot it was made from, at any depth; None when none
    states one, or when one lists the analyte without it. Two certificates
    stating different values refuse (ValueError, naming both): a mixture's
    fraction depends on how much of
    each went in. `parents_of(lot)` gives the lots it was made from,
    `certificate_of(lot)` its certificate values or None, `label(lot)` how
    the result and a refusal name it."""
    name = label or (lambda x: u"%s" % x)
    found, unstated = [], False                 # (lot, pct)
    seen, todo = set(), [lot]
    while todo:
        cur = todo.pop(0)
        if cur in seen:                         # each lot once: a cycle ends the walk
            continue
        seen.add(cur)
        for row in (certificate_of(cur) or {}).get("analytes") or []:
            if row.get("analyte") != keyword:
                continue
            if row.get("branched_pct") in (None, u""):
                unstated = True
                continue
            pct = float(row["branched_pct"])
            if not 0.0 <= pct <= 100.0:
                raise ValueError(u"%s: the certificate of %s states %g %% branched, outside 0 to 100."
                                 % (keyword, name(cur), pct))
            found.append((cur, pct))
        todo.extend(parents_of(cur) or [])
    if unstated:
        return None
    values = sorted(set(pct for _lot, pct in found))
    if len(values) > 1:
        raise ValueError(u"%s: the certificates of %s state different branched %%, so the lot's "
                         u"fraction is not known." % (keyword, u" and ".join(
                             u"%s (%g %%)" % (name(l), pct) for l, pct in found)))
    if not values:
        return None
    names = []
    for l, _pct in found:
        if name(l) not in names:
            names.append(name(l))
    return {"fraction": values[0] / 100.0, "from": names}
