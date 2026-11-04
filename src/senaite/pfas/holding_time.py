# -*- coding: utf-8 -*-
"""Holding time: elapsed days from collection to extraction, against a limit.

Holding times are a hard acceptance criterion (EPA 537.1: 14 days for
drinking water PFAS).

The "Holding Times OK" checkbox is required: an unchecked box fails
the gate. A tick never overrules a measured breach: `EXCEEDED` blocks the
gate whether or not the box is ticked.

An unconfigured limit answers `UNCONFIGURED`, never "pass": the QC criteria's
refuse-to-judge rule, since an absent limit is an unanswered question. Only
EPA 537.1 is seeded; a regulatory value is never invented, so the other
methods read as unconfigured until the lab enters theirs from its method copy.

The two dates: each sample's collection date (core Date Sampled, which the
certificate, the EDD and the CoC print; core_fields.py) and `extraction_date`
from FM-ENV-003. The methods define the holding time as collection ->
EXTRACTION, so the receipt date is not used. Samples are judged one by one
and combined: the worst verdict wins.

No Plone imports: the arithmetic is testable without a container.
"""
from __future__ import absolute_import

import datetime

#: The limit is not configured for this method × matrix. Refuse to judge.
UNCONFIGURED = "unconfigured"
#: One or both dates are missing or unreadable. Refuse to judge.
NO_DATES = "no_dates"
#: Extraction is recorded as happening before collection — a record defect.
INVALID = "invalid"
#: Extracted within the limit.
OK = "ok"
#: Extracted past the limit.
EXCEEDED = "exceeded"
#: The method sets no holding time for this matrix (stored as "none" in
#: Matrices & Units): nothing to judge, and not unconfigured.
NOT_APPLICABLE = "not_applicable"
NONE_SET = "none"

#: Statuses that must not let the Chain of Custody gate pass.
BLOCKING = frozenset([EXCEEDED, INVALID])

#: Unambiguous forms only. `03/04/2025` is NOT accepted: it is 3 April or
#: 4 March depending on who typed it, and a date that decides whether a
#: result is defensible is never guessed. An unreadable date surfaces as
#: NO_DATES, which a human resolves.
_DATE_FORMATS = (
    "%Y-%m-%d",              # what the logbook date widget writes
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
)


def date_to_iso(value):
    """A date, datetime or ISO text as "YYYY-MM-DD"; "" for nothing. A Zope
    DateTime is an instant: its date is the laboratory's calendar day (unset
    or UTC, its UTC date as always). Text is a lab date already: its first
    ten characters."""
    if not value:
        return u""
    if hasattr(value, "toZone") and hasattr(value, "parts"):
        # lab_time loads without Plone; imported relatively, here only, so
        # this module still loads on its own
        from . import lab_time
        if lab_time.active():
            day = lab_time.lab_date(value, "utc")
            return day.isoformat() if day else u""
    try:
        return value.strftime("%Y-%m-%d")
    except AttributeError:
        return (u"{0}".format(value))[:10]


