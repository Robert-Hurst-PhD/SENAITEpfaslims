# -*- coding: utf-8 -*-
"""
PFAS Prepared Standards (@@pfas-prep-standards).

Manages in-house prepared reagents and standards.  Each lot is made by a
preparation record of its recipe (prep_entries.py), stores the parent
reagents consumed (parentage), analyte concentrations, and generates an
internal certificate (HTML) at creation/update.

Complex nested data (parent_reagents, analyte_concentrations) is stored
in IAnnotations on the PreparedStandard object to avoid schema migration
overhead for list-of-dict fields.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta

from zope.event import notify
from zope.lifecycleevent import ObjectModifiedEvent

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

from senaite.pfas import lab_time
from senaite.pfas.html_text import html_safe
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import signed_in_name
from senaite.pfas.browser.prep_common import PrepTypesMixin
from senaite.pfas.holding_time import date_to_iso as _date_str, parse_date as _parse_date

logger = logging.getLogger("senaite.pfas.browser.prepared_standards")

_ANN_PARENTS  = u"senaite.pfas.prepstd.parent_reagents"
_ANN_ANALYTES = u"senaite.pfas.prepstd.analyte_concentrations"
# The equipment a lot was MADE WITH. A prepared standard's assigned value rests on
# a mass and a volume, so under ISO 17025 §6.5 the balance and pipette that
# measured them are part of its traceability -- and the certificate could not name
# them. Stored as `[{"unit_id"..., "role"...}]`, referencing the
# Facility QC unit registry, so the calibration chain is RESOLVED at read time by
# facility_qc.equipment_provenance rather than copied onto the lot and left to rot.
_ANN_EQUIPMENT = u"senaite.pfas.prepstd.equipment"
# the preparation record (prep_entries.py) that made the lot
_ANN_ENTRY = u"senaite.pfas.prepstd.entry"
# the recipe and revision that made the lot ({"id", "revision"}; prep_sitting.py)
_ANN_RECIPE = u"senaite.pfas.prepstd.recipe"

CERT_DIR = os.environ.get("PFAS_CERT_DIR", "/data/coa/certs")
# The warning mark on a problem line, drawn (the printed record carries no
# icon sprite), in the colour of the line it sits on.
WARN_ICON = (u'<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="none" '
             u'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
             u'<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
             u'<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>')

STATUS_ACTIVE    = "active"
STATUS_EXHAUSTED = "exhausted"
STATUS_EXPIRED   = "expired"
STATUS_PENDING   = "pending"        # a new lot until accepted (lot_status)
STATUS_QUARANTINE = "quarantine"    # a rejected lot until a manager releases it
# the standard type a new lot defaults to, by its recipe's kind; the form's
# type select overrides it
KIND_TYPES = {"reagent": u"Solvent / Reagent", "standard": u"QC Check Standard",
              "series": u"Calibration Standard"}

STATUSES = [(STATUS_ACTIVE, "Active"), (STATUS_EXHAUSTED, "Exhausted"), (STATUS_EXPIRED, "Expired"),
            (STATUS_PENDING, "Pending acceptance"), (STATUS_QUARANTINE, "Quarantine")]

# Vocabulary is OWNED by the PreparedStandard content type — single source of
# truth (was duplicated here). Imported so this view stays in lock-step.
from senaite.pfas.document_templates import script_json
from senaite.pfas.browser.view_helpers import ViewHelpers


# ── Annotation helpers ─────────────────────────────────────────────────────────

def _get_ann(obj, key, default=None):
    try:
        ann = IAnnotations(obj)
        raw = ann.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return default if default is not None else []


def _set_ann(obj, key, value):
    # a write that fails refuses the save: a standard kept without its
    # parent lots would break the traceability chain
    IAnnotations(obj)[key] = json.dumps(value)


# ── Date helpers ────────────────────────────────────────────────────────────────





def _compute_expiry(prepared_date_str, expiry_days):
    """Return ISO expiry string = prepared_date + expiry_days."""
    d = _parse_date(prepared_date_str)
    if not d:
        d = lab_time.today()
    try:
        exp = d + timedelta(days=int(expiry_days or 365))
    except (TypeError, ValueError):
        exp = date(d.year + 1, d.month, d.day)
    return exp.strftime("%Y-%m-%d")


def _is_expired(expiry_str):
    from senaite.pfas.lot_expiry import expired_on
    return expired_on(expiry_str, lab_time.today())


# ── Content object helpers ─────────────────────────────────────────────────────

def _get_folder(portal):
    folder = portal.get("pfas_prepared_standards")
    if folder is None:
        raise RuntimeError(
            "pfas_prepared_standards folder not found. Reinstall senaite.pfas."
        )
    return folder


def _obj_to_dict(obj):
    d = {
        "uid":             obj.getId(),
        "title":           obj.title or u"",
        "lot_number":      obj.lot_number or u"",
        "standard_type":   obj.standard_type or u"",
        "logbook_slug":    obj.logbook_slug or u"",
        "logbook_revision":obj.logbook_revision or 0,
        "logbook_title":   obj.logbook_title or u"",
        "prepared_by":     obj.prepared_by or u"",
        "prepared_date":   _date_str(obj.prepared_date),
        "expiry_date":     _date_str(obj.expiry_date),
        "expiry_notes":    obj.expiry_notes or u"",
        "storage_location":obj.storage_location or u"",
        "storage_conditions": getattr(obj, "storage_conditions", None) or u"",
        "volume_prepared": obj.volume_prepared or u"",
        "status":          obj.status or STATUS_ACTIVE,
        "notes":           obj.notes or u"",
        "parent_reagents": _get_ann(obj, _ANN_PARENTS, []),
        "analyte_concentrations": _get_ann(obj, _ANN_ANALYTES, []),
        "equipment": _get_ann(obj, _ANN_EQUIPMENT, []),
        "entry_id": IAnnotations(obj).get(_ANN_ENTRY) or u"",
        "recipe": _get_ann(obj, _ANN_RECIPE, {}),
    }
    # the extensions QA approved or was asked for (lot_extension.py)
    from senaite.pfas import lot_extension
    d["extensions"] = lot_extension.entries(IAnnotations(obj).get(lot_extension.KEY))
    # Auto-update expired status (transient read-time only — not written to DB here)
    if d["status"] == STATUS_ACTIVE and _is_expired(lot_extension.in_force(d["expiry_date"], d["extensions"])):
        d["status"] = STATUS_EXPIRED
    return d


def _populate_obj(obj, data):
    obj.title = data.get("title") or u""
    obj.lot_number = data.get("lot_number") or u""
    obj.standard_type = data.get("standard_type") or u""
    obj.logbook_slug = data.get("logbook_slug") or u""
    try:
        obj.logbook_revision = int(data.get("logbook_revision") or 0)
    except (TypeError, ValueError):
        obj.logbook_revision = 0
    obj.logbook_title = data.get("logbook_title") or u""
    obj.prepared_by = data.get("prepared_by") or u""
    obj.prepared_date = _parse_date(data.get("prepared_date"))
    obj.expiry_date = _parse_date(data.get("expiry_date"))
    # Global-default assignment: an in-house prep with no stated expiry gets
    # prepared_date + the preset global period (Reagent Inventory → Expiry
    # Defaults). Parent-lot tightening is applied dynamically at read time.
    if obj.expiry_date is None and obj.prepared_date is not None:
        from senaite.pfas.parentage_checks import default_expiry
        defaults = data.get("_expiry_defaults") or {}
        days = int(defaults.get("prepared_std_default_days", 365))
        cap = data.get("_parent_cap") or {}
        iso, capped = default_expiry(obj.prepared_date.isoformat(), days, cap.get("date"))
        obj.expiry_date = _parse_date(iso)
        note = u"Expiry assigned from global default ({0} days from prep)".format(days)
        if capped:
            note = u"Expiry capped by parent %s" % (cap.get("inherited_from") or u"")
        prev = data.get("expiry_notes") or u""
        data["expiry_notes"] = (prev + u"\n" + note).strip() if prev else note
    obj.expiry_notes = data.get("expiry_notes") or u""
    obj.storage_location = data.get("storage_location") or u""
    obj.storage_conditions = data.get("storage_conditions") or u""
    obj.volume_prepared = data.get("volume_prepared") or u""
    obj.notes = data.get("notes") or u""
    # Only touch status when the caller actually supplied one. The edit form
    # posts no status field, so an unconditional assignment silently
    # RESURRECTED an exhausted lot to active on any edit — putting an emptied
    # standard back in the picker.
    if "status" in data:
        obj.status = data.get("status") or STATUS_ACTIVE
    elif not getattr(obj, "status", None):
        obj.status = STATUS_ACTIVE

    # Store nested data in annotations
    _set_ann(obj, _ANN_PARENTS, data.get("parent_reagents") or [])
    _set_ann(obj, _ANN_ANALYTES, data.get("analyte_concentrations") or [])
    # Only when the caller supplied it. The same trap as `status` above: an
    # unconditional assignment would wipe the equipment record on any edit by a
    # form that does not post the field.
    if "equipment" in data:
        _set_ann(obj, _ANN_EQUIPMENT, data.get("equipment") or [])
    # the prep entry that made the lot (prep_entries.py); set once, by make()
    if "entry_id" in data:
        IAnnotations(obj)[_ANN_ENTRY] = data.get("entry_id") or u""
    if data.get("recipe"):
        _set_ann(obj, _ANN_RECIPE, data["recipe"])


def _save(portal, data):
    folder = _get_folder(portal)
    uid = (data.get("uid") or u"").strip() or None
    if uid and uid in folder:
        obj = folder[uid]
    else:
        uid = uid or uuid.uuid4().hex
        title = data.get("title") or u"Prepared Standard"
        folder.invokeFactory("PreparedStandard", id=uid, title=title)
        obj = folder[uid]
        # a new lot is accepted before use (lot_status)
        from senaite.pfas.lot_status import initial_status
        data["status"] = initial_status(True)
    try:
        from senaite.pfas.browser.reagents import get_expiry_defaults
        data["_expiry_defaults"] = get_expiry_defaults(portal)
    except Exception:
        pass
    if not data.get("expiry_date") and data.get("parent_reagents"):
        # a default expiry never outlives a parent (effective, any depth)
        try:
            data["_parent_cap"] = effective_expiry_info(
                portal, {"expiry_date": u"", "lot_number": data.get("lot_number") or u"",
                         "parent_reagents": data.get("parent_reagents")})
        except Exception as exc:                            # noqa: BLE001
            logger.warning("parent expiry cap: %s", exc)
    _populate_obj(obj, data)
    try:
        obj.reindexObject()
    except Exception:
        pass
    try:
        notify(ObjectModifiedEvent(obj))
    except Exception:
        pass
    _write_cert(obj)
    return uid


def lot_dict(portal, uid):
    """One lot as the list shows it (with its effective expiry and what set
    it), or None when it is not in the inventory."""
    d = _get(portal, uid)
    if d is None:
        return None
    eff = effective_expiry_info(portal, d)
    d["effective_expiry"] = eff["date"]
    d["expiry_inherited_from"] = eff["inherited_from"]
    return d


def _get(portal, uid):
    try:
        folder = _get_folder(portal)
    except RuntimeError:
        return None
    obj = folder.get(uid)
    return _obj_to_dict(obj) if obj else None


def effective_expiry_info(portal, d, _seen=None, _depth=0, as_of=None):
    """Inherited expiry: min(own expiry, every parent lot's effective expiry),
    purchased and prepared parents alike, at any depth. If a parent is
    tighter (earlier), the prep inherits it. Cycle-safe and depth-bounded as
    build_parentage is. Returns {"date": iso, "inherited_from": parent}.
    Each lot's own date is the one in force on `as_of` (a laboratory day;
    None is now): its latest extension QA approved by then
    (lot_extension.in_force), still capped by its parents."""
    from senaite.pfas import lot_extension
    own = lot_extension.in_force(d.get("expiry_date") or u"", d.get("extensions"), as_of)
    eff, src = own, ""
    seen = set(_seen or ())
    own_lot = (d.get("lot_number") or u"").strip()
    if own_lot:
        seen.add(own_lot)
    if _depth >= MAX_PARENTAGE_DEPTH:
        return {"date": eff, "inherited_from": src}
    for p in d.get("parent_reagents") or []:
        try:
            pexp = _effective_expiry_of(portal, p, seen, _depth, as_of)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("parent expiry of %s: %s", p.get("lot"), exc)
            continue
        if pexp and (not eff or pexp < eff):
            eff, src = pexp, (p.get("name") or p.get("lot") or u"parent")
    return {"date": eff, "inherited_from": src}


def parents_in_force(portal, parents, as_of=None):
    """A record's parents, each with its expiry in force ("expiry") on
    `as_of` (None: now): the walk over a lot whose only parent is that one,
    a prepared parent's inherited date included. A parent that cannot be
    resolved has none. A parent whose own extension is in force then also
    carries its printed note ("extension", lot_extension.note); a lot whose
    category has no expiry, "no_expiry"."""
    out = []
    for p in parents or []:
        q = dict(p, expiry=effective_expiry_info(portal, {"parent_reagents": [p]}, as_of=as_of)["date"] or u"")
        q.update(_parent_extras(portal, p, as_of))
        out.append(q)
    return out


def _parent_extras(portal, parent, as_of=None):
    """What a record prints beside a parent's expiry: {"extension": the
    note of the extension in force on `as_of`} and {"no_expiry": True} for
    a lot whose category has none; {} when neither or not found."""
    from senaite.pfas import lot_extension
    try:
        obj, kind = _resolve_lot(portal, parent)
    except Exception:                                       # noqa: BLE001
        return {}
    if obj is None:
        return {}
    out = {}
    if kind == KIND_MANUFACTURER:
        from senaite.pfas.browser.reagents import no_expiry_categories
        if (getattr(obj, "category", u"") or u"") in no_expiry_categories():
            return {"no_expiry": True}
    items = lot_extension.entries(IAnnotations(obj).get(lot_extension.KEY))
    note = lot_extension.note(lot_extension.in_force_entry(items, as_of))
    if note:
        out["extension"] = note
    return out


def lot_in_force(portal, uid, as_of=None):
    """The expiry in force on `as_of` of one inventory lot (its object id,
    reagent or prepared standard): the reading every gate shares."""
    return effective_expiry_info(portal, {"parent_reagents": [{"uid": uid}]}, as_of=as_of)["date"] or u""


def _effective_expiry_of(portal, parent, seen, depth, as_of=None):
    """One parent's effective expiry on `as_of`: a purchased lot's (its
    global-default rules), a prepared lot's own capped by ITS parents."""
    from senaite.pfas import lot_extension
    obj, kind = _resolve_lot(portal, parent)
    if obj is None:
        return u""
    if kind == KIND_MANUFACTURER:
        from senaite.pfas.browser.reagents import (
            _obj_to_dict as _rdict, _effective_expiry, get_expiry_defaults)
        return _effective_expiry(_rdict(obj), get_expiry_defaults(portal), as_of=as_of)
    child = _obj_to_dict(obj)
    if (child.get("lot_number") or u"").strip() in seen:
        return lot_extension.in_force(str(child.get("expiry_date") or "")[:10], child.get("extensions"), as_of)
    return effective_expiry_info(portal, child, seen, depth + 1, as_of=as_of)["date"]


