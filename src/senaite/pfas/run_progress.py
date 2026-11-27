# -*- coding: utf-8 -*-
"""A raw run while the worker processes it: its state, the words the page
shows of it and when it should be done.

A run awaits its data while the pull waits for the instrument's files
(its expectation written, no .rawrun yet): nothing is processed, no tab, no
band. It is processing from the moment its .rawrun is written (or touched
again after an edit or a processing change) until the import log records it
done. The state is read from the same
helpers as the release gate (raw_edit.unprocessed_text over the import
log; raw_waiting for edits and processing changes), so the band and the
gate never disagree. Pure: Python 2 and 3, no Plone.
"""
from __future__ import division, unicode_literals

import datetime

from senaite.pfas import raw_edit

# the states: the instrument data not arrived yet, a first import (nothing
# stored yet), edits or processing changes being processed again, a run
# done, and a QC store that cannot be read just now
AWAITING, FIRST, EDITS, READY, UNREADABLE = "awaiting", "first", "edits", "ready", "unreadable"
PROCESSING = (FIRST, EDITS)
# the states the strip lists the Integration Review tab in
TAB_STATES = (READY, FIRST, EDITS, UNREADABLE)

UPDATE_TEXT = "Page will update once completed"
UNREADABLE_TEXT = "The run's results cannot be read just now; this page will try again"
# how often the page looks again while the run is processed
POLL_MS = 5000
# how many of the latest raw runs imported the throughput is read from
SEEN_RUNS = 10
STAMP = "%Y-%m-%dT%H:%M:%S"
# the raw run's files whose last write queues it for the worker: its record
# (written when the instrument data arrive, touched again to process it
# again), its edits and its processing changes; the latest is when it started
QUEUE_FILES = (".rawrun", ".overrides.json", ".processing.json")


def state(stem, stored, imports, waiting, arrived=True, queued_at=None):
    """The raw run's state, or None when the tab has nothing to show.
    `stem` the run's file stem ("" without a raw run), `stored` how many
    traces the store holds of it (None when the store cannot be read),
    `imports` the import log's entries for its file, newest first (None
    when the log cannot be read), `waiting` whether its edits or
    processing changes wait for it (raw_waiting), `arrived` whether its
    .rawrun has been written, `queued_at` when the run was last queued
    (STAMP, UTC; the latest of QUEUE_FILES written), or None.

    Nothing stored: the data not arrived (raw_edit.unprocessed_text says
    AWAITING_TEXT) awaits them, with no tab; still being processed (no
    entry yet, or being tried again) is a first import; failed,
    refused or imported with none stored shows no tab, as before. Stored:
    waiting is processing again, unless the latest processing failed or was
    refused after the run was last queued, which the page names instead: an
    edit made after a failure queues the run again, and it is processed. A store or log that cannot be
    read is never read as no run: the page says so and tries again; without
    a raw run it says nothing."""
    if stored is None:
        return UNREADABLE if stem else None
    named = raw_edit.unprocessed_text(imports[:1], arrived) if imports is not None else None
    if stored:
        failed = bool(named) and named != raw_edit.PROCESSING_TEXT
        if failed and queued_at and (imports[0].get("updated_at") or "") < queued_at:
            failed = False                 # queued again since it failed: being processed
        return EDITS if waiting and not failed else READY
    if not stem:
        return None
    if imports is None:
        return UNREADABLE
    if named == raw_edit.AWAITING_TEXT:
        return AWAITING
    return FIRST if named == raw_edit.PROCESSING_TEXT else None


def estimate(started, now, injections, traces, seen):
    """When the run should be done (a naive UTC datetime), or None with no
    basis. `started` when it was queued, `now` the clock, `injections` and
    `traces` its size (traces None on a first import, nothing stored yet),
    `seen` [(injections, traces, seconds)] of the runs the worker processed
    lately (observations).

    The throughput seen is their seconds over their traces, pooled; a first
    import's traces are its injections at the traces an injection held in
    those runs. Once the time elapsed passes the estimate, the throughput
    seen does not hold for this run, and there is no estimate."""
    seen = [s for s in seen or () if s[0] > 0 and s[1] > 0 and s[2] > 0]
    if started is None or not seen:
        return None
    seen_traces = sum(s[1] for s in seen)
    per_trace = sum(s[2] for s in seen) / seen_traces
    if not traces:
        traces = (injections or 0) * seen_traces / sum(s[0] for s in seen)
    if not traces:
        return None
    done = started + datetime.timedelta(seconds=round(traces * per_trace))
    return done if done > now else None


def observations(rows, queued_at):
    """[(injections, traces, seconds)] of the raw runs imported (the store's
    raw_runs_done rows: file, updated_at, traces, injections): from when the
    run's file was last queued (`queued_at(file)`, a naive UTC datetime or
    None) to when the import log recorded it done. A run queued again since
    is being processed now and measures nothing."""
    out = []
    for r in rows or ():
        try:
            done = datetime.datetime.strptime(r.get("updated_at") or "", STAMP)
        except ValueError:
            continue
        queued = queued_at(r.get("file"))
        if queued is None or done <= queued:
            continue
        out.append((r.get("injections") or 0, r.get("traces") or 0, (done - queued).total_seconds()))
    return out


def band_text(started, done=None):
    """The band's line: "Processing run · Started: HH:MM · Est. completion:
    HH:MM", the times already on the lab's clock; without an estimate, no
    completion; without a start, the first words alone."""
    text = "Processing run"
    if started:
        text += " · Started: %s" % started
        if done:
            text += " · Est. completion: %s" % done
    return text
