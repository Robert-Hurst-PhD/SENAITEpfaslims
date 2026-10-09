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

Audit trail via bika.lims.api.snapshot.take_snapshot(ws).

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
from senaite.pfas.logbook_schema import active_rows
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import (
    ANALYST_ROLES, MANAGER_ROLES, has_role_at_portal)
from senaite.pfas.qc_qualification import format_remark_codes
# Safe at module scope BECAUSE holding_time imports nothing from Plone -- there
# is no import-order hazard. Most add-on helpers in this file are imported
# locally inside the method that needs them (see _bapi, analytes_for_failure,
# get_batch); do not copy this pattern for a module that does touch Plone.
from senaite.pfas import holding_time

logger = logging.getLogger("senaite.pfas.browser.data_review")

CHECKLIST_KEY         = u"senaite.pfas.data_review.checklist"
INSTRUMENT_REPORT_DIR = os.environ.get("PFAS_INSTRUMENT_REPORTS", "/data/instrument_reports")
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
# Dry ice, compressed gas and a machined part genuinely have none, and FM-ENV-004
# on the released WS-0005 records exactly that: `{"name": "Dry ice", "lot": "N/A"}`.
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


class PFASDataReviewView(BrowserView):

    template = ViewPageTemplateFile("templates/data_review.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            return self._handle_post()
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

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

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
        ws = self._get_worksheet()
        if not ws:
            return u""
        batch = self._worksheet_batch()
        if batch is not None:
            from senaite.pfas import batch_method as bm
            mid = bm.resolve(batch)[0]
            if mid:
                return mid
        from senaite.pfas.method_bridge import profile_id_for_method
        try:
            m = ws.getMethod()
            if m:
                return profile_id_for_method(m)
        except Exception:
            pass
        try:
            for analysis in (ws.getAnalyses() or []):
                m = analysis.getMethod()
                if m:
                    return profile_id_for_method(m)
        except Exception:
            pass
        # a study run: the study's method
        return (self.study_run() or {}).get("method_id") or u""

    def has_run(self):
        """True once a run of this worksheet is on record: "no departure
        detected" says nothing about a worksheet with no data."""
        ws = self._get_worksheet()
        if ws is None or not self.db_available:
            return False
        try:
            return self._store().get_batch(ws.getId()) is not None
        except Exception:                                   # noqa: BLE001
            return False

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

    def ws_state(self):
        ws = self._get_worksheet()
        if not ws:
            return u"open"
        wf_tool = getToolByName(self.context, "portal_workflow")
        return wf_tool.getInfoFor(ws, "review_state", "open")

    def active_tab(self):
        return self.request.form.get("tab", "overview")

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
        "submitted_for_review":    u"Submitted for manager review.",
        "workflow_error":          u"Workflow transition failed — check worksheet state.",
        "wrong_state":             u"Worksheet is not in the expected state.",
        "record_closed":           (u"The review record is closed: this worksheet was "
                                    u"submitted or released. A manager's rejection reopens it."),
        "batch_approved":          u"Batch approved and released.",
        "batch_rejected":          u"Batch rejected and returned for re-analysis.",
        "report_uploaded":         u"Instrument report uploaded.",
        "spike_saved":             u"Spike level recorded on the extraction log.",
        "request_sent":            u"Request sent to the bench.",
        "request_refused":         u"Request not sent.",
        "spike_saved_not_method":  (u"Spike level recorded on this batch. The "
                                    u"method's nominal level was not changed "
                                    u"\u2014 that needs a manager."),
        "spike_missing":           u"Enter a spike level.",
        "spike_invalid":           u"Spike level must be a positive number.",
        "no_batch":                u"No batch is linked to this worksheet.",
        "upload_error":            u"File upload failed.",
        "path_error":              u"Download failed — file not found.",
        "initials_required":       u"Your initials are required to sign off / correct — nothing was saved.",
        "run_plan_cleared":        u"Run plan item cleared with your note.",
        "subtraction_blank_changed": u"Subtraction blank changed. Reprocess the run so the results follow it.",
        "subtraction_blank_reason": u"Changing the subtraction blank needs a reason. Nothing was saved.",
        "subtraction_blank_invalid": u"Choose one of the run's method blanks.",
        "calibration_approved":    u"The run's calibration is approved.",
        "calibration_rejected":    u"The run's calibration is rejected: release is held.",
        "calibration_note_required": u"Rejecting the calibration needs a note saying why — nothing was saved.",
        "calibration_not_own":     u"This run has no calibration of its own to approve — nothing was saved.",
        "run_plan_note_required":  u"Clearing a run plan item needs a note saying why — nothing was saved.",
        "run_plan_not_cleared":    u"That run plan item was not open — nothing was saved.",
        "correction_logged":       u"Correction saved and logged (initialed + dated).",
        "no_change":               u"New value is identical — no correction logged.",
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

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

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
        Resolved once per request (asked ~130 times); a copy each time, so no
        caller changes another's."""
        import copy
        if not hasattr(self, "_method_profile_cache"):
            try:
                from senaite.pfas.project_specs import profile_for_batch
                mid = self.batch_method()
                self._method_profile_cache = profile_for_batch(
                    self._portal(), self._worksheet_batch(), mid,
                    self._batch_matrix()) or {} if mid else {}
            except Exception:
                self._method_profile_cache = {}
        return copy.deepcopy(self._method_profile_cache)

    def _fc(self, slug):
        """The lab's form number for a logbook (FM-ENV-003...), from the pool."""
        try:
            from senaite.pfas.logbook_store import form_code
            return form_code(self._portal(), slug)
        except Exception:                                   # noqa: BLE001
            return u"logbook %s" % slug

    def form_code(self, slug):
        return self._fc(slug)

    def batch_method_conflicts(self):
        """[(source, method)] that disagree with the batch's method."""
        batch = self._worksheet_batch()
        if batch is None:
            return []
        from senaite.pfas import batch_method as bm
        return bm.resolve(batch)[1]

    def _worksheet_batch(self):
        """The batch of this worksheet's samples (the project link lives there)."""
        ws = self._get_worksheet()
        try:
            for analysis in (ws.getAnalyses() or []) if ws is not None else []:
                batch = analysis.getRequest().getBatch()
                if batch is not None:
                    return batch
        except Exception:                                   # noqa: BLE001
            pass
        return None

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

    def sample_results_page(self):
        """Page 1 — field-sample results per analyte, with per-injection RT /
        ion-ratio and the QC flags that became qualifiers. Grouped by sample."""
        rows = self._injection_rows(qc_type="Sample", role="analyte")
        by_sample = {}
        for r in rows:
            sid = r.get("sample_id") or r.get("injection_name") or "?"
            by_sample.setdefault(sid, []).append({
                "analyte": r.get("analyte", ""),
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
        empty = {"rows": [], "types": [], "specs": {}, "pending_spikes": [], "groups": []}
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
        try:
            from senaite.pfas import qc_cells
        except ImportError:                                  # loaded by path (tests)
            import qc_cells
        spike_types = [t for t in summary.get("qc_types", []) if qc_cells.is_spike(t)]
        shown = qc_cells.tables(summary.get("columns") or [], summary.get("rows") or [],
                                keep=qc_cells.is_spike)
        prof = self._method_profile()
        qca = prof.get("qc_acceptance", {}) or {}
        from senaite.pfas.qc.qc_types import enabled_qc_types
        required = set(enabled_qc_types(prof))
        # whether each is required every run (its windows are the cited notes)
        specs = dict((t, {"required": t in required,
                          "enabled": bool((qca.get(t) or {}).get("enabled", True))})
                     for t in spike_types)
        # per analyte and type, the verdict cells (the QC Review report's table)
        rows = [{"analyte": row.get("analyte", ""),
                 "cells": dict((t, (row.get("cells") or {}).get(t)) for t in spike_types)}
                for row in summary.get("rows", [])]
        return {"rows": rows, "groups": shown["groups"], "types": spike_types,
                "specs": specs, "pending_spikes": self.pending_spike_levels()}

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
        try:
            from senaite.pfas.dilution_ref import get_spikes
        except Exception:
            return []
        spikes = get_spikes(batch)
        profile = self._method_profile() or {}
        matrix = self._batch_matrix()
        levels = ((profile.get("spike_levels") or {}).get(matrix) or {})

        # Spiked injections the RUN contains but the extraction pedigree does
        # not. Driving the prompt from the pedigree alone meant that when
        # FM-ENV-003 was never filled in, `spikes` was empty, the loop yielded
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
                        # all, so the prompt can say "not in FM-ENV-003" rather
                        # than "level missing".
                        "unrecorded": bool(entry.get("from_run"))})
        return out

    def _rounding_rule(self):
        """The rounding rule this worksheet's results are judged and printed
        with: the method x matrix format of the ISSUED reporting-template
        revision, else the method profile's (as the worker's
        export)."""
        if not hasattr(self, "_rule_cache"):
            from senaite.pfas import report_format
            from senaite.pfas.report_templates import issued_snapshot
            prof = self._method_profile() or {}
            try:
                snap, _rev = issued_snapshot(self._portal())
            except Exception:                               # noqa: BLE001
                snap = None
            src = ({report_format.KEY: (snap.get("report_formats") or {}).get(
                       prof.get("method_id") or self.batch_method()) or {}}
                   if snap is not None else prof)
            self._rule_cache = report_format.resolve(src, self._batch_matrix()).get("coa_rounding") or u"epa"
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
        IAnnotations(ws)[CHECKLIST_KEY] = json.dumps(data)

    def _audit(self, ws):
        try:
            from bika.lims.api import snapshot as _snapshot
            _snapshot.take_snapshot(ws)
        except Exception as exc:
            logger.warning("_audit snapshot failed: %s", exc)

    # ── Auto-check computation ────────────────────────────────────────────

    # ── Expiry, judged as of the date the lot was USED ───────────────────────

    def _use_date(self, lb, *fields):
        """The date a logbook says its lots were used, or "" if it does not say.

        There is no single "use date" for a worksheet, and choosing one would be
        wrong: on the real released WS-0005 the FM-ENV-004 processing date is
        2025-10-17 and the FM-ENV-003 extraction date is 2026-08-03 -- ten months
        apart. Each logbook carries the date ITS OWN rows were used, so each set
        of lots is judged against its own date. A worksheet-wide date would
        condemn one set or excuse the other.
        """
        for f in fields:
            v = (lb.get(f) or u"").strip()
            if v:
                return v[:10]
        return u""

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
        """
        if not resolved or not use_date:
            return None
        try:
            if resolved.get("type") == "PreparedStandard":
                # A prep inherits its parents' tighter expiry, so the effective
                # date is the one to judge -- not the date typed on the lot.
                from senaite.pfas.browser.prepared_standards import (
                    _get as _ps_get, effective_expiry_info)
                uid = resolved.get("uid") or u""
                d = _ps_get(portal, uid) if (portal and uid) else None
                exp = ((effective_expiry_info(portal, d) or {}).get("date")
                       if d else resolved.get("expiry_date")) or u""
                if exp and exp < use_date:
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
                        % (lot or name, _effective_expiry(resolved) or u"?",
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
            # calibration-prep lots alone passed with FM-ENV-003 never done
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
        "LFB": "blank", "LCS": "blank",
        "CCV": "ccv", "Calibration": "calibration", "RT": "rt",
        "IS": "is_response", "IS Response": "is_response",
        # per-injection flags on field samples (_injection_qc_rows)
        "Ion ratio": "ion_ratio", "S/N": "sn", "Surrogate": "surrogate",
        # a field reagent blank: a client sample, so not control material
        "FRB": "field_blank",
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
        try:
            from senaite.pfas.qc_qualification import qualifier_for, classify_failure
        except Exception as exc:                            # noqa: BLE001
            logger.error("qualifier library unavailable: %s", exc)
            return None
        failure = self._QC_TYPE_TO_FAILURE.get(qc_type)
        if failure == "is_response":
            # A qc_type of "IS" covers BOTH surrogates and the injection
            # standard, and they need opposite causes: a surrogate travels with
            # the sample so its recovery reflects the matrix, while the
            # injection standard is added at reconstitution so its response
            # reflects the instrument. The compound's ROLE in the method
            # decides. classify_failure cannot help here — it matches on a
            # source string, and "IS" on its own matches nothing.
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
            codes = set(code for code, _reason in codes_for(analysis))
            if not codes:
                continue
            marker = format_remark_codes(codes)
            if not marker:
                continue
            try:
                from senaite.pfas.qc_qualification import remarks_text
                existing = remarks_text(analysis.getRemarks())
                if marker in existing:
                    continue
                analysis.setRemarks(
                    (existing + u"\n" + marker).strip() if existing else marker)
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
        from senaite.pfas.qc_qualification import (
            applies_to_coc, applies_to_sample, reported_keyword)
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
            if e.get("qc_type") == "FRB":
                frb_uids, cocs = frb_scope(e.get("applies_to") or u"")
                return applies_to_coc(frb_uids, cocs, uid, (samples.get(uid) or ((), u""))[1])
            return applies_to_sample(e.get("applies_to") or u"", uid, names, pushed)

        def codes_for(analysis):
            try:
                sample = analysis.getRequest()
                names = (sample.getId(), sample.getClientSampleID())
                uid = sample.UID()
                entries = list(by_keyword.get(analysis.getKeyword()) or ()) + \
                    list(by_keyword.get(self.ALL_ANALYTES) or ())
            except Exception:                               # noqa: BLE001
                return []
            out = []
            for e in entries:
                if applies(e, uid, names):
                    item = (e["code"], e.get("reason") or e.get("qc_type") or u"")
                    if item not in out:
                        out.append(item)
            return out
        return codes_for

    def _injection_qc_rows(self, batch_key):
        """Failing per-injection flags on field samples (RT, ion ratio, S/N,
        surrogate recovery) as QC Summary rows scoped to their own sample.
        They qualify the result and do not hold release; they lived only in injection_results, which the gate
        never read (synthetic runs)."""
        from senaite.pfas.qc_qualification import injection_flag_qc_types
        try:
            rows = self._store().get_injection_results(batch_id=batch_key, qc_type="Sample")
        except Exception as exc:                            # noqa: BLE001
            logger.warning("_injection_qc_rows: %s", exc)
            return []
        out, seen = [], set()
        for r in rows:
            if r.get("passed", 1) or not r.get("flag"):
                continue
            for qc_type in injection_flag_qc_types(r.get("flag"), r.get("role") or u"",
                                                   r.get("std_role") or u""):
                key = (qc_type, r.get("analyte"), r.get("injection_name"))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"analyte": r.get("analyte") or u"", "qc_type": qc_type,
                            "qc_level": r.get("injection_name") or u"",
                            "applies_to": r.get("injection_name") or u"",
                            "value": None, "expected_value": None,
                            "flag": r.get("flag") or u"", "passed": 0,
                            "limit_basis": u"Judged per injection: see the Samples tab",
                            "result_status": "active"})
        return out

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
            from senaite.pfas.qc_qualification import analytes_for_failure
            found = analytes_for_failure(
                failure_type or u"", analyte or u"",
                self._method_id_for_qualification())
            return found or ([analyte] if analyte else [])
        except Exception as exc:                            # noqa: BLE001
            logger.warning("analytes_for_failure(%s, %s): %s",
                           failure_type, analyte, exc)
            return [analyte] if analyte else []

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
            # and the run's calibration approved at review
            return bool(summary.get("overall_pass", False)
                        and self.calibration_review().get("status") == "approved")
        except Exception as exc:
            logger.error("_compute_qc_status: %s", exc)
            return False

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
                applied = summary.get("qualifiers") or []
                if applied:
                    codes = sorted({(q.get("code") or "?") for q in applied})
                    return "qualified", (
                        u"released with {0} qualified result(s) [{1}] — the "
                        u"certificate carries the corresponding statement"
                        .format(len(applied), u", ".join(codes)))
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
                    u"No reagent or standard lots recorded \u2014 fill in "
                    u"{0} and {1}.".format(self._fc("251"), self._fc("252")))
            if not self._extraction_finalized():
                return "blocked", (
                    u"The guided extraction is not finished: {0} must name the "
                    u"lots the samples were extracted with.".format(self._fc("252")))
            return "fail", u""
        if key == "qc_summary":
            summary = self._get_qc_summary(ws)
            if summary.get("error"):
                return "blocked", (
                    u"QC results are not available: {0}".format(
                        summary.get("error")))
            if self.import_problems():
                return "blocked", u"A delivered run was not imported (see the top of the page)."
            if self.subtraction_change_pending():
                return "blocked", (u"The subtraction blank was changed: reprocess the run "
                                   u"so its results use it.")
            failing = []
            unevaluated = []
            qualified = []
            for row in (summary.get("rows") or []):
                for qc_type, cell in (row.get("cells") or {}).items():
                    if not cell:
                        continue
                    if cell.get("status") == "fail":
                        failing.append(qc_type)
                    elif cell.get("status") == "unevaluated":
                        unevaluated.append(qc_type)
                    elif cell.get("status") == "qualified":
                        qualified.append(qc_type)
            parts = []
            # A qualified release is a PASS with something to say, not a
            # failure. It must still be stated: releasing a failing result
            # without the certificate saying so is the thing §7.8.4 forbids.
            if qualified and not failing:
                summary_q = summary.get("qualifiers") or []
                codes = sorted({(q.get("code") or "?") for q in summary_q})
                parts.append(
                    u"released with {0} qualified result(s) [{1}] across "
                    u"{2}".format(len(summary_q), u", ".join(codes),
                                  u", ".join(sorted(set(qualified)))))
            if failing:
                parts.append(u"{0} failing QC result(s) across {1}".format(
                    len(failing), u", ".join(sorted(set(failing)))))
            if unevaluated:
                parts.append(
                    u"{0} result(s) could not be evaluated ({1})".format(
                        len(unevaluated), u", ".join(sorted(set(unevaluated)))))
                # An unevaluated result means a criterion was never configured,
                # which is an ISO 17025 deviation: the batch was measured
                # against no standard. Raise it against the worksheet so the
                # QAO is told and a reviewer has something to resolve, rather
                # than a gate reason that disappears when the page is closed.
                self._raise_unconfigured_deviation(ws, summary)
            # A QC type the method requires every run, that produced no
            # result at all, was not evaluated — silence here is how a batch
            # reaches release with its matrix spike never checked.
            profile = self._method_profile() or {}
            # the QC types the method RUNS -- the same flags the engine reads
            from senaite.pfas.qc.qc_types import enabled_qc_types
            required = set(enabled_qc_types(profile))
            present = set(summary.get("qc_types") or [])
            # a trip blank comes with the samples that ask for one (Field QC
            # on the CoC), not with every run
            missing = sorted(r for r in required
                             if r not in present and r not in ("Dup", "MxB", "TB"))
            if "LFSMD" in missing and "Dup" in present:
                # a sample duplicate run instead of the LFSMD satisfies the
                # batch's precision requirement
                missing.remove("LFSMD")
            if missing:
                parts.append(
                    u"required QC not evaluated: {0}".format(
                        u", ".join(missing)))
            # the run's calibration, approved at review
            from senaite.pfas.run_calibration import gate_reason
            cal_verdict, cal_reason = gate_reason(self.calibration_review())
            if cal_reason:
                parts.append(cal_reason)
            if failing or cal_verdict == "fail":
                return "fail", u"; ".join(parts)
            if unevaluated or missing or cal_verdict == "blocked":
                return "blocked", u"; ".join(parts)
            if qualified:
                return "qualified", u"; ".join(parts)
            return "fail", u""
        return "pending", u""

    def _raise_unconfigured_deviation(self, ws, summary):
        """File/refresh the deviation for criteria this method never set.

        Idempotent by gap signature, so rendering Data Review repeatedly does
        not file duplicates. Never allowed to break the gate: a notification
        problem must not stop a reviewer seeing why the batch is held.
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
            if gaps:
                # self._portal() -- `_portal` is a method on this view, not a
                # module function. Calling it bare raised NameError on every
                # attempt, swallowed by the except below, so no deviation was
                # ever filed. It only surfaced once the gap rows it depends on
                # became visible at all.
                ensure_deviation(self._portal(), ws.getId(), gaps,
                                 filed_by=u"system (QC evaluation)")
        except Exception as exc:                            # noqa: BLE001
            logger.error("could not raise the unconfigured-criteria "
                         "deviation: %s", exc)

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
        return not self.machine_attested_items()

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

    def checklist_json(self):
        """HTML-safe JSON of checklist status for JS use."""
        try:
            raw = json.dumps(self.checklist_status())
            return raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        except Exception:
            return "[]"

    def submission_info(self):
        ws = self._get_worksheet()
        if not ws:
            return {}
        cl = self._get_checklist(ws)
        return {
            "submitted_by": cl.get("submitted_by") or u"",
            "submitted_at": (cl.get("submitted_at") or u"")[:16],
            "approved_by":  cl.get("approved_by") or u"",
            "approved_at":  (cl.get("approved_at") or u"")[:16],
        }

    # ── CoC summary (for CoC tab) ─────────────────────────────────────────

    def _core_collection_date(self, ws):
        from senaite.pfas import core_fields
        return core_fields.core_values(ws).get("sample_collection_date") or u""

    def coc_records_summary(self, ws):
        """The worksheet's samples' CoC records:
        {} when no sample carries a CoC number (older samples: the logbook)."""
        from senaite.pfas import coc_records as cr
        from senaite.pfas.core_fields import samples_of
        samples = list(samples_of(ws))
        nums = [(s.getField("CoCNumber").get(s) or u"") for s in samples]
        if not samples or not any(nums):
            return {}
        portal = self._portal()
        recs = [cr.load(portal, n) for n in sorted(set(n for n in nums if n))]
        recs = [r for r in recs if r]
        receipts = [r.get("receipt") or {} for r in recs]
        received = bool(recs) and all(r.get("status") == cr.RECEIVED for r in recs) and all(nums)
        first = recs[0] if recs else {}
        rc = receipts[0] if receipts else {}
        return {
            "records": [{"number": r["number"], "status": r.get("status"), "origin": r.get("origin"),
                         "flags": (r.get("receipt") or {}).get("flags") or [],
                         "note": (r.get("receipt") or {}).get("note") or u""} for r in recs],
            "missing": [s.getId() for s, n in zip(samples, nums) if not n],
            "all_received": received,
            "client_name": first.get("client") or u"",
            "project_name": first.get("project") or u"",
            "sample_collection_date": self._core_collection_date(ws),
            "lab_received_by": rc.get("received_by") or u"",
            "lab_received_date": rc.get("received_at") or u"",
            "seals_intact": all(x.get("seals_intact") is True for x in receipts) if receipts else False,
            "labels_legible": all(x.get("labels_legible") is True for x in receipts) if receipts else False,
            "holding_time_ok": received and all(x.get("holding_time_ok") is True for x in receipts),
            "condition_notes": u" ".join(x.get("note") or u"" for x in receipts).strip(),
            "reviewed_by": u"", "reviewed_date": u"",
            "n_containers": len(samples),
            "n_transfers": sum(len(r.get("transfers") or []) for r in recs),
            "receipt_thermometer": None,
            "receipt_temps": [(t.get("sample_id") or u"", t.get("observed"), t.get("corrected"))
                              for x in receipts for t in x.get("readings") or []],
        }

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
        run = self.study_run() or {}
        source = run.get("source") or {}
        ws = self._get_worksheet()
        use_date = ((self._logbook_json(ws, u"senaite.pfas.logbook.252") or {}).get("extraction_date")
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
        """The CoC as Data Review checks it: the samples' CoC records, or
        (samples from before CoC numbers) the logbook annotation; {} if none."""
        ws = self._get_worksheet()
        if not ws:
            return {}
        try:
            from_records = self.coc_records_summary(ws)
            if from_records:
                return from_records
        except Exception as exc:                            # noqa: BLE001
            logger.error("coc records summary: %s", exc)
        try:
            # worksheet first, then its batch -- where the CoC logbook is filled
            # (the gate used to read the worksheet only, so a CoC on the batch
            # never counted; found in the 2026-10-06 end-to-end run)
            data = self._logbook_json(ws, u"senaite.pfas.logbook.coc")
            if data:
                return {
                    "client_name":            data.get("client_name") or u"",
                    "project_name":           data.get("project_name") or u"",
                    # core owns it: the samples' Date Sampled (core_fields.py)
                    "sample_collection_date": self._core_collection_date(ws),
                    "lab_received_by":        data.get("lab_received_by") or u"",
                    "lab_received_date":      data.get("lab_received_date") or u"",
                    "seals_intact":           bool(data.get("seals_intact")),
                    "labels_legible":         bool(data.get("labels_legible")),
                    "holding_time_ok":        bool(data.get("holding_time_ok")),
                    "condition_notes":        data.get("condition_notes") or u"",
                    "reviewed_by":            data.get("reviewed_by") or u"",
                    "reviewed_date":          data.get("reviewed_date") or u"",
                    "n_containers":           len(data.get("containers") or []),
                    "n_transfers":            len(data.get("transfers") or []),
                    # : the receipt thermometer and the factor applied
                    "receipt_thermometer":    data.get("receipt_thermometer_record") or None,
                    "receipt_temps":          [(r.get("sample_id") or u"", r.get("temp_c"),
                                                r.get("temp_c_corrected"))
                                               for r in data.get("containers") or []
                                               if isinstance(r, dict)
                                               and r.get("temp_c") not in (None, u"", "")],
                }
        except Exception as exc:
            logger.error("coc_summary: %s", exc)
        return {}

    def _run_date(self, ws):
        """The run's date in the QC record (its last acquisition), or None."""
        try:
            row = self._store().get_batch(ws.getId())
            return (row["run_date"] if row is not None else None) or None
        except Exception:                                   # noqa: BLE001
            return None

    def holding_time_summary(self):
        """Computed holding time for this worksheet's batch.

        Each sample's own collection date (core Date Sampled: core owns it; it was the Chain of Custody's one date) and
        `extraction_date` on FM-ENV-003. Read through `_logbook_json`, which
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
            ext = self._logbook_json(ws, u"senaite.pfas.logbook.252") or {}
            profile = self._method_profile() or {}
            limit = holding_time.limit_for(profile, self._batch_matrix())
            judged = dict(
                (s.getId(), holding_time.evaluate(core_fields.date_sampled(s),
                                                  ext.get("extraction_date"), limit))
                for s in core_fields.samples_of(ws))
            # the extract, extraction to analysis (EPA 537.1 §8.5: 28 days), where the method sets one
            ext_limit = holding_time.extract_limit_for(profile, self._batch_matrix())
            if ext_limit is not None:
                judged[u"extract"] = holding_time.evaluate_extract(
                    ext.get("extraction_date"), self._run_date(ws), ext_limit)
            verdict = holding_time.combine(judged)
        except Exception as exc:                            # noqa: BLE001
            logger.error("holding_time_summary: %s", exc)
            return holding_time.evaluate(None, None, None)
        verdict["matrix"] = self._batch_matrix()
        verdict["blocking"] = verdict["status"] in holding_time.BLOCKING
        return verdict

    # ── Traceability ──────────────────────────────────────────────────────

    def _build_lot_indices(self, portal):
        """Build in-memory lot dicts (lot_number is not a catalog index).

        ARCHIVED reagents are excluded. This walked
        `objectValues()` raw, so a lot the lab had deliberately withdrawn still
        satisfied traceability — demonstrated live: archiving a parent left the
        gate reporting `resolved=True`. Every other consumer of reagent data
        filters archived lots; this one did not, which is also §33.9's "three
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
        knows its batch. This used to read a `batch_id` out of the CoC logbook
        — a field the CoC schema does not define, so the join was always None
        and the traceability gate saw nothing however carefully the logbooks
        had been filled in.
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
        # Legacy: a CoC that does carry a batch_id still resolves.
        try:
            raw = IAnnotations(ws).get(u"senaite.pfas.logbook.coc")
            bid = (json.loads(raw).get("batch_id") or "").strip() if raw else ""
            if bid:
                from senaite.pfas.batch_ref import get_batch
                return get_batch(self._portal(), bid)
        except Exception:
            pass
        return None

    def _logbook_json(self, ws, key):
        """Logbook data with a DUAL-READ home: the worksheet first
        (canonical), else the CoC-linked batch (where the logbook
        views historically write) — so review finds the data wherever the
        bench recorded it."""
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
        portal = self._portal()

        def _load(key):
            return self._logbook_json(ws, key)

        lb252 = _load(u"senaite.pfas.logbook.252")
        lb251 = _load(u"senaite.pfas.logbook.251")
        # FM-ENV-004 (sample processing / homogenisation). Its rows were traced
        # NOWHERE: the walk read 252 and 251 only, so a grinder-blade or sorbent
        # lot named here was neither resolved nor reported unresolved, and the
        # balance the samples were WEIGHED on had no calibration chain. Same
        # structural gap as §33.12, in the one logbook the walk never learned to
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

        # Each logbook's own date, because its rows were used on ITS date.
        use_252 = self._use_date(lb252, "extraction_date")
        use_251 = self._use_date(lb251, "prepared_date")
        use_253 = self._use_date(lb253, "processing_date")
        # Every logbook the walk reads appears here. A logbook left out would skip
        # its expiry check SILENTLY, which is the failure §43.1 exists to prevent —
        # an unenforceable check must not look like a satisfied one.
        for lb_name, lb_date in ((self._fc("252"), use_252),
                                 (self._fc("251"), use_251),
                                 (self._fc("253"), use_253)):
            if not lb_date:
                tree["warnings"].append(
                    u"%s records no date, so the lots it names cannot be checked "
                    u"for expiry at the time of use" % lb_name)

        # --- FM-ENV-003: reagents[] table ---
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
                # it pass -- the same way the root-URL guard in §41.6 was caught.
                reason = self._expired_at_use(
                    self._reagent_record(reagent_by_lot[lot]), lot, name,
                    use_252, portal)
                if reason:
                    tree["unresolved"].append({
                        "source": "252.reagents", "lot": lot, "name": name,
                        "reason": reason,
                    })
            elif lot:
                tree["unresolved"].append({
                    "source": "252.reagents", "lot": lot, "name": name,
                    # EVERY unresolved entry carries its own reason, so the
                    # Traceability tab needs no fallback branch and cannot give
                    # the wrong advice. The expiry-at-use entries (§43) name a lot
                    # that IS in inventory, and the old blanket message sent the
                    # reviewer to fix something that was not wrong.
                    "reason": u"lot is not in the inventory — enter it to "
                              u"resolve this link",
                })
            tree["direct_reagents"].append(entry)

        # --- FM-ENV-003: standards[] table ---
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
                entry["resolved"] = {"title": ps.Title(),
                                     "url": ps.absolute_url(),
                                     "uid": ps.getId(),
                                     "type": "PreparedStandard"}
            elif lot and lot in reagent_by_lot:
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

        # --- FM-ENV-003: extraction_materials[] table ---
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
            elif lot:
                tree["unresolved"].append({
                    "source": "252.extraction_materials", "lot": lot,
                    "name": name,
                    "reason": u"lot is not in the inventory — enter it to "
                              u"resolve this link",
                })
            tree["direct_reagents"].append(entry)

        # --- FM-ENV-004: processing_materials[] table ---
        # Traced nowhere, exactly as extraction_materials was before §33.12: the
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
                    self._fc("253") + u" records %s with lot \u201c%s\u201d, so it is "
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
            elif lot:
                tree["unresolved"].append({
                    "source": "253.processing_materials", "lot": lot,
                    "name": name,
                    "reason": u"lot is not in the inventory — enter it to "
                              u"resolve this link",
                })
            tree["direct_reagents"].append(entry)

        # --- FM-ENV-004: the balance the samples were WEIGHED on ---
        # 253 records `balance_sn` as free text and nothing resolved it, so the
        # mass every result is calculated from rested on a balance with no
        # calibration chain. Same defect §38 fixed for the extraction stages'
        # `equipment_sns`, and the same policy is reused rather than a third one
        # invented: an UNREGISTERED serial is a warning (we cannot tell what it
        # owed), a registered unit with no verification for the day is a problem.
        bal_sn = (lb253.get("balance_sn") or u"").strip()
        if bal_sn:
            try:
                from senaite.pfas import facility_qc as _fq253
                entry = {"label": self._fc("253") + u" balance", "serial": bal_sn,
                         "unit": None, "records": [], "problems": [],
                         "warnings": []}
                unit = _fq253.unit_by_serial(bal_sn)
                if unit is None:
                    entry["warnings"].append(
                        u"balance %s is not registered in Facility QC, so its "
                        u"calibration on the processing date is unknown" % bal_sn)
                elif not use_253:
                    entry["warnings"].append(
                        self._fc("253") + u" records no processing date, so balance %s "
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
                        "name": self._fc("253") + u" balance", "reason": prob,
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
                                u"serial %s is not registered in Facility QC, so "
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

        # --- FM-ENV-002: lot_ref fields ---
        LOT_REF_FIELDS = [
            ("pds_a_lot",         u"PDS-A"),
            ("pds_b_lot",         u"PDS-B"),
            ("analyte_pds_lot",   u"Analyte PDS"),
            ("analyte_spike_lot", u"Surrogate Spike"),
            ("cal_a_lot",         u"CAL-A"),
        ]
        for field_name, display_label in LOT_REF_FIELDS:
            lot_ref = (lb251.get(field_name) or u"").strip()
            if not lot_ref:
                continue
            ps_node = {
                "field":           field_name,
                "label":           display_label,
                "lot":             lot_ref,
                "title":           u"",
                "prepared_date":   u"",
                "prepared_by":     u"",
                "expiry_date":     u"",
                "url":             u"",
                "found":           False,
                "parent_reagents": [],
            }
            if lot_ref in ps_by_lot:
                ps_obj = ps_by_lot[lot_ref]
                ps_node["found"]        = True
                ps_node["title"]        = ps_obj.Title()
                ps_node["prepared_date"]= str(getattr(ps_obj, "prepared_date", "") or "")[:10]
                ps_node["prepared_by"]  = getattr(ps_obj, "prepared_by", "") or u""
                ps_node["expiry_date"]  = str(getattr(ps_obj, "expiry_date", "") or "")[:10]
                ps_node["url"]          = ps_obj.absolute_url()

                # Judged against the date FM-ENV-002 says these standards were
                # used, not today. The parent-tightened expiry is the one that
                # counts -- a prep whose source CRM expired first expired with it.
                reason = self._expired_at_use(
                    {"type": "PreparedStandard", "uid": ps_obj.getId(),
                     "expiry_date": ps_node["expiry_date"]},
                    lot_ref, ps_node["title"], use_251, portal)
                if reason:
                    tree["unresolved"].append({
                        "source": field_name, "lot": lot_ref,
                        "name": ps_node["title"], "label": display_label,
                        "reason": reason,
                    })

                try:
                    ps_ann  = IAnnotations(ps_obj)
                    raw_par = ps_ann.get(u"senaite.pfas.prepstd.parent_reagents")
                    parents = json.loads(raw_par) if raw_par else []
                except Exception:
                    parents = []

                # LEVEL 1 IS NOW GATED. This loop was the only
                # branch in this method with no `else` appending to
                # tree["unresolved"], and _compute_traceability_status keys
                # solely off that list — so a parent naming a reagent that does
                # not exist PASSED the release gate while a nonexistent reagent
                # named directly in the 252 FAILED it. Proven by that contrast
                # on the live instance. The failure was rendered in the
                # Traceability tab and gated nowhere: the ISO 17025 §6.6 leaf
                # link was the one link in the chain with no enforcement.
                # THE FULL HIERARCHY, not one level. A lot may be made from
                # another lot made from a CRM, and every branch has to end at a
                # manufacturer or at the Type 1 water QC log for the day the
                # water was used.
                #
                # Same walk the Certificate of Preparation prints, deliberately:
                # the document and the gate used to disagree, and §33.9 recorded
                # three resolvers giving three different answers about whether a
                # parent existed. One function, one answer.
                try:
                    from senaite.pfas.browser.prepared_standards import (
                        _obj_to_dict as _psdict, build_parentage,
                        parentage_problems)
                    ps_node["parentage"] = build_parentage(
                        portal, _psdict(ps_obj))
                    for prob in parentage_problems(ps_node["parentage"]):
                        tree["unresolved"].append({
                            "source": "prepstd.parentage",
                            "lot": prob.get("lot"),
                            "name": prob.get("name"),
                            "reason": prob.get("reason"),
                        })
                except Exception as exc:                    # noqa: BLE001
                    logger.error("parentage walk for %s: %s", lot_ref, exc)
                    tree["unresolved"].append({
                        "source": "prepstd.parentage", "lot": lot_ref,
                        "name": ps_node["title"],
                        "reason": u"parentage could not be resolved (%s)" % exc,
                    })

                if not parents:
                    # Kept alongside the walk: build_parentage reports this too,
                    # but the flat `parent_reagents` list below is what the
                    # Traceability tab renders, and a zero-parent standard must
                    # be unmistakable in both.
                    tree["unresolved"].append({
                        "source": "prepstd.parents", "lot": lot_ref,
                        "name": ps_node["title"],
                        "reason": u"no parent reagents recorded",
                    })
                for p in parents:
                    p_lot = (p.get("lot") or u"").strip()
                    p_entry = {
                        "name":     p.get("name") or u"",
                        "supplier": p.get("supplier") or u"",
                        "lot":      p_lot,
                        "qty":      p.get("qty") or u"",
                        "unit":     p.get("unit") or u"",
                        "resolved": None,
                    }
                    p_obj = self._resolve_parent(portal, p, reagent_by_lot)
                    if p_obj is not None:
                        p_entry["resolved"] = self._reagent_dict(p_obj)
                        # A parent with NO recorded expiry is undocumented
                        # provenance, not a clean lot.
                        # `_is_expired` answers False for it -- correctly, since
                        # an unrecorded date is not evidence of expiry -- so the
                        # refusal has to happen here.
                        #
                        # Applied to PARENTS only, deliberately: the parent is
                        # the manufacturer link, which is what
                        # requires provenance for. Extending it to the direct
                        # 252/251 rows is a wider behaviour change and is left
                        # open rather than slipped in.
                        try:
                            from senaite.pfas.browser.reagents import (
                                _expiry_unknown, _obj_to_dict as _rd)
                            if _expiry_unknown(_rd(p_obj)):
                                tree["unresolved"].append({
                                    "source": "prepstd.parents",
                                    "lot": p_lot or u"(blank)",
                                    "name": p.get("name") or u"",
                                    "reason": u"parent reagent has no recorded "
                                              u"expiry",
                                })
                        except ImportError:
                            pass
                    else:
                        tree["unresolved"].append({
                            "source": "prepstd.parents",
                            "lot": p_lot or u"(blank)",
                            "name": p.get("name") or ps_node["title"],
                            "reason": u"parent reagent not in inventory",
                        })
                    ps_node["parent_reagents"].append(p_entry)
            else:
                tree["unresolved"].append({
                    "source": field_name, "lot": lot_ref, "label": display_label,
                    "reason": u"no prepared standard with this lot number "
                              u"exists in the inventory",
                })
            tree["prepared_standards"].append(ps_node)

        return tree

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
        out = self._build_qc_matrix(qc_results, qc_acceptance, run_date)
        if not out.get("result_count"):
            # a run on record with no QC row at all is a lost write, never a
            # pass (an empty matrix read overall_pass=True)
            return {"error": u"no QC results are stored for this run; reprocess it",
                    "rows": [], "qc_types": [], "overall_pass": False,
                    "batch_id": batch_key}
        return out

    def _build_qc_matrix(self, qc_results, qc_acceptance, run_date=""):
        """Group QC results into analyte x qc_type matrix with pass/warn/fail."""
        by_analyte = {}
        qc_type_set = []

        for r in qc_results:
            if r.get("result_status") == "voided":
                continue
            analyte  = r.get("analyte", "") or ""
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
        unmapped = []
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
                values = []
                for rec in recs:
                    passed = bool(rec.get("passed", 1))
                    val    = rec.get("value")
                    exp    = rec.get("expected_value")
                    recovery = None
                    if qc_type != "MB" and val is not None and exp:
                        try:
                            # shown as the checks judge it: a whole percent by
                            # the method's rule
                            from senaite.pfas.rounding import judged_pct
                            recovery = judged_pct(float(val) / float(exp) * 100.0,
                                                  self._rounding_rule())
                        except (TypeError, ZeroDivisionError):
                            recovery = None

                    if rec.get("result_status") == "unevaluated":
                        # A criterion the method never configured. Distinct
                        # from a failure -- nothing was judged -- and it must
                        # hold the report rather than read as a pass.
                        cell_status = "unevaluated"
                        overall_pass = False
                    elif not passed:
                        # A failure the QAO's library says may be released is
                        # QUALIFIED, not a block: the result goes out with a
                        # code and a statement on the certificate. Control
                        # material can never reach this branch as qualifiable —
                        # disposition_for blocks it regardless of the library.
                        qual = self._qualify_failure(qc_type, rec.get("analyte"))
                        if qual and not qual.get("needs_config"):
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
                                })
                        elif qual and qual.get("needs_config"):
                            cell_status = "unevaluated"
                            overall_pass = False
                            unmapped.append(qual.get("prompt") or u"")
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
                        "kind": u"RPD" if (rec.get("qc_level") or u"").split(u" ")[0] == u"RPD" else u"",
                    })

                cells[qc_type] = {
                    "status": cell_status,
                    "badge":  "PASS" if cell_status == "ok" else cell_status.upper(),
                    "n":      len(values),
                    "values": values,
                }

            rows.append({"analyte": analyte, "cells": cells})

        # what each cell shows: the value, coloured by its verdict, and the
        # criteria cited once per column (qc_cells)
        try:
            from senaite.pfas import qc_cells
        except ImportError:                                  # loaded by path (tests)
            import qc_cells
        display_cols, col_values = [], {}
        for row in rows:
            row["display"] = {}
            for qt in qc_type_set:
                c = row["cells"].get(qt)
                if not c:
                    continue
                for key, vals in qc_cells.split(qt, c["values"]):
                    row["display"][key] = qc_cells.cell_display(
                        qt, vals, qc_cells.sub_status(c["status"], vals))
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
            "unmapped":    unmapped,
            "result_count": sum(len(by_analyte[a].get(qt, []) or []) for a in by_analyte for qt in qc_type_set),
            "run_date":    run_date,
        }

    def get_qc_summary(self):
        ws = self._get_worksheet()
        if not ws:
            return {"error": "no_worksheet", "rows": [], "qc_types": [], "overall_pass": False}
        try:
            return self._get_qc_summary(ws)
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
        """
        ws = self._get_worksheet()
        if ws is None:
            return None
        try:
            from senaite.pfas import disclosure
            from senaite.pfas import worksheet_criteria_snapshot as wcs
        except Exception as exc:
            logger.error("accreditation_disclosure: import failed: %s", exc)
            return None

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
            from senaite.pfas import report_format, rounding
            from senaite.pfas.report_limits import canonical_matrix
            if not hasattr(self, "_reported_profile"):
                self._reported_profile = self._method_profile() or {}
            profile = self._reported_profile
            matrix = canonical_matrix(profile, sample_type)
            fmt = report_format.resolve(profile, matrix)
            text = rounding.round_sig(result, int(fmt.get("coa_sig_figs") or 3),
                                      fmt.get("coa_rounding") or rounding.DEFAULT_RULE)
            unit = unit or (profile.get("unit_map") or {}).get(matrix) or u""
            return (text if text is not None else result), unit
        except Exception:                                   # noqa: BLE001
            return result, unit

    def final_data_diagnosis(self):
        """When the Final Data table is empty, say WHY (which link in the
        chain has no data) instead of rendering a silent blank."""
        ws = self._get_worksheet()
        if not ws:
            return u"No worksheet found for this batch."
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
          1. ARs assigned via the worksheet's own analyses (SENAITE-native);
          2. the SENAITE Batch named by this worksheet's CoC (`batch_id`) —
             the CoC accompanies the worksheet, so it carries the link;
          3. legacy: ARs whose Batch UID equals this worksheet's UID."""
        ws = self._get_worksheet()
        if ws is None:
            return []
        try:
            cat = getToolByName(self.context, "senaite_catalog_sample")
        except Exception:
            return []
        # 2. CoC carries the batch id
        try:
            raw = IAnnotations(ws).get(u"senaite.pfas.logbook.coc")
            coc = json.loads(raw) if raw else {}
            bid = (coc.get("batch_id") or "").strip()
            if bid:
                portal = getToolByName(self.context,
                                       "portal_url").getPortalObject()
                from senaite.pfas.batch_ref import get_batch
                batch = get_batch(portal, bid)
                if batch is not None:
                    ars = [b.getObject() for b in cat(
                        portal_type="AnalysisRequest",
                        getBatchUID=batch.UID())]
                    if ars:
                        return ars
        except Exception as exc:
            logger.warning("_batch_ars coc join: %s", exc)
        # 3. legacy join
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
                    ar_map[ar_uid] = {
                        "sample_id": sample_id,
                        "client_sample_id": client_sid,
                        "sample_type": sample_type,
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
                try:
                    if analysis.isRetested():
                        reported = u"replaced by its dilution"
                    elif analysis.isRetest():
                        from senaite.pfas.browser.dilution_retests import dilution_fold
                        fold = dilution_fold(analysis)
                        reported = (u"reported \u2014 dilution %g-fold" % fold) if fold \
                            else u"reported \u2014 retest"
                except Exception:                           # noqa: BLE001
                    pass
                # shown as the certificate states it:
                # the lab's rounding for the method x matrix, and the unit
                # from the profile when core holds none (runs before then)
                result, unit = self._as_reported(result, unit, ar_map[ar_uid]["sample_type"])
                ar_map[ar_uid]["analyses"].append({
                    "analyte":      keyword,
                    "result":       result,
                    "unit":         unit,
                    "qualifier":    qualifier,
                    "qc_codes":     u", ".join(sorted(set(c for c, _r in codes_for(analysis)))),
                    "qc_reasons":   u"; ".join(r for _c, r in codes_for(analysis) if r),
                    "review_state": state,
                    "reported":     reported,
                })
            except Exception as exc:
                logger.error("get_final_data analysis loop: %s", exc)

        try:
            from senaite.pfas import qc_cells
        except ImportError:                                  # loaded by path (tests)
            import qc_cells
        for ar_uid in sorted(ar_map.keys(), key=lambda u: ar_map[u]["sample_id"]):
            ar_data = ar_map[ar_uid]
            for a in sorted(ar_data["analyses"], key=lambda x: x["analyte"]):
                rows.append({
                    "sample_id":        ar_data["sample_id"],
                    "client_sample_id": ar_data["client_sample_id"],
                    "sample_type":      ar_data["sample_type"],
                    "analyte":          a["analyte"],
                    "result":           a["result"],
                    "unit":             a["unit"],
                    "qualifier":        a["qualifier"],
                    "qc_codes":         a.get("qc_codes") or u"",
                    "qc_reasons":       a.get("qc_reasons") or u"",
                    # the codes drawn as the QC Summary draws a qualified cell
                    "qc_cell":          qc_cells.code_cell(a.get("qc_codes"), a.get("qc_reasons")),
                    "review_state":     a["review_state"],
                    "reported":         a.get("reported") or u"",
                })
        return rows

    # ── Extraction record ──────

    _SOURCE_LABELS = {"252": (u"252", u"Extraction Log"), "253": (u"253", u"Sample Processing Log"),
                      "251": (u"251", u"Calibration Curve Prep Log")}

    def source_label(self, source):
        """A traceability source as the reader knows it: "252.standards" ->
        "Extraction Log (FM-ENV-003), standards"; storage slugs never shown."""
        slug, _sep, part = (source or u"").partition(u".")
        if slug in self._SOURCE_LABELS:
            key, title = self._SOURCE_LABELS[slug]
            return u"%s (%s)%s" % (title, self._fc(key),
                                   u", " + part.replace(u"_", u" ") if part else u"")
        if slug == u"prepstd":
            return u"prepared standard parents"
        return (source or u"").replace(u"_", u" ")

    def extraction_record(self):
        """The guided extraction of this worksheet's batch, for review: every
        stage (extraction_review.review), the per-sample amounts and final
        volumes and the dilutions recorded in FM-ENV-003, finalized or not.
        Its being finished is part of the traceability gate; the rest is shown for review."""
        batch = self._extraction_home(self._get_worksheet())
        if batch is None:
            return None
        try:
            from senaite.pfas.browser.extraction_guide import _load_session
            from senaite.pfas.browser.logbooks import _get_logbook
            from senaite.pfas.extraction_review import review
            from senaite.pfas.method_profile_store import get_profile
            from senaite.pfas import sample_table
            from senaite.pfas.dilution_ref import parse_factor
            sess = _load_session(batch)
            if not sess:
                return {"started": False, "batch_uid": batch.UID(), "batch_id": batch.getId()}
            stages = get_profile(self._portal(), sess.get("method_id", "")).get("extraction_stages") or []
            rv = review(sess, stages)
            rows = (_get_logbook(batch, "252") or {}).get("samples") or []
            samples = sample_table.rows_for_card(rows, [])
            return {
                "started": True, "batch_uid": batch.UID(), "batch_id": batch.getId(),
                "finalized": bool(sess.get("finalized")),
                "finalized_at": sess.get("finalized_at") or u"",
                "finalized_by": sess.get("finalized_by") or u"",
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
            return [u"No guided extraction is recorded for batch %s." % rec["batch_id"]]
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
                "uploaded_at": datetime.datetime.utcfromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
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

    # ── Recent worksheets for selector ───────────────────────────────────

    def recent_worksheets_debug(self):
        """Debug method — returns HTML string describing what the catalog query returns."""
        lines = []
        try:
            cat = getToolByName(self.context, "senaite_catalog_worksheet")
            lines.append("cat=%r ctx_type=%s" % (cat, type(self.context).__name__))
            if cat is None:
                lines.append("CAT IS NONE - trying portal")
                cat = getToolByName(self._portal(), "senaite_catalog_worksheet")
                lines.append("portal cat=%r" % cat)
            brains = cat(portal_type="Worksheet", review_state=["open", "to_be_verified"])
            lines.append("brains=%d" % len(brains))
            for b in brains[:5]:
                lines.append("  id=%s state=%s" % (b.getId, b.review_state))
        except Exception as exc:
            lines.append("ERROR: %s" % exc)
        return " | ".join(lines)

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
        (once submitted) how long it has been in review."""
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
        for b in brains[:50]:
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
                                    if under_review else u"—",
                })
            except Exception as exc:
                logger.error("recent_worksheets brain: %s", exc)
        return result

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

    def _redirect_with_msg(self, msg, msg_type="ok", tab=None, detail=None):
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
        self.request.response.redirect(url)
        return u""

    # ── Corrections (ISO 17025: traceable, initialed + dated) ─────────────
    CORRECTIONS_KEY = u"senaite.pfas.data_review.corrections"
    # field → (label, CoC-annotation key). Whitelist: only these are correctable.
    # The collection date is not: core owns it (each sample's Date Sampled; core_fields.py) and it is corrected on the sample.
    CORRECTABLE_FIELDS = {
        "lab_received_date":      (u"Lab Received Date",      "lab_received_date"),
    }

    def signature_for(self, initials):
        """Signature image URL + fullname for a set of initials (staff pool) —
        appended next to sign-offs so documents carry the person's signature."""
        try:
            from senaite.pfas.staff import find_by_initials
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            return find_by_initials(portal, initials) or {}
        except Exception:
            return {}

    def publish_url(self):
        """senaite.impress COA (publish) view pre-loaded with this
        worksheet's samples — the client-facing report step (core reuse)."""
        ars = self._batch_ars()
        if not ars:
            return u""
        uids = ",".join(ar.UID() for ar in ars)
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        return u"{0}/samples/publish?uids={1}".format(
            portal.absolute_url(), uids)

    def template_status(self):
        """The issued reporting-template revision the certificate will be drawn
        from, or None when none is issued (publishing is then refused)."""
        try:
            from senaite.pfas.report_templates import issued_snapshot
            return issued_snapshot(self._portal())[1]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("template_status: %s", exc)
            return None

    def reissue_ars(self):
        """ARs in this worksheet's batch that are already published — issuing a
        CoA for them is an AMENDED reissue. We capture an amendment reason
        up front so the controlled register records why (best-effort policy)."""
        from bika.lims import api as _bapi
        out = []
        for ar in self._batch_ars():
            try:
                if _bapi.get_review_status(ar) == "published":
                    out.append(ar)
            except Exception:
                pass
        return out

    def is_reissue(self):
        return bool(self.reissue_ars())

    def needs_assignment(self):
        """True when this worksheet has no assigned analyses but its linked
        batch has samples — the assign-before-submit process point."""
        ws = self._get_worksheet()
        if ws is None:
            return False
        try:
            if len(ws.getAnalyses() or []):
                return False
        except Exception:
            pass
        return bool(self._batch_ars())

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

    def _log_correction(self, ws, field_label, old, new, initials, reason):
        user = getSecurityManager().getUser()
        entry = {
            "field":    field_label,
            "old":      old or u"—",
            "new":      new or u"—",
            "user":     user.getId(),
            "initials": initials,
            "ts":       datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "reason":   reason or u"",
        }
        log = self.corrections()
        log.append(entry)
        IAnnotations(ws)[self.CORRECTIONS_KEY] = json.dumps(log)

    def _handle_assign_batch_samples(self):
        """D44#4: enforceable process order. Receives due samples and assigns
        their UNSUBMITTED analyses to this worksheet — must happen BEFORE
        results are submitted (SENAITE's assign guard forbids it after).
        Runs in a real request, so workflow guards resolve."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if ws is None:
            return self._redirect_with_msg("no_worksheet", "error")
        from bika.lims import api as _bapi
        received = assigned = skipped = 0
        for ar in self._batch_ars():
            try:
                if _bapi.get_workflow_status_of(ar) == "sample_due":
                    _bapi.do_transition_for(ar, "receive")
                    received += 1
            except Exception as exc:
                logger.warning("receive %s: %s", ar.getId(), exc)
            for an in ar.getAnalyses(full_objects=True):
                state = _bapi.get_workflow_status_of(an)
                if state != "unassigned":
                    skipped += 1
                    continue
                try:
                    ws.addAnalysis(an)
                    assigned += 1
                except Exception as exc:
                    logger.warning("assign %s: %s", an.getKeyword(), exc)
                    skipped += 1
        self._audit(ws)
        msg = (u"Assigned {0} analyses ({1} samples received; {2} skipped — "
               u"already submitted/assigned)").format(assigned, received,
                                                      skipped)
        url = "{0}/@@pfas-data-review?batch_id={1}&msg={2}&msg_type={3}".format(
            self._portal().absolute_url(), self.batch_id(),
            msg.replace(" ", "+"), "ok" if assigned else "error")
        self.request.response.redirect(url)
        return u""

    def _handle_correct_field(self):
        """E-sign-style correction: whitelisted field, REQUIRED initials,
        old→new logged, write-through to the owning CoC record."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        field = self.request.form.get("field", "")
        new_value = (self.request.form.get("new_value") or "").strip()
        initials = (self.request.form.get("initials") or "").strip()
        reason = (self.request.form.get("reason") or "").strip()
        if field not in self.CORRECTABLE_FIELDS:
            return self._redirect_with_msg("invalid_item", "error", tab="coc")
        if not initials:
            return self._redirect_with_msg("initials_required", "error", tab="coc")
        label, coc_key = self.CORRECTABLE_FIELDS[field]
        ann = IAnnotations(ws)
        raw = ann.get(u"senaite.pfas.logbook.coc")
        data = json.loads(raw) if raw else {}
        old_value = data.get(coc_key) or u""
        if new_value == old_value:
            return self._redirect_with_msg("no_change", "error", tab="coc")
        data[coc_key] = new_value
        ann[u"senaite.pfas.logbook.coc"] = json.dumps(data)
        self._log_correction(ws, label, old_value, new_value, initials, reason)
        self._audit(ws)
        return self._redirect_with_msg("correction_logged", "ok", tab="coc")

    def _handle_post(self):
        action = self.request.form.get("action", "")
        dispatch = {
            "correct_field":            self._handle_correct_field,
            "assign_batch_samples":     self._handle_assign_batch_samples,
            "check_item":               self._handle_check_item,
            "submit_for_review":        self._handle_submit_for_review,
            "approve_release":          self._handle_approve_release,
            "reject":                   self._handle_reject,
            "upload_instrument_report": self._handle_upload_instrument_report,
            "download_report":          self._handle_download_report,
            "record_amendment_reason":  self._handle_record_amendment_reason,
            "record_spike_level":       self._handle_record_spike_level,
            "request_run":              self._handle_request_run,
            "clear_run_plan":           self._handle_clear_run_plan,
            "choose_subtraction_blank": self._handle_choose_subtraction_blank,
            "approve_calibration":      self._handle_approve_calibration,
            "reject_calibration":       self._handle_reject_calibration,
        }
        handler = dispatch.get(action)
        if handler and action in self.RECORD_ACTIONS and self.ws_state() in self.CLOSED_STATES:
            # the checklist and its signatures ARE the technical review: once
            # submitted they are read-only. A replayed sign-off overwrote a
            # verified worksheet's signatures so its submission postdated its
            # approval, leaving no trace
            return self._redirect_with_msg("record_closed", "error")
        if handler:
            return handler()
        self.request.response.redirect(self.request.URL)
        return u""

    # the actions that change the review record, and the states that close it
    RECORD_ACTIONS = frozenset((
        "assign_batch_samples", "check_item", "submit_for_review",
        "upload_instrument_report", "record_spike_level", "request_run",
        "clear_run_plan", "choose_subtraction_blank", "approve_calibration",
        "reject_calibration"))
    CLOSED_STATES = frozenset(("to_be_verified", "verified", "published"))

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
        earlier approved curve it reused (run_calibration.review_state), with
        the curve cards' data. Once per request."""
        if hasattr(self, "_cal_review"):
            return self._cal_review
        from senaite.pfas import run_calibration as rc
        state = rc.review_state([], {}, [])
        state["runs_json"] = u"[]"
        ws = self._get_worksheet()
        if ws is not None and self.db_available:
            try:
                store = self._store()
                own = store.calibrations_for_batch(ws.getId())
                manifest = self._run_manifest(ws)
                rd = rc.reused_run_date(manifest)
                reused = (store.get_calibrations_for_run(rd, method=self.batch_method())
                          if (rd and not own) else [])
                state = rc.review_state(own, manifest, reused, ws.getId())
                from senaite.pfas.browser.calibrations import PFASCalibrationsView
                cv = PFASCalibrationsView(self._portal(), self.request)
                if own:
                    state["runs_json"] = cv.calibration_runs_json(batch_id=ws.getId())
                elif state["source"] == u"reused":
                    state["runs_json"] = cv.calibration_runs_json(run_date=rd,
                                                                  method=self.batch_method())
                else:
                    state["runs_json"] = u"[]"
            except Exception as exc:                        # noqa: BLE001
                logger.warning("calibration_review: %s", exc)
                state["runs_json"] = u"[]"
        self._cal_review = state
        return state

    def calibration_approve_json(self):
        """The approve / reject bar's settings for the shared curve script."""
        st = self.calibration_review()
        ws = self._get_worksheet()
        return json.dumps({"url": (ws.absolute_url() if ws is not None else u"") + u"/@@pfas-data-review",
                           "can": bool(self.can_act()), "reused": st.get("source") == u"reused",
                           "from": st.get("from") if st.get("source") == u"reused" else u"",
                           "state": st.get("status")})

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

    def blank_comparisons(self):
        """This run's blanks, each against the previous comparable blank
        (same kind, method, matrix): what rose and the lots that differ
        (blank_history)."""
        ws = self._get_worksheet()
        if ws is None or not self.db_available:
            return []
        try:
            from senaite.pfas.browser.blank_history import blank_data, compare, previous_blank
            runs = blank_data(self.batch_method() or None)
            out, cache = [], {}
            for cur in [r for r in runs if r["batch_id"] == ws.getId()]:
                out.append(compare(self._portal(), cur, previous_blank(runs, cur, cache), cache))
            return out
        except Exception as exc:                            # noqa: BLE001
            logger.warning("blank_comparisons: %s", exc)
            return []

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

    def _handle_record_amendment_reason(self):
        """Stash an amendment reason on each already-published sample, then
        continue to the publisher. The publish (republish) transition's
        subscriber consumes it into the controlled register."""
        if not self.can_act():
            return self._redirect_with_msg("permission_denied", "error")
        reason = (self.request.form.get("reason") or "").strip()
        if reason:
            from senaite.pfas.browser.controlled_publications import \
                set_pending_amendment_reason
            for ar in self.reissue_ars():
                set_pending_amendment_reason(ar, reason)
        purl = self.publish_url()
        self.request.response.redirect(purl or self.request.URL)
        return u""

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
        # ISO 17025 §10: holding_time_ok must be confirmed before CoC can pass.
        # The tick is necessary and NOT sufficient — a measured breach blocks
        # the gate whether or not somebody ticked the box. Until 2026-08-06 the
        # tick was the only evidence in the system that a sample was in time.
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
            if not coc.get("holding_time_ok"):
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
        if not self.all_items_pass():
            return self._redirect_with_msg("checklist_incomplete", "error")
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
        return self._redirect_with_msg("submitted_for_review", "ok")

    def _handle_approve_release(self):
        if not self.is_manager():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        if self.ws_state() != "to_be_verified":
            return self._redirect_with_msg("wrong_state", "error")
        if not self.all_items_pass():
            # The checklist is computed afresh: a run reprocessed after
            # submission (or a QC record written later) can fail it. The
            # manager verifies the review as it stands, never as it stood
            # (a reprocess held a submitted worksheet's QC and Approve Release
            # still verified it).
            return self._redirect_with_msg("checklist_changed", "error")
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

    def _handle_reject(self):
        if not self.is_manager():
            return self._redirect_with_msg("permission_denied", "error")
        ws = self._get_worksheet()
        if not ws:
            return self._redirect_with_msg("no_worksheet", "error")
        if self.ws_state() != "to_be_verified":
            return self._redirect_with_msg("wrong_state", "error")
        wf_tool = getToolByName(self.context, "portal_workflow")
        try:
            wf_tool.doActionFor(ws, "reject")
        except Exception as exc:
            logger.error("reject: %s", exc)
            return self._redirect_with_msg("workflow_error", "error")
        self._audit(ws)
        return self._redirect_with_msg("batch_rejected", "ok")

    # ── dilution / re-injection requests to the bench ───────────────────

    def run_requests(self):
        from senaite.pfas import extraction_batch
        ws = self._get_worksheet()
        return extraction_batch.load_requests(ws) if ws is not None else []

    def request_targets(self):
        """The batch's injections a request may name (members)."""
        from senaite.pfas import extraction_batch
        ws = self._get_worksheet()
        return [m.get("injection") for m in (extraction_batch.load(ws) if ws is not None else [])
                if m.get("injection")]

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
