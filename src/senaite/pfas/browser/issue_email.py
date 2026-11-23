# -*- coding: utf-8 -*-
"""Issue and e-mail, in one step, from Data Review's certificate card.

The signer, in their own session, presses it once the certificate is
generated and its package built: each sample of the worksheet is
published (core's publish transition, which records the register entry
and binds the signer's signature given on Data Review to the stored PDF,
the certificate signing) and the certificates are e-mailed through the
e-mail form's own send (edd_email.PFASEmailView: the same attachments,
note and delivery record). One e-mail per client, carrying only that
client's certificates, to each sample's contact, CC contacts and CC
addresses (certificate_delivery.sample_recipients).

Before anything is issued every sample is asked what Send asks: its newest
certificate exists and is not issued, its package is built and sealed,
and the pending signature is the signed-in person's and still good
(edd_email.report_refusal, sample_hold, signature_hold). A certificate
holding samples of more than one client is refused. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.browser.issue_email")

NO_CERTIFICATE = "Generate the certificate first: open the publisher"
ISSUED = "Its newest certificate is issued already"
MIXED = "Its certificate holds samples of more than one client"
NO_RECIPIENT = "No recipient with an e-mail address"
NOT_ISSUED = "Not issued: %s"
DONE = "Issued and e-mailed to %s"


def _named(sample_id, why):
    return "%s: %s" % (sample_id, why)


def ready_reports(samples, newest_of, issued, refusal, uid_of, id_of):
    """(the certificates to issue, each once, in sample order, None), or
    ([], "<sample id>: why") for the first sample that may not go yet.
    `newest_of(sample)` is its newest certificate (None when none was
    generated), `issued(report)` whether it is issued, `refusal(report)`
    why Send would refuse it (None when it may go)."""
    out, seen = [], set()
    for sample in samples or []:
        report = newest_of(sample)
        if report is None:
            return [], _named(id_of(sample), NO_CERTIFICATE)
        if uid_of(report) in seen:
            continue
        if issued(report):
            return [], _named(id_of(sample), ISSUED)
        why = refusal(report)
        if why:
            return [], _named(id_of(sample), why)
        seen.add(uid_of(report))
        out.append(report)
    return out, None


def by_client(reports, clients_of):
    """[(client uid, [report])] in first-seen order: one e-mail per
    client. `clients_of(report)` is the client uid of each of its samples;
    a certificate whose samples are not all of one client raises
    ValueError(MIXED)."""
    groups, order = {}, []
    for report in reports or []:
        found = set(clients_of(report))
        if len(found) != 1 or None in found or "" in found:
            raise ValueError(MIXED)
        uid = found.pop()
        if uid not in groups:
            groups[uid] = []
            order.append(uid)
        groups[uid].append(report)
    return [(uid, groups[uid]) for uid in order]


# ── Plone ────────────────────────────────────────────────────────────────────

def _newest(sample):
    from senaite.pfas.browser.controlled_publications import certificate_reports
    found = certificate_reports(sample)
    return found[0] if found else None


def _refusal(userid):
    from senaite.pfas.browser import edd_email

    def refusal(report):
        held = edd_email.sample_hold(report) or edd_email.signature_hold(report, userid)
        return edd_email.report_refusal(report) or (held[1] if held else None)
    return refusal


def _client_uids(report):
    from bika.lims import api
    from senaite.pfas import report_packages
    out = []
    for uid in report_packages._report_samples(report):
        sample = api.get_object_by_uid(uid, default=None)
        out.append(sample.getClientUID() if sample is not None else None)
    return out


def readiness(samples, userid):
    """(reports, why) for the card and the button: the certificates the
    button would issue, or why it may not yet."""
    from bika.lims import api
    from senaite.pfas.browser.controlled_publications import report_issued
    return ready_reports(samples, _newest, report_issued, _refusal(userid), api.get_uid, api.get_id)


def recipients(reports):
    """Whom the e-mail goes to: each certificate's samples' recipients,
    each once."""
    from bika.lims import api
    from senaite.pfas import certificate_delivery as cd
    from senaite.pfas import report_packages
    out = []
    for report in reports:
        for uid in report_packages._report_samples(report):
            sample = api.get_object_by_uid(uid, default=None)
            for r in (cd.sample_recipients(sample) if sample is not None else []):
                if r not in out:
                    out.append(r)
    return out


def _email_view(client, request, reports, to):
    from senaite.pfas.browser.edd_email import PFASEmailView

    class IssueEmail(PFASEmailView):
        """The e-mail form for these certificates and recipients, with no
        files chosen by hand; its messages are collected, not shown."""
        notes = []

        @property
        def reports(self):
            return list(reports)

        @property
        def attachments(self):
            return []

        @property
        def email_recipients_and_responsibles(self):
            return list(to)

        def add_status_message(self, message, level="info"):
            self.notes.append("%s" % message)

    view = IssueEmail(client, request)
    view.notes = []
    return view


def any_issued(samples):
    """True when a sample's newest certificate is issued: a step that
    stopped after it issued says what went, never only that it failed."""
    from senaite.pfas.browser.controlled_publications import report_issued
    for sample in samples or []:
        report = _newest(sample)
        if report is not None and report_issued(report):
            return True
    return False


def issue_and_email(samples, request, userid):
    """Issue the worksheet's certificates and e-mail each client theirs:
    (ok, text). Everything that can refuse is asked of every sample
    before the first is issued."""
    from bika.lims import api
    from senaite.pfas import certificate_delivery as cd
    from senaite.pfas.browser.controlled_publications import report_issued
    reports, why = readiness(samples, userid)
    if why:
        return False, why
    try:
        groups = by_client(reports, _client_uids)
    except ValueError as exc:
        return False, "%s" % exc
    views = []
    for client_uid, group in groups:
        to = recipients(group)
        if not to:
            return False, _named(api.get_id(group[0].getAnalysisRequest()), NO_RECIPIENT)
        view = _email_view(api.get_object_by_uid(client_uid), request, group, to)
        if not view.validate_email_form() or not view.validate_email_size():
            return False, " ".join(view.notes) or NOT_ISSUED % api.get_id(group[0].getAnalysisRequest())
        views.append((view, to))
    said = []
    ok = True
    for view, to in views:
        view.publish_samples()
        left = [api.get_id(r.getAnalysisRequest()) for r in view.reports if not report_issued(r)]
        if left:
            # a publish the guard refused: nothing of it is e-mailed
            ok = False
            said.append(NOT_ISSUED % ", ".join(left))
            continue
        attachments = view.email_attachments
        if view.send_email(to, view.email_subject, view.email_body, attachments=attachments):
            view.write_sendlog()
            said.append(DONE % ", ".join(cd.address(r) for r in to))
        else:
            ok = False
            said.append(cd.SEND_WAITS % (getattr(view, "_wait_reason", None) or cd.NOT_REACHED))
    return ok, " ".join(said)
