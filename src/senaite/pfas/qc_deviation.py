# -*- coding: utf-8 -*-
"""
Raise an ISO 17025 deviation when a QC criterion was never configured.

A criterion the method does not define is not a QC failure — nothing was
judged. But it is also not nothing: a batch whose CCV window or calibration r²
is unset has been measured against no standard at all, and releasing it on
silence is exactly what §7.8.4's technical review exists to prevent.

The pipeline records such gaps on the batch (`batch.unconfigured`) and files
them as `unevaluated` rows in `qc_results`, which holds the Data Review gate.
This module turns that into something a reviewer can act on and a QAO is told
about: an open Deviation against the worksheet, carrying the exact criterion,
the method it belongs to and where to set it.

It is raised where the run arrives: the worker, after pushing a run's
results, asks @@pfas-unconfigured-deviation, which reads the QC Summary as
Data Review's gate reads it. A page never raises it: rendering is a read.

Reuses the deviation registry (worksheet link, risk score, sign-off workflow)
and the QAO named once in Print Settings for CoA attestation.

Python 2.7 (in-Plone add-on).
"""
from __future__ import absolute_import

import copy
import json
import logging

from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.qc_deviation")

# THE key for the deviation/CAR registry, defined here and imported everywhere
# else (browser/deviations.py, data_review): a second copy of the string can
# drift, and a deviation filed under it is invisible to every reader.
ANN_REGISTRY_KEY = u"senaite.pfas.deviations.registry"

# Marks the deviations this module owns, so a run delivered again updates the
# existing record rather than filing a duplicate.
SIGNATURE_KEY = "pfas_unconfigured_signature"

EVENT_TYPE = "QC criterion not configured"


def get_registry(portal):
    """The deviation/CAR registry as a list -- the one reader of the key."""
    raw = IAnnotations(portal).get(ANN_REGISTRY_KEY)
    return json.loads(raw) if raw else []


def save_registry(portal, data):
    """Persist the registry -- the one writer of the key."""
    IAnnotations(portal)[ANN_REGISTRY_KEY] = json.dumps(data)


def _next_id(registry):
    from senaite.pfas import lab_time
    year = lab_time.today().year
    prefix = "DEV-{0}-".format(year)
    seq = len([e for e in registry
               if str(e.get("dev_id", "")).startswith(prefix)]) + 1
    return "{0}{1:03d}".format(prefix, seq)


# A deviation filed for an unset criterion is one per criterion: the
# method's check. Its signature names them; a record filed before, one per
# worksheet, is "<worksheet>::<check>|<why>||..." and keeps its signature.
CRITERION = u"criterion::"


def criterion_signature(method_id, qc_type, worksheet_id):
    """The identity of one unset criterion: the method's check. With no
    method named the worksheet stands in, so the checks of two methods never
    share a record."""
    owner = method_id or (u"worksheet:" + (worksheet_id or u""))
    return u"{0}{1}::{2}".format(CRITERION, owner, qc_type or u"")


# Missing data on a worksheet is not an unset setting: it is filed as the
# worksheet's own deviation, one per worksheet, its checks listed on it.
MISSING = u"missing::"
MISSING_EVENT_TYPE = "QC data missing on the worksheet"


def missing_signature(worksheet_id):
    """The identity of one worksheet's missing-data deviation."""
    return u"{0}{1}".format(MISSING, worksheet_id or u"")


# What a gap in one worksheet's own data reads as, in the worker's words
# (pfas_pipeline run_queue and run_shape); every other gap is an unset
# criterion of the method.
MISSING_DATA_TYPES = (u"Run plan",)       # a planned run did not run, or ran unplanned
MISSING_DATA_WORDS = (
    u"not recorded",                           # an LFB, LFSM or LFSMD, or a portion's amount
    u"the field reagent blank is not judged",  # a field reagent blank with no limit
    u"the duplicate must match its LFSM",      # an LFSMD recorded at another level
)
# an LFSMD not judged because its LFSM was not: it goes where its LFSM goes
FOLLOWS_LFSM = u"its LFSM recovery was not judged"
# a QC type the method requires every run that the run does not hold, in
# Data Review's words (the gate files it): the worksheet's missing data
NOT_RUN = u"not run, though the method requires it every run"


