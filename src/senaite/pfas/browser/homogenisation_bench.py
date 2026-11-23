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
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.homogenisation")

RECENT = 40          # recorded samples listed for a correction


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


class PFASHomogenisationView(ViewHelpers, GateMixin, BrowserView):
    template = ViewPageTemplateFile("templates/homogenisation_bench.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors, self.done = [], []
        if self.request.method == "POST" and self.request.form.get("action") == "record":
            self._record()
        return self.template()

    # ── data ──────────────────────────────────────────────────────────────

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
            try:
                coc = s.getField("CoCNumber").get(s) or u""
            except Exception:                               # noqa: BLE001
                coc = u""
            rows.append({"uid": api.get_uid(s), "id": s.getId(), "url": api.get_url(s), "coc": coc,
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

    STATUSES = ((u"active", u"Active"), (u"pending", u"Pending"), (u"recorded", u"Recorded"))

    def status_filter(self):
        s = self.request.form.get("status") or u"active"
        return s if s in dict(self.STATUSES) else u"active"

    def status_links(self):
        base = self.portal_url() + "/@@pfas-homogenisation?status="
        return [{"label": l, "url": base + k, "on": k == self.status_filter()} for k, l in self.STATUSES]

    def rows(self):
        """One list: Pending (awaiting) and Recorded, filtered by status."""
        want = self.status_filter()
        out = []
        for r in self._samples():
            if not (r["awaiting"] or r["last"]):
                continue
            pending = bool(r["awaiting"])
            if want == u"pending" and not pending or want == u"recorded" and pending:
                continue
            out.append(dict(r, status=u"Pending" if pending else u"Recorded"))
        return out

    def row_url(self, r):
        return u"%s/@@pfas-homogenisation?status=%s&open=%s" % (self.portal_url(), self.status_filter(), r["uid"])

    def open_row(self):
        """The row whose dialog is open: the one clicked, or the one whose
        record was refused. A record that went through closes it."""
        if self.done:
            return None
        uid = self.request.form.get("open") or u""
        for r in self.rows() or []:
            if r["uid"] == uid:
                return r
        for r in self._samples():
            if r["uid"] == uid:
                return dict(r, status=u"Pending" if r["awaiting"] else u"Recorded")
        return None

    def together_choices(self, row):
        """The other samples awaiting homogenisation, to record as done with it."""
        return [r for r in self.awaiting() if r["uid"] != row["uid"]]

    def method_value(self, row):
        """The method the dialog starts at: what was typed after a refusal,
        else the sample's request (its CoC or the matrix default)."""
        return self.form_value("method") or row.get("method") or u""

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
            self.errors.append(u"Choose the technique used.")
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
                warns.append(u"replaces the record of %s" % self.lab_at(
                    prev.get("at"), (prev.get("at") or u"")[:16].replace(u"T", u" ")))
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
