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
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import coc_entry as ce
from senaite.pfas import coc_records as cr
from senaite.pfas import homogenisation as hg
from senaite.pfas import lab_time
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.coc")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _setup(portal_type):
    brains = api.search({"portal_type": portal_type, "is_active": True,
                         "sort_on": "sortable_title"}, "senaite_catalog_setup")
    return [(api.get_uid(b), api.get_title(b)) for b in brains]


class PFASCoCView(ViewHelpers, BrowserView):
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

    def is_staff(self):
        from senaite.pfas.browser.perms import is_staff
        return is_staff(api.get_portal())

    def may_receive(self):
        """Receiving changes records: a role that may change records, never
        the read-only inspector (the receipt page's own rule)."""
        from senaite.pfas.browser.perms import may_write
        return may_write(api.get_portal())

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

    # the list's Show filter: what the lab has not received yet first
    SHOW = ((u"", u"Not received"), (u"received", u"Received"), (u"all", u"All"))

    def list_show(self):
        v = (self.request.form.get("show") or u"").strip()
        return v if v in [k for k, _l in self.SHOW] else u""

    def list_q(self):
        return (self.request.form.get("q") or u"").strip()

    def list_url(self, show=None, page=None):
        from senaite.pfas.browser.list_paging import list_url
        return list_url(u"%s/@@pfas-coc" % self.portal_url(),
                        [("show", self.list_show() if show is None else show), ("q", self.list_q()),
                         ("page", page if page and page > 1 else None)])

    def list_shows(self):
        return [{"label": l, "url": self.list_url(show=k), "on": k == self.list_show()} for k, l in self.SHOW]

    def list_paging(self):
        if not hasattr(self, "_list_pg"):
            from senaite.pfas.browser.list_paging import page_number, paging
            self._list_kept = cr.list_filter(self.records(), self.list_show(), self.list_q())
            self._list_pg = paging(len(self._list_kept), page_number(self.request.form),
                                   lambda p: self.list_url(page=p))
        return self._list_pg

    def list_rows(self):
        pg = self.list_paging()
        return self._list_kept[pg["start"]:pg["end"]]

    def list_empty_text(self):
        if not self.records():
            return u"No CoC yet."
        if self.list_q():
            return u"No CoC matches this search."
        return {u"": u"Every CoC has been received.", u"received": u"No CoC has been received yet."}.get(
            self.list_show(), u"No CoC yet.")

    def clients(self):
        return [(api.get_uid(c), api.get_title(c))
                for c in api.get_portal().clients.objectValues(["Client"])]

    def contacts(self, rec):
        client = api.get_object_by_uid(rec.get("client_uid"), None)
        if client is None:
            return []
        return [(api.get_uid(c), c.getFullname()) for c in client.objectValues(["Contact"])]

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

    def subtypes_by_type(self):
        """{sample type uid: its sub-types} (sample_subtypes)."""
        if getattr(self, "_subtypes", None) is None:
            from senaite.pfas import sample_subtypes as ss
            out = {}
            for uid, _title in self.choices()["sampletypes"]:
                try:
                    subs = ss.load(api.get_object_by_uid(uid))
                except Exception:                           # noqa: BLE001
                    subs = []
                if subs:
                    out[uid] = subs
            self._subtypes = out
        return self._subtypes

    def subtype_options(self):
        """Every sub-type as a row's select offers it: its type and the
        profiles turned off (coc_row_detail.js shows those that fit the row)."""
        return [{"id": x["id"], "name": x["name"], "type": uid, "off": u" ".join(x.get("off") or [])}
                for uid, subs in sorted(self.subtypes_by_type().items()) for x in subs]

    def rows(self):
        """The rows to draw: what was typed when a save was refused, else the
        record's (sample rows, from the samples once they exist)."""
        if self.errors and self.request.form.get("action") in ("save", "submit"):
            return ce.rows_from_form(self.request.form)
        return (self.record() or {}).get("rows") or []

    def detail_summary(self, row):
        """The row's detail dialog in words (coc_entry.detail_summary)."""
        ch = self.choices()
        names = {"subtype": dict((o["id"], o["name"]) for o in self.subtype_options())}
        for key, src in (("sampling_point", "points"), ("container", "containers"),
                         ("preservation", "preservations"), ("homogenisation", "homogenisation")):
            names[key] = dict((o[0], o[1]) for o in ch[src])
        return ce.detail_summary(row, names)

    def header(self):
        rec = self.record() or {}
        if self.errors and self.request.form.get("action") in ("save", "submit"):
            return ce.header_from_form(self.request.form)
        # Sampled by starts empty: the person entering the CoC is not the
        # sampler unless they say so ("This is me")
        return dict((k, rec.get(k) or u"") for k in ce.HEADER_KEYS)

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
        if not self.is_staff():
            from senaite.pfas import coc_limits
            reached, cap = coc_limits.cap_for(api.get_portal(), api.get_uid(client), _now())
            if reached:
                self.errors.append(u"You have started %d CoCs today, the most allowed. "
                                   u"Submit one you have open, or try again tomorrow." % cap)
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
            problems = ce.row_problems(rows, cr.FIELD_QC_TYPES) + ce.subtype_problems(rows, self.subtypes_by_type())
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
        # not identified (no receipt range, no certificate)
        from senaite.pfas.analysis_profiles import apply_method
        apply_method(sample)
        sample.reindexObject()
        return api.get_uid(sample)

    _SETTERS = {"client_sid": "setClientSampleID", "sampletype": "setSampleType",
                "sampling_point": "setSamplePoint", "container": "setContainer",
                "preservation": "setPreservation"}
    _FIELDS = {"homogenisation": hg.FIELD_METHOD, "composite": "Composite",
               "units": hg.FIELD_UNITS, "description": hg.FIELD_DESCRIPTION,
               "field_qc": "FieldQCType", "field_qc_of": "FieldQCOf",
               "compliance": "ComplianceSample", "subtype": "SampleSubtype"}

    def _apply(self, uid, row, changes):
        sample = api.get_object_by_uid(uid)
        for key in changes:
            value = row.get(key)
            if key == "sampled":
                # typed on the laboratory's clock
                text = (value or u"").replace(u"T", u" ")
                sample.setDateSampled(lab_time.typed(text) or DateTime(text))
            elif key in self._SETTERS:
                getattr(sample, self._SETTERS[key])(value or None)
            elif key in self._FIELDS:
                if key == "units":
                    value = int(value) if (value or u"").isdigit() else None
                sample.getField(self._FIELDS[key]).set(sample, value)
        sample.reindexObject()
