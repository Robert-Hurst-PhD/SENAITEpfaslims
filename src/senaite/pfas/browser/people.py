# -*- coding: utf-8 -*-
"""@@pfas-people: People & Roles. One row per person over the user account,
its Lab Contact and the roles it holds.

The staff handlers (link, save, signature, badge) are lab_staff.py's, inherited
unchanged. Roles and account changes go through role_guard, which refuses an
administrator's account to a Lab Manager. @@pfas-lab-staff redirects here.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import binascii
import logging
import os
import re

from bika.lims import api
from plone.protect import CheckAuthenticator
from Products.CMFPlone.utils import safe_unicode
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden

from senaite.pfas import entry_rights, role_guard
from senaite.pfas import staff as staff_pool
from senaite.pfas.browser import staff
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.lab_staff import PFASLabStaffView, _text, users
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action, refuse
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.people")

PEOPLE_GATES = {"link": TIER_CONFIG, "save_staff": TIER_CONFIG,
                "upload_signature": TIER_CONFIG, "remove_signature": TIER_CONFIG,
                "issue_badge": TIER_CONFIG, "revoke_badge": TIER_CONFIG,
                "set_roles": TIER_CONFIG, "set_email": TIER_CONFIG,
                "add_person": TIER_CONFIG, "send_reset": TIER_CONFIG,
                "deactivate": TIER_CONFIG, "reactivate": TIER_CONFIG}

# the actions on a person's Lab Contact and badge
CONTACT_ACTIONS = frozenset(("link", "save_staff", "upload_signature", "remove_signature",
                             "issue_badge", "revoke_badge"))

ACTIVE, NO_LOGIN, INACTIVE = u"Active", u"No login", u"Inactive"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _track_account(userid, action):
    """The account's e-mail before and after, in Configuration History."""
    from senaite.pfas import config_history

    def view():
        user = api.get_user(userid)
        return {"email": (user.getProperty("email") if user is not None else u"") or u""}
    config_history.track(api.get_portal(), "person_account", userid, view,
                         label=u"Account of {0}".format(userid), action=action)


# fields that legitimately post several values
MULTI_FIELDS = ("group", "sign_as")


