# -*- coding: utf-8 -*-
"""@@pfas-time-language: the site language and the laboratory time zone.

One site language for everyone, set here by a manager. It is Plone's own
setting (plone.default_language); saving it also turns per-browser language
cookies off, so a language someone picked earlier no longer overrides the
site. Each change is recorded in the configuration change history, and the
Lab Settings console lists the language. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from plone.protect import CheckAuthenticator
from plone.registry.interfaces import IRegistry
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden
from zope.component import getUtility

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action, refuse
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.time_language")

TIME_GATES = {"save": TIER_CONFIG}
DEFAULT_KEY = "plone.default_language"
AVAILABLE_KEY = "plone.available_languages"
COOKIE_KEY = "plone.use_cookie_negotiation"


def site_language():
    reg = getUtility(IRegistry)
    try:
        return reg[DEFAULT_KEY]
    except Exception:                                       # noqa: BLE001
        return u"en"


def _state():
    reg = getUtility(IRegistry)
    out = {}
    for k in (DEFAULT_KEY, COOKIE_KEY):
        try:
            out[k] = reg[k]
        except Exception:                                   # noqa: BLE001
            out[k] = None
    return out


class PFASTimeLanguageView(ViewHelpers, GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/time_language.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        action = req.form.get("action", "")
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, action, TIME_GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            msg = "error"
            if action == "save":
                f = req.form
                code, zone = f.get("language", ""), f.get("timezone", "")
                # a refusal writes nothing: both values are checked first
                if self._language_ok(code) and self._zone_ok(zone):
                    self._save_language(code)
                    self._save_timezone(zone)
                    msg = "saved"
            req.response.redirect("%s/@@pfas-time-language?%s=1" % (self.portal_url(), msg))
            return ""
        return self.template()

    def languages(self):
        """[(code, name)] the site offers, in the registry's order."""
        reg = getUtility(IRegistry)
        try:
            codes = list(reg[AVAILABLE_KEY])
        except Exception:                                   # noqa: BLE001
            codes = [u"en"]
        names = {}
        try:
            lt = getToolByName(self.context, "portal_languages")
            for code, info in lt.getAvailableLanguageInformation().items():
                names[code] = info.get("native") or info.get("name") or code
        except Exception:                                   # noqa: BLE001
            pass
        return [(c, names.get(c, c)) for c in codes]

    def current(self):
        return site_language()

    def _language_ok(self, code):
        return code in [c for c, _n in self.languages()]

    def _save_language(self, code):
        try:
            from senaite.pfas import config_history
            config_history.track(None, "site_language", "default", _state,
                                 label=u"Site language")
        except Exception:                                   # noqa: BLE001
            logger.warning("site language change not tracked", exc_info=True)
        reg = getUtility(IRegistry)
        reg[DEFAULT_KEY] = code
        # one language for everyone: a browser cookie may no longer override it
        reg[COOKIE_KEY] = False
        return True

    # ── Laboratory time zone ────────────────────────────────────

    def timezone(self):
        from senaite.pfas import lab_time
        name = lab_time.zone()
        return u"" if name == u"UTC" else name

    def lab_now(self):
        from senaite.pfas import lab_time
        return lab_time.now().strftime("%Y-%m-%d %H:%M")

    def utc_now(self):
        from senaite.pfas import lab_time
        return lab_time._utcnow().strftime("%Y-%m-%d %H:%M")

    def timezones(self):
        from senaite.pfas import lab_time
        return lab_time.zones()

    def _zone_ok(self, name):
        from senaite.pfas import lab_time
        name = (name or u"").strip()
        return not name or name in lab_time.zones()

    def _save_timezone(self, name):
        from senaite.pfas import lab_time
        name = (name or u"").strip()
        from senaite.pfas import config_history
        config_history.track(api.get_portal(), "lab_timezone", "default",
                             lambda: {"timezone": lab_time.zone()},
                             label=u"Laboratory time zone")
        return lab_time.set_zone(name)

    def saved(self):
        return bool(self.request.form.get("saved"))

    def failed(self):
        return bool(self.request.form.get("error"))
