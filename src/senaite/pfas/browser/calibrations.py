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
from senaite.pfas import run_calibration as rc
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.qc_lists import StoreListsMixin
from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal
from senaite.pfas.browser.perms import refuse

logger = logging.getLogger("senaite.pfas.browser.calibrations")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
DEFAULT_LIMIT = 50


# Resolved at the portal via perms: resolved at the context, a
# local role on any object reached through a for="*" view counted.
def _is_manager(context):
    return has_role_at_portal(context, MANAGER_ROLES)


def _stored_at(at):
    """A curve's stored UTC stamp, "YYYY-MM-DDTHH:MM:SS": on the laboratory's
    clock while the zone converts (the run's time is read from it), the
    stored text otherwise."""
    from senaite.pfas import print_doc
    return print_doc.lab_or(at, str(at)[:19], u"%Y-%m-%dT%H:%M:%S")


def calibration_qc_rows(store, batch_id):
    """The Calibration QC rows the worker wrote for one worksheet (the
    verdicts on its curves), whatever their date."""
    return store.get_qc_for_run(None, batch_id=batch_id, qc_types=["Calibration"])


class PFASCalibrationsView(StoreListsMixin, BrowserView):
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

    def _facets(self):
        if not hasattr(self, "_facets_cache"):
            try:
                self._facets_cache = self._store().calibration_facets(self.selected_method())
            except Exception as e:                              # noqa: BLE001
                logger.error("calibration_facets: %s", e)
                self._facets_cache = ([], [])
        return self._facets_cache

    def methods(self):
        """The methods with calibrations on record (the filter)."""
        return self._facets()[0] if self.db_available else []

    def analytes(self):
        """The analytes with curves on record, of the selected method."""
        return self._facets()[1] if self.db_available else []

    def runs(self):
        """The runs (one per worksheet that ran a curve set), newest first,
        of the selected method and analyte."""
        if not self.db_available:
            return []
        if not hasattr(self, "_runs_cache"):
            try:
                self._runs_cache = self._store().calibration_archive_runs(
                    method=self.selected_method(), analyte=self.selected_analyte() or None,
                    limit=self.selected_limit())
            except Exception as e:                              # noqa: BLE001
                logger.error("calibration_archive_runs: %s", e)
                self._runs_cache = []
        return self._runs_cache

    def selected_run(self):
        """The run shown: ?run=<worksheet>&run_date=, else the newest."""
        runs = self.runs()
        ws, rd = self.request.form.get("run", ""), self.request.form.get("run_date", "")
        for r in runs:
            if r["batch_id"] == ws and (not rd or r["run_date"] == rd):
                return r
        return runs[0] if runs else None



    # ── QC acceptance criteria: the METHOD PROFILE of each run's method ────

    def method_limits(self, method=None):
        """{"r2", "cal_pct", "CAL", "ICV", "CCV"} from `method`'s profile (the
        selected method when None); None for whatever the profile does not set
        -- not judged, never a default."""
        method = method or self.selected_method() or u""
        cache = self.__dict__.setdefault("_limits_cache", {})
        if method in cache:
            return cache[method]
        out = {"r2": None, "cal_pct": None, "CAL": {}, "ICV": {}, "CCV": {}, "level_unit": u"",
               "origin": None, "weighting": None}
        if method:
            try:
                from senaite.pfas.method_profile_store import get_profile
                from Products.CMFCore.utils import getToolByName
                portal = getToolByName(self.context, "portal_url").getPortalObject()
                profile = get_profile(portal, method) or {}
                iv = profile.get("instrument_verification") or {}
                from senaite.pfas.qc.rules import method_toggles
                judge_r2 = method_toggles(profile, method).get("cal_r2", True)
            except Exception:                                   # noqa: BLE001
                iv, judge_r2, profile = {}, True, {}
            cal, ccv, icv = (iv.get("calibration") or {}), (iv.get("ccv") or {}), (iv.get("icv") or {})
            num = lambda v: None if v in (None, u"") else float(v)       # noqa: E731
            # the same keys and rules the worker judges by (qc_engine:
            # calibration_check_profiled, _ccv_window, icv_check_profiled).
            # Charts draw each point's stored window when the run recorded
            # one; these are the fallback for runs stored before it did.
            # r2: judged only when the method sets a minimum AND its
            # "Calibration r2" switch is on (as the worker judges it)
            out["r2"] = num(cal.get("r2_min")) if judge_r2 else None
            out["cal_pct"] = num(cal.get("point_pct_dev_max"))
            out["CAL"] = {"max": out["cal_pct"], "low_max": num(cal.get("low_point_pct_dev_max")),
                          "warn": None}
            out["CCV"] = {"min": num(ccv.get("recovery_min")), "max": num(ccv.get("recovery_max")),
                          "low_min": num(ccv.get("low_level_min")),
                          "low_max": num(ccv.get("low_level_max"))}
            out["ICV"] = {"same_as_ccv": icv.get("criteria") == "ccv",
                          "max": num(icv.get("pct_dev_max"))}
            from senaite.pfas.calibration_levels import unit
            out["level_unit"] = unit(profile)
            # how the method's curve is fitted: the curve card starts from it
            from senaite.pfas import calibration_fit
            out["origin"] = calibration_fit.origin(cal)
            out["weighting"] = calibration_fit.weighting(cal)
        cache[method] = out
        return out

    def r2_minimum(self, method=None):
        """The method's minimum R² (Calibration & CCV), or None."""
        return self.method_limits(method)["r2"]

    def cal_pct_max(self, method=None):
        """The method's calibration point % deviation max, or None."""
        return self.method_limits(method)["cal_pct"]

    def qc_type_limits(self, method=None):
        """Per-QC-type % deviation limits for the method (None = not set)."""
        lim = self.method_limits(method)
        return {"CAL": lim["CAL"], "ICV": lim["ICV"], "CCV": lim["CCV"]}

    # ── Calibration data ──────────────────────────────────────────────────

    def calibrations(self, batch_id=None, run_date=None, method=None):
        """Return filtered list of calibration records for the template.

        With `batch_id` (a worksheet) or `run_date` + `method` given, that
        scope only and none of the page's filters: Data Review's Calibration
        tab shows one run's curves this way."""
        if not self.db_available:
            return []
        scoped = bool(batch_id or run_date)
        analyte = None if scoped else (self.selected_analyte() or None)
        method = method if scoped else self.selected_method()
        limit = 1000 if scoped else self.selected_limit()
        status_filter = u"" if scoped else self.selected_status()
        analyst_filter = None if scoped else self.selected_analyst()
        instrument_filter = None if scoped else self.selected_instrument()
        run_date_filter = run_date if scoped else self.selected_run_date()

        try:
            if batch_id:
                rows = self._store().calibrations_for_batch(batch_id)
            elif run_date:
                rows = self._store().get_calibrations_for_run(run_date, method=method)
            else:
                # the archive: the selected run's curves
                run = self.selected_run()
                rows = (self._store().calibration_run_curves(run["run_date"], run["batch_id"])
                        if run else [])
                run_date_filter = None
                if analyte:
                    rows = [r for r in rows if r.get("analyte") == analyte]
        except Exception as e:
            logger.error("get_calibrations: %s", e)
            return []

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
            r2_min = self.r2_minimum(row.get("method"))
            # None = the run's method sets no R² minimum: not judged
            r2_ok = (None if r2_min is None or r2 is None
                     else float(r2) >= r2_min)

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
                "created_at":          _stored_at(row.get("created_at", "")),
                "approved_by":         row.get("approved_by", "") or "",
                "approved_at":         _stored_at(row.get("approved_at", "") or ""),
                "fit_type_override":   row.get("fit_type_override", "") or "",
                "weight_override":     row.get("weight_override", "") or "",
                "origin_override":     row.get("origin_override", "") or "",
            })
        return result

    def calibration_runs(self, **scope):
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
        cals = self.calibrations(**scope)
        if not cals:
            return []
        try:
            levels_by_id = self._store().get_calibration_levels_many([c.get("id") for c in cals])
        except Exception as e:                                  # noqa: BLE001
            logger.error("get_calibration_levels_many: %s", e)
            levels_by_id = {}

        # one group per run (date and the worksheet that ran it), newest first
        seen_dates = []
        groups = {}
        for cal in cals:
            rd = (cal["run_date"], cal.get("batch_id") or u"")
            if rd not in groups:
                seen_dates.append(rd)
                # Extract time from created_at e.g. '2026-06-13T00:00:00' -> '00:00'
                created = cal.get("created_at", "")
                run_time = ""
                if "T" in created:
                    run_time = created.split("T")[1][:5]
                groups[rd] = {
                    "run_date":      rd[0],
                    "batch_id":      rd[1],
                    "run_time":      run_time,
                    "instrument_id": cal.get("instrument_id", ""),
                    "analyst":       cal.get("analyst", ""),
                    "method":        cal.get("method", ""),
                    "analytes":      [],
                }
            # Pre-fetch levels for each analyte
            cal["levels"] = self.calibration_levels(cal["id"], cal.get("method"),
                                                    rows=levels_by_id.get(cal["id"]))
            groups[rd]["analytes"].append(cal)

        result = []
        for rd in seen_dates:
            grp = groups[rd]
            grp["n_total"] = len(grp["analytes"])
            grp["n_pass"] = sum(1 for a in grp["analytes"] if a["r2_ok"])
            result.append(grp)
        return result

    def calibration_levels(self, calibration_id, method=None, rows=None):
        """Return per-level data for a single calibration: the worker's
        verdict and the ±% it judged the point by (`limit_pct`). A run stored
        before the limit was recorded gets the method's: the lowest level's
        own where set (qc_engine.calibration_check_profiled). The page never
        re-judges a point: it used one limit for every level, so a lowest
        calibrator inside its own wider window showed as failed."""
        if not self.db_available:
            return []
        if rows is None:
            try:
                rows = self._store().get_calibration_levels(calibration_id)
            except Exception as e:
                logger.error("get_calibration_levels %s: %s", calibration_id, e)
                return []

        lim = self.method_limits(method)["CAL"]
        result = []
        for row in rows:
            dev = row.get("pct_deviation")
            passed = bool(row.get("passed", 1))
            limit = row.get("limit_pct")
            if limit is None:
                low = lim.get("low_max") if u"%s" % row.get("level") in (u"1", u"low", u"MRL") else None
                limit = low or lim.get("max")
            rr = row.get("response_ratio")
            result.append({
                "level":          row.get("level"),
                "expected":       row.get("expected"),
                "calculated":     row.get("calculated"),
                "pct_deviation":  round(float(dev), 2) if dev is not None else None,
                "passed":         passed,
                "limit_pct":      limit,
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
        """The run shown: the one asked for, else the newest. One run at a
        time, as tabs (: every run's 34 analyte
        cards on one page ran to 9,000 px)."""
        asked = self.request.form.get("run_date", "")
        if asked:
            return asked
        dates = self.run_dates()
        return dates[0] if dates else ""

    def _qc_for_run(self, run_date, batch_id=None):
        """Return QC results for a run_date (one worksheet's, with batch_id),
        as a dict keyed by analyte."""
        try:
            rows = self._store().get_qc_for_run(
                run_date, batch_id=batch_id, qc_types=["ICV", "CCV", "CCB", "MB", "LFB"]
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
                # the recovery window the worker judged it in (None: older run)
                "limit_low":      r.get("limit_low"),
                "limit_high":     r.get("limit_high"),
            })
        return by_analyte

    def _rules_for_run(self, run):
        """{analyte: the rule's sentence} of the run's curves that fail the
        most-calibrators-dropped rule, read from the Calibration QC rows the
        worker wrote for the worksheet that ran the curves."""
        bid = run.get("batch_id")
        if not bid:
            # a verdict belongs to the worksheet whose worker wrote it; a curve
            # with none has no rule rows of its own
            return {}
        try:
            rows = calibration_qc_rows(self._store(), bid)
        except Exception as e:                                  # noqa: BLE001
            logger.error("_rules_for_run: %s", e)
            return {}
        return rc.dropped_rules(rows)

    # {analyte: [{injection, level, reason}]}: the calibrators taken off each
    # curve by hand, from the raw run's curve provenance. The page that holds
    # the raw run (Data Review) sets it; the archive has none.
    excluded_by_hand = None

    def calibration_runs_json(self, **scope):
        """Return JSON string of all run groups for the current filter (or
        the scope given: see calibrations())."""
        runs = self.calibration_runs(**scope)
        try:
            used_by = self._store().uses_of([c["id"] for run in runs for c in run["analytes"]])
        except Exception as e:                                  # noqa: BLE001
            logger.warning("uses_of: %s", e)
            used_by = {}
        # Augment each run with QC data and override values
        for run in runs:
            run["used_by"] = sorted(set(w for c in run["analytes"] for w in used_by.get(c["id"], [])))
            # the worksheet's own ICV/CCV, whatever date its curve was run on.
            # By date alone, every worksheet run that day was drawn on one
            # chart (110 bars and 55 solvent-blank chips; UI )
            bid = scope.get("batch_id") or run.get("batch_id")
            qc_by_analyte = self._qc_for_run(None if bid else run["run_date"], bid)
            rules = self._rules_for_run(run)
            run["rule_hold"] = rc.hold_reason(rules)
            for cal in run["analytes"]:
                cal["qc"] = qc_by_analyte.get(cal["analyte"], [])
                # the curve's own rule: the worker's sentence, and the
                # calibrators taken off by hand with the reason each was
                cal["rule_fail"] = rules.get(cal["analyte"], u"")
                cal["dropped"] = ((self.excluded_by_hand or {}).get(cal["analyte"], [])
                                  if cal["rule_fail"] else [])
                cal["fit_type_override"] = cal.get("fit_type_override", "")
                cal["weight_override"] = cal.get("weight_override", "")
                cal["origin_override"] = cal.get("origin_override", "")
                cal["approved_by"] = cal.get("approved_by", "")
                # each analyte's limits from ITS run's method profile
                cal["limits"] = self.qc_type_limits(cal.get("method"))
                cal["pct_max"] = cal["limits"]["CAL"].get("max")
                cal["r2_min"] = self.r2_minimum(cal.get("method"))
                # the unit the method's calibration levels are in (ppt in the
                # sample, or ng/mL in the extract): every chart label uses it
                cal["level_unit"] = self.method_limits(cal.get("method"))["level_unit"]
                # the curve card starts from the method's Origin and Weighting;
                # "" is None in the card's weighting select, null = not set
                ml = self.method_limits(cal.get("method"))
                cal["profile_origin"] = ml["origin"]
                cal["profile_weight"] = None if ml["weighting"] is None else (
                    u"" if ml["weighting"] == u"none" else ml["weighting"])
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
            return refuse(self.request, "Forbidden: Manager role required to update calibrations")

        action = self.request.form.get("action", "update")

        if action == "approve_run":
            # a run's calibration is approved in Data Review now; this page is
            # the archive
            return refuse(self.request, "Approve a run's calibration on its worksheet's "
                                        "Data Review, Calibration tab.")
        if action == "override":
            return self._handle_override()

        self.request.response.setStatus(400)
        return "Unknown action"

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
                by_user=getattr(self.request.get("AUTHENTICATED_USER"), "getId", lambda: u"")(),
            )
        except Exception as exc:
            logger.error("override failed: %s", exc)
            self.request.response.setStatus(500)
            return json.dumps({"error": str(exc)})
        return json.dumps({"ok": True})
