# -*- coding: utf-8 -*-
"""
QC Type Grid — cross-method toggle view.

Renders a matrix of methods (rows) × QC types (columns) with a checkbox at
each intersection.  On save, updates each method's associated_qc_types list
and creates / removes the corresponding qc_acceptance entry.

Presence of a key in qc_acceptance = enabled; absence = disabled.
No enabled:True/False flags needed — the grid toggle IS the flag.

Per-spike-level RPD: LFSMD tiers may carry an optional
``spike_level`` field ("Low" / "Mid" / "High" / null = all levels).
Dup (field duplicate, unfortified) uses a single flat RPD limit — no spike
level concept applies to unfortified field replicates.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import json
import logging

from Products.Five.browser import BrowserView

logger = logging.getLogger("senaite.pfas.qc_grid")

# Canonical ordered QC type list for the grid columns.
# Instrument-level types (CAL/ICV/CCV) live in qc/rules.py — not here.
QC_COLUMNS = [
    {"code": "MB",    "label": "Method Blank",         "criterion": "blank"},
    {"code": "LRB",   "label": "Lab Reagent Blank",     "criterion": "blank"},
    {"code": "MxB",   "label": "Matrix Blank",          "criterion": "blank"},
    {"code": "LFB",   "label": "Lab Fortified Blank",   "criterion": "recovery"},
    {"code": "LCS",   "label": "Lab Control Sample",    "criterion": "recovery"},
    {"code": "LFSM",  "label": "LF Sample Spike",       "criterion": "recovery"},
    {"code": "LFSMD", "label": "LF Sample Spike Dup",   "criterion": "rpd"},
    {"code": "Dup",   "label": "Field Duplicate",       "criterion": "rpd"},
]

# Default tier seed when a QC type is first enabled for a method.
_DEFAULT_TIERS = {
    "blank": [
        {"name": "default", "analyte_group": "all", "matrix_scope": "all",
         "max_conc_x_rl": 1.0},
    ],
    "recovery": [
        {"name": "default", "analyte_group": "all", "matrix_scope": "all",
         "recovery_min": 70.0, "recovery_max": 130.0, "rsd_max": None},
    ],
    "rpd": [
        {"name": "default", "analyte_group": "all", "matrix_scope": "all",
         "rpd_max": 30.0},
    ],
}

# Spike levels for per-level RPD criterion differentiation.
SPIKE_LEVELS = ["Low", "Mid", "High"]

# Methods shown as grid rows (order matches method_profile_store.DEFAULT_PROFILES).
# Method ID list single-sourced from analyte_reference.get_method_ids();
# short labels are presentation only (see qc.rules for the same pattern).
from senaite.pfas.analyte_reference import get_method_ids as _get_method_ids

_METHOD_SHORT_LABELS = {
    "FDA_32PFAS": "FDA 32-PFAS",
    "EPA_537_1":  "EPA 537.1",
    "EPA_1633A":  "EPA 1633A",
}
GRID_METHODS = [{"id": mid, "label": _METHOD_SHORT_LABELS.get(mid, mid)}
                for mid in _get_method_ids()]


class PFASQCTypeGridView(BrowserView):
    """
    @@pfas-qc-type-grid — cross-method QC toggle grid.

    GET:  render grid with current state from method profile store.
    POST: apply checkbox changes, then redirect to GET.
    """

    def __call__(self):
        if self.request.method == "POST":
            action = self.request.form.get("action", "")
            if action == "save_grid":
                self._handle_save()
                url = self.context.absolute_url() + "/@@pfas-qc-type-grid"
                return self.request.response.redirect(url)
        return self.index()

    # ── Template helpers ──────────────────────────────────────────────────────

    def qc_columns(self):
        return QC_COLUMNS

    def grid_methods(self):
        return GRID_METHODS

    def spike_levels(self):
        return SPIKE_LEVELS

    def _portal(self):
        from bika.lims import api
        return api.get_portal()

    def _load_profile(self, method_id):
        from senaite.pfas.method_profile_store import get_profile
        try:
            return get_profile(self._portal(), method_id) or {}
        except Exception as exc:
            logger.error("_load_profile %s: %s", method_id, exc)
            return {}

    def grid_state(self):
        """Return {method_id: {qc_code: bool}} for the template."""
        state = {}
        for m in GRID_METHODS:
            mid = m["id"]
            profile = self._load_profile(mid)
            associated = set(profile.get("associated_qc_types", []))
            state[mid] = {col["code"]: (col["code"] in associated)
                          for col in QC_COLUMNS}
        return state

    def rpd_tiers(self, method_id, qc_code):
        """
        Return the tiers list for a given method × QC type, or [] if not
        associated.  Used by the per-cell criteria popup.

        For LFSMD / Dup, tiers may carry a ``spike_level`` field.
        """
        profile = self._load_profile(method_id)
        entry = profile.get("qc_acceptance", {}).get(qc_code)
        if entry is None:
            return []
        return entry.get("tiers", [])

    def rpd_tiers_json(self, method_id, qc_code):
        return json.dumps(self.rpd_tiers(method_id, qc_code))

    def is_rpd_type(self, qc_code):
        for col in QC_COLUMNS:
            if col["code"] == qc_code:
                return col["criterion"] == "rpd"
        return False

    # ── POST handler ──────────────────────────────────────────────────────────

    def _handle_save(self):
        """Apply grid checkbox state to all method profiles."""
        from senaite.pfas.method_profile_store import get_profile, save_profile
        portal = self._portal()

        for m in GRID_METHODS:
            mid = m["id"]
            try:
                profile = get_profile(portal, mid) or {}
                self._apply_method_row(profile, mid)
                save_profile(portal, mid, profile)
            except Exception as exc:
                logger.error("_handle_save %s: %s", mid, exc)

    def _apply_method_row(self, profile, method_id):
        """Update profile in-place for the checkboxes submitted for this method."""
        qa = profile.setdefault("qc_acceptance", {})
        current_assoc = list(profile.get("associated_qc_types", []))
        new_assoc = list(current_assoc)

        for col in QC_COLUMNS:
            code = col["code"]
            field_name = "qc_enabled_{}_{}".format(method_id, code)
            checked = bool(self.request.form.get(field_name))

            if checked:
                if code not in qa:
                    criterion = col["criterion"]
                    qa[code] = {
                        "enabled": True,
                        "tiers": copy.deepcopy(_DEFAULT_TIERS[criterion]),
                    }
                if code not in new_assoc:
                    new_assoc.append(code)
            else:
                # Remove key entirely — absence = disabled
                if code in qa:
                    del qa[code]
                if code in new_assoc:
                    new_assoc.remove(code)

        profile["associated_qc_types"] = new_assoc

        # Handle per-spike-level RPD criteria for LFSMD
        self._apply_rpd_tiers(qa, method_id)

    def _apply_rpd_tiers(self, qa, method_id):
        """
        If the request includes per-spike-level RPD data for LFSMD,
        update those tiers in-place.

        Form field naming: rpd_{method}_{code}_{spike_level}
        e.g. rpd_FDA_32PFAS_LFSMD_Low, rpd_FDA_32PFAS_LFSMD_Mid, ...
        A blank value means "not set" (no per-level override for that level).
        When all three spike levels have values, create one tier per level;
        when none do, keep the existing flat tier unchanged.

        Dup (field duplicate) uses a flat RPD — spike levels do not apply.
        """
        for code in ("LFSMD",):
            if code not in qa:
                continue
            level_rpds = {}
            for level in SPIKE_LEVELS:
                field = "rpd_{}__{}_{}".format(method_id, code, level)
                raw = self.request.form.get(field, "").strip()
                if raw:
                    try:
                        level_rpds[level] = float(raw)
                    except ValueError:
                        pass

            if not level_rpds:
                continue

            existing = qa[code].get("tiers", [])
            non_level = [t for t in existing if not t.get("spike_level")]
            base_tier = non_level[0] if non_level else {
                "analyte_group": "all",
                "matrix_scope": "all",
            }

            new_tiers = []
            for level in SPIKE_LEVELS:
                if level in level_rpds:
                    tier = copy.deepcopy(base_tier)
                    tier["name"] = "level_{}".format(level.lower())
                    tier["spike_level"] = level
                    tier["rpd_max"] = level_rpds[level]
                    new_tiers.append(tier)
                else:
                    # Carry forward any existing tier for this level
                    for t in existing:
                        if t.get("spike_level") == level:
                            new_tiers.append(copy.deepcopy(t))
                            break

            if new_tiers:
                qa[code]["tiers"] = new_tiers
