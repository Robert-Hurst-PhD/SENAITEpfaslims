# -*- coding: utf-8 -*-
"""
PFAS Control Chart browser view.

Registered at @@pfas-control-chart on the SENAITE portal.
Serves both the HTML chart page and a JSON data endpoint.

Python 2.7-compatible (runs inside Zope/Plone).
Reads QC results from the SQLite store written by the Python 3 pipeline.

Query parameters
----------------
qc_type       : CCV | LCS | MB | LFSM | LFSMD | IS
analyte       : analyte name (e.g. PFOA)
qc_level      : calibration level or spike (optional; omit = all levels)
analyst       : filter by analyst name (optional)
instrument_id : filter by instrument ID (optional)
limit         : number of data points; default 20, max 300
show_history  : 1 = include superseded results for analyst review
format        : json = return raw JSON instead of HTML
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

logger = logging.getLogger("senaite.pfas.browser.controlchart")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
DEFAULT_LIMIT = 20
MAX_LIMIT = 300

QC_TYPE_TARGETS = {
    "CCV":   0.0,
    "ICV":   0.0,
    "LCS":   100.0,
    "MB":    0.0,
    "MxB":   0.0,
    "LRB":   0.0,
    "LFSM":  100.0,
    "LFSMD": 100.0,
}

QC_TYPE_UNITS = {
    "CCV":   "% Deviation",
    "ICV":   "% Deviation",
    "LCS":   "% Recovery",
    "MB":    "Concentration (ng/mL)",
    "MxB":   "Concentration (ng/mL)",
    "LRB":   "Concentration (ng/mL)",
    "LFSM":  "% Recovery",
    "LFSMD": "% Recovery",
}


class PFASControlChartView(BrowserView):
    """
    Browser view serving the PFAS QC control chart.

    Supports two modes:
      html (default) — renders the Chart.js template
      json            — returns chart data as JSON for XHR/AJAX requests
    """

    template = ViewPageTemplateFile("templates/controlchart.pt")

    def __call__(self):
        req = self.request
        fmt = req.get("format", "").lower()
        accept = req.getHeader("Accept", "")
        if fmt == "json" or "application/json" in accept:
            return self._json_response()
        return self.template()

    # ── Request parameter accessors ──────────────────────────────────────

    def selected_method(self):
        return self.request.get("method", "")

    def selected_qc_type(self):
        return self.request.get("qc_type", "CCV")

    def selected_analyte(self):
        return self.request.get("analyte", "")

    def selected_level(self):
        return self.request.get("qc_level", "")

    def selected_analyst(self):
        return self.request.get("analyst", "") or None

    def selected_instrument(self):
        return self.request.get("instrument_id", "") or None

    def selected_limit(self):
        try:
            v = int(self.request.get("limit", DEFAULT_LIMIT))
            return min(max(v, 1), MAX_LIMIT)
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    def show_history(self):
        return self.request.get("show_history", "0") == "1"

    # ── Store accessors (template helpers) ───────────────────────────────

    @property
    def db_path(self):
        return DEFAULT_DB_PATH

    @property
    def db_available(self):
        return os.path.exists(self.db_path)

    def _store(self):
        from senaite.pfas.qc.store import QCResultStore
        return QCResultStore(self.db_path)

    def methods(self):
        """Distinct method IDs in the QC results store."""
        if not self.db_available:
            return []
        try:
            return self._store().get_methods()
        except Exception as e:
            logger.error("methods: %s", e)
            return []

    def qc_types(self):
        if not self.db_available:
            return ["CCV", "LCS", "MB", "LFSM", "LFSMD", "IS"]
        try:
            return self._store().get_qc_types() or ["CCV", "LCS", "MB", "LFSM", "IS"]
        except Exception as e:
            logger.error("qc_types: %s", e)
            return []

    def analytes(self, qc_type=None):
        if not self.db_available:
            return []
        try:
            method = self.selected_method() or None
            return self._store().get_analytes(qc_type=qc_type, method=method)
        except Exception as e:
            logger.error("analytes: %s", e)
            return []

    def qc_levels(self, qc_type=None, analyte=None):
        if not self.db_available:
            return []
        try:
            return self._store().get_qc_levels(qc_type=qc_type, analyte=analyte)
        except Exception as e:
            logger.error("qc_levels: %s", e)
            return []

    def analysts(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_analysts()
        except Exception as e:
            logger.error("analysts: %s", e)
            return []

    def instruments(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_instruments()
        except Exception as e:
            logger.error("instruments: %s", e)
            return []

    def summary(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_summary()
        except Exception as e:
            logger.error("summary: %s", e)
            return []

    def _cached_chart_dict(self):
        """Return (and cache) the chart dict for this request."""
        if not hasattr(self, "_chart_dict_cache"):
            self._chart_dict_cache = self._build_chart_dict()
        return self._chart_dict_cache

    def chart_data(self):
        """Expose chart dict directly to TAL (avoids JSON round-trip)."""
        return self._cached_chart_dict()

    def has_data(self):
        return bool(self._cached_chart_dict().get("n_points", 0))

    def chart_json(self):
        try:
            return json.dumps(self._cached_chart_dict())
        except (TypeError, ValueError):
            return "{}"

    def westgard_violations(self):
        return self._cached_chart_dict().get("westgard", [])

    # ── JSON endpoint ────────────────────────────────────────────────────

    def _json_response(self):
        self.request.response.setHeader("Content-Type", "application/json")
        data = self._build_chart_dict()
        try:
            return json.dumps(data)
        except (TypeError, ValueError) as e:
            return json.dumps({"error": str(e)})

    # ── Chart data builder ───────────────────────────────────────────────

    def _build_chart_dict(self):
        qc_type     = self.selected_qc_type()
        analyte     = self.selected_analyte()
        method      = self.selected_method() or None
        qc_level    = self.selected_level() or None
        analyst     = self.selected_analyst()
        instrument  = self.selected_instrument()
        limit       = self.selected_limit()
        history     = self.show_history()
        units       = QC_TYPE_UNITS.get(qc_type, "")
        target      = QC_TYPE_TARGETS.get(qc_type)

        if not self.db_available or not analyte:
            return self._empty_chart(analyte, qc_type, qc_level or "",
                                     units, limit, history)

        try:
            rows = self._store().get_chart_data(
                analyte, qc_type,
                qc_level=qc_level,
                method=method,
                analyst=analyst,
                instrument_id=instrument,
                limit=limit,
                include_superseded=history,
            )
        except Exception as e:
            logger.error("get_chart_data: %s", e)
            return self._empty_chart(analyte, qc_type, qc_level or "",
                                     units, limit, history)

        if not rows:
            return self._empty_chart(analyte, qc_type, qc_level or "",
                                     units, limit, history)

        points = []
        for r in rows:
            v = r.get("value")
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            points.append({
                "date":          str(r.get("run_date", ""))[:10],
                "value":         fv,
                "batch_id":      str(r.get("batch_id", "")),
                "flag":          str(r.get("flag", "")),
                "analyst":       str(r.get("analyst") or r.get("batch_analyst") or ""),
                "instrument_id": str(r.get("instrument_id", "")),
                "status":        str(r.get("result_status", "active")),
            })

        # Check if this QC type uses a threshold chart (blanks) vs L-J
        try:
            from senaite.pfas.qc.rules import get_store as _get_rules_store
            is_threshold = _get_rules_store().is_threshold_chart(qc_type)
            threshold_val = _get_rules_store().get_qc_type_rules(qc_type).get(
                "threshold"
            )
        except Exception:
            is_threshold = qc_type in ("MB", "MxB", "LRB")
            threshold_val = None

        if is_threshold:
            limits = None
            violations = []
        else:
            limits = self._compute_limits([p["value"] for p in points])
            violations = self._westgard(points, limits)

        # Annotate points with their worst violation
        violated = {}
        for viol in violations:
            for idx in viol.get("indices", []):
                prev = violated.get(idx, "ok")
                if viol["severity"] == "reject":
                    violated[idx] = "reject"
                elif prev != "reject" and viol["severity"] == "warning":
                    violated[idx] = "warning"

        labels, values, batch_ids, flags = [], [], [], []
        analysts_list, instruments_list = [], []
        point_viol, point_status = [], []

        for i, p in enumerate(points):
            labels.append(p["date"])
            values.append(self._r(p["value"]))
            batch_ids.append(p["batch_id"])
            flags.append(p["flag"])
            analysts_list.append(p["analyst"])
            instruments_list.append(p["instrument_id"])
            point_viol.append(",".join(
                v["rule"] for v in violations
                if i in v.get("indices", [])
            ))
            point_status.append(p["status"])

        return {
            "analyte":        analyte,
            "qc_type":        qc_type,
            "method":         method or "",
            "qc_level":       qc_level or "",
            "units":          units,
            "labels":         labels,
            "values":         values,
            "batch_ids":      batch_ids,
            "flags":          flags,
            "analysts":       analysts_list,
            "instruments":    instruments_list,
            "violations":     point_viol,
            "point_status":   point_status,
            "limits":         limits,
            "target":         target,
            "threshold":      self._r(threshold_val),
            "chart_type":     "threshold" if is_threshold else "levey_jennings",
            "westgard":       violations,
            "has_rejects":    any(v["severity"] == "reject" for v in violations),
            "has_warnings":   any(v["severity"] == "warning" for v in violations),
            "n_points":       len(points),
            "limit":          limit,
            "show_history":   history,
        }

    @staticmethod
    def _empty_chart(analyte, qc_type, qc_level, units, limit, history):
        return {
            "analyte": analyte, "qc_type": qc_type,
            "qc_level": qc_level, "units": units,
            "labels": [], "values": [], "batch_ids": [],
            "flags": [], "analysts": [], "instruments": [],
            "violations": [], "point_status": [],
            "limits": None, "target": None,
            "westgard": [], "has_rejects": False,
            "has_warnings": False, "n_points": 0,
            "limit": limit, "show_history": history,
        }

    @staticmethod
    def _compute_limits(values, n_baseline=20):
        import math as _math
        valid = [v for v in values
                 if v is not None and not (_math.isinf(v) or _math.isnan(v))]
        if len(valid) < 5:
            return None
        baseline = valid[:n_baseline]
        n = len(baseline)
        mean = sum(baseline) / float(n)
        if n < 2:
            return None
        variance = sum((x - mean) ** 2 for x in baseline) / float(n - 1)
        sd = variance ** 0.5
        if sd == 0.0:
            sd = max(abs(mean) * 0.01, 0.01)
        return {
            "mean":       round(mean, 4),
            "sd":         round(sd, 4),
            "n_baseline": n,
            "ucl_1":      round(mean + sd,     4),
            "lcl_1":      round(mean - sd,     4),
            "ucl_2":      round(mean + 2 * sd, 4),
            "lcl_2":      round(mean - 2 * sd, 4),
            "ucl_3":      round(mean + 3 * sd, 4),
            "lcl_3":      round(mean - 3 * sd, 4),
        }

    @staticmethod
    def _westgard(points, limits):
        if not limits or not points:
            return []
        mean = limits["mean"]
        sd = limits["sd"]

        def sigma(v):
            return (v - mean) / sd if sd else 0.0

        sigs = [sigma(p["value"]) for p in points]
        n = len(sigs)
        violations = []
        seen = set()

        def _add(rule, desc, severity, indices):
            key = (rule, tuple(indices))
            if key not in seen:
                seen.add(key)
                violations.append({
                    "rule": rule, "description": desc,
                    "severity": severity, "indices": list(indices),
                })

        for i in range(1, n):
            s = sigs[i]
            if abs(s) > 3.0:
                _add("1-3S", "Single value beyond +/-3SD (reject)", "reject", [i])
            elif abs(s) > 2.0:
                _add("1-2S", "Single value beyond +/-2SD (warning)", "warning", [i])
            if i >= 1:
                sp = sigs[i - 1]
                if s > 2.0 and sp > 2.0:
                    _add("2-2S", "Two consecutive above +2SD (reject)", "reject", [i-1, i])
                elif s < -2.0 and sp < -2.0:
                    _add("2-2S", "Two consecutive below -2SD (reject)", "reject", [i-1, i])
            if i >= 1 and abs(s - sigs[i-1]) >= 4.0:
                _add("R-4S", "Adjacent range >= 4SD (reject)", "reject", [i-1, i])
            if i >= 3:
                run4 = sigs[i-3:i+1]
                if all(v > 1.0 for v in run4):
                    _add("4-1S", "Four consecutive above +1SD (reject)",
                         "reject", list(range(i-3, i+1)))
                elif all(v < -1.0 for v in run4):
                    _add("4-1S", "Four consecutive below -1SD (reject)",
                         "reject", list(range(i-3, i+1)))
            if i >= 9:
                run10 = sigs[i-9:i+1]
                if all(v > 0 for v in run10):
                    _add("10X", "Ten consecutive above mean (reject)",
                         "reject", list(range(i-9, i+1)))
                elif all(v < 0 for v in run10):
                    _add("10X", "Ten consecutive below mean (reject)",
                         "reject", list(range(i-9, i+1)))

        return violations

    @staticmethod
    def _r(v, digits=4):
        if v is None:
            return None
        try:
            import math as _math
            fv = float(v)
            if _math.isinf(fv) or _math.isnan(fv):
                return None
            return round(fv, digits)
        except (TypeError, ValueError):
            return None
