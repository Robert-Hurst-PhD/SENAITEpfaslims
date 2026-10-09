# -*- coding: utf-8 -*-
"""@@pfas-extraction-batch on a Worksheet: the extraction batch's steps 1-3.


  1 Samples   the worksheet's samples (core's Add Analyses selects them)
  2 QC        populated from the method profile's QC composition, with the
              project plan's changes (profile_for_batch); more can be added
  3 Parents   each QC that is made from a sample gets it; spikes get a level
              (and the amount added, in the matrix's unit, when it is not the
              method's level); an LFSMD takes its LFSM's

Members are saved on the worksheet (extraction_batch.py). Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
from datetime import datetime

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import extraction_batch as eb
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.extraction_batch_view")

EDIT_ROLES = ("LabClerk", "Analyst", "LabManager", "Manager")


class PFASExtractionBatchView(BrowserView):

    template = ViewPageTemplateFile("templates/extraction_batch.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._post()
        return self.template()

    # ── what the page shows ──────────────────────────────────────────────────

    def portal_url(self):
        from bika.lims import api
        return api.get_portal().absolute_url()

    def ws(self):
        return self.context

    def can_edit(self):
        from senaite.pfas.browser.perms import has_role_at_portal
        return has_role_at_portal(self.context, EDIT_ROLES)

    def method_id(self):
        from senaite.pfas import batch_method
        return batch_method.resolve(self.context)[0]

    def profile(self):
        """The method profile with the client Batch's project plan applied."""
        if not hasattr(self, "_profile"):
            from bika.lims import api
            from senaite.pfas.method_profile_store import get_profile
            from senaite.pfas.project_specs import profile_for_batch
            mid = self.method_id()
            portal = api.get_portal()
            prof = {}
            if mid:
                try:
                    prof = profile_for_batch(portal, eb.linked_batch(self.context), mid,
                                             self.matrix()) or {}
                except Exception:                           # noqa: BLE001
                    logger.warning("project plan not applied", exc_info=True)
                prof = prof or get_profile(portal, mid) or {}
            self._profile = prof
        return self._profile

    def samples(self):
        if not hasattr(self, "_samples"):
            self._samples = eb.worksheet_samples(self.context)
        return self._samples

    def matrix(self):
        mats = [s["matrix"] for s in self.samples() if s.get("matrix")]
        return max(set(mats), key=mats.count) if mats else u""

    def unit(self):
        from senaite.pfas.calibration_levels import matrix_unit
        return matrix_unit(self.profile(), self.matrix())

    def members(self):
        """The members as saved, with the worksheet's current samples."""
        if not hasattr(self, "_members"):
            self._members = eb.follow_lfsm(eb.sync_samples(eb.load(self.context), self.samples()))
        return self._members

    def sample_members(self):
        return [m for m in self.members() if m.get("role") == u"Sample"]

    def qc_members(self):
        return [m for m in self.members() if m.get("role") != u"Sample"]

    def lfsm_members(self):
        return [m for m in self.members() if m.get("role") == u"LFSM"]

    def plan(self):
        n = len(self.sample_members())
        return eb.plan_qc(self.profile(), {}, n)

    def plan_text(self):
        plan = self.plan()
        return u", ".join(u"%s %d" % (r, plan[r]) for r in eb.QC_ROLES if plan.get(r)) or u"none"

    def shortfall(self):
        held = {}
        for m in self.qc_members():
            held[m["role"]] = held.get(m["role"], 0) + 1
        return dict((r, n - held.get(r, 0)) for r, n in self.plan().items() if n > held.get(r, 0))

    def levels(self):
        """[(label, value or None)] for the batch's matrix, in its unit."""
        from senaite.pfas.calibration_levels import level_value
        levels = self.profile().get("spike_levels") or {}
        by_type = levels if ("LFSM" in levels or "LFB" in levels) else (levels.get(self.matrix()) or {})
        out, seen = [], set()
        for qc in (u"LFSM", u"LFB", u"LCS"):
            for e in by_type.get(qc) or []:
                lab = (e.get("label") or u"").strip()
                if lab and lab not in seen:
                    seen.add(lab)
                    out.append((lab, level_value(e, self.unit())))
        return out or [(u"Low", None), (u"Mid", None), (u"High", None)]

    def size_limit(self):
        return self.profile().get("extraction_batch") or {}

    def size_text(self):
        """"9 of 20 samples" when the method sets a maximum, else ''."""
        size = eb.batch_size(self.members(), self.size_limit())
        if not size:
            return u""
        return u"%d of %d %s" % (size[0], size[1],
                                 u"members" if self.size_limit().get("count_qc") else u"samples")

    def problems(self):
        return eb.problems(self.members(), self.size_limit())

    def blank_matrix_lots(self):
        """The reference-material lots usable today: what a matrix blank is
        made from (matrix_blank.py; their assigned levels sit on the lot)."""
        if not hasattr(self, "_bm_lots"):
            from datetime import date
            from senaite.pfas.browser.bench_inventory import REAGENT, usable_lots
            from senaite.pfas.content.reagent import CATEGORY_REFERENCE
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            try:
                lots = usable_lots(portal, date.today().isoformat())
            except Exception:                                # noqa: BLE001
                lots = []
            self._bm_lots = [l for l in lots if l.get("kind") == REAGENT
                             and l.get("category") == CATEGORY_REFERENCE]
        return self._bm_lots

    def lot_options(self, m):
        """The usable lots, and the member's own lot even once it no longer is
        (a save must not drop it)."""
        lots = list(self.blank_matrix_lots())
        uid = m.get("lot") or u""
        if uid and uid not in [l.get("uid") for l in lots]:
            from senaite.pfas.browser.bench_inventory import REAGENT, item_index
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            held = item_index(portal).get((REAGENT, uid))
            lots.append(held or {"uid": uid, "name": uid, "lot_number": u""})
        return lots

    def needs_parent(self, m):
        return m.get("role") in eb.NEEDS_PARENT and m.get("role") != u"LFSMD"

    def spiked(self, m):
        return m.get("role") in eb.SPIKED

    def role_title(self, role):
        return eb.ROLE_TITLES.get(role, role)

    def add_roles(self):
        """The QC roles the method switches on (what may be added by hand)."""
        qca = self.profile().get("qc_acceptance") or {}
        return [r for r in eb.QC_ROLES if (qca.get(r) or {}).get("enabled")]

    def add_samples_url(self):
        return u"%s/add_analyses" % self.context.absolute_url()

    def guide_url(self):
        return u"%s/@@pfas-extraction-guide?batch_uid=%s" % (self.portal_url(), self.context.UID())

    # ── 4. labels ───────────────────────────────────────────────────────

    def label_containers(self):
        return [c for c in self.profile().get("extraction_labels") or [] if isinstance(c, dict)]

    def label_meta(self):
        client = eb.linked_batch(self.context)
        return {"worksheet": self.context.getId(),
                "batch": client.getId() if client is not None else u"",
                "method": self.profile().get("display_name") or self.method_id(),
                "matrix": self.matrix(),
                "date": datetime.utcnow().strftime("%Y-%m-%d"), "analyst": self._user()}

    def label_rows(self):
        return eb.label_rows(self.members(), self.label_containers(), self.label_meta())

    def labels_state(self):
        """{"issued", "current", "last"}: issued at least once, and whether
        the members still print what the last issue printed."""
        issues = eb.label_issues(self.context)
        last = issues[-1] if issues else None
        current = bool(last) and last.get("signature") == [list(r) for r in eb.labels_signature(self.members())]
        return {"issued": bool(last), "current": current, "last": last, "count": len(issues)}

    # ── 5. requests from review ─────────────────────────────────────────

    def requests(self):
        return eb.load_requests(self.context)

    def open_requests(self):
        return [r for r in self.requests() if r.get("status") == u"open"]

    def print_url(self):
        return u"%s/@@pfas-extraction-labels" % self.context.absolute_url()

    def message(self):
        return self.request.form.get("ok") or u"", self.request.form.get("error") or u""

    # ── saving ───────────────────────────────────────────────────────────────

    def _back(self, ok=u"", error=u""):
        try:
            from urllib import quote_plus
        except ImportError:                                 # pragma: no cover
            from urllib.parse import quote_plus
        q = (u"ok=" + quote_plus(ok.encode("utf-8"))) if ok else (u"error=" + quote_plus(error.encode("utf-8")))
        self.request.response.redirect(u"%s/@@pfas-extraction-batch?%s" % (self.context.absolute_url(), q))
        return u""

    def _post(self):
        from senaite.pfas.browser.perms import refuse
        if not self.can_edit():
            return refuse(self.request, "Forbidden: bench, analyst or manager role required")
        try:
            from plone.protect import CheckAuthenticator
            CheckAuthenticator(self.request)
        except ImportError:
            pass
        f = self.request.form
        action = f.get("action") or u""
        if f.get("remove"):                    # a row's Remove button
            action, f["member"] = "remove", f.get("remove")
        members = self.members()
        who = self._user()
        at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        if action == "populate":
            members = eb.populate(members, self.plan(), self.context.getId(), who, at)
            ok = u"QC populated from the method profile"
        elif action == "add":
            role = f.get("role") or u""
            if role not in self.add_roles():
                return self._back(error=u"Choose a QC type the method switches on.")
            plan = dict((r, len([m for m in members if m.get("role") == r])) for r in eb.QC_ROLES)
            plan[role] = plan.get(role, 0) + 1
            members = eb.populate(members, plan, self.context.getId(), who, at)
            ok = u"%s added" % role
        elif action == "remove":
            mid = f.get("member") or u""
            gone = [m for m in members if m["id"] == mid and m.get("role") != u"Sample"]
            if not gone:
                return self._back(error=u"Only a QC member can be removed.")
            members = [m for m in members if m["id"] != mid]
            for m in members:
                if m.get("parent") == mid or m.get("lfsm_of") == mid:
                    m["parent" if m.get("parent") == mid else "lfsm_of"] = u""
            ok = u"%s removed" % gone[0].get("injection")
        elif action == "made":
            requests, req, error = eb.mark_made(eb.load_requests(self.context), f.get("request") or u"", who, at)
            if error:
                return self._back(error=error)
            if req["kind"] == u"dilution":
                # written to the dilution log the pipeline reads (FM-ENV-003)
                from senaite.pfas import sample_table
                from senaite.pfas.browser.logbooks import _get_logbook, _save_logbook
                log = dict(_get_logbook(self.context, "252") or {})
                rows, derr = sample_table.append_dilution(
                    log.get("samples"), req["injection"], req["new_injection"], req["fold"], who, at)
                if derr:
                    return self._back(error=derr)
                log["samples"] = rows
                _save_logbook(self.context, "252", log)
            eb.save_requests(self.context, requests)
            return self._back(ok=u"%s made as %s" % (req["injection"], req["new_injection"]))
        elif action == "issue_labels":
            held = eb.problems(members, self.size_limit())
            if held:
                return self._back(error=u"Not issued: %s" % held[0])
            state = self.labels_state()
            reason = (f.get("reason") or u"").strip()
            if state["issued"] and state["current"]:
                return self._back(error=u"The labels issued are current; print them again instead.")
            if state["issued"] and not reason:
                return self._back(error=u"Say why the labels are issued again.")
            eb.record_label_issue(self.context, {
                "at": at, "by": who, "labels": len(self.label_rows()), "reason": reason,
                "signature": [list(r) for r in eb.labels_signature(members)]})
            self.request.response.redirect(self.print_url())
            return u""
        elif action == "save":
            unit = self.unit()
            for m in members:
                if m.get("role") == u"Sample":
                    continue
                key = m["id"]
                for field in ("parent", "lfsm_of", "level", "lot"):
                    if (u"%s.%s" % (key, field)) in f:
                        m[field] = (f.get(u"%s.%s" % (key, field)) or u"").strip()
                if (u"%s.amount" % key) in f:
                    amount = (f.get(u"%s.amount" % key) or u"").strip()
                    m["amount"], m["unit"] = amount, (unit if amount else u"")
            # the method blank the run compares with / subtracts
            if f.get("subtract_mb"):
                before = (eb.subtraction_blank(members) or {}).get("id")
                if f.get("subtract_mb") != before and self._run_delivered():
                    # once a run is in, a change is a review act: Data Review
                    # records it with a reason and holds release until the run
                    # is reprocessed
                    return self._back(error=u"A run is already in: change the subtraction blank "
                                            u"at Data Review, with a reason.")
                why = eb.mark_subtraction_blank(members, f.get("subtract_mb"))
                if why:
                    return self._back(error=why)
            ok = u"Saved"
        else:
            return self._back(error=u"Unknown action.")
        eb.save(self.context, eb.follow_lfsm(members))
        return self._back(ok=ok)

    def _run_delivered(self):
        from zope.annotation.interfaces import IAnnotations
        from senaite.pfas.browser.run_builder import RUN_FILES_KEY
        try:
            return bool(json.loads(IAnnotations(self.context).get(RUN_FILES_KEY) or u"[]"))
        except (TypeError, ValueError):
            return True

    def _user(self):
        try:
            user = self.context.portal_membership.getAuthenticatedMember()
            return user.getProperty("fullname") or user.getId()
        except Exception:                                   # noqa: BLE001
            return u""