def _says_missing(gap):
    reason = (gap.get("reason") or u"")
    return (gap.get("qc_type") or u"") in MISSING_DATA_TYPES or \
        any(w in reason for w in MISSING_DATA_WORDS + (NOT_RUN,))


def not_run(missing, released):
    """[{"qc_type", "dev_id"}] by QC type: each QC type the method requires
    every run that the run did not hold, as the gate reads it -- `missing`
    (still held) and `released` ({qc_type: dev_id} of a closed missing-data
    record). The certificate states each, naming the deviation that
    released it; one still held names none."""
    released = released or {}
    return [{"qc_type": qt, "dev_id": released.get(qt) or u""}
            for qt in sorted(set(missing or ()) | set(released))]


def merge_not_run(lists):
    """not_run's lists of several worksheets (or samples) as one, each QC
    type once, naming every deviation that released it."""
    out = {}
    for items in lists:
        for item in items or []:
            kept = out.setdefault(item["qc_type"], {"qc_type": item["qc_type"], "dev_id": u""})
            ids = [i for i in kept["dev_id"].split(u", ") if i]
            if item.get("dev_id") and item["dev_id"] not in ids:
                ids.append(item["dev_id"])
            kept["dev_id"] = u", ".join(ids)
    return [out[k] for k in sorted(out)]


def released_checks(registry, worksheet_id):
    """{check: dev_id} of the checks a missing-data record of this
    worksheet releases: one closed with closure notes that lists the check.
    A record of the worksheet not closed (open, in progress, reopened) that
    lists a check keeps it held, and a record of another worksheet or of an
    unset criterion releases nothing here."""
    signature = missing_signature(worksheet_id)
    released, held = {}, set()
    for d in registry or []:
        if d.get(SIGNATURE_KEY) != signature:
            continue
        checks = [c for c in d.get("checks") or [] if c]
        if d.get("status") != "closed":
            held.update(checks)
        elif (d.get("closure_notes") or u"").strip():
            for c in checks:
                released.setdefault(c, d.get("dev_id") or u"")
    return dict((c, i) for c, i in released.items() if c not in held)


def split_gaps(gaps):
    """(unset criteria, missing data) of one worksheet's gaps, each a list
    of the gaps as given."""
    gaps = list(gaps or [])
    lfsm_missing = any(_says_missing(g) for g in gaps
                       if (g.get("qc_type") or u"") == u"LFSM" and FOLLOWS_LFSM not in (g.get("reason") or u""))
    crit, miss = [], []
    for g in gaps:
        if FOLLOWS_LFSM in (g.get("reason") or u""):
            (miss if lfsm_missing else crit).append(g)
        elif _says_missing(g):
            miss.append(g)
        else:
            crit.append(g)
    return crit, miss


def checks_of(dev):
    """(method id or None, [check]) of a deviation filed for unset criteria
    or for a worksheet's missing data, read from its signature (and, for
    missing data, its checks); (None, []) for any other deviation."""
    sig = (dev or {}).get(SIGNATURE_KEY) or u""
    if sig.startswith(MISSING):
        return None, list((dev or {}).get("checks") or [])
    if sig.startswith(CRITERION):
        owner, _sep, check = sig[len(CRITERION):].rpartition(u"::")
        return (None if owner.startswith(u"worksheet:") else owner), [check]
    if u"::" not in sig:
        return None, []
    out = []
    for part in sig.split(u"::", 1)[1].split(u"||"):
        check = part.split(u"|", 1)[0]
        if check and check not in out:
            out.append(check)
    return None, out


def _describe(gaps, missing=False):
    if missing:
        lines = [u"The following data are missing on this worksheet, so the "
                 u"corresponding checks could not be evaluated. Results are held "
                 u"until each is recorded, or this deviation records why not.", u""]
    else:
        lines = [u"The following QC criteria are not configured for this method, "
                 u"so the corresponding checks could not be evaluated. Results are "
                 u"held until each is set in Method Profiles.", u""]
    for gap in gaps:
        lines.append(u"\u2022 {0}: {1}".format(
            gap.get("qc_type") or u"(unknown check)",
            gap.get("reason") or u""))
    return u"\n".join(lines)


def _retry_notice(portal, dev, worksheet_id, gaps):
    """Tell the QAO of a record found again that never reached them: True
    when it went (the record changed)."""
    if dev.get("qao_notified"):
        return False
    if not _notify_qao(portal, dev, worksheet_id, gaps):
        return False
    dev["qao_notified"] = True
    dev["closure_notes"] = u""
    logger.info("QAO notified retrospectively for %s", dev.get("dev_id"))
    return True


