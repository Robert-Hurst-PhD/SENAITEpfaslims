# -*- coding: utf-8 -*-
"""Equipment: every piece is a core SENAITE Instrument with a core Instrument
Type ("UI consistency ... equipment").

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
instrument's PFAS settings).

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
from senaite.pfas.browser.view_helpers import ViewHelpers
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
               "study_tolerance", "weight_points_json", "extra_config_json",
               # a pipette's calibration limits: accuracy +/- %, precision CV %
               "pipette_accuracy_pct", "pipette_precision_cv",
               # the method profiles whose samples a monitored unit stores
               # (their storage range joins its own on the Monitoring page)
               "profiles_json",
               # per method, the matrices it holds them for (none listed: all)
               "held_matrices_json",
               # a multi-point thermometer's working temperatures (temp_calibration)
               "working_temps_json",
               # an SPE manifold's ports, offered where an extraction records them
               "spe_ports_json",
               # an analytical instrument's raw data folder (raw_share.py)
               "raw_folder")
STATUS_LABEL = {"ok": u"OK", "due_soon": u"Due soon", "overdue": u"Overdue",
                "missing": u"No record", "not_set": u"Not set"}
STATUS_CLS = {"ok": "badge-active", "due_soon": "badge-quarantine", "overdue": "badge-expired",
              "missing": "badge-expired"}
# a unit's state on the Daily Checklist, as that page words it
DAILY_LABEL = {"ok": u"OK today", "pending": u"Due today", "due": u"Due", "overdue": u"Overdue",
               "out_of_range": u"Out of range", "no_data": u"No record"}
DAILY_CLS = {"ok": "badge-active", "pending": "badge-quarantine", "due": "badge-quarantine",
             "overdue": "badge-expired", "out_of_range": "badge-expired", "no_data": "badge-expired"}


def status_of(due, daily):
    """(label, badge class) of a unit's Status: what its type owes; a unit
    that owes nothing by date but is checked daily reads as the Daily
    Checklist reads it, so the two pages agree."""
    if due == "not_set" and daily:
        return DAILY_LABEL.get(daily, daily), DAILY_CLS.get(daily, "badge-archived")
    return STATUS_LABEL.get(due, due), STATUS_CLS.get(due, "badge-archived")


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
        req["configured"] = False
        return req
    req = et.normalise(stored)
    req["configured"] = True
    return req


def save_type_requirements(itype, req):
    """Store a type's requirements; the change is recorded in the
    configuration change history (@@pfas-config-history)."""
    try:
        from senaite.pfas import config_history
        config_history.track(None, "equipment_type", api.get_uid(itype),
                             lambda: _ann_json(itype, TYPE_KEY),
                             label=u"Equipment type %s" % api.safe_unicode(api.get_title(itype)))
    except Exception:                                       # noqa: BLE001
        logger.warning("equipment type change not tracked", exc_info=True)
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
    # text as unicode: core returns titles as UTF-8 bytes, and a name with a
    # non-ASCII character (a subscript two, a degree sign) breaks every
    # u"..." % name that shows it
    text = api.safe_unicode
    unit = {"id": api.get_uid(inst), "unit_type": req["kind"], "name": text(api.get_title(inst)),
            "serial_number": text(inst.getSerialNo() or u"").strip(),
            "location": text(api.get_title(loc)) if loc else u"",
            "active": 1 if api.is_active(inst) else 0,
            "type_title": text(api.get_title(itype)) if itype else u"",
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


def release_matrices(method_id, matrices):
    """Take removed matrices off every unit that names them among what it
    holds for the method (matrix_temperature.release), each change recorded
    in the configuration history. Returns the units' names."""
    from senaite.pfas import config_history
    from senaite.pfas import matrix_temperature as mt
    names = []
    for inst in _instruments(active_only=False):
        item = _ann_json(inst, ITEM_KEY) or {}
        new, changed = mt.release(item, method_id, matrices)
        if not changed:
            continue
        name = api.safe_unicode(api.get_title(inst))
        config_history.track(None, "equipment", api.get_uid(inst), lambda inst=inst: _ann_json(inst, ITEM_KEY),
                             label=u"Equipment %s" % name,
                             action=u"%s removed from %s" % (u", ".join(matrices), method_id))
        _set_ann_json(inst, ITEM_KEY, new)
        names.append(name)
    return names


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


def _cert_dates(cert):
    try:
        vf, vt = cert.getValidFrom(), cert.getValidTo()
        return (vf.asdatetime().date() if vf else None, vt.asdatetime().date() if vt else None)
    except Exception:                                       # noqa: BLE001
        return None, None


