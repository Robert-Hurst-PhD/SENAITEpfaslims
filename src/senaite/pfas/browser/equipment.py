# -*- coding: utf-8 -*-
"""Equipment: every piece is a core SENAITE Instrument with a core Instrument
Type (GAPS §100b; DECISIONS 2026-10-03 "UI consistency ... equipment").

    the TYPE      core InstrumentType + its requirements (annotation,
                  equipment_types.py): kind, calibration frequency, correction
                  factor, external certificate, unit, tolerance, worksheets
    the ITEM      core Instrument (title, serial, type, location, certificates)
                  + its PFAS settings (annotation): sensor id, temperature /
                  humidity range, study tolerance, balance weight points,
                  water limits
    the RECORDS   SQLite (facility_qc), keyed by the instrument's UID

This module is facility_qc's unit provider inside SENAITE, so every existing
caller (extraction guide, Data Review traceability, prepared standards, the
daily checklist, the sensor endpoint) reads instruments without changing.

Views: @@pfas-equipment (the list, with due status), @@pfas-equipment-types
(what each type obliges, plus the lab-wide facility defaults and the sensor
API key -- what the Unit Registry held), @@pfas-equipment-settings (one
instrument's PFAS settings). @@pfas-facility-units now redirects.

Core overrides (upgrade note): the worksheet add form (FolderView) and Manage
Results (ManageResultsView) offer only instruments whose type is "offered in
worksheets" -- a fridge or an eye wash is never an analysis instrument.
Python 2.7.
"""
from __future__ import absolute_import

import json
import logging

from bika.lims import api
from bika.lims.browser.worksheet.views import FolderView, ManageResultsView
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

from senaite.pfas import equipment_types as et
from senaite.pfas import facility_qc as db
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (
    TIER_CONFIG, TIER_SITE_ADMIN, GateMixin, deny_gated_action)

logger = logging.getLogger("senaite.pfas.equipment")

TYPE_KEY = "senaite.pfas.equipment_type"
ITEM_KEY = "senaite.pfas.equipment"
ITEM_FIELDS = ("sensor_id", "temp_min", "temp_max", "humidity_min", "humidity_max",
               "study_tolerance", "weight_points_json", "extra_config_json")
STATUS_LABEL = {"ok": u"OK", "due_soon": u"Due soon", "overdue": u"Overdue",
                "missing": u"No record", "not_set": u"Not set"}


def _ann_json(obj, key):
    try:
        raw = IAnnotations(obj).get(key)
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _set_ann_json(obj, key, value):
    IAnnotations(obj)[key] = json.dumps(value)


# ── the provider ────────────────────────────────────────────────────────────

def available():
    try:
        return api.get_portal() is not None
    except Exception:                                       # noqa: BLE001
        return False


def type_requirements(itype):
    """A type's requirements. A type nobody has configured keeps core's
    behaviour (offered in worksheets), so nothing disappears from a picker
    until the lab says what the type is."""
    stored = _ann_json(itype, TYPE_KEY) if itype is not None else None
    if not stored:
        req = et.seed("other")
        req["in_worksheets"] = True
        req["configured"] = False
        return req
    req = et.normalise(stored)
    req["configured"] = True
    return req


def save_type_requirements(itype, req):
    _set_ann_json(itype, TYPE_KEY, dict((k, req.get(k)) for k in et.FIELDS))


# Lookups are UNRESTRICTED, like the SQLite registry they replace: the sensor
# ingest endpoint is anonymous (it authenticates with the API key), and a
# permission-filtered search returns no instruments to it at all.
def _setup_catalog():
    return api.get_tool("senaite_catalog_setup")


def _by_uid(uid, portal_type=None):
    if not uid:
        return None
    q = {"UID": uid}
    if portal_type:
        q["portal_type"] = portal_type
    brains = _setup_catalog().unrestrictedSearchResults(**q)
    return brains[0]._unrestrictedGetObject() if brains else None


def _instrument_type(inst):
    try:
        uid = inst.getField("InstrumentType").getRaw(inst)
    except Exception:                                       # noqa: BLE001
        uid = None
    if isinstance(uid, (list, tuple)):
        uid = uid[0] if uid else None
    return _by_uid(uid, "InstrumentType")


def unit_for(inst):
    """An instrument as a facility unit dict (the shape facility_qc's callers
    already read)."""
    itype = _instrument_type(inst)
    req = type_requirements(itype)
    item = _ann_json(inst, ITEM_KEY) or {}
    loc = None
    try:
        raw = inst.getField("InstrumentLocation").getRaw(inst)
        loc = _by_uid(raw[0] if isinstance(raw, (list, tuple)) and raw else raw)
    except Exception:                                       # noqa: BLE001
        pass
    unit = {"id": api.get_uid(inst), "unit_type": req["kind"], "name": api.get_title(inst),
            "serial_number": (inst.getSerialNo() or u"").strip(),
            "location": api.get_title(loc) if loc else u"",
            "active": 1 if api.is_active(inst) else 0,
            "type_title": api.get_title(itype) if itype else u"",
            "type_uid": api.get_uid(itype) if itype else u"",
            "tolerance_pct": req.get("tolerance_pct"), "requirements": req,
            "url": api.get_url(inst)}
    for k in ITEM_FIELDS:
        unit[k] = item.get(k)
    if unit.get("study_tolerance") is None:
        unit["study_tolerance"] = db.STUDY_TOLERANCE_DEFAULT
    return unit


