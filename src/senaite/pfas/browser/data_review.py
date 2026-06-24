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
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

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
        cat = getToolByName(self.context, "portal_catalog")
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
        try:
            m = ws.getMethod()
            if m:
                return m.getId()
        except Exception:
            pass
        try:
            for analysis in (ws.getAnalyses() or []):
                m = analysis.getMethod()
                if m:
                    return m.getId()
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
            result.append(item)
        return result

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

    def _build_traceability_tree(self, ws):
        portal = self._portal()
        ann = IAnnotations(ws)

        def _load(key):
            try:
                raw = ann.get(key)
                return json.loads(raw) if raw else {}
            except Exception:
                return {}

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
        for row in (lb252.get("reagents") or []):
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
        for row in (lb252.get("standards") or []):
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
            qc_results = list(store.get_qc_for_run(
                run_date,
                qc_types=["LCS", "LFSM", "LFB", "LFSMD", "Dup", "MB", "IS"],
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

                    if not passed:
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

    # ── Final Data Summary (stub — columns TBD pending FDA Calculator PDF) ─

    def get_final_data(self):
        """Return basic per-sample per-analyte results from SENAITE."""
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
            return []

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

    def recent_worksheets(self):
        """Return recent Worksheets in open/to_be_verified state for batch selector."""
        cat = getToolByName(self.context, "portal_catalog")
        try:
            brains = cat(
                portal_type="Worksheet",
                review_state=["open", "to_be_verified"],
                sort_on="created",
                sort_order="descending",
                sort_limit=50,
            )
        except Exception as exc:
            logger.error("recent_worksheets: %s", exc)
            return []
        result = []
        for b in brains[:50]:
            result.append({
                "id":    b.getId,
                "title": b.Title or b.getId,
                "url":   b.getURL() + "/@@pfas-data-review",
                "state": b.review_state,
            })
        return result

    # ── POST dispatch ─────────────────────────────────────────────────────

    def _redirect_with_msg(self, msg, msg_type="ok", tab=None):
        ws = self._get_worksheet()
        if ws:
            base = ws.absolute_url() + "/@@pfas-data-review"
        else:
            base = self.context.absolute_url() + "/@@pfas-data-review"
        url = "{0}?msg={1}&msg_type={2}".format(base, msg, msg_type)
        if tab:
            url += "&tab={0}".format(tab)
        self.request.response.redirect(url)
        return u""

    def _handle_post(self):
        action = self.request.form.get("action", "")
        dispatch = {
            "check_item":               self._handle_check_item,
            "submit_for_review":        self._handle_submit_for_review,
            "approve_release":          self._handle_approve_release,
            "reject":                   self._handle_reject,
            "upload_instrument_report": self._handle_upload_instrument_report,
            "download_report":          self._handle_download_report,
        }
        handler = dispatch.get(action)
        if handler:
            return handler()
        self.request.response.redirect(self.request.URL)
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
        user = getSecurityManager().getUser()
        now  = datetime.datetime.utcnow().isoformat()
        cl   = self._get_checklist(ws)
        item = cl["items"].get(item_key, {})
        item["checked"]    = True
        item["checked_by"] = user.getId()
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
        try:
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
        try:
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
