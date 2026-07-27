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
from senaite.pfas.browser.formutil import flatten_form

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
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    # ── Request parameter accessors ──────────────────────────────────────

    def selected_analyte(self):
        return self.request.form.get("analyte", "")

    def selected_analyst(self):
        return self.request.form.get("analyst", "") or None

    def selected_instrument(self):
        return self.request.form.get("instrument_id", "") or None

    def selected_method(self):
        return self.request.form.get("method", "") or None

    def selected_status(self):
        return self.request.form.get("status", "")

    def selected_limit(self):
        try:
            v = int(self.request.form.get("limit", DEFAULT_LIMIT))
            return min(max(v, 1), 300)
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    def is_manager(self):
        return _is_manager(self.context)

    def save_message(self):
        return self.request.form.get("saved", "")

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
        """Return configured minimum R² — method override > global > default."""
        try:
            from senaite.pfas.qc.rules import get_rules
            rules = get_rules()
            method = self.selected_method()
            if method:
                v = rules.get("method_overrides", {}).get(method, {}).get("cal_r2_min")
                if v is not None:
                    return float(v)
            v = rules.get("global", {}).get("cal_r2_min")
            if v is not None:
                return float(v)
            return 0.995
        except Exception:
            return 0.995

    def cal_pct_max(self):
        """Return max % deviation for calibration standards (from CAL QC type)."""
        try:
            from senaite.pfas.qc.rules import get_rules
            return float(
                get_rules().get("qc_types", {}).get("CAL", {}).get(
                    "pct_deviation_max", 20.0
                )
            )
        except Exception:
            return 20.0

    def qc_type_limits(self):
        """Return per-QC-type % deviation limits read from the rules store."""
        defaults = {
            "CAL": {"max": 25.0, "warn": 25.0},
            "ICV": {"max": 20.0, "warn": 20.0},
            "CCV": {"max": 20.0, "warn": 10.0},
            "CCB": {"max": 20.0, "warn": 20.0},
        }
        try:
            from senaite.pfas.qc.rules import get_rules
            qt = get_rules().get("qc_types", {})
            result = {}
            for code, fallback in defaults.items():
                d = qt.get(code, {})
                result[code] = {
                    "max":  float(d.get("pct_deviation_max",  fallback["max"])),
                    "warn": float(d.get("pct_deviation_warn",
                                        d.get("pct_deviation_max", fallback["warn"]))),
                }
            return result
        except Exception:
            return defaults

    def qc_limits_json(self):
        """Return HTML-safe JSON of per-QC-type limits for embedding in templates."""
        try:
            raw = json.dumps(self.qc_type_limits())
            raw = raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            return raw
        except Exception:
            return ('{"CAL":{"max":25,"warn":25},"ICV":{"max":20,"warn":20},'
                    '"CCV":{"max":20,"warn":10},"CCB":{"max":20,"warn":20}}')

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
        run_date_filter = self.selected_run_date()

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
            if status_filter and row.get("status") != status_filter:
                continue
            if analyst_filter and row.get("analyst") != analyst_filter:
                continue
            if instrument_filter and row.get("instrument_id") != instrument_filter:
                continue
            if run_date_filter and str(row.get("run_date", ""))[:10] != run_date_filter:
                continue

            r2 = row.get("r2")
            r2_ok = r2 is not None and float(r2) >= r2_min

            result.append({
                "id":                  row.get("id"),
                "batch_id":            row.get("batch_id", ""),
                "run_date":            str(row.get("run_date", ""))[:10],
                "analyte":             row.get("analyte", ""),
                "method":              row.get("method", ""),
                "analyst":             row.get("analyst", ""),
                "instrument_id":       row.get("instrument_id", ""),
                "equation":            row.get("equation", ""),
                "fit_type":            row.get("fit_type", ""),
                "weight_type":         row.get("weight_type", ""),
                "r2":                  round(float(r2), 6) if r2 is not None else None,
                "r2_ok":               r2_ok,
                "n_levels":            row.get("n_levels", 0),
                "min_level":           row.get("min_level"),
                "max_level":           row.get("max_level"),
                "status":              row.get("status", "pending"),
                "notes":               row.get("notes", ""),
                "created_at":          str(row.get("created_at", ""))[:19],
                "approved_by":         row.get("approved_by", "") or "",
                "approved_at":         str(row.get("approved_at", "") or "")[:19],
                "fit_type_override":   row.get("fit_type_override", "") or "",
                "weight_override":     row.get("weight_override", "") or "",
                "origin_override":     row.get("origin_override", "") or "",
            })
        return result

    def calibration_runs(self):
        """Return calibrations grouped by run_date, newest first.

        Each group dict:
          run_date       TEXT  e.g. '2026-06-08'
          run_time       TEXT  time component from created_at, e.g. '09:31'
          instrument_id  TEXT
          analyst        TEXT
          method         TEXT
          n_pass         int   analytes whose R² passed
          n_total        int   total analytes in this run
          analytes       list  of per-analyte dicts (same keys as calibrations() +
                               'levels' key pre-fetched)
        """
        cals = self.calibrations()
        if not cals:
            return []

        # Group by run_date preserving newest-first order
        seen_dates = []
        groups = {}
        for cal in cals:
            rd = cal["run_date"]
            if rd not in groups:
                seen_dates.append(rd)
                # Extract time from created_at e.g. '2026-06-13T00:00:00' -> '00:00'
                created = cal.get("created_at", "")
                run_time = ""
                if "T" in created:
                    run_time = created.split("T")[1][:5]
                groups[rd] = {
                    "run_date":      rd,
                    "run_time":      run_time,
                    "instrument_id": cal.get("instrument_id", ""),
                    "analyst":       cal.get("analyst", ""),
                    "method":        cal.get("method", ""),
                    "analytes":      [],
                }
            # Pre-fetch levels for each analyte
            cal["levels"] = self.calibration_levels(cal["id"])
            groups[rd]["analytes"].append(cal)

        result = []
        for rd in seen_dates:
            grp = groups[rd]
            grp["n_total"] = len(grp["analytes"])
            grp["n_pass"] = sum(1 for a in grp["analytes"] if a["r2_ok"])
            result.append(grp)
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
            rr = row.get("response_ratio")
            result.append({
                "level":          row.get("level"),
                "expected":       row.get("expected"),
                "calculated":     row.get("calculated"),
                "pct_deviation":  round(float(dev), 2) if dev is not None else None,
                "passed":         passed,
                "response_ratio": round(float(rr), 8) if rr is not None else None,
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

    def run_dates(self):
        """Return distinct run dates (for filter pills)."""
        if not self.db_available:
            return []
        try:
            return self._store().get_run_dates(
                method=self.selected_method() or None, limit=30
            )
        except Exception as e:
            logger.error("run_dates: %s", e)
            return []

    def selected_run_date(self):
        return self.request.form.get("run_date", "")

    def _qc_for_run(self, run_date):
        """Return QC results for a run_date, as a dict keyed by analyte."""
        try:
            rows = self._store().get_qc_for_run(
                run_date, qc_types=["ICV", "CCV", "CCB", "MB", "LFB"]
            )
        except Exception as e:
            logger.error("_qc_for_run: %s", e)
            return {}
        by_analyte = {}
        for r in rows:
            a = r.get("analyte", "")
            if a not in by_analyte:
                by_analyte[a] = []
            ev = r.get("expected_value")
            val = r.get("value")
            pct = None
            if ev and val is not None:
                try:
                    pct = round((float(val) - float(ev)) / float(ev) * 100.0, 2)
                except (TypeError, ZeroDivisionError):
                    pct = None
            rr = r.get("response_ratio")
            by_analyte[a].append({
                "qc_type":        r.get("qc_type", ""),
                "qc_level":       r.get("qc_level", ""),
                "value":          val,
                "expected_value": ev,
                "pct_dev":        pct,
                "passed":         bool(r.get("passed", 1)),
                "flag":           r.get("flag", ""),
                "response_ratio": round(float(rr), 8) if rr is not None else None,
            })
        return by_analyte

    def calibration_runs_json(self):
        """Return JSON string of all run groups for the current filter."""
        runs = self.calibration_runs()
        pct_max = self.cal_pct_max()
        # Augment each run with QC data and override values
        for run in runs:
            qc_by_analyte = self._qc_for_run(run["run_date"])
            for cal in run["analytes"]:
                cal["qc"] = qc_by_analyte.get(cal["analyte"], [])
                cal["fit_type_override"] = cal.get("fit_type_override", "")
                cal["weight_override"] = cal.get("weight_override", "")
                cal["origin_override"] = cal.get("origin_override", "")
                cal["approved_by"] = cal.get("approved_by", "")
                cal["pct_max"] = pct_max
        try:
            raw = json.dumps(runs)
            # HTML-safe for Chameleon tal:replace: encode &, <, > so
            # Chameleon's escaping doesn't break JSON string values.
            raw = raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            return raw
        except Exception as e:
            logger.error("calibration_runs_json: %s", e)
            return "[]"

    def portal_url(self):
        return self.context.absolute_url()

    # ── POST handler ──────────────────────────────────────────────────────

    def _handle_post(self):
        if not _is_manager(self.context):
            self.request.response.setStatus(403)
            return "Forbidden: Manager role required to update calibrations"

        action = self.request.form.get("action", "update")

        if action == "approve_run":
            return self._handle_approve_run()
        if action == "override":
            return self._handle_override()

        # Legacy: single-calibration approve/reject
        cal_id = self.request.form.get("calibration_id", "")
        new_status = self.request.form.get("new_status", "")
        notes = self.request.form.get("notes", "")

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

    def _handle_approve_run(self):
        run_date = self.request.form.get("run_date", "").strip()
        if not run_date:
            self.request.response.setStatus(400)
            return "Missing run_date"
        try:
            from AccessControl import getSecurityManager
            user = getSecurityManager().getUser()
            approved_by = user.getUserName()
        except Exception:
            approved_by = "unknown"
        try:
            self._store().approve_run(
                run_date,
                approved_by=approved_by,
                method=self.request.form.get("method") or None,
            )
        except Exception as exc:
            logger.error("approve_run failed: %s", exc)
            self.request.response.setStatus(500)
            return "Approve failed: {}".format(exc)
        url = "{}/@@pfas-calibrations?saved=approved&run_date={}".format(
            self.context.absolute_url(), run_date
        )
        self.request.response.redirect(url)
        return ""

    def _handle_override(self):
        self.request.response.setHeader("Content-Type", "application/json")
        cal_id = self.request.form.get("calibration_id", "")
        fit_type_override = self.request.form.get("fit_type_override", "")
        weight_override = self.request.form.get("weight_override", "")
        origin_override = self.request.form.get("origin_override", "")
        try:
            cal_id = int(cal_id)
        except (TypeError, ValueError):
            self.request.response.setStatus(400)
            return json.dumps({"error": "invalid calibration_id"})
        try:
            self._store().update_calibration_override(
                cal_id,
                fit_type_override=fit_type_override,
                weight_override=weight_override,
                origin_override=origin_override,
            )
        except Exception as exc:
            logger.error("override failed: %s", exc)
            self.request.response.setStatus(500)
            return json.dumps({"error": str(exc)})
        return json.dumps({"ok": True})
