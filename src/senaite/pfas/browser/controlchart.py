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
import re

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse
from senaite.pfas.document_templates import script_json
from plone.memoize.instance import memoize

logger = logging.getLogger("senaite.pfas.browser.controlchart")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
DEFAULT_LIMIT = 20
MAX_LIMIT = 300

QC_TYPE_TARGETS = {
    # a check standard is charted as its recovery (calculated / expected):
    # the value stored is a concentration
    "CCV":   100.0,
    "ICV":   100.0,
    # LFB (lab fortified blank) is the canonical name; LCS folds into it.
    "LFB":   100.0,
    "MB":    0.0,
    "MxB":   0.0,
    "LRB":   0.0,
    "LFSM":  100.0,
    "LFSMD": 100.0,
    # Surrogate (labeled-analog / extracted-IS) recovery measured in each
    # field sample — an ongoing per-sample QC metric, target 100 % recovery.
    "SUR":   100.0,
}

QC_TYPE_UNITS = {
    "CCV":   "% Recovery",
    "ICV":   "% Recovery",
    "LFB":   "% Recovery",
    "MB":    "Concentration (ng/mL)",
    "MxB":   "Concentration (ng/mL)",
    "LRB":   "Concentration (ng/mL)",
    "LFSM":  "% Recovery",
    "LFSMD": "% Recovery",
    "SUR":   "% Recovery",
}


# a blank's non-detect is stored with no value; it is charted at 0, hollow,
# as "not detected" -- skipping it left most blank runs off the chart
BLANK_TYPES = ("MB", "LRB", "MxB", "CCB", "FRB", "TB")
RECOVERY_TYPES = ("CCV", "ICV")


def chart_value(qc_type, row):
    """(value, not_detected) as charted, or (None, False) to leave it off."""
    v = row.get("value")
    if v is None:
        return (0.0, True) if qc_type in BLANK_TYPES else (None, False)
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None, False
    if qc_type in RECOVERY_TYPES:
        try:
            exp = float(row.get("expected_value"))
        except (TypeError, ValueError):
            return None, False
        return (fv / exp * 100.0, False) if exp else (None, False)
    return fv, False


