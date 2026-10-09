# -*- coding: utf-8 -*-
"""@@pfas-specifications: retired.

The QC acceptance windows are a method profile matter: the method's Recovery
Tiers show them, and a project's Specs page its departures. Old links and
bookmarks land there: with ?project=<id> on that project's Specs page,
otherwise on Method Profiles. Python 2.7.
"""
from __future__ import absolute_import

from bika.lims import api
from Products.Five.browser import BrowserView
from six.moves.urllib.parse import urlencode


class PFASSpecificationsView(BrowserView):

    def __call__(self):
        purl = api.get_portal().absolute_url()
        project = (self.request.form.get("project") or "").strip()
        if project:
            target = "%s/@@pfas-project-specs?%s" % (purl, urlencode({"uid": project.encode("utf-8")}))
        else:
            target = "%s/@@pfas-method-profiles" % purl
        self.request.response.redirect(target)
        return u""
