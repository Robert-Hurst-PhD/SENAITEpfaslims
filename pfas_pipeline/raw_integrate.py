"""Peak integration of raw MRM chromatograms, from the methods in T. O'Haver,
"A Pragmatic Introduction to Signal Processing" (peak finding and
measurement; integration and peak area; curve fitting).

One analyte's peak in its retention-time window:
  1. smooth (Savitzky-Golay, `smooth_points` wide, second order) to find the
     peak, never to measure it;
  2. the apex is the highest smoothed point in rt +/- window;
  3. the edges are where the smoothed signal stops falling on each side
     (the baseline, or the valley to a neighbouring peak);
  4. a straight baseline joins the edges ("valley"), or runs flat at the
     lower edge ("flat": a drop line to it from each edge); a manual peak
     may also take a perpendicular drop ("drop": one line under the peak
     and its neighbour, from the pair's outer edges, cut by drop lines at
     the edges), a tangent skim ("skim": a line from the signal at the
     start, on a parent peak's tail, to the signal at the end), or two
     levels set by hand;
  5. the area is the trapezoid sum of the raw signal above the baseline,
     or the area of a fitted Gaussian or exponentially modified Gaussian
     (EMG) on a straight baseline;
  6. signal-to-noise = height above the baseline / the standard deviation
     of the raw signal about its smoothed form outside the peak; below
     `min_sn` the analyte is not detected (no area, no time).

A co-eluting pair (branched / linear isomers on one transition) is fitted
together, two EMGs on one baseline (a valley split loses a small shoulder);
summed isomers are one peak from the first edge to the last; branched isomers
beside their linear partner are every peak in their window but the
partner's, summed.

Every setting is the method's (its Integration tab); none has a default.
Python 3.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from typing import NamedTuple, Optional

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.signal import find_peaks, savgol_filter
from scipy.special import erfc, erfcx
from threadpoolctl import threadpool_limits

# each baseline end is the mean of this many raw points just outside the
# peak, unless the method's Edge points says otherwise
EDGE_POINTS = 6
# a manual peak's baselines (raw_preview.BASELINES, which mirrors them);
# an automatic peak's are the valley line and the flat line
BASELINES = ("valley", "drop", "flat", "skim")
AUTO_BASELINES = ("valley", "flat")
AREAS = ("trapezoid", "gaussian", "emg")


@dataclass(frozen=True)
class Settings:
    """The classic engine's settings. A fitted area (gaussian, emg) needs
    `fit_max_dev_pct`, the largest distance from the trapezoid over the same
    edges that a fit may keep."""
    smooth_points: int
    baseline: str
    area: str
    min_sn: float
    fit_max_dev_pct: Optional[float] = None
    edge_points: int = EDGE_POINTS

    def __post_init__(self):
        if isinstance(self.edge_points, bool) or int(self.edge_points) != self.edge_points \
                or self.edge_points < 1:
            raise ValueError("the edge points are a whole number of points, 1 or more")
        if int(self.smooth_points) < 5 or int(self.smooth_points) % 2 == 0:
            raise ValueError("smoothing is an odd number of points, 5 or more")
        if self.baseline not in BASELINES:
            raise ValueError("baseline is one of %s" % ", ".join(BASELINES))
        if self.area not in AREAS:
            raise ValueError("area is one of %s" % ", ".join(AREAS))
        if not self.min_sn > 0:
            raise ValueError("the smallest signal-to-noise is above zero")
        _check_fit_max_dev(self)


def _check_fit_max_dev(settings):
    if settings.fit_max_dev_pct is not None and not settings.fit_max_dev_pct > 0:
        raise ValueError("the largest fit deviation is above zero")
    if settings.area in ("gaussian", "emg") and settings.fit_max_dev_pct is None:
        raise ValueError("a fitted area needs the largest fit deviation")


# where the adaptive engine expects a peak: at its configured time, or moved
# by its quantitation standard's shift in that injection
RT_ANCHORS = ("fixed", "labelled")


@dataclass(frozen=True)
class AdaptiveSettings:
    """The adaptive engine's settings. `smooth` is "auto" (the half-width is
    learned from the data) or the smoothing half-width m, from an odd number
    of points n as m = (n - 1) / 2. A fitted area (gaussian, emg) needs
    `fit_max_dev_pct`, the largest distance from the trapezoid over the same
    edges that a fit may keep. `rt_anchor` "labelled" moves a native's
    expected time by its quantitation standard's found shift; "fixed" keeps
    the configured time."""
    smooth: object
    area: str
    min_sn: float
    sensitivity: float
    shoulder_pct: float
    qual_apex_tol: float
    fit_max_dev_pct: Optional[float] = None
    rt_anchor: str = "fixed"

    def __post_init__(self):
        if self.smooth != "auto" and (isinstance(self.smooth, bool) or not isinstance(self.smooth, int)
                                      or self.smooth < 1):
            raise ValueError("smoothing is auto or an odd number of points, 3 or more")
        if self.area not in AREAS:
            raise ValueError("area is one of %s" % ", ".join(AREAS))
        if not self.min_sn > 0:
            raise ValueError("the smallest signal-to-noise is above zero")
        if not self.sensitivity > 0:
            raise ValueError("the sensitivity is above zero")
        if not 0 < self.shoulder_pct < 100:
            raise ValueError("the shoulder split is above 0 and below 100 %")
        if not self.qual_apex_tol > 0:
            raise ValueError("the qualifier apex tolerance is above zero")
        _check_fit_max_dev(self)
        if self.rt_anchor not in RT_ANCHORS:
            raise ValueError("relative retention is fixed or labelled, not %r" % (self.rt_anchor,))


@dataclass
class Peak:
    area: Optional[float]
    rt: Optional[float]
    start: Optional[float]
    end: Optional[float]
    base_start: Optional[float]
    base_end: Optional[float]
    sn: Optional[float]
    method: str
    detected: bool
    note: str = ""
    # the adaptive engine's measures; None for a classic peak
    fwhm_s: Optional[float] = None
    tailing: Optional[float] = None
    plates: Optional[float] = None
    smoothing: Optional[int] = None
    # the injection a learnt smoothing came from
    smoothing_from: Optional[str] = None
    engine: Optional[str] = None
    fit_note: Optional[str] = None
    # the noise sigma the S/N was read against: a manual peak's S/N is
    # judged against the automatic peak's
    noise: Optional[float] = None
    # a manual peak's baseline, its levels where set by hand, a drop's
    # valley share and a skim's height over its parent's, in %
    baseline: Optional[str] = None
    levels: Optional[list] = None
    valley_share: Optional[float] = None
    skim_share: Optional[float] = None
    # the peak asymmetry factor on its quantifier trace (peak_asymmetry),
    # or why it has none
    asymmetry: Optional[float] = None
    asymmetry_note: Optional[str] = None
    # a change applied to every injection of the trace ("Apply to all"):
    # the change this peak was measured by, or why this injection could
    # not take it and kept its automatic peak (raw_run._processed)
    processing: Optional[dict] = None
    processing_skipped: Optional[str] = None
    # a peak separated from its neighbours by a fit (fit_peaks): the fit's
    # shape, components, baseline, residual, the component reported and its
    # 95 % interval, so the value can be reproduced
    fit: Optional[dict] = None
    # the peak's height above its baseline at the apex, in counts
    height: Optional[float] = None
    # the edge a drop baseline shares with a neighbouring peak, in minutes
    drop_rt: Optional[float] = None
    # the peak scored under each fitting method (raw_run._fit_scores)
    fit_scores: Optional[list] = None


# ── shapes ──────────────────────────────────────────────────────────────────

def gaussian(t, area, mu, sigma):
    return area / (sigma * math.sqrt(2 * math.pi)) * np.exp(-0.5 * ((t - mu) / sigma) ** 2)


def emg(t, area, mu, sigma, tau):
    """Exponentially modified Gaussian of total `area`, written so it never
    overflows (erfcx on the leading side)."""
    t = np.asarray(t, dtype=float)
    z = (sigma / tau - (t - mu) / sigma) / math.sqrt(2)
    gauss = np.exp(-0.5 * ((t - mu) / sigma) ** 2)
    out = erfcx(np.clip(z, 0, None)) * gauss
    trail = z < 0
    out[trail] = erfc(z[trail]) * np.exp(sigma ** 2 / (2 * tau ** 2) - (t[trail] - mu) / tau)
    return area / (2 * tau) * out


# ── the steps ───────────────────────────────────────────────────────────────

def _arrays(t, y):
    return np.asarray(t, dtype=float), np.asarray(y, dtype=float)


def _smooth(y, settings):
    n = min(int(settings.smooth_points), len(y) - (1 - len(y) % 2))
    return savgol_filter(y, n, 2) if n >= 5 else y


def _edges(ys, apex, lo, hi):
    s = apex
    while s > lo and ys[s - 1] <= ys[s]:
        s -= 1
    e = apex
    while e < hi and ys[e + 1] <= ys[e]:
        e += 1
    return s, e


def _edge_level(y, i, step, points=EDGE_POINTS):
    """The baseline level at an edge: the mean of the `points` raw signal
    values just OUTSIDE the peak (points inside already climb it)."""
    if step < 0:
        seg = y[max(i - points, 0):i + 1]
    else:
        seg = y[i:i + points + 1]
    return float(np.mean(seg))


def _extend(ys, i, step, bound, threshold, tol):
    """Carry an edge on outward while the smoothed signal is still above the
    baseline floor (a noise bump stopped the first walk), ending at the
    lowest point passed; a rise of more than `tol` is a neighbouring peak."""
    best = i
    while (i > bound if step < 0 else i < bound) and ys[i] > threshold:
        i += step
        if ys[i] < ys[best]:
            best = i
        elif ys[i] > ys[best] + tol:
            break
    return best


def _settled_edges(y, ys, apex, lo, hi, exclude=()):
    """(start, end, noise): the valley walk, then each edge carried down to
    the floor (the window's 10th percentile + twice the noise). The noise
    returned leaves out the `exclude` index spans; the edges do not."""
    s, e = _edges(ys, apex, lo, hi)
    noise = _noise(y, ys, lo, hi + 1, s, e)
    threshold = float(np.percentile(ys[lo:hi + 1], 10)) + 2 * noise
    s = _extend(ys, s, -1, lo, threshold, 2 * noise)
    e = _extend(ys, e, 1, hi, threshold, 2 * noise)
    return s, e, _noise(y, ys, lo, hi + 1, s, e, exclude)


def method_baseline(named):
    """The baseline an automatic peak is measured on, from a method's or a
    compound's Integration baseline (raw_preview.method_baseline: a "drop"
    stored before the perpendicular drop is "flat"); ValueError for any
    other, as an automatic peak takes the valley or the flat line only."""
    from .addon import load
    got = load("raw_preview").method_baseline(named)
    if got is None:
        raise ValueError("baseline is one of %s" % ", ".join(AUTO_BASELINES))
    return got


def _flat(settings):
    """Whether an automatic peak's baseline is flat at the lower edge; an
    automatic peak is measured on the valley line or the flat one only."""
    if settings.baseline not in AUTO_BASELINES:
        raise ValueError("an automatic peak's baseline is one of %s" % ", ".join(AUTO_BASELINES))
    return settings.baseline == "flat"


def _baseline(t, y, s, e, settings):
    """A straight line between the edges' levels (each the mean of the raw
    signal about the edge, so one noisy point does not set it), or flat at
    the lower ("flat")."""
    points = getattr(settings, "edge_points", EDGE_POINTS)
    left, right = _edge_level(y, s, -1, points), _edge_level(y, e, 1, points)
    if _flat(settings):
        return np.full_like(t, min(left, right))
    return np.interp(t, [t[s], t[e]], [left, right])


def _noise(y, ys, lo, hi, s, e, exclude=()):
    """The spread of the signal about its smoothed trace over [lo, hi),
    leaving out the peak [s, e] and each (i0, i1) index span in `exclude`."""
    mask = np.zeros(len(y), dtype=bool)
    mask[lo:hi] = True
    mask[s:e + 1] = False
    for i0, i1 in exclude:
        mask[i0:i1 + 1] = False
    resid = (y - ys)[mask]
    return float(np.std(resid)) if len(resid) > 5 else float(np.std(y - ys))


def _sn(height, noise):
    """Signal-to-noise; no height above the baseline is none (a flat or
    zero-filled channel), no noise under a real height is unbounded."""
    if not height > 0:
        return 0.0
    return height / noise if noise > 0 else float("inf")


def _window(t, rt, window):
    lo = int(np.searchsorted(t, rt - window))
    hi = int(np.searchsorted(t, rt + window))
    return max(lo, 1), min(hi, len(t) - 2)


def _spans(t, exclude):
    """(t0, t1) time spans as (i0, i1) index spans of t."""
    return [(int(np.searchsorted(t, a)), int(np.searchsorted(t, b, side="right")) - 1)
            for a, b in (sorted(span) for span in exclude)]


def _not_detected(method, sn, note, noise=None):
    return Peak(None, None, None, None, None, None, sn, method, False, note, noise=noise)


def _fit_area(t, y, s, e, apex, settings, pad=None):
    """A Gaussian or EMG on a straight baseline, fitted over the peak's
    edges widened by half the peak (or `pad` points); its area."""
    pad = max((e - s) // 2, 5) if pad is None else pad
    a, b = max(s - pad, 0), min(e + pad, len(t) - 1)
    tt, yy = t[a:b + 1], y[a:b + 1]
    height = float(y[apex] - min(yy))
    width = max(float(t[e] - t[s]) / 6.0, 1e-3)
    guess_area = max(height * width * 2.5, 1.0)
    if settings.area == "gaussian":
        def model(x, area, mu, sigma, b0, b1):
            return gaussian(x, area, mu, sigma) + b0 + b1 * (x - tt[0])
        p0 = [guess_area, t[apex], width, float(min(yy)), 0.0]
        bounds = ([0, tt[0], 1e-4, -np.inf, -np.inf], [np.inf, tt[-1], np.inf, np.inf, np.inf])
    else:
        def model(x, area, mu, sigma, tau, b0, b1):
            return emg(x, area, mu, sigma, tau) + b0 + b1 * (x - tt[0])
        p0 = [guess_area, t[apex], width, width / 2.0, float(min(yy)), 0.0]
        bounds = ([0, tt[0], 1e-4, 1e-4, -np.inf, -np.inf], [np.inf, tt[-1], np.inf, np.inf, np.inf, np.inf])
    p, _ = curve_fit(model, tt, yy, p0=p0, bounds=bounds, maxfev=20000)
    return float(abs(p[0]))


# a fitted area refused for the trapezoid over the same edges
FIT_REFUSED = "trapezoid, fit refused"


def area_method(settings, manual=False, refused=False):
    """How a peak's area was measured, as its record names it."""
    if refused:
        return ("manual " if manual else "") + FIT_REFUSED
    if manual:
        return "manual" if settings.area == "trapezoid" else "manual " + settings.area
    return settings.area


