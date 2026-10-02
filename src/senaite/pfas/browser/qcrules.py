# -*- coding: utf-8 -*-
"""
@@pfas-qc-rules -- kept as an address only: it redirects to Method Profiles.

The rule switches and every QC limit live on each method profile (QC
consolidation P2, DECISIONS 2026-10-02); qc_rules.json keeps only control
chart presentation. The old editor (and its POST, which wrote criteria and
switches into qc_rules.json) is gone so nothing can write a second copy.

Python 2.7-compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView


class PFASQCRulesView(BrowserView):

    def __call__(self):
        portal = self.context.portal_url.getPortalObject()
        self.request.response.redirect(portal.absolute_url() + "/@@pfas-method-profiles")
        return u""
