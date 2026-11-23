# -*- coding: utf-8 -*-
"""
The batch record's print (@@pfas-extraction-pdf).

The worksheet's record from receipt to release -- the record the Batch
records page assembles (batch_record.assemble) with the guided extraction
stored on the worksheet (extraction_guide._load_session) -- printed from the
issued Batch record design (Document Templates), the one layout it has. With
no design issued, or one drawn before the record had its tables, the page
answers 409 with the reason and a report package's batch record part fails
with it.

senaite.pfas.extraction_logbook.logbook_data() is pure (session + profile ->
the sections the document prints) and report_documents.batch_record_data()
flattens the record with it. Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView

from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.extraction_pdf")

from senaite.pfas import print_doc
from senaite.pfas.extraction_logbook import logbook_data
from senaite.pfas.browser.view_helpers import send_pdf
from senaite.pfas.browser.report_designs import DesignedReportError


def _stamp(at):
    """A session stamp (UTC) on the laboratory's clock; as stored while no
    zone converts."""
    return print_doc.lab_or(at, at or u"")


NO_BATCH_RECORD_DESIGN = u"No issued design for the Batch record: issue one in Document Templates"
DESIGN_PREDATES = u"The Batch record design predates the record's tables: reissue it in Document Templates"
NOT_ASSEMBLED = u"The Batch record could not be assembled: %s"


class ExtractionLogError(DesignedReportError):
    """The batch record cannot be printed for the worksheet; `status` is
    the page's HTTP answer."""

    def __init__(self, message, status=409):
        DesignedReportError.__init__(self, message)
        self.status = status


def other_lots(worksheet, record):
    from senaite.pfas.browser.batch_records import other_lots as lots
    return lots(worksheet, record)


def record_for(worksheet, request):
    """The worksheet's batch record as the Batch records page assembles it
    (batch_record.assemble): the one assembly Finalise, Approve Release,
    the print and the record view hash."""
    from senaite.pfas.browser.batch_records import PFASBatchRecordsView
    return PFASBatchRecordsView(worksheet, request).record_for(worksheet)


def extraction_inputs(worksheet, request):
    """{"data", "session", "batch_id", "record"} of the worksheet's batch
    record: the guided extraction's sections (logbook_data) and the record
    the Batch records page assembles (receipt, members, stages, loaded lots,
    run, review). Raises ExtractionLogError when there is no session or no
    method to print it under."""
    from senaite.pfas.doc_fields import utext
    from senaite.pfas.browser.extraction_guide import _load_session
    from senaite.pfas.method_profile_store import get_profile
    from bika.lims import api
    batch = worksheet                   # where the extraction record lives
    session = _load_session(batch)
    if not session:
        raise ExtractionLogError(u"No extraction session found for this worksheet", status=404)
    portal = api.get_portal()
    # the method the record is kept under, as the Batch records page resolves
    # it; never a stand-in: an extraction record printed under another
    # method's stages would misstate what was done
    from senaite.pfas.browser.batch_records import record_method_id
    from senaite.pfas.browser.sample_status import _fullname
    method_id = record_method_id(batch, session)
    if not method_id:
        raise ExtractionLogError(u"No method is set for this extraction: set the worksheet's method first.",
                                 status=409)
    profile = get_profile(portal, method_id)
    batch_id = batch.getId() if hasattr(batch, "getId") else u"extraction"
    from senaite.pfas import annotation_store, extraction_batch, extraction_store
    from senaite.pfas import extraction_amendments as ea
    from senaite.pfas.extraction_logbook import correction_marks, in_force, roster, spike_table
    finalised = extraction_batch.load(batch)
    stored = extraction_store.load_table(batch)
    if finalised and stored.get("samples"):
        stored = dict(stored, samples=extraction_batch.rekey_rows(stored["samples"], finalised))
    # the record in force: the finalised record with its corrections
    # (extraction_amendments); the finalised one is kept to mark what they
    # changed
    state = ea.load(annotation_store.read_json(batch, ea.KEY, {}))
    members, rows, ports, pedigree = in_force(finalised, stored.get("samples"), state,
                                              stored.get("spe_ports"), session.get("pedigree"))
    log = dict(stored, samples=rows, spe_ports=ports)
    data = logbook_data(batch_id, utext(batch.Title()) if hasattr(batch, "Title") else u"",
                        dict(session, pedigree=pedigree) if session.get("pedigree") else session, profile,
                        print_doc.now_stamp(),
                        spike_rows=_spike_rows(members) or (log.get("spikes") or []),
                        extracted=roster(members, log.get("samples"),
                                         log.get("spe_ports")),
                        dilution_rows=stored.get("samples"),
                        fullname=lambda uid: _fullname(portal, uid))
    marks = []
    if state["log"] and finalised:
        marks = correction_marks(finalised, stored.get("samples"), state,
                                 roster(finalised, stored.get("samples"), stored.get("spe_ports")),
                                 data["extracted"],
                                 spike_table(_spike_rows(finalised), session.get("pedigree"))[0], data["spikes"])
    # the record the Batch records page shows: one assembly for both
    record = record_for(batch, request)
    return {"data": data, "session": session, "batch_id": batch_id, "record": record, "marks": marks}


