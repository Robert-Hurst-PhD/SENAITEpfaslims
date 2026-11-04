# -*- coding: utf-8 -*-
"""Browser views for Facility QC (ISO 17025 daily verifications)."""
from __future__ import absolute_import, print_function, unicode_literals

import json
import re
import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import facility_qc as db
from senaite.pfas import lab_time
from senaite.pfas import print_doc
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (
    TIER_CONFIG, GateMixin, deny_gated_action)

logger = logging.getLogger("senaite.pfas.browser.facility_qc")


def _safe_json(obj):
    # its replacements were no-ops ("<" -> "<")
    from senaite.pfas.document_templates import script_json
    return script_json(obj, ensure_ascii=True)


def _lab_readings(readings):
    """Readings as the charts draw them: each UTC stamp `ts` on the
    laboratory's clock, in the stored "YYYY-MM-DDTHH:MM:SS" shape, while the
    zone converts; the very same list otherwise. The stored readings are not
    changed. The zone is resolved once for the whole series."""
    if not lab_time.active():
        return readings
    clock = db.lab_clock()
    out = []
    for r in readings:
        ts = r.get("ts")
        wall = clock(ts)
        out.append(dict(r, ts=wall.isoformat() if wall is not None
                        else print_doc.lab_or(ts, ts, u"%Y-%m-%dT%H:%M:%S")))
    return out


def _last_ts(ts):
    """A unit's last reading time: on the laboratory's clock while the zone
    converts, the stored stamp's minute otherwise."""
    ts = ts or u""
    return print_doc.lab_or(ts, ts[:16].replace(u"T", u" "))


def _portal(context):
    return getToolByName(context, "portal_url").getPortalObject()


def _current_user_id():
    try:
        from bika.lims import api
        user = api.get_current_user()
        return user.getId() if user else None
    except Exception:                                       # noqa: BLE001
        return None


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


class PFASFacilityDashboardView(ViewHelpers, BrowserView):
    """Daily checklist — one status row per unit."""
    _template = ViewPageTemplateFile("templates/facility_dashboard.pt")

    def __call__(self):
        flatten_form(self.request)
        return self._template()

    def summary(self):
        return db.dashboard_summary()

    def today(self):
        return lab_time.today().isoformat()

    def signed_in(self):
        """Who is recording: the signed-in person's name."""
        from senaite.pfas import print_doc
        return print_doc.current_user_label(self.context)


    def status_label(self, s):
        return {
            "ok": "OK",
            "out_of_range": "Out of Range",
            "overdue": "Overdue",
            "due": "Due",
            "pending": "Pending",
            "no_data": "No Data",
        }.get(s, s)

    def status_class(self, s):
        return {
            "ok": "fqc-ok",
            "out_of_range": "fqc-fail",
            "overdue": "fqc-warn",
            "due": "fqc-warn",
            "pending": "fqc-pending",
            "no_data": "fqc-pending",
        }.get(s, "")

    def unit_icon(self, ut):
        return {
            "refrigerator":       "fas fa-temperature-low",
            "freezer":            "fas fa-snowflake",
            "water_bath":         "fas fa-hot-tub",
            "balance_analytical": "fas fa-balance-scale",
            "balance_prep":       "fas fa-balance-scale-right",
            "eyewash":            "fas fa-eye",
            "water_system":       "fas fa-tint",
            "room_sensor":        "fas fa-thermometer-half",
        }.get(ut, "fas fa-circle")


# Which POST actions are lab configuration. The daily bench logs in
# this module -- temperature, balance, water, waste, eyewash, pipette
# calibration -- are deliberately absent: any lab user records them. The Unit
# Registry's actions moved to Equipment Types (browser/equipment.py TYPES_GATES)
# when units became core Instruments.
WEIGHT_SET_GATES = {
    "save": TIER_CONFIG,
    "delete": TIER_CONFIG,
}


def facility_defaults_for_form():
    """Lab-wide facility defaults, with balance weight points as editable text
    (Equipment Types page)."""
    d = dict(_facility_defaults())
    d["balance_rows"] = dict(
        (k, points_to_rows(v)) for k, v in (d.get("balance_points") or {}).items())
    return d


