# -*- coding: utf-8 -*-
"""@@pfas-warm: POST, the worker asks after the site starts. The first page
listing every open worksheet (the Bench, Guided Extraction, the Run Builder)
works out each worksheet's method once, about half a minute after a restart;
asked here, the worker waits instead of a person. Done once per start;
asked again it answers at once. JSON {"ok", "warmed", "worksheets"}."""
from __future__ import absolute_import, unicode_literals

import json
import logging
import time

logger = logging.getLogger("senaite.pfas.warm")

_WARMED = []                          # the time this process warmed, once


class PFASWarmView(object):

    def __init__(self, context, request):
        self.context, self.request = context, request

    def __call__(self):
        from bika.lims import api
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if self.request.method != "POST":
            resp.setStatus(405)
            return json.dumps({"ok": False, "error": u"POST only"})
        if _WARMED:
            return json.dumps({"ok": True, "warmed": False, "worksheets": None})
        t0 = time.time()
        try:
            from senaite.pfas.browser.extraction_guide import extraction_queue
            rows = extraction_queue(api.get_portal(), self.request)
        except Exception as exc:                            # noqa: BLE001
            logger.error("warm: %s", exc)
            return json.dumps({"ok": False, "error": u"%s" % exc})
        _WARMED.append(time.time())
        logger.info("warm: %d open worksheets in %.1f s", len(rows), time.time() - t0)
        return json.dumps({"ok": True, "warmed": True, "worksheets": len(rows)})
