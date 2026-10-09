# -*- coding: utf-8 -*-
"""
PFAS Extraction Logbook PDF (@@pfas-extraction-pdf).

The extraction session stored on the Batch (extraction_guide._load_session)
rendered as a print document by WeasyPrint -- the engine senaite.impress
already ships and the settings report uses. It
replaced a ReportLab build that could not run here: ReportLab was never
installed in the SENAITE image, so the view answered 500 at the end of every
guided extraction.

senaite.pfas.extraction_logbook.logbook_data() is pure (session + profile ->
the sections the document prints); the template lays them out. Python 2.7
compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging
from datetime import datetime

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.extraction_pdf")

from senaite.pfas.extraction_logbook import logbook_data


class PFASExtractionPDFView(BrowserView):
    """Render the extraction logbook to PDF with WeasyPrint."""

    print_template = ViewPageTemplateFile("templates/extraction_pdf.pt")

    def __call__(self):
        flatten_form(self.request)
        uid = self.request.form.get("batch_uid", "")
        if not uid:
            self.request.response.setStatus(400)
            return "batch_uid parameter required"
        brains = getToolByName(self.context, "uid_catalog")(UID=uid)
        if not brains:
            self.request.response.setStatus(404)
            return "Batch not found"
        from senaite.pfas import extraction_batch
        batch = extraction_batch.home(brains[0].getObject())   # the worksheet

        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas.method_profile_store import get_profile
        session = _load_session(batch)
        if not session:
            self.request.response.setStatus(404)
            return "No extraction session found for this batch"
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        profile = get_profile(portal, session.get("method_id", "FDA_32PFAS"))
        batch_id = batch.getId() if hasattr(batch, "getId") else u"extraction"
        from senaite.pfas import extraction_batch
        from senaite.pfas.browser.logbooks import _get_logbook
        members = extraction_batch.load(batch)
        by_id = dict((m["id"], m) for m in members)
        # the batch's QC members (extraction_batch.py); older spike rows else
        spike_rows = [{"sample_id": m.get("injection"), "qc_type": m.get("role"),
                       "spike_of": (by_id.get(m.get("parent")) or {}).get("injection") or u"",
                       "spike_amount": m.get("amount") or u"", "spike_unit": m.get("unit") or u"",
                       "level": m.get("level") or u"", "logged_by": m.get("added_by") or u"",
                       "logged_at": m.get("added_at") or u""}
                      for m in members if m.get("role") != u"Sample"] or \
            ((_get_logbook(batch, "252") or {}).get("spikes") or [])
        from senaite.pfas.extraction_logbook import roster
        log = _get_logbook(batch, "252") or {}
        if members and log.get("samples"):
            log = dict(log, samples=extraction_batch.rekey_rows(log["samples"], members))
        self.data = logbook_data(batch_id, batch.Title() if hasattr(batch, "Title") else u"",
                                 session, profile,
                                 datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                                 spike_rows=spike_rows,
                                 extracted=roster(members, log.get("samples"),
                                                  log.get("spe_ports")))
        # an issued design (Document Templates) is the extraction log from then on
        from senaite.pfas import report_documents
        from senaite.pfas.browser.report_designs import DesignedReportError, designed_pdf
        try:
            # the extraction analyst prepares, the reviewing analyst reviews
            pdf = designed_pdf("extraction_log", report_documents.extraction_data(self.data),
                               people={"preparer": (session.get("analyst"), session.get("started_at") or u""),
                                       "reviewer": (session.get("finalized_by"),
                                                    session.get("finalized_at") or u"")})
        except DesignedReportError as exc:
            self.request.response.setStatus(500)
            return u"%s" % exc
        try:
            if pdf is None:
                from weasyprint import HTML
                pdf = HTML(string=self.print_template()).write_pdf()
        except Exception as exc:                            # noqa: BLE001
            logger.exception("extraction PDF failed")
            self.request.response.setStatus(500)
            return "PDF generation error: {0}".format(exc)
        resp = self.request.response
        resp.setHeader("Content-Type", "application/pdf")
        resp.setHeader("Content-Disposition",
                       'attachment; filename="pfas_extraction_{0}.pdf"'.format(batch_id))
        return pdf
