# -*- coding: utf-8 -*-
"""A raw run's chromatograms as kept for review (the raw_traces table).

Each quantifier and qualifier trace of each injection is stored with its
peak, times and intensities packed as little-endian 64-bit floats. A stored
trace keeps one stretch at full resolution (full_resolution): the
analyte's search window and every span an edit may be judged on (the
automatic peak, the manual peak, each candidate), widened by the points the
engine's manual measure reads beyond an edge, and beyond every neighbour a
perpendicular drop or a tangent skim from those edges can reach (`reach`).
Any edge inside the record's "full_res" is therefore measured on the
stored trace exactly as the worker measures it on the whole trace, on any
baseline. The rest is thinned evenly (decimate).

Size: at most MAX_POINTS points when the full-resolution stretch is small;
that stretch holds at most MAX_FULL_POINTS, the neighbours' reach
included (cut back evenly about the edges past it), and the rest at least
REST_POINTS, so no stored trace holds more than MAX_STORED_POINTS. A record
offers at most MAX_CANDIDATES candidate peaks.

A kept record's "manual" is the edit ({kind, by, at, apex?, baseline?}) and
its "auto" a subset of the automatic peak; a row's derived_from record uses
the same names otherwise ("manual": true, "auto": the whole automatic
record): the two are never read as one.

Written by the worker, read by Data Review's Raw Data tab. Pure; Python 2.7
and 3.
"""
from __future__ import absolute_import, division

import bisect
import json
import struct

MAX_POINTS = 600
MAX_FULL_POINTS = 1200
REST_POINTS = 100
MAX_STORED_POINTS = MAX_FULL_POINTS + REST_POINTS
MAX_CANDIDATES = 20


def pack(values):
    return struct.pack("<%dd" % len(values), *[float(v) for v in values])


