# -*- coding: utf-8 -*-
"""
QC Rules editor browser view — accessible to users with the Manager role.

Registered at @@pfas-qc-rules on the SENAITE portal.
Reads and writes /data/qc/qc_rules.json via QCRulesStore.

Python 2.7-compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

logger = logging.getLogger("senaite.pfas.browser.qcrules")


def _check_manager(context, request):
    """Return True if the current user has the Manager role."""
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        roles = user.getRolesInContext(context)
        return "Manager" in roles or "LabManager" in roles
    except Exception:
        return False


class PFASQCRulesView(BrowserView):
    """
    Manager view for editing the PFAS QC acceptance criteria.

    GET  — render the rules editor form.
    POST — save submitted rules and redirect back with a status message.
    """

    template = ViewPageTemplateFile("templates/qcrules.pt")

    def __call__(self):
        if not _check_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden: Manager role required"

        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    # ── Template helpers ──────────────────────────────────────────────────────

    def rules(self):
        from senaite.pfas.qc.rules import get_rules
        return get_rules()

    def rules_json(self):
        return json.dumps(self.rules(), indent=2, sort_keys=True)

    def qc_types(self):
        return sorted(self.rules().get("qc_types", {}).keys())

    def global_fields(self):
        return [{"key": k, "value": v}
                for k, v in sorted(self.rules().get("global", {}).items())]

    def qc_type_fields(self, qtype):
        r = self.rules()
        return [{"key": k, "value": v}
                for k, v in sorted(r.get("qc_types", {}).get(qtype, {}).items())]

    def qc_label(self, qtype):
        r = self.rules()
        return r.get("qc_types", {}).get(qtype, {}).get("label", qtype)

    def chart_type(self, qtype):
        r = self.rules()
        return r.get("qc_types", {}).get(qtype, {}).get("chart_type", "levey_jennings")

    # ── Salt factor helpers ───────────────────────────────────────────────────

    def salt_matrices(self):
        """Return sorted list of matrix keys."""
        from senaite.pfas.qc.rules import get_store
        return get_store().matrix_names()

    def salt_factor_rows(self):
        """
        Return a list of dicts suitable for TAL iteration.
        Each dict: {matrix, default, note, overrides: [{key, value}, ...]}
        """
        r = self.rules()
        sf = r.get("salt_factors", {})
        rows = []
        for matrix in sorted(sf.keys()):
            mdict = sf[matrix]
            overrides = [
                {"key": k, "value": v}
                for k, v in sorted(mdict.items())
                if k not in ("default", "note")
            ]
            rows.append({
                "matrix":    matrix,
                "default":   mdict.get("default", 1.0),
                "note":      mdict.get("note", ""),
                "overrides": overrides,
            })
        return rows

    def save_message(self):
        return self.request.get("saved", "")

    def rules_path(self):
        from senaite.pfas.qc.rules import get_store
        return get_store().path

    # ── POST handler ──────────────────────────────────────────────────────────

    def _handle_post(self):
        req = self.request

        # Accept a raw JSON body (from AJAX) or a form field 'rules_json'
        raw = req.get("rules_json", "")
        if not raw:
            try:
                raw = req.stdin.read()
            except Exception:
                pass

        if not raw:
            self.request.response.setStatus(400)
            return "No rules data received"

        try:
            new_rules = json.loads(raw)
        except ValueError as exc:
            self.request.response.setStatus(400)
            return "Invalid JSON: {}".format(exc)

        # Get current user identity
        try:
            from AccessControl import getSecurityManager
            user_id = getSecurityManager().getUser().getId()
        except Exception:
            user_id = "unknown"

        try:
            from senaite.pfas.qc.rules import get_store
            get_store().save(new_rules, updated_by=user_id)
        except Exception as exc:
            logger.error("Failed to save QC rules: %s", exc)
            self.request.response.setStatus(500)
            return "Save failed: {}".format(exc)

        # Redirect back to form with success indicator
        url = "{}/@@pfas-qc-rules?saved=1".format(
            self.context.absolute_url()
        )
        self.request.response.redirect(url)
        return ""
