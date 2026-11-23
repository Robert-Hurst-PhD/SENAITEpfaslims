# -*- coding: utf-8 -*-
"""@@pfas-extraction-batch on a Worksheet: the extraction batch's steps 1-3.


  1 Samples   the worksheet's samples (added on @@pfas-worksheet-samples)
  2 QC        populated from the method profile's QC composition, with the
              project plan's changes (profile_for_batch); more can be added
  3 Parents   each QC that is made from a sample gets it; spikes get a level
              (and the amount added, in the matrix's unit, when it is not the
              method's level); an LFSMD takes its LFSM's; a spike created
              with its spike keys records the lot it was made with, chosen
              from the inventory, and the volume added

Members are saved on the worksheet (extraction_batch.py). Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
from datetime import datetime

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import extraction_batch as eb
from senaite.pfas import lab_time
from senaite.pfas import print_doc
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.label_pdf import LabelPrint

logger = logging.getLogger("senaite.pfas.extraction_batch_view")

EDIT_ROLES = ("LabClerk", "Analyst", "LabManager", "Manager")


class PFASExtractionBatchView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/extraction_batch.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            return self._post()
        return self.template()

    # ── what the page shows ──────────────────────────────────────────────────

    def ws(self):
        return self.context

    def can_edit(self):
        from senaite.pfas.browser.perms import has_role_at_portal
        return has_role_at_portal(self.context, EDIT_ROLES)

    def finalised(self):
        """Whether the extraction is finalised (the session's flag, which a
        send back clears): its members are then read only (finalised_refusal)."""
        if not hasattr(self, "_finalised"):
            from senaite.pfas.browser.extraction_guide import _load_session
            self._finalised = bool((_load_session(self.context) or {}).get("finalized"))
        return self._finalised

    def may_change_members(self):
        return self.can_edit() and not self.finalised()

    def method_id(self):
        """The worksheet's method, by the rule every page shares; read once
        a request (the template asks often, and the rule wakes samples)."""
        if not hasattr(self, "_method_id"):
            from senaite.pfas import batch_method
            self._method_id = batch_method.for_worksheet(self.context)
        return self._method_id

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
        # the matrix chosen with the worksheet's method; a worksheet from
        # before one was stored: the one most of its samples are
        from senaite.pfas.worksheet_samples import stored_matrix
        stored = stored_matrix(self.context)
        if stored:
            return stored
        mats = [s["matrix"] for s in self.samples() if s.get("matrix")]
        if mats:
            return max(set(mats), key=mats.count)
        # a study worksheet holds no sample: its matrix is the study's
        from senaite.pfas import study_runs
        return (study_runs.load_run(self.context) or {}).get("matrix") or u""

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

    def reextraction_of(self, member):
        """The worksheet a sample was withheld from for re-extraction, shown
        beside it ("Re-extraction of WS-358"), or "" (the portal's registry,
        written when the re-extraction was saved)."""
        if not hasattr(self, "_reextractions"):
            from senaite.pfas import annotation_store
            from senaite.pfas.browser.extraction_corrections import REGISTRY_KEY
            try:
                from bika.lims import api
                portal = api.get_portal()
                self._reextractions = annotation_store.read_json(portal, REGISTRY_KEY, {}) or {}
            except Exception:                               # noqa: BLE001
                self._reextractions = {}
        from senaite.pfas.browser.extraction_corrections import reextraction_of
        ws = reextraction_of(self._reextractions, (member or {}).get("sample_uid") or u"")
        return ws if ws and ws != self.context.getId() else u""

    def qc_members(self):
        return [m for m in self.members() if m.get("role") != u"Sample"]

    def lfsm_members(self):
        return [m for m in self.members() if m.get("role") == u"LFSM"]

    def plan(self):
        # a study batch holds its part's replicates (made when the part was
        # assigned) and owes no routine QC
        from senaite.pfas import study_runs
        if study_runs.load_run(self.context) is not None:
            return {}
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
        """The method's worksheet size with its box's state (limit_states)."""
        from senaite.pfas import limit_states
        profile = self.profile()
        return dict(profile.get("extraction_batch") or {},
                    state=limit_states.box_state(profile, "worksheet_size"))

    def size_text(self):
        """"9 of 20 samples" when the method sets a maximum, else ''."""
        size = eb.batch_size(self.members(), self.size_limit())
        if not size:
            return u""
        words = u"%d of %d %s" % (size[0], size[1],
                                  u"members" if self.size_limit().get("count_qc") else u"samples")
        advisory = eb.size_advisory(self.members(), self.size_limit())
        return words + (u" \u00b7 " + advisory if advisory else u"")

    def problems(self):
        return eb.problems(self.members(), self.size_limit())

    def blank_matrix_lots(self):
        """The reference-material lots usable today: what a matrix blank is
        made from (matrix_blank.py; their assigned levels sit on the lot)."""
        if not hasattr(self, "_bm_lots"):
            from senaite.pfas import lab_time
            from senaite.pfas.browser.bench_inventory import REAGENT, usable_lots
            from senaite.pfas.content.reagent import CATEGORY_REFERENCE
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            try:
                lots = usable_lots(portal, lab_time.today().isoformat())
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

    def member_name(self, mid):
        """A member's injection name by its id, an em dash for none."""
        hit = [m for m in self.members() if m.get("id") == mid] if mid else []
        return (hit[0].get("injection") or mid) if hit else u"\u2014"

    def lot_name(self, m):
        """A blank-matrix member's lot as its drop-down names it."""
        uid = m.get("lot") or u""
        hit = [l for l in self.lot_options(m) if l.get("uid") == uid] if uid else []
        return (u"%s %s" % (hit[0].get("name") or u"", hit[0].get("lot_number") or u"")).strip() if hit \
            else (uid or u"\u2014")

    def spike_lots(self):
        """The lots usable today a spike can be made with: prepared
        standards and reference-material reagents, by lot number."""
        if not hasattr(self, "_spike_lots"):
            from senaite.pfas import lab_time
            from senaite.pfas.browser.bench_inventory import PREPARED, REAGENT, usable_lots
            from senaite.pfas.content.reagent import CATEGORY_REFERENCE
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            try:
                lots = usable_lots(portal, lab_time.today().isoformat())
            except Exception:                                # noqa: BLE001
                lots = []
            self._spike_lots = [l for l in lots if l.get("lot_number") and (
                l.get("kind") == PREPARED
                or (l.get("kind") == REAGENT and l.get("category") == CATEGORY_REFERENCE))]
        return self._spike_lots

    def spike_lot_options(self, m):
        """[(lot number, label)]: the usable spike lots, and the member's own
        lot even once it no longer is (a save must not drop it)."""
        out = [(l["lot_number"], u"%s %s" % (l.get("name") or u"", l["lot_number"]))
               for l in self.spike_lots()]
        own = (m.get("spike_lot") or u"").strip()
        if own and own not in [k for k, _l in out]:
            out.append((own, own))
        return out

    def records_spike(self, m):
        return eb.records_spike(m)

    def follows_lfsm(self, m):
        """An LFSMD's spike cells (eb.lfsmd_spike_cells); None for any other
        member."""
        return eb.lfsmd_spike_cells(m, self.members())

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
        return u"%s/@@pfas-worksheet-samples" % self.context.absolute_url()

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
                "date": lab_time.today().isoformat(), "analyst": self._user()}

    def label_rows(self):
        return eb.label_rows(self.members(), self.label_containers(), self.label_meta())

    def labels_state(self):
        """{"issued", "current", "last"}: issued at least once, and whether
        the members still print what the last issue printed."""
        issues = eb.label_issues(self.context)
        last = issues[-1] if issues else None
        current = bool(last) and last.get("signature") == [list(r) for r in eb.labels_signature(self.members())]
        at = (last or {}).get("at") or u""
        return {"issued": bool(last), "current": current, "last": last, "count": len(issues),
                "at": print_doc.lab_or(at, at[:16].replace("T", " "))}

    # ── 5. requests from review ─────────────────────────────────────────

    def requests(self):
        return eb.load_requests(self.context)


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
        refused = eb.finalised_refusal(action, members, f, self.finalised())
        if refused:
            return self._back(error=refused)
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
                # written to the dilution log the pipeline reads (the extraction record)
                from senaite.pfas import extraction_store, sample_table
                log = dict(extraction_store.load_table(self.context))
                rows, derr = sample_table.append_dilution(
                    log.get("samples"), req["injection"], req["new_injection"], req["fold"], who, at)
                if derr:
                    return self._back(error=derr)
                log["samples"] = rows
                extraction_store.save_table(self.context, log)
            eb.save_requests(self.context, requests)
            return self._back(ok=u"%s made as %s" % (req["injection"], req["new_injection"]))
        elif action == "issue_labels":
            held = eb.problems(members, self.size_limit())
            if held:
                return self._back(error=u"Not issued: %s" % held[0])
            state = self.labels_state()
            if self.finalised() and not state["issued"]:
                # a first issue names the members (and numbers the batch):
                # never once the extraction is finalised
                return self._back(error=eb.FINALISED_REFUSED)
            reason = (f.get("reason") or u"").strip()
            if state["issued"] and state["current"]:
                return self._back(error=u"The labels issued are current; print them again instead.")
            if state["issued"] and not reason:
                return self._back(error=u"Say why the labels are issued again.")
            # the injection names (injection_names.py): a batch issued for the
            # first time takes its number for the day and every member its
            # name by the scheme; a batch issued before the scheme keeps its
            # names, a scheme batch names only members added since
            code = eb.batch_code_of(self.context)
            if not code and not state["issued"]:
                from bika.lims import api
                code = eb.issue_batch_code(api.get_portal(), self.context, at[:10])
            if code:
                from senaite.pfas import injection_names as nm
                prof = self.profile() or {}
                named = eb.name_members(members, nm.method_code(prof, self.method_id()),
                                        lambda mx: nm.matrix_code(prof, mx), code)
                if self.finalised() and eb.renamed(members, named):
                    return self._back(error=eb.FINALISED_REFUSED)
                members = named
                if not self.finalised():
                    eb.save(self.context, eb.follow_lfsm(members))
                    self._members = members
            eb.record_label_issue(self.context, {
                "at": at, "by": who, "labels": len(self.label_rows()), "reason": reason,
                "signature": [list(r) for r in eb.labels_signature(members)]})
            self.request.response.redirect(self.print_url())
            return u""
        elif action == "save":
            # once finalised a save writes the subtraction blank alone: every
            # member fact stays as the finaliser signed it (finalised_refusal)
            locked = self.finalised()
            if not locked:
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
                # each spike's lot and volume, on the members that record them
                spikes = {}
                for m in members:
                    key = m["id"]
                    if eb.records_spike(m) and (u"%s.spike_lot" % key) in f:
                        volume = f.get(u"%s.spike_volume_ul" % key) or u""
                        why = eb.spike_volume_problem(volume)
                        if why:
                            return self._back(error=u"%s: %s" % (m.get("injection") or key, why))
                        spikes[key] = (f.get(u"%s.spike_lot" % key) or u"", volume)
                members = eb.set_spikes(members, spikes)
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
        if self.finalised():
            eb.save(self.context, members)
            return self._back(ok=ok)
        members = eb.follow_lfsm(members)
        eb.save(self.context, members)
        self._record_spike_uses(members, who, at)
        return self._back(ok=ok)

    def _spike_lot_resolver(self):
        """A spike lot number to the inventory lot it names, (kind, uid), or
        None: the spike lots offered first, then any lot of that number."""
        from bika.lims import api
        from senaite.pfas.browser.bench_inventory import inventory_items
        offered = [(l["kind"], l["uid"], l.get("lot_number")) for l in self.spike_lots()]
        try:
            every = [(i["kind"], i["uid"], i.get("lot_number")) for i in inventory_items(api.get_portal())]
        except Exception:                                    # noqa: BLE001
            every = []
        by_lot = {}
        for kind, uid, number in every[::-1] + offered[::-1]:
            if number:
                by_lot[number] = (kind, uid)
        return by_lot.get

    def _record_spike_uses(self, members, who, at):
        """Each spike is a use of its lot in the usage ledger: saving the
        batch replaces its spike rows and no other stage's."""
        from senaite.pfas import inventory_ledger, worksheet_lots
        try:
            rows = worksheet_lots.spike_ledger_rows(members, self._spike_lot_resolver())
            inventory_ledger.record_stage(None, self.context.UID(), self.context.getId(),
                                          worksheet_lots.SPIKE_STAGE, worksheet_lots.SPIKE_STAGE_NAME,
                                          rows, who, at)
        except Exception as exc:                            # noqa: BLE001
            logger.error("usage ledger: the spikes of %s not written: %s", self.context.getId(), exc)

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


class PFASExtractionLabelsView(LabelPrint, PFASExtractionBatchView):
    """@@pfas-extraction-labels: the labels last issued, printed from the
    issued Extraction labels design (Document Templates), one PDF page per
    label (label_pdf.LabelPrint)."""

    label_kind = "extraction_label"

    def __call__(self):
        flatten_form(self.request)
        if not self.labels_state()["issued"]:
            self.request.response.redirect(u"%s/@@pfas-extraction-batch?error=%s" % (
                self.context.absolute_url(), u"Issue+the+labels+first."))
            return u""
        return self.labels_response(self.label_rows(), "%s-labels.pdf" % self.context.getId())

    def label_subject(self):
        return self.context.getId()

    def label_back(self):
        return (u"Extraction worksheet", u"%s/@@pfas-extraction-batch" % self.context.absolute_url())
