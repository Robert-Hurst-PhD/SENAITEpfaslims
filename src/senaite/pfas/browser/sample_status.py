# -*- coding: utf-8 -*-
"""
PFAS Analyst Batch Status view (@@pfas-sample-status).

Shows per-batch (per-Worksheet) progress through the five PFAS lab stages:
  Received → Extraction → On Instrument → QC Review → Report Published

Stage is computed from SENAITE worksheet workflow state + extraction logs in
/data/extraction_logs/{worksheet_id}_extraction.json.  Never stored as a
separate field — computed on every request so it can never drift from the
real workflow.

Stage detection rules (confirmed 2026-06-11):
  Stage 1 Received:       ws open + no extraction log
  Stage 2 Extraction:     ws open + log exists, completed=null
  Stage 3 On Instrument:  ws open + log exists, completed set
  Stage 4 QC Review:      ws to_be_verified OR (ws verified + no AR published)
  Stage 5 Report Pub.:    ws verified + at least one AR published

Mixed analysis states — least-advanced wins.  The worksheet FSM enforces this
naturally: ws cannot advance to to_be_verified until ALL analyses reach
to_be_verified.  Within the open/extraction/on-instrument range the extraction
log is the tie-breaker.

Extraction log matching: the batch_id passed to POST /log/start must equal the
SENAITE Worksheet ID (e.g. WS-001).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.sample_status")

EXTRACTION_LOG_DIR = os.environ.get("EXTRACTION_LOG_DIR", "/data/extraction_logs")

STAGE_RECEIVED      = 1
STAGE_EXTRACTION    = 2
STAGE_ON_INSTRUMENT = 3
STAGE_QC_REVIEW     = 4
STAGE_PUBLISHED     = 5

STAGES = [
    (STAGE_RECEIVED,      "Received"),
    (STAGE_EXTRACTION,    "Extraction"),
    (STAGE_ON_INSTRUMENT, "On Instrument"),
    (STAGE_QC_REVIEW,     "QC Review"),
    (STAGE_PUBLISHED,     "Report Published"),
]

# Worksheet states that should be excluded from the active list
_SKIP_STATES = frozenset(("rejected",))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _portal(context):
    return context.portal_url.getPortalObject()


def _workflow_state(obj):
    try:
        wf_tool = getToolByName(obj, "portal_workflow")
        return wf_tool.getInfoFor(obj, "review_state", "")
    except Exception:
        return ""


def _fullname(context, userid):
    """Resolve a SENAITE user ID to a display name via portal_membership."""
    if not userid:
        return ""
    try:
        mtool = getToolByName(context, "portal_membership")
        member = mtool.getMemberById(userid)
        if member:
            fn = member.getProperty("fullname", "")
            return fn if fn else userid
    except Exception:
        pass
    return userid


def _load_extraction_log(batch_id):
    """Load extraction log JSON for a worksheet ID.  Returns dict or None."""
    path = os.path.join(EXTRACTION_LOG_DIR,
                        "{0}_extraction.json".format(batch_id))
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (IOError, ValueError) as exc:
        logger.warning("Could not read extraction log %s: %s", path, exc)
        return None


def _get_worksheet_actor(ws, action):
    """
    Return user ID of whoever last performed *action* on this worksheet
    (e.g. 'submit' to find who sent it for QC review).
    Reads the Zope workflow history stored on the object.
    """
    try:
        history = ws.workflow_history
        for wf_events in history.values():
            for event in reversed(list(wf_events)):
                if event.get("action") == action:
                    return event.get("actor", "")
    except Exception:
        pass
    return ""


def _get_ar(analysis):
    """Return the AnalysisRequest that owns *analysis*, or None."""
    try:
        ar = analysis.getRequest()
        if ar is not None:
            return ar
    except AttributeError:
        pass
    parent = getattr(analysis, "aq_parent", None)
    if parent is not None:
        pt = getattr(parent, "portal_type", "")
        if pt == "AnalysisRequest":
            return parent
    return None


def _get_ar_states(ws):
    """
    Return a set of unique review_state values for all ARs in the worksheet.
    Uses the portal_catalog to avoid re-loading objects where possible.
    """
    seen = {}
    try:
        for analysis in ws.getAnalyses():
            ar = _get_ar(analysis)
            if ar is None:
                continue
            ar_id = ar.getId()
            if ar_id not in seen:
                seen[ar_id] = _workflow_state(ar)
    except Exception as exc:
        logger.debug("_get_ar_states error for %s: %s", ws.getId(), exc)
    return set(seen.values())


def _get_sample_ids(ws):
    """Return sorted list of unique AR IDs for all analyses in the worksheet."""
    seen = set()
    try:
        for analysis in ws.getAnalyses():
            ar = _get_ar(analysis)
            if ar is not None:
                seen.add(ar.getId())
    except Exception:
        pass
    return sorted(seen)


def _get_method_name(ws):
    """Return the method title from the first analysis in the worksheet."""
    try:
        for analysis in ws.getAnalyses():
            method = analysis.getMethod()
            if method:
                return method.Title() or method.getId()
    except Exception:
        pass
    return ""


def _compute_stage(ws):
    """
    Return (stage_int, responsible_display_name) for a worksheet.

    Responsible person:
      Stages 1-3: extraction log analyst (or ws analyst as fallback)
      Stage 4:    analyst who submitted for review
      Stage 5:    worksheet analyst (publisher may differ but is not easily
                  accessible; the analyst is the primary accountable person)
    """
    ws_state = _workflow_state(ws)

    analyst_id = ""
    try:
        analyst_id = ws.getAnalyst() or ""
    except Exception:
        pass

    if ws_state == "verified":
        ar_states = _get_ar_states(ws)
        # Least-advanced wins: ALL ARs must be published before Stage 5.
        # A single published AR while others are verified = still Stage 4.
        if ar_states and all(s == "published" for s in ar_states):
            return STAGE_PUBLISHED, _fullname(ws, analyst_id)
        return STAGE_QC_REVIEW, _fullname(ws, analyst_id)

    if ws_state == "to_be_verified":
        submitter_id = _get_worksheet_actor(ws, "submit") or analyst_id
        return STAGE_QC_REVIEW, _fullname(ws, submitter_id)

    # ws is "open" — differentiate Received / Extraction / On Instrument via log
    batch_id = ws.getId()
    log = _load_extraction_log(batch_id)

    if log is None:
        return STAGE_RECEIVED, _fullname(ws, analyst_id)

    log_analyst = log.get("analyst", "") or analyst_id
    if log.get("completed"):
        return STAGE_ON_INSTRUMENT, _fullname(ws, log_analyst)
    return STAGE_EXTRACTION, _fullname(ws, log_analyst)


def _build_stage_steps(current_stage):
    """Return list of step dicts for the progress indicator template."""
    steps = []
    for s_num, s_label in STAGES:
        if s_num < current_stage:
            status = "done"
        elif s_num == current_stage:
            status = "current"
        else:
            status = "pending"
        steps.append({"num": s_num, "label": s_label, "status": status})
    return steps


def _fmt_iso(iso_str):
    """Trim ISO timestamp to YYYY-MM-DD HH:MM for display."""
    if not iso_str:
        return ""
    return str(iso_str)[:16].replace("T", " ")


# ── View ─────────────────────────────────────────────────────────────────────

class PFASSampleStatusView(BrowserView):
    """
    @@pfas-sample-status — analyst/manager per-batch status view.

    Lists all SENAITE Worksheets (excluding rejected) sorted newest-first,
    showing which of the five PFAS lab stages each batch is at, who is
    responsible, and the extraction log status if available.
    """

    template = ViewPageTemplateFile("templates/sample_status.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def batches(self):
        """
        Return list of batch-status dicts for all active worksheets.
        Each dict is safe to use directly in the TAL template.
        """
        portal = _portal(self.context)
        # SENAITE 2.6 routes Worksheets to senaite_catalog_worksheet, not
        # portal_catalog.  Fall back to portal_catalog if the dedicated
        # catalog doesn't exist (other SENAITE versions / test environments).
        catalog = getToolByName(portal, "senaite_catalog_worksheet", None)
        if catalog is None:
            catalog = getToolByName(portal, "portal_catalog")
        try:
            brains = catalog(portal_type="Worksheet")
        except Exception as exc:
            logger.warning("Could not query Worksheets: %s", exc)
            return []

        result = []
        for brain in brains:
            try:
                ws_state = brain.review_state
                if ws_state in _SKIP_STATES:
                    continue
                ws = brain.getObject()
                stage, responsible = _compute_stage(ws)
                log = _load_extraction_log(ws.getId())
                sample_ids = _get_sample_ids(ws)
                result.append({
                    "batch_id":    ws.getId(),
                    "title":       ws.Title() or ws.getId(),
                    "ws_state":    ws_state,
                    "stage":       stage,
                    "stage_label": dict(STAGES).get(stage, ""),
                    "responsible": responsible,
                    "method":      _get_method_name(ws),
                    "sample_ids":  sample_ids,
                    "sample_count": len(sample_ids),
                    "created":     ws.created().strftime("%Y-%m-%d"),
                    "steps":       _build_stage_steps(stage),
                    # Extraction log details (empty strings if no log)
                    "extraction_started":
                        _fmt_iso(log.get("started",   "")) if log else "",
                    "extraction_completed":
                        _fmt_iso(log.get("completed", "")) if log else "",
                    "extraction_analyst":
                        log.get("analyst", "") if log else "",
                })
            except Exception as exc:
                logger.warning("Error processing worksheet %s: %s",
                               getattr(brain, "getId", lambda: "?")(), exc)
        result.sort(key=lambda r: r["created"], reverse=True)
        return result