def save_defaults_from_form(form, portal):
    points = {}
    for key in ("balance_analytical", "balance_prep"):
        parsed = points_from_rows(form, key)
        if parsed:
            points[key] = parsed
    data = {"balance_points": points}
    unit = (form.get("water_conductivity_unit") or "").strip()
    if unit in dict(db.CONDUCTIVITY_UNITS):
        data["water_conductivity_unit"] = unit
    for field in ("eyewash_temp_min", "eyewash_temp_max",
                  "water_conductivity_max", "water_toc_max", "study_tolerance"):
        raw = (form.get(field) or "").strip()
        if raw:
            try:
                data[field] = float(raw)
            except ValueError:
                logger.warning("facility defaults: %s=%r not a number, "
                               "left unchanged", field, raw)
    db.save_facility_defaults(portal, data)


_POINT_LABEL = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(mg|g)\s*$")


def _num_text(v):
    return u"%g" % v


def points_to_rows(points):
    """Stored weight points ([grams, label]) as form rows: the value and unit
    the label names, else the grams (below 1 g, in mg)."""
    rows = []
    for i, p in enumerate(points or []):
        grams, label = float(p[0]), p[1] if len(p) > 1 else u""
        m = _POINT_LABEL.match(label or u"")
        if m and abs((float(m.group(1)) / (1000.0 if m.group(2) == "mg" else 1.0)) - grams) < 1e-9:
            value, unit = float(m.group(1)), m.group(2)
        elif grams < 1:
            value, unit = grams * 1000.0, u"mg"
        else:
            value, unit = grams, u"g"
        rows.append({"i": i, "value": _num_text(value), "unit": unit})
    return rows


def points_from_rows(form, key):
    """The weight rows posted for one balance kind (bal_w.<kind>.<n> and
    bal_u.<kind>.<n>) as [grams, label]; the label is the value and unit typed.
    An empty, unreadable or non-positive row is skipped."""
    prefix = "bal_w.%s." % key
    idx = sorted(int(k[len(prefix):]) for k in form.keys()
                 if k.startswith(prefix) and k[len(prefix):].isdigit())
    out = []
    for i in idx:
        raw = (form.get("%s%d" % (prefix, i)) or u"").strip()
        try:
            value = float(raw)
        except ValueError:
            if raw:
                logger.warning("facility defaults: skipping weight %r", raw)
            continue
        if value <= 0:
            continue
        unit = u"mg" if form.get("bal_u.%s.%d" % (key, i)) == "mg" else u"g"
        out.append([value / 1000.0 if unit == u"mg" else value, u"%s %s" % (_num_text(value), unit)])
    return out


