# -*- coding: utf-8 -*-
"""
The batch's endpoints for the pipeline worker:

    @@pfas-retire-attachment   remove a superseded attachment, or keep it
                               under another label (manager, POST)
    @@pfas-run-manifest        the injection list the Run Builder planned
    @@pfas-batch-dilutions     the extraction record's dilutions, spikes,
                               members and sample amounts
    @@pfas-instrument-archive-sweep  the archived instrument files, each
                               kept or deleted as instrument_files decides
                               (manager, POST)

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from zope.annotation.interfaces import IAnnotations
from senaite.pfas import lab_time
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse

logger = logging.getLogger("senaite.pfas.browser.batch_api")


def record_retired(parent, label, objs, reason):
    """Before a controlled record goes: which file, on its parent's trail
    (records.log: who, when, why)."""
    from senaite.pfas import records
    for obj in objs:
        try:
            f = obj.getAttachmentFile()
            name, size = getattr(f, "filename", u"") or u"", f.get_size() if f else 0
        except Exception:                                   # noqa: BLE001
            name, size = u"", 0
        records.log(parent, u"attachment retired", reason=reason,
                    detail={u"label": label, u"id": obj.getId(), u"file": name, u"bytes": size})


def keep_superseded(parent, objs, keep_as, reason):
    """Each attachment kept beside its replacement under the label
    `keep_as`, on its parent's trail (records.log: which file, its label
    before and after, why). Returns the ids kept."""
    from senaite.pfas import records
    kept = []
    for obj in objs:
        before = obj.getAttachmentKeys() or u""
        obj.setAttachmentKeys(keep_as)
        obj.reindexObject()
        try:
            f = obj.getAttachmentFile()
            name = getattr(f, "filename", u"") or u""
        except Exception:                                   # noqa: BLE001
            name = u""
        records.log(parent, u"attachment superseded", reason=reason,
                    detail={u"label": before, u"kept_as": keep_as, u"id": obj.getId(), u"file": name})
        kept.append(obj.getId())
    return kept


class PFASRetireAttachmentView(BrowserView):
    """
    POST @@pfas-retire-attachment  {parent_uid, label, keep_as?}

    Remove superseded attachments carrying *label* from a Worksheet or
    Client; with *keep_as*, keep each under that label instead (a re-imported
    run's earlier batch report stays, marked superseded).

    senaite.jsonapi cannot delete an Attachment — its delete fires a
    "deactivate" transition the type has no workflow for, and answers HTTP 200
    with success:false. So a re-imported batch report stacked another copy each
    time (eight on one worksheet) and the worker could only report that it had
    failed to replace it. Deleting from inside the add-on works.

    A manager's or the worker's: this removes a controlled record.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        from senaite.pfas.browser.perms import require_manager, disable_csrf, may_run_worker_tasks
        if not (require_manager(self.context, self.request) or may_run_worker_tasks(self.context)):
            return refuse(self.request, json.dumps({"error": "Manager role required"}))
        disable_csrf(self.request)
        # it deletes: never from a plain link
        if (self.request.get("REQUEST_METHOD") or "").upper() != "POST":
            self.request.response.setStatus(405)
            self.request.response.setHeader("Allow", "POST")
            return json.dumps({"error": "POST required"})

        parent_uid = (self.request.get("parent_uid") or u"").strip()
        label = (self.request.get("label") or u"").strip()
        if not parent_uid or not label:
            self.request.response.setStatus(400)
            return json.dumps({
                "error": "parent_uid and label are both required"})

        from bika.lims import api as _api
        parent = _api.get_object_by_uid(parent_uid, None)
        if parent is None:
            self.request.response.setStatus(404)
            return json.dumps({"error": "No object {0}".format(parent_uid)})

        doomed = []
        for obj in parent.objectValues(["Attachment"]):
            try:
                keys = obj.getAttachmentKeys() or u""
            except Exception:
                keys = u""
            if keys == label:
                doomed.append(obj.getId())
        keep_as = (self.request.get("keep_as") or u"").strip()
        if doomed:
            reason = (self.request.get("reason") or u"").strip() or u"superseded by a newer copy"
            if keep_as and keep_as != label:
                kept = keep_superseded(parent, [parent[i] for i in doomed], keep_as, reason)
                return json.dumps({"retired": [], "superseded": kept})
            record_retired(parent, label, [parent[i] for i in doomed], reason)
            parent.manage_delObjects(doomed)
        return json.dumps({"retired": doomed})


class PFASRunManifestView(BrowserView):
    """
    @@pfas-run-manifest?batch_id=demo-b-001

    The injection list the Run Builder planned, so the importer can reconcile
    what was actually run against it. This replaces validating names against
    hardcoded regexes — which rejected 8 of 20 hand-typed names and then 21 of
    22 names this system generated itself.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        batch_id = (self.request.get("batch_id") or u"").strip()
        ws_id = (self.request.get("worksheet_id") or u"").strip()
        if not batch_id and not ws_id:
            self.request.response.setStatus(400)
            return json.dumps({"error": "worksheet_id or batch_id parameter is required"})
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        from senaite.pfas import extraction_batch
        from senaite.pfas.batch_ref import get_batch
        # the Run Builder keeps the manifest on the extraction batch (the
        # worksheet); a client Batch id is followed to it
        batch = None
        if ws_id:
            from bika.lims import api
            hits = api.search({"portal_type": "Worksheet", "getId": ws_id}, "senaite_catalog_worksheet")
            batch = api.get_object(hits[0]) if hits else None
        if batch is None and batch_id:
            b = get_batch(portal, batch_id)
            batch = extraction_batch.home(b) if b is not None else None
        if batch is None:
            self.request.response.setStatus(404)
            return json.dumps({"error": "No worksheet {0} / batch {1}".format(ws_id, batch_id)})
        try:
            from senaite.pfas.browser.run_builder import RUN_MANIFEST_KEY
            raw = IAnnotations(batch).get(RUN_MANIFEST_KEY)
        except Exception:
            raw = None
        # the identity corrections in force (Data Review): the worker judges
        # the run with them over the roles below
        from senaite.pfas import injection_identity
        from senaite.pfas.injection_identity import KEY as IDENTITY_KEY
        try:
            identity = injection_identity.overlay(IAnnotations(batch).get(IDENTITY_KEY))
        except Exception:                                   # noqa: BLE001
            identity = {}
        # the extraction corrections in force: the ids the run is judged
        # with (the worker records those it applied, and release waits for
        # the rest) and the names, in force and issued, of the members
        # withheld for re-extraction
        from senaite.pfas import extraction_amendments as ea
        amendments = extraction_batch.amendments_state(batch)
        corrections = {
            "amendments": ea.judged_ids(amendments),
            "withheld": extraction_batch.withheld_names(
                ea.members_in_force(extraction_batch.load(batch), amendments)),
        }
        if not raw:
            return json.dumps(dict({"lab_zone": lab_time.zone(), "identity": identity}, **corrections))
        try:
            manifest = json.loads(raw)
        except (ValueError, TypeError):
            return json.dumps(dict({"lab_zone": lab_time.zone(), "identity": identity}, **corrections))
        return json.dumps(dict({
            "lab_zone": lab_time.zone(),
            "identity": identity,
            "built_at": manifest.get("built_at", ""),
            "built_by": manifest.get("built_by", ""),
            "planned": [r.get("name") for r in (manifest.get("rows") or [])
                        if r.get("name")],
            # what each planned injection IS, as the Run Builder built it: the
            # pipeline never has to read a role from a name it issued
            "roles": dict((r["name"], r["role"]) for r in (manifest.get("rows") or [])
                          if r.get("name") and r.get("role")),
        }, **corrections))


def _mxb_reference(portal, lot_uid):
    """{"levels": {analyte: value}, "unit"} in force on a blank-matrix lot,
    or None."""
    try:
        from senaite.pfas.browser.assigned_levels import lot_record
        rec = lot_record(portal, lot_uid)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("matrix blank reference for %s: %s", lot_uid, exc)
        return None
    if not rec or not rec.get("levels"):
        return None
    return {"levels": dict(rec["levels"]), "unit": rec.get("unit") or u""}


def _field_qc_code(member):
    """u"FRB" for a member sample whose CoC Field QC says it is a field
    reagent blank, u"TB" for a trip blank -- read from the sample, which owns
    it; else u"". The worker judges an FRB against the blank limit and a TB
    against the method's trip blank limit (a gap while none is set)."""
    if member.get("role") != u"Sample" or not member.get("sample_uid"):
        return u""
    try:
        from bika.lims import api
        sample = api.get_object_by_uid(member["sample_uid"], None)
        fld = sample.getField("FieldQCType") if sample is not None else None
        value = (fld.get(sample) if fld else u"") or u""
    except Exception:                                       # noqa: BLE001
        return u""
    from senaite.pfas.coc_records import WORKER_FIELD_QC
    return WORKER_FIELD_QC.get(value, u"")


class PFASBatchDilutionsView(BrowserView):
    """
    @@pfas-batch-dilutions?batch_id=demo-b-001

    The dilution map recorded on the extraction record, as JSON, for the pipeline worker:

        {"DEMO Silage \"Egg-3\"; Dil. 1:10": {"parent": "DEMO Silage \"Egg-3\" Sample",
                                             "factor": 10.0}}

    Empty object when the batch records no dilutions — which is every batch
    logged before the columns existed, so the worker's behaviour is unchanged
    for them.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)

        batch_id = (self.request.get("batch_id") or u"").strip()
        ws_id = (self.request.get("worksheet_id") or u"").strip()
        if not batch_id and not ws_id:
            self.request.response.setStatus(400)
            return json.dumps({"error": "worksheet_id or batch_id parameter is required"})

        portal = getToolByName(self.context, "portal_url").getPortalObject()
        from senaite.pfas import extraction_batch
        from senaite.pfas.batch_ref import get_batch
        from senaite.pfas.dilution_ref import get_dilutions, get_sample_amounts, get_spikes
        # the extraction record lives on the worksheet; a
        # client Batch id is followed to its worksheet
        batch = None
        if ws_id:
            from bika.lims import api
            hits = api.search({"portal_type": "Worksheet", "getId": ws_id}, "senaite_catalog_worksheet")
            batch = api.get_object(hits[0]) if hits else None
        if batch is None and batch_id:
            batch = extraction_batch.home(get_batch(portal, batch_id))
        if batch is None:
            self.request.response.setStatus(404)
            return json.dumps({"error": "No worksheet {0} / batch {1}".format(ws_id, batch_id)})
        payload = get_dilutions(batch)
        # how the IS and the surrogate were handled when each dilution was
        # made (Run Builder step 4): the worker judges the IS by it
        for r in extraction_batch.load_requests(batch):
            prep = r.get("prep") or {}
            if r.get("kind") == u"dilution" and r.get("new_injection") in payload and prep:
                payload = dict(payload)
                payload[r["new_injection"]] = dict(payload[r["new_injection"]],
                                                   is_handling=prep.get("is_handling") or u"",
                                                   sur_handling=prep.get("sur_handling") or u"")
        # the extraction batch's members in force: every amendment in force
        # applied, each issued name an amendment renamed matching its member
        # (by_alias), each member withheld for re-extraction marked
        members = extraction_batch.members_in_force(batch)
        # Spike pedigree rides along under a reserved key. A dilution id can
        # never collide with it: NAME_RE forbids a leading underscore.
        spikes = extraction_batch.by_alias(get_spikes(batch), members)
        if spikes:
            payload = dict(payload)
            payload["_spikes"] = spikes
        # the extraction batch's members: each LIMS-issued injection's role and
        # a sample's uid, so the worker matches by the record
        if members:
            payload = dict(payload)
            payload["_members"] = dict(
                (m.get("injection"), {"role": m.get("role") or u"Sample",
                                      "sample_uid": m.get("sample_uid") or u"",
                                      "field_qc": _field_qc_code(m),
                                      # the method blank to subtract
                                      "subtract": bool(m.get("subtract"))})
                for m in members if m.get("injection"))
            # a matrix blank's lot reference values, for the method that
            # judges it as a recovery against them (Matrix blanks)
            for m in members:
                if m.get("role") == u"MxB" and m.get("injection") and m.get("lot"):
                    ref = _mxb_reference(portal, m["lot"])
                    if ref:
                        payload["_members"][m["injection"]]["reference"] = ref
            # a re-injection made at the bench files as its original, whether
            # it was requested under the issued name or the name in force
            payload["_members"].update(extraction_batch.reinjection_aliases(
                extraction_batch.load_requests(batch), extraction_batch.answering_members(members)))
            payload["_members"] = extraction_batch.mark_withheld(
                extraction_batch.by_alias(payload["_members"], members), members)
        # per-sample amount / final volume, also under a reserved key
        amounts = extraction_batch.by_alias(get_sample_amounts(batch), members)
        if amounts:
            payload = dict(payload)
            payload["_samples"] = amounts
        # the ids of the extraction corrections these members carry: the
        # worker records as applied only those the run manifest names too
        from senaite.pfas import extraction_amendments as ea
        applied = ea.judged_ids(extraction_batch.amendments_state(batch))
        if applied:
            payload = dict(payload)
            payload["_amendments"] = applied
        return json.dumps(payload)


class PFASInstrumentArchiveSweepView(BrowserView):
    """
    POST @@pfas-instrument-archive-sweep

    The worker asks once a day. With the System switch "Delete archived
    re-injection files" off (as it is unless a Site Administrator turns it
    on), nothing is read and nothing deleted. On, each archived instrument
    file is kept or deleted as instrument_files.decide says, naming why:
    {"enabled", "files": [{"file", "deleted", "reason"}]}. A file deleted
    keeps its run-files entry, marked deleted with its sha256, and its
    worksheet's log names it; the file goes once that record is committed.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        from senaite.pfas.browser.perms import require_manager, disable_csrf, may_run_worker_tasks
        # a manager's, or the worker's daily sweep under its own account
        if not (require_manager(self.context, self.request) or may_run_worker_tasks(self.context)):
            return refuse(self.request, json.dumps({"error": "Manager role required"}))
        disable_csrf(self.request)
        if (self.request.get("REQUEST_METHOD") or "").upper() != "POST":
            self.request.response.setStatus(405)
            self.request.response.setHeader("Allow", "POST")
            return json.dumps({"error": "POST required"})
        import sqlite3
        from bika.lims import api as _api
        from senaite.pfas import extraction_batch, instrument_files, raw_share
        from senaite.pfas.annotation_store import read_json
        from senaite.pfas.browser.run_builder import RUN_FILES_KEY, UPLOAD_DIR
        from senaite.pfas.provenance_store import DEFAULT_DB_PATH
        from senaite.pfas.qc_deviation import get_registry
        portal = _api.get_portal()
        enabled = raw_share.load(portal).get("delete_reinjection_files") is True
        if not enabled:
            return json.dumps({"enabled": False, "files": []})
        from senaite.pfas import after_commit, records
        from senaite.pfas.config_history import now
        run_files, worksheets, verified = {}, {}, set()
        for brain in _api.search({"portal_type": "Worksheet"}, "senaite_catalog_worksheet"):
            ws = brain.getObject()
            entries = read_json(ws, RUN_FILES_KEY, [])
            if entries:
                run_files[ws.getId()], worksheets[ws.getId()] = entries, ws
                # what is reported is final, and nothing more is imported, once verified
                if _api.get_review_status(ws) == "verified":
                    verified.add(ws.getId())
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        try:
            planned = instrument_files.plan(
                UPLOAD_DIR, conn, run_files,
                lambda ws_id: extraction_batch.load_requests(worksheets[ws_id]),
                get_registry(portal), enabled, verified,
                lambda ws_id: extraction_batch.load(worksheets[ws_id]))
        finally:
            conn.close()
        at = now()
        for f in planned:
            if not f["delete"]:
                continue
            # the record outlives the file: the entry stays, marked deleted
            # with its checksum, and the worksheet's log names both
            for ws_id in f["worksheets"]:
                ws = worksheets[ws_id]
                IAnnotations(ws)[RUN_FILES_KEY] = json.dumps(instrument_files.mark_deleted(
                    run_files[ws_id], f["file"], f["sha256"], at))
                records.log(ws, u"instrument file deleted",
                            reason=u"%s, sha256 %s: %s" % (f["file"], f["sha256"], instrument_files.DELETED_REASON))
            after_commit.run_once("instrument-file:" + f["file"], instrument_files.remove,
                                  UPLOAD_DIR, f["file"], f["sha256"])
        files = [{"file": f["file"], "deleted": f["delete"], "reason": f["reason"]} for f in planned]
        gone = [f["file"] for f in files if f["deleted"]]
        if gone:
            logger.info("instrument archive: deleting %s once recorded", ", ".join(gone))
        return json.dumps({"enabled": True, "files": files})
