# -*- coding: utf-8 -*-
"""Logbook fields that core SENAITE owns (: one owner per
fact).

The collection date was typed twice: on the sample (core Date Sampled, which
the certificate and the EDD print) and on the Chain of Custody logbook (which
the holding-time gate read). Core owns it now. A logbook field named here is
shown from the samples, read-only, never required and never stored; it is
changed on the sample itself.

    CORE_OWNED            {logbook field name: what core field it shows}
    samples_of(context)   the samples of a batch or a worksheet
    date_sampled(sample)  "YYYY-MM-DD" or ""
    summary(dates)        one line for the logbook field
    core_values(context)  {field name: line}

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

CORE_OWNED = {"sample_collection_date": "DateSampled"}


def samples_of(context):
    """Samples of a Batch (its own) or a Worksheet (its analyses')."""
    out, seen = [], set()
    try:
        if getattr(context, "portal_type", "") == "Worksheet":
            cands = [an.getRequest() for an in context.getAnalyses() or []]
        else:
            cands = list(context.getAnalysisRequests() or [])
    except Exception:                                       # noqa: BLE001
        cands = []
    for s in cands:
        if s is not None and s.UID() not in seen:
            seen.add(s.UID())
            out.append(s)
    return out


def date_sampled(sample):
    try:
        dt = sample.getDateSampled()
        return dt.strftime("%Y-%m-%d") if dt else u""
    except Exception:                                       # noqa: BLE001
        return u""


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