# ── Parentage hierarchy ──────────────────────────────────────────────────────
# THE canonical walk from a prepared standard up to what it was ultimately made
# from. Both the Certificate of Preparation and the Data Review traceability gate
# call it, so the document and the gate cannot disagree -- they did before, and
# recorded three separate resolvers giving three different answers
# about whether one parent existed.
#
# A lot may be made from another LOT, not only from a manufactured reagent: a
# working standard from a secondary stock from a primary stock from the CRM. So
# the walk recurses, and every branch must terminate in one of exactly three
# ways:
#
#   MANUFACTURER   a Reagent with a supplier -- the ISO 17025 §6.6 leaf
#   WATER          in-house Type 1 water, whose provenance is the water QC log
#                  for the day it was used, not a supplier
#   PROBLEM        anything else: unresolvable, or water with no log entry
#
# There is no fourth ending. A branch that stops anywhere else is a traceability
# failure by construction rather than by a check someone remembered to write --
# which is how level 1 went unenforced for so long.

KIND_MANUFACTURER = u"manufacturer"
KIND_WATER = u"water"
KIND_PREPARED = u"prepared"
KIND_UNRESOLVED = u"unresolved"

MAX_PARENTAGE_DEPTH = 12


def _resolve_lot(portal, parent):
    """(object, kind) for a parent record -- a Reagent or another
    PreparedStandard. UID first, lot string second."""
    uid = (parent.get("uid") or u"").strip()
    lot = (parent.get("lot") or u"").strip()
    for folder_id, kind in (("pfas_reagents", KIND_MANUFACTURER),
                            ("pfas_prepared_standards", KIND_PREPARED)):
        folder = portal.get(folder_id)
        if folder is None:
            continue
        if uid:
            obj = folder.get(uid)
            if obj is not None:
                return obj, kind
    # fall back to the lot number, which is all a pre-uid record carries
    if not lot:
        return None, KIND_UNRESOLVED
    for folder_id, kind in (("pfas_reagents", KIND_MANUFACTURER),
                            ("pfas_prepared_standards", KIND_PREPARED)):
        folder = portal.get(folder_id)
        if folder is None:
            continue
        for obj in folder.objectValues():
            if (getattr(obj, "lot_number", "") or "").strip() == lot:
                return obj, kind
    return None, KIND_UNRESOLVED


def resolve_loaded(portal, snap):
    """(object, kind) of a lot a run was loaded with, from the snapshot the
    run kept of it (uid, lot): the one lookup the traceability walk and the
    batch record's print share."""
    return _resolve_lot(portal, {"uid": snap.get("uid"), "lot": snap.get("lot")})


def _lx_note(items):
    from senaite.pfas import lot_extension
    return lot_extension.note(lot_extension.in_force_entry(items))


def _lx_printed(recorded, items, no_expiry=False):
    from senaite.pfas import lot_expiry, lot_extension
    if no_expiry:
        return lot_expiry.NO_EXPIRY
    return lot_extension.printed(recorded, items)


def _in_force_node(node, own, rec):
    """A parentage node's expiry: the date in force now ("expiry"); the
    lot's own date ("expiry_base") and its extensions, from which the
    review judges each use on its own day (parentage_checks.in_force). A
    lot whose category has no expiry has none."""
    from senaite.pfas import lot_extension
    if rec.get("no_expiry"):
        own = u""
    node["expiry_base"], node["extensions"] = own, rec.get("extensions") or []
    node["expiry"] = lot_extension.in_force(own, node["extensions"])


