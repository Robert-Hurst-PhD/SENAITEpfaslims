# -*- coding: utf-8 -*-
"""Store the DESIGNED certificate; refuse a certificate when none is issued.

Overrides senaite.impress's IPdfReportStorage on the PFAS browser layer (more
specific than impress's registration for any IBrowserRequest). impress builds
its PDF from the HTML preview and hands it to store(); for the PFAS
certificate, when the ISSUED reporting-template revision carries a designed
layout, the PDF is replaced by that layout rendered from the same samples
(browser/coa_document), and the stored HTML by a statement of what the PDF
is, so the ARReport does not hold a draft of another layout beside it.
When the issued revision carries no designed layout, a certificate is
refused (the reason is "Issue a certificate layout in Reporting Setup
first.") and nothing is stored: the standard certificate impress built is
no fallback. A sample's report in any other impress template (Default,
MultiDefault) is refused the same way: only the PFAS certificate is a
certificate. The QC Review report (published through the same call) is
stored as impress made it, or as its issued design, and a report that is
not a sample's is stored as impress stores it. A certificate's report
package is prepared before it is stored (report_packages.prepare: a sample
whose report tier is not in the issued catalogue refuses it) and attached to
each report stored (report_packages.attach); a certificate with no package
has its seal queued instead (report_packages.queue_seal), and publishing
waits for it. Every stored certificate records whether it was generated
interim or final (controlled_publications.record_issue_mark).

FAIL CLOSED: if the designed certificate cannot be rendered, store() raises
and nothing is stored: impress's ajax dispatcher answers HTTP 500 with
{"error": str(exc)}, and the publish screen's script throws it and shows it
as the error (senaite.impress 2.6.0 bundle: get_json / saveReports). A
certificate is never issued in a layout the lab did not issue. With several
report groups in one publish, groups stored before the failing one are
already committed by impress's create_report, so a publish can be partial.
Each certificate's mark and package or seal are committed right after
impress commits the certificate: impress syncs the connection before its
next report, which would discard them. A mark or seal that cannot be
written is aborted whole and the error raised; the certificate impress
committed is then unsealed and refused at publish.

Before anything is made, store() refuses when the user may not add a
report to every object impress would store one in (NO_ADD): impress
creates the report under a temporary id and renames it, the rename asks
that permission, and a refusal there would leave a half-made report that
the publisher commits (impress answers the error, it does not raise it).
A create that fails for any other reason aborts the transaction for the
same cause. An interim certificate its signer generates is stored on their
Interim release right (interim_release.for_generate), the preflight asked
under that grant.

Upgrade fragility: depends on impress calling
storage.store(pdf, html, uids, metadata) with metadata["template"] -- true in
senaite.impress 2.6.0 ajax.py ajax_save_reports. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from senaite.impress.storage import PdfReportStorageAdapter

logger = logging.getLogger("senaite.pfas.coa_storage")

CERTIFICATE_TEMPLATE = "senaite.pfas:CertificateOfAnalysis.pt"
QC_REVIEW_TEMPLATE = "senaite.pfas:QCReviewReport.pt"


def is_certificate(template):
    return (template or "") == CERTIFICATE_TEMPLATE


# a sample's report in any other impress template (Default, MultiDefault):
# refused, nothing stored, so there is nothing for the email form to send
OTHER_TEMPLATE = (u"Not published: certificates are printed only from the lab's issued certificate "
                  u"layout, not from %s.")


def _sample_report(uids):
    """True when any of `uids` is a sample: a report that is a certificate.
    An object that cannot be read counts as one (fail closed)."""
    for uid in uids or ():
        try:
            if api.get_portal_type(api.get_object(uid)) == "AnalysisRequest":
                return True
        except Exception:                                   # noqa: BLE001
            return True
    return False


class DesignedCertificateError(Exception):
    """The issued designed certificate could not be produced; nothing stored.

    impress answers the publish screen with str(exc) (HTTP 500, shown there as
    the error). Under Python 2 str() of a unicode message with a non-ASCII
    character would itself fail, so the message is kept as UTF-8 bytes."""

    def __init__(self, message):
        if not isinstance(message, bytes) and bytes is str:     # Python 2
            message = message.encode("utf-8")
        Exception.__init__(self, message)


def designed_pdf(uids, request=None):
    """(pdf, rev) when the issued revision carries a designed layout, else
    (None, None). Raises DesignedCertificateError when it cannot render."""
    from senaite.pfas import report_templates as rt
    snap, rev = rt.issued_snapshot(api.get_portal())
    layout = rt.designed_layout(snap)
    if layout is None:
        return None, None
    from senaite.pfas.browser import coa_document
    try:
        return coa_document.render(list(uids), layout, request=request), rev
    except Exception as exc:                                # noqa: BLE001
        logger.exception("designed certificate failed for %s", uids)
        raise DesignedCertificateError(
            u"Not published: the designed certificate (reporting template revision %s) "
            u"could not be produced: %s" % (rev, exc))


def stored_html(rev, uids):
    return (u"<p>This certificate was rendered from the designed layout of reporting "
            u"template revision %s (Document Templates); the PDF is the record.</p>"
            u"<p>Samples: %s</p>" % (rev, u", ".join(api.get_id(api.get_object(u)) for u in uids)))


def designed_qc_review(uids, request=None, sections=None, names=None, mono=False):
    """(pdf, rev) when a QC Review design is issued (Document Templates),
    else (None, None); raises when it cannot render. `sections` (section
    keys of report_documents.QC_SECTION_FIELDS), when given, prints those
    sections only, under the header every part prints: a report package's
    QC Review part. `names` ({client sample id: lab sample id},
    sample_names.lab_names), given for a package, prints every injection by
    the lab sample id. `mono` prints it in black and white (a package for a
    client who takes its certificates so)."""
    from senaite.pfas import document_templates as dt
    store = dt.load(api.get_portal())
    design = dt.issued_design(store, "qc_review")
    if design is None:
        return None, None
    rev = dt.current(store[dt.KINDS["qc_review"]["single"]])["rev"]
    try:
        from senaite.pfas import report_documents
        from senaite.pfas.browser.qc_review_report import PFASQCReviewReportView, designed_sections
        from senaite.pfas.browser.report_designs import designed_pdf as render_report
        view = PFASQCReviewReportView(api.get_object(uids[0]), request)
        found = designed_sections(view, list(uids))
        from senaite.pfas import sample_names
        found = sample_names.qc_review_sections(found, names)
        data = report_documents.qc_review_data(found)
        if sections is not None:
            # the part prints its sections only: their fields leave the data
            # and the design, headings and labels with them
            data = report_documents.qc_review_subset(data, sections)
            design = dt.subset_design(design, report_documents.qc_review_omitted(sections))
        # the worksheet's analyst prepares; the first verifier reviews
        from senaite.pfas.browser.coa_attestation import PFASCoAAttestationView
        sig = PFASCoAAttestationView(api.get_portal(), request).resolve_signatories(list(uids))
        first = (sig.get("verified") or [{}])[0]
        people = {"preparer": ((found.get("identity") or {}).get("analyst") or u"", u""),
                  "reviewer": (first.get("userid") or u"", first.get("date") or u"")}
        return render_report("qc_review", data, design=design, people=people, mono=mono), rev
    except Exception as exc:                                # noqa: BLE001
        logger.exception("designed QC Review failed for %s", uids)
        raise DesignedCertificateError(
            u"Not published: the QC Review design (revision %s) could not be produced: %s" % (rev, exc))


# the refusal before anything is made: impress would create the report and
# fail at its rename, and the half-made report would be committed
NO_ADD = u"Not generated: you may not add a report to %s."


def add_refusal(containers, can_add, name):
    """Why no report may be stored, or None: the first container the user
    may not add a report to, by name."""
    for container in containers or ():
        if not can_add(container):
            return NO_ADD % api.safe_unicode(name(container))
    return None


class PFASPdfReportStorage(PdfReportStorageAdapter):

    def containers(self, uids):
        """The objects impress creates the reports in, by its own rule: each
        object of the report, or only the primary one when multi-reports are
        not stored individually."""
        objs = [api.get_object_by_uid(uid) for uid in uids]
        if objs and not self.store_multireports_individually():
            objs = [self.get_primary_report(objs)]
        return objs

    def store(self, pdf, html, uids, metadata=None):
        """Refuse before anything is made when the user may not add a report
        to every container; an interim certificate its signer generates is
        stored on their Interim release right (interim_release.for_generate)."""
        from AccessControl.SecurityManagement import getSecurityManager
        from senaite.pfas.browser import interim_release
        metadata = dict(metadata or {})
        containers = self.containers(uids)
        with interim_release.for_generate(containers if is_certificate(metadata.get("template")) else []):
            why = add_refusal(containers, lambda c: getSecurityManager().checkPermission(
                interim_release.ADD_PERMISSION, c), api.get_id)
            if why:
                raise DesignedCertificateError(why)
            return self._store(pdf, html, uids, metadata)

    def create_report(self, parent, pdf, html, uids, metadata):
        """impress's create; a report half made (created, not renamed) is
        never committed: impress answers the error and the publisher would
        commit what the request holds, so the transaction is aborted."""
        try:
            return super(PFASPdfReportStorage, self).create_report(parent, pdf, html, uids, metadata)
        except Exception:
            import transaction
            transaction.abort()
            raise

    def _store(self, pdf, html, uids, metadata):
        plan = None
        if is_certificate(metadata.get("template")):
            # the report package is prepared before anything is stored:
            # impress commits the stored report, so a refusal (a tier the
            # issued catalogue does not hold) after it would come too late
            from senaite.pfas import report_packages
            plan = report_packages.prepare(uids, self.request)
            designed, rev = designed_pdf(uids, self.request)
            if designed is None:
                # no certificate layout issued: refused, nothing stored (the
                # standard certificate is no fallback)
                from senaite.pfas.report_templates import LAYOUT_NEEDED
                raise DesignedCertificateError(LAYOUT_NEEDED)
            pdf, html = designed, stored_html(rev, uids)
            metadata["designed_layout_revision"] = rev
        elif (metadata.get("template") or "") != QC_REVIEW_TEMPLATE and _sample_report(uids):
            raise DesignedCertificateError(OTHER_TEMPLATE % (metadata.get("template") or u"no template"))
        elif (metadata.get("template") or "") == QC_REVIEW_TEMPLATE:
            designed, rev = designed_qc_review(uids, self.request)
            if designed is not None:
                pdf = designed
                html = (u"<p>This QC Review report was rendered from revision %s of its design "
                        u"(Document Templates); the PDF is the record.</p>" % rev)
                metadata["designed_layout_revision"] = rev
        reports = super(PFASPdfReportStorage, self).store(pdf, html, uids, metadata=metadata)
        if is_certificate(metadata.get("template")):
            import transaction
            from senaite.pfas.browser.controlled_publications import record_issue_mark
            try:
                for report in reports:
                    # the mark the certificate prints: a signature of the
                    # other kind is refused at publish
                    record_issue_mark(report)
                    if plan is not None:
                        report_packages.attach(report, plan)
                    else:
                        # no package: the certificate is sealed alone, and
                        # publishing waits for the seal
                        report_packages.queue_seal(report)
                # impress commits each report it stores and syncs the
                # connection before the next, which discards whatever is not
                # committed: the mark, the package or seal record and their
                # job files are committed here, as impress commits the
                # report, so every certificate of one Save keeps them
                transaction.commit()
            except Exception:
                # nothing of the mark or the seal is kept half written: the
                # stored certificate, unsealed, is refused at publish
                transaction.abort()
                raise
        return reports
