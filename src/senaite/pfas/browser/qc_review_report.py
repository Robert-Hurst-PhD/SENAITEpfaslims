# -*- coding: utf-8 -*-
"""
QC Review Report (@@pfas-qc-review-report) — the reviewer/auditor counterpart
to the client Certificate of Analysis.

The CoA answers "what was the result". This answers "why should anyone believe
it": which criteria were applied, what every QC check returned against them,
which reagent lot every number traces back to, what the run actually did versus
what was planned, and every per-injection measurement behind it.

It is a VIEW onto data the system already holds, and it delegates to the Data
Review methods rather than recomputing anything. That is deliberate: this
project's recurring defect has been a fact recorded correctly in one place and
never carried to where it is used — seven separate instances of it — and a
report that recomputed the QC matrix would become the eighth the first time one
side changed.

Rendered two ways:

  * as an impress template (``senaite.pfas:QCReviewReport.pt``), so it appears
    in the publish picker alongside the CoA;
  * standalone at ``@@pfas-qc-review-report`` for on-screen review.

At publish time a snapshot is frozen against the publication revision (see
``snapshot_for_publication``), so re-opening revision 1 later shows what was
true when the client's certificate was issued rather than what is true now.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.qc_review_report")

SNAPSHOT_KEY = u"senaite.pfas.qc_review_snapshots"


def _review_status(obj):
    """Workflow state of an object. Worksheet has no review_state() accessor,
    so reading one gave a blank field on the report."""
    try:
        from bika.lims import api
        return api.get_review_status(obj) or u""
    except Exception:
        return u""


def _worksheet_for(obj):
    """The worksheet a sample, batch or worksheet belongs to.

    impress publishes from AnalysisRequests while the review data hangs off the
    Worksheet, so the report has to bridge the two. Every analysis knows its
    worksheet; the batch route covers a report rendered from batch context.
    """
    portal_type = getattr(obj, "portal_type", "")
    if portal_type == "Worksheet":
        return obj
    if portal_type == "AnalysisRequest":
        for analysis in obj.objectValues("Analysis"):
            try:
                worksheet = analysis.getWorksheet()
            except Exception:
                continue
            if worksheet is not None:
                return worksheet
        return None
    if portal_type == "Batch":
        try:
            from bika.lims import api
            cat = getToolByName(obj, "senaite_catalog_sample")
            for brain in cat.unrestrictedSearchResults(
                    portal_type="AnalysisRequest", getBatchUID=api.get_uid(obj)):
                found = _worksheet_for(brain.getObject())
                if found is not None:
                    return found
        except Exception:
            return None
    return None


class PFASQCReviewReportView(BrowserView):
    """Assembles the reviewer report. Every section delegates."""

    template = ViewPageTemplateFile("templates/qc_review_report.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    # ── context ──────────────────────────────────────────────────────────

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def worksheet(self):
        if not hasattr(self, "_ws"):
            self._ws = _worksheet_for(self.context)
        return self._ws

    def _review(self):
        """The Data Review view for this worksheet — the single source of every
        computed section below."""
        if not hasattr(self, "_rv"):
            worksheet = self.worksheet()
            # str() is load-bearing: unicode_literals makes this a unicode
            # string, and Zope's traverse treats a non-str path as a SEQUENCE
            # of segments — so it walked the view name one character at a time.
            self._rv = (worksheet.restrictedTraverse(str("@@pfas-data-review"))
                        if worksheet is not None else None)
            if self._rv is not None:
                # A report rendered from sample context must still resolve the
                # worksheet the review data hangs off.
                self._rv.request.form[str("batch_id")] = worksheet.getId()
        return self._rv

    def available(self):
        return self._review() is not None

    # ── 1. identity ──────────────────────────────────────────────────────

    def identity(self):
        review = self._review()
        worksheet = self.worksheet()
        if review is None:
            return {}
        batch = review._linked_batch(worksheet)
        matrix = review._batch_matrix()
        method_id = review.batch_method()
        out = {
            "worksheet": worksheet.getId(),
            "batch": batch.getId() if batch is not None else u"",
            "batch_title": batch.Title() if batch is not None else u"",
            "method": method_id,
            "matrix": matrix,
            "analyst": getattr(worksheet, "getAnalyst", lambda: u"")() or u"",
            "state": _review_status(worksheet),
        }
        try:
            from senaite.pfas.method_profile_store import get_profile
            profile = get_profile(self._portal(), method_id) or {}
            out["unit"] = (profile.get("unit_map") or {}).get(matrix, u"")
            for entry in (profile.get("matrix_factors") or []):
                if (entry.get("matrix") or u"") == matrix:
                    out["matrix_factor"] = entry.get("factor")
                    break
        except Exception:
            pass
        out["run_dates"] = self._run_dates()
        return out

    def _run_dates(self):
        review = self._review()
        rows = review._injection_rows() if review else []
        return sorted({r.get("run_date") for r in rows if r.get("run_date")})

    # ── 2. the criteria actually applied ─────────────────────────────────

    def criteria(self):
        """The thresholds this batch was judged against.

        Worth stating plainly: until the nested instrument_verification
        structure was wired up, these came from Python constants whatever the
        Method Profile said. Printing them is only now truthful.
        """
        review = self._review()
        if review is None:
            return []
        profile = review._method_profile() or {}
        iv = profile.get("instrument_verification") or {}
        cal = iv.get("calibration") or {}
        ccv = iv.get("ccv") or {}
        is_resp = iv.get("is_response") or {}
        conf = iv.get("confirmation") or {}

        def row(label, value, source):
            return {"criterion": label, "value": value, "source": source}

        out = [
            row(u"Calibration r² minimum", cal.get("r2_min"),
                u"Method Profile · instrument_verification.calibration"),
            row(u"CCV recovery window",
                self._window(ccv.get("recovery_min"), ccv.get("recovery_max")),
                u"Method Profile · instrument_verification.ccv"),
            row(u"CCV frequency", ccv.get("frequency"),
                u"Method Profile · instrument_verification.ccv"),
            row(u"Internal standard vs ICAL average",
                self._window(is_resp.get("vs_ical_avg_min"),
                             is_resp.get("vs_ical_avg_max")),
                is_resp.get("notes")
                or u"Method Profile · instrument_verification.is_response"),
            row(u"Ion-ratio tolerance",
                self._pct(conf.get("ion_ratio_tol_pct")),
                u"Method Profile · instrument_verification.confirmation"),
            row(u"Signal-to-noise minimum", conf.get("sn_quan_min"),
                u"Method Profile · instrument_verification.confirmation"),
        ]
        for qc_type, cfg in sorted((profile.get("qc_acceptance") or {}).items()):
            if not cfg.get("enabled", True):
                continue
            for tier in (cfg.get("tiers") or []):
                out.append(row(
                    u"{0} recovery — {1}".format(qc_type,
                                                 tier.get("name", u"tier")),
                    self._window(tier.get("recovery_min"),
                                 tier.get("recovery_max")),
                    u"Method Profile · qc_acceptance.{0}".format(qc_type)))
        return [r for r in out if r["value"] not in (None, u"")]

    @staticmethod
    def _window(low, high):
        if low is None and high is None:
            return u""
        return u"{0}–{1}%".format(low, high)

    @staticmethod
    def _pct(value):
        return u"±{0}%".format(value) if value is not None else u""

    # ── 3-6, 9. delegated sections ───────────────────────────────────────

    def gates(self):
        review = self._review()
        return review.checklist_status() if review else []

    def qc_summary(self):
        review = self._review()
        return review.get_qc_summary() if review else {}

    def spike_qc(self):
        review = self._review()
        return review.spike_qc_page() if review else {}

    def sample_results(self):
        review = self._review()
        return review.sample_results_page() if review else []

    def traceability(self):
        review = self._review()
        return review.get_traceability_tree() if review else {}

    def final_data(self):
        review = self._review()
        return review.get_final_data() if review else []

    def coc(self):
        review = self._review()
        return review.coc_summary() if review else {}

    def deviations(self):
        review = self._review()
        try:
            return review.active_deviations_for_worksheet() if review else []
        except Exception:
            return []

    # ── 4. calibration curves ────────────────────────────────────────────

    def calibrations(self):
        """r² per analyte for this run, against the criterion it was judged by."""
        review = self._review()
        if review is None or not review.db_available:
            return []
        try:
            store = review._store()
            # get_calibrations has no batch filter; the per-run accessor does.
            rows = store.get_calibrations_for_run(
                (self._run_dates() or [None])[-1],
                batch_id=review.batch_id())
        except Exception as exc:
            logger.warning("calibrations: %s", exc)
            return []
        profile = review._method_profile() or {}
        r2_min = ((profile.get("instrument_verification") or {})
                  .get("calibration") or {}).get("r2_min")
        out = []
        for row in rows:
            r2 = row.get("r2")
            out.append({
                "analyte": row.get("analyte", u""),
                "r2": r2,
                "limit": r2_min,
                "passed": (r2 is not None and r2_min is not None
                           and r2 >= r2_min),
            })
        return sorted(out, key=lambda r: r["analyte"])

    # ── 8. run versus plan ───────────────────────────────────────────────

    def run_vs_plan(self):
        """What the Run Builder planned against what the instrument ran."""
        review = self._review()
        worksheet = self.worksheet()
        if review is None:
            return {}
        batch = review._linked_batch(worksheet)
        planned = []
        if batch is not None:
            try:
                from senaite.pfas.browser.run_builder import RUN_MANIFEST_KEY
                raw = IAnnotations(batch).get(RUN_MANIFEST_KEY)
                if raw:
                    manifest = json.loads(raw)
                    planned = [r.get("name") for r in
                               (manifest.get("rows") or []) if r.get("name")]
            except Exception:
                planned = []
        actual = sorted({r.get("injection_name")
                         for r in review._injection_rows()
                         if r.get("injection_name")})
        return {
            "planned": planned,
            "actual": actual,
            "not_run": [p for p in planned if p not in actual],
            "unplanned": [a for a in actual if planned and a not in planned],
        }

    # ── 10. appendix: every per-injection measurement ────────────────────

    def injection_detail(self):
        """Every injection × compound row behind this batch."""
        review = self._review()
        if review is None:
            return []
        rows = review._injection_rows()
        return sorted(rows, key=lambda r: (r.get("qc_type") or u"",
                                           r.get("injection_name") or u"",
                                           r.get("analyte") or u""))

    def exceptions(self):
        """The flagged subset, so the failures can be read without wading
        through the passing rows."""
        return [r for r in self.injection_detail() if (r.get("flag") or u"")]

    # ── publication history ──────────────────────────────────────────────

    def publications(self):
        out = []
        try:
            from senaite.pfas.browser.controlled_publications import (
                get_publication_log)
        except Exception:
            return out
        for sample in self._samples():
            for entry in get_publication_log(sample):
                row = dict(entry)
                row["sample"] = sample.getId()
                out.append(row)
        return out

    def _samples(self):
        worksheet = self.worksheet()
        if worksheet is None:
            return []
        seen, out = set(), []
        for analysis in (worksheet.getAnalyses() or []):
            try:
                sample = analysis.getRequest()
            except Exception:
                continue
            if sample is not None and sample.getId() not in seen:
                seen.add(sample.getId())
                out.append(sample)
        return out


# ── publish-time snapshot ────────────────────────────────────────────────

def snapshot_for_publication(ar, revision):
    """Freeze the reviewer report against a publication revision.

    A report regenerated later reflects the data as it is NOW; an auditor
    asking about a certificate issued last October needs what was true then.
    The rendered HTML is stored on the sample beside the publication log entry
    it belongs to.
    """
    try:
        view = ar.restrictedTraverse(str("@@pfas-qc-review-report"))
        html = view()
    except Exception as exc:
        logger.error("qc-review snapshot failed for %s rev %s: %s",
                     getattr(ar, "getId", lambda: "?")(), revision, exc)
        return None
    ann = IAnnotations(ar)
    store = dict(ann.get(SNAPSHOT_KEY) or {})
    store[str(revision)] = html
    ann[SNAPSHOT_KEY] = store
    logger.info("qc-review snapshot stored for %s revision %s",
                ar.getId(), revision)
    return html


def get_snapshot(ar, revision):
    """The frozen reviewer report for a revision, or None."""
    store = IAnnotations(ar).get(SNAPSHOT_KEY) or {}
    return store.get(str(revision))
