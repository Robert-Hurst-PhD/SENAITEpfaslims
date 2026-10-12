# -*- coding: utf-8 -*-
"""A Lab workflow stage as a form.

A method's extraction stage is designed like a logbook: an ordered list of
questions, `stage["fields"]`. Two families:

  * Questions the lab writes (text, number, date, time, date and time, long
    text, checkbox, choice, section): answered at the bench, kept in the
    stage's record under "answers", judged by logbook_schema's rules
    (required, ranges, patterns, show-if).
  * Questions that record into the extraction record, with their binding
    fixed by the type:
        reagent_role    a reagent or standard picked by lot from the inventory
        consumable      a consumable picked by lot
        equipment       a piece of equipment by serial (a balance must have
                        passed its verification that day)
        confirmation    a check the chemist ticks
        sample_capture  the per-sample column: amount, final volume or SPE port
        solutions       solutions prepared at this stage (with labels)
        pedigree        the standard's parentage (CRM > stock > working)

The keys every other part of the system reads -- reagent_roles,
consumables, equipment, confirmations, captures_samples, creates_solution,
capture_pedigree -- are DERIVED from the fields when a stage is saved
(apply_fields), so the sidecar, FM-ENV-003, the traceability chain and the
review read exactly what they read before. A stage saved before forms
existed has no "fields": stage_fields() derives them from those keys, in
the order the guide always drew them, and nothing is written until a
manager saves the stage.

Pure. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy

try:
    from senaite.pfas import logbook_schema as LS
except ImportError:                                         # loaded by path (tests)
    import logbook_schema as LS

# bound type -> (the derived list key, the editor's label)
LISTED = {
    "reagent_role": ("reagent_roles", u"Reagent or standard (lot)"),
    "consumable": ("consumables", u"Consumable (lot)"),
    "equipment": ("equipment", u"Equipment"),
    "confirmation": ("confirmations", u"Check to tick"),
}
# bound type -> (the derived key, the editor's label); at most one each
SINGLE = {
    "sample_capture": ("captures_samples", u"Per-sample record"),
    "solutions": ("creates_solution", u"Solutions prepared"),
    "pedigree": ("capture_pedigree", u"Standard pedigree"),
}
BOUND_TYPES = tuple(LISTED) + tuple(SINGLE)
CAPTURE_BINDINGS = (u"amount", u"final_volume", u"spe_port")
CAPTURE_LABELS = {u"amount": u"Sample amount", u"final_volume": u"Final extract volume",
                  u"spe_port": u"SPE port"}
GENERIC_TYPES = ("text", "number", "date", "time", "datetime", "textarea", "checkbox",
                 "choice", "section")
DERIVED_KEYS = ("reagent_roles", "consumables", "equipment", "confirmations",
                "captures_samples", "creates_solution", "capture_pedigree")

# the guide's own form parameters: a question may not take one of these names
RESERVED_NAMES = frozenset(("action", "batch_uid", "stage_order", "reagents_json",
                            "equipment_sns_json", "solutions_prepared_json", "stage_analyst",
                            "samples_json", "deviations", "pedigree_json_stage", "method_id",
                            "analyst", "reason", "stage", "error", "ok"))

# the guide's blocks, in the order it always drew them
BLOCK_OF = {"sample_capture": "samples", "reagent_role": "reagents", "consumable": "consumables",
            "equipment": "equipment", "confirmation": "checks", "solutions": "solutions",
            "pedigree": "pedigree"}
LEGACY_ORDER = ("sample_capture", "reagent_role", "consumable", "equipment", "confirmation",
                "solutions", "pedigree")


def type_labels():
    """[(type, label)] for the editor's type picker: the lab's questions,
    then the ones that record into the extraction."""
    generic = [(t["type"], t["label"]) for t in LS.FIELD_TYPES if t["type"] in GENERIC_TYPES]
    bound = [(k, v[1]) for k, v in sorted(LISTED.items())] + [(k, v[1]) for k, v in sorted(SINGLE.items())]
    return generic + bound


def _name(prefix, label, taken):
    n = LS.column_name(u"%s %s" % (prefix, label or u""), taken)
    taken.add(n)
    return n


def fields_from_legacy(stage):
    """The questions a stage saved before forms existed amounts to, in the
    order the guide drew its blocks."""
    stage = stage or {}
    taken, out = set(), []
    cap = (stage.get("captures_samples") or u"").strip()
    if cap in CAPTURE_BINDINGS:
        out.append({"name": _name(u"capture", cap, taken), "type": "sample_capture",
                    "label": CAPTURE_LABELS[cap], "binding": cap})
    for t in ("reagent_role", "consumable", "equipment", "confirmation"):
        key = LISTED[t][0]
        for label in stage.get(key) or []:
            label = (label or u"").strip()
            if label:
                out.append({"name": _name(t, label, taken), "type": t, "label": label})
    if stage.get("creates_solution"):
        out.append({"name": _name(u"solutions", u"", taken), "type": "solutions",
                    "label": SINGLE["solutions"][1]})
    if stage.get("capture_pedigree"):
        out.append({"name": _name(u"pedigree", u"", taken), "type": "pedigree",
                    "label": SINGLE["pedigree"][1]})
    return out


def stage_fields(stage):
    """The stage's questions: its own, else derived from its keys."""
    fields = (stage or {}).get("fields")
    if isinstance(fields, list):
        return fields
    return fields_from_legacy(stage)


