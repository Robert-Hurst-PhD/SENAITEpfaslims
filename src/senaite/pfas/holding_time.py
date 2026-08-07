# -*- coding: utf-8 -*-
"""Holding time: elapsed days from collection to extraction, against a limit.

CLAUDE.md §10 calls holding times "a hard acceptance criterion" and names EPA
537.1's 14 days for drinking water PFAS. Until now nothing in the system
computed one. "Holding Times OK" was a checkbox a human ticked, no method
profile carried a limit, and the Data Review gate's only evidence that a sample
was in time was that somebody had said so.

WHAT THIS DOES AND DOES NOT CHANGE
----------------------------------
The checkbox stays. §10 requires it and an unchecked box still fails the gate —
this is additive. What changes is that a tick can no longer overrule a measured
breach: `EXCEEDED` blocks the gate whether or not the box is ticked.

Where the limit is not configured, the answer is `UNCONFIGURED`, not "pass".
That is the same refuse-to-judge rule the QC criteria follow: an absent limit is
an unanswered question, and answering it "fine" is how a silent default becomes
a released result. Only EPA 537.1 is seeded, because §10 documents it; §8
forbids inventing a regulatory value for the other two methods, so they read as
unconfigured until a lab enters theirs from its method copy.

WHICH TWO DATES
---------------
`sample_collection_date` from the Chain of Custody logbook and `extraction_date`
from FM-ENV-252. Both were already being recorded; nothing read them together.
The methods define the holding time as collection → EXTRACTION, not collection →
receipt, so `lab_received_date` is deliberately not used.

One authoritative source per fact: the CoC field, not `AnalysisRequest
.getDateSampled()`. The gate is about the custody record, and two sources for
one date is how they drift apart.

This module imports nothing from Plone on purpose — the arithmetic is testable
without a container, and it must stay that way.
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

#: Statuses that must not let the Chain of Custody gate pass.
BLOCKING = frozenset([EXCEEDED, INVALID])

#: Unambiguous forms only. `03/04/2025` is deliberately NOT accepted: it is
#: 3 April or 4 March depending on who typed it, and a module that refuses an
#: unset limit must not then guess a date that decides whether a result is
#: defensible. An unreadable date surfaces as NO_DATES, which a human resolves.
_DATE_FORMATS = (
    "%Y-%m-%d",              # what the logbook date widget writes
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
)


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
    edited in the same Matrices & Units table — because it is one more fact
    about one matrix, and editing those apart is how they drifted before.
    """
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
    try:
        days = float(raw)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def evaluate(collected, extracted, limit_days):
    """Judge one holding time.

    Returns a dict carrying the verdict AND the numbers behind it, so a reviewer
    is told "18 of 14 days" rather than "failed" — a gate that cannot say why it
    refused gets overridden.
    """
    result = {
        "status":     UNCONFIGURED,
        "collected":  None,
        "extracted":  None,
        "elapsed_days": None,
        "limit_days": limit_days,
        "message":    u"",
    }
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
            missing.append(u"sample collection date (Chain of Custody)")
        if end is None:
            missing.append(u"extraction date (FM-ENV-252)")
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


def _fmt_days(days):
    """Whole numbers read as `14`, not `14.0`, on a certificate or a gate."""
    try:
        if float(days) == int(float(days)):
            return u"{0}".format(int(float(days)))
    except (TypeError, ValueError):
        pass
    return u"{0}".format(days)
