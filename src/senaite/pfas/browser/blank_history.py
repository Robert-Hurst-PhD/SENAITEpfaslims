# -*- coding: utf-8 -*-
"""Blank history and the lots behind a change in background
(@@pfas-blank-history;
Part 2). Python 2.7.

    ?method=&matrix=&qc_type=&analyte=   the series charted
    ?a=<worksheet>&b=<worksheet>         compare two blanks' lots

The blank results come from the QC database (qc_results, joined to the run's
method and matrix); each run's lots from the extraction's usage ledger and
FM-ENV-002 (blank_history.lots_of). The comparison folds away the lots both
runs used. `blank_data`, `run_lots` and `compare` are shared with Data
Review's QC Summary (this run's blank against the previous one).
"""
from __future__ import absolute_import, unicode_literals

import logging
import sqlite3

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.memoize.instance import memoize
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.blank_history")


def blank_data(method=None):
    """blank_history.runs over the QC database: every blank run, newest first."""
    from senaite.pfas import blank_history as bh
    from senaite.pfas.qc.store import DEFAULT_DB_PATH
    try:
        con = sqlite3.connect(DEFAULT_DB_PATH)
        con.row_factory = sqlite3.Row
        cols = [r[1] for r in con.execute("PRAGMA table_info(batches)")]
        matrix = "b.matrix" if "matrix" in cols else "''"
        sql = ("SELECT q.batch_id, q.run_date, q.method, %s AS matrix, q.qc_type, q.analyte, "
               "q.value, q.passed, q.qc_level, q.units FROM qc_results q LEFT JOIN batches b ON b.batch_id = q.batch_id "
               "WHERE q.result_status='active' AND q.qc_type IN (%s)" % (
                   matrix, ",".join("?" * len(bh.BLANK_TYPES))))
        args = list(bh.BLANK_TYPES)
        if method:
            sql += " AND q.method=?"
            args.append(method)
        rows = [dict(r) for r in con.execute(sql, args)]
        con.close()
    except Exception as exc:                                # noqa: BLE001
        logger.warning("blank_data: %s", exc)
        rows = []
    return bh.runs(rows)


def run_lots(portal, ws_id):
    """Every lot one run used: its extraction's ledger and FM-ENV-002."""
    from bika.lims import api
    from senaite.pfas import blank_history as bh
    from senaite.pfas import inventory_ledger
    try:
        ledger = inventory_ledger.uses_for_batch(inventory_ledger.DB_PATH, ws_id)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("run_lots ledger %s: %s", ws_id, exc)
        ledger = []
    fm251 = {}
    try:
        found = api.search({"portal_type": "Worksheet", "id": ws_id}, "senaite_catalog_worksheet")
        if found:
            from senaite.pfas.browser.logbooks import _get_logbook
            fm251 = _get_logbook(found[0].getObject(), "251") or {}
    except Exception as exc:                                # noqa: BLE001
        logger.warning("run_lots fm251 %s: %s", ws_id, exc)
    return bh.lots_of(ledger, fm251)


def mxb_members(ws_id):
    """The run's matrix-blank members ([member]), read from its worksheet
    (callers cache them per page through `cache`)."""
    from bika.lims import api
    from senaite.pfas import extraction_batch as eb
    try:
        found = api.search({"portal_type": "Worksheet", "id": ws_id}, "senaite_catalog_worksheet")
        return [m for m in eb.load(found[0].getObject()) if m.get("role") == u"MxB"] if found else []
    except Exception as exc:                                # noqa: BLE001
        logger.warning("mxb_members %s: %s", ws_id, exc)
        return []


def mxb_member(run, cache=None):
    """The member a matrix-blank run entry is (by injection; a run whose
    results carry no injection name and has one matrix blank: that one)."""
    cache = {} if cache is None else cache
    if run.get("batch_id") not in cache:
        cache[run.get("batch_id")] = mxb_members(run.get("batch_id"))
    members = cache[run.get("batch_id")]
    member = [m for m in members if m.get("injection") == run.get("injection")]
    return member[0] if member else (members[0] if len(members) == 1 else None)


def previous_blank(all_runs, current, cache=None):
    """blank_history.previous; for a matrix blank, the previous one made from
    the same lot when there is one (another material is no baseline)."""
    from senaite.pfas import blank_history as bh
    if current.get("qc_type") != "MxB":
        return bh.previous(all_runs, current)
    me = mxb_member(current, cache) or {}
    if me.get("lot"):
        same = [r for r in all_runs if r.get("qc_type") != "MxB"
                or (mxb_member(r, cache) or {}).get("lot") == me["lot"]]
        found = bh.previous(same, current)
        if found is not None:
            return found
    return bh.previous(all_runs, current)


