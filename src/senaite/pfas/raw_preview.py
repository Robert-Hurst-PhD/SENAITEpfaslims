# -*- coding: utf-8 -*-
"""A manual peak previewed on a stored trace, as the worker will measure it,
and the method's limits on a manual change.

    classic(t, y, start, end, baseline, smooth_points, edge_points, levels, bounds)
    adaptive(t, y, start, end, baseline, m, levels, bounds)
        the peak between the analyst's edges: its edge indices and times,
        baseline ends, apex, height above the baseline and area, on one of
        the four baselines (BASELINES) or on levels set by hand. Each
        mirrors its engine's manual measure exactly
        (raw_integrate.integrate_between with a trapezoid area;
        raw_adaptive.between), held equal to it by tests/test_raw_preview.py
        on tests/raw_preview_parity.json
    method_baseline(named)
        the automatic baseline a method's Integration baseline names
    preview(engine, t, y, start, end, baseline, sigma, ...)
        either, with its S/N: the height over the trace's noise sigma (the
        sigma the automatic call read its S/N against, the one the worker
        records a manual peak's S/N against). On a trace kept for review
        (raw_traces) it is the worker's measure of the whole trace for
        edges within the record's "full_res", read with the record's
        "sigma", "edge_points" and "smooth_points" (Classic) or
        "smoothing" (Adaptive)
    walk_reach(sm, n, i, step)
        how far a drop's or a skim's neighbour walk from an edge can run:
        what the worker keeps at full resolution beyond the edges
    read_margin(engine, smooth_points, edge_points, m)
        how many points beyond an edge the engine's manual measure reads
    read_reach(engine, t, y, s, e, ...)
        the stored samples a drop's or a skim's measure from the edges at
        s and e reads at most: what must lie at full resolution
    half_widths(engine, t, y, measured, ...)
        a measured peak's width at half its height either side of its apex:
        its standard deviation there, over HALF_WIDTH_SIGMA
    apex_preview(t, candidate)
        another apex chosen as found: the candidate's own measures, as the
        engine found it and the worker replays it, with its edge indices
        in the stored trace `t`
    area_change_pct(auto_area, manual_area)
    edit_problem(kind, auto_area, manual_area, sn, min_change_pct, min_sn)
        why the method refuses an edit, or None
    manual_limits(integration, keyword)
        the smallest manual change and the smallest S/N for a manual peak,
        the compound's own over the method's

`t` and `y` are plain lists of floats (minutes, counts). Pure, no numpy;
Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

import math

# a manual peak's baselines: valley to valley (a line between the two edge
# levels); a perpendicular drop (one line under the peak and its neighbour,
# from the pair's outer edges, cut by drop lines at the edges); flat at the
# lower edge level, a drop line to it from each edge; a tangent skim (a line
# from the signal at the start, on a parent peak's tail, to the signal at
# the end)
BASELINES = ("valley", "drop", "flat", "skim")
# an automatic peak is measured on the valley line or flat at the lower edge
AUTO_BASELINES = ("valley", "flat")
# a method's or a compound's stored Integration baseline "drop" is the flat
# line at the lower edge
STORED_METHOD_BASELINES = {"drop": "flat"}
# the smallest manual change when the method sets none, in %
DEFAULT_MIN_MANUAL_CHANGE_PCT = 5.0

# The rules for a dropped baseline, as method settings with per-compound
# overrides: key -> (whole number, default, smallest allowed, whether the
# smallest is itself allowed). A blank setting is the default; search_amp_sn
# has none of its own: the smallest S/N for a manual peak when set, else
# DEFAULT_SEARCH_AMP_SN.
REVIEW_RULES = (
    ("edge_points", True, 6, 1, True),
    ("min_peak_points", True, 5, 3, True),
    ("edge_sigma", False, 2.0, 0, False),
    ("drop_valley_max_pct", False, 25.0, 0, False),
    ("skim_ratio_pct", False, 25.0, 0, False),
    ("search_slope", False, 0.7, 0, False),
    ("search_amp_sn", False, None, 0, False),
    ("search_smooth_pct", False, 50.0, 0, False),
    ("candidate_min_points", True, 3, 2, True),
    ("candidate_min_fwhm_pct", False, 40.0, 0, False))
REVIEW_KEYS = tuple(rule[0] for rule in REVIEW_RULES)
REVIEW_DEFAULTS = dict((rule[0], rule[2]) for rule in REVIEW_RULES)
DEFAULT_SEARCH_AMP_SN = 3.0
# the settings a compound cannot override: the method's alone
REVIEW_METHOD_ONLY = ("search_slope", "search_smooth_pct")


# ── the engines' smoothing ──────────────────────────────────────────────────

def _quadratic_at(seg, x):
    """The least-squares quadratic through `seg` (at 0, 1, ...), at x."""
    n = len(seg)
    c = (n - 1) / 2.0
    s0 = float(n)
    s2 = s4 = sy = suy = su2y = 0.0
    for i, v in enumerate(seg):
        u = i - c
        u2 = u * u
        s2 += u2
        s4 += u2 * u2
        sy += v
        suy += u * v
        su2y += u2 * v
    b = suy / s2
    det = s0 * s4 - s2 * s2
    a0 = (sy * s4 - s2 * su2y) / det
    a2 = (s0 * su2y - s2 * sy) / det
    u = x - c
    return a0 + b * u + a2 * u * u


def _savgol_at(y, i, n):
    """The Savitzky-Golay smoothing (second order, `n` points, odd) of y at
    index i: the quadratic fitted over the n points centred on i, and within
    half a window of either end the one fitted over the first or last n
    points (scipy's savgol_filter, mode "interp")."""
    half = n // 2
    if i < half:
        return _quadratic_at(y[:n], i)
    if i >= len(y) - half:
        return _quadratic_at(y[len(y) - n:], i - (len(y) - n))
    return _quadratic_at(y[i - half:i + half + 1], half)


def _classic_smoothing(y, smooth_points):
    """The classic engine's window: `smooth_points`, cut to the trace's
    length (odd), no smoothing below 5 points."""
    n = min(int(smooth_points), len(y) - (1 - len(y) % 2))
    return n if n >= 5 else None


def _adaptive_smoothing(y, m):
    """The adaptive engine's window, 2m + 1 points, when the trace holds more
    than 2m + 3; else no smoothing."""
    return 2 * m + 1 if len(y) > 2 * m + 3 else None


def _smoothed(y, i, n):
    return y[i] if n is None else _savgol_at(y, i, n)


# ── shared measures ─────────────────────────────────────────────────────────

def _nearest(t, x):
    """The index of t nearest x, the first of two equally near."""
    best = 0
    for i in range(1, len(t)):
        if abs(t[i] - x) < abs(t[best] - x):
            best = i
    return best


def _interp(x, x0, x1, y0, y1):
    """y at x on the line through (x0, y0) and (x1, y1), as numpy's interp
    computes it between two points."""
    if x == x1:
        return y1
    return (y1 - y0) / (x1 - x0) * (x - x0) + y0


def _mean(values):
    return sum(values) / len(values)


def _trapezoid(t, v):
    return sum((t[i + 1] - t[i]) * (v[i + 1] + v[i]) / 2.0 for i in range(len(t) - 1))


def _apex(y, s, e, n):
    """(index, smoothed value) of the highest smoothed point in [s, e], the
    first of equals."""
    best, top = s, _smoothed(y, s, n)
    for i in range(s + 1, e + 1):
        v = _smoothed(y, i, n)
        if v > top:
            best, top = i, v
    return best, top


# ── the engines' manual measure ─────────────────────────────────────────────

def method_baseline(named):
    """The baseline an automatic peak is measured on, from a method's or a
    compound's Integration baseline: "valley" or "flat" (a stored "drop" is
    the flat line); None for anything else."""
    named = STORED_METHOD_BASELINES.get(named, named)
    return named if named in AUTO_BASELINES else None


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and value == value and value not in (float("inf"), float("-inf")))


