# -*- coding: utf-8 -*-
"""@@pfas-bell: the top bar's notifications bell, as JSON (bell.py). The
bell fetches it after the page has loaded, so no page waits for it; each
person's answer is kept for a minute (the manager's attention items read
every verified sample).

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
import time

from AccessControl import getSecurityManager
from Products.Five.browser import BrowserView

from senaite.pfas import bell
from senaite.pfas.browser.perms import is_staff, require_manager

logger = logging.getLogger("senaite.pfas.browser.bell_view")

TTL_SECONDS = 60
_CACHE = {}


RESET_TITLE = u"Your password was reset"
RESET_TEXT = u"Reset by %s. Change it on My profile: until then your signatures are listed for review."


def _reset_notice(portal):
    """The signed-in person's open password reset (esig.credentials), as a
    notice of their own: a reset by another account until they change it."""
    try:
        from senaite.pfas.esig import credentials
        userid = getSecurityManager().getUser().getId()
        r = credentials.open_reset(userid) if userid else None
    except Exception as exc:                                # noqa: BLE001
        logger.warning("bell: password reset: %s", exc)
        return []
    if r is None:
        return []
    return [{"title": RESET_TITLE, "ws_id": u"", "text": RESET_TEXT % r["by"],
             "raised_at": r["at"], "url": u"%s/@@pfas-my-profile" % portal.absolute_url()}]


class PFASBellView(BrowserView):

    def __call__(self):
        self.request.response.setHeader("Content-Type", "application/json")
        self.request.response.setHeader("Cache-Control", "no-store")
        userid = getSecurityManager().getUser().getId()
        if not userid or not is_staff(self.context):
            return json.dumps(bell.entries([], [], []))
        hit = _CACHE.get(userid)
        if hit and time.time() - hit[0] < TTL_SECONDS:
            return hit[1]
        out = json.dumps(self._data())
        _CACHE[userid] = (time.time(), out)
        return out

    def _data(self):
        from senaite.pfas.browser.workspace_home import PFASQCManagementView, _my_notices, _portal
        portal = _portal(self.context)
        manager = require_manager(self.context, self.request)
        items = []
        if manager:
            try:
                items = PFASQCManagementView(self.context, self.request).attention()
            except Exception as exc:                        # noqa: BLE001
                logger.warning("bell: attention: %s", exc)
        equipment = []
        try:
            from senaite.pfas.browser.equipment import PFASEquipmentView
            base = portal.absolute_url()
            for r in PFASEquipmentView(self.context, self.request).rows():
                equipment.append({"name": r.get("name") or u"", "status": (r.get("due") or {}).get("status"),
                                  "url": r.get("records_url") or u"%s/@@pfas-equipment" % base})
        except Exception as exc:                            # noqa: BLE001
            logger.warning("bell: equipment: %s", exc)
        raw = []
        try:
            # a raw run not pulled, or not imported (the worker's import log)
            import sqlite3
            from senaite.pfas.browser.data_review import DEFAULT_DB_PATH
            conn = sqlite3.connect(DEFAULT_DB_PATH)
            try:
                got = conn.execute("SELECT file, batch_id, status, error FROM run_imports "
                                   "WHERE file LIKE '%.rawrun' AND status='failed'").fetchall()
            finally:
                conn.close()
            base = portal.absolute_url()
            raw = [{"file": f, "batch_id": b, "status": st, "error": e,
                    "url": u"%s/worksheets/%s/@@pfas-data-review?tab=instrument_report" % (base, b)}
                   for f, b, st, e in got]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("bell: raw runs: %s", exc)
        data = bell.entries(_my_notices(self.context) + _reset_notice(portal), items, equipment, raw)
        data["settings_url"] = u"%s/@@pfas-system#sec-notifications" % portal.absolute_url() if manager else u""
        return data
