# -*- coding: utf-8 -*-
"""Browser views for Facility QC (ISO 17025 daily verifications)."""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
from datetime import date

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import facility_qc as db
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (
    TIER_CONFIG, TIER_SITE_ADMIN, GateMixin, deny_gated_action)

logger = logging.getLogger("senaite.pfas.browser.facility_qc")


def _safe_json(obj):
    s = json.dumps(obj, ensure_ascii=True)
    return s.replace("&", r"&").replace("<", r"<").replace(">", r">")


def _portal(context):
    return getToolByName(context, "portal_url").getPortalObject()


def _facility_defaults():
    """Lab-wide facility defaults — saved values over the seed.

    Module level, because eight views need it and none of them owns it. Falls
    back to the seed when there is no portal (headless callers).
    """
    try:
        from bika.lims import api
        return db.get_facility_defaults(api.get_portal())
    except Exception:                                       # noqa: BLE001
        return db.get_facility_defaults(None)


class PFASFacilityDashboardView(BrowserView):
    """Daily checklist — one status row per unit."""
    _template = ViewPageTemplateFile("templates/facility_dashboard.pt")

    def __call__(self):
        flatten_form(self.request)
        return self._template()

    def summary(self):
        return db.dashboard_summary()

    def unit_type_label(self, ut):
        return dict(db.UNIT_TYPES).get(ut, ut)

    def status_label(self, s):
        return {
            "ok": "OK",
            "out_of_range": "Out of Range",
            "overdue": "Overdue",
            "pending": "Pending",
            "no_data": "No Data",
        }.get(s, s)

    def status_class(self, s):
        return {
            "ok": "fqc-ok",
            "out_of_range": "fqc-fail",
            "overdue": "fqc-warn",
            "pending": "fqc-pending",
            "no_data": "fqc-pending",
        }.get(s, "")

    def unit_icon(self, ut):
        return {
            "refrigerator":       "fas fa-temperature-low",
            "freezer":            "fas fa-snowflake",
            "balance_analytical": "fas fa-balance-scale",
            "balance_prep":       "fas fa-balance-scale-right",
            "eyewash":            "fas fa-eye",
            "water_system":       "fas fa-tint",
            "room_sensor":        "fas fa-thermometer-half",
        }.get(ut, "fas fa-circle")

    def portal_url(self):
        return _portal(self.context).absolute_url()


# Which POST actions are lab configuration (GAPS §46). The daily bench logs in
# this module -- temperature, balance, water, waste, eyewash, pipette
# calibration -- are deliberately absent: any lab user records them.
UNITS_GATES = {
    "save": TIER_CONFIG,
    "delete": TIER_CONFIG,
    "save_defaults": TIER_CONFIG,
    # The sensor secret authenticates the unauthenticated ingest endpoint.
    "save_api_key": TIER_SITE_ADMIN,
}

WEIGHT_SET_GATES = {
    "save": TIER_CONFIG,
    "delete": TIER_CONFIG,
}


