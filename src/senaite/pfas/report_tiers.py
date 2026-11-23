# -*- coding: utf-8 -*-
"""Report tiers: the catalogue of what a client can order with a report.

A tier has an id (T followed by a number), a name, a one-line description
and an ordered list of parts. The parts are the fixed set the code can
produce (PARTS); a QC Review part names the sections of the designed QC
Review document it draws. Pure: no Plone, Python 2.7 and 3.

    tier = {"id", "name", "description", "parts": [{"key", "scope"?}]}
"""
from __future__ import absolute_import, unicode_literals

import copy
import json
import logging
import re

logger = logging.getLogger("senaite.pfas")

CATALOGUE_KEY = "senaite.pfas.report_tiers"

PARTS = [
    ("certificate", "Certificate of Analysis", ()),
    ("contents", "Contents", ()),
    ("qc_identity", "QC Review: run identity and criteria applied",
     ("identity", "criteria")),
    ("qc_gates", "QC Review: release gates", ("gates",)),
    ("qc_summary", "QC Review: QC summary and spike QC",
     ("qc_summary", "spike_qc")),
    ("qc_calibration", "QC Review: calibration curves", ("calibrations",)),
    ("qc_traceability", "QC Review: reagent and standard traceability",
     ("traceability",)),
    ("qc_run_plan", "QC Review: run against plan", ("run_vs_plan",)),
    ("qc_deviations",
     "QC Review: publication history, deviations and exceptions",
     ("publications", "deviations", "exceptions")),
    ("qc_injections", "QC Review: every measurement", ("injections",)),
    ("chromatograms", "Chromatograms", ()),
    ("batch_record", "Batch record", ()),
    ("instrument_report", "Instrument report", ()),
]

SCOPES = (("sample", "Sample analytes"), ("sample_qc", "Sample and QC"),
          ("run", "Whole run"))

_KEYS = [k for k, _l, _s in PARTS]
_SCOPE_KEYS = [k for k, _l in SCOPES]
_ID = re.compile(r"^T[0-9]+$")


def _parts(keys, scope="run"):
    return [dict(key=k, scope=scope) if k == "chromatograms" else {"key": k}
            for k in keys]


_T2 = ["certificate", "contents", "qc_identity", "qc_gates", "qc_summary",
       "qc_traceability", "qc_deviations"]
_T3_QC = ["certificate", "contents", "qc_identity", "qc_gates", "qc_summary",
          "qc_calibration", "qc_traceability", "qc_run_plan", "qc_deviations",
          "qc_injections"]
_T3 = _T3_QC + ["batch_record"]

DEFAULTS = [
    {"id": "T1", "name": "Results",
     "description": "The certificate of analysis.",
     "parts": _parts(["certificate"])},
    {"id": "T2", "name": "Results and QC",
     "description": "The certificate with the QC review of the run.",
     "parts": _parts(_T2)},
    {"id": "T3", "name": "Results, QC and calibration",
     "description": "The certificate with the QC review, the calibration "
                    "and the batch record.",
     "parts": _parts(_T3)},
    {"id": "T4", "name": "Full data package",
     "description": "Everything in T3 with the chromatograms and the "
                    "instrument report.",
     # in the catalogue's order: the chromatograms come before the record
     "parts": _parts(_T3_QC + ["chromatograms", "batch_record",
                               "instrument_report"])},
]

# a part key a saved catalogue, an issued revision or a queued job may still
# name, and the part it is now: every reader maps it, so the old key prints
# as the part it became
RENAMED_PARTS = {"extraction_log": "batch_record"}


def part_key(key):
    """The part a key names now."""
    return RENAMED_PARTS.get(key, key)


def rename_parts(parts):
    """(parts, dropped): each renamed part under its new key, in its own
    place; a renamed part whose new key the list already names, or an
    earlier part already took, is dropped (listed in `dropped`), never kept
    twice. The input is not changed."""
    keys = [p.get("key") for p in parts or []]
    out, dropped = [], []
    for p in parts or []:
        key = p.get("key")
        if key in RENAMED_PARTS:
            if part_key(key) in keys or part_key(key) in [o.get("key") for o in out]:
                dropped.append(key)
                continue
            p = dict(p, key=part_key(key))
        out.append(copy.deepcopy(p))
    return out, dropped


