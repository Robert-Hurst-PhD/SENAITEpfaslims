# -*- coding: utf-8 -*-
"""
PFAS Calibration tracking browser view.

Registered at @@pfas-calibrations on the SENAITE portal.
Displays calibration curve history (R², equation, per-level deviations) and
allows Manager/LabManager users to approve or reject pending calibrations.

Python 2.7-compatible (runs inside Zope/Plone).
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

logger = logging.getLogger("senaite.pfas.browser.calibrations")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
DEFAULT_LIMIT = 50


def _is_manager(context):
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        roles = user.getRolesInContext(context)
        return "Manager" in roles or "LabManager" in roles
    except Exception:
        return False


class PFASCalibrationsView(BrowserView):
    """
    Browser view for PFAS calibration curve review and approval.

    GET  — render the calibration list template.
    POST — update calibration status (approve/reject) if user has permission.
    """

    template = ViewPageTemplateFile("templates/calibrations.pt")

    def __call__(self):
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    # ── Request parameter accessors ──────────────────────────────────────

    def selected_analyte(self):
        return self.request.get("analyte", "")

    def selected_analyst(self):
        return self.request.get("analyst", "") or None

    def selected_instrument(self):
        return self.request.get("instrument_id", "") or None

    def selected_method(self):
        return self.request.get("method", "") or None

    def selected_status(self):
        return self.request.get("status", "")

    def selected_limit(self):
        try:
            v = int(self.request.get("limit", DEFAULT_LIMIT))
            return min(max(v, 1), 300)
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    def is_manager(self):
        return _is_manager(self.context)

    def save_message(self):
        return self.request.get("saved", "")

    # ── Store helpers ─────────────────────────────────────────────────────

    @property
    def db_path(self):
        return DEFAULT_DB_PATH

    @property
    def db_available(self):
        return os.path.exists(self.db_path)

    def _store(self):
        from senaite.pfas.qc.store import QCResultStore
        return QCResultStore(self.db_path)

    def analytes(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_analytes()
        except Exception as e:
            logger.error("calibrations.analytes: %s", e)
            return []

    def analysts(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_analysts()
        except Exception as e:
            logger.error("calibrations.analysts: %s", e)
            return []

    def instruments(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_instruments()
        except Exception as e:
            logger.error("calibrations.instruments: %s", e)
            return []

    # ── QC acceptance criteria from rules store ───────────────────────────

    def r2_minimum(self):
        """Return the configured minimum R² from the QC rules store."""
        try:
            from senaite.pfas.qc.rules import get_rules
            return get_rules().get("global", {}).get("cal_r2_min", 0.995)
        except Exception:
            return 0.995

    def cal_pct_max(self):
        """Return configured max % deviation for calibration points."""
        try:
            from senaite.pfas.qc.rules import get_rules
            return get_rules().get("global", {}).get(
                "cal_pct_deviation_max", 20.0
            )
        except Exception:
            return 20.0

    # ── Calibration data ──────────────────────────────────────────────────

    def calibrations(self):
        """Return filtered list of calibration records for the template."""
        if not self.db_available:
            return []

        analyte = self.selected_analyte() or None
        method = self.selected_method()
        limit = self.selected_limit()
        status_filter = self.selected_status()
        analyst_filter = self.selected_analyst()
        instrument_filter = self.selected_instrument()

        try:
            rows = self._store().get_calibrations(
                analyte=analyte, method=method, limit=limit
            )
        except Exception as e:
            logger.error("get_calibrations: %s", e)
            return []

        r2_min = self.r2_minimum()

        result = []
        for row in rows:
            # Apply filters not natively in get_calibrations
            if status_filter and row.get("status") != status_filter:
                continue
            if analyst_filter and row.get("analyst") != analyst_filter:
                continue
            if instrument_filter and row.get("instrument_id") != instrument_filter:
                continue

            r2 = row.get("r2")
            r2_ok = r2 is not None and float(r2) >= r2_min

            result.append({
                "id":            row.get("id"),
                "batch_id":      row.get("batch_id", ""),
                "run_date":      str(row.get("run_date", ""))[:10],
                "analyte":       row.get("analyte", ""),
                "method":        row.get("method", ""),
                "analyst":       row.get("analyst", ""),
                "instrument_id": row.get("instrument_id", ""),
                "equation":      row.get("equation", ""),
                "fit_type":      row.get("fit_type", ""),
                "weight_type":   row.get("weight_type", ""),
                "r2":            round(float(r2), 6) if r2 is not None else None,
                "r2_ok":         r2_ok,
                "n_levels":      row.get("n_levels", 0),
                "min_level":     row.get("min_level"),
                "max_level":     row.get("max_level"),
                "status":        row.get("status", "pending"),
                "notes":         row.get("notes", ""),
                "created_at":    str(row.get("created_at", ""))[:19],
            })
        return result

    def calibration_levels(self, calibration_id):
        """Return per-level data for a single calibration."""
        if not self.db_available:
            return []
        try:
            rows = self._store().get_calibration_levels(calibration_id)
        except Exception as e:
            logger.error("get_calibration_levels %s: %s", calibration_id, e)
            return []

        pct_max = self.cal_pct_max()
        result = []
        for row in rows:
            dev = row.get("pct_deviation")
            passed = bool(row.get("passed", 1))
            if dev is not None:
                passed = abs(float(dev)) <= pct_max
            result.append({
                "level":         row.get("level"),
                "expected":      row.get("expected"),
                "calculated":    row.get("calculated"),
                "pct_deviation": round(float(dev), 2) if dev is not None else None,
                "passed":        passed,
            })
        return result

    def summary_stats(self):
        """Return aggregate stats for the current filter set."""
        cals = self.calibrations()
        if not cals:
            return {}
        r2_values = [c["r2"] for c in cals if c["r2"] is not None]
        n_pass = sum(1 for c in cals if c["r2_ok"])
        n_pending = sum(1 for c in cals if c["status"] == "pending")
        n_approved = sum(1 for c in cals if c["status"] == "approved")
        n_rejected = sum(1 for c in cals if c["status"] == "rejected")
        avg_r2 = round(sum(r2_values) / len(r2_values), 6) if r2_values else None
        return {
            "total":      len(cals),
            "r2_pass":    n_pass,
            "pending":    n_pending,
            "approved":   n_approved,
            "rejected":   n_rejected,
            "avg_r2":     avg_r2,
        }

    def status_choices(self):
        return ["pending", "approved", "rejected"]

    # ── POST handler ──────────────────────────────────────────────────────

    def _handle_post(self):
        if not _is_manager(self.context):
            self.request.response.setStatus(403)
            return "Forbidden: Manager role required to update calibrations"

        cal_id = self.request.get("calibration_id", "")
        new_status = self.request.get("new_status", "")
        notes = self.request.get("notes", "")

        if not cal_id or new_status not in ("approved", "rejected", "pending"):
            self.request.response.setStatus(400)
            return "Invalid request"

        try:
            cal_id = int(cal_id)
        except (TypeError, ValueError):
            self.request.response.setStatus(400)
            return "Invalid calibration_id"

        try:
            with self._store()._connect() as conn:
                conn.execute(
                    "UPDATE calibrations SET status=?, notes=? WHERE id=?",
                    (new_status, notes, cal_id),
                )
        except Exception as exc:
            logger.error("Failed to update calibration %s: %s", cal_id, exc)
            self.request.response.setStatus(500)
            return "Update failed: {}".format(exc)

        url = "{}/@@pfas-calibrations?saved=1".format(
            self.context.absolute_url()
        )
        self.request.response.redirect(url)
        return ""
