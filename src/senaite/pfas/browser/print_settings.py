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
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.print_settings")


class PFASPrintSettingsView(BrowserView):
    template = ViewPageTemplateFile("templates/print_settings.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST" and \
                self.request.form.get("action") == "save_qualifiers":
            return self._handle_save_qualifiers()
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

    def staff(self):
        """Lab staff pool for the QAO / Director selectors (initials + name)."""
        from senaite.pfas.staff import list_staff
        return list_staff(self._portal())

    def saved(self):
        return self.request.form.get("saved", "") == "1"

    # ── QC qualifier library ─────────────────────────────────────────────────
    # Report configuration, so it lives on the report editor rather than in a
    # page of its own: what a certificate says when QC fails is part of how the
    # certificate is written.

    def qualifier_rows(self):
        """One row per failure type: disposition, code and certificate wording."""
        from senaite.pfas.qc_qualification import (
            get_library, FAILURE_TYPES, QUALIFY)
        library = get_library(self._portal())
        rows = []
        for key, _label, _disposition, _code in FAILURE_TYPES:
            entry = dict(library[key])
            entry["qualifies"] = entry["disposition"] == QUALIFY
            rows.append(entry)
        return rows

    def qualifier_dispositions(self):
        from senaite.pfas.qc_qualification import DISPOSITIONS
        return [{"key": k, "label": l, "help": h} for k, l, h in DISPOSITIONS]

    def _handle_save_qualifiers(self):
        from senaite.pfas.qc_qualification import (
            save_library, FAILURE_TYPES, QUALIFY, BLOCK)
        f = self.request.form
        data = {}
        for key, _label, _disposition, _code in FAILURE_TYPES:
            disposition = (f.get("qual_disp.%s" % key) or "").strip()
            data[key] = {
                "disposition": disposition if disposition in (QUALIFY, BLOCK)
                               else None,
                "code": (f.get("qual_code.%s" % key) or "").strip(),
                "statement": (f.get("qual_text.%s" % key) or "").strip(),
            }
        save_library(self._portal(), data)
        return self.request.response.redirect(
            "%s/@@pfas-print-settings?saved=1#qualifiers" % self.portal_url())

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
