# -*- coding: utf-8 -*-
"""
PFAS Prepared Standards (@@pfas-prep-standards).

Manages in-house prepared reagents and standards.  Each record links to
a PrepLogbookDef revision (slug + revision number), stores the parent
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

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.prepared_standards")

_ANN_PARENTS  = u"senaite.pfas.prepstd.parent_reagents"
_ANN_ANALYTES = u"senaite.pfas.prepstd.analyte_concentrations"
# The equipment a lot was MADE WITH. A prepared standard's assigned value rests on
# a mass and a volume, so under ISO 17025 §6.5 the balance and pipette that
# measured them are part of its traceability -- and the certificate could not name
# them (GAPS §37.5). Stored as `[{"unit_id": ..., "role": ...}]`, referencing the
# Facility QC unit registry, so the calibration chain is RESOLVED at read time by
# facility_qc.equipment_provenance rather than copied onto the lot and left to rot.
_ANN_EQUIPMENT = u"senaite.pfas.prepstd.equipment"

CERT_DIR = os.environ.get("PFAS_CERT_DIR", "/data/coa/certs")

STATUS_ACTIVE    = "active"
STATUS_EXHAUSTED = "exhausted"
STATUS_EXPIRED   = "expired"

# Vocabulary is OWNED by the PreparedStandard content type — single source of
# truth (was duplicated here). Imported so this view stays in lock-step.
from senaite.pfas.content.prepared_standard import STANDARD_TYPES  # noqa: F401


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
    try:
        ann = IAnnotations(obj)
        ann[key] = json.dumps(value)
    except Exception as exc:
        logger.error("_set_ann %s: %s", key, exc)


# ── Date helpers ────────────────────────────────────────────────────────────────

def _date_str(d):
    if not d:
        return u""
    try:
        return d.strftime("%Y-%m-%d")
    except AttributeError:
        return unicode(d)[:10] if d else u""


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _compute_expiry(prepared_date_str, expiry_days):
    """Return ISO expiry string = prepared_date + expiry_days."""
    d = _parse_date(prepared_date_str)
    if not d:
        d = date.today()
    try:
        exp = d + timedelta(days=int(expiry_days or 365))
    except (TypeError, ValueError):
        exp = date(d.year + 1, d.month, d.day)
    return exp.strftime("%Y-%m-%d")


def _is_expired(expiry_str):
    d = _parse_date(expiry_str)
    if not d:
        return False
    return d < date.today()


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
        "volume_prepared": obj.volume_prepared or u"",
        "status":          obj.status or STATUS_ACTIVE,
        "notes":           obj.notes or u"",
        "parent_reagents": _get_ann(obj, _ANN_PARENTS, []),
        "analyte_concentrations": _get_ann(obj, _ANN_ANALYTES, []),
        "equipment": _get_ann(obj, _ANN_EQUIPMENT, []),
    }
    # Auto-update expired status (transient read-time only — not written to DB here)
    if d["status"] == STATUS_ACTIVE and _is_expired(d["expiry_date"]):
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
        defaults = data.get("_expiry_defaults") or {}
        days = int(defaults.get("prepared_std_default_days", 365))
        obj.expiry_date = obj.prepared_date + timedelta(days=days)
        note = u"Expiry assigned from global default ({0} days from prep)".format(days)
        prev = data.get("expiry_notes") or u""
        data["expiry_notes"] = (prev + u"\n" + note).strip() if prev else note
    obj.expiry_notes = data.get("expiry_notes") or u""
    obj.storage_location = data.get("storage_location") or u""
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
    try:
        from senaite.pfas.browser.reagents import get_expiry_defaults
        data["_expiry_defaults"] = get_expiry_defaults(portal)
    except Exception:
        pass
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


def _get(portal, uid):
    try:
        folder = _get_folder(portal)
    except RuntimeError:
        return None
    obj = folder.get(uid)
    return _obj_to_dict(obj) if obj else None


def effective_expiry_info(portal, d):
    """Inherited expiry: min(own expiry, every parent reagent lot's effective
    expiry). If a parent is tighter (earlier), the prep inherits it.
    Returns {"date": iso, "inherited_from": parent-name-or-empty}."""
    own = d.get("expiry_date") or ""
    eff, src = own, ""
    try:
        from senaite.pfas.browser.reagents import get_reagent_effective_expiry
        for p in d.get("parent_reagents") or []:
            pexp = get_reagent_effective_expiry(
                portal, p.get("lot", ""), p.get("name", ""))
            if pexp and (not eff or pexp < eff):
                eff, src = pexp, (p.get("name") or p.get("lot") or u"parent")
    except Exception:
        pass
    return {"date": eff, "inherited_from": src}


# ── Parentage hierarchy ──────────────────────────────────────────────────────
# THE canonical walk from a prepared standard up to what it was ultimately made
# from. Both the Certificate of Preparation and the Data Review traceability gate
# call it, so the document and the gate cannot disagree -- they did before, and
# GAPS §33.9 recorded three separate resolvers giving three different answers
# about whether one parent existed.
#
# A lot may be made from another LOT, not only from a manufactured reagent: a
# working standard from a secondary stock from a primary stock from the CRM. So
# the walk recurses, and every branch must terminate in one of exactly three
# ways:
#
#   MANUFACTURER   a Reagent with a supplier -- the ISO 17025 §6.6 leaf
#   WATER          in-house Type 1 water, whose provenance is the water QC log
#                  for the day it was used, not a supplier (§36)
#   PROBLEM        anything else: unresolvable, or water with no log entry
#
# There is no fourth ending. A branch that stops anywhere else is a traceability
# failure by construction rather than by a check someone remembered to write --
# which is how level 1 went unenforced for so long (§33.2).

KIND_MANUFACTURER = u"manufacturer"
KIND_WATER = u"water"
KIND_PREPARED = u"prepared"
KIND_UNRESOLVED = u"unresolved"

MAX_PARENTAGE_DEPTH = 12


def _resolve_lot(portal, parent):
    """(object, kind) for a parent record -- a Reagent or another
    PreparedStandard. UID first, lot string second (GAPS §33.7)."""
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
        }

        if obj is None:
            node["problems"].append(
                u"lot %s is not in inventory" % (lot or u"(blank)"))
            nodes.append(node)
            continue

        node["name"] = obj.Title() or node["name"]
        node["url"] = obj.absolute_url()

        if kind == KIND_MANUFACTURER:
            from senaite.pfas.browser.reagents import (
                _COA_ANN_KEY, _ANN_ARCHIVED_KEY, _obj_to_dict as _rdict,
                _effective_expiry, get_expiry_defaults)
            rd = _rdict(obj)
            node["supplier"] = rd.get("supplier") or u""
            node["cat_number"] = rd.get("cat_number") or u""
            node["expiry"] = _effective_expiry(rd, get_expiry_defaults(portal))
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
            node["expiry"] = str(child_rec.get("expiry_date") or "")[:10]
            if child_lot and child_lot in _seen:
                node["problems"].append(
                    u"circular parentage: %s is already in this chain"
                    % child_lot)
            else:
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
        if status_filter and d["status"] != status_filter:
            continue
        if type_filter and d["standard_type"] != type_filter:
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
        # established fact with the QA attestation attached (GAPS §33.3).
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
            else:
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
        if n.get("url"):
            name = u'<a href="{0}">{1}</a>'.format(n["url"], name)
        amount = u"{0} {1}".format(n.get("qty") or u"", n.get("unit") or u"").strip()
        out += (
            u'<tr><td style="padding-left:{pad}px">{badge} {name}</td>'
            u'<td>{lot}</td><td>{prov}</td><td>{amount}</td>'
            u'<td>{expiry}</td></tr>').format(
                pad=pad, badge=badge, name=name, lot=n.get("lot") or u"—",
                prov=prov, amount=amount or u"—", expiry=n.get("expiry") or u"—")
        for prob in n.get("problems") or []:
            out += (u'<tr><td colspan="5" style="padding-left:{0}px" '
                    u'class="pk-problem">&#9888; {1}</td></tr>').format(
                        pad + 18, prob)
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
    try:
        from senaite.pfas import facility_qc as fq
    except Exception as exc:                                    # noqa: BLE001
        logger.error("equipment chain: facility_qc unavailable: %s", exc)
        return out
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


def _render_equipment_html(nodes):
    """Equipment rows for the certificate: what was used, and what its measurement
    is traceable TO. A row that ends nowhere says so on the document."""
    if not nodes:
        return (u'<tr><td colspan="4">No equipment recorded against this lot '
                u'&mdash; the balance and pipettes used, and their calibration '
                u'status, cannot be shown. Record them on the prepared-standard '
                u'form.</td></tr>')
    rows = u""
    for n in nodes:
        traced = []
        for r in n.get("records") or []:
            d = r.get("data") or {}
            if r.get("type") == "weight_set":
                traced.append(u"weight set {0} &mdash; {1}, cert {2}".format(
                    d.get("set_id") or u"?", d.get("cal_lab") or u"?",
                    d.get("cal_cert_number") or u"?"))
            elif r.get("type") == "balance_verification":
                traced.append(u"verified {0}".format(d.get("verified_date") or u"?"))
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
            cell += (u'<br><span style="color:#8a1c1c">&#9888; '
                     + u"; ".join(n["problems"]) + u"</span>")
        rows += u"<tr><td>{0}</td><td>{1}</td><td>{2}</td><td>{3}</td></tr>".format(
            n.get("role") or u"&mdash;", n.get("name") or u"&mdash;",
            n.get("serial") or u"&mdash;", cell)
    return rows


def _render_cert_html(d, signers=None, portal=None):
    """Return the internal certificate HTML string for a prepared-standard dict.

    `signers` (optional) = {"qao": staff-dict-or-None, "director": ...} from
    print settings; drives the 3-tier QA attestation. Names only (this cert is
    written to a standalone file, so signature-image URLs are not embedded)."""
    signers = signers or {}
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
            parentage = build_parentage(portal, d)
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
        try:
            lab = portal.bika_setup.laboratory
            nm = (lab.getName() or u"").strip()
            if nm and nm != u"Laboratory Information":
                lab_name = nm
            addr = lab.getPostalAddress() or {}
            lab_address = u", ".join(
                [x for x in (addr.get("address"), addr.get("city"),
                             addr.get("zip"), addr.get("state"),
                             addr.get("country")) if x])
        except Exception:
            pass
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
            u'these were prepared against is unverified, so traceability to a '
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
    # (GAPS §37.5): a certificate that cannot name the balance behind its own mass
    # cannot substantiate the assigned value it carries.
    equipment = []
    if portal is not None:
        try:
            equipment = build_equipment(portal, d)
        except Exception as exc:                            # noqa: BLE001
            logger.error("certificate equipment for %s: %s",
                         d.get("lot_number"), exc)
            equipment = []
    equip_rows = _render_equipment_html(equipment)
    equip_problems = equipment_problems(equipment)
    if equip_problems:
        equip_rows += (
            u'<tr><td colspan="4" class="pk-banner">'
            u'&#9888; {0} of the equipment record(s) above do not trace to a '
            u'calibrated standard for the day this lot was prepared.'
            u'</td></tr>').format(len(equip_problems))

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
        # established fact with the 3-tier QA attestation attached (GAPS §33.3);
        # a certificate that cannot substantiate its own parentage has to say so.
        parents_html += (
            u'<tr><td colspan="5" class="pk-banner">'
            u'&#9888; THIS PARENTAGE IS NOT FULLY SUBSTANTIATED &mdash; '
            u'{0} unresolved link(s). The data-review traceability gate will '
            u'reject a worksheet that uses this lot until they are resolved.'
            u'</td></tr>').format(len(problems))
    elif not parentage:
        parents_html = (u'<tr><td colspan="5" class="pk-banner">&#9888; '
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
  <div><dt>Volume / Amount</dt><dd>{volume_prepared}</dd></div>
  <div><dt>Prep Logbook</dt><dd>{logbook_title} (Rev {logbook_revision})</dd></div>
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
        expiry_date=d.get("expiry_date", ""),
        prepared_by=d.get("prepared_by", "") or u"—",
        qao_name=qao_name,
        director_name=director_name,
        storage_location=d.get("storage_location", ""),
        volume_prepared=d.get("volume_prepared", ""),
        logbook_title=d.get("logbook_title", ""),
        logbook_revision=d.get("logbook_revision", ""),
        analyte_rows=rows_html or u"<tr><td colspan='3'>No analytes recorded</td></tr>",
        parent_rows=parents_html,
        expiry_note_section=(
            u"<p style='font-size:11px;color:#856404;background:#fff3cd;padding:8px 12px;"
            u"border-radius:4px'><strong>Expiry Note:</strong> {}</p>".format(
                d.get("expiry_notes", ""))
            if d.get("expiry_notes") else u""
        ),
        generated_date=date.today().strftime("%Y-%m-%d"),
        lab_header=lab_header,
        cert_id=cert_id,
        trace_stmt=trace_stmt,
        calc_rows=calc_rows,
        equip_rows=equip_rows,
    )


# ── View ──────────────────────────────────────────────────────────────────────

class PFASPrepStandardsView(BrowserView):
    """PFAS Prepared Standards — inventory, create, view certificate."""

    template = ViewPageTemplateFile("templates/prep_standards.pt")

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if action == "cert":
            return self._serve_cert()
        if self.request.method == "POST":
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            if action in ("add", "edit"):
                return self._handle_upsert()
            if action == "status":
                return self._handle_status()
            if action == "delete":
                return self._handle_delete()
        return self.template()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

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

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    # ── Template data ─────────────────────────────────────────────────────

    def prepared_standards(self):
        return _list(
            self._portal(),
            q=self.request.form.get("q", ""),
            status_filter=self.request.form.get("status", ""),
            type_filter=self.request.form.get("type", ""),
        )

    def prep_logbooks(self):
        """Return active/draft logbooks for the prep form selector."""
        from senaite.pfas.browser.prep_logbooks import _get_active_families
        try:
            return _get_active_families(self._portal())
        except Exception as exc:
            logger.error("prep_logbooks: %s", exc)
            return []

    def standard_types(self):
        return STANDARD_TYPES

    def edit_uid(self):
        return self.request.form.get("edit_uid", "")

    def edit_data_json(self):
        uid = self.edit_uid()
        if uid:
            rec = _get(self._portal(), uid)
            if rec:
                return json.dumps(rec)
        return "null"

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def expiry_class(self, rec):
        # colour by the EFFECTIVE (possibly parent-inherited) expiry
        exp = rec.get("effective_expiry") or rec.get("expiry_date", "")
        if not exp:
            return ""
        try:
            d = datetime.strptime(exp, "%Y-%m-%d").date()
            today = date.today()
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

        # Parse parent reagents from JSON form field
        try:
            parents = json.loads(f.get("parent_reagents_json", "[]") or "[]")
        except (ValueError, TypeError):
            parents = []

        # Parse analyte concentrations from JSON form field
        try:
            analytes = json.loads(f.get("analyte_concentrations_json", "[]") or "[]")
        except (ValueError, TypeError):
            analytes = []

        # Compute default expiry if not supplied
        logbook_slug = f.get("logbook_slug", "").strip()
        expiry_date = f.get("expiry_date", "").strip()
        expiry_days = 365
        logbook_title = f.get("logbook_title", "").strip()
        logbook_revision = f.get("logbook_revision", "1")
        if logbook_slug and not expiry_date:
            # Look up default_expiry_days from the logbook
            try:
                from senaite.pfas.browser.prep_logbooks import _list as lb_list
                lbs = lb_list(self._portal(), slug=logbook_slug, status_filter="active")
                if not lbs:
                    lbs = lb_list(self._portal(), slug=logbook_slug)
                if lbs:
                    # Sort by revision desc, take highest
                    lbs.sort(key=lambda x: -x["revision"])
                    expiry_days = lbs[0].get("default_expiry_days") or 365
                    if not logbook_title:
                        logbook_title = lbs[0].get("title", "")
                    if not logbook_revision:
                        logbook_revision = lbs[0].get("revision", 1)
            except Exception as exc:
                logger.error("logbook lookup: %s", exc)
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
            "expiry_notes":     f.get("expiry_notes", "").strip(),
            "storage_location": f.get("storage_location", "").strip(),
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
        uid = _save(self._portal(), data)
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
        if new_status not in (STATUS_ACTIVE, STATUS_EXHAUSTED, STATUS_EXPIRED):
            return self._redirect(
                "{0}?error=Unknown+status".format(self._self_url()))
        rec["status"] = new_status
        _save(self._portal(), rec)
        return self._redirect("{0}?ok=Status+updated".format(self._self_url()))

    def _handle_delete(self):
        uid = self.request.form.get("uid", "").strip()
        try:
            folder = _get_folder(self._portal())
            if uid in folder:
                folder.manage_delObjects([uid])
                # Remove cert file
                cert_path = os.path.join(CERT_DIR, "{}.html".format(uid))
                if os.path.exists(cert_path):
                    os.remove(cert_path)
                return self._redirect("{0}?ok=Deleted".format(self._self_url()))
        except Exception as exc:
            logger.error("delete prepared standard: %s", exc)
        return self._redirect("{0}?error=Not+found".format(self._self_url()))

    def _serve_cert(self):
        """Serve the certificate, RESOLVED NOW rather than replayed from disk.

        Two defects lived here (GAPS §44):

        1. The stored file was preferred whenever it existed, so every certificate
           written before §36 still asserted an unresolvable parent as established
           fact with the QA attestation attached -- the exact claim §33.3 recorded
           as wrong -- and none written before §42 named the equipment. The
           document and the release gate disagreed about the same lot, which is
           the divergence §33.9 already cost three separate resolvers to fix.
        2. The on-demand fallback called `_render_cert_html(rec, signers)` with
           **no `portal=`**, and without the portal the renderer cannot walk the
           parentage or the equipment at all. So the branch meant to cover a
           missing file reproduced the very defect the stored file had.

        Rendering on every serve costs a parentage walk (~0.2 ms per lot, measured
        in §41.5) and a SQLite read, and it cannot go stale. The stored file stays
        as the write-time artefact.

        NOTE: a certificate that has been SIGNED must be frozen instead, the way
        §26 freezes resolved criteria at the moment they judge. Nothing captures a
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