def _spike_rows(members):
    """The batch's QC members (extraction_batch.py) as the Spikes table
    reads them."""
    from senaite.pfas import extraction_batch
    by_id = dict((m["id"], m) for m in members or [])
    return [{"sample_id": m.get("injection"), "qc_type": m.get("role"),
             "spike_of": (by_id.get(m.get("parent")) or {}).get("injection") or u"",
             "spike_amount": m.get("amount") or u"", "spike_unit": m.get("unit") or u"",
             "level": m.get("level") or u"", "logged_by": m.get("added_by") or u"",
             "spike_lot": extraction_batch.spike_of(m, members)[0] or m.get("spike_lot"),
             "spike_volume_ul": extraction_batch.spike_of(m, members)[1] or m.get("spike_volume_ul"),
             "logged_at": m.get("added_at") or u""}
            for m in members or [] if m.get("role") != u"Sample"]


def _named_corrections(rows, names):
    """The Corrections rows with every sample named by the lab sample id,
    as the print's tables are (sample_names.by_lab_id, word by word)."""
    if not names or not rows:
        return rows
    import re
    from senaite.pfas import sample_names

    def named(text):
        return u"".join(sample_names.by_lab_id(w, names) if w.strip(u" ,") else w
                        for w in re.split(u"(\\s+|, )", text or u""))
    return [dict(r, what=named(r.get("what")), before=named(r.get("before")), after=named(r.get("after")))
            for r in rows]


def _corrections(portal, worksheet, record):
    """The record's Corrections rows (batch_record.corrections) by name; an
    amendment made after release says whether the ledger holds its
    signature."""
    from senaite.pfas import batch_record as br
    from senaite.pfas.browser.sample_status import _fullname
    log = record.get("amendment_log") or []
    if not log:
        return []
    st = br.signatures_of(worksheet, record) if [e for e in log if e.get("after_release")] else None
    return br.corrections(record, fullname=lambda uid: _fullname(portal, uid), st=st)


def _reviewers(portal, checklist):
    """{user id: name} of everyone Data Review's checklist names."""
    from senaite.pfas.browser.sample_status import _fullname
    checklist = checklist or {}
    ids = set([checklist.get("submitted_by"), checklist.get("approved_by")])
    for item in (checklist.get("items") or {}).values():
        if isinstance(item, dict):
            ids.update([item.get("checked_by"), item.get("proposed_by")])
    return dict((uid, _fullname(portal, uid)) for uid in ids if uid)


def _loaded_found(portal, loaded):
    """{slot: whether the inventory holds the lot the run was loaded with},
    looked up as Data Review's traceability walk looks it up
    (worksheet_lots.loaded_lots with the same resolver): the batch record
    and the QC Review report then say the same of one lot."""
    from senaite.pfas import worksheet_lots
    from senaite.pfas.browser.prepared_standards import resolve_loaded
    return dict((row["label"], row["found"]) for row in worksheet_lots.loaded_lots(
        loaded, lambda snap: resolve_loaded(portal, snap)))


def _stage_lots_found(portal, session):
    """{lot number: whether the inventory holds it} for the lots the stages
    recorded, looked up as Data Review's traceability walk looks them up."""
    from senaite.pfas import worksheet_lots
    from senaite.pfas.browser.data_review import PFASDataReviewView
    reagents, prepared = PFASDataReviewView._build_lot_indices(portal)
    return dict((lot, lot in reagents or lot in prepared)
                for lot in worksheet_lots.extraction_lot_numbers(session))