def trapezoid_area(t, y, base, s, e):
    """The raw signal above the baseline between the edges, by the trapezoid rule."""
    seg = slice(s, e + 1)
    return float(np.trapezoid(np.clip(y[seg] - base[seg], 0, None), t[seg]))


def signed_area(t, y, base, s, e):
    """The raw signal above the baseline between the edges, by the trapezoid
    rule, a part below the baseline counted against it: the area over
    levels set by hand."""
    seg = slice(s, e + 1)
    return float(np.trapezoid(y[seg] - base[seg], t[seg]))


# ── a manual peak's baseline ────────────────────────────────────────────────
# Mirrored point for point by raw_preview (_outward, _line, _shares) and the
# browser's preview, held equal by tests/raw_preview_parity.json.

def check_levels(levels):
    """[left, right] of baseline levels set by hand, two finite numbers, or
    None (raw_preview.check_levels); ValueError otherwise."""
    from .addon import load
    return load("raw_preview").check_levels(levels)


def _outward(ys, i, step, rise):
    """(top, far edge) of the neighbouring peak beyond index i on the
    smoothed signal ys, or None (raw_preview._outward: the rule lives once)."""
    from .addon import load
    return load("raw_preview")._outward(lambda k: float(ys[k]), len(ys), i, step, rise)


def neighbour_rise(noise, amp=None):
    """How far a neighbour's top rises above its valley at least: the peak
    search amplitude `amp` (raw_preview.DEFAULT_SEARCH_AMP_SN when None)
    times the noise; None without a noise."""
    from .addon import load
    return load("raw_preview")._rise(noise, amp)


