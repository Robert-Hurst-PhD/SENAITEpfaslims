# -*- coding: utf-8 -*-
"""Chain of custody records.

The LIMS issues a CoC number when a sampler starts a submission or the lab
prints a kit CoC; every sample made under it carries the number (sample
field CoCNumber). One record per number holds what belongs to the shipment,
not to any one sample:

    {"number", "client_uid", "client", "origin": "digital" | "paper",
     "status": "open" | "submitted" | "received",
     "created_by", "created_at", "project", "project_number", "sampler",
     "carrier", "tracking", "seals" (a record made before custody seals
     were dropped keeps its answer),
     "rows":      [sample rows while the CoC is open, before samples exist],
     "samples":   [uids of the samples made from it],
     "transfers": [{"relinquished_by", "relinquished_at", "received_by", "received_at"}],
     "receipt":   {"received_by", "received_at", "thermometer", "temperatures": [...],
                   "labels_legible", "compliant", "on_ice" and "holding_time_ok"
                   where asked (asked_checks), "seals_intact" on a receipt stored
                   when it was asked, "note", "flags": [...],
                   "corrections": [signed corrections of the receipt date]},
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
# the word a CoC's status reads as on the page and in print
STATUS_LABELS = {OPEN: u"Open", SUBMITTED: u"Submitted", RECEIVED: u"Received"}
DIGITAL, PAPER = u"digital", u"paper"

# the field QC types a sample can be (NMED SOP-01-ECP-2025: field reagent
# blank per event, field duplicate; trip blank where a project asks for one)
FIELD_QC_TYPES = (u"Field reagent blank", u"Field duplicate", u"Trip blank")
# each one's QC code, which an EDD profile translates into its format's code
FIELD_QC_CODES = {u"Field reagent blank": "FB", u"Field duplicate": "FD", u"Trip blank": "TB"}
# each one's role for the pipeline worker: FRB and TB are judged as blanks
# (each against its own limit), FD is left out of a CCV count that counts
# field samples only
WORKER_FIELD_QC = {u"Field reagent blank": "FRB", u"Field duplicate": "FD", u"Trip blank": "TB"}

_NUMBER = re.compile(r"^COC-(\d{4})-(\d{4,})$")

# A receipt check is answered Yes or No: True or False in the receipt, None
# while unanswered. Only True passes where a check must pass, and only False
# raises a flag. A receipt stored when checks were also answered N/A keeps
# CHECK_NA, which neither passes nor flags.
CHECK_NA = u"N/A"
_CHECK = {u"yes": True, u"no": False, u"na": CHECK_NA}

# What a receipt asks. Labels legible and compliant overall are asked of
# every receipt; the temperatures and received on ice only where a sample's
# method sets a receipt temperature range; within holding time only where a
# sample's method sets a holding time for its matrix. Custody seals are not
# asked: a receipt stored when they were keeps its answer, read as stored.
# A check that is not asked is absent from the receipt.
TEMPERATURE = u"temperature"
ALWAYS_ASKED = (u"labels_legible", u"compliant")
# what a receipt stored before the checks were scoped was asked
ASKED_BEFORE = frozenset((TEMPERATURE, u"on_ice", u"seals_intact", u"labels_legible",
                          u"holding_time_ok", u"compliant"))


def check_answer(posted, na=True):
    """The stored answer for what a Yes / No control posted; N/A only where
    `na` (a stored N/A is read, never asked again): unanswered otherwise."""
    answer = _CHECK.get((u"%s" % (posted or u"")).strip().lower())
    return None if answer == CHECK_NA and not na else answer


def asked_checks(samples):
    """The checks a receipt asks, as a frozenset of receipt keys (and
    TEMPERATURE when temperatures are taken). `samples`: one dict per
    sample, "temperature" true when its method sets a receipt temperature
    range, "holding" true when its method sets a holding time for its
    matrix."""
    out = set(ALWAYS_ASKED)
    if any(s.get("temperature") for s in samples or []):
        out.update((TEMPERATURE, u"on_ice"))
    if any(s.get("holding") for s in samples or []):
        out.add(u"holding_time_ok")
    return frozenset(out)


def range_is_set(rng):
    """A method's receipt temperature range sets a minimum or a maximum."""
    rng = rng or {}
    return any(_num(rng.get(k)) is not None for k in ("min_c", "max_c"))