def build_parentage(portal, rec, used_on=None, _seen=None, _depth=0):
    """The full parentage hierarchy of a prepared standard, as a node list.

    `rec` is a prepared-standard dict (`_obj_to_dict`). `used_on` is the ISO date
    the material was USED, which is what the water log is checked against -- it
    defaults to the standard's own prepared_date, and is passed down so a
    working standard made today from water drawn today asks about today.

    Each node:
        kind      manufacturer | water | prepared | unresolved
        name supplier cat_number lot url expiry has_coa qty unit
        water_log  the Type 1 QC entry for `used_on`, or None
        problems   [] when this branch is sound
        children   the node's own parentage (prepared lots only)

    Cycle-safe: a lot cannot be its own ancestor, and depth is bounded. Without
    that, a mis-keyed parent pointing at itself would recurse until the request
    died -- a data-entry error should not be able to take a page down.
    """
    from senaite.pfas.content.reagent import CATEGORY_INHOUSE_WATER
    from senaite.pfas.lot_expiry import REASON_KEY

    _seen = set(_seen or ())
    own_lot = (rec.get("lot_number") or u"").strip()
    if own_lot:
        _seen.add(own_lot)
    used_on = used_on or (str(rec.get("prepared_date") or "")[:10])

    nodes = []
    parents = rec.get("parent_reagents") or []
    if not parents:
        return [{
            "kind": KIND_UNRESOLVED, "name": u"", "lot": u"",
            "supplier": u"", "cat_number": u"", "url": u"", "expiry": u"",
            "has_coa": False, "qty": u"", "unit": u"", "water_log": None,
            "children": [],
            "problems": [u"no parent lots recorded — this lot cannot be traced "
                         u"to anything"],
        }]

    if _depth >= MAX_PARENTAGE_DEPTH:
        return [{
            "kind": KIND_UNRESOLVED, "name": u"", "lot": own_lot,
            "supplier": u"", "cat_number": u"", "url": u"", "expiry": u"",
            "has_coa": False, "qty": u"", "unit": u"", "water_log": None,
            "children": [],
            "problems": [u"parentage deeper than %d levels — not followed "
                         u"further" % MAX_PARENTAGE_DEPTH],
        }]

    for p in parents:
        obj, kind = _resolve_lot(portal, p)
        lot = (p.get("lot") or u"").strip()
        node = {
            "kind":       kind,
            "name":       p.get("name") or u"",
            "lot":        lot,
            # what the parentage review shows for each lot
            "prepared_date": u"", "prepared_by": u"", "entry_id": u"",
            "entry_reviewed": None, "status": u"", "storage_conditions": u"",
            "supplier":   u"",
            "cat_number": u"",
            "url":        u"",
            "expiry":     u"",
            "has_coa":    False,
            "qty":        p.get("qty") or u"",
            "unit":       p.get("unit") or u"",
            "water_log":  None,
            "children":   [],
            "problems":   [],
            # why the preparation used this parent out of date, when it did
            "expired_reason": p.get(REASON_KEY) or u"",
        }

        if obj is None:
            node["problems"].append(
                u"lot %s is not in inventory" % (lot or u"(blank)"))
            nodes.append(node)
            continue

        node["name"] = obj.Title() or node["name"]
        node["url"] = obj.absolute_url()
        node["uid"] = obj.getId()

        if kind == KIND_MANUFACTURER:
            from senaite.pfas.browser.reagents import (
                _COA_ANN_KEY, _ANN_ARCHIVED_KEY, _obj_to_dict as _rdict,
                _base_expiry, get_expiry_defaults)
            rd = _rdict(obj)
            node["status"] = rd.get("status") or u""
            node["storage_conditions"] = rd.get("storage_conditions") or u""
            node["supplier"] = rd.get("supplier") or u""
            node["cat_number"] = rd.get("cat_number") or u""
            _in_force_node(node, _base_expiry(rd, get_expiry_defaults(portal)), rd)
            node["no_expiry"] = bool(rd.get("no_expiry"))
            node["no_coa"] = bool(rd.get("no_coa"))
            # Presence is not sufficiency. A SPECIMEN certificate establishes no
            # traceability, and a claim resting on one would be exactly the false
            # assurance this subsystem exists to prevent — so the specimen flag
            # travels with the node and the §6.5 statement refuses to count it.
            node["has_coa"] = False
            node["coa_specimen"] = False
            try:
                raw = IAnnotations(obj).get(_COA_ANN_KEY)
                if raw:
                    meta = json.loads(raw) if isinstance(raw, str) else raw
                    node["has_coa"] = True
                    marker = u"{0} {1}".format(meta.get("filename") or u"",
                                               meta.get("uploaded_by") or u"")
                    node["coa_specimen"] = u"SPECIMEN" in marker.upper()
            except Exception:
                pass
            if IAnnotations(obj).get(_ANN_ARCHIVED_KEY):
                node["problems"].append(u"lot is archived")
            from senaite.pfas import certificate_values as cv
            node["has_certificate_values"] = bool(IAnnotations(obj).get(cv.KEY))

            if (rd.get("category") or u"") == CATEGORY_INHOUSE_WATER:
                # THE exception. In-house water has no manufacturer; the Type 1
                # water QC log for the day of use is its provenance, and the
                # lab's rule is that an entry must always exist for that day.
                node["kind"] = KIND_WATER
                node["supplier"] = u"In-house Type 1 water system"
                try:
                    from senaite.pfas import facility_qc
                    node["water_log"] = facility_qc.get_water_qc_for_date(used_on)
                except Exception as exc:                    # noqa: BLE001
                    logger.error("water QC lookup for %s: %s", used_on, exc)
                    node["water_log"] = None
                if not node["water_log"]:
                    node["problems"].append(
                        u"in-house Type 1 water was used on %s and there is no "
                        u"water QC entry for that date" % (used_on or u"?"))
                elif not node["water_log"].get("passed"):
                    node["problems"].append(
                        u"the Type 1 water QC entry for %s FAILED" % used_on)
            elif not node["supplier"]:
                node["problems"].append(
                    u"no supplier recorded — the lot cannot be traced to a "
                    u"manufacturer")

        elif kind == KIND_PREPARED:
            child_rec = _obj_to_dict(obj)
            child_lot = (child_rec.get("lot_number") or u"").strip()
            _in_force_node(node, str(child_rec.get("expiry_date") or "")[:10], child_rec)
            node["prepared_date"] = str(child_rec.get("prepared_date") or "")[:10]
            node["prepared_by"] = child_rec.get("prepared_by") or u""
            node["entry_id"] = child_rec.get("entry_id") or u""
            node["recipe"] = child_rec.get("recipe") or {}
            node["status"] = child_rec.get("status") or u""
            node["storage_conditions"] = child_rec.get("storage_conditions") or u""
            if child_lot and child_lot in _seen:
                node["problems"].append(
                    u"circular parentage: %s is already in this chain"
                    % child_lot)
            else:
                # the equipment a parent lot was made with, as of ITS
                # preparation: an established problem travels up the chain
                # like a missing parent does (the top lot's own equipment is
                # equipment_gate_problems)
                for prob in equipment_problems(build_equipment(portal, child_rec)):
                    node["problems"].append(u"made with %s%s: %s" % (
                        prob["unit"], u" (%s)" % prob["role"] if prob["role"] else u"",
                        prob["reason"]))
                # The child's own preparation date governs ITS water check.
                node["children"] = build_parentage(
                    portal, child_rec,
                    used_on=str(child_rec.get("prepared_date") or "")[:10]
                            or used_on,
                    _seen=_seen | {child_lot} if child_lot else _seen,
                    _depth=_depth + 1)

        nodes.append(node)
    return nodes


def parentage_problems(nodes):
    """Every problem anywhere in the hierarchy, flattened, deepest included.

    The gate needs one list; the certificate needs the tree. Same walk, so a
    branch the certificate prints as broken is exactly the one that blocks
    release.
    """
    out = []
    for n in nodes or []:
        for prob in n.get("problems") or []:
            out.append({
                "lot": n.get("lot") or u"(blank)",
                "name": n.get("name") or u"",
                "kind": n.get("kind"),
                "reason": prob,
            })
        out.extend(parentage_problems(n.get("children")))
    return out


def _list(portal, q="", status_filter="", type_filter=""):
    try:
        folder = _get_folder(portal)
    except RuntimeError:
        return []
    q_lower = (q or "").lower().strip()
    results = []
    for obj in folder.objectValues():
        if obj.portal_type != "PreparedStandard":
            continue
        d = _obj_to_dict(obj)
        eff = effective_expiry_info(portal, d)
        d["effective_expiry"] = eff["date"]
        d["expiry_inherited_from"] = eff["inherited_from"]
        # a tighter parent expiry can also expire the prep
        if d["status"] == STATUS_ACTIVE and _is_expired(eff["date"]):
            d["status"] = STATUS_EXPIRED
        from senaite.pfas.lot_status import matches_filter
        if not matches_filter(d["status"], status_filter):
            continue
        if type_filter and d["standard_type"] not in (
                type_filter if isinstance(type_filter, (list, tuple)) else (type_filter,)):
            continue
        if q_lower:
            searchable = u" ".join([
                d.get("title", ""),
                d.get("lot_number", ""),
                d.get("logbook_title", ""),
                d.get("prepared_by", ""),
            ]).lower()
            if q_lower not in searchable:
                continue
        results.append(d)
    results.sort(key=lambda x: x.get("prepared_date", "") or "", reverse=True)
    return results


# ── Internal certificate ────────────────────────────────────────────────────────

def _write_cert(obj):
    """Generate and store the internal certificate HTML for a prepared standard."""
    try:
        d = _obj_to_dict(obj)
        from senaite.pfas.print_settings import get_signoff_signers
        from bika.lims import api as _api
        _portal = _api.get_portal()
        # The portal is passed so the certificate RESOLVES the chain instead of
        # reprinting the stored copy of it. Before this it printed the parent
        # record verbatim, so a lot that was not in inventory appeared as
        # established fact with the QA attestation attached.
        html = _render_cert_html(d, get_signoff_signers(_portal), portal=_portal)
        path = os.path.join(CERT_DIR, "{}.html".format(obj.getId()))
        if not os.path.isdir(CERT_DIR):
            os.makedirs(CERT_DIR)
        with open(path, "w") as fh:
            fh.write(html.encode("utf-8") if isinstance(html, unicode) else html)
    except Exception as exc:
        logger.error("_write_cert %s: %s", obj.getId(), exc)


def _render_parentage_html(nodes, depth=0):
    """The parentage hierarchy as nested rows, with links and provenance.

    Each row states how its branch ENDS, because that is the question a reader
    and an assessor actually have: a manufacturer with a catalogue number and a
    CoA, the Type 1 water log for the day of use, or a problem. Indentation
    carries the depth; a lot made from a lot made from a CRM reads as such.
    """
    out = u""
    for n in nodes or []:
        pad = 18 * depth
        kind = n.get("kind")
        if kind == KIND_MANUFACTURER:
            badge = u'<span class="pk pk-mfr">MANUFACTURER</span>'
            prov = n.get("supplier") or u"—"
            if n.get("cat_number"):
                prov += u" &middot; cat. {0}".format(n["cat_number"])
            if n.get("coa_specimen"):
                prov += (u' &middot; <span class="pk-warn">SPECIMEN CoA only'
                         u' &mdash; establishes nothing</span>')
            elif n.get("has_coa"):
                prov += u' &middot; <strong>CoA on file</strong>'
            elif not n.get("no_coa"):
                # a lot whose category needs no CoA carries no warning
                prov += u' &middot; <span class="pk-warn">no CoA on file</span>'
        elif kind == KIND_WATER:
            badge = u'<span class="pk pk-water">TYPE 1 WATER</span>'
            wl = n.get("water_log") or {}
            if wl:
                prov = (u"in-house system &middot; QC {0} {1} &middot; "
                        u"conductivity {2} &micro;S/cm &middot; TOC {3} ppb "
                        u"&middot; {4}").format(
                    wl.get("log_date", u""), wl.get("log_time", u""),
                    wl.get("conductivity", u"—"), wl.get("toc", u"—"),
                    u"PASS" if wl.get("passed") else u"FAIL")
            else:
                prov = u'<span class="pk-warn">in-house system &mdash; no water QC entry</span>'
        elif kind == KIND_PREPARED:
            badge = u'<span class="pk pk-prep">PREPARED IN HOUSE</span>'
            prov = u"made from the lot(s) below"
        else:
            badge = u'<span class="pk pk-bad">UNRESOLVED</span>'
            prov = u'<span class="pk-warn">not traceable</span>'

        name = n.get("name") or u"(unnamed)"
        # the row opens its lot: no button stands inside a row (the url
        # arrives escaped, as every value here does)
        opens = (u' data-row-open="{0}"'.format(n["url"])
                 if n.get("url") else u"")
        amount = u"{0} {1}".format(n.get("qty") or u"", n.get("unit") or u"").strip()
        out += (
            u'<tr{opens}><td style="padding-left:{pad}px">{badge} {name}</td>'
            u'<td>{lot}</td><td>{prov}</td><td>{amount}</td>'
            u'<td>{expiry}</td></tr>').format(
                opens=opens, pad=pad, badge=badge, name=name, lot=n.get("lot") or u"—",
                prov=prov, amount=amount or u"—",
                expiry=_lx_printed(n.get("expiry"), n.get("extensions"), n.get("no_expiry")) or u"—")
        for prob in n.get("problems") or []:
            out += (u'<tr><td colspan="5" style="padding-left:{0}px" '
                    u'class="pk-problem">{2} {1}</td></tr>').format(
                        pad + 18, prob, WARN_ICON)
        out += _render_parentage_html(n.get("children"), depth + 1)
    return out


