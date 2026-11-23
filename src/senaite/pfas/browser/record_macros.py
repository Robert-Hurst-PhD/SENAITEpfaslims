# -*- coding: utf-8 -*-
"""
The record field macro provider.

Registered at @@pfas-record-macros. Exposes the `logbook_field` macro the
guided extraction (extraction_guide.pt) draws each stage question with.

Kept separate from @@pfas-macros: that file is site-wide page chrome and
already 1100+ lines; field widgets are a record concern.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASRecordMacrosView(BrowserView):
    """Exposes record_macros.pt macros to other templates."""

    _template = ViewPageTemplateFile("templates/record_macros.pt")

    @property
    def macros(self):
        return self._template.macros