def _record(registry, worksheets, gaps, filed_by, signature, today, missing=False):
    """A new open record of unset criteria (or of a worksheet's missing
    data), its id the registry's next; not yet in the registry."""
    record = {
        "dev_id":      _next_id(registry),
        "type":        "deviation",
        "filed_by":    filed_by,
        "filed_at":    today,
        "status":      "open",
        "event_type":  MISSING_EVENT_TYPE if missing else EVENT_TYPE,
        "event_date":  today,
        "description": _describe(gaps, missing),
        # A criterion that was never set is not a borderline call: every result
        # it governs is unjudged, so it scores as certain and significant.
        "likelihood":  3,
        "severity":    3,
        "risk_score":  9,
        "risk_colour": "orange",
        "affected_worksheets": list(worksheets),
        "affected_date_from":  today,
        "affected_date_to":    "",
        "scale_description":   u"All results on the worksheets listed that the "
                               u"criterion above governs.",
        "root_cause":          u"",
        "corrective_actions":  [],
        "closed_by":   None,
        "closed_at":   None,
        "closure_notes": "",
        SIGNATURE_KEY: signature,
    }
    if missing:
        record["checks"] = _checks(gaps)
    return record


def _checks(gaps):
    out = []
    for g in gaps or []:
        c = g.get("qc_type") or u""
        if c and c not in out:
            out.append(c)
    return out


def _new_record(portal, registry, worksheet_id, gaps, filed_by, signature, missing=False):
    from senaite.pfas import lab_time
    record = _record(registry, [worksheet_id], gaps, filed_by, signature,
                     lab_time.today().isoformat(), missing)
    logger.warning("Raised %s for %s on %s", record["dev_id"],
                   "missing QC data" if missing else "unconfigured QC criteria", worksheet_id)
    # Whether the QAO was actually reached is part of the record. A
    # notification that silently did not send is worse than none: the
    # deviation would look attended to. A QAO contact with no address reads
    # "not notified" until a real address is set.
    notified = _notify_qao(portal, record, worksheet_id, gaps)
    record["qao_notified"] = bool(notified)
    if not notified:
        record["closure_notes"] = (
            u"QAO was NOT notified automatically: {0} Tell them directly. "
            u"Once it is configured the notification is retried "
            u"automatically; there is no need to re-file this deviation.".format(
                record.get("qao_notify_error") or u"reason unrecorded."))
    registry.append(record)
    return record


def _covered_by_earlier(live, worksheet_id, check):
    """An open record filed one per worksheet before, naming this worksheet
    and this check, or None."""
    for d in live:
        sig = d.get(SIGNATURE_KEY) or u""
        if sig and not sig.startswith(CRITERION) and not sig.startswith(MISSING) \
                and worksheet_id in (d.get("affected_worksheets") or []) \
                and check in checks_of(d)[1]:
            return d
    return None


