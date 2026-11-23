# -*- coding: utf-8 -*-
"""The Make dialog of a dilution or re-injection Data Review asked for,
shared by Run Builder's step 4 and the guided extraction's Dilutions stage
(senaite.pfas.dilution_make holds what it lists and how it is made).

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASDilutionMakeMacrosView(BrowserView):
    """The Make dialog, shared by Run Builder and the guided extraction."""

    _template = ViewPageTemplateFile("templates/dilution_make_macros.pt")

    @property
    def macros(self):
        return self._template.macros
