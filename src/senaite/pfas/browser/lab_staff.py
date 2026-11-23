# -*- coding: utf-8 -*-
"""Lab staff and personal profiles (part B).

    PFASLabStaffView    the handlers behind @@pfas-people (People & Roles): the
                        Lab Contact a user is linked to (SENAITE's own link,
                        contact.setUser), job title, credentials, who signs as
                        preparer / reviewer, the signature picture, the badge
    @@pfas-my-profile   Everyone signed in: their own signature (their own Lab
                        Contact, resolved on the server, never from the form)
                        and what they may do ("My permissions", derived from
                        the same gate tables and roles the pages enforce)

Signatures are PNG / JPEG only, at most 512 KB (staff.check_signature). Every
change is recorded in the configuration change history -- for a signature its
fingerprint, never the picture. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import importlib
import logging
import os

from AccessControl import getSecurityManager
from bika.lims import api
from plone.protect import CheckAuthenticator
from Products.CMFPlone.utils import safe_unicode
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden
from zope.annotation.interfaces import IAnnotations

from senaite.pfas import staff as staff_pool
from senaite.pfas.browser import staff
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (ALLOWED_ROLES, SITE_ADMIN_ROLES, TIER_CONFIG,
                                        TIER_SITE_ADMIN, refuse)

logger = logging.getLogger("senaite.pfas.lab_staff")


def _text(form, key):
    return safe_unicode(form.get(key) or u"").strip()


def _upload(form, key):
    f = form.get(key)
    if f is None or not hasattr(f, "read"):
        return None
    try:
        f.seek(0)
    except Exception:                                       # noqa: BLE001
        pass
    return f.read()


def _staff_view(contact):
    """What the change history records about a person's staff settings."""
    if contact is None:
        return {}
    st = staff.staff_settings(contact)
    raw = staff.image_bytes(contact.getSignature())
    field = contact.getField("pfas_initials")
    return {"contact": api.get_uid(contact), "fullname": contact.getFullname(),
            "initials": (field.get(contact) or u"").strip().upper() if field is not None else u"",
            "jobtitle": getattr(contact, "getJobTitle", lambda: u"")() or u"",
            "credentials": st["credentials"], "sign_as": st["sign_as"],
            "signature": staff.fingerprint(raw)}


def _track(userid, label):
    try:
        from senaite.pfas import config_history
        config_history.track(None, "staff", userid,
                             lambda: _staff_view(staff.contact_for(userid)), label=label)
    except Exception:                                       # noqa: BLE001
        logger.warning("staff change not tracked", exc_info=True)


def set_signature(contact, raw):
    """Store (raw) or remove (None) a Lab Contact's signature picture."""
    field = contact.getField("Signature")
    if raw is None:
        field.set(contact, "DELETE_IMAGE")
    else:
        field.set(contact, raw)
    contact.reindexObject()


def users():
    """[(userid, fullname)] of every user account, by name. searchUsers also
    returns the stored properties of accounts that were deleted (found
    2026-10-05: five such records and no real account); only accounts that
    exist are staff."""
    out = []
    portal = api.get_portal()
    for u in portal.acl_users.searchUsers():
        uid = u.get("userid") or u.get("id")
        if not uid:
            continue
        user = api.get_user(uid)
        if user is None:
            continue
        name = user.getProperty("fullname") or uid
        out.append((uid, safe_unicode(name)))
    return sorted(set(out), key=lambda x: x[1].lower())


def portal_roles(userid):
    user = api.get_user(userid)
    if user is None:
        return []
    portal = api.get_portal()
    try:
        roles = user.getRolesInContext(portal)
    except Exception:                                       # noqa: BLE001
        roles = user.getRoles()
    return sorted(r for r in roles if r not in ("Authenticated", "Member"))