class PFASControlChartView(BrowserView):
    """
    Browser view serving the PFAS QC control chart.

    Supports two modes:
      html (default) — renders the Chart.js template
      json            — returns chart data as JSON for XHR/AJAX requests
    """

    template = ViewPageTemplateFile("templates/controlchart.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.get("REQUEST_METHOD", "GET") == "POST":
            return self._handle_post()
        fmt = req.get("format", "").lower()
        accept = req.getHeader("Accept", "")
        if fmt == "json" or "application/json" in accept:
            return self._json_response()
        return self.template()

    # ── Request parameter accessors ──────────────────────────────────────

    def selected_method(self):
        # request.get("method") returns the HTTP method (GET/POST) in Zope 2;
        # request.form is the correct place to read query-string parameters.
        return self.request.form.get("method", "")

    def selected_qc_type(self):
        """The QC type asked for, else the first with results (CCV when the
        store holds it): the page opens on a chart, not an empty pane."""
        asked = self.request.form.get("qc_type", "")
        if asked or "qc_type" in self.request.form:
            return asked
        types = self.qc_types() if self.db_available else []
        return "CCV" if "CCV" in types else (types[0] if types else "")

    def selected_chart_type_override(self):
        return self.request.form.get("chart_type_override", "")

    def selected_analytes(self):
        """The analytes on the chart: one checkbox field each (`an.<name>`;
        flatten_form keeps one value per field), else `analyte`, else the
        first with results. Several are stacked; the control limits and
        Westgard rules belong to one analyte, so only one gets them."""
        if not hasattr(self, "_sel_analytes"):
            f = self.request.form
            have = self.analytes(self.selected_qc_type()) if self.db_available else []
            picked = [a for a in have if f.get(u"an.%s" % a)]
            if not picked and self.request.get("analyte", ""):
                picked = [self.request.get("analyte", "")]
            if not picked and have:
                picked = [have[0]]
            self._sel_analytes = picked
        return self._sel_analytes

    def selected_analyte(self):
        sel = self.selected_analytes()
        return sel[0] if sel else ""

    def is_stacked(self):
        return len(self.selected_analytes()) > 1

    def stack_json(self):
        """Several analytes on one chart (points only): {labels: ["date
        batch"], series: [{analyte, values}], units}. No limits: each
        analyte's mean and SD are its own."""
        if not self.is_stacked():
            return "null"
        qc_type = self.selected_qc_type()
        cells, nds, keys = {}, set(), set()
        for a in self.selected_analytes():
            try:
                rows = self._store().get_chart_data(
                    a, qc_type, qc_level=self.selected_level() or None,
                    method=self.selected_method() or None, analyst=self.selected_analyst(),
                    instrument_id=self.selected_instrument(), limit=self.selected_limit(),
                    include_superseded=self.show_history(),
                    date_from=self.selected_date_from() or None,
                    date_to=self.selected_date_to() or None)
            except Exception as e:                          # noqa: BLE001
                logger.error("stack get_chart_data %s: %s", a, e)
                rows = []
            for r in rows:
                v, nd = chart_value(qc_type, r)
                if v is None:
                    continue
                k = (str(r.get("run_date", ""))[:10], str(r.get("batch_id", "")))
                keys.add(k)
                cells[(a, k)] = self._r(v)
                if nd:
                    nds.add((a, k))
        order = sorted(keys)
        return script_json({
            "labels": [u"%s %s" % k for k in order],
            "series": [{"analyte": a, "values": [cells.get((a, k)) for k in order],
                        "nd": [(a, k) in nds for k in order]}
                       for a in self.selected_analytes()],
            "units": QC_TYPE_UNITS.get(qc_type, ""),
            "qc_type": self.qc_type_label(qc_type)})

    def selected_level(self):
        return self.request.get("qc_level", "")

    def selected_analyst(self):
        return self.request.get("analyst", "") or None

    def selected_instrument(self):
        return self.request.get("instrument_id", "") or None

    @staticmethod
    def _clean_date(value):
        """Accept only a well-formed ISO date (YYYY-MM-DD); ignore anything
        else so a stray value can't break the query."""
        import re as _re
        value = (value or "").strip()
        return value if _re.match(r"^\d{4}-\d{2}-\d{2}$", value) else ""

    def selected_date_from(self):
        return self._clean_date(self.request.get("date_from", ""))

    def selected_date_to(self):
        return self._clean_date(self.request.get("date_to", ""))

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

    # ── QC-type display labels from core Reference Definitions ───────────
    # The UI-editable source of QC-type names is Setup -> Reference
    # Definitions. A definition opts in with a [QC:CODE] tag in its
    # Description; we map the stored qc_type code -> that definition's Title.
    # Both sides run through normalize_qc_type() so casing/aliases can't miss.
    def _qc_ref_label_map(self):
        if not hasattr(self, "_qc_label_cache"):
            from senaite.pfas.qc_labels import get_qc_label_map
            from bika.lims import api
            self._qc_label_cache = get_qc_label_map(api.get_portal())
        return self._qc_label_cache

    def qc_type_label(self, code):
        """Editable display name for a qc_type code (falls back to the raw
        code when no Reference Definition is tagged for it)."""
        from senaite.pfas.qc_labels import qc_label
        return qc_label(None, code, label_map=self._qc_ref_label_map())

    @memoize
    def methods(self):
        """Distinct method IDs in the QC results store."""
        if not self.db_available:
            return []
        try:
            return self._store().get_methods()
        except Exception as e:
            logger.error("methods: %s", e)
            return []

    @memoize
    def qc_types(self):
        # memoised: selected_qc_type() asked for it 18 times a page, one
        # DISTINCT over every QC row each
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
            # a row with no analyte (a run-level finding: CCV frequency) is
            # not a series
            return [a for a in self._store().get_analytes(qc_type=qc_type, method=method) if a]
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

    def date_bounds(self):
        """(min, max) run-date in the DB as ISO strings, for the date picker's
        min/max. Empty strings when there is no data."""
        if not self.db_available:
            return {"min": "", "max": ""}
        try:
            lo, hi = self._store().date_bounds()
            return {"min": lo or "", "max": hi or ""}
        except Exception as e:
            logger.error("date_bounds: %s", e)
            return {"min": "", "max": ""}

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

    def has_stack(self):
        try:
            d = json.loads(self.stack_json()) or {}
        except (TypeError, ValueError):
            return False
        return any(v is not None for s in d.get("series") or [] for v in s["values"])

    def chart_json(self):
        try:
            return script_json(self._cached_chart_dict())
        except (TypeError, ValueError):
            return "{}"

    def westgard_violations(self):
        """The warnings still standing (the active view's, not dismissed)."""
        return self._cached_chart_dict().get("westgard", [])

    def selected_view_mode(self):
        """'lj' (Levey-Jennings, the default) or 'westgard'."""
        return "westgard" if self.request.form.get("view_mode") == "westgard" else "lj"

    def can_review(self):
        """Dismiss a warning / remove a point: managers and QC reviewers."""
        from senaite.pfas.browser.perms import (
            MANAGER_ROLES, ANALYST_ROLES, has_role_at_portal)
        return has_role_at_portal(self.context, MANAGER_ROLES | ANALYST_ROLES)

    # ── Review actions (POST) ────────────────────────────────────────────

    _ACTIONS = {"dismiss": ("dismissed", True), "undismiss": ("dismissed", False),
                "remove": ("excluded", True), "restore": ("excluded", False)}

    def _handle_post(self):
        form = self.request.form
        action = form.get("chart_action", "")
        back = form.get("came_from") or self.request.get("HTTP_REFERER") or (
            self.context.absolute_url() + "/@@pfas-control-chart")
        if not self.can_review():
            return refuse(self.request, "Forbidden")
        try:   # only after the role check, as every PFAS POST view does
            from plone.protect.interfaces import IDisableCSRFProtection
            from zope.interface import alsoProvides
            alsoProvides(self.request, IDisableCSRFProtection)
        except ImportError:
            pass
        if action not in self._ACTIONS:
            self.request.response.setStatus(400)
            return "Unknown action"
        kind, add = self._ACTIONS[action]
        try:
            rid = int(form.get("result_id"))
        except (TypeError, ValueError):
            self.request.response.setStatus(400)
            return "result_id required"
        rule = form.get("rule", u"") or u""
        try:
            if add:
                user = self.request.get("AUTHENTICATED_USER")
                who = user.getId() if user is not None else u""
                self._store().annotate(rid, kind, form.get("reason"), who, rule=rule)
            else:
                self._store().unannotate(rid, kind, rule=rule)
        except ValueError as exc:
            sep = "&" if "?" in back else "?"
            self.request.response.redirect("%s%schart_error=%s" % (
                back, sep, str(exc).replace(" ", "+")))
            return ""
        self.request.response.redirect(back)
        return ""

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
        date_from   = self.selected_date_from() or None
        date_to     = self.selected_date_to() or None
        units       = QC_TYPE_UNITS.get(qc_type, "")
        target      = QC_TYPE_TARGETS.get(qc_type)

        if not self.db_available or not analyte or not qc_type:
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
                date_from=date_from,
                date_to=date_to,
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
            fv, nd = chart_value(qc_type, r)
            if fv is None:
                continue
            points.append({
                "nd":            nd,
                "id":            r.get("id"),
                "date":          str(r.get("run_date", ""))[:10],
                "value":         fv,
                "batch_id":      str(r.get("batch_id", "")),
                "flag":          str(r.get("flag", "")),
                "analyst":       str(r.get("analyst") or r.get("batch_analyst") or ""),
                "instrument_id": str(r.get("instrument_id", "")),
                "status":        str(r.get("result_status", "active")),
            })

        # Check if this QC type uses a threshold chart (blanks) vs L-J
        chart_type_override = self.selected_chart_type_override()
        try:
            from senaite.pfas.qc.rules import get_store as _get_rules_store
            is_threshold_auto = _get_rules_store().is_threshold_chart(qc_type)
            threshold_val = _get_rules_store().get_qc_type_rules(qc_type).get(
                "threshold"
            )
        except Exception:
            is_threshold_auto = qc_type in ("MB", "MxB", "LRB")
            threshold_val = None

        if chart_type_override == "threshold":
            is_threshold = True
        elif chart_type_override == "levey_jennings":
            is_threshold = False
        else:
            is_threshold = is_threshold_auto

        # Control-chart review: removed points are off the chart and out of
        # the mean / SD; dismissed warnings are set aside with who and why.
        from senaite.pfas import control_chart as cc
        try:
            notes = self._store().get_annotations([p["id"] for p in points])
        except Exception as e:                              # noqa: BLE001
            logger.error("chart annotations: %s", e)
            notes = []
        excluded = dict((n["result_id"], n) for n in notes if n["action"] == "excluded")
        dismissed = dict(("%s:%s" % (n["result_id"], n["rule"]), n)
                         for n in notes if n["action"] == "dismissed")
        removed = [dict(p, note=excluded[p["id"]]) for p in points if p["id"] in excluded]
        points = [p for p in points if p["id"] not in excluded]

        view_mode = self.selected_view_mode()
        if is_threshold:
            limits = None
            all_warnings = []
        else:
            limits = cc.limits([p["value"] for p in points])
            all_warnings = (cc.westgard if view_mode == "westgard" else cc.lj_warnings)(
                points, limits)
        for w in all_warnings:
            w["date"] = points[w["indices"][-1]]["date"]
            w["batch_id"] = points[w["indices"][-1]]["batch_id"]
            w["value"] = self._r(points[w["indices"][-1]]["value"])
        violations = cc.active(all_warnings, dismissed)
        dismissed_list = [dict(w, note=dismissed[w["key"]]) for w in all_warnings
                          if w["key"] in dismissed]

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
        point_viol, point_status, point_nd = [], [], []

        for i, p in enumerate(points):
            # one run per label: several runs share a date
            labels.append(u"%s %s" % (p["date"], p["batch_id"]))
            point_nd.append(bool(p.get("nd")))
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
            "qc_type_label":  self.qc_type_label(qc_type),
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
            "point_nd":       point_nd,
            "limits":         limits,
            "target":         target,
            "threshold":      self._r(threshold_val),
            "chart_type":     "threshold" if is_threshold else "levey_jennings",
            "westgard":       violations,
            "dismissed":      dismissed_list,
            "removed":        [{"id": p["id"], "date": p["date"], "batch_id": p["batch_id"],
                                "value": self._r(p["value"]), "note": p["note"]}
                               for p in removed],
            "view_mode":      view_mode,
            "has_rejects":    any(v["severity"] == "reject" for v in violations),
            "has_warnings":   any(v["severity"] == "warning" for v in violations),
            "n_points":       len(points),
            # example runs (tools/demo_control_charts.py): the page
            # says so whenever one is on the chart
            "demo_points":    sum(1 for b in batch_ids if b.startswith("DEMO-")),
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
            "westgard": [], "dismissed": [], "removed": [], "view_mode": "lj",
            "has_rejects": False,
            "has_warnings": False, "n_points": 0,
            "limit": limit, "show_history": history,
        }

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
