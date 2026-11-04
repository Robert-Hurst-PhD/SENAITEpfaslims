# -*- coding: utf-8 -*-
"""
PFAS Guided Instrument Import & Mapping Studio (@@pfas-import-studio).

Two-phase flow:
  Phase 1 (GET / POST action=upload):
    Drop a test CSV/TXT file; auto-detect the vendor; show a column-mapping
    grid where the analyst assigns each file column to a canonical purpose.
  Phase 2 (POST action=save_profile):
    Persist the mapping as JSON in ZODB annotations on the selected
    Instrument object, keyed by software version string.

Stored profile format:
  IAnnotations(instrument)["senaite.pfas.instrument_profiles"]
    = PersistentMapping {software_version: json_string}

The pipeline worker loads the saved profile via the REST API
(senaite_connector.py) and uses it during import -- no SENAITE-internal
code changes are required in the pipeline.

Python 2.7 compatible -- no f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import re

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form, json_list
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action
from senaite.pfas.browser.view_helpers import ViewHelpers
from senaite.pfas import lab_time

logger = logging.getLogger("senaite.pfas.browser.import_studio")


# ── Canonical purpose descriptions ────────────────────────────────────────────

# The mapping-grid vocabulary IS the importer's field list — one definition.
# This used to be a hand-maintained copy that had drifted
# into a strict SUBSET of what the importer consumes, so "Reporting Limit" and
# "Expected Ion Ratios" could not be mapped at all: the two columns the BLoQ
# qualifier and the ion-ratio check need.
from senaite.pfas.instrument_columns import (   # noqa: E402
    CANONICAL_FIELDS, NATIVE_COLUMN_MAP, duplicate_targets)

PURPOSES = list(CANONICAL_FIELDS)


# ── Python 2.7-compatible vendor detection ────────────────────────────────────

# Mirrored from pfas_pipeline/vendor_profiles.py detect_vendor() and maps.
_VENDOR_COLUMN_MAP = {
    "sciex": {
        "vendor": "SCIEX OS",
        "signature_cols": frozenset(["Component Name", "Area Ratio"]),
        "map": {
            "Component Name":           "compound_name",
            "Component Type":           "compound_type",
            "Sample Name":              "injection_name",
            "Sample ID":                "sample_id",
            "Sample Type":              "sample_type",
            "Retention Time":           "observed_rt",
            "Area":                     "response",
            "IS Area":                  "is_response",
            "Area Ratio":               "response_ratio",
            "Expected Concentration":   "expected_conc",
            # "Calculated Concentration" = post-adjustment final reported value
            "Calculated Concentration": "calculated_conc",
            "Final Concentration":      "calculated_conc",
            # "Concentration" = direct calibration-curve result, pre-adjustment
            "Concentration":            "measured_conc",
            "Analyte Concentration":    "measured_conc",
            "Accuracy":                 "pct_deviation",
            "%Accuracy":                "pct_deviation",
            "% Accuracy":              "pct_deviation",
            "R":                        "r2",
            "R^2":                      "r2",
            "Signal / Noise":           "signal_to_noise",
            "Signal/Noise":             "signal_to_noise",
            "IS Name":                  "linked_is",
            "ISTD Name":                "linked_is",
            "Ion Ratio":                "ion_ratios",
            "Acquisition Date":         "acq_date_str",
            "Acquisition Time":         "acq_time_str",
            "Dilution Factor":          "sample_factor",
            # Quantitation status / flags
            "Quantitation Status":      "quant_status",
            "Quant. Status":            "quant_status",
            "Status":                   "quant_status",
            "Use Record":               "ignore",
        },
    },
    "agilent": {
        "vendor": "Agilent MassHunter",
        "signature_cols": frozenset(["ISTD Resp", "Final Conc."]),
        "map": {
            "Compound Name":    "compound_name",
            "Name":             "compound_name",
            "Data File":        "injection_name",
            "Sample Name":      "sample_id",
            "Type":             "sample_type",
            "Sample Type":      "sample_type",
            "RT":               "observed_rt",
            "Area":             "response",
            "ISTD Resp":        "is_response",
            "ISTD Area":        "is_response",
            "Resp. Ratio":      "response_ratio",
            "Exp. Conc.":       "expected_conc",
            # "Final Conc." = post-adjustment (dilution, matrix) reported value
            "Final Conc.":      "calculated_conc",
            "Adjusted Conc.":   "calculated_conc",
            # "Calc. Conc." = calibration-curve result before sample corrections
            "Calc. Conc.":      "measured_conc",
            "Calculated Conc.": "measured_conc",
            "Accuracy":         "pct_deviation",
            "%Dev":             "pct_deviation",
            "R^2":              "r2",
            "S/N":              "signal_to_noise",
            "Qualifier S/N":    "qual_sn",
            "Qualifier Ratio":  "ion_ratios",
            "Ion Ratio":        "ion_ratios",
            "ISTD":             "linked_is",
            "ISTD Name":        "linked_is",
            "Level":            "level",
            "Cal Level":        "level",
            # Quantitation status / flags
            "Compound Status":  "quant_status",
            "Use":              "quant_status",
            "Flags":            "quant_status",
            "Flag":             "quant_status",
        },
    },
    "waters": {
        "vendor": "Waters MassLynx/TargetLynx",
        "signature_cols": frozenset(["Sample Text", "IS Area"]),
        "map": {
            "Name":             "compound_name",
            "Compound":         "compound_name",
            "Compound Name":    "compound_name",
            "Type":             "compound_type",
            "Sample Text":      "sample_id",
            "Sample Name":      "injection_name",
            "Sample Type":      "sample_type",
            "RT":               "observed_rt",
            "Area":             "response",
            "IS Area":          "is_response",
            "Response":         "response_ratio",
            "Resp. Ratio":      "response_ratio",
            "Std. Conc":        "expected_conc",
            "Std Conc":         "expected_conc",
            # "Conc." in TargetLynx = post-adjustment final reported value
            "Conc.":            "calculated_conc",
            "Conc":             "calculated_conc",
            # Raw concentration before sample-prep adjustments
            "ng/mL":            "measured_conc",
            "%Dev":             "pct_deviation",
            "% Dev":            "pct_deviation",
            "Accuracy":         "pct_deviation",
            "R2":               "r2",
            "R^2":              "r2",
            "S/N":              "signal_to_noise",
            "Signal/Noise":     "signal_to_noise",
            "Acq.Date":         "acq_date_str",
            "Acq.Time":         "acq_time_str",
            "Acquisition Date": "acq_date_str",
            "Acquisition Time": "acq_time_str",
            # Quantitation status / flags
            "Status":           "quant_status",
            "Fail Reason":      "quant_status",
            "Flags":            "quant_status",
        },
    },
    "native": {
        "vendor": "FDA Native / Pass-through",
        # Signature: a native export is recognised by carrying the canonical
        # header names themselves, not by a vendor-specific quirk.
        "signature_cols": frozenset([
            "Compound Name", "Injection Name", "Calculated Concentration"]),
        # Already-canonical headers, so the "mapping" is the identity. Empty
        # before, which is why a native file fell through to the regex
        # guesser and came back with three columns aimed at observed_rt.
        "map": dict(NATIVE_COLUMN_MAP),
    },
}


# ── Cross-vendor regex fallback patterns ──────────────────────────────────────
# Applied when a column name doesn't match any vendor exact-match entry.
# Ordered most-specific first; first match wins.

_FALLBACK_PATTERNS = [
    # Ion-ratio family, most specific first: software versions name
    # these slightly differently. The tolerance, deviation and
    # check columns are the software's own verdict, not a ratio.
    (re.compile(r'(?i)\bion\s+ratios?\s+(tolerances?|deviations?|checks?)\b'), 'ignore'),
    (re.compile(r'(?i)\bmethod\s+expected\s+ion\s+ratios?\b'),       'method_expected_ion_ratios'),
    (re.compile(r'(?i)\bquan(t|titation)?\s*ref(erence)?\.?\s+expected\s+ion\s+ratios?\b'),
     'quan_ref_expected_ion_ratios'),
    (re.compile(r'(?i)\b(expected|target|reference)\s+ion\s+ratios?\b'), 'expected_ion_ratios'),
    (re.compile(r'(?i)\bqual(ifier)?\.?\s+ions?\s+(responses?|areas?)\b'), 'qual_ions_responses'),
    # Compound / analyte
    (re.compile(r'(?i)\b(compound|analyte|component)\s+name\b'),    'compound_name'),
    (re.compile(r'(?i)\bcomponent\b'),                               'compound_name'),
    (re.compile(r'(?i)\bcompound\s+type\b'),                         'compound_type'),
    (re.compile(r'(?i)\bcomponent\s+type\b'),                        'compound_type'),

    # Injection / run identifier
    (re.compile(r'(?i)\b(data\s+file|injection\s+name|run\s+(id|name))\b'), 'injection_name'),
    (re.compile(r'(?i)\bsample\s+name\b'),                           'injection_name'),
    (re.compile(r'(?i)\bvial\b'),                                    'injection_name'),

    # Sample ID (client barcode / text)
    (re.compile(r'(?i)\bsample\s+(id|identifier|text|#|no\.?)\b'),  'sample_id'),
    (re.compile(r'(?i)\bclient\s+sample\b'),                         'sample_id'),

    # Sample type
    (re.compile(r'(?i)\bsample\s+type\b'),                           'sample_type'),

    # Calculated / final conc (AFTER dilution, matrix, weight corrections)
    (re.compile(r'(?i)\bcalculated\s+(conc|amount)\b'),              'calculated_conc'),
    (re.compile(r'(?i)\bcalc\.?\s+conc'),                            'calculated_conc'),
    (re.compile(r'(?i)\b(final|reported)\s+amount\b'),               'calculated_conc'),
    (re.compile(r'(?i)\bfinal\s+conc'),                              'calculated_conc'),
    (re.compile(r'(?i)\badjusted\s+conc'),                           'calculated_conc'),
    (re.compile(r'(?i)\breported\s+conc'),                           'calculated_conc'),

    # Measured / analyte conc (BEFORE corrections, direct from cal curve)
    (re.compile(r'(?i)\bmeasured\s+conc'),                           'measured_conc'),
    (re.compile(r'(?i)\banalyte\s+conc'),                            'measured_conc'),
    (re.compile(r'(?i)\braw\s+conc'),                                'measured_conc'),

    # Expected / standard concentration
    (re.compile(r'(?i)\b(expected|theoretical|nominal)\s+conc'),     'expected_conc'),
    (re.compile(r'(?i)\bstd\.?\s+conc'),                             'expected_conc'),

    # Generic conc fallback (intentionally low priority; after specific ones)
    (re.compile(r'(?i)\bconc(entration)?\b'),                        'measured_conc'),

    # Linked IS name — must come BEFORE generic IS area patterns
    (re.compile(r'(?i)\bis\s+name\b'),                               'linked_is'),
    (re.compile(r'(?i)\bistd?\s+name\b'),                            'linked_is'),
    (re.compile(r'(?i)\binternal\s+std\.?\s+name\b'),                'linked_is'),

    # IS peak area (suffix required to avoid matching "ISTD Name")
    (re.compile(r'(?i)\bis\s+(area|response|resp\.?)\b'),            'is_response'),
    (re.compile(r'(?i)\b(istd|i\.?s\.?)\s+(area|resp\.?|response)\b'), 'is_response'),
    (re.compile(r'(?i)\binternal\s+std\.?\s+(area|response)\b'),     'is_response'),

    # Native peak area
    (re.compile(r'(?i)\b(native|analyte|compound|peak)\s+area\b'),   'response'),
    (re.compile(r'(?i)\bpeak\s*area\b'),                             'response'),

    # Area / response ratio
    (re.compile(r'(?i)\b(area|resp(onse)?|resp\.?)\s+ratio\b'),      'response_ratio'),

    # Retention time
    (re.compile(r'(?i)\bret(ention)?\s*time\b'),                     'observed_rt'),
    (re.compile(r'(?i)\b(r\.?t\.?)\b'),                              'observed_rt'),

    # Qualifier S/N (before plain S/N — more specific)
    (re.compile(r'(?i)\bqual(ifier)?\s+(s\s*/\s*n|signal[\s/]noise)\b'), 'qual_sn'),

    # Signal / noise
    (re.compile(r'(?i)\bsignal\s*/?\s*(to\s*)?noise\b'),             'signal_to_noise'),
    (re.compile(r'(?i)\bs\s*/\s*n\b'),                               'signal_to_noise'),

    # Ion ratio
    (re.compile(r'(?i)\bion\s+ratios?\b'),                           'ion_ratios'),
    (re.compile(r'(?i)\bqualifier\s+ratio\b'),                       'ion_ratios'),
    (re.compile(r'(?i)\bq\s*/\s*p\b'),                               'ion_ratios'),

    # % Deviation / accuracy
    (re.compile(r'(?i)\baccuracy\b'),                                'pct_deviation'),
    (re.compile(r'(?i)\b%\s*dev(iation)?\b'),                        'pct_deviation'),
    (re.compile(r'(?i)\bdev(iation)?\b'),                            'pct_deviation'),

    # r²
    (re.compile(r'(?i)\br\s*[\^2]\s*2?\b'),                         'r2'),
    (re.compile(r'(?i)\bcorrelation\b'),                             'r2'),

    # Calibration level
    (re.compile(r'(?i)\b(cal\.?\s+)?level\b'),                       'level'),

    # Quantitation status / flags
    (re.compile(r'(?i)\bquant(itation)?\s+status\b'),                'quant_status'),
    (re.compile(r'(?i)\bcompound\s+status\b'),                       'quant_status'),
    (re.compile(r'(?i)\bstatus\b'),                                  'quant_status'),
    (re.compile(r'(?i)\bflags?\b'),                                  'quant_status'),
    (re.compile(r'(?i)\bfail\s+reason\b'),                           'quant_status'),
    (re.compile(r'(?i)\bintegration\s+flag\b'),                      'quant_status'),

    # Acquisition date / time
    (re.compile(r'(?i)\b(acq\.?|acquisition|injection)\s+date\b'),   'acq_date_str'),
    (re.compile(r'(?i)\b(acq\.?|acquisition|injection)\s+time\b'),   'acq_time_str'),
    (re.compile(r'(?i)\bdate\b'),                                    'acq_date_str'),
    (re.compile(r'(?i)\btime\b'),                                    'acq_time_str'),

    # Sample dilution / weight
    (re.compile(r'(?i)\bdilution\s+factor\b'),                       'sample_factor'),
    (re.compile(r'(?i)\bsample\s+(weight|factor)\b'),                'sample_factor'),
]


def _detect_vendor_py27(headers):
    """Best-effort auto-detection from CSV headers. Returns (vendor_key, confidence).

    Signature match is only claimed when >=50% of the vendor's signature columns
    are present — prevents a single shared column (e.g. "Component Name") from
    mis-identifying a Waters file as SCIEX.
    Uses float division to avoid Python 2.7 integer-division truncation.
    """
    h = set(headers)
    # "native" is a real instrument identity, not a fallback: an export whose
    # headers are already the canonical names needs no mapping at all. Leaving
    # it out of detection meant a canonical file was scored against vendors it
    # only incidentally overlapped with, and lost to whichever shared the most
    # generic column names.
    for key in ("native", "sciex", "agilent", "waters"):
        sig = _VENDOR_COLUMN_MAP[key]["signature_cols"]
        if sig and sig & h:
            overlap = len(sig & h)
            conf = min(100, int(float(overlap) / max(len(sig), 1) * 100))
            if conf >= 50:
                return key, conf
    # Weaker signal: score by column-name overlap against the vendor's full map
    scores = {}
    for vkey, vdata in _VENDOR_COLUMN_MAP.items():
        known = set(vdata["map"].keys())
        scores[vkey] = len(known & h)
    if scores:
        best = max(scores, key=lambda k: scores[k])
        if scores[best] > 0:
            conf = min(95, int(float(scores[best]) / max(len(_VENDOR_COLUMN_MAP[best]["map"]), 1) * 100))
            return best, conf
    return "native", 10


def _suggest_mapping(headers, vendor_key):
    """Return {column: suggested_purpose} for the given headers.

    Priority order:
      1. Vendor-specific exact match (from _VENDOR_COLUMN_MAP)
      2. Cross-vendor regex pattern (from _FALLBACK_PATTERNS)
      3. "ignore"
    """
    vmap = _VENDOR_COLUMN_MAP.get(vendor_key, {}).get("map", {})
    result = {}
    # Exact vendor matches are authoritative; regex guesses are not. Track how
    # each column was assigned so that when two columns claim the same field
    # the guess yields to the exact match instead of overwriting it.
    exact = set()
    for col in headers:
        if col in vmap:
            result[col] = vmap[col]
            exact.add(col)
            continue
        matched = None
        for pattern, purpose in _FALLBACK_PATTERNS:
            if pattern.search(col):
                matched = purpose
                break
        result[col] = matched if matched is not None else 'ignore'

    # Never suggest a mapping that would silently discard data. Three columns
    # matched the RT pattern here ("Expected RT", "Observed RT", "RT Relative
    # to IS") and all three were proposed as observed_rt; pandas' rename keeps
    # only the last. Keep one claimant per field and leave the rest to the
    # analyst to assign deliberately.
    for target, claimants in duplicate_targets(result).items():
        keep = None
        for col in claimants:
            if col in exact:
                keep = col
                break
        if keep is None:
            keep = claimants[0]
        for col in claimants:
            if col != keep:
                result[col] = 'ignore'
    return result


# ── Profile store helpers ─────────────────────────────────────────────────────


# ── Portal-level profile / template helpers ───────────────────────────────────


# The log Import Studio kept before its changes went to Configuration
# History: read, never written.
IMPORT_STUDIO_AUDIT_KEY = u"senaite.pfas.import_studio_audit"


def studio_log(portal, limit=20):
    """The newest layout and export-layout changes: Configuration History's
    (an entry without an action is one the earlier log also holds), then the
    earlier log's."""
    from senaite.pfas import config_history, lab_time
    rows = []
    for store in ("import_profile", "instrument_export"):
        for e in config_history.entries(portal, store=store, limit=limit):
            if e.get("action"):
                rows.append({"ts": e["at"], "action": e["action"], "name": e.get("label"),
                             "user": e.get("who"), "reason": e.get("reason")})
    for r in IAnnotations(portal).get(IMPORT_STUDIO_AUDIT_KEY) or []:
        try:
            rows.append(json.loads(r))
        except (ValueError, TypeError):
            continue
    rows.sort(key=lambda r: r.get("ts") or u"", reverse=True)
    # stored in UTC, shown on the laboratory's clock
    return [dict(r, ts=lab_time.show(r.get("ts") or u"")) for r in rows[:limit]]