def check_levels(levels):
    """[left, right] of baseline levels set by hand, two finite numbers in
    counts, or None; ValueError otherwise."""
    if levels is None:
        return None
    if not isinstance(levels, (list, tuple)) or len(levels) != 2 or not all(_finite(v) for v in levels):
        raise ValueError("the baseline levels are two numbers")
    return [float(levels[0]), float(levels[1])]


def _outward(sm, n, i, step, rise):
    """(top, far edge) of the neighbouring peak beyond index i, `step` -1
    before it and +1 after it, on the smoothed signal sm(i) of a trace of
    n points: from i the signal falls while it falls to the valley, climbs
    while it rises to the neighbour's top, then falls while it falls to
    its far edge. A neighbour is a peak only when its top lies inside the
    trace (a climb to the trace's end is a sloped baseline), rises at
    least `rise` above that valley (the method's peak search amplitude
    times the trace's noise) and the signal falls at least `rise` again to
    its far edge; None when it does not, or with no `rise` to judge it
    by."""
    j = i
    while 0 <= j + step < n and sm(j + step) <= sm(j):
        j += step
    valley = j
    while 0 <= j + step < n and sm(j + step) > sm(j):
        j += step
    top = j
    if rise is None or top in (0, n - 1) or not sm(top) - sm(valley) >= rise:
        return None
    while 0 <= j + step < n and sm(j + step) <= sm(j):
        j += step
    if not sm(top) - sm(j) >= rise:
        return None
    return top, j


