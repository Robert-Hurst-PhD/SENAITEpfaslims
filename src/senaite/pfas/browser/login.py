# -*- coding: utf-8 -*-
"""The sign-in page: a lock screen with account tiles.

Overrides core's `login` view (senaite.core.browser.login, itself Plone's
LoginForm) on the PFAS layer: the form, its CSRF token, `came_from`, the
failure message and the redirect after sign-in are Plone's, unchanged; only
the page around them is ours.

At a registered lab terminal (badges.py: its secure cookie; not an IP
address -- Docker Desktop shows every visitor as one address) the page shows a tile for each account that signed in there
within badge_store.TILE_DAYS, newest first. A tile only fills in the user
name: the password is still asked for. Administrators never get a tile, and
anywhere else the page shows the plain form. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import logging
import time

from bika.lims import api
from Products.CMFPlone.utils import safe_unicode
from Products.statusmessages.interfaces import IStatusMessage
from senaite.core.browser.login.login import LoginForm as CoreLoginForm

from senaite.pfas import avatars
from senaite.pfas import badge_store as bs
from senaite.pfas.browser import badges

logger = logging.getLogger("senaite.pfas.login")


def _iso(seconds_ago=0):
    t = datetime.datetime.utcnow() - datetime.timedelta(seconds=seconds_ago)
    return t.replace(microsecond=0).isoformat()


def landing_wanted(came_from, portal_url):
    """False when `came_from` names no page of its own -- empty, the portal
    root, core's dashboard or a sign-in / sign-out page -- so the role's
    landing should be used instead."""
    url = (came_from or u"").split("?")[0].split("#")[0].rstrip("/")
    if not url or url == portal_url.rstrip("/"):
        return False
    last = url.rsplit("/", 1)[-1]
    return last not in ("senaite-dashboard", "login", "login_form", "logged_out",
                        "logout", "require_login", "front-page", "senaite-frontpage")


def tile_accounts(terminal):
    """[{"userid", "name", "avatar"}] for the terminal's sign-in page, or []
    without a registered terminal. Deleted and administrator accounts are
    left out."""
    if not terminal:
        return []
    con = bs.connect()
    try:
        userids = bs.terminal_accounts(con, terminal["id"], _iso(bs.TILE_DAYS * 86400))
    finally:
        con.close()
    portal = api.get_portal()
    purl = portal.absolute_url()
    out = []
    for userid in userids:
        ok, _why = badges.may_have_badge(userid)        # no account / an administrator
        if not ok:
            continue
        user = api.get_user(userid)
        name = safe_unicode(user.getProperty("fullname") or u"") if user is not None else u""
        out.append({"userid": userid, "login": safe_unicode(user.getUserName()) if user else userid,
                    "name": name or userid, "avatar": avatars.url(purl, avatars.get(portal, userid))})
        if len(out) >= bs.TILE_MAX:
            break
    return out


class PFASLoginForm(CoreLoginForm):

    def update(self):
        super(PFASLoginForm, self).update()
        # names of the terminal's accounts are on this page: never cached by
        # a proxy (Cloudflare, nginx) or the browser
        resp = self.request.response
        resp.setHeader(str("Cache-Control"), str("private, no-store"))
        resp.setHeader(str("Vary"), str("Cookie"))

    def _post_login(self):
        """A successful PASSWORD sign-in (Plone calls this once, and never on
        a failure; a badge sign-in does not come here): at a registered
        terminal, logged like a badge sign-in, which also gives the account
        its tile there, and the terminal's idle clock starts."""
        result = super(PFASLoginForm, self)._post_login()
        try:
            term = self.terminal()
            if term:
                user = api.get_current_user()
                userid = safe_unicode(user.getId() if user is not None else u"")
                if userid:
                    con = bs.connect()
                    try:
                        bs.log_signin(con, userid, term["id"], True, u"password", _iso())
                        bs.touch(con, term["id"], userid, time.time())
                    finally:
                        con.close()
        except Exception:                                   # noqa: BLE001
            logger.warning("terminal password sign-in not logged", exc_info=True)
        return result

    def redirect_after_login(self, came_from=None, is_initial_login=False):
        """Each role lands on its workspace unless the
        sign-in was asked for by a page: Plone sent everyone to the portal
        root or core's empty dashboard."""
        if not landing_wanted(came_from, api.get_portal().absolute_url()):
            came_from = api.get_portal().absolute_url() + "/@@pfas-home"
        return super(PFASLoginForm, self).redirect_after_login(came_from, is_initial_login)

    def terminal(self):
        if not hasattr(self, "_terminal"):
            self._terminal = badges.terminal_from_request(self.request)
        return self._terminal

    def tiles(self):
        if not hasattr(self, "_tiles"):
            self._tiles = tile_accounts(self.terminal())
        return self._tiles

    def messages(self):
        return IStatusMessage(self.request).show()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def field_widgets(self):
        return [w for w in self.widgets.values() if w.mode != "hidden"]

    def hidden_widgets(self):
        return [w for w in self.widgets.values() if w.mode == "hidden"]
