# -*- coding: utf-8 -*-
"""@@pfas-batch-records?record=<worksheet uid>: one worksheet's batch record
with its signatures. The list of records is SENAITE's own listing
(batch_records_listing.py), whose rows this view reads (queue_record).

The record is the worksheet's guided extraction, kept under the method
revision it started with (batch_record.py assembles it). This view only
reads the stores; a row opens the guided extraction and prints the record.
"Print record" opens the record's print (@@pfas-extraction-pdf). A row's
signature word comes from the extraction session's display cache; the
record view reads the signature ledger against the record as it is now, and
its Verify (action=verify_record) recomputes the hashes and checks every
signature in the ledger.

Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import logging

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas import batch_record as br
from senaite.pfas import worksheet_lots
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.browser.batch_records")


def record_method_id(ws, session):
    """The method a worksheet's record is kept under: the one its extraction
    started under, from its plan, or from the session itself when it began
    before plans; a worksheet with neither (not started) by the worksheet's
    resolver, which wakes its samples. The page and the print resolve it
    here."""
    from senaite.pfas import batch_method, stage_plan
    if stage_plan.has_plan(session):
        planned = session[stage_plan.PLAN].get("method_id") or u""
        if planned:
            return planned
    started = (session or {}).get("method_id") or u""
    if started:
        return started
    return batch_method.for_worksheet(ws) or u""


def recording_roles():
    """The roles that record the extraction (the members page's own), who
    amend it and flag a re-extraction."""
    from senaite.pfas.browser.extraction_batch_view import EDIT_ROLES
    return EDIT_ROLES


def other_lots(ws, record):
    """The matrix blanks' and dilutions' lots the worksheet's analysis used
    (worksheet_lots.other_lot_rows), each looked up in the inventory as Data
    Review's traceability walk looks it up: what the record view lists and
    the print prints beside the record, never what it hashes."""
    from bika.lims import api
    from senaite.pfas import extraction_batch
    from senaite.pfas.browser.bench_inventory import item_index
    index = item_index(api.get_portal())
    members = ((record or {}).get("parts") or {}).get("members") or []
    return worksheet_lots.other_lot_rows(members, extraction_batch.load_requests(ws),
                                         lambda kind, uid: index.get((kind, uid)))


class PFASBatchRecordsView(ViewHelpers, BrowserView):
    """The worksheets' batch records."""

    template = ViewPageTemplateFile("templates/batch_records.pt")

    def __call__(self):
        flatten_form(self.request)
        self._profiles = {}
        if self.request.get("action", "") == "verify_record":
            return self._handle_verify_record()
        return self.template()

    def ok_msg(self):
        return self.request.get("ok", "")

    def error_msg(self):
        return self.request.get("error", "")

    def ea_msg(self):
        """True when the message is a correction's (shown on the
        Corrections card, not under Signatures)."""
        return bool(self.request.get("ea", ""))

    def _worksheet(self, uid):
        """The worksheet a record view names by uid, or None."""
        from bika.lims import api
        if not uid:
            return None
        obj = api.get_object_by_uid(uid, None)
        return obj if getattr(obj, "portal_type", None) == "Worksheet" else None

    def record_view(self):
        """The record ?record=<uid> names, with its signatures card, or
        None: the queue is shown."""
        if getattr(self, "_record_view", None) is None:
            self._record_view = False
            ws = self._worksheet(self.request.get("record", ""))
            if ws is not None:
                record = self.record_for(ws)
                record["signatures"] = self._signature_card(ws, record)
                # what was done and with which lots, beside who signed it
                record["stage_rows"] = self._stage_rows(record)
                record["lot_rows"] = worksheet_lots.record_lot_rows(record, other_lots(ws, record))
                record["lot_summary"] = worksheet_lots.lots_summary(record, record["lot_rows"])
                record["state_label"] = br.state_label(record)
                record["identity_rows"] = self._identity_rows(record)
                record["send_back_rows"] = self._send_back_rows(record)
                # what was corrected after Finalise, and the windows that
                # correct it
                record["correction_card"] = self._corrections(ws, record)
                self._record_view = record
        return self._record_view or None

    @staticmethod
    def _stage_rows(record):
        """The record's stages as its view lists them: each planned stage,
        when it was completed on the laboratory's clock and by whom, or
        that it is not recorded."""
        from senaite.pfas import lab_time
        out = []
        for st in (record.get("parts") or {}).get("stages") or []:
            at = st.get("completed_at") or u""
            out.append({"order": st.get("order"), "name": st.get("name") or u"",
                        "recorded": bool(st.get("recorded")),
                        "completed": lab_time.show(at) if at else u"",
                        "analyst": st.get("analyst") or u"", "deviations": st.get("deviations") or u""})
        return out

    @staticmethod
    def _identity_rows(record):
        """The injections' identity corrections the record holds, oldest
        first, as its view lists them: each correction, undo and the
        verifier's confirmation (injection_identity.record_part)."""
        from senaite.pfas import injection_identity as ii, lab_time
        part = (record.get("parts") or {}).get(br.IDENTITY_PART) or []
        out = []
        for e in reversed(ii.history({"log": part})):
            out.append({"injection": e.get("injection") or u"", "change": e["change"],
                        "from_code": e.get("from_code") or u"", "to_code": e.get("to_code") or u"",
                        "from_label": e.get("from_label") or u"", "to_label": e.get("to_label") or u"",
                        "reason": e.get("reason") or u"", "by": e.get("name") or e.get("by") or u"",
                        "when": lab_time.show(e["at"]) if e.get("at") else u""})
        return out

    # the windows a correction is made in, by the name a page opens one with
    OPENS = ("amend", "reextract", "send_back")

    def _corrections(self, ws, record):
        """The Corrections card: one row per entry of the record's
        corrections log (batch_record.corrections; without it, the log read
        here), the chips for the header, each row's menu (Undo... before
        it is confirmed, Confirm for the Lab Manager who confirms it), and
        what the Amend, Needs re-extraction and Send back windows offer.
        A correction is never made here: each window posts to
        @@pfas-extraction-corrections on the worksheet."""
        try:
            return self._corrections_card(ws, record)
        except Exception:                                   # noqa: BLE001
            logger.exception("corrections of %s unreadable", ws.getId())
            return {"rows": [], "chips": [], "undo": [], "ws_url": u"", "can": {}, "error": True}

    def _corrections_card(self, ws, record):
        from senaite.pfas import extraction_amendments as ea
        from senaite.pfas import lab_time, row_menu
        from senaite.pfas.browser import extraction_corrections as xc
        facts = xc.Facts(ws, self.request)
        state, ws_state = facts.state(), record.get("review_state") or u""
        from senaite.pfas.browser.sample_status import _fullname
        rows_of = getattr(br, "corrections", None)
        if rows_of is not None:
            try:
                st = br.signatures_of(ws, record)
            except Exception:                               # noqa: BLE001
                st = None
            rows = rows_of(record, fullname=lambda uid: _fullname(ws, uid), st=st)
        else:
            rows = xc.correction_rows(state, facts.members(), show=lab_time.show)
        chips_of = getattr(br, "chips", None)
        chips = chips_of(record) if chips_of is not None else [
            w for k, w in ((ea.AMEND, u"Amended"), (ea.SEND_BACK, u"Sent back"), (ea.REEXTRACT, u"Re-extraction"))
            if [e for e in ea.entries_in_force(state) if e.get("action") == k]]
        who = self._userid()
        from senaite.pfas.browser.perms import ANALYST_ROLES, MANAGER_ROLES
        manager, recorder = self._has(MANAGER_ROLES), self._has(recording_roles())
        analyst = self._has(ANALYST_ROLES)
        released = ws_state in ea.RELEASED_STATES
        finalised = facts.finalised()
        # what a verifier confirms now: once submitted; a whole batch
        # re-extracted while open (it never reaches verification)
        due = dict((e.get("id"), e) for e in ea.to_confirm(state)
                   if ws_state == ea.SUBMITTED or (ws_state in ea.OPEN_STATES and e.get("action") == ea.REEXTRACT
                                                   and e.get("scope") == "batch"))
        undo = []
        for r in rows:
            acts = []
            # undone while the worksheet is open (submitted, it is sent
            # back first; released, it is amended again, signed)
            if r.get("can_undo") and recorder and ws_state in ea.OPEN_STATES:
                acts.append((u"Undo\u2026", "modal", u"ea-undo-%s" % r["id"], {"danger": True}))
                undo.append(r)
            if manager and r["id"] in due:
                off = ea.OWN.format(r["id"]) if due[r["id"]].get("by") == who else None
                acts.append((u"Confirm", "form", "ea-confirm",
                             {"values": {"entry": r["id"]}, "off": off,
                              "confirm": u"Confirm %s? Your name is recorded as its countersign." % r["id"]}))
            acts.append((u"Open in Data Review", "href", u"%s/@@pfas-data-review" % self._ws_url(ws)))
            r["actions"] = row_menu.actions(*acts)
        members = facts.in_force()
        can = {
            "amend": bool(recorder and finalised and ws_state != ea.REJECTED
                          and ws_state != ea.SUBMITTED and (manager or not released)),
            "reextract": bool(recorder and finalised and ws_state in ea.OPEN_STATES + (ea.SUBMITTED,)
                              and (manager or ws_state != ea.SUBMITTED)),
            "send_back": bool((analyst or manager) and (ws_state in ea.OPEN_STATES
                                                         or (manager and ws_state == ea.SUBMITTED))),
        }
        opened = self.request.get("open", "")
        stages = [{"value": u"%s" % s["order"], "label": u"%s \u00b7 %s" % (s["order"], s["name"])}
                  for s in record.get("stage_rows") or [] if s.get("recorded")]
        out = {
            "rows": rows, "chips": chips, "undo": undo, "ws_url": self._ws_url(ws), "can": can,
            "released": released,
            "open": opened if opened in self.OPENS and can.get(opened) else u"",
            "member": self.request.get("member", ""),
            "submitted": ws_state == ea.SUBMITTED,
            "sample_rows": [{"value": u"sample:%s" % r.get("sample_id"),
                             "label": u"%s \u00b7 extracted amount" % r.get("sample_id")}
                            for r in facts.rows_in_force() if r.get("sample_id")] if can["amend"] else [],
            "members": [{"value": m.get("id"), "label": u"%s \u00b7 %s" % (m.get("injection") or m.get("id"),
                                                                          m.get("role")),
                         "withheld": bool(m.get("withheld"))} for m in members],
            "dialog_json": facts.dialog_json() if can["amend"] else u"{}",
            "fields": [{"value": k, "label": ea.FIELD_LABELS[k]} for k in ea.MEMBER_FIELDS + ea.SAMPLE_FIELDS],
            "what": [{"value": v, "label": l} for v, l in ea.WHAT],
            "scopes": [{"value": v, "label": l} for v, l in ea.SCOPES],
            "targets": [{"value": v, "label": l} for v, l in ea.TARGETS],
            "stages": stages,
            "esig": self._amend_esig(ws, record) if released and can["amend"] else None,
        }
        return out

    def _amend_esig(self, ws, record):
        """The sign dialog of an amendment to a released record: signed as
        the record's next revision by the Lab Manager who makes it."""
        from senaite.pfas.browser.perms import signed_in_name
        from senaite.pfas.esig import signing
        return {"record": record.get("worksheet") or ws.getId(),
                "revision": u"%s" % ((record.get("record_revision") or 1) + 1),
                "hash_prefix": u"", "content_text": u"The record with this amendment",
                "meaning_label": signing.meaning_label("corrected"),
                "signer_name": signed_in_name(ws), "action": u"ea_amend", "form_id": u"ea-amend-form"}

    @staticmethod
    def _ws_url(ws):
        return getattr(ws, "absolute_url", lambda: u"")()

    def _userid(self):
        from AccessControl import getSecurityManager
        return getSecurityManager().getUser().getId()

    def _has(self, roles):
        from senaite.pfas.browser.perms import has_role_at_portal
        return has_role_at_portal(self.context, roles)
    @staticmethod
    def _send_back_rows(record):
        """Verify's send backs the record holds, oldest first."""
        from senaite.pfas import review_send_back as sb, lab_time
        part = (record.get("parts") or {}).get(br.SEND_BACK_PART) or []
        return [{"change": e["change"], "reason": e.get("reason") or u"", "by": e.get("by") or u"",
                 "when": lab_time.show(e["at"]) if e.get("at") else u"", "cleared": e["cleared_text"]}
                for e in reversed(sb.history({"log": part}))]

    def _signature_card(self, ws, record):
        """The record's Signatures: each signature as the print lists it
        (report_documents.signature_rows), each role read against the hash
        its signer attests, and an extraction finalised before signatures
        were kept as the print shows it; None when the ledger cannot be
        read."""
        from senaite.pfas import lab_time, print_doc
        from senaite.pfas import report_documents as rd
        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas.browser.sample_status import _fullname
        from senaite.pfas.esig import ledger
        try:
            st = br.signatures_of(ws, record)
        except ledger.LedgerError:
            logger.exception("signatures of %s unreadable", ws.getId())
            return None
        rows = rd.signature_rows(st, br.hashes(record), lab_time.show, changed_at=print_doc.now_label())
        legacy = br.legacy_preparer_row(_load_session(ws), st, lambda uid: _fullname(ws, uid), lab_time.show)
        return ([legacy] if legacy is not None else []) + rows

    def _handle_verify_record(self):
        """Read the record's signatures against its content now: the hashes
        recomputed, every signature looked up in the ledger, the session's
        display cache checked against it. Back to the record view."""
        from six.moves.urllib.parse import quote_plus
        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas.esig import ledger
        uid = self.request.get("record", "")
        back = "{0}/@@pfas-batch-records?record={1}".format(self.portal_url(), quote_plus(uid))
        ws = self._worksheet(uid)
        if ws is None:
            return self._redirect("{0}&error=Record+not+found".format(back))
        record = self.record_for(ws)
        try:
            st = br.signatures_of(ws, record)
        except ledger.LedgerError:
            logger.exception("signatures of %s unreadable", ws.getId())
            return self._redirect("{0}&error=The+signatures+could+not+be+read".format(back))
        why = br.verify(st, (_load_session(ws) or {}).get("signatures"))
        if why:
            return self._redirect("{0}&error={1}".format(back, quote_plus(why.encode("utf-8"))))
        return self._redirect("{0}&ok=Signatures+checked".format(back))

    def _profile(self, method_id):
        """The method's profile, read once per request."""
        cache = getattr(self, "_profiles", None)
        if cache is None:
            cache = self._profiles = {}
        if method_id not in cache:
            from senaite.pfas.method_profile_store import get_profile
            cache[method_id] = (get_profile(self._portal(), method_id) or {}) if method_id else {}
        return cache[method_id]

    def _method_id(self, ws, session):
        return record_method_id(ws, session)

    def _samples_matrix_client(self, ws, profile, queue=False):
        """(samples, matrix, client): the worksheet's samples, their matrix
        as the method's profile names it, and their client. A queue row
        finds the samples through the analysis catalog, never waking each
        analysis; the full record reads them in the worksheet's order."""
        from senaite.pfas.doc_fields import utext
        from bika.lims import api
        from senaite.pfas import extraction_batch
        from senaite.pfas.core_fields import samples_of
        from senaite.pfas.report_limits import canonical_matrix
        samples = list(extraction_batch.samples_on(ws) if queue else samples_of(ws))
        matrix = br.joined(canonical_matrix(profile, s.getSampleTypeTitle()) for s in samples)
        client = br.joined(utext(api.get_title(c)) for c in (s.getClient() for s in samples) if c is not None)
        return samples, matrix, client

    def record_for(self, ws, queue=False, review_state=None, amendments=None):
        """The worksheet's batch record. `queue`: only what a queue row
        shows (title, matrix, client, state, progress); the receipt, members
        and the run are left empty, never read. `review_state`, the
        worksheet's when the caller has it (the catalog's). `amendments`,
        the corrections log to assemble it with in place of the stored one
        (the record a correction about to be stored is signed over)."""
        from senaite.pfas import annotation_store, coc_records as cr
        from senaite.pfas import extraction_batch, extraction_review, stage_plan, study_runs
        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas.browser.run_builder import RUN_MANIFEST_KEY
        from senaite.pfas.run_lots import injection_list
        session = _load_session(ws)
        manifest = annotation_store.read_json(ws, RUN_MANIFEST_KEY, {})
        checklist = annotation_store.read_json(ws, study_runs.CHECKLIST_KEY, {})
        if review_state is None:
            from bika.lims import api
            review_state = api.get_review_status(ws)
        method_id = self._method_id(ws, session)
        profile = self._profile(method_id)
        stages = stage_plan.stages_for(session, profile)
        review = extraction_review.review(session, stages)
        loaded = {"standards": manifest.get("standards") or {},
                  "solvents": manifest.get("solvents") or {}}
        samples, matrix, client = self._samples_matrix_client(ws, profile, queue)
        if queue:
            receipt, members, run = {}, [], []
        else:
            receipt = cr.worksheet_summary(self._portal(), samples)
            members = extraction_batch.load(ws) or []
            run = injection_list(manifest) if manifest.get("rows") else []
        from senaite.pfas import injection_identity
        from senaite.pfas.injection_identity import KEY as IDENTITY_KEY
        identity = [] if queue else injection_identity.record_part(
            annotation_store.read_json(ws, IDENTITY_KEY, {}))
        from senaite.pfas import extraction_amendments as ea
        if queue:
            amendments = None
        elif amendments is None:
            amendments = annotation_store.read_json(ws, ea.KEY, {})
        from senaite.pfas import review_send_back
        from senaite.pfas.review_send_back import KEY as SEND_BACK_KEY
        send_back = [] if queue else review_send_back.record_part(
            annotation_store.read_json(ws, SEND_BACK_KEY, {}))
        record = br.assemble(ws.getId(), profile.get("display_name") or method_id,
                             stage_plan.revision_of(session)[0], receipt, members, review,
                             loaded, run, checklist, session=session, manifest=manifest,
                             review_state=review_state or u"", method_id=method_id,
                             matrix=matrix, client=client, identity=identity, amendments=amendments,
                             send_back=send_back)
        record["uid"] = ws.UID()
        # the queue's word, from the session's display cache: the record
        # view reads the ledger
        record["signed"] = br.signature_word(session)
        return record

    def queue_record(self, brain):
        """The record of a worksheet the list shows (a catalog brain of
        senaite_catalog_worksheet): only what its row shows is read. One
        that cannot be read is shown as such, so a worksheet never drops
        off the list unseen."""
        try:
            return self.record_for(brain.getObject(), queue=True,
                                   review_state=getattr(brain, "review_state", None))
        except Exception as exc:                            # noqa: BLE001
            ws_id, uid = getattr(brain, "getId", u""), getattr(brain, "UID", u"")
            logger.warning("batch record of %s: %s", ws_id, exc)
            return br.unreadable(ws_id, uid)
