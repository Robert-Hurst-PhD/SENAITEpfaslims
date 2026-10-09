# -*- coding: utf-8 -*-
"""Badge sign-in at registered lab terminals (part C).

    @@pfas-terminals       Managers: register THIS computer as a lab terminal
                           (a long random token in an HttpOnly, SameSite=Strict
                           cookie; only its hash is stored), revoke terminals,
                           the sign-in log and the badge log
    @@pfas-badge-signin    a scan box. At a registered terminal a badge alone
                           signs its holder in -- signing out whoever was
                           signed in first (a scan switches user). ?idle=1 is
                           the 10-minute idle sign-out of a terminal page.
                           Anywhere else: "sign in with your password".
    (the sign-in page offers "Scan badge" at a registered terminal: login.py,
)

Refused: an unregistered or revoked terminal, a terminal locked after 5 failed
scans in 5 minutes, an unknown or revoked badge, a deleted account, and any
Manager / site-admin account (administrators always
use their password). Badges are issued and revoked on Lab Staff. Codes and
tokens are never stored or put in a URL. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import logging
import time

from AccessControl import getSecurityManager
from bika.lims import api
from Products.CMFPlone.utils import safe_unicode
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import badge_store as bs
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action, refuse

logger = logging.getLogger("senaite.pfas.badges")

COOKIE = str("pfas_terminal")
COOKIE_AGE = 5 * 365 * 24 * 3600
IDLE_SECONDS = 600
NO_BADGE_ROLES = frozenset(("Manager", "Site Administrator", "Owner"))
TERMINAL_GATES = {"register_terminal": TIER_CONFIG, "revoke_terminal": TIER_CONFIG,
                  "forget_tile": TIER_CONFIG}


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def _who():
    return safe_unicode(getSecurityManager().getUser().getId() or u"")


def _con():
    return bs.connect()


def badge_status(userid):
    con = _con()
    try:
        return bs.status(con, userid)
    finally:
        con.close()


def terminal_from_request(request):
    """The registered terminal this browser is, or None."""
    token = request.cookies.get(COOKIE) if request is not None else None
    if not token:
        return None
    con = _con()
    try:
        return bs.terminal_for_token(con, safe_unicode(token))
    finally:
        con.close()


def _portal_roles(userid):
    user = api.get_user(userid)
    if user is None:
        return None
    portal = api.get_portal()
    try:
        return set(user.getRolesInContext(portal))
    except Exception:                                       # noqa: BLE001
        return set(user.getRoles())


def may_have_badge(userid):
    """(True, "") or (False, why): administrators never sign in by badge."""
    roles = _portal_roles(userid)
    if roles is None:
        return False, u"no such account"
    if roles & NO_BADGE_ROLES:
        return False, u"administrator accounts sign in with their password"
    return True, u""


def _set_cookie(response, name, value, request, max_age):
    secure = (request.get("HTTP_X_FORWARDED_PROTO") == "https"
              or str(request.get("SERVER_URL", "")).startswith("https"))
    # waitress asserts native str header values under Python 2
    response.setCookie(str(name), str(value), path=str("/"), max_age=max_age,
                       http_only=True, same_site=str("Strict"), secure=secure)


# ── server-side idle sign-out (IPubAfterTraversal) ─────────────────────────

_IDLE_EXEMPT = ("@@pfas-badge-signin", "++resource++", "/login", "/logout", "logged_out",
                "require_login")


def enforce_terminal_idle(event):
    """Every signed-in request at a registered terminal: more than
    IDLE_SECONDS since this person's last activity there signs them out and
    goes to the badge page; otherwise the activity time is recorded (at most
    every TOUCH_EVERY seconds). Requests elsewhere cost nothing: no terminal
    cookie, no lookup."""
    request = event.request
    if not request.cookies.get(COOKIE):
        return
    url = request.get("ACTUAL_URL", "") or ""
    if any(x in url for x in _IDLE_EXEMPT):
        return
    user = getSecurityManager().getUser()
    if user is None or user.getUserName() == "Anonymous User":
        return
    con = _con()
    try:
        term = bs.terminal_for_token(con, safe_unicode(request.cookies.get(COOKIE)))
        if term is None:
            return
        userid = safe_unicode(user.getId())
        now = time.time()
        verdict = bs.idle_verdict(bs.last_seen(con, term["id"], userid), now, IDLE_SECONDS)
        if verdict == "touch":
            bs.touch(con, term["id"], userid, now)
            return
        if verdict == "fresh":
            return
        with con:
            con.execute("DELETE FROM activity WHERE terminal_id=? AND userid=?", (term["id"], userid))
    finally:
        con.close()
    target = "%s/@@pfas-badge-signin?idle=1" % api.get_portal().absolute_url()
    api.get_portal().acl_users.resetCredentials(request, request.response)
    from zExceptions import Redirect
    raise Redirect(target)


# ── issuing (called from Lab Staff, gated there) ───────────────────────────

def issue_badge(userid):
    """The new code (shown once), or raises ValueError with why not."""
    ok, why = may_have_badge(userid)
    if not ok:
        raise ValueError(why)
    con = _con()
    try:
        _track(userid)
        return bs.issue(con, userid, _who(), _now())
    finally:
        con.close()


def revoke_badge(userid):
    con = _con()
    try:
        _track(userid)
        return bs.revoke(con, userid, _who(), _now())
    finally:
        con.close()


def _track(userid):
    try:
        from senaite.pfas import config_history
        config_history.track(None, "badge", userid, lambda: badge_status(userid),
                             label=u"Badge of %s" % userid)
    except Exception:                                       # noqa: BLE001
        logger.warning("badge change not tracked", exc_info=True)


# ── terminals page ─────────────────────────────────────────────────────────

class PFASTerminalsView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/badge_terminals.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            action = req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, TERMINAL_GATES)
            if denied is not None:
                return denied
            from plone.protect import CheckAuthenticator
            from zExceptions import Forbidden
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            con = _con()
            try:
                if action == "register_terminal":
                    name = safe_unicode(req.form.get("name") or u"").strip() or u"Lab terminal"
                    token = bs.register_terminal(con, name, _who(), _now())
                    _set_cookie(req.response, COOKIE, token, req, COOKIE_AGE)
                    msg = u"ok=This computer is now the lab terminal %s." % name
                elif action == "forget_tile":
                    bs.hide_tile(con, int(req.form.get("terminal_id") or 0),
                                 safe_unicode(req.form.get("userid") or u""), _who(), _now())
                    msg = u"ok=Tile removed; it returns when that person signs in there again."
                elif action == "revoke_terminal":
                    bs.revoke_terminal(con, int(req.form.get("terminal_id") or 0), _who(), _now())
                    msg = u"ok=Terminal revoked."
                else:
                    msg = u"error=Unknown action."
            finally:
                con.close()
            from six.moves.urllib.parse import quote_plus
            kind, text = msg.split(u"=", 1)
            req.response.redirect("%s/@@pfas-terminals?%s=%s" % (
                self.portal_url(), kind, quote_plus(text.encode("utf-8"))))
            return ""
        if not self.can_configure():
            return refuse(req)
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def message(self):
        f = self.request.form
        return safe_unicode(f.get("ok") or u""), safe_unicode(f.get("error") or u"")

    def this_terminal(self):
        return terminal_from_request(self.request)

    def tile_rows(self):
        """The accounts each active terminal's sign-in page shows."""
        from senaite.pfas.browser.login import tile_accounts
        out = []
        con = _con()
        try:
            terms = [t for t in bs.terminals(con) if not t["revoked_at"]]
        finally:
            con.close()
        for t in terms:
            for a in tile_accounts(t):
                out.append({"terminal": t["name"], "terminal_id": t["id"],
                            "userid": a["userid"], "name": a["name"]})
        return out

    def data(self):
        con = _con()
        try:
            return {"terminals": bs.terminals(con), "signins": bs.signins(con, 50),
                    "events": bs.events(con, limit=50)}
        finally:
            con.close()


