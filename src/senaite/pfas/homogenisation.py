# -*- coding: utf-8 -*-
"""Homogenisation and composites.

Who owns what (one owner per fact):

    the lab's list of methods    portal annotation METHODS_KEY
                                 [{"id", "title", "unit_required", "active"}]
    a matrix's default method    annotation DEFAULT_KEY on the core Sample Type
    what a sample requests       the sample's fields (extenders/sample.py):
                                 HomogenisationMethod, CompositeUnits,
                                 CompositeDescription; core's Composite
    what was done                annotation RECORD_KEY on the sample: records
                                 appended, never edited (H-P3)

The method "none" (not homogenised: a liquid mixed by inversion, a sample
taken as it is) is always offered; the lab cannot remove it. A sample whose
method is blank predates this record and is treated as not requested.

Pure helpers first; the storage helpers import Plone lazily. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import re

METHODS_KEY = "senaite.pfas.homogenisation_methods"
DEFAULT_KEY = "senaite.pfas.homogenisation_default"
RECORD_KEY = "senaite.pfas.homogenisation"

NONE_ID = u"none"
NONE_TITLE = u"Not homogenised"

# offered to type over on the setup page, never saved by itself
STARTER_TITLES = (u"IKA mill", u"Cryogrinder")

FIELD_METHOD = "HomogenisationMethod"
FIELD_UNITS = "CompositeUnits"
FIELD_DESCRIPTION = "CompositeDescription"


def slug(title, taken):
    """A stable id for a new method: never reused, never the reserved one."""
    base = re.sub(r"[^a-z0-9]+", u"-", (title or u"").lower()).strip(u"-") or u"method"
    sid, n = base, 2
    while sid in taken or sid == NONE_ID:
        sid, n = u"%s-%d" % (base, n), n + 1
    return sid


def parse_methods(rows, existing):
    """The list as saved from the setup page. `rows` = [{"id", "title",
    "unit_required", "active"}] in page order; a row keeps its id (a rename
    changes only the title, so every sample naming it still does); a row
    with no title and no id is ignored. Returns (methods, errors)."""
    known = dict((m["id"], m) for m in existing or [] if m.get("id"))
    taken = set(known) | set([NONE_ID])
    out, errors, titles = [], [], set()
    for r in rows or []:
        title = (r.get("title") or u"").strip()
        mid = (r.get("id") or u"").strip()
        if not title and not mid:
            continue
        if not title:
            errors.append(u"A method needs a name (it can be retired instead).")
            continue
        if title.lower() in titles or title.lower() == NONE_TITLE.lower():
            errors.append(u"Two methods are named “%s”." % title)
            continue
        titles.add(title.lower())
        if mid not in known:
            mid = slug(title, taken)
            taken.add(mid)
        out.append({"id": mid, "title": title,
                    "unit_required": bool(r.get("unit_required")),
                    "active": bool(r.get("active", True))})
    # a method the page did not send is kept, retired: samples name it
    sent = set(m["id"] for m in out)
    for mid, m in known.items():
        if mid not in sent and mid != NONE_ID:
            out.append(dict(m, active=False))
    return out, errors


def choices(methods, current=u""):
    """[(id, title)] for a picker: "none" first, then the active methods,
    and the current value even when retired (so it is never lost)."""
    out = [(NONE_ID, NONE_TITLE)]
    for m in methods or []:
        if m.get("id") and m["id"] != NONE_ID and (m.get("active", True) or m["id"] == current):
            out.append((m["id"], m.get("title") or m["id"]))
    return out


def title_of(methods, mid):
    if mid == NONE_ID:
        return NONE_TITLE
    for m in methods or []:
        if m.get("id") == mid:
            return m.get("title") or mid
    return mid or u""


def unit_required(methods, mid):
    for m in methods or []:
        if m.get("id") == mid:
            return bool(m.get("unit_required"))
    return False


def requested(sample_value, type_default):
    """The method a sample asks for: its own value, else its matrix's
    default, else "" (not requested)."""
    return (sample_value or u"").strip() or (type_default or u"").strip()


def composite_problems(composite, units, description):
    """What the sample record lacks for a composite."""
    if not composite:
        return []
    out = []
    try:
        n = int(units)
    except (TypeError, ValueError):
        n = 0
    if n < 2:
        out.append(u"composite: say how many units were combined (2 or more)")
    if not (description or u"").strip():
        out.append(u"composite: say what was combined")
    return out


def composite_line(composite, units, description):
    """The certificate's line for a composite sample (H-P5), or ""."""
    if not composite:
        return u""
    try:
        n = int(units)
    except (TypeError, ValueError):
        n = 0
    head = u"Composite of %d units" % n if n >= 2 else u"Composite"
    desc = (description or u"").strip()
    return u"%s: %s" % (head, desc) if desc else head