def ensure_deviations(portal, worksheet_id, gaps, filed_by=u"system", method_id=u""):
    """The open deviations a run's gaps call for, filed when there is none:
    one per unset criterion (the method's check), and one for the
    worksheet's missing data (split_gaps).

    An open record of the criterion lists the worksheet, which is what holds
    it at Data Review; the worksheet's missing-data record lists each check
    it lacks. A record filed one per worksheet that already names the
    worksheet and the check covers it. A closed record is never reopened.
    Idempotent: the same run asked again changes nothing.
    """
    if not gaps or not worksheet_id:
        return []
    criteria, missing = split_gaps(gaps)
    groups = []
    for gap in criteria:
        check = gap.get("qc_type") or u""
        for g in groups:
            if g[0] == check:
                g[1].append(gap)
                break
        else:
            groups.append((check, [gap]))
    registry = get_registry(portal)
    out, changed = [], False
    for check, its in groups:
        signature = criterion_signature(method_id, check, worksheet_id)
        live = [d for d in registry if d.get("status") != "closed"]
        same = [d for d in live if d.get(SIGNATURE_KEY) == signature]
        earlier = _covered_by_earlier(live, worksheet_id, check)
        if same:
            dev = same[0]
            listed = dev.setdefault("affected_worksheets", [])
            if worksheet_id not in listed:
                listed.append(worksheet_id)
                changed = True
                logger.warning("%s now also holds %s", dev.get("dev_id"), worksheet_id)
            changed = _retry_notice(portal, dev, worksheet_id, its) or changed
        elif earlier is not None:
            dev = earlier
            changed = _retry_notice(portal, dev, worksheet_id, its) or changed
        else:
            dev = _new_record(portal, registry, worksheet_id, its, filed_by, signature)
            changed = True
        if dev not in out:
            out.append(dev)
    if missing:
        live = [d for d in registry if d.get("status") != "closed"]
        signature = missing_signature(worksheet_id)
        same = [d for d in live if d.get(SIGNATURE_KEY) == signature]
        uncovered = [g for g in missing
                     if _covered_by_earlier(live, worksheet_id, g.get("qc_type") or u"") is None]
        if same:
            dev = same[0]
            named = dev.setdefault("checks", [])
            for g in missing:
                c = g.get("qc_type") or u""
                if c and c not in named:
                    named.append(c)
                    dev["description"] = u"{0}\n\u2022 {1}: {2}".format(
                        dev.get("description") or u"", c, g.get("reason") or u"")
                    changed = True
            changed = _retry_notice(portal, dev, worksheet_id, missing) or changed
        elif not uncovered:
            dev = _covered_by_earlier(live, worksheet_id, missing[0].get("qc_type") or u"")
            changed = _retry_notice(portal, dev, worksheet_id, missing) or changed
        else:
            dev = _new_record(portal, registry, worksheet_id, missing, filed_by, signature, missing=True)
            changed = True
        if dev not in out:
            out.append(dev)
    if changed:
        save_registry(portal, registry)
    return out


def ensure_deviation(portal, worksheet_id, gaps, filed_by=u"system", method_id=u""):
    """The first of ensure_deviations, or None: the record a caller that
    names one deviation reports."""
    found = ensure_deviations(portal, worksheet_id, gaps, filed_by, method_id)
    return found[0] if found else None


SHOWN_WORKSHEETS = 3


def list_rows(registry, status=u"", type_=u"", q=u"", method_name=None):
    """The register as the list shows it, newest first: `status` "" keeps
    what is not closed, "all" everything, else that status; `type_` ""
    every type; `q` a word in the id, the criterion or a worksheet. Each row
    a copy with "criterion" (its checks), "criterion_method" (the method's
    name, by `method_name`), "worksheets_shown" and "worksheets_more"."""
    q = (q or u"").strip().lower()
    out = []
    for dev in reversed(registry or []):
        if type_ and dev.get("type") != type_:
            continue
        st = dev.get("status")
        if (not status and st == "closed") or (status not in (u"", u"all") and st != status):
            continue
        row = dict(dev)
        method_id, checks = checks_of(dev)
        row["criterion"] = u", ".join(checks)
        row["criterion_method"] = (method_name(method_id) if method_name else method_id) \
            if method_id else u""
        sheets = list(dev.get("affected_worksheets") or [])
        row["worksheets_shown"] = sheets[:SHOWN_WORKSHEETS]
        row["worksheets_more"] = max(0, len(sheets) - SHOWN_WORKSHEETS)
        words = u" ".join([dev.get("dev_id") or u"", row["criterion"], row["criterion_method"]] + sheets)
        if q and q not in words.lower():
            continue
        out.append(row)
    return out


# a worksheet's missing-data record releases the checks it lists only when
# its closure says why the data are missing: it never closes without notes
NOTES_REQUIRED = u"notes_required"


def needs_closure_notes(dev):
    """True for a worksheet's missing-data record: it closes only with notes."""
    return ((dev or {}).get(SIGNATURE_KEY) or u"").startswith(MISSING)


def close_record(dev, by, at, notes):
    """The one way a deviation closes: refused, u"incomplete_cas", while a
    corrective action of it is not complete, or NOTES_REQUIRED when it is a
    worksheet's missing-data record and `notes` is empty; else closed by
    `by` at `at` with `notes`, and None."""
    if [ca for ca in dev.get("corrective_actions") or [] if ca.get("status") != "complete"]:
        return u"incomplete_cas"
    if needs_closure_notes(dev) and not (notes or u"").strip():
        return NOTES_REQUIRED
    dev["status"] = "closed"
    dev["closed_by"] = by
    dev["closed_at"] = at
    dev["closure_notes"] = notes
    return None