def stored_checks(records):
    """What the stored receipts of these CoC records say about two checks
    that are not asked of every receipt, for a page that shows them:
    {"seals_intact": True when any receipt holds an answer to it,
     "seals_word": those answers in one word -- No when any is No, else Yes
                   when any is Yes, else N/A or "" (unanswered),
     "holding_time_ok": True when any receipt was asked it,
     "holding_declared": every receipt asked it says Yes}.
    A receipt that holds no answer was not asked; one stored as N/A was
    answered not applicable, which counts as not asked."""
    receipts = [(r or {}).get("receipt") or {} for r in records or [] if r]
    held = [x for x in receipts if "holding_time_ok" in x and x.get("holding_time_ok") != CHECK_NA]
    seals = [x.get("seals_intact") for x in receipts if "seals_intact" in x]
    word = (u"No" if False in seals else u"Yes" if True in seals
            else CHECK_NA if CHECK_NA in seals else u"")
    return {"seals_intact": bool(seals), "seals_word": word,
            "holding_time_ok": bool(held),
            "holding_declared": all(x.get("holding_time_ok") is True for x in held)}


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
            "sampler": u"", "carrier": u"", "tracking": u"",
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


def receipt_problems(record, receipt, extra_flags=(), asked=None):
    """(blocking, flags) for completing receipt.

    Blocking -- receipt cannot complete: no receipt date, no temperature
    where temperatures are asked, compliance not answered, within holding
    time not answered where it is asked, a non-compliance with no note, a
    paper CoC with no scan. Flags -- received, but flagged on the samples,
    in Data Review and on the certificate: each answer that is not
    compliant. `asked` (asked_checks) None: everything a receipt asked
    before the checks were scoped, holding time unrequired."""
    receipt, record = receipt or {}, record or {}
    blocking, flags = [], []
    if not (receipt.get("received_at") or u"").strip():
        blocking.append(u"the receipt date and time")
    temps = [t for t in receipt.get("temperatures") or [] if u"%s" % t not in (u"", u"None")]
    if not temps and TEMPERATURE in (ASKED_BEFORE if asked is None else asked):
        blocking.append(u"at least one temperature on receipt")
    if receipt.get("compliant") not in (True, False):
        blocking.append(u"whether the shipment is compliant")
    if asked is not None and u"holding_time_ok" in asked and receipt.get("holding_time_ok") not in (True, False):
        blocking.append(u"whether the samples are within holding time")
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


