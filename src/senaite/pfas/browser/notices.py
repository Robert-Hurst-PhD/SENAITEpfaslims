# -*- coding: utf-8 -*-
"""@@pfas-notice-reminders: POST, the worker (or a Manager) asks for the due
notice e-mails to be sent (notices.send_due); the deviation for criteria
not set is raised for every open worksheet whose run holds a result not
judged (unconfigured_deviation.raise_for_open_worksheets); and the QAO
e-mail of such a deviation that never went is tried again
(qc_deviation.retry_notifications). JSON {"ok", "sent", "deviations",
"qao_retried"}."""
from __future__ import absolute_import, unicode_literals

import json
import logging

logger = logging.getLogger("senaite.pfas.notices")


class PFASNoticeRemindersView(object):

    def __init__(self, context, request):
        self.context, self.request = context, request

    def __call__(self):
        from bika.lims import api
        from senaite.pfas import notices
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if self.request.method != "POST":
            resp.setStatus(405)
            return json.dumps({"ok": False, "error": u"POST only"})
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)
        portal = api.get_portal()
        sent = notices.send_due(portal)
        try:
            from senaite.pfas.browser.unconfigured_deviation import raise_for_open_worksheets
            deviations = raise_for_open_worksheets(portal, self.request)
        except Exception as exc:                            # noqa: BLE001
            logger.error("unconfigured-criteria deviations: %s", exc)
            deviations = []
        try:
            from senaite.pfas.qc_deviation import retry_notifications
            retried = retry_notifications(portal)
        except Exception as exc:                            # noqa: BLE001
            logger.error("QAO notification retry: %s", exc)
            retried = 0
        return json.dumps({"ok": True, "sent": sent, "deviations": deviations,
                           "qao_retried": retried})