def carry_over_parts(catalogue):
    """(catalogue, changed): every tier's parts through rename_parts, the
    tiers and their parts in their own order. The input is not changed; a
    catalogue with nothing renamed comes back as it was."""
    out = copy.deepcopy(catalogue or [])
    changed = False
    for t in out:
        parts = t.get("parts") or []
        if not [p for p in parts if p.get("key") in RENAMED_PARTS]:
            continue
        t["parts"], dropped = rename_parts(parts)
        for key in dropped:
            logger.info("tier %s names both %s and %s: %s dropped",
                        t.get("id"), key, part_key(key), key)
        changed = True
    return out, changed


def _keys(t):
    return [p.get("key") for p in t.get("parts") or []]


def parts_beyond_certificate(t):
    """The parts after the certificate, the contents page excluded."""
    return [p for p in (t.get("parts") or [])
            if p.get("key") not in ("certificate", "contents")]


def needs_package(t):
    return bool(parts_beyond_certificate(t))


def problems(catalogue):
    """The rule breaches of a catalogue, one message each, in catalogue
    order and without repeats."""
    out = []

    def add(msg):
        if msg not in out:
            out.append(msg)

    if not catalogue:
        return ["At least one tier"]
    seen_ids = set()
    seen_names = set()
    for t in catalogue:
        tid = t.get("id") or ""
        name = (t.get("name") or "").strip()
        if not _ID.match(tid):
            add("Tier ids must be T followed by a number: %s" % tid)
        elif tid in seen_ids:
            add("Two tiers have the id %s" % tid)
        seen_ids.add(tid)
        if not name:
            add("Tier %s has no name" % tid)
        elif name in seen_names:
            add("Two tiers are named %s" % name)
        seen_names.add(name)
        keys = _keys(t)
        if not keys or keys[0] != "certificate":
            add("Tier %s must start with the certificate" % tid)
        else:
            beyond = parts_beyond_certificate(t)
            if beyond and "contents" not in keys:
                add("Tier %s needs a contents page" % tid)
            if not beyond and "contents" in keys:
                add("Tier %s has a contents page and nothing after the "
                    "certificate" % tid)
        for p in t.get("parts") or []:
            if p.get("key") not in _KEYS:
                add("Unknown part %s in tier %s" % (p.get("key"), tid))
            elif (p.get("key") == "chromatograms"
                  and p.get("scope") not in _SCOPE_KEYS):
                add("Tier %s: chromatogram scope must be sample, sample_qc "
                    "or run" % tid)
    return out


def tier(catalogue, tier_id):
    for t in catalogue or []:
        if t.get("id") == tier_id:
            return t
    return None


def qc_sections_for(t):
    """The QC Review section keys the tier's parts draw, in PARTS order."""
    keys = set(_keys(t))
    out = []
    for key, _label, secs in PARTS:
        if key in keys:
            for s in secs:
                if s not in out:
                    out.append(s)
    return out


def label(catalogue, tier_id):
    t = tier(catalogue, tier_id)
    if not t:
        return ""
    return ("%s %s" % (t["id"], t.get("name") or "")).strip()


def client_defaults(clients, settings_of, catalogue):
    """[{"client", "tier_id", "tier", "set"}] for each client, by name: the
    tier its samples report at when they have none of their own (T1 until
    one is saved; "set" says whether one was), and that tier's label in the
    catalogue ("" when the catalogue has none such). `clients` are
    (name, client) pairs, `settings_of(client)` its reporting settings."""
    out = []
    for name, client in sorted(clients, key=lambda c: (c[0] or u"").lower()):
        saved = _text((settings_of(client) or {}).get("report_tier")).strip()
        tier_id = saved or DEFAULT_TIER
        out.append({"client": name, "tier_id": tier_id, "tier": label(catalogue, tier_id),
                    "set": bool(saved), "obj": client})
    return out


FIELD = "ReportTier"
DEFAULT_TIER = "T1"
# a sample in one of these states keeps the tier it has: what was published
# with it, or what it would have been, is no longer changed
LOCKED_STATES = ("published", "invalid", "cancelled", "rejected")


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value or ""


def _client_settings(sample):
    from senaite.pfas import edd_store
    client = sample.getClient()
    return edd_store.get_client_settings(client) if client is not None else {}


def prefill_value(current, client_settings):
    """The tier a new sample is given: its client's default when the sample
    has none of its own, else None (what it was registered with stands)."""
    if _text(current).strip():
        return None
    return _text((client_settings or {}).get("report_tier")).strip() or None


