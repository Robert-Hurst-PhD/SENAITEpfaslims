# -*- coding: utf-8 -*-
"""@@pfas-certificate-pdf?report=<uid>: a stored certificate's PDF, as
the register opens it. Read only (GET). Open to the roles core's own
download gives it to and to the read-only inspector (perms.
CERTIFICATE_READ_ROLES); a client opens their own certificates through
core's download, never this page.

Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

from Products.Five.browser import BrowserView

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import CERTIFICATE_READ_ROLES, has_role_at_portal, refuse

REPORT_TYPE = "ARReport"


class PFASCertificatePDFView(BrowserView):

    def __call__(self):
        flatten_form(self.request)
        if not has_role_at_portal(self.context, CERTIFICATE_READ_ROLES):
            return refuse(self.request)
        from bika.lims import api
        report = api.get_object_by_uid(self.request.form.get("report") or "", default=None)
        if report is None or api.get_portal_type(report) != REPORT_TYPE:
            self.request.response.setStatus(404)
            return "No such certificate."
        pdf = report.getPdf()
        if not pdf or not pdf.get_size():
            self.request.response.setStatus(404)
            return "This certificate has no stored PDF."
        sample = report.getAnalysisRequest()
        name = "%s.pdf" % (api.get_id(sample) if sample is not None else api.get_id(report))
        from senaite.pfas.browser.view_helpers import send_pdf
        self.request.response.setHeader(str("Cache-Control"), str("no-store"))
        return send_pdf(self.request.response, pdf.data, name, inline=True)
