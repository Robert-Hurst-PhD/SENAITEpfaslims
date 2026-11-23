# -*- coding: utf-8 -*-
"""
@@pfas-system-map -- the lab's live model as a tree (system_map_data.py),
drawn with d3 (static/system_map.js): methods, their matrices, the
worksheets of each (of the chosen period, grouped by month or status), their
stages, samples and results, the lots those worksheets used and the lab's
equipment, with the cross-links between them.

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
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import print_doc
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
        self._units = None
        form = getattr(request, "form", {}) or {}
        # a display filter: only the periods offered are taken
        raw = u"%s" % form.get("days", u"30")
        self.days = int(raw) if raw.isdigit() and int(raw) in dict(smd.PERIODS) else 30
        group = form.get("group") or "month"
        self.group = group if group in dict(smd.GROUPINGS) else "month"

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
                name = p.get("display_name") or mid
                out.append({"id": mid, "label": name,
                            "matrices": list(p.get("supported_matrices") or []),
                            "url": u"%s/@@pfas-method-profile-edit?method_id=%s" % (self.purl, mid),
                            "revision": rev,
                            "panel": smd.method_panel(mid, self.purl, self._method_why(mid, name, rev))})
            self._methods = out
        return self._methods

    def _method_why(self, mid, name, rev):
        """Why a method is highlighted: no revision issued, or its judging
        settings with no value (they refuse its runs)."""
        out = [u"No revision issued yet"] if rev == u"not issued" else []
        if getattr(self, "_unset", None) is None:
            try:
                from senaite.pfas import settings_adapters
                from senaite.pfas import settings_registry as reg
                settings_adapters.declare_all(self.portal)
                self._unset = reg.unconfigured(self.portal)
            except Exception:                               # noqa: BLE001
                self._unset = []
        for r in self._unset:
            label = r.get("label") or r.get("key") or u""
            if name in label or mid in (r.get("key") or u""):
                out.append(u"%s not set: runs it judges are refused" % label)
        return out

    def method(self, mid):
        for m in self.methods():
            if m["id"] == mid:
                return m
        return None

    # ── worksheets: open, or created within the chosen period ─────────────
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
        key = "%s|%d" % ("/".join(self.portal.getPhysicalPath()), self.days)
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
        # "Worksheets from": open ones always, others created within the period
        since = datetime.now() - timedelta(days=self.days) if self.days else None
        run_methods = self._run_methods()
        types = self._sample_types()
        out = []
        for brain in api.search({"portal_type": "Worksheet"}, "senaite_catalog_worksheet"):
            # the catalog search is the person's own: a worksheet they
            # cannot see is not listed
            state = brain.review_state
            created = brain.created
            try:
                recent = since is None or (created is not None and created.asdatetime().replace(tzinfo=None) >= since)
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
                            "created": print_doc.lab_or(created, created.strftime("%Y-%m-%d"), u"%Y-%m-%d")
                            if created else u""})
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
                       facts=[(u"Methods", len(self.methods())), (u"Open worksheets", n_open),
                              (u"Equipment", len(self.units()))])
        return {"node": lab, "children": smd.lab_children(self.methods(), None, len(self.units()))}

    # ── equipment: core Instruments, by Instrument Type ──────────────────
    def units(self):
        if self._units is None:
            try:
                from senaite.pfas.browser import equipment as eq
                self._units = eq.list_units(True)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("system map: equipment: %s", exc)
                self._units = []
        return self._units

    def _ws_equipment(self, ws_id):
        """The registered units a worksheet's extraction used: each stage's
        equipment serials and the processing log's balance, by serial."""
        from senaite.pfas.browser.extraction_guide import _load_session
        folder = self.portal.get("worksheets")
        ws = folder.get(ws_id) if folder is not None else None
        if ws is None:
            return []
        serials = []
        try:
            for _o, stage in sorted((_load_session(ws).get("stages") or {}).items()):
                serials += [v for v in (stage.get("equipment_sns") or {}).values() if v]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("system map: %s equipment: %s", ws_id, exc)
        try:
            # the balance on a sample processing record made before the
            # guided extraction took that stage over
            from zope.annotation.interfaces import IAnnotations
            old = json.loads(IAnnotations(ws).get(u"senaite.pfas.logbook.253") or u"{}")
            serials.append((old.get("balance_sn") if isinstance(old, dict) else u"") or u"")
        except Exception:                                   # noqa: BLE001
            pass
        by_serial = dict(((u.get("serial_number") or u"").strip(), u["id"]) for u in self.units()
                         if (u.get("serial_number") or u"").strip())
        out = []
        for sn in serials:
            uid = by_serial.get((sn or u"").strip())
            if uid and uid not in out:
                out.append(uid)
        return out

    def _ws_rows(self, rows):
        """Worksheet rows with their cross-links: the lots and the equipment used."""
        links = smd.ws_lot_links(self.uses())
        return [dict(w, lots=links.get(w["id"], []) + [smd.eq_id(u) for u in self._ws_equipment(w["id"])])
                for w in rows]

    def _matrix_rows(self, nid):
        """The worksheets under a matrix node (or "Method not resolved")."""
        if nid == u"unresolved":
            return [w for w in self.worksheets() if not self.method(w["method"])]
        mid, _sep, mx = nid[3:].partition(u"|")
        return [w for w in self.worksheets() if w["method"] == mid and w["matrix"] == mx]

    def _worksheets_under(self, nid):
        rows = self._matrix_rows(nid)
        if self.group != "none" and rows:
            return smd.worksheet_groups(rows, self.group, nid)
        return smd.matrix_children(self._ws_rows(rows), nid)

    def _lab_name(self):
        from senaite.pfas import lab_identity
        return lab_identity.lab_name() or u"Laboratory"

    def children(self, nid):
        nid = nid or u"lab"
        if nid == u"lab":
            return smd.lab_children(self.methods(), None)
        if nid == u"unresolved" or nid.startswith(u"mx:"):
            return self._worksheets_under(nid)
        group = smd.parse_group(nid)
        if group is not None:
            mode, key, parent = group
            rows = [w for w in self._matrix_rows(parent) if smd.group_key(w, mode) == key]
            return smd.matrix_children(self._ws_rows(rows), nid)
        if nid == u"equipment":
            return smd.equipment_types(self.units())
        if nid.startswith(u"eqt:"):
            from senaite.pfas import equipment_types as et
            return smd.equipment_items(self.units(), nid[4:], dict(et.KINDS), purl=self.purl)
        if nid.startswith(u"m:"):
            m = self.method(nid[2:])
            if m is None:
                return []
            counts = {}
            for w in self.worksheets():
                if w["method"] == m["id"]:
                    counts[w["matrix"]] = counts.get(w["matrix"], 0) + 1
            return smd.method_children(m, counts, m["url"])
        if nid.startswith(u"ws:"):
            return self._worksheet_children(nid[3:])
        if nid.startswith(u"s:"):
            return self._sample_children(nid[2:])
        if nid == u"lots":
            return [smd.lot_node(l, has_parents=l["kind"] == u"prepared_standard", url=self._lot_url(l), purl=self.purl,
                                 equipment=self._standard_equipment(l))
                    for l in smd.lots_from_uses(self.uses())][:smd.MAX_CHILDREN]
        if nid.startswith(u"lot:prepared_standard:"):
            return self._parent_lots(nid.split(u":", 2)[2])
        return []

    def _standard_equipment(self, lot):
        """The units a prepared standard records it was made with."""
        if lot.get("kind") != u"prepared_standard":
            return []
        try:
            from senaite.pfas.browser import prepared_standards as ps
            rec = ps._get(self.portal, lot["uid"]) or {}
        except Exception:                                   # noqa: BLE001
            return []
        return [e["unit_id"] for e in rec.get("equipment") or [] if e.get("unit_id")]

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
            out.append(smd.lot_node(lot, has_parents=k == u"prepared_standard", url=self._lot_url(lot), purl=self.purl,
                                    equipment=self._standard_equipment(lot)))
        return out


class PFASSystemMapView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/system_map.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def _data(self):
        if not hasattr(self, "_md"):
            self._md = _MapData(self.context, self.request)
        return self._md

    def data_url(self):
        """The level endpoint, with the page's period and grouping."""
        return self.portal_url() + u"/@@pfas-system-map-data?days=%d&group=%s" % (self._data().days, self._data().group)

    def period_links(self):
        base = self.portal_url() + u"/@@pfas-system-map?group=%s&days=" % self._data().group
        return [{"label": l, "url": base + str(d), "on": d == self._data().days} for d, l in smd.PERIODS]

    def group_links(self):
        base = self.portal_url() + u"/@@pfas-system-map?days=%d&group=" % self._data().days
        return [{"label": l, "url": base + k, "on": k == self._data().group} for k, l in smd.GROUPINGS]

    def root(self):
        if not hasattr(self, "_root"):
            try:
                self._root = self._data().root()
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