class PFASLabStaffView(ViewHelpers, BrowserView):
    """The staff handlers; PFASPeopleView is the page that dispatches to them."""

    issued_template = ViewPageTemplateFile("templates/badge_issued.pt")

    # ── actions ────────────────────────────────────────────────────────────

    def _link(self, userid):
        user = api.get_user(userid) if userid else None
        if user is None:
            return u"error:No such user."
        if staff.contact_for(userid) is not None:
            return u"ok:%s is already linked to a Lab Contact." % userid
        _track(userid, u"Lab Contact for %s" % userid)
        name = safe_unicode(user.getProperty("fullname") or userid).strip()
        first, _sep, last = name.partition(u" ")
        folder = api.get_portal().bika_setup.bika_labcontacts
        contact = api.create(folder, "LabContact", Firstname=first or userid, Surname=last or u"")
        try:
            contact.setUser(user)
        except ValueError as exc:
            api.get_parent(contact).manage_delObjects([api.get_id(contact)])
            return u"error:%s" % exc
        return u"ok:%s is linked to a new Lab Contact." % name

    def _save(self, userid, form, sign_as_values=None):
        contact = staff.contact_for(userid)
        if contact is None:
            return u"error:Link %s to a Lab Contact first." % userid
        # everything is checked before anything is written
        initials = None
        if "initials" in form:
            initials = _text(form, "initials").upper()
            holder = staff_pool.initials_holder(api.get_portal(), contact.UID(), initials) if initials else None
            if holder:
                return u"error:Initials {0} are already used by {1}.".format(initials, holder)
        # one value per switch that is on; none posted means no sign right
        sign_as = sign_as_values or form.get("sign_as") or []
        if not isinstance(sign_as, (list, tuple)):
            sign_as = [sign_as]
        sign_as = [safe_unicode(x) for x in sign_as]
        # a value that is not one of the sign rights refuses the save
        if [x for x in sign_as if x not in [k for k, _t in staff.SIGN_ROLES]]:
            titles = [t for _k, t in staff.SIGN_ROLES]
            return u"error:Choose from %s and %s." % (u", ".join(titles[:-1]), titles[-1])
        _track(userid, u"Staff settings of %s" % userid)
        if initials is not None:
            contact.getField("pfas_initials").set(contact, initials)
        if _text(form, "fullname"):
            first, _sep, last = _text(form, "fullname").partition(u" ")
            contact.setFirstname(first)
            contact.setSurname(last.strip())
        contact.setJobTitle(_text(form, "jobtitle"))
        IAnnotations(contact)[staff.STAFF_KEY] = {
            "credentials": _text(form, "credentials"),
            "sign_as": staff.clean_sign_as(sign_as)}
        contact.reindexObject()
        return u"ok:Saved %s." % contact.getFullname()

    def _signature(self, userid, remove):
        contact = staff.contact_for(userid)
        if contact is None:
            return u"error:Link %s to a Lab Contact first." % userid
        if remove:
            _track(userid, u"Signature of %s removed" % userid)
            set_signature(contact, None)
            return u"ok:Signature of %s removed." % contact.getFullname()
        raw, why = staff.check_signature(_upload(self.request.form, "signature"))
        if why:
            return u"error:%s" % why
        _track(userid, u"Signature of %s" % userid)
        set_signature(contact, raw)
        return u"ok:Signature of %s saved." % contact.getFullname()

    def _issue_badge(self, userid):
        """The issued-badge page (code shown once, never in a URL), or None
        with self._badge_error set."""
        from senaite.pfas.browser import badges
        from senaite.pfas import document_templates as dt
        if api.get_user(userid) is None:
            self._badge_error = u"error:No such user."
            return None
        try:
            code = badges.issue_badge(userid)
        except ValueError as exc:
            self._badge_error = u"error:No badge for %s: %s." % (userid, exc)
            return None
        info = staff.staff_info(userid)
        from senaite.pfas import lab_identity
        lab = lab_identity.lab_name()
        self.issued = {"name": info["fullname"], "code_grouped": u" ".join(code[i:i + 4] for i in range(0, len(code), 4)),
                       "json": dt.script_json({"name": info["fullname"], "title": info["jobtitle"],
                                               "lab": lab, "code": code})}
        self.request.response.setHeader("Cache-Control", "no-store")
        return self.issued_template()


# ── My profile ─────────────────────────────────────────────────────────────

