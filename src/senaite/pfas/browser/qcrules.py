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

# Human-readable labels and units for the "global" rules section.
# Any key not in this map falls back to the raw key as the label.
GLOBAL_PARAM_META = {
    "cal_r2_min":                {"label": u"Calibration r² Minimum",                  "unit": ""},
    "is_response_pct":           {"label": "IS Response Max Deviation",                       "unit": "%"},
    "rt_tolerance_min":          {"label": "RT Tolerance (absolute)",                         "unit": "min"},
    "rt_tolerance_pct":          {"label": "RT Tolerance (relative)",                         "unit": "%"},
    "sn_min":                    {"label": "S/N Minimum (detection)",                         "unit": ""},
    "sn_quan_min":               {"label": "S/N Minimum (quantitation)",                      "unit": ""},
    "rpd_max":                   {"label": "Max RPD",                                         "unit": "%"},
    "qq_ratio_matching_pct":     {"label": u"Ion Ratio Tolerance — Isotopic Match",      "unit": "%"},
    "qq_ratio_key_pct":          {"label": u"Ion Ratio Tolerance — Key Analytes",        "unit": "%"},
    "qq_ratio_non_iso_pct":      {"label": u"Ion Ratio Tolerance — Non-Isotopic",        "unit": "%"},
    "cal_pct_deviation_default": {"label": "Calibration % Deviation (default)",               "unit": "%"},
    "cal_pct_deviation_tight":   {"label": "Calibration % Deviation (tight, inner bracket)",  "unit": "%"},
    "cal_pct_deviation_loose":   {"label": "Calibration % Deviation (loose, outer bracket)",  "unit": "%"},
}

# Human-readable labels and units for per-QC-type field keys.
QC_TYPE_FIELD_META = {
    "pct_deviation_max":        {"label": "Max % Deviation",                   "unit": "%"},
    "pct_deviation_warn":       {"label": "Warn % Deviation",                  "unit": "%"},
    "recovery_min":             {"label": "Min Recovery",                      "unit": "%"},
    "recovery_max":             {"label": "Max Recovery",                      "unit": "%"},
    "recovery_warn_low":        {"label": "Recovery Warn Low",                 "unit": "%"},
    "recovery_warn_high":       {"label": "Recovery Warn High",                "unit": "%"},
    "threshold":                {"label": "Threshold Concentration",           "unit": ""},
    "threshold_units":          {"label": "Threshold Units",                   "unit": ""},
    "rpd_max":                  {"label": "Max RPD",                           "unit": "%"},
    "recovery_min_key_matrix":  {"label": "Min Recovery (key analyte/matrix)", "unit": "%"},
    "recovery_max_key_matrix":  {"label": "Max Recovery (key analyte/matrix)", "unit": "%"},
}


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
        meta = GLOBAL_PARAM_META
        return [
            {
                "key":   k,
                "value": v,
                "label": meta.get(k, {}).get("label", k),
                "unit":  meta.get(k, {}).get("unit", ""),
            }
            for k, v in sorted(self.rules().get("global", {}).items())
        ]

    def qc_type_fields(self, qtype):
        r = self.rules()
        qt_data = r.get("qc_types", {}).get(qtype, {})
        stored_threshold_units = qt_data.get("threshold_units", "")
        fields = []
        for k, v in sorted(qt_data.items()):
            meta = QC_TYPE_FIELD_META.get(k, {})
            unit = meta.get("unit", "")
            if k == "threshold" and not unit:
                unit = stored_threshold_units
            fields.append({
                "key":   k,
                "value": v,
                "label": meta.get("label", k),
                "unit":  unit,
            })
        return fields

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

    # ── Toggle grid helpers ───────────────────────────────────────────────────

    def methods(self):
        from senaite.pfas.qc.rules import METHODS
        return METHODS

    def rule_library(self):
        from senaite.pfas.qc.rules import RULE_LIBRARY
        return RULE_LIBRARY

    def toggle_grid(self):
        """
        Return list of row dicts for the toggle grid (one per rule).
        Each row: {rule_key, rule_label, has_params, states: [per-method...]}
        """
        from senaite.pfas.qc.rules import RULE_LIBRARY, METHODS
        rules = self.rules()
        toggles = rules.get("method_rule_toggles", {})
        rows = []
        for rule in RULE_LIBRARY:
            rkey = rule["key"]
            states = []
            for m in METHODS:
                mid = m["id"]
                method_toggles = toggles.get(mid, {})
                enabled = method_toggles.get(rkey, True)
                states.append({
                    "method_id":    mid,
                    "method_label": m["label"],
                    "enabled":      enabled,
                })
            rows.append({
                "rule_key":   rkey,
                "rule_label": rule["label"],
                "has_params": bool(rule.get("params")),
                "states":     states,
            })
        return rows

    def method_limit_sections(self):
        """
        Return one section per method with per-rule param editors.
        Each: {method_id, method_label, param_groups}
        param_groups are only included for ENABLED rules that have params.
        Each param has an 'inherited' value (global default) so JS can detect
        actual overrides vs inherited-same-value non-changes.
        """
        from senaite.pfas.qc.rules import RULE_LIBRARY, METHODS
        rules = self.rules()
        toggles = rules.get("method_rule_toggles", {})
        overrides = rules.get("method_overrides", {})
        global_vals = rules.get("global", {})
        sections = []
        for m in METHODS:
            mid = m["id"]
            method_toggles = toggles.get(mid, {})
            method_overrides = overrides.get(mid, {})
            param_groups = []
            for rule in RULE_LIBRARY:
                rkey = rule["key"]
                if not rule.get("params"):
                    continue
                enabled = method_toggles.get(rkey, True)
                params = []
                for p in rule["params"]:
                    pname = p["name"]
                    # Inherited value: global > default (in that priority)
                    inherited = global_vals.get(pname, p["default"])
                    # Method override (may be None if not set)
                    override_val = method_overrides.get(pname)
                    display_val = override_val if override_val is not None else inherited
                    params.append({
                        "name":      pname,
                        "label":     p["label"],
                        "type":      p["type"],
                        "value":     display_val,
                        "inherited": inherited,
                        "overridden": override_val is not None,
                    })
                param_groups.append({
                    "rule_key":   rkey,
                    "rule_label": rule["label"],
                    "enabled":    enabled,
                    "params":     params,
                })
            sections.append({
                "method_id":    mid,
                "method_label": m["label"],
                "param_groups": param_groups,
            })
        return sections

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
