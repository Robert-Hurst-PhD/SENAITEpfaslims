# -*- coding: utf-8 -*-
"""
D63 step D — attach the state EDD CSV to the report (COA) email.

Overrides senaite.core's @@email view
(bika.lims.browser.publish.emailview.EmailView) on the PFAS browser layer,
extending `email_attachments` to append one EDD CSV per batch represented in the
emailed reports.  So a single email carries the report PDF(s) + the state EDD.

Not a core fork: a more-specific-layer (ISenaitePFASLayer) subclass that calls
super().  If senaite.core changes the `email_attachments` property contract,
revisit here.

Delivery gate: the client's per-client EDD config must have `edd_enabled`
(the explicit "emit a state EDD for this client" opt-in) — otherwise ordinary
commercial clients would receive an EDD they never need.  The STATE is the
client's `edd_profile`; the METHOD comes from the batch. The EDD holds only
that client's samples of the batch: another client's are left out by their
ids in the builder itself (edd_builder.client_samples).

Send gate: a certificate goes out only with its package built. A package
still building, one that failed, or a tier that needs a package with no
package record on the certificate refuses Send, naming the sample and the
reason; a ready package, a tier of the certificate alone, or a report that
is not a certificate (a QC Review report), sends. A sample without the
sender's own signature from Data Review refuses Send with the publish
guard's reason (controlled_publications.signature_refusal).

Delivery record: each e-mail that attached a batch's EDD is recorded on
that batch's EDD record (edd_publish.record_delivery): the recipients it
reached, when, the file's name and the checksum of the bytes attached. An
EDD that goes with an interim certificate is marked interim, in its name
and on its record. Each attempt to e-mail a certificate is recorded on the
issued report's delivery (certificate_delivery): whom it reached, whom it
did not and why, and the files it carried. With no mail server set up
nothing is tried and the delivery waits: Send says so, and a Manager sends
it again from Certificates (@@pfas-delivery-send, this view's send).

No seal note and no seal certificate go to a client: proving an issued
PDF unaltered is the laboratory's own audit. An e-mail carrying an interim
EDD ends with a line saying so (certificate_delivery.client_note).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from bika.lims import api
from bika.lims.api import mail as mailapi
from bika.lims.browser.publish.emailview import EmailView
from ZODB.POSException import ConflictError

from senaite.pfas import report_packages
from senaite.pfas import report_tiers
from senaite.pfas.browser.report_packages_view import error_text
from senaite.pfas.report_packages import NOT_IN_CATALOGUE

logger = logging.getLogger("senaite.pfas.browser.edd_email")

STILL_BUILDING = u"The certificate is still building; try again in a minute"
PACKAGE_FAILED = (u"The certificate failed: %s. Retry the certificate from Certificates, "
                  u"or publish at a lower tier.")
NO_PACKAGE_RECORD = u"No certificate record: generate the certificate again"
UNKNOWN_STATE = u"The certificate is in no state it can be sent from: %s"
PACKAGE_UNREADABLE = u"The certificate cannot be read: %s"
HELD_BY = (u"Certificate %s, not yet issued, holds publishing: retry or delete it under Awaiting issue "
           u"on Certificates. %s")


def package_refusal(rec, tier, tier_id):
    """Why a report may not be sent yet, or None. `rec` is the report's
    package record; `tier` (None when the issued catalogue does not hold
    `tier_id`) is its primary sample's tier, read only when there is no
    record. Only a ready package, or no record at a tier of the
    certificate alone, sends."""
    if rec is None:
        if tier is None:
            return NOT_IN_CATALOGUE % (tier_id or u"none")
        if report_tiers.needs_package(tier):
            return NO_PACKAGE_RECORD
        return None
    state = rec.get("state") or u""
    if state == "ready":
        return None
    if state == "pending":
        return STILL_BUILDING
    if state == "failed":
        reason = (rec.get("reason") or u"").strip().rstrip(u".") or u"no reason given"
        return PACKAGE_FAILED % reason
    return UNKNOWN_STATE % state


def report_refusal(report):
    """Why this report may not be sent or published yet, or None: its
    package record, else its primary sample's tier. Only a certificate
    carries a package: any other report of the sample sends. Send and the
    publish guard (guards.ReportPackageGuard) both ask this."""
    rec = report_packages.record(report)
    tier = tier_id = None
    if rec is None:
        if not report_packages.is_certificate_report(report):
            return None
        tier, tier_id, _catalogue, _rev = report_tiers.resolve(report.getAnalysisRequest(), api.get_portal())
    return package_refusal(rec, tier, tier_id)


def sample_hold(report):
    """(sample id, why) when a sample of this report may not be published:
    the publish guard's own question (guards.package_hold, the sample's
    newest certificate) for each of its samples, so Send never passes what
    the publish transition after it would refuse. A hold by another
    certificate than this one names it. None when every sample may be
    published."""
    from senaite.pfas.browser.controlled_publications import certificate_reports, report_issued
    from senaite.pfas.browser.guards import package_hold
    for uid in report_packages._report_samples(report):
        sample = api.get_object_by_uid(uid, default=None)
        if sample is None:
            continue
        held = package_hold(certificate_reports(sample), report_issued, report_refusal)
        if held:
            other, why = held
            if api.get_uid(other) != api.get_uid(report):
                why = HELD_BY % (api.get_id(other), why)
            return api.get_id(sample), why
    return None


def signature_hold(report, userid):
    """(sample id, why) when a sample of this report may not be published
    by userid for its signature: the publish guard's own question
    (controlled_publications.signature_refusal: the pending signature,
    whether the sender may still sign it, the certificate's seal and its
    mark), asked of each sample before any email is sent. None when every
    sample is signed."""
    from senaite.pfas.browser.controlled_publications import signature_refusal
    for uid in report_packages._report_samples(report):
        sample = api.get_object_by_uid(uid, default=None)
        if sample is None:
            continue
        why = signature_refusal(sample, userid)
        if why:
            return api.get_id(sample), why
    return None


class PFASEmailView(EmailView):
    """Core @@email view + the package gate on Send + state EDD CSV
    attachment(s)."""

    def validate_email_form(self):
        """Core's checks first, then each report's package, then what the
        publish guard asks of each of its samples: the first that may not go
        out refuses Send with its reason, before any email is sent. A package
        that cannot be read refuses too: a report never goes out without the
        package its tier needs."""
        if not super(PFASEmailView, self).validate_email_form():
            return False
        from senaite.pfas.browser.controlled_publications import _current_userid
        userid = _current_userid()
        for report in self.reports:
            named = None
            try:
                why = self._package_refusal(report)
                if not why:
                    held = sample_hold(report) or signature_hold(report, userid)
                    if held:
                        named, why = held
            except ConflictError:
                raise                                       # Zope retries the request
            except Exception as exc:                        # noqa: BLE001
                logger.exception("report package check failed for %s", api.get_id(report))
                why = PACKAGE_UNREADABLE % error_text(exc)
            if why:
                self.add_status_message(u"{0}: {1}".format(named or self._named(report), why), "warning")
                return False
        return True

    def publish(self, sample):
        """Core's publish of one sample (prepublish, publish or republish by
        its state). An interim its signer issues goes on their Interim
        release right, with core's Publish Results granted for that one
        transition on that sample (interim_release.for_sample); every other
        publish needs Publish Results as before."""
        from senaite.pfas.browser import interim_release
        with interim_release.for_sample(sample):
            return super(PFASEmailView, self).publish(sample)

    def _package_refusal(self, report):
        return report_refusal(report)

    def _named(self, report):
        """The report as the person knows it: its primary sample's id."""
        try:
            return api.get_id(report.getAnalysisRequest())
        except Exception:                                   # noqa: BLE001
            return api.get_id(report)

    @property
    def email_attachments(self):
        # Core attachments first (report PDFs + user-selected attachments).
        attachments = super(PFASEmailView, self).email_attachments
        self._files = self._report_files()
        try:
            attachments.extend(self._edd_attachments())
        except Exception as exc:
            # Never let EDD assembly break the report email itself.
            logger.error("EDD attach failed; report email still sent: %s", exc)
        return attachments

    # ── the certificate's delivery and its note ─────────────────────────────

    def _report_files(self):
        """The name and SHA-256 of each report PDF the e-mail attaches."""
        import hashlib
        out = []
        for report in self.reports:
            pdf = self.get_pdf(report)
            data = getattr(pdf, "data", None) if pdf is not None else None
            if data:
                out.append({"name": self.get_report_filename(report), "sha256": hashlib.sha256(data).hexdigest()})
        return out

    def _interim(self):
        """True when a report e-mailed was generated as an interim
        certificate (its issue mark): its EDD goes marked interim."""
        from senaite.pfas.browser.controlled_publications import issue_mark
        for report in self.reports:
            try:
                if (issue_mark(report) or {}).get("interim"):
                    return True
            except Exception:                               # noqa: BLE001
                continue
        return False

    def delivery_note(self):
        """The line the e-mail ends with: that its EDD is interim, when it
        carries one (certificate_delivery.client_note); u"" otherwise."""
        from senaite.pfas import certificate_delivery as cd
        sent = getattr(self, "_edd_sent", None) or {}
        return cd.client_note(any(e.get("interim") for e in sent.values()), superseded=self._superseded())

    def _superseded(self):
        """The interim certificates the e-mailed certificates supersede
        ([{"report_id", "reason"}]), from their register entries."""
        from senaite.pfas.browser.controlled_publications import get_publication_log
        out = []
        for report in self.reports:
            try:
                uid = api.get_uid(report)
                for e in get_publication_log(report.getAnalysisRequest()):
                    if e.get("report_uid") == uid:
                        out.extend(e.get("supersedes_interim") or [])
            except Exception:                               # noqa: BLE001
                continue
        return out

    def mail_host_name(self):
        """The mail server the site sends through, as the reason names it."""
        try:
            return api.safe_unicode(getattr(api.get_tool("MailHost"), "smtp_host", u"") or u"")
        except Exception:                                   # noqa: BLE001
            return u""

    def mail_ready(self):
        from senaite.pfas import certificate_delivery as cd
        try:
            return cd.smtp_ready(api.get_tool("MailHost"))
        except Exception:                                   # noqa: BLE001
            return False

    def form_action_send(self):
        """Core's Send after the issue: every report's delivery is recorded,
        and when the e-mail could not go the sender reads that it waits and
        where to send it again, never only that it failed."""
        from senaite.pfas import certificate_delivery as cd
        success = self.send_email(self.email_recipients_and_responsibles, self.email_subject,
                                  self.email_body, attachments=self.email_attachments)
        if success:
            self.write_sendlog()
            self.add_status_message(u"Message sent to {}".format(
                u", ".join(self.email_recipients_and_responsibles)), "info")
        else:
            self.add_status_message(cd.SEND_WAITS % (getattr(self, "_wait_reason", None) or cd.NOT_REACHED),
                                    "warning")
        self.request.response.redirect(self.exit_url)

    def _record_certificate_deliveries(self, reached, failed, reason, recipients):
        """Record this attempt on the newest delivery of each certificate
        e-mailed; a resend keeps the recipients queued. A record that cannot
        be written is logged and never fails the e-mail."""
        from senaite.pfas import certificate_delivery as cd
        from senaite.pfas.browser.controlled_publications import _current_userid
        at = report_packages.stamp()
        for report in self.reports:
            try:
                if not report_packages.is_certificate_report(report):
                    continue
                found = cd.load(report)
                if not found or not cd.is_waiting(found[-1]):
                    found = found + [cd.new_delivery(u"", [], self._interim(), at)]
                found[-1] = cd.record_attempt(found[-1], reached, failed, reason, at, _current_userid(),
                                              getattr(self, "_files", None) or [],
                                              recipients=None if getattr(self, "resend", False) else recipients)
                cd.save(report, found)
            except ConflictError:
                raise
            except Exception as exc:                        # noqa: BLE001
                logger.error("certificate delivery not recorded for %s: %s", api.get_id(report), exc)

    def _edd_attachments(self):
        """One EDD CSV per distinct batch across the emailed reports, for
        clients that have opted into state EDD delivery. A report can span more
        than one batch (primary + contained samples), so every sample is
        considered; batches are de-duplicated by UID."""
        out = []
        seen_batches = set()
        # the EDDs this build attaches, by batch uid; Send records them
        self._edd_sent = {}
        for batch, client in self._batches_and_clients():
            buid = api.get_uid(batch)
            if buid in seen_batches:
                continue
            seen_batches.add(buid)

            if not self._edd_enabled(client):
                continue

            att = self._build_edd_attachment(batch, client)
            if att is not None:
                out.append(att)
        return out

    # ── helpers ──────────────────────────────────────────────────────────────

    def _batches_and_clients(self):
        """Yield (batch, client) for every sample across the emailed reports —
        the primary sample and any contained samples of each report."""
        for report in self.reports:
            samples = []
            try:
                primary = report.getAnalysisRequest()
                if primary is not None:
                    samples.append(primary)
            except Exception:
                pass
            try:
                samples.extend(report.getContainedAnalysisRequests() or [])
            except Exception:
                pass
            for ar in samples:
                batch = None
                client = None
                try:
                    batch = ar.getBatch()
                except Exception:
                    pass
                if batch is None:
                    continue
                try:
                    client = ar.getClient()
                except Exception:
                    pass
                if client is None:
                    continue
                yield (batch, client)

    def _edd_enabled(self, client):
        try:
            from senaite.pfas.edd_store import is_edd_enabled
            return bool(is_edd_enabled(client))
        except Exception:
            return False

    def _build_edd_attachment(self, batch, client):
        """Generate the state EDD for a batch and return a mail attachment, or
        None (empty CSV, or BLOCKING validation errors → do not attach a bad
        file; the batch-stored EDD + export view still surface the errors)."""
        from senaite.pfas.edd_builder import EDDBuilder
        # the builder holds only this client's samples of the batch: another
        # client's are left out by their ids (EDDBuilder.batch_samples)
        portal = api.get_portal()
        builder = EDDBuilder(portal)
        csv_str, errors, filename = builder.generate_from_batch(
            batch, client_obj=client)

        if not csv_str:
            return None

        blocking = [e for e in errors if e.get("type") == "BLOCKING"]
        if blocking:
            logger.warning(
                "EDD not attached to report email for batch %s — %d blocking "
                "error(s); resolve in EDD settings, then resend.",
                api.get_id(batch), len(blocking))
            return None

        csv_bytes = csv_str.encode("utf-8") if isinstance(csv_str, unicode) \
            else csv_str
        # an EDD going with an interim certificate is marked interim in its
        # name; its columns are its format's and never change. EDDs are
        # neither signed nor sealed.
        interim = self._interim()
        if interim:
            from senaite.pfas.certificate_delivery import interim_filename
            filename = interim_filename(filename)
        self._note_edd(batch, api.get_uid(batch), filename, csv_bytes, interim=interim)
        return mailapi.to_email_attachment(csv_bytes, filename)

    # ── the delivery record ──────────────────────────────────────────────────

    def _note_edd(self, batch, uid, filename, data, interim=False):
        """Remember an EDD this e-mail attaches: the batch, the file's name
        and the SHA-256 of its exact bytes, and whether it is interim."""
        import hashlib
        sent = getattr(self, "_edd_sent", None)
        if sent is None:
            sent = self._edd_sent = {}
        sent[uid] = {"batch": batch, "filename": filename, "data": data,
                     "sha256": hashlib.sha256(data).hexdigest(), "interim": bool(interim)}
        files = getattr(self, "_files", None)
        if files is not None:
            files.append({"name": filename, "sha256": sent[uid]["sha256"]})

    def send_email(self, recipients, subject, body, attachments=None):
        """Core's send, one recipient at a time as core sends it, so the
        EDDs attached are recorded as delivered to the recipients reached
        and no others, and each certificate's delivery records whom it
        reached. The body ends with the delivery note. With no mail server
        nothing is tried: the deliveries wait with that reason. True only
        when every recipient was reached."""
        from senaite.pfas import certificate_delivery as cd
        recipients = list(recipients or [])
        if not self.mail_ready():
            self._wait_reason = cd.NO_MAIL_SERVER
            # nothing went: the attempt names no file
            self._files = []
            self._record_certificate_deliveries([], [], cd.NO_MAIL_SERVER, recipients)
            return False
        body = cd.with_note(body, self.delivery_note())
        reached, failed = [], []
        for recipient in recipients:
            if super(PFASEmailView, self).send_email([recipient], subject, body, attachments=attachments):
                reached.append(recipient)
            else:
                failed.append(recipient)
        if reached:
            self._record_edd_deliveries(reached)
        self._wait_reason = (cd.server_refused(self.mail_host_name()) if failed
                             else (cd.NO_RECIPIENT if not recipients else None))
        self._record_certificate_deliveries(reached, failed, self._wait_reason or u"", recipients)
        return bool(recipients) and not failed

    def _record_edd_deliveries(self, reached):
        """Append a delivery to each attached EDD's batch. A record that
        cannot be written is logged and never fails the e-mail."""
        from datetime import datetime
        from senaite.pfas.edd_store import delivery_entry
        from senaite.pfas.browser.edd_publish import record_delivery
        sent_at = datetime.utcnow().replace(microsecond=0).isoformat()
        for uid, edd in sorted((getattr(self, "_edd_sent", None) or {}).items()):
            try:
                record_delivery(edd["batch"], delivery_entry(reached, sent_at, edd["filename"], edd["data"],
                                                             interim=bool(edd.get("interim"))))
            except Exception as exc:                        # noqa: BLE001
                logger.error("EDD delivery not recorded for %s: %s", uid, exc)