def mxb_assigned(portal, run, cache=None):
    """A matrix blank against its lot's assigned levels: {uid, label,
    record, rows} (matrix_blank.compare), or None when the run's members
    name no matrix blank. Shown, never judged."""
    from senaite.pfas import matrix_blank as mxb
    from senaite.pfas.browser.assigned_levels import history, lot_label, lot_object
    member = mxb_member(run, cache)
    if member is None:
        return None
    obj = lot_object(portal, member.get("lot"))
    rec = mxb.current(history(obj))
    return {"uid": member.get("lot") or u"", "label": lot_label(obj),
            "injection": member.get("injection"), "record": rec,
            "unit": run.get("units") or u"",
            "rows": mxb.compare(run.get("values"), run.get("units"), rec)}


def _with_blank_matrix(portal, lots, run, cache):
    """A matrix blank's own material joins its run's lots: the likeliest
    cause of a change in a matrix blank."""
    from senaite.pfas.browser.assigned_levels import lot_object
    if run.get("qc_type") != "MxB":
        return lots
    member = mxb_member(run, cache) or {}
    obj = lot_object(portal, member.get("lot"))
    if obj is None:
        return lots
    return lots + [{"kind": u"reagent", "lot": getattr(obj, "lot_number", u"") or obj.getId(),
                    "name": obj.Title(), "role": u"Blank matrix", "stage": u"Matrix blank"}]


def compare(portal, current, prev, cache=None):
    """{current, previous, rise, lots, assigned} for two blank runs."""
    from senaite.pfas import blank_history as bh
    cache = {} if cache is None else cache
    out = {"current": current, "previous": prev, "rise": [], "lots": None, "assigned": None}
    if current is None:
        return out
    if current.get("qc_type") == "MxB":
        out["assigned"] = mxb_assigned(portal, current, cache)
    out["rise"] = bh.rise(current, prev)
    if prev is not None:
        out["lots"] = bh.lot_diff(
            _with_blank_matrix(portal, run_lots(portal, current["batch_id"]), current, cache),
            _with_blank_matrix(portal, run_lots(portal, prev["batch_id"]), prev, cache))
    return out


