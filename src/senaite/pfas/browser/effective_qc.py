# -*- coding: utf-8 -*-
"""@@pfas-effective-qc: every QC check of one method in one matrix with the
limits that apply and the level that set each (effective_qc.py holds the
rows). Read only: it posts nothing. Python 2.7."""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import effective_qc as eq
from senaite.pfas import method_profile_store
from senaite.pfas.browser.perms import refuse, require_manager


class PFASEffectiveQCView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/effective_qc.pt")

    def __call__(self):
        if not require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden: Manager, LabManager, or Owner role required")
        return self.template()

    def method_ids(self):
        return list(method_profile_store.list_method_ids(api.get_portal()))

    def method_id(self):
        mid = (self.request.form.get("method") or "").strip()
        ids = self.method_ids()
        return mid if mid in ids else (ids[0] if ids else u"")

    def profile(self):
        mid = self.method_id()
        return method_profile_store.get_profile(api.get_portal(), mid) if mid else {}

    def matrices(self):
        return list(self.profile().get("supported_matrices") or [])

    def matrix(self):
        matrix = (self.request.form.get("matrix") or "").strip()
        options = self.matrices()
        return matrix if matrix in options else (options[0] if options else u"")

    def only_overrides(self):
        return (self.request.form.get("only") or "") == "overrides"

    def filter_links(self):
        """The show-inherited / only-overrides strip, each choice a link that
        keeps the method and the matrix."""
        try:
            from urllib import urlencode
        except ImportError:
            from urllib.parse import urlencode
        out = []
        for value, label in (("", u"Show inherited"), ("overrides", u"Only overrides")):
            q = [("method", self.method_id().encode("utf-8")), ("matrix", self.matrix().encode("utf-8"))]
            if value:
                q.append(("only", value))
            out.append({"label": label, "on": value == ("overrides" if self.only_overrides() else ""),
                        "url": u"%s/@@pfas-effective-qc?%s" % (self.portal_url(), urlencode(q))})
        return out

    def editor_url(self):
        return u"%s/@@pfas-method-profile-edit?method_id=%s" % (self.portal_url(), self.method_id())

    def sheet(self):
        return eq.effective_sheet(self.profile(), self.matrix(), only_overrides=self.only_overrides())
