# -*- coding: utf-8 -*-
"""A compound's expected retention time, set from a peak under review.

The method profile owns each compound's expected time, the Integration
tab's compound row (integration.analytes[<compound>].rt). The time drifts
from run to run and is updated routinely, so an analyst may set it from the
quantifier peak of a run under review (Data Review's Integration Review card), and it
is not a setting an issued method revision freezes: `exempt` leaves every
expected time out of what method_revisions fingerprints, and the value
carries from run to run without a new issue.

The analyst sets it from the quantifier peak (the card's menu) or by
dragging the expected-time line on the chromatogram to the peak; a dragged
time must lie inside every stored trace of the compound in that injection
(`span`): the run refuses a compound whose expected time a transition's
chromatogram does not hold.

    PATH                          where one compound's time lives
    exempt(profile)               a copy without the expected times
    posted_time(value)            a dragged time read strictly, or None
    span(traces)                  (lo, hi) every trace of the compound holds
    plan(profile, compound, rt, check=None, pending=False, span=None)
                                  -> (problem, (old, new))
    applied(profile, compound, new)          a copy with the time set
    history_reason(ws, injection, compound)  what the change history says
    change_reason(ws, injection, compound, old, new, dragged)
                                  the same, with how and both times

Pure; Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import copy
import math

PATH = (u"integration", u"analytes")
FIELD = u"rt"
# a time is kept to the ten-thousandth of a minute: finer than any sampling,
# coarse enough that a float's tail never reads as a change
PLACES = 4

NO_ROW = u"%s has no compound row on the method's Integration tab."
NO_PEAK = u"%s has no detected quantifier peak in this injection."
SAME = u"The expected retention time of %s is already %s min."
PENDING = u"An edit of this peak waits for the run to be processed: set the time once it is."
NO_SPAN = u"%s has no acquisition in this injection."
OUTSIDE = u"%s is acquired from %.3f to %.3f min: drag the line inside."


def exempt(profile):
    """A copy of `profile` with every compound's expected time removed."""
    p = copy.deepcopy(profile or {})
    rows = (p.get(PATH[0]) or {}).get(PATH[1])
    if isinstance(rows, dict):
        for row in rows.values():
            if isinstance(row, dict):
                row.pop(FIELD, None)
    return p


def _rows(profile):
    rows = ((profile or {}).get(PATH[0]) or {}).get(PATH[1])
    return rows if isinstance(rows, dict) else {}


def _time(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, PLACES) if not (math.isnan(v) or math.isinf(v)) and v > 0 else None


def posted_time(value):
    """A time posted from the dragged line: a finite number of minutes above
    0, kept to PLACES; None for anything else."""
    if isinstance(value, (list, tuple, dict)):
        return None
    return _time(value)


def span(traces):
    """(lo, hi): the times every stored trace given covers, from the latest
    first time to the earliest last time (a stored trace keeps its first and
    last acquired points); None when no trace holds a time."""
    ends = [(t["t"][0], t["t"][-1]) for t in traces or [] if (t or {}).get("t")]
    if not ends:
        return None
    lo, hi = max(e[0] for e in ends), min(e[1] for e in ends)
    return (lo, hi) if lo <= hi else None


def applied(profile, compound, new):
    """A copy of `profile` with `compound`'s expected time set to `new`."""
    p = copy.deepcopy(profile or {})
    p[PATH[0]][PATH[1]][compound][FIELD] = new
    return p


def plan(profile, compound, found_rt, check=None, pending=False, span=None):
    """(problem, None) or (None, (old, new)): set `compound`'s expected time
    to `found_rt`, the found apex or the time the line was dragged to.
    Refused when the method has no Integration row for it, the peak is not
    detected, an edit of it waits for the run, the time lies outside `span`
    (lo, hi) where one is given (empty: no trace holds a time), the time is
    already that, or the method's own Integration check finds a new problem
    with the time set (`check(profile)` -> [error], as the method editor's
    save runs it: a partner's window it would overlap)."""
    rows = _rows(profile)
    if compound not in rows or not isinstance(rows.get(compound), dict):
        return NO_ROW % compound, None
    new = _time(found_rt)
    if new is None:
        return NO_PEAK % compound, None
    if pending:
        return PENDING, None
    if span is not None:
        if not span:
            return NO_SPAN % compound, None
        if not span[0] <= new <= span[1]:
            return OUTSIDE % (compound, span[0], span[1]), None
    old = rows[compound].get(FIELD)
    if _time(old) == new:
        return SAME % (compound, new), None
    if check is not None:
        before = set(check(profile) or [])
        after = [e for e in check(applied(profile, compound, new)) or [] if e not in before]
        if after:
            return after[0], None
    return None, (old, new)


def history_reason(worksheet_id, injection, compound):
    """The change history's reason: the worksheet and injection whose peak
    set the time."""
    return u"From the peak of %s in %s, worksheet %s" % (compound, injection, worksheet_id)


def _shown(value):
    v = _time(value)
    return u"none" if v is None else u"%s" % v


def change_reason(worksheet_id, injection, compound, old, new, dragged=False):
    """The change history's reason with how the time was set and the times
    before and after: "Dragged on the chromatogram of ..." or "From the
    peak of ...", then ": <old> to <new> min"."""
    how = (u"Dragged on the chromatogram of %s in %s, worksheet %s" % (compound, injection, worksheet_id)
           if dragged else history_reason(worksheet_id, injection, compound))
    return u"%s: %s to %s min" % (how, _shown(old), _shown(new))