def _instruments(active_only=True):
    q = {"portal_type": "Instrument", "sort_on": "sortable_title"}
    if active_only:
        q["is_active"] = True
    return [b._unrestrictedGetObject() for b in _setup_catalog().unrestrictedSearchResults(**q)]


def list_units(active_only=True):
    units = [unit_for(i) for i in _instruments(active_only)]
    return sorted(units, key=lambda u: (u["unit_type"], u["name"].lower()))


def get_unit(unit_id):
    obj = _by_uid(unit_id, "Instrument")
    return unit_for(obj) if obj is not None else None


def get_unit_by_sensor(sensor_id):
    for u in list_units(True):
        if sensor_id and u.get("sensor_id") == sensor_id:
            return u
    return None


def unit_by_serial(serial):
    serial = (u"%s" % (serial or u"")).strip()
    for u in list_units(False):
        if serial and u.get("serial_number") == serial:
            return u
    return None


import sys  # noqa: E402
db.set_unit_provider(sys.modules[__name__])


def due_status(unit, inst=None):
    """equipment_types.due for one unit: its type's frequency since the last
    PFAS check, and its SENAITE certificate when the type requires one."""
    cert_to = None
    inst = inst or _by_uid(unit["id"], "Instrument")
    try:
        cert = inst.getLatestValidCertification() if inst is not None else None
        cert_to = cert.getValidTo().asdatetime().date() if cert is not None else None
    except Exception:                                       # noqa: BLE001
        cert_to = None
    return et.due(unit["requirements"], db.last_check_date(unit["id"], unit["unit_type"]),
                  cert_to)


def offered_in_worksheets(brain_or_obj):
    inst = api.get_object(brain_or_obj)
    return type_requirements(_instrument_type(inst)).get("in_worksheets", True)


# ── views ────────────────────────────────────────────────────────────────────

class PFASEquipmentView(BrowserView):
    """Every instrument, grouped by type, with what is due."""
    template = ViewPageTemplateFile("templates/equipment.pt")

    def __call__(self):
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    _RECORDS = {"balance_analytical": "pfas-balance-log", "balance_prep": "pfas-balance-log",
                "pipette": "pfas-pipette-calibration", "refrigerator": "pfas-temperature-log",
                "freezer": "pfas-temperature-log", "room_sensor": "pfas-temperature-log",
                "eyewash": "pfas-eyewash-log", "water_system": "pfas-water-log"}

    def rows(self):
        out = []
        for inst in _instruments(active_only=False):
            u = unit_for(inst)
            d = due_status(u, inst)
            page = self._RECORDS.get(u["unit_type"])
            out.append(dict(u, due=d, status_label=STATUS_LABEL.get(d["status"], d["status"]),
                            records_url=("%s/@@%s?unit_id=%s" % (self.portal_url(), page, u["id"])
                                         if page else None),
                            kind_label=dict(et.KINDS).get(u["unit_type"], u["unit_type"])))
        return sorted(out, key=lambda r: (r["type_title"].lower(), r["name"].lower()))

    def add_url(self):
        return self.portal_url() + "/bika_setup/bika_instruments/createObject?type_name=Instrument"


TYPES_GATES = {
    "save_types": TIER_CONFIG,
    "save_defaults": TIER_CONFIG,
    # The sensor secret authenticates the unauthenticated ingest endpoint.
    "save_api_key": TIER_SITE_ADMIN,
}


class PFASEquipmentTypesView(GateMixin, BrowserView):
    """What each equipment type obliges; the lab-wide facility defaults and
    the sensor API key (what the Unit Registry held)."""
    template = ViewPageTemplateFile("templates/equipment_types.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors = []
        req = self.request
        action = req.form.get("action", "")
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, action, TYPES_GATES)
            if denied is not None:
                return denied
            if action == "save_types":
                self._save_types()
                if self.errors:
                    return self.template()
            elif action == "save_defaults":
                from senaite.pfas.browser.facility_qc import save_defaults_from_form
                save_defaults_from_form(req.form, api.get_portal())
            elif action == "save_api_key":
                db.set_api_key(api.get_portal(), req.form.get("api_key", ""))
            req.response.redirect(self.portal_url() + "/@@pfas-equipment-types?saved=1")
            return ""
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def kinds(self):
        return [{"key": k, "label": l} for k, l in et.KINDS]

    def types(self):
        brains = api.search({"portal_type": "InstrumentType", "sort_on": "sortable_title"},
                            "senaite_catalog_setup")
        out = []
        for b in brains:
            t = api.get_object(b)
            out.append({"uid": api.get_uid(t), "title": api.get_title(t),
                        "req": type_requirements(t), "url": api.get_url(t)})
        return out

    def _save_types(self):
        form = self.request.form
        for t in self.types():
            uid = t["uid"]
            vals = dict((k, form.get("%s.%s" % (k, uid))) for k in et.FIELDS)
            req, errors = et.parse(vals, label=t["title"])
            if errors:
                self.errors.extend(errors)
                continue
            save_type_requirements(api.get_object_by_uid(uid), req)

    def add_type_url(self):
        # SENAITE 2.6 keeps instrument types as Dexterity items under setup/
        return self.portal_url() + "/setup/instrumenttypes/++add++InstrumentType"

    def facility_defaults(self):
        from senaite.pfas.browser.facility_qc import facility_defaults_for_form
        return facility_defaults_for_form()

    def balance_unit_types(self):
        return [{"key": k, "label": l} for k, l in et.KINDS if k in et.BALANCE_KINDS]

    def api_key(self):
        # Never rendered to anyone who may not set it (GAPS §46.7).
        if not self.can_site_admin():
            return u""
        return db.get_api_key(api.get_portal()) or u""

    def saved(self):
        return self.request.form.get("saved") == "1"


