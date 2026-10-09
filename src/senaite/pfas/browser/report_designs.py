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


class DesignedReportError(Exception):
    """The issued design could not be rendered; nothing was produced."""


def issued_design(kind):
    return dt.issued_design(dt.load(api.get_portal()), kind)


def designed_pdf(kind, data, design=None, people=None):
    """`people` ({"preparer": (who, date), "reviewer": (who, date)}) adds the
    laboratory and signatory fields (doc_people); a placed
    signature its signer may not give refuses the document."""
    design = design if design is not None else issued_design(kind)
    if design is None:
        return None
    try:
        if people is not None:
            from senaite.pfas.browser.doc_people import signed_fields
            data = dict(data)
            data.update(signed_fields(design, people))
        return pdf_renderer.render_documents([dt.compile_document(kind, design, data)])
    except Exception as exc:                                # noqa: BLE001
        logger.exception("designed %s failed", kind)
        raise DesignedReportError(u"The issued %s design could not be produced: %s"
                                  % (dt.KINDS[kind]["title"], exc))