# a closed record is read-only: the page's actions that change a record are
# refused on it; only a manager reopens it, with a reason (reopen_record)
CLOSED_READ_ONLY = u"closed_read_only"
REASON_REQUIRED = u"reason_required"
NOT_CLOSED = u"not_closed"
# the status a reopened record takes: its work goes on where it stopped
REOPENED_STATUS = u"in_progress"


def closed_refusal(dev):
    """CLOSED_READ_ONLY when the record is closed, else None: the one check
    every action that changes a record asks first."""
    return CLOSED_READ_ONLY if (dev or {}).get("status") == "closed" else None


def reopen_record(dev, by, at, reason):
    """The one way a closed record reopens: refused, NOT_CLOSED, when it is
    not closed, or REASON_REQUIRED without a reason; else it goes back to
    REOPENED_STATUS and its history keeps who reopened it, when, why, and
    the closure it undoes (who closed it, when, and the closure notes)."""
    reason = (reason or u"").strip()
    if (dev or {}).get("status") != "closed":
        return NOT_CLOSED
    if not reason:
        return REASON_REQUIRED
    dev.setdefault("history", []).append({
        "at": at, "by": by, "action": u"reopened", "reason": reason,
        "closed_by": dev.get("closed_by"), "closed_at": dev.get("closed_at"),
        "closure_notes": dev.get("closure_notes") or u"",
        "changes": [{"field": "status", "before": "closed", "after": REOPENED_STATUS}]})
    dev["status"] = REOPENED_STATUS
    dev["closed_by"] = None
    dev["closed_at"] = None
    dev["closure_notes"] = u""
    return None


# ── one deviation per unset criterion, for the records filed before ─────────

SUPERSEDED = u"Superseded by {0}, one deviation per unset criterion"
SUPERSEDED_MISSING = u"Superseded by {0}, one deviation per worksheet for its missing data"
ALSO_MISSING = u"its missing data by {0}, one per worksheet"
REMOVED = u"Worksheet removed: {0} no longer exists"
MIGRATED_BY = u"system (one deviation per criterion)"


def _legacy(dev):
    """True for an open record filed one per worksheet for unset criteria
    (a signature "<worksheet>::<check>|<why>||..."). A record a person
    filed carries no signature and is never one."""
    sig = dev.get(SIGNATURE_KEY) or u""
    return bool(sig) and dev.get("status") != "closed" and u"::" in sig \
        and not sig.startswith(CRITERION) and not sig.startswith(MISSING)


def _legacy_gaps(dev):
    """The gaps a record filed one per worksheet names, in its order."""
    out = []
    for part in (dev.get(SIGNATURE_KEY) or u"").split(u"::", 1)[1].split(u"||"):
        check, _sep, why = part.partition(u"|")
        gap = {"qc_type": check, "reason": why}
        if check and gap not in out:
            out.append(gap)
    return out


def held(registry, live):
    """The worksheets in `live` that an open record of the registry lists:
    what Data Review holds on a deviation."""
    out = set()
    for d in registry or []:
        if d.get("status") != "closed":
            out.update(w for w in d.get("affected_worksheets") or [] if w in live)
    return out


def _and(ids):
    ids = list(ids)
    return ids[0] if len(ids) == 1 else u"{0} and {1}".format(u", ".join(ids[:-1]), ids[-1])


def _earliest(values):
    values = [v for v in values if v]
    return min(values) if values else u""