def manual_line(t, ys, s, e, baseline, ends, levels=None, bounds=None, rise=None, skip=()):
    """A manual peak's baseline over the edges s and e: {"b": [at s, at e],
    "line": the whole line as a function of an index, "outer": [L, R] the
    indices its levels are read at, "tops": [(side, top)] the neighbours'
    tops, side -1 before the peak and +1 after it, a side in `skip` left
    out, "ends"}.
    `ends(i, j)` is the engine's [level at i, level at j]; `levels`, set by
    hand, replace the two levels the baseline reads. valley: the levels at
    s and e; flat: the lower of them, level; drop: the levels at the
    pair's outer edges (`bounds` (t0, t1), else each neighbour's far edge
    (_outward), else the edge itself, so a peak with no neighbour is its
    valley line), the line between them; skim: the smoothed signal at s
    and at e. A neighbour is found by _outward, `rise` above its valley."""
    left = right = None
    if baseline in ("drop", "skim"):
        left = None if -1 in skip else _outward(ys, s, -1, rise)
        right = None if 1 in skip else _outward(ys, e, 1, rise)
    tops = [(side, x[0]) for side, x in ((-1, left), (1, right)) if x is not None]
    lo, hi = s, e
    if baseline == "drop":
        if bounds is not None:
            lo, hi = _index(t, min(bounds)), _index(t, max(bounds))
            if lo > s or hi < e:
                raise ValueError("the drop's baseline runs under the whole pair")
        else:
            lo = left[1] if left is not None else s
            hi = right[1] if right is not None else e
    if levels is not None:
        lv, rv = levels
    elif baseline == "skim":
        lv, rv = float(ys[s]), float(ys[e])
    else:
        lv, rv = ends(lo, hi)
    if baseline == "flat":
        lv = rv = min(lv, rv)
    x0, x1 = t[lo], t[hi]

    def line(i):
        return float(np.interp(t[i], [x0, x1], [lv, rv]))
    return {"b": [line(s), line(e)], "line": line, "outer": [lo, hi], "tops": tops, "ends": ends, "rise": rise,
            "skip": skip, "baseline": baseline}


def line_shares(t, ys, s, e, a, height, baseline, ln):
    """(valley share, skim share, the sides whose neighbour is no peak
    beside this one), each share in % and None where it does not apply,
    a share only between 0 and 100 (raw_preview._share). A drop's: for
    each neighbour, the lowest smoothed point between the two tops above
    the line over the smaller peak's height above it, the larger of the two
    sides; a neighbour whose share is none is no neighbour. A skim's: the
    peak's height over its parent's, the parent the taller neighbour, its
    height above the line between the pair's outer edge levels (its own
    baseline)."""
    from .addon import load
    share_of = load("raw_preview")._share
    if baseline == "drop":
        out, bad = None, ()
        for side, top in ln["tops"]:
            lo, hi = min(a, top), max(a, top)
            v = lo + int(np.argmin(ys[lo:hi + 1]))
            share = share_of(float(ys[v]) - ln["line"](v), min(height, float(ys[top]) - ln["line"](top)))
            if share is None:
                bad += (side,)
            else:
                out = share if out is None else max(out, share)
        return out, None, bad
    if baseline == "skim" and ln["tops"]:
        parent = ln["tops"][0][1]
        for _side, top in ln["tops"][1:]:
            if ys[top] > ys[parent]:
                parent = top
        outer = manual_line(t, ys, s, e, "drop", ln["ends"], rise=ln["rise"], skip=ln["skip"])
        return None, share_of(height, float(ys[parent]) - outer["line"](parent)), ()
    return None, None, ()


def settled_line(t, ys, s, e, a, build):
    """(line, height above it at the apex a, valley share, skim share) of
    the line `build(skip)` draws (manual_line), drawn again without each
    neighbour that is no peak beside this one (line_shares)."""
    skip = ()
    while True:
        ln = build(skip)
        height = float(ys[a] - float(np.interp(t[a], [t[s], t[e]], ln["b"])))
        valley, skim, bad = line_shares(t, ys, s, e, a, height, ln["baseline"], ln)
        if not bad:
            return ln, height, valley, skim
        skip += bad


def manual_measure(t, y, start, end, settings, levels=None, bounds=None, noise=None, amp=None):
    """The classic engine's manual peak between `start` and `end` on
    settings.baseline (one of BASELINES) or `levels` set by hand, a
    neighbour rising `amp` times `noise` above its valley: {"s", "e",
    "apex" (an index), "base" (the line over the trace), "height" above it
    at the apex, "area" (the trapezoid above it, a part below counted as
    none, or against it with levels set by hand), "valley_share",
    "skim_share", "levels"}."""
    if settings.baseline not in BASELINES:
        raise ValueError("baseline is one of %s" % ", ".join(BASELINES))
    levels = check_levels(levels)
    t, y = _arrays(t, y)
    ys = _smooth(y, settings)
    s = int(np.argmin(abs(t - start)))
    e = int(np.argmin(abs(t - end)))
    if not e > s:
        raise ValueError("a peak's start is before its end")
    apex = s + int(np.argmax(ys[s:e + 1]))
    points = getattr(settings, "edge_points", EDGE_POINTS)
    rise = neighbour_rise(noise, amp)

    def ends(i, j):
        return [_edge_level(y, i, -1, points), _edge_level(y, j, 1, points)]
    ln, _h, valley, skim = settled_line(
        t, ys, s, e, apex, lambda skip: manual_line(t, ys, s, e, settings.baseline, ends, levels, bounds, rise, skip))
    base = np.interp(t, [t[s], t[e]], ln["b"])
    height = float(ys[apex] - base[apex])
    area = signed_area(t, y, base, s, e) if levels is not None else trapezoid_area(t, y, base, s, e)
    return {"s": s, "e": e, "apex": apex, "base": base, "height": height, "area": area, "ys": ys,
            "valley_share": valley, "skim_share": skim, "levels": levels}


def gated_fit(t, y, s, e, apex, settings, trapezoid, pad=None):
    """(area, fit_note): the method's shape fitted over the peak, or, with
    the reason, `trapezoid` (the trapezoid over the same edges) when the fit
    fails, gives no finite area, or lies further from the trapezoid than the
    method's largest fit deviation (fit_max_dev_pct, in %)."""
    try:
        area = _fit_area(t, y, s, e, apex, settings, pad)
    except (RuntimeError, ValueError) as exc:
        return trapezoid, "the %s fit failed: %s; the trapezoid is used" % (settings.area, exc)
    if not math.isfinite(area):
        return trapezoid, "the %s fit gives no area: the trapezoid is used" % settings.area
    if not trapezoid > 0:
        return trapezoid, "no trapezoid area to check the %s fit against: the trapezoid is used" % settings.area
    dev = abs(area - trapezoid) / trapezoid * 100.0
    if not dev <= settings.fit_max_dev_pct:
        return trapezoid, ("the %s area is %.1f %% from the trapezoid over the same edges, beyond %g %%: "
                           "the trapezoid is used" % (settings.area, dev, settings.fit_max_dev_pct))
    return area, None


def integrate(t, y, rt, window, settings):
    """One analyte's peak in rt +/- window (minutes)."""
    return integrate_excluding(t, y, rt, window, settings, ())


def integrate_excluding(t, y, rt, window, settings, exclude):
    """integrate, with the (t0, t1) spans in `exclude` -- another analyte's
    peaks, such as an isomer partner's -- left out of the noise."""
    t, y = _arrays(t, y)
    ys = _smooth(y, settings)
    lo, hi = _window(t, rt, window)
    apex = lo + int(np.argmax(ys[lo:hi]))
    return _measure_from_apex(t, y, ys, apex, lo, hi, settings, _spans(t, exclude))


def _reach(t, lo, hi):
    """The index bounds an edge walk and the noise may reach from the window
    [lo, hi): 60 points either side."""
    return max(lo - 60, 1), min(hi + 60, len(t) - 2)


def _measure_from_apex(t, y, ys, apex, lo, hi, settings, exclude):
    """The peak at index `apex` of the window [lo, hi) as the automatic
    integration measures it: its settled edges, the method's baseline, its
    S/N against the noise outside it and the `exclude` index spans, and its
    area; not detected below the method's smallest S/N."""
    s, e, noise = _settled_edges(y, ys, apex, *_reach(t, lo, hi), exclude=exclude)
    base = _baseline(t, y, s, e, settings)
    height = float(ys[apex] - base[apex])
    sn = _sn(height, noise)
    if not sn >= settings.min_sn:
        return _not_detected(settings.area, sn, "no peak above the signal-to-noise of %g" % settings.min_sn,
                             noise)
    area, fit_note = trapezoid_area(t, y, base, s, e), None
    if settings.area != "trapezoid":
        area, fit_note = gated_fit(t, y, s, e, apex, settings, area)
    return Peak(area, float(t[apex]), float(t[s]), float(t[e]), float(base[s]), float(base[e]), sn,
                area_method(settings, refused=fit_note is not None), True, fit_note=fit_note, noise=noise,
                height=height)


def as_candidate(peak, t, y):
    """A detected peak as a choice offered to the analyst: its apex time,
    the raw signal there, its edges, baseline ends, area, S/N and height
    above the baseline (its S/N times the noise that was read against; none
    when no noise was read), the engine's own measures, which the review
    shows and judges for the choice."""
    noise = peak.noise
    height = float(peak.sn) * float(noise) if noise is not None and noise > 0 and math.isfinite(peak.sn) else None
    return {"apex": float(peak.rt), "y": float(np.interp(peak.rt, t, y)),
            "start": float(peak.start), "end": float(peak.end),
            "base_start": float(peak.base_start), "base_end": float(peak.base_end),
            "area": float(peak.area), "sn": float(peak.sn), "height": height}