class PFASFacilityUnitsView(GateMixin, BrowserView):
    """Unit registry — CRUD for lab manager."""
    _template = ViewPageTemplateFile("templates/facility_units.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        action = req.form.get("action", "")
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, action, UNITS_GATES)
            if denied is not None:
                return denied
            if action == "save":
                self._save()
            elif action == "delete":
                db.delete_unit(req.form.get("unit_id", ""))
            elif action == "save_defaults":
                self._save_defaults()
            elif action == "save_api_key":
                db.set_api_key(_portal(self.context), req.form.get("api_key", ""))
            self.request.response.redirect(
                _portal(self.context).absolute_url() + "/@@pfas-facility-units"
            )
            return ""
        return self._template()

    def _save(self):
        f = self.request.form
        uid = f.get("unit_id") or None
        unit_type = f.get("unit_type", "")
        weight_points = None
        if unit_type in _facility_defaults()["balance_points"]:
            # Rebuild weight points from posted form fields
            pts = []
            defaults = _facility_defaults()["balance_points"][unit_type]
            for i, d in enumerate(defaults):
                nom = f.get("wp_nominal_{}".format(i))
                lbl = f.get("wp_label_{}".format(i))
                tol = f.get("wp_tolerance_{}".format(i))
                if nom:
                    pts.append([
                        float(nom),
                        lbl or d[1],
                        float(tol) if tol else d[2],
                    ])
            if pts:
                weight_points = json.dumps(pts)
        extra = {}
        if unit_type == "water_system":
            d = _facility_defaults()
            extra["conductivity_max"] = f.get(
                "conductivity_max", str(d["water_conductivity_max"]))
            extra["toc_max"] = f.get("toc_max", str(d["water_toc_max"]))
        if unit_type in ("eyewash",):
            extra["temp_min"] = f.get("temp_min", "15")
            extra["temp_max"] = f.get("temp_max", "25")
        data = {
            "id": uid,
            "unit_type": unit_type,
            "name": f.get("name", ""),
            "location": f.get("location", ""),
            "serial_number": f.get("serial_number", ""),
            "sensor_id": f.get("sensor_id", "") or None,
            "temp_min": f.get("temp_min") or None,
            "temp_max": f.get("temp_max") or None,
            "humidity_min": f.get("humidity_min") or None,
            "humidity_max": f.get("humidity_max") or None,
            # The lab-wide default, not a literal: the Unit Registry collects
            # `study_tolerance` in its Defaults panel and every consumer used to
            # hardcode 1.0, so that field was inert too.
            "study_tolerance": (f.get("study_tolerance")
                                or _facility_defaults().get("study_tolerance")),
            "weight_points_json": weight_points,
            "extra_config_json": json.dumps(extra) if extra else None,
            "active": True,
        }
        db.save_unit(data)

    def units(self):
        return db.list_units(active_only=False)

    def unit_types(self):
        return db.UNIT_TYPES

    def balance_defaults_json(self):
        return _safe_json(_facility_defaults()["balance_points"])

    def api_key(self):
        # Never rendered to anyone who may not set it (GAPS §46.7).
        if not self.can_site_admin():
            return ""
        return db.get_api_key(_portal(self.context))

    def portal_url(self):
        return _portal(self.context).absolute_url()

    # ── Lab-wide defaults ────────────────────────────────────────────────────

    def facility_defaults(self):
        """Current lab-wide defaults, with weight points as editable text."""
        d = dict(_facility_defaults())
        d["balance_points_text"] = dict(
            (k, _points_to_text(v)) for k, v in
            (d.get("balance_points") or {}).items())
        return d

    def balance_unit_types(self):
        # Dicts, not tuples: TAL's string: expression takes a simple path, so
        # ${bt/key} works where ${python:bt[0]} does not.
        return [{"key": k, "label": label} for k, label in db.UNIT_TYPES
                if k.startswith("balance_")]

    def _save_defaults(self):
        f = self.request.form
        points = {}
        for bt in self.balance_unit_types():
            key = bt["key"]
            parsed = _points_from_text(f.get("bal_points.%s" % key, u""))
            if parsed:
                points[key] = parsed
        data = {"balance_points": points}
        for field in ("eyewash_temp_min", "eyewash_temp_max",
                      "water_conductivity_max", "water_toc_max",
                      "study_tolerance", "balance_tolerance"):
            raw = (f.get(field) or "").strip()
            if raw:
                try:
                    data[field] = float(raw)
                except ValueError:
                    logger.warning("facility defaults: %s=%r not a number, "
                                   "left unchanged", field, raw)
        db.save_facility_defaults(_portal(self.context), data)





def _points_to_text(points):
    """Weight points as editable text: one per line, `nominal, label, tol`."""
    return u"\n".join(
        u"{0}, {1}, {2}".format(p[0], p[1], p[2]) for p in (points or []))


def _points_from_text(text):
    """Parse the editable form back. A malformed line is skipped rather than
    silently zeroing a tolerance, which would make every weighing pass."""
    out = []
    for line in (text or u"").splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 3 or not parts[0]:
            continue
        try:
            out.append([float(parts[0]), parts[1], float(parts[2])])
        except ValueError:
            logger.warning("facility defaults: skipping unparseable weight "
                           "point %r", line)
    return out

