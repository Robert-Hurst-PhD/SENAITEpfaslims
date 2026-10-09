# -*- coding: utf-8 -*-
"""A method study's parts, each assigned to one analyst as a study worksheet.

A part is one element of a study -- the precision and accuracy replicates,
the MRL-confirmation replicates, the detection-limit replicates, the MDL
spikes and blanks -- given to one analyst. Assigning it makes a SENAITE
worksheet (its Analyst = that person) whose extraction batch holds the part's
replicates; the study reads its results from those worksheets. Only the
configuration tier assigns.

A study run holds no client sample, so it has no chain of custody. What
stands in its place is the study's matrix SOURCE, chosen per part:

  water_system    the in-house reagent water system; its provenance is the
                  reagent-water check of the day of the extraction
                  (facility_qc.get_water_qc_for_date)
  water_lot       a vendor reagent-water lot from the inventory
  reference_lot   a reference sample received into the inventory
                  ("Standard / Reference Material"): its receipt record
                  and its CoA are required

Data Review's chain-of-custody item reads the worksheet's study run record
(STUDY_RUN_KEY) and states the source instead.

    new_part(rec, ...)               -> (part, problem)
    plan(part, method_id)            -> {extraction-batch role: count}
    run_record(rec, part)            -> what the study worksheet carries
    source_problems(...)             -> why the source cannot stand in for a CoC
    coc_item(run, problems)          -> (label, verdict, reason) for Data Review
    new_receipt(form, by, at)        -> (receipt, problem)

Pure helpers + the annotation shell. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

try:
    from senaite.pfas.study_data import blank_role
except ImportError:                    # tests: loaded by path
    from study_data import blank_role

STUDY_RUN_KEY = "senaite.pfas.study_run"
RECEIPT_KEY = "senaite.pfas.reagent.receipt"

BLANK = None                           # the method's own blank role (blank_role)
LFB = u"LFB"
# element -> (label, the extraction-batch role its replicates take, the
# default number of replicates per assignment)
ELEMENTS = [
    ("pa", u"Precision and accuracy replicates (near mid-calibration)", LFB, 4),
    ("mrl", u"MRL confirmation replicates (at the proposed MRL)", LFB, 7),
    ("dl", u"Detection-limit replicates (one run per day)", LFB, 3),
    ("mdl", u"MDL spiked replicates", LFB, 3),
    ("blank", u"Method blanks", BLANK, 3),
]
ELEMENT = dict((e[0], e) for e in ELEMENTS)
# the parts a study of each kind may have (a proficiency test has none: its
# sample is the provider's)
KIND_ELEMENTS = {"pa": ("pa",), "mrl": ("mrl",), "dl": ("dl",), "mdl": ("mdl", "blank")}
WATER_SYSTEM, WATER_LOT, REFERENCE_LOT = u"water_system", u"water_lot", u"reference_lot"
SOURCES = [(WATER_SYSTEM, u"In-house reagent water system"),
           (WATER_LOT, u"Vendor reagent water (inventory lot)"),
           (REFERENCE_LOT, u"Reference sample (inventory lot, receipt and CoA)")]
SOURCE_LABELS = dict(SOURCES)


def elements_for(kind):
    return [ELEMENT[e] for e in KIND_ELEMENTS.get(kind, ())]


def role_for(element, method_id):
    role = ELEMENT[element][2]
    return blank_role(method_id) if role is BLANK else role


def next_part_id(parts):
    nums = [int(p["id"][1:]) for p in parts or [] if p.get("id", u"")[1:].isdigit()]
    return u"P%d" % (max(nums or [0]) + 1)


def new_part(rec, element, analyst, analyst_name, level, replicates, source, by, at):
    """(part, problem). The caller appends the part to rec["parts"]."""
    if rec.get("status") != u"draft":
        return None, u"An approved study is not changed."
    if element not in KIND_ELEMENTS.get(rec.get("kind"), ()):
        return None, u"This kind of study has no such part."
    if not analyst:
        return None, u"Choose the analyst who performs it."
    kind = (source or {}).get("kind")
    if kind not in SOURCE_LABELS:
        return None, u"Choose where the study's matrix comes from."
    if kind != WATER_SYSTEM and not source.get("uid"):
        return None, u"Choose the lot the replicates are made in."
    if replicates in (None, u"", ""):
        n = ELEMENT[element][3]
    else:
        try:
            n = int(replicates)
        except (TypeError, ValueError):
            return None, u"Give the number of replicates."
    if n < 1:
        return None, u"At least one replicate."
    level = (level or u"").strip()
    if ELEMENT[element][2] == LFB:
        if not level:
            return None, u"Choose the spiking level."
        if rec.get("levels") and level not in rec["levels"]:
            # the study reads only its own levels: a part at another level
            # would be run and then never counted
            return None, u"The study runs %s, not %s." % (u", ".join(rec["levels"]), level)
    else:
        level = u""
    part = {"id": next_part_id(rec.get("parts")), "element": element, "analyst": analyst,
            "analyst_name": analyst_name or analyst, "level": level, "replicates": n,
            "source": dict(source), "worksheets": [], "by": by, "at": at}
    return part, u""


def add_reference(rec, source):
    """A part made in a reference sample names it in the study's own list of
    reference materials (one list, never a second)."""
    if (source or {}).get("kind") != REFERENCE_LOT:
        return
    rms = rec.setdefault("reference_materials", [])
    if source.get("uid") not in [m.get("uid") for m in rms]:
        rms.append({"uid": source["uid"], "name": source.get("name") or u"",
                    "lot_number": source.get("lot_number") or u""})


def plan(part, method_id):
    """{extraction-batch role: count} for one assignment of the part."""
    return {role_for(part["element"], method_id): part["replicates"]}


def set_levels(members, part):
    """The part's spiking level on its spiked members (they are created
    without one)."""
    out = []
    for m in members:
        m = dict(m)
        if part.get("level") and m.get("role") == LFB and not m.get("level"):
            m["level"] = part["level"]
        out.append(m)
    return out


def study_worksheets(rec):
    """Every worksheet a study draws from: its parts' and the typed ones."""
    out = list(rec.get("worksheets") or [])
    for p in rec.get("parts") or []:
        for w in p.get("worksheets") or []:
            if w not in out:
                out.append(w)
    return out


