# -*- coding: utf-8 -*-
"""@@pfas-report-tiers - Reporting Setup > Report tiers: the lab's catalogue
of report tiers, each a named list of the parts a report package holds.
Python 2.7 compatible."""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from plone.protect import CheckAuthenticator
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden

from senaite.pfas import report_tiers as rt
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, deny_gated_action, refuse
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.browser.report_tiers")

# The page is the manager's as a whole (perms.MANAGER_VIEWS); its writes are
# gated again here so a save never depends on the page's guard.
GATES = {"save": TIER_CONFIG, "remove": TIER_CONFIG, "add": TIER_CONFIG}


class PFASReportTiersView(ViewHelpers, BrowserView):
    template = ViewPageTemplateFile("templates/report_tiers.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        self._problems = []
        self._rows = None
        if req.method == "POST":
            action = "remove" if "remove" in req.form else req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            if action in ("save", "remove", "add"):
                return self._handle_post(action)
        return self.template()

    def saved(self):
        return self.request.form.get("saved", "") == "1"

    def problems(self):
        return self._problems

    def parts(self):
        return [{"key": k, "label": l} for k, l, _s in rt.PARTS]

    def scopes(self):
        return [{"key": k, "label": l} for k, l in rt.SCOPES]

    def tiers(self):
        """The cards to draw: the page as posted when it is shown again,
        else the catalogue."""
        rows = self._rows if self._rows is not None else rt.get_catalogue(self._portal())
        out = []
        for t in rows:
            keys = [p.get("key") for p in t.get("parts") or []]
            scope = [p.get("scope") for p in t.get("parts") or []
                     if p.get("key") == "chromatograms"]
            out.append({"id": t.get("id", ""), "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "keys": keys, "scope": (scope or [None])[0] or "sample"})
        return out

    def client_defaults(self):
        """Each client's default tier, with the way to its Client reporting
        page where it is set."""
        from senaite.pfas import edd_store
        portal = self._portal()
        folder = portal.get("clients")
        clients = [(c.Title(), c) for c in (folder.objectValues() if folder is not None else [])
                   if getattr(c, "portal_type", None) == "Client"]
        rows = rt.client_defaults(clients, edd_store.get_client_settings, rt.get_catalogue(portal))
        for r in rows:
            r["url"] = u"%s/@@pfas-edd-client-config" % r.pop("obj").absolute_url()
        return rows

    def _handle_post(self, action):
        portal = self._portal()
        form = self.request.form
        catalogue = rt.from_form(form)
        if action == "add":
            self._rows = catalogue + [{"id": "", "name": "", "description": "",
                                       "parts": []}]
            return self.template()
        if action == "remove":
            tier_id = (form.get("tier_id.%s" % form.get("remove")) or "").strip()
            using = rt.in_use(portal, tier_id)
            if using:
                self._rows = catalogue
                self._problems = [u"Tier %s is in use: %s"
                                  % (tier_id, u", ".join(using))]
                return self.template()
            catalogue = [t for t in catalogue if t.get("id") != tier_id]
        found = rt.save_catalogue(portal, catalogue)
        if found:
            self._rows = catalogue
            self._problems = found
            return self.template()
        logger.info("report tiers saved")
        self.request.response.redirect(
            "%s/@@pfas-report-tiers?saved=1" % self.portal_url())
        return u""
