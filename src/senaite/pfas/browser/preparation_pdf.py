# -*- coding: utf-8 -*-
"""
The preparation record's print (@@pfas-preparation-pdf?entry=<id>).

A preparation record (prep_entries) printed from the issued "Preparation
record" design (Document Templates). With no issued design nothing is
printed: the page answers 409 with the reason, and never falls back to
another layout. The Signatures table and the signature images come from the
signature ledger, read against the record's content as it is now; a design
without the table prints without it. Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.Five.browser import BrowserView

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.report_designs import DesignedReportError
from senaite.pfas.browser.view_helpers import send_pdf

logger = logging.getLogger("senaite.pfas.browser.preparation_pdf")

NO_PREPARATION_DESIGN = u"No issued design for the Preparation record: issue one in Document Templates"


class PFASPreparationPDFView(BrowserView):
    """One preparation record, from its issued design."""

    def _inputs(self, portal, entry):
        """(the record's lots by uid, its parents with their effective
        expiry, the recipe revision). A parent that cannot be resolved
        prints no expiry; the reason goes to the log."""
        from senaite.pfas import recipes
        from senaite.pfas.browser import prepared_standards as ps
        lots = {}
        for uid in entry.get("lots") or []:
            lot = ps.lot_dict(portal, uid)
            if lot is not None:
                lots[uid] = lot
        # each parent as it was in force on the prep date: an extension
        # approved later does not reach back (lot_extension)
        parents = ps.parents_in_force(portal, entry.get("parents"), as_of=entry.get("prepared_date") or None)
        for p in parents:
            if not p["expiry"]:
                logger.warning("preparation %s: no expiry for parent %s", entry.get("id"), p.get("lot"))
        pin = entry.get("recipe") or {}
        rev = next((r for r in recipes.revisions(recipes.load(portal), pin.get("id"))
                    if r.get("revision") == pin.get("revision")), None)
        return lots, parents, rev

    @staticmethod
    def _signatures(entry):
        """(the Signatures table's rows, the fields a signed role prints
        from the ledger: its kept image, name and credentials as at
        signing) of the record, read against its content now."""
        from senaite.pfas import prep_entries
        from senaite.pfas.esig import print_rows
        current, st = prep_entries.signature_status(entry)
        return print_rows.table_and_fields(st, current)

    def __call__(self):
        flatten_form(self.request)
        from bika.lims import api
        from senaite.pfas import prep_entries, report_documents
        from senaite.pfas.browser.report_designs import designed_pdf, issued_design
        portal = api.get_portal()
        entry = prep_entries.load(portal).get(self.request.form.get("entry") or u"")
        if not entry:
            self.request.response.setStatus(404)
            return u"Preparation record not found"
        design = issued_design("preparation")
        if design is None:
            self.request.response.setStatus(409)
            return NO_PREPARATION_DESIGN
        try:
            lots, parents, rev = self._inputs(portal, entry)
            rows, fields = self._signatures(entry)
            # an analyte by its display name, as the certificate and the QC
            # Review print it
            from senaite.pfas import compound_library, compound_library_store
            library = compound_library_store.library()
            from senaite.pfas import facility_qc
            data = report_documents.preparation_data(
                dict(entry, parents=parents), lots, rev, signatures=rows,
                analyte_name=lambda name: compound_library.canonical_name(library, name) if name else name,
                unit_of=facility_qc.get_unit)
            from senaite.pfas import document_templates as dt
            if not dt.shows(design, "storage_conditions"):
                data = report_documents.storage_with_conditions(data)
            if not dt.shows(design, "expired_parents"):
                data = report_documents.expired_in_expiry_note(data)
            if not dt.shows(design, "extension"):
                data = report_documents.extension_in_expiry_note(data)
            pdf = designed_pdf("preparation", data, design=design,
                               people={"preparer": (entry.get("made_by"), entry.get("made_at")),
                                       "reviewer": (entry.get("reviewed_by"), entry.get("reviewed_at"))},
                               ledger_fields=fields)
        except DesignedReportError as exc:
            self.request.response.setStatus(500)
            return u"%s" % exc
        except Exception as exc:                            # noqa: BLE001
            logger.exception("preparation record %s", entry.get("id"))
            self.request.response.setStatus(500)
            return u"The preparation record could not be read: %s" % exc
        return send_pdf(self.request.response, pdf, "pfas_preparation_{0}.pdf".format(entry["id"]),
                        inline=False)