def _stage_lot_extensions(portal, session):
    """{lot number: its extension entries} for the lots the stages recorded
    that QA ever extended: what the materials table prints beside the
    expiry (report_documents.extended_materials), never part of the
    record. The notes are the print's alone: one that cannot be read is
    logged and the record prints without it."""
    from senaite.pfas import worksheet_lots
    from senaite.pfas.browser.data_review import PFASDataReviewView
    try:
        from senaite.pfas.browser import lot_extensions
        reagents, prepared = PFASDataReviewView._build_lot_indices(portal)
        out = {}
        for lot in worksheet_lots.extraction_lot_numbers(session):
            obj = reagents.get(lot) or prepared.get(lot)
            items = lot_extensions.load(obj) if obj is not None else []
            if items:
                out[lot] = items
        return out
    except Exception:                                       # noqa: BLE001
        logger.warning("lot extensions not read for the batch record", exc_info=True)
        return {}


def _equipment_units(session):
    """{serial: the Equipment register's unit} for each serial the stages
    recorded (facility_qc.unit_by_serial, the register's one lookup): what
    the equipment table prints each serial from. A serial the register does
    not hold is left out, and the print says so. A unit carries
    `uncalibrated_sets`: the weight sets behind its calibration on the days
    it was used whose calibration is not required, which the print states."""
    from senaite.pfas import facility_qc
    from senaite.pfas.extraction_review import done_on
    out = {}
    for stage in ((session or {}).get("stages") or {}).values():
        used_on = done_on(stage or {})
        for serial in ((stage or {}).get("equipment_sns") or {}).values():
            serial = (serial or u"").strip()
            if not serial:
                continue
            if serial not in out:
                try:
                    unit = facility_qc.unit_by_serial(serial)
                except Exception:                           # noqa: BLE001
                    logger.warning("equipment %s not looked up", serial, exc_info=True)
                    unit = None
                out[serial] = dict(unit, uncalibrated_sets=[]) if unit else None
            if out[serial] and used_on:
                try:
                    for set_id in facility_qc.uncalibrated_weight_sets(out[serial].get("id"), used_on):
                        if set_id not in out[serial]["uncalibrated_sets"]:
                            out[serial]["uncalibrated_sets"].append(set_id)
                except Exception:                           # noqa: BLE001
                    logger.warning("weight sets of %s not read", serial, exc_info=True)
    return dict((k, v) for k, v in out.items() if v)