def record_warnings(req, method, unit_name, cleaned, units_combined, methods):
    """What a homogenisation record must explain in a note (H-P3, DB4
    pattern): a method other than the one requested, a method that names a
    homogeniser unit with none chosen, a unit not confirmed cleaned, a
    composite whose count differs from the sample's. `req` = sample_request.
    """
    out = []
    want = (req or {}).get("method") or u""
    if want and method != want:
        out.append(u"homogenised by %s, %s requested"
                   % (title_of(methods, method), title_of(methods, want)))
    if method != NONE_ID and unit_required(methods, method):
        if not unit_name:
            out.append(u"no homogeniser unit chosen")
        elif not cleaned:
            out.append(u"%s not confirmed cleaned" % unit_name)
    if (req or {}).get("composite"):
        try:
            asked = int(req.get("units"))
        except (TypeError, ValueError):
            asked = None
        try:
            got = int(units_combined)
        except (TypeError, ValueError):
            got = None
        if got is None:
            out.append(u"composite: units combined not confirmed")
        elif asked is not None and got != asked:
            out.append(u"composite: %d units combined, %d requested" % (got, asked))
    return out


def latest(records):
    """The record in force: the last one (a correction is a later record)."""
    return (records or [None])[-1]


def awaiting(req, records):
    """True when a sample still needs homogenising: a method other than
    "none" is requested and nothing is recorded."""
    return bool((req or {}).get("method")) and req["method"] != NONE_ID and not records


def stage_rows(samples, methods):
    """What the processing stage (FM-ENV-004) confirms per sample (H-P4):
    `samples` = [(sample_id, request, records)]. Each row carries the
    request, the record in force and `warning` -- a requested method with
    no record, which needs a note at the stage."""
    out = []
    for sid, req, records in samples or []:
        req = req or {}
        rec = latest(records) or {}
        want = req.get("method") or u""
        warning = u""
        if awaiting(req, records):
            warning = u"%s: no homogenisation recorded (%s requested)" % (sid, title_of(methods, want))
        out.append({
            "sample_id": sid,
            "requested": title_of(methods, want) if want else u"",
            "composite": composite_line(req.get("composite"), req.get("units"), req.get("description")),
            "method": title_of(methods, rec.get("method")) if rec else u"",
            "unit": rec.get("unit_name") or u"",
            "units_combined": rec.get("units_combined"),
            "by": rec.get("by") or u"", "at": (rec.get("at") or u"")[:16].replace(u"T", u" "),
            "note": rec.get("note") or u"",
            "warning": warning})
    return out


# ── storage (Plone) ───────────────────────────────────────────────────────

def _ann(obj):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(obj)


def load_methods(portal):
    try:
        return json.loads(_ann(portal).get(METHODS_KEY) or u"[]")
    except (ValueError, TypeError):
        return []


def save_methods(portal, methods):
    _ann(portal)[METHODS_KEY] = json.dumps(methods)


def type_default(sample_type):
    if sample_type is None:
        return u""
    return _ann(sample_type).get(DEFAULT_KEY) or u""


def set_type_default(sample_type, mid):
    ann = _ann(sample_type)
    if mid:
        ann[DEFAULT_KEY] = mid
    elif DEFAULT_KEY in ann:
        del ann[DEFAULT_KEY]


def field_value(sample, name):
    field = sample.getField(name) if hasattr(sample, "getField") else None
    return field.get(sample) if field is not None else None


def sample_request(sample):
    """{"method", "composite", "units", "description", "problems"} as the
    sample states it; "method" falls back to its matrix's default."""
    st = sample.getSampleType() if hasattr(sample, "getSampleType") else None
    composite = bool(field_value(sample, "Composite"))
    units = field_value(sample, FIELD_UNITS)
    desc = field_value(sample, FIELD_DESCRIPTION) or u""
    return {"method": requested(field_value(sample, FIELD_METHOD), type_default(st)),
            "composite": composite, "units": units, "description": desc,
            "problems": composite_problems(composite, units, desc)}


def on_sample_initialized(sample, event):
    """A new sample with no method takes its matrix's default, frozen then:
    a later change of the default does not rewrite what was requested."""
    try:
        field = sample.getField(FIELD_METHOD)
        if field is None or (field.get(sample) or u"").strip():
            return
        mid = type_default(sample.getSampleType())
        if mid:
            field.set(sample, mid)
    except Exception:                                       # noqa: BLE001
        import logging
        logging.getLogger("senaite.pfas.homogenisation").warning(
            "homogenisation default not set", exc_info=True)


def load_records(sample):
    try:
        return json.loads(_ann(sample).get(RECORD_KEY) or u"[]")
    except (ValueError, TypeError):
        return []


def append_record(sample, record):
    """Records are appended, never edited: a correction is a later record
    that says why (the earlier one is kept and shown)."""
    records = load_records(sample) + [record]
    _ann(sample)[RECORD_KEY] = json.dumps(records)
    return records