class PFASTemperatureLogView(BrowserView):
    """Time-series chart for a single temp/humidity unit."""
    _template = ViewPageTemplateFile("templates/facility_temp_log.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST" and req.form.get("action") == "add_study":
            self._create_study()
            self.request.response.redirect(self.request.URL)
            return ""
        if req.method == "POST" and req.form.get("action") == "save_point":
            self._save_point()
            self.request.response.redirect(self.request.URL)
            return ""
        return self._template()

    def _create_study(self):
        f = self.request.form
        uid = f.get("unit_id", "")
        unit = db.get_unit(uid)
        if not unit:
            return
        db.create_study(
            unit_id=uid,
            operator=f.get("operator", ""),
            nist_serial=f.get("nist_serial", ""),
            nist_cert_date=f.get("nist_cert_date") or None,
            study_date=f.get("study_date") or None,
            tolerance=float(f.get("tolerance") or unit.get("study_tolerance")
                            or _facility_defaults().get("study_tolerance")),
            notes=f.get("notes") or None,
        )

    def _save_point(self):
        f = self.request.form
        study_id = int(f.get("study_id", 0))
        time_point = int(f.get("time_point", 0))
        sr = f.get("sensor_reading")
        nr = f.get("nist_reading")
        ra = f.get("recorded_at") or None
        db.save_study_point(
            study_id=study_id,
            time_point=time_point,
            sensor_reading=float(sr) if sr else None,
            nist_reading=float(nr) if nr else None,
            recorded_at=ra,
        )

    def unit(self):
        uid = self.request.form.get("unit_id", "")
        return db.get_unit(uid) if uid else None

    def days(self):
        try:
            return int(self.request.form.get("days", 7))
        except (TypeError, ValueError):
            return 7

    def readings_json(self):
        unit = self.unit()
        if not unit:
            return _safe_json([])
        readings = db.get_temperature_readings(unit["id"], days=self.days())
        return _safe_json(readings)

    def unit_json(self):
        return _safe_json(self.unit() or {})

    def studies(self):
        unit = self.unit()
        if not unit:
            return []
        return db.list_studies(unit["id"])

    def study_detail(self):
        sid = self.request.form.get("study_id")
        if not sid:
            return None
        try:
            return db.get_study(int(sid))
        except (TypeError, ValueError):
            return None

    def units_for_nav(self):
        return [u for u in db.list_units()
                if u["unit_type"] in ("refrigerator", "freezer", "room_sensor", "eyewash")]

    def portal_url(self):
        return _portal(self.context).absolute_url()


def _weight_set_label(weight_set_id):
    """The set's human identifier, for a reader of the log.

    A verification is signed off by someone who knows the set as `WS-001`, not by
    its internal row id. The pipette history first rendered
    `(c["weight_set_id"] or "")[:8]` -- a truncated uuid, which identifies the set
    to nobody and cannot be told apart from a different set sharing a prefix. One
    helper so the balance log and the pipette log cannot drift.
    """
    if not weight_set_id:
        return u""
    ws = db.get_weight_set(weight_set_id)
    if ws is None:
        # Not blanked: a record pointing at a set that no longer exists is
        # precisely the traceability break the release gate reports, so the log
        # has to say so rather than look empty.
        return u"unknown set %s" % weight_set_id
    label = ws.get("set_id") or weight_set_id
    cls = ws.get("weight_class") or u""
    return u"%s (%s)" % (label, cls) if cls else label


class PFASBalanceLogView(BrowserView):
    """Balance verification entry and history."""
    _template = ViewPageTemplateFile("templates/facility_balance.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            self._save()
            self.request.response.redirect(
                _portal(self.context).absolute_url()
                + "/@@pfas-balance-log?unit_id="
                + self.request.form.get("unit_id", "")
            )
            return ""
        return self._template()

    def _save(self):
        f = self.request.form
        unit_id = f.get("unit_id", "")
        unit = db.get_unit(unit_id)
        if not unit:
            return
        weight_points = self._weight_points(unit)
        points = []
        for i, wp in enumerate(weight_points):
            actual = f.get("actual_{}".format(i))
            points.append({
                "nominal_g": wp[0],
                "label": wp[1],
                "actual_g": float(actual) if actual else None,
                "tolerance_g": wp[2],
            })
        db.save_balance_verification(
            unit_id=unit_id,
            operator=f.get("operator", ""),
            verified_date=f.get("verified_date", ""),
            points=points,
            notes=f.get("notes") or None,
            # `or None` deliberately: an empty string is not NULL, so a traceless
            # row would be counted as traced by any `weight_set_id IS NOT NULL`
            # query. Same idiom as the pipette handler.
            weight_set_id=(f.get("weight_set_id", "").strip() or None),
            # So the lab-wide balance_tolerance actually reaches the verdict.
            portal=_portal(self.context),
        )

    def unit(self):
        uid = self.request.form.get("unit_id", "")
        return db.get_unit(uid) if uid else None

    def balance_units(self):
        return [u for u in db.list_units()
                if u["unit_type"] in ("balance_analytical", "balance_prep")]

    def weight_sets(self):
        return db.list_weight_sets()

    def weight_points(self):
        unit = self.unit()
        if not unit:
            return []
        return self._weight_points(unit)

    def _weight_points(self, unit):
        wp_json = unit.get("weight_points_json")
        if wp_json:
            try:
                return json.loads(wp_json)
            except (ValueError, TypeError):
                pass
        return _facility_defaults()["balance_points"].get(
            unit["unit_type"], [])

    def history(self):
        unit = self.unit()
        if not unit:
            return []
        rows = db.list_balance_verifications(unit["id"])
        for r in rows:
            r["weight_set_label"] = _weight_set_label(r.get("weight_set_id"))
        return rows

    def portal_url(self):
        return _portal(self.context).absolute_url()


class PFASWaterLogView(BrowserView):
    """Type 1 water QC log."""
    _template = ViewPageTemplateFile("templates/facility_water.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            f = self.request.form
            db.save_water_qc(
                operator=f.get("operator", ""),
                conductivity=_ff(f.get("conductivity")),
                toc=_ff(f.get("toc")),
                log_date=f.get("log_date") or None,
                log_time=f.get("log_time") or None,
                conductivity_max=_ff(f.get("conductivity_max")),
                toc_max=_ff(f.get("toc_max")),
                notes=f.get("notes") or None,
            )
            self.request.response.redirect(
                _portal(self.context).absolute_url() + "/@@pfas-water-log"
            )
            return ""
        return self._template()

    def logs(self):
        return db.list_water_qc(limit=60)

    def defaults(self):
        d = _facility_defaults()
        return {"conductivity_max": d["water_conductivity_max"],
                "toc_max": d["water_toc_max"]}

    def portal_url(self):
        return _portal(self.context).absolute_url()


class PFASWasteLogView(BrowserView):
    """SAA waste container log."""
    _template = ViewPageTemplateFile("templates/facility_waste.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            f = self.request.form
            db.save_waste_log(
                unit_id=f.get("unit_id", ""),
                operator=f.get("operator", ""),
                condition=f.get("condition", "acceptable"),
                log_date=f.get("log_date") or None,
                log_time=f.get("log_time") or None,
                notes=f.get("notes") or None,
            )
            self.request.response.redirect(
                _portal(self.context).absolute_url() + "/@@pfas-waste-log"
            )
            return ""
        return self._template()

    def waste_units(self):
        return [u for u in db.list_units() if "waste" in u.get("name", "").lower()
                or u.get("unit_type") == "waste"]

    def logs(self):
        return db.list_waste_logs(limit=60)

    def portal_url(self):
        return _portal(self.context).absolute_url()


class PFASEyeWashLogView(BrowserView):
    """Eye wash station verification log."""
    _template = ViewPageTemplateFile("templates/facility_eyewash.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            f = self.request.form
            unit_id = f.get("unit_id", "")
            unit = db.get_unit(unit_id) if unit_id else None
            extra = {}
            if unit and unit.get("extra_config_json"):
                try:
                    extra = json.loads(unit["extra_config_json"])
                except (ValueError, TypeError):
                    pass
            db.save_eyewash_log(
                unit_id=unit_id,
                operator=f.get("operator", ""),
                working=f.get("working") == "yes",
                temperature=_ff(f.get("temperature")),
                log_date=f.get("log_date") or None,
                log_time=f.get("log_time") or None,
                temp_min=(_ff(extra.get("temp_min"))
                          or _facility_defaults()["eyewash_temp_min"]),
                temp_max=(_ff(extra.get("temp_max"))
                          or _facility_defaults()["eyewash_temp_max"]),
                notes=f.get("notes") or None,
            )
            self.request.response.redirect(
                _portal(self.context).absolute_url() + "/@@pfas-eyewash-log"
            )
            return ""
        return self._template()

    def eyewash_units(self):
        return [u for u in db.list_units() if u["unit_type"] == "eyewash"]

    def logs(self):
        return db.list_eyewash_logs(limit=60)

    def portal_url(self):
        return _portal(self.context).absolute_url()


class PFASWeightSetsView(GateMixin, BrowserView):
    """Reference weight sets and their EXTERNAL metrology-lab calibration.

    This is where the equipment chain leaves the laboratory (GAPS §38). A balance
    verification is only as good as the weights it was performed with, and those
    are calibrated by an accredited metrology laboratory — the equipment analogue
    of a reagent's manufacturer certificate of analysis. Without a certificate
    recorded here, every balance verification performed with the set traces to
    nothing, and the traceability gate says so.
    """
    _template = ViewPageTemplateFile("templates/facility_weight_sets.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            action = self.request.form.get("action", "")
            denied = deny_gated_action(
                self.context, self.request, action, WEIGHT_SET_GATES)
            if denied is not None:
                return denied
            if action == "save":
                self._save()
            elif action == "delete":
                self._delete()
            self.request.response.redirect(
                _portal(self.context).absolute_url() + "/@@pfas-weight-sets")
            return ""
        return self._template()

    def _save(self):
        f = self.request.form
        db.save_weight_set({
            "id":                    f.get("id") or None,
            "set_id":                f.get("set_id", "").strip(),
            "description":           f.get("description", "").strip(),
            "weight_class":          f.get("weight_class", "").strip(),
            "serial_number":         f.get("serial_number", "").strip(),
            "cal_lab":               f.get("cal_lab", "").strip(),
            "cal_lab_accreditation": f.get("cal_lab_accreditation", "").strip(),
            "cal_cert_number":       f.get("cal_cert_number", "").strip(),
            "cal_date":              f.get("cal_date", "").strip(),
            "cal_due_date":          f.get("cal_due_date", "").strip(),
            "nist_traceable":        1 if f.get("nist_traceable") else 0,
            "active":                1 if f.get("active", "1") else 0,
            "notes":                 f.get("notes", "").strip(),
        })

    def _delete(self):
        wid = self.request.form.get("id", "")
        if wid:
            db.save_weight_set(dict(db.get_weight_set(wid) or {},
                                    id=wid, active=0))

    def weight_sets(self):
        """Every set, with the problems the gate would raise, so the QAO sees
        here exactly what would block a release rather than discovering it at
        review."""
        out = []
        for ws in db.list_weight_sets(active_only=False):
            probs = []
            if not ws.get("cal_cert_number") or not ws.get("cal_lab"):
                probs.append(u"no external calibration certificate recorded")
            if not ws.get("nist_traceable"):
                probs.append(u"not recorded as NIST-traceable")
            due = ws.get("cal_due_date") or ""
            if due and due < self.today():
                probs.append(u"calibration expired %s" % due)
            elif not due:
                probs.append(u"no calibration due date recorded")
            ws["problems"] = probs
            out.append(ws)
        return out

    def today(self):
        return date.today().strftime("%Y-%m-%d")

    def portal_url(self):
        return _portal(self.context).absolute_url()


class PFASPipetteCalibrationView(BrowserView):
    """Pipette calibration — quarterly in house, or external.

    An INTERNAL check is a measurement this laboratory made, so it carries its own
    provenance: the balance and the reference weight set used, which run on to the
    metrology lab. An EXTERNAL one carries the provider, its accreditation and the
    certificate number. Both record a due date, because the gate judges
    calibration as of the date the pipette was USED, not today (GAPS §38).
    """
    _template = ViewPageTemplateFile("templates/facility_pipettes.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            self._save()
            self.request.response.redirect(
                _portal(self.context).absolute_url()
                + "/@@pfas-pipette-calibration?unit_id="
                + self.request.form.get("unit_id", ""))
            return ""
        return self._template()

    def _save(self):
        f = self.request.form
        kind = f.get("kind", "internal")
        try:
            as_found = float(f.get("as_found_pct") or 0) or None
        except (TypeError, ValueError):
            as_found = None
        try:
            tol = float(f.get("tolerance_pct") or 0) or None
        except (TypeError, ValueError):
            tol = None
        db.save_pipette_calibration({
            "unit_id":                f.get("unit_id", ""),
            "kind":                   kind,
            "cal_date":               f.get("cal_date", "").strip(),
            "due_date":               f.get("due_date", "").strip(),
            "operator":               f.get("operator", "").strip(),
            "provider":               f.get("provider", "").strip(),
            "provider_accreditation": f.get("provider_accreditation", "").strip(),
            "cert_number":            f.get("cert_number", "").strip(),
            # An in-house check must say what it was measured WITH; an external
            # one has no balance or weight set of ours involved.
            "balance_unit_id":        (f.get("balance_unit_id", "").strip()
                                       if kind == "internal" else None),
            "weight_set_id":          (f.get("weight_set_id", "").strip()
                                       if kind == "internal" else None),
            "as_found_pct":           as_found,
            "tolerance_pct":          tol,
            "passed":                 1 if f.get("passed") else 0,
            "notes":                  f.get("notes", "").strip(),
        })

    def unit(self):
        uid = self.request.form.get("unit_id", "")
        return db.get_unit(uid) if uid else None

    def pipettes(self):
        return [u for u in db.list_units() if u["unit_type"] == "pipette"]

    def balances(self):
        return [u for u in db.list_units()
                if u["unit_type"] in ("balance_analytical", "balance_prep")]

    def weight_sets(self):
        return db.list_weight_sets()

    def history(self):
        unit = self.unit()
        if not unit:
            return []
        rows = db.list_pipette_calibrations(unit["id"])
        today = date.today().strftime("%Y-%m-%d")
        for r in rows:
            due = r.get("due_date") or ""
            r["expired"] = bool(due and due < today)
            r["weight_set_label"] = _weight_set_label(r.get("weight_set_id"))
        return rows

    def in_force(self):
        """What covers TODAY — shown so the page answers the question a reviewer
        actually asks, rather than leaving them to read dates off a list."""
        unit = self.unit()
        if not unit:
            return None
        return db.get_pipette_calibration_in_force(
            unit["id"], date.today().strftime("%Y-%m-%d"))

    def today(self):
        return date.today().strftime("%Y-%m-%d")

    def portal_url(self):
        return _portal(self.context).absolute_url()


class PFASSensorIngestView(BrowserView):
    """Unauthenticated POST endpoint for Raspberry Pi sensor readings.

    Expects JSON body:
      {"api_key": "...", "sensor_id": "fridge-01",
       "timestamp": "2026-06-23T14:30:00",
       "temperature": 4.2, "humidity": null}

    Returns JSON: {"status": "ok", "in_range": true}
                  {"status": "error", "message": "..."}
    """

    def __call__(self):
        flatten_form(self.request)
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")

        # Read body
        body = self.request.get("BODY", b"")
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body.strip() else {}
        except ValueError as e:
            resp.setStatus(400)
            return json.dumps({"status": "error", "message": "invalid JSON: {}".format(str(e))})

        # Validate API key
        expected_key = db.get_api_key(_portal(self.context))
        if not expected_key or payload.get("api_key", "") != expected_key:
            resp.setStatus(403)
            return json.dumps({"status": "error", "message": "invalid api_key"})

        sensor_id = payload.get("sensor_id", "").strip()
        if not sensor_id:
            resp.setStatus(400)
            return json.dumps({"status": "error", "message": "sensor_id required"})

        unit = db.get_unit_by_sensor(sensor_id)
        if not unit:
            resp.setStatus(404)
            return json.dumps({"status": "error",
                               "message": "unknown sensor_id: {}".format(sensor_id)})

        temp = payload.get("temperature")
        humidity = payload.get("humidity")
        ts = payload.get("timestamp") or None

        in_range = db.record_temperature(
            unit_id=unit["id"],
            sensor_id=sensor_id,
            temperature=float(temp) if temp is not None else None,
            humidity=float(humidity) if humidity is not None else None,
            ts=ts,
            source="sensor",
        )

        return json.dumps({"status": "ok", "in_range": bool(in_range)})


def _ff(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None
