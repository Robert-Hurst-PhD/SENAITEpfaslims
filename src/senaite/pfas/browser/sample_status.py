# -*- coding: utf-8 -*-
"""
PFAS Analyst Batch Status view (@@pfas-sample-status).

Shows each worksheet's progress through the five PFAS lab stages, the one
line of stage names Data Review and the Client Tracker show too:
  Received → Extraction → Analysis → Verify → Certificate issued

Stage is computed from SENAITE worksheet workflow state + the guided
extraction of the worksheet's batch (DB1: the tablet
service's log files, never even mounted in this container, are retired).
Never stored as a separate field — computed on every request so it can never
drift from the real workflow.

Stage detection rules:
  Stage 1 Received:       ws open + no extraction started
  Stage 2 Extraction:     ws open + extraction started, not finalized
  Stage 3 Analysis:       ws open + extraction finalized
  Stage 4 Verify:         ws to_be_verified OR (ws verified + no AR published)
  Stage 5 Certificate:    ws verified + at least one AR published

Mixed analysis states — least-advanced wins.  The worksheet FSM enforces this
naturally: ws cannot advance to to_be_verified until ALL analyses reach
to_be_verified.  Within the open/extraction/on-instrument range the extraction
is the tie-breaker.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers, core_method_name
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.sample_status")

STAGE_RECEIVED      = 1
STAGE_EXTRACTION    = 2
STAGE_ON_INSTRUMENT = 3
STAGE_QC_REVIEW     = 4
STAGE_PUBLISHED     = 5

# The one line of stage names: this page, Data Review's line of stages and
# the Client Tracker all read it. Each stage's picture (icons.py) is named
# here beside it, so a stage is drawn the same wherever it is listed.
STAGES = [
    (STAGE_RECEIVED,      "Received"),
    (STAGE_EXTRACTION,    "Extraction"),
    (STAGE_ON_INSTRUMENT, "Analysis"),
    (STAGE_QC_REVIEW,     "Verify"),
    (STAGE_PUBLISHED,     "Certificate issued"),
]
STAGE_ICONS = {
    STAGE_RECEIVED:      "received",
    STAGE_EXTRACTION:    "extraction",
    STAGE_ON_INSTRUMENT: "analysis",
    STAGE_QC_REVIEW:     "verify",
    STAGE_PUBLISHED:     "issued",
}

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


def _state_title(ws, state):
    """The worksheet's workflow state as core titles it, never its id."""
    try:
        title = getToolByName(ws, "portal_workflow").getTitleForStateOnType(state, "Worksheet")
    except Exception as exc:                                # noqa: BLE001
        logger.warning("state title of %s: %s", getattr(ws, "getId", lambda: "?")(), exc)
        title = None
    return (title or state or u"").strip()


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


def _load_extraction_log(ws):
    """{started, completed, analyst} of the guided extraction of this
    worksheet's batch, or None when none was started. Takes the worksheet;
    given its id, it is looked up (three callers still passed the id after
    the worksheet became the extraction batch; and every one failed
    silently -- the Data Review queue listed nothing)."""
    from senaite.pfas.browser.extraction_guide import _load_session
    from senaite.pfas.extraction_sidecar import extraction_progress
    if isinstance(ws, basestring if str is bytes else str):   # noqa: F821
        from bika.lims import api
        found = api.search({"portal_type": "Worksheet", "id": ws}, "senaite_catalog_worksheet")
        if not found:
            return None
        ws = found[0].getObject()
    try:
        # the worksheet is the extraction batch
        sess = _load_session(ws)
        if sess:
            return extraction_progress(sess)
        for analysis in ws.getAnalyses() or []:             # an older record
            ar = _get_ar(analysis)
            batch = ar.getBatch() if ar is not None else None
            if batch is not None:
                return extraction_progress(_load_session(batch))
    except Exception as exc:                                # noqa: BLE001
        logger.warning("extraction for %s: %s", ws.getId(), exc)
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
                return core_method_name(method)
    except Exception:
        pass
    return ""


_NOT_READ = object()


def _compute_stage(ws, log=_NOT_READ):
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

    # ws is "open" — differentiate Received / Extraction / On Instrument via
    # log (read here unless the caller already has it)
    if log is _NOT_READ:
        log = _load_extraction_log(ws)

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
        steps.append({"num": s_num, "label": s_label, "status": status,
                      "icon": STAGE_ICONS.get(s_num, "received")})
    return steps


def _fmt_iso(iso_str):
    """A UTC ISO timestamp as YYYY-MM-DD HH:MM for display, on the
    laboratory's clock while the zone converts."""
    if not iso_str:
        return ""
    from senaite.pfas import print_doc
    return print_doc.lab_or(iso_str, str(iso_str)[:16].replace("T", " "))


# ── View ─────────────────────────────────────────────────────────────────────

SHOW = ((u"", u"Not finished"), (u"published", u"Report published"), (u"all", u"All"))


