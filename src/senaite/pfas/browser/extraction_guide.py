# -*- coding: utf-8 -*-
"""
Guided Extraction Interface (@@pfas-extraction-guide).

Per-method, per-stage tablet-friendly workflow for PFAS extractions.

Flow:
  1. Open via Batch sub-tab or URL: @@pfas-extraction-guide?batch_uid=XXX
  2. Analyst walks stage-by-stage through the method's extraction_stages.
  3. Each stage: confirm reagent lots (scan/OCR optional), log equipment S/Ns,
     note deviations, optionally prepare a new solution → label generator.
  4. Spike stages: capture standard pedigree (CRM → stock → working).
  5. At completion: download PDF logbook (@@pfas-extraction-pdf).

Session state stored in:
  IAnnotations(batch)["senaite.pfas.extraction_session"] = json_string

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json

try:
    from urllib import quote_plus
except ImportError:                                         # Python 3
    from urllib.parse import quote_plus
import logging
from datetime import datetime

from persistent.mapping import PersistentMapping
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

from senaite.pfas.method_profile_store import get_profile
# Imported, never redeclared: senaite.pfas.dilution_ref owns this key and reads
# the same session to resolve per-sample dilution factors.
from senaite.pfas.dilution_ref import EXTRACTION_SESSION_KEY
from senaite.pfas.browser.reagents import _save_reagent, STATUS_OPENED
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.bench_queue import is_consumable_row, is_standard_row
from senaite.pfas.document_templates import script_json

logger = logging.getLogger("senaite.pfas.browser.extraction_guide")


# ── Session helpers ───────────────────────────────────────────────────────────

def _load_session(batch):
    ann = IAnnotations(batch)
    raw = ann.get(EXTRACTION_SESSION_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _save_session(batch, data):
    ann = IAnnotations(batch)
    ann[EXTRACTION_SESSION_KEY] = json.dumps(data)


def batch_method_id(batch, request):
    """The batch's method by the ONE resolver (batch_method.py: the batch's
    analyses and core first, then the session and logbooks)."""
    try:
        from senaite.pfas.browser.logbooks import PFASLogbookIndexView
        return PFASLogbookIndexView(batch, request).batch_method() or u""
    except Exception:                                       # noqa: BLE001
        return u""


def _json_or(raw, default):
    try:
        value = json.loads(raw) if raw else default
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


def resolve_rows(portal, rows):
    """Each reagent row as the inventory has it now (bench_queue.resolve_rows)."""
    from senaite.pfas.bench_queue import resolve_rows as _resolve
    from senaite.pfas.browser.bench_inventory import item_index
    return _resolve(item_index(portal), rows)


# worksheet uid -> (method id, when resolved). Resolving a worksheet's
# method walks its samples x analyses (batch_method.py); the queue did that
# for every open worksheet on every Bench, Run Builder and guide load --
# 25,000 catalog searches, 24-48 s. A
# worksheet's method does not change between page loads; a few minutes'
# staleness in a queue label is the price.
_METHOD_CACHE = {}
METHOD_CACHE_SECONDS = 300


def queue_method_id(batch, request):
    import time
    from bika.lims import api
    uid = api.get_uid(batch)
    hit = _METHOD_CACHE.get(uid)
    if hit is not None and time.time() - hit[1] < METHOD_CACHE_SECONDS:
        return hit[0]
    method_id = batch_method_id(batch, request)
    if method_id:                         # "no method yet" is looked up again
        _METHOD_CACHE[uid] = (method_id, time.time())
    return method_id


def extraction_queue(portal, request):
    """[{id, uid, title, method_id, method_label, state...}] for every open
    extraction batch -- the WORKSHEET -- oldest first:
    the Bench landing's queue and the guide's picker. Built once per request
    (the Bench page asked for it twice)."""
    other = getattr(request, "other", None)
    if isinstance(other, dict) and "_pfas_extraction_queue" in other:
        return other["_pfas_extraction_queue"]
    rows = _extraction_queue(portal, request)
    if isinstance(other, dict):
        other["_pfas_extraction_queue"] = rows
    return rows


def _extraction_queue(portal, request):
    from bika.lims import api
    from senaite.pfas import extraction_batch
    from senaite.pfas.bench_queue import extraction_state
    from senaite.pfas.method_profile_store import get_profile
    rows, seen = [], set()
    for brain in api.search({"portal_type": "Worksheet", "review_state": "open"},
                            "senaite_catalog_worksheet"):
        try:
            batch = brain.getObject()
        except Exception:                                   # noqa: BLE001
            continue
        uid = api.get_uid(batch)
        if uid in seen or api.get_review_status(batch) not in ("open",):
            continue
        seen.add(uid)
        session = _load_session(batch)
        method_id = queue_method_id(batch, request)       # core first (batch_method.py)
        profile = get_profile(portal, method_id) if method_id else {}
        orders = [s.get("order") for s in profile.get("extraction_stages") or []]
        state = extraction_state(session, orders)
        client = extraction_batch.linked_batch(batch)
        title = batch.getId() + (u" \u00b7 " + client.Title() if client is not None else u"")
        rows.append(dict(state, id=batch.getId(), uid=uid, title=title,
                         method_id=method_id,
                         method_label=profile.get("display_name") or method_id or u"",
                         analyst=session.get("analyst") or u"",
                         created=str(getattr(batch, "created", lambda: "")())[:10]))
    order = {u"in_progress": 0, u"not_started": 1, u"finished": 2}
    rows.sort(key=lambda r: (order.get(r["state"], 3), r["created"], r["id"]))
    return rows


def _utcnow():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ── View ──────────────────────────────────────────────────────────────────────

class PFASExtractionGuideView(BrowserView):
    """Stage-by-stage guided extraction for PFAS analyses."""

    template = ViewPageTemplateFile("templates/extraction_guide.pt")

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            if action == "start":
                return self._handle_start()
            if action == "complete_stage":
                return self._handle_complete_stage()
            if action == "save_pedigree":
                return self._handle_save_pedigree()
            if action == "prepare_solution":
                return self._handle_prepare_solution()
            if action == "update_reagent_status":
                return self._handle_reagent_status()
            if action == "finalize":
                return self._handle_finalize()
            if action == "receive_lot":
                return self._handle_receive_lot()
            if action == "log_dilution":
                return self._handle_log_dilution()
            if action == "reopen_stage":
                return self._handle_reopen_stage()
        return self.template()

    # ── Context helpers ──────────────────────────────────────────────────────

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def _self_url(self):
        return "{0}/@@pfas-extraction-guide".format(self.context.absolute_url())

    # ── Batch resolution ─────────────────────────────────────────────────────

    def _get_batch(self):
        """The extraction batch: the worksheet. An older link
        to a client Batch is followed to its worksheet (extraction_batch.home)."""
        from senaite.pfas import extraction_batch
        uid = self.request.form.get("batch_uid", "")
        if not uid:
            return None
        catalog = getToolByName(self.context, "uid_catalog")
        brains = catalog(UID=uid)
        if brains:
            try:
                return extraction_batch.home(brains[0].getObject())
            except Exception:
                pass
        return None

    def batch_uid(self):
        b = self._get_batch()
        return b.UID() if b is not None else self.request.form.get("batch_uid", "")

    def batch_method_id(self):
        """Preselected on the start screen: the batch already has a method."""
        b = self._get_batch()
        return batch_method_id(b, self.request) if b else u""

    def current_user_name(self):
        """The logged-in chemist -- the start screen's default analyst."""
        try:
            user = self.context.portal_membership.getAuthenticatedMember()
            return user.getProperty("fullname") or user.getId()
        except Exception:                                   # noqa: BLE001
            return u""

    def batch_choices(self):
        """No batch chosen: the open batches to pick from."""
        return extraction_queue(self._portal(), self.request)

    def batch_title(self):
        from senaite.pfas import extraction_batch
        b = self._get_batch()
        if b is None:
            return ""
        client = extraction_batch.linked_batch(b) if extraction_batch.is_worksheet(b) else None
        return b.getId() + (u" \u00b7 " + client.Title() if client is not None else u"")

    def batch_url(self):
        b = self._get_batch()
        return b.absolute_url() if b else self.portal_url()

    # ── Session data ─────────────────────────────────────────────────────────

    def session(self):
        b = self._get_batch()
        if not b:
            return {}
        return _load_session(b)

    def session_json(self):
        return script_json(self.session())

    # ── Method profile + stages ───────────────────────────────────────────────

    def _method_id(self):
        """The batch's method by the ONE resolver (core first); an extraction session started under another method is a
        conflict, shown (method_conflicts), never silently followed."""
        b = self._get_batch()
        mid = batch_method_id(b, self.request) if b is not None else u""
        return mid or self.session().get("method_id") or self.request.form.get("method_id", "FDA_32PFAS")

    def method_conflicts(self):
        """[(source, method)] that disagree with the batch's method."""
        b = self._get_batch()
        if b is None:
            return []
        from senaite.pfas import batch_method as bm
        return bm.resolve(b)[1]

    def method_profile(self):
        return get_profile(self._portal(), self._method_id())

    def extraction_stages(self):
        profile = self.method_profile()
        stages = profile.get("extraction_stages", [])
        return sorted(stages, key=lambda s: s.get("order", 0))

    def current_stage_order(self):
        sess = self.session()
        if sess.get("reopened") is not None:          # a stage being corrected
            return int(sess["reopened"])
        return int(sess.get("current_stage", 1))

    # ── What the page shows: edit / view a completed stage / review ─────────

    def _orders(self):
        return [s.get("order", 0) for s in self.extraction_stages()]

    def view_order(self):
        try:
            return int(self.request.form.get("stage") or "")
        except (TypeError, ValueError):
            return None

    def mode(self):
        from senaite.pfas.extraction_review import mode
        return mode(self.session(), self._orders(), self.view_order())

    def viewed_stage(self):
        """The completed stage shown read-only (?stage=N), as summarised."""
        from senaite.pfas.extraction_review import stage_summary
        n = self.view_order()
        st = ([s for s in self.extraction_stages() if s.get("order") == n] or [{}])[0]
        return stage_summary(n, st.get("name"),
                             (self.session().get("stages") or {}).get(u"%s" % n))

    def review_data(self):
        from senaite.pfas.extraction_review import review
        return review(self.session(), self.extraction_stages())

    def stage_url(self, order=None):
        base = u"{0}?batch_uid={1}".format(self._self_url(), self.batch_uid())
        return base + (u"&stage={0}".format(order) if order is not None else u"")

    def current_stage(self):
        order = self.current_stage_order()
        for s in self.extraction_stages():
            if s.get("order") == order:
                return s
        return {}

    def stage_media_url(self, stage):
        """URL of this stage's action GIF/photo, or "" if none.

        Stages are plain dicts loaded from the method profile and existing
        saved profiles predate this key (get_profile back-fills top-level keys
        only), so always read it with a default.
        """
        from senaite.pfas.browser.logbook_media import media_src
        return media_src(self.portal_url(), (stage or {}).get("media"))

    def stage_status(self, stage):
        """Return 'done', 'active', or 'pending'."""
        order = stage.get("order", 0)
        current = self.current_stage_order()
        sess = self.session()
        if sess.get("reopened") is not None and order == current:
            return "active"                   # being corrected
        if str(order) in (sess.get("stages") or {}):
            return "done"
        if order == current:
            return "active"
        return "pending"

    def completed_stages(self):
        return self.session().get("stages", {})

    def is_finalized(self):
        return bool(self.session().get("finalized", False))

    def total_stages(self):
        return len(self.extraction_stages())

    def progress_pct(self):
        total = self.total_stages()
        if not total:
            return 0
        done = len(self.completed_stages())
        # float: under Python 2 `done / total` is integer division, so the
        # bar read 0 % until the last stage
        return int(round(100.0 * done / total))

    # ── Reagent inventory lookup for stage reagents ───────────────────────────

    def stage_lots_json(self):
        """The current stage's lot picker: every usable lot (reagents and
        prepared standards) and, per reagent role, the suggested lots and the
        one to preselect ("Bench phase 2")."""
        from datetime import date
        from senaite.pfas.bench_queue import default_pick, suggested
        from senaite.pfas.browser.bench_inventory import usable_lots, role_picks
        portal = self._portal()
        lots = usable_lots(portal, date.today())
        picks = role_picks(portal, self.session().get("method_id", ""))

        def key(it):
            return u"{0}:{1}".format(it["kind"], it["uid"])
        roles = {}
        stage = self.current_stage()
        for role in list(stage.get("reagent_roles", [])) + list(stage.get("consumables") or []):
            rem = picks.get(role)
            pick = default_pick(lots, role, rem)
            roles[role] = {"suggested": [key(i) for i in suggested(lots, role, rem)],
                           "default": key(pick) if pick else u""}
        slim = [{"key": key(i), "kind": i["kind"], "kind_label": i["kind_label"],
                 "uid": i["uid"], "name": i["name"], "lot": i["lot_number"],
                 "expiry": i["expiry"], "status": i["status"], "barcode": i["barcode"],
                 "cat_number": i["cat_number"], "left": i.get("remaining_text") or u"",
                 "unit": i.get("quantity_unit") or u""}
                for i in sorted(lots, key=lambda i: (i["name"].lower(), i["lot_number"]))]
        return script_json({"lots": slim, "roles": roles,
                           "role_order": list(stage.get("reagent_roles", [])),
                           "consumable_order": list(stage.get("consumables") or [])})

    # ── Pedigree ──────────────────────────────────────────────────────────────

    def pedigree(self):
        return self.session().get("pedigree", {})

    def pedigree_json(self):
        return script_json(self.pedigree())

    # ── Available methods for start form ─────────────────────────────────────

    def available_methods(self):
        """The lab's LIVE method profiles with extraction stages (the built-in
        defaults missed a method made in the wizard)."""
        from senaite.pfas.method_profile_store import get_profile, list_method_ids
        portal = self._portal()
        out = []
        for mid in sorted(list_method_ids(portal)):
            p = get_profile(portal, mid)
            if p.get("extraction_stages"):
                out.append((mid, p.get("display_name", mid)))
        return out

    # ── PDF and label URLs ────────────────────────────────────────────────────

    def pdf_url(self):
        return "{0}/@@pfas-extraction-pdf?batch_uid={1}".format(
            self.portal_url(), self.batch_uid())

    def label_url(self):
        return "{0}/@@pfas-label".format(self.portal_url())

    # ── Action handlers ───────────────────────────────────────────────────────

    def _handle_start(self):
        b = self._get_batch()
        if not b:
            url = "{0}?error=Batch+not+found".format(self._self_url())
            return self._redirect(url)
        method_id = (self.request.form.get("method_id", "").strip()
                     or batch_method_id(b, self.request))
        if not method_id:
            return self._redirect("{0}?batch_uid={1}&error=Choose+the+method".format(
                self._self_url(), b.UID()))
        analyst = self.request.form.get("analyst", "").strip() or self.current_user_name()
        data = {
            "method_id":     method_id,
            "started_at":    _utcnow(),
            "analyst":       analyst,
            "current_stage": 1,
            "stages":        {},
            "pedigree":      {},
            "finalized":     False,
        }
        _save_session(b, data)
        url = "{0}?batch_uid={1}&ok=Extraction+session+started".format(
            self._self_url(), b.UID())
        return self._redirect(url)

    def _handle_complete_stage(self):
        b = self._get_batch()
        if not b:
            return self._redirect("{0}?error=Batch+not+found".format(self._self_url()))
        sess = _load_session(b)
        f = self.request.form
        stage_order = f.get("stage_order", "").strip()

        # Parse reagent rows from JSON
        reagents_raw = f.get("reagents_json", "[]")
        try:
            reagents = json.loads(reagents_raw)
        except (ValueError, TypeError):
            reagents = []

        # The inventory is the record: a row naming a lot takes its name, lot
        # number, expiry and status from the inventory as they are NOW, never
        # from what the browser sent (a typed or stale expiry is not evidence).
        reagents = resolve_rows(self._portal(), reagents)

        # DB4: an empty role, or a lot not from the
        # inventory or not usable, may go ahead only with a deviation note.
        # A balance without a passed verification on the day may not go ahead
        # at all: no note unlocks it. Either way nothing is
        # changed -- but nothing the chemist entered is thrown away either:
        # the stage is kept as a draft and the page reopens on it.
        from datetime import date
        from senaite.pfas.bench_queue import balance_blocks, stage_warnings
        equipment_sns = _json_or(f.get("equipment_sns_json"), {})
        profile_stages = get_profile(self._portal(), sess.get("method_id", "")).get(
            "extraction_stages", [])
        stage_def = ([s for s in profile_stages
                      if u"%s" % s.get("order") == stage_order] or [{}])[0]
        warnings = stage_warnings(reagents, date.today())
        # a correction is judged on the day the stage was first done, the day
        # the sample was weighed -- not the day the correction is typed
        from senaite.pfas.extraction_review import done_on, unconfirmed
        blocks = balance_blocks(self._balance_checks(
            stage_def, equipment_sns,
            done_on((sess.get("stages") or {}).get(str(stage_order))) or None))
        # the checks the stage asks to be ticked (stage editor: confirmations)
        # one field per check (flatten_form keeps only the first of a list)
        checks = [c for c in stage_def.get("confirmations") or [] if (c or u"").strip()]
        confirmed = [c for i, c in enumerate(checks) if f.get("confirmed_%d" % i)]
        warnings += [u"Not confirmed: %s" % c for c in unconfirmed(stage_def, confirmed)]
        # per-sample amount / final volume (FM-ENV-003 samples rows)
        from senaite.pfas import sample_table
        sample_col = sample_table.capture_column(stage_def)
        sample_edits = _json_or(f.get("samples_json"), []) if sample_col else []
        if sample_col == sample_table.SPE_PORT:
            warnings += sample_table.port_warnings(sample_edits)
        else:
            what = u"sample amount" if sample_col == sample_table.AMOUNT else u"final extract volume"
            warnings += [u"{0}: no {1} recorded".format(sid, what)
                         for sid in sample_table.missing(None, sample_edits, sample_col)]
        # the processing stage confirms each sample's homogenisation (H-P4):
        # a sample with a method requested and nothing recorded needs a note
        homog = []
        from senaite.pfas.sample_table import processing_stage
        ps = processing_stage(profile_stages)
        if ps is not None and u"%s" % ps.get("order") == stage_order:
            homog = self._homogenisation_rows(b)
            warnings += [r["warning"] for r in homog if r["warning"]]
        deviations = f.get("deviations", "").strip()
        analyst = f.get("stage_analyst", sess.get("analyst", "")).strip()
        if blocks or (warnings and not deviations):
            sess.setdefault("drafts", {})[str(stage_order)] = {
                "saved_at": _utcnow(), "analyst": analyst, "reagents": reagents,
                "equipment_sns": equipment_sns,
                "solutions_prepared": _json_or(f.get("solutions_prepared_json"), []),
                "samples": sample_edits, "deviations": deviations, "confirmed": confirmed,
                "warnings": warnings, "blocks": blocks}
            _save_session(b, sess)
            msg = (u"Not completed: a balance without a passed verification that day "
                   u"cannot be used. Record its verification under Equipment, or choose "
                   u"a balance that passed. Your entries are kept." if blocks else
                   u"Not completed yet: write a deviation note explaining what is "
                   u"listed under Needs a note. Your entries are kept.")
            return self._redirect("{0}?batch_uid={1}&error={2}".format(
                self._self_url(), b.UID(), quote_plus(msg.encode("utf-8"))))
        (sess.get("drafts") or {}).pop(str(stage_order), None)

        try:
            from senaite.pfas.browser.bench_inventory import remember_picks
            remember_picks(self._portal(), sess.get("method_id", ""), reagents)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("remember_picks: %s", exc)

        # Update reagent inventory status for any flagged lots
        for rg in reagents:
            uid = rg.get("inventory_uid", "")
            new_status = rg.get("new_status", "")
            if uid and new_status and rg.get("kind", "reagent") == "reagent":
                rec = None
                from senaite.pfas.browser.reagents import _get_reagent
                rec = _get_reagent(self._portal(), uid)
                if rec:
                    rec["status"] = new_status
                    if new_status == STATUS_OPENED and not rec.get("opened_date"):
                        from datetime import date
                        rec["opened_date"] = date.today().strftime("%Y-%m-%d")
                    _save_reagent(self._portal(), rec)

        stage_data = {
            "completed_at":        _utcnow(),
            "analyst":             analyst,
            "reagents":            reagents,
            "equipment_sns":       equipment_sns,
            "deviations":          deviations,
            "confirmed":           confirmed,       # the stage's checks ticked
            "homogenisation":      homog,           # what was confirmed per sample
            "warnings":            warnings,        # what the note had to explain
            "solutions_prepared":  _json_or(f.get("solutions_prepared_json"), []),
        }
        stages = sess.setdefault("stages", {})
        # a corrected stage keeps every earlier version and its reason
        previous = stages.get(str(stage_order)) or {}
        if previous.get("corrections"):
            stage_data["corrections"] = previous["corrections"]
        stages[str(stage_order)] = stage_data
        sess.pop("reopened", None)
        if sample_col and sample_edits:
            self._save_samples(b, sample_edits, sample_col)

        # Advance to the first stage not yet completed (after a correction
        # that may be an earlier one, or none: then the review screen shows)
        from senaite.pfas.extraction_review import next_stage
        upcoming = next_stage([s.get("order", 0) for s in profile_stages], sess)
        sess["current_stage"] = upcoming if upcoming is not None else int(stage_order)

        _save_session(b, sess)
        # Phase 3: the inventory learns where each lot went and how much
        # (inventory_ledger; completing the stage again replaces its rows).
        try:
            from senaite.pfas import inventory_ledger
            from senaite.pfas.browser.bench_inventory import item_index
            units = dict((k, v.get("quantity_unit") or u"")
                         for k, v in item_index(self._portal()).items())
            inventory_ledger.record_stage(
                None, b.UID(), b.getId(), stage_order, stage_def.get("name") or u"",
                reagents, analyst, stage_data["completed_at"], stock_units=units)
        except Exception as exc:                            # noqa: BLE001
            logger.error("usage ledger not written for %s stage %s: %s",
                         b.getId(), stage_order, exc)
        url = "{0}?batch_uid={1}&ok=Stage+completed".format(self._self_url(), b.UID())
        return self._redirect(url)

    def _handle_reopen_stage(self):
        """Reopen a completed stage for correction: the
        previous version is kept with the reason; after finalizing, never."""
        from senaite.pfas.extraction_review import reopen
        b = self._get_batch()
        if not b:
            return self._redirect("{0}?error=Batch+not+found".format(self._self_url()))
        try:
            order = int(self.request.form.get("stage_order") or "")
        except (TypeError, ValueError):
            order = None
        sess, why = reopen(_load_session(b), order, self.request.form.get("reason"),
                           self.current_user_name(), _utcnow())
        if why:
            return self._redirect("{0}?batch_uid={1}&stage={2}&error={3}".format(
                self._self_url(), b.UID(), order or u"", quote_plus(why.encode("utf-8"))))
        _save_session(b, sess)
        return self._redirect("{0}?batch_uid={1}&ok={2}".format(
            self._self_url(), b.UID(), quote_plus(u"Stage reopened for correction".encode("utf-8"))))

    def _handle_save_pedigree(self):
        b = self._get_batch()
        if not b:
            return self._redirect("{0}?error=Batch+not+found".format(self._self_url()))
        sess = _load_session(b)
        pedigree_json = self.request.form.get("pedigree_json", "{}")
        try:
            pedigree = json.loads(pedigree_json)
        except (ValueError, TypeError):
            pedigree = {}
        sess["pedigree"] = pedigree
        _save_session(b, sess)
        url = "{0}?batch_uid={1}&ok=Pedigree+saved".format(self._self_url(), b.UID())
        return self._redirect(url)

    def _balance_checks(self, stage, equipment_sns, day=None):
        """One entry per balance the stage lists: the serial chosen, the
        registered unit it names (None when none has it) and whether that
        unit passed its verification on `day` (default today; Equipment,
        ISO 17025 \u00a76.4)."""
        labels = [e for e in (stage or {}).get("equipment") or []
                  if u"balance" in (e or u"").lower()]
        if not labels:
            return []
        try:
            from senaite.pfas import facility_qc as fq
        except Exception as exc:                            # noqa: BLE001
            logger.warning("balance check unavailable: %s", exc)
            fq = None
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        day = day or today
        out = []
        for label in labels:
            serial = (equipment_sns.get(label) or u"").strip()
            unit, verified, note = None, False, u""
            if serial and fq is not None:
                try:
                    unit = fq.unit_by_serial(serial)
                    if unit:
                        verified, note = fq.balance_verified_on(unit["id"], day)
                        if day != today:
                            note = note.replace(u"today", u"on %s" % day)
                except Exception as exc:                    # noqa: BLE001
                    logger.warning("balance check %r: %s", serial, exc)
            out.append({"label": label, "serial": serial,
                        "unit_name": (unit.get("name") or serial) if unit else None,
                        "verified": verified, "note": note})
        return out

    def is_processing_stage(self, stage=None):
        """True on the stage that is the Sample Processing Log (FM-ENV-004)."""
        from senaite.pfas.sample_table import processing_stage
        st = processing_stage(self.extraction_stages())
        cur = stage if stage is not None else self.current_stage()
        return bool(st) and st.get("order") == (cur or {}).get("order")

    def processing_form_code(self):
        from senaite.pfas.logbook_store import form_code
        try:
            return form_code(self._portal(), "253")
        except Exception:                                   # noqa: BLE001
            return u"FM-ENV-004"

    def _homogenisation_rows(self, b):
        """Each of the batch's samples: its homogenisation request and the
        record in force (homogenisation.stage_rows)."""
        from bika.lims import api
        from senaite.pfas import extraction_batch
        from senaite.pfas import homogenisation as hg
        samples = []
        try:
            uids = [m.get("sample_uid") for m in extraction_batch.load(b)
                    if m.get("role") == u"Sample" and m.get("sample_uid")]
            if uids:
                objs = [api.get_object_by_uid(u, None) for u in uids]
            else:
                from senaite.pfas.core_fields import samples_of
                objs = list(samples_of(b))
            for s in sorted([o for o in objs if o is not None], key=lambda o: o.getId()):
                samples.append((s.getId(), hg.sample_request(s), hg.load_records(s)))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("homogenisation rows: %s", exc)
        return hg.stage_rows(samples, hg.load_methods(self._portal()))

    def homogenisation_rows(self):
        """For the processing stage's card; [] on any other stage."""
        if not self.is_processing_stage():
            return []
        b = self._get_batch()
        return self._homogenisation_rows(b) if b is not None else []

    def stage_confirmed(self):
        """Checks ticked: the draft's, else what the stage recorded."""
        draft = self.stage_draft()
        if draft:
            return draft.get("confirmed") or []
        done = (self.session().get("stages") or {}).get(
            u"%s" % self.current_stage().get("order")) or {}
        return done.get("confirmed") or []

    def stage_equipment_json(self):
        """Per stage equipment label: the registered Facility QC units it can
        be (balances, pipettes) with today's status, so the chemist picks the
        unit instead of typing its serial. Other equipment keeps a serial
        field. The stored shape (label -> serial) is unchanged."""
        from datetime import date
        from senaite.pfas.bench_queue import equipment_family, units_for
        try:
            from senaite.pfas import facility_qc as fq
            units = fq.list_units()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("stage equipment: %s", exc)
            fq, units = None, []
        today = date.today().strftime("%Y-%m-%d")
        out = []
        for label in self.current_stage().get("equipment") or []:
            fam = equipment_family(label)
            opts = []
            for u in units_for(label, units):
                ok, note = True, u""
                try:
                    if fam == u"balance":
                        ok, note = fq.balance_verified_on(u["id"], today)
                    elif fam == u"pipette":
                        ok = bool(fq.get_pipette_calibration_in_force(u["id"], today))
                        note = u"calibration in force" if ok else u"calibration NOT in force"
                except Exception as exc:                    # noqa: BLE001
                    logger.warning("unit status %s: %s", u.get("id"), exc)
                opts.append({"serial": u.get("serial_number") or u"",
                             "name": u.get("name") or u"", "ok": ok, "note": note})
            out.append({"label": label, "family": fam, "units": opts})
        return script_json(out)

    # ── Per-sample table and dilution log (FM-ENV-003 samples rows) ─────────

    def _batch_samples(self, b):
        """[{sample_id, matrix}] for the batch's samples: the Client Sample ID
        (the name the instrument run uses), else the sample id."""
        from senaite.pfas import extraction_batch
        members = [m for m in extraction_batch.load(b) if m.get("role") == u"Sample"]
        if members:
            # the extraction batch's samples under their LIMS-issued names
            return sorted(({"sample_id": m.get("injection"), "matrix": m.get("matrix") or u""}
                           for m in members), key=lambda s: s["sample_id"])
        out = []
        try:
            from senaite.pfas.core_fields import samples_of
            for ar in samples_of(b):                       # a worksheet's or a batch's
                st = ar.getSampleType()
                out.append({"sample_id": ar.getClientSampleID() or ar.getId(),
                            "matrix": st.Title() if st else u""})
        except Exception as exc:                            # noqa: BLE001
            logger.warning("batch samples: %s", exc)
        return sorted(out, key=lambda s: s["sample_id"])

    def _samples_log(self, b):
        """FM-ENV-003, its rows keyed by the members' LIMS-issued names."""
        from senaite.pfas import extraction_batch
        from senaite.pfas.browser.logbooks import _get_logbook
        data = dict(_get_logbook(b, "252") or {})
        members = extraction_batch.load(b)
        if members and data.get("samples"):
            data["samples"] = extraction_batch.rekey_rows(data["samples"], members)
        return data

    def _save_samples(self, b, edits, column):
        from senaite.pfas import sample_table
        from senaite.pfas.browser.logbooks import _save_logbook
        data = self._samples_log(b)
        if column == sample_table.SPE_PORT:
            data["spe_ports"] = sample_table.merge_ports(data.get("spe_ports"), edits)
        else:
            data["samples"] = sample_table.merge_samples(data.get("samples"), edits, column)
        _save_logbook(b, "252", data)

    def _port_rows(self, b):
        """Every member, samples and QC, with its SPE port ("Every member"); a batch without members lists its samples."""
        from senaite.pfas import extraction_batch
        ports = self._samples_log(b).get("spe_ports") or {}
        members = extraction_batch.load(b)
        rows = ([{"sample_id": m.get("injection"), "matrix_type": m.get("role") or u""}
                 for m in members if m.get("injection")] or
                [{"sample_id": s["sample_id"], "matrix_type": u"Sample"}
                 for s in self._batch_samples(b)])
        for r in rows:
            r["spe_port"] = ports.get(r["sample_id"]) or u""
        return rows

    def sample_card_json(self):
        """The current stage's per-sample table: which column it records and
        the rows (recorded ones, then the batch's samples not yet listed)."""
        from senaite.pfas import sample_table
        b = self._get_batch()
        col = sample_table.capture_column(self.current_stage())
        if b is None or not col:
            return script_json({"column": u"", "rows": []})
        if col == sample_table.SPE_PORT:
            rows = self._port_rows(b)
        else:
            rows = sample_table.rows_for_card(self._samples_log(b).get("samples"),
                                              self._batch_samples(b))
        draft = dict((d.get("sample_id"), d) for d in self.stage_draft().get("samples") or [])
        for r in rows:
            if r.get("sample_id") in draft:
                d = draft[r["sample_id"]]
                r[col] = d.get("value") or u""
                if col == sample_table.AMOUNT and d.get("unit"):
                    r["amount_unit"] = d["unit"]
        return script_json({"column": col, "rows": rows})

    def dilution_rows(self):
        from senaite.pfas import sample_table
        b = self._get_batch()
        return sample_table.dilutions(self._samples_log(b).get("samples")) if b is not None else []

    def dilution_parents(self):
        from senaite.pfas import sample_table
        b = self._get_batch()
        if b is None:
            return []
        return [r["sample_id"] for r in sample_table.rows_for_card(
            self._samples_log(b).get("samples"), self._batch_samples(b))]

    def _handle_log_dilution(self):
        """Append one dilution to FM-ENV-003: which
        sample, the dilution's injection name, the factor, who and when.
        Never edited afterwards."""
        from senaite.pfas import sample_table
        from senaite.pfas.browser.logbooks import _save_logbook
        b = self._get_batch()
        if b is None:
            return self._redirect("{0}?error=Batch+not+found".format(self._self_url()))
        f = self.request.form
        data = self._samples_log(b)
        rows, error = sample_table.append_dilution(
            data.get("samples"), f.get("dilution_of"), f.get("dilution_injection"),
            f.get("dilution_factor"), self.current_user_name(), _utcnow())
        if error:
            return self._redirect("{0}?batch_uid={1}&error={2}".format(
                self._self_url(), b.UID(), quote_plus(error.encode("utf-8"))))
        data["samples"] = rows
        _save_logbook(b, "252", data)
        return self._redirect("{0}?batch_uid={1}&ok={2}".format(
            self._self_url(), b.UID(), quote_plus(u"Dilution logged".encode("utf-8"))))

    # ── Batch QC (extraction_batch.py) ───────────────────────

    def members_url(self):
        b = self._get_batch()
        return u"{0}/@@pfas-extraction-batch".format(b.absolute_url()) if b is not None else u""

    def qc_members(self):
        from senaite.pfas import extraction_batch
        b = self._get_batch()
        members = extraction_batch.load(b) if b is not None else []
        by_id = dict((m["id"], m) for m in members)
        return [dict(m, parent_injection=(by_id.get(m.get("parent")) or {}).get("injection") or u"")
                for m in members if m.get("role") != u"Sample"]

    def suppliers_json(self):
        """Core Suppliers and "In-house" for the receive form (core_lists.py)."""
        from senaite.pfas.browser.core_lists import IN_HOUSE, supplier_titles
        return script_json(supplier_titles() + [IN_HOUSE]).replace("<", "\\u003c")

    def categories_json(self):
        from senaite.pfas.content.reagent import REAGENT_CATEGORIES
        return script_json(list(REAGENT_CATEGORIES))

    def _handle_receive_lot(self):
        """Receive a lot that is not in the inventory without leaving the
        stage: the same record the Reagent
        Inventory makes, then handed back to the picker. JSON in, JSON out.
        A lot number already on file is never received twice -- the answer
        says why the picker did not offer it."""
        from datetime import date
        from senaite.pfas.bench_queue import is_usable, lot_on_file
        from senaite.pfas.browser.bench_inventory import inventory_items
        from senaite.pfas.browser.reagents import STATUS_ACTIVE
        f = self.request.form
        self.request.response.setHeader("Content-Type", "application/json")
        name = (f.get("name") or u"").strip()
        lot = (f.get("lot_number") or u"").strip()
        if not name or not lot:
            return json.dumps({"ok": False, "error": u"Name and lot number are required."})
        portal = self._portal()
        existing = lot_on_file(inventory_items(portal), lot)
        if existing is not None:
            usable = is_usable(existing, date.today())
            return json.dumps({"ok": False, "exists": True, "usable": usable, "error": (
                u"Lot {0} is already in the inventory as {1}{2}.".format(
                    lot, existing.get("name"),
                    u"" if usable else u" and cannot be used ({0})".format(
                        existing.get("status") or u"expired")))})
        from senaite.pfas.browser.core_lists import problems
        bad = problems({"supplier": (f.get("supplier") or u"").strip()}, kinds=("supplier",))
        if bad:
            return json.dumps({"ok": False, "error": bad[0]})
        b = self._get_batch()
        data = {
            "uid": None, "name": name, "lot_number": lot,
            "category": (f.get("category") or u"").strip(),
            "supplier": (f.get("supplier") or u"").strip(),
            "cat_number": (f.get("cat_number") or u"").strip(),
            "manufacturer_expiry": (f.get("expiry") or u"").strip(),
            "expiry_date": u"", "opened_date": u"",
            "received_date": date.today().strftime("%Y-%m-%d"),
            "storage_location": u"", "quantity": u"", "unit": u"",
            "barcode": (f.get("barcode") or u"").strip(),
            "notes": u"Received at the bench during the extraction of {0}.".format(
                b.getId() if b is not None else u"a batch"),
            "status": STATUS_ACTIVE,
        }
        uid = _save_reagent(portal, data)
        item = [i for i in inventory_items(portal)
                if i["kind"] == u"reagent" and i["uid"] == uid]
        if not item:
            return json.dumps({"ok": False, "error": u"Saved, but the lot could not be read back."})
        i = item[0]
        return json.dumps({"ok": True, "lot": {
            "key": u"reagent:{0}".format(i["uid"]), "kind": i["kind"],
            "kind_label": i["kind_label"], "uid": i["uid"], "name": i["name"],
            "lot": i["lot_number"], "expiry": i["expiry"], "status": i["status"],
            "barcode": i["barcode"], "cat_number": i["cat_number"]}})

    def stage_draft(self):
        """The current stage's kept entries after a completion was refused
        for want of a deviation note, or {}."""
        return (self.session().get("drafts") or {}).get(
            str(self.current_stage_order())) or {}

    def stage_draft_json(self):
        return script_json(self.stage_draft())

    def _resolve_equipment(self, sns_json):
        """[{unit_id, role}] for each stage equipment serial that is registered.

        `role` is the label the stage used ("Analytical balance", "Pipette 1000 uL"),
        which is what the analyst sees, so the certificate reads the same way the
        bench form did.
        """
        try:
            sns = json.loads(sns_json or "{}") or {}
        except (ValueError, TypeError):
            return []
        try:
            from senaite.pfas import facility_qc as fq
        except Exception as exc:                            # noqa: BLE001
            logger.warning("equipment resolution unavailable: %s", exc)
            return []
        out = []
        for label, serial in sns.items():
            serial = (serial or "").strip()
            if not serial:
                continue
            try:
                unit = fq.unit_by_serial(serial)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("unit_by_serial(%r): %s", serial, exc)
                continue
            if unit:
                out.append({"unit_id": unit["id"], "role": label})
        return out

    def _handle_prepare_solution(self):
        """Record a solution prepared at the bench as a PREPARED STANDARD.

        This used to call `_save_reagent`, filing an in-house preparation as a
        level-1 MANUFACTURER reagent: `supplier="In-house"`, no catalogue number,
        no manufacturer expiry, composition buried in a free-text `notes` string
        -- and no parentage, because `IReagent` has no field that could hold any.
        The three-level ISO 17025 §6.6 chain therefore collapsed
        to two the moment a bench chemist prepared anything, and the object that
        resulted CLAIMED TO BE the manufacturer material. Because it was a
        Reagent, the traceability gate resolved it happily and reported green.

        This path was meant to "record a new
        Prepared Standard lot (parents = the stage's reagents; expiry inherits)
        … completing the 3-level traceability chain the review gate checks". It
        never did. This is that.

        The parents are the STAGE'S REAGENT ROWS, which is what D50 specifies and
        is also the strongest form available: those rows carry `inventory_uid`, a
        real Reagent UID, so the link survives a lot-number correction or a
        rename -- the uid-first resolution added for §33.7 reads it.

        Refuses when no parent is named. A parentless prepared standard is
        exactly §33.4, the traceability gate now rejects one, and telling the
        analyst at the bench beats telling them at release.
        """
        b = self._get_batch()
        if not b:
            return self._redirect("{0}?error=Batch+not+found".format(self._self_url()))
        f = self.request.form
        from datetime import date
        from senaite.pfas.browser.prepared_standards import (
            _save as _save_prepstd, effective_expiry_info)

        name = f.get("sol_name", "").strip()
        lot = f.get("sol_lot", "").strip()
        if not name or not lot:
            return self._redirect(
                "{0}?batch_uid={1}&error=Solution+name+and+lot+are+required".format(
                    self._self_url(), b.UID()))

        try:
            parents = json.loads(f.get("parent_reagents_json", "[]") or "[]")
        except (ValueError, TypeError):
            parents = []
        parents = [p for p in parents
                   if (p.get("lot") or "").strip() or (p.get("uid") or "").strip()]
        if not parents:
            return self._redirect(
                "{0}?batch_uid={1}&error=Record+the+reagent+lots+this+solution"
                "+was+made+from+before+saving+it".format(
                    self._self_url(), b.UID()))

        today = date.today().strftime("%Y-%m-%d")
        analyst = f.get("sol_analyst", "").strip()
        conc = f.get("sol_conc", "").strip()
        rec = {
            "uid":              None,
            "title":            name,
            "lot_number":       lot,
            "standard_type":    u"Solvent / Reagent",
            "logbook_slug":     "",
            "logbook_revision": 1,
            "logbook_title":    u"",
            "prepared_by":      analyst,
            "prepared_date":    today,
            # Blank lets _populate_obj apply the configured default; the
            # parent-tightened value is then resolved on read by
            # effective_expiry_info, so an expiry can never outlive its source.
            "expiry_date":      f.get("sol_expiry", "").strip(),
            "expiry_notes":     u"",
            "storage_location": f.get("sol_storage", "").strip(),
            "volume_prepared":  f.get("sol_volume", "").strip(),
            "notes":            u"Prepared at the bench during extraction batch "
                                u"{0}{1}".format(
                                    b.UID()[:8],
                                    u"; nominal concentration: {0}".format(conc)
                                    if conc else u""),
            "parent_reagents":  parents,
            "analyte_concentrations": [],
        }
        # What it was MADE WITH. The stage already collects equipment serial
        # numbers, so the solution inherits them rather than asking the analyst
        # again -- and the serial is resolved to a REGISTERED unit, because only a
        # registered one has a calibration chain the certificate can follow.
        # A serial that resolves to nothing is dropped here and reported by the
        # certificate as equipment it cannot substantiate, not silently kept.
        if f.get("equipment_posted"):
            rec["equipment"] = self._resolve_equipment(
                f.get("equipment_sns_json", "{}"))
        uid = _save_prepstd(self._portal(), rec)

        # The label shows the expiry actually in force, which may be earlier than
        # the one just stored if a parent lot expires sooner.
        try:
            from senaite.pfas.browser.prepared_standards import _get
            shown_expiry = (effective_expiry_info(
                self._portal(), _get(self._portal(), uid)) or {}).get("date", "")
        except Exception:
            shown_expiry = rec["expiry_date"]

        import urllib
        params = urllib.urlencode({
            "name":     name,
            "lot":      lot,
            "conc":     conc,
            "vol":      f.get("sol_volume", "").strip(),
            "analyst":  analyst,
            "exp":      shown_expiry,
            "date":     today,
            "back":     "{0}?batch_uid={1}".format(self._self_url(), b.UID()),
        })
        url = "{0}/@@pfas-label?{1}".format(self.portal_url(), params)
        return self._redirect(url)

    def _handle_reagent_status(self):
        b = self._get_batch()
        uid = self.request.form.get("reagent_uid", "").strip()
        new_status = self.request.form.get("new_status", "").strip()
        if uid and new_status:
            from senaite.pfas.browser.reagents import _get_reagent
            rec = _get_reagent(self._portal(), uid)
            if rec:
                rec["status"] = new_status
                _save_reagent(self._portal(), rec)
        url = "{0}?batch_uid={1}&ok=Reagent+updated".format(
            self._self_url(), b.UID() if b else "")
        return self._redirect(url)

    def _handle_finalize(self):
        b = self._get_batch()
        if not b:
            return self._redirect("{0}?error=Batch+not+found".format(self._self_url()))
        sess = _load_session(b)
        sess["finalized"] = True
        sess["finalized_at"] = _utcnow()
        sess["finalized_by"] = self.request.form.get("analyst", "").strip()
        _save_session(b, sess)

        # Write a summary stub into logbook 252 so the logbook index shows it as filled
        try:
            from senaite.pfas.browser.logbooks import _save_logbook, _get_logbook
            # MERGE onto what is already stored. _save_logbook replaces the
            # annotation wholesale, so writing this summary flat would erase
            # the samples table (and its dilution rows) that the analyst filled
            # in on the FM-ENV-003 form.
            data = dict(_get_logbook(b, "252") or {})
            data.update({
                "analyst":         sess.get("analyst", ""),
                "extraction_date": (sess.get("started_at") or "")[:10],
                "method":          sess.get("method_id", ""),
                "from_guided":     True,
                "finalized_at":    sess.get("finalized_at", ""),
                "finalized_by":    sess.get("finalized_by", ""),
            })
            # Carry the per-stage reagent and standard lots the guide collected
            # into the shape Data Review's traceability gate reads. They were
            # captured in the session and then dropped on the floor.
            reagents, standards, materials = [], [], []
            for _order in sorted((sess.get("stages") or {}), key=lambda k: int(k)):
                for rg in (sess["stages"][_order].get("reagents") or []):
                    entry = {
                        "name": rg.get("name") or "",
                        "lot": rg.get("lot") or "",
                        "supplier": rg.get("supplier") or "",
                        "volume": rg.get("volume") or "",
                        # the lot's inventory status when the stage used it:
                        # a quarantined or used-up lot is shown to the
                        # reviewer at release
                        "status_at_use": rg.get("status_at_use") or "",
                    }
                    if not entry["lot"]:
                        continue
                    if is_consumable_row(rg):
                        m = {"name": entry["name"], "lot": entry["lot"], "notes": u"",
                             "status_at_use": entry["status_at_use"]}
                        if m not in materials:
                            materials.append(m)
                        continue
                    bucket = standards if is_standard_row(rg) else reagents
                    if entry not in bucket:
                        bucket.append(entry)
            # The guide OWNS these two tables — they are derived from its own
            # per-stage scans, so replaying the stages must refresh them.
            # Preserving them instead left stale lots behind after a correction.
            # What must survive untouched is `samples`, which the analyst fills
            # in on the FM-ENV-003 form.
            if reagents:
                data["reagents"] = reagents
            if materials:
                data["extraction_materials"] = materials
            if standards:
                data["standards"] = [
                    {"name": e["name"], "lot": e["lot"], "conc": "", "volume": e["volume"],
                     "status_at_use": e.get("status_at_use") or ""} for e in standards]
            _save_logbook(b, "252", data)
        except Exception as exc:
            logger.warning("_handle_finalize: could not write logbook 252 stub: %s", exc)

        url = "{0}?batch_uid={1}&ok=Extraction+logbook+finalized".format(
            self._self_url(), b.UID())
        return self._redirect(url)
