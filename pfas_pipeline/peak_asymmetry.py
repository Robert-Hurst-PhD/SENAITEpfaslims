"""The peak asymmetry factor of one peak (EPA 537.1 v2.0 §9.3.9).

    As = b / a

measured at 10 % of the peak's height: a is the width of the front half,
from the leading edge to a line dropped perpendicularly from the apex; b
the width of the back half, from that line to the trailing edge. The
height is read above the peak's integration baseline (the straight line
from its start to its end, held level beyond them), and each edge is where
the trace crosses 10 % of that height above the line, interpolated between
the two points either side of it. A peak with no baseline is read above
zero.

measure() returns (factor, None), or (None, why) when the factor cannot be
read: too few points, no height above the baseline, the apex outside the
trace, or an edge that does not fall to 10 % inside the trace.

The 10 % is the method's definition of the factor, not a lab setting; the
acceptance window is the method profile's (idc.asymmetry). Pure.
"""
from __future__ import annotations

# the fraction of the apex height the widths are read at (§9.3.9)
FRACTION = 0.10

TOO_FEW = "the trace has too few points to measure"
NO_HEIGHT = "the peak has no height above its baseline"
APEX_OUTSIDE = "the apex lies outside the trace"
NO_LEADING = "the leading edge does not fall to 10 % of the apex height inside the trace"
NO_TRAILING = "the trailing edge does not fall to 10 % of the apex height inside the trace"
APEX_OFF = "the apex lies outside the peak at 10 % of its height"


def _line(start, end, base_start, base_end):
    """The baseline as a function of time; zero where the peak has none."""
    if None in (start, end, base_start, base_end) or not end > start:
        return lambda x: 0.0
    s, e, b0, b1 = float(start), float(end), float(base_start), float(base_end)

    def at(x):
        if x <= s:
            return b0
        if x >= e:
            return b1
        return b0 + (b1 - b0) * (x - s) / (e - s)
    return at


def _apex_index(t, c, apex, start, end):
    """The highest point of the peak: within its span when it has one,
    else the hilltop reached from the point nearest the apex time."""
    if start is not None and end is not None and end > start:
        inside = [i for i in range(len(t)) if start <= t[i] <= end]
        if inside:
            return max(inside, key=lambda i: c[i])
    k = min(range(len(t)), key=lambda i: abs(t[i] - apex))
    while True:
        step = max((j for j in (k - 1, k + 1) if 0 <= j < len(t)), key=lambda j: c[j])
        if c[step] <= c[k]:
            return k
        k = step


def _crossing(t, c, k, level, direction):
    """The time the trace falls to `level` walking from point k in
    `direction` (-1 to the front, +1 to the back), interpolated; None when
    it does not inside the trace."""
    i = k
    while 0 <= i < len(t) and c[i] > level:
        i += direction
    if not 0 <= i < len(t):
        return None
    j = i - direction                      # the point above the level beside it
    if c[j] == c[i]:
        return t[i]
    return t[i] + (level - c[i]) * (t[j] - t[i]) / (c[j] - c[i])


def measure(t, y, apex, start=None, end=None, base_start=None, base_end=None):
    """(As, None) of the peak at `apex` (minutes) on the trace (t, y), its
    baseline from (start, base_start) to (end, base_end); (None, why) when
    it cannot be read."""
    if len(t) != len(y) or len(t) < 3 or apex is None:
        return None, TOO_FEW
    t = [float(v) for v in t]
    base = _line(start, end, base_start, base_end)
    c = [float(v) - base(x) for x, v in zip(t, y)]
    apex = float(apex)
    if not t[0] <= apex <= t[-1]:
        return None, APEX_OUTSIDE
    k = _apex_index(t, c, apex, start, end)
    height = c[k]
    if not height > 0:
        return None, NO_HEIGHT
    level = FRACTION * height
    front = _crossing(t, c, k, level, -1)
    if front is None:
        return None, NO_LEADING
    back = _crossing(t, c, k, level, +1)
    if back is None:
        return None, NO_TRAILING
    a, b = apex - front, back - apex
    if not (a > 0 and b > 0):
        return None, APEX_OFF
    return round(b / a, 4), None