def run_record(rec, part):
    """What the study worksheet carries (STUDY_RUN_KEY)."""
    return {"study": rec["id"], "part": part["id"], "element": part["element"],
            "method_id": rec["method"], "matrix": rec["matrix"], "source": part["source"],
            "analyst": part["analyst"], "level": part.get("level") or u""}


def lot_choices(items, kind, reference_category, not_water):
    """The usable inventory lots a source of `kind` may name. `items` are
    bench_inventory items; a reference sample is a reagent lot of the
    reference category; vendor water is any other reagent lot outside
    `not_water` (categories that are never purchased water)."""
    out = []
    for i in items or []:
        if i.get("kind") != u"reagent":
            continue
        cat = i.get("category") or u""
        if kind == REFERENCE_LOT and cat == reference_category:
            out.append(i)
        elif kind == WATER_LOT and cat != reference_category and cat not in not_water:
            out.append(i)
    return out


def source_problems(source, lot, receipt, coa, water_check, use_date):
    """Why the study's matrix cannot stand in for a chain of custody ([] =
    it can). `lot` = the bench_inventory item (or None), `receipt` its
    receipt record, `coa` its CoA metadata, `water_check` the reagent-water
    check of `use_date` (or None), `use_date` the day of the extraction."""
    kind = (source or {}).get("kind")
    out = []
    if kind == WATER_SYSTEM:
        if not use_date:
            return [u"the extraction date is not recorded (Extraction Log)"]
        if water_check is None:
            out.append(u"no reagent-water check is recorded for %s (Equipment > Reagent Water)" % use_date)
        elif not water_check.get("passed"):
            out.append(u"the reagent-water check of %s failed" % use_date)
        return out
    if kind not in (WATER_LOT, REFERENCE_LOT):
        return [u"the study's matrix source is not recorded"]
    if not lot:
        return [u"the lot is not in the inventory"]
    exp = lot.get("expiry") or u""
    if exp and use_date and exp < use_date:
        out.append(u"lot %s expired %s, before it was used on %s" % (lot.get("lot_number") or u"", exp, use_date))
    if kind == REFERENCE_LOT:
        if not receipt:
            out.append(u"the reference sample's receipt is not recorded")
        if not coa:
            out.append(u"the reference sample has no CoA on file")
    return out


def source_text(source):
    """The source in words: the water system, or the lot's name and number."""
    source = source or {}
    if source.get("kind") == WATER_SYSTEM:
        return u"the in-house water system"
    name = u" ".join(x for x in (source.get("name") or u"", source.get("lot_number") or u"") if x)
    return u"%s %s" % (u"lot", name) if name else u"an inventory lot"


def coc_item(run, problems):
    """(label, verdict, reason) of Data Review's chain-of-custody item for a
    study run: it is computed, never ticked."""
    source = (run or {}).get("source") or {}
    if source.get("kind") == REFERENCE_LOT:
        label = u"Reference sample receipt"
    else:
        label = u"Not applicable: study on reagent water from %s" % source_text(source)
    if problems:
        return label, u"fail", u"; ".join(problems)
    return label, u"pass", u""


def receipt_problems(form):
    if not (form.get("received_at") or u"").strip():
        return u"Give the date it was received."
    if not (form.get("received_by") or u"").strip():
        return u"Say who received it."
    if not (form.get("condition") or u"").strip():
        return u"Say what condition it arrived in."
    return u""


RECEIPT_FIELDS = ("received_by", "condition", "provider_ref", "storage", "note")


def new_receipt(form, previous, by, at):
    """(receipt, problem). The received date is the lot's own Received Date
    (the caller writes it there); the record keeps who received it, its
    condition, the provider's sample / certificate reference, where it was
    stored and a note. An earlier record is kept in its history."""
    problem = receipt_problems(form)
    if problem:
        return None, problem
    rec = dict((k, (form.get(k) or u"").strip()) for k in RECEIPT_FIELDS)
    rec.update(recorded_by=by, recorded_at=at)
    history = list((previous or {}).get("history") or [])
    if previous:
        history.append(dict((k, v) for k, v in previous.items() if k != "history"))
    rec["history"] = history
    return rec, u""


# ── annotation shell ─────────────────────────────────────────────────────────

def _load(obj, key):
    from zope.annotation.interfaces import IAnnotations
    try:
        raw = IAnnotations(obj).get(key)
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None


def load_run(ws):
    return _load(ws, STUDY_RUN_KEY)


def save_run(ws, record):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(ws)[STUDY_RUN_KEY] = json.dumps(record)


def load_receipt(obj):
    return _load(obj, RECEIPT_KEY)


def save_receipt(obj, receipt):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(obj)[RECEIPT_KEY] = json.dumps(receipt)
