# -*- coding: utf-8 -*-
"""Above the calibration range with no dilution (rules in
senaite.pfas.above_range).

    @@pfas-above-range   the worker hands over an ALoQ result's record (the
                         top of the range on the sample basis, the reading,
                         the injection) for an analysis (POST JSON); kept on
                         the analysis, or cleared with {"clear": true}
The certificate and Data Review read the record with above_range.of(),
while the analysis's Result is still ALoQ.

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json
import logging

from AccessControl import getSecurityManager
from Products.Five.browser import BrowserView
from zope.annotation.interfaces import IAnnotations

from senaite.pfas import above_range as ar
from senaite.pfas.above_range import KEY as ABOVE_RANGE_KEY
from senaite.pfas.browser.perms import refuse

logger = logging.getLogger("senaite.pfas.browser.above_range_view")

EDIT_RESULT = "senaite.core: Field: Edit Analysis Result"


class PFASAboveRangeView(BrowserView):
    """POST {analysis_uid, limit, reading, injection} or {analysis_uid,
    clear: true}. Needs the right to edit that analysis's result."""

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
            return refuse(self.request, json.dumps({"ok": False, "error": u"not allowed"}))
        from senaite.pfas.browser.perms import disable_csrf
        if body.get("clear"):
            disable_csrf(self.request)
            ann = IAnnotations(analysis)
            if ABOVE_RANGE_KEY in ann:
                del ann[ABOVE_RANGE_KEY]
            return json.dumps({"ok": True})
        rec, why = ar.record(body, datetime.datetime.utcnow().isoformat())
        if rec is None:
            resp.setStatus(400)
            return json.dumps({"ok": False, "error": why})
        disable_csrf(self.request)
        IAnnotations(analysis)[ABOVE_RANGE_KEY] = json.dumps(rec)
        return json.dumps({"ok": True})