def _index(t, x):
    """The index of t nearest x, the first of two equally near."""
    return int(np.argmin(np.abs(np.asarray(t, dtype=float) - x)))


def span_points(t, peak):
    """How many samples of t a found peak's span holds, both edges counted."""
    return _index(t, peak.end) - _index(t, peak.start) + 1


def _own_height(t, y, ys, peak, points):
    """(s, e, a, above, half) of a found peak read above its OWN baseline:
    the straight line between its edge levels, each the mean of the raw
    signal `y` from the edge outwards over `points` more samples
    (_edge_level), never a baseline shared with a neighbour, which can lie
    far below a peak riding on its tail. `above(v, i)` is the value v at
    sample i above that line; `half` is half the height of the smoothed
    signal `ys` above it at the apex sample `a`. None for an apex on or
    outside its own edges, whose height is not its own to read there."""
    s, e = _index(t, peak.start), _index(t, peak.end)
    a = _index(t, peak.rt)
    if not s < a < e:
        return None
    left_level, right_level = _edge_level(y, s, -1, points), _edge_level(y, e, 1, points)

    def above(v, i):
        return float(v[i]) - float(np.interp(t[i], [t[s], t[e]], [left_level, right_level]))

    return s, e, a, above, above(ys, a) / 2.0


def half_height_width(t, y, ys, peak, points=EDGE_POINTS):
    """A found peak's width at half its height, in minutes, on its engine's
    smoothed signal `ys`, above its own edge levels (_own_height): each
    half-height crossing is read between the peak's own edges, on the
    straight line between the samples either side of it, or at the edge
    itself where the signal stays above half height up to it. 0 for no
    height above that line; None for an apex on or outside its own edges."""
    t = np.asarray(t, dtype=float)
    own = _own_height(t, y, ys, peak, points)
    if own is None:
        return None
    s, e, a, above, half = own
    if not half > 0:
        return 0.0
    i = a
    while i > s and above(ys, i) > half:
        i -= 1
    left = t[i] if above(ys, i) > half else np.interp(half, [above(ys, i), above(ys, i + 1)], [t[i], t[i + 1]])
    j = a
    while j < e and above(ys, j) > half:
        j += 1
    right = t[j] if above(ys, j) > half else np.interp(half, [above(ys, j), above(ys, j - 1)], [t[j], t[j - 1]])
    return float(right - left)


def points_above_half(t, y, ys, peak, points=EDGE_POINTS):
    """How many RAW samples of `y` between a found peak's own edges stand at
    or above half its height above its own edge levels (_own_height, the
    height read on the smoothed `ys`): the smoothing widens a one- or
    two-sample spike, the raw samples do not. 0 for no height above that
    line; None for an apex on or outside its own edges."""
    t = np.asarray(t, dtype=float)
    own = _own_height(t, y, ys, peak, points)
    if own is None:
        return None
    s, e, _a, above, half = own
    if not half > 0:
        return 0
    return sum(1 for i in range(s, e + 1) if above(y, i) >= half)


def review_floor(floor=None):
    """(fewest points, smallest width in % of the automatic peak's) a
    candidate is offered at: `floor`, else the review's defaults
    (raw_preview.REVIEW_DEFAULTS)."""
    if floor is not None:
        return floor
    from .addon import load
    defaults = load("raw_preview").REVIEW_DEFAULTS
    return defaults["candidate_min_points"], defaults["candidate_min_fwhm_pct"]


def wide_enough(t, y, ys, peaks, auto, floor=None, points=EDGE_POINTS):
    """`peaks` less those too narrow to offer as another peak: a candidate
    is offered when at least the floor's fewest points of the raw signal
    `y` stand at or above half its height above its own edge levels
    (points_above_half) and, beside an automatic peak with a width, its
    width at half height (half_height_width, on the smoothed `ys`) is at
    least the floor's share of the automatic peak's, read the same way;
    each edge level is over `points` samples. A candidate whose apex lies
    on or outside its own edges has no height of its own to read: it is
    judged on the samples its span holds instead, and not by width. The
    automatic peak (`auto`, one of `peaks` or None) is always kept. A
    fragment on a peak's tail, a few samples between two ripples, or a
    one- or two-sample spike, whatever the smoothing, is no peak of its
    own."""
    min_points, min_pct = review_floor(floor)
    t, y = _arrays(t, y)
    ref = half_height_width(t, y, ys, auto, points) if auto is not None else None
    out = []
    for p in peaks:
        if p is not auto:
            count = points_above_half(t, y, ys, p, points)
            if (span_points(t, p) if count is None else count) < min_points:
                continue
            width = half_height_width(t, y, ys, p, points) if ref else None
            if width is not None and width < min_pct / 100.0 * ref:
                continue
        out.append(p)
    return out


def candidates(t, y, rt, window, settings, exclude=(), floor=None):
    """The peaks an analyst may choose among in rt +/- window, in time
    order, each as_candidate (candidate_peaks)."""
    t, y = _arrays(t, y)
    return [as_candidate(p, t, y) for p in candidate_peaks(t, y, rt, window, settings, exclude, floor)]


def candidate_peaks(t, y, rt, window, settings, exclude=(), floor=None):
    """The peaks an analyst may choose among in rt +/- window, in time
    order, each a Peak. They are the automatic peak (the highest
    smoothed point in the window) and every other maximum of the smoothed
    signal there, each measured from its own apex exactly as the automatic
    peak is (_measure_from_apex), kept when it clears the method's smallest
    S/N and is wide enough (wide_enough, at `floor`: the compound's fewest
    points and smallest width, None for the review's defaults). Taking the
    maxima from the highest down, one whose apex lies within
    the edges of a higher one, or whose edges hold a higher one's apex, is
    that peak (a ripple on its top or flank, or a flat top's second
    shoulder) and is no candidate of its own, so each apex lies within one
    candidate's edges only, and no two share an apex (each is its own
    sample; distinct_apexes, as under Adaptive). The (t0, t1) spans in
    `exclude` are left out of the noise, as for the automatic peak."""
    t, y = _arrays(t, y)
    ys = _smooth(y, settings)
    lo, hi = _window(t, rt, window)
    auto = lo + int(np.argmax(ys[lo:hi]))
    pk, _ = find_peaks(ys[lo:hi])
    others = sorted(set(lo + int(p) for p in pk) - {auto}, key=lambda i: (-ys[i], i))
    spans = _spans(t, exclude)
    taken, out, auto_peak = [], [], None
    # the automatic apex first: it is always its own peak
    for apex in [auto] + others:
        s, e, _noise = _settled_edges(y, ys, apex, *_reach(t, lo, hi), exclude=spans)
        if any(s <= a <= e or s0 <= apex <= e0 for a, s0, e0 in taken):
            continue
        taken.append((apex, s, e))
        peak = _measure_from_apex(t, y, ys, apex, lo, hi, settings, spans)
        if peak.detected:
            out.append(peak)
            if apex == auto:
                auto_peak = peak
    return distinct_apexes(wide_enough(t, y, ys, out, auto_peak, floor,
                                       getattr(settings, "edge_points", EDGE_POINTS)))


def distinct_apexes(peaks, auto=None):
    """`peaks` in time order, those that share one apex time offered once:
    the automatic peak (`auto`, one of `peaks`) when it is one of them, so
    the automatic integration is the candidate offered at its apex; else
    the one with the larger area (the earlier of two equal). An apex choice
    names its peak by its apex, and two pieces of one split peak can both
    top out on the point they share."""
    out = []
    for p in sorted(peaks, key=lambda p: p.rt):
        if out and out[-1].rt == p.rt:
            if out[-1] is not auto and (p is auto or (p.area or 0.0) > (out[-1].area or 0.0)):
                out[-1] = p
            continue
        out.append(p)
    return out


def with_baseline(settings, baseline=None):
    """The classic settings with one peak's own baseline, one of BASELINES;
    None keeps the method's. Settings refuses any other."""
    return settings if baseline is None else dataclasses.replace(settings, baseline=baseline)