# ── REST bridge view ──────────────────────────────────────────────────────────

class PFASInstrumentProfileView(BrowserView):
    """JSON endpoint the pipeline worker asks for a file's import layout.

    POST/GET @@pfas-instrument-profile  head=<the file's first lines>
                                        instrument_uid=<the run's instrument>
      -> 200 the saved layout profile ({"id", "name", "reader", "map", ...})
      -> 200 {"error": "..."} when no saved layout fits the file, or two do

    The file is read with each saved layout's own options and matched by its
    columns (senaite.pfas.import_layouts.match); a file no layout fits is
    refused, never sent to a pass-through. `columns` alone (a header row an
    older worker read as comma-separated) is matched the same way.
    """

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        self.request.response.setHeader("Content-Type", "application/json")
        f = self.request.form
        head = f.get("head") or ""
        columns = []
        raw_columns = f.get("columns") or ""
        if raw_columns:
            try:
                columns = json.loads(raw_columns)
            except (ValueError, TypeError):
                columns = [c for c in raw_columns.split("\t") if c]
        if not head and not columns:
            self.request.response.setStatus(400)
            return json.dumps({"error": "send the file's first lines (head) to match its import layout"})
        from senaite.pfas import import_layouts, import_layouts_store
        try:
            profile = import_layouts_store.match_file(
                portal, head=head, instrument_uid=(f.get("instrument_uid") or "").strip(),
                columns=columns)
        except import_layouts.LayoutRefused as exc:
            return json.dumps({"error": "%s" % exc})
        profile = dict(profile)
        profile["resolved_id"] = profile.get("id")
        profile["resolved_name"] = profile.get("name")
        return json.dumps(profile)


