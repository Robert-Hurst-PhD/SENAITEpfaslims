# -*- coding: utf-8 -*-
"""
@@pfas-system-map -- the lab's live model as a tree (system_map_data.py),
drawn with d3 (static/system_map.js): methods, their matrices, the recent
worksheets of each, their stages, samples and results, and the lots those
worksheets used, with the cross-links between them.

@@pfas-system-map-data?node=<id> answers one level (the node's children) as
JSON; nothing loads until a node is opened. Staff only: the map names
samples, worksheets and lots. Read-only.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import system_map_data as smd
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.system_map")

QC_DB = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
OPEN_STATES = ("open", "attachment_due", "to_be_verified")

# The worksheet index (method, matrix, samples per recent worksheet) is
# shared by every request for INDEX_SECONDS: opening one node after another
# must not walk every worksheet each time. A map a minute or two old is the
# price, as for the Bench queue's method cache.
_INDEX = {}
INDEX_SECONDS = 120


class _MapData(object):
    """Gathers what the nodes are made from, once per request."""

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.portal = getToolByName(context, "portal_url").getPortalObject()
        self.purl = self.portal.absolute_url()
        self._methods = None
        self._worksheets = None
        self._uses = None

    # ── methods ──────────────────────────────────────────────────────────
    def methods(self):
        if self._methods is None:
            from senaite.pfas.method_profile_store import get_profile, list_method_ids
            from senaite.pfas import method_revisions as mr
            out = []
            for mid in list_method_ids(self.portal):
                p = get_profile(self.portal, mid) or {}
                try:
                    recs = mr.records(self.portal, mid)
                    rev = (u"issued r%s" % max(r.get("rev", 0) for r in recs)) if recs else u"not issued"
                except Exception:                           # noqa: BLE001
                    rev = u""
                out.append({"id": mid, "label": p.get("display_name") or mid,
                            "matrices": list(p.get("supported_matrices") or []),
                            "url": u"%s/@@pfas-method-profile-edit?method_id=%s" % (self.purl, mid),
                            "revision": rev})
            self._methods = out
        return self._methods

    def method(self, mid):
        for m in self.methods():
            if m["id"] == mid:
                return m
        return None

    # ── worksheets: open, or closed within RECENT_DAYS ─────────────────────
    def _run_methods(self):
        try:
            conn = sqlite3.connect(QC_DB)
            try:
                return dict((r[0], r[1]) for r in conn.execute("SELECT batch_id, method FROM batches"))
            finally:
                conn.close()
        except Exception:                                   # noqa: BLE001
            return {}

    def worksheets(self):
        if self._worksheets is not None:
            return self._worksheets
        import time
        key = "/".join(self.portal.getPhysicalPath())
        hit = _INDEX.get(key)
        if hit is not None and time.time() - hit[1] < INDEX_SECONDS:
            self._worksheets = hit[0]
            return hit[0]
        self._worksheets = self._index()
        _INDEX[key] = (self._worksheets, time.time())
        return self._worksheets

    def _known_method(self, ws, session, run_methods):
        """The worksheet's method from what is already recorded: its
        extraction, its processed run, or the Bench queue's cache. Never the
        full resolver (it walks every analysis: tens of seconds for a lab's
        open worksheets); a worksheet with none of these shows under
        "Method not resolved"."""
        from bika.lims import api
        from senaite.pfas.browser import extraction_guide as eg
        mid = session.get("method_id") or run_methods.get(ws.getId())
        if not mid:
            hit = eg._METHOD_CACHE.get(api.get_uid(ws))
            mid = hit[0] if hit else u""
        return mid or u""

    def _sample_types(self):
        from bika.lims import api
        try:
            return dict((b.UID, b.Title) for b in api.search({"portal_type": "SampleType"}, "senaite_catalog_setup"))
        except Exception:                                   # noqa: BLE001
            return {}

    def _analyses(self, query):
        """Routine analyses as catalog brains: no sample or analysis is
        opened to draw the map."""
        from bika.lims import api
        q = dict(query, portal_type="Analysis")
        return api.search(q, "senaite_catalog_analysis")

    def _index(self):
        """One row per recent worksheet, from the worksheet and analysis
        catalogs; a worksheet object is opened only to read its extraction's
        method when no processed run names it."""
        from bika.lims import api
        from senaite.pfas.browser.extraction_guide import _load_session
        since = datetime.now() - timedelta(days=smd.RECENT_DAYS)
        run_methods = self._run_methods()
        types = self._sample_types()
        out = []
        for brain in api.search({"portal_type": "Worksheet"}, "senaite_catalog_worksheet"):
            # the catalog search is the person's own: a worksheet they
            # cannot see is not listed
            state = brain.review_state
            created = brain.created
            try:
                recent = created is not None and created.asdatetime().replace(tzinfo=None) >= since
            except Exception:                               # noqa: BLE001
                recent = False
            if state not in OPEN_STATES and not recent:
                continue
            try:
                ws_id = brain.getId
                mid = run_methods.get(ws_id) or u""
                analyst = u""
                if not mid:
                    ws = brain.getObject()
                    session = _load_session(ws)
                    mid = self._known_method(ws, session, run_methods)
                    analyst = session.get("analyst") or u""
                an = self._analyses({"getWorksheetUID": brain.UID})
                samples = set(x.getRequestID for x in an)
                m = self.method(mid)
                matrix = smd.matrix_of(m["matrices"] if m else [],
                                       [types.get(x.getSampleTypeUID, u"") for x in an])
                out.append({"id": ws_id, "uid": brain.UID, "state": state, "url": brain.getURL(),
                            "method": mid, "matrix": matrix, "analyst": analyst,
                            "samples": len(samples),
                            "created": created.strftime("%Y-%m-%d") if created else u""})
            except Exception as exc:                        # noqa: BLE001
                logger.warning("system map: worksheet %s: %s", brain.getId, exc)
        return out

    def uses(self):
        if self._uses is None:
            from senaite.pfas import inventory_ledger as led
            try:
                self._uses = led.uses_for_batches(None, [w["id"] for w in self.worksheets()])
            except Exception as exc:                        # noqa: BLE001
                logger.warning("system map: usage ledger: %s", exc)
                self._uses = []
        return self._uses

    # ── one level ────────────────────────────────────────────────────────
    def root(self):
        """The lab and its first level, from the catalog alone: no worksheet
        is opened until a method is."""
        from bika.lims import api
        try:
            n_open = len(api.search({"portal_type": "Worksheet", "review_state": list(OPEN_STATES)},
                                    "senaite_catalog_worksheet"))
        except Exception:                                   # noqa: BLE001
            n_open = u""
        lab = smd.node(u"lab", self._lab_name(), "lab", sub=u"Laboratory", has_children=True,
                       facts=[(u"Methods", len(self.methods())), (u"Open worksheets", n_open)])
        return {"node": lab, "children": smd.lab_children(self.methods(), None)}

    def _lab_name(self):
        try:
            ps = self.context.restrictedTraverse("@@pfas-macros").print_settings()
            return ps.get("lab_name") or u"Laboratory"
        except Exception:                                   # noqa: BLE001
            return u"Laboratory"

    def children(self, nid):
        nid = nid or u"lab"
        if nid == u"lab":
            return smd.lab_children(self.methods(), None)
        if nid == u"unresolved":
            links = smd.ws_lot_links(self.uses())
            rows = [dict(w, lots=links.get(w["id"], [])) for w in self.worksheets()
                    if not self.method(w["method"])]
            return smd.matrix_children(rows, nid)
        if nid.startswith(u"m:"):
            m = self.method(nid[2:])
            if m is None:
                return []
            counts = {}
            for w in self.worksheets():
                if w["method"] == m["id"]:
                    counts[w["matrix"]] = counts.get(w["matrix"], 0) + 1
            return smd.method_children(m, counts, m["url"])
        if nid.startswith(u"mx:"):
            mid, _sep, mx = nid[3:].partition(u"|")
            links = smd.ws_lot_links(self.uses())
            rows = [dict(w, lots=links.get(w["id"], [])) for w in self.worksheets()
                    if w["method"] == mid and w["matrix"] == mx]
            return smd.matrix_children(rows, nid)
        if nid.startswith(u"ws:"):
            return self._worksheet_children(nid[3:])
        if nid.startswith(u"s:"):
            return self._sample_children(nid[2:])
        if nid == u"lots":
            return [smd.lot_node(l, has_parents=l["kind"] == u"prepared_standard", url=self._lot_url(l))
                    for l in smd.lots_from_uses(self.uses())][:smd.MAX_CHILDREN]
        if nid.startswith(u"lot:prepared_standard:"):
            return self._parent_lots(nid.split(u":", 2)[2])
        return []

    def _lot_url(self, lot):
        return u"%s/@@pfas-lot-usage?kind=%s&uid=%s" % (self.purl, lot["kind"], lot["uid"])

    def _worksheet_children(self, ws_id):
        from bika.lims import api
        from senaite.pfas.browser.sample_status import _build_stage_steps, _compute_stage
        row = ([w for w in self.worksheets() if w["id"] == ws_id] or [None])[0]
        folder = self.portal.get("worksheets")
        ws = folder.get(ws_id) if folder is not None else None
        if ws is None:
            return []
        try:
            steps = _build_stage_steps(_compute_stage(ws)[0])
        except Exception:                                   # noqa: BLE001
            steps = []
        an = self._analyses({"getWorksheetUID": row["uid"] if row else api.get_uid(ws)})
        per = {}
        for x in an:
            rec = per.setdefault(x.getRequestID, {"id": x.getRequestID, "url": x.getRequestURL,
                                                  "results": 0, "csid": u"", "state": u""})
            if (x.getResult or u"") != u"":
                rec["results"] += 1
        if per:
            for sb in api.search({"portal_type": "AnalysisRequest", "getId": list(per)}, "senaite_catalog_sample"):
                if sb.getId in per:
                    per[sb.getId]["state"] = sb.review_state
                    per[sb.getId]["csid"] = getattr(sb, "getClientSampleID", u"") or u""
        review = u"%s/@@pfas-data-review?batch_id=%s" % (self.purl, ws_id)
        return smd.worksheet_children(ws_id, steps, [per[k] for k in sorted(per)], review)

    def _sample_children(self, sample_id):
        out = []
        for x in self._analyses({"getRequestID": sample_id}):
            if (x.getResult or u"") == u"":
                continue
            out.append({"keyword": x.getKeyword, "title": x.Title, "result": x.getResult,
                        "unit": x.getUnit or u"", "state": x.review_state, "url": x.getRequestURL})
        return smd.sample_children(sample_id, sorted(out, key=lambda r: r["title"] or u""))

    def _parent_lots(self, ps_uid):
        from senaite.pfas.browser import prepared_standards as ps
        rec = ps._get(self.portal, ps_uid) or {}
        out = []
        for parent in rec.get("parent_reagents") or []:
            try:
                obj, kind = ps._resolve_lot(self.portal, parent)
            except Exception:                               # noqa: BLE001
                obj, kind = None, None
            if obj is None:
                out.append(smd.node(u"lot:unresolved:%s" % (parent.get("lot") or parent.get("name") or u"?"),
                                    parent.get("lot") or parent.get("name") or u"?", "lot",
                                    sub=u"Parent lot not found", badge=u"unresolved", badge_kind=u"badge-expired"))
                continue
            k = u"prepared_standard" if kind == ps.KIND_PREPARED else u"reagent"
            lot = {"id": smd.lot_id(k, obj.getId()), "kind": k, "uid": obj.getId(),
                   "lot": getattr(obj, "lot_number", u"") or u"", "name": obj.Title(), "worksheets": []}
            out.append(smd.lot_node(lot, has_parents=k == u"prepared_standard", url=self._lot_url(lot)))
        return out


class PFASSystemMapView(BrowserView):

    template = ViewPageTemplateFile("templates/system_map.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def data_url(self):
        return self.portal_url() + u"/@@pfas-system-map-data"

    def root(self):
        if not hasattr(self, "_root"):
            try:
                self._root = _MapData(self.context, self.request).root()
            except Exception as exc:                        # noqa: BLE001
                logger.exception("system map root: %s", exc)
                self._root = {"node": smd.node(u"lab", u"Laboratory", "lab"), "children": []}
        return self._root

    def root_json(self):
        from senaite.pfas.document_templates import script_json
        return script_json(self.root())


class PFASSystemMapDataView(BrowserView):
    """@@pfas-system-map-data?node=<id> -> {"node", "children"} as JSON."""

    def __call__(self):
        flatten_form(self.request)
        from senaite.pfas.browser.perms import is_staff, refuse
        self.request.response.setHeader("Content-Type", "application/json")
        if not is_staff(self.context):
            return refuse(self.request, json.dumps({"error": "Staff only."}))
        nid = (self.request.form.get("node") or u"lab").strip()
        try:
            children = _MapData(self.context, self.request).children(nid)
        except Exception as exc:                            # noqa: BLE001
            logger.exception("system map node %s", nid)
            self.request.response.setStatus(500)
            return json.dumps({"error": "The map could not be read: %s" % exc})
        return json.dumps({"node": nid, "children": children})