def batch_record_pdf_bytes(worksheet, request, names=None, mono=False):
    """(pdf, rev): the worksheet's batch record printed from its issued
    design (Document Templates) and that design's revision. `names`
    ({client sample id: lab sample id}, sample_names.lab_names), given for a
    report package, prints every sample by the lab sample id; `mono` prints
    it in black and white; the record and its hash are not changed. The design is
    checked before the record is read: none issued, or one without the
    record's tables, refuses (status 409). Raises DesignedReportError, its
    message the reason: no design, a design that predates the tables, no
    session, no method, a record that cannot be assembled, or a design that
    cannot render."""
    from bika.lims import api
    from ZODB.POSException import ConflictError
    from senaite.pfas import document_templates as dt
    from senaite.pfas import report_documents
    from senaite.pfas.browser.data_review import _CHECKLIST_ITEMS
    from senaite.pfas.browser.report_designs import designed_pdf
    portal = api.get_portal()
    store = dt.load(portal)
    design = dt.issued_design(store, "batch_record")
    if design is None:
        raise ExtractionLogError(NO_BATCH_RECORD_DESIGN, status=409)
    if dt.missing_tables("batch_record", design):
        raise ExtractionLogError(DESIGN_PREDATES, status=409)
    rev = dt.current(store[dt.KINDS["batch_record"]["single"]])["rev"]
    try:
        inputs = extraction_inputs(worksheet, request)
        record = inputs["record"]
        # a signature image kept at signing that is missing or altered
        # refuses the print with its reason
        rows, fields = _signatures(portal, worksheet, record, inputs["session"])
        from senaite.pfas import stage_plan
        data = report_documents.batch_record_data(
            record, inputs["data"], review_order=[k for k, _l, _a in _CHECKLIST_ITEMS],
            people=_reviewers(portal, (record.get("parts") or {}).get("review")), signatures=rows,
            loaded_found=_loaded_found(portal, (record.get("parts") or {}).get("loaded")),
            lots_found=_stage_lots_found(portal, inputs["session"]),
            extensions=_stage_lot_extensions(portal, inputs["session"]),
            units=_equipment_units(inputs["session"]),
            other_lots=other_lots(worksheet, record),
            revision_text=stage_plan.revision_words(inputs["session"]),
            corrections=_corrections(portal, worksheet, record))
    except (ConflictError, DesignedReportError):
        raise
    except Exception as exc:                                # noqa: BLE001
        logger.exception("batch record of %s not assembled", getattr(worksheet, "getId", lambda: u"?")())
        # the message as text: a UTF-8 byte message (Python 2) never raises here
        from senaite.pfas.browser.report_packages_view import error_text
        raise DesignedReportError(NOT_ASSEMBLED % error_text(exc))
    session = inputs["session"]
    review = (record.get("parts") or {}).get("review") or {}
    # the finaliser prepares (attests the extraction), the approver reviews
    # (releases the record); a signed role prints as the ledger has it
    # a part only older records carry is left out when this one has none
    from senaite.pfas import sample_names
    data = sample_names.batch_record_data(data, names)
    # an amended cell prints the value in force (named as the print names
    # it) and the entry; the Corrections section says what it was
    data = report_documents.mark_cells(data, inputs.get("marks"),
                                       rename=lambda value: sample_names.by_lab_id(value, names))
    data["corrections"] = _named_corrections(data.get("corrections"), names)
    # a design issued before the Corrections table says them under the
    # deviations: a correction is never left off the record
    if data.get("corrections") and not dt.shows(design, "corrections"):
        data["deviations"] = u"\n\n".join(t for t in (data.get("deviations"),
                                                     report_documents.corrections_text(data["corrections"])) if t)
    omit = report_documents.empty_fields(data)
    if omit:
        design = dt.subset_design(design, omit)
    pdf = designed_pdf("batch_record", data, design=design,
                       people={"preparer": (session.get("finalized_by"), _stamp(session.get("finalized_at"))),
                               "reviewer": (review.get("approved_by"), _stamp(review.get("approved_at")))},
                       ledger_fields=fields, mono=mono)
    return pdf, rev


def _signatures(portal, worksheet, record, session):
    """(the Signatures table's rows, the fields a signed role prints from
    the ledger) of the worksheet's record, each role read against the hash
    its signer attests. An extraction finalised before signatures were
    kept has a row saying so, and its preparer image is left blank rather
    than drawn from the person's image today."""
    from senaite.pfas import batch_record as br
    from senaite.pfas.browser.sample_status import _fullname
    from senaite.pfas.esig import print_rows
    st = br.signatures_of(worksheet, record)
    rows, fields = print_rows.table_and_fields(st, br.hashes(record))
    legacy = br.legacy_preparer_row(session, st, lambda uid: _fullname(portal, uid), _stamp)
    if legacy is not None:
        rows = [legacy] + list(rows)
        fields["preparer_signature"] = u""
    return rows, fields


class PFASExtractionPDFView(BrowserView):
    """Print the worksheet's batch record from its issued design."""

    def __call__(self):
        flatten_form(self.request)
        uid = self.request.form.get("batch_uid", "")
        if not uid:
            self.request.response.setStatus(400)
            return "batch_uid parameter required"
        brains = getToolByName(self.context, "uid_catalog")(UID=uid)
        if not brains:
            self.request.response.setStatus(404)
            return "Worksheet not found"
        from senaite.pfas import extraction_batch
        batch = extraction_batch.home(brains[0].getObject())   # the worksheet
        try:
            pdf, _rev = batch_record_pdf_bytes(batch, self.request)
        except DesignedReportError as exc:
            self.request.response.setStatus(getattr(exc, "status", 500))
            return u"%s" % exc
        return send_pdf(self.request.response, pdf, "pfas_extraction_{0}.pdf".format(batch.getId()),
                        inline=False)
