# -*- coding: utf-8 -*-
"""@@pfas-tour: the system tour, ten stops through the lab's work (tour.py).
One stop is shown at a time (?stop=<key>) with the rail of all ten, so the
page needs no script. A stop's target the person cannot open is shown as
unavailable with the reason. Read-only: a view writes nothing.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import tour
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.tour")


class PFASTourView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/pfas_tour.pt")

    def __call__(self):
        flatten_form(self.request)
        if not tour.visible_to(self._roles()):
            from zExceptions import Unauthorized
            raise Unauthorized("The tour is for laboratory staff.")
        return self.template()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _roles(self):
        portal = self._portal()
        try:
            return list(getSecurityManager().getUser().getRolesInContext(portal))
        except Exception:                                   # noqa: BLE001
            return []

    def _overrides(self):
        from zope.annotation.interfaces import IAnnotations
        return tour.load(IAnnotations(self._portal()).get(tour.KEY))

    def _can_open(self, path):
        """True when the person's own traversal reaches the page's objects
        (tour.traversal_check); None when there is nothing at that path."""
        return tour.traversal_check(self._portal().restrictedTraverse, path)

    def stops(self):
        """The ten stops, each target with `url`, `ok` and `why`."""
        if not hasattr(self, "_stops"):
            roles, base = self._roles(), self.portal_url()
            out = tour.stops(self._overrides())
            for stop in out:
                for t in stop["targets"]:
                    t["ok"], t["why"] = tour.availability(t["path"], roles, self._can_open)
                    t["url"] = u"%s/%s" % (base, t["path"])
                    t["dom"] = u"why-" + t["key"].replace(".", "-")
            self._stops = out
        return self._stops

    def position(self):
        keys = list(tour.STOP_KEYS)
        want = (self.request.form.get("stop") or u"").strip()
        return keys.index(want) if want in keys else 0

    def rail(self):
        """The ten steps for the rail, with the link, number and state."""
        here, base = self.position(), self.portal_url()
        return [{"n": i + 1, "key": s["key"], "title": s["title"], "icon": s["icon"],
                 "url": u"%s/@@pfas-tour?stop=%s" % (base, s["key"]),
                 "state": "now" if i == here else ("done" if i < here else "next")}
                for i, s in enumerate(self.stops())]

    def current(self):
        return self.stops()[self.position()]

    def neighbours(self):
        here, base = self.position(), self.portal_url()
        keys = tour.STOP_KEYS
        return {"prev": (u"%s/@@pfas-tour?stop=%s" % (base, keys[here - 1])) if here else None,
                "next": (u"%s/@@pfas-tour?stop=%s" % (base, keys[here + 1])) if here + 1 < len(keys) else None,
                "n": here + 1, "of": len(keys)}