def build_equipment(portal, rec):
    """The calibration chain of everything this lot was MADE WITH, as of the day
    it was made.

    Returns [{unit_id, role, name, serial, kind, records, problems, warnings}].

    `as_of` is the PREPARED date, not today: a standard weighed on a balance that
    was in calibration that morning stays defensible after the calibration lapses.
    Judging against today would condemn correct historical work -- the same reason
    `used_on` exists in build_parentage.

    One function does the calibration walk (facility_qc.equipment_provenance), so
    the chain a prep certificate prints is the chain the release gate walks for an
    extraction. A second implementation here would be a second answer.
    """
    out = []
    as_of = str(rec.get("prepared_date") or u"")[:10]
    from senaite.pfas import facility_qc as fq
    for item in rec.get("equipment") or []:
        unit_id = (item.get("unit_id") or u"").strip()
        role = item.get("role") or u""
        if not unit_id:
            continue
        try:
            prov = fq.equipment_provenance(unit_id, as_of)
        except Exception as exc:                                # noqa: BLE001
            logger.error("equipment chain for %s: %s", unit_id, exc)
            continue
        unit = prov.get("unit") or {}
        out.append({
            "unit_id":  unit_id,
            "role":     role,
            "name":     unit.get("name") or unit_id,
            "serial":   unit.get("serial_number") or u"",
            "kind":     prov.get("kind") or u"",
            "records":  prov.get("records") or [],
            "problems": prov.get("problems") or [],
            "warnings": prov.get("warnings") or [],
        })
    return out


def equipment_problems(nodes):
    """Flattened, the way parentage_problems flattens the lot hierarchy."""
    out = []
    for n in nodes or []:
        for prob in n.get("problems") or []:
            out.append({"unit": n.get("name") or u"", "role": n.get("role") or u"",
                        "reason": prob})
    return out


def equipment_gate_problems(portal, rec):
    """The established equipment problems of a lot -- a balance with no passed
    verification on the prepared date, a pipette out of calibration -- as
    release blockers: [{"lot", "name", "reason"}]. Warnings (no equipment
    recorded, an unregistered serial) are not here: they do not block (lab,
    2026-10-09, option A). One function for the release gate and the bench
    lot picker, so both give the same answer."""
    return [{"lot": rec.get("lot_number") or u"", "name": p["unit"],
             "reason": u"%s%s: %s" % (p["unit"], u" (%s)" % p["role"] if p["role"] else u"",
                                     p["reason"])}
            for p in equipment_problems(build_equipment(portal, rec))]


def _render_equipment_html(nodes):
    """Equipment rows for the certificate: what was used, and what its measurement
    is traceable TO. A row that ends nowhere says so on the document."""
    if not nodes:
        return (u'<tr><td colspan="4">No equipment recorded against this lot '
                u'&mdash; the balance and pipettes used, and their calibration '
                u'status, cannot be shown. Record them on the prepared-standard '
                u'form.</td></tr>')
    from senaite.pfas import facility_qc
    rows = u""
    for n in nodes:
        traced = []
        for r in n.get("records") or []:
            d = r.get("data") or {}
            if r.get("type") == "weight_set" and not facility_qc.calibration_required(d):
                traced.append(u"weight set {0} &mdash; not calibrated".format(d.get("set_id") or u"?"))
            elif r.get("type") == "weight_set":
                traced.append(u"weight set {0} &mdash; {1}, cert {2}".format(
                    d.get("set_id") or u"?", d.get("cal_lab") or u"?",
                    d.get("cal_cert_number") or u"?"))
            elif r.get("type") == "balance_verification":
                traced.append(u"checked {0}".format(d.get("verified_date") or u"?"))
            elif r.get("type") == "pipette_calibration":
                # For an EXTERNAL check the provider and its certificate are the
                # traceability endpoint -- the same role the metrology laboratory
                # plays for a weight set -- so they have to be named, not just
                # dated. The first version printed only the dates, which said the
                # pipette was calibrated without saying by whom.
                who = u""
                if (d.get("kind") or u"") == u"external":
                    who = u" by {0}{1}".format(
                        d.get("provider") or u"an unnamed provider",
                        u" (cert {0})".format(d["cert_number"])
                        if d.get("cert_number") else u"")
                traced.append(u"calibration {0}{1}, due {2}".format(
                    d.get("cal_date") or u"?", who, d.get("due_date") or u"?"))
            elif r.get("type") == "no_calibration_required":
                traced.append(u"makes no measurement &mdash; no calibration "
                              u"standard to trace to")
        cell = u"; ".join(traced) or u"&mdash;"
        if n.get("problems"):
            cell += (u'<br><span style="color:#8a1c1c">' + WARN_ICON + u' '
                     + u"; ".join(n["problems"]) + u"</span>")
        rows += u"<tr><td>{0}</td><td>{1}</td><td>{2}</td><td>{3}</td></tr>".format(
            n.get("role") or u"&mdash;", n.get("name") or u"&mdash;",
            n.get("serial") or u"&mdash;", cell)
    return rows


def _named_concentrations(rows):
    """The concentration rows with each analyte by the compound library's
    display name (compound_library.canonical_name); a name the library does
    not know prints as stored. An unreadable library leaves them as stored."""
    rows = list(rows or [])
    try:
        from senaite.pfas import compound_library, compound_library_store
        library = compound_library_store.library()
    except Exception:                                       # noqa: BLE001
        logger.warning("compound library unreadable: analytes print as stored", exc_info=True)
        return rows
    return [dict(r, analyte=compound_library.canonical_name(library, r.get("analyte")))
            if isinstance(r, dict) and r.get("analyte") else r for r in rows]


