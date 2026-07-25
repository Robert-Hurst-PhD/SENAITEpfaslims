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

import csv
import json
import logging
import re

import StringIO

from persistent.mapping import PersistentMapping
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.import_studio")

# Per-instrument profile store (existing — keyed by software version string)
INSTR_PROFILES_KEY = u"senaite.pfas.instrument_profiles"

# Portal-level: working profiles used by the pipeline importer.
# Key format: "vendor_key:version"  e.g. "sciex:1.7.2"
# Written when a lab saves a profile in Import Studio.
# The pipeline reads ONLY from here (strict mode — seeded templates don't count).
PORTAL_PROFILES_KEY = u"senaite.pfas.vendor_profiles"

# Portal-level: read-only default templates that pre-fill Import Studio UI.
# Seeded at install from _VENDOR_COLUMN_MAP.  The pipeline importer does NOT
# read from here; it reads only from PORTAL_PROFILES_KEY.
PORTAL_TEMPLATES_KEY = u"senaite.pfas.vendor_templates"

# ── Canonical purpose descriptions ────────────────────────────────────────────

PURPOSES = [
    ("ignore",          "Ignore"),
    # ── Identifiers ──────────────────────────────────────────────────────────
    ("compound_name",   "Analyte / Compound Name"),
    ("compound_type",   "Compound Type (native analyte / IS flag)"),
    ("sample_id",       "Sample Identifier (client-facing ID or barcode)"),
    ("injection_name",  "Injection / Run Name (data file / vial label)"),
    ("sample_type",     "Sample Type (Cal / QC / Unknown / Blank)"),
    # ── Concentrations ───────────────────────────────────────────────────────
    # measured_conc  = result straight off the calibration curve, BEFORE any
    #                  sample-preparation corrections (dilution, matrix factor,
    #                  salt factor, weight).  Some vendors call this "Calc. Conc."
    # calculated_conc = final reported value AFTER all adjustments are applied.
    #                   Some vendors call this "Final Conc." or just "Conc."
    ("measured_conc",   "Measured Conc. (pre-adjustment, direct from cal. curve)"),
    ("calculated_conc", "Calculated / Final Conc. (post-adjustment, reported value)"),
    ("expected_conc",   "Expected / Standard Concentration (cal. standard target)"),
    # ── Instrument response ──────────────────────────────────────────────────
    ("response",        "Raw Peak Area (native analyte)"),
    ("is_response",     "IS Peak Area"),
    ("response_ratio",  "Area Ratio (native / IS)"),
    # ── Chromatography ───────────────────────────────────────────────────────
    ("observed_rt",     "Retention Time (RT)"),
    ("signal_to_noise", "Signal / Noise (S/N)"),
    ("qual_sn",         "Qualifier S/N"),
    ("ion_ratios",      "Ion Ratio (qualifier / quantifier)"),
    # ── QC & calibration ─────────────────────────────────────────────────────
    ("pct_deviation",   "% Deviation / Accuracy"),
    ("r2",              "Calibration r or r²"),
    ("linked_is",       "Linked Internal Standard"),
    ("level",           "Calibration Level"),
    ("quant_status",    "Quantitation Status / Flags (pass, fail, review)"),
    # ── Metadata ─────────────────────────────────────────────────────────────
    ("acq_date_str",    "Acquisition Date"),
    ("acq_time_str",    "Acquisition Time"),
    ("sample_factor",   "Sample Dilution / Weight Factor"),
]

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
        "signature_cols": frozenset(),
        "map": {},
    },
}


# ── Cross-vendor regex fallback patterns ──────────────────────────────────────
# Applied when a column name doesn't match any vendor exact-match entry.
# Ordered most-specific first; first match wins.

