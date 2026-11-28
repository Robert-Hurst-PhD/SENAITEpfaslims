# -*- coding: utf-8 -*-
"""
@@pfas-run-builder — LC-MS Run Builder (Bench).

Everything derives from the relational spine — nothing method-specific is
hardcoded here:
  * batch → METHOD by the one resolver every page uses (batch_method.of:
    the analyses' method, core's Batch Method, the guided extraction's
    session, then the extraction record);
  * the extraction batch's members supply the per-sample rows — sample id,
    MATRIX (varies per sample) and SPIKE — then the guided extraction's
    sample table (extraction_store), with the batch's linked samples
    (matrix = core SampleType) as fallback;
  * CCV interval comes from the method profile
    (instrument_verification.ccv.frequency);
  * analyst initials come from the laboratory staff pool (LabContacts).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import csv
import hashlib
import io
import json
import logging
import os
import re
from datetime import datetime

try:
    from urllib import quote_plus
except ImportError:                                         # Python 3
    from urllib.parse import quote_plus

from zope.annotation.interfaces import IAnnotations
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas import lab_time
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (MANAGER_ROLES, TIER_CONFIG, deny_gated_action,
                                        disable_csrf, has_role_at_portal)

logger = logging.getLogger("senaite.pfas.browser.run_builder")


def _first(value, default=u""):
    """First value if the form field arrived as a list (Zope merges duplicate
    query-string + POST-body params into a list — e.g. batch_id, which is both
    in the page URL from the batch selector and a hidden field in the build/
    upload forms). Returns a string so .strip()/.splitlines() are always safe."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else default
    return default if value is None else value


RUN_MANIFEST_KEY = u"senaite.pfas.run_manifest"

# QC made at extraction (the extraction batch's members); the rest of a run
# template's tokens are instrument QC (CAL / ICV / CCV / CCB) the run adds
from senaite.pfas.extraction_batch import QC_ROLES as _QC_ROLES
EXTRACTION_QC = frozenset(r.upper() for r in _QC_ROLES)

# The run files uploaded for an extraction batch ([{file, kind, at}], a
# supplementary run's with the requests it carried): a supplementary run is
# processed together with them.
RUN_FILES_KEY = u"senaite.pfas.run_files"
UPLOAD_DIR = os.environ.get("PFAS_INSTRUMENT_UPLOAD_DIR",
                            "/addon/data/instrument_output")


def _about(ws_id, title):
    """What a worksheet's title says beyond its id (the client batch): the
    landing shows it beside the id's button, never the id twice."""
    title = title or u""
    if title.startswith(ws_id):
        return title[len(ws_id):].lstrip(u" \u00b7")
    return title


def ready_batches(portal, request):
    """The extraction batches ready to build: their extraction finalized
    and no run built yet, or the run sent back. [{"id", "title", "about",
    "sent_back", "url"}], for the Run Builder and the Bench landing."""
    from bika.lims import api
    from senaite.pfas import send_back as sb
    from senaite.pfas.annotation_store import read_json
    from senaite.pfas.browser.extraction_guide import _load_session, extraction_queue
    out = []
    for r in extraction_queue(portal, request):
        hits = api.search({"portal_type": "Worksheet", "getId": r["id"]}, "senaite_catalog_worksheet")
        ws = api.get_object(hits[0]) if hits else None
        if ws is None:
            continue
        manifest = read_json(ws, RUN_MANIFEST_KEY, {})
        # a built run is listed again once sent back (a rejected lot)
        if manifest and not sb.blocks_release(manifest):
            continue
        if not (_load_session(ws) or {}).get("finalized"):
            continue
        out.append({"id": r["id"], "title": r.get("title") or r["id"], "about": _about(r["id"], r.get("title")),
                    "sent_back": (manifest.get("sent_back") or {}).get("reason") or u"",
                    "url": u"%s/@@pfas-run-builder?batch_id=%s" % (portal.absolute_url(), r["id"])})
    return out


def in_progress_batches(portal, request):
    """The extraction batches whose run is built and waits at a later step
    (run_plan.waiting_step, from the manifest, the run files, the review
    requests and the worker's import log): [{"id", "title", "about",
    "step", "label", "url"}], each url opening the run at that step, for
    the Run Builder's landing."""
    from bika.lims import api
    from senaite.pfas import extraction_batch as eb
    from senaite.pfas import run_plan
    from senaite.pfas.browser.extraction_guide import extraction_queue
    # the import log only adds its signals (results imported with no
    # upload, an import failed): unread, the list stands without them
    try:
        from senaite.pfas.qc.store import QCResultStore, DEFAULT_DB_PATH
        store = QCResultStore(DEFAULT_DB_PATH)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("in progress: import log unread: %s", exc)
        store = None
    labels = dict(run_plan.WAITING)
    out = []
    for r in extraction_queue(portal, request):
        hits = api.search({"portal_type": "Worksheet", "getId": r["id"]}, "senaite_catalog_worksheet")
        ws = api.get_object(hits[0]) if hits else None
        if ws is None:
            continue
        ann = IAnnotations(ws)
        try:
            manifest = json.loads(ann.get(RUN_MANIFEST_KEY) or u"{}")
            files = json.loads(ann.get(RUN_FILES_KEY) or u"[]")
        except ValueError:
            continue
        if not manifest:
            continue
        imports = []
        if store is not None:
            try:
                imports = store.import_log(r["id"])
            except Exception as exc:                        # noqa: BLE001
                logger.warning("in progress: import log of %s unread: %s", r["id"], exc)
        step = run_plan.waiting_step(manifest, files, eb.load_requests(ws), imports)
        if step is None:
            continue
        out.append({"id": r["id"], "title": r.get("title") or r["id"], "about": _about(r["id"], r.get("title")),
                    "step": step, "label": labels[step],
                    "url": u"%s/@@pfas-run-builder?batch_id=%s&step=%s" % (portal.absolute_url(), r["id"], step)})
    return out


NOT_FINALISED = u"Extraction not finalised"
RUN_DONE = u"Run built and its results imported"


def stages_recorded(row):
    """An extraction's state as its batch record's stages say it: "N of M
    stages recorded", or "Not started" before any (extraction_queue row)."""
    total, done = row.get("total") or 0, row.get("done") or 0
    if not total:
        return row.get("label") or u""
    return u"%d of %d stages recorded" % (done, total)


BUILD_REFUSED = u"Extraction not finalised: finalise it in the Extraction Guide, then build the run."


def build_refusal(session):
    """Why a run may not be built for a worksheet, or None: its extraction
    (the guided extraction's session) is not finalised. The same test the
    Ready to build list reads."""
    return None if (session or {}).get("finalized") else BUILD_REFUSED


def not_ready_reason(row):
    """Why an open worksheet is neither ready to build nor waiting at a
    later step, from its extraction queue row (extraction_queue): its
    extraction not finalised, else its run built and its results in."""
    if not row.get("finalized"):
        return NOT_FINALISED
    return RUN_DONE


def other_batches(portal, request, listed):
    """Every open worksheet the two lists do not hold (`listed`: their
    ids), each with its extraction's state and the reason it is not ready:
    [{"id", "about", "state", "reason", "url", "next_label", "next_url"}],
    the next button opening the page where it moves on (the Extraction
    Guide, or Data Review once its results are in)."""
    from senaite.pfas.browser.extraction_guide import extraction_queue
    base = portal.absolute_url()
    out = []
    for r in extraction_queue(portal, request):
        if r["id"] in listed:
            continue
        reason = not_ready_reason(r)
        if reason == NOT_FINALISED:
            nxt = (u"Extraction Guide", u"%s/@@pfas-extraction-guide?batch_uid=%s" % (base, r["uid"]))
        else:
            nxt = (u"Data Review", u"%s/worksheets/%s/@@pfas-data-review" % (base, r["id"]))
        out.append({"id": r["id"], "about": _about(r["id"], r.get("title")),
                    "state": stages_recorded(r), "reason": reason,
                    "url": u"%s/@@pfas-run-builder?batch_id=%s" % (base, r["id"]),
                    "next_label": nxt[0], "next_url": nxt[1]})
    return out


# Building a run and requesting one are bench work. The run template is
# method configuration, and the export upload is what the worker imports.
RUN_BUILDER_GATES = {
    "save_template": TIER_CONFIG,
    "upload_export": TIER_CONFIG,
}


# What the Run Builder accepts as an instrument export: the worker's
# watched export types (pipeline.WATCHED_TYPES less its own .rawrun). The
# worker's control files (.rawrun, .rawexpect.json, _extraction.json,
# .rawstatus.json, .rawfail) are written only by the LIMS and the worker.
EXPORT_TYPES = (".csv", ".txt", ".tsv")



def _worksheet_by_id(ws_id):
    from bika.lims import api
    hits = api.search({"portal_type": "Worksheet", "getId": ws_id}, "senaite_catalog_worksheet") if ws_id else []
    return api.get_object(hits[0]) if hits else None


def acid_basis_of(portal, batch_obj, find=None):
    """(analytes, known): the analytes whose calibration lots, as loaded
    for the curve's run (its run manifest), are all stated as acid
    (run_lots.acid_analytes). A run reusing an earlier curve takes the
    curve run's basis -- one curve, one basis; `known` is False when that
    run cannot be found. `find(batch id)` gives that run's worksheet. The
    run record carries this to the worker, and the certificate reads it
    again from the same manifest, so a result's reporting limit and its
    salt correction follow one basis."""
    from senaite.pfas import run_lots
    from senaite.pfas.browser.prepared_standards import _get
    find = find or _worksheet_by_id

    def manifest_of(obj):
        try:
            return json.loads(IAnnotations(obj).get(RUN_MANIFEST_KEY) or "{}") if obj is not None else {}
        except (TypeError, ValueError):
            return {}
    manifest = manifest_of(batch_obj)
    cal = manifest.get("calibration") or {}
    if cal.get("new_curve") is False:
        try:
            from senaite.pfas.qc.store import QCResultStore, DEFAULT_DB_PATH
            rows = QCResultStore(DEFAULT_DB_PATH).get_calibrations(method=manifest.get("method_id"), limit=500)
        except Exception:                               # noqa: BLE001
            rows = []
        bid = run_lots.curve_batch(rows, (cal.get("last_curve") or {}).get("run_date"))
        manifest = manifest_of(find(bid)) if bid else {}
        if not manifest:
            return [], False
    lots = [lot for slot, lot in (manifest.get("standards") or {}).items()
            if (slot or u"").upper().startswith(u"CAL-") and lot.get("kind") == u"prepared_standard"]
    return run_lots.acid_analytes([(_get(portal, lot.get("uid")) or {}).get("analyte_concentrations") or []
                                   for lot in lots]), True


