# -*- coding: utf-8 -*-
"""Batch logbooks as designable documents.

    register_all(portal)  -- a document kind per active logbook definition
                             (document_templates.KINDS["logbook:<slug>"]),
                             rebuilt from the definitions on each call, so a
                             new revision's fields are what a design is
                             checked against
    designed_logbook_pdf(portal, batch, slug, schema, entry, header)
                          -- the PDF, None when no design is issued; raises
                             when the issued design no longer fits the
                             definition or cannot render

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

from senaite.pfas import document_templates as dt
from senaite.pfas import logbook_documents as ld
from senaite.pfas import report_documents as rd

logger = logging.getLogger("senaite.pfas.logbook_designs")


class LogbookDesignError(Exception):
    """The issued logbook design cannot print; the message says why."""


def register_all(portal):
    from senaite.pfas.browser.prep_logbooks import _list
    from senaite.pfas.logbook_store import form_code
    for kind in [k for k in dt.KINDS if k.startswith(ld.PREFIX)]:
        del dt.KINDS[kind]
    seen = set()
    for d in _list(portal, status_filter="active"):
        slug = d.get("logbook_slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        try:
            schema = json.loads(d.get("field_schema_json") or "[]")
        except (TypeError, ValueError):
            schema = []
        spec = ld.kind_spec(slug, d.get("title"), form_code(portal, slug),
                            d.get("revision"), schema, starter=rd.starter)
        spec["sizes"] = dt.PAGE_SIZES
        dt.KINDS[ld.kind_id(slug)] = spec


def designed_logbook_pdf(portal, slug, schema, entry, header):
    register_all(portal)
    kind = ld.kind_id(slug)
    if kind not in dt.KINDS:
        return None
    design = dt.issued_design(dt.load(portal), kind)
    if design is None:
        return None
    problems = dt.validate(kind, design)
    if problems:
        raise LogbookDesignError(
            u"The issued design of this logbook no longer fits its definition (revision %s): %s "
            u"Update the design in Document Templates and issue it again."
            % (dt.KINDS[kind].get("definition_revision"), u" ".join(problems)))
    from senaite.pfas import pdf_renderer
    try:
        data = ld.data(schema, entry, header)
        # the logbook's own sign-off fields name its preparer and reviewer;
        # a signature resolves only for a user id
        from senaite.pfas.browser.doc_people import signed_fields
        entry = entry or {}
        data.update(signed_fields(design, {
            "preparer": (entry.get("prepared_by") or entry.get("analyst"), entry.get("prepared_date") or u""),
            "reviewer": (entry.get("reviewed_by"), entry.get("reviewed_date") or u"")}))
        return pdf_renderer.render_documents([dt.compile_document(kind, design, data)])
    except Exception as exc:                                # noqa: BLE001
        logger.exception("designed logbook %s failed", slug)
        raise LogbookDesignError(u"The issued design of this logbook could not be produced: %s" % exc)
