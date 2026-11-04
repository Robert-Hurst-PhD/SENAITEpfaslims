# -*- coding: utf-8 -*-
"""
The method profile's grid macro provider (profile_grids.py).

Registered at @@pfas-grid-macros. The `sheet` macro draws one grid model
(profile_grids.Sheet): every tab that is a grid is drawn by this one macro,
which hands the model to the one renderer.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.profile_grids import render_sheet


class PFASGridMacrosView(BrowserView):
    """Exposes grid_macros.pt macros, and the renderer they call."""

    _template = ViewPageTemplateFile("templates/grid_macros.pt")

    @property
    def macros(self):
        return self._template.macros

    def render(self, view, sheet):
        return render_sheet(view, sheet)
