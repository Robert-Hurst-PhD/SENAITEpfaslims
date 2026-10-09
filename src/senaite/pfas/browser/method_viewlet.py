# -*- coding: utf-8 -*-
"""
Reverse bridge add-in: a panel on the core SENAITE Method view that links back
to its PFAS method profile (QC ranges / tiers / tolerances).

The forward direction (profile → core Method) is shown on the PFAS Method
Profiles page. This is the other side: standing on a proper core Method record,
jump to the intuitive PFAS profile that governs its QC. Rendered as an
upgrade-safe viewlet on ISenaitePFASLayer — no core template is forked.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.app.layout.viewlets.common import ViewletBase

logger = logging.getLogger("senaite.pfas.method_viewlet")


class PFASMethodProfileViewlet(ViewletBase):
    """Shows the linked PFAS method profile (if any) on a core Method view."""

    index = ViewPageTemplateFile("templates/method_profile_viewlet.pt")

    def update(self):
        super(PFASMethodProfileViewlet, self).update()
        self.profile_id = None
        self.profile_title = None
        self.n_services = 0
        self.n_sampletypes = 0
        self.edit_url = None
        try:
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            from senaite.pfas.method_bridge import (
                get_profile_id_for_method, get_association)
            pid = get_profile_id_for_method(portal, self.context)
            if not pid:
                return
            assoc = get_association(portal, pid)
            from senaite.pfas.method_profile_store import get_profile
            prof = get_profile(portal, pid)
            self.profile_id = pid
            self.profile_title = prof.get("display_name", pid)
            self.n_services = len(assoc.get("service_uids", []))
            self.n_sampletypes = len(assoc.get("sampletype_uids", []))
            self.edit_url = "{0}/@@pfas-method-profile-edit?method_id={1}".format(
                portal.absolute_url(), pid)
        except Exception as exc:
            logger.warning("method profile viewlet failed: %s", exc)

    def render(self):
        # Render nothing for core Methods that have no PFAS profile.
        if not self.profile_id:
            return u""
        return self.index()