# ── sign-in ────────────────────────────────────────────────────────────────

class PFASBadgeSigninView(BrowserView):

    template = ViewPageTemplateFile("templates/badge_signin.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        self.terminal = terminal_from_request(req)
        self.error = u""
        self.signed_out = False
        if req.get("idle") and self.terminal:
            # the terminal page's idle timer (10 minutes): sign out. The
            # cookie is SameSite=Strict, so a link from another site cannot.
            self._signout()
            self.signed_out = True          # this request still carries the old user
            self.notice = u"Signed out after %d minutes without activity." % (IDLE_SECONDS // 60)
        else:
            self.notice = u""
        if req.method == "POST" and req.form.get("action") == "badge":
            return self._scan(safe_unicode(req.form.get("code") or u""))
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def current_user(self):
        if self.signed_out:
            return u""
        user = getSecurityManager().getUser()
        if user is None or user.getUserName() == "Anonymous User":
            return u""
        return safe_unicode(user.getProperty("fullname") or user.getId()) \
            if hasattr(user, "getProperty") else safe_unicode(user.getId())

    def _signout(self):
        try:
            api.get_portal().acl_users.resetCredentials(self.request, self.request.response)
        except Exception:                                   # noqa: BLE001
            logger.warning("sign-out failed", exc_info=True)

    def _scan(self, code):
        req = self.request
        if self.terminal is None:
            self.error = u"This computer is not a registered lab terminal: sign in with your password."
            req.response.setStatus(403)
            return self.template()
        tid = self.terminal["id"]
        now = time.time()
        con = _con()
        try:
            if bs.locked(con, tid, now):
                bs.log_signin(con, u"", tid, False, u"terminal locked", _now())
                self.error = u"Too many unrecognised scans: this terminal is locked for 5 minutes."
                req.response.setStatus(429)
                return self.template()
            userid = bs.user_for_code(con, code)
            why = u""
            if userid is None:
                why = u"badge not recognised"
            else:
                ok, why = may_have_badge(userid)
                why = u"" if ok else why
            if why:
                bs.failure(con, tid, now)
                bs.log_signin(con, userid or u"", tid, False, why, _now())
                self.error = (u"Badge not recognised." if userid is None else
                              u"This badge cannot sign in: %s." % why)
                req.response.setStatus(403)
                return self.template()
            bs.clear(con, tid)
            bs.log_signin(con, userid, tid, True, u"", _now())
            bs.touch(con, tid, userid, now)     # the idle clock starts at the scan
        finally:
            con.close()
        # a scan switches user: whoever was signed in is signed out first.
        # Signing out EXPIRES the session cookie on this response; setting the
        # new session on the same response would keep that expiry, so the
        # expired entry is dropped first (found live 2026-10-05).
        self._signout()
        session = api.get_portal().acl_users.session
        req.response.cookies.pop(session.cookie_name, None)
        session._setupSession(str(userid), req.response)
        req.response.redirect("%s/@@pfas-home" % self.portal_url())
        return ""

