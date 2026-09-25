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
from senaite.pfas.browser.reagents import _list_reagents, _save_reagent, STATUS_OPENED
from senaite.pfas.browser.formutil import flatten_form

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
        uid = self.request.form.get("batch_uid", "")
        if not uid:
            return None
        catalog = getToolByName(self.context, "uid_catalog")
        brains = catalog(UID=uid)
        if brains:
            try:
                return brains[0].getObject()
            except Exception:
                pass
        return None

    def batch_uid(self):
        return self.request.form.get("batch_uid", "")

    def batch_title(self):
        b = self._get_batch()
        return b.Title() if b else ""

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
        return json.dumps(self.session())

    # ── Method profile + stages ───────────────────────────────────────────────

    def _method_id(self):
        sess = self.session()
        return sess.get("method_id") or self.request.form.get("method_id", "FDA_32PFAS")

    def method_profile(self):
        return get_profile(self._portal(), self._method_id())

    def extraction_stages(self):
        profile = self.method_profile()
        stages = profile.get("extraction_stages", [])
        return sorted(stages, key=lambda s: s.get("order", 0))

    def current_stage_order(self):
        return int(self.session().get("current_stage", 1))

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
        return int(done / total * 100)

    # ── Reagent inventory lookup for stage reagents ───────────────────────────

    def stage_reagents_json(self):
        """For the current stage: return inventory matches for each reagent role."""
        stage = self.current_stage()
        roles = stage.get("reagent_roles", [])
        portal = self._portal()
        result = {}
        for role in roles:
            matches = _list_reagents(portal, q=role.split("(")[0].strip())[:5]
            result[role] = [
                {
                    "uid":         r.get("uid", ""),
                    "name":        r.get("name", ""),
                    "lot_number":  r.get("lot_number", ""),
                    "expiry_date": r.get("expiry_date") or r.get("manufacturer_expiry", ""),
                    "status":      r.get("status", ""),
                }
                for r in matches
            ]
        return json.dumps(result)

    # ── Pedigree ──────────────────────────────────────────────────────────────

    def pedigree(self):
        return self.session().get("pedigree", {})

    def pedigree_json(self):
        return json.dumps(self.pedigree())

    # ── Available methods for start form ─────────────────────────────────────

    def available_methods(self):
        from senaite.pfas.method_profile_store import DEFAULT_PROFILES
        return [
            (mid, p.get("display_name", mid))
            for mid, p in sorted(DEFAULT_PROFILES.items())
            if p.get("extraction_stages")
        ]

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
        method_id = self.request.form.get("method_id", "FDA_32PFAS")
        analyst = self.request.form.get("analyst", "").strip()
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

        # Update reagent inventory status for any flagged lots
        for rg in reagents:
            uid = rg.get("inventory_uid", "")
            new_status = rg.get("new_status", "")
            if uid and new_status:
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
            "analyst":             f.get("stage_analyst", sess.get("analyst", "")).strip(),
            "reagents":            reagents,
            "equipment_sns":       json.loads(f.get("equipment_sns_json", "{}")),
            "deviations":          f.get("deviations", "").strip(),
            "solutions_prepared":  json.loads(f.get("solutions_prepared_json", "[]")),
        }
        stages = sess.setdefault("stages", {})
        stages[str(stage_order)] = stage_data

        # Advance to next stage
        all_orders = sorted(s.get("order", 0) for s in
                            get_profile(self._portal(), sess.get("method_id", "")).get("extraction_stages", []))
        current = int(stage_order)
        remaining = [o for o in all_orders if o > current]
        sess["current_stage"] = remaining[0] if remaining else current

        _save_session(b, sess)
        url = "{0}?batch_uid={1}&ok=Stage+completed".format(self._self_url(), b.UID())
        return self._redirect(url)

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

    def _handle_prepare_solution(self):
        b = self._get_batch()
        if not b:
            return self._redirect("{0}?error=Batch+not+found".format(self._self_url()))
        f = self.request.form
        # Save the new solution as a reagent in inventory
        from datetime import date
        from senaite.pfas.browser.reagents import _auto_expiry_from_open
        name = f.get("sol_name", "").strip()
        lot = f.get("sol_lot", "").strip()
        today = date.today().strftime("%Y-%m-%d")
        auto_exp = _auto_expiry_from_open(name, today)
        rec = {
            "name":             name,
            "category":         "Extraction Reagent",
            "supplier":         "In-house",
            "cat_number":       "",
            "lot_number":       lot,
            "received_date":    today,
            "opened_date":      today,
            "manufacturer_expiry": "",
            "expiry_date":      auto_exp,
            "storage_location": f.get("sol_storage", "").strip(),
            "quantity":         f.get("sol_volume", "").strip(),
            "unit":             "mL",
            "notes":            u"Prepared during extraction batch {0}; "
                                u"concentration: {1}; prepared by: {2}".format(
                                    b.UID()[:8],
                                    f.get("sol_conc", ""),
                                    f.get("sol_analyst", ""),
                                ),
            "status":           STATUS_OPENED,
        }
        _save_reagent(self._portal(), rec)
        # Redirect to label printer
        import urllib
        params = urllib.urlencode({
            "name":     name,
            "lot":      lot,
            "conc":     f.get("sol_conc", ""),
            "vol":      f.get("sol_volume", ""),
            "analyst":  f.get("sol_analyst", ""),
            "exp":      auto_exp,
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
            # in on the FM-ENV-252 form.
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
            reagents, standards = [], []
            for _order in sorted((sess.get("stages") or {}), key=lambda k: int(k)):
                for rg in (sess["stages"][_order].get("reagents") or []):
                    entry = {
                        "name": rg.get("name") or "",
                        "lot": rg.get("lot") or "",
                        "supplier": rg.get("supplier") or "",
                        "volume": rg.get("volume") or "",
                    }
                    if not entry["lot"]:
                        continue
                    bucket = standards if (rg.get("supplier") == "In-house"
                                           or "standard" in entry["name"].lower()
                                           or "spike" in entry["name"].lower()) \
                        else reagents
                    if entry not in bucket:
                        bucket.append(entry)
            # The guide OWNS these two tables — they are derived from its own
            # per-stage scans, so replaying the stages must refresh them.
            # Preserving them instead left stale lots behind after a correction.
            # What must survive untouched is `samples`, which the analyst fills
            # in on the FM-ENV-252 form.
            if reagents:
                data["reagents"] = reagents
            if standards:
                data["standards"] = [
                    {"name": e["name"], "lot": e["lot"],
                     "conc": "", "volume": e["volume"]} for e in standards]
            _save_logbook(b, "252", data)
        except Exception as exc:
            logger.warning("_handle_finalize: could not write logbook 252 stub: %s", exc)

        url = "{0}?batch_uid={1}&ok=Extraction+logbook+finalized".format(
            self._self_url(), b.UID())
        return self._redirect(url)
