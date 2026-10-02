# -*- coding: utf-8 -*-
"""
PFAS Extraction Logbook PDF (@@pfas-extraction-pdf).

The extraction session stored on the Batch (extraction_guide._load_session)
rendered as a print document by WeasyPrint -- the engine senaite.impress
already ships and the settings report uses (docs/REUSE_REVIEW.md U1). It
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
        batch = brains[0].getObject()

        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas.method_profile_store import get_profile
        session = _load_session(batch)
        if not session:
            self.request.response.setStatus(404)
            return "No extraction session found for this batch"
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        profile = get_profile(portal, session.get("method_id", "FDA_32PFAS"))
        batch_id = batch.getId() if hasattr(batch, "getId") else u"extraction"
        self.data = logbook_data(batch_id, batch.Title() if hasattr(batch, "Title") else u"",
                                 session, profile,
                                 datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
        try:
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
