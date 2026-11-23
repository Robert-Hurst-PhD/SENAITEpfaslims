# -*- coding: utf-8 -*-
"""Logbook fields that core SENAITE owns: one owner per fact.

The collection date is core's Date Sampled, which the certificate, the EDD
and the holding-time gate read; it is never typed again on a logbook. A
logbook field named here is shown from the samples, read-only, never required
and never stored; it is changed on the sample itself.

    CORE_OWNED            {logbook field name: what core field it shows}
    samples_of(context)   the samples of a batch or a worksheet
    date_sampled(sample)  "YYYY-MM-DD" (the lab's day) or ""
    summary(dates)        one line for the logbook field
    core_values(context)  {field name: line}

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

CORE_OWNED = {"sample_collection_date": "DateSampled"}


def samples_of(context):
    """Samples of a Batch (its own) or a Worksheet (its analyses'): a
    reference analysis has no sample and is skipped; a duplicate gives the
    sample it duplicates."""
    out, seen = [], set()
    if getattr(context, "portal_type", "") == "Worksheet":
        cands = [an.getRequest() for an in context.getAnalyses() or [] if hasattr(an, "getRequest")]
        cands = [s for s in cands if getattr(s, "portal_type", None) == "AnalysisRequest"]
    else:
        cands = list(context.getAnalysisRequests() or [])
    for s in cands:
        if s is not None and s.UID() not in seen:
            seen.add(s.UID())
            out.append(s)
    return out


def date_sampled(sample):
    """The collection date on the laboratory's calendar; unset or UTC, its
    UTC date as always."""
    from senaite.pfas import lab_time
    dt = sample.getDateSampled()
    if not dt:
        return u""
    if not lab_time.active():
        return dt.strftime("%Y-%m-%d")
    day = lab_time.lab_date(dt, "utc")
    return day.isoformat() if day else u""


def summary(dates):
    """One line from the samples' dates: the date, a range, or why not."""
    known = sorted(set(d for d in dates if d))
    if not dates:
        return u""
    if not known:
        return u"not set on the samples"
    text = known[0] if len(known) == 1 else u"%s to %s (per sample)" % (known[0], known[-1])
    missing = len([d for d in dates if not d])
    return text + (u"; %d sample(s) without one" % missing if missing else u"")


def core_values(context):
    dates = [date_sampled(s) for s in samples_of(context)]
    return {"sample_collection_date": summary(dates)}