class PFASExtractionLabelsView(PFASExtractionBatchView):
    """@@pfas-extraction-labels: the labels last issued, printed. The issued
    Extraction label design (Document Templates) as one PDF page per label;
    else the built-in sheet with a Code 128 barcode of each injection name."""

    template = ViewPageTemplateFile("templates/extraction_labels.pt")

    def __call__(self):
        flatten_form(self.request)
        if not self.labels_state()["issued"]:
            self.request.response.redirect(u"%s/@@pfas-extraction-batch?error=%s" % (
                self.context.absolute_url(), u"Issue+the+labels+first."))
            return u""
        if self.request.form.get("format") != "sheet":
            pdf = self._designed_pdf()
            if pdf:
                self.request.response.setHeader("Content-Type", "application/pdf")
                self.request.response.setHeader(
                    "Content-Disposition", 'inline; filename="%s-labels.pdf"' % self.context.getId())
                return pdf
        return self.template()

    def _designed_pdf(self):
        from senaite.pfas import document_templates as dt
        from senaite.pfas import pdf_renderer
        from bika.lims import api
        try:
            issued = dt.issued(dt.load(api.get_portal()), "extraction_label")
        except Exception:                                   # noqa: BLE001
            return None
        if not issued:
            return None
        _entry, rev = issued[0]
        docs = [dt.compile_document("extraction_label", rev["template"], row) for row in self.label_rows()]
        return pdf_renderer.render_documents(docs) if docs else None

    def size(self):
        from senaite.pfas import document_templates as dt
        sid = self.request.form.get("size") or u"2x1"
        s = dt.size_of("extraction_label", sid) or dt.size_of("extraction_label", u"2x1") or {}
        return {"id": sid, "w": s.get("width") or 50.8, "h": s.get("height") or 25.4}

    def sizes(self):
        from senaite.pfas import document_templates as dt
        return [s for s in dt.LABEL_SIZES if s[0] != u"a4"]

    def sheet_style(self):
        s = self.size()
        return u"--lbl-w:%smm;--lbl-h:%smm" % (s["w"], s["h"])