def keep(show, ws_state, published):
    """Whether Batch Status lists a worksheet: "" (the default) what is
    not finished (any worksheet but one whose report is published),
    "published" those, "all" every one. `published` is asked only of a
    verified worksheet, the one state where it can be true."""
    if show == u"all":
        return True
    done = ws_state == "verified" and published()
    return done if show == u"published" else not done


class PFASSampleStatusView(ViewHelpers, BrowserView):
    """
    @@pfas-sample-status: where each worksheet stands, one page at a time.

    Lists the SENAITE Worksheets (rejected ones left out), newest first,
    opening on those not finished: which of the five PFAS lab stages each
    is at, who is responsible, and its guided extraction. Lab staff only
    (perms.keep_clients_out): a client follows a sample on the Client
    Tracker.
    """

    template = ViewPageTemplateFile("templates/sample_status.pt")
    SHOW = SHOW

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def show(self):
        v = (self.request.form.get("show") or u"").strip()
        return v if v in [k for k, _l in SHOW] else u""

    def q(self):
        return (self.request.form.get("q") or u"").strip()

    def url(self, show=None, page=None):
        from senaite.pfas.browser.list_paging import list_url
        return list_url(u"%s/@@pfas-sample-status" % self.portal_url(),
                        [("show", self.show() if show is None else show), ("q", self.q()),
                         ("page", page if page and page > 1 else None)])

    def shows(self):
        return [{"label": l, "url": self.url(show=k), "on": k == self.show()} for k, l in SHOW]

    def _brains(self):
        """The worksheets the filters keep, newest first: the catalog's
        order and metadata, a worksheet woken only to ask whether a verified
        one's report is published."""
        portal = _portal(self.context)
        # SENAITE 2.6 routes Worksheets to senaite_catalog_worksheet, not
        # portal_catalog.  Fall back to portal_catalog if the dedicated
        # catalog doesn't exist (other SENAITE versions / test environments).
        catalog = getToolByName(portal, "senaite_catalog_worksheet", None)
        if catalog is None:
            catalog = getToolByName(portal, "portal_catalog")
        try:
            brains = catalog(portal_type="Worksheet", sort_on="created", sort_order=str("descending"))
        except Exception as exc:
            logger.warning("Could not query Worksheets: %s", exc)
            return []
        show, q = self.show(), self.q().lower()
        out = []
        self._any = False
        for brain in brains:
            try:
                ws_state = brain.review_state
                if ws_state in _SKIP_STATES:
                    continue
                self._any = True
                if q and q not in (u"%s %s" % (brain.getId, brain.Title or u"")).lower():
                    continue
                if keep(show, ws_state,
                        lambda: _compute_stage(brain.getObject())[0] == STAGE_PUBLISHED):
                    out.append(brain)
            except Exception as exc:
                logger.warning("Error filtering worksheet %s: %s", getattr(brain, "getId", "?"), exc)
        return out

    def paging(self):
        if not hasattr(self, "_pg"):
            from senaite.pfas.browser.list_paging import page_number, paging
            self._kept = self._brains()
            self._pg = paging(len(self._kept), page_number(self.request.form),
                              lambda p: self.url(page=p))
        return self._pg

    def empty_text(self):
        self.paging()
        if not getattr(self, "_any", False):
            return u"No worksheet yet. A worksheet is made from received samples."
        if self.q():
            return u"No worksheet matches this search."
        return {u"": u"Every worksheet's report is published.",
                u"published": u"No worksheet has its report published yet."}.get(
                    self.show(), u"No worksheet yet. A worksheet is made from received samples.")

    def batches(self):
        """The page of worksheets shown, each a dict safe to use directly
        in the TAL template."""
        if not hasattr(self, "_rows"):
            pg = self.paging()
            self._rows = []
            for brain in self._kept[pg["start"]:pg["end"]]:
                try:
                    self._rows.append(self._row(brain.getObject(), brain.review_state))
                except Exception as exc:
                    logger.warning("Error processing worksheet %s: %s",
                                   getattr(brain, "getId", "?"), exc)
        return self._rows

    def _row(self, ws, ws_state):
        log = _load_extraction_log(ws)
        stage, responsible = _compute_stage(ws, log)
        sample_ids = _get_sample_ids(ws)
        return {
            "batch_id":    ws.getId(),
            "url":         ws.absolute_url(),
            "title":       ws.Title() or ws.getId(),
            "ws_state":    ws_state,
            "ws_state_title": _state_title(ws, ws_state),
            "stage":       stage,
            "stage_label": dict(STAGES).get(stage, ""),
            "stage_icon":  STAGE_ICONS.get(stage),
            "responsible": responsible,
            "method":      _get_method_name(ws),
            "sample_ids":  sample_ids,
            "sample_count": len(sample_ids),
            "created":     self.lab_at(ws.created(), ws.created().strftime("%Y-%m-%d"), u"%Y-%m-%d"),
            "steps":       _build_stage_steps(stage),
            # Extraction log details (empty strings if no log)
            "extraction_started":
                _fmt_iso(log.get("started",   "")) if log else "",
            "extraction_completed":
                _fmt_iso(log.get("completed", "")) if log else "",
            "extraction_analyst":
                log.get("analyst", "") if log else "",
        }
