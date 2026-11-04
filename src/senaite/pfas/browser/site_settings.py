# -*- coding: utf-8 -*-
"""@@pfas-site-settings: the old Site Settings address. Its settings moved to
Laboratory, Time & Language and System; bookmarks and links still arrive.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from Products.Five.browser import BrowserView

from senaite.pfas.browser.view_helpers import ViewHelpers


class PFASSiteSettingsRedirect(ViewHelpers, BrowserView):

    def __call__(self):
        return self._redirect("%s/@@pfas-laboratory" % self.portal_url())
