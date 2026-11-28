# -*- coding: utf-8 -*-
"""
PFAS Control Chart browser view.

Registered at @@pfas-control-chart on the SENAITE portal.
Serves both the HTML chart page and a JSON data endpoint.

Python 2.7-compatible (runs inside Zope/Plone).
Reads QC results from the SQLite store written by the Python 3 pipeline.

Query parameters
----------------
qc_type       : CCV | LCS | MB | LFSM | LFSMD | IS
analyte       : analyte name (e.g. PFOA)
qc_level      : calibration level or spike (optional; omit = all levels)
analyst       : filter by analyst name (optional)
instrument_id : filter by instrument ID (optional)
limit         : number of data points; default 20, max 300
format        : json = return raw JSON instead of HTML
export        : points = the plotted points as CSV, with the page's filters
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
import re

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.qc_lists import StoreListsMixin
from senaite.pfas.browser.perms import refuse
from senaite.pfas.browser.view_helpers import LabTime, MethodNames
from senaite.pfas import sample_type_icons as sti
from senaite.pfas.document_templates import script_json
from plone.memoize.instance import memoize

logger = logging.getLogger("senaite.pfas.browser.controlchart")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
DEFAULT_LIMIT = 20
MAX_LIMIT = 300
# the whole series is read for its limits: no run count reaches this
SERIES_MAX = 1000000
# the rule names the Levey-Jennings view recorded dismissals under
LEGACY_RULES = {"3SD": "1-3s", "2SD": "1-2s"}

QC_TYPE_TARGETS = {
    # a check standard is charted as its recovery (calculated / expected):
    # the value stored is a concentration
    "CCV":   100.0,
    "ICV":   100.0,
    # LFB (lab fortified blank) is the canonical name; LCS folds into it.
    "LFB":   100.0,
    "MB":    0.0,
    "MxB":   0.0,
    "LRB":   0.0,
    "LFSM":  100.0,
    "LFSMD": 100.0,
    # Surrogate (labeled-analog / extracted-IS) recovery measured in each
    # field sample — an ongoing per-sample QC metric, target 100 % recovery.
    "SUR":   100.0,
}

# the quantity, then its unit in brackets (an axis title, and "Mean recovery (%)")
QC_TYPE_UNITS = {
    "CCV":   "Recovery (%)",
    "ICV":   "Recovery (%)",
    "LFB":   "Recovery (%)",
    "MB":    "Concentration (ng/mL)",
    "MxB":   "Concentration (ng/mL)",
    "LRB":   "Concentration (ng/mL)",
    "LFSM":  "Recovery (%)",
    "LFSMD": "Recovery (%)",
    "SUR":   "Recovery (%)",
}


# a blank's non-detect is stored with no value; it is charted at 0, hollow,
# as "not detected" -- skipping it left most blank runs off the chart. The
# list is the one Blank History's rules keep (blanks mode, 2026-10-11).
from senaite.pfas.blank_history import BLANK_TYPES   # noqa: E402
RECOVERY_TYPES = ("CCV", "ICV")
# the QC type list's entry for peak asymmetry: every analyte's factor at
# each raw run's mid-level calibrator (asymmetry_track), with the control
# limits every chart draws from its plotted points; tracked, never held
ASYMMETRY = "ASYM"
ASYMMETRY_LABEL = u"Peak asymmetry"
QC_TYPE_UNITS[ASYMMETRY] = "Asymmetry factor"
# the Removed panel lists this many, then counts the rest
REMOVED_SHOWN = 50


def chart_unit(qc_type):
    """The charted value's unit: "%" for a recovery, "ng/mL" for a blank."""
    m = re.search(r"\(([^)]*)\)\s*$", QC_TYPE_UNITS.get(qc_type, ""))
    return m.group(1) if m else ""


def drawn_kind(qc_type):
    """What a row needs to be drawn (chart_value), as the store counts it:
    a blank's non-detect is drawn with no value, a recovery needs its
    expected value, any other a value."""
    if qc_type in BLANK_TYPES:
        return None
    return "recovery" if qc_type in RECOVERY_TYPES else "value"


def injection_of(qc_level):
    """A check standard's qc_level is its injection's key ("<injection>|<acquired>"):
    the injection's name; another type's level as stored."""
    return (qc_level or "").split("|")[0]


def chart_value(qc_type, row):
    """(value, not_detected) as charted, or (None, False) to leave it off."""
    v = row.get("value")
    if v is None:
        return (0.0, True) if qc_type in BLANK_TYPES else (None, False)
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None, False
    if qc_type in RECOVERY_TYPES:
        try:
            exp = float(row.get("expected_value"))
        except (TypeError, ValueError):
            return None, False
        return (fv / exp * 100.0, False) if exp else (None, False)
    return fv, False