ITEM_GATES = {"save": TIER_CONFIG}


class PFASEquipmentSettingsView(GateMixin, BrowserView):
    """One instrument's PFAS settings."""
    template = ViewPageTemplateFile("templates/equipment_settings.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        self.inst = api.get_object_by_uid(req.form.get("uid", ""), default=None)
        if self.inst is None or api.get_portal_type(self.inst) != "Instrument":
            req.response.redirect(api.get_portal().absolute_url() + "/@@pfas-equipment")
            return ""
        action = req.form.get("action", "")
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, action, ITEM_GATES)
            if denied is not None:
                return denied
            if action == "save":
                self._save()
            req.response.redirect("%s/@@pfas-equipment-settings?uid=%s&saved=1"
                                  % (api.get_portal().absolute_url(), api.get_uid(self.inst)))
            return ""
        return self.template()

    def unit(self):
        return unit_for(self.inst)

    def weight_points(self):
        u = self.unit()
        try:
            pts = json.loads(u.get("weight_points_json") or "null")
        except (TypeError, ValueError):
            pts = None
        if pts:
            return pts
        return db.get_facility_defaults(api.get_portal())["balance_points"].get(u["unit_type"], [])

    def _save(self):
        f = self.request.form
        data = {}
        for k in ("sensor_id",):
            data[k] = (f.get(k) or u"").strip() or None
        for k in ("temp_min", "temp_max", "humidity_min", "humidity_max", "study_tolerance"):
            raw = (f.get(k) or u"").strip()
            try:
                data[k] = float(raw) if raw else None
            except ValueError:
                data[k] = None
        u = self.unit()
        if u["unit_type"] in et.BALANCE_KINDS:
            pts = []
            for i in range(20):
                nom, lbl = f.get("wp_nominal_%d" % i), f.get("wp_label_%d" % i)
                if nom:
                    try:
                        pts.append([float(nom), (lbl or u"").strip() or u"%s g" % nom])
                    except ValueError:
                        pass
            data["weight_points_json"] = json.dumps(pts) if pts else None
        if u["unit_type"] == "water_system":
            extra = {}
            for k in ("conductivity_max", "toc_max"):
                if (f.get(k) or u"").strip():
                    extra[k] = f.get(k).strip()
            data["extra_config_json"] = json.dumps(extra) if extra else None
        try:
            from senaite.pfas import config_history
            config_history.track(None, "equipment", u["id"], lambda: _ann_json(self.inst, ITEM_KEY),
                                 label=u"Equipment %s" % u["name"])
        except Exception:                                   # noqa: BLE001
            pass
        _set_ann_json(self.inst, ITEM_KEY, data)

    def extra(self):
        try:
            return json.loads(self.unit().get("extra_config_json") or "{}") or {}
        except (TypeError, ValueError):
            return {}

    def saved(self):
        return self.request.form.get("saved") == "1"

    def portal_url(self):
        return api.get_portal().absolute_url()


class PFASFacilityUnitsRedirect(BrowserView):
    """The Unit Registry folded into Equipment (lab, 2026-10-03)."""

    def __call__(self):
        self.request.response.redirect(api.get_portal().absolute_url() + "/@@pfas-equipment")
        return ""


# ── core worksheet pickers: analysis instruments only ───────────────────────

class PFASWorksheetFolderView(FolderView):
    def _get_instruments_brains(self):
        return [b for b in super(PFASWorksheetFolderView, self)._get_instruments_brains()
                if offered_in_worksheets(b)]


class PFASManageResultsView(ManageResultsView):
    def getInstruments(self):
        items = super(PFASManageResultsView, self).getInstruments()
        current = self.context.getInstrument()
        keep = []
        for uid, title in items.items():
            obj = api.get_object_by_uid(uid, default=None) if uid else None
            if not uid or obj is None or offered_in_worksheets(obj) or (
                    current is not None and api.get_uid(current) == uid):
                keep.append((uid, title))
        from Products.Archetypes.utils import DisplayList
        return DisplayList(keep)
