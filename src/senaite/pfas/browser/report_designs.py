# -*- coding: utf-8 -*-
"""Render a designed report from its issued design.

    designed_pdf(kind, data) -> PDF bytes, or None when no design is issued

The extraction log, the QC Review report and the settings report call this
with the data report_documents flattened from their own assembly. None: the
report prints as it always has. Once a design is issued it is the report: a
failure raises DesignedReportError and the caller refuses, never falling back
to the old layout. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api

from senaite.pfas import document_templates as dt
from senaite.pfas import pdf_renderer

logger = logging.getLogger("senaite.pfas.report_designs")


# the document control field of a controlled record (report_documents)
_CONTROL = "control"


class DesignedReportError(Exception):
    """The issued design could not be rendered; nothing was produced."""


def issued_design(kind):
    return dt.issued_design(dt.load(api.get_portal()), kind)


def control_text(kind, printed_by=None):
    """The document control block of a designed record: the document (its
    design) with the revision it is printed from and that revision's issue
    date, and under it who printed it and when, and that a printed copy is
    uncontrolled. The pieces are print_doc's, as on every controlled print."""
    from senaite.pfas import print_doc
    portal = api.get_portal()
    entry = dt.load(portal).get(dt.KINDS[kind].get("single")) or {}
    cur = dt.current(entry) or {}
    line = print_doc.doc_line(dt.KINDS[kind]["title"], cur.get("rev"))
    issued = cur.get("issued_at") or u""
    if issued:
        line += u" \u00b7 Issued %s" % (print_doc.lab_or(issued, issued, u"%Y-%m-%d") or u"")[:10]
    who = printed_by if printed_by is not None else print_doc.current_user_label(portal)
    printed = u"Printed %s%s \u00b7 %s" % (print_doc.now_label(), (u" by %s" % who) if who else u"",
                                           print_doc.UNCONTROLLED)
    out = u"%s\n%s" % (line, printed)
    if dt.KINDS[kind].get("zone_in_control"):
        # a custody document names its time zone in the control block
        zone = print_doc.times_line(printed)
        if zone:
            out += u"\n%s" % zone
    return out


def designed_pdf(kind, data, design=None, people=None, ledger_fields=None, mono=False):
    """`people` ({"preparer": (who, date), "reviewer": (who, date)}) adds the
    laboratory and signatory fields (doc_people); a placed
    signature its signer may not give refuses the document.
    `ledger_fields` ({"<role>_signature": data URI, "<role>_name": ...,
    "<role>_credentials": ...}, report_documents.signature_images and
    signer_fields): what the signature ledger says of the roles it signed;
    it replaces the person's image, name and credentials as they are today.
    `mono`: the document in black and white, for a client who takes its
    certificates so (document_templates.monochrome)."""
    design = design if design is not None else issued_design(kind)
    if design is None:
        return None
    try:
        if _CONTROL in dt.field_keys(kind) and not (data or {}).get(_CONTROL):
            # a controlled record names its design revision and who printed it
            data = dict(data or {}, **{_CONTROL: control_text(kind)})
        if people is not None:
            from senaite.pfas.browser.doc_people import signed_fields
            ledger_fields = ledger_fields or {}
            data = dict(data)
            data.update(signed_fields(design, people, ledger_roles=[
                k[:-len("_signature")] for k in ledger_fields if k.endswith("_signature")]))
            # the signer as signed, never as on file today
            data.update(ledger_fields)
        template, inputs = dt.compile_document(kind, design, data)
        return pdf_renderer.render_documents([dt.monochrome_document(kind, template, inputs) if mono
                                                else (template, inputs)])
    except Exception as exc:                                # noqa: BLE001
        logger.exception("designed %s failed", kind)
        raise DesignedReportError(u"The issued %s design could not be produced: %s"
                                  % (dt.KINDS[kind]["title"], exc))