def analysis_acid_basis(analysis, cache):
    """The acid-basis analytes of the run an analysis was measured in (its
    worksheet's, acid_basis_of), [] when it is on no worksheet or the
    curve's run is not found (the method's salt factors apply, as the
    worker applies them). `cache` {worksheet id: analytes} spans one page."""
    try:
        ws = analysis.getWorksheet()
    except Exception:                                   # noqa: BLE001
        ws = None
    if ws is None:
        return []
    key = ws.getId()
    if key not in cache:
        try:
            from bika.lims import api
            cache[key] = acid_basis_of(api.get_portal(), ws)[0]
        except Exception as exc:                        # noqa: BLE001
            logger.warning("acid basis of %s: %s", key, exc)
            cache[key] = []
    return cache[key]

class PFASRunBuilderView(ViewHelpers, BrowserView):
    template = ViewPageTemplateFile("templates/run_builder.pt")

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            denied = deny_gated_action(
                self.context, self.request, action, RUN_BUILDER_GATES)
            if denied is not None:
                return denied
            disable_csrf(self.request)
            if action == "build":
                return self._handle_build()
            if action == "upload_export":
                return self._handle_upload_export()
            if action == "save_template":
                return self._handle_save_template()
            if action == "make_request":
                return self._handle_make_request()
            if action == "mark_loaded":
                return self._handle_mark_loaded()
        if action == "download_csv":
            return self._handle_download_csv()
        if action == "download_masslynx":
            return self._handle_download_masslynx()
        return self.template()

    # ── helpers ───────────────────────────────────────────────────────────
    def ok_msg(self):
        return self.request.form.get("ok", "")

    error = None

    def error_msg(self):
        return self.error or self.request.form.get("error", "")

    def selected_batch(self):
        """The worksheet the run is for: the form's batch_id, else the
        worksheet whose address the page was opened under."""
        bid = _first(self.request.form.get("batch_id", ""))
        if not bid and getattr(self.context, "portal_type", "") == "Worksheet":
            bid = self.context.getId()
        return bid

    def import_problems(self):
        """The selected worksheet's delivered runs the worker has not
        imported (import_log; "will import it" was promised and a failure
        never shown), a refused one with them."""
        b = self._batch()
        if b is None:
            return []
        try:
            from senaite.pfas.qc.store import QCResultStore, DEFAULT_DB_PATH
            return QCResultStore(DEFAULT_DB_PATH).import_problems(b.getId(), refused=True)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("import_problems: %s", exc)
            return []

    def _batch(self, batch_id=None):
        """The extraction batch: a WORKSHEET by id; a
        client Batch id (an older link) is followed to its worksheet."""
        from bika.lims import api
        from senaite.pfas import extraction_batch
        from senaite.pfas.batch_ref import get_batch
        bid = batch_id or self.selected_batch()
        if not bid:
            return None
        hits = api.search({"portal_type": "Worksheet", "getId": bid}, "senaite_catalog_worksheet")
        if hits:
            return api.get_object(hits[0])
        b = get_batch(self._portal(), bid)
        return extraction_batch.home(b) if b is not None else None

    def _client(self, b):
        """The client Batch of an extraction batch (its prep log and project)."""
        from senaite.pfas import extraction_batch
        if b is not None and extraction_batch.is_worksheet(b):
            return extraction_batch.linked_batch(b)
        return b

    def _members(self, b):
        from senaite.pfas import extraction_batch
        return extraction_batch.load(b) if b is not None and extraction_batch.is_worksheet(b) else []

    def qc_members(self, b):
        """{role: [injection]} of the extraction batch's QC members, in order."""
        out = {}
        for m in self._members(b):
            if m.get("role") and m.get("role") != u"Sample":
                out.setdefault(m["role"].upper(), []).append(m.get("injection"))
        return out

    # ── supplementary runs: what review asked for, made at the bench ──

    def made_requests(self, b=None):
        """Requests made at the bench and not yet run."""
        from senaite.pfas import extraction_batch
        b = b if b is not None else self._batch()
        if b is None or not extraction_batch.is_worksheet(b):
            return []
        # a planned dilution run with its sample's run is in that run already
        return [r for r in extraction_batch.load_requests(b) if r.get("status") == u"made" and not r.get("in_run")]

    # The landing's lists. A list that cannot be read is None, which the
    # page says ("Could not list the worksheets"), never an empty list.
    # Each is read once per page.
    def ready_to_build(self):
        if not hasattr(self, "_ready"):
            try:
                self._ready = ready_batches(self._portal(), self.request)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("ready to build: %s", exc)
                self._ready = None
        return self._ready

    def in_progress(self):
        if not hasattr(self, "_going"):
            try:
                self._going = in_progress_batches(self._portal(), self.request)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("in progress: %s", exc)
                self._going = None
        return self._going

    def other_worksheets(self):
        """Every open worksheet neither list holds, with its state and why
        it is not ready (other_batches); None when they cannot be read."""
        ready, going = self.ready_to_build(), self.in_progress()
        if ready is None or going is None:
            return None
        listed = set(r["id"] for r in (ready or []) + (going or []))
        try:
            return other_batches(self._portal(), self.request, listed)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("other worksheets: %s", exc)
            return None

    def selected_not_ready(self):
        """The chosen worksheet when its extraction is not finalised, which
        refuses a build: {"id", "state", "reason", "guide_url"}; else None."""
        if hasattr(self, "_not_ready"):
            return self._not_ready
        self._not_ready = None
        bid = self.selected_batch()
        if not bid:
            return None
        try:
            from senaite.pfas.browser.extraction_guide import extraction_queue
            rows = [r for r in extraction_queue(self._portal(), self.request) if r["id"] == bid]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("selected not ready: %s", exc)
            return None
        if not rows or not_ready_reason(rows[0]) != NOT_FINALISED:
            return None
        r = rows[0]
        self._not_ready = {"id": bid, "state": stages_recorded(r), "reason": NOT_FINALISED,
                           "guide_url": u"%s/@@pfas-extraction-guide?batch_uid=%s" % (self.portal_url(), r["uid"])}
        return self._not_ready

    def review_requests(self, b=None):
        """Step 4: every dilution and re-injection review asked for on this
        batch, open or made, with what the table shows (dilution_make.listed)."""
        from senaite.pfas.dilution_make import listed
        return listed(b if b is not None else self._batch())

    def make_options(self):
        """The Make dialog's choices (dilution_make.options)."""
        from senaite.pfas.dilution_make import options
        return options(self._portal())

    def _handle_make_request(self):
        """Step 4's Make: a request made at the bench, its injection named; a
        dilution records its vial's prep and is written to the extraction
        record the worker reads (dilution_make.make, as the guided
        extraction's Dilutions stage does)."""
        from senaite.pfas import entry_rights
        from senaite.pfas.dilution_make import make
        from senaite.pfas.browser.staff import may_enter
        if not may_enter():                 # it writes the extraction log
            self.error = entry_rights.REFUSAL
            return self.template()
        f = self.request.form
        b = self._batch(f.get("batch_id"))
        at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        error = make(b, f, self._current_user_name(), at, self.dilution_settings(b) if b is not None else None)
        if error:
            self.error = error
            return self.template()
        self.request.response.redirect(u"%s/@@pfas-run-builder?batch_id=%s#step-4" % (
            self.portal_url(), f.get("batch_id") or u""))
        return u""

    def _current_user_name(self):
        try:
            from bika.lims import api
            u = api.get_current_user()
            return u.getProperty("fullname") or u.getId()
        except Exception:                                   # noqa: BLE001
            return u""

    def run_files(self, b):
        from senaite.pfas.annotation_store import read_json
        return read_json(b, RUN_FILES_KEY, [])

    def _supplementary_rows(self, b, initials, method_id, include_cal, std, ccv):
        """Opening checks for the curve decision, the made requests under
        their LIMS-issued names, a bracket every `ccv` injections, a closing
        bracket."""
        from senaite.pfas import extraction_batch, run_plan
        run_date = lab_time.today()
        method_code = self._method_code(method_id)
        tpl = self.run_template(method_id)
        bracket = tpl["bracket_qc"] or "CCV"
        roles = dict((m.get("injection"), m.get("role")) for m in extraction_batch.load(b))
        rows, counters = [], {}

        def add(name, typ, desc, role=u""):
            # `role` is the row's own kind: its type column draws that kind's symbol
            rows.append({"vial": len(rows) + 1, "name": name, "type": typ, "description": desc, "role": role})

        def add_qc(code):
            counters[code] = counters.get(code, 0) + 1
            name, desc = self._qc_injection(code, initials, u"", run_date, counters[code], std, method_code)
            add(name, self.qc_injection_type(code), desc, code.upper())

        for tok in run_plan.opening([], include_cal, self._profile(method_id)):
            if tok == "CAL":
                for name, typ, desc in self._cal_rows(method_id, run_date, initials, std):
                    add(name, typ, desc, u"CAL")
            else:
                add_qc(tok)
        n = 0
        for r in self.made_requests(b):
            role = roles.get(r["injection"]) or u"Sample"
            what = (u"dilution 1 in %s of %s" % (r["fold"], r["injection"]) if r["kind"] == u"dilution"
                    else u"re-injection of %s" % r["injection"])
            add(r["new_injection"], self.qc_injection_type(role.upper()) if role != u"Sample" else "Sample",
                u"%s · %s · %s" % (initials, what, run_date.isoformat()),
                u"Dilution" if r["kind"] == u"dilution" else role)
            n += 1
            if n % max(1, int(ccv or 1)) == 0:
                add_qc(bracket)
        if not rows or rows[-1]["name"].find(bracket) < 0:
            add_qc(bracket)
        return rows

    def last_curve(self, method_id):
        """{run_date, status} of the method's most recent calibration on record
        (every analyte's curve of that run; approved only when all are)."""
        try:
            from senaite.pfas.qc.store import QCResultStore, DEFAULT_DB_PATH
            rows = QCResultStore(DEFAULT_DB_PATH).get_calibrations(method=method_id, limit=500) or []
        except Exception:                                   # noqa: BLE001
            return None
        if not rows:
            return None
        last = max(str(r.get("run_date") or "")[:10] for r in rows)

        def state(r):
            # the Calibrations page approves a run by recording who and when
            # (approve_run), leaving `status` as it was
            st = (r.get("status") or u"pending").lower()
            if st == u"rejected":
                return st
            return u"approved" if (st == u"approved" or r.get("approved_by")) else st
        states = set(state(r) for r in rows if str(r.get("run_date") or "")[:10] == last)
        status = u"approved" if states == set([u"approved"]) else sorted(states - set([u"approved"]))[0]
        return {"run_date": last, "status": status}

    def curve_decision(self, b=None):
        from senaite.pfas import run_plan
        b = b if b is not None else self._batch()
        mid = self.batch_method(b) if b is not None else u""
        if not mid:
            return None
        d = run_plan.curve_decision(self._profile(mid), self.last_curve(mid), lab_time.today().isoformat())
        d["last"] = self.last_curve(mid)
        return d

    # ── method / extraction-log resolution (all dynamic) ─────────────────
    def batch_method(self, batch=None):
        """Method id for the selected batch, by the one resolver (batch_method.of)."""
        b = batch or self._batch()
        if b is None:
            return ""
        from senaite.pfas import batch_method as bm
        try:
            return bm.of(b) or ""
        except Exception:                                   # noqa: BLE001
            return ""

    def dilution_settings(self, batch=None):
        """The batch's dilution settings: its method's, with its project's
        overrides."""
        from senaite.pfas import method_profile_sections as mps
        b = batch or self._batch()
        try:
            from senaite.pfas.project_specs import profile_for_batch
            return mps.dilution_settings(profile_for_batch(self._portal(), b, self.batch_method(b)))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("dilution settings: %s", exc)
            return mps.dilution_settings({})

    def dilution_routes(self):
        """[(key, label)] the routes the batch's method allows."""
        from senaite.pfas.method_profile_sections import DILUTION_ROUTES
        allowed = self.dilution_settings()["routes"]
        return [r for r in DILUTION_ROUTES if r[0] in allowed]

    def _profile(self, method_id):
        try:
            from senaite.pfas.method_profile_store import get_profile
            return get_profile(self._portal(), method_id) or {}
        except Exception:
            return {}

    def extraction_logbook_slug(self, method_id):
        """The storage slug of the extraction record's sample table: one
        record for every method, the guided extraction (dilution_ref
        LOGBOOK_SLUG); none without a method."""
        from senaite.pfas.dilution_ref import LOGBOOK_SLUG
        return u"%s" % LOGBOOK_SLUG if method_id else u""

    def extraction_logbook_label(self, method_id):
        """The extraction record, named by its kind; never the storage
        slug or a form number."""
        return u"the guided extraction" if method_id else u""

    def ccv_interval(self, method_id, batch=None):
        """CCV frequency: project QAPP -> lab method profile -> published-
        method baseline, resolved via senaite.pfas.ruleset.resolve_for_batch
        -- the SAME three-tier path the numeric QC criteria already use.
        Never a form input.

        A project can tighten this (CCV every 5 samples instead of every
        10); a project-less batch (`batch=None`, or any batch with no linked
        project -- the default, and every batch that predates project
        support) falls straight through to the lab profile's
        instrument_verification.ccv.frequency exactly as this method read it
        directly before this change -- see ruleset.resolve()'s rule 3."""
        resolved = self._resolve_composition(method_id, batch, "ccv_frequency")
        try:
            return max(1, int(resolved))
        except (TypeError, ValueError):
            return 6

    def _resolve_composition(self, method_id, batch, key):
        """Resolve one QC-COMPOSITION key (ccv_frequency / lfsm_frequency /
        duplicate_all_samples) through project -> lab -> baseline via
        senaite.pfas.ruleset.resolve_for_batch -- the identical mechanism
        the numeric QC criteria already use. Returns the resolved value, or
        None if nothing resolves anywhere (a project-less batch with no lab
        value configured either -- both legitimate, never an error).

        Resolved DIRECTLY here, add-on side, because composition decides how
        THIS view builds a run -- never routed through
        senaite.pfas.resolved_criteria_store, which exists for the Py3
        pipeline worker's per-batch evaluation of already-produced results
        (see that module's docstring and); composition is a
        build-time decision that store was never meant to carry.
        """
        try:
            from senaite.pfas import ruleset
            from senaite.pfas import project_ref
            matrix = u""
            if batch is not None:
                try:
                    from senaite.pfas.browser.batch_project_viewlet import (
                        _batch_matrix)
                    matrix = _batch_matrix(self._portal(), batch) or u""
                except Exception:
                    matrix = u""
                if not matrix and project_ref.get_project_uid(batch):
                    # A project IS linked but its matrix can't be derived --
                    # the project tier is being SKIPPED, not "there is no
                    # override"; say so rather than resolving silently.
                    logger.warning(
                        "_resolve_composition(%s): batch %r is linked to a "
                        "project but its matrix could not be derived -- any "
                        "project-tier override for this key is being "
                        "skipped, not applied", key, batch)
            resolved = ruleset.resolve_for_batch(
                self._portal(), batch, method_id, matrix or None, key)
            return resolved.value
        except Exception as exc:
            logger.warning("_resolve_composition(%s) failed: %s", key, exc)
            return None

    # ── run template (per-method, editable) ──────────────────────────────
    #
    # A run template is ONE ordered sequence of injection tokens describing HOW
    # a worklist is assembled. Tokens are: a QC code (MB, LFB, ICV, LFSM, …),
    # the special "CAL" token (the calibration ladder), and exactly one
    # "SAMPLES" token (the batch's field samples). Stored on the method profile
    # (senaite.pfas.method_profiles) so the METHOD owns its sequence (§3). QC
    # codes are the canonical Reference-Definition vocabulary the control charts
    # / method profiles use — the run builder never invents its own QC list.
    #
    # CCV bracketing (user-confirmed): the CAL token
    # expands to the ladder + one OPENING bracket injection and starts the
    # bracketed BODY; every injection in the body — extracted QC AND field
    # samples alike — counts toward the "CCV every N" interval (N = the method's
    # own CCV frequency); a CLOSING bracket ends the run. Extracted QC therefore
    # sit INSIDE the bracketing simply by being placed after CAL in the
    # sequence. Tokens before CAL (e.g. a system MeOH blank) are pre-bracket.

    SAMPLES_TOKEN = "SAMPLES"

    def _default_run_template(self, profile):
        """Sensible starting sequence derived from the method's own QC types.

        Reproduces the historic order (system MB, calibration, ICV, MB, LFB for
        methods that use it, samples, matrix-spike QC) as a single editable
        sequence. The opening/interval/closing CCVs are inserted automatically
        at build time, so no literal bracket token is seeded."""
        from senaite.pfas.qc.qc_types import enabled_qc_types
        assoc = [str(c).upper() for c in enabled_qc_types(profile)]
        seq = ["MB", "CAL", "ICV", "MB"]
        if "LFB" in assoc:
            seq.append("LFB")
        seq.append(self.SAMPLES_TOKEN)
        seq += [q for q in ("LFSM", "LFSMD") if q in assoc]
        return {"sequence": seq, "bracket_qc": "CCV"}

    def run_template(self, method_id):
        """The saved run template for a method, else the derived default.

        Migrates the legacy {opening, closing} shape to a single sequence:
        opening + SAMPLES + closing (a trailing literal CCV in the old closing
        block is harmless — build_sequence de-dupes the auto closing CCV)."""
        prof = self._profile(method_id)
        tpl = prof.get("run_template")
        if isinstance(tpl, dict):
            if tpl.get("sequence"):
                return {
                    "sequence":   [str(c) for c in tpl["sequence"]],
                    "bracket_qc": str(tpl.get("bracket_qc") or "CCV"),
                }
            if tpl.get("opening") or tpl.get("closing"):
                seq = [str(c) for c in (tpl.get("opening") or [])]
                seq.append(self.SAMPLES_TOKEN)
                seq += [str(c) for c in (tpl.get("closing") or [])]
                return {"sequence": seq,
                        "bracket_qc": str(tpl.get("bracket_qc") or "CCV")}
        return self._default_run_template(prof)

    def current_template(self, method_id=None):
        """A method's run template as the editor draws it: the selected
        batch's method, or the one named (the method profile's Run Template
        tab, which has no batch: the field samples are counted as none)."""
        on_batch = method_id is None
        method_id = method_id or self.batch_method()
        if not method_id:
            return None
        tpl = self.run_template(method_id)
        vocab = {v["code"]: v["label"] for v in self.qc_vocabulary()}
        n = len(self.sample_rows()) if on_batch else 0
        # guarantee exactly one SAMPLES token so the UI always shows the block
        seq = [c for c in tpl["sequence"] if c != self.SAMPLES_TOKEN]
        insert_at = tpl["sequence"].index(self.SAMPLES_TOKEN) \
            if self.SAMPLES_TOKEN in tpl["sequence"] else len(seq)
        seq.insert(min(insert_at, len(seq)), self.SAMPLES_TOKEN)
        tpl["sequence_labelled"] = [self._chip(c, vocab, n) for c in seq]
        tpl["n_samples"] = n
        # how many injections each step takes: the calibrator list one per
        # level of the method's ladder, the field samples one each, a QC one
        try:
            from senaite.pfas.calibration_levels import levels
            n_levels = len(levels(self._profile(method_id)))
        except Exception:                                   # noqa: BLE001
            n_levels = 0
        for c in tpl["sequence_labelled"]:
            c["injections"] = (n_levels if c["kind"] == "cal" else
                               (n if c["kind"] == "samples" else 1))
        tpl["n_levels"] = n_levels
        return tpl

    def _chip(self, code, vocab, n_samples=0):
        """One row descriptor for the sequence editor."""
        if code == self.SAMPLES_TOKEN:
            return {"code": code, "kind": "samples", "removable": False,
                    "label": u"Field samples ({0})".format(n_samples)}
        if code == "CAL":
            return {"code": code, "kind": "cal", "removable": True,
                    "label": u"Calibrator list"}
        kind = "blank" if self.qc_injection_type(code) == "Blank" else "qc"
        return {"code": code, "kind": kind, "removable": True,
                "label": vocab.get(code, code)}

    def add_vocabulary(self):
        """QC types offered in the sequence add-list — the full vocabulary minus
        the bracket QC (CCV), which is inserted automatically from the method's
        CCV frequency, never placed by hand."""
        return [v for v in self.qc_vocabulary() if v["code"] != "CCV"]

    def _noncount_codes(self):
        """QC codes that DON'T advance the CCV interval — the instrument
        calibration/verification injections (the calibrator ladder, ICV, CCV).
        They are counted like calibrators, not like body injections. Sourced
        from the Reference Definition 'instrument' category; constant fallback."""
        cache = getattr(self, "_noncount_cache", None)
        if cache is not None:
            return cache
        out = set()
        try:
            folder = self._portal().bika_setup.bika_referencedefinitions
            tagre = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")
            for d in folder.objectValues():
                cat = u""
                try:
                    cat = d.getField("pfas_category").get(d) or u""
                except Exception:
                    pass
                if cat != "instrument":
                    continue
                code = None
                try:
                    code = d.getField("pfas_qc_code").get(d)
                except Exception:
                    pass
                if not code:
                    m = tagre.search(d.Description() or u"")
                    code = m.group(1) if m else None
                if code:
                    out.add(code.upper())
        except Exception as exc:
            logger.warning("_noncount_codes: %s", exc)
        # CAL/ICV/CCV are instrument-cal; CCB is the solvent/system blank — all
        # ride with the calibration, none advance the sample CCV interval.
        out |= set(["CAL", "ICV", "CCV", "CCB"])
        self._noncount_cache = out
        return out

    def qc_vocabulary(self):
        """[{code,label}] of QC types, from the single Reference-Definition
        source the control charts and method profiles use."""
        try:
            from senaite.pfas.qc_labels import get_qc_label_map
            m = get_qc_label_map(self._portal())
        except Exception as exc:
            logger.warning("qc_vocabulary: %s", exc)
            m = {}
        return [{"code": k, "label": m[k]} for k in sorted(m)]

    def _blank_codes(self):
        """QC codes whose injection type is Blank (from the Reference
        Definition blank flag), with a conservative constant fallback."""
        cache = getattr(self, "_blank_cache", None)
        if cache is not None:
            return cache
        out = set()
        try:
            folder = self._portal().bika_setup.bika_referencedefinitions
            tagre = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")
            for d in folder.objectValues():
                code = None
                try:
                    code = d.getField("pfas_qc_code").get(d)
                except Exception:
                    pass
                if not code:
                    m = tagre.search(d.Description() or "")
                    code = m.group(1) if m else None
                if code and d.getBlank():
                    out.add(code.upper())
        except Exception as exc:
            logger.warning("_blank_codes: %s", exc)
        out |= set(["MB", "LRB", "MXB", "CCB"])
        self._blank_cache = out
        return out

    def qc_injection_type(self, code):
        """Worklist 'Sample Type' column for a QC code: Standard for the
        calibration ladder, Blank for blank QC types, QC otherwise."""
        if code == "CAL":
            return "Standard"
        return "Blank" if code.upper() in self._blank_codes() else "QC"

    def _extraction_log(self, batch, slug):
        raw = IAnnotations(batch).get(u"senaite.pfas.logbook." + str(slug))
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    def sample_rows(self, batch_id=None):
        """[{sample_id, matrix, spike}]: the extraction batch's members
        first, then the guided extraction's sample table; batch-linked
        samples (matrix = core SampleType) as fallback. Matrix varies PER
        SAMPLE; spike is per the sample table."""
        b = self._batch(batch_id)
        if b is None:
            return []
        method_id = self.batch_method(b)
        slug = self.extraction_logbook_slug(method_id) if method_id else ""
        rows = []
        members = self._members(b)
        if members:
            # the extraction batch's samples, under their LIMS-issued names;
            # its QC members are placed by build_sequence
            # role from the record: a blank role sent build_sequence to guess
            # one from the Client Sample ID, and a sample whose id held
            # "CCV" / "ICV" / "LFB" (SYNTH-ccv_high-W1)
            # took that QC's place -- the run lost its CCV
            return [{"sample_id": m.get("sample_id") or m.get("injection"),
                     "injection": m.get("injection"), "matrix": m.get("matrix") or u"",
                     "role": u"Sample", "spike": u"", "client_sample_id": m.get("client_sid") or u""}
                    for m in members if m.get("role") == u"Sample"]
        if slug:
            log = self._extraction_log(b, slug)
            for key in ("samples", "sample_rows", "rows"):
                for r in (log.get(key) or []):
                    if not isinstance(r, dict):
                        continue
                    sid = r.get("sample_id") or r.get("id") or r.get("name")
                    if not sid:
                        continue
                    rows.append({
                        "sample_id": sid,
                        # NOTE: log field `sample_type` is the QC ROLE
                        # (Sample/Dup/MB), NOT the matrix — never use it here.
                        "matrix": r.get("matrix") or "",
                        "role": r.get("sample_type") or r.get("role") or "",
                        "spike": r.get("spike_ppt") or r.get("spike") or "",
                    })
                if rows:
                    break
            if not rows:
                # spike may live at log level even when rows are elsewhere
                pass
        # enrich: rows without a matrix resolve it from the sample's REAL
        # core SampleType (matrix varies per sample — §3 link, not a form input)
        # Also pick up each sample's Client Sample ID. That is the field the
        # importer joins an instrument export on, so a worklist that proposes
        # anything else cannot round-trip: the analyst types the proposed name
        # at the instrument and the result then matches no sample.
        try:
            cat = getToolByName(self._portal(), "senaite_catalog_sample")
            for r in rows:
                # The extraction log names a sample however the bench writes
                # it — usually the Client Sample ID, not the lab id — so match
                # on either. Matching only on getId meant that filling in the
                # log stopped the lookup working and every sample picked up a
                # redundant method-code prefix in the worklist.
                brains = cat.unrestrictedSearchResults(
                    portal_type="AnalysisRequest", getId=r["sample_id"])
                if not brains:
                    brains = cat.unrestrictedSearchResults(
                        portal_type="AnalysisRequest",
                        getClientSampleID=r["sample_id"])
                for br in brains:
                    ar = br.getObject()
                    if not r.get("matrix"):
                        st = ar.getSampleType()
                        if st:
                            r["matrix"] = st.Title()
                    try:
                        r["client_sample_id"] = ar.getClientSampleID() or ""
                    except Exception:
                        r["client_sample_id"] = ""
                    break
        except Exception:
            pass
        if not rows:
            # fallback: batch-linked samples; matrix = the REAL SampleType
            try:
                cat = getToolByName(self._portal(), "senaite_catalog_sample")
                for br in cat(portal_type="AnalysisRequest", getBatchUID=b.UID()):
                    ar = br.getObject()
                    st = ar.getSampleType()
                    rows.append({
                        "sample_id": ar.getId(),
                        "matrix": st.Title() if st else "",
                        "spike": "",
                        "client_sample_id": (ar.getClientSampleID() or ""),
                    })
            except Exception:
                pass
        return rows

    def run_context(self):
        """Everything the form shows read-only, derived from the batch."""
        bid = self.selected_batch()
        if not bid:
            return None
        b = self._batch(bid)
        method_id = self.batch_method(b)
        slug = self.extraction_logbook_slug(method_id) if method_id else ""
        rows = self.sample_rows()
        return {
            "batch_id": bid,
            "method_id": method_id or "(unresolved)",
            "extraction_slug": slug,
            "extraction_label": self.extraction_logbook_label(method_id) or u"none set on the method",
            "ccv_interval": self.ccv_interval(method_id, batch=b) if method_id else 6,
            "rows": rows,
            "n_samples": len(rows),
        }

    # ── laboratory staff pool ─────────────────────────────────────────────
    def staff_pool(self):
        """Laboratory staff pool (single source: senaite.pfas.staff)."""
        try:
            from senaite.pfas.staff import list_staff
            return list_staff(self._portal(), active_with_login=True)
        except Exception as exc:
            logger.warning("staff_pool: %s", exc)
            return []

    def batches(self):
        """The open extraction batches (worksheets)."""
        try:
            from senaite.pfas.browser.extraction_guide import extraction_queue
            return [{"id": r["id"], "title": r["title"]}
                    for r in extraction_queue(self._portal(), self.request)]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("batches: %s", exc)
            return []

    # ── what the run loads (run_lots.py) ───────────────────────────────────

    RUN_LEDGER_STAGE = 100          # the run's lots in the usage ledger
    _QC_SLOT = {"QCS": "ICV", "CCC": "CCV"}

    def run_slots(self, method_id, new_curve=True):
        """[(key, label)] the run loads: the calibration levels and the ICV
        for a new curve, the CCV, one lot per LC solvent channel."""
        from senaite.pfas import calibration_levels as cl
        from senaite.pfas import run_lots
        from senaite.pfas.method_profile_sections import solvent_channels
        prof = self._profile(method_id)
        return run_lots.slots(len(cl.calibrators(prof)), solvent_channels(prof, u"lc"),
                              prof.get("qc_name_codes") or {}, new_curve)

    def _inventory(self):
        cache = getattr(self, "_inv_cache", None)
        if cache is None:
            from senaite.pfas.browser.bench_inventory import inventory_items
            cache = dict(("%s:%s" % (i["kind"], i["uid"]), i) for i in inventory_items(self._portal()))
            self._inv_cache = cache
        return cache

    def slot_options(self, key, method_id):
        """[(lot key, label)] usable today and made for this slot: a
        calibration level, check or LC channel takes the lots its
        preparation record made for it (run_lots.lots_for_slot); an LC
        channel also takes purchased solvent loaded as it is. Every kind
        of record is read: a single standard's record makes the check or
        channel lot its recipe names."""
        from senaite.pfas import prep_entries, run_lots
        from senaite.pfas.bench_queue import is_usable
        today = lab_time.today().isoformat()
        levels = getattr(self, "_levels_cache", None)
        if levels is None:
            levels = self._levels_cache = run_lots.levels_by_uid(prep_entries.list_entries(self._portal()))
        usable = [i for i in self._inventory().values() if is_usable(i, today)]
        out = []
        codes = self._profile(method_id).get("qc_name_codes") or {}
        for i in run_lots.lots_for_slot(key, usable, levels, self.run_slots(method_id, True), codes):
            label = u"%s \u00b7 %s \u00b7 exp %s" % (i.get("name") or u"", i.get("lot_number") or u"",
                                                    i.get("expiry") or u"?")
            if i["pending"]:
                label += u" \u00b7 pending acceptance"
            out.append((u"%s:%s" % (i["kind"], i["uid"]), label))
        return out

    def series_options(self, method_id):
        """The calibration series preparations that made every level,
        newest first; none prepared, none offered."""
        from senaite.pfas import prep_entries, run_lots
        return run_lots.series_options(prep_entries.list_entries(self._portal(), kind=u"series")[:30],
                                       self.run_slots(method_id, True))

    def _run_lots(self, method_id, include_cal):
        """(chosen, slots, lots by key) from the build form."""
        from senaite.pfas import prep_entries, run_lots
        sl = self.run_slots(method_id, include_cal)
        # the calibration levels come from one series preparation
        entries = prep_entries.list_entries(self._portal(), kind=u"series")
        return run_lots.from_series(self.request.form, entries, sl), sl, self._inventory()

    def _record_run_lots(self, batch_obj, standards, solvents, by, stage):
        """The run's lots in the usage ledger (a rebuild replaces them)."""
        try:
            from senaite.pfas import inventory_ledger, run_lots
            inventory_ledger.record_stage(
                None, batch_obj.UID(), batch_obj.getId(), stage, u"Run",
                run_lots.ledger_rows(standards, solvents), by,
                datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
        except Exception as exc:                            # noqa: BLE001
            logger.error("usage ledger not written for the run of %s: %s", batch_obj.getId(), exc)

    def _std_lot(self, std, code):
        """The lot loaded for a check / level: {"lot", "prepared_date"}."""
        code = (code or u"").upper()
        return (std or {}).get(code) or (std or {}).get(self._QC_SLOT.get(code, u"")) or {}

    # ── sequence construction ─────────────────────────────────────────────

    def _label_map(self):
        cache = getattr(self, "_lbl_cache", None)
        if cache is None:
            try:
                from senaite.pfas.qc_labels import get_qc_label_map
                cache = get_qc_label_map(self._portal())
            except Exception:
                cache = {}
            self._lbl_cache = cache
        return cache

    def _label(self, code):
        m = self._label_map()
        return m.get(code) or m.get(code.upper(), code)

    def _method_code(self, method_id):
        """The method's code in injection names (injection_names.py)."""
        from senaite.pfas import injection_names as nm
        return nm.method_code(self._profile(method_id), method_id)

    def _cal_rows(self, method_id, run_date, initials, std):
        """(name, type, description) per calibrator level, by the injection
        name scheme (injection_names.py): 537_CAL-1_261001, the standard's
        prep date (else the run's); the description holds the analyst, the
        prep date, the concentration, the lot and the level."""
        from senaite.pfas import calibration_levels as cl
        from senaite.pfas import injection_names as nm
        code = self._method_code(method_id)
        prof = self._profile(method_id)
        unit = cl.unit(prof)
        out = []
        # one calibrator per level of the METHOD PROFILE's curve
        for lvl, conc in cl.calibrators(self._profile(method_id)):
            loaded = self._std_lot(std, u"CAL-%d" % lvl)
            cal_lot, prep = loaded.get("lot") or u"", loaded.get("prepared_date") or u""
            day = prep or run_date.strftime("%Y-%m-%d")
            name = nm.standard(code, u"CAL", day, level=lvl)
            desc = nm.description(initials, u"prep %s" % prep if prep else u"run %s" % day,
                                  (u"%g %s" % (conc, unit)).strip() if conc is not None else u"",
                                  u"lot %s" % cal_lot if cal_lot else u"", nm.role_part(u"CAL", lvl))
            out.append((name, "Standard", desc))
        return out

    def _qc_injection(self, code, initials, matrix, run_date, seq, std,
                      method_code, name_code=None):
        """(name, description) for one QC injection. Injection name = the linked
        prepared-standard lot (cal/spike) + type; blanks & no-lot QC fall back to
        the method code. Description surfaces the lot + real prep date so the
        reviewer needn't open the logbook."""
        from senaite.pfas import injection_names as nm
        label = self._label(code)
        loaded = self._std_lot(std, code)
        lot, prep = loaded.get("lot") or u"", loaded.get("prepared_date") or u""
        day = prep or run_date.strftime("%Y-%m-%d")
        cu = code.upper()
        # the method's own name for the role (EPA 537.1: CCC, QCS); the role
        # itself is recorded on the row. By the scheme (injection_names.py):
        # 537_CCV_261006_02 -- each CCV / CCB in the run numbered, any other
        # check only when it repeats
        nc = name_code or cu
        repeat = u"%02d" % seq if (cu in (u"CCV", u"CCB", u"CCC") or seq > 1) else u""
        name = nm.standard(method_code, nc, day, repeat=repeat)
        kind = u"spike lot" if cu in ("LFB", "LFSM", "LFSMD") else u"lot"
        desc = nm.description(initials, u"prep %s" % prep if prep else u"run %s" % day,
                              matrix if not lot else u"", u"%s %s" % (kind, lot) if lot else u"", label)
        return name, desc

    def _planned(self, batch_obj, rows_in, initials):
        """{sample injection: planned dilution request run with this run}, the
        planned requests saved; (None, [why]) when one is refused."""
        from senaite.pfas import extraction_batch as eb
        from senaite.pfas.sample_table import plan_problem
        f, plans, refused = self.request.form, [], []
        settings = self.dilution_settings(batch_obj)
        for r in rows_in:
            sid = r.get("sample_id") or u""
            fold = eb.planned_fold(_first(f.get(u"pdil_pct.%s" % sid)), _first(f.get(u"pdil_take.%s" % sid)),
                                   _first(f.get(u"pdil_to.%s" % sid)))
            if fold:
                route = _first(f.get(u"proute.%s" % sid)) or u"extract"
                problem = plan_problem(fold, route, settings)
                if problem:
                    refused.append(u"%s: %s" % (sid, problem))
                plans.append({"injection": r.get("injection") or u"", "fold": fold, "route": route,
                              "runs": u"separately" if _first(f.get(u"pruns.%s" % sid)) == u"separately" else u"with"})
        if refused:
            return (None, refused)
        if not plans:
            return {}
        reqs, errors = eb.add_planned(eb.load_requests(batch_obj), self._members(batch_obj), plans, initials,
                                      datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
        if errors:
            return (None, errors)
        eb.save_requests(batch_obj, reqs)
        return dict((q["injection"], q) for q in reqs if q.get("planned") and q.get("in_run")
                    and q.get("status") == u"open")

    def build_sequence(self, sample_rows, initials, method_id, ccv_interval,
                       include_cal, std=None, duplicate_all_samples=None,
                       lfsm_frequency=None, qc_members=None, planned=None):
        """Assemble the injection worklist by walking the method's run sequence.

        Each row carries a lot-code injection NAME (the linked prepared-standard
        lot where one exists — cal lot / spike lot from the calibration series
        preparation — else the
        method code) and a human DESCRIPTION (analyst · QC type · lot · prep
        date). CAL opens the CCV-bracketed body; instrument-cal injections
        (CAL/ICV/CCV/CCB) don't advance the interval; extraction QC + samples do;
        a single closing CCV ends the run.

        `duplicate_all_samples` / `lfsm_frequency` are QC-COMPOSITION
        overrides (senaite.pfas.ruleset / senaite.pfas.run_composition) —
        applied ONLY inside the SAMPLES-token block, via
        run_composition.compose_sample_block(): every field sample optionally
        gets a duplicate injection, and an extra LFSM is optionally inserted
        every N field samples. Both are None by default, which is IDENTITY —
        a project-less batch (the caller's default) builds exactly the
        sequence it always has; see run_composition.py's docstring."""
        std = std or {}
        run_date = lab_time.today()
        sample_date = run_date.strftime("%Y-%m-%d")
        # QC rows use the run's dominant matrix (from the extraction log)
        matrices = [r.get("matrix") for r in sample_rows if r.get("matrix")]
        dom = max(set(matrices), key=matrices.count) if matrices else "Lab"
        method_code = self._method_code(method_id)
        tpl = self.run_template(method_id)
        bracket = tpl["bracket_qc"] or "CCV"
        seq = list(tpl["sequence"])
        if self.SAMPLES_TOKEN not in seq:
            seq.append(self.SAMPLES_TOKEN)          # samples are never optional
        # the calibration and its verification for this run's curve decision
        # (run_plan.opening; the method profile's rule, else the bench chemist)
        from senaite.pfas import run_plan
        seq = run_plan.opening(seq, include_cal, self._profile(method_id))
        # the extraction batch's QC members play their roles under their own
        # LIMS-issued names; roles the template lacks follow the samples
        placed = run_plan.place_members(seq, dict(qc_members or {}), self.SAMPLES_TOKEN)
        n = max(1, int(ccv_interval or 1))
        noncount = self._noncount_codes()           # instrument cal ≠ body count

        rows = []
        counters = {}
        # pending_open: the ladder has run, but the bracket has NOT opened yet.
        # It opens immediately before the first COUNTING injection, so
        # instrument-cal injections (ICV, solvent blank) placed after the
        # calibrators stay in the calibration block — outside the bracketing.
        state = {"in_body": False, "pending_open": False,
                 "count": 0, "last_bracket": False}

        def add(name, typ, desc=u"", role=u"", level=u""):
            # `role` is what the row IS (CAL, ICV, CCV, CCB, MB, LFB, LFSM,
            # LFSMD, Dup, Sample): the pipeline reads it from this record, so
            # an injection's name may use the method's own terms (EPA 537.1:
            # CCC, QCS) -- 
            rows.append({"vial": len(rows) + 1, "name": name,
                         "type": typ, "description": desc, "role": role, "level": level})
            state["last_bracket"] = False

        from senaite.pfas.method_profile_sections import name_code
        prof = self._profile(method_id)

        def add_qc(code):
            counters[code] = counters.get(code, 0) + 1
            name, desc = self._qc_injection(
                code, initials, dom, run_date, counters[code], std, method_code,
                name_code(prof, code))
            add(name, self.qc_injection_type(code), desc, code.upper())

        def emit_bracket():
            add_qc(bracket)
            state["count"] = 0
            state["last_bracket"] = True
            state["pending_open"] = False

        def open_bracket_if_needed():
            """Open the bracket lazily — right before the first counting row."""
            if state["pending_open"]:
                emit_bracket()

        def body_tick():
            state["count"] += 1
            if state["count"] >= n:
                emit_bracket()

        spikes = [r.get("spike") for r in sample_rows if r.get("spike")]

        # A QC role the batch already holds as a registered sample is NOT
        # generated again: MB, LFSM and LFSMD were each appearing twice, once
        # from the sequence and once from the sample list, giving 27 vial
        # positions for a 20-injection run. An entry with no matching sample
        # still produces its injection, so a batch that does not register its
        # blank as a sample is not silently run without one.
        roles_in_samples = set()
        for r in sample_rows:
            role = (r.get("role") or "").strip().upper()
            if not role:
                role = self._role_from_sample(r)
            if role:
                roles_in_samples.add(role)
        supplied_by_samples = set()

        for tok, member in placed:
            if member is not None:
                counts = state["in_body"] and tok.upper() not in noncount
                if counts:
                    open_bracket_if_needed()
                add(member, self.qc_injection_type(tok.upper()),
                    u"{0} · {1} · {2}".format(initials, tok.upper(), sample_date), tok.upper())
                supplied_by_samples.add(tok.upper())
                if counts:
                    body_tick()
                continue
            if qc_members is not None and tok.upper() in EXTRACTION_QC:
                # a batch with members holds ALL its extraction QC: a template
                # token it has no member for is not invented: every injection
                # name comes from the batch's record
                supplied_by_samples.add(tok.upper())
                continue
            if tok == "CAL":
                if include_cal:
                    # each calibrator's level rides on its row: the
                    # instrument's sample list has a LEVEL column
                    for n_cal, (name, typ, desc) in enumerate(self._cal_rows(
                            method_id, run_date, initials, std), 1):
                        add(name, typ, desc, u"CAL", u"%d" % n_cal)
                    # bracket does NOT open here — it opens at the first
                    # counting injection, leaving ICV/solvent blank outside
                    state["in_body"] = True
                    state["pending_open"] = True
                continue
            if tok == self.SAMPLES_TOKEN:
                if not state["in_body"]:
                    state["in_body"] = True     # no CAL: body starts at samples
                    state["pending_open"] = True
                open_bracket_if_needed()        # samples count → open now
                from senaite.pfas import run_composition
                for r, marker in run_composition.compose_sample_block(
                        sample_rows, duplicate_all_samples, lfsm_frequency):
                    if marker == "lfsm":
                        # An interval-driven extra LFSM (QAPP composition
                        # override). Emitted even if the batch also registers
                        # its own LFSM sample elsewhere in the sequence —
                        # more QC than the template calls for is always safe
                        # under the direction rule, so no suppression here.
                        add_qc("LFSM")
                        body_tick()
                        continue
                    mtx = r.get("matrix") or dom
                    sid = r["sample_id"]
                    # Prefer the sample's Client Sample ID: it is what the
                    # importer matches on, so this is the name that makes the
                    # run round-trip. Fall back to the method-prefixed lab id
                    # for samples that have none.
                    csid = (r.get("client_sample_id") or "").strip()
                    # the extraction batch's LIMS-issued name first
                    name = r.get("injection") or csid or u"{0}-{1}".format(method_code, sid)
                    if marker == "duplicate":
                        name = u"{0}-DUP".format(name)
                        desc = u"{0} · Duplicate of {1} · {2} · {3}".format(
                            initials, sid, mtx or u"Lab", sample_date)
                    else:
                        desc = u"{0} · Sample {1} · {2} · {3}".format(
                            initials, sid, mtx or u"Lab", sample_date)
                    add(name, "Sample", desc, u"Dup" if marker == "duplicate" else u"Sample")
                    body_tick()
                    plan = (planned or {}).get(name) if marker != "duplicate" else None
                    if plan:
                        # a planned dilution, never in place of the undiluted injection
                        add(plan["new_injection"], "Sample",
                            u"{0} · planned dilution 1 in {1} of {2} · {3}".format(initials, plan["fold"], sid, sample_date),
                            u"Sample")
                        body_tick()
                continue
            # a QC token
            if tok == bracket and state["in_body"]:
                emit_bracket()       # an explicitly-placed bracket injection
                continue             # resets the interval; never double-counts
            if tok == bracket and not include_cal:
                # a run on a reused curve opens with its bracket check
                # (run_plan.opening): that CCV opens the body, never a second
                emit_bracket()
                state["in_body"] = True
                continue
            # instrument-cal injections (CAL/ICV/CCV/CCB) ride with the
            # calibration: they neither open the bracket nor advance the CCV
            # interval. Extraction QC (MB/LFB/LFSM/LFSMD) and field samples do.
            if tok.upper() in roles_in_samples:
                supplied_by_samples.add(tok.upper())
                continue                 # the registered sample plays this role

            counts = state["in_body"] and tok.upper() not in noncount
            if counts:
                open_bracket_if_needed()    # bracket opens BEFORE this row
            add_qc(tok)
            if counts:
                body_tick()

        # closing bracket (skip if the run already ended on one)
        if state["in_body"] and not state["last_bracket"]:
            emit_bracket()

        # Every QC role the method's sequence asks for must end up with an
        # injection, from the sequence or from a registered sample.
        emitted = {r["name"] for r in rows}
        missing = []
        for tok in seq:
            code = tok.upper()
            if code == self.SAMPLES_TOKEN or code in supplied_by_samples:
                continue
            if not any(code in n.upper() for n in emitted):
                missing.append(tok)
        self._missing_roles = missing
        return rows, dom, (spikes[0] if spikes else "")

    def _role_from_sample(self, row):
        """QC role a registered sample plays, from its id. Only used to decide
        whether a sequence entry is redundant, never to alter a result.

        Delegates to senaite.pfas.run_composition.classify_sample_role, which
        also backs that module's is_field_sample() (duplicate_all_samples /
        lfsm_frequency must only ever touch genuine field samples) — one
        definition, not two copies drifting apart."""
        from senaite.pfas import run_composition
        return run_composition.classify_sample_role(row)

    def _close_notices(self, batch_obj):
        """A rebuilt run closes its sent-back notice (notices.py)."""
        from senaite.pfas import notices as nt
        if batch_obj is None:
            return
        portal = self._portal()
        store = nt.load(portal)
        if nt.close_run(store, batch_obj.getId(), nt.now()):
            nt.save(portal, store)

    # ── actions ───────────────────────────────────────────────────────────
    def _handle_build(self):
        f = self.request.form
        batch_id = _first(f.get("batch_id")).strip()
        initials = _first(f.get("initials")).strip().upper()
        if not batch_id:
            return self._redirect_err(batch_id, "Select a worksheet first")
        # a run is built only for a finalised extraction; the page shows the
        # reason beside the Extraction Guide button
        from senaite.pfas.browser.extraction_guide import _load_session
        ws = self._batch(batch_id)
        why = build_refusal(_load_session(ws) if ws is not None else None)
        if why:
            return self._redirect_err(batch_id, why)
        if not initials:
            return self._redirect_err(batch_id, "Select the analyst")
        # A new calibration curve or not: the method
        # profile's rule, else the bench chemist's answer; a curve not
        # approved or too old is never reused (run_plan.curve_decision).
        decision = self.curve_decision(self._batch(batch_id)) or {}
        answer = _first(f.get("new_curve")).strip()
        if decision.get("forced"):
            include_cal = decision["forced"] == u"new"
        elif answer in ("yes", "no"):
            include_cal = answer == "yes"
        else:
            return self._redirect_err(batch_id, "Say whether a new calibration curve is needed")
        method_id = self.batch_method(self._batch(batch_id))
        if not method_id:
            return self._redirect_err(
                batch_id, "Worksheet has no method — fill its extraction log first")
        rows_in = self.sample_rows(batch_id)
        # manual additions (one per line) are appended, matrix left blank
        for s in _first(f.get("extra_samples")).splitlines():
            s = s.strip()
            if s:
                rows_in.append({"sample_id": s, "matrix": "", "spike": ""})
        if not rows_in:
            return self._redirect_err(batch_id, "No samples to run")

        batch_obj = self._batch(batch_id)
        ccv = self.ccv_interval(method_id, batch=batch_obj)
        # QC-COMPOSITION overrides (senaite.pfas.ruleset / run_composition):
        # None for a project-less batch, which is IDENTITY -- see
        # build_sequence()'s docstring and run_composition.py.
        duplicate_all_samples = self._resolve_composition(
            method_id, batch_obj, "duplicate_all_samples")
        lfsm_frequency = self._resolve_composition(
            method_id, batch_obj, "lfsm_frequency")
        # what the instrument is loaded with: refused while a lot is missing
        # or out of date on the run date (run_lots.py)
        from senaite.pfas import run_lots
        chosen, slot_list, lots = self._run_lots(method_id, include_cal)
        problems = run_lots.problems(chosen, slot_list, lots, lab_time.today().isoformat())
        if problems:
            return self._redirect_err(batch_id, u" ".join(problems))
        standards, solvents = run_lots.for_manifest(chosen, lots)
        std = standards
        if _first(f.get("run_kind")) == "supplementary":
            made = self.made_requests(batch_obj)
            if not made:
                return self._redirect_err(batch_id, "No request made at the bench to run")
            rows = self._supplementary_rows(batch_obj, initials, method_id, include_cal, std, ccv)
            manifest = {"built_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                        "built_by": initials, "batch_id": batch_id, "method_id": method_id,
                        "kind": "supplementary", "requests": [r["id"] for r in made],
                        "ccv_interval": ccv, "worksheet_id": batch_obj.getId(),
                        "calibration": {"new_curve": bool(include_cal),
                                        "decided_by": (u"method profile" if decision.get("forced") else initials),
                                        "reason": decision.get("reason") or u"",
                                        "last_curve": decision.get("last") or None},
                        "standards": standards, "solvents": solvents,
                        "rows": rows}
            IAnnotations(batch_obj)[RUN_MANIFEST_KEY] = json.dumps(manifest)
            self._record_run_lots(batch_obj, standards, solvents, initials, self.RUN_LEDGER_STAGE)
            self._close_notices(batch_obj)
            self.request.response.redirect("{0}/@@pfas-run-builder?batch_id={1}&built=1".format(
                self.portal_url(), batch_id))
            return u""
        if self._members(batch_obj):
            # the batch's members already hold the plan's duplicates and
            # extra LFSMs (extraction_batch.plan_qc): never added twice
            duplicate_all_samples = lfsm_frequency = None
        # planned dilutions: each a dilution request marked planned;
        # one run with this run follows its sample in the sequence
        planned = self._planned(batch_obj, rows_in, initials)
        if isinstance(planned, tuple):
            return self._redirect_err(batch_id, u" ".join(planned[1]))
        rows, dom, spike = self.build_sequence(
            rows_in, initials, method_id, ccv, include_cal, std=std,
            duplicate_all_samples=duplicate_all_samples,
            lfsm_frequency=lfsm_frequency,
            qc_members=self.qc_members(batch_obj) if self._members(batch_obj) else None,
            planned=planned)
        manifest = {
            "built_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "built_by": initials,
            "batch_id": batch_id,
            "method_id": method_id,
            "extraction_logbook": self.extraction_logbook_slug(method_id),
            "dominant_matrix": dom,
            "ccv_interval": ccv,
            "spike_ppt": spike,
            # the lots the instrument was loaded with (run_lots.py): what the
            # parentage review walks
            "standards": standards,
            "solvents": solvents,
            # QC-composition overrides actually applied to this run, for the
            # same reason the lots are recorded here: an output must
            # name its parentage -- a reviewer looking at
            # extra DUP/LFSM rows in `rows` should not have to guess why.
            "duplicate_all_samples": bool(duplicate_all_samples),
            "lfsm_frequency": lfsm_frequency,
            # the calibration decision and who made it (audit)
            "calibration": {"new_curve": bool(include_cal),
                            "decided_by": (u"method profile" if decision.get("forced") else initials),
                            "reason": decision.get("reason") or u"",
                            "last_curve": decision.get("last") or None},
            "worksheet_id": batch_obj.getId() if batch_obj is not None else u"",
            "rows": rows,
        }
        # a method whose results come from the raw data: what the converter
        # service waits for on the share (raw_expect.py)
        raw = self._write_raw_expectation(batch_obj, batch_id, method_id, manifest)
        if raw:
            manifest["raw_expectation"] = raw
        missing = getattr(self, "_missing_roles", []) or []
        if missing:
            manifest["missing_qc_roles"] = missing
            logger.warning("Batch %s: no injection for QC role(s) %s",
                           batch_id, missing)
        try:
            IAnnotations(self._batch(batch_id))[RUN_MANIFEST_KEY] = \
                json.dumps(manifest)
        except Exception as exc:
            logger.warning("manifest save failed: %s", exc)
        self._record_run_lots(batch_obj, standards, solvents, initials, self.RUN_LEDGER_STAGE)
        self._close_notices(batch_obj)
        from six.moves.urllib.parse import quote_plus
        warns = [u"No injection for " + u" ".join(missing)] if missing else []
        if raw and raw.get("error"):
            # said now, not left for the run to wait on the share
            raw_warn = u"What the raw run expects was not written: %s" % raw["error"]
            warns.append(raw_warn)
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&built=1{2}".format(
                self.portal_url(), batch_id,
                ("&warn=" + quote_plus(u"; ".join(warns).encode("utf-8"))) if warns else ""))
        return u""

    def built(self):
        return self.request.form.get("built", "") == "1"

    STEPS = (("1", u"1 \u00b7 Build the run"), ("2", u"2 \u00b7 Load on the instrument"),
             ("3", u"3 \u00b7 Import results"), ("4", u"4 \u00b7 Dilutions and re-injections"))

    def active_step(self):
        """The step shown: the one asked for, else Load once the run
        is built, else Build."""
        want = u"%s" % (self.request.form.get("step") or u"")
        if want in dict(self.STEPS):
            return want
        return u"2" if self.manifest() else u"1"

    def manifest(self):
        b = self._batch()
        if b is None:
            return None
        try:
            raw = IAnnotations(b).get(RUN_MANIFEST_KEY)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def can_mark_loaded(self):
        """May the Loaded button stamp this run? Only a built run that waits
        at step 2 (run_plan.waiting_step): not one sent back, and not one whose
        results are already in."""
        from senaite.pfas import extraction_batch as eb
        from senaite.pfas import run_plan
        b = self._batch()
        m = self.manifest() if b is not None else None
        if not m:
            return False
        imports = []
        try:
            from senaite.pfas.qc.store import QCResultStore, DEFAULT_DB_PATH
            imports = QCResultStore(DEFAULT_DB_PATH).import_log(b.getId())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("loaded: import log unread: %s", exc)
        return run_plan.waiting_step(m, self.run_files(b), eb.load_requests(b), imports) == u"2"

    def _handle_mark_loaded(self):
        """Stamp the built run with who loaded it on the instrument and when.
        Once stamped it stays: a second press changes nothing."""
        from senaite.pfas import run_plan
        bid = _first(self.request.form.get("batch_id")).strip()
        b = self._batch(bid)
        m = self.manifest() if b is not None else None
        if not m:
            return self._redirect_err(bid, u"No built run")
        if self.can_mark_loaded() and not m.get("loaded"):
            m["loaded"] = run_plan.loaded_stamp(self._current_user_name(),
                                                u"{0:%Y-%m-%d %H:%M} UTC".format(datetime.utcnow()))
            IAnnotations(b)[RUN_MANIFEST_KEY] = json.dumps(m)
        self.request.response.redirect("{0}/@@pfas-run-builder?batch_id={1}&step=3".format(
            self.portal_url(), bid))
        return u""

    def _handle_download_csv(self):
        m = self.manifest()
        if not m:
            return self._redirect_err(self.selected_batch(), "No built run")
        from senaite.pfas import run_lots
        buf = io.BytesIO()
        w = csv.writer(buf)
        # the table on screen, column for column (run_lots.injection_list)
        for row in run_lots.injection_list(m):
            w.writerow([(u"%s" % c).encode("utf-8") for c in row])
        resp = self.request.response
        resp.setHeader("Content-Type", "text/csv")
        resp.setHeader("Content-Disposition",
                       "attachment; filename=worklist_{0}.csv".format(
                           re.sub(r"[^A-Za-z0-9_-]", "_",
                                  m["batch_id"] or "run")))
        return buf.getvalue()

    def _handle_upload_export(self):
        f = self.request.form.get("export_file")
        bid = _first(self.request.form.get("batch_id")).strip()
        if f is None or not getattr(f, "filename", ""):
            return self._redirect_err(bid, "No file selected")
        note, error = self.deliver(bid, f.filename, f.read())
        if error:
            return self._redirect_err(bid, error)
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&ok={2}".format(
                self.portal_url(), bid, quote_plus(note.encode("utf-8"))))
        return u""

    def deliver(self, bid, filename, data):
        """Hand an instrument export to the pipeline worker for the extraction
        batch `bid` (a worksheet id): its run record first, then the file, in
        the watched folder. The one way an export reaches the pipeline -- the
        Run Builder's upload and core's instrument import (core_instrument.py)
        both come here. Returns (message, error)."""
        self.request.form["batch_id"] = bid
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename or u"run.csv"))
        if os.path.splitext(fname)[1].lower() not in EXPORT_TYPES or fname.startswith("."):
            return u"", (u"An instrument export is a .csv, .txt or .tsv file; "
                         u"%s was not accepted" % fname)
        if not os.path.isdir(UPLOAD_DIR):
            try:
                os.makedirs(UPLOAD_DIR)
            except OSError:
                return u"", u"Watch directory unavailable"
        # A supplementary run (what review asked for) is processed together
        # with the extraction batch's earlier run files.
        b = self._batch(bid)
        m = self.manifest() or {}
        files = self.run_files(b) if b is not None else []
        # supplementary when the run built last is, unless this file is
        # already on record as the batch's full run (uploaded again)
        supplementary = m.get("kind") == "supplementary" and not any(
            x.get("file") == fname and x.get("kind") == "full" for x in files)
        extra = {}
        # the batch's runs are one record: a supplementary run joins every
        # earlier file; the full run, uploaded again, joins the supplementary
        # runs already recorded
        joins = [x["file"] for x in files if x.get("file") != fname and not x.get("deleted")
                 and (supplementary or x.get("kind") == "supplementary")]
        if joins:
            extra["supplementary_of"] = joins
        if supplementary:
            if not joins:
                return u"", (u"No earlier run of this worksheet is on record: "
                             u"upload its run first, then this one")
        # The run record goes in FIRST: the worker starts on the CSV the
        # moment it appears and reads the record beside it then.
        try:
            note = self._write_sidecar(bid, os.path.splitext(fname)[0], extra=extra)
        except Exception as exc:                            # noqa: BLE001
            logger.error("run_builder: extraction record not written: %s", exc)
            note = u"no extraction record (see log)"
        try:
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as out:
                out.write(data)
        except Exception as exc:
            logger.error("upload failed: %s", exc)
            return u"", u"Upload failed — see log"
        logger.info("run_builder: uploaded %s to watch dir (%s)", fname, note)
        if b is not None:
            from senaite.pfas import extraction_batch
            # the checksum names the file on record, and outlives it
            # (instrument_files.mark_deleted)
            entry = {"file": fname, "kind": "supplementary" if supplementary else "full",
                     "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "sha256": hashlib.sha256(data).hexdigest()}
            if supplementary:
                # the requests the follow-up run carried: what makes its file a
                # re-injection's (instrument_files.reinjection_file)
                entry["requests"] = list(m.get("requests") or [])
            files = [x for x in files if x.get("file") != fname or x.get("deleted")] + [entry]
            IAnnotations(b)[RUN_FILES_KEY] = json.dumps(files)
            if supplementary and extraction_batch.is_worksheet(b):
                reqs = extraction_batch.load_requests(b)
                for r in reqs:
                    if r.get("id") in (m.get("requests") or []) and r.get("status") == u"made":
                        r["status"] = u"run"
                extraction_batch.save_requests(b, reqs)
        return (u"Uploaded {0}, {1}. The pipeline worker will import it.".format(fname, note), u"")

    def _batch_worksheet_id(self, batch):
        """The id of the one worksheet holding this batch's analyses, or ""
        when there is none or more than one (the run cannot be told apart)."""
        from bika.lims import api
        buid = api.get_uid(batch)
        found = []
        cat = getToolByName(self._portal(), "senaite_catalog_worksheet")
        for br in cat(portal_type="Worksheet"):
            ws = br.getObject()
            for an in ws.getAnalyses() or []:
                try:
                    ab = an.getRequest().getBatch()
                except Exception:                           # noqa: BLE001
                    ab = None
                if ab is not None and api.get_uid(ab) == buid:
                    found.append(ws.getId())
                    break
        return found[0] if len(found) == 1 else u""

    def _acid_basis(self, batch_obj):
        """(analytes, known) for the run built on `batch_obj`
        (acid_basis_of)."""
        return acid_basis_of(self._portal(), batch_obj, self._batch)

    def _write_raw_expectation(self, b, batch_id, method_id, manifest):
        """`<stem>.rawexpect.json` in the watch folder for a method whose
        results come from the raw data: {"stem"}, or {"error"} when it could
        not be written; None for any other method."""
        from senaite.pfas import raw_expect
        from senaite.pfas import calibration_levels as cl
        prof = self._profile(method_id)
        if not raw_expect.wants_raw(prof):
            return None
        try:
            lots = self._slot_lot_values(manifest, cl.unit(prof))
            stem = u"RAW_{0}_{1}".format(
                re.sub(r"[^A-Za-z0-9_-]", "_", manifest.get("worksheet_id") or batch_id),
                datetime.utcnow().strftime("%Y%m%d%H%M%S"))
            branched = self._branched_fractions(prof, manifest)
            data = raw_expect.raw_expectation(
                manifest["rows"], self._sidecar_record(batch_id), prof, self.export_columns(b),
                lot_values=lots, calibration=manifest.get("calibration"), run=stem, branched=branched,
                lot_names=dict(((slot or u"").upper(), (lot or {}).get("lot") or (lot or {}).get("name") or u"")
                               for slot, lot in (manifest.get("standards") or {}).items()))
            path = os.path.join(UPLOAD_DIR, stem + ".rawexpect.json")
            text = json.dumps(data, indent=2, sort_keys=True)
            with open(path + ".part", "wb") as out:
                out.write(text if isinstance(text, bytes) else text.encode("utf-8"))
            os.rename(path + ".part", path)
            return {"stem": stem}
        except Exception as exc:                            # noqa: BLE001
            logger.exception("raw expectation for %s not written", batch_id)
            return {"error": u"%s" % exc}

    def _slot_lot_values(self, manifest, unit):
        """{slot: {analyte: concentration in `unit`}} for every standard
        slot with a lot: a prepared lot's stated concentrations, {} for any
        other, so a refusal can tell no lot from no value."""
        from senaite.pfas import raw_expect
        from senaite.pfas.browser.prepared_standards import _get
        lots = {}
        for slot, lot in (manifest.get("standards") or {}).items():
            values = {}
            if lot.get("kind") == u"prepared_standard":
                found = _get(self._portal(), lot.get("uid")) or {}
                values = raw_expect.lot_values(found.get("analyte_concentrations") or [], unit)
            lots[(slot or u"").upper()] = values
        return lots

    def _branched_fractions(self, prof, manifest):
        """{keyword: {slot: {"fraction", "from"}}} for each analyte with a
        branched peak, in each calibrator, CCV and ICV lot: the branched %
        its native reagent's certificate states, followed up the lot's
        parent lots, and the lots whose certificates state it. A slot whose
        certificates state none is left out."""
        from senaite.pfas import certificate_values as cv
        from senaite.pfas import raw_expect
        from senaite.pfas.browser.prepared_standards import (
            _ANN_PARENTS, _get_ann, _resolve_lot, KIND_MANUFACTURER, KIND_PREPARED)
        keywords = sorted(kw for kw, e in raw_expect.isomer_entries(prof).items()
                          if [x for x in e.get("branched") or [] if x])
        if not keywords:
            return {}
        portal = self._portal()
        objs = {}

        def node(obj, kind):
            key = (kind, obj.getId())
            objs[key] = obj
            return key

        def parents_of(key):
            if key[0] != KIND_PREPARED:
                return []
            out = []
            for p in _get_ann(objs[key], _ANN_PARENTS, []) or []:
                obj, kind = _resolve_lot(portal, p)
                if obj is not None:
                    out.append(node(obj, kind))
            return out

        def certificate_of(key):
            if key[0] != KIND_MANUFACTURER:
                return None
            raw = IAnnotations(objs[key]).get(cv.KEY)
            return json.loads(raw) if raw else None

        def label(key):
            return getattr(objs[key], "lot_number", None) or key[1]

        out = {}
        for slot, lot in sorted((manifest.get("standards") or {}).items()):
            slot = (slot or u"").upper()
            if not (slot.startswith(u"CAL-") or slot in (u"CCV", u"ICV")):
                continue
            obj, kind = _resolve_lot(portal, {"uid": lot.get("uid"), "lot": lot.get("lot")})
            if obj is None:
                continue
            start = node(obj, kind)
            for kw in keywords:
                source = cv.branched_source(start, kw, parents_of, certificate_of, label)
                if source is not None:
                    out.setdefault(kw, {})[slot] = source
        return out

    def _write_sidecar(self, batch_id, stem, extra=None):
        """Write `{stem}_extraction.json` beside the upload from the batch and
        its guided extraction (senaite.pfas.extraction_sidecar). Returns what
        the run record holds, for the confirmation message."""
        record = self._sidecar_record(batch_id, extra)
        if record is None:
            return u"no worksheet chosen, so no method, matrix or extraction record"
        path = os.path.join(UPLOAD_DIR, "{0}_extraction.json".format(stem))
        tmp = path + ".part"
        data = json.dumps(record, indent=2, sort_keys=True)
        with open(tmp, "wb") as out:
            out.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        os.rename(tmp, path)
        cb = self._client(self._batch(batch_id))
        parts = [u"worksheet {0}".format(record["batch_id"]) if record.get("batch_id")
                 else u"no single worksheet"]
        if cb is not None:
            parts.append(u"batch {0}".format(cb.getId()))
        parts.append(u"extraction finalized" if record["completed"]
                     else u"extraction in progress" if record["started"]
                     else u"no extraction recorded")
        if record.get("acid_basis_unknown"):
            parts.append(u"the reused curve's standards were not found: the method's salt factors apply")
        return u", ".join(parts)

    def _sidecar_record(self, batch_id, extra=None):
        """The run record (`{stem}_extraction.json`'s content) from the batch
        and its guided extraction (senaite.pfas.extraction_sidecar), or None
        with no batch."""
        from senaite.pfas.extraction_sidecar import build_sidecar
        from senaite.pfas.browser.extraction_guide import _load_session
        from senaite.pfas.browser.sample_status import _fullname
        from senaite.pfas.browser.batch_project_viewlet import _batch_matrix
        from senaite.pfas.method_profile_store import get_profile
        from bika.lims import api
        b = self._batch(batch_id)
        if b is None:
            return None
        from senaite.pfas import extraction_batch
        sess = dict(_load_session(extraction_batch.home(b)))   # on the worksheet
        # the batch's one resolver (batch_method.resolve, core first; the
        # session is one of its sources), so the run is judged by the method
        # every other page shows -- the session used to win here
        sess["method_id"] = self.batch_method(b) or sess.get("method_id") or u""
        names = {}
        if sess["method_id"]:
            from senaite.pfas.stage_plan import stages_for
            for st in stages_for(sess, get_profile(self._portal(), sess["method_id"])):
                names[u"%s" % st.get("order")] = st.get("name") or u""
        # the extraction batch is the worksheet; its client Batch names
        # the project, the prep log and the client
        cb = self._client(b)
        client = cb.getClient() if cb is not None and hasattr(cb, "getClient") else None
        ws_id = b.getId() if extraction_batch.is_worksheet(b) else self._batch_worksheet_id(b)
        matrix = _batch_matrix(self._portal(), cb) if cb is not None else u""
        if not matrix or client is None:
            # samples entered on a CoC belong to no client Batch: the
            # worksheet's own samples name the matrix (the most common) and
            # the client (synthetic runs: no matrix meant
            # no spike amount was found and no spike was judged)
            ws_samples = extraction_batch.worksheet_samples(b) if extraction_batch.is_worksheet(b) else []
            mats = [s["matrix"] for s in ws_samples if s.get("matrix")]
            if not matrix and mats:
                matrix = max(set(mats), key=mats.count)
            if client is None and ws_samples:
                obj = api.get_object_by_uid(ws_samples[0]["uid"], None)
                client = obj.getClient() if obj is not None else None
        record = build_sidecar(sess, names, worksheet_id=ws_id,
                               senaite_batch_id=cb.getId() if cb is not None else u"",
                               matrix=matrix,
                               client_uid=api.get_uid(client) if client else u"",
                               fullname=lambda uid: _fullname(self.context, uid))
        # the run's instrument: the worker's import layout is matched for it
        instr = self._instrument(b)
        record["instrument_uid"] = api.get_uid(instr) if instr is not None else u""
        # no salt factor on an analyte whose calibration lots are stated as acid
        acid, known = self._acid_basis(b)
        record["acid_basis_analytes"] = acid
        if not known:
            record["acid_basis_unknown"] = True
        # the results source the run was built / uploaded under (Integration)
        from senaite.pfas import raw_expect
        record["integration_mode"] = raw_expect.mode(get_profile(self._portal(), sess["method_id"])
                                                     if sess["method_id"] else {})
        record.update(extra or {})
        return record

    # ── run-template save (Manager only — this is method configuration) ──
    def _is_manager(self):
        # Resolved at the portal via perms.
        return has_role_at_portal(self.context, MANAGER_ROLES)

    def _handle_save_template(self):
        f = self.request.form
        batch_id = _first(f.get("batch_id")).strip()
        if not self._is_manager():
            return self._redirect_err(
                batch_id, "Only a Manager may edit the run template")
        method_id = (_first(f.get("method_id")).strip()
                     or self.batch_method(self._batch(batch_id)))
        if not method_id:
            return self._redirect_err(batch_id, "No method to configure")

        raw = _first(f.get("sequence_codes")) or u""
        sequence = [c.strip() for c in raw.split(",") if c.strip()]
        if self.SAMPLES_TOKEN not in sequence:
            sequence.append(self.SAMPLES_TOKEN)     # samples are never optional
        bracket = _first(f.get("bracket_qc")).strip() or "CCV"

        portal = self._portal()
        try:
            from senaite.pfas.method_profile_store import (
                get_profile, save_profile)
            prof = get_profile(portal, method_id)
            tpl = {"sequence": sequence, "bracket_qc": bracket}
            prof["run_template"] = tpl
            save_profile(portal, method_id, prof)
        except Exception as exc:
            logger.error("save_template failed: %s", exc)
            return self._redirect_err(batch_id, "Save failed — see log")
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&tpl_saved=1".format(
                self.portal_url(), batch_id))
        return u""

    # ── the instrument's sample list (D4: Waters MassLynx) ──────────────────
    # The format is the worksheet's INSTRUMENT's, kept in Import Studio beside
    # its import mapping (instrument_export.py).

    def _instrument(self, b=None):
        b = b if b is not None else self._batch()
        try:
            return b.getInstrument() if b is not None and hasattr(b, "getInstrument") else None
        except Exception:                                   # noqa: BLE001
            return None

    def export_columns(self, b=None):
        from senaite.pfas import instrument_export
        return instrument_export.columns_for(self._instrument(b))[0]

    def masslynx_csv(self, manifest, b=None):
        """The built run as the instrument's sample list (bytes)."""
        from senaite.pfas import run_plan
        buf = io.BytesIO()
        w = csv.writer(buf)
        for line in run_plan.export_rows(manifest["rows"], self.export_columns(b)):
            w.writerow([(u"%s" % v).encode("utf-8") for v in line])
        return buf.getvalue()

    def _handle_download_masslynx(self):
        """The built run as the instrument's sample list (run_plan.export_rows)."""
        m = self.manifest()
        if not m:
            return self._redirect_err(self.selected_batch(), "No built run")
        data = self.masslynx_csv(m)
        resp = self.request.response
        resp.setHeader("Content-Type", "text/csv")
        resp.setHeader("Content-Disposition", "attachment; filename=masslynx_{0}.csv".format(
            re.sub(r"[^A-Za-z0-9_-]", "_", m.get("worksheet_id") or m["batch_id"] or "run")))
        return data

    def _redirect_err(self, batch_id, msg):
        from six.moves.urllib.parse import quote_plus
        self.request.response.redirect(
            "{0}/@@pfas-run-builder?batch_id={1}&error={2}".format(
                self.portal_url(), batch_id, quote_plus((u"%s" % msg).encode("utf-8"))))
        return u""
