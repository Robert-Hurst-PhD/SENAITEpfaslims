# -*- coding: utf-8 -*-
"""Recipes: what is made on a prep log and how.

A logbook template is the form; a recipe is what is made on it -- what it
is made from, how much is taken into what final volume, the steps and the
shelf life -- and names its log (FM-ENV-001 or 002). Recipes are site-wide:
a reagent shared by methods is one recipe that each method lists. Each is
revised like a logbook template: a Draft is edited, made Active (the prior
Active revision is archived), and never edited once active; a lot is pinned
to the revision it was made by.

    store = {recipe id: [revision, ...]}
    revision = {"revision", "status": draft|active|archived, "name", "log",
                "methods", "made_from": [{"kind": purchased|recipe, "ref",
                "take", "take_unit"}], "final_volume", "final_unit", "unit",
                "series": {"levels": [...], "mode": serial|independent},
                "steps": [text], "shelf_life_days", "by", "at"}

Nothing is seeded (SEEDED is empty): every amount and shelf life is the
lab's. Pure helpers first; the storage helpers import Plone lazily.
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json
import re

KEY = "senaite.pfas.recipes"
DRAFT, ACTIVE, ARCHIVED = u"draft", u"active", u"archived"
SEEDED = ()

_FIELDS = ("name", "log", "methods", "made_from", "final_volume", "final_unit", "unit",
           "series", "steps", "shelf_life_days", "storage", "slot")


def _id_for(name, taken):
    base = re.sub(r"[^a-z0-9]+", u"-", (name or u"").lower()).strip(u"-") or u"recipe"
    rid, n = base, 2
    while rid in taken:
        rid, n = u"%s-%d" % (base, n), n + 1
    return rid


from senaite.pfas.rounding import number as _num


def problems(data):
    """What a recipe needs before it is saved."""
    out = []
    if not (data.get("name") or u"").strip():
        out.append(u"Give the recipe a name.")
    if not (data.get("log") or u"").strip():
        out.append(u"Say which prep log it is made on.")
    if not data.get("made_from"):
        out.append(u"Say what it is made from.")
    levels = (data.get("series") or {}).get("levels") or []
    if levels:
        for lv in levels:
            f = _num(lv.get("final"))
            if f is None or f <= 0:
                out.append(u"%s: give its final volume." % (lv.get("level") or u"A level"))
    else:
        fv = _num(data.get("final_volume"))
        if fv is None or fv <= 0:
            out.append(u"Give the final volume.")
    return out


def _t(form, key):
    v = form.get(key)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else u""
    return (u"%s" % (v or u"")).strip()


def _idx(form, prefix):
    return sorted(set(int(k[len(prefix):]) for k in form if k.startswith(prefix) and k[len(prefix):].isdigit()))


def from_form(form):
    """A recipe from the editor: indexed rows for what it is made from
    (mf_*.N), a series' levels (lv_*.N) and the steps (step_*.N), in index
    order; an empty row is no row."""
    methods = form.get("methods") or []
    if not isinstance(methods, (list, tuple)):
        methods = [methods]
    # a switch per method (method.<id>): the page's form, whose lists are flattened
    methods = list(methods) + sorted(k[len("method."):] for k in form
                                     if k.startswith("method.") and form.get(k) and k[len("method."):] not in methods)
    made = [{"kind": _t(form, "mf_kind.%d" % i) or u"purchased", "ref": _t(form, "mf_ref.%d" % i),
             "take": _num(_t(form, "mf_take.%d" % i)), "take_unit": _t(form, "mf_take_unit.%d" % i) or u"mL"}
            for i in _idx(form, "mf_ref.") if _t(form, "mf_ref.%d" % i)]
    levels = [{"level": _t(form, "lv_name.%d" % i), "take": _num(_t(form, "lv_take.%d" % i)),
               "take_unit": _t(form, "lv_take_unit.%d" % i) or u"mL",
               "final": _num(_t(form, "lv_final.%d" % i)), "final_unit": _t(form, "lv_final_unit.%d" % i) or u"mL"}
              for i in _idx(form, "lv_name.") if _t(form, "lv_name.%d" % i)]
    steps = [{"instruction": _t(form, "step_text.%d" % i), "amount": _t(form, "step_amount.%d" % i),
              "equipment": _t(form, "step_equipment.%d" % i), "check": _t(form, "step_check.%d" % i)}
             for i in _idx(form, "step_text.") if _t(form, "step_text.%d" % i)]
    shelf = _t(form, "shelf_life_days")
    return {"name": _t(form, "name"), "log": _t(form, "log"),
            "methods": [m for m in methods if m],
            "made_from": made, "final_volume": _num(_t(form, "final_volume")),
            "final_unit": _t(form, "final_unit") or u"mL", "unit": _t(form, "unit") or u"ng/mL",
            "series": ({"mode": _t(form, "series_mode") or u"serial", "levels": levels} if levels else {}),
            "steps": steps, "shelf_life_days": int(float(shelf)) if shelf else None,
            "storage": {"location": _t(form, "storage_location"), "conditions": _t(form, "storage_conditions")},
            # the LC channel its lots are loaded on (the Run Builder's slot), if any
            "slot": _t(form, "slot")}


def _clean(data):
    return dict((k, copy.deepcopy(data.get(k))) for k in _FIELDS)


def revisions(store, rid):
    return list((store or {}).get(rid) or [])


def active(store, rid):
    return next((r for r in revisions(store, rid) if r.get("status") == ACTIVE), None)


def new_recipe(store, data, who, at):
    """(store, recipe id): revision 1, a draft."""
    store = copy.deepcopy(store or {})
    rid = _id_for(data.get("name"), store)
    store[rid] = [dict(_clean(data), revision=1, status=DRAFT, by=who, at=at)]
    return store, rid


def save_draft(store, rid, rev, data):
    """(store, error): a draft revision edited; an active or archived one is
    never edited (make a new revision)."""
    revs = revisions(store, rid)
    cur = next((r for r in revs if r.get("revision") == rev), None)
    if cur is None:
        return store, u"No such recipe revision."
    if cur.get("status") != DRAFT:
        return store, u"Revision %d is %s: make a new revision to change it." % (rev, cur.get("status"))
    out = copy.deepcopy(store)
    for r in out[rid]:
        if r.get("revision") == rev:
            r.update(_clean(data))
    return out, u""


def activate(store, rid, rev, who, at):
    """The revision made active; the prior active one archived."""
    out = copy.deepcopy(store)
    for r in out.get(rid) or []:
        if r.get("revision") == rev:
            r.update(status=ACTIVE, activated_by=who, activated_at=at)
        elif r.get("status") == ACTIVE:
            r["status"] = ARCHIVED
    return out


def new_revision(store, rid, who, at):
    """(store, revision): a draft copy of the newest revision, numbered next."""
    revs = revisions(store, rid)
    if not revs:
        return store, None
    newest = max(revs, key=lambda r: r.get("revision") or 0)
    n = (newest.get("revision") or 0) + 1
    out = copy.deepcopy(store)
    out[rid].append(dict(_clean(newest), revision=n, status=DRAFT, by=who, at=at))
    return out, n


def for_method(store, method_id):
    """The active revisions of the recipes a method lists."""
    out = []
    for rid in sorted(store or {}):
        a = active(store, rid)
        if a and method_id in (a.get("methods") or []):
            out.append(dict(a, id=rid))
    return out


def shelf_life(rev, log_defaults):
    """The recipe's shelf life in days, else its log's default (each prep
    template's default expiry), else None."""
    own = rev.get("shelf_life_days")
    if own not in (None, u""):
        return int(own)
    d = (log_defaults or {}).get(rev.get("log"))
    return int(d) if d not in (None, u"") else None


# ── storage (Plone) ───────────────────────────────────────────────────────

def load(portal):
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(portal).get(KEY)
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def save(portal, store):
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import config_history
    config_history.track(portal, "recipes", "all", lambda: load(portal), label=u"Recipes")
    IAnnotations(portal)[KEY] = json.dumps(store, sort_keys=True)
