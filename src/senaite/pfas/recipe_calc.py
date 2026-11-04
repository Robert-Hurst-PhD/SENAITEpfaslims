# -*- coding: utf-8 -*-
"""A made lot's concentrations, calculated from its parent's.

    as_acid(value, stated_as, mw_acid, mw_salt)   -> value as acid, or None
    certificate_concentrations(cert, unit)        -> {analyte: as acid in unit}
    diluted(parent, take, take_unit, final, final_unit) -> {analyte: conc}
    series(stock, levels, mode)                   -> [{analyte: conc}] per level

A purchased standard's certificate states each analyte as the acid or as a
salt; a salt is converted to acid with the molecular weights the lab enters
(Acid = Salt x MW(acid) / MW(salt), EPA 537.1 §7.2.3). A made lot is its
parent's concentration x the volume taken / the final volume, so a serial
dilution carries through each step. A value that cannot be calculated (a
salt with no molecular weights, no volumes) is None -- never guessed.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

# mass concentrations and volumes in one base each (ng/mL, mL)
_CONC = {u"ng/ml": 1.0, u"ug/ml": 1e3, u"µg/ml": 1e3, u"mg/ml": 1e6,
         u"ng/l": 1e-3, u"ug/l": 1.0, u"µg/l": 1.0, u"mg/l": 1e3, u"pg/ml": 1e-3}
_VOL = {u"ml": 1.0, u"ul": 1e-3, u"µl": 1e-3, u"l": 1e3}


from senaite.pfas.rounding import number as _num


def _factor(table, unit):
    return table.get((u"%s" % (unit or u"")).strip().lower())


def as_acid(value, stated_as, mw_acid, mw_salt):
    v = _num(value)
    if v is None:
        return None
    if (stated_as or u"acid") != u"salt":
        return v
    a, s = _num(mw_acid), _num(mw_salt)
    if not a or not s:
        return None
    return v * a / s


def convert(value, unit, to_unit):
    """A mass concentration in another unit, or None when either is unknown."""
    v = _num(value)
    f, t = _factor(_CONC, unit), _factor(_CONC, to_unit)
    if v is None or f is None or t is None:
        return None
    return v * f / t


def certificate_concentrations(cert, unit):
    """{analyte: concentration as acid, in `unit`} from a purchased lot's
    certificate values; None for an analyte that cannot be converted."""
    cert = cert or {}
    out = {}
    for a in cert.get("analytes") or []:
        acid = as_acid(a.get("certified"), a.get("stated_as"), a.get("mw_acid"), a.get("mw_salt"))
        out[a.get("analyte")] = convert(acid, cert.get("unit"), unit) if acid is not None else None
    return out


def diluted(parent, take, take_unit, final, final_unit):
    """{analyte: parent x take / final}, volumes in any of mL, uL, L; None
    when a volume is missing or the final volume is zero."""
    t, f = _num(take), _num(final)
    ft, ff = _factor(_VOL, take_unit or u"mL"), _factor(_VOL, final_unit or u"mL")
    if t is None or f is None or ft is None or ff is None or f * ff == 0:
        return None
    ratio = (t * ft) / (f * ff)
    return dict((k, (v * ratio if v is not None else None)) for k, v in (parent or {}).items())


def series(stock, levels, mode):
    """Each level's concentrations: serial -- each from the level before (the
    first from the stock); independent -- each from the stock."""
    out, prev = [], stock
    for lv in levels or []:
        src = prev if mode == u"serial" else stock
        c = diluted(src, lv.get("take"), lv.get("take_unit"), lv.get("final"), lv.get("final_unit"))
        out.append(c)
        prev = c if c is not None else {}
    return out


def _rev(store, rid):
    revs = (store or {}).get(rid) or []
    act = [r for r in revs if r.get("status") == u"active"]
    return act[0] if act else (revs[-1] if revs else None)


def resolve(store, rid, purchased, _seen=None):
    """A recipe's concentrations as its card shows them: {"levels": [{"level",
    "conc": {analyte: value or None}}]}. Its parent is its first "made from":
    a purchased product's values from `purchased(name)` (its lot's certificate,
    as acid; None when not on file), a recipe's from resolving that recipe. A
    series gives one entry per level; anything else one entry, level "". What
    cannot be calculated yet reads {} (no parent values) or None (an analyte)."""
    seen = set(_seen or ())
    rev = _rev(store, rid)
    if rev is None:
        return {"levels": []}
    parent = {}
    mf = (rev.get("made_from") or [{}])[0]
    if rid not in seen:
        seen.add(rid)
        if mf.get("kind") == u"purchased":
            parent = purchased(mf.get("ref")) or {}
        elif mf.get("kind") == u"recipe" and mf.get("ref") not in seen:
            up = resolve(store, mf.get("ref"), purchased, seen)["levels"]
            parent = up[0]["conc"] if len(up) == 1 else {}
    ser = rev.get("series") or {}
    if ser.get("levels"):
        concs = series(parent, ser["levels"], ser.get("mode") or u"serial")
        return {"levels": [{"level": lv.get("level") or u"", "conc": c or {}}
                           for lv, c in zip(ser["levels"], concs)]}
    c = diluted(parent, mf.get("take"), mf.get("take_unit"), rev.get("final_volume"), rev.get("final_unit"))
    return {"levels": [{"level": u"", "conc": c or {}}]}