def gated_actions():
    """[(page, action, tier)] from every view's gate table (*_GATES), the
    tables the pages enforce -- so "My permissions" cannot drift from them."""
    here = os.path.dirname(os.path.abspath(__file__))
    out = []
    for name in sorted(os.listdir(here)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        try:
            mod = importlib.import_module("senaite.pfas.browser." + name[:-3])
        except Exception:                                   # noqa: BLE001
            continue
        for attr in sorted(dir(mod)):
            table = getattr(mod, attr)
            if attr.endswith("_GATES") and isinstance(table, dict):
                page = name[:-3].replace("_", " ").capitalize()
                for action, tier in sorted(table.items()):
                    out.append((page, action.replace("_", " "), tier))
    return out


PIN_ACTIONS = ("set_my_pin", "remove_my_pin", "sign_with")
PIN_PASSWORD = u"Enter your password to set a PIN."
PIN_MISMATCH = u"The two PINs differ."


# what the PIN form posts; each name holds "passw", so Zope's error log
# obscures it, and each is taken off the request as it is read
PIN_FIELDS = ("current_password", "new_pin_password", "new_pin_password_again")


def _taken(form, other, key):
    value = form.pop(key, None)
    if isinstance(other, dict):
        other.pop(key, None)
    return safe_unicode(value or u"")


def pin_action(action, userid, form, other=None):
    """A person's own signing PIN (esig.credentials): set or change it with
    their password, remove it, or choose which one signing asks for. A
    wrong password counts as a failed signing attempt. Returns the page's
    "ok:..." or "error:..." message; no PIN or password is ever logged."""
    from senaite.pfas.esig import credentials as cr
    from senaite.pfas.esig import signing
    at = signing.stamp()
    if action == "remove_my_pin":
        cr.remove_pin(userid, at)
        return u"ok:Your PIN is removed: signing asks for your password."
    if action == "sign_with":
        use_pin = form.get("sign_with_pin") in ("on", "1", "true")
        got = cr.set_default(userid, use_pin, at)
        return u"ok:Signing asks for your %s." % signing.CREDENTIAL_WORDS[got]
    password, pin, again = (_taken(form, other, k) for k in PIN_FIELDS)
    rules = signing.rules()
    wait = cr.locked(userid, signing._now(), rules=rules)
    if wait:
        return u"error:" + signing.LOCKED % max(1, (wait + 59) // 60)
    if not password:
        return u"error:" + PIN_PASSWORD
    if not signing._check_password(userid, password):
        cr.failure(userid, cr.PASSWORD, signing._now(), at, rules=rules)
        return u"error:" + signing.WRONG_SECRET % u"password"
    if pin != again:
        return u"error:" + PIN_MISMATCH
    try:
        cr.set_pin(userid, pin, at, rules=rules)
    except ValueError as exc:
        return u"error:%s" % exc
    cr.clear(userid)
    return u"ok:Your PIN is set. Signing asks for your %s." % signing.CREDENTIAL_WORDS[cr.method(userid)]


def signing_summary(info):
    """The profile's one line on what signing asks for: the PIN after a
    badge sign-in (none set: set one), an expired credential, else the
    person's default."""
    word = u"PIN" if info.get("method") == "pin" else u"password"
    if info.get("badge") and not info.get("has_pin"):
        return u"You signed in with your badge: set a PIN to sign."
    if info.get("expired"):
        return (u"Your PIN has expired: set a new one to sign." if word == u"PIN"
                else u"Your password has expired: change it to sign.")
    if info.get("badge"):
        return u"You signed in with your badge: every signature asks for your PIN."
    return u"Every signature asks for your %s." % word


class PFASMyProfileView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/my_profile.pt")

    @staticmethod
    def sign_titles(keys):
        """The sign rights held, by their titles (staff.SIGN_ROLES)."""
        titles = dict(staff.SIGN_ROLES)
        return [titles.get(k, k) for k in keys or []]

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        userid = self.userid()
        if not userid:
            return refuse(req)
        if req.method == "POST":
            action = req.form.get("action", "")
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            msg = u"error:Unknown action."
            contact = staff.contact_for(userid)
            if action in PIN_ACTIONS:
                # what signing asks for needs no Lab Contact; a store that
                # cannot be read refuses
                try:
                    msg = pin_action(action, userid, req.form, getattr(req, "other", None))
                except Exception:                           # noqa: BLE001
                    logger.error("signing PIN of %s not changed", userid, exc_info=True)
                    msg = u"error:Your PIN could not be changed."
            elif action == "set_avatar":
                # the sign-in tile's picture: needs no Lab Contact
                from senaite.pfas import avatars
                try:
                    avatars.choose(api.get_portal(), userid, req.form.get("avatar") or u"")
                    msg = u"ok:Your sign-in picture is saved."
                except ValueError as exc:
                    msg = u"error:%s" % exc
            elif contact is None:
                msg = u"error:Your account is not linked to a Lab Contact yet: ask a manager on People & Roles."
            elif action == "upload_my_signature":
                raw, why = staff.check_signature(_upload(req.form, "signature"))
                if why:
                    msg = u"error:%s" % why
                else:
                    _track(userid, u"Signature of %s (own profile)" % userid)
                    set_signature(contact, raw)
                    msg = u"ok:Your signature is saved."
            elif action == "remove_my_signature":
                _track(userid, u"Signature of %s removed (own profile)" % userid)
                set_signature(contact, None)
                msg = u"ok:Your signature is removed."
            from six.moves.urllib.parse import urlencode
            kind, text = msg.split(u":", 1)
            req.response.redirect("%s/@@pfas-my-profile?%s" % (
                self.portal_url(), urlencode({kind: text.encode("utf-8")})))
            return ""
        return self.template()

    def userid(self):
        user = getSecurityManager().getUser()
        if user is None or user.getUserName() == "Anonymous User":
            return u""
        return safe_unicode(user.getId())

    def message(self):
        return _text(self.request.form, "ok"), _text(self.request.form, "error")

    def info(self):
        return staff.staff_info(self.userid())

    def avatar_choices(self):
        """[{"id", "label", "url", "chosen"}]: the sign-in tile pictures."""
        from senaite.pfas import avatars
        portal = api.get_portal()
        mine = avatars.get(portal, self.userid())
        purl = portal.absolute_url()
        return [{"id": i, "label": label, "url": avatars.url(purl, i), "chosen": i == mine}
                for i, label in avatars.AVATARS]

    def roles(self):
        return portal_roles(self.userid())

    def is_director(self):
        return staff.director_userid() == self.userid()

    def tiers(self):
        roles = set(self.roles())
        return {TIER_CONFIG: bool(roles & set(ALLOWED_ROLES)),
                TIER_SITE_ADMIN: bool(roles & set(SITE_ADMIN_ROLES))}

    def permissions(self):
        """[(page, [(action, allowed)])] -- every gated action, and whether
        this user's roles pass its gate. Actions on no gate are open to any
        signed-in user (bench work)."""
        tiers = self.tiers()
        pages = {}
        for page, action, tier in gated_actions():
            pages.setdefault(page, []).append((action, tiers.get(tier, False)))
        return sorted(pages.items())

    def signing(self):
        """{"method": "password" | "pin", "has_pin", "badge", "expired",
        "pin_rule"}: what signing asks this person for in this session (the
        PIN after a badge sign-in), whether that has expired, and the PIN
        rule in force."""
        from senaite.pfas.esig import credentials as cr
        from senaite.pfas.esig import signing as sg
        userid = self.userid()
        try:
            rules = sg.rules()
            kind = sg.credential_kind(self.request, userid)
            expired = (cr.pin_expired(userid, sg.utcnow(), rules) if kind == cr.PIN
                       else sg.password_expired(userid, rules))
            out = {"method": kind, "has_pin": cr.has_pin(userid),
                   "badge": sg._badge_session(self.request, userid),
                   "expired": expired, "pin_rule": cr.pin_format(rules)}
        except Exception:                                   # noqa: BLE001
            logger.warning("signing credentials not readable", exc_info=True)
            out = {"method": cr.PASSWORD, "has_pin": False, "badge": False, "expired": False,
                   "pin_rule": cr.PIN_FORMAT}
        out["summary"] = signing_summary(out)
        return out

    def badge(self):
        try:
            from senaite.pfas.browser import badges
            return badges.badge_status(self.userid())
        except Exception:                                   # noqa: BLE001
            return None