def _render_cert_html(d, signers=None, portal=None):
    """Return the internal certificate HTML string for a prepared-standard dict.

    `signers` (optional) = {"qao": staff-dict-or-None, "director"...} from
    print settings; drives the 3-tier QA attestation. Names only (this cert is
    written to a standalone file, so signature-image URLs are not embedded)."""
    # an analyte by its display name, as the certificate and the QC Review
    # print it
    d = dict(d, analyte_concentrations=_named_concentrations(d.get("analyte_concentrations")))
    # the page is built as a string: every value is escaped first
    d = html_safe(d)
    signers = html_safe(signers or {})
    _qao = signers.get("qao") or {}
    _dir = signers.get("director") or {}
    qao_name = _qao.get("fullname") or u"—"
    director_name = _dir.get("fullname") or u"—"
    rows_html = u""
    for row in d.get("analyte_concentrations") or []:
        rows_html += (
            u"<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                row.get("analyte", ""), row.get("concentration", ""),
                row.get("unit", "")
            )
        )
    # The parentage HIERARCHY, resolved, not the stored copy reprinted. A lot may
    # be made from another lot made from a CRM, and every branch has to end at a
    # manufacturer or at the Type 1 water log -- so the certificate walks it and
    # says where each branch ends.
    parentage = []
    if portal is not None:
        try:
            parentage = html_safe(build_parentage(portal, d))
        except Exception as exc:                            # noqa: BLE001
            logger.error("certificate parentage for %s: %s",
                         d.get("lot_number"), exc)
            parentage = []
    parents_html = _render_parentage_html(parentage)
    problems = parentage_problems(parentage)

    # ISO 17025 §7.8.2.1(a): the name and address of the laboratory. Read from
    # the SENAITE Laboratory object rather than hardcoded, and when it is
    # unconfigured the certificate SAYS SO instead of printing the stock
    # placeholder as though it were the lab's name.
    lab_name, lab_address = u"", u""
    if portal is not None:
        from senaite.pfas import lab_identity
        nm = lab_identity.lab_name(portal)
        if nm and nm != u"Laboratory Information":
            lab_name = html_safe(nm)
        lab_address = html_safe(lab_identity.lab_address(portal))
    lab_header = lab_name or (
        u'<span style="color:#8a1c1c">Laboratory name and address not '
        u'configured (ISO 17025 §7.8.2.1(a))</span>')
    if lab_address:
        lab_header += u" &mdash; " + lab_address

    # §7.8.2.1(b) unique identification, and GMP document control: a reissued
    # certificate must be distinguishable from the one it replaced.
    cert_version = d.get("cert_version") or 1
    cert_id = u"COP-{0}-r{1}".format(d.get("lot_number") or u"UNKNOWN",
                                     cert_version)

    # §6.5 metrological traceability. The assigned concentration of a prepared
    # standard is only as traceable as the chain it descends from, so the claim
    # is DERIVED from the parentage walk rather than asserted: if any
    # manufacturer node in the chain has no CoA on file, traceability to a
    # reference value is not established and the certificate must not imply it.
    def _mfr_nodes(nodes):
        out = []
        for n in nodes or []:
            if n.get("kind") == KIND_MANUFACTURER:
                out.append(n)
            out.extend(_mfr_nodes(n.get("children")))
        return out

    mfr = _mfr_nodes(parentage)
    # A specimen counts as NO certificate for traceability purposes.
    without_coa = [n for n in mfr
                   if not n.get("has_coa") or n.get("coa_specimen")]
    specimens = [n for n in mfr if n.get("coa_specimen")]
    if not mfr:
        trace_stmt = (u'<span style="color:#8a1c1c">No manufactured reference '
                      u'material appears in this lot\'s parentage, so no '
                      u'metrological traceability can be stated.</span>')
    elif without_coa:
        _spec = ((u" {0} of them {1} only a SPECIMEN certificate, which is "
                  u"illustrative and establishes nothing.").format(
                      len(specimens),
                      u"carries" if len(specimens) == 1 else u"carry")
                 if specimens else u"")
        trace_stmt = (
            u'<span style="color:#8a1c1c">NOT ESTABLISHED.</span> The assigned '
            u'values are gravimetrically derived from the parentage above, but '
            u'{0} of {1} source lot(s) have no USABLE certificate of analysis '
            u'on file '
            u'({2}). Without the supplier\'s certificate the reference value '
            u'these were prepared against is not confirmed, so traceability to a '
            u'stated reference cannot be claimed (ISO 17025 §6.5).').format(
                len(without_coa), len(mfr),
                u", ".join(n.get("lot") or u"?" for n in without_coa)) + _spec
    else:
        trace_stmt = (
            u'Assigned values are gravimetrically derived from the source lots '
            u'above, each of which has a supplier certificate of analysis on '
            u'file. Traceability rests on those certificates; this laboratory '
            u'asserts no independent value assignment and states no '
            u'measurement uncertainty of its own for this lot '
            u'(ISO 17025 §6.5).')

    # The equipment this lot was MADE WITH, resolved as of the PREPARED date.
    # Until now the certificate printed a sentence saying equipment "is not
    # recorded against this lot" and pointed at the logbook -- true, and a gap
    # : a certificate that cannot name the balance behind its own mass
    # cannot substantiate the assigned value it carries.
    equipment = []
    if portal is not None:
        try:
            equipment = html_safe(build_equipment(portal, d))
        except Exception as exc:                            # noqa: BLE001
            logger.error("certificate equipment for %s: %s",
                         d.get("lot_number"), exc)
            equipment = []
    equip_rows = _render_equipment_html(equipment)
    equip_problems = equipment_problems(equipment)
    if equip_problems:
        equip_rows += (
            u'<tr><td colspan="4" class="pk-banner">'
            u'{1} {0} of the equipment record(s) above do not trace to a '
            u'calibrated standard for the day this lot was prepared.'
            u'</td></tr>').format(len(equip_problems), WARN_ICON)

    # GMP: the preparation must be reproducible from the record. Volumes taken
    # come from the parentage rows; the final volume is the lot's own.
    calc_rows = u""
    for n in parentage:
        amt = u"{0} {1}".format(n.get("qty") or u"", n.get("unit") or u"").strip()
        calc_rows += (u"<tr><td>{0}</td><td>{1}</td><td>{2}</td></tr>".format(
            n.get("name") or u"—", n.get("lot") or u"—", amt or u"(not recorded)"))
    if not calc_rows:
        calc_rows = u"<tr><td colspan='3'>No component amounts recorded</td></tr>"
    if problems:
        # Stated ON the document. It previously printed an unresolvable parent as
        # established fact with the 3-tier QA attestation attached;
        # a certificate that cannot substantiate its own parentage has to say so.
        parents_html += (
            u'<tr><td colspan="5" class="pk-banner">'
            u'{1} THIS PARENTAGE IS NOT FULLY SUBSTANTIATED &mdash; '
            u'{0} unresolved link(s). The data-review traceability gate will '
            u'reject a worksheet that uses this lot until they are resolved.'
            u'</td></tr>').format(len(problems), WARN_ICON)
    elif not parentage:
        parents_html = (u'<tr><td colspan="5" class="pk-banner">' + WARN_ICON + u' '
                        u'No parent lots recorded &mdash; this lot cannot be '
                        u'traced to anything.</td></tr>')
    return u"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Internal Certificate — {title}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 12px; margin: 30px 40px; color: #222; }}
  h1 {{ font-size: 18px; margin-bottom: 4px; }}
  .pk {{ display:inline-block; font-size:9px; font-weight:bold; padding:1px 5px;
         border-radius:3px; margin-right:6px; vertical-align:middle; }}
  .pk-mfr {{ background:#d5e8d4; color:#1e5b2a; }}
  .pk-water {{ background:#d6e6f5; color:#14496e; }}
  .pk-prep {{ background:#efe3c8; color:#6b4c11; }}
  .pk-bad {{ background:#f5d5d5; color:#8a1c1c; }}
  .pk-warn {{ color:#8a1c1c; font-weight:bold; }}
  .pk-problem {{ color:#8a1c1c; font-size:11px; }}
  .pk-banner {{ background:#f8e6e6; color:#8a1c1c; font-weight:bold;
                padding:6px 8px; }}
  .cert-meta {{ background: #f4f6f8; padding: 12px 16px; border-radius: 6px;
               margin-bottom: 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 24px; }}
  .cert-meta dt {{ font-weight: 700; font-size: 11px; text-transform: uppercase; color: #555; }}
  .cert-meta dd {{ margin: 0 0 6px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  th {{ background: #e8edf2; padding: 6px 10px; text-align: left; font-size: 11px;
        text-transform: uppercase; letter-spacing: .04em; }}
  td {{ padding: 5px 10px; border-bottom: 1px solid #ddd; }}
  .footer {{ margin-top: 40px; padding-top: 10px; border-top: 1px solid #ccc;
             font-size: 11px; color: #888; }}
  .sig-block {{ margin-top: 30px; display: flex; gap: 60px; }}
  .sig-block div {{ border-top: 1px solid #333; padding-top: 4px; min-width: 160px; font-size: 11px; }}
  .signoff {{ margin-top: 28px; border: 1px solid #000; border-radius: 6px; padding: 12px 14px; }}
  .signoff-title {{ font-size: 11px; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: #444; margin-bottom: 6px; }}
  .signoff-tbl {{ width: 100%; border-collapse: collapse; font-size: 11px; margin: 0; }}
  .signoff-tbl td {{ padding: 9px 8px; border-top: 1px solid #eee; vertical-align: bottom; }}
  .signoff-tbl .r {{ width: 92px; font-weight: 600; color: #555; white-space: nowrap; }}
  .signoff-tbl .dt {{ width: 150px; white-space: nowrap; color: #555; }}
  .signoff-tbl .ln {{ display: inline-block; min-width: 90px; border-bottom: 1px solid #888; }}
</style>
</head>
<body>
<h1>Internal Certificate of Preparation</h1>
<p style="margin-top:2px;color:#555;font-size:11px">{lab_header}</p>
<p style="margin-top:2px;font-size:11px">{title}</p>
<dl class="cert-meta">
  <div><dt>Certificate number</dt><dd>{cert_id}</dd></div>
  <div><dt>Date of issue</dt><dd>{generated_date}</dd></div>
  <div><dt>Lot Number</dt><dd>{lot_number}</dd></div>
  <div><dt>Standard Type</dt><dd>{standard_type}</dd></div>
  <div><dt>Date Prepared</dt><dd>{prepared_date}</dd></div>
  <div><dt>Expiry Date</dt><dd>{expiry_date}</dd></div>
  <div><dt>Prepared By</dt><dd>{prepared_by}</dd></div>
  <div><dt>Storage Location</dt><dd>{storage_location}</dd></div>
  <div><dt>Storage conditions</dt><dd>{storage_conditions}</dd></div>
  <div><dt>Volume / Amount</dt><dd>{volume_prepared}</dd></div>
  <div><dt>{made_by_label}</dt><dd>{made_by_value}</dd></div>
</dl>

<h2 style="font-size:13px;margin-bottom:8px">Analyte Concentrations</h2>
<table>
  <thead><tr><th>Analyte</th><th>Concentration</th><th>Unit</th></tr></thead>
  <tbody>{analyte_rows}</tbody>
</table>

<h2 style="font-size:13px;margin-bottom:8px">Parentage &mdash; full hierarchy to source</h2>
<p style="margin:0 0 8px 0;color:#555">Each branch ends at a
<strong>manufacturer</strong> (supplier, catalogue number and CoA) or, for
reagent-grade water produced in house, at the <strong>Type 1 water system QC log
for the day it was used</strong>. Indentation shows depth: a lot made from a lot
made from a certified reference material reads down the page.</p>
<table>
  <thead><tr><th>Lot / source</th><th>Lot number</th><th>Provenance</th>
             <th>Amount used</th><th>Expiry</th></tr></thead>
  <tbody>{parent_rows}</tbody>
</table>

<h2 style="font-size:13px;margin-bottom:6px">Preparation record</h2>
<table>
  <thead><tr><th>Component</th><th>Lot number</th><th>Amount taken</th></tr></thead>
  <tbody>{calc_rows}</tbody>
</table>
<p style="margin-top:0;font-size:11px;color:#555">Made to a final volume of
<strong>{volume_prepared}</strong>.</p>

<h2 style="font-size:13px;margin-bottom:6px">Equipment used, and what it is traceable to</h2>
<table>
  <thead><tr><th>Role</th><th>Unit</th><th>Serial</th>
             <th>Calibration in force on {prepared_date}</th></tr></thead>
  <tbody>{equip_rows}</tbody>
</table>
<p style="margin-top:0;font-size:11px;color:#555">Calibration is judged as of the
date this lot was <strong>prepared</strong>, not today: a standard weighed on a
balance that was in calibration that morning stays defensible afterwards.</p>

<h2 style="font-size:13px;margin-bottom:6px">Metrological traceability (ISO 17025 §6.5)</h2>
<p style="margin-top:0">{trace_stmt}</p>

{expiry_note_section}

<div class="signoff">
  <div class="signoff-title">Quality Assurance sign-off</div>
  <p style="margin:0 0 8px 0;font-size:11px;color:#8a1c1c">
    <strong>UNSIGNED UNTIL DATED.</strong> The names below are the designated
    signatories; a row with no date and no signature records no review. This
    certificate is issued automatically when the lot is recorded and does not
    itself constitute verification or authorisation.</p>
  <table class="signoff-tbl">
    <tr><td class="r">Prepared&nbsp;by</td>
        <td>Prepared by <strong>{prepared_by}</strong>, as recorded at the bench.</td>
        <td class="dt">Date: {prepared_date}</td></tr>
    <tr><td class="r">Verification</td>
        <td>Reserved for <strong>{qao_name}</strong>, Quality Assurance Officer.
            Signature: <span class="ln">&nbsp;</span></td>
        <td class="dt">Date: <span class="ln">&nbsp;</span></td></tr>
    <tr><td class="r">Authorisation</td>
        <td>Reserved for <strong>{director_name}</strong>, Laboratory Director.
            Signature: <span class="ln">&nbsp;</span></td>
        <td class="dt">Date: <span class="ln">&nbsp;</span></td></tr>
  </table>
</div>
<div class="footer">
  {cert_id} &middot; issued {generated_date} &middot; all dates ISO 8601
  (YYYY-MM-DD). Generated automatically by senaite.pfas.<br>
  This document relates only to the lot identified above. It is an INTERNAL
  preparation record and is <strong>not a manufacturer certificate of
  analysis</strong>; it assigns no independently measured value.
</div>
</body>
</html>""".format(
        title=d.get("title", ""),
        lot_number=d.get("lot_number", ""),
        standard_type=d.get("standard_type", ""),
        prepared_date=d.get("prepared_date", ""),
        # an extended lot prints the extension: the date in force, the
        # original and who approved it (lot_extension.printed)
        expiry_date=_lx_printed(d.get("expiry_date", ""), d.get("extensions")),
        prepared_by=d.get("prepared_by", "") or u"—",
        qao_name=qao_name,
        director_name=director_name,
        storage_location=d.get("storage_location", ""),
        storage_conditions=d.get("storage_conditions") or u"not recorded",
        volume_prepared=d.get("volume_prepared", ""),
        # a lot names the preparation record that made it; a lot made
        # before records, the logbook it was entered on
        made_by_label=u"Preparation record" if d.get("entry_id") else u"Prep Logbook",
        made_by_value=d.get("entry_id") or u"%s (Rev %s)" % (d.get("logbook_title", ""),
                                                            d.get("logbook_revision", "")),
        analyte_rows=rows_html or u"<tr><td colspan='3'>No analytes recorded</td></tr>",
        parent_rows=parents_html,
        expiry_note_section=(
            u"<p style='font-size:11px;color:#856404;background:#fff3cd;padding:8px 12px;"
            u"border-radius:4px'><strong>Expiry Note:</strong> {}</p>".format(
                d.get("expiry_notes", ""))
            if d.get("expiry_notes") else u""
        ),
        generated_date=lab_time.today().isoformat(),
        lab_header=lab_header,
        cert_id=cert_id,
        trace_stmt=trace_stmt,
        calc_rows=calc_rows,
        equip_rows=equip_rows,
    )


def _why(exc):
    """A refusal's message as text: a SignatureRefused's own text, else the
    exception's."""
    text = getattr(exc, "text", None)
    if text:
        return text
    try:
        return u"%s" % exc
    except UnicodeDecodeError:
        return str(exc).decode("utf-8", "replace")


# ── View ──────────────────────────────────────────────────────────────────────



class PFASPrepStandardsView(ViewHelpers, PrepTypesMixin, BrowserView):
    """PFAS Prepared Standards — inventory, create, view certificate."""

    def core_storage(self):
        """Core Storage Locations: where a standard may be kept (core_lists.py)."""
        from senaite.pfas.browser.core_lists import storage_titles
        return storage_titles()

    template = ViewPageTemplateFile("templates/prep_standards.pt")

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if action == "cert":
            return self._serve_cert()
        if action == "verify_prep":
            return self._handle_verify_prep()
        if self.request.method == "POST":
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
            if action == "add":
                from six.moves.urllib.parse import quote_plus
                return self._redirect("{0}?error={1}".format(self._self_url(), quote_plus(
                    u"A new lot is made from its recipe: + New Prepared Standard.".encode("utf-8"))))
            if action == "edit":
                return self._handle_upsert()
            if action == "make_recipe":
                return self._handle_make_recipe()
            if action == "status":
                return self._handle_status()
            if action == "review_prep":
                return self._handle_review_prep()
        return self.template()

    # ── preparation records (prep_entries.py) ─────────────────────────────

    def parent_lots(self):
        """{"kind:uid": item}: the lots a prep may use -- not used up,
        archived or quarantined. A lot out of date is offered too: the
        sitting judges it against the prep date and uses it only with a
        reason (lot_expiry.gate)."""
        from senaite.pfas.bench_queue import is_usable, out_of_date_only
        from senaite.pfas.browser.bench_inventory import inventory_items
        today = lab_time.today().isoformat()
        return dict(("%s:%s" % (i["kind"], i["uid"]), i) for i in inventory_items(self._portal())
                    if is_usable(i, today) or out_of_date_only(i, today))

    def _handle_review_prep(self):
        from senaite.pfas import prep_entries
        from senaite.pfas.browser.staff import may_enter
        from senaite.pfas.entry_rights import REFUSAL
        from six.moves.urllib.parse import quote_plus
        f = self.request.form
        back = self._self_url()
        if f.get("back") == "recipes":
            # reviewed from the recipe's preparations: back to that recipe
            back = "{0}/@@pfas-recipes?method={1}".format(self.context.absolute_url(), quote_plus(
                (f.get("method") or u"").encode("utf-8")))
            if f.get("recipe"):
                back += "&recipe={0}".format(quote_plus((f.get("recipe") or u"").encode("utf-8")))
        sep = "&" if "?" in back else "?"
        if not may_enter():
            return self._redirect("{0}{1}error={2}".format(back, sep, quote_plus(REFUSAL.encode("utf-8"))))
        if f.get("sign") != "1":
            # a review is recorded only through the sign dialog
            return self._redirect("{0}{1}error=Sign+the+review+to+record+it.".format(back, sep))
        portal = self._portal()
        entries = prep_entries.load(portal)
        entry = entries.get(f.get("entry_id") or u"")
        if entry is None:
            return self._redirect("{0}{1}error=Record+not+found".format(back, sep))
        from AccessControl import getSecurityManager
        from senaite.pfas.esig import ledger, signing
        note = (f.get("sign_note") or u"").strip()
        request = self.request

        def sign(rid, h):
            return signing.cache([signing.sign(portal, request, "preparation", rid, prep_entries.REVISION, h, "reviewer",
                                               note=note)])
        try:
            prep_entries.review(entry, getSecurityManager().getUser().getId(),
                                datetime.utcnow().strftime("%Y-%m-%d %H:%M"), sign=sign)
        except (ValueError, signing.SignatureRefused, ledger.LedgerError) as exc:
            return self._redirect("{0}{1}error={2}".format(back, sep, quote_plus(_why(exc).encode("utf-8"))))
        prep_entries.save(portal, entries)
        return self._redirect("{0}{1}ok=Record+reviewed".format(back, sep))

    def _handle_verify_prep(self):
        """Read the record's signatures against its content now: the hash
        recomputed, every signature looked up in the ledger
        (prep_entries.verify). Back to the lot's record card."""
        from senaite.pfas import prep_entries
        from senaite.pfas.esig import ledger
        from six.moves.urllib.parse import quote_plus
        f = self.request.form
        back = self._self_url()
        if f.get("record"):
            back += "?record={0}".format(quote_plus((f.get("record") or u"").encode("utf-8")))
        sep = "&" if "?" in back else "?"
        entry = prep_entries.load(self._portal()).get(f.get("entry") or u"")
        if entry is None:
            return self._redirect("{0}{1}error=Record+not+found".format(back, sep))
        try:
            _current, st = prep_entries.signature_status(entry)
        except ledger.LedgerError:
            logger.exception("signatures of %s unreadable", entry.get("id"))
            return self._redirect("{0}{1}error=The+signatures+could+not+be+read".format(back, sep))
        why = prep_entries.verify(entry, st)
        if why:
            return self._redirect("{0}{1}error={2}".format(back, sep, quote_plus(why.encode("utf-8"))))
        return self._redirect("{0}{1}ok=Signatures+checked".format(back, sep))

    def _signature_card(self, entry):
        """The record card's Signatures: each signature as the print lists
        it (report_documents.signature_rows), read from the ledger against
        the record's content now; None when the ledger cannot be read."""
        from senaite.pfas import prep_entries, print_doc
        from senaite.pfas import report_documents as rd
        from senaite.pfas.esig import ledger
        try:
            current, st = prep_entries.signature_status(entry)
        except ledger.LedgerError:
            logger.exception("signatures of %s unreadable", entry.get("id"))
            return None
        return rd.signature_rows(st, current, lab_time.show, changed_at=print_doc.now_label())

    def make_esig(self):
        """The sign dialog of New Prepared Standard: the record is numbered
        and its content hashed when it is saved, so neither is known here."""
        from senaite.pfas import prep_entries
        from senaite.pfas.esig import signing
        return {"record": u"New preparation record", "revision": prep_entries.REVISION,
                "hash_prefix": u"Set when saved", "meaning_label": signing.meaning_label("preparer"),
                "signer_name": signed_in_name(self.context), "action": u"make_recipe", "form_id": u"psNewForm"}

    def make_nonce(self):
        """A new id for the Make form as drawn: its lots' uids come from it
        (prep_entries.lot_uids), so the same post retried names the same
        lots and signs the same content."""
        return uuid.uuid4().hex

    # ── New Prepared Standard: a sitting made from its recipe (prep_sitting) ─

    def _recipe_store(self):
        from senaite.pfas import recipes as rs
        if getattr(self, "_recipes_cache", None) is None:
            self._recipes_cache = rs.load(self._portal())
        return self._recipes_cache

    def _certificate(self, uid):
        """A purchased lot's certificate values (certificate_values.py)."""
        from senaite.pfas import certificate_values as cv
        from senaite.pfas.browser.reagents import _get_reagents_folder
        try:
            obj = _get_reagents_folder(self._portal()).get(uid)
            return json.loads(IAnnotations(obj).get(cv.KEY) or "{}") if obj is not None else {}
        except (RuntimeError, TypeError, ValueError):
            return {}

    def _choices(self, mf, usable, records):
        """The lots a "made from" may use, newest first, those out of date
        last: a purchased
        product's lots by name; a recipe's lots made from it, else (before
        any is) the lots under the recipe's name."""
        from senaite.pfas import recipe_calc as rc
        if mf.get("kind") == u"recipe":
            pinned = [i for i in usable if i["kind"] == u"prepared_standard"
                      and ((records.get(i["uid"]) or {}).get("recipe") or {}).get("id") == mf.get("ref")]
            name = (rc._rev(self._recipe_store(), mf.get("ref")) or {}).get("name")
            found = pinned or [i for i in usable if i["kind"] == u"prepared_standard" and i.get("name") == name]
        else:
            found = [i for i in usable if i["kind"] == u"reagent" and i.get("name") == mf.get("ref")]
        found.sort(key=lambda i: (i.get("received") or u"", i.get("lot_number") or u""), reverse=True)
        # a lot out of date today is listed last, never the one preselected
        from senaite.pfas.lot_expiry import expired_on
        today = lab_time.today()
        found.sort(key=lambda i: expired_on(i.get("expiry"), today))
        return [{"key": u"%s:%s" % (i["kind"], i["uid"]), "expiry": i.get("expiry") or u"",
                 "label": u"%s \u00b7 %s" % (i.get("lot_number") or u"", i.get("expiry") or u"no expiry")}
                for i in found]

    def new_standard(self):
        """The New Prepared Standard dialog's data: per method its recipes,
        each with its kind, code, default standard type and every "made
        from" with the lots it may use. The dialog opens on the recipe the
        address names (?method=&recipe=)."""
        from senaite.pfas import configured_methods, recipes as rs
        from senaite.pfas import prep_sitting
        from senaite.pfas.injection_names import method_code
        from senaite.pfas.method_profile_store import raw_profile
        portal = self._portal()
        store = self._recipe_store()
        usable = list(self.parent_lots().values())
        records = dict((r["uid"], r) for r in _list(portal))
        methods = []
        for m in configured_methods.choices(portal):
            code = method_code(raw_profile(portal, m["id"]) or {}, m["id"])
            recipes = []
            for rev in rs.for_method(store, m["id"]):
                names = prep_sitting.lot_names(rev, code)
                series = (rev.get("series") or {}).get("levels") or []
                final = series[0].get("final") if series else rev.get("final_volume")
                unit = (series[0].get("final_unit") if series else rev.get("final_unit")) or u"mL"
                recipes.append({
                    "id": rev["id"], "name": rev.get("name") or rev["id"],
                    "kind": rev.get("kind") or u"", "code": rev.get("code") or u"",
                    "standard_type": KIND_TYPES.get(rev.get("kind")) or u"",
                    "titles": [t for _l, t in names], "statement": prep_sitting.statement(names),
                    "final": final, "final_unit": unit, "per_level": bool(series),
                    "storage": rev.get("storage") or {}, "shelf_days": rs.shelf_life(rev),
                    "made_from": [{"kind": mf.get("kind"), "take": mf.get("take"),
                                   "take_unit": mf.get("take_unit") or u"",
                                   "label": (rs.active(store, mf.get("ref")) or {}).get("name") or mf.get("ref"),
                                   "lots": self._choices(mf, usable, records)}
                                  for mf in rev.get("made_from") or []]})
            methods.append({"id": m["id"], "label": m["label"], "recipes": recipes})
        return {"methods": methods, "who": signed_in_name(self.context)}

    def new_standard_json(self):
        return script_json(self.new_standard())

    # ── the lot record (lot_record.py) ────────────────────────────────────

    def record(self):
        """The lot record dialog's data for ?record=<uid>, or None."""
        if hasattr(self, "_record"):
            return self._record
        self._record = None
        uid = self.request.form.get("record") or u""
        if not uid:
            return None
        from senaite.pfas import lot_expiry, lot_record as lr, prep_entries, recipes as rs
        portal = self._portal()
        recs = dict((r["uid"], r) for r in _list(portal))
        rec = recs.get(uid)
        if rec is None:
            return None
        store = self._recipe_store()

        def revision(rid, n):
            return next((r for r in rs.revisions(store, rid) if r.get("revision") == n), None)

        def label(rid, n):
            return u"%s Rev %s" % ((revision(rid, n) or {}).get("name") or rid, n)
        pin = rec.get("recipe") or {}
        rev = revision(pin.get("id"), pin.get("revision")) if pin.get("id") else None
        entry = prep_entries.load(portal).get(rec.get("entry_id") or u"") or {}
        shelf = rs.shelf_life(rev) if rev else None
        made = lr.sitting(entry, recs)
        self._record = {
            # a lot made from a preparation record shows that record's
            # signatures; a lot made before records has none to show
            "entry_id": entry.get("id") or u"",
            "signatures": self._signature_card(entry) if entry.get("id") else [],
            "uid": uid, "title": u"Lot %s \u00b7 %s" % (rec.get("lot_number") or u"", rec.get("title") or u""),
            "recipe": label(pin["id"], pin.get("revision")) if rev else u"",
            "recorded_on": lr.recorded_on(entry),
            "made": u"%s by %s" % (rec.get("prepared_date") or u"", rec.get("prepared_by") or u""),
            "expires": rec.get("effective_expiry") or rec.get("expiry_date") or u"",
            "expiry_note": lr.expiry_note(rec, shelf),
            # the extension in force: the original date and who approved it
            "extension": _lx_note(rec.get("extensions")),
            # a parent its preparation used out of date, and why (lot_expiry.gate)
            # a lot not made from a recipe keeps the reasons on its own parents
            "expired_parents": lot_expiry.statement(
                parents_in_force(portal, entry.get("parents") or rec.get("parent_reagents")),
                entry.get("prepared_date") or rec.get("prepared_date")),
            "tree": lr.tree_rows(rec, build_parentage(portal, rec), label),
            "steps": lr.steps(rev, rec.get("prepared_by")),
            "conc": lr.conc_rows(rec),
            "sitting": made, "sitting_text": (u"%s to %s" % (made[0], made[-1])) if len(made) > 1 else u"",
            "label_url": self.label_url(rec),
            "labels_url": (u"%s/@@pfas-sitting-labels?entry=%s" % (self.portal_url(), rec["entry_id"]))
                          if len(made) > 1 else u"",
            "cert_url": u"%s/@@pfas-prep-standards?action=cert&uid=%s" % (self.portal_url(), uid),
        }
        return self._record


    def _handle_make_recipe(self):
        """One preparation record of the recipe, one lot per level, each
        pinned to the recipe revision (prep_sitting.build, prep_entries.make)."""
        from senaite.pfas import prep_entries, prep_sitting, recipes as rs
        from senaite.pfas.browser.staff import may_enter
        from senaite.pfas.entry_rights import REFUSAL
        from senaite.pfas.injection_names import method_code
        from senaite.pfas.method_profile_store import raw_profile
        from six.moves.urllib.parse import quote_plus
        f = self.request.form
        back = self._self_url()
        rid, mid = f.get("recipe") or u"", f.get("method") or u""

        def refused(msg):
            # the sitting reopens on the method and recipe it was made from
            keep = u"new=1&method={0}&recipe={1}&".format(
                quote_plus(mid.encode("utf-8")), quote_plus(rid.encode("utf-8"))) if rid else u""
            return self._redirect("{0}?{1}error={2}".format(back, keep, quote_plus((u"%s" % msg).encode("utf-8"))))
        if not may_enter():
            return refused(REFUSAL)
        if f.get("sign") != "1":
            # a record is saved only through the sign dialog
            return refused(u"Sign the record to save it.")
        portal = self._portal()
        rev = rs.active(self._recipe_store(), rid)
        if rev is None or mid not in (rev.get("methods") or []):
            return refused(u"Choose a standard the method prepares.")
        if rs.shelf_life(rev) is None:
            # a lot's expiry is its recipe's shelf life: none, no lot
            return refused(u"The recipe has no shelf life: edit it first.")
        lots = self.parent_lots()
        parents, made_from = [], []
        for i, mf in enumerate(rev.get("made_from") or []):
            made_from.append(dict(mf, ref=(rs.active(self._recipe_store(), mf.get("ref")) or {}).get("name")
                                  or mf.get("ref")))
            item = lots.get(f.get("pl_lot.%d" % i) or u"")
            p = {"item": None, "qty": (f.get("pl_qty.%d" % i) or u"").strip(),
                 "unit": (f.get("pl_unit.%d" % i) or u"").strip() or mf.get("take_unit") or u""}
            if item is not None:
                item = dict(item)
                # judged on the date in force on the prep date: an extension
                # approved after it does not reach back (lot_extension)
                prep_day = (f.get("prepared_date") or u"").strip()[:10]
                if prep_day:
                    item["expiry"] = lot_in_force(portal, item["uid"], prep_day)
                if item["kind"] == u"prepared_standard":
                    item["analyte_concentrations"] = (_get(portal, item["uid"]) or {}).get("analyte_concentrations") or []
                else:
                    p["cert"] = self._certificate(item["uid"])
                p["item"] = item
            parents.append(p)
        equipment = [{"unit_id": (f.get(key) or u"").strip(), "role": role}
                     for key, role in (("equip_balance_unit_id", u"Balance"), ("equip_pipette_unit_id", u"Pipette"))
                     if (f.get(key) or u"").strip()]
        sitting = {"prepared_by": signed_in_name(self.context),
                   "prepared_date": (f.get("prepared_date") or u"").strip(),
                   "standard_type": (f.get("standard_type") or u"").strip() or KIND_TYPES.get(rev.get("kind")) or u"",
                   "storage_location": (f.get("storage_location") or u"").strip(),
                   "storage_conditions": (f.get("storage_conditions") or u"").strip(),
                   "equipment": equipment, "final": (f.get("final") or u"").strip(),
                   "shelf_days": rs.shelf_life(rev),
                   # a lot number is never repeated (a second sitting that day)
                   "taken": [r.get("lot_number") for r in _list(portal)],
                   # a standard's or a series' concentrations are calculated, never typed
                   "needs_values": rev.get("kind") in (u"standard", u"series"),
                   # why a parent out of date on the prep date is used
                   "expired_reason": (f.get("expired_reason") or u"").strip()}
        code = method_code(raw_profile(portal, mid) or {}, mid)
        # the record takes the active revision's own code, the one its pin
        # names; the code check holds it for this recipe while a draft
        # names another
        entry, rows, problems = prep_sitting.build(
            dict(rev, made_from=made_from, code=rev.get("code") or u""), rid, code, sitting, parents)
        if problems:
            return refused(u" ".join(problems))
        note = (f.get("notes") or u"").strip()
        for r in rows:
            r["notes"] = note
        from AccessControl import getSecurityManager
        from senaite.pfas.esig import ledger, signing
        request = self.request
        # the lots take their uids from the form's nonce: a retry after a
        # conflict posts the same nonce and signs the same content
        uids = prep_entries.lot_uids((f.get("make_nonce") or u"").strip() or uuid.uuid4().hex, len(rows))
        folder = _get_folder(portal)
        if [u for u in uids if u in folder]:
            # the form was saved already (posted again from the browser)
            return refused(u"This form was saved already: reload the page.")

        def sign(record_id, record_hash):
            # signed before any lot, the record or a usage row is saved
            return prep_entries.sign_made(portal, request, record_id, record_hash,
                                          note=(f.get("sign_note") or u"").strip())
        try:
            entry_id, uids = prep_entries.make(portal, entry, rows, getSecurityManager().getUser().getId(),
                                               datetime.utcnow().strftime("%Y-%m-%d %H:%M"), sign=sign, uids=uids,
                                               held=prep_entries.held_in_ledger)
        except RuntimeError as exc:
            # a lot saved under another id: the lots saved before it must
            # not stay without their record
            import transaction
            transaction.abort()
            return refused(_why(exc))
        except (ValueError, signing.SignatureRefused, ledger.LedgerError) as exc:
            return refused(_why(exc))
        return self._redirect("{0}?ok={1}".format(back, quote_plus(
            (u"%s saved: %d lot(s) made, pending acceptance." % (entry_id, len(uids))).encode("utf-8"))))

    def facility_balances(self):
        """Registered balances, for the equipment picker. The registry is the one
        Facility QC owns, so a unit named here already has a calibration chain."""
        return self._facility_units(("balance_analytical", "balance_prep"))

    def facility_pipettes(self):
        return self._facility_units(("pipette",))

    def _facility_units(self, kinds):
        try:
            from senaite.pfas import facility_qc as fq
            return [u for u in fq.list_units() if u["unit_type"] in kinds]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("facility units unavailable: %s", exc)
            return []

    def _self_url(self):
        return "{}/@@pfas-prep-standards".format(self.context.absolute_url())

    # ── Template data ─────────────────────────────────────────────────────

    def statuses(self):
        return STATUSES

    def status_filter(self):
        """The Status filter: active until someone chooses ("all" = every
        status)."""
        s = self.request.form.get("status")
        if s is None:
            return u"active"
        return u"" if s == "all" else s

    def prepared_standards(self):
        return _list(
            self._portal(),
            q=self.request.form.get("q", ""),
            status_filter=self.status_filter(),
            type_filter=self.request.form.get("type", ""),
        )

    def attention(self, rec):
        """Why an active standard needs attention: no preparation record or
        logbook linked (a traceability gap), or expiring within 30 days."""
        if rec.get("status") != "active":
            return []
        from senaite.pfas import certificate_values as cv
        from senaite.pfas import lot_attention
        obj = _get_folder(self._portal()).get(rec.get("uid") or u"")
        return lot_attention.reasons(expiry=rec.get("effective_expiry") or rec.get("expiry_date"),
                                     logbook=bool(rec.get("entry_id") or rec.get("logbook_slug")),
                                     review=cv.flags_of(obj) if obj is not None else None)

    def edit_uid(self):
        return self.request.form.get("edit_uid", "")

    def edit_data_json(self):
        uid = self.edit_uid()
        if uid:
            rec = _get(self._portal(), uid)
            if rec:
                return script_json(rec)
        return "null"

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def label_url(self, rec):
        """Print label: this lot's values on @@pfas-label."""
        from senaite.pfas import lot_extension
        from senaite.pfas.browser.label_print import label_href
        return label_href(self.portal_url(), back=self.portal_url() + "/@@pfas-prep-standards",
                          name=rec.get("title"), lot=rec.get("lot_number"),
                          exp=rec.get("effective_expiry") or rec.get("expiry_date"),
                          date=rec.get("prepared_date"), analyst=rec.get("prepared_by"),
                          vol=rec.get("volume_prepared"),
                          storage=rec.get("storage_conditions") or rec.get("storage_location"),
                          **lot_extension.label_values(rec.get("extensions")))

    def expiry_class(self, rec):
        # colour by the EFFECTIVE (possibly parent-inherited) expiry
        exp = rec.get("effective_expiry") or rec.get("expiry_date", "")
        if not exp:
            return ""
        try:
            d = datetime.strptime(exp, "%Y-%m-%d").date()
            today = lab_time.today()
            if d < today:
                return "exp-expired"
            if (d - today).days <= 30:
                return "exp-warning"
        except (ValueError, TypeError):
            pass
        return ""

    # ── Action handlers ───────────────────────────────────────────────────

    def _handle_upsert(self):
        f = self.request.form
        title = f.get("title", "").strip()
        lot = f.get("lot_number", "").strip()
        if not title or not lot:
            return self._redirect("{0}?error=Title+and+Lot+Number+required".format(
                self._self_url()))

        # An edit sets the logbook, the expiry justification, the parents and
        # the concentrations only when it posts them; otherwise the lot keeps
        # its own (prep_sitting.edit_values).
        from senaite.pfas import prep_sitting
        stored = _get(self._portal(), (f.get("uid") or "").strip()) or {}
        kept = prep_sitting.edit_values(f, stored)
        parents = kept["parent_reagents"]
        analytes = kept["analyte_concentrations"]
        # a parent the edit adds that was out of date on the date prepared is
        # refused unless a reason is given, kept on that parent as a
        # preparation keeps it; the parents already on the lot keep theirs
        from senaite.pfas import lot_expiry
        prep_day = f.get("prepared_date", "").strip() or stored.get("prepared_date") or u""
        parents, expired = lot_expiry.gate_edit(
            parents, stored.get("parent_reagents") or [],
            [p.get("expiry") for p in parents_in_force(self._portal(), parents, as_of=prep_day)],
            prep_day, f.get("expired_reason"))
        if expired:
            from six.moves.urllib.parse import quote_plus
            return self._redirect("{0}?error={1}".format(
                self._self_url(), quote_plus(u" ".join(expired).encode("utf-8"))))

        # Compute default expiry if not supplied
        logbook_slug = (kept["logbook_slug"] or u"").strip()
        expiry_date = f.get("expiry_date", "").strip()
        if not expiry_date and stored.get("expiry_date"):
            # a blank expiry keeps the recorded one, never a later default
            expiry_date = (stored.get("expiry_date") or u"")[:10]
        expiry_days = 365
        logbook_title = (kept["logbook_title"] or u"").strip()
        logbook_revision = kept["logbook_revision"] or 1
        if logbook_slug and not expiry_date:
            # a lot made on a logbook keeps the title and revision it was
            # made under; with no expiry kept, the default shelf life applies
            prepared_date = f.get("prepared_date", "").strip()
            expiry_date = _compute_expiry(prepared_date, expiry_days)

        data = {
            "uid":              f.get("uid", "").strip() or None,
            "title":            title,
            "lot_number":       lot,
            "standard_type":    f.get("standard_type", "").strip(),
            "logbook_slug":     logbook_slug,
            "logbook_revision": logbook_revision,
            "logbook_title":    logbook_title,
            "prepared_by":      f.get("prepared_by", "").strip(),
            "prepared_date":    f.get("prepared_date", "").strip(),
            "expiry_date":      expiry_date,
            "expiry_notes":     (kept["expiry_notes"] or u"").strip(),
            "storage_location": f.get("storage_location", "").strip(),
            "storage_conditions": f.get("storage_conditions", "").strip(),
            "volume_prepared":  f.get("volume_prepared", "").strip(),
            "notes":            f.get("notes", "").strip(),
            # NB: no "status" key — the edit form does not post one, and
            # including it here would reset an exhausted lot to active.
            # Status is changed only through _handle_status.
            "parent_reagents":  parents,
            "analyte_concentrations": analytes,
        }
        # Only a form that DECLARES it owns the equipment field may set it.
        # Without the marker, saving through any other path would wipe the record
        # -- the same trap that once resurrected exhausted lots via `status`.
        if f.get("equipment_posted"):
            equipment = []
            for key, role in (("equip_balance_unit_id", u"Balance"),
                              ("equip_pipette_unit_id", u"Pipette")):
                unit_id = (f.get(key, "") or "").strip()
                if unit_id:
                    equipment.append({"unit_id": unit_id, "role": role})
            data["equipment"] = equipment
        # storage is a core Storage Location (core_lists.py)
        from senaite.pfas.browser.core_lists import problems
        from senaite.pfas.browser.core_lists import lot_problems
        from six.moves.urllib.parse import quote_plus
        bad = lot_problems(data) + problems(data, kinds=("storage_location",))
        # a recorded expiry moves earlier only: a later date comes through an
        # extension (lot_extension.edit_problems)
        from senaite.pfas import lot_extension
        bad += lot_extension.edit_problems((("expiry_date", u"The expiry"),), stored, data)
        if bad:
            return self._redirect("{0}?error={1}".format(self._self_url(), quote_plus(bad[0].encode("utf-8"))))
        _save(self._portal(), data)
        return self._redirect("{0}?ok=Prepared+standard+saved".format(self._self_url()))

    def _handle_status(self):
        uid = self.request.form.get("uid", "").strip()
        new_status = self.request.form.get("new_status", "").strip()
        rec = _get(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Not+found".format(self._self_url()))
        # Whitelist: _populate_obj assigns obj.status directly, which bypasses
        # the schema.Choice vocabulary — an unrecognised value would persist and
        # make the lot permanently invisible to the picker (which allows only
        # "active") with no error anywhere.
        if new_status not in dict(STATUSES):
            return self._redirect(
                "{0}?error=Unknown+status".format(self._self_url()))
        from senaite.pfas.lot_status import status_change_problem
        from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal
        why = status_change_problem(rec.get("status") or STATUS_ACTIVE, new_status,
                                    has_role_at_portal(self.context, MANAGER_ROLES))
        if why:
            from six.moves.urllib.parse import quote_plus
            return self._redirect("{0}?error={1}".format(self._self_url(), quote_plus(why.encode("utf-8"))))
        rec["status"] = new_status
        _save(self._portal(), rec)
        return self._redirect("{0}?ok=Status+updated".format(self._self_url()))

    def _serve_cert(self):
        """Serve the certificate, RESOLVED NOW rather than replayed from disk.

        Two defects lived here:

        1. The stored file was preferred whenever it existed, so every certificate
 written before still asserted an unresolvable parent as established
 fact with the QA attestation attached -- the exact claim recorded
 as wrong -- and none written before named the equipment. The
           document and the release gate disagreed about the same lot, which is
 the divergence already cost three separate resolvers to fix.
        2. The on-demand fallback called `_render_cert_html(rec, signers)` with
           **no `portal=`**, and without the portal the renderer cannot walk the
           parentage or the equipment at all. So the branch meant to cover a
           missing file reproduced the very defect the stored file had.

        Rendering on every serve costs a parentage walk (~0.2 ms per lot, measured
 in ) and a SQLite read, and it cannot go stale. The stored file stays
        as the write-time artefact.

        NOTE: a certificate that has been SIGNED must be frozen instead, the way
 freezes resolved criteria at the moment they judge. Nothing captures a
        signature yet -- every certificate prints "UNSIGNED UNTIL DATED" with
        reserved rows -- so there is nothing to freeze, and a fresh render is
        unambiguously the truthful answer today. When sign-off is built, this is
        the place that has to change with it.
        """
        uid = self.request.form.get("uid", "").strip()
        rec = _get(self._portal(), uid)
        if not rec:
            self.request.response.setStatus(404)
            return "Certificate not found"
        from senaite.pfas.print_settings import get_signoff_signers
        html = _render_cert_html(rec, get_signoff_signers(self._portal()),
                                 portal=self._portal())
        self.request.response.setHeader("Content-Type", "text/html; charset=utf-8")
        return html
