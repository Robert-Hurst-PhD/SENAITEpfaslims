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
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks, savgol_filter
from scipy.special import erfc, erfcx

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
                area_method(settings, refused=fit_note is not None), True, fit_note=fit_note, noise=noise)


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
                skim_share=got["skim_share"])


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
                "summed", True, noise=noise)


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
                "summed", True, noise=noise)


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
                        noise=noise))
    return out[0], out[1]
