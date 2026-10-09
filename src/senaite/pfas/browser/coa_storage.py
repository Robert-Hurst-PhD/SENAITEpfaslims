# -*- coding: utf-8 -*-
"""Store the DESIGNED certificate when one is issued (lab decision
2026-10-04: "the designed PDF replaces it").

Overrides senaite.impress's IPdfReportStorage on the PFAS browser layer (more
specific than impress's registration for any IBrowserRequest). impress builds
its PDF from the HTML preview and hands it to store(); for the PFAS
certificate, when the ISSUED reporting-template revision carries a designed
layout, the PDF is replaced by that layout rendered from the same samples
(browser/coa_document), and the stored HTML by a statement of what the PDF
is, so the ARReport does not hold a draft of another layout beside it.
Everything else -- other templates (the QC Review report publishes through
the same call), certificates without a designed layout -- is stored exactly
as impress stores it.

FAIL CLOSED: if the designed certificate cannot be rendered, store() raises
and nothing is stored: impress's ajax dispatcher answers HTTP 500 with
{"error": str(exc)}, and the publish screen's script throws it and shows it
as the error (senaite.impress 2.6.0 bundle: get_json / saveReports). A
certificate is never issued in a layout the lab did not issue. With several
report groups in one publish, groups stored before the failing one are
already committed by impress's create_report, so a publish can be partial.

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
            u"could not be produced -- %s" % (rev, exc))


def stored_html(rev, uids):
    return (u"<p>This certificate was rendered from the designed layout of reporting "
            u"template revision %s (Document Templates); the PDF is the record.</p>"
            u"<p>Samples: %s</p>" % (rev, u", ".join(api.get_id(api.get_object(u)) for u in uids)))


def designed_qc_review(uids, request=None):
    """(pdf, rev) when a QC Review design is issued (Document Templates),
    else (None, None); raises when it cannot render."""
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
        sections = designed_sections(view, list(uids))
        data = report_documents.qc_review_data(sections)
        # the worksheet's analyst prepares; the first verifier reviews
        from senaite.pfas.browser.coa_attestation import PFASCoAAttestationView
        sig = PFASCoAAttestationView(api.get_portal(), request).resolve_signatories(list(uids))
        first = (sig.get("verified") or [{}])[0]
        people = {"preparer": ((sections.get("identity") or {}).get("analyst") or u"", u""),
                  "reviewer": (first.get("userid") or u"", first.get("date") or u"")}
        return render_report("qc_review", data, design=design, people=people), rev
    except Exception as exc:                                # noqa: BLE001
        logger.exception("designed QC Review failed for %s", uids)
        raise DesignedCertificateError(
            u"Not published: the QC Review design (revision %s) could not be produced -- %s" % (rev, exc))


class PFASPdfReportStorage(PdfReportStorageAdapter):

    def store(self, pdf, html, uids, metadata=None):
        metadata = dict(metadata or {})
        if is_certificate(metadata.get("template")):
            designed, rev = designed_pdf(uids, self.request)
            if designed is not None:
                pdf, html = designed, stored_html(rev, uids)
                metadata["designed_layout_revision"] = rev
        elif (metadata.get("template") or "") == QC_REVIEW_TEMPLATE:
            designed, rev = designed_qc_review(uids, self.request)
            if designed is not None:
                pdf = designed
                html = (u"<p>This QC Review report was rendered from revision %s of its design "
                        u"(Document Templates); the PDF is the record.</p>" % rev)
                metadata["designed_layout_revision"] = rev
        return super(PFASPdfReportStorage, self).store(pdf, html, uids, metadata=metadata)
