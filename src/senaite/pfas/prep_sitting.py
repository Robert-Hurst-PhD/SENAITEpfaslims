# -*- coding: utf-8 -*-
"""A prep sitting made from its recipe.

New Prepared Standard is one sitting on a prep log, made from one recipe
revision. The lots it makes are named from the method's code and the
recipe's levels (a series makes one lot per level), numbered by the prep
date; their concentrations are calculated from the parent lot actually
picked -- a purchased lot's certificate values as acid, a made lot's own --
with the measured volumes, never typed. Each concentration says whether it
rests on certificate values as acid ("acid") or on a typed value somewhere
up the chain ("typed"). Expiry is the recipe's shelf life from the prep
date, no later than the earliest parent's. Every lot is pinned to the
recipe and revision that made it.

    lot_names(rev, code)              -> [(level, title)]
    statement(names)                  -> "This sitting makes 7 lots, ..."
    lot_number(title, day, taken)     -> "537_CAL-1_261013" (-2 when taken)
    parent_values(item, cert, unit)   -> ({analyte: value}, {analyte: basis})
    build(rev, rid, code, sitting, parents) -> (entry, rows, [problem])
    edit_values(form, rec)            -> what an edit keeps that it does not post

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

from senaite.pfas import recipe_calc as rc
from senaite.pfas.parentage_checks import default_expiry

ACID, TYPED = u"acid", u"typed"


def lot_names(rev, code):
    """[(level, title)]: a series one per level, titled "<code>_<level>"
    (a level already named with the code keeps its name); a single recipe
    one lot under the recipe's name, its level the LC channel it is loaded
    on ("slot") when the recipe names one, else its name."""
    levels = ((rev or {}).get("series") or {}).get("levels") or []
    if not levels:
        name = (rev or {}).get("name") or u""
        return [((rev or {}).get("slot") or name, name)]
    out = []
    for lv in levels:
        level = (lv.get("level") or u"").strip()
        prefix = u"%s_" % code if code else u""
        out.append((level, level if not prefix or level.startswith(prefix) else prefix + level))
    return out


def statement(names):
    titles = [t for _l, t in names or []]
    if len(titles) == 1:
        return u"This sitting makes one lot, %s." % titles[0]
    return u"This sitting makes %d lots, %s to %s, one per level." % (len(titles), titles[0], titles[-1])


def lot_number(title, day, taken=()):
    """"<title>_<YYMMDD>", with -2, -3 ... when the inventory already has it
    (a second sitting of the same recipe that day)."""
    base = u"%s_%s" % (title, (day or u"").replace(u"-", u"")[2:8])
    out, n = base, 1
    while out in (taken or ()):
        n += 1
        out = u"%s-%d" % (base, n)
    return out


def parent_values(item, cert=None, unit=u"ng/mL"):
    """A parent lot's concentrations in `unit` and their basis: a purchased
    lot's certificate values as acid; a made lot's own, acid only when they
    were calculated as acid."""
    item = item or {}
    if item.get("kind") != u"prepared_standard":
        values = rc.certificate_concentrations(cert, unit) if cert else {}
        return values, dict((a, ACID if v is not None else TYPED) for a, v in values.items())
    values, basis = {}, {}
    for c in item.get("analyte_concentrations") or []:
        name = c.get("analyte")
        if not name:
            continue
        values[name] = rc.convert(c.get("concentration"), c.get("unit"), unit)
        basis[name] = ACID if c.get("basis") == ACID and values[name] is not None else TYPED
    return values, basis


def _fmt(v):
    return u"" if v is None else u"%.6g" % v


from senaite.pfas.rounding import number as _num


def _conc_rows(values, basis, unit):
    return [{"analyte": a, "concentration": _fmt(values[a]), "unit": unit, "calculated": True,
             "basis": (basis.get(a) or TYPED) if values[a] is not None else TYPED} for a in sorted(values)]


def build(rev, rid, code, sitting, parents):
    """(entry, rows, problems) for prep_entries.make. `sitting`: the log
    (form_code, slug, revision, title), prepared_by, prepared_date,
    standard_type, needs_values (a standard: refuse what cannot be
    calculated), taken (lot numbers already used), storage_location /
    storage_conditions (blank: the
    recipe's), equipment, final (the measured final volume, blank: the
    recipe's) and shelf_days. `parents`: one per "made from", in order:
    {"item": the picked lot or None, "cert": a purchased lot's certificate,
    "qty", "unit"}; the first is the one the concentrations come from."""
    rev, s = rev or {}, sitting or {}
    unit = rev.get("unit") or u"ng/mL"
    made_from = rev.get("made_from") or []
    problems, entry_parents, expiries = [], [], []
    for i, mf in enumerate(made_from):
        p = parents[i] if i < len(parents or []) else {}
        item = p.get("item")
        if not item:
            problems.append(u"Choose the lot of %s." % (mf.get("ref") or u"the parent"))
            continue
        entry_parents.append({"kind": item.get("kind"), "uid": item.get("uid"), "lot": item.get("lot_number"),
                              "name": item.get("name") or u"", "qty": p.get("qty") or u"",
                              "unit": p.get("unit") or u""})
        if item.get("expiry"):
            expiries.append(item["expiry"])
    first = (parents or [{}])[0] if parents else {}
    stock, basis = parent_values(first.get("item"), first.get("cert"), unit) if first.get("item") else ({}, {})
    if s.get("needs_values") and first.get("item"):
        # a standard is calculated, never typed: refuse what cannot be calculated
        it = first["item"]
        if not stock:
            problems.append(u"No concentrations can be calculated: %s lot %s has no %s on file." % (
                it.get("name") or u"the parent", it.get("lot_number") or u"",
                u"concentrations" if it.get("kind") == u"prepared_standard" else u"certificate values"))
        else:
            missing = sorted(a for a, v in stock.items() if v is None)
            if missing:
                problems.append(u"%s cannot be calculated: stated as salt with no molecular weights entered, "
                                u"or no value on the parent." % u", ".join(missing))
    storage = rev.get("storage") or {}
    pin = {"id": rid, "revision": rev.get("revision")}
    final = _num(s.get("final"))
    levels = (rev.get("series") or {}).get("levels") or []
    if levels:
        scale = final / _num(levels[0].get("final")) if final and _num(levels[0].get("final")) else 1.0
        concs = rc.series(stock, levels, (rev.get("series") or {}).get("mode") or u"serial")
        volumes = [u"%g %s" % ((_num(lv.get("final")) or 0) * scale, lv.get("final_unit") or u"mL")
                   if _num(lv.get("final")) else u"" for lv in levels]
    else:
        mf = made_from[0] if made_from else {}
        take = _num(first.get("qty")) if _num(first.get("qty")) is not None else mf.get("take")
        take_unit = first.get("unit") or mf.get("take_unit")
        fv = final if final is not None else _num(rev.get("final_volume"))
        concs = [rc.diluted(stock, take, take_unit, fv, rev.get("final_unit"))]
        volumes = [u"%g %s" % (fv, rev.get("final_unit") or u"mL") if fv else u""]
    shelf = s.get("shelf_days")
    cap = min(expiries) if expiries else u""
    day = s.get("prepared_date") or u""
    if shelf not in (None, u"") and day:
        expiry = default_expiry(day, int(shelf), cap)[0]
    else:
        expiry = cap
    rows = []
    for (level, title), conc, vol in zip(lot_names(rev, code), concs, volumes):
        rows.append({"title": title, "lot_number": lot_number(title, day, s.get("taken") or ()), "level": level,
                     "standard_type": s.get("standard_type") or u"",
                     "storage_conditions": s.get("storage_conditions") or storage.get("conditions") or u"",
                     "volume_prepared": vol, "expiry_date": expiry,
                     "analyte_concentrations": _conc_rows(conc or dict((a, None) for a in stock), basis, unit),
                     "recipe": dict(pin)})
    entry = {"form_code": s.get("form_code") or u"", "logbook_slug": s.get("slug") or rev.get("log") or u"",
             "logbook_revision": s.get("revision") or 1, "logbook_title": s.get("title") or u"",
             "prepared_by": s.get("prepared_by") or u"", "prepared_date": day,
             "storage_location": s.get("storage_location") or storage.get("location") or u"",
             "equipment": list(s.get("equipment") or []), "parents": entry_parents,
             "unknown_parents": [], "recipe": dict(pin)}
    return entry, rows, problems


_KEPT = ("logbook_slug", "logbook_title", "logbook_revision", "expiry_notes")
_KEPT_JSON = (("parent_reagents", "parent_reagents_json"), ("analyte_concentrations", "analyte_concentrations_json"))


def edit_values(form, rec):
    """The fields an edit sets only when it posts them; a field not posted
    keeps the lot's own value, as status and equipment do."""
    form, rec = form or {}, rec or {}
    out = dict((k, form[k] if k in form else rec.get(k)) for k in _KEPT)
    for key, field in _KEPT_JSON:
        if field in form:
            try:
                out[key] = json.loads(form.get(field) or "[]")
            except (TypeError, ValueError):
                out[key] = rec.get(key) or []
        else:
            out[key] = rec.get(key) or []
    return out
