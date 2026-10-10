# -*- coding: utf-8 -*-
"""Lists the lab edits: a term is {key, label, active}.

The seed is the list the code shipped; the lab relabels a term, adds one, or
withdraws one (it leaves new picks, and a record that holds it keeps it and
still shows its label). A term's key never changes and a term is never
deleted, so no stored record is orphaned by an edit. Lists whose terms the
code branches on (equipment kinds, QC roles, statuses) are not here.

    LISTS                          {name: (title, seed [(key, label)])}
    terms(stored, name)            pure: every term, seed merged with the lab's
    choices(stored, name, keep)    pure: [(key, label)] to pick from (active,
                                   plus `keep`, a record's current value)
    options(stored, name)          pure: every term, withdrawn ones marked
    label(stored, name, key)       pure: a term's label (the key when unknown)
    edit(stored, name, rows, new)  pure: (stored', [problem])
    get(portal) / save(portal, d)  the annotation

Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import re

KEY = "senaite.pfas.vocabularies"

# name -> (title, seed). Seeds equal the lists the code shipped; a string-
# stored list keys each term by its string, so stored values are unchanged.
LISTS = {
    "deviation_event_types": (u"Deviation event types", [
        (u"missed_calibration", u"Missed Calibration"),
        (u"missed_verification", u"Missed Verification"),
        (u"procedure_deviation", u"Procedure Deviation"),
        (u"equipment_failure", u"Equipment Failure"),
        (u"reagent_issue", u"Reagent / Standard Issue"),
        (u"data_entry_error", u"Data Entry Error"),
        (u"other", u"Other")]),
    "regulatory_limit_kinds": (u"Regulatory limit kinds", [
        (k, k) for k in (u"MCL", u"Interim standard", u"Action level", u"Advisory")]),
    # stored as the string on each lot; three of them the code branches on
    # (content/reagent.py CATEGORY_*): those keys stay, only labels change
    "reagent_categories": (u"Reagent categories", [(k, k) for k in (
        u"Mobile Phase / Solvent", u"Extraction Reagent", u"Standard / Reference Material",
        u"Internal Standard", u"Buffer", u"Acid / Base", u"Salt",
        u"Reagent Water \u2014 in-house Type 1", u"Reagent Water \u2014 purchased",
        u"Consumable", u"Other Reagent")]),
    # stored as the string on each lot; prep logbooks filter lots by it
    "prepared_standard_types": (u"Prepared standard types", [(k, k) for k in (
        u"Calibration Standard", u"QC Check Standard", u"Surrogate Mix",
        u"Internal Standard Mix", u"Matrix Spike", u"Solvent / Reagent", u"Other")]),
}


def _seed(name):
    return [{"key": k, "label": l, "active": True} for k, l in LISTS[name][1]]


def terms(stored, name):
    """Every term of `name`: the seed's, relabelled / withdrawn as the lab
    saved them, then the lab's own, in the saved order."""
    saved = (stored or {}).get(name)
    if not saved:
        return _seed(name)
    out, seen = [], set()
    for t in saved:
        if t.get("key") and t["key"] not in seen:
            seen.add(t["key"])
            out.append({"key": t["key"], "label": t.get("label") or t["key"],
                        "active": bool(t.get("active", True))})
    for t in _seed(name):                 # a seed term the saved list lacks
        if t["key"] not in seen:
            out.append(t)
    return out


def choices(stored, name, keep=None):
    """[(key, label)] to choose from: the active terms, and `keep` (the
    record's current value) even if withdrawn or unknown."""
    out = [(t["key"], t["label"]) for t in terms(stored, name) if t["active"]]
    if keep and keep not in [k for k, _l in out]:
        out.append((keep, label(stored, name, keep)))
    return out


def options(stored, name):
    """[(key, label)] for every term, a withdrawn one marked so: an edit
    form, where a record may already hold a withdrawn term, or a filter."""
    return [(t["key"], t["label"] if t["active"] else u"%s (withdrawn)" % t["label"])
            for t in terms(stored, name)]


def label(stored, name, key):
    for t in terms(stored, name):
        if t["key"] == key:
            return t["label"]
    return key or u""


def _new_key(label_text, taken):
    base = re.sub(r"[^a-z0-9]+", u"_", (label_text or u"").lower()).strip(u"_") or u"term"
    key, n = base, 2
    while key in taken:
        key, n = u"%s_%d" % (base, n), n + 1
    return key


def edit(stored, name, rows, new_label=u""):
    """(stored', problems). `rows` = [{key, label, active}] for the existing
    terms (a key not already a term is ignored: keys are never invented by
    the form); `new_label` adds a term. A label may not be blank or repeat
    another's."""
    current = terms(stored, name)
    by_key = dict((t["key"], t) for t in current)
    problems = []
    for r in rows or []:
        t = by_key.get(r.get("key"))
        if t is None:
            continue
        lab = (r.get("label") or u"").strip()
        if not lab:
            problems.append(u"%s: a term needs a label." % t["key"])
            continue
        t["label"] = lab
        t["active"] = bool(r.get("active"))
    new_label = (new_label or u"").strip()
    if new_label:
        current.append({"key": _new_key(new_label, set(by_key)), "label": new_label,
                        "active": True})
    labels = [t["label"].lower() for t in current]
    dup = sorted(set(l for l in labels if labels.count(l) > 1))
    if dup:
        problems.append(u"Two terms are labelled %s." % u", ".join(dup))
    if problems:
        return stored, problems
    out = dict(stored or {})
    out[name] = current
    return out, []


def get(portal):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(portal).get(KEY) or u"{}")
    except (TypeError, ValueError):
        return {}


def save(portal, data):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(portal)[KEY] = json.dumps(data)
