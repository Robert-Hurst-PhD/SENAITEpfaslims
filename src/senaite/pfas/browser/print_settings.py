# -*- coding: utf-8 -*-
"""@@pfas-print-settings — Configuration page for the site-wide print
header/footer (consumed by the shared printhead macro on every printable
form: logbooks, CoC/receipt, SOP copies). Python 2.7 compatible."""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from plone.protect import CheckAuthenticator
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden

from senaite.pfas.print_settings import (
    DEFAULTS, get_print_settings, logo_src, save_print_settings)
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, config_read_only, deny_gated_action, refuse

logger = logging.getLogger("senaite.pfas.browser.print_settings")

# The page is the manager's as a whole (perms.MANAGER_VIEWS); its saves are
# gated again here so the save itself never depends on the page's guard.
PRINT_GATES = {"save": TIER_CONFIG, "save_qualifiers": TIER_CONFIG}


class PFASPrintSettingsView(ViewHelpers, BrowserView):
    template = ViewPageTemplateFile("templates/print_settings.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            action = req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, PRINT_GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            if action == "save_qualifiers":
                return self._handle_save_qualifiers()
            if action == "save":
                return self._handle_save()
        return self.template()

    def settings(self):
        return get_print_settings(self._portal())

    def logo_src(self):
        return logo_src(self.settings(), self.portal_url())

    def qam_tokens_json(self):
        """The Laboratory QAM statement's fill-in parts, for its chip editor."""
        import json
        from senaite.pfas import qs_statement
        return json.dumps([list(t) for t in qs_statement.INTERNAL_TOKEN_LABELS])

    def lab_qam(self):
        """The document marked as the laboratory's QAM, or None."""
        from senaite.pfas.browser.sop_documents import lab_qam
        return lab_qam(self._portal())

    def qam_missing(self):
        """The QAM statement names the QAM but no document is marked."""
        from senaite.pfas import qs_statement
        return qs_statement.uses_qam(self.settings().get(qs_statement.INTERNAL_KEY)) and not self.lab_qam()

    def qapp_tokens_json(self):
        """The QAPP statement's fill-in parts, for its chip editor."""
        import json
        from senaite.pfas import qs_statement
        return json.dumps([list(t) for t in qs_statement.TOKEN_LABELS])

    def director_name(self):
        """The Laboratory Director, set on the Laboratory page, shown here."""
        from senaite.pfas.print_settings import director_staff
        d = director_staff(self._portal())
        return d["fullname"] if d else u""

    def staff(self):
        """Lab staff pool for the QAO selector (initials + name)."""
        from senaite.pfas.staff import list_staff
        return list_staff(self._portal(), active_with_login=True)

    def read_only(self):
        """The page drawn view-only (the inspector reading QC Qualifiers):
        no Save."""
        return config_read_only(self.context)

    def saved(self):
        return self.request.form.get("saved", "") == "1"

    # ── QC qualifier library ─────────────────────────────────────────────────
    # Report configuration, so it lives on the report editor rather than in a
    # page of its own: what a certificate says when QC fails is part of how the
    # certificate is written.

    def qualifier_rows(self):
        """One row per failure type: disposition, code and certificate wording."""
        from senaite.pfas.qc_qualification import (
            get_library, FAILURE_TYPES, QUALIFY, REPORTING_RULES)
        library = get_library(self._portal())
        rows = []
        for key, _label, _disposition, _code in FAILURE_TYPES:
            entry = dict(library[key])
            entry["qualifies"] = entry["disposition"] == QUALIFY
            # a reporting rule: its code and disposition are fixed
            entry["rule"] = key in REPORTING_RULES
            entry["kind"] = False
            rows.append(entry)
        # the kinds of exceedance: a code and a wording, no disposition
        from senaite.pfas.qc_qualification import KIND_KEYS
        for key in KIND_KEYS:
            entry = dict(library[key])
            entry["qualifies"], entry["rule"], entry["kind"] = True, False, True
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
        from senaite.pfas.qc_qualification import KIND_KEYS
        for key in KIND_KEYS:
            data[key] = {"code": (f.get("qual_code.%s" % key) or "").strip(),
                         "statement": (f.get("qual_text.%s" % key) or "").strip()}
        save_library(self._portal(), data)
        return self.request.response.redirect(
            "%s/@@pfas-qc-qualifiers?saved=1" % self.portal_url())

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


class PFASQCQualifiersView(PFASPrintSettingsView):
    """@@pfas-qc-qualifiers — Reporting Setup > QC Qualifiers: what a
    certificate says, and whether the result is held or qualified, when a QC
    criterion fails. Its own tab after Print Settings; saved by the same
    handler (action save_qualifiers)."""
    template = ViewPageTemplateFile("templates/qc_qualifiers.pt")
