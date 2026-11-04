# -*- coding: utf-8 -*-
"""Notices: something the lab must act on, told to the person responsible
on their landing and by e-mail, with reminders until it is done.

Kinds: a run sent back by a rejected lot (send_back.py),
told to the analyst who built the run (or finalized the extraction it goes
back to) and closed when the run is rebuilt. One open notice per kind and
worksheet; a notice with no user named shows to everyone.

The System page sets, per kind, whether e-mails are sent and how many hours
apart the reminders are (0: the first e-mail only). The worker asks for
the due e-mails every NOTICE_TICK_SECONDS (pfas_pipeline).

    raise_(store, kind, userid, ws_id, stage, lot, text, at) -> notice
    open_for(store, userid)                 -> [notice]
    close_run(store, ws_id, at)             -> number closed
    due_reminders(store, settings, now)     -> [notice]
    mark_sent(notice, at)
    settings(stored) / settings_from_form(form)
    email(notice, portal_url)               -> (subject, body)

Times are stored "YYYY-MM-DD HH:MM" (UTC); an e-mail says them on the
laboratory's clock. The store and its rules are pure; load / save / send
need Zope. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json
import logging

from senaite.pfas import lab_time

logger = logging.getLogger("senaite.pfas.notices")

KEY = "senaite.pfas.notices"
SETTINGS_KEY = "senaite.pfas.notice_settings"
KINDS = {"run_sent_back": u"Run sent back"}
DEFAULT = {"email": True, "every_hours": 24}
_FMT = "%Y-%m-%d %H:%M"
_STAGE_PAGES = {"run": u"Run Builder", "extraction": u"extraction"}


def raise_(store, kind, userid, ws_id, stage, lot, text, at):
    fields = {"userid": userid or u"", "stage": stage, "lot": lot or u"", "text": text or u"",
              "raised_at": at}
    for n in store:
        if n.get("kind") == kind and n.get("ws_id") == ws_id and not n.get("closed_at"):
            n.update(fields)
            return n
    n = dict(fields, id=u"N%d" % (len(store) + 1), kind=kind, ws_id=ws_id,
             emailed_at=u"", closed_at=u"")
    store.append(n)
    return n


def open_for(store, userid):
    return [n for n in store or []
            if not n.get("closed_at") and (not n.get("userid") or n.get("userid") == userid)]


def close_run(store, ws_id, at):
    n_closed = 0
    for n in store or []:
        if n.get("ws_id") == ws_id and not n.get("closed_at"):
            n["closed_at"] = at
            n_closed += 1
    return n_closed


def settings(stored):
    out = {}
    for kind in KINDS:
        s = dict(DEFAULT)
        s.update((stored or {}).get(kind) or {})
        out[kind] = s
    return out


def settings_from_form(form):
    out = {}
    for kind in KINDS:
        try:
            hours = max(0, int(u"%s" % (form.get("notice_hours.%s" % kind) or u"").strip()))
        except ValueError:
            hours = DEFAULT["every_hours"]
        out[kind] = {"email": bool(form.get("notice_email.%s" % kind)), "every_hours": hours}
    return out


def _t(value):
    return datetime.datetime.strptime((value or u"")[:16], _FMT)


def due_reminders(store, settings_, now):
    out = []
    for n in store or []:
        s = (settings_ or {}).get(n.get("kind")) or {}
        if n.get("closed_at") or not s.get("email"):
            continue
        last = n.get("emailed_at")
        if not last:
            out.append(n)
        elif s.get("every_hours") and _t(now) - _t(last) >= datetime.timedelta(hours=s["every_hours"]):
            out.append(n)
    return out


def mark_sent(notice, at):
    notice["emailed_at"] = at


def email(notice, portal_url, prefix):
    subject = u"%s %s: %s" % (
        prefix, KINDS.get(notice.get("kind"), notice.get("kind")), notice.get("ws_id"))
    body = u"%s\n\nRun: %s\nGo back to: %s\nLot: %s\nSince: %s\n\nData Review: %s/@@pfas-data-review?batch_id=%s\n" % (
        notice.get("text") or u"", notice.get("ws_id"),
        _STAGE_PAGES.get(notice.get("stage"), notice.get("stage") or u""),
        notice.get("lot") or u"", lab_time.show(notice.get("raised_at") or u""), portal_url,
        notice.get("ws_id"))
    return subject, body


# ── storage and sending (Zope) ───────────────────────────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def load(portal):
    try:
        return json.loads(_ann(portal).get(KEY) or u"[]")
    except ValueError:
        return []


def save(portal, store):
    _ann(portal)[KEY] = json.dumps(store, sort_keys=True)


def load_settings(portal):
    try:
        return settings(json.loads(_ann(portal).get(SETTINGS_KEY) or u"{}"))
    except ValueError:
        return settings({})


def save_settings(portal, values):
    _ann(portal)[SETTINGS_KEY] = json.dumps(values, sort_keys=True)


def now():
    return datetime.datetime.utcnow().strftime(_FMT)


def userid_for_initials(portal, initials):
    """The user signed in as the Lab Contact with these initials, or u""."""
    from senaite.pfas.staff import contacts_folder, staff_record
    ini = (initials or u"").strip().upper()
    folder = contacts_folder(portal)
    for c in (folder.objectValues() if (ini and folder is not None) else []):
        if (staff_record(c) or {}).get("initials") == ini:
            return getattr(c, "getUsername", lambda: u"")() or u""
    return u""


def _address(userid):
    from senaite.pfas.browser.staff import contact_for
    contact = contact_for(userid)
    return (contact.getEmailAddress() or u"").strip() if contact is not None else u""


def send(portal, notice):
    """E-mail one notice to its user (the qc_deviation pattern). False when
    there is no address or no SMTP host, or the send failed."""
    address = _address(notice.get("userid"))
    if not address or not (getattr(getattr(portal, "MailHost", None), "smtp_host", "") or ""):
        logger.warning("notice %s for %s: no e-mail address or no SMTP host",
                       notice.get("id"), notice.get("userid") or u"everyone")
        return False
    from senaite.pfas import lab_identity, mail_text
    subject, body = email(notice, portal.absolute_url(), lab_identity.mail_prefix(portal))
    message = mail_text.message(
        portal.getProperty("email_from_address", "lims@localhost"), address, subject, body)
    try:
        portal.MailHost.send(message, immediate=True)
        return True
    except Exception as exc:                                # noqa: BLE001
        logger.error("notice %s not sent: %s", notice.get("id"), exc)
        return False


def send_due(portal):
    """Send the due e-mails; returns how many went. A failed send waits
    for the next reminder too (logged), rather than retrying every tick."""
    store = load(portal)
    due = due_reminders(store, load_settings(portal), now())
    sent = 0
    for n in due:
        ok = send(portal, n)
        mark_sent(n, now())
        n["email_ok"] = ok
        sent += 1 if ok else 0
    if due:
        save(portal, store)
    return sent
