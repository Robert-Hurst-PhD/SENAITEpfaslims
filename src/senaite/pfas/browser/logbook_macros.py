# -*- coding: utf-8 -*-
"""
Logbook-specific METAL macro provider.

Registered at @@pfas-logbook-macros. Exposes the `logbook_field` macro so the
concise form (logbook_dynamic.pt) and the guided step view (logbook_guided.pt)
render a field identically — CLAUDE.md §6C, define UI once.

Kept separate from @@pfas-macros: that file is site-wide page chrome and
already 1100+ lines; field widgets are a logbook concern.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASLogbookMacrosView(BrowserView):
    """Exposes logbook_field_macros.pt macros to other templates."""

    _template = ViewPageTemplateFile("templates/logbook_field_macros.pt")

    @property
    def macros(self):
        return self._template.macros
