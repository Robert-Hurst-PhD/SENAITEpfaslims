# -*- coding: utf-8 -*-
"""
PFAS shared page-chrome macros view.

Registered at @@pfas-macros.  All PFAS full-page templates access the
shared METAL macro via:

    metal:use-macro="context/@@pfas-macros/macros/page"

The macro defines slots:
  title          -- <title> element text (browser tab)
  head-extra     -- additional <head> content (scripts, page-specific <style>)
  header-title   -- <h1> inner content
  header-right   -- badge / back-link area to the right of the h1
  content        -- the main page body

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASMacrosView(BrowserView):
    """Exposes pfas_macros.pt macros for use by other PFAS page templates."""

    _template = ViewPageTemplateFile("templates/pfas_macros.pt")

    @property
    def macros(self):
        return self._template.macros

    def portal_url(self):
        return self.context.portal_url.getPortalObject().absolute_url()