def dedupe(registry, method_of, by, at, today):
    """One deviation per unset criterion, for the open records filed one
    per worksheet before. Returns (registry', report); `registry` itself is
    not changed.

    Each record's gaps are split (split_gaps): an unset criterion joins the
    one open record of its method's check, which lists every worksheet of
    its records (an open record of that criterion already filed is kept
    and extended); a worksheet's missing data goes to that worksheet's own
    record. The new records are written first, then each old record is
    closed through close_record with what superseded it, so no worksheet is
    ever left unheld. A record whose worksheets are all gone (`method_of`
    gives None) is closed as worksheet removed. A record a person filed, or
    one of another kind, is not touched. Refuses (ValueError) when a live
    worksheet held before would not be held after.

    `method_of(worksheet id)`: its method id, "" when it has none, None
    when the worksheet is gone. report: {"created", "extended", "closed",
    "kept", "held_before", "held_after"}; "created" and "extended" list
    {"dev_id", "signature", "worksheets", "replaces"}, "closed" lists
    (dev_id, note), "kept" (dev_id, why it stayed open)."""
    registry = copy.deepcopy(list(registry or []))
    sheets_all = set()
    for d in registry:
        sheets_all.update(d.get("affected_worksheets") or [])
    live = set(w for w in sheets_all if method_of(w) is not None)
    before = held(registry, live)

    olds = [d for d in registry if _legacy(d)]
    criteria, missing, removed = {}, {}, []
    for dev in olds:
        sheets = [w for w in dev.get("affected_worksheets") or [] if w in live]
        if not sheets:
            removed.append(dev)
            continue
        crit, miss = split_gaps(_legacy_gaps(dev))
        for ws in sheets:
            for gap in crit:
                sig = criterion_signature(method_of(ws) or u"", gap["qc_type"], ws)
                g = criteria.setdefault(sig, {"gaps": [], "sheets": [], "sources": []})
                for bucket, item in ((g["gaps"], gap), (g["sheets"], ws), (g["sources"], dev)):
                    if item not in bucket:
                        bucket.append(item)
            if miss:
                g = missing.setdefault(ws, {"gaps": [], "sheets": [ws], "sources": []})
                g["gaps"].extend(x for x in miss if x not in g["gaps"])
                if dev not in g["sources"]:
                    g["sources"].append(dev)

    successors = {}
    report = {"created": [], "extended": [], "closed": [], "kept": []}
    plans = [(sig, criteria[sig], False) for sig in sorted(criteria)] + \
            [(missing_signature(ws), missing[ws], True) for ws in sorted(missing)]
    for sig, g, is_missing in plans:
        replaces = [d.get("dev_id") for d in g["sources"]]
        note = u"Replaces {0}, filed one per worksheet.".format(_and(replaces))
        same = [d for d in registry if d.get("status") != "closed" and d.get(SIGNATURE_KEY) == sig]
        if same:
            dev = same[0]
            listed = dev.setdefault("affected_worksheets", [])
            listed.extend(w for w in g["sheets"] if w not in listed)
            if is_missing:
                named = dev.setdefault("checks", [])
                named.extend(c for c in _checks(g["gaps"]) if c not in named)
            dev["description"] = u"{0}\n\n{1}".format(dev.get("description") or u"", note)
            report["extended"].append({"dev_id": dev["dev_id"], "signature": sig,
                                       "worksheets": list(listed), "replaces": replaces})
        else:
            dev = _record(registry, g["sheets"], g["gaps"], MIGRATED_BY, sig, today, is_missing)
            dev["description"] = u"{0}\n\n{1}".format(dev["description"], note)
            dev["event_date"] = _earliest(d.get("event_date") for d in g["sources"]) or today
            dev["affected_date_from"] = _earliest(
                d.get("affected_date_from") or d.get("filed_at") for d in g["sources"]) or today
            # the QAO was told of the records it replaces, or is told now
            # by the notice tick (retry_notifications)
            dev["qao_notified"] = all(bool(d.get("qao_notified")) for d in g["sources"])
            registry.append(dev)
            report["created"].append({"dev_id": dev["dev_id"], "signature": sig,
                                      "worksheets": list(g["sheets"]), "replaces": replaces})
        for d in g["sources"]:
            successors.setdefault(d.get("dev_id"), []).append((dev["dev_id"], is_missing))

    for dev in olds:
        if dev in removed:
            gone = [w for w in dev.get("affected_worksheets") or []] or [u"its worksheet"]
            note = REMOVED.format(_and(gone))
        else:
            nexts = successors.get(dev.get("dev_id")) or []
            if not nexts:
                report["kept"].append((dev.get("dev_id"), u"no gap of it could be read"))
                continue
            crit = [i for i, m in nexts if not m]
            miss = [i for i, m in nexts if m]
            if crit and miss:
                note = u"{0}; {1}".format(SUPERSEDED.format(_and(crit)), ALSO_MISSING.format(_and(miss)))
            elif crit:
                note = SUPERSEDED.format(_and(crit))
            else:
                note = SUPERSEDED_MISSING.format(_and(miss))
        refused = close_record(dev, by, at, note)
        if refused:
            report["kept"].append((dev.get("dev_id"), u"a corrective action is not complete"))
        else:
            report["closed"].append((dev.get("dev_id"), note))

    after = held(registry, live)
    if before - after:
        raise ValueError(u"Refused: {0} would no longer be held.".format(_and(sorted(before - after))))
    report["held_before"] = sorted(before)
    report["held_after"] = sorted(after)
    return registry, report


