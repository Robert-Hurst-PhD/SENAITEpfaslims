# -*- coding: utf-8 -*-
"""
PFAS per-method per-stage time estimates from historical SENAITE workflow data.

Computes rolling averages across completed (verified) worksheets grouped by
method.  At least MIN_SAMPLES data points are required before an estimate is
emitted; stages with fewer samples return no estimate rather than a misleading
average.

Stage durations
---------------
  Stage 2 Extraction:    extraction_log[started] → extraction_log[completed]
  Stage 3 On Instrument: extraction_log[completed] → WS workflow 'submit' event
  Stage 4 QC Review:     WS workflow 'submit' event → WS workflow 'verify' event

  Stage 1 (Received) and Stage 5 (Published) durations are not currently
  computed — Stage 1 has no reliable start time, and Stage 5 (WS verify →
  individual AR publish) involves per-AR timing that is hard to aggregate.
  Both can be added when sufficient data is available.

  Stages 2 & 3 additionally require the extraction log to be retained on disk;
  if the log file has been removed for a batch, those stages contribute nothing
  to the average (they are skipped, not zeroed).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
import logging

from Products.CMFCore.utils import getToolByName

from .sample_status import (
    STAGE_EXTRACTION, STAGE_ON_INSTRUMENT, STAGE_QC_REVIEW,
    _load_extraction_log,
)

logger = logging.getLogger('senaite.pfas.browser.stage_estimates')

MIN_SAMPLES = 3  # minimum data points before emitting an estimate


# ── Time helpers ─────────────────────────────────────────────────────────────

def _zope_to_dt(zope_dt):
    """Convert Zope DateTime to naive Python datetime, or None."""
    if zope_dt is None:
        return None
    try:
        if hasattr(zope_dt, 'asdatetime'):
            return zope_dt.asdatetime().replace(tzinfo=None)
    except Exception:
        pass
    return None


def _parse_iso(ts):
    """Parse ISO 8601 / 'YYYY-MM-DD HH:MM' string to naive datetime, or None."""
    if not ts:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.datetime.strptime(str(ts)[:len(fmt)], fmt)
        except (ValueError, TypeError):
            pass
    return None


def _workflow_event_time(obj, action):
    """Return datetime of the most recent *action* transition on *obj*, or None."""
    try:
        for wf_events in obj.workflow_history.values():
            for event in reversed(list(wf_events)):
                if event.get('action') == action:
                    return _zope_to_dt(event.get('time'))
    except Exception:
        pass
    return None


def _hours(delta):
    """Convert timedelta to positive float hours, or None if delta is non-positive."""
    secs = delta.total_seconds()
    return secs / 3600.0 if secs > 0 else None


# ── Per-worksheet duration extractors ─────────────────────────────────────────

def _d_extraction(ws_id):
    """Stage 2 duration: log[started] → log[completed], hours."""
    log = _load_extraction_log(ws_id)
    if not log:
        return None
    t0 = _parse_iso(log.get('started'))
    t1 = _parse_iso(log.get('completed'))
    if t0 is None or t1 is None:
        return None
    return _hours(t1 - t0)


def _d_on_instrument(ws):
    """Stage 3 duration: log[completed] → WS submit, hours."""
    log = _load_extraction_log(ws.getId())
    if not log:
        return None
    t0 = _parse_iso(log.get('completed'))
    t1 = _workflow_event_time(ws, 'submit')
    if t0 is None or t1 is None:
        return None
    return _hours(t1 - t0)


def _d_qc_review(ws):
    """Stage 4 duration: WS submit → WS verify, hours."""
    t0 = _workflow_event_time(ws, 'submit')
    t1 = _workflow_event_time(ws, 'verify')
    if t0 is None or t1 is None:
        return None
    return _hours(t1 - t0)


def _get_method_title(ws):
    """Return method title from first analysis in worksheet."""
    try:
        for analysis in ws.getAnalyses():
            method = analysis.getMethod()
            if method:
                return method.Title() or method.getId()
    except Exception:
        pass
    return ''


# ── Public API ────────────────────────────────────────────────────────────────

def get_stage_estimates(portal, method_name):
    """
    Return {stage_num: avg_hours} for the given method (or all methods if empty).

    Only stages with >= MIN_SAMPLES data points are included.  Returns an empty
    dict if no completed worksheets exist yet.
    """
    catalog = getToolByName(portal, 'senaite_catalog_worksheet', None)
    if catalog is None:
        catalog = getToolByName(portal, 'portal_catalog')

    try:
        brains = catalog(portal_type='Worksheet', review_state='verified')
    except Exception as exc:
        logger.debug('Could not query completed worksheets: %s', exc)
        return {}

    buckets = {STAGE_EXTRACTION: [], STAGE_ON_INSTRUMENT: [], STAGE_QC_REVIEW: []}

    for brain in brains:
        try:
            ws = brain.getObject()
            if method_name and _get_method_title(ws) != method_name:
                continue
            ws_id = ws.getId()

            d2 = _d_extraction(ws_id)
            if d2 is not None:
                buckets[STAGE_EXTRACTION].append(d2)

            d3 = _d_on_instrument(ws)
            if d3 is not None:
                buckets[STAGE_ON_INSTRUMENT].append(d3)

            d4 = _d_qc_review(ws)
            if d4 is not None:
                buckets[STAGE_QC_REVIEW].append(d4)

        except Exception as exc:
            logger.debug('Error in estimate for WS brain: %s', exc)

    result = {}
    for stage, durations in buckets.items():
        if len(durations) >= MIN_SAMPLES:
            result[stage] = sum(durations) / float(len(durations))

    return result


def format_estimate(hours):
    """Return human-readable duration string, e.g. '~45 min', '~4 hours', '~2 days'."""
    if hours < 1.0:
        mins = max(1, int(round(hours * 60)))
        return '~{0} min'.format(mins)
    if hours < 48.0:
        h = int(round(hours))
        return '~{0} hour{1}'.format(h, 's' if h != 1 else '')
    days = int(round(hours / 24.0))
    return '~{0} day{1}'.format(days, 's' if days != 1 else '')