class PFASControlChartView(StoreListsMixin, BrowserView, LabTime, MethodNames):
    """
    Browser view serving the PFAS QC control chart.

    Supports two modes:
      html (default) — renders the Chart.js template
      json            — returns chart data as JSON for XHR/AJAX requests
    """

    template = ViewPageTemplateFile("templates/controlchart.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.get("REQUEST_METHOD", "GET") != "POST":
            # the blank history helpers read a single ?qc_type=
            req.form["qc_type"] = self.selected_qc_type()
        if req.get("REQUEST_METHOD", "GET") == "POST":
            return self._handle_post()
        if req.form.get("export") == "points":
            return self.export_points()
        fmt = req.get("format", "").lower()
        accept = req.getHeader("Accept", "")
        if fmt == "json" or "application/json" in accept:
            return self._json_response()
        return self.template()

    # ── Request parameter accessors ──────────────────────────────────────

    def selected_method(self):
        # request.get("method") returns the HTTP method (GET/POST) in Zope 2;
        # request.form is the correct place to read query-string parameters.
        return self.request.form.get("method", "")

    def selected_qc_types(self):
        """The QC kinds ticked: one checkbox field each (`qt.<kind>`); an old
        link's single `qc_type` is one tick; Clear (`qt_none`) is none; with
        no choice at all, CCV when the store holds it, else the first kind:
        the page opens on a chart, not an empty pane."""
        if not hasattr(self, "_sel_kinds"):
            f = self.request.form
            have = self.qc_types() if self.db_available else []
            have = list(have) + ([ASYMMETRY] if self.db_available and ASYMMETRY not in have else [])
            picked = [k for k in have if f.get(u"qt.%s" % k)]
            if not picked and f.get("qc_type"):
                picked = [f.get("qc_type")]
            elif not picked and ("qt_none" in f or "qc_type" in f):
                picked = []
            elif not picked:
                picked = ["CCV"] if "CCV" in have else (have[:1] if have else [])
            # peak asymmetry is its own chart: alone, or not at all
            if ASYMMETRY in picked and len(picked) > 1:
                picked = [ASYMMETRY]
            self._sel_kinds = picked
        return self._sel_kinds

    def selected_qc_type(self):
        """The first kind ticked (what the single-kind helpers read)."""
        kinds = self.selected_qc_types()
        return kinds[0] if kinds else ""

    def qc_kinds_available(self):
        """Every kind that can be ticked: the method's results carry them."""
        return list(self.qc_types()) + ([ASYMMETRY] if self.db_available else [])

    def _selection_groups(self):
        """{analyte: [stored names]} over every kind ticked."""
        merged = {}
        for k in self.selected_qc_types():
            for a, names in self._analyte_groups(k).items():
                merged[a] = sorted(set(merged.get(a, [])) | set(names))
        return merged

    def selection_analytes(self):
        return sorted(self._selection_groups())

    def selected_analytes(self):
        """The analytes on the chart: one checkbox field each (`an.<name>`;
        flatten_form keeps one value per field), else `analyte`, else the
        first with results. Several are stacked; the control limits and
        Westgard rules belong to one analyte, so only one gets them."""
        if not hasattr(self, "_sel_analytes"):
            f = self.request.form
            have = self.selection_analytes() if self.db_available else []
            picked = [a for a in have if f.get(u"an.%s" % a)]
            # Clear, then apply: nothing is picked, and the page says so
            if not picked and f.get("an_none"):
                self._sel_analytes = []
                return self._sel_analytes
            if not picked and self.request.get("analyte", ""):
                picked = [self._chart_name(self.request.get("analyte", ""))]
            if not picked and have:
                picked = [have[0]]
            self._sel_analytes = picked
        return self._sel_analytes

    def analyte_button_label(self, picked, available, all_word=u"All analytes"):
        """What a pick-list button shows: the picked names ("10:2FTS, PFOS
        +2"), "All analytes" or "None picked"."""
        if not picked:
            return u"None picked"
        if available and len(picked) == len(available) and len(picked) > 2:
            return all_word
        if len(picked) <= 2:
            return u", ".join(picked)
        return u"%s +%d" % (u", ".join(picked[:2]), len(picked) - 2)

    def selected_analyte(self):
        sel = self.selected_analytes()
        return sel[0] if sel else ""

    def is_stacked(self):
        return len(self.selected_analytes()) > 1

    # ── Peak asymmetry: each raw run's mid-level calibrator ──
    def asymmetry_mode(self):
        return self.selected_qc_types() == [ASYMMETRY]

    def asymmetry_label(self):
        return ASYMMETRY_LABEL

    def _asymmetry_points(self):
        """Every measured factor under the page's filters, oldest run first
        (asymmetry_track.trend); the worksheets of studies not opted into
        the charts left out."""
        if not hasattr(self, "_asym_points"):
            import sqlite3
            from senaite.pfas import asymmetry_track as at
            self._asym_points = []
            if self.db_available:
                try:
                    conn = sqlite3.connect(self.db_path)          # read only
                    try:
                        rows = at.load_rows(conn, method=self.selected_method() or None,
                                            instrument=self.selected_instrument(),
                                            analyst=None,
                                            date_from=self.selected_date_from() or None,
                                            date_to=self.selected_date_to() or None)
                    finally:
                        conn.close()
                    hidden = self._study_hidden()
                    pts = at.trend([r for r in rows if r["batch_id"] not in hidden])
                    who = self.selected_analyst()
                    self._asym_points = [p for p in pts if p["analyst"] in who] if who else pts
                except Exception as e:                          # noqa: BLE001
                    logger.error("peak asymmetry: %s", e)
        return self._asym_points

    def _asymmetry_series(self, analyte, whole=False):
        """One analyte's factors, oldest first: the newest `limit` of them, or
        the whole series (what its limits stand on)."""
        names = set(self._analyte_groups(ASYMMETRY).get(analyte) or [analyte])
        pts = [p for p in self._asymmetry_points() if p["analyte"] in names]
        return pts if whole else pts[-self.selected_limit():]

    def _asymmetry_chart_dict(self):
        """One analyte's factors as a control chart: the mean and the +/- 2 SD
        warning and +/- 3 SD control limits from the plotted runs, standing
        on BASELINE_N in-control results as on every chart (control_chart).
        A point beyond a limit is marked; nothing is reviewed or held."""
        from senaite.pfas import control_chart as cc, idc
        analyte, limit = self.selected_analyte(), self.selected_limit()
        units = QC_TYPE_UNITS[ASYMMETRY]
        whole = self._asymmetry_series(analyte, whole=True) if analyte else []
        if not whole:
            return self._empty_chart(analyte, ASYMMETRY, u"", units, limit)
        # judged to the places the card and the IDC show; the limits stand on
        # the whole series (the first BASELINE_N in-control results), Runs
        # shown only trims what is drawn
        every = [{"id": u"%s/%s" % (p["batch_id"], p["injection"]), "value": round(p["factor"], idc.SHOWN_PLACES),
                  "date": p["run_date"][:10]} for p in whole]
        offset = max(0, len(whole) - limit)
        pts, points = whole[offset:], every[offset:]
        drawn = cc.drawn_limits([p["value"] for p in every])
        lim = drawn if cc.ready(drawn) else None
        flags = []
        for w in cc.lj_warnings(every, lim):
            if w["indices"][-1] >= offset:
                w["indices"] = [i - offset for i in w["indices"] if i >= offset]
                flags.append(w)
        severity, rule_lines = cc.point_marks(points, flags, lim)
        labels = [u"%s %s" % (p["run_date"][:10], p["batch_id"]) for p in pts]
        return dict(self._empty_chart(analyte, ASYMMETRY, u"", units, limit), **{
            "qc_type_label": ASYMMETRY_LABEL, "method": self.selected_method() or u"",
            "labels": labels, "values": [p["value"] for p in points],
            "batch_ids": [p["batch_id"] for p in pts], "flags": [u"" for _p in pts],
            "analysts": [p["analyst"] for p in pts], "instruments": [p["instrument_id"] for p in pts],
            "dates": [p["date"] for p in points], "injections": [p["injection"] for p in pts],
            "point_severity": severity, "point_rules": rule_lines,
            "point_status": [u"active" for _p in pts], "point_nd": [False for _p in pts],
            "prov_keys": [u"" for _p in pts], "overlay": self.overlay_series(labels),
            "overlays": self.overlays_series(labels), "show": self.show(),
            "chart_type": "levey_jennings", "limits": lim, "drawn": drawn, "window": None,
            "type_group": None, "qc_types": [ASYMMETRY], "left_off": [], "limit_lines": self.limit_lines(),
            "point_kinds": [ASYMMETRY for _p in pts], "point_groups": [None for _p in pts],
            "too_few_points": lim is None, "baseline_n": cc.BASELINE_N,
            "insight": cc.insight_title(points, flags, noun=u"run", lim=lim),
            "has_rejects": u"reject" in severity, "has_warnings": any(severity),
            "n_points": len(pts), "demo_points": 0})

    def stack_json(self):
        """Several analytes on one chart (points only): {labels: ["date
        batch"], series: [{analyte, values}], units}. No limits: each
        analyte's mean and SD are its own."""
        if not self.is_stacked():
            return "null"
        # the same kinds as the one-analyte chart: blanks and kinds of
        # another measure are left off (kind_plan), every other ticked kind drawn
        used, left_off, left_why, _thr = self.kind_plan()
        qc_type = used[0] if used else self.selected_qc_type()
        many = len(used) > 1
        cells, nds, keys = {}, set(), set()
        if self.asymmetry_mode():
            from senaite.pfas import idc
            for a in self.selected_analytes():
                for p in self._asymmetry_series(a):
                    k = (p["run_date"][:10], p["batch_id"])
                    keys.add(k)
                    cells[(a, k)] = round(p["factor"], idc.SHOWN_PLACES)
        for a in ([] if self.asymmetry_mode() else self.selected_analytes()):
            for kind in used:
                try:
                    rows = self._store().get_chart_data(
                        self._spellings(a), kind,
                        qc_level=(self.selected_level() or ("Recovery" if kind == "LFSMD" else None)),
                        method=self.selected_method() or None, analyst=self.selected_analyst(),
                        instrument_id=self.selected_instrument(), limit=self.selected_limit(),
                        date_from=self.selected_date_from() or None,
                        date_to=self.selected_date_to() or None,
                        exclude_batches=self._study_hidden())
                except Exception as e:                      # noqa: BLE001
                    logger.error("stack get_chart_data %s: %s", a, e)
                    rows = []
                for r in rows:
                    v, nd = chart_value(kind, r)
                    if v is None:
                        continue
                    k = (str(r.get("run_date", ""))[:10], str(r.get("batch_id", ""))) + ((kind,) if many else ())
                    keys.add(k)
                    cells[(a, k)] = self._r(v)
                    if nd:
                        nds.add((a, k))
        order = sorted(keys)
        return script_json({
            "lot_markers": self._lot_markers([k[1] for k in order]),
            "overlay": self.overlay_series([u" ".join(k) for k in order]),
            "labels": [u" ".join(k) for k in order],
            "series": [{"analyte": a, "values": [cells.get((a, k)) for k in order],
                        "nd": [(a, k) in nds for k in order]}
                       for a in self.selected_analytes()],
            "units": QC_TYPE_UNITS.get(qc_type, ""),
            "qc_types": used, "left_off": left_off,
            "qc_type": u", ".join(self.qc_type_label(k) for k in used)})

    def selected_level(self):
        # a level belongs to one kind
        return self.request.get("qc_level", "") if len(self.selected_qc_types()) == 1 else ""

    def limit_lines(self):
        """The Average and sigma lines show unless the switch is off; the
        switch posts with a marker so off can be told from not asked."""
        f = self.request.form
        return bool(f.get("limit_lines")) or not f.get("limit_lines_form")

    # ── Blanks mode: Blank History's features on the chart page ──
    def blanks_mode(self):
        """A blank kind is selected: the page adds what rose, the lots that
        differ, the compare-two form and lot-change markers on the chart."""
        return bool(self.db_available and len(self.selected_qc_types()) == 1
                    and self.selected_qc_type() in BLANK_TYPES)

    @memoize
    def blank_view(self):
        """The blank runs this same request selects (its ?method=, ?qc_type=,
        ?a=, ?b=, ?matrix= are the ones this page uses)."""
        from senaite.pfas.browser.blank_history import BlankSelection
        return BlankSelection(self.context, self.request)

    def blank_runs(self):
        return self.blank_view().runs() if self.blanks_mode() else []

    def blank_pair(self):
        return self.blank_view().pair() if self.blanks_mode() else (None, None)

    def blank_comparison(self):
        return self.blank_view().comparison() if self.blanks_mode() else None

    def _lot_markers(self, batch_ids):
        """Lot changes between consecutive runs on the chart (blank_history
        .lot_markers), each run's lots read once."""
        if not self.blanks_mode() or not batch_ids:
            return []
        from senaite.pfas import blank_history as bh
        from senaite.pfas.browser.blank_history import run_lots
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        lots = {}
        for b in batch_ids:
            if b not in lots:
                try:
                    lots[b] = run_lots(portal, b)
                except Exception as exc:                        # noqa: BLE001
                    logger.warning("lot markers %s: %s", b, exc)
                    lots[b] = []
        return bh.lot_markers(list(batch_ids), lots)

    def selected_analysts(self):
        """The analysts ticked: one checkbox field each (`as.<name>`); an old
        link's single `analyst` is one tick; none ticked is every analyst."""
        if not hasattr(self, "_sel_analysts"):
            f = self.request.form
            have = self.analysts() if self.db_available else []
            picked = [a for a in have if f.get(u"as.%s" % a)]
            if not picked and f.get("analyst"):
                picked = [f.get("analyst")]
            self._sel_analysts = picked
        return self._sel_analysts

    def selected_analyst(self):
        """What the store filters on: the analysts ticked, None for every
        analyst (none ticked, or all of them)."""
        picked = self.selected_analysts()
        have = self.analysts() if self.db_available else []
        if not picked or (have and set(picked) >= set(have)):
            return None
        return picked

    def selected_instrument(self):
        return self.request.get("instrument_id", "") or None

    @staticmethod
    def _clean_date(value):
        """Accept only a well-formed ISO date (YYYY-MM-DD); ignore anything
        else so a stray value can't break the query."""
        import re as _re
        value = (value or "").strip()
        return value if _re.match(r"^\d{4}-\d{2}-\d{2}$", value) else ""

    def selected_date_from(self):
        return self._clean_date(self.request.get("date_from", ""))

    def selected_date_to(self):
        return self._clean_date(self.request.get("date_to", ""))

    def selected_limit(self):
        try:
            v = int(self.request.get("limit", DEFAULT_LIMIT))
            return min(max(v, 1), MAX_LIMIT)
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    # ── Store accessors (template helpers) ───────────────────────────────

    @property
    def db_path(self):
        return DEFAULT_DB_PATH

    @property
    def db_available(self):
        return os.path.exists(self.db_path)

    def _store(self):
        from senaite.pfas.qc.store import QCResultStore
        return QCResultStore(self.db_path)

    # ── QC-type display labels from core Reference Definitions ───────────
    # The UI-editable source of QC-type names is Setup -> Reference
    # Definitions. A definition opts in with a [QC:CODE] tag in its
    # Description; we map the stored qc_type code -> that definition's Title.
    # Both sides run through normalize_qc_type() so casing/aliases can't miss.
    def _qc_ref_label_map(self):
        if not hasattr(self, "_qc_label_cache"):
            from senaite.pfas.qc_labels import get_qc_label_map
            from bika.lims import api
            self._qc_label_cache = get_qc_label_map(api.get_portal())
        return self._qc_label_cache

    def qc_type_label(self, code):
        """Editable display name for a qc_type code (falls back to the raw
        code when no Reference Definition is tagged for it)."""
        if code == ASYMMETRY:
            return ASYMMETRY_LABEL
        from senaite.pfas.qc_labels import qc_label
        return qc_label(None, code, label_map=self._qc_ref_label_map())

    @memoize
    def methods(self):
        """Distinct method IDs in the QC results store."""
        if not self.db_available:
            return []
        try:
            return self._store().get_methods()
        except Exception as e:
            logger.error("methods: %s", e)
            return []

    @memoize
    def qc_types(self):
        # memoised: selected_qc_type() asked for it 18 times a page, one
        # DISTINCT over every QC row each
        if not self.db_available:
            return ["CCV", "LCS", "MB", "LFSM", "LFSMD", "IS"]
        try:
            return self._store().get_qc_types(self.selected_method() or None) or ["CCV", "LCS", "MB", "LFSM", "IS"]
        except Exception as e:
            logger.error("qc_types: %s", e)
            return []

    def _chart_name(self, name):
        """The name an analyte's series goes by: its keyword
        (compound_library.listed_namer), so a result stored under the
        export's name and one stored under the keyword are one series; an
        isomer peak keeps its own name; the name as stored when the library
        cannot be read."""
        if not hasattr(self, "_namer"):
            try:
                from senaite.pfas import compound_library, compound_library_store
                self._namer = compound_library.listed_namer(compound_library_store.library(), ())
            except Exception as e:                          # noqa: BLE001
                logger.warning("chart analyte names not resolved: %s", e)
                self._namer = lambda name: name
        return self._namer(name) or name

    def _analyte_groups(self, qc_type=None):
        """{series name: [the names its results are stored under]}."""
        cache = self.__dict__.setdefault("_groups", {})
        if qc_type == ASYMMETRY and qc_type not in cache:
            groups = {}
            for p in self._asymmetry_points():
                names = groups.setdefault(self._chart_name(p["analyte"]), [])
                if p["analyte"] not in names:
                    names.append(p["analyte"])
            cache[qc_type] = groups
        if qc_type not in cache:
            groups = {}
            if self.db_available:
                try:
                    method = self.selected_method() or None
                    stored = self._store().get_analytes(qc_type=qc_type, method=method)
                except Exception as e:
                    logger.error("analytes: %s", e)
                    stored = []
                # a row with no analyte (a run-level finding: CCV frequency)
                # is not a series
                for name in stored:
                    if name:
                        groups.setdefault(self._chart_name(name), []).append(name)
            cache[qc_type] = groups
        return cache[qc_type]

    def _spellings(self, analyte):
        """Every name the selected QC type's results of `analyte` are stored
        under, for the store's chart queries."""
        return self._selection_groups().get(analyte) or [analyte]

    def analytes(self, qc_type=None):
        return sorted(self._analyte_groups(qc_type))

    def qc_levels(self, qc_type=None, analyte=None):
        """[(value, label)]: one option per level, never one per injection."""
        if not self.db_available or qc_type == ASYMMETRY:
            return []
        try:
            return self._store().get_level_options(
                qc_type=qc_type, analyte=(self._analyte_groups(qc_type).get(analyte) or analyte)
                if analyte else analyte,
                method=self.selected_method() or None)
        except Exception as e:
            logger.error("qc_levels: %s", e)
            return []

    # ── Overlay: an environmental reading on a second axis ─────────────────
    def overlay_options(self):
        """[(value, label)]: each monitored unit's temperature, and a room's
        humidity, as "<unit id>:<field>"."""
        try:
            from senaite.pfas import facility_qc
            units = [u for u in facility_qc.list_units()
                     if u.get("unit_type") in facility_qc.READING_KINDS]
        except Exception as e:                              # noqa: BLE001
            logger.error("overlay_options: %s", e)
            return []
        out = []
        for u in units:
            name = u.get("name") or u"%s" % u.get("id")
            if u.get("unit_type") == "room_sensor":
                out.append((u"%s:humidity" % u["id"], u"%s humidity" % name))
            out.append((u"%s:temperature" % u["id"], u"%s temperature" % name))
        return out

    def selected_overlays(self):
        """The readings chosen (chart_overlay.selected: switches ov.<value>)."""
        from senaite.pfas import chart_overlay
        return chart_overlay.selected(self.request.form, [o[0] for o in self.overlay_options()])

    def selected_overlay(self):
        chosen = self.selected_overlays()
        return chosen[0] if chosen else ""

    def show(self):
        from senaite.pfas import chart_overlay
        return chart_overlay.show(self.request.form)

    def _page_url(self, **changes):
        """The page as it is (its filters), with `changes` set."""
        from six.moves.urllib.parse import urlencode
        form = dict((k, v) for k, v in self.request.form.items()
                    if k not in changes and isinstance(v, (str, type(u""))))
        q = dict(form, **changes)
        base = u"%s/@@pfas-control-chart" % self.context.absolute_url()
        return base + u"?" + urlencode(sorted((k, (v.encode("utf-8") if not isinstance(v, bytes) else v))
                                              for k, v in q.items()))

    def show_links(self):
        """Stacked | Relative overlay, each the page as it is with show= set."""
        return [{"label": label, "on": self.show() == key, "url": self._page_url(show=key)}
                for key, label in ((u"stacked", u"Stacked"), (u"relative", u"Relative overlay"))]

    def points_url(self):
        """The Download: the plotted points as CSV, with the page's filters."""
        return self._page_url(export=u"points")

    def overlays_series(self, labels):
        return [x for x in (self.overlay_series(labels, v) for v in self.selected_overlays()) if x]

    def overlay_series(self, labels, sel=None):
        """A chosen reading at each point: the mean of that run day's
        readings, None where there are none. None when no overlay is chosen."""
        sel = sel if sel is not None else self.selected_overlay()
        label = dict(self.overlay_options()).get(sel)
        if not label:
            return None
        unit_id, field = sel.rsplit(u":", 1)
        days = sorted(set((l or u"")[:10] for l in labels if l))
        try:
            from senaite.pfas import facility_qc
            means = facility_qc.daily_means(unit_id, field, days[0] if days else None,
                                            days[-1] if days else None)
        except Exception as e:                              # noqa: BLE001
            logger.error("overlay_series: %s", e)
            means = {}
        values = [means.get((l or u"")[:10]) for l in labels]
        return {"label": label, "unit": u"\u00b0C" if field == "temperature" else u"% RH",
                "values": [None if v is None else round(v, 2) for v in values],
                "empty": not [v for v in values if v is not None]}

    def level_label(self, value):
        """How the chosen level reads in the chart's subtitle."""
        for v, label in self.qc_levels(self.selected_qc_type(), self.selected_analyte()):
            if v == value:
                return label.split(u" \u00b7 ")[0]
        return value



    def summary(self):
        if not self.db_available:
            return []
        try:
            return self._store().get_summary()
        except Exception as e:
            logger.error("summary: %s", e)
            return []

    def date_bounds(self):
        """(min, max) run-date in the DB as ISO strings, for the date picker's
        min/max. Empty strings when there is no data."""
        if not self.db_available:
            return {"min": "", "max": ""}
        try:
            lo, hi = self._store().date_bounds()
            return {"min": lo or "", "max": hi or ""}
        except Exception as e:
            logger.error("date_bounds: %s", e)
            return {"min": "", "max": ""}

    def _cached_chart_dict(self):
        """Return (and cache) the chart dict for this request."""
        if not hasattr(self, "_chart_dict_cache"):
            self._chart_dict_cache = self._build_chart_dict()
        return self._chart_dict_cache

    def chart_data(self):
        """Expose chart dict directly to TAL (avoids JSON round-trip)."""
        return self._cached_chart_dict()

    def has_data(self):
        return bool(self._cached_chart_dict().get("n_points", 0))


    def chart_json(self):
        try:
            return script_json(self._cached_chart_dict())
        except (TypeError, ValueError):
            return "{}"

    def show_notes(self):
        """The Westgard notes panel: one analyte's Levey-Jennings chart whose
        limits stand (the rules judge nothing against a provisional line)."""
        d = self._cached_chart_dict()
        return bool(not self.is_stacked() and not self.asymmetry_mode()
                    and d.get("chart_type") == "levey_jennings" and d.get("limits"))

    @staticmethod
    def rule_label(rule):
        from senaite.pfas import control_chart as cc
        return cc.rule_label(rule)

    @staticmethod
    def note_line(v, data):
        """A note in one line: date, injection (else worksheet) and value."""
        value = u"%s %s" % (v.get("value"), data.get("unit") or u"")
        return u" \u00b7 ".join([x for x in (v.get("date"), v.get("injection") or v.get("batch_id"),
                                             value.strip()) if x])

    def filter_summary(self):
        """The page's filters in one line, for the printed chart."""
        d = self._cached_chart_dict()
        bits = [u"Method: %s" % (self.method_name(self.selected_method()) if self.selected_method() else u"all methods"),
                u"QC kinds: %s" % u", ".join(self.selected_qc_types() or [u"none"]),
                u"Analytes: %s" % u", ".join(self.selected_analytes() or [u"none"])]
        for label, val in ((u"Analysts", u", ".join(self.selected_analysts())), (u"Instrument", self.selected_instrument()),
                           (u"From", self.selected_date_from()), (u"To", self.selected_date_to())):
            if val:
                bits.append(u"%s: %s" % (label, val))
        bits.append(u"Runs shown: %s" % self.selected_limit())
        return u" \u00b7 ".join(bits) if d is not None else u""

    def analyst_filter_label(self, picked, available):
        """"All analysts" when none or all are ticked, else the names."""
        if not picked or (available and set(picked) >= set(available)):
            return u"All analysts"
        return self.analyte_button_label(picked, available)

    def kind_name(self, kind):
        return ASYMMETRY_LABEL if kind == ASYMMETRY else kind

    @staticmethod
    def type_icon(kind):
        """A kind's own symbol; an empty slot of the same width for a kind
        none holds (IS, peak asymmetry), so the labels line up."""
        return sti.svg(kind, hidden=True) or u'<span class="pfas-type-slot" aria-hidden="true"></span>'

    def kinds_label(self):
        """The kinds on the chart, in words."""
        used = self.kind_plan()[0]
        return u", ".join(self.qc_type_label(k) for k in used)

    def left_off_note(self):
        """Kinds ticked but not on the chart, and why."""
        d = self._cached_chart_dict()
        left, why = d.get("left_off") or [], d.get("left_off_why") or {}
        out = []
        blanks = [k for k in left if why.get(k) == "blanks"]
        other = [k for k in left if why.get(k) == "measure"]
        if blanks:
            out.append(u"%s: blanks have their own threshold chart; untick the other kinds to see them."
                       % u", ".join(blanks))
        if other:
            out.append(u"%s: not the same measure as the kinds charted; chart %s on its own to see it."
                       % (u", ".join(other), u"it" if len(other) == 1 else u"them"))
        return u" ".join(out)

    def few_points_note(self):
        """The line under a chart whose limits do not yet stand."""
        d = self._cached_chart_dict()
        drawn, n = d.get("drawn"), d.get("n_points", 0)
        if drawn:
            return (u"Provisional limits from the %d in-control results of the series so far; "
                    u"they are fixed at %d." % (drawn["n_baseline"], d["baseline_n"]))
        return u"Limits need at least 2 results; %d shown." % n

    def westgard_violations(self):
        """The Westgard notes still standing (not dismissed): information
        only, nothing reads them as a gate."""
        return self._cached_chart_dict().get("westgard", [])

    def can_review(self):
        """Dismiss a warning / remove a point: managers and QC reviewers."""
        from senaite.pfas.browser.perms import (
            MANAGER_ROLES, ANALYST_ROLES, has_role_at_portal)
        return has_role_at_portal(self.context, MANAGER_ROLES | ANALYST_ROLES)

    # ── Review actions (POST) ────────────────────────────────────────────

    _ACTIONS = {"dismiss": ("dismissed", True), "undismiss": ("dismissed", False),
                "remove": ("excluded", True), "restore": ("excluded", False)}

    def _handle_post(self):
        form = self.request.form
        action = form.get("chart_action", "")
        back = form.get("came_from") or self.request.get("HTTP_REFERER") or (
            self.context.absolute_url() + "/@@pfas-control-chart")
        if not self.can_review():
            return refuse(self.request, "Forbidden")
        # only after the role check, as every PFAS POST view does
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)
        if action not in self._ACTIONS:
            self.request.response.setStatus(400)
            return "Unknown action"
        kind, add = self._ACTIONS[action]
        try:
            rid = int(form.get("result_id"))
        except (TypeError, ValueError):
            self.request.response.setStatus(400)
            return "result_id required"
        rule = form.get("rule", u"") or u""
        try:
            user = self.request.get("AUTHENTICATED_USER")
            who = user.getId() if user is not None else u""
            if add:
                self._store().annotate(rid, kind, form.get("reason"), who, rule=rule)
            else:
                self._store().unannotate(rid, kind, rule=rule, by_user=who)
        except ValueError as exc:
            sep = "&" if "?" in back else "?"
            self.request.response.redirect("%s%schart_error=%s" % (
                back, sep, str(exc).replace(" ", "+")))
            return ""
        self.request.response.redirect(back)
        return ""

    # ── JSON endpoint ────────────────────────────────────────────────────

    def _json_response(self):
        self.request.response.setHeader("Content-Type", "application/json")
        data = self._build_chart_dict()
        try:
            return json.dumps(data)
        except (TypeError, ValueError) as e:
            return json.dumps({"error": str(e)})

    # ── Points download (CSV) ────────────────────────────────────────────

    def export_points(self):
        """The points the chart draws, read from the chart's own dict so the
        download and the page cannot disagree: date, run, injection, analyte,
        value, unit, verdict, rule."""
        from senaite.pfas import control_chart as cc
        d = self._cached_chart_dict()
        name = u"control-chart-%s-%s.csv" % tuple(
            re.sub(r"[^A-Za-z0-9_-]", "_", x or u"none") for x in (d.get("analyte"), u"-".join(d.get("qc_types") or [d.get("qc_type")])))
        resp = self.request.response
        resp.setHeader("Content-Type", "text/csv; charset=utf-8")
        resp.setHeader("Content-Disposition", 'attachment; filename="%s"' % name)
        return cc.points_csv(cc.point_rows(d)).encode("utf-8")

    # ── The y axis while there are too few points for limits ─────────────

    @memoize
    def _calibrations(self):
        """The Calibration Archive's view: its method_limits read a method's
        check-standard windows as the worker judges them."""
        from senaite.pfas.browser.calibrations import PFASCalibrationsView
        return PFASCalibrationsView(self.context, self.request)

    def qc_window(self, qc_type, method):
        """(low, high) the method judges this QC type in, or None: no method,
        no whole window, a low-level window that may apply instead, or a
        type judged per matrix tier."""
        from senaite.pfas import control_chart as cc
        if not method:
            return None
        try:
            lim = self._calibrations().method_limits(method)
        except Exception as e:                              # noqa: BLE001
            logger.warning("chart window %s: %s", method, e)
            return None
        return cc.check_window(lim, qc_type)

    # ── Chart data builder ───────────────────────────────────────────────

    @staticmethod
    def _measure(kind):
        """What a kind's charted value is: kinds whose unit is a recovery
        pool together; any other kind is a measure of its own (a duplicate's
        RPD, an internal standard's response)."""
        return "recovery" if QC_TYPE_UNITS.get(kind) == "Recovery (%)" else kind

    def kind_plan(self, kinds=None):
        """(used, left_off, why, is_threshold) for the ticked kinds: a
        threshold chart when every kind is a blank kind; otherwise the
        recovery kinds pooled (else the first kind alone). Blanks, and kinds
        of another measure, are left off with the reason."""
        kinds = self.selected_qc_types() if kinds is None else kinds
        thr = [k for k in kinds if self._is_threshold_kind(k)]
        if kinds and len(thr) == len(kinds):
            return list(kinds), [], {}, True
        non = [k for k in kinds if k not in thr]
        rec = [k for k in non if self._measure(k) == "recovery"]
        used = rec or non[:1]
        why = dict((k, "blanks") for k in thr)
        for k in non:
            if k not in used:
                why[k] = "measure"
        return used, [k for k in kinds if k in why], why, False

    @staticmethod
    def _is_threshold_kind(kind):
        """A blank kind: charted against its threshold, never as a recovery."""
        try:
            from senaite.pfas.qc.rules import get_store as _get_rules_store
            return bool(_get_rules_store().is_threshold_chart(kind))
        except Exception:                                   # noqa: BLE001
            return kind in ("MB", "MxB", "LRB")

    def _study_hidden(self):
        """Worksheets of studies not opted into the charts."""
        if not hasattr(self, "_hidden"):
            from bika.lims import api
            from senaite.pfas import study_records
            try:
                self._hidden = study_records.chart_hidden(
                    study_records.load(api.get_portal()))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("study runs not hidden: %s", exc)
                self._hidden = set()
        return self._hidden

    def _build_chart_dict(self):
        if self.asymmetry_mode():
            return self._asymmetry_chart_dict()
        kinds       = self.selected_qc_types()
        qc_type     = self.selected_qc_type()
        analyte     = self.selected_analyte()
        method      = self.selected_method() or None
        qc_level    = self.selected_level() or None
        analyst     = self.selected_analyst()           # a list, or None for every analyst
        instrument  = self.selected_instrument()
        limit       = self.selected_limit()
        date_from   = self.selected_date_from() or None
        date_to     = self.selected_date_to() or None
        # the chart type follows the QC kinds (kind_plan): a threshold chart
        # when every kind ticked is a blank kind; otherwise the recovery
        # kinds, pooled. Blanks, and kinds of another measure, are left off
        # and the chart says so.
        used, left_off, left_why, is_threshold = self.kind_plan(kinds)
        qc_type     = used[0] if used else qc_type
        units       = QC_TYPE_UNITS.get(qc_type, "")
        target      = QC_TYPE_TARGETS.get(qc_type)

        if not self.db_available or not analyte or not qc_type:
            return self._empty_chart(analyte, qc_type, qc_level or "",
                                     units, limit)

        filters = dict(qc_level=qc_level, method=method, analyst=analyst,
                       instrument_id=instrument,
                       date_from=date_from, date_to=date_to,
                       exclude_batches=self._study_hidden())
        store = self._store()
        try:
            rows = []
            for k in used:
                kf = dict(filters)
                if k == "LFSMD" and not qc_level:
                    # an LFSMD stores an RPD and a recovery per duplicate: the
                    # chart is its recovery unless a level is chosen
                    kf["qc_level"] = "Recovery"
                rows.extend(dict(r, _kind=k) for r in store.get_chart_data(
                    self._spellings(analyte), k, limit=SERIES_MAX, **kf))
        except Exception as e:
            logger.error("get_chart_data: %s", e)
            return self._empty_chart(analyte, qc_type, qc_level or "",
                                     units, limit)
        # the whole series in acquisition order, every kind together: the run
        # date, then when each was acquired (a check standard's qc_level is
        # "<injection>|<acquired>"), then the row
        rows.sort(key=lambda r: (str(r.get("run_date", "")), (r.get("qc_level") or "").partition("|")[2],
                                 r.get("id") or 0))

        if not rows:
            return self._empty_chart(analyte, qc_type, qc_level or "",
                                     units, limit)

        points = []
        for r in rows:
            fv, nd = chart_value(r["_kind"], r)
            if fv is None:
                continue
            points.append({
                "kind":          r["_kind"],
                "nd":            nd,
                "id":            r.get("id"),
                "date":          str(r.get("run_date", ""))[:10],
                "value":         fv,
                "batch_id":      str(r.get("batch_id", "")),
                "flag":          str(r.get("flag", "")),
                "analyst":       str(r.get("analyst") or r.get("batch_analyst") or ""),
                "instrument_id": str(r.get("instrument_id", "")),
                "status":        str(r.get("result_status", "active")),
                # the value's provenance record: a point click opens it on
                # the run's Data Review
                "prov_key":      str(r.get("prov_key") or ""),
                "injection":     injection_of(r.get("qc_level")),
                "method":        str(r.get("method") or ""),
                # the window the worker judged it in, when it recorded one
                "window":        (r.get("limit_low"), r.get("limit_high")),
            })

        threshold_val = None
        if is_threshold:
            try:
                from senaite.pfas.qc.rules import get_store as _get_rules_store
                threshold_val = _get_rules_store().get_qc_type_rules(qc_type).get("threshold")
            except Exception:                               # noqa: BLE001
                threshold_val = None

        # Control-chart review: removed points are off the chart and out of
        # the mean / SD; dismissed warnings are set aside with who and why.
        from senaite.pfas import control_chart as cc
        try:
            notes = store.get_annotations([p["id"] for p in points])
        except Exception as e:                              # noqa: BLE001
            logger.error("chart annotations: %s", e)
            notes = []
        excluded = dict((n["result_id"], n) for n in notes if n["action"] == "excluded")
        # a dismissal made under the former Levey-Jennings view's rule names
        # stands for the Westgard rule that now says the same thing
        dismissed = dict(("%s:%s" % (n["result_id"], LEGACY_RULES.get(n["rule"], n["rule"])), n)
                         for n in notes if n["action"] == "dismissed")
        removed = [dict(p, note=excluded[p["id"]]) for p in points if p["id"] in excluded]
        series = [p for p in points if p["id"] not in excluded]
        removed.sort(key=lambda p: (str(p["note"].get("at") or ""), p["id"] or 0), reverse=True)
        removed_shown = removed if self.request.form.get("removed_all") else removed[:REMOVED_SHOWN]
        # Runs shown only says how many of the series are drawn: the limits
        # and the rules stand on the whole series
        offset = max(0, len(series) - limit)
        points = series[offset:]

        if is_threshold:
            limits = drawn = None
            all_warnings = []
        else:
            drawn = cc.drawn_limits([p["value"] for p in series])
            # limits stand on BASELINE_N in-control results of the series; on
            # fewer the lines drawn are provisional and no point is judged
            # against them. The Westgard set is always evaluated, over the
            # whole series; its findings are notes
            limits = drawn if cc.ready(drawn) else None
            all_warnings = []
            for w in cc.westgard(series, limits):
                if w["indices"][-1] < offset:
                    continue                        # ends before the first point drawn
                w["indices"] = [i - offset for i in w["indices"] if i >= offset]
                all_warnings.append(w)
        for w in all_warnings:
            w["date"] = points[w["indices"][-1]]["date"]
            w["batch_id"] = points[w["indices"][-1]]["batch_id"]
            w["value"] = self._r(points[w["indices"][-1]]["value"])
            w["injection"] = points[w["indices"][-1]]["injection"]
        violations = cc.active(all_warnings, dismissed)
        dismissed_list = [dict(w, note=dismissed[w["key"] if w["key"] in dismissed else w["legacy_key"]],
                               stored_rule=dismissed[w["key"] if w["key"] in dismissed else w["legacy_key"]]["rule"])
                          for w in all_warnings if cc.is_dismissed(w, dismissed)]

        # each point's mark and the rules its tooltip leads with; a threshold
        # chart judges a point above its threshold
        threshold = self._r(threshold_val)
        if is_threshold:
            severity, rule_lines = cc.threshold_marks(points, threshold)
        else:
            severity, rule_lines = cc.point_marks(points, violations, limits)
        # a point whose finding was dismissed says so, never "in control"
        point_dismissed = [[] for _p in points]
        for w in dismissed_list:
            for i in w["indices"]:
                point_dismissed[i].append(cc.rule_line(w, points[i].get("value"), limits))
        too_few = not is_threshold and limits is None
        window = recorded = None
        if too_few:
            # the axis: the windows the points were judged in; the method's
            # window only for a point that recorded none
            judged = [p["window"] for p in points]
            fallback = None
            if not all(w[0] is not None and w[1] is not None for w in judged):
                methods = set(p["method"] for p in points if p["method"])
                fallback = self.qc_window(qc_type, method or (methods.pop() if len(methods) == 1 else None))
            window = cc.axis_window(judged, fallback)
            recorded = len(series)

        labels, values, batch_ids, flags = [], [], [], []
        analysts_list, instruments_list = [], []
        point_status, point_nd, prov_keys = [], [], []
        point_kinds = [p["kind"] for p in points]

        for i, p in enumerate(points):
            # one run per label: several runs share a date
            labels.append(u"%s %s" % (p["date"], p["batch_id"]))
            point_nd.append(bool(p.get("nd")))
            values.append(self._r(p["value"]))
            batch_ids.append(p["batch_id"])
            flags.append(p["flag"])
            analysts_list.append(p["analyst"])
            instruments_list.append(p["instrument_id"])
            point_status.append(p["status"])
            prov_keys.append(p.get("prov_key") or "")

        return {
            "analyte":        analyte,
            "qc_type":        qc_type,
            "qc_types":       used,
            "qc_type_label":  u", ".join(self.qc_type_label(k) for k in used),
            "left_off":       left_off,
            "left_off_why":   left_why,
            "point_dismissed": point_dismissed,
            "point_kinds":    point_kinds,
            "point_groups":   [sti.group_of(k) for k in point_kinds],
            "method":         method or "",
            "qc_level":       qc_level or "",
            "units":          units,
            "labels":         labels,
            "values":         values,
            "batch_ids":      batch_ids,
            "flags":          flags,
            "analysts":       analysts_list,
            "instruments":    instruments_list,
            "dates":          [p["date"] for p in points],
            "injections":     [p["injection"] for p in points],
            "point_severity": severity,
            "point_rules":    rule_lines,
            "point_status":   point_status,
            "point_nd":       point_nd,
            "prov_keys":      prov_keys,
            "lot_markers":    self._lot_markers(batch_ids),
            "overlay":        self.overlay_series(labels),
            "overlays":       self.overlays_series(labels),
            "show":           self.show(),
            "limits":         limits,
            "drawn":          drawn,
            # each point is its QC type's icon (sample_type_icons), drawn in
            # the flag colour when a rule flags it
            "type_group":     sti.group_of(qc_type),
            "limit_lines":    self.limit_lines(),
            "target":         target,
            "threshold":      threshold,
            "chart_type":     "threshold" if is_threshold else "levey_jennings",
            "unit":           chart_unit(qc_type),
            "too_few_points": too_few,
            "baseline_n":     cc.BASELINE_N,
            "recorded":       recorded,
            # the store holds more than the chart shows: the line says how many
            "more_recorded":  bool(recorded and recorded > len(points)),
            "window":         list(window) if window else None,
            "insight":        cc.insight_title(points, violations,
                                               noun=qc_type if len(used) == 1 else u"QC result", lim=limits,
                                               chart="threshold" if is_threshold else "levey_jennings",
                                               threshold=threshold, dismissed=len(dismissed_list),
                                               recorded=recorded),
            "westgard":       violations,
            "dismissed":      dismissed_list,
            # the newest removals first, so a point removed today can be restored
            "removed":        [{"id": p["id"], "date": p["date"], "batch_id": p["batch_id"],
                                "value": self._r(p["value"]), "note": p["note"]}
                               for p in removed_shown],
            "removed_more":   len(removed) - len(removed_shown),
            "has_rejects":    any(v["severity"] == "reject" for v in violations),
            "has_warnings":   any(v["severity"] == "warning" for v in violations),
            "n_points":       len(points),
            # example runs (tools/demo_control_charts.py): the page
            # says so whenever one is on the chart
            "demo_points":    sum(1 for b in batch_ids if b.startswith("DEMO-")),
            "limit":          limit,
        }

    @staticmethod
    def _empty_chart(analyte, qc_type, qc_level, units, limit):
        return {
            "analyte": analyte, "qc_type": qc_type,
            "qc_level": qc_level, "units": units,
            "labels": [], "values": [], "batch_ids": [],
            "flags": [], "analysts": [], "instruments": [],
            "dates": [], "injections": [], "point_severity": [], "point_rules": [],
            "point_status": [], "unit": chart_unit(qc_type), "too_few_points": False,
            "window": None, "recorded": None, "more_recorded": False, "insight": u"",
            "limits": None, "target": None,
            "westgard": [], "dismissed": [], "removed": [], "removed_more": 0,
            "has_rejects": False,
            "has_warnings": False, "n_points": 0,
            "limit": limit, "qc_types": [qc_type] if qc_type else [], "left_off": [],
            "point_kinds": [], "point_groups": [], "limit_lines": True, "qc_type_label": u"",
        }

    @staticmethod
    def _r(v, digits=4):
        if v is None:
            return None
        try:
            import math as _math
            fv = float(v)
            if _math.isinf(fv) or _math.isnan(fv):
                return None
            return round(fv, digits)
        except (TypeError, ValueError):
            return None
