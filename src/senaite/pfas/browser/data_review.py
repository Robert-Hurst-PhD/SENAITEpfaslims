# -*- coding: utf-8 -*-
"""
PFAS Data Review workspace (@@pfas-data-review).

Per-batch checklist for Analyst data release:
  - Chain of Custody (manual)
  - Reagent/Standard Traceability (auto)
  - QC Summary (auto)
  - Final Data Summary (manual)
  - Instrument Report (manual + file attachment)

Signs off via native SENAITE Worksheet DCWorkflow:
  Analyst: submit -> to_be_verified
  Manager: verify -> verified

Audit trail: each review act on the worksheet's own trail (records.log).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import csv
import datetime
import io
import json
import logging
import mimetypes
import os
import re

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from senaite.pfas.logbook_schema import active_rows
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (
    ANALYST_ROLES, MANAGER_ROLES, disable_csrf, has_role_at_portal, refuse)
from senaite.pfas.qc_qualification import format_remark_codes
# Safe at module scope BECAUSE holding_time, lab_time and print_doc import
# nothing from Plone at load -- there is no import-order hazard. Most add-on helpers in this file are imported
# locally inside the method that needs them (see _bapi, analytes_for_failure,
# get_batch); do not copy this pattern for a module that does touch Plone.
from senaite.pfas import above_range as _above_range
from senaite.pfas.above_range import REASONS_KEY as ABOVE_RANGE_REASONS_KEY
from senaite.pfas import holding_time
from senaite.pfas import lab_time
from senaite.pfas import print_doc

logger = logging.getLogger("senaite.pfas.browser.data_review")

from senaite.pfas.study_runs import CHECKLIST_KEY  # noqa: E402  (one definition)
# pure, like holding_time: the refusal while a raw run's edits wait is said once
from senaite.pfas.raw_edit import FAILED_TEXT as RAW_FAILED_TEXT  # noqa: E402
from senaite.pfas.raw_edit import WAITING_TEXT as RAW_WAITING_TEXT  # noqa: E402
INSTRUMENT_REPORT_DIR = os.environ.get("PFAS_INSTRUMENT_REPORTS", "/data/instrument_reports")
# the QC result the worker files for a sample's result above the calibration
# range with no dilution (above_range)
ABOVE_RANGE_QC_TYPE = _above_range.QC_TYPE
# and for a sample's result the instrument wrote BLoQ with no number
from senaite.pfas import no_number as _no_number  # noqa: E402
from senaite.pfas.injection_identity import KEY as IDENTITY_KEY  # noqa: E402
from senaite.pfas.review_send_back import KEY as SEND_BACK_KEY  # noqa: E402
# a method revision as the sign dialog names it: major.sub
from senaite.pfas.method_revisions import revision_text as _method_revision_text  # noqa: E402
DEFAULT_DB_PATH       = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")


def on_after_transition(instance, event):
    """Freeze the resolved QC criteria whenever a Worksheet reaches `verified`,
    by WHATEVER route got it there.

    This began life as a direct call inside `_handle_approve_release()`, which
    made the freeze a property of one button: a worksheet verified from a native
    SENAITE listing, a script, or any other workflow action skipped it, and the
    record then read "not recorded" for work that genuinely had been judged —
    missing precisely when it mattered. Hanging it on the transition instead
    makes it a property of the verification itself.

    Same shape as `controlled_publications.on_after_transition`, and for the
    same reason: an immutable record must be written every time the thing it
    records happens, not every time someone uses the expected screen.

    The reject path is the fast path — this handler runs on EVERY transition in
    the site — and it can NEVER raise. A subscriber that raises aborts the
    transaction, which would roll back the very verification it exists to
    record: a far worse defect than the one it fixes.
    """
    if getattr(event, "transition", None) is None:
        return
    from senaite.pfas.worksheet_criteria_snapshot import should_freeze
    if not should_freeze(getattr(instance, "portal_type", None),
                         event.transition.id):
        return
    try:
        # Reuse the view's own resolvers rather than reimplementing them.
        # batch_method()/_batch_matrix() derive purely from the worksheet (its
        # method, else its analyses' methods and sample types), and
        # _get_worksheet() returns self.context when the context IS a
        # Worksheet — so traversed here they answer about THIS worksheet.
        # controlled_publications._review_state_at_issue does the same.
        review = instance.restrictedTraverse(str("@@pfas-data-review"))
        from senaite.pfas import worksheet_criteria_snapshot
        worksheet_criteria_snapshot.freeze_resolved_criteria(
            review._portal(), instance, review._linked_batch(instance),
            review.batch_method(), review._batch_matrix())
    except Exception as exc:                                    # noqa: BLE001
        logger.error("criteria-freeze: failed for worksheet %s on verify: %s",
                     getattr(instance, "getId", lambda: "?")(), exc)
    # each result keeps the reporting limit it was verified with
    try:
        from senaite.pfas import verified_rl
        review = instance.restrictedTraverse(str("@@pfas-data-review"))
        verified_rl.freeze_worksheet(review._portal(), instance)
    except Exception as exc:                                    # noqa: BLE001
        logger.error("RL freeze: failed for worksheet %s on verify: %s",
                     getattr(instance, "getId", lambda: "?")(), exc)
    # the worksheet keeps the QC types not run and the deviations that
    # released them, as verified
    try:
        from senaite.pfas import verified_rl
        review = instance.restrictedTraverse(str("@@pfas-data-review"))
        verified_rl.freeze_worksheet_not_run(instance, lambda: review.qc_types_not_run(instance))
    except Exception as exc:                                    # noqa: BLE001
        logger.error("not-run freeze: failed for worksheet %s on verify: %s",
                     getattr(instance, "getId", lambda: "?")(), exc)

# Ordered checklist items (key, label, auto-computed)
_CHECKLIST_ITEMS = [
    ("coc",               u"Chain of Custody",              False),
    ("traceability",      u"Reagent/Standard Traceability", True),
    ("qc_summary",        u"QC Summary",                    True),
    ("final_data",        u"Final Data Summary",            False),
    ("instrument_report", u"Instrument Report",             False),
]


# A non-human actor attests differently from a person, and the difference has to
# be recorded at the moment of attestation or it cannot be reconstructed later.
#
# Membership of this GROUP is what makes an account automated -- not a name
# pattern, not a parallel list in a Python constant.: visibility and
# authority key off the permissions SENAITE already enforces, never a second
# permission system. So granting or revoking automation is a group membership
# change in the normal Plone UI, and an auditor can see who is in it.
#
# This is a group ID, not a title. `getGroups()` returns IDs, so it must match
# exactly -- and a mismatch fails SILENTLY, classifying every service account as
# human, which is the failure direction that matters. Hence no space and the
# CamelCase this site already uses (Analysts, LabManagers,
# RegulatoryInspectors), and hence `setup_automation_group()` in setuphandlers
# CREATES it rather than leaving a lab to type the id correctly.
#
# It deliberately grants NO roles. It classifies an account; it does not empower
# one. A service account still needs Analyst or LabManager from the normal role
# model to reach this view at all (`can_act`), so capability and classification
# stay separate -- do not attach permissions to this group.
AUTOMATION_GROUP = "PFASAutomation"

# an interim certificate is released in Submit's sign dialog
INTERIM_SIGN_FIRST = u"Sign the interim certificate to submit."
# before verification a final signed on the card would replace the interim
# certificate that waits to be issued
INTERIM_WAITS = u"An interim certificate waits to be issued: issue it before signing the final."


def changed_after(change_at, written_at):
    """True when a change ("2026-10-09 12:00 UTC") is later than the run's
    last QC write ("2026-10-09T11:59:30"); False when either is unreadable
    and there is no write at all is treated as pending."""
    if not change_at:
        return False
    text = change_at.replace(u" UTC", u"")
    try:
        changed = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S" if text.count(u":") == 2
                                             else "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    if not written_at:
        return True
    try:
        written = datetime.datetime.strptime(written_at[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return written < changed


def _lab_day(at):
    """"YYYY-MM-DD": the laboratory's day of a recorded UTC instant (a run's
    build, a send-back); the stored text's first ten characters while the
    zone does not convert."""
    at = at or u""
    return print_doc.lab_or(at, at[:10], u"%Y-%m-%d")


def _actor_kind(user=None):
    """``"automated"`` if the acting user is a declared service account.

    ISO 17025 requires results to be authorised by a competent, authorised
    PERSON. A service account cannot hold a competence record or take
    responsibility, so its attestation is evidence gathered, not authorisation
    given -- and the two must not be indistinguishable in the record.

    Fails CLOSED to "human": an unreadable group list must not silently reclassify
    a person's sign-off as machine output, which would discard a valid
    attestation. The risk runs the other way (a service account mistaken for a
    person), and that is why membership is explicit rather than inferred.
    """
    try:
        if user is None:
            user = getSecurityManager().getUser()
        groups = user.getGroups() if hasattr(user, "getGroups") else []
        return u"automated" if AUTOMATION_GROUP in (groups or []) else u"human"
    except Exception:
        return u"human"


# Resolved at the portal via perms: resolved at the context, a
# local role on any object reached through a for="*" view counted.
def _is_manager(context):
    return has_role_at_portal(context, MANAGER_ROLES)


def _is_analyst(context):
    # SENAITE core grants no worksheet-local Analyst role (it only ever grants
    # Owner locally), so nothing relied on resolving this at the worksheet.
    return has_role_at_portal(context, ANALYST_ROLES)


# A lot cell an analyst has filled in to mean "this material has no lot number".
# Dry ice, compressed gas and a machined part genuinely have none, and the
# processing stage on the released WS-0005 records exactly that: `{"name": "Dry ice", "lot": "N/A"}`.
#
# Treated as NO LOT, which is what the analyst meant, not as a lot that failed to
# resolve. Resolving it would have invented a traceability failure for dry ice the
# first time the 253 walk ran. It is REPORTED, though (see the warnings), because
# the supported way to say "not applicable" is to strike the row -- `active_rows`
# already makes a struck row inert -- and free text saying it informally should not
# be silently equivalent.
#
# Not a new hole: a BLANK lot is already skipped everywhere in this walk, so this
# only recognises the same statement written a different way.
_LOT_SENTINELS = frozenset((
    u"n/a", u"na", u"n.a.", u"none", u"nil", u"-", u"--", u"not applicable",
))


def lot_or_none(raw):
    """(lot, sentinel_text). `lot` is u"" when the cell names no lot at all."""
    lot = (raw or u"").strip()
    if lot.lower() in _LOT_SENTINELS:
        return u"", lot
    return lot, u""



def _rejected_after(obj, used_on):
    """The lot was rejected at review on or after the day it was used."""
    from senaite.pfas import lot_status as ls
    return ls.rejected_after_use(IAnnotations(obj).get(ls.QUARANTINE_KEY), used_on)



def _run_order(rows):
    """Injection rows in the order the run acquired them."""
    return sorted(rows or [], key=lambda r: (r.get("acquired_at") or u"", r.get("id") or 0))

class PFASDataReviewView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/data_review.pt")
    # {lot: reason} of the worksheet whose traceability is being built
    _use_reasons = None

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            if self.request.form.get("action", "") == "download_report":
                return self._handle_download_report()
            if not self.can_act():
                if (self.request.form.get("action", "") in ("raw_edit", "raw_apply_all", "raw_processing_undo")
                        and self._wants_json()):
                    self.request.response.setHeader("Content-Type", "application/json; charset=utf-8")
                    return refuse(self.request, json.dumps({"ok": False, "error": self.RAW_NO_RIGHTS}))
                return refuse(self.request)
            disable_csrf(self.request)
            return self._handle_post()
        if self.request.form.get("export") == "comparison":
            return self._comparison_csv()
        if self.request.form.get("raw_card"):
            return self._raw_card_json()
        if self.request.form.get("raw_status"):
            return self._raw_status_json()
        if self.request.form.get("raw_tab"):
            return self._raw_tab_reply()
        return self.template()

    # ── Context resolution ────────────────────────────────────────────────

    def _get_worksheet(self):
        """Return the Worksheet object from context or query params, or None."""
        if getattr(self.context, "portal_type", "") == "Worksheet":
            return self.context
        cat = getToolByName(self.context, "senaite_catalog_worksheet")
        uid = (self.request.form.get("batch_uid") or "").strip()
        if uid:
            brains = cat(UID=uid, portal_type="Worksheet")
            if brains:
                return brains[0].getObject()
        bid = (self.request.form.get("batch_id") or "").strip()
        if bid:
            brains = cat(portal_type="Worksheet", id=bid)
            if brains:
                return brains[0].getObject()
        return None

    # ── Identity accessors ────────────────────────────────────────────────

    def batch_id(self):
        ws = self._get_worksheet()
        return ws.getId() if ws else u""

    def extraction_guide_url(self):
        """The guided extraction of this worksheet's batch (its spike record)."""
        ws = self._get_worksheet()
        if ws is None:
            return u"{0}/@@pfas-extraction-guide".format(self.portal_url())
        return u"{0}/@@pfas-extraction-batch".format(ws.absolute_url())

    def batch_uid(self):
        ws = self._get_worksheet()
        if not ws:
            return u""
        try:
            return ws.UID() or ws.getId()
        except Exception:
            return ws.getId()

    def batch_title(self):
        ws = self._get_worksheet()
        if not ws:
            return u""
        try:
            return ws.Title() or ws.getId()
        except Exception:
            return ws.getId()

    def batch_url(self):
        ws = self._get_worksheet()
        return ws.absolute_url() if ws else u""

    def batch_method(self):
        """The ONE resolver (batch_method.py; core first) for the worksheet's batch; a worksheet without a batch
        reads its own method or its analyses'. Once per request: the page asks
        ~130 times, and each walk reads every analysis (a 35 s Data Review)."""
        if not hasattr(self, "_batch_method_cache"):
            self._batch_method_cache = self._batch_method_uncached()
        return self._batch_method_cache

    def _batch_method_uncached(self):
        from senaite.pfas import batch_method as bm
        ws = self._get_worksheet()
        return bm.for_worksheet(ws) if ws else u""

    def has_run(self):
        """True once a run of this worksheet is on record with its QC rows:
        "no departure detected" says nothing about a worksheet with no data,
        and a run registered with no QC row was not imported."""
        ws = self._get_worksheet()
        if ws is None or not self.db_available:
            return False
        try:
            store = self._store()
            return store.get_batch(ws.getId()) is not None and store.has_qc_results(ws.getId())
        except Exception:                                   # noqa: BLE001
            return False

    def _run_integration_mode(self):
        """The results source this worksheet's run was built or uploaded
        under, from its run record beside its file (the latest full run
        uploaded, else the raw run's), or None when it carries none or its
        records cannot be read (the method's mode is read then)."""
        from senaite.pfas import raw_expect
        from senaite.pfas.browser.run_builder import RUN_FILES_KEY, UPLOAD_DIR
        ws = self._get_worksheet()
        if ws is None:
            return None
        try:
            files = json.loads(IAnnotations(ws).get(RUN_FILES_KEY) or u"[]")
            full = [f for f in files if isinstance(f, dict) and f.get("kind") == u"full" and f.get("file")]
            stems = [os.path.splitext(f["file"])[0]
                     for f in sorted(full, key=lambda f: f.get("at") or u"", reverse=True)]
            raw = (self._run_manifest(ws).get("raw_expectation") or {}).get("stem")
            if raw:
                stems.append(raw)
            return raw_expect.run_mode([os.path.join(UPLOAD_DIR, s + u"_extraction.json") for s in stems])
        except Exception as exc:                            # noqa: BLE001
            logger.warning("run mode of %s unread: %s", ws.getId(), exc)
            return None

    def import_problems(self):
        """Run files delivered for this worksheet that the worker could not
        import yet (retrying) or gave up on (failed)."""
        ws = self._get_worksheet()
        if ws is None or not self.db_available:
            return []
        try:
            return self._store().import_problems(ws.getId())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("import_problems: %s", exc)
            return []

    def import_refusals(self):
        """Run files delivered after the worksheet closed, refused by the
        worker: the record stands, nothing is held."""
        ws = self._get_worksheet()
        if ws is None or not self.db_available:
            return []
        try:
            return [ip for ip in self._store().import_problems(ws.getId(), refused=True)
                    if ip.get("status") == "refused"]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("import_refusals: %s", exc)
            return []

    def ws_state(self):
        ws = self._get_worksheet()
        if not ws:
            return u"open"
        wf_tool = getToolByName(self.context, "portal_workflow")
        state = wf_tool.getInfoFor(ws, "review_state", "open")
        if self._study_review(ws):
            from senaite.pfas.study_runs import checklist_review_state
            return checklist_review_state(state, False, self._get_checklist(ws))
        return state

    def ws_state_title(self):
        """The worksheet's state as core titles it, for the eye; ws_state
        stays the id the page's logic reads."""
        from senaite.pfas.browser.sample_status import _state_title
        return _state_title(self._get_worksheet() or self.context, self.ws_state())

    def _study_review(self, ws):
        """A study worksheet without analyses: its review is this checklist
        (core cannot submit or verify an empty worksheet)."""
        try:
            return self.study_run() is not None and not (ws.getAnalyses() or [])
        except Exception:                                   # noqa: BLE001
            return False

    def active_tab(self):
        tab = self.request.form.get("tab", "overview")
        # the Samples tab joined Final Data (each result shows its instrument
        # result and RT): an old link lands there
        if tab == "samples":
            return "final_data"
        # a tab the strip does not list is not drawn: its address shows Overview
        if tab in ("raw", "compare", "instrument_report") and "?tab=" + tab not in [t[0] for t in self.shown_tabs()]:
            return "overview"
        return tab

    def _results_mode(self):
        """Where this worksheet's results come from: the run's own mode when
        its run record carries one, else the method's (a worksheet with no
        run yet reads the method's)."""
        from senaite.pfas import raw_expect
        return self._run_integration_mode() or raw_expect.mode(self._method_profile())

    def shown_tabs(self):
        """The strip's tabs as (address, label, title). The tabs that depend
        on the results mode: Validation lists Integration Review, Instrument
        Report and Comparison; Instrument software lists Instrument Report
        only; LIMS integration lists Integration Review only. Integration
        Review also needs a run that has something to show (raw_tab_shown).
        Every other tab is always listed."""
        mode = self._results_mode()
        tabs = [(u"?tab=overview", u"Overview", u""), (u"?tab=coc", u"Chain of Custody", u""),
                (u"?tab=traceability", u"Traceability", u""),
                (u"?tab=extraction", u"Extraction", u"The guided extraction of this worksheet"),
                (u"?tab=qc_summary", u"Blanks", u""), (u"?tab=calibration", u"Calibration", u""),
                (u"?tab=spike_qc", u"Spike QC", u"LFSM/LFSMD/LFB/LCS recovery + RPD"),
                (u"?tab=final_data", u"Final Data", u"")]
        if mode in (u"vendor", u"validation"):
            tabs.append((u"?tab=instrument_report", u"Instrument Report", u""))
        if mode in (u"validation", u"lims") and self.raw_tab_shown():
            tabs.append((u"?tab=raw", u"Integration Review", u"Each peak this run was integrated, by compound"))
        if mode == u"validation":
            tabs.append((u"?tab=compare", u"Comparison", u"The run imported both ways"))
        return tuple(tabs)

    def context_tree(self):
        """Where this run sits: client > chain of custody >
        batch > this worksheet > its stage, with the samples and QC under it.
        Drawn by the shared tree; nothing here is new data."""
        ws = self._get_worksheet()
        if ws is None:
            return {}
        from bika.lims import api
        from senaite.pfas.core_fields import samples_of
        from senaite.pfas.browser.sample_status import _compute_stage, _build_stage_steps
        out = {"client": None, "coc": [], "batch": None, "worksheet": {"id": ws.getId(), "state": self.ws_state_title(),
                                                                       "url": ws.absolute_url()},
               "stages": [], "samples": [], "qc": 0}
        try:
            stage, who = _compute_stage(ws)
            # the one line of stage names (sample_status.STAGES)
            out["stages"] = _build_stage_steps(stage)
            out["stage_who"] = who
        except Exception as exc:                            # noqa: BLE001
            logger.warning("context_tree stage: %s", exc)
        samples = []
        try:
            samples = list(samples_of(ws))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("context_tree samples: %s", exc)
        for s in samples:
            try:
                out["samples"].append({"id": s.getId(), "csid": s.getClientSampleID() or u"",
                                       "state": api.get_review_status(s), "url": s.absolute_url()})
            except Exception:                                 # noqa: BLE001
                continue
        try:
            first = samples[0] if samples else None
            batch = first.getBatch() if first is not None else None
            if batch is not None:
                out["batch"] = {"id": batch.getId(), "title": batch.Title(), "url": batch.absolute_url(),
                                "state": api.get_review_status(batch)}
            client = (batch.getClient() if batch is not None else None) or (first.getClient() if first is not None else None)
            if client is not None:
                out["client"] = {"title": client.Title(), "url": client.absolute_url()}
        except Exception as exc:                            # noqa: BLE001
            logger.warning("context_tree batch: %s", exc)
        try:
            for r in (self.coc_records_summary(ws) or {}).get("records") or []:
                out["coc"].append({"number": r.get("number"), "status": r.get("status") or u"",
                                   "url": u"%s/@@pfas-coc?number=%s" % (self.portal_url(), r.get("number"))})
        except Exception as exc:                            # noqa: BLE001
            logger.warning("context_tree coc: %s", exc)
        try:
            from senaite.pfas import extraction_batch
            out["qc"] = len([m for m in (extraction_batch.load(ws) or []) if (m.get("role") or u"Sample") != u"Sample"])
        except Exception:                                   # noqa: BLE001
            pass
        return out

    def save_message(self):
        return self.request.form.get("msg", "")

    def save_message_type(self):
        return self.request.form.get("msg_type", "ok")

    _MSG_TEXTS = {
        "item_checked":            u"Checklist item marked.",
        "permission_denied":       u"Permission denied.",
        "no_worksheet":            u"No worksheet found.",
        "invalid_item":            u"Invalid checklist item.",
        "mi_not_ready":            u"Cannot mark the instrument report reviewed: the manual integrations are not complete.",
        "coc_not_received":        u"Cannot mark CoC as reviewed: not every sample's chain of custody has "
                                   u"been received by the laboratory (Chain of Custody, Receive).",
        "coc_holding_time_fail":   u"Cannot mark CoC as reviewed: Holding Times OK is not checked. "
                                    u"Samples received past holding time must be documented before releasing.",
        "coc_holding_time_computed_fail":
                                   u"Cannot mark CoC as reviewed — the recorded dates say "
                                   u"otherwise, regardless of the checkbox.",
        "coc_study_computed":      u"A study run has no chain of custody: this item is computed from the "
                                   u"study's source (reagent water or the reference sample's receipt and CoA).",
        "checklist_incomplete":    u"All checklist items must pass before submitting.",
        "checklist_changed":       u"Not approved: the checklist no longer passes (the QC record changed after submission). Send it back.",
        "automated_proposal_recorded": (
            u"Recorded as an AUTOMATED proposal, not a sign-off. This account is "
            u"a declared service account, so what it found is evidence for the "
            u"reviewer; a person must still authorise the item."),
        "checklist_machine_attested": (
            u"One or more items carry an automated attestation. ISO 17025 "
            u"requires a person to authorise results, so a human must sign "
            u"those items off before submission."),
        "submitted_for_review":    u"Submitted for verification.",
        "workflow_error":          u"Workflow transition failed — check worksheet state.",
        "wrong_state":             u"Worksheet is not in the expected state.",
        "record_closed":           (u"The review record is closed: this worksheet was "
                                    u"submitted or released. A manager's rejection reopens it."),
        "batch_approved":          u"Worksheet verified.",
        "batch_rejected":          u"Worksheet sent back for re-analysis.",
        "run_rejected":            u"Run rejected. Its results go to a new worksheet for the retest.",
        "reject_refused":          u"Not rejected:",
        "report_uploaded":         u"Instrument report uploaded.",
        "spike_saved":             u"Spike level recorded on the extraction log.",
        "request_sent":            u"Request sent to the bench.",
        "request_refused":         u"Request not sent.",
        "above_range_reported":    u"Reason recorded: the result is reported above the calibration range with E.",
        "above_range_refused":     u"Reason not recorded.",
        "no_number_resolved":      u"Reason recorded: the result is reported without the instrument's number.",
        "no_number_refused":       u"Reason not recorded.",
        "lot_reviewed":           u"Lot reviewed.",
        "lot_refused":             u"Lot not reviewed.",
        "run_sent_back":           u"Lot rejected and quarantined. The run is sent back to be rebuilt.",
        "lot_not_found":           u"The lot is not in the inventory.",
        "spike_saved_not_method":  (u"Spike level recorded on this worksheet. The "
                                    u"method's nominal level was not changed "
                                    u"\u2014 that needs a manager."),
        "spike_missing":           u"Enter a spike level.",
        "spike_invalid":           u"Spike level must be a positive number.",
        "no_batch":                u"No worksheet found.",
        "upload_error":            u"File upload failed.",
        "path_error":              u"Download failed — file not found.",
        "initials_required":       u"Your initials are required to sign off / correct — nothing was saved.",
        "run_plan_cleared":        u"Run plan item cleared with your note.",
        "identity_corrected":      u"Identity corrected. The run is being judged again; release waits until it is.",
        "identity_reverted":       u"Correction undone. The run is being judged again; release waits until it is.",
        "identity_refused":        u"Not done:",
        "identity_confirmed":      u"Correction confirmed.",
        "identity_pending_signoff": u"Not signed: the run is not yet judged again.",
        "review_sent_back":        u"Sent back to the analyst. Any run on file is filed again; the cleared sign-offs are made again before it is submitted.",
        "send_back_refused":       u"Not sent back:",
        "extraction_corrected":    u"Extraction record:",
        "extraction_refused":      u"Not done:",
        "extraction_pending_signoff": u"Not signed: an extraction amendment is not yet judged again.",
        "subtraction_blank_changed": u"Subtraction blank changed. Reprocess the run so the results follow it.",
        "subtraction_blank_reason": u"Changing the subtraction blank needs a reason. Nothing was saved.",
        "subtraction_blank_invalid": u"Choose one of the run's method blanks.",
        "calibration_approved":    u"The run's calibration is approved.",
        "calibration_rejected":    u"The run's calibration is rejected: release is held.",
        "calibration_note_required": u"Rejecting the calibration needs a note saying why — nothing was saved.",
        "calibration_not_own":     u"This run has no calibration of its own to approve — nothing was saved.",
        "calibration_held":        u"The calibration is not approved, nothing was saved.",
        "run_plan_note_required":  u"Clearing a run plan item needs a note saying why — nothing was saved.",
        "run_plan_not_cleared":    u"That run plan item was not open — nothing was saved.",
        "reintegrated":            u"Re-integrated and listed under Manual changes; the run is being processed again.",
        "apex_chosen":             u"Apex chosen and listed under Manual changes; the run is being processed again.",
        "peak_deleted":            u"Peak deleted and listed under Manual changes; the run is being processed again.",
        "peaks_fitted":            u"Peaks fitted and listed under Manual changes; the run is being processed again.",
        "edit_reverted":           u"Edit undone; the run is being processed again with the automatic peak.",
        "processing_applied":      u"Applied to all injections and listed under Processing changes; "
                                   u"the run is being processed again.",
        "processing_undone":       u"Processing change undone; the run is being processed again.",
        "processing_proposed":     u"Proposed for the method: it waits on the method's page for a countersign.",
        "proposal_refused":        u"Not proposed:",
        "manual_changes_saved":    u"Manual changes saved.",
        "manual_changes_refused":  u"Manual changes:",
        "manual_changes_open":     u"Give each manual change a reason and your initials before submitting:",
        "raw_countersign_refused": u"Not released:",
        "sign_refused":            u"Not released:",
        "certificate_refused":     u"Not signed:",
        "submit_sign_refused":     u"Not submitted:",
        "issue_email_refused":     u"Not issued:",
        "issue_email":             u"Issue and e-mail:",
        "raw_pull_asked":          u"The raw data is asked for again; the run waits until its folders are settled.",
        "raw_pull_nothing":        u"No failed pull to ask for again.",
        "raw_pull_closed":         u"This worksheet is closed: its run is not imported again. Import it on a new worksheet.",
        "raw_edit_refused":        u"Not changed:",
        "expected_rt_set":         u"Expected retention time set on the method; it applies from the next run.",
        "expected_rt_refused":     u"Expected retention time not set:",
        "raw_edits_waiting":       RAW_WAITING_TEXT,
        "raw_run_failed":          RAW_FAILED_TEXT,
    }

    def save_message_text(self):
        """The banner text, plus any computed detail carried with it.

        A gate that refuses without saying WHY gets worked around, so a refusal
        whose reason is calculated (the holding time is "18 days against a limit
        of 14", not a fixed sentence) passes that sentence through `detail`.
        """
        key = self.request.form.get("msg", "")
        text = self._MSG_TEXTS.get(key, key)
        detail = (self.request.form.get("detail") or "").strip()
        if detail:
            return u"{0} {1}".format(text, detail)
        return text

    # ── Role helpers ──────────────────────────────────────────────────────

    def is_manager(self):
        return _is_manager(self.context)

    def is_analyst(self):
        return _is_analyst(self.context)

    def can_act(self):
        return self.is_analyst() or self.is_manager()

    # ── SQLite helpers ────────────────────────────────────────────────────

    @property
    def db_available(self):
        return os.path.exists(DEFAULT_DB_PATH)

    def _store(self):
        from senaite.pfas.qc.store import QCResultStore
        return QCResultStore(DEFAULT_DB_PATH)

    # ── Multi-page verification ─────────────────────────────────────
    # Each page walks results (from injection_results + qc_results) and checks
    # them against this method's Method-Profile spec. All pages feed the QC
    # Summary gate.

    def _method_profile(self):
        """What this worksheet's batch runs to: the method profile with its
        project's specs applied -- the criteria the pipeline used.
        Resolved once per request (asked hundreds of times a page) and the
        same dict returned to every caller: a reader never changes it, and
        a caller that must change it copies it first."""
        if not hasattr(self, "_method_profile_cache"):
            try:
                from senaite.pfas.project_specs import profile_for_batch
                mid = self.batch_method()
                self._method_profile_cache = profile_for_batch(
                    self._portal(), self._worksheet_batch(), mid,
                    self._batch_matrix()) or {} if mid else {}
            except Exception:
                self._method_profile_cache = {}
        return self._method_profile_cache

    def batch_method_conflicts(self):
        """[(source, method)] that disagree with the batch's method."""
        batch = self._worksheet_batch()
        if batch is None:
            return []
        from senaite.pfas import batch_method as bm
        return bm.resolve(batch, home=self._get_worksheet())[1]

    def _worksheet_batch(self):
        """The batch of this worksheet's samples (the project link lives
        there). Its samples by the catalog, never each analysis woken; once
        per view (the worker's scan of every open worksheet asked twice)."""
        if not hasattr(self, "_worksheet_batch_cache"):
            from senaite.pfas import extraction_batch
            ws, found = self._get_worksheet(), None
            try:
                for sample in extraction_batch.samples_on(ws) if ws is not None else []:
                    found = sample.getBatch()
                    if found is not None:
                        break
            except Exception:                               # noqa: BLE001
                found = None
            self._worksheet_batch_cache = found
        return self._worksheet_batch_cache

    def _injection_rows(self, qc_type=None, role=None):
        """Per-injection detail rows for this worksheet's batch."""
        bid = self.batch_id()
        if not bid or not self.db_available:
            return []
        try:
            return self._store().get_injection_results(
                batch_id=bid, qc_type=qc_type, role=role)
        except Exception as exc:
            logger.warning("_injection_rows: %s", exc)
            return []

    # ── Integration Review (a run imported from raw data) ─────────────────────
    def _raw_connect(self):
        """A connection to the QC store, or None without a batch or store."""
        import sqlite3
        if not self.batch_id() or not self.db_available:
            return None
        return sqlite3.connect(DEFAULT_DB_PATH)

    def _raw_traces(self, injection=None, analytes=None, role=None):
        """This worksheet's raw_traces rows (raw_traces.read), narrowed by the
        filters given. Each distinct filter is read once per request and kept
        under its own key."""
        import sqlite3
        from senaite.pfas import raw_traces
        key = (injection, tuple(analytes) if analytes is not None else None, role)
        cache = self.__dict__.setdefault("_raw_cache", {})
        if key in cache:
            return cache[key]
        cache[key] = []
        try:
            conn = self._raw_connect()
            if conn is None:
                return cache[key]
            try:
                cache[key] = raw_traces.read(conn, self.batch_id(), injection=injection,
                                             analytes=analytes, role=role)
            finally:
                conn.close()
        except sqlite3.Error:
            pass                                            # no raw run stored (no table yet)
        return cache[key]

    def _raw_peaks(self, injection=None, analytes=None, role=None):
        """This worksheet's stored peaks without their signal
        (raw_traces.peaks), narrowed by the filters given: what says whether
        the run shows its edits and changes, which the page polls. Each
        distinct filter is read once per request."""
        import sqlite3
        from senaite.pfas import raw_traces
        key = (injection, tuple(analytes) if analytes is not None else None, role)
        cache = self.__dict__.setdefault("_raw_peaks_cache", {})
        if key in cache:
            return cache[key]
        cache[key] = []
        try:
            conn = self._raw_connect()
            if conn is None:
                return cache[key]
            try:
                cache[key] = raw_traces.peaks(conn, self.batch_id(), injection=injection, analytes=analytes,
                                              role=role)
            finally:
                conn.close()
        except sqlite3.Error:
            pass                                            # no raw run stored (no table yet)
        return cache[key]

    def _raw_trace_index(self, analyte):
        """The analyte's stored traces as {injection, analyte, transition,
        role}, none unpacked (raw_traces.listing); [] with no raw run."""
        import sqlite3
        from senaite.pfas import raw_traces
        try:
            conn = self._raw_connect()
            if conn is None:
                return []
            try:
                return raw_traces.listing(conn, self.batch_id(), [analyte])
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    def raw_available(self):
        import sqlite3
        from senaite.pfas import raw_traces
        try:
            conn = self._raw_connect()
            if conn is None:
                return False
            try:
                return raw_traces.exists(conn, self.batch_id())
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def _upload_path(self, name):
        """A file of that name in the instrument upload folder."""
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        return os.path.join(UPLOAD_DIR, name)

    def _raw_file(self, suffix):
        """The raw run's file of that suffix in the upload folder; "" without
        a raw run."""
        stem = self._raw_stem()
        return self._upload_path(stem + suffix) if stem else u""

    def _raw_stored(self):
        """(traces, injections) the QC store holds of this run (raw_traces.counts),
        (0, 0) with none stored, no table yet among them; None when the store
        is missing or cannot be read (a lock held past sqlite's wait among
        them): the page says so and tries again, never reads it as no run.
        Once per request."""
        if not hasattr(self, "_raw_stored_cache"):
            import sqlite3
            from senaite.pfas import raw_traces
            got = None
            try:
                conn = self._raw_connect() if self.batch_id() else None
                if conn is not None:
                    try:
                        got = raw_traces.counts(conn, self.batch_id())
                    finally:
                        conn.close()
                elif not self.batch_id():
                    got = (0, 0)
            except sqlite3.Error as exc:
                if isinstance(exc, sqlite3.OperationalError) and u"no such table" in (u"%s" % exc):
                    got = (0, 0)
                else:
                    logger.warning("raw run: the QC store cannot be read: %s", exc)
            self._raw_stored_cache = got
        return self._raw_stored_cache

    def raw_state(self):
        """The raw run's state (run_progress.state): a first import, edits
        being processed again, ready, a store that cannot be read, or None.
        Read from the import log and raw_waiting, as the release gate reads
        them. Once per request."""
        if not hasattr(self, "_raw_state_cache"):
            from senaite.pfas import run_progress
            stored, stem = self._raw_stored(), self._raw_stem()
            count = stored[0] if stored is not None else None
            waiting = bool(stem and count) and bool(self.raw_waiting()[0])
            queued = self._raw_queued()
            self._raw_state_cache = run_progress.state(
                stem, count, self._raw_imports() if stem else [], waiting, arrived=self._raw_arrived(),
                queued_at=queued.replace(microsecond=0).isoformat() if queued is not None else None)   # a stored UTC stamp
        return self._raw_state_cache

    def _raw_queued(self):
        """When the raw run was last queued (a naive UTC datetime): the
        latest of its run_progress.QUEUE_FILES written; None with none."""
        from senaite.pfas import run_progress
        paths = [self._raw_file(s) for s in run_progress.QUEUE_FILES]
        stamps = [os.path.getmtime(p) for p in paths if p and os.path.exists(p)]
        return datetime.datetime.utcfromtimestamp(int(max(stamps))) if stamps else None

    def raw_tab_shown(self):
        """Whether the strip lists Integration Review and its pane draws: the
        one place that decides. A run being processed keeps it, even before a
        trace is stored, and a store that cannot be read keeps it to say so
        (run_progress.TAB_STATES)."""
        from senaite.pfas import run_progress
        return self.raw_state() in run_progress.TAB_STATES

    def _raw_injection_count(self):
        """How many injections the raw run holds: its .rawrun record's; 0
        when it cannot be read."""
        return len(self._raw_record().get("injections") or [])

    def _raw_seen(self):
        """[(injections, traces, seconds)] of the raw runs the worker imported
        lately (run_progress.observations): each from when its .rawrun was
        last written or touched to when the import log recorded it done."""
        from senaite.pfas import run_progress
        if not self.db_available:
            return []
        try:
            rows = self._store().raw_runs_done(run_progress.SEEN_RUNS)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("raw run: the runs imported cannot be read: %s", exc)
            return []

        def queued(name):
            path = self._upload_path(name or u"")
            if not name or not os.path.exists(path):
                return None
            return datetime.datetime.utcfromtimestamp(int(os.path.getmtime(path)))
        return run_progress.observations(rows, queued)

    def raw_progress(self):
        """The band while the worker processes the run, or while the store
        cannot be read: {"state", "first", "text", "note", "poll_ms"}. The
        text is "Processing run · Started: HH:MM · Est. completion: HH:MM" on
        the lab's clock (run_progress.band_text), started when the run was
        last queued (the latest of run_progress.QUEUE_FILES), the estimate from its
        size and the throughput seen (run_progress.estimate); or the
        unreadable store's words. None when nothing is processed. Once per
        request."""
        if hasattr(self, "_raw_progress_cache"):
            return self._raw_progress_cache
        from senaite.pfas import lab_time, run_progress
        state, got = self.raw_state(), None
        if state == run_progress.UNREADABLE:
            got = {"state": state, "first": False, "text": run_progress.UNREADABLE_TEXT, "note": u"",
                   "poll_ms": run_progress.POLL_MS}
        elif state in run_progress.PROCESSING:
            started = self._raw_queued()
            stored = self._raw_stored() or (0, 0)
            if stored[0]:
                injections, traces = stored[1], stored[0]
            else:
                injections, traces = self._raw_injection_count(), None
            done = run_progress.estimate(started, lab_time._utcnow(), injections, traces, self._raw_seen())

            def hm(dt):
                return lab_time.show(dt, fmt=u"%H:%M") if dt is not None else None
            got = {"state": state, "first": state == run_progress.FIRST,
                   "text": run_progress.band_text(hm(started), hm(done)), "note": run_progress.UPDATE_TEXT,
                   "poll_ms": run_progress.POLL_MS}
        self._raw_progress_cache = got
        return got

    # the Integration Review tab's overview: every analyte of one injection, or one
    # analyte across every injection
    RAW_MODES = (u"injection", u"compound")
    # what the page says once an edit is made, by its kind
    RAW_EDIT_DONE = {u"integrate": "reintegrated", u"apex": "apex_chosen", u"delete": "peak_deleted",
                     u"revert": "edit_reverted", u"fit": "peaks_fitted"}
    # the edit as posted, carried back on the redirect (posted_<field>) so
    # the card opens on it again after a refusal
    RAW_POSTED = ("transition", "kind", "start", "end", "apex", "baseline", "level_start", "level_end", "shape",
                  "apexes", "pick", "alone")
    # a value longer than any edit's field is not carried: the address stays short
    RAW_POSTED_MAX = 64

    def _raw_library(self):
        """The compound library as the services hold it now (the worker reads
        the same export). Once per request."""
        if not hasattr(self, "_raw_library_cache"):
            from senaite.pfas import compound_library_store
            self._raw_library_cache = compound_library_store.library()
        return self._raw_library_cache

    def _raw_rows(self):
        """The result rows the Integration Review tab shows: the raw side, kept apart
        under Validation, reported under LIMS integration. The worker names
        a row by the compound library's display name and its traces and
        edits by the keyword: each row's analyte is resolved to its keyword
        through the library, its name kept as the label it is shown under
        (raw_review.keyed_rows). Once per request."""
        if not hasattr(self, "_raw_rows_cache"):
            from senaite.pfas import raw_review
            rows = self._sides()[1] or _run_order(self._injection_rows())
            self._raw_rows_cache = raw_review.keyed_rows(
                rows, raw_review.library_keyword_of(self._raw_library()))
        return self._raw_rows_cache

    def _raw_stem(self):
        """The raw run's file stem in the upload folder, "" without one."""
        return (self._run_manifest(self._get_worksheet()).get("raw_expectation") or {}).get("stem") or u""

    def _raw_record(self):
        """The raw run's record (<stem>.rawrun), {} when there is none."""
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        stem = self._raw_stem()
        path = os.path.join(UPLOAD_DIR, stem + u".rawrun")
        if not stem or not os.path.exists(path):
            return {}
        try:
            with open(path) as fh:
                return json.load(fh) or {}
        except (IOError, OSError, ValueError) as exc:
            logger.warning("raw run record %s unread: %s", path, exc)
            return {}

    def _raw_overrides(self):
        """The run's edits, kept beside it (<stem>.overrides.json)."""
        from senaite.pfas import raw_review
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        stem = self._raw_stem()
        return raw_review.read_overrides(os.path.join(UPLOAD_DIR, stem + u".overrides.json")) if stem else {}

    def _raw_imports(self):
        """The import log's entries for the raw run's file, newest first;
        None when the log cannot be read. Once per request."""
        if not hasattr(self, "_raw_imports_cache"):
            stem, got = self._raw_stem(), []
            if stem and self.db_available:
                try:
                    got = [r for r in self._store().import_log(self.batch_id())
                           if r.get("file") == stem + u".rawrun"]
                except Exception as exc:                    # noqa: BLE001
                    logger.warning("raw run: import log unread: %s", exc)
                    got = None
            self._raw_imports_cache = got
        return self._raw_imports_cache

    def _raw_edit_reads(self):
        """(overrides, traces): the run's edits, and the stored peaks that
        show what the last processing made of them, the edited and the
        undone ones, read by injection and analyte, their signal not read
        (_raw_peaks). Once per request."""
        if not hasattr(self, "_raw_edit_reads_cache"):
            from senaite.pfas import raw_edit
            from senaite.pfas.browser import manual_integration_view as miv
            overrides = self._raw_overrides()
            dropped = [r for r in miv.load_state(self._get_worksheet()).get("raw_changes") or []
                       if r.get("dropped")]
            traces = []
            for inj, analytes in sorted(raw_edit.edited_reads(overrides, dropped).items()):
                traces.extend(self._raw_peaks(injection=inj, analytes=analytes))
            self._raw_edit_reads_cache = (overrides, traces)
        return self._raw_edit_reads_cache

    def _raw_no_effect(self):
        """{(injection, analyte, transition): why} of the edits the last
        processing kept but could not apply (raw_review.no_effect): the
        Manual changes panel says so and asks nothing of them."""
        from senaite.pfas import raw_review
        if self._get_worksheet() is None or not self._raw_stem():
            return {}
        return raw_review.no_effect(*self._raw_edit_reads())

    def _raw_processing_path(self):
        """The run's processing changes, kept beside it
        (<stem>.processing.json); "" without a raw run."""
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        stem = self._raw_stem()
        return os.path.join(UPLOAD_DIR, stem + u".processing.json") if stem else u""

    def _raw_processing(self):
        """The run's processing file, the whole dict ({} when there is none);
        ValueError when it cannot be read (raw_review.read_processing)."""
        from senaite.pfas import raw_review
        path = self._raw_processing_path()
        return raw_review.read_processing(path) if path else {}

    def _raw_processing_reads(self):
        """(processing, traces): the run's processing file and the stored
        peaks, of every injection, of each analyte it changes or whose
        last change was undone, which show whether the run has caught up
        with it, their signal not read (_raw_peaks). ValueError when the
        file cannot be read. Once per request."""
        if not hasattr(self, "_raw_processing_reads_cache"):
            from senaite.pfas import raw_review
            from senaite.pfas.browser import manual_integration_view as miv
            proc = self._raw_processing()
            analytes = set(raw_review.parse_processing_key(k)[0] for k in (proc.get("traces") or {}))
            analytes.update(proc.get("smoothing") or {})
            ws = self._get_worksheet()
            if ws is not None:
                analytes.update(r["analyte"] for r in miv.load_state(ws).get("processing_changes") or []
                                if r.get("undone"))
            traces = self._raw_peaks(analytes=sorted(analytes)) if analytes else []
            self._raw_processing_reads_cache = (proc, traces)
        return self._raw_processing_reads_cache

    def processing_misfits(self):
        """[(text, the method page's address)] of the processing changes
        saved on this worksheet's method that their compound can no longer
        take (method_proposals.misfits): the worker processes the compound
        without them; and of a saved fit skipped on every injection while
        the method's fit limit is unset (method_proposals.misfit_lines).
        One line per compound and reason."""
        from bika.lims import api
        from six.moves.urllib.parse import quote
        from senaite.pfas import method_proposals as mp
        from senaite.pfas.method_profile_store import raw_profile
        mid = self.batch_method()
        if not mid:
            return []
        try:
            found = mp.misfit_lines(raw_profile(api.get_portal(), mid))
        except Exception:                                   # noqa: BLE001
            logger.warning("saved processing of %s unread", mid, exc_info=True)
            return []
        from senaite.pfas.site_search import pane_for
        url = u"%s/@@pfas-method-profile-edit?method_id=%s#%s"
        return [(text, url % (self.portal_url(), quote(mid.encode("utf-8"), safe=""), pane_for(section)))
                for text, section in found]

    def _method_processing(self):
        """{keyword: processing entry} of the worksheet's method: the
        processing changes countersigned from a run as the method's own,
        which the worker applies where the run's file holds none."""
        from bika.lims import api
        from senaite.pfas import method_proposals as mp
        from senaite.pfas.method_profile_store import raw_profile
        mid = self.batch_method()
        profile = raw_profile(api.get_portal(), mid) if mid else {}
        rows = (profile.get("integration") or {}).get("analytes") or {}
        # what the worker applies: a change the compound cannot take is left out
        return dict((kw, mp.fitting_entry(profile, kw)) for kw, row in rows.items()
                    if isinstance(row, dict) and row.get("processing"))

    def _method_held(self):
        """{processing key: record} of the method's processing changes this
        run applied (mi.method_held), read from its stored peaks
        (raw_review.method_applied over _raw_method_traces): what the
        worker applied, never the method's entry as it is now, so a removed
        or replaced entry still lists what the run shows, and a run
        processed before the method had a change lists none. Only a raw
        run is processed so; {} without one. Listed under Processing
        changes, and a major one countersigned at release. ValueError when
        the run's processing file or its stored peaks cannot be read
        (_raw_method_traces): the gate refuses. Once per request."""
        if not hasattr(self, "_method_held_cache"):
            from senaite.pfas import raw_review
            held, smoothed, applied = {}, {}, {}
            if self._raw_stem():
                traces = self._raw_method_traces()
                held = raw_review.method_applied(self._raw_processing(), traces)
                smoothed = raw_review.smoothing_applied(traces)
                applied = raw_review.processing_applied(traces)
            self._method_held_cache = held
            self._stored_smoothing_cache = smoothed
            self._stored_processing_cache = applied
        return self._method_held_cache

    def _stored_smoothing(self):
        """{keyword: change} of the run's smoothing changes its stored peaks
        name (raw_review.smoothing_applied), read with _method_held: the
        gate refuses one with no smoothing change in force on record.
        ValueError as _method_held."""
        self._method_held()
        return self._stored_smoothing_cache

    def _stored_processing(self):
        """{processing key: record} of the run's own trace changes its
        stored peaks show (raw_review.processing_applied), read with
        _method_held: the gate refuses one with no change in force on
        record. ValueError as _method_held."""
        self._method_held()
        return self._stored_processing_cache

    # the stored peaks could not be read: the release gate refuses rather
    # than read them as no change from the method
    METHOD_UNREAD = (u"The run's stored peaks cannot be read, so the processing the method applied "
                     u"cannot be listed: %s")
    NO_PEAKS = u"no peak of this run is stored"

    def _raw_method_traces(self):
        """The stored traces whose peak may carry a change from the method
        (raw_traces.method_marked), their signal not read. ValueError
        (METHOD_UNREAD) when they cannot be judged: the run has no batch,
        the QC store is missing or cannot be read (a lock held past sqlite's
        wait among them), or no peak of the run is stored (no table yet, or
        no row of its batch): a raw run's results come from its stored
        peaks, so none stored says nothing of what it applied. _raw_gate and
        the Processing changes line refuse, never pass, on it."""
        import sqlite3
        from senaite.pfas import raw_edit, raw_traces
        unjudged = raw_edit.RawNotJudged
        try:
            conn = self._raw_connect()
        except sqlite3.Error as exc:
            raise unjudged(self.METHOD_UNREAD % exc)
        if conn is None:
            raise unjudged(self.METHOD_UNREAD % (u"the QC store is missing" if self.batch_id()
                                                 else u"the run has no batch to read its peaks under"))
        try:
            if not raw_traces.stored(conn, self.batch_id()):
                raise unjudged(self._no_peaks_text())
            return raw_traces.method_marked(conn, self.batch_id())
        except sqlite3.Error as exc:
            if isinstance(exc, sqlite3.OperationalError) and u"no such table" in (u"%s" % exc):
                raise unjudged(self._no_peaks_text())
            raise unjudged(self.METHOD_UNREAD % exc)
        finally:
            conn.close()

    def _no_peaks_text(self):
        """Why a raw run with no stored peak cannot be judged, by its state
        in the import log and whether its instrument data have arrived
        (raw_edit.unprocessed_text): not arrived yet, still being processed,
        its processing failed (named), or imported with no peak stored."""
        from senaite.pfas import raw_edit
        return (raw_edit.unprocessed_text(self._raw_imports(), self._raw_arrived())
                or self.METHOD_UNREAD % self.NO_PEAKS)

    def _raw_arrived(self):
        """Whether the raw run's instrument data have arrived: the pull
        handed over its .rawrun (until then the run awaits its data, and
        nothing is processed)."""
        path = self._raw_file(u".rawrun")
        return bool(path) and os.path.exists(path)

    def raw_waiting(self):
        """(waiting, edits): whether the raw run's edits and processing
        changes wait for it to be processed again (raw_edit.waiting: when
        <stem>.overrides.json or <stem>.processing.json was last written,
        the run's import log, and whether each edited or undone trace's
        stored peak shows it, and each trace a processing change covers
        shows that change: raw_review.processing_pending), and how many
        traces are edited. An import log or a processing file that cannot
        be read leaves them waiting. Once per request."""
        if hasattr(self, "_raw_waiting_cache"):
            return self._raw_waiting_cache
        from senaite.pfas import raw_edit, raw_review
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        stem = self._raw_stem()
        path = os.path.join(UPLOAD_DIR, stem + u".overrides.json")
        ppath = self._raw_processing_path()
        written = [p for p in (path, ppath) if stem and os.path.exists(p)]
        if not written:
            self._raw_waiting_cache = (False, 0)
            return self._raw_waiting_cache
        # the later of the two files' times
        edited_at = datetime.datetime.utcfromtimestamp(
            max(int(os.path.getmtime(path)) for path in written)).isoformat()   # a stored UTC stamp, whole seconds
        imports = self._raw_imports()
        overrides, traces = self._raw_edit_reads()
        unshown = raw_review.pending(overrides, traces)
        try:
            unshown = unshown + raw_review.processing_pending(*self._raw_processing_reads(),
                                                              method=self._method_processing())
        except ValueError as exc:
            # a processing file that cannot be read is never read as none:
            # the run waits, and the worker refuses it naming why
            logger.warning("raw run: processing changes unread: %s", exc)
            imports = None
        if imports is None:
            self._raw_waiting_cache = (True, len(overrides))
        else:
            self._raw_waiting_cache = raw_edit.waiting(edited_at, imports, overrides, unshown)
        return self._raw_waiting_cache

    def _raw_submit_refusal(self):
        """(message key, detail) why submit and release wait on the raw run
        (raw_edit.submit_refusal: its failed processing, named, or its edits
        waiting), or None."""
        from senaite.pfas import raw_edit
        return raw_edit.submit_refusal(self.raw_waiting()[0], self._raw_imports())

    def _raw_failure(self):
        """The raw run's last processing when it failed, was refused or is
        being tried again (the import log): {"status", "error", "attempts",
        "at"}; None when it imported or nothing is on record."""
        mine = self._raw_imports()
        if not mine or mine[0].get("status") not in (u"failed", u"refused", u"retrying"):
            return None
        return {"status": mine[0]["status"], "error": mine[0].get("error") or u"",
                "attempts": mine[0].get("attempts") or 0, "at": mine[0].get("updated_at") or u""}

    def raw_can_edit(self):
        """Whether this user may edit the run's peaks now: entry rights, and
        the review record still open."""
        return bool(self.can_act()) and self.ws_state() not in self.CLOSED_STATES

    def raw_tab_json(self):
        """The Integration Review tab's data, safe inside a <script>:
        {"mode": "injection" | "compound", "list": the left column (the
        injections, or the analytes), "selected", "thumbs" (raw_review.thumbs),
        "pending" (edits not yet processed, of the traces read), "failure"
        (_raw_failure), "waiting" and "edited" (raw_waiting: whether the
        batch's edits wait for the run to be processed again; how many),
        "processing" (raw_progress: the band while the worker processes the
        run, or the store cannot be read; None once done), "busy" (the
        traces shown whose processing change waits:
        raw_review.processing_pending),
        "cal_dropped" (by compound: the calibrators a deleted peak took
        off the selected analyte's curve, when this worksheet's worker failed
        the curve for them: read from its Calibration QC rows), "can_edit", "card_url"
        (one card: add &injection=&analyte=), "injections"}. Only the traces
        the mode shows are read. A card is not here: raw_data.js fetches the
        one opened (raw_card=1), so the cards of a whole injection never
        ride in the page."""
        from senaite.pfas import raw_review
        f = self.request.form
        mode = f.get("mode") if f.get("mode") in self.RAW_MODES else u"injection"
        results = self._raw_rows()
        # the method's labelled standards decide a compound's section
        from senaite.pfas import labelled_standards
        roles = labelled_standards.roles(self._method_profile())
        record = self._raw_record().get("injections") or []
        injections = raw_review.injections(results, record)
        overrides = self._raw_overrides()
        waiting, edited = self.raw_waiting()
        data = {"mode": mode, "injections": injections, "cal_dropped": [], "failure": self._raw_failure(),
                "waiting": waiting, "edited": edited, "can_edit": self.raw_can_edit(),
                "processing": self.raw_progress(),
                "order_warning": raw_review.clock_order_warning(injections),
                "unit": self.instrument_unit(),
                "edited_in": raw_review.edited_injections(overrides),
                "analytes": [a["name"] for a in raw_review.analytes(results, roles)],
                "sections": [list(pair) for pair in raw_review.SECTIONS],
                "card_url": self.ws_url() + u"/@@pfas-data-review?raw_card=1"}
        if mode == u"injection":
            listed = injections
            chosen = f.get("injection") or u""
        else:
            listed = raw_review.analytes(results, roles)
            chosen = f.get("analyte") or u""
        names = [i["name"] for i in listed]
        chosen = chosen if chosen in names else (names[0] if names else u"")
        traces = []
        if chosen and mode == u"injection":
            traces = self._raw_traces(injection=chosen)
        elif chosen:
            traces = self._raw_traces(analytes=[chosen])
            levels = dict((i.get("name"), i.get("level")) for i in record)
            data["cal_dropped"] = raw_review.cal_dropped(results, chosen, levels, self.calibration_own_rule_rows())
        data.update(list=listed, selected=chosen,
                    thumbs=raw_review.thumbs(mode, chosen, traces, results, overrides, record, roles,
                                             self._rounding_rule(), self._recovery_places()) if chosen else [],
                    pending=raw_review.pending(overrides, traces), busy=self._raw_busy(traces))
        return raw_review.page_json(data)

    def _raw_busy(self, traces):
        """[{injection, analyte, transition}] of `traces` whose stored peak
        does not yet show the run's processing changes
        (raw_review.processing_pending), while the run is processed again;
        [] otherwise, or when its processing file cannot be read."""
        from senaite.pfas import raw_review, run_progress
        if self.raw_state() != run_progress.EDITS or not traces:
            return []
        try:
            proc = self._raw_processing()
        except ValueError:
            return []
        return raw_review.processing_pending(proc, traces, method=self._method_processing())

    def _raw_card_json(self):
        """GET raw_card=1&injection=&analyte=: one analyte of one injection as
        the Integration Review dialog draws it (raw_review.card, an edit not yet
        processed reading as pending), with "injection", "can_edit", the
        compound's "limits" on a manual change, its "rules" for a manual peak
        (raw_edit.review_rules; "rules_problem" when they cannot be read), the
        "method_baseline" its automatic peak was measured on, each waiting
        edit named in the panel's words (raw_review.name_pending), the
        "unit" its concentration is in (instrument_unit: the curve's),
        "is_standard" (an isotope standard, whose deletion the client
        confirms in one step and whose peak is never fitted) and
        "check_labels" (peak_limits.CHECK_LABELS, the words of each score check),
        "smoothing_steps", "smoothing_in_force_points" and "manual_kept" (raw_edit.smoothing_card:
        the Low, Mid and High half-widths, the change in force and the
        hand-integrated peaks it leaves), "standard_all_text" (the words an
        isotope standard's change for all is confirmed with; "" for any other
        compound), "fit_limit", the method's largest fit residual (None while unset:
        no fit is allowed), and "fit_preview", the words and counts the
        card's preview of a fit refuses with (raw_review.fit_preview_words),
        and "reasons", the lab's reasons a one-injection change is given.
        404 with {"error"} when the run holds no such card."""
        from senaite.pfas import raw_edit, raw_preview, raw_review
        from senaite.pfas.browser import manual_integration_view as miv
        f = self.request.form
        inj, an = raw_edit.text(f, "injection"), raw_edit.text(f, "analyte")
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json; charset=utf-8")
        resp.setHeader("Cache-Control", "no-store")
        traces = self._raw_traces(injection=inj) if inj and an else []
        rows = self._raw_rows()
        profile = self._method_profile()
        # the calibrator lots are on the Calibration tab and in the
        # traceability tree, not on the card: the run's manifest is not read
        found = raw_review.card(inj, an, traces, rows, [], self._raw_overrides())
        if found is None:
            resp.setStatus(404)
            return json.dumps({"error": u"%s / %s is not in this worksheet's raw run." % (inj, an)})
        integration = profile.get("integration") or {}
        try:
            change, sn = raw_preview.manual_limits(integration, an)
        except (TypeError, ValueError):
            change, sn = None, None
        quant = [t for t in traces if t["analyte"] == an and t["role"] == u"quant"][0]
        grid = profile.get("labelled_standards")
        rules, rules_problem = raw_edit.review_rules(integration, an)
        found.update(injection=inj, can_edit=self.raw_can_edit(), rules=rules, rules_problem=rules_problem,
                     is_standard=raw_edit.is_standard(rows, inj, an,
                                                      sorted(grid) if isinstance(grid, dict) else ()),
                     limits={"min_manual_change_pct": change, "min_manual_sn": sn},
                     fit_limit=raw_edit.fit_limit(integration),
                     fit_preview=raw_review.fit_preview_words(),
                     method_baseline=raw_edit.method_baseline(quant.get("peak"), integration),
                     unit=self.instrument_unit(),
                     reasons=[{"id": r["id"], "text": r["text"]} for r in miv.get_settings()["reasons"]
                              if r.get("active", True)])
        # the compound's expected time on the method, and the analyst's route
        # to set it from this peak (expected_rt), where a row holds one
        row = (integration.get("analytes") or {}).get(an)
        found["expected_rt"] = row.get("rt") if isinstance(row, dict) else None
        if isinstance(row, dict) and self.raw_can_edit():
            found["set_rt_url"] = self.ws_url() + u"/@@pfas-set-expected-rt"
        found["fit_accept_score"] = raw_edit.fit_accept_score(integration, self._portal())
        # the words of each check the score is made of: one definition, shared with the worker
        from senaite.pfas import peak_limits
        found["check_labels"] = dict(peak_limits.CHECK_LABELS)
        # the method's partner and its peak's edges here: a dragged drop line moves the shared edge of both
        from senaite.pfas import isomers
        found["partner"] = raw_edit.partner_of(integration, an, traces, inj, isomers.partners(profile))
        raw_review.name_pending(found, found["method_baseline"])
        # "Apply to all N injections": the injections holding each trace shown
        # (the preview's denominator), and the method's mode for the compound
        # (a pair or summed compound is not offered it)
        held = self._raw_trace_index(an)
        for shown in [found["quant"]] + list(found.get("quals") or []):
            shown["injection_count"] = raw_edit.apply_all_count(held, an, shown["transition"])
        found["injection_count"] = found["quant"]["injection_count"]
        # a branched isomer peak is summed, as the worker reads it
        found["peak_mode"] = raw_edit.peak_mode(integration, an, isomers.branched_peaks(profile))
        natives = raw_review.natives_of(rows, an, inj)
        found["standard_all_text"] = (raw_edit.IS_ALL_TEXT % (found["label"], ", ".join(natives) or raw_edit.IS_ALL_NATIVES)
                                      if natives or found["is_standard"] else u"")
        # the smoothing stepper: Low, Mid and High from the compound's Mid
        # (its first smoothing change's, else its stored peaks'), the change
        # in force, and the hand-integrated peaks a change leaves alone
        from senaite.pfas import manual_integration as mi
        state = miv.load_state(self._get_worksheet())
        held_now = mi.processing_in_force(state, raw_review.smoothing_key(an))
        found.update(raw_edit.smoothing_card(
            self._raw_traces(analytes=[an]), self._raw_overrides(), an,
            first_mid=mi.smoothing_first_mid(state, an)[1],
            in_force=((held_now or {}).get("after") or {}).get("points")))
        # the ion ratios: each qualifier's line from the run's ION record,
        # whether an edit here moves the expected ratio the samples are judged
        # on, and the method's tolerance the lines are judged by. Both are the
        # reported side's: a raw side kept apart for the comparison has no
        # record of its own and judges nothing
        from senaite.pfas import raw_compare
        from senaite.pfas.provenance_store import ProvenanceStore
        record = None
        reported = not raw_compare.alt_rows(DEFAULT_DB_PATH, self.batch_id(), "raw")
        try:
            if reported:
                record = ProvenanceStore(DEFAULT_DB_PATH).get(self.batch_id(), u"ION|%s|%s" % (inj, found["label"]))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("ion ratio record %s / %s unread: %s", inj, an, exc)
        ions = raw_review.ion_lines(record, found.get("quals"))
        sources = [i.get("source") for i in ions]
        off = raw_review.off_curve(rows, an)
        feeds, samples = raw_review.feeds_expected(rows, inj, an, integration, off, sources)
        # "Apply to all" reaches every calibrator, from whichever card it is made
        feeds_all = raw_review.feeds_expected(rows, None, an, integration, off, sources)[0]
        found.update(ions=ions, ion_warning={"feeds": feeds and reported, "samples": samples},
                     ion_warning_all={"feeds": feeds_all and reported, "samples": samples},
                     ion_tol_pct=raw_review.ion_tolerance(profile))
        # the qualifier detection floor, as the worker reads it: the compound's
        # own, else the method's confirmation S/N, else the smallest S/N
        floor = raw_review.qual_floor(profile, integration, an)
        found["verdicts"] = raw_review.verdicts(found, integration, found["ion_tol_pct"], floor)
        return json.dumps(found, sort_keys=True)

    RAW_NO_RIGHTS = u"You may not edit this run."
    REASON_TEXT = u"Choose a reason from the lab's list."
    COMMENT_TEXT = u"Write a comment on the change."

    def _wants_json(self):
        """Whether the request asks for JSON (Accept holds application/json)."""
        return "application/json" in (self.request.getHeader("Accept") or u"")

    def _raw_reply(self, ok, kind=u"", error=u"", notes=(), back=u"", status=200, tab="raw"):
        """The answer to a raw edit: JSON {"ok", "kind" (the message key),
        "error", "notes", "waiting"} when the request's Accept holds
        application/json, else the redirect to the Integration Review tab (or `tab`)
        with the message (the refusal's text as its detail) and `back`."""
        if self._wants_json():
            resp = self.request.response
            resp.setHeader("Content-Type", "application/json; charset=utf-8")
            resp.setHeader("Cache-Control", "no-store")
            resp.setStatus(status)
            self.__dict__.pop("_raw_waiting_cache", None)
            self.__dict__.pop("_raw_processing_reads_cache", None)
            return json.dumps({"ok": bool(ok), "kind": kind, "error": error, "notes": list(notes or ()),
                               "waiting": bool(self.raw_waiting()[0])}, sort_keys=True)
        if ok:
            return self._redirect_with_msg(kind, "ok", tab=tab, extra=back)
        if kind == "permission_denied":
            return self._redirect_with_msg(kind, "error")
        return self._redirect_with_msg(kind or "raw_edit_refused", "error", tab=tab, detail=error or None,
                                       extra=back)

    def _raw_status_json(self):
        """GET raw_status=1: {"waiting", "edited", "failure", "pending",
        "processing"}: the run's edits waiting for it to be processed again,
        how many traces are edited, its last processing when refused
        (_raw_failure), the edits not yet shown on a trace
        (raw_review.pending), and the band while the worker processes the
        run (raw_progress)."""
        from senaite.pfas import raw_review
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json; charset=utf-8")
        resp.setHeader("Cache-Control", "no-store")
        waiting, edited = self.raw_waiting()
        pending = []
        if self._get_worksheet() is not None and self._raw_stem():
            pending = raw_review.pending(*self._raw_edit_reads())
        return json.dumps({"waiting": bool(waiting), "edited": edited, "failure": self._raw_failure(),
                           "pending": pending, "processing": self.raw_progress()}, sort_keys=True)

    def _raw_tab_reply(self):
        """GET raw_tab=1&mode=&injection=|analyte=: raw_tab_json, so the grid
        refreshes in place; with busy=1, only what says the run is being
        processed (_raw_busy_json)."""
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json; charset=utf-8")
        resp.setHeader("Cache-Control", "no-store")
        if self.request.form.get("busy"):
            return self._raw_busy_json()
        return self.raw_tab_json()

    def _raw_busy_json(self):
        """GET raw_tab=1&busy=1&mode=&injection=|analyte=: {"processing"
        (raw_progress), "pending" (the selection's edits not yet shown,
        raw_review.pending), "busy" (its traces whose processing change
        waits, _raw_busy)}: the band and the dimmed cards, the selection's
        stored peaks read without their signal and no card drawn."""
        from senaite.pfas import raw_review
        f = self.request.form
        mode = f.get("mode") if f.get("mode") in self.RAW_MODES else u"injection"
        chosen = f.get("injection") if mode == u"injection" else f.get("analyte")
        traces = []
        if chosen and self._get_worksheet() is not None and self._raw_stem():
            traces = (self._raw_peaks(injection=chosen) if mode == u"injection"
                      else self._raw_peaks(analytes=[chosen]))
        return json.dumps({"processing": self.raw_progress(),
                           "pending": raw_review.pending(self._raw_overrides(), traces),
                           "busy": self._raw_busy(traces)}, sort_keys=True)

    def _handle_raw_edit(self):
        """An analyst's edit of one raw trace, its quantifier or a qualifier:
        re-integrate (edges, baseline), another apex (and baseline), delete
        the peak, or undo the edit. raw_edit.decide
        refuses, before anything is written, what the trace or the method's
        limits do not allow. Then the edit is kept beside the run and
        replayed whenever it is processed, listed under Manual changes with
        the automatic peak and the edit (its sample type from the side the tab
        shows), and the run is processed again. Every change but an undo
        is posted with a reason_id from the lab's active list and a comment
        (detail), refused without them in that order. The redirect opens the card
        again with the edit as posted (posted_<field>, read after a refusal)
        and the method's notes on the edit made (notes, one per line)."""
        from six.moves.urllib.parse import quote
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import raw_edit, raw_review
        from senaite.pfas.browser import manual_integration_view as miv
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        if not self.can_act():
            return self._raw_reply(False, kind="permission_denied", error=self.RAW_NO_RIGHTS, status=403)
        ws = self._get_worksheet()
        if ws is None:
            return self._raw_reply(False, kind="no_worksheet", error=self._MSG_TEXTS["no_worksheet"], status=404)
        f = self.request.form
        inj, an = raw_edit.text(f, "injection"), raw_edit.text(f, "analyte")
        mode = f.get("mode") if f.get("mode") in self.RAW_MODES else u"injection"
        q = lambda s: quote(s.encode("utf-8"), safe="")
        # back to the same view, its dialog open on the edited card, with the
        # edit as posted: its trace, kind, edges, apex, line and levels
        back = u"&mode=%s&injection=%s&analyte=%s&open=%s" % (mode, q(inj), q(an), q(inj + u"|" + an))
        back += u"".join(u"&posted_%s=%s" % (k, q(raw_edit.text(f, k))) for k in self.RAW_POSTED
                         if 0 < len(raw_edit.text(f, k)) <= self.RAW_POSTED_MAX)
        stem = self._raw_stem()
        rawrun = os.path.join(UPLOAD_DIR, stem + u".rawrun")
        if not stem or not os.path.exists(rawrun):
            return self._raw_reply(False, kind="raw_edit_refused", back=back, status=409,
                                   error=u"This worksheet has no raw run to edit.")
        path = os.path.join(UPLOAD_DIR, stem + u".overrides.json")
        overrides = raw_review.read_overrides(path)
        state = miv.load_state(ws)
        # an undo of one half of a shared edge undoes both: the partner both open records name
        shared = mi.shared_partner(state, inj, an) if raw_edit.text(f, "kind") == u"revert" else None
        partner = raw_edit.text(f, "partner_analyte") or shared
        traces = self._raw_traces(injection=inj, analytes=[an] + ([partner] if partner else [])) if inj and an else []
        profile = self._method_profile()
        grid = profile.get("labelled_standards")
        # an undo retried after its first try removed the edit from the run
        # but its record was not saved: the open record lets it complete
        # a dragged drop line moves the edge two peaks share: both edits are planned before either is
        # written, and written in the one change below (raw_edit.decide_pair)
        from senaite.pfas import isomers
        problem, plans = raw_edit.decide_pair(f, traces, self._raw_rows(), overrides, profile.get("integration") or {},
                                              labelled=sorted(grid) if isinstance(grid, dict) else (),
                                              open_changes=[mi.raw_key(r) for r in mi.raw_open(state)],
                                              partners=isomers.partners(profile), shared_with=shared)
        plan = plans[0] if plans else None
        if problem:
            return self._raw_reply(False, kind="raw_edit_refused", error=problem, back=back, status=422)
        # a change to one injection is given a reason from the lab's active
        # list and a comment; an undo asks for neither
        reason_id, reason, detail = u"", u"", u""
        if plan["kind"] != u"revert":
            active = dict((r["id"], r["text"]) for r in miv.get_settings()["reasons"] if r.get("active", True))
            reason_id = raw_edit.text(f, "reason_id")
            detail = raw_edit.text(f, "detail")
            if reason_id not in active:
                return self._raw_reply(False, kind="raw_edit_refused", error=self.REASON_TEXT, back=back, status=422)
            if not detail:
                return self._raw_reply(False, kind="raw_edit_refused", error=self.COMMENT_TEXT, back=back, status=422)
            reason = active[reason_id]
        who = getSecurityManager().getUser().getId()
        when = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        if all(each.get("gone") for each in plans):
            # every edit is already out of the run: only the records are closed
            for each in plans:
                mi.drop_raw_edit(state, each["injection"], each["analyte"], each["transition"], who, when,
                                 quant_transition=each["quant_transition"])
            miv.save_state(ws, state)
            self._audit(ws)
            return self._raw_reply(True, kind=self.RAW_EDIT_DONE[plan["kind"]], back=back)
        # the write is one edit at a time, on the file as it is now: an edit
        # made meanwhile to another trace is kept (raw_review.update_overrides)
        def change(current):
            if plan["kind"] == u"revert":
                new = current
                for each in plans:          # the peak's undo, then its shared partner's: each its own record
                    if not each.get("gone"):
                        new = raw_review.clear_edit(new, each["injection"], each["analyte"], each["transition"],
                                                    each["quant_transition"])[0]
                    mi.drop_raw_edit(state, each["injection"], each["analyte"], each["transition"], who, when,
                                     quant_transition=each["quant_transition"])
            else:
                new = current
                for each in plans:          # the peak's edit, then its partner's: each its own record
                    new = raw_review.set_edit(new, each["injection"], each["analyte"], each["transition"],
                                              each["quant_transition"], each["edit"], who, when)
                    mi.record_raw_edit(state, each["injection"], each["analyte"], each["transition"], each["kind"],
                                       each["before"], each["after"], who, when, qc_type=each["qc_type"],
                                       quant_transition=each["quant_transition"],
                                       reason_id=reason_id, reason=reason, detail=detail,
                                       shared_with=each.get("shared_with") or u"")
            return new
        try:
            raw_review.update_overrides(path, change)
        except ValueError as exc:
            return self._raw_reply(False, kind="raw_edit_refused", back=back, status=422,
                                   error=exc.args[0] if exc.args else u"")
        miv.save_state(ws, state)
        os.utime(rawrun, None)                   # the worker processes the run again
        self._audit(ws)
        # what the method notes of the edit made, never a refusal: the card
        # shows each as a chip, one per line
        notes = raw_edit.edit_notes(plans)
        if notes:
            back += u"&notes=" + q(u"\n".join(notes))
        return self._raw_reply(True, kind=self.RAW_EDIT_DONE[plan["kind"]], notes=notes, back=back)

    # a change in the run's processing file that no record in force shows
    UNRECORDED_TEXT = (u"The run's processing file holds a change for %s with no record: undo it under "
                       u"Processing changes on the Overview tab.")
    # the file holds another change than the record: it is not undone by its record
    NOT_IN_FILE_TEXT = (u"The run's processing file holds another change for this trace: undo that one "
                        u"under Processing changes on the Overview tab.")

    def _handle_raw_apply_all(self):
        """One trace's change applied to every injection of the run ("Apply
        to all"): raw_edit.plan_all judges it against every injection
        before anything is written, refusing what no injection can take
        and listing those that cannot take it, and why. With preview=1 it
        answers {"ok", "text" (raw_edit.applies_text, then an isotope
        standard's confirm naming its natives), "skipped", "manual_kept",
        "major", "needs_confirm", "natives"} and writes nothing. Otherwise
        the change becomes the trace's processing for the run (its
        processing file, written one change at a time), is listed under
        Processing changes with who, when, before and after, and the run
        is processed again. No reason or comment is asked: it is
        processing, not a manual change. With `smoothing` (a window in
        points) it is the compound's smoothing change instead, every trace
        in every injection (_raw_smoothing_write)."""
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import raw_edit, raw_review
        from senaite.pfas.browser import manual_integration_view as miv
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        if not self.can_act():
            return self._raw_reply(False, kind="permission_denied", error=self.RAW_NO_RIGHTS, status=403)
        ws = self._get_worksheet()
        if ws is None:
            return self._raw_reply(False, kind="no_worksheet", error=self._MSG_TEXTS["no_worksheet"], status=404)
        f = self.request.form
        an = raw_edit.text(f, "analyte")
        stem = self._raw_stem()
        rawrun = os.path.join(UPLOAD_DIR, stem + u".rawrun")
        if not stem or not os.path.exists(rawrun):
            return self._raw_reply(False, kind="raw_edit_refused", status=409,
                                   error=u"This worksheet has no raw run to edit.")
        overrides = self._raw_overrides()
        traces = self._raw_traces(analytes=[an]) if an else []
        profile = self._method_profile()
        grid = profile.get("labelled_standards")
        labelled = sorted(grid) if isinstance(grid, dict) else ()
        integration = profile.get("integration") or {}
        rows = self._raw_rows()
        # a smoothing change steps from the Mid of the compound's first one on record
        first_mid = mi.smoothing_first_mid(miv.load_state(ws), an)[1] if an else None
        # a branched isomer peak is summed, as the worker reads it: no change applies to all of it
        from senaite.pfas import isomers
        branched = isomers.branched_peaks(profile)
        if f.get("preview"):
            # the confirm an isotope standard asks is part of what the card
            # says before Apply, never a refusal of the preview
            problem, plan = raw_edit.plan_all(dict(f, confirm=u"1"), traces, rows, overrides, integration, labelled,
                                              branched=branched, first_mid=first_mid)
            if problem:
                return self._raw_reply(False, kind="raw_edit_refused", error=problem, status=422)
            unconfirmed = raw_edit.plan_all(dict(f, confirm=u""), traces, rows, overrides, integration, labelled,
                                            branched=branched, first_mid=first_mid)[0]
            needs_confirm = bool(unconfirmed)
            text = raw_edit.applies_text(plan)
            if needs_confirm:
                text = text.rstrip(u".") + u". " + unconfirmed
            resp = self.request.response
            resp.setHeader("Content-Type", "application/json; charset=utf-8")
            resp.setHeader("Cache-Control", "no-store")
            return json.dumps({"ok": True, "text": text, "skipped": plan["skipped"],
                               "manual_kept": plan["manual_kept"], "major": plan["major"],
                               "needs_confirm": needs_confirm, "natives": plan["natives"]}, sort_keys=True)
        problem, plan = raw_edit.plan_all(f, traces, rows, overrides, integration, labelled, branched=branched,
                                          first_mid=first_mid)
        if problem:
            return self._raw_reply(False, kind="raw_edit_refused", error=problem, status=422)
        who = getSecurityManager().getUser().getId()
        when = datetime.datetime.utcnow().replace(microsecond=0).isoformat()   # a stored stamp
        if plan["kind"] == raw_review.SMOOTHING_KIND:
            return self._raw_smoothing_write(ws, rawrun, plan, rows, who, when)
        an, tr, qt = plan["analyte"], plan["transition"], plan["quant_transition"]
        key = raw_review.processing_key(an, tr, qt)
        state = miv.load_state(ws)
        # the change before is the one in force on record; the file, read
        # under the lock, must still hold it: a change there with no record
        # is undone under Processing changes first, never recorded as before
        held = mi.processing_in_force(state, key)
        before = held["after"] if held else None
        # with none on the run, the method's own change may have been in
        # force: the list says so, never "automatic" (the file read below
        # must still hold none)
        from senaite.pfas import method_proposals as mp
        by_method = key in ((mp.with_method_processing({}, self._method_processing())[0] or {}).get("traces") or {})
        made = {}

        def change(current):
            entry = ((current or {}).get("traces") or {}).get(key)
            if entry is None and before is not None:
                raise ValueError(mi.PROCESSING_NOT_IN_FILE % key + u".")
            if entry != before:
                raise ValueError(self.UNRECORDED_TEXT % key)
            new = raw_review.set_processing(current, an, tr, qt, plan["record"], who, when)
            made["after"] = new["traces"][key]
            return new
        try:
            raw_review.update_processing(self._raw_processing_path(), change)
        except ValueError as exc:
            return self._raw_reply(False, kind="raw_edit_refused", status=422,
                                   error=exc.args[0] if exc.args else u"")
        mi.record_processing_change(state, an, tr, plan["kind"], before, made["after"], plan["major"],
                                    who, when, skipped=plan["skipped"], before_method=by_method)
        miv.save_state(ws, state)
        os.utime(rawrun, None)                   # the worker processes the run again
        self._audit(ws)
        return self._raw_reply(True, kind="processing_applied")

    def _raw_smoothing_write(self, ws, rawrun, plan, rows, who, when):
        """The compound's smoothing change written to the run's processing
        file (raw_review.with_smoothing), under its lock, and listed under
        Processing changes with before and after, a major change
        countersigned at release; the run is processed again. The file
        must still hold the smoothing change in force on record, or none: one
        there with no record is undone under Processing changes first."""
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import raw_review
        from senaite.pfas.browser import manual_integration_view as miv
        an = plan["analyte"]
        key = raw_review.smoothing_key(an)
        name = mi.processing_key_text(key, lambda kw: raw_review.label_of(rows, kw))
        state = miv.load_state(ws)
        held = mi.processing_in_force(state, key)
        before = held["after"] if held else None
        # Mid is the window the run smoothed over before its first smoothing
        # change of the compound: every later change, after an undo too,
        # keeps the first one's, never the stored peaks', which may show an
        # undone change
        found, first = mi.smoothing_first_mid(state, an)
        mid = first if found else plan.get("mid")
        record = dict(plan["record"], by=who, at=when)
        made = {}

        def change(current):
            entry = ((current or {}).get("smoothing") or {}).get(an)
            if entry is None and before is not None:
                raise ValueError(mi.PROCESSING_NOT_IN_FILE % name + u".")
            if entry != before:
                raise ValueError(self.UNRECORDED_TEXT % name)
            new = raw_review.with_smoothing(current, an, record)
            made["after"] = new["smoothing"][an]
            return new
        try:
            raw_review.update_processing(self._raw_processing_path(), change)
        except ValueError as exc:
            return self._raw_reply(False, kind="raw_edit_refused", status=422,
                                   error=exc.args[0] if exc.args else u"")
        mi.record_processing_change(state, an, None, plan["kind"], before, made["after"], plan["major"], who, when,
                                    mid=mid, label=raw_review.label_of(rows, an))
        miv.save_state(ws, state)
        os.utime(rawrun, None)                   # the worker processes the run again
        self._audit(ws)
        return self._raw_reply(True, kind="processing_applied")

    # the Who of a change the method holds, listed on the run
    METHOD_WHO = u"The method's processing"
    # the Before of a run's change made over the method's own
    METHOD_BEFORE = u"the method's processing"

    # the row menu's line under "Propose for the method"
    PROPOSE_NOTE = u"Waits on the method's page for a countersign"

    def _proposed_traces(self):
        """{mp.waiting_key} of the proposals waiting on this worksheet's
        method: (analyte, transition) of a trace's, apart from a smoothing
        change's; None when the person may not propose (no
        manager) or the method is not known."""
        from senaite.pfas import method_proposals as mp
        from senaite.pfas.browser.perms import require_manager
        mid = self.batch_method()
        if not mid or not require_manager(self.context, self.request):
            return None
        try:
            from bika.lims import api
            return set(mp.waiting_key(p["analyte"], p.get("transition"), p.get("record"))
                       for p in mp.pending(mp.load(api.get_portal()), mid))
        except Exception:                                   # noqa: BLE001
            logger.warning("method proposals unread", exc_info=True)
            return None

    @staticmethod
    def _propose_waiting_text(rec):
        from senaite.pfas import method_proposals as mp
        return mp.ALREADY_WAITING % mp.trace_text(rec["analyte"], rec.get("transition"), rec.get("after"))

    def _client_batch_id(self, ws):
        """The client Batch of the worksheet's samples, else u""."""
        from senaite.pfas.core_fields import samples_of
        try:
            first = next(iter(samples_of(ws)), None)
            batch = first.getBatch() if first is not None else None
            return batch.getId() if batch is not None else u""
        except Exception:                                   # noqa: BLE001
            return u""

    def _handle_propose_processing(self):
        """A manager proposes a processing change in force as the method's
        own setting for its compound and trace: it waits on the method's
        page, the profile unchanged, until a different manager or QA
        officer countersigns it (method_profiles). It changes no review
        record, so a verified run may propose too."""
        from bika.lims import api
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import method_proposals as mp
        from senaite.pfas.browser import manual_integration_view as miv
        from senaite.pfas.browser.perms import require_manager
        from senaite.pfas.method_profile_store import raw_profile
        back = u"#dr-processing-changes"
        if not require_manager(self.context, self.request):
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error")
        rec_id = (self.request.form.get("id") or u"").strip()
        rec = next((r for r in mi.processing_open(miv.load_state(ws)) if r["id"] == rec_id), None)
        if rec is None or not rec.get("after"):
            return self._redirect_with_msg("proposal_refused", "error", detail=self.NOT_IN_FORCE_TEXT, extra=back)
        portal, mid = api.get_portal(), self.batch_method()
        why = mp.applies(raw_profile(portal, mid) if mid else {}, rec["analyte"], rec.get("transition"), rec["after"])
        if why:
            return self._redirect_with_msg("proposal_refused", "error", detail=why, extra=back)
        from Products.CMFPlone.utils import safe_unicode
        # unicode, as the method's page compares it with the person deciding
        who = safe_unicode(getSecurityManager().getUser().getId() or u"")
        when = datetime.datetime.utcnow().replace(microsecond=0).isoformat()   # a stored stamp
        source = {"worksheet": ws.getId(), "batch_id": self._client_batch_id(ws), "change": rec["id"]}
        try:
            data = mp.propose(mp.load(portal), mid, rec["analyte"], rec.get("transition"), rec["after"],
                              source, who, when)
        except ValueError as exc:
            return self._redirect_with_msg("proposal_refused", "error", detail=u"%s" % exc, extra=back)
        mp.save(portal, data)
        logger.info("%s: processing change %s proposed for %s by %s", ws.getId(), rec["id"], mid, who)
        return self._redirect_with_msg("processing_proposed", "ok", extra=back)

    NOT_IN_FORCE_TEXT = u"That processing change is not the one in force."

    def _handle_raw_processing_undo(self):
        """A processing change undone while the worksheet is open (the
        dispatch refuses a closed one): only the change in force for its
        trace, whose before is put back in the processing file (or the
        trace's change removed), and the run is processed again. A change
        in the file with no record (`key`, its processing key, in place of
        `id`) is taken out of the file and the history says so
        (mi.undo_orphan_processing), so the gate can always be cleared from
        here. From the Processing changes list the page comes back to it."""
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import raw_review
        from senaite.pfas.browser import manual_integration_view as miv
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        if not self.can_act():
            return self._raw_reply(False, kind="permission_denied", error=self.RAW_NO_RIGHTS, status=403)
        ws = self._get_worksheet()
        if ws is None:
            return self._raw_reply(False, kind="no_worksheet", error=self._MSG_TEXTS["no_worksheet"], status=404)
        stem = self._raw_stem()
        rawrun = os.path.join(UPLOAD_DIR, stem + u".rawrun")
        if not stem or not os.path.exists(rawrun):
            return self._raw_reply(False, kind="raw_edit_refused", status=409, tab=None,
                                   error=u"This worksheet has no raw run to edit.")
        state = miv.load_state(ws)
        rec_id = (self.request.form.get("id") or u"").strip()
        key = (self.request.form.get("key") or u"").strip()
        if not rec_id and key:
            return self._undo_orphan_processing(ws, state, key, rawrun)
        rec = next((r for r in mi.processing_open(state) if r["id"] == rec_id), None)
        if rec is None:
            return self._raw_reply(False, kind="raw_edit_refused", status=422, tab=None,
                                   error=self.NOT_IN_FORCE_TEXT)
        who = getSecurityManager().getUser().getId()
        when = datetime.datetime.utcnow().replace(microsecond=0).isoformat()   # a stored stamp
        an, tr, before = rec["analyte"], rec.get("transition"), rec.get("before")
        key = raw_review.processing_key(an, tr, None)
        smoothing = rec.get("kind") == mi.SMOOTHING

        # the file, read under the lock, holds the change on record, or none
        # (a record claiming a change the run does not apply): another
        # change there is undone by its key
        def change(current):
            entry = mi.processing_entry(current, mi.processing_rec_key(rec))
            if entry is not None and entry != rec.get("after"):
                raise ValueError(self.NOT_IN_FILE_TEXT)
            if smoothing:
                # the compound's smoothing before it, or none
                if before:
                    return raw_review.with_smoothing(current, an, before)
                if entry is not None:
                    return raw_review.without_smoothing(current, an)
                return current or raw_review.processing_dict({})
            if before:
                return raw_review.set_processing(current, an, tr, None, before, before.get("by") or who,
                                                 before.get("at") or when)
            if entry is not None:
                return raw_review.clear_processing(current, an, tr, None)
            return current or raw_review.processing_dict({})
        try:
            raw_review.update_processing(self._raw_processing_path(), change)
        except ValueError as exc:
            return self._raw_reply(False, kind="raw_edit_refused", status=422, tab=None,
                                   error=exc.args[0] if exc.args else u"")
        mi.undo_processing_change(state, rec_id, who, when)
        miv.save_state(ws, state)
        os.utime(rawrun, None)                   # the worker processes the run again
        self._audit(ws)
        return self._raw_reply(True, kind="processing_undone", tab=None)

    def _undo_orphan_processing(self, ws, state, key, rawrun):
        """A change in the run's processing file that no record in force
        shows (mi.processing_orphans) taken out of the file, under its lock,
        read as it is then, and the trace's change in force on record put
        back in its place; it stays listed, not recorded and undone, and
        its history row names who, when and both."""
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import raw_review
        from senaite.pfas.browser import manual_integration_view as miv
        who = getSecurityManager().getUser().getId()
        when = datetime.datetime.utcnow().replace(microsecond=0).isoformat()   # a stored stamp
        removed = {}

        held = mi.processing_in_force(state, key)
        restored = held["after"] if held else None

        def change(current):
            if key not in mi.processing_orphans(state, current):
                raise ValueError(u"That processing change is not an unrecorded one in the run's file.")
            traces = dict(current.get("traces") or {})
            smoothing = dict(current.get("smoothing") or {})
            # a compound's smoothing by its smoothing key, else a trace's
            analyte = raw_review.parse_smoothing_key(key)
            section, name = (smoothing, analyte) if analyte is not None else (traces, key)
            removed["record"] = section.pop(name)
            if restored is not None:
                section[name] = restored
            return raw_review.processing_dict(traces, smoothing)
        try:
            raw_review.update_processing(self._raw_processing_path(), change)
        except ValueError as exc:
            return self._raw_reply(False, kind="raw_edit_refused", status=422, tab=None,
                                   error=exc.args[0] if exc.args else u"")
        mi.undo_orphan_processing(state, key, who, when, removed["record"], restored)
        miv.save_state(ws, state)
        os.utime(rawrun, None)                   # the worker processes the run again
        self._audit(ws)
        return self._raw_reply(True, kind="processing_undone", tab=None)

    # ── Validation: the run imported both ways, compared ────────────
    def _sides(self):
        """(vendor rows, raw rows): the reported side from injection_results,
        the other from the rows kept apart (raw_compare.alt_rows)."""
        from senaite.pfas import raw_compare
        bid = self.batch_id()
        if not bid or not self.db_available:
            return [], []
        raw = raw_compare.alt_rows(DEFAULT_DB_PATH, bid, "raw")
        if raw:
            return _run_order(self._injection_rows()), _run_order(raw)
        vendor = raw_compare.alt_rows(DEFAULT_DB_PATH, bid, "vendor")
        return (_run_order(vendor), _run_order(self._injection_rows())) if vendor else ([], [])

    def comparison_available(self):
        return bool(self._sides()[1])

    def comparison_empty(self):
        """Why the Comparison tab has nothing, as the run stands: "no_run"
        (no run imported yet), "not_integrated" (a Validation run whose raw
        data were not integrated), "no_export" (a LIMS-integrated run whose
        instrument export was not imported), else "vendor" (the method
        reports the instrument software's results). The mode is the run's
        own when its run record carries one, else the method's."""
        if not self.has_run():
            return u"no_run"
        mode = self._results_mode()
        return {u"validation": u"not_integrated", u"lims": u"no_export"}.get(mode, u"vendor")

    def comparison(self):
        """{"lines", "summary"}: every peak's two areas, retention times,
        concentrations and verdicts, names matched on their keyword."""
        if hasattr(self, "_comparison"):
            return self._comparison
        from senaite.pfas import compound_library, raw_compare
        from senaite.pfas.compound_library_store import library
        from bika.lims import api
        try:
            n2k = compound_library.name_to_keyword(library(api.get_portal()))
        except Exception:                                   # noqa: BLE001
            n2k = {}
        vendor, raw = self._sides()
        lines = raw_compare.compare(vendor, raw, key=lambda name: n2k.get(name, name))
        self._comparison = {"lines": lines, "summary": raw_compare.summary(lines)}
        return self._comparison

    def comparison_headings(self):
        """The table's headings, the validation record's (raw_compare.COLUMNS)
        but its last: a disagreement is marked on the raw verdict."""
        from senaite.pfas import raw_compare
        return [label for _k, label in raw_compare.COLUMNS[:-1]]

    def _comparison_csv(self):
        """The comparison as the validation record (CSV)."""
        from senaite.pfas import raw_compare
        ws = self._get_worksheet()
        bid = self.batch_id()
        method = (self._run_manifest(ws).get("method_id") if ws is not None else u"") or u""
        text = raw_compare.to_csv(self.comparison()["lines"], run=bid, method=method)
        resp = self.request.response
        resp.setHeader("Content-Type", "text/csv; charset=utf-8")
        resp.setHeader("Content-Disposition", 'attachment; filename="comparison_{0}.csv"'.format(
            re.sub(r"[^A-Za-z0-9_-]", "_", bid or "run")))
        return text.encode("utf-8")

    def raw_run_status(self):
        """The raw run this worksheet's run expects: waiting (naming what
        for), failed (why) or pulled; {} when the run expects none."""
        from senaite.pfas import raw_review
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        raw = self._run_manifest(self._get_worksheet()).get("raw_expectation") or {}
        stem = raw.get("stem")
        if not stem and not raw.get("error"):
            return {}
        return raw_review.run_status(os.path.join(UPLOAD_DIR, stem or u"none"), expect_error=raw.get("error"))

    def _handle_raw_pull_again(self):
        """A failed raw pull asked for again (its failure removed; the
        worker's pull then waits for the folders afresh)."""
        from senaite.pfas import raw_review
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        # verified, published or rejected: the worker refuses the run too
        if self.ws_state() in self.VERIFIED_STATES or self.ws_state() == "rejected":
            return self._redirect_with_msg("raw_pull_closed", "error", tab="instrument_report")
        stem = (self._run_manifest(self._get_worksheet()).get("raw_expectation") or {}).get("stem")
        if not stem or not raw_review.pull_again(os.path.join(UPLOAD_DIR, stem)):
            return self._redirect_with_msg("raw_pull_nothing", "error", tab="instrument_report")
        try:
            import sqlite3
            conn = sqlite3.connect(DEFAULT_DB_PATH)
            try:                                 # off the bell while it is tried again
                conn.execute("UPDATE run_imports SET status='retrying' WHERE file=?", (stem + ".rawrun",))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("raw pull again: import log not updated: %s", exc)
        self._audit(self._get_worksheet())
        return self._redirect_with_msg("raw_pull_asked", "ok", tab="instrument_report")

    def raw_run_files(self):
        """The raw files, checksums and conversion of this worksheet's raw run
        (its .rawrun record), or None."""
        from senaite.pfas import raw_review
        from senaite.pfas.browser.run_builder import UPLOAD_DIR
        stem = (self._run_manifest(self._get_worksheet()).get("raw_expectation") or {}).get("stem")
        path = os.path.join(UPLOAD_DIR, (stem or u"") + ".rawrun")
        if not stem or not os.path.exists(path):
            return None
        with open(path) as fh:
            return raw_review.run_files(json.load(fh))

    def sample_results_page(self):
        """Page 1 — field-sample results per analyte, with per-injection RT /
        ion-ratio and the QC flags that became qualifiers. Grouped by sample."""
        rows = self._injection_rows(qc_type="Sample", role="analyte")
        by_sample = {}
        for r in rows:
            sid = r.get("sample_id") or r.get("injection_name") or "?"
            inj = r.get("injection_name") or u""
            an = r.get("analyte", "") or u""
            by_sample.setdefault(sid, []).append({
                "analyte": an,
                "injection_name": inj,
                # the provenance records behind each cell (the drawer); RT
                # and ion-ratio keys carry the acquisition time the row
                # does not, so the store matches them on the injection
                "prov": {"result": u"RESULT|%s|%s" % (inj, an), "rt": u"RT|%s|%s" % (inj, an),
                         "ion": u"ION|%s|%s" % (inj, an)},
                "result": r.get("calc_conc"),
                # The instrument's own verdict when there is no number. Without
                # it "below quantitation" and "not detected" look identical.
                "conc_qualifier": r.get("conc_qualifier") or "",
                "rt": r.get("rt"),
                "ion_ratio": r.get("ion_ratio_obs"),
                "flag": r.get("flag") or "",
                "passed": bool(r.get("passed", 1)),
            })
        out = []
        for sid in sorted(by_sample):
            analytes = sorted(by_sample[sid], key=lambda a: a["analyte"])
            out.append({
                "sample_id": sid,
                "analytes": analytes,
                "n_flagged": sum(0 if a["passed"] else 1 for a in analytes),
            })
        return out

    def spike_qc_page(self):
        """Page 2 — LFSM/LFSMD/LFB/LCS recoveries and RPDs per analyte, drawn
        with the QC Summary's cells: each value coloured by its stored
        verdict, the window it was judged by cited under the table."""
        # Every exit from this method MUST carry the same keys. The template
        # dereferences page/pending_spikes and page['specs'] unconditionally, so
        # an early return that omitted them raised LocationError and 500'd the
        # WHOLE Data Review page — not just this pane. It fired for any
        # worksheet with no QC record in the store ("no_batch_record"), which
        # is exactly the to_be_verified and verified worksheets this page exists
        # to review. Found by loading the page against a real worksheet in each
        # state rather than only the one that happened to have QC rows.
        empty = {"rows": [], "types": [], "specs": {}, "pending_spikes": [], "groups": [], "factor": None}
        if not self.db_available:
            return empty
        ws = self._get_worksheet()
        if ws is None:
            return empty
        summary = self._get_qc_summary(ws)          # reuse the matrix builder
        if summary.get("error"):
            out = dict(empty)
            out["error"] = summary.get("error")
            return out
        # the QC Summary's own cells (qc_cells), for the spike / recovery QC
        # types only, their criteria numbered for this page
        from senaite.pfas import qc_cells
        spike_types = [t for t in summary.get("qc_types", []) if qc_cells.is_spike(t)]
        shown = qc_cells.tables(summary.get("columns") or [], summary.get("rows") or [],
                                keep=qc_cells.is_spike)
        prof = self._method_profile()
        qca = prof.get("qc_acceptance", {}) or {}
        from senaite.pfas.qc.qc_types import enabled_qc_types
        required = set(enabled_qc_types(prof))
        # every required spike has its column, judged or not
        wanted = [t for t in qc_cells.SPIKE if t in required]
        for t in wanted:
            if t not in spike_types:
                spike_types.append(t)
        spike_types.sort(key=qc_cells.column_order)
        # whether each is required every run (its windows are the cited notes)
        specs = dict((t, {"required": t in required,
                          "enabled": bool((qca.get(t) or {}).get("enabled", True))})
                     for t in spike_types)
        # why a required spike's cells are empty: the run's own flag, and a
        # matrix factor the method lacks for a spike judged per sample
        why = {}
        for f in summary.get("run_flags") or []:
            if f.get("flags"):
                why.setdefault(f["qc_type"], u"; ".join(f["flags"]))
        mf = self.missing_matrix_factor()
        said = u""
        if mf:
            said = self._no_factor_text(mf)
            said = said[:1].upper() + said[1:] + u"."
            for t in self._SAMPLE_BASIS_SPIKES:
                why[t] = said
        groups = qc_cells.with_equations(qc_cells.with_required(
            shown["groups"], wanted, summary.get("qc_types") or [],
            [r.get("analyte") for r in summary.get("rows") or [] if r.get("analyte")], why))
        # per analyte and type, the verdict cells (the QC Review report's table)
        rows = [{"analyte": row.get("analyte", ""),
                 "cells": dict((t, (row.get("cells") or {}).get(t)) for t in spike_types)}
                for row in summary.get("rows", [])]
        fix = None
        if mf and [t for t in self._SAMPLE_BASIS_SPIKES if t in wanted]:
            fix = {"text": said, "label": u"Matrices", "url": mf["url"]}
        return {"rows": rows, "groups": groups, "types": spike_types,
                "specs": specs, "pending_spikes": self.pending_spike_levels(), "factor": fix}

    def pending_spike_levels(self):
        """Spiked injections whose spike level nobody has recorded.

        Without a level the recovery cannot be computed, and it used to be
        skipped in silence — a batch could reach release with its matrix spike
        never evaluated. Rather than blocking, the reviewer is asked for the
        value: these rows drive that prompt.
        """
        ws = self._get_worksheet()
        batch = self._extraction_home(ws) if ws else None
        if batch is None:
            return []
        from senaite.pfas.dilution_ref import get_spikes
        spikes = get_spikes(batch)
        profile = self._method_profile() or {}
        matrix = self._batch_matrix()
        levels = ((profile.get("spike_levels") or {}).get(matrix) or {})

        # Spiked injections the RUN contains but the extraction pedigree does
        # not. Driving the prompt from the pedigree alone meant that when
        # the extraction record was never filled in, `spikes` was empty, the loop yielded
        # nothing, and the reviewer was offered no way to supply a level — while
        # the QC gate blocked on "required QC not evaluated: LFSM, LFSMD". A
        # gate with no exit is worse than no gate: it cannot be satisfied and it
        # cannot be understood.
        #
        # The run is the evidence of what was injected; the pedigree is the
        # record of what was intended. Where they disagree, ask about what was
        # actually run.
        for qc_type in ("LFSM", "LFSMD"):
            for row in (self._injection_rows(qc_type=qc_type) or []):
                name = row.get("injection_name")
                if name and name not in spikes:
                    spikes[name] = {"parent": "", "level": "",
                                    "spike": None, "from_run": True}

        out = []
        from senaite.pfas.calibration_levels import PPT_PER_UNIT, level_value, matrix_unit
        unit = matrix_unit(profile, matrix)

        def _same_scale(a, b):
            fa, fb = PPT_PER_UNIT.get((a or u"").lower()), PPT_PER_UNIT.get((b or u"").lower())
            return not a or not b or (fa is not None and fa == fb)

        for injection, entry in sorted(spikes.items()):
            if entry.get("spike") and _same_scale(entry.get("spike_unit"), unit):
                continue
            wrong_unit = bool(entry.get("spike")) and not _same_scale(entry.get("spike_unit"), unit)
            if entry.get("lfsm"):
                # a recorded LFSMD takes its LFSM's amount: never asked twice
                continue
            label = entry.get("level") or ""
            nominal = None
            for lv in (levels.get("LFSM") or []):
                if not label or lv.get("label") == label:
                    nominal = level_value(lv, unit)
                    if lv.get("label") == label:
                        break
            if nominal and not wrong_unit:
                continue
            out.append({"injection": injection,
                        # an amount recorded in another scale (e.g. ppt for
                        # a matrix reporting ng/g): asked again, in the unit
                        "recorded_in": entry.get("spike_unit") if wrong_unit else u"",
                        "parent": entry.get("parent", ""),
                        "level": label,
                        "matrix": matrix, "unit": unit,
                        # True when the pedigree does not know this injection at
                        # all, so the prompt can say "not in the extraction record" rather
                        # than "level missing".
                        "unrecorded": bool(entry.get("from_run"))})
        return out

    def _certificate_format(self, sample_type):
        """The settings the certificate prints a sample of `sample_type` with
        (report_templates.certificate_format): Final Data, the release checks
        and the certificate round alike."""
        from senaite.pfas.print_settings import get_print_settings
        from senaite.pfas.report_limits import canonical_matrix
        from senaite.pfas.report_templates import certificate_format, issued_snapshot
        if not hasattr(self, "_cert_inputs"):
            try:
                snap = issued_snapshot(self._portal())[0]
            except Exception:                               # noqa: BLE001
                snap = None
            self._cert_inputs = (snap, self._method_profile() or {}, get_print_settings(self._portal()))
        snap, profile, live = self._cert_inputs
        method_id = profile.get("method_id") or self.batch_method()
        return certificate_format(snap, method_id, profile, canonical_matrix(profile, sample_type), live)[0]

    def _rounding_rule(self):
        """The rounding rule this worksheet's results are judged and printed
        with: the certificate's for the batch's matrix."""
        if not hasattr(self, "_rule_cache"):
            from senaite.pfas import rounding
            self._rule_cache = (self._certificate_format(self._batch_matrix()).get("coa_rounding")
                                or rounding.DEFAULT_RULE)
        return self._rule_cache

    def _batch_matrix(self):
        """The batch's matrix, from its samples' SampleType."""
        ws = self._get_worksheet()
        if ws is None:
            return u""
        try:
            for analysis in (ws.getAnalyses() or []):
                st = analysis.getRequest().getSampleType()
                if st:
                    return st.Title() or u""
        except Exception:
            pass
        # a study run holds no sample: its matrix is the study's
        return (self.study_run() or {}).get("matrix") or u""

    # ── Checklist data model ──────────────────────────────────────────────

    def _default_checklist(self, ws):
        items = {}
        for key, label, auto in _CHECKLIST_ITEMS:
            items[key] = {
                "label":      label,
                "auto":       auto,
                "checked":    False,
                "checked_by": None,
                "checked_at": None,
                "notes":      u"",
                # "human" | "automated" -- who ATTESTED, in kind rather than by
                # name. None until attested.
                "checked_by_kind": None,
                # An automated actor's PROPOSED disposition. Deliberately
                # separate from `notes`, which a human owns: a proposal must
                # survive the human acting on it, or the record cannot show that
                # a machine looked first.
                "proposed_by":    None,
                "proposed_at":    None,
                "proposed_notes": u"",
            }
        return {
            "version":   1,
            "batch_id":  ws.getId() if ws else u"",
            "items":     items,
            "submitted_by": None, "submitted_at": None,
            "approved_by":  None, "approved_at":  None,
            "instrument_report_file": None,
            "instrument_report_uploaded_at": None,
        }

    def _get_checklist(self, ws):
        try:
            raw = IAnnotations(ws).get(CHECKLIST_KEY)
            if raw:
                data = json.loads(raw)
                # Back-fill any missing items (schema additions)
                items = data.setdefault("items", {})
                for key, label, auto in _CHECKLIST_ITEMS:
                    if key not in items:
                        items[key] = {
                            "label": label, "auto": auto, "checked": False,
                            "checked_by": None, "checked_at": None, "notes": u"",
                            "checked_by_kind": None, "proposed_by": None,
                            "proposed_at": None, "proposed_notes": u"",
                        }
                return data
        except Exception as exc:
            logger.error("_get_checklist: %s", exc)
        return self._default_checklist(ws)

    def _save_checklist(self, ws, data):
        self._checklist_cache = None      # recomputed on the next read
        # what a write in this request may change is read afresh after it
        self._qc_summary_memo = None
        self._analyses_index = None
        self._sample_inputs = None
        self._pushes_memo = None
        self.__dict__.pop("_accred_disclosure", None)
        IAnnotations(ws)[CHECKLIST_KEY] = json.dumps(data)

    def _audit(self, ws):
        """The review act on the worksheet's own trail: who, when, the action
        posted and its reason (records.log). The act's content is in its own
        record (sign-offs, corrections, the review log)."""
        from senaite.pfas import records
        form = self.request.form
        records.log(ws, form.get("action") or u"review",
                    reason=(form.get("reason") or form.get("note") or u"").strip())

    # ── Auto-check computation ────────────────────────────────────────────

    # ── Expiry, judged as of the date the lot was USED ───────────────────────

    def _use_date(self, lb, *fields):
        """The date a logbook says its lots were used, or "" if it does not say.

        There is no single "use date" for a worksheet, and choosing one would be
        wrong: on the real released WS-0005 the processing stage's date is
        2025-10-17 and the extraction record's date is 2026-08-03 -- ten months
        apart. Each logbook carries the date ITS OWN rows were used, so each set
        of lots is judged against its own date. A worksheet-wide date would
        condemn one set or excuse the other.
        """
        for f in fields:
            v = (lb.get(f) or u"").strip()
            if v:
                return v[:10]
        return u""

    @staticmethod
    def _names_lots(lb):
        """True when a logbook names something its date is needed for: an
        active row holding a lot number, or a balance serial. A logbook that
        holds none (the processing record the guided extraction replaced,
        never written now) has nothing to check, so no date is missing."""
        if (lb.get("balance_sn") or u"").strip():
            return True
        return any((row.get("lot") or u"").strip()
                   for rows in lb.values() if isinstance(rows, list)
                   for row in active_rows(rows))

    def review_flags(self):
        """Why this run is flagged for review (a corrected certificate behind a
        lot it used; certificate_values.add_flag)."""
        from senaite.pfas import certificate_values as cv
        ws = self._get_worksheet()
        return cv.flags_of(ws) if ws is not None else []

    def trace_rows(self, t):
        """The Traceability table: every reagent, consumable and standard the
        extraction log names, one row each -- what it is, its lot, its
        supplier ("Prepared in-house" for a prepared standard), its expiry and
        its certificate (a reagent's CoA, a prepared standard's preparation
        certificate). One supplier per row: the inventory's, else the log's."""
        from senaite.pfas.browser.reagents import _effective_expiry
        from senaite.pfas.browser import prepared_standards as _ps
        from senaite.pfas.lot_links import lot_menu
        portal = self._portal()
        purl = self.portal_url()
        reagent_by_lot, ps_by_lot = self._build_lot_indices(portal)
        rows = []
        for e in list(t.get("direct_reagents") or []) + list(t.get("direct_standards") or []):
            res, lot = e.get("resolved") or {}, (e.get("lot") or u"").strip()
            row = {"name": e.get("name") or res.get("title") or u"", "lot": lot,
                   "supplier": u"", "expiry": u"", "cert_url": u"", "cert": u"",
                   "found": bool(res), "kind": u""}
            try:
                if res.get("type") == "PreparedStandard" and lot in ps_by_lot:
                    obj = ps_by_lot[lot]
                    rec = _ps._obj_to_dict(obj) or {}
                    row["supplier"] = u"Prepared in-house"
                    row["expiry"] = _ps.effective_expiry_info(portal, rec).get("date") or u""
                    row["cert_url"] = u"%s/@@pfas-prep-standards?action=cert&uid=%s" % (purl, obj.getId())
                    row["cert"] = u"Preparation certificate"
                    row["kind"] = u"prepared"
                elif res and lot in reagent_by_lot:
                    obj = reagent_by_lot[lot]
                    rec = self._reagent_record(obj)
                    row["supplier"] = res.get("supplier") or e.get("supplier") or u""
                    row["expiry"] = _effective_expiry(rec) or u""
                    if res.get("has_coa"):
                        row["cert_url"] = u"%s/@@pfas-reagents?action=coa&uid=%s" % (purl, obj.UID())
                        row["cert"] = u"Supplier's CoA"
                    row["kind"] = u"purchased"
                else:
                    row["supplier"] = e.get("supplier") or u""
            except Exception as exc:                        # noqa: BLE001
                logger.warning("trace_rows %s: %s", lot, exc)
            # the row's + menu: the lot, and its certificate when on file
            row["menu"] = lot_menu(row["kind"], lot, purl, row["cert_url"])
            rows.append(row)
        return rows

    def _reagent_record(self, obj):
        """The FULL reagent record, for deciding expiry.

        `_reagent_dict` is the DISPLAY projection -- title, url, supplier,
        cat_number, lot_number, has_coa -- and carries no expiry of any kind, so
        handing it to the expiry resolver produced a check that could never fire.
        """
        if obj is None:
            return {}
        try:
            from senaite.pfas.browser.reagents import _obj_to_dict as _rd
            return _rd(obj)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("reagent record for expiry decision: %s", exc)
            return {}

    def _expired_at_use(self, resolved, lot, name, use_date, portal=None):
        """A reason string when this lot was already expired on `use_date`, else None.

        Decided in item 7 and never implemented: judging a
        lot against TODAY makes a released batch LESS defensible as time passes.
        Every standard on this instance is expired now, yet the runs that used them
        were in date at the time -- so blocking on today's date would retroactively
        condemn correct work, which is the opposite of what the gate is for.

        Returns None when the use date is unknown: an unrecorded date is not
        evidence of expiry. That is reported as a warning rather than enforced, the
        same posture the equipment walk takes for an unregistered serial -- only an
        ESTABLISHED unmet obligation blocks release.

        Returns None too when a reason was recorded for that use: at the bench
        the stage's deviation note is the reason (`self._use_reasons`, set by
        _build_traceability_tree from lot_expiry.stage_reasons).
        """
        if not resolved or not use_date:
            return None
        if (self._use_reasons or {}).get(lot):
            return None
        try:
            if resolved.get("type") == "PreparedStandard":
                # A prep inherits its parents' tighter expiry, so the effective
                # date is the one to judge -- not the date typed on the lot.
                from senaite.pfas.browser.prepared_standards import (
                    _get as _ps_get, effective_expiry_info)
                uid = resolved.get("uid") or u""
                d = _ps_get(portal, uid) if (portal and uid) else None
                # the date in force on the day of use: an extension QA
                # approved later does not reach back (lot_extension)
                exp = ((effective_expiry_info(portal, d, as_of=use_date) or {}).get("date")
                       if d else resolved.get("expiry_date")) or u""
                from senaite.pfas.lot_expiry import expired_on
                if expired_on(exp, use_date):
                    return (u"prepared standard lot %s expired %s, before it was "
                            u"used on %s" % (lot or name, exp, use_date))
                return None
            # A manufacturer lot: _is_expired owns the expiry_date ->
            # manufacturer_expiry -> global-default resolution, so it is asked
            # rather than reimplemented here.
            from senaite.pfas.browser.reagents import (
                _is_expired, _effective_expiry)
            from datetime import datetime
            ref = datetime.strptime(use_date, "%Y-%m-%d").date()
            if _is_expired(resolved, as_of=ref):
                return (u"lot %s expired %s, before it was used on %s"
                        % (lot or name, _effective_expiry(resolved, as_of=use_date) or u"?",
                           use_date))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("expiry-at-use for %s: %s", lot, exc)
        return None

    def _compute_traceability_status(self, ws):
        try:
            tree = self._build_traceability_tree(ws)
            # "Has data" means at least one row that actually NAMES A LOT.
            # Counting bare list lengths let one 252 row carrying
            # a name and an empty lot satisfy the gate with ZERO lots resolved,
            # because the entry is appended outside the `if lot:` branch so it
            # could neither resolve nor be reported unresolved.
            def _with_lots(key):
                return [e for e in tree.get(key, []) if (e.get("lot") or "").strip()]

            has_data = bool(_with_lots("direct_reagents")
                            or _with_lots("direct_standards")
                            or _with_lots("prepared_standards"))
            # and the extraction itself finished: the
            # calibration-prep lots alone passed with the extraction record never done
            return (has_data and len(tree.get("unresolved", [])) == 0
                    and self._extraction_finalized())
        except Exception as exc:
            logger.error("_compute_traceability_status: %s", exc)
            return False

    # ── Qualified release ────────────────────────────────────────────────────
    #
    # A failing QC result may still be released, provided the certificate says
    # so (ISO 17025 §7.8.4). Whether it may is not a judgement made here: the
    # QAO owns the library, and `qc_qualification.disposition_for` decides,
    # with the rule that a failure on LABORATORY CONTROL MATERIAL always
    # blocks whatever the library says — there is no client matrix in a blank
    # to attribute it to.

    #: qc_results.qc_type -> the failure type the qualifier library is keyed on
    _QC_TYPE_TO_FAILURE = {
        "LFSM": "lfsm", "LFSMD": "lfsmd", "Dup": "duplicate",
        "MB": "blank", "MxB": "blank", "LRB": "blank", "CCB": "blank",
        "LFB": "lcs", "LCS": "lcs",
        "CCV": "ccv", "Calibration": "calibration", "RT": "rt",
        "IS": "is_response", "IS Response": "is_response",
        # per-injection flags on field samples (_injection_qc_rows)
        "Ion ratio": "ion_ratio", "S/N": "sn", "Surrogate": "surrogate",
        # a field reagent blank: a client sample, so not control material
        "FRB": "field_blank",
        "TB": "trip_blank",
    }

    #: qc_types that ARE laboratory control material. Everything else is
    #: client-derived (a sample, or a spike/duplicate prepared from one).
    _CONTROL_QC_TYPES = frozenset([
        "MB", "MxB", "LRB", "CCB", "LFB", "LCS", "CCV", "ICV", "CAL",
        "Calibration",
    ])

    def _qualify_failure(self, qc_type, analyte):
        """The qualifier for a failing QC result, or None when it must hold.

        Returns the dict `qc_qualification.qualifier_for` produces (which may
        carry `needs_config`), or None when the disposition is BLOCK.
        """
        from senaite.pfas.qc_qualification import qualifier_for
        failure = self._QC_TYPE_TO_FAILURE.get(qc_type)
        if failure == "is_response":
            # A qc_type of "IS" covers BOTH surrogates and the injection
            # standard, and they need opposite causes: a surrogate travels with
            # the sample so its recovery reflects the matrix, while the
            # injection standard is added at reconstitution so its response
            # reflects the instrument. The compound's ROLE in the method
            # decides.
            from senaite.pfas.qc_qualification import _labelled_role
            role_kind = _labelled_role(analyte or u"",
                                       self._method_id_for_qualification())
            failure = role_kind or failure
        if not failure:
            return None
        role = qc_type if qc_type in self._CONTROL_QC_TYPES else u""
        try:
            return qualifier_for(self._portal(), failure, role)
        except Exception as exc:                            # noqa: BLE001
            logger.error("qualifier_for(%s, %s): %s", failure, role, exc)
            return None

    def _high_bias_qualifier(self):
        """The QC Qualifiers library's high-bias entry
        (qc_qualification.high_bias_qualifier), read once per view; None
        when the QAO holds the release or the library cannot be read."""
        if "_high_bias" not in self.__dict__:
            from senaite.pfas.qc_qualification import high_bias_qualifier
            try:
                self._high_bias = high_bias_qualifier(self._portal())
            except Exception as exc:                        # noqa: BLE001
                logger.error("high-bias qualifier: %s", exc)
                self._high_bias = None
        return self._high_bias

    def _stamp_qualifier_remarks(self, ws):
        """Write each qualifier code onto the analyses it applies to.

        Remarks is the durable per-analysis record of the qualification. The
        code is rendered beside the value on the certificate by the add-on's
        report view (`browser/reportview.py`), which reads this stamp back
        through `parse_remark_codes` — core's results table has no remarks cell
        of its own, and an earlier version of this docstring wrongly claimed it
        did, so the stamps were written and never shown. The full wording lives
        once, in the QC Qualifications section.

        Done at APPROVE time rather than during a render: it is a write, and it
        should have a named user and a moment behind it.
        """
        try:
            summary = self._get_qc_summary(ws) or {}
        except Exception as exc:                            # noqa: BLE001
            logger.error("qualifier remarks: %s", exc)
            return
        codes_for = self._qualifier_plan(ws, summary)
        if codes_for is None:
            return
        stamped = 0
        for analysis in (ws.getAnalyses() or []):
            try:
                keyword = analysis.getKeyword()
            except Exception:                               # noqa: BLE001
                continue
            pairs = codes_for(analysis)
            codes = set(code for code, _reason in pairs)
            if not codes:
                continue
            marker = format_remark_codes(codes)
            if not marker:
                continue
            try:
                from senaite.pfas.qc_qualification import remarks_text
                existing = remarks_text(analysis.getRemarks())
                # the release note of a high-biased failure rides beside the codes
                hb_code = (self._high_bias_qualifier() or {}).get("code") or u""
                lines = [marker] + sorted(set(
                    reason for code, reason in pairs if hb_code and code == hb_code and reason))
                lines = [l for l in lines if l not in existing]
                if not lines:
                    continue
                added = u"\n".join(lines)
                analysis.setRemarks(
                    (existing + u"\n" + added).strip() if existing else added)
                stamped += 1
            except Exception as exc:                        # noqa: BLE001
                logger.warning("could not stamp %s: %s", keyword, exc)
        if stamped:
            logger.info("Stamped a QC qualifier onto %d analysis result(s) on "
                        "%s", stamped, ws.getId())

    def _qualifier_plan(self, ws, summary=None):
        """codes_for(analysis) -> [(code, reason)]: the qualifiers this
        worksheet's QC puts on that analysis, only on the samples each
        failure belongs to. None when there are none.
        The stamp writes them; the Final Data tab shows them for review."""
        entries_for = self._qualifier_entries(ws, summary)
        if entries_for is None:
            return None

        from senaite.pfas.rule_flags import on_certificate

        def codes_for(analysis):
            out = []
            for e in entries_for(analysis):
                if not on_certificate(e):
                    continue                # an EDD-only flag's code: never stamped or printed
                item = (e["code"], e.get("reason") or e.get("qc_type") or u"")
                if item not in out:
                    out.append(item)
            return out
        return codes_for

    def _qualifier_entries(self, ws, summary=None):
        """entries_for(analysis) -> the QC summary's qualifier entries that
        belong on that analysis (its code, the lab's statement, the reason),
        only on the samples each failure belongs to. None when the summary
        has none. One plan for the stamp, Final Data and the certificate's
        rows, so a code is never on one and missing from another."""
        from senaite.pfas.qc_qualification import (
            COC_BLANKS, applies_to_coc, applies_to_sample, reported_keyword)
        from senaite.pfas import rule_flags
        if summary is None:
            try:
                summary = self._get_qc_summary(ws) or {}
            except Exception as exc:                        # noqa: BLE001
                logger.error("qualifier plan: %s", exc)
                return None
        pushed, keyword_of = {}, {}
        for p in self._result_pushes(ws.getId()):
            if p.get("injection") and p.get("sample_uid"):
                pushed.setdefault(p["injection"], set()).add(p["sample_uid"])
            if p.get("analyte") and p.get("keyword"):
                keyword_of[p["analyte"]] = p["keyword"]
        by_keyword = {}
        for entry in (summary.get("qualifiers") or []):
            if entry.get("analyte") and entry.get("code"):
                by_keyword.setdefault(
                    reported_keyword(entry["analyte"], keyword_of), []).append(entry)
        if not by_keyword:
            return None
        # a field reagent blank qualifies the samples of its own CoC
        samples = {}
        try:
            for a in (ws.getAnalyses() or []):
                s = a.getRequest()
                if s.UID() not in samples:
                    fld = s.getField("CoCNumber")
                    samples[s.UID()] = ((s.getId(), s.getClientSampleID()),
                                        (fld.get(s) if fld else u"") or u"")
        except Exception as exc:                            # noqa: BLE001
            logger.warning("qualifier plan samples: %s", exc)

        def frb_scope(inj):
            uids = pushed.get(inj) or set(u for u, (names, _c) in samples.items() if inj in names)
            return uids, [samples[u][1] for u in uids if u in samples]

        def applies(e, uid, names):
            if rule_flags.applies_everywhere(e):
                return True             # an analyte row's or the batch's code: every sample
            if e.get("qc_type") in COC_BLANKS:
                frb_uids, cocs = frb_scope(e.get("applies_to") or u"")
                return applies_to_coc(frb_uids, cocs, uid, (samples.get(uid) or ((), u""))[1])
            return applies_to_sample(e.get("applies_to") or u"", uid, names, pushed)

        def entries_for(analysis):
            try:
                sample = analysis.getRequest()
                names = (sample.getId(), sample.getClientSampleID())
                uid = sample.UID()
                entries = list(by_keyword.get(analysis.getKeyword()) or ()) + \
                    list(by_keyword.get(self.ALL_ANALYTES) or ())
            except Exception:                               # noqa: BLE001
                return []
            out = [e for e in entries if applies(e, uid, names)]
            if out and [e for e in out if self._estimate_entry(e)] and not self._prints_number(analysis):
                # an estimate needs a number: a result printed with none
                # carries neither the S/N qualifier nor the code J
                out = [e for e in out if not self._estimate_entry(e)]
            return out
        return entries_for

    def _flag_qualifiers(self, qualifiers, qc_results, batch_key):
        """The QC summary's qualifier entries with each rule's flags applied
        (rule_flags): an Enforced failing rule, or the tier that judged it,
        adds its kind's code (flag_kinds) and each code of its own, each at
        its place and output, and the library's own entry for that failure
        goes. Nothing printing anywhere: the entries as they are. An
        Evaluate failure prints nothing (_flag_advisories). Never changes a
        verdict."""
        from senaite.pfas import rule_flags as rf
        profile = self._method_profile() or {}
        try:
            library = self._qualifier_library()
            if not rf.any_code(profile, library):
                return list(qualifiers)
            tier_of = self._flag_tier_finder(profile)
            role_of = self._flag_role_finder(profile)
            rows = [r for r in qc_results if rf.failing(r) and rf.enforced(r)]
            if any(f["code"] for f in rf.rule_flag_list(profile, "mdl_check")):
                rows += [r for r in self._mdl_rows(batch_key) if rf.enforced(r)]
            added = []
            for r in rows:
                rule, flags = rf.printing_flags(profile, r, library, tier_of, role_of)
                if not flags:
                    continue
                failure = self._QC_TYPE_TO_FAILURE.get(r.get("qc_type"))
                analytes = (self._affected_analytes(failure, r.get("analyte"))
                            if r.get("analyte") else [self.ALL_ANALYTES])
                for flag in flags:
                    added += rf.flag_entries(r, rule, flag, library, analytes, self.ALL_ANALYTES)
            kept = [e for e in qualifiers
                    if not rf.replaced(profile, library, e, self._QC_TYPE_TO_FAILURE, tier_of, role_of)]
            return kept + added
        except Exception as exc:                            # noqa: BLE001
            logger.error("flag qualifiers: %s", exc)
            return list(qualifiers)

    def _flag_advisories(self, qc_results):
        """What each Evaluate failure would raise (rule_flags
        .advisory_entries): for Data Review alone, each marked not printed;
        never a qualifier, a stamp, a certificate or an EDD code."""
        from senaite.pfas import rule_flags as rf
        profile = self._method_profile() or {}
        try:
            library = self._qualifier_library()
            tier_of = self._flag_tier_finder(profile)
            role_of = self._flag_role_finder(profile)
            out = []
            for r in qc_results:
                if rf.failing(r) and not rf.enforced(r):
                    for e in rf.advisory_entries(profile, r, library, tier_of, role_of):
                        if e not in out:
                            out.append(e)
            return out
        except Exception as exc:                            # noqa: BLE001
            logger.error("flag advisories: %s", exc)
            return []

    def _flag_role_finder(self, profile):
        """compound -> its role in the method's labelled-standards grid
        ("surrogate", "injection_is" or ""), as the flags read an IS row."""
        try:
            from senaite.pfas import labelled_standards
            roles = labelled_standards.roles(profile or {}) or {}
        except Exception:                                   # noqa: BLE001
            roles = {}

        def role_of(name):
            name = name or u""
            if name in roles:
                return roles[name] or u""
            # another spelling of the same compound (qc_qualification._same_compound)
            try:
                from senaite.pfas.qc_qualification import _same_compound
                for key, role in roles.items():
                    if _same_compound(key, name):
                        return role or u""
            except Exception:                               # noqa: BLE001
                pass
            return u""
        return role_of

    def advisory_lines(self):
        """Final Data's "Not printed (Evaluate)" lines: each Evaluate
        failure's code (No code while the lab has set none), its kind, and
        what failed where. [] when there is none."""
        try:
            ws = self._get_worksheet()
            summary = self._get_qc_summary(ws) if ws is not None else {}
        except Exception as exc:                            # noqa: BLE001
            logger.warning("advisory lines: %s", exc)
            return []
        out = []
        for e in (summary or {}).get("advisories") or []:
            head = [e.get("code") or u"No code"] + ([e["kind"]] if e.get("kind") else [])
            where = u" ".join(x for x in (e.get("qc_type"), e.get("analyte")) if x)
            if e.get("applies_to"):
                where += u" on %s" % e["applies_to"]
            line = u"%s: %s" % (u" \u00b7 ".join(head), where)
            if e.get("reason"):
                line += u", %s" % e["reason"]
            if line not in out:
                out.append(line)
        return out

    def _qualifier_library(self):
        """The QC Qualifiers library, read once per view; its seeds when it
        cannot be read."""
        if "_flag_library" not in self.__dict__:
            from senaite.pfas import qc_qualification
            try:
                self._flag_library = qc_qualification.get_library(self._portal())
            except Exception:                               # noqa: BLE001
                self._flag_library = qc_qualification.library_from({})
        return self._flag_library

    def _flag_tier_finder(self, profile):
        """row -> the ordinary tier the engine judges the row's analyte by
        in this worksheet's matrix (method_profile_sections.resolve_tier),
        for a QC type that has tiers; None otherwise."""
        from senaite.pfas import method_profile_sections as mps
        from senaite.pfas import report_limits
        try:
            matrix = report_limits.canonical_matrix(profile, self._batch_matrix())
        except Exception:                                   # noqa: BLE001
            matrix = self._batch_matrix()
        groups = mps.engine_flags(profile)
        name = self._qc_row_namer()

        def tier_of(row):
            qc_type = row.get("qc_type") or u""
            if not isinstance(((profile.get("qc_acceptance") or {}).get(qc_type)), dict):
                return None
            k, n = groups.get(name(row.get("analyte") or u""), (False, False))
            return mps.resolve_tier(profile, k, n, matrix, qc_type)
        return tier_of

    def _mdl_rows(self, batch_key):
        """The MDL check's failures (a detection below the MDL, the
        worker's "(MDL)" on a field sample's injection) as QC rows its
        flag can attach to: they are no QC Summary column."""
        from senaite.pfas.rule_flags import MDL_MARK
        try:
            rows = self._store().get_injection_results(batch_id=batch_key, qc_type="Sample")
        except Exception as exc:                            # noqa: BLE001
            logger.warning("MDL rows: %s", exc)
            return []
        # an MDL Check in Evaluate files its failure advisory: never printed
        return [{"qc_type": u"MDL", "analyte": r.get("analyte") or u"", "applies_to": r.get("injection_name") or u"",
                 "flag": r.get("flag") or u"", "passed": 0, "result_status": "active",
                 "advisory": 1 if r.get("advisory") else 0}
                for r in rows if MDL_MARK in (r.get("flag") or u"")]

    def _estimate_entry(self, entry):
        """A qualifier entry that says the value is an estimate: any
        carrying the code J (the certificate's estimate between the MDL and
        the RL), or the S/N failure of a quantifier below its limit (the
        worker's "(J)"), whatever code the QAO gives it."""
        from senaite.pfas.coa_format import J_CODE
        return entry.get("code") == J_CODE or (
            entry.get("qc_type") == u"S/N" and u"(J)" in (entry.get("reason") or u""))

    def _marked_qualifiers(self, ws):
        """(rows, holds) for each result the worker marked for a QC
        Qualifiers entry (a re-spiked dilution, co-eluting peaks split, a
        fitted estimate), read through the one helper that fails closed
        (qc_qualification.marked_qualifiers): a result its entry cannot
        qualify is held by the release gate, with why. Analyses that cannot
        be read hold the run: no result is known to be unmarked. SENAITE's
        own reference analyses carry no sample and no worker mark."""
        from senaite.pfas import qc_qualification as qq
        try:
            items = [{"sample_id": a.getRequest().getId(), "analyte": a.getKeyword(),
                      "remarks": qq.remarks_text(a.getRemarks())} for a in (ws.getAnalyses() or [])
                     if getattr(a, "portal_type", u"") != "ReferenceAnalysis"]
        except Exception as exc:                            # noqa: BLE001
            logger.error("marked qualifiers: %s", exc)
            return [], [qq.MARKS_UNREAD]

        def read(kind):
            return qq.qualifier_for(self._portal(), kind)

        def code_of(kind):
            return (qq.get_library(self._portal()).get(kind) or {}).get("code")
        return qq.marked_qualifiers(items, read, code_of)

    def _receipt_qualifiers(self, ws):
        """The receipt qualifier (qc_qualification "receipt") on every result
        of each sample received out of compliance with its method: its own
        receipt temperature, holding time or the shipment (receipt_compliance)."""
        from senaite.pfas import coc_records as cr
        from senaite.pfas import receipt_compliance as rc
        from senaite.pfas.qc_qualification import qualifier_for
        try:
            qual = qualifier_for(self._portal(), "receipt")
        except Exception as exc:                            # noqa: BLE001
            logger.error("receipt qualifier: %s", exc)
            return []
        if not qual or qual.get("needs_config"):
            return []
        out, seen, records = [], set(), {}
        for a in (ws.getAnalyses() or []):
            try:
                s = a.getRequest()
                if s.UID() in seen:
                    continue
                seen.add(s.UID())
                fld = s.getField("CoCNumber")
                num = (fld.get(s) if fld else u"") or u""
                if not num:
                    continue
                if num not in records:
                    records[num] = cr.load(self._portal(), num) or {}
                flags = ((records[num].get("receipt") or {}).get("flags")) or []
                found = rc.breaches(flags, (s.getId(), s.getClientSampleID()))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("receipt qualifier for a sample: %s", exc)
                continue
            if found:
                out.append({"qc_type": u"Receipt", "applies_to": s.getId(),
                            "reason": u"; ".join(found), "analyte": self.ALL_ANALYTES,
                            "code": qual.get("code") or u"", "statement": qual.get("statement") or u""})
        return out

    def _injection_qc_rows(self, batch_key):
        """Failing per-injection flags on field samples (RT, ion ratio, S/N,
        surrogate recovery) as QC Summary rows scoped to their own sample.
        They qualify the result and do not hold release; they lived only in injection_results, which the gate
        never read (synthetic runs). A flag from a rule in the state
        Evaluate carries the row's advisory mark: a warning, never a
        failure (a database from before the column reads as Enforced).
        A dilution's flag qualifies the sample it was diluted from, as the
        worker files it (a qualifier deleted on the dilution)."""
        from senaite.pfas.qc_qualification import injection_flag_qc_types
        try:
            rows = self._store().get_injection_results(batch_id=batch_key, qc_type="Sample")
            diluted = self._store().get_injection_results(batch_id=batch_key, qc_type="Dilution")
        except Exception as exc:                            # noqa: BLE001
            logger.warning("_injection_qc_rows: %s", exc)
            return []
        parents = self._dilution_parents() if diluted else {}
        out, seen = [], set()
        for r, is_dilution in [(r, False) for r in rows] + [(r, True) for r in diluted]:
            if r.get("passed", 1) or not r.get("flag"):
                continue
            # a dilution with no parent on record qualifies nothing it can name
            sample = parents.get(r.get("injection_name")) if is_dilution else r.get("injection_name")
            if not sample:
                continue
            for qc_type in injection_flag_qc_types(r.get("flag"), r.get("role") or u"",
                                                   r.get("std_role") or u""):
                key = (qc_type, r.get("analyte"), r.get("injection_name"))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"analyte": r.get("analyte") or u"", "qc_type": qc_type,
                            "qc_level": r.get("injection_name") or u"",
                            "applies_to": sample or u"",
                            "value": None, "expected_value": None,
                            "flag": r.get("flag") or u"", "passed": 0,
                            "advisory": 1 if r.get("advisory") else 0,
                            "limit_basis": u"Judged per injection: see the Samples tab",
                            "result_status": "active"})
        return out

    def _dilution_parents(self):
        """{dilution injection: the sample injection it was diluted from},
        from the worksheet's extraction record (dilution_ref.get_dilutions,
        what the worker is given); {} when it cannot be read."""
        try:
            from senaite.pfas.dilution_ref import get_dilutions
            return dict((k, (v or {}).get("parent") or u"")
                        for k, v in get_dilutions(self._get_worksheet()).items())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("_dilution_parents: %s", exc)
            return {}

    #: an entry's analyte meaning "every result on its sample"
    ALL_ANALYTES = u"*"

    def _affected_analytes(self, failure_type, analyte):
        """Reported analytes a failure touches, scoped as narrowly as it is.
        A surrogate failure under a method whose profile says "every result
        on that sample" (EPA 537.1 §9.3.5.3) touches them all."""
        if failure_type == "surrogate" and (
                (self._method_profile() or {}).get("surrogate_failure_scope") == "sample"):
            return [self.ALL_ANALYTES]
        try:
            from senaite.pfas.qc_qualification import MAPPED_FAILURES, analytes_for_failure
            mapping = self._surrogate_map() if failure_type in MAPPED_FAILURES else None
            found = analytes_for_failure(
                failure_type or u"", analyte or u"",
                self._method_id_for_qualification(), mapping=mapping)
            return found or ([analyte] if analyte else [])
        except Exception as exc:                            # noqa: BLE001
            logger.warning("analytes_for_failure(%s, %s): %s",
                           failure_type, analyte, exc)
            return [analyte] if analyte else []

    def _surrogate_map(self):
        """The method's native -> surrogate map (qc_qualification.surrogate_map),
        loaded once per request: every surrogate or isotope-standard failure
        reverses it."""
        if not hasattr(self, "_surrogate_map_memo"):
            from senaite.pfas.qc_qualification import surrogate_map
            self._surrogate_map_memo = surrogate_map(self._method_id_for_qualification())
        return self._surrogate_map_memo

    def _method_id_for_qualification(self):
        profile = self._method_profile() or {}
        return profile.get("method_id") or u""

    def _compute_qc_status(self, ws):
        try:
            summary = self._get_qc_summary(ws)
            if summary.get("error"):
                return False
            if self.import_problems():
                return False             # a run not (fully) imported: its results are not all here
            if self.subtraction_change_pending():
                return False             # results still use the blank chosen before
            if self.identity_pending():
                return False             # the run is not yet judged with the identity corrections
            if self.extraction_pending():
                return False             # nor with the extraction amendments
            if self.send_back_pending():
                return False             # sent back: the retests are not filed yet
            # nothing the gate holds on (a failure, a result not judged, a
            # required QC type not run), and the run's calibration approved
            # at review
            return bool(not self._gate_holds(self._qc_gate(summary))
                        and self.calibration_review().get("status") == "approved")
        except Exception as exc:
            logger.error("_compute_qc_status: %s", exc)
            return False

    # a QC Summary gate that holds with nothing to say
    QC_HOLDS = u"the QC Summary gate holds release"

    def qc_hold(self):
        """Why the QC Summary gate holds release now, or u"": the question
        Approve Release asks of the checklist's QC Summary item
        (_compute_qc_status), worded as the item gives its reason
        (_auto_verdict). Issue asks it again at the moment of issue
        (controlled_publications.qc_hold_refusal), so a hold that applies
        after release, a qualifier set to block, refuses the issue."""
        ws = self._get_worksheet()
        if ws is None or self._compute_qc_status(ws):
            return u""
        return self._auto_verdict(ws, "qc_summary", {"checked": False})[1] or self.QC_HOLDS

    # ── Public checklist interface ────────────────────────────────────────

    def checklist_status(self):
        """The checklist with its auto items computed -- once per request.

        The page asks for it up to seven times (overview cards, the release
        button, three tab notices, the gate) and each computation walks the
        traceability tree and QC results: ~8 s on a real worksheet, so a tab
        took ~40 s. The view lives for one request; saving the checklist
        clears the cached copy."""
        import copy
        cached = getattr(self, "_checklist_cache", None)
        if cached is None:
            cached = self._checklist_status_uncached()
            self._checklist_cache = cached
        return copy.deepcopy(cached)

    def _checklist_status_uncached(self):
        """Return ordered list of item dicts with live-computed auto-checks."""
        ws = self._get_worksheet()
        if not ws:
            return []
        checklist = self._get_checklist(ws)
        items = checklist.get("items", {})

        # Recompute auto items fresh every request
        if "traceability" in items:
            items["traceability"]["checked"] = self._compute_traceability_status(ws)
        if "qc_summary" in items:
            items["qc_summary"]["checked"] = self._compute_qc_status(ws)

        study = self.study_run()
        result = []
        for key, label, auto in _CHECKLIST_ITEMS:
            item = dict(items.get(key, {
                "label": label, "auto": auto, "checked": False,
                "checked_by": None, "checked_at": None, "notes": u"",
                "checked_by_kind": None, "proposed_by": None,
                "proposed_at": None, "proposed_notes": u"",
            }))
            item["key"] = key
            if key == "coc" and study is not None:
                # no chain of custody: the study's source stands in, computed
                # per request and never written into the stored checklist
                item["label"], item["verdict"], item["reason"] = self.study_source_check()[:3]
                item.update(auto=True, study=True, checked=item["verdict"] == "pass")
                result.append(item)
                continue
            # An automatic gate that has run and not passed is a FAILURE, and a
            # gate that could not be evaluated is a third thing. Both showed as
            # "PENDING", which reads as "nobody has got to it yet" — the state
            # least likely to make a reviewer look.
            if item.get("auto"):
                item["verdict"], item["reason"] = self._auto_verdict(ws, key,
                                                                     item)
            else:
                item["verdict"] = "pass" if item.get("checked") else "pending"
                item["reason"] = u""
            result.append(item)
        return result

    def _auto_verdict(self, ws, key, item):
        """(verdict, reason) for an automatic gate.

        verdict is "pass", "qualified", "fail" or "blocked".

        "blocked" means the check could not run, which is not the same as
        failing it. "qualified" means it passed WITH released-but-failing
        results carrying a certificate qualifier — a pass that has something to
        say, and saying it is the whole point of a qualified release.
        """
        if item.get("checked"):
            if key == "qc_summary":
                summary = self._get_qc_summary(ws) or {}
                # a study's own replicates are judged by the study: their
                # routine qualifiers are not the run's
                gate = self._qc_gate(summary)
                by_study = gate["by_study"]
                # a type not run that a closed deviation released is said
                released = u"; ".join(u"{0} not run: released by {1}".format(qt, did)
                                      for qt, did in sorted((gate.get("released") or {}).items()))
                applied = [q for q in summary.get("qualifiers") or []
                           if q.get("qc_type") not in by_study]
                if applied:
                    codes = sorted({(q.get("code") or "?") for q in applied})
                    return "qualified", (
                        u"released with {0} qualified result(s) [{1}] — the "
                        u"certificate carries the corresponding statement"
                        .format(len(applied), u", ".join(codes))) + (u"; " + released if released else u"")
                if released:
                    return "pass", released
            return "pass", u""
        if key == "traceability":
            tree = self._build_traceability_tree(ws) or {}
            unresolved = tree.get("unresolved") or []
            if unresolved:
                return "fail", (
                    u"{0} reagent/standard lot(s) named in the logbooks are "
                    u"not in inventory.".format(len(unresolved)))
            if not (tree.get("prepared_standards") or tree.get("direct_reagents")):
                return "blocked", (
                    u"No reagent or standard lots recorded \u2014 choose the lots "
                    u"loaded in the Run Builder and fill in the extraction record.")
            if not self._extraction_finalized():
                return "blocked", (
                    u"The guided extraction is not finished: the extraction record "
                    u"must name the lots the samples were extracted with.")
            return "fail", u""
        if key == "qc_summary":
            summary = self._get_qc_summary(ws)
            if summary.get("error"):
                return "blocked", (
                    u"QC results are not available: {0}".format(
                        self._QC_ERRORS.get(summary["error"], summary["error"])))
            if self.import_problems():
                return "blocked", u"A delivered run was not imported (see the top of the page)."
            if self.subtraction_change_pending():
                return "blocked", (u"The subtraction blank was changed: reprocess the run "
                                   u"so its results use it.")
            if self.identity_pending():
                return "blocked", self.IDENTITY_PENDING
            if self.extraction_pending():
                return "blocked", self.EXTRACTION_PENDING
            if self.send_back_pending():
                return "blocked", self.SEND_BACK_PENDING
            gate = self._qc_gate(summary)
            failing = [qt for qt, _a, _c in gate["failing"]]
            unevaluated = [qt for qt, _a, _c in gate["unevaluated"]]
            qualified = list(gate["qualified"])
            # the whole-run flags that hold it: a failure, a QC type not
            # judged, a blank whose own limit is not set
            run_failed = [f["qc_type"] for f in gate["run"] if f.get("status") == "fail"]
            # a whole-run failure no qualifier is mapped for is said as the
            # strip and the Blanks verdict say it; any other not judged
            run_unmapped = []
            for f in gate["run"]:
                if f.get("status") != "fail" and f.get("unmapped") and not f.get("unjudged") \
                        and f["unmapped"] not in run_unmapped:
                    run_unmapped.append(f["unmapped"])
            run_unjudged = [f["qc_type"] for f in gate["run"] if f.get("status") != "fail"
                            and (f.get("unjudged") or not f.get("unmapped"))]
            parts = []
            if failing:
                parts.append(u"{0} failing QC result(s) across {1}".format(
                    len(failing), u", ".join(sorted(set(failing)))))
            if run_failed:
                parts.append(u"{0} failed for the whole run".format(u", ".join(run_failed)))
            if gate["unset"]:
                parts.append(u"{0} {1} not set for {2}".format(
                    u" and ".join(gate["unset"]), u"limit" if len(gate["unset"]) == 1 else u"limits",
                    self.method_label()))
            if run_unjudged:
                parts.append(u"{0} not judged for the whole run".format(u", ".join(run_unjudged)))
            if run_unmapped:
                parts.append(u"no qualifier mapped for {0}".format(u", ".join(run_unmapped)))
            if unevaluated:
                # a criterion never configured is also a deviation; it is
                # raised when the run arrives (raise_unconfigured_deviation),
                # never by a page, which only reads
                parts.append(
                    u"{0} result(s) could not be evaluated, no {1}".format(
                        len(unevaluated), u", ".join(sorted(set(unevaluated)))))
            missing = gate["missing"]
            if missing:
                parts.append(
                    u"required QC not evaluated: {0}".format(
                        u", ".join(missing)))
            # a marked result its QC Qualifiers entry cannot qualify
            holds = gate.get("qualifier_holds") or []
            parts.extend(holds)
            # the run's calibration, approved at review
            from senaite.pfas.run_calibration import gate_reason
            cal_verdict, cal_reason = gate_reason(self.calibration_review())
            if cal_reason:
                parts.append(cal_reason)
            if failing or run_failed or cal_verdict == "fail":
                return "fail", u"; ".join(parts)
            if unevaluated or run_unjudged or run_unmapped or gate["unset"] or missing \
                    or cal_verdict == "blocked" or holds:
                return "blocked", u"; ".join(parts)
            if qualified:
                # A qualified release is a PASS with something to say, not a
                # failure. It must still be stated: releasing a failing
                # result without the certificate saying so is the thing
                # §7.8.4 forbids. Said only for this verdict: beside a hold,
                # the reason names the hold.
                summary_q = [q for q in summary.get("qualifiers") or []
                             if q.get("qc_type") not in gate["by_study"]]
                codes = sorted({(q.get("code") or "?") for q in summary_q})
                parts.insert(0, u"released with {0} qualified result(s) [{1}] across "
                                u"{2}".format(len(summary_q), u", ".join(codes),
                                              u", ".join(sorted(set(qualified)))))
                return "qualified", u"; ".join(parts)
            return "fail", u""
        return "pending", u""

    def _qc_gate(self, summary):
        """What holds the QC Summary gate in the summary: one reading for
        the gate's verdict (_auto_verdict), the Blanks verdict's reason
        (overall_reason) and the warnings strip (_gate_rows), holding what
        overall_pass holds. {"failing": [(qc_type, analyte, cell)],
        "unevaluated": [(qc_type, analyte, cell)], "qualified": [qc_type],
        "missing": [qc_type], "run": [flag] the whole-run flags that hold
        it (failed or not judged), "unset": [qc_type] the blanks of those
        not judged for want of their own limit, "by_study": the QC types a
        study run's replicates take}. A study run must carry its part's own
        role (gate_scope), and its replicates are judged by the study, not
        by the routine limits of that role: their routine verdicts never
        hold the run."""
        failing, unevaluated, qualified = [], [], []
        study, study_required, by_study = self.study_run(), None, set()
        if study is not None:
            from senaite.pfas.qc.qc_types import enabled_qc_types
            from senaite.pfas.study_runs import gate_scope
            from senaite.pfas.study_data import blank_role
            study_required, by_study = gate_scope(
                study, enabled_qc_types(self._method_profile() or {}),
                blank_role(self._method_profile() or {}))
            by_study = set(by_study or ())
        for row in (summary.get("rows") or []):
            for qc_type, cell in sorted((row.get("cells") or {}).items()):
                if not cell or qc_type in by_study:
                    continue
                if cell.get("status") == "fail":
                    failing.append((qc_type, row.get("analyte"), cell))
                elif cell.get("status") == "unevaluated":
                    unevaluated.append((qc_type, row.get("analyte"), cell))
                elif cell.get("status") == "qualified":
                    qualified.append(qc_type)
        # A QC type the method requires every run, that produced no
        # result at all, was not evaluated — silence here is how a batch
        # reaches release with its matrix spike never checked.
        profile = self._method_profile() or {}
        # the QC types the method RUNS -- the same flags the engine reads
        from senaite.pfas.qc.qc_types import enabled_qc_types
        required = set(enabled_qc_types(profile)) if study_required is None \
            else study_required
        present = set(summary.get("qc_types") or [])
        # a trip blank or field reagent blank comes with the samples that
        # ask for one (Field QC on the CoC), not with every run
        missing = sorted(r for r in required
                         if r not in present and r not in ("Dup", "MxB", "FRB", "TB"))
        if "LFSMD" in missing and "Dup" in present:
            # a sample duplicate run instead of the LFSMD satisfies the
            # batch's precision requirement
            missing.remove("LFSMD")
        # a type not run that the worksheet's missing-data deviation lists,
        # closed with notes, is released by it; reopened, it holds again
        released = {}
        if missing:
            closed = self._released_missing()
            released = dict((qt, closed[qt]) for qt in missing if qt in closed)
            missing = [qt for qt in missing if qt not in released]
        run_flags = [f for f in summary.get("run_flags") or [] if f.get("qc_type") not in by_study]
        unset = self._unset_blank_limits(run_flags)
        run = [f for f in run_flags if f.get("status") in self._GATING and f.get("qc_type") not in unset]
        # a marked result its QC Qualifiers entry cannot qualify (held)
        holds = list(summary.get("qualifier_holds") or [])
        return {"failing": failing, "unevaluated": unevaluated,
                "qualified": qualified, "missing": missing, "run": run, "unset": unset,
                "by_study": by_study, "released": released, "qualifier_holds": holds}

    def _released_missing(self):
        """{qc_type: dev_id} the worksheet's closed missing-data deviation
        releases (qc_deviation.released_checks), read once per request; {}
        when the registry cannot be read, so nothing is released unread."""
        memo = getattr(self, "_released_memo", None)
        if memo is None:
            memo = {}
            try:
                from senaite.pfas.qc_deviation import get_registry, released_checks
                ws = self._get_worksheet()
                if ws is not None:
                    memo = released_checks(get_registry(self._portal()), ws.getId())
            except Exception as exc:                        # noqa: BLE001
                logger.error("_released_missing: %s", exc)
                memo = {}
            self._released_memo = memo
        return memo

    def qc_types_not_run(self, ws):
        """[{"qc_type", "dev_id"}] (qc_deviation.not_run): the QC types the
        method requires every run that this worksheet's run did not hold, as
        the gate reads them, each with the closed missing-data deviation
        that released it. The certificate states them. Raises ValueError
        when the QC summary cannot be read: a gate not read is never stated
        as nothing missing."""
        from senaite.pfas.qc_deviation import not_run
        summary = self._get_qc_summary(ws) or {}
        if summary.get("error"):
            raise ValueError(u"the QC summary of {0} could not be read ({1})".format(
                ws.getId(), summary["error"]))
        gate = self._qc_gate(summary)
        return not_run(gate.get("missing"), gate.get("released"))

    @staticmethod
    def _gate_holds(gate):
        """True when the QC Summary gate (_qc_gate) holds release: a failing
        result, one not judged, a whole-run flag that holds, a blank limit
        not set, or a QC type the method requires every run that was not
        run. A required type not run holds like a failure until it is run,
        the method or the project's QAPP switch stops requiring it, or the
        worksheet's missing-data deviation that lists it is closed with
        notes."""
        return bool(gate["failing"] or gate["unevaluated"] or gate["run"]
                    or gate["unset"] or gate["missing"] or gate.get("qualifier_holds"))

    def raise_unconfigured_deviation(self, ws):
        """Raise the deviation for the criteria this run's method never set,
        when the gate holds on a result not evaluated (_qc_gate): an ISO
        17025 deviation, since the batch was measured against no standard,
        raised against the worksheet so the QAO is told and a reviewer has
        something to resolve. Asked by the worker once it has pushed the run
        (@@pfas-unconfigured-deviation), never by a render: a page GET does
        not write. The record, or None when there is nothing to raise."""
        summary = self._get_qc_summary(ws) or {}
        if summary.get("error"):
            return None
        gate = self._qc_gate(summary)
        if not gate["unevaluated"] and not gate.get("missing"):
            return None
        return self._raise_unconfigured_deviation(ws, summary, gate.get("missing") or ())

    def _raise_unconfigured_deviation(self, ws, summary, not_run=()):
        """File/refresh the deviation for criteria this method never set, and
        the worksheet's missing-data deviation for each required QC type
        `not_run` (the gate's, after what a closed record releases); the
        first record, or None.

        Idempotent by gap signature, so a run pushed again does not file a
        duplicate. A notification problem never stops the push: it is
        logged, and the record says the QAO was not told.
        """
        try:
            from senaite.pfas.qc_deviation import ensure_deviation
            gaps = []
            for row in (summary.get("rows") or []):
                for qc_type, cell in (row.get("cells") or {}).items():
                    if not cell or cell.get("status") != "unevaluated":
                        continue
                    reason = u""
                    for value in (cell.get("values") or []):
                        if value.get("flag"):
                            reason = value["flag"]
                            break
                    entry = {"qc_type": qc_type, "reason": reason}
                    if entry not in gaps:
                        gaps.append(entry)
            from senaite.pfas.qc_deviation import NOT_RUN
            gaps += [{"qc_type": qt, "reason": NOT_RUN} for qt in not_run or ()]
            if gaps:
                # self._portal() -- `_portal` is a method on this view, not a
                # module function. Calling it bare raised NameError on every
                # attempt, swallowed by the except below, so no deviation was
                # ever filed. It only surfaced once the gap rows it depends on
                # became visible at all.
                return ensure_deviation(self._portal(), ws.getId(), gaps,
                                        filed_by=u"system (QC evaluation)",
                                        method_id=self._method_id_for_qualification())
        except Exception as exc:                            # noqa: BLE001
            logger.error("could not raise the unconfigured-criteria "
                         "deviation: %s", exc)
        return None

    def all_items_pass(self):
        """Every item checked, and every MANUAL item attested by a person.

        `checked` alone is not enough. The three manual items are the ones ISO
        17025 requires a competent, authorised person to authorise, so an
        attestation recorded by a declared service account must not open the
        gate -- see `_handle_check_item`, which refuses to set `checked` for such
        an account in the first place. This is the second half of the same rule,
        enforced at the gate rather than only at the point of entry, because an
        item could also be written by a migration or a scripted POST that never
        goes through that handler (is exactly that shape).

        A manual item with `checked_by_kind` unset is treated as HUMAN. Every
        such item predates this field, and every one of them was written by
        `_handle_check_item`, which has always required an authenticated user and
        typed initials -- so reading them as machine output would invalidate
        real sign-offs retroactively. New automated attestations are labelled,
        so the ambiguity does not grow.
        """
        items = self.checklist_status()
        if not all(i.get("checked") for i in items):
            return False
        # manual integrations: justified, signed and stamped,
        # enforced here too -- a tick written any other way does not open it
        if not self.mi_gate()[0]:
            return False
        # the Integration Review changes: each with a reason and the analyst's initials
        if not self.raw_changes_gate()[0]:
            return False
        return not self.machine_attested_items()

    def submit_held(self):
        """Why Submit for verification is held, said at the top of the page while
        the worksheet is open, the person may submit and the checklist does
        not pass: {"text", "next", "fix_label", "fix_url"}, the next step
        being the first block of the strip (its own button), else the
        checklist at the foot of the Overview. None otherwise."""
        if not (self.can_act() and self.ws_state() == u"open") or self.all_items_pass():
            return None
        pending = [i.get("label") for i in self.checklist_status() if not i.get("checked")]
        text = u"Submit for verification is held until every checklist item passes"
        text += (u": %s not yet." % u", ".join(pending)) if pending else u"."
        blocks = [w for w in self.warnings() or [] if w.get("severity") == self.BLOCKS]
        if blocks:
            return {"text": text, "next": u"First: %s" % blocks[0]["text"],
                    "fix_label": blocks[0]["fix_label"], "fix_url": blocks[0]["fix_url"]}
        return {"text": text, "next": u"", "fix_label": u"Checklist",
                "fix_url": u"%s#dr-submit" % self.review_url(u"overview")}

    def mi_gate(self):
        """(ok, [missing], records, stamped file) for the worksheet's manual
        integrations (manual_integration_view.gate_state); refused, never
        opened, on an error."""
        if not hasattr(self, "_mi_gate"):
            ws = self._get_worksheet()
            if ws is None:
                self._mi_gate = (True, [], 0, u"")
            else:
                try:
                    from bika.lims import api as _mapi
                    from senaite.pfas.browser import manual_integration_view as miv
                    ok, need, state = miv.gate_state(ws)
                    n = len(state.get("records") or [])
                    stamped = (state.get("stamped") or {}).get("file") or u""
                    if n == 0 and _mapi.get_review_status(ws) == "verified":
                        # verified before manual integration was reviewed here:
                        # its release is not reopened
                        self._mi_gate = (True, [], 0, stamped)
                    else:
                        self._mi_gate = (ok, need, n, stamped)
                except Exception as exc:                    # noqa: BLE001
                    logger.exception("manual integration gate")
                    self._mi_gate = (False, [u"the manual-integration records could not be read: %s" % exc], 0, u"")
        return self._mi_gate

    def raw_changes_gate(self):
        """(ok, [missing]) for the changes made on the Integration Review tab: each open
        change has a reason and the analyst's initials; once the worksheet is
        verified, by whatever route, also the verifier's countersignature
        (read when a certificate is issued). A change the run could not apply
        asks nothing; an edit in the run's file with no record is missing.
        The run's processing changes too (mi.processing_gate): each in the
        processing file has a record, and once verified each major one is
        countersigned. Refused, never opened, on an error (a processing
        file that cannot be read among them). The phase is _gate_phase's:
        Approve Release reads the submit gate and gives the countersignature
        itself."""
        if not hasattr(self, "_raw_gate"):
            ws = self._get_worksheet()
            if ws is None:
                self._raw_gate = (True, [])
            else:
                from senaite.pfas import raw_edit
                try:
                    from senaite.pfas import manual_integration as mi
                    from senaite.pfas.browser import manual_integration_view as miv
                    phase = self._gate_phase()
                    self._raw_gate = mi.raw_gate(miv.load_state(ws), phase, self._raw_no_effect(),
                                                 self._raw_overrides())
                    from senaite.pfas import raw_review
                    proc, method = self._raw_processing(), self._method_held()
                    smoothed, label = self._stored_smoothing(), raw_review.library_label(self._raw_library())
                    p_ok, p_need = mi.processing_gate(miv.load_state(ws), phase, proc, method, smoothed, label,
                                                      stored_processing=self._stored_processing())
                    self._raw_gate = (self._raw_gate[0] and p_ok, self._raw_gate[1] + p_need)
                except raw_edit.RawNotJudged as exc:
                    # the run's peaks cannot say what it applied: its own words
                    self._raw_gate = (False, [u"%s" % exc])
                except Exception as exc:                    # noqa: BLE001
                    logger.exception("manual changes gate")
                    self._raw_gate = (False, [u"the manual changes could not be read: %s" % exc])
        return self._raw_gate

    def _gate_phase(self):
        """The phase the gate in force is read in (mi.phase of ws_state, the
        worksheet's state as this page reads it: a study worksheet's is its
        checklist's): raw_changes_gate, which Submit and Approve Release
        enforce, and the Manual changes and Processing changes lines all
        read it here."""
        from senaite.pfas import manual_integration as mi
        return mi.phase(self.ws_state())

    def readiness_phase(self):
        """The phase the readiness lines are worded in (mi.readiness_phase
        of the same state): "verify" from to_be_verified on. Data Review's
        Manual changes and Processing changes and the Manual integration
        page all read it here; each judges the gate in force (_gate_phase),
        so a line never asks what Approve Release itself gives."""
        from senaite.pfas import manual_integration as mi
        return mi.readiness_phase(self.ws_state())

    def _ion_verdicts(self):
        """{change id: ["PFOA: MILK-0027 now fails the ion ratio", ...]}: the
        ion-ratio verdicts each change's own processing changed
        (raw_review.ion_verdict_changes, pinned to it), noted on the change
        in force, Manual or Processing; of a compound's changes processed
        together, on the last. {} without a worksheet or a store, or when the
        store cannot be read (the lists are never held up by it). Once per
        request."""
        if hasattr(self, "_ion_verdicts_cache"):
            return self._ion_verdicts_cache
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import raw_review
        from senaite.pfas.browser import manual_integration_view as miv
        out = self._ion_verdicts_cache = {}
        try:
            ws = self._get_worksheet()
            if ws is None:
                return out
            state = miv.load_state(ws)
            by = {}
            for r in mi.raw_open(state) + mi.processing_open(state):
                if r.get("at"):
                    by.setdefault(r.get("analyte"), []).append(r)
            if not by:
                return out
            label = raw_review.library_label(self._raw_library())
            conn = self._raw_connect()
            if conn is None:
                return out
            try:
                times = raw_review.kept_times(conn, self.batch_id())
                for a, recs in by.items():
                    recs = sorted(recs, key=lambda x: x["at"])
                    for i, r in enumerate(recs):
                        processed = next((t for t in times if t > r["at"]), None)
                        if processed is None or (i + 1 < len(recs) and recs[i + 1]["at"] < processed):
                            continue                # not processed yet, or processed with a later change
                        texts = raw_review.verdict_texts(label(a), raw_review.ion_verdict_changes(
                            conn, self.batch_id(), label(a), r["at"]))
                        if texts:
                            out[r["id"]] = texts
            finally:
                conn.close()
        except Exception:                                   # noqa: BLE001
            # never in the way of the change lists: the notes are left out
            logger.exception("ion ratio verdict changes unread")
            out.clear()
        return out

    def manual_changes(self):
        """The Manual changes panel: every change made on the Integration Review tab
        and not undone, with the active reasons to choose from. A change the
        run could not apply says why ("no_effect") and asks no reason or
        initials; "initialled" counts those that need them. A row says which
        samples changed ion-ratio verdict when the run was processed after
        it ("verdicts", _ion_verdicts). Once submitted its line judges the
        release ("ready", mi.verify_readiness in readiness_phase) against
        the gate in force (_gate_phase), never asking the countersignature
        Approve Release gives; before, "ready" is None and the line reads
        the submit gate ("ok", "missing")."""
        ws = self._get_worksheet()
        if ws is None:
            return {"rows": [], "ok": True, "missing": [], "verify_ok": True, "initialled": 0, "ready": None}
        from senaite.pfas import manual_integration as mi
        from senaite.pfas.browser import manual_integration_view as miv
        state = miv.load_state(ws)
        no_effect = self._raw_no_effect()
        active = [r for r in miv.get_settings()["reasons"] if r.get("active", True)]
        from six.moves.urllib.parse import quote
        base = ws.absolute_url() + u"/@@pfas-data-review?tab=raw&injection="
        from senaite.pfas import raw_review
        # a record keeps the keyword its edit is keyed by; it is shown by name
        label = raw_review.library_label(self._raw_library())
        rows = []
        for r in mi.raw_open(state):
            choices = list(active)
            if r.get("reason_id") and r["reason_id"] not in [c["id"] for c in active]:
                # a reason since taken off the list stays shown as chosen
                choices.append({"id": r["reason_id"], "text": r.get("reason") or r["reason_id"]})
            rows.append({"id": r["id"], "injection": r["injection"], "analyte": label(r["analyte"]),
                         "transition": r.get("transition") or u"quantifier",
                         "kind": mi.RAW_KIND_TEXT.get(r.get("kind"), r.get("kind") or u""),
                         "summary": mi.raw_summary(r),
                         "shared": (u"Shared edge with %s" % label(r["shared_with"])) if r.get("shared_with") else u"",
                         "reason_id": r.get("reason_id") or u"",
                         "reason": r.get("reason") or u"",
                         "detail": r.get("detail") or u"", "choices": choices,
                         "analyst": r["analyst"] if mi.raw_signed(r, "analyst") else None,
                         "verifier": r["verifier"] if mi.raw_signed(r, "verifier") else None,
                         "no_effect": (u"No effect: " + no_effect[mi.raw_key(r)]
                                       if mi.raw_key(r) in no_effect else u""),
                         "verdicts": self._ion_verdicts().get(r["id"], []),
                         "href": base + quote(r["injection"].encode("utf-8"), safe="")})
        overrides = self._raw_overrides()
        ok, missing = mi.raw_gate(state, u"submit", no_effect, overrides)
        v_ok, v_missing = mi.raw_gate(state, u"verify", no_effect, overrides)
        # the line asks only what the gate in force asks: until release the
        # countersignature is Approve Release's own to give
        gate = (v_ok, v_missing) if self._gate_phase() == u"verify" else (ok, missing)
        return {"rows": rows, "ok": ok, "missing": missing,
                "initialled": len([r for r in rows if not r["no_effect"]]),
                "verify_ok": v_ok, "ready": mi.verify_readiness(self.readiness_phase(), *gate)}

    # a change in the run's processing file whose record was never saved
    NOT_RECORDED = u"not recorded"
    # the Transition of a smoothing change, the compound's
    ALL_TRANSITIONS = u"all transitions"
    # a change that cannot be read is listed in these words, never left out
    UNREADABLE_CHANGE = u"an unreadable change"

    def _processing_words(self, record):
        """A change as the list words it (raw_review.processing_text), or
        UNREADABLE_CHANGE for one that cannot be read: an entry taken out
        of the file by its key may be any shape, and the history keeps it."""
        from senaite.pfas import raw_review
        if record is None:
            return raw_review.processing_text(None)
        try:
            return raw_review.processing_text(raw_review.processing_of(record))
        except (AttributeError, KeyError, TypeError, ValueError):
            return self.UNREADABLE_CHANGE

    def processing_changes(self):
        """The Processing changes list beside Manual changes: every change
        applied to all injections, in the order made, undone ones too, then
        each change in the run's file with no record ("recorded" False, its
        "id" its processing key, its Undo taking it out of the file), each
        {"id", "who" (the person's name), "when" (lab time), "compound",
        "transition", "before", "after" (raw_review.processing_text),
        "major", "in_force" (its trace's last change not undone: the one a
        major change's countersign is asked of), "verifier" (the
        countersignature that holds, or None), "verdicts" (the samples
        whose ion-ratio verdict the run's processing after it changed,
        _ion_verdicts),
        "undone" ({"who", "when"} or None), "actions" (the row's menu:
        Undo while the worksheet is open and the change is in force, Open
        in Integration Review)}; with the gate ("ok", "missing" at submit), whether
        Verify still countersigns a major change ("verify_ok") and, once
        submitted, the line judging the release ("ready",
        mi.verify_readiness in readiness_phase; None before). Then each
        change the method holds that the run applies (_method_held), read
        only, its Who METHOD_WHO and "held" its words ("Fitted by the
        method's processing"; None on the run's own rows), a major one
        countersigned at release. A processing file that cannot be read is
        said, never read as none."""
        ws = self._get_worksheet()
        if ws is None:
            return {"rows": [], "ok": True, "missing": [], "verify_ok": True, "ready": None}
        from six.moves.urllib.parse import quote
        from senaite.pfas import manual_integration as mi
        from senaite.pfas import method_proposals as mp
        from senaite.pfas import raw_review, row_menu
        from senaite.pfas.browser import manual_integration_view as miv
        from senaite.pfas.browser import staff
        state = miv.load_state(ws)
        label = raw_review.library_label(self._raw_library())
        in_force = set(r["id"] for r in mi.processing_open(state))
        edit = self.can_act() and self.ws_state() == u"open"
        names = {}

        def name(userid):
            if userid not in names:
                try:
                    names[userid] = staff.staff_info(userid).get("fullname") or userid
                except Exception:                           # noqa: BLE001
                    names[userid] = userid
            return names[userid]
        base = ws.absolute_url() + u"/@@pfas-data-review?tab=raw&mode=compound&analyte="
        try:
            proc, unread = self._raw_processing(), None
        except ValueError as exc:
            proc, unread = {}, u"%s" % exc
        rows = []
        verdicts = self._ion_verdicts()
        orphans = mi.processing_orphans(state, proc) if not unread else []
        waiting = self._proposed_traces()
        for r in state.get("processing_changes") or []:
            undone = r.get("undone")
            recorded = r.get("recorded", True)
            undo = propose = None
            smoothing = r.get("kind") == mi.SMOOTHING
            # a change whose file holds another is undone by that one's row
            if edit and r["id"] in in_force and mi.processing_rec_key(r) not in orphans:
                undo = (u"Undo", "form", "dr-processing-undo", {"values": {"id": r["id"]}, "danger": True})
            # a manager proposes the change in force as the method's own,
            # whatever the worksheet's state: it changes no review record
            # nor one the method already holds
            if (waiting is not None and r["id"] in in_force and r.get("after")
                    and not mp.holds(self._method_profile(), r["analyte"], r.get("transition"), r["after"])):
                busy = mp.waiting_key(r["analyte"], r.get("transition"), r["after"]) in waiting
                propose = (u"Propose for the method", "form", "dr-processing-propose",
                           {"values": {"id": r["id"]},
                            "off": self._propose_waiting_text(r) if busy else None,
                            "note": None if busy else self.PROPOSE_NOTE})
            if smoothing and recorded:
                # the compound's smoothing, by step: "Mid", then "Smoothing
                # for PFOS: Mid to High"
                before = mi.smoothing_step((r.get("before") or {}).get("points"), r.get("mid"))
                after = mi.smoothing_words(r, label(r["analyte"]))
            else:
                before = (self.NOT_RECORDED if not recorded
                          else self.METHOD_BEFORE if r.get("before") is None and r.get("before_method")
                          else self._processing_words(r.get("before")))
                after = self._processing_words(r.get("after"))
            rows.append({"id": r["id"], "who": name(r.get("by") or u""),
                         "when": lab_time.show(r.get("at")) if r.get("at") else u"",
                         "compound": label(r["analyte"]),
                         "transition": self.ALL_TRANSITIONS if smoothing else r.get("transition") or u"quantifier",
                         "before": before, "after": after, "major": bool(r.get("major")),
                         "in_force": r["id"] in in_force, "recorded": recorded, "held": None,
                         "verifier": r["verifier"] if mi.processing_signed(r) else None,
                         "verdicts": verdicts.get(r["id"], []),
                         "undone": ({"who": name(undone.get("by") or u""),
                                     "when": lab_time.show(undone.get("at")) if undone.get("at") else u""}
                                    if undone else None),
                         "actions": row_menu.actions(
                             undo, propose,
                             (u"Open in Integration Review", "href", base + quote(r["analyte"].encode("utf-8"), safe="")))})
        for key in orphans:
            rec = mi.processing_entry(proc, key)
            after = self._processing_words(rec)
            analyte, transition, smoothing = mi.processing_key_trace(key)
            rec = rec if isinstance(rec, dict) else {}
            undo = None
            if edit:
                undo = (u"Undo", "form", "dr-processing-undo", {"values": {"key": key}, "danger": True})
            rows.append({"id": key, "who": name(rec.get("by") or u""),
                         "when": lab_time.show(rec.get("at")) if rec.get("at") else u"",
                         "compound": label(analyte),
                         "transition": self.ALL_TRANSITIONS if smoothing else transition or u"quantifier",
                         "before": self.NOT_RECORDED, "after": after,
                         "major": rec.get("kind") in mi.PROCESSING_MAJOR_KINDS, "in_force": True,
                         "recorded": False, "held": None, "verifier": None, "undone": None, "verdicts": [],
                         "actions": row_menu.actions(
                             undo, (u"Open in Integration Review", "href", base + quote(analyte.encode("utf-8"), safe="")))})
        phase = self.readiness_phase()
        if unread:
            return {"rows": rows, "ok": False, "missing": [unread], "verify_ok": False,
                    "ready": mi.verify_readiness(phase, False, [unread])}
        # the method's own changes the run applies: listed, read-only, as
        # done by the method's processing; a fit countersigned at release.
        # Stored peaks that cannot be read are said and refused, never read
        # as none
        try:
            method = self._method_held()
        except ValueError as exc:
            held_unread = u"%s" % exc
            return {"rows": rows, "ok": False, "missing": [held_unread], "verify_ok": False,
                    "ready": mi.verify_readiness(phase, False, [held_unread])}
        signed = state.get("method_processing_signed") or {}
        for h in mi.method_held(method):
            held_text = mi.METHOD_KIND_TEXT.get(h["kind"], u"")
            rows.append({"id": u"method:" + h["key"], "who": self.METHOD_WHO, "when": u"",
                         "compound": label(h["analyte"]), "transition": h["transition"] or u"quantifier",
                         "before": raw_review.processing_text(None), "after": self._processing_words(h["record"]),
                         "major": h["major"], "in_force": True, "recorded": True,
                         "held": held_text[:1].upper() + held_text[1:],
                         "verifier": signed.get(h["key"]) if mi.method_held_signed(state, h) else None,
                         "verdicts": [], "undone": None,
                         "actions": row_menu.actions(
                             (u"Open in Integration Review", "href", base + quote(h["analyte"].encode("utf-8"), safe="")))})
        smoothed, applied = self._stored_smoothing(), self._stored_processing()
        ok, missing = mi.processing_gate(state, u"submit", proc, method, smoothed, label, stored_processing=applied)
        v_ok, v_missing = mi.processing_gate(state, u"verify", proc, method, smoothed, label,
                                             stored_processing=applied)
        # as the Manual changes line: only what the gate in force asks
        gate = (v_ok, v_missing) if self._gate_phase() == u"verify" else (ok, missing)
        return {"rows": rows, "ok": ok, "missing": missing,
                "verify_ok": v_ok, "ready": mi.verify_readiness(phase, *gate)}

    def _handle_manual_changes(self):
        """The analyst gives each Integration Review change a reason from the lab's
        active list, with any detail, and initials them all at once. A person,
        never a service account, initials."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error")
        from senaite.pfas import manual_integration as mi
        from senaite.pfas.browser import manual_integration_view as miv
        f = self.request.form
        user = getSecurityManager().getUser()
        who = user.getId()
        when = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        initials = (f.get("initials") or u"").strip()
        if initials and _actor_kind(user) == u"automated":
            return self._redirect_with_msg("manual_changes_refused", "error",
                                           detail=u"a service account does not initial manual changes.")
        state = miv.load_state(ws)
        no_effect = self._raw_no_effect()
        active = dict((r["id"], r) for r in miv.get_settings()["reasons"] if r.get("active", True))
        error = u""
        for rec in mi.raw_open(state, no_effect):
            rid = f.get("%s.reason_id" % rec["id"])
            if rid is None:
                continue
            if rid == (rec.get("reason_id") or u""):
                reason = rec.get("reason") or u""       # kept as chosen, even if since retired
            elif rid in active:
                reason = active[rid]["text"]
            elif rid:
                error = u"%s: choose a reason from the list." % mi.raw_label(rec)
                continue
            else:
                reason = u""
            mi.set_raw_reason(state, rec["id"], rid, reason, f.get("%s.detail" % rec["id"]), who, when)
        if initials and not error:
            # the analyst's sign right in People & Roles, as for the instrument
            # report's records; a staff record that cannot be read signs nothing
            try:
                info = miv.staff_sign_info(who)
                mi.initial_raw(state, initials, who, when, info["name"], no_effect, info["sign_as"], info["signature"])
            except ValueError as exc:
                error = u"%s" % exc
        miv.save_state(ws, state)
        self._audit(ws)
        if error:
            return self._redirect_with_msg("manual_changes_refused", "error", detail=error)
        return self._redirect_with_msg("manual_changes_saved", "ok")

    def _countersign_raw_changes(self, ws, save=False):
        """At release the person who approves countersigns every open
        Integration Review change and every major processing change in force, the
        method's that the run applies among them (_method_held); refused
        (the message) without the reviewer sign right in People & Roles, or
        when they initialled or edited one, or made the processing change.
        u"" when signed or there is none. Unless `save`, the countersign is only tried, on a
        copy: Approve Release saves it once the worksheet is verified, so the
        record names the person who released."""
        import copy
        from senaite.pfas import manual_integration as mi
        from senaite.pfas.browser import manual_integration_view as miv
        state = miv.load_state(ws)
        no_effect = self._raw_no_effect()
        # the major processing changes in force are countersigned with them,
        # the method's the run applies among them; refused when the run's
        # stored peaks cannot be read
        try:
            method = self._method_held()
        except ValueError as exc:
            return u"%s" % exc
        major = [r for r in mi.processing_open(state) if r.get("major")]
        major += [h for h in mi.method_held(method) if h["major"]]
        if not mi.raw_open(state, no_effect) and not major:
            return u""
        who = getSecurityManager().getUser().getId()
        when = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        work = state if save else copy.deepcopy(state)
        try:
            info = miv.staff_sign_info(who)
            if mi.raw_open(work, no_effect):
                mi.countersign_raw(work, who, when, info["name"],
                                   no_effect, info["sign_as"], info["signature"])
            mi.countersign_processing(work, who, when, info["name"], info["sign_as"], info["signature"], method)
        except ValueError as exc:
            return u"%s" % exc
        if save:
            miv.save_state(ws, state)
        return u""

    def machine_attested_items(self):
        """Manual items whose attestation was made by a service account.

        Non-empty means the checklist LOOKS complete but is not authorised.
        Returned rather than merely counted so the reviewer is told WHICH items
        still need a person.
        """
        return [i for i in self.checklist_status()
                if not i.get("auto")
                and i.get("checked")
                and i.get("checked_by_kind") == u"automated"]


    def submission_info(self):
        ws = self._get_worksheet()
        if not ws:
            return {}
        cl = self._get_checklist(ws)
        return {
            "submitted_by": cl.get("submitted_by") or u"",
            "submitted_at": print_doc.lab_or(cl.get("submitted_at"), (cl.get("submitted_at") or u"")[:16],
                                             u"%Y-%m-%dT%H:%M"),
            "approved_by":  cl.get("approved_by") or u"",
            "approved_at":  print_doc.lab_or(cl.get("approved_at"), (cl.get("approved_at") or u"")[:16],
                                             u"%Y-%m-%dT%H:%M"),
        }

    # ── CoC summary (for CoC tab) ─────────────────────────────────────────

    def _core_collection_date(self, ws):
        from senaite.pfas import core_fields
        return core_fields.core_values(ws).get("sample_collection_date") or u""

    def coc_records_summary(self, ws):
        """The worksheet's samples' CoC records (coc_records.summary), with
        core's collection date: {} when no sample carries a CoC number."""
        from senaite.pfas import coc_records as cr
        from senaite.pfas.core_fields import samples_of
        samples = list(samples_of(ws))
        out = cr.worksheet_summary(self._portal(), samples)
        if out:
            out["sample_collection_date"] = self._core_collection_date(ws)
            # which of the scoped checks the receipts hold an answer to: a
            # check that was not asked is neither shown nor required
            out["checks"] = cr.stored_checks(cr.worksheet_records(self._portal(), samples))
        return out

    def study_run(self):
        """The worksheet's study run record (study_runs), or None."""
        if not hasattr(self, "_study_run"):
            ws = self._get_worksheet()
            self._study_run = None
            if ws is not None:
                from senaite.pfas import study_runs
                self._study_run = study_runs.load_run(ws)
        return self._study_run

    def study_source_check(self):
        """(label, verdict, reason, detail) of the chain-of-custody item for a
        study run: its source, judged on the day of the extraction."""
        if hasattr(self, "_study_source"):
            return self._study_source
        from senaite.pfas import study_runs as sru
        from senaite.pfas.dilution_ref import LOGBOOK_KEY
        run = self.study_run() or {}
        source = run.get("source") or {}
        ws = self._get_worksheet()
        use_date = ((self._logbook_json(ws, LOGBOOK_KEY) or {}).get("extraction_date")
                    or u"")[:10] if ws is not None else u""
        detail = {"source": source, "source_label": sru.SOURCE_LABELS.get(source.get("kind"), u""),
                  "use_date": use_date, "lot": None, "receipt": None, "coa": None, "water_check": None,
                  "study": run.get("study") or u"", "part": run.get("part") or u""}
        try:
            if source.get("kind") == sru.WATER_SYSTEM:
                if use_date:
                    from senaite.pfas import facility_qc
                    detail["water_check"] = facility_qc.get_water_qc_for_date(use_date)
            elif source.get("uid"):
                from senaite.pfas.browser.bench_inventory import REAGENT, item_index
                from senaite.pfas.browser.reagents import _get_coa_meta
                portal = self._portal()
                detail["lot"] = item_index(portal).get((REAGENT, source["uid"]))
                folder = portal.get("pfas_reagents")
                obj = folder.get(source["uid"]) if folder is not None else None
                detail["receipt"] = sru.load_receipt(obj) if obj is not None else None
                detail["coa"] = _get_coa_meta(portal, source["uid"]) or None
            problems = sru.source_problems(source, detail["lot"], detail["receipt"], detail["coa"],
                                           detail["water_check"], use_date)
        except Exception as exc:                            # noqa: BLE001
            logger.exception("study source check")
            problems = [u"the study's source could not be read: %s" % exc]
        label, verdict, reason = sru.coc_item(run, problems)
        self._study_source = (label, verdict, reason, detail)
        return self._study_source

    def coc_summary(self):
        """The CoC as Data Review checks it: the samples' CoC records
        (coc_records.worksheet_summary); {} when no sample carries a CoC
        number."""
        ws = self._get_worksheet()
        if not ws:
            return {}
        try:
            from_records = self.coc_records_summary(ws)
            if from_records:
                return from_records
        except Exception as exc:                            # noqa: BLE001
            logger.error("coc records summary: %s", exc)
        return {}

    def _run_date(self, ws):
        """The run's date in the QC record (its last acquisition), or None."""
        try:
            row = self._store().get_batch(ws.getId())
            return (row["run_date"] if row is not None else None) or None
        except Exception:                                   # noqa: BLE001
            return None

    def _analysis_times(self, ws):
        """When each of the worksheet's reported results was analysed, in
        order, as naive datetimes on the laboratory's clock: the
        certificate's reader (analysed_at: the injection's acquisition time,
        else the date the result was captured), never the run's date in the
        QC store. A result not yet entered, or retracted, rejected or
        cancelled, has none."""
        cache = self.__dict__.setdefault("_analysis_times_cache", {})
        key = ws.getId()
        if key not in cache:
            from bika.lims import api as _api
            from senaite.pfas import analysed_at
            from senaite.pfas.sample_method import EXCLUDED_STATES
            reported = [an for an in ws.getAnalyses() or []
                        if getattr(an, "portal_type", "") == "Analysis"
                        and (an.getResult() or u"").strip()
                        and _api.get_review_status(an) not in EXCLUDED_STATES]
            acquired = analysed_at.acquired_by_uid([_api.get_uid(an) for an in reported])
            times = [analysed_at.wall(acquired.get(_api.get_uid(an)), an.getResultCaptureDate())
                     for an in reported]
            cache[key] = sorted(t for t in times if t is not None)
        return cache[key]

    def analysis_dates(self, ws=None):
        """When the worksheet's results were analysed, one answer for holding
        time, this page's run line and the QC Review: the certificate's
        reader (_analysis_times) whenever any reported result has a date;
        when none has, the run's date in the QC store, marked so, never
        nothing -- a gate does not weaken because a date is missing.
        {"days": ["YYYY-MM-DD"], "last": date or None, "by_run_date": bool,
         "text": "2026-10-05, 2026-10-06" or "2026-11-07, by run date"}."""
        ws = ws if ws is not None else self._get_worksheet()
        none = {"days": [], "last": None, "by_run_date": False, "text": u""}
        if ws is None:
            return none
        try:
            times = self._analysis_times(ws)
        except Exception as exc:                            # noqa: BLE001
            logger.error("analysis_dates: %s", exc)
            times = []
        if times:
            days = sorted(set(t.date().isoformat() for t in times))
            return {"days": days, "last": times[-1].date(), "by_run_date": False,
                    "text": u", ".join(days)}
        last = holding_time.parse_date(self._run_date(ws))
        if last is None:
            return none
        return {"days": [last.isoformat()], "last": last, "by_run_date": True,
                "text": u"%s, %s" % (last.isoformat(), holding_time.BY_RUN_DATE)}

    def run_days(self):
        """The run line: the days the worksheet's results were analysed, or
        the run's date marked "by run date" (analysis_dates)."""
        return self.analysis_dates()["text"]

    def holding_time_summary(self):
        """Computed holding time for this worksheet's batch.

        Each sample's own collection date (core Date Sampled: core owns it; it was the Chain of Custody's one date) and
        `extraction_date` on the extraction record. Read through `_logbook_json`, which
        looks on the worksheet then the linked batch — on the one worksheet
        with real data the CoC is on both and 252 is on the BATCH only, so a
        worksheet-only read would have found nothing and reported `no_dates`
        forever.

        The limit comes from the method profile keyed by matrix, resolved the
        same way the matrix factor is. Unset means refuse to judge.
        """
        ws = self._get_worksheet()
        if ws is None:
            return holding_time.evaluate(None, None, None)
        try:
            # each sample from its own Date Sampled (core owns the collection
            # date; core_fields.py)
            from senaite.pfas import core_fields
            from senaite.pfas.dilution_ref import LOGBOOK_KEY
            ext = self._logbook_json(ws, LOGBOOK_KEY) or {}
            profile = self._method_profile() or {}
            limit = holding_time.limit_for(profile, self._batch_matrix())
            samples = core_fields.samples_of(ws)
            judged = dict(
                (s.getId(), holding_time.evaluate(core_fields.date_sampled(s),
                                                  ext.get("extraction_date"), limit))
                for s in samples)
            # a homogenised sample's own clock, homogenisation complete to
            # extraction, from the lab day of its UTC stamp; a sample not
            # homogenised has none
            from senaite.pfas import homogenisation as hg
            from senaite.pfas import lab_time
            proc_limit = holding_time.processed_limit_for(profile, self._batch_matrix())
            for s in samples:
                rec = hg.latest(hg.load_records(s)) or {}
                if rec and rec.get("method") not in (None, u"", hg.NONE_ID):
                    judged[holding_time.PROCESSED + s.getId()] = holding_time.evaluate_processed(
                        lab_time.lab_date(rec.get("at"), "utc"), ext.get("extraction_date"), proc_limit)
            # the extract, extraction to analysis (EPA 537.1 §8.5: 28 days), where the method sets one:
            # to the last result's analysis date, read as the certificate reads it, else the run's date
            ext_limit = holding_time.extract_limit_for(profile, self._batch_matrix())
            if ext_limit is not None:
                dates = self.analysis_dates(ws)
                judged[u"extract"] = holding_time.evaluate_extract(
                    ext.get("extraction_date"), dates["last"], ext_limit, by_run_date=dates["by_run_date"])
            verdict = holding_time.combine(judged)
        except Exception as exc:                            # noqa: BLE001
            logger.error("holding_time_summary: %s", exc)
            return holding_time.evaluate(None, None, None)
        verdict["matrix"] = self._batch_matrix()
        verdict["blocking"] = verdict["status"] in holding_time.BLOCKING
        return verdict

    def holding_time_rows(self):
        """The three clocks as dates: sample, processed sample, extract."""
        return holding_time.clock_rows(self.holding_time_summary())

    # ── Traceability ──────────────────────────────────────────────────────

    @staticmethod
    def _build_lot_indices(portal):
        """Build in-memory lot dicts (lot_number is not a catalog index).

        ARCHIVED reagents are excluded. This walked
        `objectValues()` raw, so a lot the lab had deliberately withdrawn still
        satisfied traceability — demonstrated live: archiving a parent left the
        gate reporting `resolved=True`. Every other consumer of reagent data
        filters archived lots; this one did not, which is also.9's "three
        resolvers, three answers".
        """
        from senaite.pfas.browser.reagents import _ANN_ARCHIVED_KEY
        reagent_by_lot = {}
        reagent_folder = portal.get("pfas_reagents")
        if reagent_folder is not None:
            for obj in reagent_folder.objectValues():
                if getattr(obj, "portal_type", "") != "Reagent":
                    continue
                try:
                    if IAnnotations(obj).get(_ANN_ARCHIVED_KEY):
                        continue
                except Exception:
                    pass
                lot = (getattr(obj, "lot_number", "") or "").strip()
                if lot:
                    reagent_by_lot[lot] = obj

        ps_by_lot = {}
        ps_folder = portal.get("pfas_prepared_standards")
        if ps_folder is not None:
            for obj in ps_folder.objectValues():
                if getattr(obj, "portal_type", "") == "PreparedStandard":
                    lot = (getattr(obj, "lot_number", "") or "").strip()
                    if lot:
                        ps_by_lot[lot] = obj

        return reagent_by_lot, ps_by_lot

    def _reagent_dict(self, r):
        # `has_coa` carried because the chain previously terminated at a Reagent
        # URL and never reached the certificate of analysis — so the
        # tree proved inventory membership, not that the lot is certified
        # reference material, which is the whole point of level 1.
        has_coa = False
        try:
            from senaite.pfas.browser.reagents import _COA_ANN_KEY
            has_coa = bool(IAnnotations(r).get(_COA_ANN_KEY))
        except Exception:
            pass
        return {
            "title":      r.Title() if hasattr(r, "Title") else (r.title or u""),
            "cat_number": getattr(r, "cat_number", "") or u"",
            "supplier":   getattr(r, "supplier", "") or u"",
            "lot_number": getattr(r, "lot_number", "") or u"",
            "url":        r.absolute_url(),
            "has_coa":    has_coa,
            # the inventory category the lot is filed under
            "category":   getattr(r, "category", "") or u"",
        }

    def _resolve_parent(self, portal, parent, reagent_by_lot):
        """The Reagent a parent record refers to, or None.

        UID FIRST, lot string second. The annotation has always
        carried a `uid` per parent and nothing read it — resolution was by
        lot-number string alone, so renaming or re-lotting a Reagent broke the
        level-1 link silently. The repo already does this correctly for
        salt-factor CoA links (D54: `{analyte, factor, lot_uid, lot_number}`
        resolved by uid); `parent_reagents` was never brought up to it.

        The lot fallback is deliberate and permanent: every parent record written
        before this carries no usable uid, and they must keep resolving.
        """
        uid = (parent.get("uid") or u"").strip()
        if uid:
            folder = portal.get("pfas_reagents")
            obj = folder.get(uid) if folder is not None else None
            if obj is not None and getattr(obj, "portal_type", "") == "Reagent":
                return obj
        lot = (parent.get("lot") or u"").strip()
        return reagent_by_lot.get(lot) if lot else None

    def _extraction_home(self, ws):
        """Where this worksheet's extraction record lives: the worksheet
        itself, or -- for an older record not yet moved
        -- its client Batch."""
        if ws is None:
            return None
        from senaite.pfas import extraction_batch
        from senaite.pfas.dilution_ref import EXTRACTION_SESSION_KEY, LOGBOOK_KEY
        ann = IAnnotations(ws)
        if extraction_batch.load(ws) or ann.get(EXTRACTION_SESSION_KEY) or ann.get(LOGBOOK_KEY):
            return ws
        return self._linked_batch(ws) or ws

    def _linked_batch(self, ws):
        """The SENAITE Batch this worksheet's analyses belong to.

        Derived structurally: every analysis knows its sample, and every sample
        knows its batch (SENAITE's own link); a worksheet whose analyses name
        no batch has none.
        """
        try:
            counts = {}
            for analysis in (ws.getAnalyses() or []):
                try:
                    batch = analysis.getRequest().getBatch()
                except Exception:
                    continue
                if batch is not None:
                    counts[batch] = counts.get(batch, 0) + 1
            if counts:
                return max(counts, key=counts.get)
        except Exception:
            pass
        return None

    def _logbook_json(self, ws, key):
        """A record annotation with a DUAL-READ home: the worksheet first
        (canonical), else the batch SENAITE links its analyses to, which
        holds the records written before they moved to the worksheet -- so
        review finds the extraction record wherever the bench recorded it."""
        for obj in (ws, self._linked_batch(ws)):
            if obj is None:
                continue
            try:
                raw = IAnnotations(obj).get(key)
                if raw:
                    return json.loads(raw)
            except Exception:
                continue
        return {}

    def _build_traceability_tree(self, ws):
        from senaite.pfas.dilution_ref import LOGBOOK_KEY
        portal = self._portal()

        def _load(key):
            return self._logbook_json(ws, key)

        lb252 = _load(LOGBOOK_KEY)
        # The guided extraction's stages are the record of the lots it used,
        # and the batch record prints them from the session. The walk reads
        # the same rows through the same function (worksheet_lots), never
        # the copy Finalise leaves on the extraction table: a lot the batch
        # record lists is then always a lot this walk judges.
        from senaite.pfas import worksheet_lots
        from senaite.pfas.dilution_ref import EXTRACTION_SESSION_KEY
        session = _load(EXTRACTION_SESSION_KEY)
        if worksheet_lots.recorded(session):
            lb252 = dict(lb252, **worksheet_lots.extraction_tables(session))
        # the spike lots the QC members were made with are standards the
        # analysis used: walked and judged as the stages' standards are
        # so are the other lots it used: each dilution's diluent, internal
        # standard and surrogate, and each matrix blank's blank-matrix lot
        from senaite.pfas import extraction_batch
        from senaite.pfas.browser.bench_inventory import item_index
        members = extraction_batch.load(ws)
        index = item_index(portal)
        more = worksheet_lots.analysis_lots(members, extraction_batch.load_requests(ws),
                                            lambda kind, uid: index.get((kind, uid)))
        more[worksheet_lots.STANDARDS] = worksheet_lots.spike_standards(members) + more[worksheet_lots.STANDARDS]
        for table, rows in sorted(more.items()):
            if rows:
                lb252 = dict(lb252, **{table: list(lb252.get(table) or []) + rows})
        # a lot a stage used out of date with a deviation note is a recorded
        # use, not a finding (_expired_at_use)
        from senaite.pfas import lot_expiry
        from senaite.pfas.extraction_review import done_on as stage_day
        self._use_reasons = lot_expiry.stage_reasons(session, stage_day)
        # The processing stage (sample processing / homogenisation). Its rows were traced
        # NOWHERE: the walk read 252 and 251 only, so a grinder-blade or sorbent
        # lot named here was neither resolved nor reported unresolved, and the
        # balance the samples were WEIGHED on had no calibration chain. Same
        # structural gap as, in the one logbook the walk never learned to
        # read.
        lb253 = _load(u"senaite.pfas.logbook.253")
        reagent_by_lot, ps_by_lot = self._build_lot_indices(portal)

        tree = {
            "direct_reagents":    [],
            "direct_standards":   [],
            "prepared_standards": [],
            # Equipment used during extraction, resolved to registered units and
            # checked for calibration as of the day of use.
            "equipment":          [],
            "unresolved":         [],
            # Reported but not enforced — see _expired_at_use.
            "warnings":           [],
        }
        # a solution a stage prepared at the bench: walked as a standard when
        # the inventory holds its lot; else listed, untraced, with a warning
        for sol in worksheet_lots.solutions(session):
            if sol["lot"] in ps_by_lot or sol["lot"] in reagent_by_lot:
                lb252 = dict(lb252, standards=list(lb252.get("standards") or []) + [
                    {"name": sol["name"], "lot": sol["lot"], "conc": u"", "volume": u""}])
            else:
                tree["direct_standards"].append({"name": sol["name"], "lot": sol["lot"], "resolved": None})
                tree["warnings"].append(u"%s, lot %s, stage %s, is not in the inventory: its parents "
                                        u"are not traced" % (sol["name"], sol["lot"], sol["stage"]))

        # Each logbook's own date, because its rows were used on ITS date.
        use_252 = self._use_date(lb252, "extraction_date")
        use_253 = self._use_date(lb253, "processing_date")
        # Every logbook the walk reads appears here. A logbook left out would skip
        # its expiry check SILENTLY, which is the failure  exists to prevent —
        # an unenforceable check must not look like a satisfied one.
        for lb_name, lb_date, lb in ((self._SOURCE_LABELS["252"], use_252, lb252),
                                     (self._SOURCE_LABELS["253"], use_253, lb253)):
            if not lb_date and self._names_lots(lb):
                tree["warnings"].append(
                    u"%s: no date, so the lots it names cannot be checked "
                    u"for expiry at the time of use" % lb_name)

        # --- extraction record: reagents[] table ---
        # active_rows(): a row struck as not-applicable is recorded but inert.
        # Without this a struck row holding a half-typed lot would be reported
        # as unresolved and would block worksheet release.
        for row in active_rows(lb252.get("reagents")):
            lot  = (row.get("lot") or u"").strip()
            name = row.get("name") or u""
            entry = {
                "name":     name,
                "lot":      lot,
                "supplier": row.get("supplier") or u"",
                "volume":   row.get("volume") or u"",
                "resolved": None,
            }
            if lot and lot in reagent_by_lot:
                entry["resolved"] = self._reagent_dict(reagent_by_lot[lot])
                # The FULL record, not entry["resolved"]: _reagent_dict carries
                # only what the Traceability tab renders (title, url, supplier,
                # cat_number, lot, has_coa) and NO expiry at all, so
                # _effective_expiry returned "" and this check could never fire.
                # Caught by asking it to fail on a use date of 2030 and watching
                # it pass -- the same way the root-URL guard in  was caught.
                reason = self._expired_at_use(
                    self._reagent_record(reagent_by_lot[lot]), lot, name,
                    use_252, portal)
                if reason:
                    tree["unresolved"].append({
                        "source": "252.reagents", "lot": lot, "name": name,
                        "reason": reason,
                    })
                self._flag_pending(tree, reagent_by_lot[lot], u"reagent", "252.reagents", lot, name, use_252)
            elif lot and lot in ps_by_lot:
                entry["resolved"] = self._resolve_prepared(
                    tree, portal, ps_by_lot[lot], "252.reagents", lot, name, use_252)
            elif lot:
                tree["unresolved"].append({
                    "source": "252.reagents", "lot": lot, "name": name,
                    # EVERY unresolved entry carries its own reason, so the
                    # Traceability tab needs no fallback branch and cannot give
                    # the wrong advice. The expiry-at-use entries name a lot
                    # that IS in inventory, and the old blanket message sent the
                    # reviewer to fix something that was not wrong.
                    "reason": u"lot is not in the inventory — enter it to "
                              u"resolve this link",
                })
            tree["direct_reagents"].append(entry)

        # --- extraction record: standards[] table ---
        for row in active_rows(lb252.get("standards")):
            lot  = (row.get("lot") or u"").strip()
            name = row.get("name") or u""
            entry = {
                "name":   name,
                "lot":    lot,
                "conc":   row.get("conc") or u"",
                "volume": row.get("volume") or u"",
                "resolved": None,
            }
            if lot and lot in ps_by_lot:
                ps = ps_by_lot[lot]
                self._flag_pending(tree, ps, u"prepared", "252.standards", lot, name, use_252)
                self._walk_extraction_lot(tree, portal, ps, name, use_252)
                entry["resolved"] = {"title": ps.Title(),
                                     "url": ps.absolute_url(),
                                     "uid": ps.getId(),
                                     "type": "PreparedStandard",
                                     "category": getattr(ps, "standard_type", "") or u""}
            elif lot and lot in reagent_by_lot:
                self._flag_pending(tree, reagent_by_lot[lot], u"reagent", "252.standards", lot, name, use_252)
                entry["resolved"] = self._reagent_dict(reagent_by_lot[lot])
                entry["resolved"]["type"] = "Reagent"
            elif lot:
                tree["unresolved"].append({
                    "source": "252.standards", "lot": lot, "name": name,
                    "reason": u"lot is not in the inventory — enter it to "
                              u"resolve this link",
                })
            if entry["resolved"]:
                # A standards[] row may resolve to either kind, so the record
                # handed over depends on which: a PreparedStandard is judged on
                # its parent-tightened expiry, a Reagent on its full record.
                judged = (entry["resolved"]
                          if entry["resolved"].get("type") == "PreparedStandard"
                          else self._reagent_record(reagent_by_lot.get(lot)))
                reason = self._expired_at_use(judged, lot, name,
                                              use_252, portal)
                if reason:
                    tree["unresolved"].append({
                        "source": "252.standards", "lot": lot, "name": name,
                        "reason": reason,
                    })
            tree["direct_standards"].append(entry)

        # --- extraction record: extraction_materials[] table ---
        # Traced nowhere before: the gate read only reagents[] and
        # standards[], so a cartridge or sorbent lot was neither resolved nor
        # reported unresolved. These consumables touch the extract and belong in
        # the chain.
        for row in active_rows(lb252.get("extraction_materials")):
            lot  = (row.get("lot") or u"").strip()
            name = row.get("name") or u""
            entry = {
                "name":     name,
                "lot":      lot,
                "notes":    row.get("notes") or u"",
                "resolved": None,
            }
            if lot and lot in reagent_by_lot:
                entry["resolved"] = self._reagent_dict(reagent_by_lot[lot])
                reason = self._expired_at_use(
                    self._reagent_record(reagent_by_lot[lot]), lot, name,
                    use_252, portal)
                if reason:
                    tree["unresolved"].append({
                        "source": "252.extraction_materials", "lot": lot,
                        "name": name, "reason": reason,
                    })
                self._flag_pending(tree, reagent_by_lot[lot], u"reagent",
                                   "252.extraction_materials", lot, name, use_252)
            elif lot and lot in ps_by_lot:
                entry["resolved"] = self._resolve_prepared(
                    tree, portal, ps_by_lot[lot], "252.extraction_materials", lot, name, use_252)
            elif lot:
                tree["unresolved"].append({
                    "source": "252.extraction_materials", "lot": lot,
                    "name": name,
                    "reason": u"lot is not in the inventory — enter it to "
                              u"resolve this link",
                })
            tree["direct_reagents"].append(entry)

        # --- processing stage: processing_materials[] table ---
        # Traced nowhere, exactly as extraction_materials was: the
        # rows carry lots, `processing_date` records when they were used, and
        # nothing read either. Grinder blades, dry ice and sorbents touch the
        # sample before extraction, so they belong in the chain.
        #
        # Landed in `direct_reagents` deliberately, the same bucket
        # extraction_materials uses: a separate tree key would have to be rendered
        # separately, and these are the same kind of thing — a consumable lot that
        # must resolve to inventory.
        for row in active_rows(lb253.get("processing_materials")):
            lot, sentinel = lot_or_none(row.get("lot"))
            name = row.get("name") or u""
            entry = {
                "name":     name,
                "lot":      lot,
                "notes":    row.get("notes") or u"",
                "resolved": None,
            }
            if sentinel:
                # The analyst said this material has no lot. Reported, not
                # enforced — see lot_or_none.
                tree["warnings"].append(
                    u"The processing stage records %s with lot \u201c%s\u201d, so it is "
                    u"traced to nothing; strike the row instead if it is genuinely "
                    u"not applicable" % (name or u"a processing material",
                                         sentinel))
            elif lot and lot in reagent_by_lot:
                entry["resolved"] = self._reagent_dict(reagent_by_lot[lot])
                reason = self._expired_at_use(
                    self._reagent_record(reagent_by_lot[lot]), lot, name,
                    use_253, portal)
                if reason:
                    tree["unresolved"].append({
                        "source": "253.processing_materials", "lot": lot,
                        "name": name, "reason": reason,
                    })
                self._flag_pending(tree, reagent_by_lot[lot], u"reagent",
                                   "253.processing_materials", lot, name, use_253)
            elif lot and lot in ps_by_lot:
                entry["resolved"] = self._resolve_prepared(
                    tree, portal, ps_by_lot[lot], "253.processing_materials", lot, name, use_253)
            elif lot:
                tree["unresolved"].append({
                    "source": "253.processing_materials", "lot": lot,
                    "name": name,
                    "reason": u"lot is not in the inventory — enter it to "
                              u"resolve this link",
                })
            tree["direct_reagents"].append(entry)

        # --- processing stage: the balance the samples were WEIGHED on ---
        # 253 records `balance_sn` as free text and nothing resolved it, so the
        # mass every result is calculated from rested on a balance with no
        # calibration chain. Same defect  fixed for the extraction stages'
        # `equipment_sns`, and the same policy is reused rather than a third one
        # invented: an UNREGISTERED serial is a warning (we cannot tell what it
        # owed), a registered unit with no verification for the day is a problem.
        bal_sn = (lb253.get("balance_sn") or u"").strip()
        if bal_sn:
            try:
                from senaite.pfas import facility_qc as _fq253
                entry = {"label": u"Processing stage balance", "serial": bal_sn,
                         "unit": None, "records": [], "problems": [],
                         "warnings": []}
                unit = _fq253.unit_by_serial(bal_sn)
                if unit is None:
                    entry["warnings"].append(
                        u"balance %s is not registered under Equipment, so its "
                        u"calibration on the processing date is unknown" % bal_sn)
                elif not use_253:
                    entry["warnings"].append(
                        u"The processing stage records no date, so balance %s "
                        u"cannot be checked for the day it was used" % bal_sn)
                else:
                    prov = _fq253.equipment_provenance(unit.get("id"), use_253)
                    entry["unit"] = unit
                    entry["records"] = prov.get("records") or []
                    entry["problems"] = prov.get("problems") or []
                    entry["warnings"] = prov.get("warnings") or []
                tree.setdefault("equipment", []).append(entry)
                for prob in entry["problems"]:
                    tree["unresolved"].append({
                        "source": "253.balance_sn", "lot": bal_sn,
                        "name": u"Processing stage balance", "reason": prob,
                    })
                tree["warnings"].extend(entry["warnings"])
            except Exception as exc:                        # noqa: BLE001
                logger.error("253 balance provenance: %s", exc)

        # --- Equipment: serial -> unit -> calibration, as of the day used ---
        # The extraction record captures equipment as free-text SERIAL NUMBERS
        # per stage (`equipment_sns`), and until now they were read only by the
        # PDF: printed, never resolved, never checked. A balance is
        # verified per working day and a pipette on a period, so a mass or volume
        # step performed on a day with no verification has no provenance.
        #
        # The chain ends where the reagent chain does — at someone else's
        # accredited measurement: verification -> weight set -> metrology lab.
        try:
            from senaite.pfas import facility_qc as _fq
            # DUAL READ, worksheet then linked batch — the same order
            # _logbook_json uses and for the same reason: the extraction views
            # historically write to the batch, and a worksheet may carry its own
            # copy. Reading only one place is how §33's seeding reported "saw
            # nothing" for the wrong reason.
            sess = {}
            for holder in (ws, self._linked_batch(ws)):
                if holder is None:
                    continue
                raw_sess = IAnnotations(holder).get(
                    u"senaite.pfas.extraction_session")
                if raw_sess:
                    sess = json.loads(raw_sess)
                    break
            for _order, stage in sorted((sess.get("stages") or {}).items()):
                # The date the equipment was USED, not today -- and not the
                # day a correction was typed (the guide judges the same day)
                from senaite.pfas.extraction_review import done_on
                used_on = done_on(stage)
                for label, serial in (stage.get("equipment_sns") or {}).items():
                    serial = (serial or u"").strip()
                    entry = {"label": label, "serial": serial, "unit": None,
                             "records": [], "problems": [], "warnings": []}
                    if not serial:
                        entry["warnings"].append(
                            u"no serial recorded for %s" % label)
                    else:
                        unit = _fq.unit_by_serial(serial)
                        if unit is None:
                            # WARNING, not a gate failure. An unregistered serial
                            # means we cannot tell whether this equipment owed a
                            # calibration at all — a vortex mixer does not. The
                            # gap is REGISTRATION, and the lab closes it by
                            # registering the unit, at which point enforcement
                            # begins automatically for a balance or pipette.
                            #
                            # Blocking here would have retroactively failed the
                            # already-released WS-0005 on a cryogenic mill.
                            entry["warnings"].append(
                                u"serial %s is not registered under Equipment, so "
                                u"its calibration status is unknown" % serial)
                        else:
                            prov = _fq.equipment_provenance(unit.get("id"),
                                                            used_on)
                            entry["unit"] = unit
                            entry["records"] = prov.get("records") or []
                            entry["problems"] = prov.get("problems") or []
                            entry["warnings"] = prov.get("warnings") or []
                    tree.setdefault("equipment", []).append(entry)
                    # Only an ESTABLISHED unmet obligation blocks release: a
                    # registered balance with no verification for the day it was
                    # used, or a pipette out of calibration. Unknown status is
                    # reported, not enforced.
                    for prob in entry["problems"]:
                        tree["unresolved"].append({
                            "source": "equipment",
                            "lot": serial or label,
                            "name": label,
                            "reason": prob,
                        })
        except Exception as exc:                            # noqa: BLE001
            logger.error("equipment provenance walk: %s", exc)

        # A lot quarantined or used up when the extraction used it: the guide
        # let the stage go ahead only with a deviation note. Shown to
        # the reviewer, not a hold; an expired
        # lot is the one that holds (_expired_at_use above).
        for table in ("reagents", "standards", "extraction_materials"):
            for row in active_rows(lb252.get(table)):
                why = {u"quarantine": u"quarantined", u"exhausted": u"used up"}.get(
                    (row.get("status_at_use") or u"").lower())
                if why and (row.get("lot") or u"").strip():
                    tree["warnings"].append(
                        u"%s lot %s was %s when the extraction used it (see the "
                        u"stage's deviation note)" % (row.get("name") or u"", row["lot"], why))

        # --- The run: the lots the instrument was loaded with (Run Builder) ---
        # Each is walked to full depth (build_parentage) and judged on the run
        # date (parentage_checks): expired, a parent out of date when it was
        # made, a lot that outlives a parent, pending acceptance,
        # quarantined, no storage conditions. An unreviewed preparation record is
        # reported, never a block.
        from senaite.pfas import parentage_checks as pchk
        from senaite.pfas import prep_entries
        from senaite.pfas import run_lots as rl
        from senaite.pfas.browser.prepared_standards import (
            KIND_PREPARED, _obj_to_dict as _psdict, build_parentage,
            equipment_gate_problems, parentage_problems, resolve_loaded)
        from senaite.pfas import send_back as sb
        manifest = self._run_manifest(ws) or {}
        run_day = _lab_day(manifest.get("built_at"))
        if sb.blocks_release(manifest):
            back = manifest["sent_back"]
            tree["unresolved"].append({
                "source": u"run.sent_back", "lot": back.get("lot") or u"",
                "reason": u"sent back %s on %s: %s" % (
                    u"to the Run Builder" if back.get("stage") == sb.RUN else u"to the extraction",
                    _lab_day(back.get("at")), back.get("reason") or u"")})
        # the same rows the batch record's Loaded table prints, each looked
        # up in the inventory once (worksheet_lots.loaded_lots)
        loaded = worksheet_lots.loaded_lots(manifest, lambda snap: resolve_loaded(portal, snap))
        if manifest and not loaded:
            tree["warnings"].append(u"The run records no lots loaded on the instrument (Run Builder).")
        try:
            entries = prep_entries.load(portal)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("preparation records unreadable: %s", exc)
            entries = {}
        warned = set()
        for row in loaded:
            display_label, snap, lot_ref = row["label"], row["snap"], row["lot"]
            # kind: what the run recorded when the lot was loaded, replaced
            # below by what the inventory holds once the lot is found
            ps_node = {"field": u"run", "label": display_label, "lot": lot_ref,
                       "title": snap.get("name") or u"", "prepared_date": u"", "prepared_by": u"",
                       "expiry_date": snap.get("expiry") or u"", "url": u"", "found": False,
                       "kind": row["kind"], "parent_reagents": [], "parentage": []}
            tree["prepared_standards"].append(ps_node)
            obj, kind = row["obj"], row["inventory_kind"]
            if obj is None:
                tree["unresolved"].append({"source": u"run", "lot": lot_ref, "label": display_label,
                                           "reason": u"the lot loaded is not in the inventory"})
                continue
            ps_node.update(found=True, title=obj.Title(), url=obj.absolute_url(),
                           kind=rl.PREPARED if kind == KIND_PREPARED else rl.REAGENT)
            if kind == KIND_PREPARED:
                rec = _psdict(obj)
                ps_node.update(prepared_date=str(rec.get("prepared_date") or "")[:10],
                               prepared_by=rec.get("prepared_by") or u"",
                               expiry_date=str(rec.get("expiry_date") or "")[:10],
                               category=rec.get("standard_type") or u"")
                try:
                    ps_node["parentage"] = build_parentage(portal, rec)
                    for prob in parentage_problems(ps_node["parentage"]):
                        tree["unresolved"].append({"source": "prepstd.parentage", "lot": prob.get("lot"),
                                                   "name": prob.get("name"), "reason": prob.get("reason")})
                    # the equipment the lot was made with, as of its preparation
                    for prob in equipment_gate_problems(portal, rec):
                        tree["unresolved"].append(dict(prob, source="prepstd.equipment"))
                except Exception as exc:                    # noqa: BLE001
                    logger.error("parentage walk for %s: %s", lot_ref, exc)
                    tree["unresolved"].append({"source": "prepstd.parentage", "lot": lot_ref,
                                               "name": ps_node["title"],
                                               "reason": u"parentage could not be resolved (%s)" % exc})
                root = {"kind": KIND_PREPARED, "lot": lot_ref, "name": ps_node["title"], "uid": obj.getId(),
                        "expiry": ps_node["expiry_date"], "prepared_date": ps_node["prepared_date"],
                        "status": rec.get("status") or u"", "entry_id": rec.get("entry_id") or u"",
                        "storage_conditions": rec.get("storage_conditions") or u"",
                        "extensions": rec.get("extensions") or [],
                        "children": ps_node["parentage"]}
            else:
                # a purchased solvent loaded straight on the LC
                from senaite.pfas.browser.reagents import (
                    _obj_to_dict as _rd, _base_expiry, _effective_expiry, get_expiry_defaults)
                rd = _rd(obj)
                ps_node["expiry_date"] = _effective_expiry(rd, get_expiry_defaults(portal))
                ps_node["category"] = rd.get("category") or u""
                root = {"kind": kind, "lot": lot_ref, "name": ps_node["title"], "uid": obj.getId(),
                        "expiry": ps_node["expiry_date"], "status": rd.get("status") or u"",
                        "expiry_base": _base_expiry(rd, get_expiry_defaults(portal)),
                        "extensions": rd.get("extensions") or [], "no_expiry": bool(rd.get("no_expiry")),
                        "storage_conditions": rd.get("storage_conditions") or u"", "children": []}
            ps_node["parent_reagents"] = [
                {"name": n.get("name") or u"", "lot": n.get("lot") or u"",
                 "expiry": n.get("expiry") or u"",
                 "resolved": n.get("kind") != u"unresolved" or None}
                for n in root["children"]]
            for p in pchk.walk_problems([root], run_day):
                tree["unresolved"].append({"source": u"run.parentage", "lot": p["lot"], "name": p["name"],
                                           "label": display_label, "reason": p["reason"],
                                           "pending": p["pending"], "uid": p["uid"], "kind": p["kind"]})
            for eid in self._entry_ids([root]):
                if eid in warned:
                    continue
                warned.add(eid)
                rec = entries.get(eid) or {}
                code = (rec.get("recipe") or {}).get("code")
                if not rec.get("reviewed_by"):
                    tree["warnings"].append(u"%s: preparation record %s not reviewed" % (
                        display_label, u"%s \u00b7 %s" % (code, eid) if code else eid))
        # the run's last injection after a solvent lot expired (after import)
        for late in rl.late_injections(self._run_date(ws), manifest.get("solvents")):
            tree["unresolved"].append({"source": u"run.solvents", "lot": late["lot"],
                                       "label": u"LC %s" % late["channel"], "reason": late["reason"]})

        return tree

    def _resolve_prepared(self, tree, portal, ps, source, lot, name, use_date):
        """A lot a reagent or material row names that is an in-house prepared
        lot: resolved to its prepared standard, judged on its expiry and
        walked to its parents, as a standards row is."""
        self._flag_pending(tree, ps, u"prepared", source, lot, name, use_date)
        self._walk_extraction_lot(tree, portal, ps, name, use_date)
        resolved = {"title": ps.Title(), "url": ps.absolute_url(),
                    "uid": ps.getId(), "type": "PreparedStandard",
                    "category": getattr(ps, "standard_type", "") or u""}
        reason = self._expired_at_use(resolved, lot, name, use_date, portal)
        if reason:
            tree["unresolved"].append({"source": source, "lot": lot,
                                       "name": name, "reason": reason})
        return resolved

    @staticmethod
    def _walk_extraction_lot(tree, portal, ps, label, use_date):
        """A prepared lot the extraction used, walked to full depth as the
        run's are (parentage_checks.walk_below: its own expiry and status
        are judged above)."""
        from senaite.pfas import parentage_checks as pchk
        from senaite.pfas.browser.prepared_standards import (
            KIND_PREPARED, _obj_to_dict as _psdict, build_parentage)
        try:
            rec = _psdict(ps)
            root = {"kind": KIND_PREPARED, "lot": rec.get("lot_number") or u"", "name": ps.Title(),
                    "uid": ps.getId(), "expiry": str(rec.get("expiry_date") or "")[:10],
                    "prepared_date": str(rec.get("prepared_date") or "")[:10],
                    "status": rec.get("status") or u"",
                    "storage_conditions": rec.get("storage_conditions") or u"",
                    "extensions": rec.get("extensions") or [],
                    "children": build_parentage(portal, rec)}
        except Exception as exc:                            # noqa: BLE001
            logger.error("parentage walk for %s: %s", ps.getId(), exc)
            tree["unresolved"].append({"source": u"252.parentage", "lot": ps.getId(), "name": label,
                                       "reason": u"parentage could not be resolved (%s)" % exc})
            return
        for p in pchk.walk_below(root, use_date):
            tree["unresolved"].append({"source": u"252.parentage", "lot": p["lot"], "name": p["name"],
                                       "label": label, "reason": p["reason"], "pending": p["pending"],
                                       "uid": p["uid"], "kind": p["kind"]})

    @staticmethod
    def _flag_pending(tree, obj, kind, source, lot, name, used_on=u""):
        """A lot the extraction used that is pending acceptance: release
        waits for the reviewer to approve it, or reject it and send the run
        back (send_back.py). One rejected at review after it was used holds
        release until the record no longer names it, so a rebuild alone never
        clears a rejection (one quarantined before it was picked is a
        warning, with the stage's deviation note)."""
        status = getattr(obj, "status", None)
        if status == u"pending":
            tree["unresolved"].append({"source": source, "lot": lot, "name": name,
                                       "reason": u"pending acceptance", "pending": True,
                                       "uid": obj.getId(), "kind": kind})
        elif status == u"quarantine" and _rejected_after(obj, used_on):
            tree["unresolved"].append({"source": source, "lot": lot, "name": name,
                                       "reason": u"rejected after use"})

    def _entry_ids(self, nodes):
        """Every preparation record named in a parentage tree, depth-first."""
        out = []
        for n in nodes or []:
            if n.get("entry_id"):
                out.append(n["entry_id"])
            out.extend(self._entry_ids(n.get("children")))
        return out

    def get_traceability_tree(self):
        ws = self._get_worksheet()
        if not ws:
            return {"direct_reagents": [], "direct_standards": [], "prepared_standards": [], "unresolved": []}
        try:
            return self._build_traceability_tree(ws)
        except Exception as exc:
            logger.error("get_traceability_tree: %s", exc)
            return {"error": str(exc), "direct_reagents": [], "direct_standards": [], "prepared_standards": [], "unresolved": []}

    # ── QC Summary ────────────────────────────────────────────────────────

    def _get_qc_summary(self, ws):
        """The worksheet's QC Summary -- built once per request.

        The gate's status, its verdict, the warnings strip and the QC tab
        each ask for it, and each build judges every QC row (sample results
        for every failing one): three builds were nearly all of a raw run's
        page time. Keyed by the worksheet. Every caller gets the one shared
        dict and only reads it; a caller that must change it copies it
        first. The template's summary (get_qc_summary) is a copy of its own.
        Saving the checklist drops it."""
        memo = getattr(self, "_qc_summary_memo", None)
        if memo is None:
            memo = self._qc_summary_memo = {}
        key = ws.getId()
        if key not in memo:
            out = self._get_qc_summary_uncached(ws)
            if not out.get("error"):
                # the summary's overall verdict is the gate's one reading: a
                # required QC type not run holds it, a study's own replicates
                # do not
                out["overall_pass"] = not self._gate_holds(self._qc_gate(out))
            memo[key] = out
        return memo[key]

    def _get_qc_summary_uncached(self, ws):
        if not self.db_available:
            return {"error": "db_unavailable", "rows": [], "qc_types": [], "overall_pass": False}

        batch_id = ws.getId()
        store = self._store()

        batch_row = None
        try:
            batch_row = store.get_batch(batch_id)
        except Exception as exc:
            logger.error("_get_qc_summary.get_batch: %s", exc)

        if batch_row is None:
            # Fallback: try UID
            try:
                batch_row = store.get_batch(ws.UID())
            except Exception:
                pass

        if not batch_row:
            return {
                "error": "no_batch_record",
                "rows": [], "qc_types": [], "overall_pass": False,
                "batch_id": batch_id,
            }

        run_date = batch_row["run_date"] if hasattr(batch_row, "__getitem__") else batch_row.get("run_date", "")

        try:
            # EVERY qc_type the worker stored for this run. A hand-copied list
            # dropped what it forgot: solvent blanks (CCB) and the surrogate
            # and QC-store gaps never reached the gate.
            # THIS worksheet's run only. By run date alone, two worksheets
            # run the same day (another method, another instrument) shared
            # one QC Summary, and each one's release gate was judged on the
            # other's QC too (an EPA 1633A worksheet's summary held an FDA
            # worksheet's rows).
            batch_key = (batch_row["batch_id"] if hasattr(batch_row, "__getitem__")
                         else batch_row.get("batch_id")) or batch_id
            qc_results = list(store.get_qc_for_run(
                run_date,
                batch_id=batch_key,
            ))
        except Exception as exc:
            logger.error("_get_qc_summary.get_qc_for_run: %s", exc)
            return {"error": "db_error", "rows": [], "qc_types": [], "overall_pass": False}

        # Load method profile acceptance limits
        qc_acceptance = {}
        method_id = self.batch_method()
        if method_id:
            try:
                qc_acceptance = self._method_profile().get("qc_acceptance", {})
            except Exception as exc:
                logger.warning("_get_qc_summary.get_profile: %s", exc)

        qc_results += self._injection_qc_rows(batch_key)
        # a recovery is judged and shown at the method's decimal places; a run
        # that recorded the places its checks judged at is shown at those, so a
        # value never sits beside a verdict reached at other places
        places = self._recovery_places(batch_key, method_id)
        out = self._build_qc_matrix(qc_results, qc_acceptance, run_date, ws=ws, places=places,
                                    rule=self._rounding_rule() if places else None,
                                    row_name=self._qc_row_namer())
        if not out.get("result_count"):
            # a run on record with no QC row at all is a lost write, never a
            # pass (an empty matrix read overall_pass=True)
            return {"error": u"no QC results are stored for this run; reprocess it",
                    "rows": [], "qc_types": [], "overall_pass": False,
                    "batch_id": batch_key}
        # each failing rule whose flag carries a code: that code at its
        # place, in place of the library's (rule_flags)
        out["qualifiers"] = self._flag_qualifiers(out.get("qualifiers") or [], qc_results, batch_key)
        # an Evaluate failure: shown in Data Review, marked not printed
        out["advisories"] = self._flag_advisories(qc_results)
        # a sample received out of compliance with its method: every result
        # of that sample (receipt_compliance)
        # and each result the worker marked (a re-spiked dilution, peaks
        # split or fitted) under its entry's code; one its entry cannot
        # qualify holds the release gate, with why
        marked, holds = self._marked_qualifiers(ws)
        out["qualifiers"] = (list(out.get("qualifiers") or []) + self._receipt_qualifiers(ws) + marked)
        out["qualifier_holds"] = holds
        return out

    def _sample_results_for(self, ws, keyword, applies_to=u""):
        """[{"keyword", "nondetect", "below_rl", "undecidable"}] for the
        worksheet's sample analyses of one analyte that a QC row covers,
        skipping the
        samples the LIMS itself records as QC: a SENAITE reference analysis,
        or a sample the worksheet's QC assignment (extraction_batch) gives a
        QC role. A matrix spike is always detected. A sample it records as
        a field sample counts; one it records nothing (or an unknown role)
        for counts too, and its non-detect is "undecidable", which never
        releases. A sample's ids are never read for its role.
        `applies_to` is the row's own scope (a matrix spike's parent); empty
        covers every sample of the run. Both are the certificate's own row
        (coa_format.build_rows: its RL and MDL, scaled by a dilution's fold):
        non-detect is a result it prints as not detected; below_rl is one it
        prints below its reporting limit, a non-detect or a J value (a J
        value is detected)."""
        from senaite.pfas import coa_format, extraction_batch, report_limits
        from senaite.pfas.browser.dilution_retests import dilution_fold
        from senaite.pfas.print_settings import get_print_settings
        from senaite.pfas.qc_qualification import applies_to_sample
        from senaite.pfas.report_templates import (
            certificate_format, issued_snapshot)
        qc_roles = set(r.upper() for r in extraction_batch.QC_ROLES)
        # the worksheet's QC assignment, the issued template and the print
        # settings: read once per request (asked once per failing QC row),
        # and only read here. An assignment that cannot be read leaves
        # every answer unknown.
        inputs = getattr(self, "_sample_inputs", None)
        if inputs is None or inputs[0] != ws.getId():
            try:
                roles = dict((m.get("sample_uid"), (m.get("role") or u"").strip())
                             for m in (extraction_batch.load(ws) or []) if m.get("sample_uid"))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("sample roles for %s: %s", keyword, exc)
                roles = None
            snap = live = None
            if roles is not None:
                snap, _rev = issued_snapshot(self._portal())
                live = get_print_settings(self._portal()) if snap is None else {}
            inputs = self._sample_inputs = (ws.getId(), roles, snap, live)
        _ws_id, roles, snap, live = inputs
        if roles is None:
            return []                                       # unknown: holds
        profile = self._method_profile() or {}
        method_id = self.batch_method()
        pushed = {}
        if applies_to:
            # where the worker wrote each injection's results: the link that
            # holds when injections are named otherwise than the samples
            try:
                for p in self._result_pushes(ws.getId()):
                    if p.get("injection") and p.get("sample_uid"):
                        pushed.setdefault(p["injection"], set()).add(p["sample_uid"])
            except Exception as exc:                        # noqa: BLE001
                logger.warning("sample results scope for %s: %s", keyword, exc)
                return []                                   # unknown: holds
        # the worksheet's analyses by keyword, in worksheet order: walked
        # once per request (asked once per failing QC row). An analysis
        # whose keyword cannot be read leaves every answer unknown.
        index = getattr(self, "_analyses_index", None)
        if index is None or index[0] != ws.getId():
            analyses, by_keyword = ws.getAnalyses() or [], {}
            try:
                for analysis in analyses:
                    by_keyword.setdefault(analysis.getKeyword(), []).append(analysis)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("worksheet analyses by keyword: %s", exc)
                by_keyword = None
            index = self._analyses_index = (ws.getId(), by_keyword)
        if index[1] is None:
            return []                                       # unknown: holds
        out = []
        for analysis in index[1].get(keyword, ()):
            try:
                if getattr(analysis, "portal_type", u"") == "ReferenceAnalysis":
                    continue                                # SENAITE's own QC
                sample = analysis.getRequest()
                names = (sample.getId(), sample.getClientSampleID())
                role = roles.get(sample.UID(), u"")
                if role.upper() in qc_roles:
                    continue
                if not applies_to_sample(applies_to, sample.UID(), names, pushed):
                    continue
                matrix = report_limits.canonical_matrix(
                    profile, sample.getSampleTypeTitle())
                # judged as the certificate prints this sample's row
                merged, _fmt = certificate_format(snap, method_id, profile, matrix, live)
                # its run's acid-basis analytes; unknown, the salt factor applies, as in the worker
                try:
                    from senaite.pfas.browser.run_builder import analysis_acid_basis
                    acid = analysis_acid_basis(analysis, self.__dict__.setdefault("_acid_basis_cache", {}))
                except Exception as exc:                    # noqa: BLE001
                    logger.warning("acid basis for %s: %s", keyword, exc)
                    acid = []
                from senaite.pfas.above_range import of as above_range_of
                res = coa_format.build_rows(
                    [{"keyword": keyword, "result": analysis.getResult(),
                      "dilution": dilution_fold(analysis),
                      "above": (above_range_of(analysis) or {}).get("limit"),
                      "acid_basis": keyword.upper() in [a.upper() for a in acid]}], profile, matrix, merged)[0]
            except Exception as exc:                        # noqa: BLE001
                logger.warning("sample result for %s: %s", keyword, exc)
                return []                                   # unknown: holds
            out.append({"keyword": keyword, "nondetect": res["detected"] is False,
                        "below_rl": res["detected"] is False or bool(res["estimated"]),
                        "undecidable": role != u"Sample"})
        return out

    def _qc_row_namer(self):
        """name -> the name the QC Summary's row goes by
        (compound_library.listed_namer over the method's analytes and its
        isotope standards); the name as stored when the library cannot be
        read."""
        try:
            from senaite.pfas import compound_library, compound_library_store
            profile = self._method_profile() or {}
            listed = list(profile.get("master_analyte_set") or []) + sorted(
                (profile.get("labelled_standards") or {}).keys()
                if isinstance(profile.get("labelled_standards"), dict) else [])
            return compound_library.listed_namer(compound_library_store.library(), listed)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("QC Summary analyte names not resolved: %s", exc)
            return lambda name: name or u""

    def _build_qc_matrix(self, qc_results, qc_acceptance, run_date="", ws=None, places=0, rule=None,
                         row_name=None):
        """Group QC results into analyte x qc_type matrix with pass/warn/fail.
        `row_name(name)`: the name a result's row goes by (_qc_row_namer);
        the name as stored without it.

        An Evaluate (advisory) failure is a warning and never blocks. A
        failure biased high on an analyte that is a non-detect in every
        sample of ws is qualified with a note instead of failing."""
        by_analyte = {}
        qc_type_set = []
        # a sample's result above the calibration range with no dilution
        from senaite.pfas.above_range import QC_TYPE as above_range_type
        # and one the instrument wrote BLoQ with no number
        from senaite.pfas.no_number import QC_TYPE as no_number_type
        # one row per analyte, named as the method's analyte list names it,
        # whatever spelling a check stored its result under
        row_name = row_name or (lambda name: name)

        for r in qc_results:
            if r.get("result_status") == "voided":
                continue
            analyte  = row_name(r.get("analyte", "") or "")
            qc_type  = r.get("qc_type", "") or ""
            if not analyte and (r.get("result_status") == "unevaluated"
                                or not r.get("passed", 1)):
                # a gap or a FAILURE about the whole run (a matrix spike not
                # judged, a run not closed by a CCV): dropped for having no
                # analyte, it never held the release it was filed to hold
                analyte = u"(whole run)"
            if not analyte or not qc_type:
                continue

            if qc_type not in qc_type_set:
                qc_type_set.append(qc_type)
            if analyte not in by_analyte:
                by_analyte[analyte] = {}
            if qc_type not in by_analyte[analyte]:
                by_analyte[analyte][qc_type] = []
            by_analyte[analyte][qc_type].append(r)

        overall_pass = True
        # Qualifiers applied to released-but-failing results, and prompts for
        # failures the QAO has not mapped. Both are surfaced: a qualified
        # release must be visible, and an unmapped one must be actionable.
        qualifiers = []
        unmapped_prompts = []
        rows = []
        for analyte in sorted(by_analyte.keys()):
            cells = {}
            for qc_type in qc_type_set:
                recs = by_analyte[analyte].get(qc_type, [])
                if not recs:
                    cells[qc_type] = None
                    continue

                # For non-MB types: compute recovery
                cell_status = "ok"
                cell_note = u""
                # why a cell was not judged: a criterion never set, or a
                # failure no qualifier is mapped for (its library label)
                unjudged, unmapped = False, u""
                values = []
                for rec in recs:
                    passed = bool(rec.get("passed", 1))
                    val    = rec.get("value")
                    exp    = rec.get("expected_value")
                    recovery = None
                    if qc_type != "MB" and val is not None and exp:
                        # shown as the checks judge it: the method's
                        # decimal places for recoveries by its rule
                        from senaite.pfas import recovery as _recovery
                        recovery = _recovery.recovery_pct(
                            {"value": val, "expected_value": exp}, self._rounding_rule(), places)

                    if rec.get("result_status") == "unevaluated":
                        # A criterion the method never configured. Distinct
                        # from a failure -- nothing was judged -- and it must
                        # hold the report rather than read as a pass. A cell
                        # with a failure among its records stays failed.
                        if cell_status != "fail":
                            cell_status = "unevaluated"
                        unjudged = True
                        overall_pass = False
                    elif not passed and qc_type == above_range_type:
                        # a sample's result above the calibration range with
                        # no dilution: held until the reviewer records the
                        # reason to report it with E. Never qualified by the
                        # library: the reason is the reviewer's, per result
                        # (a dilution, once run, files no such row)
                        why = self.above_range_reason(rec.get("applies_to"), rec.get("analyte"))
                        if why:
                            if cell_status in ("ok", "warn"):
                                cell_status = "qualified"
                            cell_note = u"Reported with E: %s" % why.get("reason")
                        else:
                            cell_status = "fail"
                            overall_pass = False
                    elif not passed and qc_type == no_number_type:
                        # a sample's result the instrument wrote BLoQ with no
                        # number: held until the reviewer records the reason
                        # to report it, never reported not detected silently
                        why = self.no_number_reason(rec.get("applies_to"), rec.get("analyte"))
                        if why:
                            if cell_status in ("ok", "warn"):
                                cell_status = "qualified"
                            cell_note = u"Reported without a number: %s" % why.get("reason")
                        else:
                            cell_status = "fail"
                            overall_pass = False
                    elif not passed and rec.get("advisory"):
                        # an Evaluate rule: shown, never blocking
                        if cell_status == "ok":
                            cell_status = "warn"
                    elif not passed:
                        # A failure the QAO's library says may be released is
                        # QUALIFIED, not a block: the result goes out with a
                        # code and a statement on the certificate. A recovery
                        # check (a calibration verification or a spike) whose
                        # recovery is biased high on an analyte that is a
                        # non-detect in every sample is qualified with a
                        # note, judged on the recovery as shown here. Control
                        # material is otherwise never qualifiable by the
                        # library (disposition_for blocks it).
                        qual = self._qualify_failure(qc_type, rec.get("analyte"))
                        note = hb = None
                        if ws is not None:
                            from senaite.pfas.qc_qualification import high_bias_release
                            from senaite.pfas.rounding import judged_pct
                            rule = self._rounding_rule()
                            # a recovery judged at the method's decimal places
                            note = high_bias_release(
                                rec, self._sample_results_for(
                                    ws, rec.get("analyte"),
                                    applies_to=rec.get("applies_to") or u""),
                                judged=lambda pct: judged_pct(pct, rule, places))
                            # released under the library's entry: held while
                            # the QAO holds it (None), asked for while it has
                            # no code or wording
                            hb = self._high_bias_qualifier() if note else None
                            if note and hb is None:
                                note = None
                            elif note and hb.get("needs_config"):
                                note, qual = None, hb
                        if note:
                            from senaite.pfas.qc_qualification import high_bias_note
                            note = high_bias_note(hb.get("statement"), qc_type)
                            if cell_status in ("ok", "warn"):
                                cell_status = "qualified"
                            cell_note = note
                            qualifiers.append({
                                "qc_type": qc_type,
                                "applies_to": rec.get("applies_to") or u"",
                                "reason": note,
                                "analyte": rec.get("analyte") or u"",
                                "code": hb.get("code") or u"",
                                "statement": note,
                            })
                        elif qual and not qual.get("needs_config"):
                            if cell_status in ("ok", "warn"):
                                cell_status = "qualified"
                            # The NATIVES the failure actually affects, not the
                            # compound the failure was recorded against. A
                            # surrogate failure is recorded on 13C2-PFHxDA; the
                            # client's certificate is about PFHxDA. Listing the
                            # labelled compound would name something that does
                            # not appear in the results table at all.
                            for affected in self._affected_analytes(
                                    qual.get("failure_type"),
                                    rec.get("analyte") or u""):
                                qualifiers.append({
                                    "qc_type": qc_type,
                                    "applies_to": rec.get("applies_to") or u"",
                                    "reason": rec.get("flag") or u"",
                                    "analyte": affected,
                                    "code": qual.get("code") or u"",
                                    "statement": qual.get("statement") or u"",
                                    # the library entry and the compound the
                                    # failure was recorded on: what a rule's
                                    # flag replaces it by (rule_flags.replaced)
                                    "failure": qual.get("failure_type") or u"",
                                    "source": rec.get("analyte") or u"",
                                })
                        elif qual and qual.get("needs_config"):
                            if cell_status != "fail":
                                cell_status = "unevaluated"
                            overall_pass = False
                            unmapped = qual.get("label") or qc_type
                            unmapped_prompts.append(qual.get("prompt") or u"")
                        else:
                            cell_status = "fail"
                            overall_pass = False
                    elif rec.get("result_status") == "flagged_reanalysis":
                        if cell_status == "ok":
                            cell_status = "warn"

                    values.append({
                        "value": val,
                        "expected": exp,
                        "recovery": recovery,
                        "passed": passed,
                        "flag": rec.get("flag") or u"",
                        # the window and rule it was judged by (the worker's)
                        "limit_low": rec.get("limit_low"),
                        "limit_high": rec.get("limit_high"),
                        "limit_basis": rec.get("limit_basis") or u"",
                        "units": rec.get("units") or u"",
                        # a precision: a pair's RPD, or the RSD of several spikes
                        "kind": u"RPD" if (rec.get("qc_level") or u"").split(u" ")[0] in (u"RPD", u"RSD") else u"",
                        # the value's provenance record (the drawer)
                        "prov_key": rec.get("prov_key") or u"",
                    })

                cells[qc_type] = {
                    "status": cell_status,
                    "badge":  "PASS" if cell_status == "ok" else cell_status.upper(),
                    "n":      len(values),
                    "values": values,
                }
                if cell_note:
                    cells[qc_type]["note"] = cell_note
                if unjudged:
                    cells[qc_type]["unjudged"] = True
                if unmapped:
                    cells[qc_type]["unmapped"] = unmapped

            rows.append({"analyte": analyte, "cells": cells})

        # A whole-run flag still holds the gate (overall_pass above) but is
        # not an analyte: it leaves the table for the warnings box.
        run_flags = []
        for row in [r for r in rows if r["analyte"] == u"(whole run)"]:
            for qt in qc_type_set:
                c = row["cells"].get(qt)
                if c and c["status"] != "ok":
                    # each reason once, however many records state it
                    said = []
                    for v in c["values"]:
                        if v["flag"] and v["flag"] not in said:
                            said.append(v["flag"])
                    run_flags.append({"qc_type": qt, "status": c["status"], "flags": said,
                                      "unjudged": bool(c.get("unjudged")),
                                      "unmapped": c.get("unmapped") or u""})
        rows = [r for r in rows if r["analyte"] != u"(whole run)"]

        # what each cell shows: the value, coloured by its verdict, and the
        # criteria cited once per column (qc_cells)
        # a recovery shows `places`, the method's decimal places for
        # recoveries, by its `rule` (display only)
        from senaite.pfas import qc_cells
        display_cols, col_values = [], {}
        for row in rows:
            row["display"] = {}
            for qt in qc_type_set:
                c = row["cells"].get(qt)
                if not c:
                    continue
                for key, vals in qc_cells.split(qt, c["values"]):
                    row["display"][key] = qc_cells.cell_display(
                        qt, vals, qc_cells.sub_status(c["status"], vals), places, rule)
                    if key not in display_cols:
                        display_cols.append(key)
                    col_values.setdefault(key, []).extend(vals)
        # extracted QC first, then the instrument's; within each, the QC
        # types' order, a split column after its own
        display_cols.sort(key=qc_cells.column_order)
        shown = qc_cells.tables(
            [{"key": key, "unit": qc_cells.column_unit(key.split(" ")[0], col_values[key])}
             for key in display_cols], rows)

        return {
            "qc_types":    qc_type_set,
            "columns":     shown["columns"],
            "notes":       shown["notes"],
            "groups":      shown["groups"],
            "rows":        rows,
            "overall_pass": overall_pass,
            "qualifiers":  qualifiers,
            "unmapped":    unmapped_prompts,
            "run_flags":   run_flags,
            "result_count": sum(len(by_analyte[a].get(qt, []) or []) for a in by_analyte for qt in qc_type_set),
            "run_date":    run_date,
        }

    def get_qc_summary(self, shared=False):
        """The worksheet's QC Summary: a copy of the request's one (the
        template's, and another view's), or with `shared` the request's own
        dict, for a reader in this view that never changes it."""
        import copy
        ws = self._get_worksheet()
        if not ws:
            return {"error": "no_worksheet", "rows": [], "qc_types": [], "overall_pass": False}
        try:
            summary = self._get_qc_summary(ws)
            return summary if shared else copy.deepcopy(summary)
        except Exception as exc:
            logger.error("get_qc_summary: %s", exc)
            return {"error": str(exc), "rows": [], "qc_types": [], "overall_pass": False}

    # ── Accreditation / non-conformance disclosure ────────────────────────

    def accreditation_disclosure(self):
        """What this worksheet's certificate will say about accreditation, or
        None when there is nothing to show.

        The timing here is the whole difficulty, and getting it wrong would
        recreate The criteria are frozen AT verification, so a
        reviewer about to approve does not have a frozen record yet — only what
        resolution says right now. Those are different claims and the caller
        must never conflate them, so the mode is explicit:

          "recorded"     the worksheet is verified and a snapshot exists. This
                         IS what governed the results. Authoritative.
          "preview"      the worksheet is not verified yet. This is what WOULD
                         be recorded if it were approved now, and it may still
                         change. Never presented as the record.
          "not_recorded" the worksheet IS verified and no snapshot exists —
                         every worksheet verified before the freeze existed.
                         Deliberately NOT a preview: resolving live here and
                         showing it would describe what the lab would do now as
                         though it were what the lab did.

        Once per request: the strip asks for it and for its lines
        (disclosure_lines), and a preview resolves every criterion.
        """
        if not hasattr(self, "_accred_disclosure"):
            self._accred_disclosure = self._accreditation_disclosure_uncached()
        return self._accred_disclosure

    def _accreditation_disclosure_uncached(self):
        ws = self._get_worksheet()
        if ws is None:
            return None
        from senaite.pfas import disclosure
        from senaite.pfas import worksheet_criteria_snapshot as wcs

        verified = self.ws_state() == "verified"
        try:
            frozen = wcs.get_frozen_criteria(ws)
        except Exception as exc:
            logger.error("accreditation_disclosure: reading the snapshot for "
                         "%s raised: %s", ws.getId(), exc)
            frozen = None

        if frozen:
            out = disclosure.build_disclosure(frozen)
            out["mode"] = u"recorded"
            return out

        if verified:
            # No snapshot, but the judgement already happened. Say so; do NOT
            # substitute live criteria.
            out = disclosure.build_disclosure(None)
            out["mode"] = u"not_recorded"
            return out

        # Not verified yet — show what would be recorded, clearly labelled.
        try:
            from senaite.pfas import resolved_criteria_store as rcs
            rows = rcs.resolve_rows_for_batch(
                self._portal(), self._linked_batch(ws),
                self.batch_method(), self._batch_matrix())
            payload = wcs.build_snapshot_payload(
                self.batch_id(), self.batch_method(), self._batch_matrix(),
                rows)
            out = disclosure.build_disclosure(payload)
        except Exception as exc:
            logger.error("accreditation_disclosure: preview resolution for %s "
                         "raised: %s", ws.getId(), exc)
            out = disclosure.build_disclosure(None)
        out["mode"] = u"preview"
        return out

    def disclosure_lines(self):
        """The itemised departures as human-readable lines, or []."""
        d = self.accreditation_disclosure() or {}
        try:
            from senaite.pfas import disclosure
            return [disclosure.format_departure(i) for i in d.get("items") or []]
        except Exception as exc:
            logger.error("disclosure_lines: %s", exc)
            return []

    # ── Final Data Summary ────────────────────────────────────────────────

    def qualifier_meanings(self):
        """{qualifier: what it means} from the client's EDD profile's map:
        a qualifier explains itself on hover (no legend)."""
        return dict((q.get("our_qualifier"), q.get("description") or u"") for q in self.qualifier_legend() or [])

    def instrument_unit(self):
        """The unit the instrument's results are in: the method's calibration
        unit (ng/mL in the extract), or the matrix's unit when the levels
        state the concentration in the sample."""
        try:
            from senaite.pfas.calibration_levels import unit, EXTRACT
            profile = self._method_profile() or {}
            u = unit(profile)
            if u == EXTRACT:
                return u
            return (profile.get("unit_map") or {}).get(self._batch_matrix()) or u
        except Exception:                                   # noqa: BLE001
            return u""

    def qualifier_legend(self):
        """The qualifier vocabulary the worksheet's results are exported
        with: its client's EDD profile's map (single source, edited under
        EDD Export), NOT hardcoded here. The legend under the Final Data
        table."""
        try:
            from senaite.pfas import edd_store
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            client = None
            ws = self._get_worksheet()
            for a in (ws.getAnalyses() if ws is not None else []) or []:
                try:
                    client = a.getRequest().getClient()
                    break
                except Exception:                           # noqa: BLE001
                    continue
            cfg = edd_store.get_client_settings(client) if client is not None else {}
            prof = edd_store.get_edd_profile_for_client(portal, cfg)[1]
            return [dict(r, profile=prof.get("name", u"")) for r in
                    (edd_store.section(prof, "qualifier_map") or [])]
        except Exception as exc:
            logger.warning("qualifier_legend: %s", exc)
            return []

    def result_checks(self):
        """Core results against the method panel and the worker's push log
        (result_checks.py). Flags, never a gate."""
        if hasattr(self, "_result_checks"):
            return self._result_checks
        empty = {"pushes_recorded": False, "not_written": [], "not_judged": [], "panel": []}
        ws = self._get_worksheet()
        if ws is None:
            self._result_checks = empty
            return empty
        try:
            from bika.lims import api as _api
            from senaite.pfas import report_format, rounding
            from senaite.pfas import result_checks as rc
            from senaite.pfas.method_bridge import get_core_method
            from senaite.pfas.method_profile_store import get_profile, get_included_analytes, service_index
            from senaite.pfas.report_limits import canonical_matrix
            from senaite.pfas.sample_method import EXCLUDED_STATES, project_added
            portal = _api.get_portal()
            mid = self.batch_method()
            profile = get_profile(portal, mid) if mid else {}
            core_method = get_core_method(portal, mid) if mid else None
            roles = service_index()
            by_sample = {}
            for an in ws.getAnalyses() or []:
                if roles.get(an.getKeyword(), {}).get("role") != u"analyte":
                    continue
                if _api.get_review_status(an) in EXCLUDED_STATES or an.getHidden():
                    continue
                sample = an.getRequest()
                rec = by_sample.get(sample.UID())
                if rec is None:
                    matrix = canonical_matrix(profile, sample.getSampleTypeTitle())
                    panel = (get_included_analytes(portal, mid, matrix)
                             if mid and matrix in (profile.get("supported_matrices") or []) else None)
                    extra = set()
                    if core_method is not None:
                        extra = project_added(sample)(core_method) or set()
                    fmt = report_format.resolve(profile, matrix) if profile else {}
                    rec = by_sample[sample.UID()] = {"uid": sample.UID(), "id": sample.getId(),
                                                     "panel": panel, "allowed_extra": extra,
                                                     "format": (int(fmt.get("coa_sig_figs") or 3),
                                                                fmt.get("coa_rounding") or rounding.DEFAULT_RULE)
                                                               if fmt else None,
                                                     "analyses": []}
                retest = False
                try:
                    if an.isRetest():
                        from senaite.pfas.browser.dilution_retests import dilution_fold
                        retest = bool(dilution_fold(an))
                except Exception:                           # noqa: BLE001
                    retest = False
                rec["analyses"].append({"uid": an.UID(), "keyword": an.getKeyword(),
                                        "result": an.getResult(), "dilution_retest": retest})
            self._result_checks = rc.check(list(by_sample.values()), self._result_pushes(ws.getId()))
        except Exception as exc:                            # noqa: BLE001
            logger.exception("result checks")
            self._result_checks = dict(empty, error=u"%s" % exc)
        return self._result_checks

    def _result_pushes(self, ws_id):
        """The worker's push log of the worksheet (result_pushes): queried
        once per worksheet a request; its readers only read it."""
        memo = getattr(self, "_pushes_memo", None)
        if memo is None:
            memo = self._pushes_memo = {}
        if ws_id not in memo:
            memo[ws_id] = self._result_pushes_uncached(ws_id)
        return memo[ws_id]

    def _recovery_places(self, batch_id=None, method_id=None):
        """The decimal places a recovery is judged and shown at: the method's;
        a run that recorded the places its checks judged at is shown at
        those, so a value never sits beside a verdict reached at other
        places."""
        from senaite.pfas import method_engine, rounding
        batch_id = batch_id or self.batch_id()
        method_id = method_id if method_id is not None else self.batch_method()
        places = method_engine.recovery_decimals(self._method_profile()) if method_id else 0
        recorded = self._judged_rules(batch_id)
        if len(recorded) == 1:
            places = rounding.judged_places(recorded[0])
        return places

    def _judged_rules(self, batch_id, path=None):
        """The rules ("epa;3;pct1") a run's checks recorded they judged with,
        from its injection rows in the QC store; [] when none is recorded or
        the store cannot be read."""
        import sqlite3
        from senaite.pfas.qc.store import DEFAULT_DB_PATH
        path = path or DEFAULT_DB_PATH
        if not batch_id or not os.path.exists(path):
            return []
        try:
            con = sqlite3.connect(path)
            try:
                return sorted(r[0] for r in con.execute(
                    "SELECT DISTINCT judged_rule FROM injection_results "
                    "WHERE batch_id=? AND judged_rule != ''", (batch_id,)))
            finally:
                con.close()
        except sqlite3.Error as exc:
            logger.warning("judged rules of %s unreadable: %s", batch_id, exc)
            return []

    def _result_pushes_uncached(self, ws_id):
        import sqlite3
        from senaite.pfas.qc.store import DEFAULT_DB_PATH
        if not os.path.exists(DEFAULT_DB_PATH):
            return []
        con = sqlite3.connect(DEFAULT_DB_PATH)
        try:
            if not con.execute("SELECT name FROM sqlite_master WHERE name='result_pushes'").fetchone():
                return []
            cols = ("injection", "sample_uid", "analysis_uid", "analyte", "keyword", "value", "ok", "reason")
            return [dict(zip(cols, r)) for r in con.execute(
                "SELECT %s FROM result_pushes WHERE batch_id=?" % ",".join(cols), (ws_id,))]
        finally:
            con.close()

    def _as_reported(self, result, unit, sample_type):
        """(result, unit) as the certificate states them: rounded by the
        method x matrix rule (rounding.py, report_format.py); the profile's
        unit when the analysis carries none. Non-numbers pass unchanged."""
        try:
            from senaite.pfas import rounding
            from senaite.pfas.report_limits import canonical_matrix
            fmt = self._certificate_format(sample_type)
            text = rounding.round_sig(result, int(fmt.get("coa_sig_figs") or 3),
                                      fmt.get("coa_rounding") or rounding.DEFAULT_RULE)
            profile = self._cert_inputs[1]
            unit = unit or (profile.get("unit_map") or {}).get(canonical_matrix(profile, sample_type)) or u""
            return (text if text is not None else result), unit
        except Exception:                                   # noqa: BLE001
            return result, unit

    def _certificate_row(self, analysis):
        """The certificate's own row for one analysis (coa_format.build_rows:
        its RL and MDL, frozen at verification where they were, scaled by a
        dilution's fold), without QC codes: what it prints and the rule's
        codes. None where it cannot be read. Once per analysis per request."""
        cache = self.__dict__.setdefault("_cert_rows", {})
        try:
            uid = analysis.UID()
        except Exception:                                   # noqa: BLE001
            return None
        if uid in cache:
            return cache[uid]
        row = None
        try:
            from senaite.pfas import coa_format, verified_rl
            from senaite.pfas.above_range import of as above_range_of
            from senaite.pfas.browser.dilution_retests import dilution_fold
            from senaite.pfas.report_limits import canonical_matrix
            sample_type = analysis.getRequest().getSampleTypeTitle()
            merged = self._certificate_format(sample_type)
            profile = self._cert_inputs[1]
            keyword = analysis.getKeyword()
            try:
                from senaite.pfas.browser.run_builder import analysis_acid_basis
                acid = analysis_acid_basis(analysis, self.__dict__.setdefault("_acid_basis_cache", {}))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("acid basis for %s: %s", keyword, exc)
                acid = []
            row = coa_format.build_rows(
                [{"keyword": keyword, "result": analysis.getResult(),
                  "dilution": dilution_fold(analysis), "frozen_rl": verified_rl.frozen_for(analysis),
                  "above": (above_range_of(analysis) or {}).get("limit"),
                  "acid_basis": keyword.upper() in [a.upper() for a in acid]}],
                profile, canonical_matrix(profile, sample_type), merged)[0]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("certificate row of an analysis: %s", exc)
        cache[uid] = row
        return row

    def _prints_number(self, analysis):
        """Does the certificate print this result as a number? Not for a text
        result (BLoQ, N.D.), "< RL", N.Q. or "> top". Where the certificate's
        row cannot be read, whether the stored result is a number."""
        from senaite.pfas.rounding import number
        row = self._certificate_row(analysis)
        if row is not None:
            return number(row.get("result")) is not None
        try:
            return number(analysis.getResult()) is not None
        except Exception:                                   # noqa: BLE001
            return True

    def final_data_diagnosis(self):
        """When the Final Data table is empty, say WHY (which link in the
        chain has no data) instead of rendering a silent blank."""
        ws = self._get_worksheet()
        if not ws:
            return u"No worksheet found."
        try:
            n_assigned = len(ws.getAnalyses() or [])
        except Exception:
            n_assigned = 0
        if n_assigned:
            return u""
        ars = self._batch_ars()
        if not ars:
            return (u"No analyses are assigned to this worksheet and no "
                    u"samples are linked to this batch. Assign samples/"
                    u"analyses to the worksheet, or link samples to the batch.")
        n_res = 0
        for ar in ars:
            try:
                n_res += len([a for a in ar.getAnalyses(full_objects=True)
                              if a.getResult()])
            except Exception:
                pass
        if n_res == 0:
            return (u"%d sample(s) found on this batch, but no results have "
                    u"been entered/imported yet. Import instrument data or "
                    u"enter results, then this summary will populate."
                    % len(ars))
        return u""

    def _batch_ars(self):
        """Samples for this worksheet when none are formally assigned.

        Join chain (Worksheet ↔ Batch was a missing link in the model):
          1. the samples of the SENAITE Batch the worksheet's analyses
             belong to (_linked_batch: SENAITE's own sample -> batch link);
          2. ARs whose Batch UID is this worksheet's UID."""
        ws = self._get_worksheet()
        if ws is None:
            return []
        try:
            cat = getToolByName(self.context, "senaite_catalog_sample")
        except Exception:
            return []
        # 1. the batch SENAITE links the worksheet's samples to
        try:
            batch = self._linked_batch(ws)
            if batch is not None:
                ars = [b.getObject() for b in cat(
                    portal_type="AnalysisRequest", getBatchUID=batch.UID())]
                if ars:
                    return ars
        except Exception as exc:
            logger.warning("_batch_ars batch join: %s", exc)
        # 2. legacy join
        try:
            return [b.getObject() for b in cat(
                portal_type="AnalysisRequest", getBatchUID=self.batch_uid())]
        except Exception as exc:
            logger.warning("_batch_ars: %s", exc)
            return []

    def get_final_data(self):
        """Per-sample per-analyte results. Primary source: analyses assigned
        to the worksheet; fallback: analyses of the batch's samples (the
        chain is often batch-linked before worksheet assignment)."""
        ws = self._get_worksheet()
        if not ws:
            return []
        rows = []
        wf_tool = getToolByName(self.context, "portal_workflow")
        ar_map = {}
        # the QC qualifiers each result will carry: reviewed here, with the
        # result, before "Final Data Reviewed"
        codes_for = self._qualifier_plan(ws) or (lambda _a: [])

        try:
            ws_analyses = ws.getAnalyses() or []
        except Exception as exc:
            logger.error("get_final_data.getAnalyses: %s", exc)
            ws_analyses = []

        if not ws_analyses:
            # Fallback: batch → samples → analyses
            for ar in self._batch_ars():
                try:
                    ws_analyses.extend(ar.getAnalyses(full_objects=True) or [])
                except Exception:
                    continue

        for analysis in ws_analyses:
            try:
                ar = analysis.getRequest()
                if ar is None:
                    continue
                ar_uid = ar.UID()
                if ar_uid not in ar_map:
                    try:
                        sample_id = ar.getSampleID() or ar.getId()
                    except Exception:
                        sample_id = ar.getId()
                    client_sid = getattr(ar, "ClientSampleID", "") or u""
                    sample_type = u""
                    try:
                        st = ar.getSampleType()
                        if st:
                            sample_type = st.Title()
                    except Exception:
                        pass
                    # its field QC (FRB, TB, FD) as the worker reads it,
                    # for the type icon beside the sample
                    field_qc = u""
                    try:
                        from senaite.pfas.coc_records import WORKER_FIELD_QC
                        fld = ar.getField("FieldQCType")
                        field_qc = WORKER_FIELD_QC.get((fld.get(ar) if fld else u"") or u"", u"")
                    except Exception:                       # noqa: BLE001
                        pass
                    ar_map[ar_uid] = {
                        "sample_id": sample_id,
                        "client_sample_id": client_sid,
                        "sample_type": sample_type,
                        "field_qc": field_qc,
                        "analyses": [],
                    }

                keyword = analysis.getKeyword() or u""
                result  = analysis.getResult() or u""
                unit    = analysis.getUnit() or u""
                state   = wf_tool.getInfoFor(analysis, "review_state", u"")

                # Detection limit qualifier
                qualifier = u""
                for attr in ("getDetectionLimitOperand", "result_operator"):
                    try:
                        v = getattr(analysis, attr, None)
                        if callable(v):
                            v = v()
                        if v in ("<", ">", "="):
                            qualifier = v
                            break
                    except Exception:
                        pass

                # which value is reported: a neat reading replaced by its
                # dilution is kept for review, its retest is what reports
                reported = u""
                dilution = False
                try:
                    if analysis.isRetested():
                        reported = u"replaced by its dilution"
                    elif analysis.isRetest():
                        from senaite.pfas.browser.dilution_retests import dilution_fold
                        fold = dilution_fold(analysis)
                        dilution = bool(fold)
                        reported = (u"reported \u2014 dilution %g-fold" % fold) if fold \
                            else u"reported \u2014 retest"
                except Exception:                           # noqa: BLE001
                    pass
                # shown as the certificate states it:
                # the lab's rounding for the method x matrix, and the unit
                # from the profile when core holds none (runs before then)
                result, unit = self._as_reported(result, unit, ar_map[ar_uid]["sample_type"])
                # the certificate's J: a number between the MDL and the RL
                cert = self._certificate_row(analysis)
                from senaite.pfas.coa_format import J_CODE
                rule_code = J_CODE if cert is not None and cert.get("estimated") else u""
                pairs = codes_for(analysis)
                ar_map[ar_uid]["analyses"].append({
                    "analyte":      keyword,
                    "title":        analysis.Title() or u"",
                    "result":       result,
                    "unit":         unit,
                    "qualifier":    qualifier,
                    "rule_code":    rule_code,
                    "qc_pairs":     pairs,
                    "qc_codes":     u", ".join(sorted(set(c for c, _r in pairs))),
                    "qc_reasons":   u"; ".join(r for _c, r in pairs if r),
                    "review_state": state,
                    "reported":     reported,
                    "dilution":     dilution,
                })
            except Exception as exc:
                logger.error("get_final_data analysis loop: %s", exc)

        from senaite.pfas import qc_cells
        from senaite.pfas import final_data
        from senaite.pfas import sample_type_icons as sti
        # the instrument's result and RT behind each reported result (the
        # injection rows the Samples tab used to show)
        try:
            inj = dict((s["sample_id"], s["analytes"]) for s in self.sample_results_page())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("get_final_data instrument rows: %s", exc)
            inj = {}
        for ar_uid in sorted(ar_map.keys(), key=lambda u: ar_map[u]["sample_id"]):
            ar_data = ar_map[ar_uid]
            for a in sorted(ar_data["analyses"], key=lambda x: x["analyte"]):
                ps = final_data.parts(inj.get(ar_data["sample_id"]) or [], a["analyte"], a.get("title"))
                instrument, instrument_parts = final_data.text(ps)
                rt, rt_parts = final_data.rt_text(ps)
                rows.append({
                    # the value in the number column, an isomer sum's parts
                    # on the muted line under it
                    "instrument":       instrument,
                    "instrument_parts": instrument_parts,
                    "rt":               rt,
                    "rt_parts":         rt_parts,
                    # the injection a request to the preparer names
                    "injection":        next((p["injection"] for p in ps if p.get("injection")), u""),
                    "instrument_prov":  ps[0].get("prov") if len(ps) == 1 else None,
                    # the reported result's own record
                    "result_prov":      final_data.result_key(ps, a["analyte"]),
                    "sample_id":        ar_data["sample_id"],
                    "client_sample_id": ar_data["client_sample_id"],
                    "sample_type":      ar_data["sample_type"],
                    "analyte":          a["analyte"],
                    # the analysis's title: the name the certificate prints
                    "title":            a.get("title") or u"",
                    "result":           a["result"],
                    "unit":             a["unit"],
                    "qualifier":        a["qualifier"],
                    # the certificate's J beside a number in the band
                    "rule_code":        a.get("rule_code") or u"",
                    "qc_codes":         a.get("qc_codes") or u"",
                    "qc_reasons":       a.get("qc_reasons") or u"",
                    "qc_pairs":         a.get("qc_pairs") or [],
                    # the codes drawn as the QC Summary draws a qualified cell
                    "qc_cell":          qc_cells.code_cell(a.get("qc_codes"), a.get("qc_reasons"),
                                                       self.code_meanings()),
                    "review_state":     a["review_state"],
                    "reported":         a.get("reported") or u"",
                    # the type beside the sample: a field QC or a dilution
                    # retest; a plain field sample has none
                    "type_code":        sti.result_code(ar_data.get("field_qc"), a.get("dilution")),
                })
        # a sample withheld for re-extraction stays listed, greyed
        rows = self._withheld_rows(rows, inj)
        return self._beyond_common_codes(rows, qc_cells)

    def _beyond_common_codes(self, rows, qc_cells):
        """A code every result carries is stated once above the table
        (common_codes_line): each row's chip keeps the codes beyond it, and
        a row with a chip is marked for review on its edge."""
        common = set(self.common_codes(rows))
        for r in rows:
            if common:
                extra = [(c, why) for c, why in r.get("qc_pairs") or [] if c not in common]
                r["qc_cell"] = qc_cells.code_cell(
                    u", ".join(sorted(set(c for c, _w in extra))),
                    u"; ".join(why for _c, why in extra if why), self.code_meanings())
            r["state"] = u"review" if (r.get("qc_cell") and not r.get("qualifier")) else u""
        return rows

    # ── Extraction record ──────

    _SOURCE_LABELS = {"252": u"Extraction record", "253": u"Processing stage"}

    def source_label(self, source):
        """A traceability source as the reader knows it: "252.standards" ->
        "Extraction record, standards"; storage slugs never shown."""
        slug, _sep, part = (source or u"").partition(u".")
        if slug in self._SOURCE_LABELS:
            return u"%s%s" % (self._SOURCE_LABELS[slug],
                              u", " + part.replace(u"_", u" ") if part else u"")
        if slug == u"prepstd":
            return u"prepared standard parents"
        if source == u"run.sent_back":
            return u"run sent back"
        if slug == u"run":
            return u"loaded on the instrument" + (u", " + part if part else u"")
        return (source or u"").replace(u"_", u" ")

    def extraction_record(self):
        """The guided extraction of this worksheet, for review: every
        stage (extraction_review.review), the per-sample amounts and final
        volumes and the dilutions recorded in the extraction record, finalized or not.
        Its being finished is part of the traceability gate; the rest is shown for review."""
        batch = self._extraction_home(self._get_worksheet())
        if batch is None:
            return None
        try:
            from senaite.pfas.browser.extraction_guide import _load_session
            from senaite.pfas.browser.sample_status import _fullname
            from senaite.pfas import extraction_store
            from senaite.pfas.extraction_review import review
            from senaite.pfas.method_profile_store import get_profile
            from senaite.pfas import sample_table
            from senaite.pfas.dilution_ref import parse_factor
            sess = _load_session(batch)
            # the record's home named by what it is: a worksheet (WS) or,
            # for an older record, its client batch (B)
            kind = u"Worksheet" if getattr(batch, "portal_type", "") == "Worksheet" else u"Batch"
            if not sess:
                return {"started": False, "batch_uid": batch.UID(), "batch_id": batch.getId(), "kind": kind}
            from senaite.pfas.stage_plan import stages_for
            stages = stages_for(sess, get_profile(self._portal(), sess.get("method_id", "")))
            rv = review(sess, stages)
            rows = extraction_store.load_table(batch).get("samples") or []
            samples = sample_table.rows_for_card(rows, [])
            return {
                "started": True, "batch_uid": batch.UID(), "batch_id": batch.getId(), "kind": kind,
                "finalized": bool(sess.get("finalized")),
                "finalized_at": sess.get("finalized_at") or u"",
                "finalized_by": _fullname(self.context, sess.get("finalized_by") or u""),
                "started_at": sess.get("started_at") or u"",
                "analyst": sess.get("analyst") or u"",
                "review": rv,
                "samples": samples,
                "dilutions": [dict(d, fold_ok=parse_factor(d.get("dilution_factor")) is not None)
                              for d in sample_table.dilutions(rows)],
                "pdf_url": u"{0}/@@pfas-extraction-pdf?batch_uid={1}".format(
                    self._portal().absolute_url(), batch.UID()),
                "guide_url": u"{0}/@@pfas-extraction-guide?batch_uid={1}".format(
                    self._portal().absolute_url(), batch.UID()),
            }
        except Exception as exc:                            # noqa: BLE001
            logger.warning("extraction_record: %s", exc)
            return None

    def _extraction_finalized(self):
        rec = self.extraction_record()
        return bool(rec and rec.get("started") and rec.get("finalized"))

    def extraction_flags(self):
        """What the Overview says about the extraction."""
        rec = self.extraction_record()
        if rec is None:
            return []
        if not rec.get("started"):
            return [u"No guided extraction is recorded for %s %s." % (rec.get("kind", u"Worksheet").lower(), rec["batch_id"])]
        out = []
        rv = rec["review"]
        if not rec["finalized"]:
            out.append(u"The extraction is not finalized.")
        if rv["missing"]:
            out.append(u"Stage(s) not recorded: %s." % u", ".join(u"%s" % o for o in rv["missing"]))
        if rv["unnoted"]:
            out.append(u"Stage(s) with warnings but no deviation note: %s."
                       % u", ".join(u"%s" % o for o in rv["unnoted"]))
        bad = [d["sample_id"] for d in rec["dilutions"] if not d["fold_ok"]]
        if bad:
            out.append(u"Dilution(s) not recorded as a fold, so not applied: %s \u2014 log the "
                       u"total fold (e.g. 10)." % u", ".join(bad))
        if rv["corrections"]:
            out.append(u"%d stage correction(s) recorded \u2014 see the Extraction tab."
                       % rv["corrections"])
        return out

    # ── Instrument Report ─────────────────────────────────────────────────

    def _report_dir(self, ws):
        uid = self.batch_uid()
        return os.path.join(INSTRUMENT_REPORT_DIR, uid)

    def get_instrument_reports(self):
        ws = self._get_worksheet()
        if not ws:
            return []
        report_dir = self._report_dir(ws)
        if not os.path.exists(report_dir):
            return []
        files = []
        for fname in sorted(os.listdir(report_dir)):
            fpath = os.path.join(report_dir, fname)
            if not os.path.isfile(fpath):
                continue
            stat = os.stat(fpath)
            files.append({
                "filename":    fname,
                "size_kb":     max(1, stat.st_size // 1024),
                "uploaded_at": lab_time.show(datetime.datetime.utcfromtimestamp(stat.st_mtime)),
                "is_csv":      fname.lower().endswith((".csv", ".tsv")),
            })
        return files

    def get_csv_preview(self):
        """Return first 100 rows of the first CSV/TSV instrument report, or []."""
        ws = self._get_worksheet()
        if not ws:
            return []
        report_dir = self._report_dir(ws)
        if not os.path.exists(report_dir):
            return []
        for fname in sorted(os.listdir(report_dir)):
            if fname.lower().endswith((".csv", ".tsv")):
                fpath = os.path.join(report_dir, fname)
                try:
                    with open(fpath, "rb") as f:
                        content = f.read().decode("utf-8", errors="replace")
                    dialect = csv.excel_tab if fname.lower().endswith(".tsv") else csv.excel
                    reader = csv.reader(io.StringIO(content), dialect=dialect)
                    rows = []
                    for i, row in enumerate(reader):
                        if i >= 101:
                            break
                        rows.append(row)
                    return rows
                except Exception as exc:
                    logger.error("get_csv_preview: %s", exc)
        return []

    # ── Pending-review worklist helpers ───────────────────────────────────
    # All age arithmetic is done in naive-UTC: extraction logs store
    # datetime.utcnow().isoformat(), and workflow-history timestamps are Zope
    # DateTime whose .timeTime() is an absolute epoch we read via utcfromtimestamp.

    @staticmethod
    def _parse_iso(value):
        """Parse an ISO-8601 timestamp string (with or without microseconds)
        into a naive datetime, or None."""
        if not value:
            return None
        text = value.split("+")[0].split("Z")[0].strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(text, fmt)
            except (ValueError, TypeError):
                continue
        return None

    @staticmethod
    def _ws_action_time(ws, action):
        """Most-recent time a workflow *action* (e.g. 'submit') fired on the
        worksheet, as a naive-UTC datetime, or None."""
        try:
            history = ws.workflow_history
        except Exception:
            return None
        best = None
        try:
            for events in history.values():
                for event in events:
                    if event.get("action") != action:
                        continue
                    stamp = event.get("time")
                    if stamp is None:
                        continue
                    try:
                        moment = datetime.datetime.utcfromtimestamp(
                            stamp.timeTime())
                    except Exception:
                        continue
                    if best is None or moment > best:
                        best = moment
        except Exception:
            return None
        return best

    @staticmethod
    def _fmt_age(now, then):
        """Human elapsed time between two datetimes, e.g. '12d 4h', '5h 20m',
        '45m'. Returns an em-dash when *then* is unknown."""
        if then is None:
            return u"—"
        total = int((now - then).total_seconds())
        if total < 0:
            total = 0
        days = total // 86400
        hours = (total % 86400) // 3600
        mins = (total % 3600) // 60
        if days >= 1:
            return u"{0}d {1}h".format(days, hours)
        if hours >= 1:
            return u"{0}h {1}m".format(hours, mins)
        return u"{0}m".format(mins)

    def recent_worksheets(self):
        """Pending data-review worklist: worksheets in open/to_be_verified,
        enriched per row with the responsible analyst, whether it is under
        peer review, how long the case has been open since extraction, and
        (once submitted) how long it has been in review: u"" until then,
        which the queue reads "not yet"."""
        from senaite.pfas import retired
        from senaite.pfas.browser.sample_status import (
            _fullname, _load_extraction_log)
        try:
            cat = getToolByName(self.context, "senaite_catalog_worksheet")
            if cat is None:
                cat = getToolByName(self._portal(), "senaite_catalog_worksheet")
            brains = cat(
                portal_type="Worksheet",
                review_state=["open", "to_be_verified"],
            )
            # newest first (by worksheet number): the 50 listed are the most
            # recent, not the catalog's arbitrary first 50
            import re as _re

            def _num(b):
                m = _re.search(r"(\d+)$", b.getId or "")
                return int(m.group(1)) if m else -1
            brains = sorted(brains, key=_num, reverse=True)
        except Exception as exc:
            logger.error("recent_worksheets: %s", exc, exc_info=True)
            return []
        now = datetime.datetime.utcnow()
        result = []
        for b in brains:
            # the 50 listed are the newest that are not retired
            if len(result) >= 50:
                break
            try:
                wid = b.getId
                state = b.review_state
                under_review = (state == "to_be_verified")

                # the worksheet IS the extraction batch: its record is
                # read off the object, never off the id
                try:
                    obj = b.getObject()
                except Exception:
                    obj = None
                if obj is not None and retired.is_retired(obj):
                    continue
                log = (_load_extraction_log(obj) if obj is not None else None) or {}
                analyst = (log.get("analyst") or u"").strip()
                started = self._parse_iso(log.get("started"))
                if not analyst and obj is not None:
                    try:
                        analyst = _fullname(obj, obj.getAnalyst() or u"")
                    except Exception:
                        analyst = u""
                submitted = None
                if under_review and obj is not None:
                    submitted = self._ws_action_time(obj, "submit")

                result.append({
                    "id":           wid,
                    "title":        b.Title or wid,
                    "url":          b.getURL() + "/@@pfas-data-review",
                    "state":        state,
                    "analyst":      analyst or u"—",
                    "under_review": under_review,
                    "stage_label":  u"In peer review" if under_review
                                    else u"With analyst",
                    "open_age":     self._fmt_age(now, started),
                    "review_age":   self._fmt_age(now, submitted)
                                    if under_review else u"",
                })
            except Exception as exc:
                logger.error("recent_worksheets brain: %s", exc)
        return result

    # the field blanks whose columns show whenever the method's rules
    # enforce them, said "none on this worksheet" when it holds none
    _SHOWN_FIELD_BLANKS = (u"FRB",)

    def blanks_table(self, qc=None):
        """The Blanks tab: every extracted blank against its limit
        (qc_cells.blank_table). A field blank the method's rules enforce
        (its row on the Rules grid is not Off) always has its columns; the
        limit heading states the method's rule as Effective QC does where
        no stored row carries the limit applied."""
        from senaite.pfas import qc_cells
        qc = qc if qc is not None else self.get_qc_summary()
        rules = self.blank_rules() or {}
        return qc_cells.blank_table(qc.get("rows") or [], qc.get("qc_types") or [],
                                    always=rules.get("always") or (), absent=rules.get("absent") or (),
                                    rule=rules.get("rule") or {})

    def blank_rules(self):
        """What the method's rules say of the blanks, for the Blanks tab:
        {"always": the field blanks its rules enforce, "absent": those the
        worksheet holds none of, "rule": {qc_type: its limit in Effective
        QC's words, for the field blanks}}. Once per request."""
        if hasattr(self, "_blank_rules"):
            return self._blank_rules
        out = {"always": [], "absent": [], "rule": {}}
        try:
            from senaite.pfas.effective_qc import blank_limit_words
            from senaite.pfas import limit_states
            profile = self._method_profile() or {}
            matrix = self._batch_matrix()
            qca = profile.get("qc_acceptance") or {}
            # a blank judged: held, and its limit box not Off
            out["always"] = [qt for qt in self._SHOWN_FIELD_BLANKS
                             if qt in qca and limit_states.qc_type_state(profile, qt) != u"off"]
            if out["always"]:
                held = self._field_qc_held()
                out["absent"] = [qt for qt in out["always"] if qt not in held]
            # only a field blank's row was ever filed without the limit it
            # was judged by; any other blank with none stored had none applied
            for qt in self._RUN_BLANKS:
                words = blank_limit_words(profile, qt, matrix)
                if words:
                    out["rule"][qt] = words
        except Exception as exc:                            # noqa: BLE001
            logger.warning("blank rules: %s", exc)
        self._blank_rules = out
        return out

    def _field_qc_held(self):
        """The field QC kinds ("FRB", "TB", "FD") the worksheet's samples
        carry, read from each sample's Field QC as the worker reads it."""
        ws = self._get_worksheet()
        if ws is None:
            return set()
        try:
            from senaite.pfas.coc_records import WORKER_FIELD_QC
            from senaite.pfas.core_fields import samples_of
            out = set()
            for s in samples_of(ws):
                fld = s.getField("FieldQCType") if s is not None else None
                code = WORKER_FIELD_QC.get((fld.get(s) if fld else u"") or u"")
                if code:
                    out.add(code)
            return out
        except Exception as exc:                            # noqa: BLE001
            logger.warning("field QC held: %s", exc)
            return set()

    def run_level_flags(self, flags=None):
        """The run's whole-run QC flags (a field reagent blank, a run not
        closed by a CCV) as warnings: they hold the gate, but belong to no
        analyte. [{"qc_type", "status", "title", "text", "unjudged",
        "unmapped"}]; `flags` the QC Summary's run_flags when the caller has
        them."""
        out = []
        if flags is None:
            try:
                flags = self.get_qc_summary(shared=True).get("run_flags") or []
            except Exception:                               # noqa: BLE001
                flags = []
        if not flags:
            return out
        from senaite.pfas.qc_labels import qc_label
        from bika.lims import api as _api
        for f in flags:
            name = qc_label(_api.get_portal(), f["qc_type"])
            verb = u"not judged" if f["status"] == "unevaluated" else u"flagged"
            detail = u"; ".join(f.get("flags") or [])
            out.append({"qc_type": f["qc_type"], "status": f["status"], "title": u"%s %s" % (name, verb),
                        "text": u"for the whole run" + (u": %s" % detail if detail else u"."),
                        "unjudged": bool(f.get("unjudged")), "unmapped": f.get("unmapped") or u""})
        return out

    def limits_not_set(self):
        """The analytes of this run with no RL or no MDL for their matrix:
        a blank or a result cannot be compared with a limit that is not set
        (one warning, with a button to the method's Reporting Limits), or None."""
        ws = self._get_worksheet()
        mid = self.batch_method()
        if ws is None or not mid:
            return None
        try:
            from senaite.pfas.report_limits import canonical_matrix, limits_for
            from senaite.pfas.core_fields import samples_of
            profile = self._method_profile() or {}
            keywords = list(profile.get("master_analyte_set") or [])
            matrices = sorted(set(canonical_matrix(profile, s.getSampleTypeTitle())
                                  for s in samples_of(ws) if s is not None))
            missing, where, no_rl, no_mdl = set(), [], set(), set()
            for m in matrices:
                lim = dict((kw, limits_for(profile, m, kw)) for kw in keywords)
                rl = set(kw for kw in keywords if lim[kw]["rl"] is None)
                mdl = set(kw for kw in keywords if lim[kw]["mdl"] is None)
                if rl or mdl:
                    missing.update(rl | mdl)
                    no_rl.update(rl)
                    no_mdl.update(mdl)
                    where.append(m)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("limits_not_set: %s", exc)
            return None
        if not missing:
            return None
        what = u"RL or MDL" if (no_rl and no_mdl) else (u"RL" if no_rl else u"MDL")
        return {"n": len(missing), "matrix": u", ".join(where), "what": what,
                "url": u"%s/@@pfas-method-profile-edit?method_id=%s#pane-analytes" % (self.portal_url(), mid)}

    # ── Warnings by severity: one strip under the title ──────────────────

    # a blank judged for the whole run against its own limit: none set is
    # "not judged" for the whole run (the worker files no analyte for it)
    _RUN_BLANKS = (u"FRB", u"TB")
    BLOCKS, NOTE = u"blocks", u"note"
    # a whole-run flag in one of these holds the QC gate (overall_pass)
    _GATING = (u"fail", u"unevaluated")
    # the words for a QC Summary that could not be read
    _QC_ERRORS = {u"db_unavailable": u"the QC database is not available",
                  u"db_error": u"the QC database could not be read",
                  u"no_batch_record": u"no run is on record",
                  u"no_worksheet": u"no worksheet is open"}

    def method_label(self):
        """The batch's method as the lab names it (its profile's display
        name), else its id."""
        from senaite.pfas.configured_methods import method_label
        return method_label(self._method_profile(), self.batch_method())

    def editor_url(self, pane):
        """The batch method's editor, opened on `pane`; u"" with no method."""
        mid = self.batch_method()
        if not mid:
            return u""
        return u"%s/@@pfas-method-profile-edit?method_id=%s#%s" % (self.portal_url(), mid, pane)

    def review_url(self, tab):
        """This worksheet's Data Review on `tab`."""
        return u"%s/@@pfas-data-review?tab=%s" % (self.batch_url(), tab)

    # the tab a QC type's values are shown on: (tab, its name)
    _QC_TABS = {"spike": (u"spike_qc", u"Spike QC"), "blank": (u"qc_summary", u"Blanks"),
                "instrument": (u"calibration", u"Calibration")}

    def _qc_tab(self, qc_type):
        """(tab, its name) that shows `qc_type`'s values, or None."""
        from senaite.pfas import qc_cells
        if qc_cells.is_spike(qc_type):
            kind = "spike"
        elif qc_type.split(u" ")[0] in qc_cells.BLANK_COLUMNS:
            kind = "blank"
        elif qc_cells.group_of(qc_type) == u"instrument":
            kind = "instrument"
        else:
            return None
        return self._QC_TABS[kind]

    # the spikes judged against a spike level per sample: a run whose results
    # stay in the extract's unit cannot judge them
    _SAMPLE_BASIS_SPIKES = (u"LFSM", u"LFSMD")

    # how the worker records a matrix spike it could not judge because its
    # results and its spike level are in different units
    # (pfas_pipeline/run_queue.py, the LFSM evaluation)
    _SPIKE_UNITS_DIFFER = u"results are in"

    def missing_matrix_factor(self):
        """{"matrix", "method", "url"} when a matrix spike was not judged
        because its results and its spike level are in different units, and
        the method puts its results on the sample basis by its matrix
        factor (Sample correction: nominal) yet sets none for the batch's
        matrix, so they stayed in the extract's unit; the url opens the
        method's Matrices tab. None otherwise (another cause, or a factor
        set)."""
        if hasattr(self, "_missing_factor"):
            return self._missing_factor
        out = None
        try:
            from senaite.pfas.calibration_levels import matrix_factor
            from senaite.pfas.sample_correction import NOMINAL
            profile = self._method_profile() or {}
            matrix = self._batch_matrix()
            mode = (profile.get("sample_correction") or u"").strip()
            flags = [t for f in (self.get_qc_summary(shared=True) or {}).get("run_flags") or []
                     if f.get("qc_type") in self._SAMPLE_BASIS_SPIKES for t in f.get("flags") or []]
            differ = any(self._SPIKE_UNITS_DIFFER in (t or u"") for t in flags)
            if differ and profile and matrix and mode in (NOMINAL, u"") and matrix_factor(profile, matrix) is None:
                out = {"matrix": matrix, "method": self.method_label(),
                       "url": self.editor_url(u"pane-matrices")}
        except Exception as exc:                            # noqa: BLE001
            logger.warning("missing matrix factor: %s", exc)
        self._missing_factor = out
        return out

    @staticmethod
    def _no_factor_text(mf):
        return (u"no matrix factor for %s on %s, so the results stay in the extract's unit and "
                u"cannot be compared with the spike level" % (mf["matrix"], mf["method"]))

    def _unset_blank_limits(self, run_flags):
        """The run's blanks judged against their own limit that were not
        judged for want of one (FRB, TB), in the order filed."""
        out = []
        for f in run_flags or []:
            if f.get("status") == "unevaluated" and f.get("qc_type") in self._RUN_BLANKS \
                    and f["qc_type"] not in out:
                out.append(f["qc_type"])
        return out

    @staticmethod
    def _analytes(n):
        return u"%d analyte%s" % (n, u"" if n == 1 else u"s")

    def _gate_rows(self, summary):
        """The QC Summary gate's reasons while it does not pass (its verdict
        on the checklist): [(text, fix_label, fix_url)], one per QC kind
        and one per whole-run flag that holds it, each with the button the
        Blanks verdict gives the same cause. Read from the one reading the
        verdict reads (_qc_gate), so the strip and the verdicts agree. An
        import not done is its own warning."""
        item = [i for i in self.checklist_status() or [] if i.get("key") == u"qc_summary"]
        if item and item[0].get("verdict") in (u"pass", u"qualified"):
            return []
        if summary.get("error"):
            err = summary["error"]
            if err != u"db_unavailable" and not self.has_run():
                return [(u"No run imported yet.", u"", u"")]
            return [(u"QC results are not available: %s." % self._QC_ERRORS.get(err, err), u"", u"")]
        out = []
        if self.subtraction_change_pending():
            out.append((u"The subtraction blank was changed: reprocess the run so its results "
                        u"use it.", u"", u""))
        if self.identity_pending():
            out.append((self.IDENTITY_PENDING, u"", u""))
        if self.extraction_pending():
            out.append((self.EXTRACTION_PENDING, u"", u""))
        if self.send_back_pending():
            out.append((self.SEND_BACK_PENDING, u"", u""))
        gate = self._qc_gate(summary)
        from senaite.pfas import qc_cells
        names = self._qc_names(set(qt for qt, _a, _c in gate["failing"] + gate["unevaluated"])
                               | set(gate["missing"]) | set(f["qc_type"] for f in gate["run"]))
        criteria = self.editor_url(u"pane-qc")
        qualifiers = u"%s/@@pfas-qc-qualifiers" % self.portal_url()

        def failed_fix(qt):
            tab = self._qc_tab(qt)
            return (tab[1], self.review_url(tab[0])) if tab else (u"", u"")

        def by_kind(entries):
            kinds = {}
            for qt, analyte, _cell in entries:
                kinds.setdefault(qt, set()).add(analyte)
            return [(qt, kinds[qt]) for qt in sorted(kinds, key=qc_cells.column_order)]
        for qt, analytes in by_kind(gate["failing"]):
            out.append((u"%s failed for %s." % (names.get(qt, qt), self._analytes(len(analytes))),)
                       + failed_fix(qt))
        unmapped = []
        for _qt, _a, cell in gate["unevaluated"]:
            if cell.get("unmapped") and cell["unmapped"] not in unmapped:
                unmapped.append(cell["unmapped"])
        mf = self.missing_matrix_factor()
        for qt, analytes in by_kind([e for e in gate["unevaluated"]
                                     if e[2].get("unjudged") or not e[2].get("unmapped")]):
            if mf and qt in self._SAMPLE_BASIS_SPIKES:
                out.append((u"%s not judged for %s: %s." % (
                    names.get(qt, qt), self._analytes(len(analytes)), self._no_factor_text(mf)),
                    u"Matrices", mf["url"]))
                continue
            out.append((u"%s not judged for %s: its criterion is not set." % (
                names.get(qt, qt), self._analytes(len(analytes))),
                u"QC criteria" if criteria else u"", criteria))
        # the whole-run flags: a blank whose own limit is not set is said
        # from its state, never from the worker's prose
        for qt in gate["unset"]:
            out.append((u"%s limit not set for %s: the blank is not judged for this run." % (
                qt, self.method_label()), u"QC criteria" if criteria else u"", criteria))
        for f in self.run_level_flags(gate["run"]):
            if f["status"] == u"fail":
                fix = failed_fix(f["qc_type"])
            elif f.get("unmapped") and not f.get("unjudged"):
                # said as a cell's is, once (below)
                if f["unmapped"] not in unmapped:
                    unmapped.append(f["unmapped"])
                continue
            elif mf and f["qc_type"] in self._SAMPLE_BASIS_SPIKES:
                # judged against a per-sample spike level: with no matrix
                # factor the results stay in the extract's unit
                out.append((u"%s for the whole run: %s." % (f["title"], self._no_factor_text(mf)),
                            u"Matrices", mf["url"]))
                continue
            else:
                fix = (u"QC criteria" if criteria else u"", criteria)
            out.append((u"%s %s" % (f["title"], f["text"]),) + fix)
        for label in unmapped:
            out.append((u"No qualifier mapped for %s failures." % label, u"QC Qualifiers", qualifiers))
        # a marked result its QC Qualifiers entry cannot qualify, each named
        for text in gate.get("qualifier_holds") or []:
            out.append((text + u".", u"QC Qualifiers", qualifiers))
        for qt in gate["missing"]:
            out.append((u"%s not run: the method requires it every run." % names.get(qt, qt),
                        u"Worksheet QC", self.extraction_guide_url()))
        from senaite.pfas import run_calibration as rc
        cal = self.calibration_review() or {}
        st = cal.get("status")
        if st != rc.APPROVED:
            if st == rc.REJECTED:
                text = u"The run's calibration was rejected%s." % (
                    (u": %s" % cal["note"]) if cal.get("note") else u"")
            elif st == rc.MISSING:
                text = u"No calibration was found for this run."
            else:
                text = u"The run's calibration is not approved yet."
            out.append((text, u"Calibration", self.review_url(u"calibration")))
        return out

    def _qc_names(self, qc_types):
        """{qc_type: the lab's name for it} (qc_labels), the code itself
        where none is found."""
        if not qc_types:
            return {}
        try:
            from senaite.pfas.qc_labels import qc_label
            from bika.lims import api as _api
            portal = _api.get_portal()
            return dict((qt, qc_label(portal, qt)) for qt in qc_types)
        except Exception:                                   # noqa: BLE001
            return {}

    def warnings(self):
        """Everything a reviewer must read before release, as one list:
        [{"severity": "blocks" | "note", "text", "fix_label", "fix_url",
        "lines"}], what blocks first (a stable sort). "blocks" is whatever
        holds the QC gate or the release: an open non-conformance, a run
        not imported, each QC kind the gate fails on, a whole-run flag that
        failed or was not judged, a blank's limit not set. "note" is the
        rest: an advisory flag, a method disagreement, accreditation, a
        reporting limit not set. A fix is the button to the page where it
        is made (u"" when there is none to make); "lines" lists a warning's
        items (the departures from a published method). The accreditation
        notes are always here, so no reviewer must open a particular tab to
        learn a report is outside accreditation; the mode is always stated,
        because "what would be recorded if you approve now" and "what was
        recorded" are different claims (see accreditation_disclosure).
        Once per request."""
        if hasattr(self, "_warnings"):
            return self._warnings
        out = []

        def add(severity, text, fix_label=u"", fix_url=u"", lines=None):
            out.append({"severity": severity, "text": text, "fix_label": fix_label if fix_url else u"",
                        "fix_url": fix_url or u"", "lines": list(lines or [])})

        portal = self.portal_url()
        for dev in self.active_deviations_for_worksheet() or []:
            did = dev.get("dev_id") or u""
            status = (dev.get("status") or u"").replace(u"_", u" ").lower()
            add(self.BLOCKS, u"Non-conformance %s is %s and references this worksheet: "
                u"review it before releasing data." % (did, status or u"open"),
                u"Open %s" % did, u"%s/@@pfas-deviations?dev_id=%s" % (portal, did))
        # a delivered run not imported holds release (the QC Summary gate)
        for ip in self.import_problems() or []:
            if ip.get("status") == "failed":
                add(self.BLOCKS, u"Import failed for %s after %s attempts: %s. Check its layout "
                    u"in Import Studio, then deliver the run again from the Run Builder." % (
                        ip.get("file"), ip.get("attempts"), ip.get("error") or u"no reason given"),
                    u"Import Studio", u"%s/@@pfas-import-studio" % portal)
            else:
                add(self.BLOCKS, u"Import of %s is retrying after %s attempts: %s. The worker "
                    u"tries again shortly." % (ip.get("file"), ip.get("attempts"),
                                               ip.get("error") or u"no reason given"))
        # a run delivered again after the worksheet closed: refused, the record stands
        for ip in self.import_refusals():
            add(self.NOTE, u"Import refused for %s: %s." % (ip.get("file"), ip.get("error") or u""))
        accred = self.accreditation_disclosure() or {}
        mode = accred.get("mode")
        if accred.get("out_of_scope"):
            when = {u"preview": u" if approved now, not yet recorded",
                    u"recorded": u", recorded at verification"}.get(mode, u"")
            if mode == u"recorded" and accred.get("frozen_at"):
                when += u" on %s" % self.lab_at(accred["frozen_at"], accred["frozen_at"])
            add(self.NOTE, u"Outside accreditation scope%s. This sample departs from a published "
                u"method requirement and is not covered by the laboratory's accreditation; the "
                u"certificate must state each departure." % when,
                lines=self.disclosure_lines())
        if accred and mode == u"not_recorded":
            add(self.NOTE, u"Governing criteria not recorded: this worksheet was verified before "
                u"the criteria were frozen at review, so what it was judged against cannot be "
                u"stated. No accreditation claim is made either way.")
        elif accred and not accred.get("out_of_scope") and accred.get("uncompared") and self.has_run():
            n = accred.get("uncompared", 0)
            add(self.NOTE, u"No departure detected, but %d of %d criteria have no published-method "
                u"baseline to compare against, so conformance is not established for those. This "
                u"is not a statement that the sample conforms." % (n, n + accred.get("compared", 0)))
        for source, method in self.batch_method_conflicts() or []:
            add(self.NOTE, u"Method disagrees: %s says %s; this batch is %s." % (
                source, method, self.batch_method()))
        try:
            summary = self.get_qc_summary(shared=True) or {}
        except Exception:                                   # noqa: BLE001
            summary = {}
        # the gate's own reasons, so the strip and its verdicts agree: each
        # QC kind and each whole-run flag that holds it (_gate_rows)
        for text, fix_label, fix_url in self._gate_rows(summary):
            add(self.BLOCKS, text, fix_label, fix_url)
        # a whole-run flag that holds nothing (advisory) is a note
        for f in self.run_level_flags(summary.get("run_flags") or []):
            if f.get("status") not in self._GATING:
                add(self.NOTE, u"%s %s" % (f["title"], f["text"]))
        # a processing change saved on the method that its compound can no
        # longer take: the worker leaves it out, and the run says so
        for text, url in self.processing_misfits():
            add(self.NOTE, text, u"Method profile", url)
        nl = self.limits_not_set()
        if nl:
            add(self.NOTE, u"No %s set for %d analytes in %s, so blanks and results cannot be "
                u"compared with them." % (nl["what"], nl["n"], nl["matrix"]),
                u"Reporting limits", nl.get("url"))
        out.sort(key=lambda w: 0 if w["severity"] == self.BLOCKS else 1)
        self._warnings = out
        return out

    @staticmethod
    def warnings_actionable(warns):
        """True when the strip holds something the reviewer can act on: a
        row that blocks release, or one with a button to where it is fixed.
        Notes with neither are read, not acted on, so no table is drawn."""
        return any(w.get("severity") == u"blocks" or w.get("fix_url") for w in warns or [])

    @staticmethod
    def warning_counts(warns):
        """The strip's count line: {"blocks", "notes", "blocks_text",
        "notes_text"} ("1 blocks release", "0 block release", "3 notes")."""
        b = len([w for w in warns or [] if w.get("severity") == u"blocks"])
        n = len(warns or []) - b
        return {"blocks": b, "notes": n,
                "blocks_text": u"%d %s release" % (b, u"blocks" if b == 1 else u"block"),
                "notes_text": u"%d %s" % (n, u"note" if n == 1 else u"notes")}

    def overall_reason(self, qc):
        """Why the run's QC does not pass, said beside the verdict, with the
        button to where it is fixed: {"text", "fix_label", "fix_url"}, or
        None when it passes. Read from the gate's one reading (_qc_gate).
        A blank limit not set and a QC type not judged link the method's
        QC criteria; a failure no qualifier is mapped for links the QC
        Qualifiers; a failure alone names its QC types and links the tab
        that shows them, never the limits. A cell with a failure among its
        records reads failed."""
        qc = qc or {}
        if qc.get("error") or qc.get("overall_pass"):
            return None
        gate = self._qc_gate(qc)
        unset = gate["unset"]
        criteria = self.editor_url(u"pane-qc")
        failing, unjudged, unmapped = [], [], []
        cells = [(qt, c) for qt, _a, c in gate["failing"] + gate["unevaluated"]]
        cells += [(f.get("qc_type"), f) for f in gate["run"]]
        for qt, c in cells:
            if not qt:
                continue
            if c.get("status") == "fail":
                if qt not in failing:
                    failing.append(qt)
                continue
            if c.get("unmapped") and c["unmapped"] not in unmapped:
                unmapped.append(c["unmapped"])
            if (c.get("unjudged") or not c.get("unmapped")) and qt not in unjudged:
                unjudged.append(qt)
        parts = []
        if unset:
            parts.append(u"%s %s not set for %s" % (u" and ".join(unset),
                         u"limit" if len(unset) == 1 else u"limits", self.method_label()))
        if failing:
            parts.append(u"%s failed" % u", ".join(failing))
        mf = self.missing_matrix_factor() if unjudged else None
        no_factor = [qt for qt in unjudged if mf and qt in self._SAMPLE_BASIS_SPIKES]
        other = [qt for qt in unjudged if qt not in no_factor]
        if no_factor:
            parts.append(u"%s not judged: no matrix factor for %s" % (u", ".join(no_factor), mf["matrix"]))
        if other:
            parts.append(u"%s not judged" % u", ".join(other))
        if unmapped:
            parts.append(u"no qualifier mapped for %s" % u", ".join(unmapped))
        if not parts:
            return None
        if no_factor and not unset and not other:
            fix_label, fix_url = u"Matrices", mf["url"]
        elif unset or unjudged:
            fix_label, fix_url = (u"QC criteria" if criteria else u""), criteria
        elif unmapped:
            fix_label, fix_url = u"QC Qualifiers", u"%s/@@pfas-qc-qualifiers" % self.portal_url()
        else:
            # the tab that shows the failure; a blank's is the one the
            # verdict is on, so no button
            tabs = [t for t in (self._qc_tab(qt) for qt in failing) if t and t[0] != u"qc_summary"]
            fix_url, fix_label = (self.review_url(tabs[0][0]), tabs[0][1]) if tabs else (u"", u"")
        return {"text": u"; ".join(parts), "fix_label": fix_label, "fix_url": fix_url}

    # ── Final Data: a qualifier the whole table carries, said once ───────

    @staticmethod
    def _codes(row):
        return [c.strip() for c in (row.get("qc_codes") or u"").split(u",") if c.strip()]

    def common_codes(self, rows):
        """The QC qualifier codes every result of the table carries (a table
        of two or more), stated once above it; the rows show a chip only for
        the codes beyond these. [] otherwise."""
        # a withheld result is not reported: it carries nothing to state
        rows = [r for r in rows or [] if not r.get("withheld")]
        if len(rows) < 2:
            return []
        common = set(self._codes(rows[0]))
        for r in rows[1:]:
            common &= set(self._codes(r))
        return sorted(common)

    def code_label(self, code):
        """What a qualifier code stands for: the label of the qualifier
        library's entries that carry it ("or" between several)."""
        try:
            from senaite.pfas.qc_qualification import get_library
            labels = []
            for _k, entry in sorted(get_library(self._portal()).items()):
                if entry.get("code") == code and entry.get("label") not in labels:
                    labels.append(entry.get("label"))
            return u" or ".join(labels)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("code_label: %s", exc)
            return u""

    def code_meanings(self):
        """{code: what it means}, as the certificate's legend words it: the
        wording each code carries in this worksheet's plan (the QC
        Qualifiers library's, a rule's flag's included), and J's reporting
        rule. Read once per request."""
        if "_code_meanings" not in self.__dict__:
            said = {}
            try:
                ws = self._get_worksheet()
                summary = self._get_qc_summary(ws) if ws is not None else {}
            except Exception as exc:                        # noqa: BLE001
                logger.warning("code meanings: %s", exc)
                summary = {}
            for e in (summary or {}).get("qualifiers") or []:
                code, text = e.get("code") or u"", (e.get("statement") or u"").strip()
                if code and text and text not in said.setdefault(code, []):
                    said[code].append(text)
            from senaite.pfas.coa_format import J_CODE
            if self.estimate_meaning():
                said.setdefault(J_CODE, [])
                if self.estimate_meaning() not in said[J_CODE]:
                    said[J_CODE].insert(0, self.estimate_meaning())
            self._code_meanings = dict((c, u"; ".join(t.rstrip(u".") for t in ts)) for c, ts in said.items() if ts)
        return self._code_meanings

    def final_data_legend(self, rows):
        """[{"code", "line"}]: the legend under Final Data, one line per
        code its rows carry in the certificate's words (coa_format.legend_lines)."""
        from senaite.pfas import coa_format
        meanings = self.code_meanings()
        as_cert = []
        for r in rows or []:
            if r.get("withheld"):
                continue
            codes = self._codes(r)
            as_cert.append({"estimated": bool(r.get("rule_code")), "qc_codes": codes,
                            "qc_statements": dict((c, [meanings.get(c) or u""]) for c in codes)})
        return coa_format.legend_lines(as_cert, {coa_format.J_CODE: self.estimate_meaning()})

    def common_codes_line(self, rows):
        """"All 12 results carry H (Sample receipt not compliant)", or u""."""
        codes = self.common_codes(rows)
        if not codes:
            return u""
        named = []
        for code in codes:
            label = self.code_label(code)
            named.append(u"%s (%s)" % (code, label) if label else code)
        return u"All %d results carry %s" % (len(rows), u" and ".join(named))

    def active_deviations_for_worksheet(self):
        """Return open deviations/CARs that reference the current worksheet."""
        ws = self._get_worksheet()
        if not ws:
            return []
        ws_id = ws.getId()
        try:
            from senaite.pfas.qc_deviation import get_registry
            registry = get_registry(self._portal())
            return [
                d for d in registry
                if d.get("status") != "closed"
                and ws_id in d.get("affected_worksheets", [])
            ]
        except Exception as exc:
            logger.error("active_deviations_for_worksheet: %s", exc)
            return []

    # ── POST dispatch ─────────────────────────────────────────────────────

    def _redirect_with_msg(self, msg, msg_type="ok", tab=None, detail=None, extra=u""):
        ws = self._get_worksheet()
        if ws:
            base = ws.absolute_url() + "/@@pfas-data-review"
        else:
            base = self.context.absolute_url() + "/@@pfas-data-review"
        url = "{0}?msg={1}&msg_type={2}".format(base, msg, msg_type)
        if tab:
            url += "&tab={0}".format(tab)
        if detail:
            from six.moves.urllib.parse import quote
            url += "&detail={0}".format(quote(detail.encode("utf-8"), safe=""))
        self.request.response.redirect(url + extra)
        return u""

    # ── Corrections (ISO 17025: traceable, initialed + dated) ─────────────
    CORRECTIONS_KEY = u"senaite.pfas.data_review.corrections"
    def signature_for(self, initials):
        """Signature image URL + fullname for a set of initials (staff pool) —
        appended next to sign-offs so documents carry the person's signature."""
        try:
            from senaite.pfas.staff import find_by_initials
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            return find_by_initials(portal, initials) or {}
        except Exception:
            return {}

    def _report_ars(self):
        """The samples a report from this worksheet covers: its own (its
        analyses' samples); a worksheet with no analyses yet, the batch join
        (_batch_ars). Never every sample of the client Batch, which may sit
        on other worksheets."""
        from senaite.pfas.core_fields import samples_of
        ws = self._get_worksheet()
        own = list(samples_of(ws)) if ws is not None else []
        return own or self._batch_ars()

    def _issue_ars(self):
        """The samples a certificate is generated and issued for now: the
        worksheet's own; before its run is verified, those an interim
        certificate waits on when any does (only they may issue then)."""
        ars = self._report_ars()
        if self.ws_state() in self.VERIFIED_STATES:
            return ars
        from senaite.pfas.browser.controlled_publications import pending_signature
        interim = [ar for ar in ars if (pending_signature(ar) or {}).get("interim")]
        return interim or ars

    def publish_url(self):
        """senaite.impress COA (publish) view pre-loaded with this
        worksheet's samples — the client-facing report step (core reuse);
        before verification, the samples an interim certificate waits on."""
        from senaite.pfas.browser.view_helpers import publisher_url
        ars = self._issue_ars()
        if not ars:
            return u""
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        return publisher_url(portal.absolute_url() + u"/samples", [ar.UID() for ar in ars])

    def template_status(self):
        """The issued reporting-template revision the certificate will be drawn
        from, or None when none is issued (publishing is then refused)."""
        try:
            from senaite.pfas.report_templates import issued_snapshot
            return issued_snapshot(self._portal())[1]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("template_status: %s", exc)
            return None

    def certificate_layout_problem(self):
        """Why no certificate can be issued now (no certificate layout
        issued), or None. Read as the publish guard and the certificate
        storage read it."""
        try:
            from senaite.pfas import report_templates as rt
            return rt.certificate_layout_problem(rt.issued_snapshot(self._portal())[0])
        except Exception as exc:                            # noqa: BLE001
            logger.warning("certificate_layout_problem: %s", exc)
            from senaite.pfas.report_templates import LAYOUT_NEEDED
            return LAYOUT_NEEDED

    def reissue_ars(self):
        """ARs in this worksheet's batch that are already published — issuing a
        CoA for them is an AMENDED reissue. We capture an amendment reason
        up front so the controlled register records why (best-effort policy)."""
        from bika.lims import api as _bapi
        out = []
        for ar in self._report_ars():
            try:
                # an interim certificate issued before verification leaves
                # the sample unpublished: its register says it was issued
                if _bapi.get_review_status(ar) == "published" or self._issued_before(ar):
                    out.append(ar)
            except Exception:
                pass
        return out

    def _issued_before(self, ar):
        """True when the sample's register holds an issued revision."""
        from senaite.pfas.browser.controlled_publications import get_publication_log
        return bool(get_publication_log(ar))

    def is_reissue(self):
        return bool(self.reissue_ars())

    def needs_assignment(self):
        """True while this worksheet holds no analyses: its samples are added
        on @@pfas-worksheet-samples before any result is entered. A method
        study's worksheet holds none by design."""
        ws = self._get_worksheet()
        if ws is None or self.study_run() is not None:
            return False
        try:
            return not ws.getRawAnalyses()
        except Exception:                                   # noqa: BLE001
            return False

    def corrections(self):
        """Correction log for this worksheet (rendered in Final Review)."""
        ws = self._get_worksheet()
        if not ws:
            return []
        try:
            raw = IAnnotations(ws).get(self.CORRECTIONS_KEY)
            return json.loads(raw) if raw else []
        except Exception:
            return []

    def _handle_post(self):
        action = self.request.form.get("action", "")
        dispatch = {
            "check_item":               self._handle_check_item,
            "submit_for_review":        self._handle_submit_for_review,
            "approve_release":          self._handle_approve_release,
            "reject":                   self._handle_reject,
            "upload_instrument_report": self._handle_upload_instrument_report,
            "download_report":          self._handle_download_report,
            "sign_certificate":         self._handle_sign_certificate,
            "issue_email":              self._handle_issue_email,
            "record_spike_level":       self._handle_record_spike_level,
            "request_run":              self._handle_request_run,
            # a result above the range reported with E instead of a dilution
            "report_above_range":       self._handle_report_above_range,
            # a result the instrument wrote BLoQ with no number: the reason
            "resolve_no_number":        self._handle_resolve_no_number,
            "clear_run_plan":           self._handle_clear_run_plan,
            "choose_subtraction_blank": self._handle_choose_subtraction_blank,
            "approve_calibration":      self._handle_approve_calibration,
            "reject_calibration":       self._handle_reject_calibration,
            # a lot pending acceptance, on its traceability node
            "approve_lot":              self._handle_lot_review,
            "reject_lot":               self._handle_lot_review,
            # a raw run's peak edited by hand (the Integration Review tab)
            "raw_edit":                 self._handle_raw_edit,
            "raw_pull_again":           self._handle_raw_pull_again,
            # one trace's change applied to every injection, and its undo
            "raw_apply_all":            self._handle_raw_apply_all,
            "raw_processing_undo":      self._handle_raw_processing_undo,
            # a processing change proposed as the method's own: no review
            # record changes, so not a record action
            "propose_processing":       self._handle_propose_processing,
            # the Integration Review changes' reasons and the analyst's initials
            "save_manual_changes":      self._handle_manual_changes,
            # an injection's identity corrected, or the correction undone
            "correct_identity":         self._handle_correct_identity,
            "revert_identity":          self._handle_correct_identity,
            # the verifier confirms one (a verification act, not the review record's)
            "confirm_identity":         self._handle_confirm_identity,
            # the verifier sends the submitted worksheet back to the analyst
            "send_back_review":         self._handle_send_back_review,
        }
        handler = dispatch.get(action)
        if handler and action in self.RECORD_ACTIONS and self.ws_state() in self.CLOSED_STATES:
            # the checklist and its signatures ARE the technical review: once
            # submitted they are read-only. A replayed sign-off overwrote a
            # verified worksheet's signatures so its submission postdated its
            # approval, leaving no trace
            if action in ("raw_edit", "raw_apply_all", "raw_processing_undo") and self._wants_json():
                return self._raw_reply(False, kind="record_closed", error=self._MSG_TEXTS["record_closed"],
                                       status=409)
            return self._redirect_with_msg("record_closed", "error")
        if handler:
            return handler()
        self.request.response.redirect(self.request.URL)
        return u""

    # the actions that change the review record, and the states that close it
    RECORD_ACTIONS = frozenset((
        "check_item", "submit_for_review",
        "upload_instrument_report", "record_spike_level", "request_run", "report_above_range",
        "resolve_no_number", "clear_run_plan", "choose_subtraction_blank", "approve_calibration",
        "reject_calibration", "approve_lot", "reject_lot", "raw_edit", "raw_apply_all", "raw_processing_undo",
        "save_manual_changes", "correct_identity", "revert_identity"))
    CLOSED_STATES = frozenset(("to_be_verified", "verified", "published"))
    # past release: the Integration Review changes must carry the verifier's countersignature
    VERIFIED_STATES = frozenset(("verified", "published"))

    # ── The run's calibration ─────────────────────

    def _run_manifest(self, ws):
        try:
            from senaite.pfas.browser.run_builder import RUN_MANIFEST_KEY
            raw = IAnnotations(ws).get(RUN_MANIFEST_KEY)
            return json.loads(raw) if raw else {}
        except Exception:                                   # noqa: BLE001
            return {}

    def calibration_review(self):
        """The calibration this run is reviewed on: its own curves, or the
        earlier approved curve it reused (run_calibration.review_state): its
        status, source and run date. The gate and the warnings strip read
        only these, on every tab; the curve cards are the Calibration tab's
        own (calibration_cards_json). Once per request."""
        if hasattr(self, "_cal_review"):
            return self._cal_review
        from senaite.pfas import run_calibration as rc
        state, scope = rc.review_state([], {}, []), None
        ws = self._get_worksheet()
        self._cal_batches = [ws.getId()] if ws is not None else []
        if ws is not None and self.db_available:
            try:
                store = self._store()
                own = store.calibrations_for_batch(ws.getId())
                manifest = self._run_manifest(ws)
                rd = rc.reused_run_date(manifest)
                reused = (store.get_calibrations_for_run(rd, method=self.batch_method())
                          if (rd and not own) else [])
                state = rc.review_state(own, manifest, reused, ws.getId())
                # the worksheets whose worker judged a curve this worksheet
                # used: its own and those that ran the curves it re-used. An
                # earlier curve only the Run Builder names is read by none
                self._cal_batches = sorted(set(self._cal_batches) | set(
                    r.get("batch_id") for r in own if r.get("batch_id")))
                # the curves the cards draw: the worksheet's own on record
                # (one re-used from another worksheet among them), else the
                # earlier curve the manifest names
                if own:
                    scope = {"batch_id": ws.getId()}
                elif state["source"] == u"reused":
                    scope = {"run_date": rd, "method": self.batch_method()}
            except Exception as exc:                        # noqa: BLE001
                logger.warning("calibration_review: %s", exc)
        self._cal_review, self._cal_cards_scope = state, scope
        return state

    def calibration_rule_rows(self):
        """The failing Calibration QC rows that name calibrators dropped by
        hand, for the curves this run is reviewed on (run_calibration.
        failed_rule_rows): the worker's verdict on its most-calibrators-
        dropped rule, which the pages read and never count again. Once per
        request."""
        if hasattr(self, "_cal_rule_rows"):
            return self._cal_rule_rows
        from senaite.pfas import run_calibration as rc
        from senaite.pfas.browser.calibrations import calibration_qc_rows
        self.calibration_review()
        rows = []
        if self.db_available:
            for bid in self._cal_batches:
                try:
                    rows += calibration_qc_rows(self._store(), bid)
                except Exception as exc:                    # noqa: BLE001
                    logger.warning("calibration rule rows %s: %s", bid, exc)
        self._cal_rule_rows = rc.failed_rule_rows(rows)
        return self._cal_rule_rows

    def calibration_own_rule_rows(self):
        """calibration_rule_rows of this worksheet's own worker only: the
        Raw tab lists calibrators of the run it shows, never another
        worksheet's."""
        ws = self._get_worksheet()
        wid = ws.getId() if ws is not None else None
        return [r for r in self.calibration_rule_rows() if r.get("batch_id") == wid]

    def calibration_hold(self):
        """Why the run's calibration cannot be approved while a curve fails
        its dropped-by-hand rule, u"" when none does. The Approve button and
        the refused post say this one sentence."""
        from senaite.pfas import run_calibration as rc
        return rc.hold_reason(rc.dropped_rules(self.calibration_rule_rows()))

    def calibration_cards_json(self):
        """The Calibration tab's curve cards (the calibrations view's
        calibration_runs_json) for the curves calibration_review found;
        "[]" when there are none. Built only by the tab that draws them."""
        self.calibration_review()
        scope = getattr(self, "_cal_cards_scope", None)
        if not scope:
            return u"[]"
        try:
            from senaite.pfas.browser.calibrations import PFASCalibrationsView
            cv = PFASCalibrationsView(self._portal(), self.request)
            try:
                from senaite.pfas import raw_review
                levels = dict((i.get("name"), i.get("level")) for i in self._raw_record().get("injections") or [])
                rows = self._raw_rows()
                cv.excluded_by_hand = dict(
                    (label, raw_review.manual_excluded(rows, key, levels))
                    for key, label in set((r.get("analyte"), r.get("label")) for r in rows))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("calibrators dropped by hand: %s", exc)
            return cv.calibration_runs_json(**scope)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("calibration cards: %s", exc)
            return u"[]"

    def calibration_approve_json(self):
        """The approve / reject bar's settings for the shared curve script."""
        st = self.calibration_review()
        ws = self._get_worksheet()
        return json.dumps({"url": (ws.absolute_url() if ws is not None else u"") + u"/@@pfas-data-review",
                           "can": bool(self.can_act()), "reused": st.get("source") == u"reused",
                           "from": st.get("from") if st.get("source") == u"reused" else u"",
                           "state": st.get("status"), "hold": self.calibration_hold()})

    def _handle_approve_calibration(self):
        """The analyst approves the run's calibration at review: release waits
        for it; the manager's verification covers it."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        initials = (self.request.form.get("initials") or "").strip()
        if not initials:
            return self._redirect_with_msg("initials_required", "error", tab="calibration")
        user = getSecurityManager().getUser()
        if _actor_kind(user) == u"automated":
            return self._redirect_with_msg("permission_denied", "error")
        state = self.calibration_review()
        hold = self.calibration_hold()
        if hold:
            return self._redirect_with_msg("calibration_held", "error", tab="calibration", detail=hold)
        # a curve this worksheet used, its own or re-used: approved once;
        # one only named by the Run Builder is not
        # on record here and cannot be approved from this worksheet
        if not self._store().calibrations_for_batch(ws.getId()):
            return self._redirect_with_msg("calibration_not_own", "error", tab="calibration")
        n = self._store().approve_run(state["run_date"], approved_by=u"%s (%s)" % (user.getId(), initials),
                                      batch_id=ws.getId())
        self._audit(ws)
        return self._redirect_with_msg("calibration_approved" if n else "calibration_not_own",
                                       "ok" if n else "error", tab="calibration")

    def _handle_reject_calibration(self):
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        note = (self.request.form.get("note") or "").strip()
        if not note:
            return self._redirect_with_msg("calibration_note_required", "error", tab="calibration")
        user = getSecurityManager().getUser()
        if _actor_kind(user) == u"automated":
            return self._redirect_with_msg("permission_denied", "error")
        ok = self._store().reject_run(ws.getId(), user.getId(), note)
        self._audit(ws)
        return self._redirect_with_msg("calibration_rejected" if ok else "calibration_not_own",
                                       "ok" if ok else "error", tab="calibration")

    def run_plan_items(self):
        """The run compared with its plan: each
        difference, open (holding release) or cleared with its note."""
        ws = self._get_worksheet()
        if ws is None or not self.db_available:
            return []
        try:
            return self._store().run_plan_rows(ws.getId())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("run_plan_items: %s", exc)
            return []

    SUBTRACTION_CHANGES_KEY = "senaite.pfas.subtraction_blank_changes"

    def method_blank_members(self):
        """The worksheet's method blanks (extraction batch members)."""
        from senaite.pfas import extraction_batch as eb
        ws = self._get_worksheet()
        return [m for m in eb.load(ws) if m.get("role") == u"MB"] if ws else []

    def subtraction_blank_changes(self):
        ws = self._get_worksheet()
        try:
            return json.loads(IAnnotations(ws).get(self.SUBTRACTION_CHANGES_KEY) or u"[]") if ws else []
        except (TypeError, ValueError):
            return []

    def subtraction_change_pending(self):
        """True when the subtraction blank was changed after the run's QC was
        last written: the results still use the earlier blank until the run is
        reprocessed, and release waits for it."""
        changes = self.subtraction_blank_changes()
        ws = self._get_worksheet()
        if not changes or ws is None or not self.db_available:
            return False
        try:
            row = self._store().get_batch(ws.getId()) or {}
        except Exception:                                   # noqa: BLE001
            return False
        return changed_after(changes[-1].get("at"), row.get("updated_at") or row.get("created_at"))

    def ws_url(self):
        ws = self._get_worksheet()
        return ws.absolute_url() if ws else self.context.absolute_url()

    def _handle_choose_subtraction_blank(self):
        """The reviewer changes the blank results are compared with / taken
        from. A reason is required and kept; the run is
        reprocessed for the results to follow."""
        from senaite.pfas import extraction_batch as eb
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        reason = (self.request.form.get("reason") or "").strip()
        if not reason:
            return self._redirect_with_msg("subtraction_blank_reason", "error", tab="qc_summary")
        members = eb.load(ws)
        before = (eb.subtraction_blank(members) or {}).get("injection") or u""
        if eb.mark_subtraction_blank(members, self.request.form.get("member") or u""):
            return self._redirect_with_msg("subtraction_blank_invalid", "error", tab="qc_summary")
        eb.save(ws, members)
        after = (eb.subtraction_blank(members) or {}).get("injection") or u""
        changes = self.subtraction_blank_changes() + [{
            "from": before, "to": after, "reason": reason,
            "by": getSecurityManager().getUser().getId(),
            "at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}]
        IAnnotations(ws)[self.SUBTRACTION_CHANGES_KEY] = json.dumps(changes)
        self._audit(ws)
        return self._redirect_with_msg("subtraction_blank_changed", "ok", tab="qc_summary")

    # ── The extraction record corrected (extraction_amendments) ─────
    # The corrections are made on the batch record page and posted to
    # @@pfas-extraction-corrections; Data Review reads them: what to
    # confirm at Verify, whether the run is judged with them, which rows
    # are withheld, and the way to each window.

    EXTRACTION_PENDING = (u"An extraction correction is recorded: waiting for the run to be "
                          u"judged or filed again.")

    def _extraction_state(self):
        from senaite.pfas import extraction_amendments as ea
        ws = self._get_worksheet()
        if ws is None:
            return ea.empty()
        return ea.load(IAnnotations(ws).get(ea.KEY))

    def _extraction_members(self, ws):
        """The members as everything downstream reads them (in force)."""
        if "_extraction_members_memo" in self.__dict__:
            return self._extraction_members_memo
        from senaite.pfas import extraction_amendments as ea
        from senaite.pfas import extraction_batch
        try:
            members = ea.members_in_force(extraction_batch.load(ws) or [], self._extraction_state())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("extraction members: %s", exc)
            members = []
        self._extraction_members_memo = members
        return members

    def extraction_applied(self):
        """The extraction corrections the stored run was judged with; []
        while the provenance store cannot say, so release keeps waiting."""
        if "_extraction_applied" in self.__dict__:
            return self._extraction_applied
        out = []
        bid = self.batch_id()
        if bid and self.db_available:
            try:
                from senaite.pfas.provenance_store import ProvenanceStore
                applied = getattr(ProvenanceStore(DEFAULT_DB_PATH), "amendments_applied", None)
                out = list(applied(bid) or []) if applied is not None else []
            except Exception as exc:                        # noqa: BLE001
                logger.warning("extraction amendments applied: %s", exc)
        self._extraction_applied = out
        return out

    def extraction_pending(self):
        """The corrections in force the stored run was not yet judged with;
        [] when none."""
        from senaite.pfas import extraction_amendments as ea
        state = self._extraction_state()
        if not state["log"]:
            return []
        # an amendment made after release is signed as the record's next
        # revision; the released run is not judged again, so it holds nothing
        later = set(e.get("id") for e in state["log"] if e.get("after_release"))
        out = [i for i in ea.pending(state, self.extraction_applied()) if i not in later]
        # a send back to the data import waits for the run filed after it
        sent = ea.send_back_pending(state, self._run_filed_at())
        if sent is not None:
            out.append(sent.get("id"))
        return out

    def _run_filed_at(self):
        """When the run's QC was last written for this worksheet, or None."""
        ws = self._get_worksheet()
        if ws is None or not self.db_available:
            return None
        try:
            row = self._store().get_batch(ws.getId()) or {}
        except Exception:                                   # noqa: BLE001
            return None
        return row.get("updated_at") or row.get("created_at")

    def extraction_verify_refusal(self):
        """Why Verify waits on the extraction corrections, or u""."""
        from senaite.pfas import extraction_amendments as ea
        return ea.verify_refusal(self._extraction_state()) or u""

    def _record_url(self, ws, opens=u"", member=u""):
        """The worksheet's batch record page, opening one of its windows."""
        url = u"%s/@@pfas-batch-records?record=%s" % (self.portal_url(), ws.UID())
        if opens:
            url += u"&open=%s" % opens
        if member:
            from six.moves.urllib.parse import quote
            url += u"&member=%s" % quote(member.encode("utf-8"), safe="")
        return url

    def _extraction_to_confirm(self):
        """The extraction corrections in force, as Verify lists them beside
        the identity corrections ({injection, change, reason, by, when,
        confirmed, confirmed_text, actions}). Only a submitted worksheet's
        verifier acts on them; one made by the verifier is shown, refused."""
        from senaite.pfas import extraction_amendments as ea
        from senaite.pfas import row_menu
        ws = self._get_worksheet()
        state = self._extraction_state()
        if ws is None or not state["log"]:
            return []
        members = self._extraction_members(ws)
        who = getSecurityManager().getUser().getId()
        mine = self.is_manager() and self.ws_state() == "to_be_verified"
        out = []
        for e in ea.to_confirm(state):
            act = None
            if mine:
                act = (u"Confirm the correction", "form", "dr-extraction-confirm",
                       {"values": {"entry": e.get("id")},
                        "off": ea.OWN.format(e.get("id")) if e.get("by") == who else None})
            change = ea.describe(e, members)
            if e.get("action") == ea.AMEND:
                change = u"%s: %s to %s" % (change, e.get("from") or u"not recorded", e.get("to") or u"")
            out.append({"injection": e.get("id") or u"", "change": change,
                        "reason": e.get("reason") or u"", "by": e.get("name_by") or e.get("by") or u"",
                        "when": lab_time.show(e.get("at")) if e.get("at") else u"",
                        "confirmed": None, "confirmed_text": u"Not confirmed",
                        "actions": row_menu.actions(act, (u"Open the batch record", "href",
                                                          self._record_url(ws)))})
        return out

    def _amend_links(self, ws):
        """{injection name: the batch record's Amend window for its member}:
        every name a member answers to (in force, and the name issued)."""
        out = {}
        for m in self._extraction_members(ws) if ws is not None else []:
            url = self._record_url(ws, u"amend", m.get("id") or u"")
            for name in [m.get("injection")] + list(m.get("aliases") or []):
                if name:
                    out[name] = url
        return out

    def send_back_url(self):
        """Overview's Send back: the batch record's window, for an Analyst
        or a Lab Manager while open, a Lab Manager once submitted; u""
        otherwise."""
        ws = self._get_worksheet()
        state = self.ws_state()
        if ws is None or self.study_run() is not None:
            return u""
        if not ((self.can_act() and state == "open") or (self.is_manager() and state == "to_be_verified")):
            return u""
        return self._record_url(ws, u"send_back")

    def _withheld_rows(self, rows, inj):
        """Final Data with the samples withheld for re-extraction kept
        listed, greyed and tagged (a withheld sample's analyses have left the
        worksheet: its row is drawn from the instrument's rows, values
        still readable); every other sample's rows offer Needs
        re-extraction."""
        ws = self._get_worksheet()
        members = [m for m in self._extraction_members(ws) if m.get("role") == u"Sample"] if ws else []
        held = dict((m.get("sample_id"), m) for m in members if m.get("withheld"))
        ask = dict((m.get("sample_id"), self._record_url(ws, u"reextract", m.get("id") or u""))
                   for m in members if not m.get("withheld")) if self.can_act() else {}
        seen = set()
        for r in rows:
            sid = r.get("sample_id")
            if sid in held:
                r["withheld"] = True
                seen.add(sid)
            else:
                r["reextract_url"] = ask.get(sid, u"")
        for sid in sorted(k for k in held if k and k not in seen):
            for part in inj.get(sid) or [{}]:
                value = part.get("result")
                rows.append({"sample_id": sid, "analyte": part.get("analyte") or u"", "title": u"",
                             "client_sample_id": held[sid].get("client_sid") or u"", "sample_type": u"",
                             "instrument": (u"%.4g" % value) if isinstance(value, (int, float)) else u"",
                             "instrument_parts": u"", "rt": u"", "rt_parts": u"",
                             "injection": part.get("injection_name") or u"", "instrument_prov": None,
                             "result_prov": None, "result": u"", "unit": u"", "qualifier": u"",
                             "rule_code": u"", "qc_codes": u"", "qc_reasons": u"", "qc_pairs": [],
                             "qc_cell": None, "review_state": u"", "reported": u"", "state": u"",
                             "withheld": True})
        return rows

    # ── An injection's identity, corrected at review ─────────────────
    # (injection_identity: the overlay, its refusals and its requeue)

    IDENTITY_PENDING = (u"An injection's identity was corrected: waiting for the run to be "
                        u"judged again.")

    def _identity_state(self):
        from senaite.pfas import injection_identity as ii
        ws = self._get_worksheet()
        if ws is None:
            return ii.empty()
        return ii.load(IAnnotations(ws).get(IDENTITY_KEY))

    def identity_applied(self):
        """{injection: correction id} the stored run was judged with."""
        if "_identity_applied" in self.__dict__:
            return self._identity_applied
        out = {}
        bid = self.batch_id()
        if bid and self.db_available:
            try:
                from senaite.pfas.provenance_store import ProvenanceStore
                out = ProvenanceStore(DEFAULT_DB_PATH).identity_applied(bid)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("identity applied: %s", exc)
        self._identity_applied = out
        return out

    def identity_pending(self):
        """The injections whose correction the stored run was not yet
        judged with (in force against applied); [] when none."""
        from senaite.pfas import injection_identity as ii
        state = self._identity_state()
        if not state["log"]:
            return []
        return ii.pending(state, self.identity_applied())

    def _identity_low(self):
        """The injections a stored CCV or ICV verdict judged by the
        Low-Level window (its basis names the lowest level)."""
        conn = self._raw_connect()
        if conn is None:
            return set()
        try:
            rows = conn.execute(
                "SELECT DISTINCT qc_level FROM qc_results WHERE batch_id=? AND qc_type IN ('CCV', 'ICV') "
                "AND limit_basis LIKE '%lowest level%' AND result_status != 'superseded'",
                (self.batch_id(),)).fetchall()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("identity low level: %s", exc)
            rows = []
        finally:
            conn.close()
        return set((r[0] or u"").split(u"|")[0] for r in rows)

    def _identity_members(self, ws):
        from senaite.pfas import extraction_batch
        from senaite.pfas.dilution_ref import get_dilutions
        try:
            members = [m.get("injection") for m in extraction_batch.load(ws) or [] if m.get("injection")]
        except Exception:                                   # noqa: BLE001
            members = []
        try:
            dilutions = list((get_dilutions(ws) or {}).keys())
        except Exception:                                   # noqa: BLE001
            dilutions = []
        return members, dilutions

    def _identity_filed(self, ws):
        """The injections whose results the worker filed on a SENAITE sample
        (the push log, written)."""
        try:
            return set(p.get("injection") for p in self._result_pushes(ws.getId()) if p.get("ok"))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("identity: push log unread: %s", exc)
            return set()

    def identity_to_confirm(self):
        """The corrections in force as Verify lists them: {injection,
        change, reason, by, when, confirmed (the confirm entry or None),
        actions}. Only a submitted worksheet's verifier acts on them."""
        from senaite.pfas import injection_identity as ii
        from senaite.pfas import row_menu
        state = self._identity_state()
        done = ii.confirmed(state)
        who = getSecurityManager().getUser().getId()
        mine = self.is_manager() and self.ws_state() == "to_be_verified"
        out = []
        for inj, e in sorted(ii.in_force(state).items()):
            c = done.get(inj)
            off = None
            if e.get("by") == who:
                off = ii.OWN.format(inj)
            act = None
            if mine and c is None:
                act = (u"Confirm the correction", "form", "dr-identity-confirm",
                       {"values": {"injection": inj}, "off": off})
            out.append({"injection": inj,
                        "change": u"{0} to {1}".format(ii.label(e.get("from")), ii.label(e.get("to"))),
                        "from_code": e.get("from") or u"", "to_code": e.get("to") or u"",
                        "from_label": ii.label(e.get("from")), "to_label": ii.label(e.get("to")),
                        "reason": e.get("reason") or u"", "by": e.get("by") or u"",
                        "when": lab_time.show(e.get("at")) if e.get("at") else u"",
                        "confirmed": c,
                        "confirmed_text": (u"{0}, {1}".format(c.get("name") or c.get("by"),
                                                              lab_time.show(c.get("at")))
                                           if c else u"Not confirmed"),
                        "actions": row_menu.actions(act)})
        # the extraction corrections are confirmed in the same list
        out.extend(self._extraction_to_confirm())
        return out

    def identity_undo_lines(self):
        from senaite.pfas import injection_identity as ii
        return ii.undo_lines()

    def identity_unconfirmed(self):
        from senaite.pfas import injection_identity as ii
        return ii.unconfirmed(self._identity_state())

    def identity_closed(self):
        """Why no identity is corrected now (the person or the state), or u""."""
        from senaite.pfas import injection_identity as ii
        return (ii.actor_refusal(self.can_act(), _actor_kind(getSecurityManager().getUser()))
                or ii.state_refusal(self.ws_state()) or u"")

    def identity_offered(self):
        """[{code, label}] of the roles this method offers."""
        from senaite.pfas import injection_identity as ii
        return [{"code": c, "label": ii.label(c)} for c in ii.offered_roles(self._method_profile())]

    def identity_what_json(self):
        """{current: {target: [sentence]}}: what each change judges again,
        for the window."""
        from senaite.pfas import injection_identity as ii
        offered = ii.offered_roles(self._method_profile())
        return json.dumps(dict((cur, dict((t, ii.rejudged(cur, t)) for t in offered if t != cur))
                               for cur in ii.CORRECTABLE), sort_keys=True)

    def identity_injections(self):
        """The run's injections, in run order, as the Injections table lists
        them: {injection, role, role_label, sample_id, compounds, entry,
        marker, actions}."""
        if "_identity_rows" in self.__dict__:
            return self._identity_rows
        from senaite.pfas import injection_identity as ii
        from senaite.pfas import row_menu
        ws = self._get_worksheet()
        rows = _run_order(self._injection_rows())
        state = self._identity_state()
        forced = ii.in_force(state)
        if ws is None or not (rows or forced):
            self._identity_rows = []
            return []
        low = self._identity_low()
        members, dilutions = self._identity_members(ws)
        waiting = set(ii.pending(state, self.identity_applied()))
        closed = self.identity_closed()
        # a member's role belongs to the extraction record: amended there
        amend = self._amend_links(ws)
        order, by = [], {}
        for r in rows:
            name = r.get("injection_name") or u""
            if not name:
                continue
            if name not in by:
                order.append(name)
                by[name] = {"injection": name, "qc_type": r.get("qc_type") or u"",
                            "sample_id": r.get("sample_id") or u"", "compounds": set()}
            by[name]["compounds"].add(r.get("analyte") or u"")
        # an injection corrected to Not judged has no rows once the run is
        # judged again: it stays listed, from its record
        for name in sorted(forced):
            if name not in by:
                order.append(name)
                by[name] = {"injection": name, "qc_type": forced[name].get("from") or u"",
                            "sample_id": u"", "compounds": set()}
        out = []
        for name in order:
            row = by[name]
            role = ii.judged_role(row["qc_type"], name in low)
            entry = forced.get(name)
            shown = entry.get("to") if entry else role
            why = closed
            if not why and name in dilutions:
                why = ii.DILUTION.format(name)
            elif not why and name in members:
                why = ii.MEMBER.format(name)
            elif not why and shown not in ii.CORRECTABLE:
                why = ii.NOT_CORRECTABLE.format(name, ii.label(shown))
            acts = [(u"Correct identity\u2026", "event", "dr-identity", {"off": why})]
            if name in amend:
                acts = [(u"Amend on the extraction record\u2026", "href", amend[name])]
            if entry:
                acts.append((u"Undo the correction\u2026", "event", "dr-identity-undo",
                             {"danger": True, "off": closed}))
            out.append({
                "injection": name, "role": shown, "role_label": ii.label(shown),
                "sample_id": row["sample_id"], "compounds": len(row["compounds"]),
                "entry": entry,
                "marker": ii.marker(entry, name in waiting,
                                    lab_time.show(entry.get("at")) if entry else None) if entry else None,
                "actions": row_menu.actions(*acts)})
        self._identity_rows = out
        return out

    def identity_history(self):
        """Every correction and undo, newest first, for Overview."""
        from senaite.pfas import injection_identity as ii
        out = []
        for e in ii.history(self._identity_state()):
            out.append(dict(e, when=lab_time.show(e.get("at")) if e.get("at") else u""))
        return out

    def _identity_requeue_args(self, ws):
        from senaite.pfas.browser.run_builder import RUN_FILES_KEY, UPLOAD_DIR
        from senaite.pfas.annotation_store import read_json
        return UPLOAD_DIR, self._raw_stem(), read_json(ws, RUN_FILES_KEY, [])

    def _handle_correct_identity(self):
        """A reviewer corrects what an injection is (correct_identity) or
        undoes a correction (revert_identity). injection_identity refuses,
        before anything is written, what the person, the worksheet's state,
        the injection or the method does not allow; a reason is required.
        The entry is appended to the worksheet's log and its trail, and once
        the save commits the run is queued again: the worker judges it with
        the corrections in force, and release waits until it has."""
        from senaite.pfas import after_commit
        from senaite.pfas import injection_identity as ii
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error")
        f = self.request.form
        who = getSecurityManager().getUser()
        when = datetime.datetime.utcnow().replace(microsecond=0).isoformat()
        upload_dir, stem, files = self._identity_requeue_args(ws)
        can_requeue = ii.requeue_target(upload_dir, stem, files) is not None
        state = self._identity_state()
        if f.get("action") == "revert_identity":
            problem, state, _entry = ii.revert(
                state, f.get("injection"), f.get("reason"), who.getId(), when, self.ws_state(),
                self.can_act(), _actor_kind(who), can_requeue=can_requeue)
            done = "identity_reverted"
        else:
            judged = dict((r["injection"], r["role"]) for r in self.identity_injections())
            # the stored run's judgement, not a correction already in force
            for inj, e in ii.in_force(state).items():
                if inj in judged:
                    judged[inj] = e.get("from")
            members, dilutions = self._identity_members(ws)
            problem, state, _entry = ii.correct(
                state, f.get("injection"), f.get("to"), f.get("reason"), who.getId(), when,
                self.ws_state(), self.can_act(), _actor_kind(who), judged,
                ii.offered_roles(self._method_profile()), members=members, dilutions=dilutions,
                can_requeue=can_requeue, filed=self._identity_filed(ws))
            done = "identity_corrected"
        if problem:
            return self._redirect_with_msg("identity_refused", "error", tab="instrument_report",
                                           detail=problem)
        if _entry is not None and _entry.get("retract"):
            # the results filed on its sample are retracted with the
            # correction, in this transaction: a refusal keeps nothing
            from senaite.pfas import identity_retract as ir
            try:
                _entry["retracted"] = self._identity_retract(ws, _entry, ir)
            except ir.RetractRefused as exc:
                import transaction
                transaction.abort()
                return self._redirect_with_msg("identity_refused", "error", tab="instrument_report",
                                               detail=exc.args[0] if exc.args else u"")
        # the sign-offs over what is judged again are cleared, to be made
        # again once it is; kept on the entry and in the trail
        checklist, cleared = ii.reset_signoffs(self._get_checklist(ws))
        if cleared:
            _entry["cleared"] = cleared
            self._save_checklist(ws, checklist)
        IAnnotations(ws)[IDENTITY_KEY] = ii.dump(state)
        from senaite.pfas import records
        records.log(ws, f.get("action") or u"correct_identity", reason=(f.get("reason") or u"").strip(),
                    detail={u"injection": _entry.get("injection"), u"from": _entry.get("from"),
                            u"to": _entry.get("to"), u"cleared": [c["item"] for c in cleared]})
        # the worker reads the corrections from the run manifest only once
        # they are committed
        after_commit.run_once("identity-requeue:" + ws.getId(), ii.requeue, upload_dir, stem, files)
        return self._redirect_with_msg(done, "ok", tab="instrument_report")

    def _identity_retract(self, ws, entry, ir):
        """Retract the results the worker filed for the entry's injection
        (the push log), through core's workflow; the worksheet stays open
        (a retest is added to it), or RetractRefused."""
        from bika.lims import api as _bapi
        from bika.lims.workflow import doActionFor as _do
        uids = sorted(set(p.get("analysis_uid") for p in self._result_pushes(ws.getId())
                          if p.get("ok") and p.get("injection") == entry["injection"] and p.get("analysis_uid")))
        analyses = [a for a in (_bapi.get_object_by_uid(u, None) for u in uids) if a is not None]

        def note(an, text):
            try:
                an.setRemarks(text)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("identity retract: remark on %s: %s", _bapi.get_uid(an), exc)
        # a reopen on purpose: the guard lets these retracts run (reopen_guard)
        from senaite.pfas import reopen_guard
        with reopen_guard.allowing(self.request):
            out = ir.retract(analyses, lambda o, t: bool(_do(o, t)[0]), _bapi.get_review_status,
                             lambda a: bool((a.getResult() or u"").strip()), note, entry.get("reason"))
        if _bapi.get_review_status(ws) != "open":
            raise ir.RetractRefused(u"The worksheet did not stay open after the retraction.")
        return out

    # ── Verify sends a submitted worksheet back to the analyst ─────────

    SEND_BACK_PENDING = u"Sent back: waiting for the run to be filed again."

    def _review_send_back_state(self):
        from senaite.pfas import review_send_back as sb
        ws = self._get_worksheet()
        return sb.load(IAnnotations(ws).get(SEND_BACK_KEY)) if ws is not None else sb.empty()

    def send_back_pending(self):
        """True while the run is not filed again since the latest send back."""
        from senaite.pfas import review_send_back as sb
        state = self._review_send_back_state()
        if not state["log"]:
            return False
        ws = self._get_worksheet()
        filed = None
        if ws is not None and self.db_available:
            try:
                row = self._store().get_batch(ws.getId()) or {}
                filed = row.get("updated_at") or row.get("created_at")
            except Exception:                               # noqa: BLE001
                filed = None
        return sb.pending(state, filed)

    def send_back_reasons(self):
        """The lab's prefilled reasons (vocab_store "send_back_reasons"),
        edited in the Lists editor: the active labels, in order."""
        from bika.lims import api
        from senaite.pfas import vocab_store as vs
        return [l for _k, l in vs.choices(vs.get(api.get_portal()), "send_back_reasons")]

    def send_back_history(self):
        from senaite.pfas import review_send_back as sb
        return [dict(e, when=lab_time.show(e.get("at")) if e.get("at") else u"")
                for e in sb.history(self._review_send_back_state())]

    def _mark_interims(self, ws, entry):
        """Mark, on each sample of the worksheet whose current issue is an
        interim certificate, that the next certificate supersedes it
        (interim_certificates); its reissue reason is stashed unless one is
        pending. Returns the interims marked."""
        from senaite.pfas import interim_certificates as ic
        from senaite.pfas.interim_certificates import MARKS_KEY as INTERIM_MARKS_KEY
        from senaite.pfas.browser.controlled_publications import (
            PENDING_REASON_KEY, get_publication_log, set_pending_amendment_reason)

        def cp_has_pending_reason(ar):
            return bool(IAnnotations(ar).get(PENDING_REASON_KEY))
        marked, seen = [], set()
        for an in ws.getAnalyses() or []:
            try:
                ar = an.getRequest()
            except Exception:                               # noqa: BLE001
                continue
            if ar is None or ar.UID() in seen:
                continue
            seen.add(ar.UID())
            report_id = ic.interim_to_mark(get_publication_log(ar))
            if not report_id:
                continue
            ann = IAnnotations(ar)
            marks, mark = ic.mark_superseded(json.loads(ann.get(INTERIM_MARKS_KEY) or "[]"), report_id,
                                             entry["id"], entry["reason"], entry["by"], entry["at"])
            ann[INTERIM_MARKS_KEY] = json.dumps(marks)
            if not cp_has_pending_reason(ar):
                set_pending_amendment_reason(ar, ic.reissue_reason([mark]))
            marked.append(report_id)
        return marked

    def _handle_send_back_review(self):
        """The verifier sends the submitted worksheet back to the analyst,
        with a reason: core's worksheet retract (every analysis retracted,
        its retest on the same worksheet, the worksheet open again), the
        sign-offs the reset rule names cleared, the submission cleared, the
        entry appended and the run, when there is one, queued again to file the
        retests (a worksheet with no run file is sent back all the same). Any
        refusal keeps nothing. The e-signature ledger is not written."""
        from senaite.pfas import after_commit, records
        from senaite.pfas import injection_identity as ii
        from senaite.pfas import review_send_back as sb
        from bika.lims import api as _bapi
        from bika.lims.workflow import doActionFor as _do
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error")
        user = getSecurityManager().getUser()
        reason = (self.request.form.get("reason") or u"").strip()
        upload_dir, stem, files = self._identity_requeue_args(ws)
        why = sb.refusal(reason, self.ws_state(), self.is_manager(), _actor_kind(user))
        if why:
            return self._redirect_with_msg("send_back_refused", "error", detail=why)
        before = [a for a in (ws.getAnalyses() or []) if _bapi.get_review_status(a) == "to_be_verified"]
        import transaction
        from senaite.pfas import reopen_guard
        try:
            # the one route that reopens a submitted worksheet (reopen_guard)
            with reopen_guard.allowing(self.request):
                _do(ws, "retract")
        except Exception as exc:                            # noqa: BLE001
            transaction.abort()
            logger.error("send back: %s", exc)
            return self._redirect_with_msg("send_back_refused", "error", detail=u"%s" % exc)
        if _bapi.get_review_status(ws) != "open":
            transaction.abort()
            return self._redirect_with_msg("send_back_refused", "error",
                                           detail=u"SENAITE did not reopen the worksheet.")
        checklist, cleared = ii.reset_signoffs(self._get_checklist(ws))
        self._save_checklist(ws, sb.clear_submission(checklist))
        when = datetime.datetime.utcnow().replace(microsecond=0).isoformat()
        state, entry = sb.record(self._review_send_back_state(), reason, user.getId(), when, cleared,
                                 retracted=len(before))
        # an interim certificate issued at Submit is marked superseded by
        # the next certificate; it is never withdrawn nor altered
        entry["interims"] = self._mark_interims(ws, entry)
        IAnnotations(ws)[SEND_BACK_KEY] = sb.dump(state)
        records.log(ws, u"send_back_review", reason=reason,
                    detail={u"to": entry["to"], u"cleared": [c["item"] for c in cleared],
                            u"retracted": entry["retracted"]})
        # the retests are filed by the run, queued again once this commits
        after_commit.run_once("send-back-requeue:" + ws.getId(), ii.requeue, upload_dir, stem, files)
        return self._redirect_with_msg("review_sent_back", "ok")

    def _handle_confirm_identity(self):
        """The verifier confirms one identity correction in force: a Lab
        Manager with the reviewer sign right, never the person who made it,
        while the worksheet is submitted (injection_identity.confirm). The
        confirmation is appended to the log, which the release signature
        binds; Verify waits until every correction in force is confirmed."""
        from senaite.pfas import injection_identity as ii
        from senaite.pfas import records
        from senaite.pfas.browser import manual_integration_view as miv
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error")
        user = getSecurityManager().getUser()
        who = user.getId()
        try:
            info = miv.staff_sign_info(who)
        except ValueError as exc:
            return self._redirect_with_msg("identity_refused", "error", detail=u"%s" % exc)
        inj = self.request.form.get("injection") or u""
        problem, state, entry = ii.confirm(
            self._identity_state(), inj, who, datetime.datetime.utcnow().replace(microsecond=0).isoformat(),
            self.ws_state(), self.is_manager(), _actor_kind(user), info["sign_as"], info["name"])
        if problem:
            return self._redirect_with_msg("identity_refused", "error", detail=problem)
        IAnnotations(ws)[IDENTITY_KEY] = ii.dump(state)
        records.log(ws, u"confirm_identity", detail={u"injection": inj, u"confirms": entry["confirms"]})
        return self._redirect_with_msg("identity_confirmed", "ok")

    def _handle_clear_run_plan(self):
        """Clear one run-plan item with a note: the reviewer has seen it and
        says why the run stands (a re-injection made at the instrument, a
        QC moved to another batch...). Who, when and why are kept."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        note = (self.request.form.get("note") or "").strip()
        if not note:
            return self._redirect_with_msg("run_plan_note_required", "error", tab="qc_summary")
        user = getSecurityManager().getUser()
        if _actor_kind(user) == u"automated":
            return self._redirect_with_msg("permission_denied", "error")
        ok = self._store().clear_result(ws.getId(), self.request.form.get("result_id") or 0,
                                        user.getId(), note)
        self._audit(ws)
        return self._redirect_with_msg("run_plan_cleared" if ok else "run_plan_not_cleared",
                                       "ok" if ok else "error", tab="qc_summary")

    def _handle_sign_certificate(self):
        """The authoriser signs the certificate before it is generated: the
        signature waits on each sample of the report (always a final one:
        an interim certificate is released at Submit) and the publish guard asks for it;
        the publish subscriber binds it to the stored PDF. A reissue's
        amendment reason is kept for the register the same way. Then on to
        the publisher."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        if self.request.form.get("sign") != "1":
            # a certificate is signed only through the sign dialog
            return self._redirect_with_msg("certificate_refused", "error",
                                           detail=u"Sign the certificate to issue it.")
        from senaite.pfas.browser.controlled_publications import (
            current_is_interim, pending_signature, set_pending_amendment_reason, set_pending_signature)
        from senaite.pfas.esig import certificate as esig_certificate
        from senaite.pfas.esig import ledger, signing
        ars = self._report_ars()
        if not ars:
            return self._redirect_with_msg("certificate_refused", "error",
                                           detail=u"No sample to issue a certificate for.")
        form = self.request.form
        # the card signs a final certificate; an interim is released at Submit
        interim = False
        if self.ws_state() not in self.VERIFIED_STATES and \
                [ar for ar in ars if (pending_signature(ar) or {}).get("interim")]:
            # a final signed now would replace the interim waiting to issue
            return self._redirect_with_msg("certificate_refused", "error", detail=INTERIM_WAITS)
        note = (form.get("sign_note") or u"").strip()
        msgs = esig_certificate.problems(self.request, interim)
        if msgs:
            return self._redirect_with_msg("certificate_refused", "error", detail=u" ".join(msgs))
        userid = signing.current_userid(self.request)
        now = signing.utcnow()
        # the credential the dialog confirmed (problems above), which the
        # ledger row written at publish records
        cred = signing.credential_ok(self.request, userid)
        rec = esig_certificate.pending_record(userid, interim, note, esig_certificate.now_stamp(now),
                                              credential=cred)
        # the publish guard's own rule, asked before anything is stored: while
        # the current revision is interim, another interim needs its reason
        why = esig_certificate.refusal(rec, userid, any(current_is_interim(ar) for ar in ars), now)
        if why:
            return self._redirect_with_msg("certificate_refused", "error", detail=why)
        # the certificate generated next prints the signer as signed now: the
        # image is kept before the signature is stored, and the ledger row
        # written at publish records the same picture
        try:
            signer = esig_certificate.signer_snapshot(userid)
        except (signing.SignatureRefused, ledger.LedgerError) as exc:
            return self._redirect_with_msg("certificate_refused", "error", detail=signing.reason(exc))
        rec = esig_certificate.pending_record(userid, interim, note, rec["at"], signer=signer, credential=cred)
        for ar in ars:
            set_pending_signature(ar, rec)
        reason = (form.get("reason") or u"").strip()
        if reason:
            for ar in self.reissue_ars():
                set_pending_amendment_reason(ar, reason)
        purl = self.publish_url()
        self.request.response.redirect(purl or self.request.URL)
        return u""

    def issue_email_state(self):
        """The card's Issue and e-mail: ready, or why not yet, and whom it
        e-mails (browser/issue_email.py asks what Send asks)."""
        from senaite.pfas.browser import issue_email
        from senaite.pfas.esig import signing
        from ZODB.POSException import ConflictError
        try:
            reports, why = issue_email.readiness(self._issue_ars(), signing.current_userid(self.request))
            to = issue_email.recipients(reports) if reports else []
        except ConflictError:
            raise
        except Exception as exc:                            # noqa: BLE001
            logger.warning("issue and e-mail readiness: %s", exc)
            reports, why, to = [], u"%s" % exc, []
        from senaite.pfas import certificate_delivery as cd
        return {"ready": bool(reports) and not why, "why": why or u"", "to": to,
                "to_shown": [cd.shown_recipient(r) for r in to]}

    def _handle_issue_email(self):
        """Issue and e-mail in one step, in the signer's own session: the
        publish transition, then the e-mail form's send, one e-mail per
        client (browser/issue_email.py)."""
        from senaite.pfas.browser import issue_email
        from senaite.pfas.esig import signing
        ars = self._issue_ars()
        if not ars:
            return self._redirect_with_msg("issue_email_refused", "error",
                                           detail=u"No sample to issue a certificate for.")
        ok, text = issue_email.issue_and_email(ars, self.request, signing.current_userid(self.request))
        if not ok and not issue_email.any_issued(ars):
            return self._redirect_with_msg("issue_email_refused", "error", detail=text)
        return self._redirect_with_msg("issue_email", "ok" if ok else "error", detail=text)

    def certificate_esig(self):
        """The sign dialog of Issue certificate: the register's next report
        id of each sample. The PDF does not exist yet: the signature binds
        to it as it is issued."""
        from senaite.pfas.browser.controlled_publications import get_publication_log
        from senaite.pfas.browser.perms import signed_in_name
        from senaite.pfas.esig import signing
        ids, revisions = [], []
        for ar in self._report_ars():
            revision = len(get_publication_log(ar)) + 1
            ids.append(u"%s-R%s" % (ar.getId(), revision))
            revisions.append(revision)
        return {"record": u", ".join(ids),
                "revision": u", ".join(u"%s" % r for r in sorted(set(revisions))),
                "hash_prefix": u"", "content_text": u"The certificate PDF as issued",
                "meaning_label": signing.meaning_label("authoriser"),
                "signer_name": signed_in_name(self.context), "action": u"sign_certificate",
                "form_id": u"drIssueForm"}

    def pending_certificate(self):
        """The signature waiting on this worksheet's samples, as the card
        shows it: the signer's name, the lab time, whether it is an interim,
        whether it is the signed-in person's own ("mine": only they can
        issue it) and whether it is too old to issue ("stale", read as the
        publish guard reads it); None when none waits."""
        from senaite.pfas.browser.controlled_publications import pending_signature
        from senaite.pfas.esig import certificate as esig_certificate
        from senaite.pfas.esig import signing
        from ZODB.POSException import ConflictError
        for ar in self._report_ars():
            rec = pending_signature(ar)
            if rec:
                userid = rec.get("userid") or u""
                try:
                    name = signing.staff_info(userid).get("fullname") or userid
                except ConflictError:
                    raise
                except Exception:                           # noqa: BLE001
                    name = userid
                return {"signer": name, "at": self.lab_at(rec.get("at"), rec.get("at") or u""),
                        "interim": bool(rec.get("interim")),
                        "mine": bool(userid) and userid == signing.current_userid(self.request),
                        "stale": esig_certificate.is_stale(rec, signing.utcnow())}
        return None

    # ── interim certificates, released at Submit ──────────────────────────

    def _interim_ars(self):
        """The worksheet's samples whose client takes interim certificates
        (Client reporting)."""
        from senaite.pfas import edd_store
        from senaite.pfas import interim_certificates as ic
        out = []
        for ar in self._report_ars():
            try:
                client = ar.getClient()
                if client is not None and edd_store.get_client_settings(client).get(ic.SETTING):
                    out.append(ar)
            except Exception:                               # noqa: BLE001
                logger.warning("interim: the client of %s could not be read", ar.getId(), exc_info=True)
        return out

    def interim_submit(self):
        """What Submit does about interim certificates: {"due": a sample's
        client takes them, "ok": this Submit signs one, "why": the note when
        it cannot, "current": another interim then needs a reason, "ars":
        the samples}. Asked before Submit, without the credential, which
        the dialog asks (interim_certificates.why_not)."""
        if hasattr(self, "_interim_submit"):
            return self._interim_submit
        from bika.lims import api as _bapi
        from senaite.core.permissions import ManageAnalysisRequests
        from senaite.pfas import interim_certificates as ic
        from senaite.pfas import report_tiers
        from senaite.pfas.browser.controlled_publications import current_is_interim
        from senaite.pfas.esig import certificate as esig_certificate
        from senaite.pfas.esig import signing
        out = {"due": False, "ok": False, "why": u"", "current": False, "ars": []}
        ars = self._interim_ars()
        if ars:
            portal = self._portal()
            tiers = []
            for ar in ars:
                tier, tier_id, _catalogue, _rev = report_tiers.resolve(ar, portal)
                tiers.append((_bapi.safe_unicode(ar.getClient().Title()),
                              (tier.get("name") or tier_id) if tier else None,
                              report_tiers.needs_package(tier) if tier else False))
            sm = getSecurityManager()
            # the Interim release right is the authority to issue it (asked
            # below): prepublish is granted to its signer for the interim
            # alone (interim_release); generating and sending it need the
            # publisher and the e-mail form
            can_issue = bool(sm.checkPermission(ManageAnalysisRequests, portal))
            userid = signing.current_userid(self.request)
            sign_problems = signing.problems(esig_certificate.KIND, esig_certificate.meaning_for(True),
                                             userid, [], signing.staff_info(userid), True)
            why = ic.why_not(tiers, can_issue, sign_problems)
            out.update(due=True, ok=not why, why=ic.note(why) if why else u"", ars=ars,
                       current=any(current_is_interim(ar) for ar in ars))
        self._interim_submit = out
        return out

    def submit_esig(self):
        """The sign dialog of Submit for a client taking interim
        certificates: the register's next report id of each of its
        samples, signed as released interim."""
        from senaite.pfas.browser.controlled_publications import get_publication_log
        from senaite.pfas.browser.perms import signed_in_name
        from senaite.pfas.esig import signing
        ids, revisions = [], []
        for ar in self.interim_submit()["ars"]:
            revision = len(get_publication_log(ar)) + 1
            ids.append(u"%s-R%s" % (ar.getId(), revision))
            revisions.append(revision)
        return {"record": u", ".join(ids),
                "revision": u", ".join(u"%s" % r for r in sorted(set(revisions))),
                "hash_prefix": u"", "content_text": u"The interim certificate PDF as issued",
                "meaning_label": signing.meaning_label("released_interim"),
                "signer_name": signed_in_name(self.context), "action": u"submit_for_review",
                "form_id": u"drSubmitForm"}

    def _sign_interim(self):
        """(record, None) when this Submit signs an interim certificate: the
        pending record to keep on the interim clients' samples once the run
        is submitted; (None, None) when no interim is released (the note
        says why); (None, refusal detail) when the signature the dialog gave
        is refused, which refuses the Submit: nothing has changed yet."""
        state = self.interim_submit()
        if not state["ok"]:
            return None, None
        from senaite.pfas.esig import certificate as esig_certificate
        from senaite.pfas.esig import ledger, signing
        if self.request.form.get("sign") != "1":
            return None, INTERIM_SIGN_FIRST
        msgs = esig_certificate.problems(self.request, True)
        if msgs:
            return None, u" ".join(msgs)
        userid = signing.current_userid(self.request)
        now = signing.utcnow()
        cred = signing.credential_ok(self.request, userid)
        note = (self.request.form.get("sign_note") or u"").strip()
        rec = esig_certificate.pending_record(userid, True, note, esig_certificate.now_stamp(now),
                                              credential=cred)
        # the publish guard's own rule: another interim needs its reason
        why = esig_certificate.refusal(rec, userid, state["current"], now)
        if why:
            return None, why
        try:
            signer = esig_certificate.signer_snapshot(userid)
        except (signing.SignatureRefused, ledger.LedgerError) as exc:
            return None, signing.reason(exc)
        return esig_certificate.pending_record(userid, True, note, rec["at"], signer=signer,
                                               credential=cred), None

    def certificate_signatures(self):
        """The current register row's signatures of each sample, read from
        the ledger against the hash the row was signed on, as the one
        signature table draws them (report_documents.signature_row, with
        "doc" the certificate): a valid signature is on file; a certificate
        issued unsigned, or whose signatures cannot be read, says so."""
        from senaite.pfas import lab_time
        from senaite.pfas import report_documents as rd
        from senaite.pfas.browser.controlled_publications import get_publication_log
        from senaite.pfas.esig import signing
        from ZODB.POSException import ConflictError

        def note(report_id, state):
            row = rd.signature_row(u"", u"", u"", state, u"", u"", u"")
            row["doc"] = report_id
            return row

        out = []
        for ar in self._report_ars():
            log = get_publication_log(ar)
            if not log:
                continue
            entry = log[0]
            if entry.get("unsigned"):
                out.append(note(entry["report_id"], u"Issued without a signature"))
                continue
            if entry.get("signature_seq") is None:
                continue
            try:
                st = signing.status("certificate", entry["report_id"], entry.get("certificate_sha256") or u"")
            except ConflictError:
                raise
            except Exception:                               # noqa: BLE001
                logger.warning("certificate signatures of %s unreadable", entry["report_id"], exc_info=True)
                out.append(note(entry["report_id"], u"The signatures could not be read"))
                continue
            for meaning, row in sorted(st["valid"].items()):
                e = row.get("entry") or {}
                signer = e.get("signer") or {}
                sig = rd.signature_row(signing.meaning_label(meaning), signer.get("fullname") or u"",
                                       signer.get("credentials"), rd.ON_FILE,
                                       lab_time.show(e.get("signed_at"), "utc"),
                                       (e.get("record_hash") or u"")[:12], meaning, seq=row.get("seq"))
                sig["doc"] = entry["report_id"]
                out.append(sig)
        return out

    def _handle_check_item(self):
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        item_key = self.request.form.get("item_key", "")
        manual_keys = {"coc", "final_data", "instrument_report"}
        if item_key not in manual_keys:
            return self._redirect_with_msg("invalid_item", "error")
        # ISO 17025 §10: where a sample's method sets a holding time, the
        # receipt's "within holding time" must be Yes before CoC can pass.
        # The answer is necessary and NOT sufficient -- a measured breach
        # blocks the gate whatever was answered.
        # a sign-off a correction cleared is made again only once the run
        # is judged with it
        from senaite.pfas import injection_identity as _ii
        if item_key in _ii.AFFECTED_SIGNOFFS and (self.identity_pending() or self.send_back_pending()):
            return self._redirect_with_msg("identity_pending_signoff", "error",
                                           tab=self.request.form.get("tab", "overview"))
        if item_key in _ii.AFFECTED_SIGNOFFS and self.extraction_pending():
            return self._redirect_with_msg("extraction_pending_signoff", "error",
                                           tab=self.request.form.get("tab", "overview"))
        if item_key == "instrument_report":
            ok, need = self.mi_gate()[:2]
            if not ok:
                return self._redirect_with_msg("mi_not_ready", "error", tab="instrument_report",
                                               detail=u"; ".join(need))
        if item_key == "coc" and self.study_run() is not None:
            return self._redirect_with_msg("coc_study_computed", "error", tab="coc")
        if item_key == "coc":
            coc = self.coc_summary()
            if coc.get("records") is not None and not coc.get("all_received"):
                return self._redirect_with_msg("coc_not_received", "error", tab="coc")
            from senaite.pfas.coc_records import holding_declared
            if not holding_declared(coc):
                return self._redirect_with_msg("coc_holding_time_fail", "error", tab="coc")
            verdict = self.holding_time_summary()
            if verdict.get("status") in holding_time.BLOCKING:
                return self._redirect_with_msg(
                    "coc_holding_time_computed_fail", "error", tab="coc",
                    detail=verdict.get("message", u""))
        # E-sign style: sign-off requires typed initials (initial + date shown
        # in the checklist and carried into the final review).
        initials = (self.request.form.get("initials") or "").strip()
        if not initials:
            return self._redirect_with_msg(
                "initials_required", "error",
                tab=self.request.form.get("tab", "overview"))
        user = getSecurityManager().getUser()
        now  = datetime.datetime.utcnow().isoformat()
        cl   = self._get_checklist(ws)
        item = cl["items"].get(item_key, {})

        # A declared service account may RECORD what it found; it may not sign
        # the item off. The three manual items are the human-judgement ones --
        # chain of custody, the final data review, the instrument report -- and
        # ISO 17025 requires a competent, authorised PERSON to authorise results.
        # A machine holds no competence record and takes no responsibility, so
        # its output is evidence FOR the reviewer, not the review.
        #
        # Enforced rather than documented because `checked` is what
        # all_items_pass() reads, and therefore what opens the release gate. An
        # automated actor able to set it would make "reviewed" and "computed" one
        # state -- a defect seen in other forms: a pass that
        # quietly means nobody looked.
        if _actor_kind(user) == u"automated":
            item["proposed_by"]    = user.getId()
            item["proposed_at"]    = now
            item["proposed_notes"] = initials
            cl["items"][item_key]  = item
            self._save_checklist(ws, cl)
            self._audit(ws)
            return self._redirect_with_msg(
                "automated_proposal_recorded", "ok",
                tab=self.request.form.get("tab", "overview"))

        item["checked"]         = True
        item["checked_by"]      = user.getId()
        item["checked_by_kind"] = u"human"
        item["initials"]        = initials
        item["checked_at"]      = now
        cl["items"][item_key] = item
        self._save_checklist(ws, cl)
        self._audit(ws)
        tab = self.request.form.get("tab", "overview")
        return self._redirect_with_msg("item_checked", "ok", tab=tab)

    def _handle_submit_for_review(self):
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        if self.machine_attested_items():
            # Distinct from "incomplete": every box is ticked, but one was ticked
            # by a machine. Saying "incomplete" would send the reviewer looking
            # for an empty box that does not exist.
            return self._redirect_with_msg("checklist_machine_attested", "error")
        # the review is of the run as processed with every edit
        held = self._raw_submit_refusal()
        if held:
            return self._redirect_with_msg(held[0], "error", detail=held[1])
        raw_ok, raw_need = self.raw_changes_gate()
        if not raw_ok:
            return self._redirect_with_msg("manual_changes_open", "error", detail=u"; ".join(raw_need))
        if not self.all_items_pass():
            return self._redirect_with_msg("checklist_incomplete", "error")
        if self._study_review(ws):
            return self._sign_study_review(ws, "submitted")
        # an interim certificate for a client taking them: signed in Submit's
        # dialog, asked before anything moves; a refused signature refuses
        # the Submit, an interim that cannot be released never does
        interim, refused = self._sign_interim()
        if refused:
            return self._redirect_with_msg("submit_sign_refused", "error", detail=refused)
        wf_tool = getToolByName(self.context, "portal_workflow")
        # Submit the RESULTS this review just signed off, then the worksheet.
        #
        # The pipeline pushes results but leaves each analysis `assigned`, and
        # the worksheet's `submit` guard only opens once its analyses are
        # submitted. So this handler called a transition that could never fire
        # ("No workflow provides the action"), and the release path was
        # unreachable — which is why no sample on this system has ever reached
        # `verified`. The checklist IS the technical review; completing it is
        # what submits the results it reviewed.
        #
        # `api` is NOT a module-level name in this module; it is imported
        # locally where needed. Reaching for a bare `api` here raises NameError
        # at request time, not import time.
        from bika.lims import api as _bapi
        submitted = 0
        for analysis in (ws.getAnalyses() or []):
            try:
                if _bapi.get_review_status(analysis) != "assigned":
                    continue
                if analysis.getResult() in (None, ""):
                    continue
                wf_tool.doActionFor(analysis, "submit")
                submitted += 1
                # a dilution the worker recorded for this result is appended
                # now, as a retest with its own result and analysis time
                from senaite.pfas.browser.dilution_retests import append_dilution_retest
                if append_dilution_retest(analysis, wf_tool) is not None:
                    submitted += 1
            except Exception as exc:                        # noqa: BLE001
                logger.warning("submit_for_review: %s could not submit: %s",
                               getattr(analysis, "getKeyword", lambda: "?")(),
                               exc)
        if submitted:
            logger.info("submit_for_review: submitted %d analysis result(s) on "
                        "%s", submitted, ws.getId())
        try:
            if _bapi.get_review_status(ws) == "open":
                wf_tool.doActionFor(ws, "submit")
        except Exception as exc:
            logger.error("submit_for_review: %s", exc)
            return self._redirect_with_msg("workflow_error", "error")
        user = getSecurityManager().getUser()
        now  = datetime.datetime.utcnow().isoformat()
        cl   = self._get_checklist(ws)
        cl["submitted_by"] = user.getId()
        cl["submitted_at"] = now
        self._save_checklist(ws, cl)
        self._audit(ws)
        from senaite.pfas import interim_certificates as ic
        said = self.interim_submit()
        if interim is not None:
            # the run is submitted: the interim waits on its clients' samples
            from senaite.pfas.browser.controlled_publications import set_pending_signature
            for ar in said["ars"]:
                set_pending_signature(ar, interim)
            return self._redirect_with_msg("submitted_for_review", "ok", detail=ic.SIGNED)
        return self._redirect_with_msg("submitted_for_review", "ok", detail=said["why"] or None)

    def _handle_approve_release(self):
        if not self.is_manager():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        if self.ws_state() != "to_be_verified":
            return self._redirect_with_msg("wrong_state", "error")
        # the review is of the run as processed with every edit
        held = self._raw_submit_refusal()
        if held:
            return self._redirect_with_msg(held[0], "error", detail=held[1])
        if not self.all_items_pass():
            # The checklist is computed afresh: a run reprocessed after
            # submission (or a QC record written later) can fail it. The
            # manager verifies the review as it stands, never as it stood
            # (a reprocess held a submitted worksheet's QC and Approve Release
            # still verified it).
            return self._redirect_with_msg("checklist_changed", "error")
        # every identity correction in force is confirmed first: refused
        # before anything is signed
        from senaite.pfas import injection_identity as _ii
        unconfirmed = _ii.verify_refusal(self._identity_state())
        if unconfirmed:
            return self._redirect_with_msg("identity_refused", "error", detail=unconfirmed)
        # and every extraction correction
        from senaite.pfas import extraction_amendments as ea
        unconfirmed = ea.verify_refusal(self._extraction_state())
        if unconfirmed:
            return self._redirect_with_msg("extraction_refused", "error", detail=unconfirmed)
        # the verifier countersigns the Integration Review changes, and is never the
        # person who initialled them: tried here, saved once released
        refused = self._countersign_raw_changes(ws)
        if refused:
            return self._redirect_with_msg("raw_countersign_refused", "error", detail=refused)
        # the approver signs the batch record as its reviewer before anything
        # is verified: a refused signature releases nothing (a study
        # worksheet's record too)
        unsigned = self._sign_release(ws)
        if unsigned is not None:
            return unsigned
        if self._study_review(ws):
            self._countersign_raw_changes(ws, save=True)
            return self._sign_study_review(ws, "approved")
        wf_tool = getToolByName(self.context, "portal_workflow")
        # Verify the RESULTS, and the worksheet follows. `verify` is available
        # on the analyses, not on the worksheet — the same cascade as submit.
        # Calling it on the worksheet raised "No workflow provides the action"
        # and the release could never complete.
        from bika.lims import api as _bapi
        verified = 0
        for analysis in (ws.getAnalyses() or []):
            try:
                if _bapi.get_review_status(analysis) != "to_be_verified":
                    continue
                wf_tool.doActionFor(analysis, "verify")
                verified += 1
            except Exception as exc:                        # noqa: BLE001
                logger.warning("approve_release: %s could not verify: %s",
                               getattr(analysis, "getKeyword", lambda: "?")(),
                               exc)
        if verified:
            logger.info("approve_release: verified %d analysis result(s) on %s",
                        verified, ws.getId())
        try:
            if _bapi.get_review_status(ws) == "to_be_verified":
                wf_tool.doActionFor(ws, "verify")
        except Exception as exc:
            logger.error("approve_release: %s", exc)
            return self._redirect_with_msg("workflow_error", "error")
        # the countersign is the release: saved only once the worksheet is
        # verified, naming the person who released it
        if _bapi.get_review_status(ws) in self.VERIFIED_STATES:
            refused = self._countersign_raw_changes(ws, save=True)
            if refused:
                logger.error("approve_release: %s verified, its manual changes not countersigned: %s",
                             ws.getId(), refused)
        # NO freeze call here. The resolved-criteria freeze now
        # hangs on the Worksheet `verify` TRANSITION -- see module-level
        # on_after_transition() above -- so it happens whatever route verifies
        # the worksheet, including the native SENAITE listings this handler is
        # not involved in. The doActionFor(ws, "verify") just above is what
        # fires it. Calling it here as well would make two producers of one
        # record, which is the dead-twin shape removed twice already
        # (A4); write-once stays a safety property, not a
        # licence to write from two places.
        user = getSecurityManager().getUser()
        now  = datetime.datetime.utcnow().isoformat()
        cl   = self._get_checklist(ws)
        cl["approved_by"] = user.getId()
        cl["approved_at"] = now
        self._save_checklist(ws, cl)
        self._stamp_qualifier_remarks(ws)
        self._audit(ws)
        return self._redirect_with_msg("batch_approved", "ok")

    def _sign_release(self, ws):
        """Sign the worksheet's batch record as its reviewer, the signed-in
        person, bound to the whole record (batch_record.record_hash): None
        when signed, else the refusal's redirect. The finaliser may not
        approve (the signing core reads every live row of the record); a
        record finalised before signatures were kept has no preparer row,
        and is approved by this signature alone."""
        if self.request.form.get("sign") != "1":
            # a release is recorded only through the sign dialog
            return self._redirect_with_msg("sign_refused", "error", detail=u"Sign the release to record it.")
        from ZODB.POSException import ConflictError
        from senaite.pfas import batch_record as br
        from senaite.pfas.browser import extraction_pdf
        from senaite.pfas.browser.extraction_guide import _load_session, _save_session
        from senaite.pfas.esig import ledger, signing
        try:
            record = extraction_pdf.record_for(ws, self.request)
        except ConflictError:
            raise
        except Exception as exc:                            # noqa: BLE001
            logger.exception("approve_release: the record of %s could not be read", ws.getId())
            return self._redirect_with_msg("sign_refused", "error",
                                           detail=u"The batch record could not be read: %s" % signing.reason(exc))
        try:
            rows = br.sign_approved(self._portal(), self.request, record,
                                    note=self.request.form.get("sign_note") or u"")
        except signing.SignatureRefused as exc:
            return self._redirect_with_msg("sign_refused", "error", detail=u"; ".join(exc.messages))
        except ledger.LedgerError as exc:
            return self._redirect_with_msg("sign_refused", "error", detail=signing.reason(exc))
        # the session keeps the display cache; the ledger is the truth
        home = self._extraction_home(ws)
        sess = _load_session(home) if home is not None else {}
        if sess:
            sess["signatures"] = signing.merge_cache(sess.get("signatures"), rows)
            _save_session(home, sess)
        return None

    def approve_esig(self):
        """The sign dialog of Verify: the worksheet's record, its
        method revision and the whole record's hash as it stands."""
        from senaite.pfas import batch_record as br
        from senaite.pfas.browser import extraction_pdf
        from senaite.pfas.browser.perms import signed_in_name
        from senaite.pfas.esig import signing
        from ZODB.POSException import ConflictError
        ws = self._get_worksheet()
        record, prefix = {}, u""
        try:
            record = extraction_pdf.record_for(ws, self.request) if ws is not None else {}
            prefix = br.record_hash(record)[:12] if record else u""
        except ConflictError:
            raise
        except Exception:                                   # noqa: BLE001
            # shown only: Approve Release reads the record again and refuses there
            logger.warning("approve dialog: the record could not be read", exc_info=True)
        return {"record": record.get("worksheet") or (ws.getId() if ws is not None else u""),
                "revision": _method_revision_text(record.get("revision")), "hash_prefix": prefix,
                "meaning_label": signing.meaning_label("reviewer"),
                "signer_name": signed_in_name(self.context), "action": u"approve_release",
                "form_id": u"drApproveForm"}

    def _sign_study_review(self, ws, step):
        """Submit or approve a study worksheet's review: the checklist is the
        record (no core transition can fire on it). Approval freezes the
        criteria here, the one producer on this path: no verify transition
        fires to do it."""
        user = getSecurityManager().getUser()
        now = datetime.datetime.utcnow().isoformat()
        cl = self._get_checklist(ws)
        cl[step + "_by"] = user.getId()
        cl[step + "_at"] = now
        self._save_checklist(ws, cl)
        if step == "approved":
            try:
                from senaite.pfas import worksheet_criteria_snapshot
                worksheet_criteria_snapshot.freeze_resolved_criteria(
                    self._portal(), ws, self._linked_batch(ws),
                    self.batch_method(), self._batch_matrix())
            except Exception as exc:                        # noqa: BLE001
                logger.error("criteria-freeze: study worksheet %s: %s", ws.getId(), exc)
        self._audit(ws)
        return self._redirect_with_msg(
            "batch_approved" if step == "approved" else "submitted_for_review", "ok")

    def _handle_reject(self):
        if not self.is_manager():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        if self.ws_state() != "to_be_verified":
            return self._redirect_with_msg("wrong_state", "error")
        if self._study_review(ws):
            cl = self._get_checklist(ws)
            cl["submitted_by"] = cl["submitted_at"] = None
            self._save_checklist(ws, cl)
            self._audit(ws)
            return self._redirect_with_msg("batch_rejected", "ok")
        from senaite.pfas import run_reject
        from senaite.pfas import records
        reason = (self.request.form.get("reason") or u"").strip()
        disposition = self.request.form.get("disposition") or u""
        why = run_reject.refusal(reason, disposition)
        if why:
            return self._redirect_with_msg("reject_refused", "error", detail=why)
        from bika.lims import api as _rapi
        from bika.lims.workflow import doActionFor as _do
        try:
            retests = run_reject.reject(ws, lambda o, t: _do(o, t)[0], _rapi.get_review_status)
        except Exception as exc:                            # noqa: BLE001
            # a rejection half made is no rejection: nothing is kept
            import transaction
            transaction.abort()
            logger.error("reject: %s", exc)
            return self._redirect_with_msg("workflow_error", "error")
        who = getSecurityManager().getUser().getId()
        rec = run_reject.record(who, datetime.datetime.utcnow().isoformat(), reason, disposition, retests)
        IAnnotations(ws)[run_reject.REJECT_KEY] = json.dumps(rec)
        records.log(ws, u"reject", reason=reason, detail={u"disposition": disposition, u"retests": rec[u"retests"]})
        if disposition == run_reject.VOID:
            self._store().void_run(ws.getId(), who, reason)
        return self._redirect_with_msg("run_rejected", "ok", extra=u"&car=1")

    # ── dilution / re-injection requests to the bench ───────────────────

    def run_requests(self):
        from senaite.pfas import extraction_batch
        ws = self._get_worksheet()
        return extraction_batch.load_requests(ws) if ws is not None else []

    def request_targets(self):
        """The batch's injections a request may name (members). Once per
        request."""
        if hasattr(self, "_request_targets"):
            return self._request_targets
        from senaite.pfas import extraction_batch
        ws = self._get_worksheet()
        self._request_targets = [m.get("injection") for m in (extraction_batch.load(ws) if ws is not None else [])
                                 if m.get("injection")]
        return self._request_targets

    # ── above the calibration range with no dilution ─────────────────────

    def above_range_reasons(self):
        """{reason_key: {"reason", "by", "at"}}: the reasons the reviewer
        recorded to report a result above the range with E. Once per request."""
        if "_above_reasons" not in self.__dict__:
            ws = self._get_worksheet()
            try:
                raw = IAnnotations(ws).get(ABOVE_RANGE_REASONS_KEY) if ws is not None else None
                self._above_reasons = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                self._above_reasons = {}
        return self._above_reasons

    def above_range_reason(self, injection, analyte):
        return self.above_range_reasons().get(_above_range.reason_key(injection, analyte))

    def above_range_items(self):
        """The run's sample results above the calibration range with no
        dilution, as the worker filed them: [{"injection", "analyte",
        "reading", "limit", "reason" (the record, or None)}]. Data Review
        lists each until a dilution is run or a reason is recorded. Once per
        request."""
        if "_above_items" in self.__dict__:
            return self._above_items
        out = []
        ws = self._get_worksheet()
        if ws is not None and self.db_available:
            try:
                rows = self._store().get_qc_for_run(None, batch_id=ws.getId())
            except Exception as exc:                        # noqa: BLE001
                logger.error("above-range results: %s", exc)
                rows = []
            seen = set()
            for r in rows:
                r = dict(r)
                if r.get("qc_type") != ABOVE_RANGE_QC_TYPE or r.get("result_status") == "voided":
                    continue
                key = _above_range.reason_key(r.get("applies_to"), r.get("analyte"))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"injection": r.get("applies_to") or u"", "analyte": r.get("analyte") or u"",
                            "reading": r.get("value"), "limit": r.get("limit_high"),
                            "reason": self.above_range_reasons().get(key)})
        self._above_items = out
        return out

    @staticmethod
    def above_range_number(value):
        try:
            return u"%g" % float(value)
        except (TypeError, ValueError):
            return u"—"

    @staticmethod
    def above_range_status(item):
        """What an above-range result waits on, or the reason recorded."""
        rec = item.get("reason")
        if not rec:
            return u"Waiting for a dilution or a reason"
        return u"Reported with E: %s, %s" % (rec.get("reason") or u"", rec.get("by") or u"")

    def _handle_report_above_range(self):
        """The reviewer's reason to report a result above the calibration
        range with E instead of running a dilution: one of the run's own,
        recorded on the worksheet with who and when, logged."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error", tab="final_data")
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error", tab="final_data")
        f = self.request.form
        injection, analyte = (f.get("injection") or u"").strip(), (f.get("analyte") or u"").strip()
        # only a result the run holds above its range (a forged form names any)
        if not [i for i in self.above_range_items() if (i["injection"], i["analyte"]) == (injection, analyte)]:
            return self._redirect_with_msg("above_range_refused", "error", tab="final_data",
                                           detail=u"That result is not above the calibration range.")
        user = getSecurityManager().getUser()
        reasons, why = _above_range.reason_record(
            self.above_range_reasons(), injection, analyte, f.get("reason"), user.getId(),
            datetime.datetime.utcnow().isoformat())
        if reasons is None:
            return self._redirect_with_msg("above_range_refused", "error", tab="final_data", detail=why)
        IAnnotations(ws)[ABOVE_RANGE_REASONS_KEY] = json.dumps(reasons)
        from senaite.pfas import records
        records.log(ws, u"report_above_range", reason=(f.get("reason") or u"").strip(),
                    detail={u"injection": injection, u"analyte": analyte})
        self._audit(ws)
        return self._redirect_with_msg("above_range_reported", "ok", tab="final_data")

    # ── the instrument gave no number ────────────────────────────────────

    def no_number_reasons(self):
        """{reason_key: {"reason", "by", "at"}}: the reasons the reviewer
        recorded to report a result the instrument wrote BLoQ with no
        number. Once per request."""
        if "_no_number_reasons" not in self.__dict__:
            ws = self._get_worksheet()
            try:
                raw = IAnnotations(ws).get(_no_number.REASONS_KEY) if ws is not None else None
                self._no_number_reasons = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                self._no_number_reasons = {}
        return self._no_number_reasons

    def no_number_reason(self, injection, analyte):
        return self.no_number_reasons().get(_no_number.reason_key(injection, analyte))

    def no_number_items(self):
        """The run's sample results the instrument wrote BLoQ with no
        number, as the worker filed them: [{"injection", "analyte", "reason"
        (the record, or None)}]. Data Review lists each until its reason is
        recorded. Once per request."""
        if "_no_number_items" in self.__dict__:
            return self._no_number_items
        out = []
        ws = self._get_worksheet()
        if ws is not None and self.db_available:
            try:
                rows = self._store().get_qc_for_run(None, batch_id=ws.getId())
            except Exception as exc:                        # noqa: BLE001
                logger.error("results with no number: %s", exc)
                rows = []
            seen = set()
            for r in rows:
                r = dict(r)
                if r.get("qc_type") != _no_number.QC_TYPE or r.get("result_status") == "voided":
                    continue
                key = _no_number.reason_key(r.get("applies_to"), r.get("analyte"))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"injection": r.get("applies_to") or u"", "analyte": r.get("analyte") or u"",
                            "reason": self.no_number_reasons().get(key)})
        self._no_number_items = out
        return out

    @staticmethod
    def no_number_status(item):
        """What a result with no number waits on, or the reason recorded."""
        rec = item.get("reason")
        if not rec:
            return u"Waiting for a reason"
        return u"Reported without a number: %s, %s" % (rec.get("reason") or u"", rec.get("by") or u"")

    def _handle_resolve_no_number(self):
        """The reviewer's reason to report a result the instrument wrote
        BLoQ with no number: one of the run's own, recorded on the worksheet
        with who and when, logged and audited."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error", tab="final_data")
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error", tab="final_data")
        f = self.request.form
        injection, analyte = (f.get("injection") or u"").strip(), (f.get("analyte") or u"").strip()
        # only a result the run holds for want of a number (a forged form names any)
        if not [i for i in self.no_number_items() if (i["injection"], i["analyte"]) == (injection, analyte)]:
            return self._redirect_with_msg("no_number_refused", "error", tab="final_data",
                                           detail=u"The instrument gave a number for that result.")
        user = getSecurityManager().getUser()
        reasons, why = _no_number.reason_record(
            self.no_number_reasons(), injection, analyte, f.get("reason"), user.getId(),
            datetime.datetime.utcnow().isoformat())
        if reasons is None:
            return self._redirect_with_msg("no_number_refused", "error", tab="final_data", detail=why)
        IAnnotations(ws)[_no_number.REASONS_KEY] = json.dumps(reasons)
        from senaite.pfas import records
        records.log(ws, u"resolve_no_number", reason=(f.get("reason") or u"").strip(),
                    detail={u"injection": injection, u"analyte": analyte})
        self._audit(ws)
        return self._redirect_with_msg("no_number_resolved", "ok", tab="final_data")

    def estimate_meaning(self):
        """The J rule's wording (QC Qualifiers, "Between MDL and RL"), shown
        on hover beside a number between the MDL and the RL. Once per
        request."""
        if "_estimate_meaning" not in self.__dict__:
            from senaite.pfas import qc_qualification
            try:
                library = qc_qualification.get_library(self._portal())
            except Exception:                               # noqa: BLE001
                library = qc_qualification.DEFAULT_LIBRARY
            self._estimate_meaning = (library.get("between_mdl_rl") or {}).get("statement") or u""
        return self._estimate_meaning

    def ask_target(self, injection):
        """The request target a Final Data row's injection names (matched on
        letters and digits), u"" when none does: the dialog then asks for
        the injection rather than choosing one."""
        from senaite.pfas import final_data
        return final_data.target_of(injection, self.request_targets())

    def _handle_lot_review(self):
        """Approve (verified for use: active) or reject (quarantined) a lot
        pending acceptance, from its node in the traceability check."""
        from senaite.pfas import lot_status as ls
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error", tab="traceability")
        f = self.request.form
        ws = self._get_worksheet()
        # only a lot this run's check names as pending (a forged form names any)
        if ws is None or not ls.reviewable((self._build_traceability_tree(ws) or {}).get("unresolved"),
                                           f.get("uid"), f.get("kind")):
            return self._redirect_with_msg("lot_not_found", "error", tab="traceability")
        folder = self._portal().get("pfas_prepared_standards" if f.get("kind") == u"prepared"
                                    else "pfas_reagents")
        obj = folder.get(f.get("uid") or u"") if folder is not None else None
        if obj is None:
            return self._redirect_with_msg("lot_not_found", "error", tab="traceability")
        user = getSecurityManager().getUser()
        try:
            status, key, rec = ls.review_lot(getattr(obj, "status", None) or u"", f.get("action"),
                                             user.getId(), datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), f)
        except ValueError as exc:
            return self._redirect_with_msg("lot_refused", "error", tab="traceability", detail=u"%s" % exc)
        obj.status = status
        IAnnotations(obj)[key] = json.dumps(rec)
        try:
            obj.reindexObject()
        except Exception:                                   # noqa: BLE001
            pass
        if f.get("action") == u"reject_lot":
            self._send_back(ws, f, rec, user.getId())
            self._audit(ws)
            return self._redirect_with_msg("run_sent_back", "ok", tab="traceability")
        self._audit(ws)
        return self._redirect_with_msg("lot_reviewed", "ok", tab="traceability")

    def _send_back(self, ws, f, rec, who):
        """A rejected lot sends the run back to the stage that can fix it
        (send_back.py): the Run Builder, or the extraction stage that used it."""
        from senaite.pfas import extraction_batch
        from senaite.pfas import send_back as sb
        from senaite.pfas.browser.extraction_guide import _load_session, _save_session
        from senaite.pfas.browser.run_builder import RUN_MANIFEST_KEY
        stage = sb.stage_for(f.get("source"))
        lot = (f.get("lot") or u"").strip()
        reason = u"%s lot %s rejected: %s" % (f.get("label") or f.get("name") or u"", lot, rec.get("why") or u"")
        home = extraction_batch.home(ws)
        before = _load_session(home)
        built = self._run_manifest(ws)
        manifest, session = sb.apply(built, before, stage, reason.strip(),
                                     lot, who, rec.get("at") or u"", uid=f.get("uid"))
        if manifest != built:
            IAnnotations(ws)[RUN_MANIFEST_KEY] = json.dumps(manifest)
        reopened = session.get("reopened") is not None and session != before
        if reopened:
            _save_session(home, session)
        if manifest == built and not reopened:
            return                      # nothing built and nothing to reopen
        # the analyst responsible: who built the run, or finalized the extraction
        from senaite.pfas import notices as nt
        portal = self._portal()
        initials = built.get("built_by") if stage == sb.RUN else before.get("finalized_by")
        # the finaliser is kept as a user id; a run's builder, and a
        # finaliser from before, by initials
        from bika.lims import api as _napi
        userid = initials if (initials and stage != sb.RUN and _napi.get_user(initials) is not None) \
            else nt.userid_for_initials(portal, initials)
        store = nt.load(portal)
        nt.raise_(store, "run_sent_back", userid, ws.getId(),
                  stage, lot, reason.strip(), nt.now())
        nt.save(portal, store)

    def _handle_request_run(self):
        from senaite.pfas import extraction_batch
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error", tab="final_data")
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error", tab="final_data")
        f = self.request.form
        user = getSecurityManager().getUser()
        requests, error = extraction_batch.new_request(
            extraction_batch.load_requests(ws), extraction_batch.load(ws),
            (f.get("injection") or u"").strip(), (f.get("kind") or u"").strip(),
            f.get("fold"), f.get("reason") or u"", user.getId(),
            datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
        if error:
            return self._redirect_with_msg("request_refused", "error", tab="final_data", detail=error)
        extraction_batch.save_requests(ws, requests)
        self._audit(ws)
        return self._redirect_with_msg("request_sent", "ok", tab="final_data")

    def _handle_record_spike_level(self):
        """Record a spike level a reviewer supplies for an unevaluated spike.

        Written to the batch's extraction pedigree — where "what was actually
        spiked" already lives — attributed to whoever entered it and marked as
        reviewer-entered, so an auditor can see it was added after the bench
        record rather than taken from it.

        Setting the METHOD's nominal level is a separate, manager-only act:
        one batch's observation should not silently reconfigure every future
        batch of that matrix.
        """
        # a reviewer's act: the value feeds the release gate (M1 -- a Bench Chemist reached it)
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error", tab="spike_qc")
        from AccessControl import getSecurityManager
        f = self.request.form
        injection = (f.get("injection") or "").strip()
        raw = (f.get("spike_ppt") or "").strip()
        if not injection or not raw:
            return self._redirect_with_msg("spike_missing", "error",
                                           tab="spike_qc")
        try:
            spike_ppt = float(raw)
        except (TypeError, ValueError):
            return self._redirect_with_msg("spike_invalid", "error",
                                           tab="spike_qc")
        if spike_ppt <= 0:
            return self._redirect_with_msg("spike_invalid", "error",
                                           tab="spike_qc")

        ws = self._get_worksheet()
        batch = self._extraction_home(ws) if ws else None
        if batch is None:
            return self._redirect_with_msg("no_batch", "error", tab="spike_qc")

        from senaite.pfas.dilution_ref import EXTRACTION_SESSION_KEY
        ann = IAnnotations(batch)
        try:
            session = json.loads(ann.get(EXTRACTION_SESSION_KEY) or "{}")
        except (ValueError, TypeError):
            session = {}
        pedigree = session.setdefault("pedigree", {})
        entry = pedigree.setdefault(injection, {})
        # in the batch matrix's reporting unit
        from senaite.pfas.calibration_levels import matrix_unit
        from senaite.pfas.method_profile_store import get_profile as _gp
        entry["spike"] = spike_ppt
        # the METHOD's unit map (this handler may save the method profile,
        # so it never reads the project-applied one)
        entry["spike_unit"] = matrix_unit(_gp(self._portal(), self.batch_method()) or {},
                                          self._batch_matrix())
        entry.pop("spike_ppt", None)
        entry["spike_source"] = "reviewer-entered"
        entry["spike_entered_by"] = getSecurityManager().getUser().getId()
        entry["spike_entered_at"] = datetime.datetime.utcnow().strftime(
            "%Y-%m-%d %H:%M")
        ann[EXTRACTION_SESSION_KEY] = json.dumps(session)

        # Manager-only, and only when explicitly asked for.
        if f.get("set_method_nominal") == "yes":
            from senaite.pfas.browser.perms import require_manager
            if not require_manager(self.context, self.request):
                return self._redirect_with_msg("spike_saved_not_method", "ok",
                                               tab="spike_qc")
            try:
                from senaite.pfas.method_profile_store import (
                    get_profile, save_profile)
                portal = self._portal()
                mid = self.batch_method()
                profile = get_profile(portal, mid) or {}
                matrix = self._batch_matrix()
                label = (entry.get("level")
                         or (f.get("level") or "").strip() or "Mid")
                levels = (profile.setdefault("spike_levels", {})
                          .setdefault(matrix, {}).setdefault("LFSM", []))
                for lv in levels:
                    if lv.get("label") == label:
                        lv["value"] = spike_ppt          # the matrix's unit
                        lv.pop("ppt", None)
                        break
                else:
                    levels.append({"label": label, "value": spike_ppt})
                save_profile(portal, mid, profile)
            except Exception as exc:
                logger.error("could not set the method's nominal level: %s", exc)
                return self._redirect_with_msg("spike_saved_not_method", "ok",
                                               tab="spike_qc")

        return self._redirect_with_msg("spike_saved", "ok", tab="spike_qc")

    def _handle_upload_instrument_report(self):
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error", tab="instrument_report")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error", tab="instrument_report")
        upload = self.request.form.get("report_file")
        if not upload or not getattr(upload, "filename", None):
            return self._redirect_with_msg("no_file", "error", tab="instrument_report")

        report_dir = self._report_dir(ws)
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)

        raw_name = os.path.basename(upload.filename or "report")
        safe_name = re.sub(r"[^\w\.\-]", "_", raw_name) or "report"
        filepath  = os.path.join(report_dir, safe_name)
        tmp_path  = filepath + ".tmp"

        try:
            content = upload.read()
            with open(tmp_path, "wb") as fh:
                fh.write(content)
            os.rename(tmp_path, filepath)
        except Exception as exc:
            logger.error("upload_instrument_report: %s", exc)
            return self._redirect_with_msg("upload_failed", "error", tab="instrument_report")

        # read its text now (manual-integration heading pages): the
        # gate only reads the kept scan, never scans
        from senaite.pfas.browser import manual_integration_view as _miv
        _miv.scan_quietly(filepath)

        cl = self._get_checklist(ws)
        cl["instrument_report_file"] = safe_name
        cl["instrument_report_uploaded_at"] = datetime.datetime.utcnow().isoformat()
        self._save_checklist(ws, cl)
        self._audit(ws)
        return self._redirect_with_msg("report_uploaded", "ok", tab="instrument_report")

    def _handle_download_report(self):
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        raw_name = self.request.form.get("filename", "")
        safe_name = re.sub(r"[^\w\.\-]", "_", raw_name)
        if not safe_name:
            return self._redirect_with_msg("no_file", "error")
        report_dir = self._report_dir(ws)
        filepath   = os.path.realpath(os.path.join(report_dir, safe_name))
        safe_root  = os.path.realpath(INSTRUMENT_REPORT_DIR)
        if not filepath.startswith(safe_root):
            return self._redirect_with_msg("permission_denied", "error")
        if not os.path.isfile(filepath):
            return self._redirect_with_msg("file_not_found", "error")
        content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
        self.request.response.setHeader("Content-Type", content_type)
        self.request.response.setHeader(
            "Content-Disposition",
            'attachment; filename="{0}"'.format(safe_name),
        )
        with open(filepath, "rb") as fh:
            return fh.read()