def integrate_between(t, y, start, end, settings, exclude=(), noise=None, levels=None, bounds=None, amp=None):
    """A peak between edges the analyst set (manual re-integration): its
    baseline between them (settings.baseline, manual_line: valley, drop,
    flat or skim; `levels` [left, right] in counts replace the two levels
    it reads; `bounds` (t0, t1) are a drop's outer edges, else found from
    the neighbours, each rising `amp` (the peak search amplitude) times
    the noise above its valley) and the method's area measure -- the
    trapezoid above the baseline (manual_measure), or the method's shape
    fitted to those points. The S/N is the height above the baseline over `noise`, given
    (a manual peak is judged against the automatic call's noise, the
    number the review previewed), or else the signal's spread within 60
    points of the edges, the (t0, t1) spans in `exclude` left out. The
    peak carries its baseline, its levels, a drop's valley share and a
    skim's height over its parent's."""
    t, y = _arrays(t, y)
    if noise is None:
        s = int(np.argmin(abs(t - start)))
        e = int(np.argmin(abs(t - end)))
        noise = _noise(y, _smooth(y, settings), max(s - 60, 1), min(e + 60, len(t) - 2), s, e,
                       _spans(t, exclude))
    got = manual_measure(t, y, start, end, settings, levels, bounds, noise, amp)
    s, e, apex, base = got["s"], got["e"], got["apex"], got["base"]
    sn = _sn(got["height"], noise)
    area, fit_note = got["area"], None
    if settings.area != "trapezoid":
        # the method's shape, fitted to the points between the given edges
        area, fit_note = gated_fit(t, y, s, e, apex, settings, area, pad=0)
    return Peak(area, float(t[apex]), float(t[s]), float(t[e]), float(base[s]), float(base[e]), sn,
                area_method(settings, manual=True, refused=fit_note is not None), True, fit_note=fit_note,
                noise=noise, baseline=settings.baseline, levels=got["levels"], valley_share=got["valley_share"],
                skim_share=got["skim_share"], height=got["height"])


def integrate_summed(t, y, rts, window, settings):
    """Isomers reported as one: one peak from the first isomer's leading edge
    to the last isomer's trailing edge."""
    t, y = _arrays(t, y)
    ys = _smooth(y, settings)
    lo, _ = _window(t, min(rts), window)
    _, hi = _window(t, max(rts), window)
    pk, _ = find_peaks(ys[lo:hi])
    pk = lo + pk if len(pk) else np.array([lo + int(np.argmax(ys[lo:hi]))])
    first = pk[np.argmin(abs(t[pk] - min(rts)))]
    last = pk[np.argmin(abs(t[pk] - max(rts)))]
    apex = lo + int(np.argmax(ys[lo:hi]))
    s, _e, _n = _settled_edges(y, ys, min(first, apex), max(lo - 60, 1), min(hi + 60, len(t) - 2))
    _s, e, noise = _settled_edges(y, ys, max(last, apex), max(lo - 60, 1), min(hi + 60, len(t) - 2))
    base = _baseline(t, y, s, e, settings)
    sn = _sn(float(ys[apex] - base[apex]), noise)
    if not sn >= settings.min_sn:
        return _not_detected("summed", sn, "no peak above the signal-to-noise of %g" % settings.min_sn, noise)
    seg = slice(s, e + 1)
    area = float(np.trapezoid(np.clip(y[seg] - base[seg], 0, None), t[seg]))
    return Peak(area, float(t[apex]), float(t[s]), float(t[e]), float(base[s]), float(base[e]), sn,
                "summed", True, noise=noise, height=float(ys[apex] - base[apex]))


def integrate_cluster(t, y, rt, window, settings, exclude=(), bound=None):
    """Branched isomers reported as one: every maximum of the smoothed trace
    in rt +/- window standing the smallest S/N above the floor, as one peak
    from the first one's leading edge to the last one's trailing edge, timed
    at the highest. `bound` (start, end, apex) is the partner's chosen peak:
    no maximum within its edges is counted and the cluster stops at its
    nearer edge. The (t0, t1) spans in `exclude` are left out of the noise."""
    t, y = _arrays(t, y)
    ys = _smooth(y, settings)
    lo, hi = _window(t, rt, window)
    stop_lo, stop_hi = 0, len(t) - 1
    if bound is not None:
        if bound[2] >= rt:
            stop_hi = int(np.searchsorted(t, bound[0]))
            hi = min(hi, stop_hi)
        else:
            stop_lo = int(np.searchsorted(t, bound[1]))
            lo = max(lo, stop_lo)
    note = "no peak above the signal-to-noise of %g" % settings.min_sn
    wlo, whi = max(lo - 60, 1), min(hi + 60, len(t) - 2)
    if hi - lo < 3:
        # no peak in a window cut this short, but a noise, read about it
        # with the window left out: a manual peak there is judged on it
        return _not_detected("summed", None, note,
                             _noise(y, ys, wlo, whi + 1, lo, hi - 1, _spans(t, exclude)))
    apex = lo + int(np.argmax(ys[lo:hi]))
    _s, _e, noise = _settled_edges(y, ys, apex, wlo, whi, _spans(t, exclude))
    floor = float(np.percentile(ys[wlo:whi + 1], 10))
    pk, _ = find_peaks(ys[lo:hi])
    tops = sorted(set([lo + int(p) for p in pk if ys[lo + p] - floor >= settings.min_sn * noise] + [apex]))
    s = max(_settled_edges(y, ys, tops[0], wlo, whi)[0], stop_lo)
    e = min(_settled_edges(y, ys, tops[-1], wlo, whi)[1], stop_hi)
    # an edge cut at the partner's peak takes the smoothed signal there,
    # never the mean of the partner's rise beyond it
    points = getattr(settings, "edge_points", EDGE_POINTS)
    left = float(ys[s]) if s == stop_lo else _edge_level(y, s, -1, points)
    right = float(ys[e]) if e == stop_hi else _edge_level(y, e, 1, points)
    if _flat(settings):
        base = np.full_like(t, min(left, right))
    else:
        base = np.interp(t, [t[s], t[e]], [left, right])
    noise = _noise(y, ys, wlo, whi + 1, s, e, _spans(t, exclude))
    sn = _sn(float(ys[apex] - base[apex]), noise)
    if not sn >= settings.min_sn:
        return _not_detected("summed", sn, note, noise)
    seg = slice(s, e + 1)
    area = float(np.trapezoid(np.clip(y[seg] - base[seg], 0, None), t[seg]))
    return Peak(area, float(t[apex]), float(t[s]), float(t[e]), float(base[s]), float(base[e]), sn,
                "summed", True, noise=noise, height=float(ys[apex] - base[apex]))


def integrate_pair(t, y, rt, partner_rt, window, settings, exclude=()):
    """(this peak, its partner): two EMGs on one straight baseline fitted
    together over both windows. The noise is read over both windows and 60
    points either side, leaving out both fitted peaks (each from mu - 3 sigma
    to mu + 3 sigma + 3 tau) and the (t0, t1) spans in `exclude`."""
    t, y = _arrays(t, y)
    ys = _smooth(y, settings)
    lo, _ = _window(t, min(rt, partner_rt), window)
    _, hi = _window(t, max(rt, partner_rt), window)
    pk, _ = find_peaks(ys[lo:hi])
    pk = lo + pk
    near = lambda target: (pk[np.argmin(abs(t[pk] - target))] if len(pk)
                           else int(np.searchsorted(t, target)))
    a_idx, b_idx = near(rt), near(partner_rt)
    tt, yy = t[lo:hi], y[lo:hi]
    floor = float(np.percentile(yy, 5))
    sig = 0.03
    p0, lower, upper = [], [], []
    for idx, target in ((a_idx, rt), (b_idx, partner_rt)):
        h = max(float(ys[idx]) - floor, 1.0)
        p0 += [h * sig * 2.5, target, sig, sig / 2]
        lower += [0.0, target - window / 2, 0.005, 0.002]
        upper += [np.inf, target + window / 2, 0.2, 0.2]
    p0 += [floor, 0.0]
    lower += [-np.inf, -np.inf]
    upper += [np.inf, np.inf]

    def model(x, a1, m1, s1, k1, a2, m2, s2, k2, b0, b1):
        return emg(x, a1, m1, s1, k1) + emg(x, a2, m2, s2, k2) + b0 + b1 * (x - tt[0])
    p, _ = curve_fit(model, tt, yy, p0=p0, bounds=(lower, upper), maxfev=40000)
    base = p[8] + p[9] * (t - tt[0])
    fitted = [(p[k + 1] - 3 * p[k + 2], p[k + 1] + 3 * p[k + 2] + 3 * p[k + 3]) for k in (0, 4)]
    noise = _noise(y, ys, max(lo - 60, 1), min(hi + 60, len(t) - 2), lo, lo,
                   _spans(t, fitted + list(exclude)))
    out = []
    for k in (0, 4):
        area, mu, sigma, tau = p[k:k + 4]
        mode = mu + tau if tau < sigma else mu + sigma ** 2 / tau
        height = float(emg(np.array([mode]), area, mu, sigma, tau)[0])
        sn = _sn(height, noise)
        if not sn >= settings.min_sn:
            out.append(_not_detected("pair", sn, "no peak above the signal-to-noise of %g" % settings.min_sn,
                                     noise))
            continue
        start, end = mu - 3 * sigma, mu + 3 * sigma + 3 * tau
        out.append(Peak(float(area), float(mode), float(start), float(end),
                        float(np.interp(start, t, base)), float(np.interp(end, t, base)), sn, "pair", True,
                        noise=noise, height=height))
    return out[0], out[1]


