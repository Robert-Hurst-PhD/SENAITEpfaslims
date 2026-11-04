# -*- coding: utf-8 -*-
"""@@pfas-system: notifications, the raw-data share and the Site
Administrator's shortcuts to Plone's own control panels. The raw-data share
is where the pipeline reads instrument files from, so only a Site
Administrator changes it. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from plone.protect import CheckAuthenticator
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, TIER_SITE_ADMIN, GateMixin, deny_gated_action, refuse
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.system_settings")

SYSTEM_GATES = {"save_notices": TIER_CONFIG, "save_raw": TIER_SITE_ADMIN}

# Plone's own control panels, for the Site Administrator
CONTROL_PANELS = (
    ("mail-controlpanel", "Mail"),
    ("security-controlpanel", "Security"),
    ("site-controlpanel", "Site"),
    ("usergroup-userprefs", "Users and groups"),
)


class PFASSystemView(ViewHelpers, GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/system_settings.pt")

    def __call__(self):
        req = self.request
        flatten_form(req)
        action = req.form.get("action", "")
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, action, SYSTEM_GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            msg = "error"
            if action == "save_notices":
                msg = "saved" if self._save_notices(req.form) else "error"
            elif action == "save_raw":
                msg = "saved" if self._save_raw(req.form) else "raw_error"
            req.response.redirect("%s/@@pfas-system?%s=1" % (self.portal_url(), msg))
            return ""
        return self.template()

    def control_panels(self):
        return [{"href": "%s/@@%s" % (self.portal_url(), n), "label": l} for n, l in CONTROL_PANELS]

    def notice_kinds(self):
        """[{"kind", "title", "email", "every_hours"}] for the Notifications section."""
        from senaite.pfas import notices
        current = notices.load_settings(api.get_portal())
        return [dict(current[k], kind=k, title=t) for k, t in sorted(notices.KINDS.items())]

    def _save_notices(self, form):
        from senaite.pfas import notices
        portal = api.get_portal()
        try:
            from senaite.pfas import config_history
            config_history.track(portal, "notice_settings", "default",
                                 lambda: notices.load_settings(portal), label=u"Notifications")
        except Exception:                                   # noqa: BLE001
            logger.warning("notification change not tracked", exc_info=True)
        notices.save_settings(portal, notices.settings_from_form(form))
        return True

    # ── Raw-data share ──────────────────────────────────────────

    def raw_share(self):
        from senaite.pfas import raw_share
        return raw_share.load(api.get_portal())

    def _save_raw(self, form):
        """False when a value is refused: nothing of the share is saved."""
        from senaite.pfas import raw_share
        portal = api.get_portal()
        values, errors = raw_share.from_form(form)
        if errors:
            return False
        try:
            from senaite.pfas import config_history
            config_history.track(portal, "raw_share", "default",
                                 lambda: raw_share.load(portal), label=u"Raw-data share")
        except Exception:                                   # noqa: BLE001
            logger.warning("raw-data share change not tracked", exc_info=True)
        raw_share.save(portal, values)
        return True

    def raw_failed(self):
        return bool(self.request.form.get("raw_error"))

    def saved(self):
        return bool(self.request.form.get("saved"))

    def failed(self):
        return bool(self.request.form.get("error"))
