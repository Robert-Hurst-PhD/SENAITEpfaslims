# -*- coding: utf-8 -*-
"""A prepared lot's record: the recipe revision it was made
by (pinned: a later revision does not change the lot), the log it is on,
made and expires (and why), its parentage as a tree down to the purchased
material, the recipe's steps, its concentrations -- calculated from its
recipe or, on a lot made before recipes, typed -- and the lots made in the
same sitting.

    tree_rows(rec, nodes, recipe_label) -> [{"depth", "lot", "name", "note", "problem"}]
    expiry_note(rec, shelf_days)        -> why it expires when it does
    steps(rev, who)                     -> [(n, instruction, who)]
    conc_rows(rec)                      -> [{"analyte", "value", "how"}]
    sitting(entry, lots_by_uid)         -> [lot number]
    label_rows(entry, lots_by_uid)      -> one label's values per lot of the sitting

`nodes` are prepared_standards.build_parentage's. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import datetime


def _amount(node):
    q = (u"%s %s" % (node.get("qty") or u"", node.get("unit") or u"")).strip()
    return u"%s · %s" % (node.get("name") or u"", q) if q else node.get("name") or u""


def _note(node, recipe_label):
    if node.get("problems"):
        return node["problems"][0]
    kind = node.get("kind")
    if kind == u"prepared":
        pin = node.get("recipe") or {}
        if pin.get("id") and recipe_label:
            return u"made here · recipe %s" % recipe_label(pin["id"], pin.get("revision"))
        return u"made here"
    if kind == u"water":
        return u"in-house water"
    if node.get("has_certificate_values"):
        return u"purchased · Certificate values"
    return u"purchased"


def tree_rows(rec, nodes, recipe_label):
    """The lot, then each parent indented under what it made."""
    rows = [{"depth": 0, "lot": rec.get("lot_number") or u"", "name": rec.get("title") or u"",
             "note": u"this lot", "problem": False}]

    def walk(ns, depth):
        for n in ns or []:
            rows.append({"depth": depth, "lot": n.get("lot") or u"", "name": _amount(n),
                         "note": _note(n, recipe_label), "problem": bool(n.get("problems"))})
            walk(n.get("children"), depth + 1)
    walk(nodes, 1)
    return rows


def expiry_note(rec, shelf_days):
    if rec.get("expiry_inherited_from"):
        return u"no later than its parent %s" % rec["expiry_inherited_from"]
    try:
        made = datetime.datetime.strptime((rec.get("prepared_date") or u"")[:10], "%Y-%m-%d").date()
        own = (made + datetime.timedelta(days=int(shelf_days))).isoformat()
    except (TypeError, ValueError):
        return u""
    if own == (rec.get("expiry_date") or u"")[:10]:
        return u"the recipe's shelf life, %d days after preparation" % int(shelf_days)
    return u""


def steps(rev, who):
    out = []
    for i, s in enumerate((rev or {}).get("steps") or []):
        text = s.get("instruction") if isinstance(s, dict) else s
        if text:
            out.append((i + 1, text, who or u""))
    return out


def conc_rows(rec):
    out = []
    for c in rec.get("analyte_concentrations") or []:
        v = (u"%s" % (c.get("concentration") or u"")).strip()
        if not c.get("calculated"):
            how = u"typed"
        elif c.get("basis") == u"acid" and v:
            how = u"calculated, as acid"
        else:
            how = u"calculated"
        out.append({"analyte": c.get("analyte") or u"",
                    "value": (u"%s %s" % (v, c.get("unit") or u"")).strip() if v else u"", "how": how})
    return out


def sitting(entry, lots_by_uid):
    return [(lots_by_uid.get(u) or {}).get("lot_number") or u"?" for u in (entry or {}).get("lots") or []]


def label_rows(entry, lots_by_uid):
    """One label per lot the sitting made, with that lot's own values
    (the fields @@pfas-label prints)."""
    out = []
    for uid in (entry or {}).get("lots") or []:
        r = lots_by_uid.get(uid)
        if not r:
            continue
        out.append({"name": r.get("title") or u"", "lot": r.get("lot_number") or u"",
                    "exp": r.get("effective_expiry") or r.get("expiry_date") or u"",
                    "date": r.get("prepared_date") or u"", "analyst": r.get("prepared_by") or u"",
                    "vol": r.get("volume_prepared") or u"",
                    "storage": r.get("storage_conditions") or r.get("storage_location") or u""})
    return out