# ── overlapping peaks fitted by hand ────────────────────────────────────────
# The analyst clicks two or three apexes between two edges; the chosen shape
# per apex, summed on one straight baseline, is fitted to the raw signal over
# those edges by iterative least squares (O'Haver, "Curve fitting C"; the
# pair fit, integrate_pair, generalised to n peaks). The words of each
# refusal are the add-on's (raw_review), so the card repeats them.

def _review_words():
    from .addon import load
    return load("raw_review")


FIT_NOT_CONVERGED = _review_words().FIT_NOT_CONVERGED
FIT_RESIDUAL = _review_words().FIT_RESIDUAL
FIT_INTERVAL = _review_words().FIT_INTERVAL
FIT_COUNT = _review_words().FIT_COUNT
FIT_APART = _review_words().FIT_APART
FIT_FEW = _review_words().FIT_FEW
FIT_NO_NOISE = _review_words().FIT_NO_NOISE
FIT_COLLAPSED = _review_words().FIT_COLLAPSED
FIT_FEW_REFITS = _review_words().FIT_FEW_REFITS
FIT_NOT_COMPUTED = _review_words().FIT_NOT_COMPUTED
FIT_FLOOR = _review_words().FIT_FLOOR
# the add-on's raw_review.FIT_SHAPES is the same tuple (a lockstep test,
# test_fit_fixture): the engine stays free of the add-on
FIT_SHAPES = ("gaussian", "emg")
# each component's width and tail are bounded as the pair fit bounds them
FIT_SIGMA = (0.005, 0.2)
FIT_TAU = (0.002, 0.2)
# the approximate 95 % interval of a fitted area (the card's preview):
# area +/- this many standard errors from the fit's covariance
Z95 = 1.96
# the reported interval: the middle 95 % of the area over this many refits
# of the fit with its own residuals resampled, and the share of them that
# must converge
FIT_RESAMPLES = 200
FIT_RESAMPLED_SHARE = 0.9
# a refit starts at the fit itself: one that has not settled within this
# many evaluations has not converged
FIT_REFIT_MAXFEV = 1000
# a parameter this share of its bounds' span (or of the largest area) from a
# bound sits on it
FIT_ON_BOUND = 1e-6
# the solvers every start of a fit is solved with, the closest fit kept
FIT_SOLVERS = ("trf", "dogbox")
# a refit starts this share of the span inside any bound the fit sits on:
# one started on a bound stops there and narrows the interval
FIT_INSIDE = 1e-3
# the fits kept, by their seed and refits: a run processed again reuses them
FIT_CACHE_SIZE = 512
_FIT_CACHE = OrderedDict()


class FitRefused(ValueError):
    """A fit that cannot be accepted: it did not converge, or its
    covariance cannot be read (FIT_NOT_CONVERGED)."""


class FitComponent(NamedTuple):
    """One fitted peak: its area and the area's standard error (the square
    root of its variance in the fit's covariance: the approximate interval,
    approx_interval), its centre `mu`, width `sigma` and tail `tau` (None
    for a Gaussian), its apex and its height above the fitted baseline
    there, and its resampled 95 % interval [lo, hi] (fit_peaks: the middle
    95 % of its area over the refits), the interval reported."""
    area: float
    se: float
    mu: float
    sigma: float
    tau: Optional[float]
    apex: float
    height: float
    lo: Optional[float] = None
    hi: Optional[float] = None


class FitResult(NamedTuple):
    """The fit: its shape, the components in the order their apexes were
    given, the baseline b0 + b1 (t - t0), its residual in % of the signal
    (residual_pct, for information), the RMS of its residual (the counts
    the fit leaves, judged against the trace's noise: fit_problem), the
    span (t0, t1) of the samples it was fitted to, how many resampled
    refits the interval was read on and the seed they were drawn with."""
    shape: str
    components: list
    b0: float
    b1: float
    t0: float
    residual_pct: float
    span: tuple
    residual_rms: float = 0.0
    resamples: int = 0
    seed: int = 0
    # the refits drawn; `resamples` of them converged
    refits: int = 0


def residual_pct(y, yhat):
    """O'Haver's percent fitting error: 100 x ||y - yhat|| / ||y||, the raw
    signal against the model with its baseline, over the fitted span; an
    all-zero signal has none (inf)."""
    y, yhat = np.asarray(y, dtype=float), np.asarray(yhat, dtype=float)
    norm = float(np.linalg.norm(y))
    return 100.0 * float(np.linalg.norm(y - yhat)) / norm if norm > 0 else float("inf")


def _component(shape, x, p):
    return gaussian(x, *p) if shape == "gaussian" else emg(x, *p)


def _rows(shape, x, P, peaks):
    """The fit's model at the samples `x` for each row of parameters `P`
    (m, k): [m, len(x)], every row in one pass. The same sum as
    fit_peaks' model: each peak's shape on the line P[:, -2] + P[:, -1]
    (x - x[0])."""
    n = 3 if shape == "gaussian" else 4
    x = np.asarray(x, dtype=float)[None, :]
    out = P[:, -2:-1] + P[:, -1:] * (x - x[0, 0])
    for j in range(peaks):
        area, mu, sigma = P[:, j * n:j * n + 1], P[:, j * n + 1:j * n + 2], P[:, j * n + 2:j * n + 3]
        if shape == "gaussian":
            out = out + area / (sigma * math.sqrt(2 * math.pi)) * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
            continue
        tau = P[:, j * n + 3:j * n + 4]
        z = (sigma / tau - (x - mu) / sigma) / math.sqrt(2)
        lead = erfcx(np.clip(z, 0, None)) * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
        # the trailing side's exponent is below zero wherever it is used
        trail = erfc(z) * np.exp(np.minimum(sigma ** 2 / (2 * tau ** 2) - (x - mu) / tau, 0.0))
        out = out + area / (2 * tau) * np.where(z < 0, trail, lead)
    return out


def _apex_of(shape, p):
    """(apex time, height above the baseline) of one fitted component: a
    Gaussian's centre, an EMG's mode read on a fine grid over its body."""
    if shape == "gaussian":
        area, mu, sigma = p
        return float(mu), float(area / (sigma * math.sqrt(2 * math.pi)))
    area, mu, sigma, tau = p
    grid = np.linspace(mu - 3 * sigma, mu + 3 * sigma + 3 * tau, 4001)
    vals = emg(grid, area, mu, sigma, tau)
    i = int(np.argmax(vals))
    return float(grid[i]), float(vals[i])


def fit_peaks(t, y, start, end, apexes, shape, settings=None, resamples=None, alone=False):
    """_fit_peaks, kept by its seed (the samples, the clicks and the shape:
    fit_seed) and its refits, so a run processed again reuses a fit, or its
    refusal, rather than making it again; and made on one BLAS thread, as a
    fit's arrays are too small to share."""
    resamples = FIT_RESAMPLES if resamples is None else int(resamples)
    if resamples == 0:
        # a point estimate, with no interval: made fresh and never kept, so
        # the fits an analyst applies keep their place in the cache
        if len(apexes) < (1 if alone else 2) or len(apexes) > 3:
            raise ValueError(FIT_COUNT)
        with threadpool_limits(1):
            return _fit_peaks(*_arrays(t, y), start, end, apexes, shape, 0)
    # a fit of overlapping peaks is of two or three apexes; `alone` fits the
    # one peak scored under a fitted shape (raw_run._fit_scores)
    if len(apexes) < (1 if alone else 2) or len(apexes) > 3:
        raise ValueError(FIT_COUNT)
    t, y = _arrays(t, y)
    s, e = int(np.argmin(abs(t - start))), int(np.argmin(abs(t - end)))
    key = (fit_seed(t[s:e + 1], y[s:e + 1], apexes, shape, order=True), resamples)
    if key not in _FIT_CACHE:
        try:
            with threadpool_limits(1):
                _FIT_CACHE[key] = _fit_peaks(t, y, start, end, apexes, shape, resamples)
        except FitRefused as exc:
            # its words only: the raised exception would keep the fit's frames alive
            _FIT_CACHE[key] = FitRefused(str(exc))
        while len(_FIT_CACHE) > FIT_CACHE_SIZE:
            _FIT_CACHE.popitem(last=False)
    _FIT_CACHE.move_to_end(key)
    got = _FIT_CACHE[key]
    if isinstance(got, FitRefused):
        raise FitRefused(str(got))
    return got._replace(components=list(got.components))


