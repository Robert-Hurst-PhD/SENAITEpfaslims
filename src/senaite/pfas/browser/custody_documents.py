# -*- coding: utf-8 -*-
"""Print the designed Chain of Custody and controlled-document cover
(custody_documents.py).

    <batch or worksheet>/@@pfas-coc-document   its samples' CoC
    @@pfas-sop-cover?sop_id=SOP-001            a controlled document's cover

Both print only from an ISSUED design (Document Templates): there is no
older layout to fall back to, so with none issued the page says so.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging
from datetime import datetime

from bika.lims import api
from Products.Five.browser import BrowserView

from senaite.pfas import custody_documents as cus
from senaite.pfas import homogenisation as hg

logger = logging.getLogger("senaite.pfas.custody_documents")


def _when(dt_value):
    """'YYYY-MM-DD HH:MM' of a DateTime, or ''."""
    try:
        return dt_value.strftime("%Y-%m-%d %H:%M") if dt_value else u""
    except Exception:                                       # noqa: BLE001
        return u"%s" % (dt_value or u"")


def _title(obj):
    try:
        return api.get_title(obj) if obj is not None else u""
    except Exception:                                       # noqa: BLE001
        return u""


def sample_row(sample, methods):
    """One CoC row from the sample record (one owner per fact)."""
    req = hg.sample_request(sample)
    analyses = sorted(set(_title(an.getMethod()) or an.Title()
                          for an in sample.getAnalyses(full_objects=True)))
    return {
        "sample_id": sample.getId(),
        "client_sid": sample.getClientSampleID() or u"",
        "sampling_point": _title(sample.getSamplePoint()),
        "matrix": sample.getSampleTypeTitle() or u"",
        "sampled": _when(sample.getDateSampled()),
        "containers": _title(sample.getContainer()),
        "preservative": _title(sample.getPreservation()),
        "analyses": u", ".join(a for a in analyses if a),
        "homogenisation": hg.title_of(methods, req["method"]) if req["method"] else u"",
        "composite": hg.composite_line(req["composite"], req["units"], req["description"]),
    }


def _pdf(view, kind, data, name):
    from senaite.pfas.browser.report_designs import DesignedReportError, designed_pdf
    resp = view.request.response
    try:
        pdf = designed_pdf(kind, data)
    except DesignedReportError as exc:
        resp.setStatus(500)
        return u"%s" % exc
    if pdf is None:
        resp.setHeader("Content-Type", "text/plain; charset=utf-8")
        return (u"No %s design is issued. Issue one under Reporting > Document Templates."
                % cus_title(kind))
    resp.setHeader("Content-Type", "application/pdf")
    resp.setHeader("Content-Disposition", "inline; filename=%s.pdf" % name)
    return pdf


def cus_title(kind):
    from senaite.pfas import document_templates as dt
    return dt.KINDS[kind]["title"]


def _printed():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


class PFASCoCDocumentView(BrowserView):
    """The CoC of a batch's or worksheet's samples."""

    def data(self):
        from senaite.pfas import extraction_batch
        from senaite.pfas.browser.doc_people import _lab
        from senaite.pfas.browser.logbooks import _get_logbook
        from senaite.pfas.core_fields import samples_of
        methods = hg.load_methods(api.get_portal())
        samples = sorted(samples_of(self.context), key=lambda s: s.getId())
        record = {}
        for holder in (extraction_batch.home(self.context), self.context):
            record = _get_logbook(holder, "coc") or {}
            if record:
                break
        record = dict(record)
        record.setdefault("coc_id", self.context.getId())
        # the client and contact are SENAITE's (the samples' own); the CoC
        # record's typed client name only when no sample names one
        if samples:
            client, contact = samples[0].getClient(), samples[0].getContact()
            if client is not None:
                record["client_name"] = api.get_title(client)
            if contact is not None:
                record["contact"] = contact.getFullname()
                record["contact_phone"] = (contact.getBusinessPhone() or
                                           contact.getMobilePhone() or u"")
                record["contact_email"] = contact.getEmailAddress() or u""
        return cus.coc_data(record, [sample_row(s, methods) for s in samples], _lab(), _printed())

    def __call__(self):
        from senaite.pfas.core_fields import samples_of
        numbers = set((s.getField("CoCNumber").get(s) or u"") for s in samples_of(self.context))
        if len(numbers) == 1 and list(numbers)[0]:
            # the samples came in on one CoC: print that record (CW5)
            self.request.response.redirect(u"%s/@@pfas-coc-print?coc=%s"
                                           % (api.get_portal().absolute_url(), list(numbers)[0]))
            return u""
        return _pdf(self, "coc", self.data(), "%s-coc" % self.context.getId())


def coc_print_data(record):
    """The printed CoC of a CoC record: its samples' rows (from the sample
    records), the contact from SENAITE, the laboratory (CW5)."""
    from senaite.pfas.browser.doc_people import _lab
    methods = hg.load_methods(api.get_portal())
    samples = [api.get_object_by_uid(u, None) for u in record.get("samples") or []]
    samples = sorted([s for s in samples if s is not None], key=lambda s: s.getId())
    rows = []
    for s in samples:
        row = sample_row(s, methods)
        row["field_qc"] = s.getField("FieldQCType").get(s) or u""
        row["field_qc_of"] = s.getField("FieldQCOf").get(s) or u""
        rows.append(row)
    record = dict(record)
    if samples and samples[0].getContact() is not None:
        c = samples[0].getContact()
        record.update(contact=c.getFullname(), contact_email=c.getEmailAddress() or u"",
                      contact_phone=c.getBusinessPhone() or c.getMobilePhone() or u"")
    return cus.coc_record_data(record, rows, _lab(), _printed())


class PFASCoCPrintView(BrowserView):
    """@@pfas-coc-print?coc=COC-…: the CoC as recorded, or blank for a kit
    (no samples yet). Client-safe: a client prints only their own CoC."""

    def __call__(self):
        from senaite.pfas import coc_records as cr
        from senaite.pfas.browser.perms import is_staff
        num = (self.request.form.get("coc") or u"").strip()
        rec = cr.load(api.get_portal(), num) if num else None
        if rec is not None and not is_staff(api.get_portal()):
            client = api.get_current_client()
            if client is None or api.get_uid(client) != rec.get("client_uid"):
                rec = None
        if rec is None:
            self.request.response.setStatus(404)
            return u"No CoC %s." % num
        return _pdf(self, "coc", coc_print_data(rec), num)


class PFASSOPCoverView(BrowserView):
    """A controlled document's cover page and page header."""

    def data(self, sop_id):
        from senaite.pfas.browser import sop_documents as sd
        from senaite.pfas.browser.doc_people import _lab
        portal = api.get_portal()
        entry = [e for e in sd._get_registry(portal) if e.get("sop_id") == sop_id]
        if not entry:
            return None
        entry = dict(entry[0])
        entry["method_label"] = sd.method_label(entry.get("method_slug"))
        revs = sd._get_revisions(portal, sop_id)
        names = {}
        for r in revs:
            for k in ("uploaded_by", "activated_by"):
                uid = r.get(k)
                if uid and uid not in names:
                    user = api.get_user(uid)
                    names[uid] = (user.getProperty("fullname") or uid) if user else uid
        return cus.sop_data(entry, revs, _lab(), _printed(), names)

    def __call__(self):
        sop_id = (self.request.form.get("sop_id") or u"").strip()
        data = self.data(sop_id) if sop_id else None
        if data is None:
            self.request.response.setStatus(404)
            return u"No controlled document %s." % sop_id
        return _pdf(self, "sop_cover", data, "%s-cover" % sop_id)
