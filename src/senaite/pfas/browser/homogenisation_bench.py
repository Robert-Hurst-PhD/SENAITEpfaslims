# -*- coding: utf-8 -*-
"""@@pfas-homogenisation (Bench): samples awaiting homogenisation, and the
record of doing it -- one sample or a whole bulk grind in one action, each
sample getting its own record (H-P3).

A record names the method used, the homogeniser unit, whether it was
cleaned, and for a composite the units combined. What differs from the
sample's request needs a note (homogenisation.record_warnings). Recording a
sample again is a correction: the earlier record is kept. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging
from datetime import datetime

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import homogenisation as hg
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import GateMixin

logger = logging.getLogger("senaite.pfas.homogenisation")

RECENT = 40          # recorded samples listed for a correction


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


class PFASHomogenisationView(GateMixin, BrowserView):
    template = ViewPageTemplateFile("templates/homogenisation_bench.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors, self.done = [], []
        if self.request.method == "POST" and self.request.form.get("action") == "record":
            self._record()
        return self.template()

    # ── data ──────────────────────────────────────────────────────────────

    def portal_url(self):
        return api.get_portal().absolute_url()

    def methods(self):
        if not hasattr(self, "_methods"):
            self._methods = hg.load_methods(api.get_portal())
        return self._methods

    def method_choices(self):
        return hg.choices(self.methods())

    def units(self):
        """Registered homogenisers (Equipment, kind Homogeniser)."""
        try:
            from senaite.pfas import facility_qc as fq
            from senaite.pfas.bench_queue import units_for
            return [{"serial": u.get("serial_number") or u"", "name": u.get("name") or u""}
                    for u in units_for(u"Homogeniser", fq.list_units())]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("homogeniser units: %s", exc)
            return []

    def _samples(self):
        if hasattr(self, "_rows"):
            return self._rows
        rows = []
        for brain in api.search({"portal_type": "AnalysisRequest", "review_state": "sample_received"},
                                "senaite_catalog_sample"):
            s = api.get_object(brain)
            req = hg.sample_request(s)
            records = hg.load_records(s)
            if not req["method"] or (req["method"] == hg.NONE_ID and not records):
                continue
            st = s.getSampleType()
            last = hg.latest(records) or {}
            rows.append({"uid": api.get_uid(s), "id": s.getId(), "url": api.get_url(s),
                         "csid": s.getClientSampleID() or u"",
                         "matrix": api.get_title(st) if st else u"",
                         "method": req["method"], "method_title": hg.title_of(self.methods(), req["method"]),
                         "composite": req["composite"], "units": req["units"],
                         "description": req["description"], "problems": req["problems"],
                         "awaiting": hg.awaiting(req, records), "last": last,
                         "last_title": hg.title_of(self.methods(), last.get("method")) if last else u""})
        self._rows = sorted(rows, key=lambda r: r["id"])
        return self._rows

    def awaiting(self):
        return [r for r in self._samples() if r["awaiting"]]

    def recorded(self):
        done = [r for r in self._samples() if r["last"]]
        return sorted(done, key=lambda r: r["last"].get("at") or u"", reverse=True)[:RECENT]

    def form_value(self, name, default=u""):
        """What the chemist typed, kept when a record is refused."""
        return self.request.form.get(name, default) if self.errors else default

    def selected(self):
        if not self.errors:
            return []
        return self._sel()

    def _sel(self):
        """Selected sample uids: one field per row, sel__<uid> (flatten_form
        keeps only the first value of a list)."""
        return [k[len("sel__"):] for k in self.request.form if k.startswith("sel__")]

    # ── record ────────────────────────────────────────────────────────────

    def _user(self):
        try:
            u = api.get_current_user()
            return u.getProperty("fullname") or u.getId()
        except Exception:                                   # noqa: BLE001
            return u""

    def _record(self):
        f = self.request.form
        sel = self._sel()
        method = (f.get("method") or u"").strip()
        serial = (f.get("unit_serial") or u"").strip()
        cleaned = f.get("cleaned") == u"on"
        note = (f.get("note") or u"").strip()
        if not sel:
            self.errors.append(u"Select the samples homogenised.")
            return
        valid = set(m for m, _t in self.method_choices())
        if method not in valid:
            self.errors.append(u"Choose the method used.")
            return
        unit_name = u""
        if serial:
            try:
                from senaite.pfas import facility_qc as fq
                unit = fq.unit_by_serial(serial)
                unit_name = (unit or {}).get("name") or u""
            except Exception as exc:                        # noqa: BLE001
                logger.warning("homogeniser %r: %s", serial, exc)
            if not unit_name:
                self.errors.append(u"No registered homogeniser has serial %s." % serial)
                return
        plan, needs = [], []
        for uid in sel:
            s = api.get_object_by_uid(uid, None)
            if s is None:
                continue
            req = hg.sample_request(s)
            units = (f.get(u"units__%s" % uid) or u"").strip()
            warns = hg.record_warnings(req, method, unit_name, cleaned, units, self.methods())
            prev = hg.latest(hg.load_records(s))
            if prev:
                warns.append(u"replaces the record of %s" % (prev.get("at") or u"")[:16].replace(u"T", u" "))
            plan.append((s, units, warns))
            needs += [u"%s: %s" % (s.getId(), w) for w in warns]
        if needs and not note:
            self.errors.append(u"Write a note explaining:")
            self.errors.extend(needs)
            return
        at, by = _now(), self._user()
        for s, units, warns in plan:
            hg.append_record(s, {
                "at": at, "by": by, "method": method, "unit_serial": serial,
                "unit_name": unit_name, "cleaned": cleaned,
                "units_combined": int(units) if units.isdigit() else None,
                "note": note, "warnings": warns, "batch": [x[0].getId() for x in plan]})
            self.done.append(s.getId())
        self.__dict__.pop("_rows", None)
