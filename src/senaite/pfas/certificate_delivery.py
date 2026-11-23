# -*- coding: utf-8 -*-
"""The e-mail that delivers an issued certificate to its client, and its
record.

A certificate is e-mailed when it is issued: the sample's publish (or
republish) transition, which records the register entry and the
authoriser's ledger row, queues one delivery on the issued report, in the
same transaction, so an issue never loses its e-mail. The report's PDF is
the package its tier calls for (the worker replaces the stored certificate
with the sealed package), so the e-mail carries the package. The e-mail
form's Send (browser/edd_email.py) sends it in the same request, after the
issue is committed, as core does; a Manager sends a waiting one again from
Certificates (@@pfas-delivery-send). With no mail server set up nothing is
tried: the delivery waits with that reason. The report's annotation
DELIVERY_KEY holds the list, newest last:

    [{"report_ids": [id], "interim": bool, "queued_at": iso,
      "recipients": ["Name <address>"], "sent_to": [address],
      "state": "queued" | "sent", "reason": text,
      "attempts": [{"at", "by", "reached": [address], "failed": [address],
                    "reason", "files": [{"name", "sha256"}]}]}]

A delivery is sent once every recipient was reached; until then it waits,
with the reason the last attempt gave.

A client's e-mail carries no seal note and no seal certificate: proving an
issued PDF unaltered is the laboratory's own audit (the register's hash,
the authoriser's ledger row and the seal, checked by tools/esig/verify.py).
An e-mail with an interim EDD says the EDD is interim.

The record and the texts are pure (Python 2.7 and 3); load and save read
Plone and import it when called.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json
import logging
import os

logger = logging.getLogger("senaite.pfas.certificate_delivery")

DELIVERY_KEY = "senaite.pfas.certificate_delivery"
QUEUED, SENT = "queued", "sent"

NO_MAIL_SERVER = "No mail server is set up"
NO_RECIPIENT = "No recipient with an e-mail address"
NOT_REACHED = "Not reached"
SERVER_REFUSED = "The mail server %s did not accept it"
WAITING = "Waiting to be e-mailed"
SENT_LINE = "E-mailed to %s, %s"
SENT_AT_ISSUE = "E-mailed to %s"
NOT_SENT_LINE = "Not e-mailed: %s"
PARTLY_LINE = "E-mailed to %s; waiting for %s: %s"
# what the person who pressed Send reads when the e-mail could not go
SEND_WAITS = ("Issued. The e-mail waits: %s. Send it again from Certificates "
              "once mail is set up.")

# what an e-mail carrying an interim EDD says of it
NOTE_EDD_INTERIM = "The EDD file is marked interim, as the certificate is: a final follows."
INTERIM_MARK = "_INTERIM"


def _u(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "%s" % (value,)


def shown_recipient(recipient):
    """A recipient as a person reads it: "Name <address>" with the name as
    written, never the escapes the mail header form gives brackets in it
    ("Quality Manager \\(DEMO\\)"); the bare address when it has no name."""
    from email.utils import parseaddr
    text = _u(recipient).strip()
    name, addr = parseaddr(text)
    if not addr:
        return text
    name = (name or u"").strip()
    return u"%s <%s>" % (name, addr) if name and name != addr else addr


def address(recipient):
    """The bare address of a recipient ("Name <address>" or an address)."""
    from email.utils import parseaddr
    text = _u(recipient).strip()
    return (parseaddr(text)[1] or text).strip()


def _unique(items):
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def new_delivery(report_id, recipients, interim, at):
    return {"report_ids": [report_id] if report_id else [], "interim": bool(interim), "queued_at": at,
            "recipients": _unique(_u(r).strip() for r in recipients or []), "sent_to": [],
            "state": QUEUED, "reason": "", "attempts": []}


def queue_issue(deliveries, report_id, recipients, interim, at):
    """The report's deliveries with this issue queued: a copy. The samples
    of one report are published together, so an issue joins the newest
    delivery while it has not been tried yet; otherwise a new delivery is
    queued."""
    out = copy.deepcopy(list(deliveries or []))
    last = out[-1] if out else None
    if last is not None and last.get("state") == QUEUED and not last.get("attempts"):
        last["report_ids"] = _unique(list(last.get("report_ids") or []) + [report_id])
        last["recipients"] = _unique(list(last.get("recipients") or []) + [_u(r).strip() for r in recipients or []])
        last["interim"] = bool(last.get("interim")) or bool(interim)
        return out
    out.append(new_delivery(report_id, recipients, interim, at))
    return out


def waiting_for(delivery):
    """The recipients not reached yet."""
    sent = set(address(a) for a in (delivery or {}).get("sent_to") or [])
    return [r for r in (delivery or {}).get("recipients") or [] if address(r) not in sent]


def record_attempt(delivery, reached, failed, reason, at, by, files, recipients=None):
    """The delivery after one attempt to e-mail it: a copy. `recipients`,
    when given, are the ones the sender chose: they replace the queued
    ones before the first attempt and join them after. The delivery is
    sent once nobody is left to reach; else it waits with `reason`."""
    out = copy.deepcopy(delivery or new_delivery("", [], False, at))
    if recipients is not None:
        chosen = [_u(r).strip() for r in recipients]
        out["recipients"] = _unique(chosen if not out.get("attempts") else list(out.get("recipients") or []) + chosen)
    reached = _unique(address(r) for r in reached or [])
    failed = _unique(address(r) for r in failed or [])
    out["sent_to"] = _unique(list(out.get("sent_to") or []) + reached)
    out["attempts"] = list(out.get("attempts") or []) + [
        {"at": at, "by": _u(by), "reached": reached, "failed": failed, "reason": _u(reason),
         "files": [{"name": _u(f.get("name")), "sha256": _u(f.get("sha256"))} for f in files or []]}]
    done = bool(out.get("recipients")) and not waiting_for(out)
    out["state"] = SENT if done else QUEUED
    out["reason"] = "" if done else (_u(reason) or (NO_RECIPIENT if not out.get("recipients") else NOT_REACHED))
    return out


def newest(deliveries):
    return (deliveries or [None])[-1]


def is_waiting(delivery):
    return bool(delivery) and delivery.get("state") == QUEUED


def retry_due(delivery):
    """True for a delivery the timed retry sends again: waiting after an
    attempt that did not reach everyone. One never tried is the Send's of
    the issue itself (or a Manager's), never the timer's."""
    return is_waiting(delivery) and bool(delivery.get("attempts"))


def delivery_line(delivery, shown, issued_at=None):
    """What Certificates says of a report's newest delivery; `shown` gives a
    stored time as the screen shows it. The time it was sent is left out
    when it reads as the issue's own (`issued_at`), which the row shows
    already. u"" when there is none."""
    if not delivery:
        return ""
    attempts = delivery.get("attempts") or []
    sent_to = delivery.get("sent_to") or []
    last_at = attempts[-1].get("at") if attempts else ""
    if delivery.get("state") == SENT:
        when = shown(last_at)
        if issued_at and when == shown(issued_at):
            return SENT_AT_ISSUE % ", ".join(sent_to)
        return SENT_LINE % (", ".join(sent_to), when)
    if not attempts:
        return WAITING
    reason = delivery.get("reason") or NOT_REACHED
    if sent_to:
        return PARTLY_LINE % (", ".join(sent_to), ", ".join(address(r) for r in waiting_for(delivery)), reason)
    return NOT_SENT_LINE % reason


def server_refused(host):
    """The reason an attempt waits when the mail server named did not take
    the e-mail: a server that is down, or one named by default and never
    set up, reads the same, with its name."""
    host = _u(host).strip()
    return SERVER_REFUSED % host if host else NOT_REACHED


def smtp_ready(mailhost):
    """True when the site's mail host names a server to send through; a
    mail host with none accepts a message and sends nothing."""
    return bool((getattr(mailhost, "smtp_host", "") or "").strip())


# ── the note ─────────────────────────────────────────────────────────────────

# what the e-mail of a certificate superseding an interim says of it
NOTE_SUPERSEDES = "This certificate supersedes interim certificate %s: %s."


def client_note(interim_edd=False, superseded=None):
    """The note an e-mail ends with, as HTML: that its EDD is interim, when
    it carries one, and which interim certificates it supersedes
    ([{"report_id", "reason"}]); u"" otherwise. No seal note and no seal
    certificate go to a client."""
    from senaite.pfas.html_text import escape
    lines = []
    if interim_edd:
        lines.append(NOTE_EDD_INTERIM)
    for s in superseded or []:
        lines.append(NOTE_SUPERSEDES % (s.get("report_id") or "", (s.get("reason") or "").rstrip(".")))
    return "".join("<p>%s</p>" % escape(t) for t in lines)


def with_note(body, note):
    """The e-mail body with the note after it."""
    return "%s\n<hr/>\n%s" % (_u(body), note) if note else _u(body)


def interim_filename(name):
    """An EDD's attachment name marked interim, before its extension; the
    file's own columns are its format's and are never changed."""
    name = _u(name)
    if INTERIM_MARK in name:
        return name
    stem, ext = os.path.splitext(name)
    return "%s%s%s" % (stem, INTERIM_MARK, ext)


# ── on the report ────────────────────────────────────────────────────────────

def sample_recipients(ar):
    """Whom core's e-mail form offers for a sample: its contact, its CC
    contacts and its CC addresses, each with an address, as "Name
    <address>"; the sample's responsibles too when core's setup always
    copies them."""
    from bika.lims import api
    from bika.lims.api import mail as mailapi
    out = []

    def add(name, email):
        email = _u(email).strip()
        if email:
            out.append(_u(mailapi.to_email_address(email, name=api.safe_unicode(name or email))))

    for contact in [ar.getContact()] + list(ar.getCCContact() or []):
        if contact:
            add(contact.Title(), contact.getEmailAddress())
    for email in ar.getCCEmails(as_list=True) or []:
        add(email, email)
    try:
        if api.get_setup().getAlwaysCCResponsiblesInReportEmail():
            found = ar.getResponsible() or {}
            for mid in found.get("ids", []):
                rec = (found.get("dict") or {}).get(mid) or {}
                add(rec.get("name"), rec.get("email"))
    except Exception:                                       # noqa: BLE001
        logger.warning("responsibles not read for %s", api.get_id(ar), exc_info=True)
    return _unique(out)


def queue_for_issue(ar, entry, report):
    """Queue the e-mail of an issue on the report it issued: called with
    the register entry as it is recorded, in the issue's transaction."""
    if report is None:
        return None
    found = queue_issue(load(report), entry.get("report_id"), sample_recipients(ar),
                        bool(entry.get("interim")), entry.get("issued_at") or "")
    save(report, found)
    return found[-1]


def load(report):
    """The report's deliveries, [] when it has none or they cannot be read."""
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(report).get(DELIVERY_KEY)
    if not raw:
        return []
    try:
        found = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("certificate delivery record: %s", exc)
        return []
    return found if isinstance(found, list) else []


def save(report, deliveries):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(report)[DELIVERY_KEY] = json.dumps(list(deliveries), sort_keys=True)
