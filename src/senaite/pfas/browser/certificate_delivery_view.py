# -*- coding: utf-8 -*-
"""A Manager sends an issued certificate's waiting e-mail again
(@@pfas-delivery-send, from Certificates).

    POST report=<report uid>    that report's waiting delivery
    POST all=1                  every current issue whose e-mail waits
    POST auto=1                 the worker's timed retry: every current
                                issue whose e-mail waits after an attempt
                                (certificate_delivery.retry_due), answered
                                in JSON {"ok", "mail", "sent": [id],
                                "waiting": [id]}; with no mail server named
                                nothing is tried ("mail": false)

Each goes through the e-mail form's own send (edd_email.PFASEmailView):
the same attachments (the report's PDF, which is its tier's package, and
the client's EDDs), the same note and the same record, to the recipients
not reached yet. Back to Certificates with what
went and what still waits. Only a caller who may manage the site and holds
the LabManager or Manager role at the portal is answered, as the package
retry asks. The worker's post carries no form token: its JSON mode does
only what the timer does. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

from AccessControl import getSecurityManager
from plone.protect import CheckAuthenticator
from Products.Five.browser import BrowserView
from zExceptions import Forbidden
from ZODB.POSException import ConflictError

from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal, refuse

logger = logging.getLogger("senaite.pfas.browser.certificate_delivery_view")

NOTHING_WAITS = u"No e-mail waits for this certificate"
SENT_SOME = u"E-mailed: %s"
STILL_WAITS = u"Still waiting: %s"


def _send(report, request):
    """Send the report's waiting delivery through the e-mail form's send:
    (sent, reason) with the reason it still waits, or NOTHING_WAITS."""
    from senaite.pfas import certificate_delivery as cd
    from senaite.pfas.browser.edd_email import PFASEmailView
    last = cd.newest(cd.load(report))
    if not cd.is_waiting(last):
        return False, NOTHING_WAITS
    sample = report.getAnalysisRequest()

    class Resend(PFASEmailView):
        """The e-mail form for this one report, with no files chosen by
        hand: what goes is what the form's Send attaches."""
        resend = True

        @property
        def reports(self):
            return [report]

        @property
        def attachments(self):
            return []

    view = Resend(sample.getClient(), request)
    recipients = cd.waiting_for(last) or list(last.get("recipients") or [])
    # the attachments first: they decide the note the body ends with
    attachments = view.email_attachments
    ok = view.send_email(recipients, view.email_subject, view.email_body, attachments=attachments)
    return ok, (None if ok else (getattr(view, "_wait_reason", None) or cd.NOT_REACHED))


class PFASDeliverySendView(BrowserView):
    """A Manager sends waiting certificate e-mails from Certificates."""

    def __call__(self):
        from bika.lims import api
        from senaite.core.permissions import ManageBika
        from senaite.pfas.browser.perms import may_run_worker_tasks
        # the worker's automatic retry (auto=1, POST) runs under its own
        # account's worker permission; every other send is a Lab Manager's
        if (self.request.method == "POST" and self.request.form.get("auto") == "1"
                and may_run_worker_tasks(self.context)):
            return self._auto()
        if not getSecurityManager().checkPermission(ManageBika, api.get_portal()):
            return refuse(self.request)
        # a Lab Manager's: core grants Manage Bika to the LabClerk too
        if not has_role_at_portal(self.context, MANAGER_ROLES):
            return refuse(self.request)
        if self.request.method != "POST":
            self.request.response.setStatus(405)
            return u"POST only"
        if self.request.form.get("auto") == "1":
            return self._auto()
        try:
            CheckAuthenticator(self.request)
        except Forbidden:
            return refuse(self.request)
        form = self.request.form
        if form.get("all") == "1":
            reports = self._waiting_reports()
        else:
            report = api.get_object_by_uid(form.get("report") or u"", default=None)
            if report is None or api.get_portal_type(report) != "ARReport":
                return self._back([], [(u"", u"No such certificate")])
            reports = [report]
        sent, waits = [], []
        for report in reports:
            name = api.get_id(report.getAnalysisRequest())
            try:
                ok, why = _send(report, self.request)
            except ConflictError:
                raise
            except Exception as exc:                        # noqa: BLE001
                logger.exception("certificate e-mail of %s not sent", name)
                ok, why = False, u"%s" % (exc,)
            if ok:
                sent.append(name)
            else:
                waits.append((name, why))
        return self._back(sent, waits)

    def _auto(self):
        """The worker's timed retry, answered in JSON: nothing is tried
        while no mail server is named; else every e-mail waiting after an
        attempt is sent again through the form's own send."""
        from bika.lims import api
        from senaite.pfas import certificate_delivery as cd
        from senaite.pfas.browser.perms import disable_csrf
        self.request.response.setHeader("Content-Type", "application/json")
        # the worker's post carries no form token; the gates above have run
        disable_csrf(self.request)
        if not cd.smtp_ready(api.get_tool("MailHost")):
            return json.dumps({"ok": True, "mail": False, "sent": [], "waiting": []})
        sent, waiting = [], []
        for report in self._waiting_reports(due=cd.retry_due):
            name = api.get_id(report.getAnalysisRequest())
            try:
                ok, _why = _send(report, self.request)
            except ConflictError:
                raise
            except Exception:                               # noqa: BLE001
                logger.exception("certificate e-mail of %s not sent again", name)
                ok = False
            (sent if ok else waiting).append(name)
        if sent or waiting:
            logger.info("timed retry: %d e-mailed, %d still waiting", len(sent), len(waiting))
        return json.dumps({"ok": True, "mail": True, "sent": sent, "waiting": waiting})

    def _waiting_reports(self, due=None):
        """The reports of the current issues whose e-mail waits, each once;
        `due(delivery)`, when given, also decides."""
        from bika.lims import api
        from senaite.pfas import certificate_delivery as cd
        from senaite.pfas.browser.controlled_publications import PFASControlledPublicationsView
        rows = PFASControlledPublicationsView(self.context, self.request).publications()
        out, seen = [], set()
        for r in rows:
            uid = r.get("report_uid")
            if not r.get("delivery_waiting") or not uid or uid in seen:
                continue
            seen.add(uid)
            report = api.get_object_by_uid(uid, default=None)
            last = cd.newest(cd.load(report)) if report is not None else None
            if cd.is_waiting(last) and (due is None or due(last)):
                out.append(report)
        return out

    def _back(self, sent, waits):
        """Back to Certificates, which shows what went and what waits."""
        from bika.lims import api
        from Products.statusmessages.interfaces import IStatusMessage
        msgs = IStatusMessage(self.request)
        if sent:
            msgs.add(SENT_SOME % u", ".join(sent), type="info")
        if waits:
            msgs.add(STILL_WAITS % u"; ".join((u"%s: %s" % (n, w)) if n else w for n, w in waits), type="error")
        if not sent and not waits:
            msgs.add(NOTHING_WAITS, type="info")
        self.request.response.redirect(
            "{0}/@@pfas-controlled-publications".format(api.get_url(api.get_portal())))
        return u""