def on_sample_initialized(sample, event):
    """A new sample with no tier takes its client's default, frozen then: a
    later change of the client's default does not rewrite it."""
    try:
        field = sample.getField(FIELD)
        if field is None:
            return
        value = prefill_value(field.get(sample), _client_settings(sample))
        if value:
            field.set(sample, value)
    except Exception:                                       # noqa: BLE001
        logger.warning("report tier default not set", exc_info=True)


def tier_id_of(sample, portal, _settings=None):
    """The tier a sample reports at: its own ReportTier, else its client's
    default, else T1. A new sample is given its client's default when it is
    registered; one still blank (registered before, or the client's default
    could not be read) takes the client's default when it is read."""
    field = sample.getField(FIELD) if hasattr(sample, "getField") else None
    own = _text(field.get(sample) if field is not None else "").strip()
    if own:
        return own
    cfg = (_settings or _client_settings)(sample) or {}
    return _text(cfg.get("report_tier")).strip() or DEFAULT_TIER


def resolve(sample, portal):
    """(tier or None, tier id, catalogue, rev) of the issued catalogue: None
    when the id the sample resolves to is not in it."""
    from senaite.pfas import report_templates
    catalogue, rev = report_templates.issued_tiers(portal)
    tier_id = tier_id_of(sample, portal)
    return tier(catalogue, tier_id), tier_id, catalogue, rev


def from_form(form):
    """The catalogue posted by the editor: rows tier_id.N, tier_name.N,
    tier_desc.N, part_<key>.N ("on") and chrom_scope.N, in index order;
    a row with a blank id is dropped; parts follow PARTS order."""
    rows = set()
    for k in form:
        m = re.match(r"^tier_id\.([0-9]+)$", k)
        if m:
            rows.add(int(m.group(1)))
    out = []
    for n in sorted(rows):
        tid = (form.get("tier_id.%d" % n) or "").strip()
        if not tid:
            continue
        parts = []
        for key in _KEYS:
            if form.get("part_%s.%d" % (key, n)) != "on":
                continue
            if key == "chromatograms":
                parts.append({"key": key, "scope":
                              form.get("chrom_scope.%d" % n) or "sample"})
            else:
                parts.append({"key": key})
        out.append({"id": tid,
                    "name": (form.get("tier_name.%d" % n) or "").strip(),
                    "description": (form.get("tier_desc.%d" % n) or "").strip(),
                    "parts": parts})
    return out


def saved_catalogue(portal):
    """The catalogue the lab saved, or None when it never saved one (or the
    stored value cannot be read)."""
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(portal).get(CATALOGUE_KEY)
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("saved_catalogue: %s", exc)
        return None
    if not isinstance(found, list):
        logger.warning("saved_catalogue: stored value is not a list")
        return None
    return found


def get_catalogue(portal):
    """The saved catalogue, else the shipped one: always a copy."""
    saved = saved_catalogue(portal)
    return copy.deepcopy(DEFAULTS if saved is None else saved)


def save_catalogue(portal, catalogue):
    """Persist `catalogue`; returns its problems and writes nothing when
    there are any."""
    found = problems(catalogue)
    if found:
        return found
    # the change history is strict: when its entry cannot be prepared the
    # save does not happen
    from senaite.pfas import config_history
    config_history.track(portal, 'report_tiers', 'lab',
                         lambda: get_catalogue(portal), label=u"Certificate tiers")
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(portal)[CATALOGUE_KEY] = json.dumps(catalogue)
    return []


def _open_samples(portal):
    """(id, tier id, review state) of every sample not yet issued."""
    from Products.CMFCore.utils import getToolByName
    out = []
    for brain in getToolByName(portal, "senaite_catalog_sample")():
        state = brain.review_state
        if state in LOCKED_STATES:
            continue
        sample = brain.getObject()
        field = sample.getField(FIELD) if hasattr(sample, "getField") else None
        found = _text(field.get(sample) if field is not None else "")
        out.append((sample.getId(), found.strip(), state))
    return out


def in_use(portal, tier_id, _samples=None):
    """Who still names `tier_id`: the clients whose default it is and the
    samples not yet issued that carry it, as u"Client <name>" and
    u"Sample <id>"."""
    from senaite.pfas import edd_store
    out = []
    folder = portal.get("clients")
    for client in (folder.objectValues() if folder is not None else []):
        if getattr(client, "portal_type", None) != "Client":
            continue
        if edd_store.get_client_settings(client).get("report_tier") == tier_id:
            out.append(u"Client %s" % _text(client.Title()))
    for sid, found, _state in (_open_samples(portal) if _samples is None else _samples):
        if found == tier_id:
            out.append(u"Sample %s" % _text(sid))
    return out