def parse_date(value):
    """A `date` from a logbook value, or None. Never raises.

    An unparseable value returns None, which surfaces as NO_DATES — a refusal,
    not a pass.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = u"{0}".format(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # a longer timestamp (trailing zone, microseconds) still starts with ISO
    try:
        return datetime.datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def limit_for(profile, matrix):
    """Holding-time limit in days for a matrix, or None if not configured.

    Keyed by matrix TITLE, the same as `unit_map` and `matrix_factors`, and
    edited in the same Matrices & Units table: one more fact about one
    matrix.
    A matrix whose Sample holding is "none" has no holding time: not
    applicable, never unconfigured.
    """
    if (profile or {}).get("sample_holding_none"):
        # the retired method-wide switch, on in a profile not yet migrated
        # to per-matrix cells: every matrix has no holding time
        return NONE_SET
    limits = (profile or {}).get("holding_times") or {}
    if not isinstance(limits, dict):
        return None
    raw = limits.get(matrix)
    if raw is None and matrix:
        # tolerate case/whitespace drift between the profile and the SampleType
        wanted = matrix.strip().lower()
        for key, value in limits.items():
            if u"{0}".format(key).strip().lower() == wanted:
                raw = value
                break
    if isinstance(raw, (type(u""), type(""))) and raw.strip().lower() == NONE_SET:
        return NONE_SET
    try:
        days = float(raw)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def evaluate(collected, extracted, limit_days):
    """Judge one holding time.

    Returns a dict carrying the verdict AND the numbers behind it, so a reviewer
    is told "18 of 14 days" rather than "failed".
    """
    result = {
        "status":     UNCONFIGURED,
        "collected":  None,
        "extracted":  None,
        "elapsed_days": None,
        "limit_days": limit_days,
        "message":    u"",
    }
    if limit_days == NONE_SET:
        result["status"] = NOT_APPLICABLE
        result["message"] = u"The method sets no holding time for this matrix."
        return result
    if limit_days is None:
        result["message"] = (
            u"No holding time is configured for this method and matrix. "
            u"Set it in Method Profiles → Matrices & Units, from the "
            u"method document.")
        return result

    start = parse_date(collected)
    end = parse_date(extracted)
    result["collected"] = start
    result["extracted"] = end
    if start is None or end is None:
        result["status"] = NO_DATES
        missing = []
        if start is None:
            missing.append(u"the sample's Date Sampled")
        if end is None:
            missing.append(u"extraction date (Extraction Log)")
        result["message"] = (
            u"Holding time cannot be calculated: missing {0}.".format(
                u" and ".join(missing)))
        return result

    elapsed = (end - start).days
    result["elapsed_days"] = elapsed
    if elapsed < 0:
        result["status"] = INVALID
        result["message"] = (
            u"Extraction is recorded {0} day(s) BEFORE collection "
            u"({1} extracted, {2} collected). One of the two records is "
            u"wrong.".format(abs(elapsed), end, start))
        return result

    if elapsed > limit_days:
        result["status"] = EXCEEDED
        result["message"] = (
            u"Holding time EXCEEDED: extracted {0} day(s) after collection, "
            u"limit {1}. Results are compromised and must be documented in the "
            u"custody condition notes before release.".format(
                elapsed, _fmt_days(limit_days)))
        return result

    result["status"] = OK
    result["message"] = (
        u"Extracted {0} day(s) after collection, within the {1} day "
        u"limit.".format(elapsed, _fmt_days(limit_days)))
    return result


# worst first: the combined verdict of several samples is the worst one
_RANK = [INVALID, EXCEEDED, NO_DATES, UNCONFIGURED, OK, NOT_APPLICABLE]


def extract_limit_for(profile, matrix):
    """The extract holding time in days (extraction to analysis) for a
    matrix, or None: EPA 537.1 §8.5, 28 days.
    Matrices & Units, beside the collection-to-extraction holding time."""
    return limit_for({"holding_times": (profile or {}).get("extract_holding_times") or {}}, matrix)


def processed_limit_for(profile, matrix):
    """The processed-sample holding time in days (homogenisation complete to
    extraction) for a matrix, or None: entered by the lab, nothing seeded."""
    return limit_for({"holding_times": (profile or {}).get("processed_holding_times") or {}}, matrix)


def evaluate_processed(homogenised, extracted, limit_days):
    """Judge a processed sample's holding time, homogenisation complete to
    extraction: the same statuses as evaluate, its own wording.
    With no processed-sample holding time set the clock is not judged
    (NOT_APPLICABLE): nothing is seeded, and an unset value fires no check."""
    if limit_days is None:
        r = evaluate(homogenised, extracted, NONE_SET)
        r["message"] = u"No processed-sample holding time is set for this method and matrix."
        return r
    r = evaluate(homogenised, extracted, limit_days)
    days = r.get("elapsed_days")
    if r["status"] == EXCEEDED:
        r["message"] = (u"Processed-sample holding time EXCEEDED: extracted {0} day(s) after "
                        u"homogenisation, limit {1}.".format(days, _fmt_days(limit_days)))
    elif r["status"] == OK:
        r["message"] = (u"Extracted {0} day(s) after homogenisation, within the {1} day "
                        u"processed-sample holding time.".format(days, _fmt_days(limit_days)))
    elif r["status"] == INVALID:
        r["message"] = (u"The extraction is dated {0} day(s) BEFORE the homogenisation. One of "
                        u"the two records is wrong.".format(abs(days or 0)))
    elif r["status"] == NO_DATES:
        r["message"] = u"Processed-sample holding time cannot be calculated: no homogenisation or extraction date."
    return r


PROCESSED = u"processed:"


def evaluate_extract(extracted, analysed, limit_days):
    """Judge an extract's holding time, extraction to analysis: the same
    statuses as evaluate(), its own wording."""
    r = evaluate(extracted, analysed, limit_days)
    days = r.get("elapsed_days")
    if r["status"] == EXCEEDED:
        r["message"] = (u"Extract holding time EXCEEDED: analysed {0} day(s) after "
                        u"extraction, limit {1}.".format(days, _fmt_days(limit_days)))
    elif r["status"] == OK:
        r["message"] = (u"Analysed {0} day(s) after extraction, within the {1} day "
                        u"extract holding time.".format(days, _fmt_days(limit_days)))
    elif r["status"] == INVALID:
        r["message"] = (u"The run is dated {0} day(s) BEFORE the extraction. One of "
                        u"the two records is wrong.".format(abs(days or 0)))
    elif r["status"] == NO_DATES:
        r["message"] = u"Extract holding time cannot be calculated: no extraction or run date."
    return r


def combine(by_sample):
    """One verdict for a worksheet from {sample id: evaluate(...)}: the worst
    status; its message names the samples it applies to. Each sample is
    judged from its OWN collection date (core Date Sampled), not one date for the batch."""
    if not by_sample:
        return evaluate(None, None, None)
    worst = min(by_sample.values(), key=lambda v: _RANK.index(v["status"]))
    out = dict(worst)
    out["by_sample"] = dict(by_sample)
    hit = sorted(set((u"%s" % sid)[len(PROCESSED):] if (u"%s" % sid).startswith(PROCESSED) else sid
                     for sid, v in by_sample.items() if v["status"] == worst["status"]))
    if worst["status"] != OK or len(by_sample) > 1:
        out["message"] = u"%s%s" % (
            (u"%s: " % u", ".join(hit)) if worst["status"] != OK else u"All %d samples: " % len(
                [k for k in by_sample if k != u"extract" and not (u"%s" % k).startswith(PROCESSED)]),
            worst["message"])
    return out


def table_rows(verdict):
    """The holding time as dates, one row per collection date (a row per
    sample when their dates differ): {"samples", "collected", "limit_days",
    "extract_by", "extracted", "elapsed_days", "ok", "status"}. The extract's
    own holding time ("extract") is not a sample row."""
    groups = {}
    for sid, v in sorted((verdict or {}).get("by_sample", {}).items()):
        if sid == u"extract" or sid == "extract" or (u"%s" % sid).startswith(PROCESSED):
            continue
        key = (v.get("collected"), v.get("extracted"), v.get("limit_days"))
        groups.setdefault(key, []).append((sid, v))
    rows = []
    for (collected, extracted, limit), members in sorted(groups.items(), key=lambda kv: (u"%s" % kv[0][0], u"%s" % kv[0][1])):
        v = members[0][1]
        by = None
        try:
            if collected is not None and limit not in (None, NONE_SET):
                by = collected + datetime.timedelta(days=float(limit))
        except (TypeError, ValueError):
            by = None
        rows.append({"samples": [sid for sid, _v in members],
                     "collected": collected, "limit_days": limit,
                     "limit_text": _fmt_days(limit) if limit not in (None, NONE_SET) else u"",
                     "extract_by": by, "extracted": extracted,
                     "elapsed_days": v.get("elapsed_days"),
                     "ok": v.get("status") == OK, "status": v.get("status")})
    return rows


def _due(start, limit):
    try:
        if start is not None and limit not in (None, NONE_SET):
            return start + datetime.timedelta(days=float(limit))
    except (TypeError, ValueError):
        pass
    return None


def _clock_row(clock, members, start_word, end_word):
    v = members[0][1]
    limit = v.get("limit_days")
    return {"clock": clock, "samples": [sid for sid, _v in members],
            "start": v.get("collected"), "start_word": start_word,
            "limit_text": _fmt_days(limit) if limit not in (None, NONE_SET) else u"",
            "due": _due(v.get("collected"), limit), "end": v.get("extracted"), "end_word": end_word,
            "elapsed_days": v.get("elapsed_days"), "ok": v.get("status") == OK,
            "status": v.get("status"), "note": u""}


def clock_rows(verdict):
    """The CoC tab's holding table: the sample clock (one row per
    collection date), the processed sample's (homogenisation complete to
    extraction, per homogenisation date) and the extract's (extraction to
    analysis). {"clock", "samples", "start", "start_word", "limit_text",
    "due", "end", "end_word", "elapsed_days", "ok", "status", "note"}."""
    by = (verdict or {}).get("by_sample", {}) or {}
    samples = sorted(sid for sid in by if sid != u"extract" and not (u"%s" % sid).startswith(PROCESSED))
    rows = [dict(r, clock=u"sample", samples=r["samples"], start=r["collected"], start_word=u"collected",
                 due=r["extract_by"], end=r["extracted"], end_word=u"extracted", note=u"")
            for r in table_rows(verdict)]
    groups = {}
    for key, v in sorted(by.items()):
        if (u"%s" % key).startswith(PROCESSED):
            groups.setdefault((v.get("collected"), v.get("extracted"), v.get("limit_days")), []).append(
                (key[len(PROCESSED):], v))
    proc = [_clock_row(u"processed", m, u"homogenised", u"extracted")
            for _k, m in sorted(groups.items(), key=lambda kv: (u"%s" % kv[0][0], u"%s" % kv[0][1]))]
    rows += proc or [{"clock": u"processed", "samples": [], "note":
                      u"Not applicable: no sample in this batch was homogenised."}]
    ext = by.get(u"extract")
    if ext:
        rows.append(_clock_row(u"extract", [(None, ext)], u"extracted", u"analysed"))
        rows[-1]["samples"] = samples
    else:
        rows.append({"clock": u"extract", "samples": [], "note": u"No extract holding time is set for this matrix."})
    return rows


def _fmt_days(days):
    """Whole numbers read as `14`, not `14.0`, on a certificate or a gate."""
    try:
        if float(days) == int(float(days)):
            return u"{0}".format(int(float(days)))
    except (TypeError, ValueError):
        pass
    return u"{0}".format(days)