def summary(records, numbers):
    """The CoC as a worksheet's samples carry it: `records`, the loaded CoC
    records of the numbers the samples carry; `numbers`, one (sample id,
    CoC number or "") per sample. {} when no sample carries a number (older
    samples: the CoC logbook). Received only when every sample carries a
    number and every record is received; the collection date is core's,
    added by the caller."""
    numbers = list(numbers or [])
    nums = [n or u"" for _sid, n in numbers]
    if not numbers or not any(nums):
        return {}
    recs = [r for r in records or [] if r]
    receipts = [r.get("receipt") or {} for r in recs]
    received = bool(recs) and all(r.get("status") == RECEIVED for r in recs) and all(nums)
    first = recs[0] if recs else {}
    rc = receipts[0] if receipts else {}
    return {
        # each record's own receipt (the batch record prints one row per CoC)
        "records": [{"number": r["number"], "status": r.get("status"), "origin": r.get("origin"),
                     "flags": (r.get("receipt") or {}).get("flags") or [],
                     "not_judged": (r.get("receipt") or {}).get("not_judged") or [],
                     "note": (r.get("receipt") or {}).get("note") or u"",
                     "received_by": (r.get("receipt") or {}).get("received_by") or u"",
                     # the date in force: a signed correction's, else as received
                     "received_at": received_in_force(r),
                     "temperatures": [(t.get("sample_id") or u"", t.get("observed"), t.get("corrected"))
                                      for t in (r.get("receipt") or {}).get("readings") or []]}
                    for r in recs],
        "missing": [sid for sid, n in zip([sid for sid, _n in numbers], nums) if not n],
        "all_received": received,
        "client_name": first.get("client") or u"",
        "project_name": first.get("project") or u"",
        "lab_received_by": rc.get("received_by") or u"",
        "lab_received_date": received_in_force(first),
        "seals_intact": all(x.get("seals_intact") is True for x in receipts) if receipts else False,
        "labels_legible": all(x.get("labels_legible") is True for x in receipts) if receipts else False,
        "holding_time_ok": received and all(x.get("holding_time_ok") is True for x in receipts),
        "condition_notes": u" ".join(x.get("note") or u"" for x in receipts).strip(),
        "reviewed_by": u"", "reviewed_date": u"",
        "n_containers": len(numbers),
        "n_transfers": sum(len(r.get("transfers") or []) for r in recs),
        "receipt_thermometer": None,
        "receipt_temps": [(t.get("sample_id") or u"", t.get("observed"), t.get("corrected"))
                          for x in receipts for t in x.get("readings") or []],
    }


from senaite.pfas.rounding import number as _num


def judge_temperatures(readings, on_ice):
    """(flags, not_judged) for receipt temperatures against each sample's
    range: its matrix's on its method, over All matrices
    (matrix_temperature.receipt_range), frozen into the reading.

    `readings`: [{"sample_id", "observed", "corrected", "range": {"min_c",
    "max_c", "same_day_on_ice"} or None, "same_day": bool}]. The corrected
    value is judged (the observed one when no correction applies). With the
    method's same-day switch on, a sample received the day it was collected
    and on ice is not flagged for being ABOVE the maximum (never below the
    minimum). A sample whose method sets no range is listed as not judged;
    one whose range is No requirement is neither judged nor listed: the
    method says there is nothing to judge."""
    from senaite.pfas import matrix_temperature
    flags, not_judged = [], []
    for r in readings or []:
        rng = r.get("range") or {}
        if matrix_temperature.no_requirement(rng):
            continue
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


def receipt_verdict(receipt):
    """How a recorded receipt reads in words: its flags, then what was not
    judged, and Compliant only when something was judged and nothing is
    flagged. A temperature with no range to judge it against is never read
    as a pass."""
    receipt = receipt or {}
    parts = list(receipt.get("flags") or [])
    not_judged = receipt.get("not_judged") or []
    if not_judged:
        parts.append(u"Not judged: " + u"; ".join(not_judged))
    return u"; ".join(parts) or u"Compliant"


def holding_declared(coc):
    """Whether Data Review's CoC item may pass on "within holding time":
    `coc` the page's summary, with "checks" (stored_checks). Every receipt
    that holds an answer says Yes; a receipt that was not asked owes none.
    A summary without "checks" reads its own holding_time_ok."""
    checks = (coc or {}).get("checks")
    if checks is None:
        return bool((coc or {}).get("holding_time_ok"))
    return bool(checks.get("holding_declared")) if checks.get("holding_time_ok") else True


# ── a correction of the receipt date ─────────────────────────────────────
#
# A received CoC's receipt date is corrected by a signed correction. The
# receipt keeps the date it was received with ("received_at"); each
# correction is appended to receipt["corrections"] and changes afterwards
# only in its state. It gives the new date, the date in force it replaced,
# the reason and who. The person who corrects signs it (ledger kind
# RECEIPT_KIND, meaning RECEIPT_MEANING, record id the CoC number), bound to
# correction_content; a later correction's signature supersedes it. The date
# in force is the last correction still signed, else the date received; a
# correction whose signature was withdrawn no longer counts.