def legacy_from_fields(fields):
    """The keys the rest of the system reads, from the questions."""
    out = {"reagent_roles": [], "consumables": [], "equipment": [], "confirmations": [],
           "captures_samples": u"", "creates_solution": False, "capture_pedigree": False}
    for f in fields or []:
        t = (f or {}).get("type")
        if t in LISTED:
            label = (f.get("label") or u"").strip()
            if label:
                out[LISTED[t][0]].append(label)
        elif t == "sample_capture":
            out["captures_samples"] = f.get("binding") if f.get("binding") in CAPTURE_BINDINGS else u""
        elif t == "solutions":
            out["creates_solution"] = True
        elif t == "pedigree":
            out["capture_pedigree"] = True
    return out


def legacy_view(stage):
    """A stage's derived keys as they stand (for the equivalence check)."""
    stage = stage or {}
    return {"reagent_roles": [x for x in (stage.get("reagent_roles") or []) if (x or u"").strip()],
            "consumables": [x for x in (stage.get("consumables") or []) if (x or u"").strip()],
            "equipment": [x for x in (stage.get("equipment") or []) if (x or u"").strip()],
            "confirmations": [x for x in (stage.get("confirmations") or []) if (x or u"").strip()],
            "captures_samples": (stage.get("captures_samples") or u"")
            if (stage.get("captures_samples") or u"") in CAPTURE_BINDINGS else u"",
            "creates_solution": bool(stage.get("creates_solution")),
            "capture_pedigree": bool(stage.get("capture_pedigree"))}


def apply_fields(stage, fields):
    """The stage with these questions and the keys derived from them."""
    out = copy.deepcopy(stage or {})
    out["fields"] = copy.deepcopy(fields or [])
    out.update(legacy_from_fields(fields))
    return out


def generic_fields(stage):
    """The lab's own questions of a stage (answered, judged, kept as answers)."""
    return [f for f in stage_fields(stage) if (f or {}).get("type") in GENERIC_TYPES]


def validate(fields):
    """Sentences for what is wrong with a stage's questions; [] when fine."""
    errors = []
    if not isinstance(fields, list):
        return [u"A stage's questions must be a list."]
    singles, names = {}, set()
    for i, f in enumerate(fields):
        where = u"Question %d" % (i + 1)
        if not isinstance(f, dict):
            errors.append(u"%s: not a question." % where)
            continue
        t = f.get("type") or "text"
        name = (f.get("name") or u"").strip()
        if t not in GENERIC_TYPES and t not in BOUND_TYPES:
            errors.append(u"%s ('%s'): unknown type '%s'." % (where, name or u"?", t))
            continue
        if name in RESERVED_NAMES or name.startswith(u"confirmed_"):
            errors.append(u"%s ('%s'): the name is used by the guide itself; choose another." % (where, name))
        if name and name in names:
            errors.append(u"%s: duplicate name '%s'." % (where, name))
        names.add(name)
        if t in BOUND_TYPES and t not in ("solutions", "pedigree") and not (f.get("label") or u"").strip():
            errors.append(u"%s: a %s needs its name." % (where, (LISTED.get(t) or SINGLE.get(t))[1].lower()))
        if t in SINGLE:
            singles[t] = singles.get(t, 0) + 1
            if singles[t] == 2:
                errors.append(u"%s: a stage has one %s." % (where, SINGLE[t][1].lower()))
        if t == "sample_capture" and f.get("binding") not in CAPTURE_BINDINGS:
            errors.append(u"%s: the per-sample record must be the amount, the final volume or the SPE port." % where)
    generic = [f for f in fields if isinstance(f, dict) and f.get("type") in GENERIC_TYPES]
    errors += [u"%s" % e for e in LS.validate_schema(generic)]
    return errors


def layout(stage):
    """What the guide draws, in order: {"block": name} for the extraction
    blocks (each at its first question's place; homogenisation after the
    equipment, or after the last sample / lot block) and {"field": f} for
    the lab's own questions."""
    items, seen = [], set()
    for f in stage_fields(stage):
        t = (f or {}).get("type")
        if t in BLOCK_OF:
            b = BLOCK_OF[t]
            if b not in seen:
                seen.add(b)
                items.append({"block": b})
        elif t in GENERIC_TYPES:
            items.append({"field": f})
    anchor = None
    for i, it in enumerate(items):
        if it.get("block") == "equipment":
            anchor = i
    if anchor is None:
        for i, it in enumerate(items):
            if it.get("block") in ("samples", "reagents", "consumables"):
                anchor = i
    items.insert(0 if anchor is None else anchor + 1, {"block": "homogenisation"})
    return items


def answer_rows(stage, answers):
    """[(label, text)] for a stage record's answers to its own questions, in
    the stage's order: a choice by its options' labels, a checkbox Yes / No,
    headings and unanswered questions left out."""
    answers = answers or {}
    out = []
    for f in generic_fields(stage):
        t, name = f.get("type"), f.get("name")
        if t == "section" or name not in answers:
            continue
        v = answers.get(name)
        if t == "checkbox":
            text = u"Yes" if v in (True, u"yes", u"on", u"1", 1) else u"No"
        elif t == "choice":
            labels = dict((u"%s" % o.get("value"), o.get("label") or o.get("value"))
                          for o in f.get("options") or [] if isinstance(o, dict))
            picked = v if isinstance(v, (list, tuple)) else ([v] if v not in (None, u"") else [])
            text = u", ".join(u"%s" % labels.get(u"%s" % p, p) for p in picked)
        elif isinstance(v, (list, tuple)):
            text = u", ".join(u"%s" % x for x in v)
        else:
            text = u"%s" % (v if v is not None else u"")
        if text.strip():
            out.append((f.get("label") or name, text))
    return out