class PFASTemperatureLogView(ViewHelpers, BrowserView):
    """Time-series chart for a single temp/humidity unit."""
    _template = ViewPageTemplateFile("templates/facility_temp_log.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST" and req.form.get("action") == "add_study":
            self.error = self._create_study()
            if self.error:
                return self._template()
            self.request.response.redirect(self.request.URL)
            return ""
        if req.method == "POST" and req.form.get("action") == "save_points":
            self._save_points()
            self.request.response.redirect(self.request.URL)
            return ""
        return self._template()

    def _create_study(self):
        f = self.request.form
        uid = f.get("unit_id", "")
        unit = db.get_unit(uid)
        if not unit:
            return
        # The reference thermometer is a registered one (Equipment Checks >
        # Reference Thermometers): its serial and certificate come from its
        # record, never typed
        from senaite.pfas.browser import equipment as eq
        ref_uid = (f.get("reference_uid") or "").strip() or None
        ref = db.get_unit(ref_uid) if ref_uid else None
        if ref is None or ref.get("unit_type") != "reference_thermometer":
            return u"Choose the registered reference thermometer the study is read against."
        # a multi-point unit: each study is done at one of its working temperatures
        study_temp = None
        if db._model(unit) == db.tc.MULTI:
            study_temp = _ff(f.get("study_temp"))
            if study_temp is None or study_temp not in db.unit_working_temps(unit):
                return u"Choose the working temperature the study is done at."
        chk = eq.reference_check(ref_uid, f.get("study_date") or lab_time.today().isoformat())
        nist_serial = ref.get("serial_number") or ref.get("name") or u""
        nist_cert = chk.get("valid_to") if chk else None
        db.create_study(
            unit_id=uid,
            operator=f.get("operator", ""),
            nist_serial=nist_serial,
            nist_cert_date=nist_cert,
            reference_uid=ref_uid,
            study_date=f.get("study_date") or None,
            tolerance=float(f.get("tolerance") or unit.get("study_tolerance")
                            or _facility_defaults().get("study_tolerance")),
            notes=f.get("notes") or None,
            study_temp=study_temp,
        )
        return None

    error = None

    def reference_options(self):
        """Each registered reference with what the study form shows read-only."""
        from senaite.pfas.browser import equipment as eq
        out = []
        for r in eq.reference_thermometers():
            chk = eq.reference_check(r["id"], lab_time.today().isoformat()) or {}
            out.append({"id": r["id"], "label": u"%s \u00b7 S/N %s \u00b7 %s" % (
                r["name"], r.get("serial_number") or u"?",
                (u"certificate to %s" % chk["valid_to"]) if chk.get("valid_to") else u"no certificate in force")})
        return out

    def _save_points(self):
        """The open study's readings table, saved at once: a row left as it was
        keeps its entry (who and when) untouched; a row with nothing typed is
        skipped."""
        f = self.request.form
        try:
            study_id = int(f.get("study_id", 0))
        except (TypeError, ValueError):
            return
        stored = dict((p["time_point"], p) for p in (db.get_study(study_id) or {}).get("points") or [])
        for tp in sorted(stored):
            old = stored[tp]
            sr, nr = _ff(f.get("sensor_reading.%d" % tp)), _ff(f.get("nist_reading.%d" % tp))
            ra = (f.get("recorded_at.%d" % tp) or "").strip() or None
            if sr is None and nr is None and not ra:
                continue
            if ((sr, nr) == (old.get("sensor_reading"), old.get("nist_reading"))
                    and (ra or "")[:16] == (old.get("recorded_at") or "")[:16]):
                continue
            db.save_study_point(
                study_id=study_id,
                time_point=tp,
                sensor_reading=sr,
                nist_reading=nr,
                recorded_at=ra,
                entered_by=_current_user_id(),      # the study's audit trail
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
        return _safe_json(_lab_readings(readings))

    def unit_json(self):
        return _safe_json(self.unit() or {})

    def studies(self):
        unit = self.unit()
        if not unit:
            return []
        out = []
        from senaite.pfas.browser import equipment as eq
        for s in db.list_studies(unit["id"]):
            det = db.get_study(s["id"]) or {}
            out.append(dict(s, correction=db.study_correction(det.get("points")),
                            reference=eq.reference_check(s.get("reference_uid"), s.get("study_date"))))
        return out

    def reference_thermometers(self):
        from senaite.pfas.browser import equipment as eq
        return eq.reference_thermometers()

    def study_changes(self):
        det = self.study_detail()
        return db.study_point_changes(det["study"]["id"]) if det else []

    def correction(self):
        """The correction applied to this unit's readings now (a single
        factor or a multi-point calibration, described), or None; and
        whether its type requires one."""
        unit = self.unit()
        if not unit:
            return None
        cal = db.calibration(unit["id"], unit=unit)
        return {"required": db._requires_correction(unit), "current": cal,
                "text": db.tc.describe(cal)}

    def working_temps(self):
        """The working temperatures of a multi-point unit, else []."""
        unit = self.unit()
        return db.unit_working_temps(unit) if unit and db._model(unit) == db.tc.MULTI else []

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
                if u["unit_type"] in ("refrigerator", "freezer", "water_bath", "room_sensor", "eyewash",
                                      "thermometer", "ir_gun", "nitrogen_evaporator")]

    # ── Monitoring: one card per unit of a kind (no unit chosen) ─────────
    MONITOR_KINDS = (("refrigerator", u"Refrigerators"), ("freezer", u"Freezers"),
                     ("water_bath", u"Water baths"), ("room_sensor", u"Lab room"),
                     ("thermometer", u"Thermometers"))
    MONITOR_DAYS = (7, 30, 90)

    def monitor_kind(self):
        k = self.request.form.get("kind") or "refrigerator"
        return k if k in dict(self.MONITOR_KINDS) else "refrigerator"

    def monitor_days(self):
        raw = u"%s" % self.request.form.get("days", u"7")
        return int(raw) if raw.isdigit() and int(raw) in self.MONITOR_DAYS else 7

    def monitor_links(self):
        base = _portal(self.context).absolute_url() + "/@@pfas-temperature-log"
        kind, days = self.monitor_kind(), self.monitor_days()
        return {"kinds": [{"label": l, "on": k == kind, "url": "%s?kind=%s&days=%d" % (base, k, days)}
                          for k, l in self.MONITOR_KINDS],
                "days": [{"label": u"%dd" % d, "on": d == days, "url": "%s?kind=%s&days=%d" % (base, kind, d)}
                         for d in self.MONITOR_DAYS]}

    def add_sensor_url(self):
        """A new monitored unit is a core Instrument whose type is of that kind."""
        return _portal(self.context).absolute_url() + "/bika_setup/bika_instruments/createObject?type_name=Instrument"

    def _storage_ranges(self, entries):
        """The ranges for what the unit holds, per method (Storage and holding)."""
        from senaite.pfas import method_profile_sections as mps
        from senaite.pfas.method_profile_store import raw_profile
        portal = _portal(self.context)
        return mps.kept_ranges(entries, lambda mid: raw_profile(portal, mid))

    def monitor_cards(self):
        """Each unit of the kind: its sensor, last reading, current value
        judged against the tightest of its own range and the storage ranges
        of the methods whose samples it stores, and its readings for the
        chart."""
        out = []
        for u in db.list_units():
            if u["unit_type"] != self.monitor_kind():
                continue
            try:
                mids = json.loads(u.get("profiles_json") or "[]") or []
            except (TypeError, ValueError):
                mids = []
            storage = self._storage_ranges(mids)
            lo, hi = db.effective_range(_ff(u.get("temp_min")), _ff(u.get("temp_max")),
                                        [(r[1], r[2]) for r in storage])
            last = db.latest_reading(u["id"])
            value = None
            if last:
                value = last.get("corrected") if last.get("corrected") is not None else last.get("temperature")
            ok = None
            conflict = u""
            if db.range_conflict(lo, hi):
                # no reading can meet ranges that do not overlap: say so, judge nothing
                conflict = u"It holds items whose ranges do not overlap: %s. Change what it holds." % u"; ".join(
                    u"%s %s to %s \u00b0C" % (r[0], u"%g" % r[1] if r[1] is not None else u"?",
                                               u"%g" % r[2] if r[2] is not None else u"?") for r in storage)
            elif value is not None and (lo is not None or hi is not None):
                ok = (lo is None or value >= lo) and (hi is None or value <= hi)
            readings = db.get_temperature_readings(u["id"], days=self.monitor_days())
            out.append({"id": u["id"], "name": u["name"], "sensor": u.get("sensor_id") or u"",
                        "last_ts": _last_ts((last or {}).get("ts")),
                        "value": value, "humidity": (last or {}).get("humidity"), "ok": ok,
                        "lo": lo, "hi": hi, "profiles": [r[0] for r in storage] or mids,
                        "conflict": conflict,
                        "readings_json": _safe_json([{"ts": r.get("ts"), "t": (r.get("corrected") if r.get("corrected") is not None else r.get("temperature")),
                                                      "h": r.get("humidity")} for r in _lab_readings(readings)]),
                        "url": "%s/@@pfas-temperature-log?unit_id=%s" % (_portal(self.context).absolute_url(), u["id"])})
        return out

    def deviation_url(self):
        return _portal(self.context).absolute_url() + "/@@pfas-deviations?new=deviation"


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


class PFASBalanceLogView(ViewHelpers, BrowserView):
    """Balance verification entry and history."""
    _template = ViewPageTemplateFile("templates/facility_balance.pt")
    error = None

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            self.error = self._save()
            if self.error:
                return self._template()
            self.request.response.redirect(
                _portal(self.context).absolute_url()
                + "/@@pfas-balance-log?unit_id="
                + self.request.form.get("unit_id", "")
            )
            return ""
        return self._template()

    def _save(self):
        """Saves the verification; returns why it was refused, else None.
        Every weight of the set is read each time: a
        partial verification is refused, never stored."""
        f = self.request.form
        unit_id = f.get("unit_id", "")
        unit = db.get_unit(unit_id)
        if not unit:
            return None
        weight_points = self._weight_points(unit)
        points, missing = [], []
        for i, wp in enumerate(weight_points):
            actual = _ff(f.get("actual_{}".format(i)))
            if actual is None:
                missing.append(wp[1])
            points.append({
                "nominal_g": wp[0],
                "label": wp[1],
                "actual_g": actual,
            })
        if missing:
            return u"Every weight needs a reading: %s." % u", ".join(missing)
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
            # the balance's TYPE decides acceptance: % of nominal
            tolerance_pct=unit.get("tolerance_pct"),
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

    def tolerance_text(self, wp):
        """A weight's tolerance in the unit its own label uses (10 mg -> \u00b10.02 mg,
        not \u00b10.00002 g): [grams, label, tolerance in grams]."""
        tol_g, label = float(wp[2]), (wp[1] or u"").strip()
        mg = label.endswith(u"mg")
        return u"\u00b1%s %s" % (u"%g" % (tol_g * 1000.0 if mg else tol_g), u"mg" if mg else u"g")

    def history(self):
        unit = self.unit()
        if not unit:
            return []
        rows = db.list_balance_verifications(unit["id"], limit=10)
        for r in rows:
            r["weight_set_label"] = _weight_set_label(r.get("weight_set_id"))
        return rows


class PFASWaterLogView(ViewHelpers, BrowserView):
    """Type 1 water QC log."""
    _template = ViewPageTemplateFile("templates/facility_water.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            f = self.request.form
            unit_id = f.get("unit_id") or u""
            if self.water_units() and not unit_id:
                self.error = u"Choose the water system."
                return self._template()
            # the limits are the system's own, else the lab-wide defaults
            # (Equipment Types), never typed per entry; a reading in MOhm.cm
            # is judged as uS/cm
            d, unit = self.defaults(unit_id), self.conductivity_unit()
            reading = _ff(f.get("conductivity"))
            db.save_water_qc(
                unit_id=unit_id,
                operator=f.get("operator", ""),
                conductivity=db.conductivity_us(reading, unit),
                toc=_ff(f.get("toc")),
                log_date=f.get("log_date") or None,
                log_time=f.get("log_time") or None,
                conductivity_max=d["conductivity_max"],
                toc_max=d["toc_max"],
                notes=f.get("notes") or None,
                conductivity_entered=(u"%g %s" % (reading, unit)) if reading is not None else None,
            )
            self.request.response.redirect(
                _portal(self.context).absolute_url() + "/@@pfas-water-log"
            )
            return ""
        return self._template()

    error = None

    def logs(self):
        names = dict((u["id"], u["name"]) for u in self.water_units())
        return [dict(r, system=names.get(r.get("unit_id"), u"")) for r in db.list_water_qc(limit=60)]

    def water_units(self):
        return [u for u in db.list_units() if u["unit_type"] == "water_system"]

    def defaults(self, unit_id=None):
        """The limits a reading is judged by: the system's own (set on the
        Equipment page), each one falling back to the lab-wide default."""
        d = _facility_defaults()
        out = {"conductivity_max": d["water_conductivity_max"], "toc_max": d["water_toc_max"]}
        unit = db.get_unit(unit_id) if unit_id else None
        try:
            own = json.loads((unit or {}).get("extra_config_json") or "{}")
        except (ValueError, TypeError):
            own = {}
        for k in out:
            if _ff(own.get(k)) is not None:
                out[k] = _ff(own.get(k))
        return out

    def conductivity_unit(self):
        u = _facility_defaults().get("water_conductivity_unit") or "uS/cm"
        return u if u in dict(db.CONDUCTIVITY_UNITS) else "uS/cm"

    def conductivity_label(self):
        return dict(db.CONDUCTIVITY_UNITS)[self.conductivity_unit()]

    def conductivity_limit(self):
        """The limit as the reading is entered: <= max uS/cm, or >= 1/max MOhm.cm."""
        mx = self.defaults(self.request.get("unit_id"))["conductivity_max"]
        if self.conductivity_unit() == "MOhm.cm":
            return u"Limit \u2265 %g M\u03a9\u00b7cm" % (round(1.0 / mx, 4) if mx else 0)
        return u"Limit \u2264 %g \u00b5S/cm" % mx


class PFASWasteLogView(ViewHelpers, BrowserView):
    """SAA waste container log."""
    _template = ViewPageTemplateFile("templates/facility_waste.pt")
    error = None

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            f = self.request.form
            # a log names one registered SAA (equipment of kind SAA)
            if f.get("unit_id", "") not in [u["id"] for u in self.waste_units()]:
                self.error = u"Choose the SAA container; register it as equipment first."
                return self._template()
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

    def add_saa_url(self):
        """New equipment: an SAA is a core Instrument whose type is of kind SAA."""
        return _portal(self.context).absolute_url() + "/bika_setup/bika_instruments/createObject?type_name=Instrument"

    def waste_units(self):
        """The registered waste containers: equipment of kind SAA (never a
        rule on the name)."""
        return [u for u in db.list_units() if u.get("unit_type") == "saa"]

    def logs(self):
        return db.list_waste_logs(limit=60)


class PFASEyeWashLogView(ViewHelpers, BrowserView):
    """Eye wash station verification log."""
    _template = ViewPageTemplateFile("templates/facility_eyewash.pt")
    error = None

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            f = self.request.form
            unit_id = f.get("unit_id", "")
            if not unit_id:
                self.error = u"Choose the station."
                return self._template()
            # the flush water temperature is part of every check
            if _ff(f.get("temperature")) is None:
                self.error = u"Record the flush water temperature."
                return self._template()
            from senaite.pfas import print_doc
            db.save_eyewash_log(
                unit_id=unit_id,
                operator=print_doc.current_user_label(self.context) or f.get("operator", ""),
                working=f.get("working") == "yes",
                temperature=_ff(f.get("temperature")),
                log_date=f.get("log_date") or None,
                log_time=f.get("log_time") or None,
                temp_min=_facility_defaults()["eyewash_temp_min"],
                temp_max=_facility_defaults()["eyewash_temp_max"],
                notes=f.get("notes") or None,
            )
            back = "/@@pfas-facility-qc" if f.get("return_to") == "checklist" else "/@@pfas-eyewash-log"
            self.request.response.redirect(_portal(self.context).absolute_url() + back)
            return ""
        return self._template()

    def signed_in(self):
        """Who is recording: the signed-in person's name."""
        from senaite.pfas import print_doc
        return print_doc.current_user_label(self.context)

    def eyewash_units(self):
        return [u for u in db.list_units() if u["unit_type"] == "eyewash"]

    def required_range(self):
        """The lab-wide flush temperature range, as the button beside the
        value reads it ("Required 15-25 \u00b0C")."""
        d = _facility_defaults()
        return u"Required %s\u2013%s \u00b0C" % (u"%g" % d["eyewash_temp_min"], u"%g" % d["eyewash_temp_max"])

    def in_range(self, r):
        """A logged temperature against the range stored with it."""
        t, lo, hi = r.get("temperature"), r.get("temp_min"), r.get("temp_max")
        if t is None or lo is None or hi is None:
            return True
        return lo <= t <= hi

    def logs(self):
        return db.list_eyewash_logs(limit=60)


class PFASWeightSetsView(GateMixin, BrowserView):
    """Reference weight sets and their EXTERNAL metrology-lab calibration.

    This is where the equipment chain leaves the laboratory. A balance
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
            due = ws.get("cal_due_date") or ""
            if due and due < self.today():
                probs.append(u"calibration expired %s" % due)
            elif not due:
                probs.append(u"no calibration due date recorded")
            ws["problems"] = probs
            out.append(ws)
        return out

    def today(self):
        return lab_time.today().isoformat()

    def portal_url(self):
        return _portal(self.context).absolute_url()


class PFASPipetteCalibrationView(ViewHelpers, BrowserView):
    """Pipette calibration — quarterly in house, or external.

    An INTERNAL check is a measurement this laboratory made, so it carries its own
    provenance: the balance and the reference weight set used, which run on to the
    metrology lab. An EXTERNAL one carries the provider, its accreditation and the
    certificate number. Both record a due date, because the gate judges
    calibration as of the date the pipette was USED, not today.
    """
    _template = ViewPageTemplateFile("templates/facility_pipettes.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            self.error = self._refused()
            if self.error:
                return self._template()
            self._save()
            self.request.response.redirect(
                _portal(self.context).absolute_url()
                + "/@@pfas-pipette-calibration?unit_id="
                + self.request.form.get("unit_id", ""))
            return ""
        return self._template()

    error = None

    def _refused(self):
        """Why an in-house calibration cannot be recorded: the balance it was
        weighed on must have passed its verification that day (the lab,
        2026-10-13). None when it may be recorded."""
        f = self.request.form
        if f.get("kind", "internal") != "internal":
            return None
        if self._worked_out()[2]:
            return self._worked_out()[2][0]
        bal, day = (f.get("balance_unit_id") or "").strip(), (f.get("cal_date") or "").strip()
        if not bal or not day:
            return u"Choose the balance used and the calibration date."
        ok, _note = db.balance_verified_on(bal, day)
        if not ok:
            return u"The balance was not verified on %s: verify it first, then record the calibration." % day
        return None

    def balance_checks_json(self):
        """{balance id: {"passed": [dates], "failed": [dates]}} for the form's
        status line beside "Balance used"."""
        out = {}
        for b in self.balances():
            rows = db.list_balance_verifications(b["id"], limit=400)
            out[b["id"]] = {"passed": sorted(set(r["verified_date"] for r in rows if r.get("passed"))),
                            "failed": sorted(set(r["verified_date"] for r in rows if not r.get("passed")))}
        return _safe_json(out)

    def signed_in(self):
        """Who is recording: the signed-in person's name."""
        from senaite.pfas import print_doc
        return print_doc.current_user_label(self.context)

    def measurement_rows(self):
        """The posted measurements table: [{"volume", "weighings": [5]}]."""
        f, out = self.request.form, []
        idx = sorted(set(int(k[5:]) for k in f.keys() if k.startswith("pm_v.") and k[5:].isdigit()))
        from senaite.pfas import pipette_cal
        for i in idx:
            # typed in g, as the balance shows them; the calibration works in mg
            out.append({"volume": f.get("pm_v.%d" % i),
                        "weighings": pipette_cal.from_grams(
                            [f.get("pm_w%d.%d" % (n, i)) for n in range(1, pipette_cal.WEIGHINGS + 1)])})
        return out

    def limits(self):
        """(permissible systematic error +/- %, permissible random error RSD %)
        set on the pipette (Equipment settings)."""
        u = self.unit() or {}
        return _ff(u.get("pipette_accuracy_pct")), _ff(u.get("pipette_precision_cv"))

    def _worked_out(self):
        """(rows, passed, problems, water temp, worst accuracy) of an in-house
        calibration, from the weighings (pipette_cal.py)."""
        from senaite.pfas import pipette_cal
        temp = _ff(self.request.form.get("water_temp"))
        z = pipette_cal.z_factor(temp)
        acc, cv = self.limits()
        rows, passed, problems = pipette_cal.evaluate(self.measurement_rows(), z, acc, cv)
        worst = max([abs(r["systematic_pct"]) for r in rows if r["systematic_pct"] is not None] or [None])
        return rows, passed, problems, temp, worst

    def _save(self):
        f = self.request.form
        kind = f.get("kind", "internal")
        as_found, tol, passed, rows, temp = None, None, 1 if f.get("passed") else 0, None, None
        if kind == "internal":
            # worked out from the weighings, never typed:
            # without the water temperature or the pipette's limits it is not a pass
            rows, verdict, _problems, temp, as_found = self._worked_out()
            tol = self.limits()[0]
            passed = 1 if verdict is True else 0
        db.save_pipette_calibration({
            "unit_id":                f.get("unit_id", ""),
            "kind":                   kind,
            "cal_date":               f.get("cal_date", "").strip(),
            # in house: once in each calendar quarter, worked out, never typed
            "due_date":               (db.quarter_due(f.get("cal_date", "").strip())[1] or u""
                                       if kind == "internal" else f.get("due_date", "").strip()),
            # the signed-in person, never typed
            "operator":               self.signed_in() or f.get("operator", "").strip(),
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
            "passed":                 passed,
            "notes":                  f.get("notes", "").strip(),
            "measurements_json":      json.dumps(rows) if rows is not None else None,
            "water_temp":             temp,
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
        today = lab_time.today().isoformat()
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
            unit["id"], lab_time.today().isoformat())

    def today(self):
        return lab_time.today().isoformat()


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
        except ValueError:
            resp.setStatus(400)
            return json.dumps({"status": "error", "message": "invalid JSON"})
        if not isinstance(payload, dict):
            resp.setStatus(400)
            return json.dumps({"status": "error", "message": "the body must be a JSON object"})

        # Validate API key
        expected_key = db.get_api_key(_portal(self.context))
        if not db.api_key_matches(expected_key, payload.get("api_key")):
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
        if (temp is not None and _ff(temp) is None) or (humidity is not None and _ff(humidity) is None):
            resp.setStatus(400)
            return json.dumps({"status": "error", "message": "temperature and humidity must be numbers"})

        in_range = db.record_temperature(
            unit_id=unit["id"],
            sensor_id=sensor_id,
            temperature=_ff(temp),
            humidity=_ff(humidity),
            ts=ts,
            source="sensor",
        )

        return json.dumps({"status": "ok", "in_range": bool(in_range)})


from senaite.pfas.rounding import number as _ff