RECEIPT_KIND = u"coc_receipt"
RECEIPT_MEANING = u"corrected"
RECEIPT_REVISION = 1
SIGNED, WITHDRAWN = u"signed", u"withdrawn"

NOT_RECEIVED = u"Only a received CoC's receipt date can be corrected."
NO_NEW_DATE = u"Enter the corrected receipt date and time."
SAME_DATE = u"The corrected date is the date in force already."
NO_CORRECTION_REASON = u"Give the reason for the correction."
IN_FUTURE = u"The corrected date is later than now."
BEFORE_COLLECTION = u"The corrected date is before %s was sampled, %s."

_AT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


def _at(value):
    """A typed date and time as the receipt keeps it: "YYYY-MM-DD HH:MM"."""
    return (u"%s" % (value or u"")).strip().replace(u"T", u" ")[:16]


def corrections(record):
    return [c for c in ((record or {}).get("receipt") or {}).get("corrections") or [] if isinstance(c, dict)]


def correction_in_force(record):
    """The last correction still signed, or None."""
    signed = [c for c in corrections(record) if c.get("state") == SIGNED]
    return signed[-1] if signed else None


def received_in_force(record):
    """The receipt date in force: the last signed correction's date, else
    the date the CoC was received with."""
    c = correction_in_force(record)
    if c is not None:
        return c.get("to") or u""
    return ((record or {}).get("receipt") or {}).get("received_at") or u""


def correction_problems(record, new_at, reason, now, collected=()):
    """Why this correction cannot be made: `new_at` the corrected date and
    time, `now` the laboratory's now, `collected` [(sample id, collection
    date and time)], each on the laboratory's clock."""
    record = record or {}
    if record.get("status") != RECEIVED:
        return [NOT_RECEIVED]
    out, new = [], _at(new_at)
    if not _AT.match(new):
        out.append(NO_NEW_DATE)
    elif new == _at(received_in_force(record)):
        out.append(SAME_DATE)
    elif now and new > _at(now):
        out.append(IN_FUTURE)
    else:
        for sid, when in collected or ():
            if when and new < _at(when):
                out.append(BEFORE_COLLECTION % (sid, _at(when)))
    if not (reason or u"").strip():
        out.append(NO_CORRECTION_REASON)
    return out


def new_correction(record, new_at, reason, userid, name, at):
    """The correction entry, not yet signed: its id is the CoC number and
    its place in the list."""
    return {"id": u"%s-c%d" % (record["number"], len(corrections(record)) + 1),
            "original": ((record.get("receipt") or {}).get("received_at") or u""),
            "from": received_in_force(record), "to": _at(new_at),
            "reason": (reason or u"").strip(), "by": userid or u"", "by_name": name or userid or u"",
            "at": at, "state": u"unsigned"}


def correction_content(record, entry):
    """What the corrector's signature binds: the CoC, its samples, the date
    received, the date replaced, the new date, the reason and who."""
    return {"kind": RECEIPT_KIND, "id": record.get("number") or u"", "revision": RECEIPT_REVISION,
            "correction": entry.get("id") or u"", "samples": sorted(record.get("samples") or []),
            "original": entry.get("original") or u"", "from": entry.get("from") or u"",
            "to": entry.get("to") or u"", "reason": entry.get("reason") or u"",
            "corrected_by": entry.get("by") or u""}


def correction_hash(record, entry):
    from senaite.pfas.esig import canonical
    return canonical.sha256_of(correction_content(record, entry))


def add_correction(record, entry, signature, cache):
    """The record with the signed correction appended and logged.
    `signature` {"seq", "hash", "record_hash"} of the ledger row, `cache`
    its display copy (esig.signing.cache)."""
    signed = dict(entry, state=SIGNED, signature=dict(signature or {}), signatures=list(cache or []))
    record.setdefault("receipt", {}).setdefault("corrections", []).append(signed)
    record.setdefault("log", []).append({"at": entry.get("at"), "by": entry.get("by_name"),
                                         "what": u"receipt date corrected", "before": entry.get("from"),
                                         "after": entry.get("to"), "reason": entry.get("reason")})
    return record