class PFASBlankHistoryView(BrowserView):

    template = ViewPageTemplateFile("templates/blank_history.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return self.portal().absolute_url()

    def _f(self, key, default=u""):
        return (self.request.form.get(key) or default).strip()

    def all_runs(self):
        if not hasattr(self, "_runs"):
            from bika.lims import api
            from senaite.pfas import study_records
            try:
                hidden = study_records.chart_hidden(study_records.load(api.get_portal()))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("study runs not hidden: %s", exc)
                hidden = set()
            # study runs stay out unless their study opted in
            self._runs = [r for r in blank_data() if r.get("batch_id") not in hidden]
        return self._runs

    # each choice is derived from the others; unmemoised, one page computed
    # method() 2.2 million times
    @memoize
    def methods(self):
        return sorted(set(r["method"] for r in self.all_runs() if r["method"]))

    @memoize
    def method(self):
        # the method of the newest blank run, else the first
        rs = self.all_runs()
        return self._f("method") or (rs[0]["method"] if rs else (self.methods() or [u""])[0])

    @memoize
    def matrices(self):
        return sorted(set(r["matrix"] for r in self.all_runs()
                          if r["matrix"] and r["method"] == self.method()))

    @memoize
    def matrix(self):
        return self._f("matrix")

    def qc_types(self):
        from senaite.pfas import blank_history as bh
        return list(bh.BLANK_TYPES)

    @memoize
    def qc_type(self):
        have = [r["qc_type"] for r in self.runs_unfiltered_type()]
        return self._f("qc_type") or (u"LRB" if u"LRB" in have else (have or [u"MB"])[0])

    @memoize
    def runs_unfiltered_type(self):
        return [r for r in self.all_runs() if r["method"] == self.method()
                and (not self.matrix() or not r["matrix"] or r["matrix"] == self.matrix())]

    @memoize
    def runs_any_unit(self):
        return [r for r in self.runs_unfiltered_type() if r["qc_type"] == self.qc_type()]

    @memoize
    def units(self):
        """The units this blank kind was reported in (newest first)."""
        out = []
        for r in self.runs_any_unit():
            u = r.get("units") or u""
            if u not in out:
                out.append(u)
        return out

    @memoize
    def unit(self):
        """One unit on the chart at a time: the one asked for, else the
        newest run's (values in different units are never plotted together)."""
        asked = self.request.form.get("unit")
        units = self.units()
        if asked is not None and asked in units:
            return asked
        return units[0] if units else u""

    @memoize
    def runs(self):
        u = self.unit()
        return [r for r in self.runs_any_unit() if (r.get("units") or u"") == u]

    @memoize
    def analytes(self):
        names = set()
        for r in self.runs():
            names.update(a for a in r["values"] if a)
        return sorted(names)

    @memoize
    def analyte(self):
        a = self._f("analyte")
        if a:
            return a
        # the analyte that rose most recently, else the first
        rs = self.runs()
        if len(rs) >= 2:
            from senaite.pfas import blank_history as bh
            up = bh.rise(rs[0], bh.previous(rs, rs[0]))
            if up:
                return up[0][0]
        return (self.analytes() or [u""])[0]

    @memoize
    def selected_analytes(self):
        """The analytes stacked on the chart (one checkbox field each,
        `an.<analyte>`: flatten_form keeps one value per field), else the
        default one. A blank's analytes share its run's unit, so they stack."""
        f = self.request.form
        have = set(self.analytes())
        picked = sorted(k[3:] for k in f if k.startswith(u"an.") and f.get(k) and k[3:] in have)
        return picked or ([self.analyte()] if self.analyte() else [])

    def series_json(self):
        """Oldest first: {labels: [run], units, series: [{analyte, values,
        failed, assigned}], rl}. The RL line (and a matrix blank's assigned
        level) only when one analyte is shown: each belongs to its own."""
        runs = list(reversed(self.runs()))
        names = self.selected_analytes()
        one = len(names) == 1
        # a non-detect (stored with no value) is charted at 0, hollow; an
        # analyte the run did not measure is a gap
        series = [{"analyte": a,
                   "values": [(r["values"].get(a) or 0.0) if a in r["values"] else None for r in runs],
                   "nd": [a in r["values"] and r["values"].get(a) is None for r in runs],
                   "failed": [a in r["failed"] for r in runs],
                   "assigned": [self._assigned(r, a) for r in runs] if one else []}
                  for a in names]
        units = sorted(set(r.get("units") or u"" for r in runs) - set([u""]))
        from senaite.pfas.document_templates import script_json
        return script_json({"labels": [u"%s %s" % (r["run_date"], r["key"]) for r in runs],
                           "series": series, "units": u", ".join(units),
                           "rl": self.rl() if one else None})

    def _assigned(self, run, analyte):
        """A matrix blank's assigned level for `analyte`, in the run's unit
        (None when the lot has none, or holds it in another unit)."""
        if run.get("qc_type") != "MxB":
            return None
        from senaite.pfas.matrix_blank import same_unit
        got = mxb_assigned(self.portal(), run, self._cache()) or {}
        rec = got.get("record") or {}
        if not same_unit(run.get("units"), rec.get("unit")):
            return None
        return (rec.get("levels") or {}).get(analyte)

    def rl(self):
        try:
            from senaite.pfas.method_profile_store import get_profile
            from senaite.pfas.report_limits import limits_for
            from senaite.pfas.analyte_reference import COMPOUND_NAME_TO_KEYWORD as kw
            a = self.analyte()
            key = kw.get(a.replace(u"lr-", u"").replace(u"br-", u""), a)
            mtx = self.matrix() or (self.matrices() or [u""])[0]
            return limits_for(get_profile(self.portal(), self.method()) or {}, mtx, key).get("rl")
        except Exception:                                   # noqa: BLE001
            return None

    def pair(self):
        """The two runs compared: ?a=&b=, else the newest and its previous."""
        from senaite.pfas import blank_history as bh
        rs = self.runs()
        by = dict((r["key"], r) for r in rs)
        a = by.get(self._f("a")) or (rs[0] if rs else None)
        b = by.get(self._f("b")) if self._f("b") else (
            previous_blank(rs, a, self._cache()) if a else None)
        return a, b

    def _cache(self):
        if not hasattr(self, "_mxb_cache"):
            self._mxb_cache = {}
        return self._mxb_cache

    def comparison(self):
        a, b = self.pair()
        return compare(self.portal(), a, b, self._cache())


class PFASBlankHistoryMacrosView(BrowserView):
    """The blank comparison macro, shared with Data Review."""

    _template = ViewPageTemplateFile("templates/blank_history_macros.pt")

    @property
    def macros(self):
        return self._template.macros