def unpack(blob):
    blob = bytes(blob or b"")
    return list(struct.unpack("<%dd" % (len(blob) // 8), blob))


def decimate(t, y, start, end, max_points=MAX_POINTS):
    """(t, y) with every point in [start, end] (the full-resolution
    stretch) and an even selection of the rest, the first and last points
    among them: at most max(max_points, the stretch's points + REST_POINTS)
    in all. A trace that fits is kept whole."""
    t, y = list(t), list(y)
    inside = set(i for i, v in enumerate(t) if start is not None and start <= v <= end)
    rest = [i for i in range(len(t)) if i not in inside]
    room = max(max_points - len(inside), REST_POINTS)
    if len(rest) <= room:
        return t, y
    # room >= 2 points of the rest, evenly spaced from its first to its last;
    # the step exceeds 1, so no two round to the same point
    step = (len(rest) - 1) / float(room - 1)
    keep = sorted(inside | set(rest[int(round(k * step))] for k in range(room)))
    return [t[i] for i in keep], [y[i] for i in keep]


def _indices(t, span):
    """The index range of the points of t within the (t0, t1) span; a span
    between two points is the nearer point."""
    lo, hi = min(span), max(span)
    i0 = bisect.bisect_left(t, lo)
    i1 = bisect.bisect_right(t, hi) - 1
    if i1 < i0:
        near = min((i for i in (i1, i0) if 0 <= i < len(t)), key=lambda i: abs(t[i] - lo))
        return near, near
    return max(i0, 0), min(i1, len(t) - 1)


def full_resolution(t, spans, margin, smooth_window, max_points=MAX_FULL_POINTS, reach=None):
    """(lo, hi, e0, e1): the index range lo..hi a stored trace keeps at full
    resolution, and the range e0..e1 an edge may lie in.

    e0..e1 holds every (t0, t1) span in `spans` (the first is the peak's
    own: past the size limit the rest is cut back around it, evenly on
    either side). lo..hi is e0..e1 widened by `margin` points each side,
    the most an engine's manual measure reads beyond an edge (its edge
    levels and the smoothing about its apex), and, with `reach`, a
    function of (e0, e1) giving (r0, r1), the farthest indices a drop's or
    a skim's neighbour walk from an edge in e0..e1 reads, widened by
    `margin` beyond those, as far as the size limit leaves room, evenly on
    either side; where it reaches a trace end it holds that end's first
    `smooth_window` points, which the smoothing of a point near the end is
    fitted over. lo..hi holds at most `max_points` points."""
    n = len(t)
    if not n:
        return 0, -1, 0, -1
    ranges = [_indices(t, s) for s in spans if s and s[0] is not None and s[1] is not None]
    if not ranges:
        return 0, n - 1, 0, n - 1
    p0, p1 = ranges[0]
    e0, e1 = min(r[0] for r in ranges), max(r[1] for r in ranges)
    # room for the edges: the stretch less both margins and an end's window
    cap = max(max_points - 2 * margin - smooth_window, 1)
    if e1 - e0 + 1 > cap:
        room = cap - (p1 - p0 + 1)
        if room < 0:
            # the peak's own span alone is over the limit: its middle is kept
            e0 = (p0 + p1) // 2 - cap // 2
            e1 = e0 + cap - 1
        else:
            left = min(p0 - e0, max(room // 2, room - (e1 - p1)))
            e0, e1 = p0 - left, p1 + min(e1 - p1, room - left)
    lo, hi = max(e0 - margin, 0), min(e1 + margin, n - 1)
    if reach is not None:
        r0, r1 = reach(e0, e1)
        want_lo, want_hi = max(min(r0, e0) - margin, 0), min(max(r1, e1) + margin, n - 1)
        # the neighbours' reach within what the limit leaves beside the edges
        room = max(max_points - smooth_window - (hi - lo + 1), 0)
        left = min(lo - want_lo, max(room // 2, room - (want_hi - hi)))
        lo, hi = lo - left, hi + min(want_hi - hi, room - left)
    if lo == 0:
        hi = max(hi, min(smooth_window - 1, n - 1))
    if hi == n - 1:
        lo = min(lo, max(n - smooth_window, 0))
    return lo, hi, e0, e1


def keep(t, y, spans, margin, smooth_window, reach=None):
    """(t, y, full_res): the trace as stored and [t0, t1], the times an edge
    may lie between for the stored trace to measure as the whole trace
    does: the whole trace when it is stored whole."""
    return keep_reach(t, y, spans, margin, smooth_window, reach)[:3]


def keep_reach(t, y, spans, margin, smooth_window, reach=None):
    """(t, y, full_res, full_res_reach): keep's, and [t0, t1] the times the
    stored trace holds at full resolution (full_resolution's lo..hi, the
    whole trace when it is stored whole): a drop or a skim whose
    neighbours and the points read beyond them lie inside is measured on
    the stored trace as on the whole trace."""
    t, y = list(t), list(y)
    if not t:
        return t, y, None, None
    lo, hi, e0, e1 = full_resolution(t, spans, margin, smooth_window, reach=reach)
    st, sy = decimate(t, y, t[lo], t[hi])
    if len(st) == len(t):
        return st, sy, [t[0], t[-1]], [t[0], t[-1]]
    return st, sy, [t[e0], t[e1]], [t[lo], t[hi]]


def read(conn, batch_id, injection=None, analytes=None, role=None):
    """The batch's stored traces, t / y unpacked and peak parsed, in the
    order they were stored. Each filter given narrows the rows in SQL (values
    are bound parameters): one injection, a list of analytes, one role. No
    filter reads the whole batch; an empty list of analytes reads none."""
    where, args = ["batch_id=?"], [batch_id]
    if injection is not None:
        where.append("injection=?")
        args.append(injection)
    if analytes is not None:
        analytes = list(analytes)
        if not analytes:
            return []
        where.append("analyte IN (%s)" % ",".join("?" * len(analytes)))
        args.extend(analytes)
    if role is not None:
        where.append("role=?")
        args.append(role)
    rows = conn.execute("SELECT injection, analyte, transition, role, t, y, peak FROM raw_traces "
                        "WHERE " + " AND ".join(where) + " ORDER BY id", args).fetchall()
    return [{"injection": r[0], "analyte": r[1], "transition": r[2], "role": r[3],
             "t": unpack(r[4]), "y": unpack(r[5]), "peak": json.loads(r[6] or "{}")} for r in rows]


def envelope(t, y, lo, hi, buckets=60):
    """(t, y) of the points with lo <= t <= hi reduced to at most 2 * buckets
    points: each of `buckets` runs of consecutive points keeps its lowest and
    highest point, in time order, so the window's global maximum (the apex)
    is always kept exactly. A window of 2 * buckets points or fewer is
    returned unchanged."""
    idx = [i for i in range(min(len(t), len(y))) if lo <= t[i] <= hi]
    if len(idx) <= 2 * buckets:
        return [t[i] for i in idx], [y[i] for i in idx]
    keep, n = [], len(idx)
    for b in range(buckets):
        run = idx[b * n // buckets:(b + 1) * n // buckets]
        if not run:
            continue
        low = min(run, key=lambda i: y[i])
        high = max(run, key=lambda i: y[i])
        keep.extend(sorted(set([low, high])))
    return [t[i] for i in keep], [y[i] for i in keep]


def exists(conn, batch_id):
    """True when the batch has any stored trace; reads one row, unpacks none."""
    return conn.execute("SELECT 1 FROM raw_traces WHERE batch_id=? LIMIT 1", (batch_id,)).fetchone() is not None