def withdraw_correction(record, seq, by, at, reason, cache=()):
    """The correction whose signature is ledger row `seq` withdrawn, so the
    date in force returns to the one before it; logged. True when a
    correction changed."""
    for c in corrections(record):
        if (c.get("signature") or {}).get("seq") == seq and c.get("state") == SIGNED:
            c.update(state=WITHDRAWN, withdrawn_by=by or u"", withdrawn_at=at or u"",
                     withdrawn_reason=(reason or u"").strip())
            c["signatures"] = list(c.get("signatures") or []) + list(cache or [])
            record.setdefault("log", []).append({"at": at, "by": by, "what": u"receipt date correction withdrawn",
                                                 "before": c.get("to"), "after": received_in_force(record),
                                                 "reason": (reason or u"").strip()})
            return True
    return False


def correction_line(entry, lead=u"Corrected"):
    """A correction in words: "Corrected from A to B by NAME: reason"."""
    line = u"%s from %s to %s by %s: %s" % (lead, entry.get("from") or u"", entry.get("to") or u"",
                                                    entry.get("by_name") or entry.get("by") or u"",
                                                    entry.get("reason") or u"")
    return line + (u" (withdrawn)" if entry.get("state") == WITHDRAWN else u"")


def transcription_line(record):
    """The printed CoC's note for a paper CoC, or ""."""
    t = (record or {}).get("transcribed") or {}
    if (record or {}).get("origin") != PAPER or not t.get("by"):
        return u""
    from senaite.pfas import print_doc
    at = t.get("at") or u""
    return (u"Transcribed from paper CoC %s by %s on %s. Paper original retained."
            % (record.get("number"), t["by"], print_doc.lab_or(at, at[:10], u"%Y-%m-%d")))


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


def delete(portal, number):
    """Drop a record. Its number stays in the index, so no later CoC is
    issued the same number."""
    ann = _ann(portal)
    key = RECORD_PREFIX + (number or u"")
    if key in ann:
        del ann[key]


def issue(portal, client_uid, client, origin, by, at):
    """A new record under the next number; saved."""
    rec = new_record(next_number(numbers(portal), at[:4]), client_uid, client, origin, by, at)
    save(portal, rec)
    return rec


def _numbers_of(samples):
    return [(s.getId(), s.getField("CoCNumber").get(s) or u"") for s in samples or []]


def worksheet_summary(portal, samples):
    """summary() of these samples' CoC records, read from the store: Data
    Review's CoC check and the batch record read the same one."""
    numbers = _numbers_of(samples)
    if not any(n for _sid, n in numbers):
        return {}
    return summary([load(portal, n) for n in sorted(set(n for _sid, n in numbers if n))], numbers)


def worksheet_records(portal, samples):
    """The CoC records these samples carry the numbers of, as stored."""
    return [r for r in (load(portal, n) for n in sorted(set(n for _sid, n in _numbers_of(samples) if n))) if r]


def list_filter(records, show=u"", q=u""):
    """The CoCs a list shows: `show` "" those not received yet, "received"
    those received, "all" every one; `q` a word in the number or the
    client's name."""
    q = (q or u"").strip().lower()
    out = []
    for r in records or []:
        received = (r.get("status") or OPEN) == RECEIVED
        if (show == u"" and received) or (show == u"received" and not received):
            continue
        if q and q not in (u"%s %s" % (r.get("number") or u"", r.get("client") or u"")).lower():
            continue
        out.append(r)
    return out


def for_client(portal, client_uid):
    out = []
    for n in numbers(portal):
        r = load(portal, n)
        if r and (client_uid is None or r.get("client_uid") == client_uid):
            out.append(r)
    return out
