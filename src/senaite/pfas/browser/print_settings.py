# -*- coding: utf-8 -*-
"""@@pfas-print-settings — Configuration page for the site-wide print
header/footer (consumed by the shared printhead macro on every printable
form: logbooks, CoC/receipt, SOP copies). Python 2.7 compatible."""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.print_settings import (
    DEFAULTS, get_print_settings, save_print_settings)

logger = logging.getLogger("senaite.pfas.browser.print_settings")


class PFASPrintSettingsView(BrowserView):
    template = ViewPageTemplateFile("templates/print_settings.pt")

    def __call__(self):
        if self.request.method == "POST" and \
                self.request.form.get("action") == "save":
            return self._handle_save()
        return self.template()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return self._portal().absolute_url()

    def settings(self):
        return get_print_settings(self._portal())

    def saved(self):
        return self.request.form.get("saved", "") == "1"

    def _handle_save(self):
        f = self.request.form
        data = {}
        for key, default in DEFAULTS.items():
            if isinstance(default, bool):
                data[key] = f.get(key, "") in ("on", "true", "1")
            else:
                data[key] = (f.get(key, "") or "").strip()
        save_print_settings(self._portal(), data)
        logger.info("print settings saved")
        self.request.response.redirect(
            "%s/@@pfas-print-settings?saved=1" % self.portal_url())
        return u""