def qao_email(portal):
    """The QAO's address, from the single place the QAO is already named."""
    from senaite.pfas.print_settings import get_signoff_signers
    try:
        qao = (get_signoff_signers(portal) or {}).get("qao")
        return (qao or {}).get("email") or u""
    except Exception as exc:                                # noqa: BLE001
        logger.warning("could not resolve the QAO contact: %s", exc)
        return u""


def _notify_qao(portal, record, worksheet_id, gaps):
    """Email the QAO. A failure here must not undo the deviation."""
    address = qao_email(portal)
    if not address:
        logger.warning(
            u"%s: no QAO email: set the QAO's initials in Print Settings and "
            u"an email address on that LabContact. The notification is retried "
            u"once one is set.", record["dev_id"])
        record["qao_notify_error"] = (
            u"No email address on the QAO LabContact "
            u"(Print Settings \u2192 QAO initials).")
        return False

    # A MailHost with no SMTP host silently accepts nothing. Say so up front
    # rather than reporting a generic send failure.
    if not (getattr(getattr(portal, "MailHost", None), "smtp_host", "") or ""):
        logger.warning(u"%s: QAO is %s but no SMTP host is configured in "
                       u"MailHost, so nothing can be sent.",
                       record["dev_id"], address)
        record["qao_notify_error"] = (
            u"No SMTP host configured in MailHost; "
            u"the QAO address ({0}) is set.".format(address))
        return False

    try:
        from senaite.pfas import lab_identity
        prefix = lab_identity.mail_prefix(portal)
    except Exception:                                       # noqa: BLE001
        prefix = u"[LIMS]"
    # what the record is about says what the QAO is told and where to act:
    # missing data on the worksheet's Data Review, an unset criterion in
    # Method Profiles
    base = portal.absolute_url()
    if (record.get(SIGNATURE_KEY) or u"").startswith(MISSING):
        subject = u"{0} {1}: QC data missing on {2}".format(prefix, record["dev_id"], worksheet_id)
        where = u"Data Review: {0}/worksheets/{1}/@@pfas-data-review".format(base, worksheet_id)
    else:
        subject = u"{0} {1}: QC criteria not configured on {2}".format(
            prefix, record["dev_id"], worksheet_id)
        where = u"Method Profiles: {0}/@@pfas-method-profiles".format(base)
    body = u"{0}\n\n{1}\n\nWorksheet: {2}/worksheets/{3}\n{4}\n".format(
        subject, record["description"], base, worksheet_id, where)
    try:
        from senaite.pfas import mail_text
        message = mail_text.message(
            portal.getProperty("email_from_address", "lims@localhost"),
            address, subject, body)
        portal.MailHost.send(message, immediate=True)
        logger.info("Notified the QAO (%s) of %s", address, record["dev_id"])
        return True
    except Exception as exc:                                # noqa: BLE001
        logger.error("QAO notification failed for %s: %s",
                     record["dev_id"], exc)
        record["qao_notify_error"] = u"Send failed: {0}".format(exc)
        return False


def retry_notifications(portal):
    """E-mail the QAO each open deviation this module filed that never
    reached the QAO; returns how many went. Asked on a POST (the worker's
    notice tick), never by a page. Nothing is tried, and nothing logged,
    while there is no QAO address or no SMTP host to send it with."""
    if not qao_email(portal):
        return 0
    if not (getattr(getattr(portal, "MailHost", None), "smtp_host", "") or ""):
        return 0
    registry = get_registry(portal)
    sent = 0
    for dev in registry:
        if not dev.get(SIGNATURE_KEY) or dev.get("status") == "closed" \
                or dev.get("qao_notified"):
            continue
        worksheet_id = (dev.get("affected_worksheets") or [u""])[0]
        if _notify_qao(portal, dev, worksheet_id, []):
            dev["qao_notified"] = True
            dev["closure_notes"] = u""
            sent += 1
            logger.info("QAO notified retrospectively for %s", dev.get("dev_id"))
    if sent:
        save_registry(portal, registry)
    return sent