_FALLBACK_PATTERNS = [
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
    (re.compile(r'(?i)\bion\s+ratio\b'),                             'ion_ratios'),
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
    for key in ("sciex", "agilent", "waters"):
        sig = _VENDOR_COLUMN_MAP[key]["signature_cols"]
        if sig and sig & h:
            overlap = len(sig & h)
            conf = min(100, int(float(overlap) / max(len(sig), 1) * 100))
            if conf >= 50:
                return key, conf
    # Weaker signal: score by column-name overlap against the vendor's full map
    scores = {}
    for vkey, vdata in _VENDOR_COLUMN_MAP.items():
        if vkey == "native":
            continue
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
    for col in headers:
        if col in vmap:
            result[col] = vmap[col]
            continue
        matched = None
        for pattern, purpose in _FALLBACK_PATTERNS:
            if pattern.search(col):
                matched = purpose
                break
        result[col] = matched if matched is not None else 'ignore'
    return result


def _detect_software_version(lines):
    """Scan first 20 lines for a version string like X.Y.Z or X.Y.Z.W."""
    version_re = re.compile(r'\b(\d+\.\d+[\.\d]*)\b')
    for line in lines[:20]:
        m = version_re.search(line)
        if m:
            return m.group(1)
    return ""


# ── Profile store helpers ─────────────────────────────────────────────────────

def _get_profile_store(instrument):
    ann = IAnnotations(instrument)
    if INSTR_PROFILES_KEY not in ann:
        ann[INSTR_PROFILES_KEY] = PersistentMapping()
    return ann[INSTR_PROFILES_KEY]


def _list_profiles(instrument):
    """Return list of {version, vendor, calc_mode} for all saved profiles."""
    store = _get_profile_store(instrument)
    result = []
    for ver, raw in store.items():
        try:
            data = json.loads(raw)
            result.append({
                "version": ver,
                "vendor": data.get("vendor", ""),
                "calc_mode": data.get("calc_mode", "final"),
            })
        except (ValueError, TypeError):
            pass
    return sorted(result, key=lambda x: x["version"])


def _save_profile(instrument, version, vendor_key, calc_mode, column_map, notes=""):
    store = _get_profile_store(instrument)
    data = {
        "vendor": _VENDOR_COLUMN_MAP.get(vendor_key, {}).get("vendor", vendor_key),
        "vendor_key": vendor_key,
        "calc_mode": calc_mode,
        "map": column_map,
        "notes": notes,
    }
    store[version] = json.dumps(data)


def _load_profile(instrument, version):
    store = _get_profile_store(instrument)
    raw = store.get(version)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


# ── Portal-level profile / template helpers ───────────────────────────────────

def _get_portal_store(portal, key):
    ann = IAnnotations(portal)
    if key not in ann:
        ann[key] = PersistentMapping()
    return ann[key]


def _portal_profile_key(vendor_key, version):
    """Composite lookup key for portal-level stores."""
    return u"{0}:{1}".format(vendor_key, version or "")


def save_vendor_profile(portal, vendor_key, version, profile_data):
    """Write a profile to the portal-level importer store."""
    store = _get_portal_store(portal, PORTAL_PROFILES_KEY)
    store[_portal_profile_key(vendor_key, version)] = json.dumps(profile_data)


def load_vendor_profile(portal, vendor_key, version):
    """Read a profile from the portal-level importer store; None if absent."""
    store = _get_portal_store(portal, PORTAL_PROFILES_KEY)
    raw = store.get(_portal_profile_key(vendor_key, version))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


IMPORT_STUDIO_AUDIT_KEY = u"senaite.pfas.import_studio_audit"


def _audit_import_studio(portal, entry):
    """Append an audit entry for import-profile lifecycle events. Profiles are
    annotation records (not content objects), so SENAITE snapshots don't apply;
    this dedicated log is the audit trail, surfaced in the Import Studio UI."""
    import datetime
    from persistent.list import PersistentList
    ann = IAnnotations(portal)
    if IMPORT_STUDIO_AUDIT_KEY not in ann:
        ann[IMPORT_STUDIO_AUDIT_KEY] = PersistentList()
    entry = dict(entry)
    entry["ts"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    ann[IMPORT_STUDIO_AUDIT_KEY].append(json.dumps(entry))


def get_import_studio_audit(portal, limit=50):
    ann = IAnnotations(portal)
    raw = ann.get(IMPORT_STUDIO_AUDIT_KEY) or []
    out = []
    for r in list(raw)[-limit:]:
        try:
            out.append(json.loads(r))
        except (ValueError, TypeError):
            continue
    return list(reversed(out))


def set_vendor_profile_retired(portal, vendor_key, version, retired, user,
                               reason=""):
    """Retire (or reactivate) a saved import profile. Retired profiles are
    REFUSED by the pipeline REST bridge, so imports cannot silently use a
    withdrawn mapping. Every transition is written to the audit log."""
    prof = load_vendor_profile(portal, vendor_key, version)
    if prof is None:
        return False
    prof["retired"] = bool(retired)
    prof["retired_by" if retired else "reactivated_by"] = user
    save_vendor_profile(portal, vendor_key, version, prof)
    _audit_import_studio(portal, {
        "action": "retire" if retired else "reactivate",
        "vendor_key": vendor_key, "version": version or "",
        "user": user, "reason": reason or "",
    })
    return True


def list_vendor_profiles(portal):
    """All saved portal-level import profiles with retired state."""
    store = _get_portal_store(portal, PORTAL_PROFILES_KEY)
    out = []
    for key in sorted(store.keys()):
        try:
            prof = json.loads(store[key])
        except (ValueError, TypeError):
            continue
        vk, _, ver = key.partition(":")
        out.append({
            "key": key, "vendor_key": vk, "version": ver,
            "vendor": prof.get("vendor", vk),
            "n_columns": len(prof.get("map", {}) or {}),
            "retired": bool(prof.get("retired")),
            "notes": prof.get("notes", ""),
        })
    return out


def load_vendor_template(portal, vendor_key):
    """Return the default column-map template for a vendor (UI pre-fill only)."""
    store = _get_portal_store(portal, PORTAL_TEMPLATES_KEY)
    raw = store.get(vendor_key)
    if not raw:
        # Inline fallback: use _VENDOR_COLUMN_MAP directly
        vdata = _VENDOR_COLUMN_MAP.get(vendor_key)
        if vdata:
            return {
                "vendor": vdata["vendor"],
                "vendor_key": vendor_key,
                "calc_mode": "final",
                "map": vdata["map"],
                "notes": vdata.get("notes", ""),
            }
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def seed_vendor_templates(portal):
    """Idempotent: write default templates to PORTAL_TEMPLATES_KEY.

    Called from setuphandlers and lazily from Import Studio's upload handler.
    Only writes vendors that don't already have a template entry.
    """
    store = _get_portal_store(portal, PORTAL_TEMPLATES_KEY)
    seeded = 0
    for vendor_key, vdata in _VENDOR_COLUMN_MAP.items():
        if vendor_key not in store:
            store[vendor_key] = json.dumps({
                "vendor": vdata["vendor"],
                "vendor_key": vendor_key,
                "calc_mode": "final",
                "map": dict(vdata.get("map", {})),
                "notes": vdata.get("notes", ""),
            })
            seeded += 1
    if seeded:
        logger.info("Seeded %d vendor template(s) into %s", seeded, PORTAL_TEMPLATES_KEY)
    return seeded


# ── REST bridge view ──────────────────────────────────────────────────────────

class PFASInstrumentProfileView(BrowserView):
    """JSON endpoint used by the pipeline importer to fetch a saved column-
    mapping profile.

    GET @@pfas-instrument-profile?vendor_key=sciex&version=1.7.2
      → 200 {"vendor": "SCIEX OS", "vendor_key": "sciex", "map": {...}, ...}
      → 200 {"error": "No import mapping exists for sciex version 1.7.2 — ..."}

    The pipeline treats any response with an "error" key as a refusal.
    No profile is served from the templates store; only explicitly saved
    profiles (written by Import Studio) satisfy the pipeline's check.
    """

    def __call__(self):
        flatten_form(self.request)
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        vendor_key = (self.request.form.get("vendor_key", "") or "").strip().lower()
        version = (self.request.form.get("version", "") or "").strip()

        self.request.response.setHeader("Content-Type", "application/json")

        if not vendor_key:
            self.request.response.setStatus(400)
            return json.dumps({"error": "vendor_key parameter is required"})

        profile = load_vendor_profile(portal, vendor_key, version)
        if profile is not None and profile.get("retired"):
            self.request.response.setHeader("Content-Type", "application/json")
            return json.dumps({"error": (
                "Import profile for {0} version {1} is RETIRED — imports are "
                "refused. Reactivate it in Import Studio if this mapping is "
                "still valid.".format(vendor_key, version or "(any)"))})
        if profile is not None:
            return json.dumps(profile)

        # Not found — return refusal message for the pipeline
        v_label = _VENDOR_COLUMN_MAP.get(vendor_key, {}).get("vendor", vendor_key)
        if version:
            detail = "{0} version {1}".format(v_label, version)
        else:
            detail = v_label
        return json.dumps({
            "error": (
                "No import mapping exists for {0} — "
                "open Import Studio to create one.".format(detail)
            )
        })


# ── View ─────────────────────────────────────────────────────────────────────

class PFASImportStudioView(BrowserView):
    """Guided Instrument Import & Mapping Studio."""

    template = ViewPageTemplateFile("templates/import_studio.pt")

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            if action == "upload":
                return self._handle_upload()
            if action == "retire_profile":
                return self._handle_retire_profile(True)
            if action == "reactivate_profile":
                return self._handle_retire_profile(False)
            if action == "save_profile":
                return self._handle_save_profile()
        if action == "edit_profile":
            return self._handle_edit_profile()
        return self.template()

    # -- Helpers -------------------------------------------------------------

    def _handle_retire_profile(self, retired):
        from AccessControl import getSecurityManager
        f = self.request.form
        user = getSecurityManager().getUser().getId()
        ok = set_vendor_profile_retired(
            self._portal(), (f.get("vendor_key") or "").strip(),
            (f.get("version") or "").strip(), retired, user,
            reason=(f.get("reason") or "").strip())
        msg = ("Profile+retired" if retired else "Profile+reactivated") if ok \
            else "Profile+not+found"
        return self._redirect("{0}?ok={1}".format(self._self_url(), msg))

    def saved_profiles(self):
        return list_vendor_profiles(self._portal())

    def studio_audit(self):
        return get_import_studio_audit(self._portal(), limit=25)

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    def _self_url(self):
        return "{0}/@@pfas-import-studio".format(self.context.absolute_url())

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    # -- Template data -------------------------------------------------------

    def instruments(self):
        """List all Instruments for the instrument selector."""
        catalog = getToolByName(self.context, "senaite_catalog_setup")
        result = []
        for brain in catalog({"portal_type": "Instrument", "sort_on": "sortable_title"}):
            try:
                obj = brain.getObject()
                result.append({
                    "uid": obj.UID(),
                    "title": obj.Title(),
                    "profiles": _list_profiles(obj),
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

    def vendor_names(self):
        return [(k, v["vendor"]) for k, v in sorted(_VENDOR_COLUMN_MAP.items())]

    # -- Upload state (passed via hidden form fields after parse) ------------

    def upload_result_json(self):
        raw = self.request.form.get("upload_result_json", "null")
        # Escape chars that break XML/Chameleon parsing when injected into <script>
        return raw.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')

    # -- Phase 1: upload & detect -------------------------------------------

    def _handle_upload(self):
        f = self.request.form
        instrument_uid = f.get("instrument_uid", "").strip()
        upload = f.get("upload_file")
        # Zope wraps file uploads as FileUpload objects; an empty/missing
        # upload may still have a .read method but an empty filename.
        upload_filename = getattr(upload, "filename", "") or ""
        if not upload or not hasattr(upload, "read") or not upload_filename:
            url = "{0}?error=Please+select+a+file+before+uploading".format(self._self_url())
            return self._redirect(url)

        try:
            raw = upload.read()
            filename = upload_filename or "file.csv"
        except Exception as exc:
            url = "{0}?error=Upload+failed:+{1}".format(self._self_url(), str(exc)[:40])
            return self._redirect(url)

        # Decode
        try:
            text = raw.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            try:
                text = raw.decode("latin-1")
            except Exception:
                text = str(raw)

        lines = text.splitlines()
        if not lines:
            url = "{0}?error=File+is+empty".format(self._self_url())
            return self._redirect(url)

        # Detect software version (works on unicode lines)
        auto_version = _detect_software_version(lines)

        # Python 2.7's csv module requires byte strings for the file content
        # and the delimiter. unicode_literals makes "," into u"," which breaks
        # csv.reader with "TypeError: delimiter must be string, not unicode".
        text_bytes = text.encode("utf-8") if isinstance(text, unicode) else text

        # Parse headers (sniff delimiter)
        try:
            sample_bytes = b"\n".join(text_bytes.splitlines()[:5])
            dialect = csv.Sniffer().sniff(sample_bytes)
            delimiter = str(dialect.delimiter)  # str() = bytes in Python 2.7
        except Exception:
            delimiter = b","

        reader = csv.reader(StringIO.StringIO(text_bytes), delimiter=delimiter)
        headers = []
        preview_rows = []
        for i, row in enumerate(reader):
            if i == 0:
                headers = [h.decode("utf-8", "replace") if isinstance(h, bytes) else h
                           for h in row]
            else:
                preview_rows.append(
                    [c.decode("utf-8", "replace") if isinstance(c, bytes) else c
                     for c in row]
                )
            if i >= 4:
                break

        if not headers:
            url = "{0}?error=Could+not+parse+headers".format(self._self_url())
            return self._redirect(url)

        # Detect vendor
        vendor_key, confidence = _detect_vendor_py27(headers)

        # Build suggested mapping
        col_map = _suggest_mapping(headers, vendor_key)

        # Check for existing profile on this instrument
        existing_profile = None
        instrument_title = ""
        instrument_profiles = []
        if instrument_uid:
            catalog = getToolByName(self.context, "uid_catalog")
            brains = catalog(UID=instrument_uid)
            if brains:
                try:
                    instr = brains[0].getObject()
                    instrument_title = instr.Title() or ""
                    instrument_profiles = _list_profiles(instr)
                    # Try matching by version
                    if auto_version:
                        existing_profile = _load_profile(instr, auto_version)
                    # If not found, take the most recent
                    if not existing_profile and instrument_profiles:
                        existing_profile = _load_profile(
                            instr, instrument_profiles[-1]["version"])
                    if existing_profile:
                        col_map = existing_profile.get("map", col_map)
                        vendor_key = existing_profile.get("vendor_key", vendor_key)
                except Exception:
                    pass

        upload_result = {
            "filename": filename,
            "delimiter": delimiter,
            "headers": headers,
            "preview": preview_rows[:3],
            "vendor_key": vendor_key,
            "confidence": confidence,
            "auto_version": auto_version,
            "col_map": col_map,
            "instrument_uid": instrument_uid,
            "instrument_title": instrument_title,
            "instrument_profiles": instrument_profiles,
            "existing_profile": bool(existing_profile),
        }

        self.request.form["upload_result_json"] = json.dumps(upload_result)
        return self.template()

    # -- Phase 1b: load saved profile for editing (no file upload needed) ----

    def _handle_edit_profile(self):
        f = self.request.form
        instrument_uid = f.get("instrument_uid", "").strip()
        version = f.get("version", "").strip()
        if not instrument_uid or not version:
            url = "{0}?error=Missing+instrument+or+version".format(self._self_url())
            return self._redirect(url)
        catalog = getToolByName(self.context, "uid_catalog")
        brains = catalog(UID=instrument_uid)
        if not brains:
            url = "{0}?error=Instrument+not+found".format(self._self_url())
            return self._redirect(url)
        try:
            instr = brains[0].getObject()
        except Exception:
            url = "{0}?error=Could+not+load+instrument".format(self._self_url())
            return self._redirect(url)
        profile = _load_profile(instr, version)
        if not profile:
            url = "{0}?error=Profile+version+not+found".format(self._self_url())
            return self._redirect(url)

        col_map = profile.get("map", {})
        vendor_key = profile.get("vendor_key", "native")
        # Reconstruct headers from the saved mapping keys
        headers = list(col_map.keys())

        upload_result = {
            "filename": "Saved profile: {0}".format(version),
            "delimiter": ",",
            "headers": headers,
            "preview": [],
            "vendor_key": vendor_key,
            "confidence": 100,
            "auto_version": version,
            "col_map": col_map,
            "instrument_uid": instrument_uid,
            "instrument_title": instr.Title() or "",
            "instrument_profiles": _list_profiles(instr),
            "existing_profile": True,
            "edit_mode": True,
        }
        self.request.form["upload_result_json"] = json.dumps(upload_result)
        return self.template()

    # -- Phase 2: save profile -----------------------------------------------

    def _handle_save_profile(self):
        f = self.request.form
        instrument_uid = f.get("instrument_uid", "").strip()
        version = f.get("software_version", "").strip()
        vendor_key = f.get("vendor_key", "native").strip()
        calc_mode = f.get("calc_mode", "final").strip()
        notes = f.get("notes", "").strip()
        col_map_raw = f.get("col_map_json", "{}")
        try:
            col_map = json.loads(col_map_raw)
        except (ValueError, TypeError):
            col_map = {}

        if not instrument_uid:
            return self._redirect("{0}?error=No+instrument+selected".format(self._self_url()))
        if not version:
            return self._redirect("{0}?error=Software+version+is+required".format(self._self_url()))

        catalog = getToolByName(self.context, "uid_catalog")
        brains = catalog(UID=instrument_uid)
        if not brains:
            return self._redirect("{0}?error=Instrument+not+found".format(self._self_url()))
        try:
            instr = brains[0].getObject()
        except Exception:
            return self._redirect("{0}?error=Could+not+load+instrument".format(self._self_url()))

        _save_profile(instr, version, vendor_key, calc_mode, col_map, notes)

        # Also write to portal-level profiles store so the pipeline importer
        # can fetch this profile by vendor_key + version without a ZODB lookup.
        portal = self._portal()
        profile_data = {
            "vendor": _VENDOR_COLUMN_MAP.get(vendor_key, {}).get("vendor", vendor_key),
            "vendor_key": vendor_key,
            "calc_mode": calc_mode,
            "map": col_map,
            "notes": notes,
        }
        save_vendor_profile(portal, vendor_key, version, profile_data)

        url = "{0}?instrument_uid={1}&ok=Profile+saved+for+{2}".format(
            self._self_url(), instrument_uid, version.replace(" ", "+"))
        return self._redirect(url)
