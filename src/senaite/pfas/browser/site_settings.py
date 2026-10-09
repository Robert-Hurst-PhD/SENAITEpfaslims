# -*- coding: utf-8 -*-
"""@@pfas-site-settings: settings that belong to the whole site.

"The language settings should be in the site settings not on a
navigation bar." Decided: one site language for everyone, set here by a
manager. It is Plone's own setting (plone.default_language); saving it also
turns per-browser language cookies off, so a language someone picked with the
old bar selector no longer overrides the site. The change is recorded in the
configuration change history, and the Lab Settings console lists it.
Python 2.7.
"""
from __future__ import absolute_import

import logging

from bika.lims import api
from plone.registry.interfaces import IRegistry
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.component import getUtility

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action

logger = logging.getLogger("senaite.pfas.site_settings")

SITE_GATES = {"save_language": TIER_CONFIG, "save_director": TIER_CONFIG}
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


class PFASSiteSettingsView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/site_settings.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        action = req.form.get("action", "")
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, action, SITE_GATES)
            if denied is not None:
                return denied
            msg = "error"
            if action == "save_language":
                msg = "saved" if self._save_language(req.form.get("language", "")) else "error"
            elif action == "save_director":
                msg = "saved" if self._save_director(req.form.get("director", "")) else "error"
            req.response.redirect("%s/@@pfas-site-settings?%s=1" % (self.portal_url(), msg))
            return ""
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

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

    def _save_language(self, code):
        if code not in [c for c, _n in self.languages()]:
            return False
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

    # ── Laboratory Director ─────────────────────────────────────

    def director(self):
        from senaite.pfas.browser.staff import director_userid
        return director_userid()

    def director_choices(self):
        """Users linked to a Lab Contact (the Director signs through it)."""
        from senaite.pfas.browser import staff
        from senaite.pfas.browser.lab_staff import users
        out = []
        for userid, name in users():
            info = staff.staff_info(userid)
            if info["has_contact"]:
                out.append((userid, info["fullname"] or name, "director" in info["sign_as"]))
        return out

    def _save_director(self, userid):
        from zope.annotation.interfaces import IAnnotations
        from senaite.pfas.browser import staff
        userid = (userid or u"").strip()
        if userid and userid not in [u for u, _n, _d in self.director_choices()]:
            return False
        portal = api.get_portal()
        try:
            from senaite.pfas import config_history
            config_history.track(portal, "lab_director", "default",
                                 lambda: {"director": IAnnotations(portal).get(staff.DIRECTOR_KEY) or u""},
                                 label=u"Laboratory Director")
        except Exception:                                   # noqa: BLE001
            logger.warning("director change not tracked", exc_info=True)
        IAnnotations(portal)[staff.DIRECTOR_KEY] = userid
        return True

    def saved(self):
        return bool(self.request.form.get("saved"))

    def failed(self):
        return bool(self.request.form.get("error"))