def walk_reach(sm, n, i, step):
    """The index farthest beyond i, `step` -1 before it and +1 after it,
    that the neighbour walk (_outward) from i or from any edge between i
    and the peak ends at, whatever the rise it is judged by: the end of
    the walk's three runs from i (falls, climbs, falls), or its valley
    where the climb runs to the trace's end (no neighbour there). A walk
    from an edge further in that passes i is then falling, climbing or
    falling again through i: the first two go on as the walk from i does,
    and the third stops at the valley the walk from i falls to first."""
    j = i
    while 0 <= j + step < n and sm(j + step) <= sm(j):
        j += step
    valley = j
    while 0 <= j + step < n and sm(j + step) > sm(j):
        j += step
    if j in (0, n - 1):
        return valley
    while 0 <= j + step < n and sm(j + step) <= sm(j):
        j += step
    return j


def read_margin(engine, smooth_points=None, edge_points=None, m=None):
    """How many points beyond an edge, and about the apex, the engine's
    manual measure reads. Classic: its edge levels read edge_points beyond
    each edge and its smoothing half its window either side. Adaptive: its
    line reads m beyond each edge, and its apex parabola the smoothed points
    beside the apex, each smoothed over m either side, so m + 1."""
    if engine == "adaptive":
        return max(int(m), 1) + 1
    return max(int(edge_points), int(smooth_points) // 2)


def _engine_smoothing(engine, y, smooth_points=None, m=None):
    """The window the engine smooths the stored trace with (None: none)."""
    if engine == "adaptive":
        return _adaptive_smoothing(y, max(int(m), 1))
    return _classic_smoothing(y, smooth_points)


def read_reach(engine, t, y, s, e, smooth_points=None, edge_points=None, m=None):
    """(i0, i1): the indices of the stored trace (t, y) that a perpendicular
    drop's or a tangent skim's measure from the edges at indices s and e
    reads at most, on the engine's smoothed signal: the neighbour walk
    either way (walk_reach), one sample past where it stops (the walk
    compares it), and read_margin beyond (the levels at an outer edge and
    the smoothing of the samples read). The worker keeps the same span at
    full resolution, so a measure whose reach lies inside the record's
    full_res_reach is the worker's."""
    n = len(y)
    sm = _memo(y, _engine_smoothing(engine, y, smooth_points, m))
    margin = read_margin(engine, smooth_points, edge_points, m)
    return (max(walk_reach(sm, n, s, -1) - 1 - margin, 0),
            min(walk_reach(sm, n, e, 1) + 1 + margin, n - 1))


# a Gaussian peak's half width at half its height, in its standard deviations
HALF_WIDTH_SIGMA = math.sqrt(2.0 * math.log(2.0))


def half_widths(engine, t, y, measured, smooth_points=None, m=None):
    """[before, after]: how far, in minutes, a measured peak (a preview's
    result, or another apex's) falls to half its height either side of its
    apex, on the engine's smoothed signal above its line, the line carried
    on past its edges so an edge set short cannot cut the width; the
    crossing is read linearly between the two samples about it. None for a
    side whose signal turns up again (a neighbour) or reaches the trace's
    end before half height, and both None with no height."""
    s, e = measured["s"], measured["e"]
    a = _nearest(t, measured["apex"])
    sm = _memo(y, _engine_smoothing(engine, y, smooth_points, m))
    b0, b1 = measured["base_start"], measured["base_end"]
    if t[e] == t[s]:
        return [None, None]

    def above(i):
        return sm(i) - _interp(t[i], t[s], t[e], b0, b1)
    half = above(a) / 2.0
    if not half > 0:
        return [None, None]

    def side(step):
        i = a
        while 0 <= i + step < len(t):
            j = i + step
            vi, vj = above(i), above(j)
            if vj <= half:
                x = t[j] + (half - vj) / (vi - vj) * (t[i] - t[j])
                return abs(measured["apex"] - x)
            if sm(j) > sm(i):
                return None
            i = j
        return None
    return [side(-1), side(1)]


def _rise(sigma, amp):
    """How far a neighbour's top rises above its valley at least: the peak
    search amplitude `amp` (DEFAULT_SEARCH_AMP_SN when None) times the
    trace's noise sigma; None without a sigma."""
    if sigma is None:
        return None
    return (DEFAULT_SEARCH_AMP_SN if amp is None else amp) * sigma


def _line(t, sm, s, e, baseline, ends, levels, bounds, rise, skip=()):
    """The manual baseline over the edges s and e: {"b": [at s, at e],
    "line": the whole line as a function of an index, "outer": [L, R] the
    indices its ends are read at, "tops": [(side, top)] the neighbours'
    tops, side -1 before the peak and +1 after it, a side in `skip` left
    out}. `ends(i, j)` is the engine's [level at i, level at j]; `levels`, set by hand,
    replace the two levels the baseline reads. valley: the edge levels at
    s and e; flat: the lower of them, level; drop: the levels at the
    pair's outer edges (`bounds`, else each neighbour's far edge, else the
    edge itself), the line between them; skim: the smoothed signal at s
    and at e. A neighbour is found by _outward, `rise` above its valley."""
    left = right = None
    if baseline in ("drop", "skim"):
        left = None if -1 in skip else _outward(sm, len(t), s, -1, rise)
        right = None if 1 in skip else _outward(sm, len(t), e, 1, rise)
    tops = [(side, x[0]) for side, x in ((-1, left), (1, right)) if x is not None]
    lo, hi = s, e
    if baseline == "drop":
        if bounds is not None:
            lo, hi = _nearest(t, min(bounds)), _nearest(t, max(bounds))
            if lo > s or hi < e:
                raise ValueError("the drop's baseline runs under the whole pair")
        else:
            lo = left[1] if left is not None else s
            hi = right[1] if right is not None else e
    if levels is not None:
        lv, rv = levels
    elif baseline == "skim":
        lv, rv = sm(s), sm(e)
    else:
        lv, rv = ends(lo, hi)
    if baseline == "flat":
        lv = rv = min(lv, rv)
    x0, x1 = t[lo], t[hi]

    def line(i):
        return _interp(t[i], x0, x1, lv, rv)
    return {"b": [line(s), line(e)], "line": line, "outer": [lo, hi], "tops": tops,
            "ends": ends, "rise": rise, "skip": skip}


def _share(part, whole):
    """part over whole in %, when it reads as a share of a peak: between 0
    and 100 (the valley no deeper than the line, the peak no taller than
    the one it is read against); else None."""
    if not whole > 0:
        return None
    share = part / whole * 100.0
    return share if 0.0 <= share <= 100.0 else None


def _shares(t, sm, s, e, a, height, baseline, ln):
    """(valley share, skim share, the sides whose neighbour is no peak
    beside this one), each share in % and None where it does not apply.
    A drop's: for each neighbour, the lowest smoothed point between the
    two tops above the line over the smaller peak's height above it, the
    larger of the two sides; a neighbour whose share is no share (_share)
    is no neighbour, and the line is drawn again without it. A skim's: the
    height over the parent's, the parent the taller neighbour, its height
    above the line between the pair's outer edge levels (its own
    baseline); none when it is no share."""
    if baseline == "drop":
        out, bad = None, ()
        for side, top in ln["tops"]:
            lo, hi = min(a, top), max(a, top)
            v = lo
            for i in range(lo + 1, hi + 1):
                if sm(i) < sm(v):
                    v = i
            share = _share(sm(v) - ln["line"](v), min(height, sm(top) - ln["line"](top)))
            if share is None:
                bad += (side,)
            else:
                out = share if out is None else max(out, share)
        return out, None, bad
    if baseline == "skim" and ln["tops"]:
        parent = ln["tops"][0][1]
        for _side, top in ln["tops"][1:]:
            if sm(top) > sm(parent):
                parent = top
        outer = _line(t, sm, s, e, "drop", ln["ends"], None, None, ln["rise"], ln["skip"])
        return None, _share(height, sm(parent) - outer["line"](parent)), ()
    return None, None, ()


def _memo(y, n):
    """The smoothed signal as a function of an index, each point once."""
    seen = {}

    def sm(i):
        if i not in seen:
            seen[i] = _smoothed(y, i, n)
        return seen[i]
    return sm


def _check(baseline, levels):
    if baseline not in BASELINES:
        raise ValueError("baseline is one of %s" % ", ".join(BASELINES))
    return check_levels(levels)


def _measures(t, y, s, e, a, top, build, sm, baseline, levels, clip):
    """The measures every engine returns over the line `build(skip)` draws
    (_line), drawn again without a neighbour that is no peak beside this
    one (_shares): the trapezoid above it (`clip` the engine's own reading
    of a part below it; none with levels set by hand, where the signal
    below the line counts against the area), the shares, the baseline and
    its levels."""
    skip = ()
    while True:
        ln = build(skip)
        b0, b1 = ln["b"]
        height = top - _interp(t[a], t[s], t[e], b0, b1)
        valley, skim, bad = _shares(t, sm, s, e, a, height, baseline, ln)
        if not bad:
            break
        skip += bad
    base = [_interp(t[i], t[s], t[e], b0, b1) for i in range(s, e + 1)]
    above = [y[i] - base[i - s] for i in range(s, e + 1)]
    if levels is not None:
        area = _trapezoid(t[s:e + 1], above)
    else:
        area = clip(t[s:e + 1], above)
    lo, hi = ln["outer"]
    return {"s": s, "e": e, "start": t[s], "end": t[e], "base_start": b0, "base_end": b1,
            "apex_index": a, "height": height, "area": area, "baseline": baseline,
            "levels": levels, "valley_share": valley, "skim_share": skim,
            "bounds": [t[lo], t[hi]] if baseline == "drop" else None}


def classic(t, y, start, end, baseline, smooth_points, edge_points, levels=None, bounds=None, sigma=None,
            amp=None):
    """The classic engine's peak between `start` and `end`: each edge is the
    point nearest its time and the start must lie before the end; each
    edge level is the mean of the raw signal from the edge outwards over
    `edge_points` more points, and the line is the baseline's (_line); the
    apex is the highest smoothed point between the edges and its height
    is above the line there; the area is the trapezoid of the raw signal
    above the line, each point's part below it counted as none, unless
    the levels are set by hand. A neighbour rises `amp` times `sigma`
    above its valley (_rise)."""
    levels = _check(baseline, levels)
    s, e = _nearest(t, start), _nearest(t, end)
    if not e > s:
        raise ValueError("a peak's start is before its end")

    def ends(i, j):
        return [_mean(y[max(i - edge_points, 0):i + 1]), _mean(y[j:j + edge_points + 1])]
    sm = _memo(y, _classic_smoothing(y, smooth_points))
    rise = _rise(sigma, amp)
    a, top = _apex(y, s, e, _classic_smoothing(y, smooth_points))
    out = _measures(t, y, s, e, a, top, lambda skip: _line(t, sm, s, e, baseline, ends, levels, bounds, rise, skip),
                    sm, baseline, levels,
                    lambda tt, above: _trapezoid(tt, [max(v, 0.0) for v in above]))
    out["apex"] = t[a]
    return out


def _adaptive_base(y, s, e, m):
    """The adaptive engine's line: each end the mean over m points on the
    outer side of the edge, read at the centre of that window, the line
    through the two centres extrapolated to the edges (in points)."""
    w = max(m, 1)
    l0, r1 = max(s - w, 0), min(e + w, len(y) - 1)
    left = _mean(y[l0:s + 1])
    right = _mean(y[e:r1 + 1])
    cl, cr = (l0 + s) / 2.0, (e + r1) / 2.0
    k = (right - left) / (cr - cl)
    return [left + k * (s - cl), right + k * (e - cr)]


def adaptive(t, y, start, end, baseline, m, levels=None, bounds=None, sigma=None, amp=None):
    """The adaptive engine's peak between `start` and `end`, given either
    way round: each edge is the point nearest its time and the span holds
    at least four points; the edge levels are the adaptive line's
    (_adaptive_base) and the line is the baseline's (_line); the apex is
    the highest point smoothed at m, its time read by a parabola through
    the top three smoothed points, and its height is above the line
    there; the area is the trapezoid above the line, never below zero,
    unless the levels are set by hand. A neighbour rises `amp` times
    `sigma` above its valley (_rise)."""
    levels = _check(baseline, levels)
    s, e = _nearest(t, min(start, end)), _nearest(t, max(start, end))
    if e < s + 3:
        raise ValueError("the re-integration spans too few points")
    m = max(int(m), 1)
    n = _adaptive_smoothing(y, m)
    sm = _memo(y, n)
    rise = _rise(sigma, amp)

    def ends(i, j):
        return _adaptive_base(y, i, j, m)
    a, top = _apex(y, s, e, n)
    out = _measures(t, y, s, e, a, top, lambda skip: _line(t, sm, s, e, baseline, ends, levels, bounds, rise, skip),
                    sm, baseline, levels,
                    lambda tt, above: max(_trapezoid(tt, above), 0.0))
    rt = t[a]
    if 0 < a < len(t) - 1:
        y0, y1, y2 = _smoothed(y, a - 1, n), top, _smoothed(y, a + 1, n)
        den = y0 - 2 * y1 + y2
        off = min(0.5, max(-0.5, 0.5 * (y0 - y2) / den)) if den < 0 else 0.0
        rt = t[a] + off * (t[a + 1] - t[a])
    out["apex"] = rt
    return out


def sn(engine, height, sigma):
    """A manual peak's S/N, its height over the trace's noise sigma, as its
    engine reads one: under Classic no height above the baseline is 0, and
    no noise under a real height is unbounded; under Adaptive no noise is
    unbounded. None when the trace has no sigma."""
    if sigma is None:
        return None
    if engine == "classic" and not height > 0:
        return 0.0
    return height / sigma if sigma > 0 else float("inf")


def preview(engine, t, y, start, end, baseline, sigma, smooth_points=None, edge_points=None, m=None,
            levels=None, bounds=None, amp=None):
    """The manual peak under `engine` ("classic" or "adaptive") with its
    S/N against `sigma`. Classic needs the compound's smoothing in points
    and its edge points; Adaptive its smoothing half-width m. `levels`
    [left, right] in counts set the baseline's two levels by hand;
    `bounds` the pair's outer edges for a drop (else found from the
    neighbours, each rising `amp`, the peak search amplitude, times
    `sigma` above its valley; with no sigma none is found). ValueError for
    edges the engine refuses."""
    if engine == "adaptive":
        out = adaptive(t, y, start, end, baseline, m, levels, bounds, sigma, amp)
    else:
        out = classic(t, y, start, end, baseline, smooth_points, edge_points, levels, bounds, sigma, amp)
    out["sn"] = sn(engine, out["height"], sigma)
    return out


# the measures of a candidate the preview of another apex shows
APEX_MEASURES = ("start", "end", "base_start", "base_end", "apex", "height", "area", "sn")


def apex_preview(t, candidate):
    """Another apex chosen as found (on the method's baseline): the
    candidate's own measures as the engine found them and the worker
    replays the choice (its edges, baseline ends, apex, height, area and
    S/N, none where the record has none), and "s" and "e", the indices of
    its edges in `t`, the stored samples nearest them. Never a measure of
    its own over the candidate's span: that is a re-integration, a
    different peak."""
    out = dict((k, candidate.get(k)) for k in APEX_MEASURES)
    out["s"], out["e"] = _nearest(t, candidate["start"]), _nearest(t, candidate["end"])
    return out


# ── the method's limits on a manual change ──────────────────────────────────

def area_change_pct(auto_area, manual_area):
    """How far the manual area lies from the automatic, in % of the
    automatic; None without an automatic area above zero or a manual one."""
    if auto_area is None or manual_area is None or not auto_area > 0:
        return None
    return abs(manual_area - auto_area) / auto_area * 100.0


def _above(value, limit):
    """`value` with the fewest decimals (one at least) that still reads
    above `limit`, so a near miss never prints as the limit itself."""
    for places in range(1, 10):
        text = "%.*f" % (places, value)
        if float(text) > limit:
            return text
    return "%r" % value


def _below(value, limit):
    """`value` with the fewest decimals (one at least) that still reads
    below `limit`, so a near miss never prints as the limit itself."""
    for places in range(1, 10):
        text = "%.*f" % (places, value)
        if float(text) < limit:
            return text
    return "%r" % value


# an edit the limits judge: a re-integration, another apex or a fit (judged
# by the worker, which fits); a deletion and an undo are never refused
JUDGED = ("integrate", "apex", "fit")


def edit_problem(kind, auto_area, manual_area, sn_value, min_change_pct, min_sn):
    """Why the method refuses an analyst's edit, or None. A re-integration
    or another apex whose area lies less than `min_change_pct` % from the
    automatic area is refused (an automatic area of none or 0 is not
    judged), and so is one whose S/N is under `min_sn` (unset: not judged;
    an S/N that cannot be read is refused while the limit is set)."""
    if kind not in JUDGED:
        return None
    pct = area_change_pct(auto_area, manual_area)
    # judged unrounded, but not on floating-point noise: 4.9999999999 % is a change AT 5 %
    if min_change_pct is not None and pct is not None and round(pct, 9) < min_change_pct:
        return "The change is under the method's smallest manual change of %g %%: %s %%." % (
            min_change_pct, _below(pct, min_change_pct))
    if min_sn is not None:
        if sn_value is None:
            return "The peak's S/N cannot be read on this trace: process the run again."
        if sn_value < min_sn:
            return "The peak's S/N %s is under the method's smallest S/N for a manual peak, %g." % (
                _below(sn_value, min_sn), min_sn)
    return None


def _set(value):
    return value is not None and ("%s" % value).strip() != ""


def manual_limits(integration, keyword):
    """(smallest manual change in %, smallest S/N for a manual peak or None)
    for `keyword` from a method's Integration block: the compound's own
    where it sets one, else the method's; the change defaults to
    DEFAULT_MIN_MANUAL_CHANGE_PCT, an unset S/N is no limit."""
    intg = integration or {}
    row = (intg.get("analytes") or {}).get(keyword) or {}
    out = []
    for key, default in (("min_manual_change_pct", DEFAULT_MIN_MANUAL_CHANGE_PCT), ("min_manual_sn", None)):
        value = row.get(key) if _set(row.get(key)) else intg.get(key)
        out.append(float(value) if _set(value) else default)
    return tuple(out)


def review_limits(integration, keyword=None):
    """{key: value} for every setting of REVIEW_RULES, for `keyword` (None:
    the method) from a method's Integration block: the compound's own where
    it sets one (never search_slope or search_smooth_pct), else the method's,
    else the default. An unset search_amp_sn is the smallest S/N for a manual
    peak where one is set, else DEFAULT_SEARCH_AMP_SN. A value that is no
    number, not whole where it counts points, or out of range raises
    ValueError naming the setting."""
    intg = integration or {}
    row = ((intg.get("analytes") or {}).get(keyword) or {}) if keyword is not None else {}
    out = {}
    for key, whole, default, low, inclusive in REVIEW_RULES:
        value = intg.get(key)
        if key not in REVIEW_METHOD_ONLY and _set(row.get(key)):
            value = row.get(key)
        if not _set(value):
            if key == "search_amp_sn":
                default = manual_limits(intg, keyword)[1]
                default = DEFAULT_SEARCH_AMP_SN if default is None else default
            out[key] = default
            continue
        try:
            if isinstance(value, bool):
                raise ValueError(value)
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                raise ValueError(value)
        except (TypeError, ValueError):
            raise ValueError("%s %r is not a number" % (key, value))
        if whole:
            if number != int(number):
                raise ValueError("%s %r is not a whole number" % (key, value))
            number = int(number)
        if number < low or (number == low and not inclusive):
            raise ValueError("%s %r is out of range" % (key, value))
        out[key] = number
    return out
