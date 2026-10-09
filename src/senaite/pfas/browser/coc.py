# -*- coding: utf-8 -*-
"""@@pfas-coc: the chain of custody entry sheet. Client contacts and lab samplers enter their samples here, one row per
sample, under a LIMS-issued CoC number; lab staff use the same sheet to
transcribe a paper CoC (CW4) and reach receipt from it (CW3).

    @@pfas-coc                 the CoCs this person may see, and New CoC
    @@pfas-coc?coc=COC-…       one CoC: its header and sample rows

Submitting creates the SENAITE samples (create_analysisrequest) with the
CoC number set and records the sampler's relinquish -- who, from the login,
and when. A client edits their own CoC until the lab receives it; every edit
after submission is logged with the earlier value; after receipt only lab
staff edit, with a reason. Client-safe: listed in perms.CLIENT_VIEWS, and a
client sees only their own client's CoCs. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging
from datetime import datetime

from bika.lims import api
from DateTime import DateTime
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import coc_entry as ce
from senaite.pfas import coc_records as cr
from senaite.pfas import homogenisation as hg
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.coc")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _setup(portal_type):
    brains = api.search({"portal_type": portal_type, "is_active": True,
                         "sort_on": "sortable_title"}, "senaite_catalog_setup")
    return [(api.get_uid(b), api.get_title(b)) for b in brains]


class PFASCoCView(BrowserView):
    template = ViewPageTemplateFile("templates/coc.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors, self.saved = [], u""
        f = self.request.form
        action = f.get("action") or u""
        if self.request.method == "POST":
            if action == "new":
                return self._new()
            rec = self.record()
            if rec is None:
                self.errors.append(u"No such CoC.")
            elif action in ("save", "submit"):
                self._save(rec, submit=(action == "submit"))
        return self.template()

    # ── who ───────────────────────────────────────────────────────────────

    def portal_url(self):
        return api.get_portal().absolute_url()

    def is_staff(self):
        from senaite.pfas.browser.perms import is_staff
        return is_staff(api.get_portal())

    def my_client(self):
        try:
            return api.get_current_client()
        except Exception:                                   # noqa: BLE001
            return None

    def user_name(self):
        user = api.get_current_user()
        return user.getProperty("fullname") or user.getId()

    def _own(self, rec):
        client = self.my_client()
        return client is not None and api.get_uid(client) == rec.get("client_uid")

    def can_see(self, rec):
        return self.is_staff() or self._own(rec)

    def can_edit(self):
        rec = self.record()
        if rec is None:
            return False
        return cr.may_edit(rec, self.is_staff(), self._own(rec))[0]

    # ── data ──────────────────────────────────────────────────────────────

    def record(self):
        if not hasattr(self, "_rec"):
            num = (self.request.form.get("coc") or u"").strip()
            rec = cr.load(api.get_portal(), num) if num else None
            self._rec = rec if rec is not None and self.can_see(rec) else None
        return self._rec

    def records(self):
        client = self.my_client()
        if self.is_staff():
            recs = cr.for_client(api.get_portal(), None)
        elif client is not None:
            recs = cr.for_client(api.get_portal(), api.get_uid(client))
        else:
            recs = []
        return sorted(recs, key=lambda r: r["number"], reverse=True)

    def clients(self):
        return [(api.get_uid(c), api.get_title(c))
                for c in api.get_portal().clients.objectValues("Client")]

    def contacts(self, rec):
        client = api.get_object_by_uid(rec.get("client_uid"), None)
        if client is None:
            return []
        return [(api.get_uid(c), c.getFullname()) for c in client.objectValues("Contact")]

    def choices(self):
        if hasattr(self, "_choices"):
            return self._choices
        from senaite.pfas.analysis_profiles import generated
        from senaite.pfas.method_profile_store import get_profile, list_method_ids
        portal = api.get_portal()
        methods = []
        for mid in list_method_ids(portal):
            by_type = generated(portal, mid)
            if by_type:
                methods.append({"id": mid, "title": get_profile(portal, mid).get("display_name") or mid,
                                "types": sorted(by_type)})
        self._choices = {
            "sampletypes": _setup("SampleType"), "points": _setup("SamplePoint"),
            "containers": _setup("SampleContainer"), "preservations": _setup("SamplePreservation"),
            "methods": methods, "homogenisation": hg.choices(hg.load_methods(portal)),
            "field_qc": cr.FIELD_QC_TYPES}
        return self._choices

    def rows(self):
        """The rows to draw: what was typed when a save was refused, else the
        record's (sample rows, from the samples once they exist)."""
        if self.errors and self.request.form.get("action") in ("save", "submit"):
            return ce.rows_from_form(self.request.form)
        return (self.record() or {}).get("rows") or []

    def header(self):
        rec = self.record() or {}
        if self.errors and self.request.form.get("action") in ("save", "submit"):
            return ce.header_from_form(self.request.form)
        h = dict((k, rec.get(k) or u"") for k in ce.HEADER_KEYS)
        h["sampler"] = h["sampler"] or self.user_name()
        return h

    # ── actions ───────────────────────────────────────────────────────────

    def _redirect(self, num, msg=u""):
        url = u"%s/@@pfas-coc?coc=%s" % (self.portal_url(), num)
        if msg:
            url += u"&saved=" + msg
        self.request.response.redirect(url)
        return u""

    def _new(self):
        f = self.request.form
        if self.is_staff():
            client = api.get_object_by_uid(f.get("client_uid") or u"", None)
            origin = cr.PAPER if f.get("origin") == cr.PAPER else cr.DIGITAL
        else:
            client, origin = self.my_client(), cr.DIGITAL
        if client is None:
            self.errors.append(u"Choose the client.")
            return self.template()
        rec = cr.issue(api.get_portal(), api.get_uid(client), api.get_title(client), origin,
                       self.user_name(), _now())
        return self._redirect(rec["number"])

    def _save(self, rec, submit):
        f = self.request.form
        staff, own = self.is_staff(), self._own(rec)
        ok, why = cr.may_edit(rec, staff, own)
        if not ok:
            self.errors.append(why)
            return
        reason = (f.get("reason") or u"").strip()
        if rec["status"] == cr.RECEIVED and not reason:
            self.errors.append(u"Say why a received CoC is being corrected.")
            return
        rows = ce.rows_from_form(f)
        header = ce.header_from_form(f)
        if submit or rec["status"] != cr.OPEN:
            problems = ce.row_problems(rows, cr.FIELD_QC_TYPES)
            if problems:
                self.errors.extend(problems)
                return
        contact_uid = f.get("contact_uid") or u""
        if not contact_uid:
            contact = api.get_user_contact(api.get_current_user(), ["Contact"])
            contact_uid = api.get_uid(contact) if contact is not None else u""
        if (submit or rec["status"] != cr.OPEN) and not contact_uid:
            self.errors.append(u"Choose the client contact for these samples.")
            return
        at, by = _now(), self.user_name()
        before_header = dict((k, rec.get(k)) for k in ce.HEADER_KEYS)
        if rec["status"] != cr.OPEN:
            cr.log_changes(rec, before_header, header, by, at, reason)
        rec.update(header)
        old_rows = dict((r.get("sample_uid"), r) for r in rec.get("rows") or [] if r.get("sample_uid"))
        if rec["status"] == cr.OPEN and not submit:
            rec["rows"] = rows
            cr.save(api.get_portal(), rec)
            self.saved = u"Saved."
            self._rec = rec
            return
        made = []
        for row in rows:
            uid = row.get("sample_uid")
            if uid and uid in old_rows:
                changes = ce.changed_fields(old_rows[uid], row)
                if "method" in changes:
                    self.errors.append(u"%s: the analysis cannot be changed after submission; "
                                       u"ask the laboratory." % row["client_sid"])
                    row["method"] = old_rows[uid].get("method")
                    changes.pop("method")
                if changes:
                    self._apply(uid, row, changes)
                    for k, (b, a) in sorted(changes.items()):
                        rec["log"].append({"at": at, "by": by, "what": u"%s %s" % (row["client_sid"], k),
                                           "before": b, "after": a, "reason": reason})
            else:
                row["sample_uid"] = self._create(rec, row, contact_uid)
                made.append(row["client_sid"])
        rec["rows"] = rows
        rec["samples"] = [r["sample_uid"] for r in rows if r.get("sample_uid")]
        if submit and rec["status"] == cr.OPEN:
            rec["status"] = cr.SUBMITTED
            # the sampler's electronic relinquish; a paper CoC's relinquish is
            # on the paper (its scan), never the transcribing clerk's
            if rec.get("origin") != cr.PAPER:
                rec["transfers"].append({"relinquished_by": by, "relinquished_at": at,
                                         "received_by": u"", "received_at": u""})
            rec["log"].append({"at": at, "by": by, "what": u"submitted", "before": None,
                               "after": u", ".join(made), "reason": u""})
        elif made:
            rec["log"].append({"at": at, "by": by, "what": u"samples added", "before": None,
                               "after": u", ".join(made), "reason": reason})
        cr.save(api.get_portal(), rec)
        self._rec = rec
        self.saved = u"Submitted." if submit else u"Saved."

    def _profile_uid(self, row):
        from senaite.pfas.analysis_profiles import generated
        return generated(api.get_portal(), row.get("method"))[row.get("sampletype")]

    def _create(self, rec, row, contact_uid):
        from bika.lims.utils.analysisrequest import create_analysisrequest
        client = api.get_object_by_uid(rec["client_uid"])
        profile = api.get_object_by_uid(self._profile_uid(row))
        values = ce.sample_values(row, rec["client_uid"], contact_uid)
        values["Profiles"] = [api.get_uid(profile)]
        sample = create_analysisrequest(client, self.request, values, profile.getServiceUIDs())
        sample.getField("CoCNumber").set(sample, rec["number"])
        # the analyses carry the profile's method (analysis_profiles): the
        # transition subscriber does not see the profile on a sample made by
        # code, so it is applied here -- without it the sample's method is
        # not identified (no receipt range, no certificate; found 2026-10-06)
        from senaite.pfas.analysis_profiles import apply_method
        apply_method(sample)
        sample.reindexObject()
        return api.get_uid(sample)

    _SETTERS = {"client_sid": "setClientSampleID", "sampletype": "setSampleType",
                "sampling_point": "setSamplePoint", "container": "setContainer",
                "preservation": "setPreservation"}
    _FIELDS = {"homogenisation": hg.FIELD_METHOD, "composite": "Composite",
               "units": hg.FIELD_UNITS, "description": hg.FIELD_DESCRIPTION,
               "field_qc": "FieldQCType", "field_qc_of": "FieldQCOf"}

    def _apply(self, uid, row, changes):
        sample = api.get_object_by_uid(uid)
        for key in changes:
            value = row.get(key)
            if key == "sampled":
                sample.setDateSampled(DateTime((value or u"").replace(u"T", u" ")))
            elif key in self._SETTERS:
                getattr(sample, self._SETTERS[key])(value or None)
            elif key in self._FIELDS:
                if key == "units":
                    value = int(value) if (value or u"").isdigit() else None
                sample.getField(self._FIELDS[key]).set(sample, value)
        sample.reindexObject()