class PFASPeopleView(GateMixin, PFASLabStaffView):

    template = ViewPageTemplateFile("templates/people.pt")

    def __call__(self):
        # flatten_form keeps only the first of a repeated field; the role pills
        # and the sign-as choices post one field per value, so read them first
        multi = dict((k, self.request.form.get(k)) for k in MULTI_FIELDS)
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            action = req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, PEOPLE_GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            userid = _text(req.form, "userid")
            msg = u"error:Unknown action."
            if action in CONTACT_ACTIONS and userid:
                # a contact is its account's: the account's own rules apply
                refusal = role_guard.may_manage_account(api.get_portal(), userid)
                if refusal:
                    msg = u"error:%s" % refusal
                    action = ""
            if action == "link":
                msg = self._link(userid)
            elif action == "save_staff":
                msg = self._save(userid, req.form, multi.get("sign_as"))
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
            elif action == "set_roles":
                msg = self._set_roles(userid, req.form, multi.get("group"))
            elif action == "set_email":
                msg = self._set_email(userid, _text(req.form, "email"))
            elif action == "send_reset":
                msg = self._send_reset(userid)
            elif action == "add_person":
                msg = self._add_person(req.form)
            elif action in ("deactivate", "reactivate"):
                msg = self._set_active(_text(req.form, "contact_uid"), userid,
                                       action == "reactivate", _text(req.form, "reason"))
            from six.moves.urllib.parse import urlencode
            kind, text = msg.split(u":", 1)
            req.response.redirect("%s/@@pfas-people?%s#%s" % (
                self.portal_url(), urlencode({kind: text.encode("utf-8")}),
                userid or _text(req.form, "contact_uid")))
            return ""
        if not self.can_configure():
            return refuse(req)
        return self.template()

    def message(self):
        return _text(self.request.form, "ok"), _text(self.request.form, "error")

    # ── actions ────────────────────────────────────────────────────────────

    def _actor_id(self):
        user = api.get_current_user()
        return user.getId() if user is not None else u""

    def _set_roles(self, userid, form, wanted):
        portal = api.get_portal()
        wanted = wanted or []
        if not isinstance(wanted, (list, tuple)):
            wanted = [wanted]
        wanted = set(safe_unicode(g).strip() for g in wanted)
        held = set(role_guard.held_groups(portal, userid))
        add, remove = wanted - held, held - wanted
        if not (add or remove):
            return u"ok:No role changed."
        refusal = role_guard.apply(portal, self._actor_id(), userid, add, remove,
                                   _text(form, "reason"))
        return u"error:%s" % refusal if refusal else u"ok:Roles of %s saved." % userid

    def _set_email(self, userid, email):
        portal = api.get_portal()
        refusal = role_guard.may_manage_account(portal, userid)
        if refusal:
            return u"error:%s" % refusal
        if not _EMAIL.match(email):
            return u"error:Enter a valid e-mail address."
        _track_account(userid, u"change e-mail")
        portal.portal_membership.getMemberById(userid).setMemberProperties({"email": email})
        return u"ok:E-mail of %s saved." % userid

    def _send_reset(self, userid):
        try:
            refusal = role_guard.send_reset(api.get_portal(), userid)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("reset e-mail not sent for %s", userid, exc_info=True)
            return u"error:The reset e-mail was not sent: {0}".format(exc)
        return u"error:%s" % refusal if refusal else u"ok:Reset e-mail sent to %s." % userid

    def _add_person(self, form):
        username, name, email = _text(form, "username"), _text(form, "fullname"), _text(form, "email")
        if not (username and name):
            return u"error:Give a user name and a full name."
        if not _EMAIL.match(email):
            return u"error:Enter a valid e-mail address."
        portal = api.get_portal()
        # a random password nobody sees; the person sets theirs from the reset e-mail
        password = binascii.hexlify(os.urandom(16)).decode("ascii") + u"Aa1"
        _track_account(username, u"account created")
        try:
            portal.portal_registration.addMember(
                username, password, properties={"fullname": name, "email": email})
        except ValueError as exc:
            return u"error:%s" % exc
        msg = self._link(username)
        if msg.startswith(u"error:"):
            return msg
        contact = staff.contact_for(username)
        if contact is not None:
            contact.setEmailAddress(email)
        sent = self._send_reset(username)
        if sent.startswith(u"error:"):
            return u"error:Account %s created, but %s" % (username, sent[len(u"error:"):])
        return u"ok:Account %s created and a reset e-mail sent. Set the roles next." % username

    def _set_active(self, contact_uid, posted_userid, activate, reason):
        contact = api.get_object_by_uid(contact_uid, None) if contact_uid else None
        if contact is None:
            return u"error:No such person."
        portal = api.get_portal()
        # the account is the contact's own, read here; the form cannot name another
        account = (contact.getUsername() or u"").strip()
        if account and api.get_user(account) is None:
            account = u""
        if posted_userid != account:
            return u"error:That account does not belong to this person."
        if not reason:
            return u"error:Give a reason for the change."
        if account:
            refusal = role_guard.may_manage_account(portal, account)
            if refusal:
                return u"error:%s" % refusal
            if not activate and account == self._actor_id():
                return u"error:Nobody deactivates their own account."
            groups = role_guard.held_groups(portal, account) if not activate else []
            if groups:
                refusal = role_guard.apply(portal, self._actor_id(), account, (), groups, reason)
                if refusal:
                    return u"error:%s" % refusal
        api.do_transition_for(contact, u"activate" if activate else u"deactivate")
        from senaite.pfas import config_history
        action = u"reactivated" if activate else u"deactivated"
        config_history.append(portal, {
            "store": "person_account", "key": account or contact_uid, "who": config_history.actor(),
            "label": u"Account of {0}".format(account or contact.getFullname()),
            "action": action, "reason": reason, "changes": []})
        if account and not activate:
            # an inactive person no longer signs in, by badge either; the
            # revocation is recorded in the badge's own history
            from senaite.pfas.browser import badges
            try:
                badges.revoke_badge(account)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("badge of %s not revoked", account, exc_info=True)
                return u"error:%s is inactive, but the badge was not revoked: %s" % (
                    contact.getFullname(), exc)
        return u"ok:%s is %s." % (contact.getFullname(), u"active again" if activate else u"inactive")

    # ── page data ──────────────────────────────────────────────────────────

    def signs_as(self):
        return [(k, label) for k, label, _w in staff.SIGNS_AS]

    def signs_as_key(self, info):
        return staff.signs_as_key(info.get("sign_as"))

    def role_choices(self):
        return [(g, label) for g, _r, label in role_guard.ROLE_GROUPS]

    def show_inactive(self):
        return bool(_text(self.request.form, "inactive"))

    def visible_rows(self):
        return [r for r in self.rows() if self.show_inactive() or r["status"] != INACTIVE]

    def rows(self):
        portal = api.get_portal()
        role_label = dict((r, label) for _g, r, label in role_guard.ROLE_GROUPS)
        order = [r for _g, r, _l in role_guard.ROLE_GROUPS]
        out, seen = [], set()
        for contact in staff_pool.contacts_folder(portal).objectValues():
            row = self._row(portal, contact, role_label, order)
            if row is not None:
                out.append(row)
                seen.add(row["userid"])
        for userid, name in users():
            if userid in seen:
                continue
            out.append(self._row(portal, None, role_label, order, userid, name))
        return sorted(out, key=lambda r: r["fullname"].lower())

    def _row(self, portal, contact, role_label, order, userid=u"", name=u""):
        info = staff_pool.staff_record(contact) if contact is not None else {
            "fullname": name, "initials": u"", "email": u"", "signature_url": u"", "uid": u"",
            "username": userid}
        if not info:
            return None
        userid = info["username"] if contact is not None else userid
        user = api.get_user(userid) if userid else None
        userid = user.getId() if user is not None else u""
        if contact is None:
            status = ACTIVE
        elif not api.is_active(contact):
            status = INACTIVE
        else:
            status = ACTIVE if staff_pool.has_login(contact) else NO_LOGIN
        held = set(user.getRolesInContext(portal)) if user is not None else set()
        entry = staff.entry_status(userid) if userid else None
        sign_info = staff.staff_info(userid) if userid else None
        issues = []
        if userid and status != INACTIVE:
            if sign_info["has_contact"]:
                if not sign_info["signature"]:
                    issues.append(u"no signature")
                if not staff.clean_sign_as(sign_info["sign_as"]) and userid != staff.director_userid():
                    issues.append(u"may not sign anything")
            else:
                issues.append(u"no Lab Contact")
        return {"issues": issues, "userid": userid, "fullname": info["fullname"],
                "username": user.getUserName() if user is not None else info["username"],
                "email": (user.getProperty("email") if user is not None else u"") or info["email"],
                "initials": info["initials"],
                "roles": [role_label[r] for r in order if r in held],
                "groups": role_guard.held_groups(portal, userid) if userid else [],
                "has_signature": bool(info["signature_url"]),
                "can_enter": entry == entry_rights.OK,
                "status": status, "contact_uid": info["uid"],
                "info": sign_info if userid else {
                    "userid": u"", "fullname": info["fullname"], "jobtitle": u"", "credentials": u"",
                    "sign_as": [], "signature": u"", "has_contact": contact is not None},
                "badge": self._badge(userid) if userid else None}

    def checklist(self):
        """What still stops a designed document from being signed."""
        rows = [r for r in self.rows() if r["userid"] and r["status"] != INACTIVE]
        out = []
        if not staff.director_userid():
            out.append(u"No Laboratory Director is set: choose one on Laboratory.")
        for role, title in staff.SIGN_ROLES:
            if not [r for r in rows if role in r["info"]["sign_as"]]:
                out.append(u"Nobody may sign as %s yet." % title.lower())
        return out

    def _badge(self, userid):
        try:
            from senaite.pfas.browser import badges
            return badges.badge_status(userid)
        except Exception:                                   # noqa: BLE001
            return None


class PFASLabStaffRedirect(ViewHelpers, BrowserView):
    """The old Lab Staff address: bookmarks and links still arrive."""

    def __call__(self):
        return self._redirect("%s/@@pfas-people" % self.portal_url())
