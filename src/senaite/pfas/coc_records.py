# -*- coding: utf-8 -*-
"""Chain of custody records.

The LIMS issues a CoC number when a sampler starts a submission or the lab
prints a kit CoC; every sample made under it carries the number (sample
field CoCNumber). One record per number holds what belongs to the shipment,
not to any one sample:

    {"number", "client_uid", "client", "origin": "digital" | "paper",
     "status": "open" | "submitted" | "received",
     "created_by", "created_at", "project", "project_number", "sampler",
     "carrier", "tracking", "seals",
     "rows":      [sample rows while the CoC is open, before samples exist],
     "samples":   [uids of the samples made from it],
     "transfers": [{"relinquished_by", "relinquished_at", "received_by", "received_at"}],
     "receipt":   {"received_by", "received_at", "thermometer", "temperatures": [...],
                   "seals_intact", "labels_legible", "holding_time_ok",
                   "compliant", "note", "flags": [...]},
     "scan":      {"filename", "path", "by", "at"}        (paper CoC)
     "transcribed": {"by", "at"}                         (paper CoC)
     "log":       [{"at", "by", "what", "before", "after", "reason"}]}

Who may change it: the client contact edits their own CoC
until the lab receives it, every edit logged; after receipt only lab staff,
with a reason. Pure helpers first; storage imports Plone lazily.
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import re

INDEX_KEY = "senaite.pfas.coc.index"
RECORD_PREFIX = "senaite.pfas.coc.r."

OPEN, SUBMITTED, RECEIVED = u"open", u"submitted", u"received"
DIGITAL, PAPER = u"digital", u"paper"

# the field QC types a sample can be (NMED SOP-01-ECP-2025: field reagent
# blank per event, field duplicate; trip blank where a project asks for one)
FIELD_QC_TYPES = (u"Field reagent blank", u"Field duplicate", u"Trip blank")
# each one's QC code, which an EDD profile translates into its format's code
FIELD_QC_CODES = {u"Field reagent blank": "FB", u"Field duplicate": "FD", u"Trip blank": "TB"}

_NUMBER = re.compile(r"^COC-(\d{4})-(\d{4,})$")


def next_number(existing, year):
    """COC-<year>-<seq>, the sequence continuing within the year."""
    seq = 0
    for n in existing or []:
        m = _NUMBER.match(n or u"")
        if m and int(m.group(1)) == int(year):
            seq = max(seq, int(m.group(2)))
    return u"COC-%04d-%04d" % (int(year), seq + 1)


def new_record(number, client_uid, client, origin, by, at):
    return {"number": number, "client_uid": client_uid or u"", "client": client or u"",
            "origin": origin if origin in (DIGITAL, PAPER) else DIGITAL, "status": OPEN,
            "created_by": by, "created_at": at, "project": u"", "project_number": u"",
            "sampler": u"", "carrier": u"", "tracking": u"", "seals": u"",
            "rows": [], "samples": [], "transfers": [], "receipt": {}, "scan": {},
            "transcribed": {}, "log": []}


def may_edit(record, staff, own_client):
    """(ok, why). A client edits their own CoC until it is received; lab
    staff edit at any time, a received CoC only with a reason (asked by the
    caller)."""
    status = (record or {}).get("status") or OPEN
    if staff:
        return True, u""
    if not own_client:
        return False, u"This CoC belongs to another client."
    if status == RECEIVED:
        return False, u"The laboratory has received this CoC; ask the laboratory to correct it."
    return True, u""


def log_changes(record, before, after, by, at, reason=u""):
    """Append one log entry per changed key (`before` / `after` flat dicts
    of what was edited). Returns the entries added."""
    added = []
    for k in sorted(set(before or {}) | set(after or {})):
        b, a = (before or {}).get(k), (after or {}).get(k)
        if b != a:
            added.append({"at": at, "by": by, "what": k, "before": b, "after": a,
                          "reason": reason or u""})
    record.setdefault("log", []).extend(added)
    return added


def receipt_problems(record, receipt, extra_flags=()):
    """(blocking, flags) for completing receipt.

    Blocking -- receipt cannot complete: no receipt date, no temperature,
    compliance not answered, a non-compliance with no note, a paper CoC
    with no scan. Flags -- received, but flagged on the samples, in Data
    Review and on the certificate: each answer that is not compliant."""
    receipt, record = receipt or {}, record or {}
    blocking, flags = [], []
    if not (receipt.get("received_at") or u"").strip():
        blocking.append(u"the receipt date and time")
    temps = [t for t in receipt.get("temperatures") or [] if u"%s" % t not in (u"", u"None")]
    if not temps:
        blocking.append(u"at least one temperature on receipt")
    if receipt.get("compliant") not in (True, False):
        blocking.append(u"whether the shipment is compliant")
    for key, what in (("seals_intact", u"custody seals not intact"),
                      ("labels_legible", u"labels not legible"),
                      ("holding_time_ok", u"holding time exceeded")):
        if receipt.get(key) is False:
            flags.append(what)
    flags.extend(extra_flags or ())            # e.g. temperatures out of range
    if receipt.get("compliant") is False:
        flags.append(u"received not compliant")
    if flags and not (receipt.get("note") or u"").strip():
        blocking.append(u"a note explaining: " + u"; ".join(flags))
    if record.get("origin") == PAPER and not (record.get("scan") or {}).get("path"):
        blocking.append(u"the scan of the paper CoC")
    return blocking, flags


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def judge_temperatures(readings, on_ice):
    """(flags, not_judged) for receipt temperatures against each sample's
    METHOD range (method profile receipt_temperature).

    `readings`: [{"sample_id", "observed", "corrected", "range": {"min_c",
    "max_c", "same_day_on_ice"} or None, "same_day": bool}]. The corrected
    value is judged (the observed one when no correction applies). With the
    method's same-day switch on, a sample received the day it was collected
    and on ice is not flagged for being ABOVE the maximum (never below the
    minimum). A sample whose method sets no range is listed as not judged."""
    flags, not_judged = [], []
    for r in readings or []:
        rng = r.get("range") or {}
        lo, hi = _num(rng.get("min_c")), _num(rng.get("max_c"))
        value = _num(r.get("corrected")) if _num(r.get("corrected")) is not None else _num(r.get("observed"))
        sid = r.get("sample_id") or u""
        if lo is None and hi is None:
            not_judged.append(u"%s: no receipt range on its method" % sid)
            continue
        if value is None:
            not_judged.append(u"%s: no temperature" % sid)
            continue
        if lo is not None and hi is not None and lo > hi:
            not_judged.append(u"%s: its method's receipt range is reversed (%g > %g)" % (sid, lo, hi))
            continue
        span = u"%s to %s \u00b0C" % (u"%g" % lo if lo is not None else u"\u2013",
                                       u"%g" % hi if hi is not None else u"\u2013")
        if lo is not None and value < lo:
            flags.append(u"temperature out of range: %s %g \u00b0C (allowed %s)" % (sid, value, span))
        elif hi is not None and value > hi:
            if rng.get("same_day_on_ice") and r.get("same_day") and on_ice:
                continue        # collected today and cooling on ice: the method allows it
            flags.append(u"temperature out of range: %s %g \u00b0C (allowed %s)" % (sid, value, span))
    return flags, not_judged


def transcription_line(record):
    """The printed CoC's note for a paper CoC, or ""."""
    t = (record or {}).get("transcribed") or {}
    if (record or {}).get("origin") != PAPER or not t.get("by"):
        return u""
    return (u"Transcribed from paper CoC %s by %s on %s. Paper original retained."
            % (record.get("number"), t["by"], (t.get("at") or u"")[:10]))


# ── storage (Plone): one annotation per record, and an index ──────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def numbers(portal):
    try:
        return json.loads(_ann(portal).get(INDEX_KEY) or u"[]")
    except (ValueError, TypeError):
        return []


def load(portal, number):
    raw = _ann(portal).get(RECORD_PREFIX + (number or u""))
    try:
        return json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None


def save(portal, record):
    ann = _ann(portal)
    ann[RECORD_PREFIX + record["number"]] = json.dumps(record)
    idx = numbers(portal)
    if record["number"] not in idx:
        idx.append(record["number"])
        ann[INDEX_KEY] = json.dumps(idx)


def issue(portal, client_uid, client, origin, by, at):
    """A new record under the next number; saved."""
    rec = new_record(next_number(numbers(portal), at[:4]), client_uid, client, origin, by, at)
    save(portal, rec)
    return rec


def for_client(portal, client_uid):
    out = []
    for n in numbers(portal):
        r = load(portal, n)
        if r and (client_uid is None or r.get("client_uid") == client_uid):
            out.append(r)
    return out
