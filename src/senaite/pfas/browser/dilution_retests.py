# -*- coding: utf-8 -*-
"""Dilutions on SENAITE results (DECISIONS 2026-10-02 "Dilutions: SENAITE
retest"; pure rules in senaite.pfas.dilution_retest).

    @@pfas-dilution-result   the worker hands over a dilution's result for an
                             analysis (POST JSON); kept on the analysis
    append_dilution_retest() called by Data Review submission: the submitted
                             neat analysis gets a retest carrying the
                             dilution's result and analysis time

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json
import logging

from AccessControl import getSecurityManager
from Products.Five.browser import BrowserView
from zope.annotation.interfaces import IAnnotations

from senaite.pfas.dilution_retest import KEY, record, retest_plan

logger = logging.getLogger("senaite.pfas.browser.dilution_retests")

EDIT_RESULT = "senaite.core: Field: Edit Analysis Result"


def _load(analysis):
    try:
        return json.loads(IAnnotations(analysis).get(KEY) or u"null")
    except (TypeError, ValueError):
        return None


def _save(analysis, rec):
    IAnnotations(analysis)[KEY] = json.dumps(rec)


def dilution_fold(analysis):
    """The total fold an analysis's result was diluted by: the fold kept on
    the neat analysis this one is the retest of; None for any other."""
    try:
        if not analysis.isRetest():
            return None
        rec = _load(analysis.getRetestOf()) or {}
    except Exception:                                       # noqa: BLE001
        return None
    try:
        f = float(rec.get("factor"))
    except (TypeError, ValueError):
        return None
    return f if f > 1 else None


def pending_dilution(analysis):
    """The dilution kept on an analysis and not yet appended, or None."""
    rec = _load(analysis)
    return rec if rec and not rec.get("retest_uid") else None


def append_dilution_retest(analysis, wf_tool):
    """After the neat analysis is submitted: create its retest with the
    dilution's result, the dilution's analysis time as the capture date and a
    remark naming both readings, then submit the retest. Returns the retest
    or None. SENAITE's own create_retest is used directly: the `retest`
    TRANSITION would first verify the original, which the Analyst who just
    submitted it may not do (no self-verification); the Manager verifies both
    at approval, ending in the same state as the native path."""
    rec = pending_dilution(analysis)
    if rec is None:
        return None
    from bika.lims import api
    from bika.lims.utils.analysis import create_retest
    from DateTime import DateTime
    if api.get_review_status(analysis) != "to_be_verified" or analysis.getRetest():
        return None
    plan = retest_plan(rec)
    retest = create_retest(analysis)
    retest.setResult(plan["result"])
    try:
        retest.setResultCaptureDate(DateTime(plan["captured"]))
    except Exception as exc:                                # noqa: BLE001
        logger.warning("retest capture date %r: %s", plan["captured"], exc)
    retest.setRemarks(plan["remarks"])
    retest.reindexObject()
    wf_tool.doActionFor(retest, "submit")
    rec["retest_uid"] = api.get_uid(retest)
    _save(analysis, rec)
    logger.info("dilution %s appended to %s as retest %s", rec.get("injection"),
                analysis.getKeyword(), retest.getId())
    return retest


class PFASDilutionResultView(BrowserView):
    """POST {analysis_uid, result, qualifier, factor, injection, analysed_at,
    neat_*}: keep the dilution on the analysis. Needs the right to edit that
    analysis's result."""

    def __call__(self):
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if self.request.method != "POST":
            resp.setStatus(405)
            return json.dumps({"ok": False, "error": u"POST only"})
        try:
            body = json.loads(self.request.get("BODY") or u"{}")
        except (TypeError, ValueError):
            resp.setStatus(400)
            return json.dumps({"ok": False, "error": u"not JSON"})
        from bika.lims import api
        analysis = api.get_object_by_uid(body.get("analysis_uid") or u"", default=None)
        if analysis is None:
            resp.setStatus(404)
            return json.dumps({"ok": False, "error": u"no such analysis"})
        if not getSecurityManager().checkPermission(EDIT_RESULT, analysis):
            resp.setStatus(403)
            return json.dumps({"ok": False, "error": u"not allowed"})
        rec, why = record(body, datetime.datetime.utcnow().isoformat())
        if rec is None:
            resp.setStatus(400)
            return json.dumps({"ok": False, "error": why})
        try:
            from plone.protect.interfaces import IDisableCSRFProtection
            from zope.interface import alsoProvides
            alsoProvides(self.request, IDisableCSRFProtection)
        except ImportError:
            pass
        _save(analysis, rec)
        return json.dumps({"ok": True})
