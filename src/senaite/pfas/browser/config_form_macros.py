# -*- coding: utf-8 -*-
"""
Declared-section METAL macro provider (config_forms.py, R2).

Registered at @@pfas-config-form-macros. The `section` macro draws one
declared configuration section -- every settings page that migrates to
config_forms renders its fields with this one macro (CLAUDE.md §6C).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASConfigFormMacrosView(BrowserView):
    """Exposes config_form_macros.pt macros to other templates."""

    _template = ViewPageTemplateFile("templates/config_form_macros.pt")

    @property
    def macros(self):
        return self._template.macros
