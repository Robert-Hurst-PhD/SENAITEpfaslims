# -*- coding: utf-8 -*-
"""Browser views for Facility QC (ISO 17025 daily verifications)."""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import facility_qc as db
from senaite.pfas.browser.formutil import flatten_form

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


class PFASFacilityUnitsView(BrowserView):
    """Unit registry — CRUD for lab manager."""
    _template = ViewPageTemplateFile("templates/facility_units.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        action = req.form.get("action", "")
        if req.method == "POST":
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
            "study_tolerance": f.get("study_tolerance", "1.0"),
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
            tolerance=float(f.get("tolerance") or unit.get("study_tolerance") or 1.0),
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
        )

    def unit(self):
        uid = self.request.form.get("unit_id", "")
        return db.get_unit(uid) if uid else None

    def balance_units(self):
        return [u for u in db.list_units()
                if u["unit_type"] in ("balance_analytical", "balance_prep")]

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
        return db.list_balance_verifications(unit["id"])

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