def _fit_peaks(t, y, start, end, apexes, shape, resamples):
    """The chosen shape ("gaussian" or "emg") at each of two or three
    `apexes`, summed on one straight baseline, fitted by curve_fit to the
    raw signal over the samples nearest `start` and `end`, both included.
    Each component starts at its click with the width the gaps allow, its
    area and the line read by linear least squares (_linear_areas); an EMG
    is started with a short tail and with one as long as its width, the
    closer fit kept. Its centre is held to the click plus or minus half the
    gap to the next click on each side (the outer side as the inner),
    inside the span; its width in FIT_SIGMA, its tail in FIT_TAU, its area
    at or above zero. `settings` are not read: the fit is the shape's
    alone.

    Each component's reported 95 % interval (lo, hi) is resampled: the fit
    is made again `resamples` times (FIT_RESAMPLES) with its own residuals
    drawn back onto the fitted model (_resampled_areas), seeded from the
    trace (fit_seed) so a rerun reports the same interval, and the middle
    95 % of each area is kept. The covariance's SE stays for the
    approximate interval (approx_interval).

    ValueError("two or three apexes") for fewer than 2 or more than 3;
    ValueError for apexes not apart and inside the span, an unknown shape
    or fewer samples than raw_review.fit_fewest. FitRefused
    (FIT_NOT_CONVERGED) when curve_fit does not converge, its covariance
    holds inf or nan (FIT_NOT_CONVERGED); the samples cannot be computed on
    (FIT_NOT_COMPUTED); a component collapsed (FIT_COLLAPSED: its area at
    none, or its centre, width or tail on a bound, a tail at its shortest
    excepted, which is the Gaussian the EMG tends to); or too few refits
    converge (FIT_FEW_REFITS)."""
    if shape not in FIT_SHAPES:
        raise ValueError("the shape is one of %s" % ", ".join(FIT_SHAPES))
    t, y = _arrays(t, y)
    s, e = int(np.argmin(abs(t - start))), int(np.argmin(abs(t - end)))
    tt, yy = t[s:e + 1], y[s:e + 1]
    clicks = [float(a) for a in apexes]
    order = sorted(range(len(clicks)), key=lambda k: clicks[k])
    times = [clicks[k] for k in order]
    if len(set(times)) != len(times) or not (len(tt) and tt[0] < times[0] and times[-1] < tt[-1]):
        raise ValueError(FIT_APART)
    if len(tt) < _review_words().fit_fewest(shape, len(clicks)):
        raise ValueError(FIT_FEW)
    t0 = float(tt[0])
    k = min(3, len(tt) // 2)
    left, right = float(np.mean(yy[:k])), float(np.mean(yy[-k:]))
    slope = (right - left) / (float(tt[-1]) - t0)
    line = left + slope * (tt - t0)
    gaps = [b - a for a, b in zip(times, times[1:])]
    if len(times) == 1:
        # one peak: its width is read from the span, edges lying about 3 sigma out
        gaps = [0.4 * (float(tt[-1]) - t0)]
    p0, lower, upper = [], [], []
    for i, mu in enumerate(times):
        below = gaps[i - 1] if i > 0 else gaps[0]
        above = gaps[i] if i < len(gaps) else gaps[-1]
        lo, hi = max(mu - below / 2.0, t0), min(mu + above / 2.0, float(tt[-1]))
        sig = float(np.clip(min(below, above) / 2.5, FIT_SIGMA[0], FIT_SIGMA[1]))
        h = max(float(np.interp(mu, tt, yy - line)), 1.0)
        area = h * sig * math.sqrt(2 * math.pi)
        if shape == "gaussian":
            p0 += [area, mu, sig]
            lower += [0.0, lo, FIT_SIGMA[0]]
            upper += [np.inf, hi, FIT_SIGMA[1]]
        else:
            tau = float(np.clip(sig / 2.0, FIT_TAU[0], FIT_TAU[1]))
            p0 += [area, mu, sig, tau]
            lower += [0.0, lo, FIT_SIGMA[0], FIT_TAU[0]]
            upper += [np.inf, hi, FIT_SIGMA[1], FIT_TAU[1]]
    p0 += [left, slope]
    lower += [-np.inf, -np.inf]
    upper += [np.inf, np.inf]
    n = 3 if shape == "gaussian" else 4
    upper_bounds = np.asarray(upper, dtype=float)

    def model(x, *p):
        return _rows(shape, x, np.asarray(p, dtype=float)[None, :], len(times))[0]

    def jac(x, *p):
        # forward differences, every step evaluated in one pass, each step
        # taken away from an upper bound it would cross
        p = np.asarray(p, dtype=float)
        h = np.sqrt(np.finfo(float).eps) * np.maximum(1.0, np.abs(p))
        h = np.where(p + h > upper_bounds, -h, h)
        rows = _rows(shape, x, np.vstack([p, p + np.diag(h)]), len(times))
        return ((rows[1:] - rows[0]) / h[:, None]).T
    model.jac = jac
    # an EMG is started twice, with a short tail and with one as long as
    # its width, and the closer fit kept: a tall peak's tail can otherwise
    # be taken by its neighbour
    try:
        starts = [_linear_areas(shape, tt, yy, p0, len(times))]
        if shape == "emg":
            longer = list(p0)
            for j in range(len(times)):
                longer[j * n + 3] = float(np.clip(p0[j * n + 2], FIT_TAU[0], FIT_TAU[1]))
            starts.append(_linear_areas(shape, tt, yy, longer, len(times)))
    except ValueError:                    # numpy's LinAlgError among them
        raise FitRefused(FIT_NOT_COMPUTED)
    # each start is solved twice, by the trust region kept inside the bounds
    # and by steps that stop on them (dogbox, as the card's preview also
    # solves it), and the closest fit of all kept: the two paths can settle
    # in different minima, a shoulder taking the main peak's tail on one
    p, cov, best = None, None, None
    for start_values in starts:
        for method in FIT_SOLVERS:
            try:
                q, qcov = _least_squares(model, tt, yy, start_values, (lower, upper), method=method)
            except ValueError:
                raise FitRefused(FIT_NOT_COMPUTED)
            if q is not None and np.all(np.isfinite(qcov)):
                cost = float(np.sum((yy - model(tt, *q)) ** 2))
                if best is None or cost < best:
                    p, cov, best = q, qcov, cost
    if p is None:
        raise FitRefused(FIT_NOT_CONVERGED)
    if collapsed(shape, p, lower, upper, len(times)):
        raise FitRefused(FIT_COLLAPSED)
    yhat = model(tt, *p)
    seed = fit_seed(tt, yy, times, shape)
    # no resamples: the point estimate alone, its components with no interval
    areas = (_resampled_areas(model, tt, yhat, yy - yhat, p, (lower, upper), [j * n for j in range(len(times))],
                              resamples, seed, _inside(p, lower, upper, len(times), shape))
             if resamples else None)
    fitted = []
    for j in range(len(times)):
        q = [float(v) for v in p[j * n:(j + 1) * n]]
        apex, height = _apex_of(shape, q)
        lo, hi = ((float(v) for v in np.percentile(areas[:, j], [2.5, 97.5]))
                  if areas is not None else (None, None))
        fitted.append(FitComponent(area=q[0], se=float(math.sqrt(max(cov[j * n, j * n], 0.0))), mu=q[1],
                                   sigma=q[2], tau=q[3] if shape == "emg" else None, apex=apex, height=height,
                                   lo=lo, hi=hi))
    # back in the order the apexes were given: a pick names one of them
    components = [None] * len(clicks)
    for j, k in enumerate(order):
        components[k] = fitted[j]
    return FitResult(shape=shape, components=components, b0=float(p[-2]), b1=float(p[-1]), t0=t0,
                     residual_pct=residual_pct(yy, yhat), span=(t0, float(tt[-1])),
                     residual_rms=float(np.sqrt(np.mean((yy - yhat) ** 2))),
                     resamples=len(areas) if areas is not None else 0, seed=seed,
                     refits=resamples)


def _on_bound(value, low, high, scale):
    """Whether `value` sits on `low` or `high` (an infinite bound is never
    reached), within FIT_ON_BOUND of `scale`."""
    tol = FIT_ON_BOUND * scale
    return (np.isfinite(low) and value - low <= tol) or (np.isfinite(high) and high - value <= tol)


def collapsed(shape, p, lower, upper, peaks):
    """Whether a fitted component collapsed: its area at none, or its
    centre, width or tail on a bound of its own. A tail at its shortest is
    not a collapse: the EMG has become the Gaussian it tends to."""
    n = 3 if shape == "gaussian" else 4
    largest = max([abs(float(p[j * n])) for j in range(peaks)] + [1.0])
    for j in range(peaks):
        for k in range(n):
            i = j * n + k
            if k == 3 and upper[i] - float(p[i]) > FIT_ON_BOUND * (upper[i] - lower[i]):
                continue                       # the tail at its shortest, or free
            scale = largest if k == 0 else upper[i] - lower[i]
            if _on_bound(float(p[i]), lower[i], upper[i], scale):
                return True
    return False


def _inside(p, lower, upper, peaks, shape):
    """`p` moved FIT_INSIDE of its bounds' span (or of the largest area)
    inside any bound it sits on: a refit started on a bound stops there."""
    n = 3 if shape == "gaussian" else 4
    largest = max([abs(float(p[j * n])) for j in range(peaks)] + [1.0])
    out = np.array(p, dtype=float)
    for i in range(len(out)):
        low, high = lower[i], upper[i]
        if not (np.isfinite(low) or np.isfinite(high)):
            continue
        step = FIT_INSIDE * (high - low if np.isfinite(high) and np.isfinite(low) else largest)
        if np.isfinite(low):
            out[i] = max(out[i], low + step)
        if np.isfinite(high):
            out[i] = min(out[i], high - step)
    return out


def _linear_areas(shape, x, y, p0, peaks):
    """`p0` with its areas and its line read by linear least squares with
    each peak's centre, width and tail held: the start a fit is made
    from, so a tall peak's tail is not first given to its neighbour. An
    area that reads below zero starts at a small share of the largest."""
    n = 3 if shape == "gaussian" else 4
    cols = []
    for j in range(peaks):
        # the peak alone at unit area, on no line
        unit = np.array([[1.0] + list(p0[j * n + 1:(j + 1) * n]) + [0.0, 0.0]])
        cols.append(_rows(shape, x, unit, 1)[0])
    cols += [np.ones_like(x), x - x[0]]
    coef = np.linalg.lstsq(np.column_stack(cols), y, rcond=None)[0]
    out = list(p0)
    floor = max(float(np.max(coef[:peaks])), 1.0) * 1e-3
    for j in range(peaks):
        out[j * n] = max(float(coef[j]), floor)
    out[-2], out[-1] = float(coef[-2]), float(coef[-1])
    return out


def _least_squares(model, x, y, p0, bounds, maxfev=40000, **kw):
    """(parameters, covariance) of curve_fit from `p0` within `bounds`, or
    (None, None) when it does not converge (its solver reports no
    convergence within `maxfev` evaluations) or a parameter is not finite;
    a covariance that cannot be estimated comes back as inf. ValueError
    when the samples or the start cannot be computed on."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            p, cov = curve_fit(model, x, y, p0=p0, bounds=bounds, maxfev=maxfev,
                               jac=getattr(model, "jac", None), **kw)
    except RuntimeError:
        return None, None
    return (p, cov) if np.all(np.isfinite(p)) else (None, None)


def fit_seed(t, y, apexes, shape, order=False):
    """The resampling's seed for one fit: read from the samples fitted and
    what was clicked, so the same trace fitted again draws the same
    refits and reports the same interval; with `order`, the clicks in the
    order given too (the components come back in it: the cache's key)."""
    clicks = [float(a) for a in apexes] if order else sorted(float(a) for a in apexes)
    digest = hashlib.sha256(np.ascontiguousarray(t, dtype="<f8").tobytes()
                            + np.ascontiguousarray(y, dtype="<f8").tobytes()
                            + repr((clicks, shape)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")


def _resampled_areas(model, x, yhat, resid, p, bounds, at, resamples, seed, start=None):
    """[refit, component] areas of a residual bootstrap: `resamples` times
    the fit's own residuals, centred and widened for the parameters fitted
    (sqrt(n / (n - k))), are drawn with replacement onto the fitted model
    and fitted again from `start` (the fit's parameters moved inside any
    bound they sit on: _inside), each parameter scaled by the Jacobian. A
    refit that does not converge, or cannot be computed, is dropped;
    FitRefused (FIT_FEW_REFITS) when fewer than FIT_RESAMPLED_SHARE of them
    converge."""
    rng = np.random.default_rng(seed)
    resid = (resid - resid.mean()) * math.sqrt(len(resid) / float(len(resid) - len(p)))
    start = p if start is None else start
    out = []
    for _i in range(resamples):
        try:
            q, _cov = _least_squares(model, x, yhat + rng.choice(resid, size=len(resid), replace=True), start,
                                     bounds, FIT_REFIT_MAXFEV, x_scale="jac")
        except ValueError:
            q = None
        if q is not None:
            out.append([q[k] for k in at])
    if not out or len(out) < FIT_RESAMPLED_SHARE * resamples:
        raise FitRefused(FIT_FEW_REFITS)
    return np.asarray(out, dtype=float)


def approx_interval(component):
    """[low, high] of a component's approximate 95 % interval, area +/- Z95
    x SE from the fit's covariance: the card's preview, labelled
    approximate; the interval reported is the resampled one (lo, hi)."""
    return [component.area - Z95 * component.se, component.area + Z95 * component.se]


def noise_multiple(result, noise):
    """How many times the trace's baseline noise (the sigma its S/N is read
    against) the fit leaves: the RMS of its residual over the fitted span
    over `noise`; inf for a residual over no noise, None without a noise."""
    if noise is None:
        return None
    if not noise > 0:
        return 0.0 if result.residual_rms == 0 else float("inf")
    return result.residual_rms / float(noise)


def fit_problem(result, pick, max_noise_multiple, noise):
    """Why a fit cannot be reported, or "": no baseline noise to judge it
    by (FIT_NO_NOISE); a residual RMS over the method's largest multiple of
    the trace's baseline noise (FIT_RESIDUAL), so a good fit passes at any
    level; or the picked component's resampled 95 % interval wider than its
    area, hi - lo > area (FIT_INTERVAL)."""
    multiple = noise_multiple(result, noise)
    if multiple is None:
        return FIT_NO_NOISE
    if not multiple <= max_noise_multiple:
        from .addon import load
        return FIT_RESIDUAL % (load("raw_preview")._above(multiple, max_noise_multiple), max_noise_multiple)
    comp = result.components[pick]
    if comp.hi - comp.lo > comp.area:
        counts = _review_words().counts
        return FIT_INTERVAL % (counts(comp.lo), counts(comp.hi))
    return ""


def fit_record(result, pick, apexes, noise=None, limit=None):
    """The fit as a peak's record keeps it, so the value can be reproduced:
    {"shape", "components": [{"area", "se", "mu", "sigma", "tau"}],
    "baseline": [b0, b1, t0], "pick", "ci": the picked component's
    resampled 95 % interval [low, high], "ci_approx": its approximate one
    (approx_interval), "resamples" (the refits that converged, which the
    interval was read on), "refits" (those drawn) and "seed",
    "residual_rms", "noise" (the trace's baseline noise),
    "noise_multiple" (the one over the other) and "noise_multiple_limit"
    (the method's largest, in force when it was judged), "apexes" as
    clicked, "span": [t0, t1]}."""
    comp = result.components[pick]
    return {"shape": result.shape,
            "components": [{"area": c.area, "se": c.se, "mu": c.mu, "sigma": c.sigma, "tau": c.tau}
                           for c in result.components],
            "baseline": [result.b0, result.b1, result.t0], "pick": pick, "ci": [comp.lo, comp.hi],
            "ci_approx": approx_interval(comp), "resamples": result.resamples, "refits": result.refits,
            "seed": result.seed, "residual_rms": result.residual_rms, "noise": noise,
            "noise_multiple": noise_multiple(result, noise), "noise_multiple_limit": limit,
            "apexes": [float(a) for a in apexes], "span": list(result.span)}


def fitted_peak(result, pick, apexes, noise=None, limit=None, min_sn=None):
    """The picked component as a Peak: its area and apex, its edges at
    mu - 3 sigma and mu + 3 sigma (+ 3 tau for an EMG) with the fitted
    baseline there, its height over `noise` as its S/N, measured by "fit,
    <shape>", carrying the fit's record (fit_record, `limit` the method's
    largest fit residual in force). Under `min_sn`, the engine's detection
    floor, it is not detected, as the engine reads such a peak: no area,
    no time, its S/N and the fit's record kept."""
    c = result.components[pick]
    start, end = c.mu - 3 * c.sigma, c.mu + 3 * c.sigma + (3 * c.tau if c.tau is not None else 0.0)
    sn = _sn(c.height, noise) if noise is not None else None
    record = fit_record(result, pick, apexes, noise, limit)
    method = "fit, " + result.shape
    if min_sn is not None and sn is not None and not sn >= min_sn:
        return dataclasses.replace(
            _not_detected(method, sn, FIT_FLOOR % min_sn, noise), fit=record)

    def base(x):
        return result.b0 + result.b1 * (x - result.t0)
    return Peak(c.area, c.apex, start, end, base(start), base(end), sn, method, True, noise=noise, fit=record,
                height=float(c.height))
