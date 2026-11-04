# -*- coding: utf-8 -*-
"""The sample page, tidied without forking core; each
is a viewlet or view registered on the PFAS layer over core's, listed in
A core template override, listed in the decisions record with its upgrade risk:

  * Attachments is its own tab (@@pfas-sample-attachments) instead of the
    collapsed button under the title (core's AttachmentsViewlet, shown there)
  * the analyses list folds to one line saying what it holds; it opens on
    request (core's registry switch collapses it; the title is ours)
  * the results interpretation reads "Comments on the certificate"

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core.browser.viewlets.attachments import AttachmentsViewlet
from senaite.core.browser.viewlets.resultsinterpretation import ResultsInterpretationViewlet
from senaite.core.browser.viewlets.sampleanalyses import LabAnalysesViewlet


class PFASSampleAttachmentsViewlet(AttachmentsViewlet):
    """Not under the sample's title: Attachments is a tab of its own."""

    def render(self):
        return u""


class PFASSampleAttachmentsView(BrowserView):
    """@@pfas-sample-attachments: core's attachments panel, open, as a tab."""
    template = ViewPageTemplateFile("templates/sample_attachments.pt")

    def __call__(self):
        return self.template()

    def panel(self):
        self.request.set("show_attachments", "1")
        v = AttachmentsViewlet(self.context, self.request, self, None)
        v.update()
        return v.template()


class PFASLabAnalysesViewlet(LabAnalysesViewlet):
    """The sample's analyses, folded to one line that says what they are."""

    @property
    def title(self):
        n = len(self.sample.getAnalyses(getPointOfCapture=self.capture))
        panel = u""
        try:
            profiles = self.sample.getProfiles() or []
            panel = u", ".join(api.get_title(p) for p in profiles)
            if not panel and self.sample.getTemplate() is not None:
                panel = api.get_title(self.sample.getTemplate())
        except Exception:                                   # noqa: BLE001
            panel = u""
        parts = [u"Analyses", u"%d analyte%s" % (n, u"" if n == 1 else u"s")]
        if panel:
            parts.append(u"%s panel" % panel)
        parts.append(u"set by the method")
        return u" · ".join(parts)


class PFASWorksheetOpenView(BrowserView):
    """@@pfas-ws-open: a worksheet's default view (the type's "(Default)"
    alias, setuphandlers.worksheet_opens_on_review): its Data Review. Core's
    results grid stays as the "Results entry" tab (manage_results)."""

    def __call__(self):
        url = u"%s/@@pfas-data-review?batch_id=%s" % (api.get_portal().absolute_url(), self.context.getId())
        self.request.response.redirect(url)
        return u""


class PFASResultsInterpretationViewlet(ResultsInterpretationViewlet):
    """Core's results interpretation, named for what it does: printed on the
    sample's certificate, under each department's heading."""
    index = ViewPageTemplateFile("templates/resultsinterpretation.pt")
    title = u"Comments on the certificate"
