# -*- coding: utf-8 -*-
"""When a password is set, from the user folder's own event
(ICredentialsUpdatedEvent, fired whenever a password changes).

The time is kept for the expiry a manager sets (signing_rules), and who set
it decides the rest (esig.credentials.password_changed):

* set by another signed-in account, a reset opens (as a reset e-mail a
  manager sends does, role_guard.send_reset): the person is told, on the
  bell and by e-mail to their Lab Contact's address where mail is set up,
  and every signature made as them until they change the password
  themselves is listed for review on the Signatures page;
* set by its holder, signed in, every open reset of theirs closes; set
  through the reset link (nobody signed in) none does, as whoever held the
  link may not be the person; a password set by another account or through
  the link also removes the person's signing PIN;
* a service account's (PFASAutomation) keeps its time alone: it signs
  nothing.

Written after the transaction commits, so a change that aborts leaves no
record. Never the password. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.password_events")

TOLD_SUBJECT = u"%s Your password was reset by %s"
TOLD_BODY = (u"Your password for %s was reset by %s at %s.\n\n"
             u"Once signed in, change it on My profile: %s/@@pfas-my-profile\n\n"
             u"Every signature made as you until you change it there is listed for the "
             u"quality officer's review. If you did not ask for this, tell them.\n")


def _actor_id():
    """The signed-in account making the change; "" when nobody is (the
    reset link) or the system acts unnamed."""
    from AccessControl import getSecurityManager
    user = getSecurityManager().getUser()
    if user is None or user.getUserName() == "Anonymous User":
        return u""
    return u"%s" % (user.getId() or u"")


def on_credentials_updated(event):
    principal = getattr(event, "principal", None) or getattr(event, "object", None)
    userid = getattr(principal, "getId", lambda: None)()
    if not userid:
        return
    try:
        from senaite.pfas import after_commit
        from senaite.pfas.esig import signing
        after_commit.run_once("password-set:%s" % userid, record, u"%s" % userid,
                              signing.stamp(), _actor_id())
    except Exception:                                       # noqa: BLE001
        logger.error("the password change of %s was not recorded", userid, exc_info=True)


def record(userid, at, by):
    """Keep the change; tell the person of a reset."""
    from senaite.pfas.esig import credentials, signing
    review = not signing._is_automation(userid)
    if credentials.password_changed(userid, at, by, review=review) == "reset":
        logger.warning("the password of %s was set by %s: a reset is open for review", userid, by)
        tell(userid, at, by)


def tell(userid, at, by):
    """E-mail the person at the address on their Lab Contact, which the
    account's own e-mail (a manager may change it) is not; nothing when mail
    is not set up or there is no such address (the bell still tells them)."""
    try:
        from bika.lims import api
        from senaite.pfas import lab_identity, lab_time, mail_text
        portal = api.get_portal()
        if not (getattr(getattr(portal, "MailHost", None), "smtp_host", "") or ""):
            return False
        address = _address(userid)
        if not address:
            return False
        subject = TOLD_SUBJECT % (lab_identity.mail_prefix(portal), by)
        body = TOLD_BODY % (userid, by, lab_time.show(at, "utc"), portal.absolute_url())
        portal.MailHost.send(mail_text.message(
            portal.getProperty("email_from_address", "lims@localhost"), address, subject, body),
            immediate=True)
        return True
    except Exception:                                       # noqa: BLE001
        logger.warning("%s was not told of the reset by e-mail", userid, exc_info=True)
        return False


def _address(userid):
    from senaite.pfas.browser.staff import contact_for
    contact = contact_for(userid)
    return (contact.getEmailAddress() or u"").strip() if contact is not None else u""


def reset_mailed(userid, at, by):
    """A manager mailed `userid` a reset link: a reset opens and the person
    is told (role_guard.send_reset, after its commit)."""
    from senaite.pfas.esig import credentials
    credentials.reset_sent(userid, at, by)
    if by and by != userid:
        tell(userid, at, by)
