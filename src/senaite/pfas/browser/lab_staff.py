# -*- coding: utf-8 -*-
"""Lab staff and personal profiles (part B).

    @@pfas-lab-staff    Managers: every user, the Lab Contact it is linked to
                        (SENAITE's own link, contact.setUser), job title,
                        credentials, who may sign as preparer / reviewer /
                        director, the signature picture, and a setup checklist
    @@pfas-my-profile   Everyone signed in: their own signature (their own Lab
                        Contact, resolved on the server, never from the form)
                        and what they may do ("My permissions", derived from
                        the same gate tables and roles the pages enforce)

Signatures are PNG / JPEG only, at most 512 KB (staff.check_signature). Every
change is recorded in the configuration change history -- for a signature its
fingerprint, never the picture. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import importlib
import logging
import os

from AccessControl import getSecurityManager
from bika.lims import api
from plone.protect import CheckAuthenticator
from Products.CMFPlone.utils import safe_unicode
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden
from zope.annotation.interfaces import IAnnotations

from senaite.pfas.browser import staff
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (ALLOWED_ROLES, SITE_ADMIN_ROLES, TIER_CONFIG,
                                        TIER_SITE_ADMIN, GateMixin, deny_gated_action, refuse)

logger = logging.getLogger("senaite.pfas.lab_staff")

STAFF_GATES = {"link": TIER_CONFIG, "save_staff": TIER_CONFIG,
               "upload_signature": TIER_CONFIG, "remove_signature": TIER_CONFIG,
               "issue_badge": TIER_CONFIG, "revoke_badge": TIER_CONFIG}


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
    return {"contact": api.get_uid(contact), "fullname": contact.getFullname(),
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


class PFASLabStaffView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/lab_staff.pt")
    issued_template = ViewPageTemplateFile("templates/badge_issued.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            action = req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, STAFF_GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            userid = _text(req.form, "userid")
            msg = u"error:Unknown action."
            if action == "link":
                msg = self._link(userid)
            elif action == "save_staff":
                msg = self._save(userid, req.form)
            elif action in ("upload_signature", "remove_signature"):
                msg = self._signature(userid, action == "remove_signature")
            elif action == "issue_badge":
                page = self._issue_badge(userid)
                if page is not None:
                    return page             # the code is shown once, in this response
                msg = self._badge_error
            elif action == "revoke_badge":
                from senaite.pfas.browser import badges
                msg = (u"ok:Badge of %s revoked." % userid if badges.revoke_badge(userid)
                       else u"error:%s has no badge." % userid)
            from six.moves.urllib.parse import urlencode
            kind, text = msg.split(u":", 1)
            req.response.redirect("%s/@@pfas-lab-staff?%s#%s" % (
                self.portal_url(), urlencode({kind: text.encode("utf-8")}), userid))
            return ""
        if not self.can_configure():
            return refuse(req)
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def message(self):
        return _text(self.request.form, "ok"), _text(self.request.form, "error")

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

    def _save(self, userid, form):
        contact = staff.contact_for(userid)
        if contact is None:
            return u"error:Link %s to a Lab Contact first." % userid
        _track(userid, u"Staff settings of %s" % userid)
        contact.setJobTitle(_text(form, "jobtitle"))
        sign_as = form.get("sign_as") or []
        if not isinstance(sign_as, (list, tuple)):
            sign_as = [sign_as]
        IAnnotations(contact)[staff.STAFF_KEY] = {
            "credentials": _text(form, "credentials"),
            "sign_as": staff.clean_sign_as([safe_unicode(x) for x in sign_as])}
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
        from senaite.pfas.print_settings import get_print_settings
        lab = get_print_settings(api.get_portal()).get("lab_name") or u""
        self.issued = {"name": info["fullname"], "code_grouped": u" ".join(code[i:i + 4] for i in range(0, len(code), 4)),
                       "json": dt.script_json({"name": info["fullname"], "title": info["jobtitle"],
                                               "lab": lab, "code": code})}
        self.request.response.setHeader("Cache-Control", "no-store")
        return self.issued_template()

    # ── page data ──────────────────────────────────────────────────────────

    def sign_roles(self):
        return staff.SIGN_ROLES

    def rows(self):
        director = staff.director_userid()
        out = []
        for userid, name in users():
            info = staff.staff_info(userid)
            issues = []
            if not info["has_contact"]:
                issues.append(u"no Lab Contact")
            else:
                if not info["signature"]:
                    issues.append(u"no signature")
                if not info["sign_as"]:
                    issues.append(u"may not sign anything")
            out.append({"userid": userid, "name": info["fullname"] or name,
                        "roles": portal_roles(userid), "info": info,
                        "director": userid == director, "issues": issues,
                        "badge": self._badge(userid)})
        return out

    def _badge(self, userid):
        try:
            from senaite.pfas.browser import badges
            return badges.badge_status(userid)
        except Exception:                                   # noqa: BLE001
            return None

    def checklist(self):
        """What still stops a designed document from being signed."""
        rows = self.rows()
        out = []
        director = staff.director_userid()
        if not director:
            out.append(u"No Laboratory Director is set (Site Settings).")
        for role, title in staff.SIGN_ROLES:
            if not [r for r in rows if role in r["info"]["sign_as"]]:
                out.append(u"Nobody may sign as %s yet." % title.lower())
        return out


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


class PFASMyProfileView(BrowserView):

    template = ViewPageTemplateFile("templates/my_profile.pt")

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
            if action == "set_avatar":
                # the sign-in tile's picture: needs no Lab Contact
                from senaite.pfas import avatars
                try:
                    avatars.choose(api.get_portal(), userid, req.form.get("avatar") or u"")
                    msg = u"ok:Your sign-in picture is saved."
                except ValueError as exc:
                    msg = u"error:%s" % exc
            elif contact is None:
                msg = u"error:Your account is not linked to a Lab Contact yet: ask a manager (Lab Staff)."
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

    def portal_url(self):
        return api.get_portal().absolute_url()

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

    def badge(self):
        try:
            from senaite.pfas.browser import badges
            return badges.badge_status(self.userid())
        except Exception:                                   # noqa: BLE001
            return None