def certificate_covering(inst, on_date):
    """(valid_from, valid_to) of the instrument's SENAITE certificate in force
    on `on_date` (a date or 'YYYY-MM-DD'), or None."""
    import datetime
    if not isinstance(on_date, datetime.date):
        try:
            on_date = datetime.datetime.strptime((on_date or u"")[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    try:
        certs = inst.getCertifications() or []
    except Exception:                                       # noqa: BLE001
        certs = []
    for c in certs:
        vf, vt = _cert_dates(c)
        if vf and vt and vf <= on_date <= vt:
            return vf, vt
    return None


def reference_thermometers():
    """Registered reference thermometers (kind reference_thermometer)."""
    return [u for u in list_units(True) if u["unit_type"] == et.REFERENCE_KIND]


def reference_check(reference_uid, on_date):
    """Whether a study's reference thermometer was externally verified on the
    study date: {"name", "serial", "valid_to", "ok", "why"} or None
    when the study names no registered reference."""
    inst = _by_uid(reference_uid, "Instrument") if reference_uid else None
    if inst is None:
        return None
    u = unit_for(inst)
    cov = certificate_covering(inst, on_date)
    return {"name": u["name"], "serial": u["serial_number"],
            "valid_to": cov[1].isoformat() if cov else None, "ok": bool(cov),
            "why": u"" if cov else u"no external certificate in force on %s" % (on_date or u"?")[:10]}


def offered_in_worksheets(brain_or_obj):
    """Runs samples: its type's kind is Analytical instrument. A type nobody
    has set up keeps core's behaviour (offered), so nothing leaves a picker
    until the lab says what the type is."""
    inst = api.get_object(brain_or_obj)
    req = type_requirements(_instrument_type(inst))
    return et.runs_samples(req) or not req.get("configured")


# ── views ────────────────────────────────────────────────────────────────────

class PFASEquipmentView(ViewHelpers, BrowserView):
    """Every instrument, grouped by type, with what is due."""
    template = ViewPageTemplateFile("templates/equipment.pt")

    def __call__(self):
        return self.template()

    _RECORDS = {"balance_analytical": "pfas-balance-log", "balance_prep": "pfas-balance-log",
                "pipette": "pfas-pipette-calibration", "refrigerator": "pfas-temperature-log",
                "freezer": "pfas-temperature-log", "room_sensor": "pfas-temperature-log",
                "water_bath": "pfas-temperature-log", "saa": "pfas-waste-log",
                "thermometer": "pfas-temperature-log", "ir_gun": "pfas-temperature-log",
                "nitrogen_evaporator": "pfas-temperature-log",
                "eyewash": "pfas-eyewash-log", "water_system": "pfas-water-log"}

    def _daily(self):
        """{unit id: its Daily Checklist status} for the units checked daily,
        read as the Daily Checklist reads them; {} when it cannot be read."""
        try:
            return dict((r["id"], r.get("status")) for r in db.dashboard_summary())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("equipment: the daily checklist could not be read: %s", exc)
            return {}

    def rows(self):
        out = []
        daily = self._daily()
        for inst in _instruments(active_only=False):
            u = unit_for(inst)
            d = due_status(u, inst)
            page = self._RECORDS.get(u["unit_type"])
            day = daily.get(u["id"])
            label, cls = status_of(d["status"], day)
            out.append(dict(u, due=d, status_label=label, status_cls=cls,
                            daily=day, daily_label=DAILY_LABEL.get(day, day) if day else u"",
                            records_url=("%s/@@%s?unit_id=%s" % (self.portal_url(), page, u["id"])
                                         if page else None),
                            kind_label=dict(et.KINDS).get(u["unit_type"], u["unit_type"])))
        return sorted(out, key=lambda r: (r["type_title"].lower(), r["name"].lower()))

    def types_url(self):
        """Where a type's check frequency is set."""
        return self.portal_url() + "/@@pfas-equipment-types"

    def checklist_url(self):
        return self.portal_url() + "/@@pfas-facility-qc"

    def add_url(self):
        return self.portal_url() + "/bika_setup/bika_instruments/createObject?type_name=Instrument"


TYPES_GATES = {
    "save_types": TIER_CONFIG,
    "save_defaults": TIER_CONFIG,
    # The sensor secret authenticates the unauthenticated ingest endpoint.
    "save_api_key": TIER_SITE_ADMIN,
}


class PFASEquipmentTypesView(ViewHelpers, GateMixin, BrowserView):
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

    def kinds(self):
        return [{"key": k, "label": l} for k, l in et.KINDS]

    def types(self):
        brains = api.search({"portal_type": "InstrumentType", "sort_on": "sortable_title"},
                            "senaite_catalog_setup")
        out = []
        for b in brains:
            t = api.get_object(b)
            out.append({"uid": api.get_uid(t), "title": api.safe_unicode(api.get_title(t)),
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

    def correction_models(self):
        return et.CORRECTION_MODELS

    def add_type_url(self):
        # SENAITE 2.6 keeps instrument types as Dexterity items under setup/
        return self.portal_url() + "/setup/instrumenttypes/++add++InstrumentType"

    def facility_defaults(self):
        from senaite.pfas.browser.facility_qc import facility_defaults_for_form
        return facility_defaults_for_form()

    def unit_choices(self, current):
        """Equipment Types' unit picker, grouped by quantity."""
        from senaite.pfas.equipment_types import unit_choices
        return unit_choices(current)

    def conductivity_units(self):
        return list(db.CONDUCTIVITY_UNITS)

    def balance_unit_types(self):
        return [{"key": k, "label": l} for k, l in et.KINDS if k in et.BALANCE_KINDS]

    def api_key(self):
        # Never rendered to anyone who may not set it.
        if not self.can_site_admin():
            return u""
        return db.get_api_key(api.get_portal()) or u""

    def saved(self):
        return self.request.form.get("saved") == "1"


ITEM_GATES = {"save": TIER_CONFIG}


class PFASEquipmentSettingsView(ViewHelpers, GateMixin, BrowserView):
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
            flag = "saved=1"
            if action == "save":
                if self._save() is False:
                    flag = "error=raw_folder"
            req.response.redirect("%s/@@pfas-equipment-settings?uid=%s&%s"
                                  % (api.get_portal().absolute_url(), api.get_uid(self.inst), flag))
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
        """False when the raw data folder is refused: nothing is saved."""
        f = self.request.form
        data = {}
        for k in ("sensor_id",):
            data[k] = (f.get(k) or u"").strip() or None
        for k in ("temp_min", "temp_max", "humidity_min", "humidity_max", "study_tolerance",
                  "pipette_accuracy_pct", "pipette_precision_cv"):
            raw = (f.get(k) or u"").strip()
            try:
                data[k] = float(raw) if raw else None
            except ValueError:
                data[k] = None
        u = self.unit()
        if u["unit_type"] in et.MONITORED_KINDS:
            # what it holds per method: "MID" its samples, "MID:processed", "MID:extract"
            mids = [m for m in self.method_ids() if f.get("profile.%s" % m)]
            mids += ["%s:%s" % (m, k) for m in self.method_ids() for k in ("processed", "extract")
                     if f.get("profile.%s:%s" % (m, k))]
            data["profiles_json"] = json.dumps(mids) if mids else None
            # the matrices held, per method: every one ticked (or none) is all
            held = {}
            from senaite.pfas import matrix_temperature as mt
            for m in self.method_ids():
                every = self._matrices(m)
                chosen = mt.held_from_ticks(every, [x for i, x in enumerate(every) if f.get("held.%s.%d" % (m, i))])
                if chosen:
                    held[m] = chosen
            data["held_matrices_json"] = json.dumps(held, sort_keys=True) if held else None
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
        # a multi-point unit's working temperatures (kept when not on the form)
        if "working_temps" in f:
            temps = sorted(set(et.working_temps(f.get("working_temps"))))
            data["working_temps_json"] = json.dumps(temps) if temps else None
        else:
            data["working_temps_json"] = u.get("working_temps_json")
        # an SPE manifold's ports (kept when not on the form)
        if "spe_ports" in f:
            ports = et.spe_ports(f.get("spe_ports") or u"")
            data["spe_ports_json"] = json.dumps(ports) if ports else None
        else:
            data["spe_ports_json"] = u.get("spe_ports_json")
        # an analytical instrument's raw data folder (kept when not on the form)
        if u["unit_type"] == "analytical" and "raw_folder" in f:
            from senaite.pfas import raw_share
            folder = (f.get("raw_folder") or u"").strip()
            if raw_share.folder_error(folder):
                return False
            data["raw_folder"] = folder or None
        else:
            data["raw_folder"] = u.get("raw_folder")
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
        if u["unit_type"] == "analytical":
            from senaite.pfas import raw_share
            raw_share.export_again(api.get_portal())
        return True

    def multi_point(self):
        """The unit is calibrated over its working temperatures (its type's
        correction option)."""
        u = self.unit()
        return bool(u) and db._requires_correction(u) and db._model(u) == db.tc.MULTI

    def spe_ports_text(self):
        return u", ".join(et.spe_ports(self.unit().get("spe_ports_json")))

    def working_temps_text(self):
        return u", ".join(u"%g" % t for t in db.unit_working_temps(self.unit()))

    def method_ids(self):
        from senaite.pfas.method_profile_store import list_method_ids
        return list_method_ids(api.get_portal())

    def _judgement(self):
        """What the unit is judged against: the narrowest of its own range
        and each held matrix's storage range (matrix_temperature)."""
        from senaite.pfas import matrix_temperature as mt
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas import homogenisation as hg
        portal = api.get_portal()
        return mt.unit_judgement(self.unit() or {}, lambda mid: raw_profile(portal, mid), hg.homogenised_titles())

    def hold_conflict(self):
        """Why what the unit holds cannot all be kept at once (ranges that do
        not overlap), or u"" (matrix_temperature.conflict)."""
        got = self._judgement()
        if not got["conflict"]:
            return u""
        return u"These ranges do not overlap: %s. No temperature meets them all." % got["clash"]

    def hold_range(self):
        """The range the unit is judged against and how it was reached
        ("-20 to -10 \u00b0C, narrowest of Tissue, Solid"), or u"" when
        nothing sets one or the ranges clash."""
        got = self._judgement()
        if got["conflict"] or (got["lo"] is None and got["hi"] is None):
            return u""
        span = u"%s to %s \u00b0C" % (u"%g" % got["lo"] if got["lo"] is not None else u"?",
                                       u"%g" % got["hi"] if got["hi"] is not None else u"?")
        return u"Judged at %s%s" % (span, (u", " + got["why"][0].lower() + got["why"][1:]) if got["why"] else u"")

    def _matrices(self, mid):
        from senaite.pfas.method_profile_store import raw_profile
        return list(raw_profile(api.get_portal(), mid).get("supported_matrices") or [])

    def kept_choices(self):
        """Per method, a switch for each kept item the unit may hold, and one
        for each matrix it holds them for (all on while none is chosen)."""
        from senaite.pfas import matrix_temperature as mt
        mine = set(self.stored_profiles())
        held = mt.held_of(self.unit() or {})
        out = []
        for m in self.method_ids():
            items = []
            for key, label in (("", u"Samples"), (":processed", u"Processed samples"), (":extract", u"Extracts")):
                entry = m + key
                items.append({"name": "profile.%s" % entry, "label": label, "on": entry in mine})
            matrices = [{"name": "held.%s.%d" % (m, i), "label": x, "on": on}
                        for i, (x, on) in enumerate(mt.held_switches(self._matrices(m), held.get(m)))]
            out.append({"mid": m, "items": items, "matrices": matrices})
        return out

    def stored_profiles(self):
        try:
            return json.loads(self.unit().get("profiles_json") or "[]") or []
        except (TypeError, ValueError):
            return []

    def extra(self):
        try:
            return json.loads(self.unit().get("extra_config_json") or "{}") or {}
        except (TypeError, ValueError):
            return {}

    def saved(self):
        return self.request.form.get("saved") == "1"

    def folder_refused(self):
        return self.request.form.get("error") == "raw_folder"

class PFASReferenceThermometersView(ViewHelpers, BrowserView):
    """Equipment Checks > Reference Thermometers: the registered references
    (core Instruments of kind reference_thermometer) and the external
    certificate each is calibrated under (its SENAITE certifications). A
    temperature study picks one of these; nothing is typed."""
    template = ViewPageTemplateFile("templates/reference_thermometers.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def add_url(self):
        return self.portal_url() + "/bika_setup/bika_instruments/createObject?type_name=Instrument"

    def rows(self):
        from senaite.pfas import lab_time
        today = lab_time.today()
        out = []
        for u in reference_thermometers():
            inst = _by_uid(u["id"], "Instrument")
            cert, vf, vt = None, None, None
            try:
                cert = inst.getLatestValidCertification() if inst is not None else None
            except Exception:                               # noqa: BLE001
                cert = None
            if cert is not None:
                vf, vt = _cert_dates(cert)
            if cert is None:
                status, cls = u"No certificate", "badge-fail"
            elif vt and vt < today:
                status, cls = u"Expired", "badge-fail"
            else:
                status, cls = u"Traceable", "badge-ok"
            out.append({"name": u["name"], "serial": u["serial_number"] or u"",
                        "model": getattr(inst, "getModel", lambda: u"")() if inst is not None else u"",
                        "lab": (getattr(cert, "getAgency", lambda: u"")() or u"") if cert is not None else u"",
                        "certificate": (cert.Title() or u"") if cert is not None else u"",
                        "calibrated": vf.isoformat() if vf else u"", "due": vt.isoformat() if vt else u"",
                        "status": status, "status_cls": cls, "url": u.get("url") or u""})
        return out


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
