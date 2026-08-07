# -*- coding: utf-8 -*-
"""
PFAS Data Review workspace (@@pfas-data-review).

Per-batch checklist for Analyst data release:
  - Chain of Custody (manual)
  - Reagent/Standard Traceability (auto)
  - QC Summary (auto)
  - Final Data Summary (manual, stub pending FDA Calculator PDF)
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

# Ordered checklist items (key, label, auto-computed)
_CHECKLIST_ITEMS = [
    ("coc",               u"Chain of Custody",              False),
    ("traceability",      u"Reagent/Standard Traceability", True),
    ("qc_summary",        u"QC Summary",                    True),
    ("final_data",        u"Final Data Summary",            False),
    ("instrument_report", u"Instrument Report",             False),
]


def _is_manager(context):
    try:
        user = getSecurityManager().getUser()
        roles = user.getRolesInContext(context)
        return "Manager" in roles or "LabManager" in roles
    except Exception:
        return False


def _is_analyst(context):
    try:
        user = getSecurityManager().getUser()
        roles = user.getRolesInContext(context)
        return "Analyst" in roles or "Verifier" in roles
    except Exception:
        return False


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
        ws = self._get_worksheet()
        if not ws:
            return u""
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
        return u""

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
        "coc_holding_time_fail":   u"Cannot mark CoC as reviewed: Holding Times OK is not checked. "
                                    u"Samples received past holding time must be documented before releasing.",
        "coc_holding_time_computed_fail":
                                   u"Cannot mark CoC as reviewed — the recorded dates say "
                                   u"otherwise, regardless of the checkbox.",
        "checklist_incomplete":    u"All checklist items must pass before submitting.",
        "submitted_for_review":    u"Submitted for manager review.",
        "workflow_error":          u"Workflow transition failed — check worksheet state.",
        "wrong_state":             u"Worksheet is not in the expected state.",
        "batch_approved":          u"Batch approved and released.",
        "batch_rejected":          u"Batch rejected and returned for re-analysis.",
        "report_uploaded":         u"Instrument report uploaded.",
        "spike_saved":             u"Spike level recorded on the extraction log.",
        "spike_saved_not_method":  (u"Spike level recorded on this batch. The "
                                    u"method's nominal level was not changed "
                                    u"\u2014 that needs a manager."),
        "spike_missing":           u"Enter a spike level.",
        "spike_invalid":           u"Spike level must be a positive number.",
        "no_batch":                u"No batch is linked to this worksheet.",
        "upload_error":            u"File upload failed.",
        "path_error":              u"Download failed — file not found.",
        "initials_required":       u"Your initials are required to sign off / correct — nothing was saved.",
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

    # ── Multi-page verification (D59) ─────────────────────────────────────
    # Each page walks results (from injection_results + qc_results) and checks
    # them against this method's Method-Profile spec. All pages feed the QC
    # Summary gate.

    def _method_profile(self):
        try:
            from senaite.pfas.method_profile_store import get_profile
            mid = self.batch_method()
            return get_profile(self._portal(), mid) or {} if mid else {}
        except Exception:
            return {}

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
        """Page 2 — LFSM/LFSMD/LFB/LCS recoveries + RPD vs the method's spec
        limits, per analyte. Reads the aggregate qc_results (value=recovery/rpd)
        and shows the limit each was judged against."""
        if not self.db_available:
            return {"rows": [], "types": []}
        ws = self._get_worksheet()
        if ws is None:
            return {"rows": [], "types": []}
        summary = self._get_qc_summary(ws)          # reuse the matrix builder
        if summary.get("error"):
            return {"rows": [], "types": [], "error": summary.get("error")}
        # keep only spike/recovery QC types on this page
        spike_types = [t for t in summary.get("qc_types", [])
                       if t in ("LFSM", "LFSMD", "LFB", "LCS", "SD")]
        prof = self._method_profile()
        qca = prof.get("qc_acceptance", {}) or {}
        required = set(prof.get("associated_qc_types", []) or [])
        rows = []
        for row in summary.get("rows", []):
            cells = {}
            for t in spike_types:
                cells[t] = row.get("cells", {}).get(t)
            rows.append({"analyte": row.get("analyte", ""), "cells": cells})
        # per-type spec (recovery window / rpd) + whether required every run
        specs = {}
        for t in spike_types:
            cfg = qca.get(t, {}) or {}
            tiers = cfg.get("tiers", []) or []
            tier0 = tiers[0] if tiers else {}
            specs[t] = {
                "recovery_min": tier0.get("recovery_min"),
                "recovery_max": tier0.get("recovery_max"),
                "rpd_max": tier0.get("rpd_max"),
                "required": t in required,
                "enabled": bool(cfg.get("enabled", True)),
            }
        return {"rows": rows, "types": spike_types, "specs": specs,
                "pending_spikes": self.pending_spike_levels()}

    def pending_spike_levels(self):
        """Spiked injections whose spike level nobody has recorded.

        Without a level the recovery cannot be computed, and it used to be
        skipped in silence — a batch could reach release with its matrix spike
        never evaluated. Rather than blocking, the reviewer is asked for the
        value: these rows drive that prompt.
        """
        ws = self._get_worksheet()
        batch = self._linked_batch(ws) if ws else None
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
        # FM-ENV-252 was never filled in, `spikes` was empty, the loop yielded
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
                                    "spike_ppt": None, "from_run": True}

        out = []
        for injection, entry in sorted(spikes.items()):
            if entry.get("spike_ppt"):
                continue
            label = entry.get("level") or ""
            nominal = None
            for lv in (levels.get("LFSM") or []):
                if not label or lv.get("label") == label:
                    nominal = lv.get("ppt")
                    if lv.get("label") == label:
                        break
            if nominal:
                continue
            out.append({"injection": injection,
                        "parent": entry.get("parent", ""),
                        "level": label,
                        "matrix": matrix,
                        # True when the pedigree does not know this injection at
                        # all, so the prompt can say "not in FM-ENV-252" rather
                        # than "level missing".
                        "unrecorded": bool(entry.get("from_run"))})
        return out

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
        return u""

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
                        }
                return data
        except Exception as exc:
            logger.error("_get_checklist: %s", exc)
        return self._default_checklist(ws)

    def _save_checklist(self, ws, data):
        IAnnotations(ws)[CHECKLIST_KEY] = json.dumps(data)

    def _audit(self, ws):
        try:
            from bika.lims.api import snapshot as _snapshot
            _snapshot.take_snapshot(ws)
        except Exception as exc:
            logger.warning("_audit snapshot failed: %s", exc)

    # ── Auto-check computation ────────────────────────────────────────────

    def _compute_traceability_status(self, ws):
        try:
            tree = self._build_traceability_tree(ws)
            has_data = (
                len(tree.get("direct_reagents", [])) > 0 or
                len(tree.get("direct_standards", [])) > 0 or
                len(tree.get("prepared_standards", [])) > 0
            )
            return has_data and len(tree.get("unresolved", [])) == 0
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
        codes_by_analyte = {}
        for entry in (summary.get("qualifiers") or []):
            analyte = entry.get("analyte")
            code = entry.get("code")
            if analyte and code:
                codes_by_analyte.setdefault(analyte, set()).add(code)
        if not codes_by_analyte:
            return
        stamped = 0
        for analysis in (ws.getAnalyses() or []):
            try:
                keyword = analysis.getKeyword()
            except Exception:                               # noqa: BLE001
                continue
            codes = codes_by_analyte.get(keyword)
            if not codes:
                continue
            marker = format_remark_codes(codes)
            if not marker:
                continue
            try:
                existing = analysis.getRemarks() or u""
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

    def _affected_analytes(self, failure_type, analyte):
        """Reported analytes a failure touches, scoped as narrowly as it is."""
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
            return summary.get("overall_pass", False)
        except Exception as exc:
            logger.error("_compute_qc_status: %s", exc)
            return False

    # ── Public checklist interface ────────────────────────────────────────

    def checklist_status(self):
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

        result = []
        for key, label, auto in _CHECKLIST_ITEMS:
            item = dict(items.get(key, {
                "label": label, "auto": auto, "checked": False,
                "checked_by": None, "checked_at": None, "notes": u"",
            }))
            item["key"] = key
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
                    u"FM-ENV-251 and FM-ENV-252.")
            return "fail", u""
        if key == "qc_summary":
            summary = self._get_qc_summary(ws)
            if summary.get("error"):
                return "blocked", (
                    u"QC results are not available: {0}".format(
                        summary.get("error")))
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
            required = set(profile.get("associated_qc_types") or [])
            present = set(summary.get("qc_types") or [])
            missing = sorted(r for r in required
                             if r not in present and r not in ("Dup", "MxB"))
            if missing:
                parts.append(
                    u"required QC not evaluated: {0}".format(
                        u", ".join(missing)))
            if failing:
                return "fail", u"; ".join(parts)
            if unevaluated or missing:
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
        return all(i.get("checked") for i in self.checklist_status())

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

    def coc_summary(self):
        """Return key CoC fields from the logbook annotation, or empty dict."""
        ws = self._get_worksheet()
        if not ws:
            return {}
        try:
            raw = IAnnotations(ws).get(u"senaite.pfas.logbook.coc")
            if raw:
                data = json.loads(raw)
                return {
                    "client_name":            data.get("client_name") or u"",
                    "project_name":           data.get("project_name") or u"",
                    "sample_collection_date": data.get("sample_collection_date") or u"",
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
                }
        except Exception as exc:
            logger.error("coc_summary: %s", exc)
        return {}

    def holding_time_summary(self):
        """Computed holding time for this worksheet's batch.

        Two dates that were both already being recorded and never read
        together: `sample_collection_date` on the Chain of Custody, and
        `extraction_date` on FM-ENV-252. Read through `_logbook_json`, which
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
            coc = self._logbook_json(ws, u"senaite.pfas.logbook.coc") or {}
            ext = self._logbook_json(ws, u"senaite.pfas.logbook.252") or {}
            limit = holding_time.limit_for(self._method_profile() or {},
                                           self._batch_matrix())
            verdict = holding_time.evaluate(
                coc.get("sample_collection_date"),
                ext.get("extraction_date"),
                limit)
        except Exception as exc:                            # noqa: BLE001
            logger.error("holding_time_summary: %s", exc)
            return holding_time.evaluate(None, None, None)
        verdict["matrix"] = self._batch_matrix()
        verdict["blocking"] = verdict["status"] in holding_time.BLOCKING
        return verdict

    # ── Traceability ──────────────────────────────────────────────────────

    def _build_lot_indices(self, portal):
        """Build in-memory lot-number dicts (lot_number not a catalog index)."""
        reagent_by_lot = {}
        reagent_folder = portal.get("pfas_reagents")
        if reagent_folder is not None:
            for obj in reagent_folder.objectValues():
                if getattr(obj, "portal_type", "") == "Reagent":
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
        return {
            "title":      r.Title() if hasattr(r, "Title") else (r.title or u""),
            "cat_number": getattr(r, "cat_number", "") or u"",
            "supplier":   getattr(r, "supplier", "") or u"",
            "lot_number": getattr(r, "lot_number", "") or u"",
            "url":        r.absolute_url(),
        }

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
        """Logbook data with a DUAL-READ home (D44#6): the worksheet first
        (CLAUDE.md canonical), else the CoC-linked batch (where the logbook
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
        reagent_by_lot, ps_by_lot = self._build_lot_indices(portal)

        tree = {
            "direct_reagents":    [],
            "direct_standards":   [],
            "prepared_standards": [],
            "unresolved":         [],
        }

        # --- FM-ENV-252: reagents[] table ---
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
            elif lot:
                tree["unresolved"].append({
                    "source": "252.reagents", "lot": lot, "name": name,
                })
            tree["direct_reagents"].append(entry)

        # --- FM-ENV-252: standards[] table ---
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
                entry["resolved"] = {"title": ps.Title(), "url": ps.absolute_url(), "type": "PreparedStandard"}
            elif lot and lot in reagent_by_lot:
                entry["resolved"] = self._reagent_dict(reagent_by_lot[lot])
                entry["resolved"]["type"] = "Reagent"
            elif lot:
                tree["unresolved"].append({
                    "source": "252.standards", "lot": lot, "name": name,
                })
            tree["direct_standards"].append(entry)

        # --- FM-ENV-251: lot_ref fields ---
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

                try:
                    ps_ann  = IAnnotations(ps_obj)
                    raw_par = ps_ann.get(u"senaite.pfas.prepstd.parent_reagents")
                    parents = json.loads(raw_par) if raw_par else []
                except Exception:
                    parents = []

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
                    if p_lot and p_lot in reagent_by_lot:
                        p_entry["resolved"] = self._reagent_dict(reagent_by_lot[p_lot])
                    ps_node["parent_reagents"].append(p_entry)
            else:
                tree["unresolved"].append({
                    "source": field_name, "lot": lot_ref, "label": display_label,
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
            # The last four are the qc_types an UNEVALUATED gap row carries
            # (run_queue names the check, not a QC sample type). Omitting them
            # filtered out every gap row before the gate could see it.
            qc_results = list(store.get_qc_for_run(
                run_date,
                qc_types=["LCS", "LFSM", "LFB", "LFSMD", "Dup", "MB", "IS",
                          "MxB", "LRB", "CCV", "Calibration", "RT",
                          "IS Response"],
            ))
        except Exception as exc:
            logger.error("_get_qc_summary.get_qc_for_run: %s", exc)
            return {"error": "db_error", "rows": [], "qc_types": [], "overall_pass": False}

        # Load method profile acceptance limits
        qc_acceptance = {}
        method_id = self.batch_method()
        if method_id:
            try:
                from senaite.pfas.method_profile_store import get_profile
                profile = get_profile(self._portal(), method_id) or {}
                qc_acceptance = profile.get("qc_acceptance", {})
            except Exception as exc:
                logger.warning("_get_qc_summary.get_profile: %s", exc)

        return self._build_qc_matrix(qc_results, qc_acceptance, run_date)

    def _build_qc_matrix(self, qc_results, qc_acceptance, run_date=""):
        """Group QC results into analyte x qc_type matrix with pass/warn/fail."""
        by_analyte = {}
        qc_type_set = []

        for r in qc_results:
            if r.get("result_status") == "voided":
                continue
            analyte  = r.get("analyte", "") or ""
            qc_type  = r.get("qc_type", "") or ""
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
                            recovery = round(float(val) / float(exp) * 100.0, 1)
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
                    })

                cells[qc_type] = {
                    "status": cell_status,
                    "badge":  "PASS" if cell_status == "ok" else cell_status.upper(),
                    "n":      len(values),
                    "values": values,
                }

            rows.append({"analyte": analyte, "cells": cells})

        return {
            "qc_types":    qc_type_set,
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

    # ── Final Data Summary ────────────────────────────────────────────────

    def qualifier_legend(self):
        """The lab's qualifier vocabulary — read from the EGAD config store
        (single source, editable under Reporting → EGAD Config), NOT hardcoded
        here. Rendered as the legend under the Final Data table."""
        try:
            from senaite.pfas.egad_store import get_qualifier_map
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            return get_qualifier_map(portal) or []
        except Exception as exc:
            logger.warning("qualifier_legend: %s", exc)
            return []

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

                ar_map[ar_uid]["analyses"].append({
                    "analyte":      keyword,
                    "result":       result,
                    "unit":         unit,
                    "qualifier":    qualifier,
                    "review_state": state,
                })
            except Exception as exc:
                logger.error("get_final_data analysis loop: %s", exc)

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
                    "review_state":     a["review_state"],
                })
        return rows

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

                log = _load_extraction_log(wid) or {}
                analyst = (log.get("analyst") or u"").strip()
                started = self._parse_iso(log.get("started"))

                # Load the object only when we still need something off it:
                # a fallback analyst (no extraction log) or the submit time.
                obj = None
                if not analyst or under_review:
                    try:
                        obj = b.getObject()
                    except Exception:
                        obj = None
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
            ann = IAnnotations(self._portal())
            raw = ann.get(u"senaite.pfas.deviations.registry")
            if not raw:
                return []
            registry = json.loads(raw)
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
    CORRECTABLE_FIELDS = {
        "sample_collection_date": (u"Sample Collection Date", "sample_collection_date"),
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

    def reissue_ars(self):
        """ARs in this worksheet's batch that are already published — issuing a
        CoA for them is an AMENDED reissue (D65). We capture an amendment reason
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
        batch has samples — the assign-before-submit process point (D44#4)."""
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
        }
        handler = dispatch.get(action)
        if handler:
            return handler()
        self.request.response.redirect(self.request.URL)
        return u""

    def _handle_record_amendment_reason(self):
        """Stash an amendment reason on each already-published sample, then
        continue to the publisher. The publish (republish) transition's
        subscriber consumes it into the controlled register (D65)."""
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
        if item_key == "coc":
            coc = self.coc_summary()
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
        item["checked"]    = True
        item["checked_by"] = user.getId()
        item["initials"]   = initials
        item["checked_at"] = now
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
        batch = self._linked_batch(ws) if ws else None
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
        entry["spike_ppt"] = spike_ppt
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
                        lv["ppt"] = spike_ppt
                        break
                else:
                    levels.append({"label": label, "ppt": spike_ppt})
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