# ── View ─────────────────────────────────────────────────────────────────────

# Every Studio POST authors or changes an instrument mapping -- the single
# source of truth the importer reads -- so all are lab
# configuration. `upload` persists nothing, but it is the first step
# of authoring; a bench user reaching the mapping screen only to be refused at
# save is worse than being refused at the start. The pipeline never POSTs here:
# it reads @@pfas-instrument-profile.
STUDIO_GATES = {
    "upload": TIER_CONFIG,
    "sniff": TIER_CONFIG,          # reads a dropped file's options; saves nothing
    "save_profile": TIER_CONFIG,
    "retire_profile": TIER_CONFIG,
    "reactivate_profile": TIER_CONFIG,
    "delete_profile": TIER_CONFIG,
    "save_export": TIER_CONFIG,
}


class PFASImportStudioView(ViewHelpers, GateMixin, BrowserView):
    """Guided Instrument Import & Mapping Studio."""

    template = ViewPageTemplateFile("templates/import_studio.pt")

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            denied = deny_gated_action(
                self.context, self.request, action, STUDIO_GATES)
            if denied is not None:
                return denied
            if action == "upload":
                return self._handle_upload()
            if action == "sniff":
                return self._handle_sniff()
            if action == "retire_profile":
                return self._handle_retire_profile(True)
            if action == "reactivate_profile":
                return self._handle_retire_profile(False)
            if action == "delete_profile":
                return self._handle_delete_profile()
            if action == "save_profile":
                return self._handle_save_profile()
            if action == "save_export":
                return self._handle_save_export()
        if action == "edit_profile":
            return self._handle_edit_profile()
        return self.template()

    # -- Helpers -------------------------------------------------------------

    def _handle_retire_profile(self, retired):
        from senaite.pfas import import_layouts_store
        f = self.request.form
        ok = import_layouts_store.set_retired(
            self._portal(), (f.get("layout_id") or "").strip(), retired,
            reason=(f.get("reason") or "").strip())
        msg = ("Layout+retired" if retired else "Layout+reactivated") if ok else "Layout+not+found"
        return self._redirect("{0}?ok={1}".format(self._self_url(), msg))

    def _handle_delete_profile(self):
        """Delete a layout profile; Configuration History keeps what it was."""
        from senaite.pfas import import_layouts_store
        f = self.request.form
        ok = import_layouts_store.delete(self._portal(), (f.get("layout_id") or "").strip(),
                                         reason=(f.get("reason") or "").strip())
        return self._redirect("{0}?{1}".format(
            self._self_url(), "ok=Layout+deleted" if ok else "error=Layout+not+found"))

    def saved_profiles(self):
        """The saved import layouts, for the list: name, instrument, layout,
        columns, status."""
        from senaite.pfas import import_layouts, import_layouts_store
        titles = dict((i["uid"], i["title"]) for i in self.instruments())
        kinds = dict(import_layouts.LAYOUTS)
        out = []
        for p in import_layouts_store.list_profiles(self._portal()):
            out.append({"id": p["id"], "name": p.get("name") or p["id"],
                        "instrument": titles.get(p.get("instrument_uid") or "", u"any instrument")
                        if p.get("instrument_uid") else u"any instrument",
                        "layout": kinds.get((p.get("reader") or {}).get("layout") or "long", u""),
                        "n_columns": len(p.get("signature") or []),
                        "retired": bool(p.get("retired")), "notes": p.get("notes") or u""})
        return out

    # -- Injection list per instrument (instrument_export.py) ----

    def export_configs(self):
        """Per instrument: the injection-list format its software reads."""
        from senaite.pfas import instrument_export
        out = []
        catalog = getToolByName(self.context, "senaite_catalog_setup")
        from senaite.pfas.browser.equipment import offered_in_worksheets
        for brain in catalog({"portal_type": "Instrument", "sort_on": "sortable_title"}):
            obj = brain.getObject()
            if not offered_in_worksheets(obj):
                continue                 # only instruments that run samples
            version, cfg = instrument_export.current(instrument_export.load(obj))
            cols, where = instrument_export.columns_for(obj)
            out.append({"uid": obj.UID(), "title": obj.Title(), "version": version,
                        "software": (cfg or {}).get("software") or u"Waters MassLynx",
                        "saved": bool(cfg), "saved_by": (cfg or {}).get("saved_by") or u"",
                        "saved_at": lab_time.show((cfg or {}).get("saved_at") or u""),
                        "columns_text": instrument_export.columns_text(cols),
                        # the table's rows: what fills each column of the list
                        "columns": [{"header": h, "source": (src if not src.startswith(u"fixed:") else u"fixed"),
                                     "fixed": src[6:] if src.startswith(u"fixed:") else u""}
                                    for h, src in cols or []]})
        return out

    # what can fill a column of the injection list (run_plan.SOURCES, then a
    # fixed text); the stored form is unchanged ("source" or "fixed:<text>")
    EXPORT_SOURCES = ((u"name", u"Injection name"), (u"description", u"Description"),
                      (u"vial", u"Vial position"), (u"type", u"Injection type"),
                      (u"level", u"Calibration level"), (u"fixed", u"Fixed value"))
    # the words an injection type is written in: one "Injection type" source,
    # its wording on the row (stored "type" or "masslynx-type", as before);
    # another vendor's wording is added when the lab supplies it
    TYPE_WORDINGS = ((u"type", u"LIMS words"), (u"masslynx-type", u"Waters MassLynx"))

    def export_starters_json(self):
        """The software choices and the columns each starts with (the
        MassLynx starter; Other starts with none)."""
        from senaite.pfas import run_plan
        return json.dumps({u"Waters MassLynx": run_plan.MASSLYNX_COLUMNS, u"Other": []})

    def _handle_save_export(self):
        from datetime import datetime
        from AccessControl import getSecurityManager
        from senaite.pfas import instrument_export
        f = self.request.form
        uid = (f.get("instrument_uid") or u"").strip()
        version = (f.get("version") or u"").strip()
        brains = getToolByName(self.context, "uid_catalog")(UID=uid) if uid else []
        if not brains or not version:
            return self._redirect("{0}?error={1}".format(
                self._self_url(), "Choose+the+instrument+and+give+the+software+version"))
        columns = instrument_export.parse_columns(f.get("columns") or u"")
        if not columns:
            return self._redirect("{0}?error={1}".format(self._self_url(), "Give+at+least+one+column"))
        user = getSecurityManager().getUser().getId()
        at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        instrument_export.save(brains[0].getObject(), version, (f.get("software") or u"").strip(),
                               columns, user, at)
        return self._redirect("{0}?ok=Injection+list+format+saved".format(self._self_url()))

    def studio_audit(self):
        return studio_log(self._portal())

    def layout_row_url(self, p):
        """Where a saved layout's row opens: its editor, for those who may edit."""
        if not self.can_configure():
            return u""
        return u"{0}/@@pfas-import-studio?action=edit_profile&layout_id={1}".format(self.portal_url(), p["id"])

    def layout_status(self):
        """The Saved Import Layouts filter: active (the default) or retired."""
        return "retired" if self.request.form.get("layouts") == "retired" else "active"

    def _self_url(self):
        return "{0}/@@pfas-import-studio".format(self.context.absolute_url())

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    # -- Template data -------------------------------------------------------

    def instruments(self):
        """The instruments that run samples, for the instrument selector."""
        from senaite.pfas.browser.equipment import offered_in_worksheets
        catalog = getToolByName(self.context, "senaite_catalog_setup")
        result = []
        for brain in catalog({"portal_type": "Instrument", "sort_on": "sortable_title"}):
            try:
                obj = brain.getObject()
                if not offered_in_worksheets(obj):
                    continue
                result.append({
                    "uid": obj.UID(),
                    "title": obj.Title(),
                })
            except Exception:
                pass
        return result

    def selected_instrument(self):
        uid = self.request.form.get("instrument_uid", "")
        if not uid:
            return None
        catalog = getToolByName(self.context, "uid_catalog")
        brains = catalog(UID=uid)
        if brains:
            try:
                return brains[0].getObject()
            except Exception:
                pass
        return None

    def purposes(self):
        return PURPOSES


    # -- Upload state (passed via hidden form fields after parse) ------------

    def upload_result_json(self):
        """The parse result the handler put on the form, re-emitted as JSON
        for the page's script. A value that is not JSON (a URL parameter of
        the same name) is null."""
        from senaite.pfas.document_templates import script_json
        raw = self.request.form.get("upload_result_json", "null")
        try:
            return script_json(json.loads(raw))
        except (TypeError, ValueError):
            return "null"

    # -- the reader options the page offers (senaite.pfas.import_layouts) ----

    def layout_choices(self):
        from senaite.pfas import import_layouts as L
        return {"layouts": L.LAYOUTS, "layout_hints": L.LAYOUT_HINTS,
                "delimiters": L.DELIMITERS, "encodings": L.ENCODINGS,
                "match": L.MATCH_MODES}

    def skip_rows(self):
        """The skip conditions to draw: the form's, else one empty row."""
        from senaite.pfas import import_layouts as L
        return L.options(self.reader_form())["skip_conditions"] or [["", ""]]

    def reader_form(self):
        """The reader options as the upload form last held them (defaults first)."""
        from senaite.pfas import import_layouts as L
        f = self.request.form
        out = dict(L.READER_DEFAULTS)
        for k in L.READER_DEFAULTS:
            if f.get(k) not in (None, ""):
                out[k] = f.get(k)
        if any(("%s" % k).startswith("skip_col.") for k in f):
            out["skip_conditions"] = L.skip_conditions_from_form(f)
        return out

    # -- Phase 1: upload & read ----------------------------------------------

    def _handle_sniff(self):
        """A dropped export, read before anything is chosen (upload first):
        the reader options the file shows, a saved layout it fits (whose
        options then take over) and how many columns and rows they read.
        JSON; nothing is saved."""
        from senaite.pfas import import_layouts as L
        from senaite.pfas import import_layouts_store
        self.request.response.setHeader("Content-Type", "application/json")
        upload = self.request.form.get("upload_file")
        try:
            raw = upload.read() if upload is not None and hasattr(upload, "read") else b""
        except Exception:                                   # noqa: BLE001
            raw = b""
        if not raw:
            return json.dumps({"error": u"The file is empty."})
        g = L.guess_options(raw)
        text = L.decode(raw, g["encoding"])
        saved = None
        try:
            existing = import_layouts_store.match_file(self._portal(), head=L.head(text), instrument_uid="")
        except L.LayoutRefused:
            existing = None
        if existing:
            reader = L.options(existing.get("reader"))
            for k in ("layout", "delimiter", "encoding", "header_row"):
                g[k] = reader.get(k, g[k])
            saved = {"name": existing.get("name") or existing.get("id"),
                     "instrument_uid": existing.get("instrument_uid") or u""}
        opts = dict(L.READER_DEFAULTS, layout=g["layout"], delimiter=g["delimiter"],
                    encoding=g["encoding"], header_row=g["header_row"])
        try:
            got = L.read(text, opts)
            columns, rows = len(got["headers"]), len(got["rows"])
        except ValueError:
            columns = rows = 0
        g.update(saved=saved, columns=columns, rows=rows,
                 filename=getattr(upload, "filename", u"") or u"")
        return json.dumps(g)

    def _handle_upload(self):
        """Read the uploaded export with the reader options chosen on the
        form; a saved layout the file fits is opened for editing, else the
        columns start from the detected vendor's suggestions. Nothing is
        saved."""
        from senaite.pfas import import_layouts as L
        from senaite.pfas import import_layouts_store
        f = self.request.form
        instrument_uid = (f.get("instrument_uid") or "").strip()
        upload = f.get("upload_file")
        upload_filename = getattr(upload, "filename", "") or ""
        if not upload or not hasattr(upload, "read") or not upload_filename:
            return self._redirect("{0}?error=Please+select+a+file+before+uploading".format(self._self_url()))
        try:
            raw = upload.read()
        except Exception as exc:
            return self._redirect("{0}?error=Upload+failed:+{1}".format(self._self_url(), str(exc)[:40]))
        opts = L.options(self.reader_form())
        text = L.decode(raw, opts.get("encoding"))
        if not text.strip():
            return self._redirect("{0}?error=File+is+empty".format(self._self_url()))
        try:
            got = L.read(text, opts)
        except ValueError as exc:
            self.request.form["error"] = u"%s" % exc
            return self.template()
        headers = got["headers"]
        if not headers:
            self.request.form["error"] = (u"No column was read with these options: check the "
                                          u"layout, the delimiter and the header row.")
            return self.template()
        preview = [[r.get(h, u"") for h in headers] for r in got["rows"][:3]]
        vendor_key, confidence = _detect_vendor_py27(headers)
        col_map = _suggest_mapping(headers, vendor_key)
        # a saved layout this file fits (its own columns, this instrument):
        # opened for editing -- never another layout's mapping
        existing, notice = None, u""
        try:
            existing = import_layouts_store.match_file(self._portal(), head=L.head(text),
                                                       instrument_uid=instrument_uid)
        except L.LayoutRefused as exc:
            existing, notice = None, u"%s" % exc
            closest = getattr(exc, "closest", None)
            if closest:
                # never guessed into processing: the analyst maps the file,
                # starting from the columns the closest layout found
                found = L.resolve_map(closest, headers)
                col_map = dict((h, found.get(h) or col_map.get(h, "ignore")) for h in headers)
        settings = {}
        if existing:
            found = L.resolve_map(existing, headers)
            col_map = dict((h, found.get(h, "ignore")) for h in headers)
            settings = self._settings_of(existing)
            opts = L.options(existing.get("reader"))
        instr_title = u""
        if instrument_uid:
            brains = getToolByName(self.context, "uid_catalog")(UID=instrument_uid)
            if brains:
                instr_title = brains[0].getObject().Title() or u""
        self.request.form["upload_result_json"] = json.dumps({
            "filename": upload_filename, "headers": headers, "preview": preview,
            "rows_read": len(got["rows"]), "delimiter": got["delimiter"],
            "vendor_key": vendor_key, "confidence": confidence, "col_map": col_map,
            "instrument_uid": instrument_uid, "instrument_title": instr_title,
            "reader": opts, "signature": got["signature"],
            "existing_profile": bool(existing), "layout_id": (existing or {}).get("id") or "",
            "settings": settings, "notice": notice,
        })
        return self.template()

    def _settings_of(self, p):
        """A saved layout's settings as the save form shows them."""
        from senaite.pfas import import_layouts as L
        return {"layout_name": p.get("name") or "", "match": p.get("match") or "within",
                "required_fields": u", ".join(p.get("required") or []),
                "calc_mode": p.get("calc_mode") or "final",
                "manual_markers": p.get("manual_markers") or "",
                "date_format": p.get("date_format") or "",
                "value_maps": L.format_value_maps(p.get("value_maps")),
                "scales": L.format_scales(p.get("scales")),
                "qualifier_suffix": p.get("qualifier_suffix") or "",
                "labelled_from_columns": bool(p.get("labelled_from_columns")),
                "notes": p.get("notes") or "", "software": p.get("software") or ""}

    # -- Phase 1b: a saved layout, opened for editing (no file) ------------

    def _handle_edit_profile(self):
        from senaite.pfas import import_layouts_store
        f = self.request.form
        p = import_layouts_store.get(self._portal(), (f.get("layout_id") or "").strip())
        if not p:
            return self._redirect("{0}?error=Layout+not+found".format(self._self_url()))
        headers = list(p.get("columns") or p.get("signature") or [])
        self.request.form["upload_result_json"] = json.dumps({
            "filename": u"Saved layout: %s" % (p.get("name") or p["id"]), "headers": headers,
            "preview": [], "rows_read": 0, "delimiter": "", "vendor_key": "", "confidence": 100,
            "col_map": dict((h, (p.get("map") or {}).get(h, "ignore")) for h in headers),
            "instrument_uid": p.get("instrument_uid") or "", "instrument_title": u"",
            "reader": p.get("reader") or {}, "signature": p.get("signature") or [],
            "existing_profile": True, "layout_id": p["id"], "edit_mode": True,
            "settings": self._settings_of(p),
        })
        return self.template()

    # -- Phase 2: save the layout ---------------------------------------------

    def _handle_save_profile(self):
        """Save the layout profile from the form (senaite.pfas.import_layouts.
        build_profile): refused, naming what is missing, when it could not
        import a file."""
        from senaite.pfas import import_layouts as L
        from senaite.pfas import import_layouts_store
        f = dict(self.request.form)
        try:
            f.update(json.loads(f.get("reader_json") or "{}"))
        except (ValueError, TypeError):
            pass
        profile, problems = L.build_profile(f, duplicate_targets=duplicate_targets)
        try:
            profile["columns"] = json_list(f, "columns_json", "column list")
        except ValueError as exc:
            problems.append(u"{0}".format(exc))
        if problems:
            return self._redirect("{0}?error={1}".format(self._self_url(), _q(u" ".join(problems))))
        lid = import_layouts_store.save(self._portal(), profile)
        return self._redirect("{0}?ok={1}".format(
            self._self_url(), _q(u"Layout saved: %s" % (profile.get("name") or lid))))


def _q(text):
    """Text for a redirect's query string (Python 2: bytes first)."""
    from six.moves.urllib.parse import quote_plus
    return quote_plus(text.encode("utf-8") if not isinstance(text, bytes) else text)
