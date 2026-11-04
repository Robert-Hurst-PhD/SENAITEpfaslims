# -*- coding: utf-8 -*-
"""Adaptive peak finder for chromatographic traces.

Credits the peak-finding method published by Nagura Lab
(naguralab.com/integration), re-implemented from its description.

Method:
  noise     sigma = 1.4826 * MAD(first differences) / sqrt(2). A second pass
            recomputes it with every detected peak span and every excluded
            span masked, so branched isomers beside a linear peak do not
            inflate the noise.
  slope     Savitzky-Golay first derivative over 2m+1 points, minus the
            median slope of the run.
  window    first pass m = 2, retried at m = 3 and then m = 5 when it keeps
            no peak; then m = about a third of the width at half height of
            the largest peaks, and a second pass.
  edges     a peak starts where the slope exceeds k times the robust spread of
            the slope and ends where it stays within that for max(m, 3)
            points. A flat stretch above the shoulder fraction of the height
            is a shoulder: the peak splits there and the shoulder runs on to
            the true end. A rise before the end splits at the valley.
  tails     each edge moves outward while the smoothed signal keeps falling,
            at most as far again.
  baseline  straight, each end the mean over m points on the outer side of
            the edge, read at the centre of that window, and the line
            through the two centres extrapolated to the edges. A group of
            touching peaks shares one baseline and drop lines split it. Edge
            decisions run on the smoothed trace with the run's median drift
            removed.
  exclude   an excluded span belongs to another analyte's call: it is left
            out of the noise, and a candidate whose apex lies inside it is
            left out of the output only: its group and baseline are built
            with it in place.
  keep      height above the baseline >= min_sn times sigma, and the apex
            also clears the higher baseline end (a dip is not a peak). S/N
            is height over sigma.
  dip       a baseline end lies in a dip when it sits clearly below both
            the level the trace beyond it climbs back to and the baseline
            across the peak (_dips); the peak is flagged "baseline dip".
  measure   apex by a parabola through the top three smoothed points, offset
            clamped to half a point; area (never negative) is the
            trapezoid above the baseline in counts x minutes (t is in
            minutes); width at half height, USP tailing, plates. The
            half-height walk stops at an edge shared with an excluded
            member of the group, so a taller excluded neighbour does not
            widen the peak.
"""
import math

import numpy as np
from scipy.signal import savgol_filter

from .raw_integrate import BASELINES, check_levels, manual_line, neighbour_rise, settled_line


def robust_sigma(y, keep=None):
    """Noise from first differences. `keep` is an optional boolean mask of
    points to use; a difference counts only when both its points are kept."""
    y = np.asarray(y, float)
    d = np.diff(y)
    if keep is not None:
        keep = np.asarray(keep, bool)
        d = d[keep[:-1] & keep[1:]]
    if len(d) < 3:
        return 0.0
    med = np.median(d)
    mad = np.median(np.abs(d - med))
    s = 1.4826 * mad if mad > 0 else 1.2533 * np.mean(np.abs(d - med))
    return float(s / math.sqrt(2))


def _slope(t, y, m, drift=False):
    n = 2 * m + 1
    if len(y) < n + 2:
        n = max(3, (len(y) // 2) * 2 - 1)
    dt = float(np.median(np.diff(t)))
    s = savgol_filter(y, n, 1, deriv=1, delta=dt)
    if drift:
        return s - np.median(s), float(np.median(s))
    return s - np.median(s)


def _smooth(y, m):
    return savgol_filter(y, 2 * m + 1, 2) if len(y) > 2 * m + 3 else y


def _base(y, s, e, m):
    """Each end is the mean over m points on the outer side of the edge, read
    at the centre of that window; the line through the two centres is
    extrapolated to the edges."""
    w = max(m, 1)
    l0, r1 = max(s - w, 0), min(e + w, len(y) - 1)
    left = float(np.mean(y[l0:s + 1]))
    right = float(np.mean(y[e:r1 + 1]))
    cl, cr = (l0 + s) / 2.0, (e + r1) / 2.0
    k = (right - left) / (cr - cl)
    return [left + k * (s - cl), right + k * (e - cr)]


def _candidates(t, y, m, k, shoulder, hmin=0.0, keep=None):
    """Raw [start, apex, end] index triples with edges, drop lines and
    groups resolved, plus the smoothed trace. No height gate. `keep` is an
    optional boolean mask of the points an apex may lie on."""
    sl, drift = _slope(t, y, m, True)
    spread = 1.4826 * np.median(np.abs(sl - np.median(sl))) or (np.std(sl) or 1.0)
    thr = k * spread
    ys = _smooth(y, m)
    ysm = ys
    ys = ys - drift * (t - t[0])
    hold = max(m, 3)
    level = float(np.median(ys))
    peaks, i, n = [], 1, len(y)
    while i < n - 1:
        if sl[i] > thr:
            s = i
            while s > 0 and sl[s - 1] > 0:
                s -= 1
            j = i
            while j < n - 1 and sl[j] > 0:
                j += 1
            apex = j
            e, quiet = apex, 0
            s0 = s
            if hmin > 0:
                # a start never sits in a dip: move it to where the
                # detrended signal is back within the gate of the median
                while s0 < apex and ys[s0] < level - hmin:
                    s0 += 1
            floor = ys[s] + shoulder * (ys[apex] - ys[s])
            while e < n - 1:
                e += 1
                quiet = quiet + 1 if abs(sl[e]) <= thr else 0
                if quiet >= hold and ys[e] > floor:
                    split = e - quiet + 1
                    f, q2 = split, 0
                    # the shoulder runs on at most 12 times the distance from
                    # the start (out of any dip) to the split
                    reach = max(12 * (split - s0), hold)
                    while f < n - 1 and f - split < reach:
                        f += 1
                        q2 = q2 + 1 if abs(sl[f]) <= thr else 0
                        if (q2 >= hold and ys[f] <= floor) or sl[f] > thr:
                            break
                    peaks.append([s, apex, split])
                    s, apex, e = split, split + int(np.argmax(ys[split:f + 1])), f
                    break
                if quiet >= hold or sl[e] > thr and e > apex + 1:
                    break
            if sl[e] > thr and e < n - 1:
                e = apex + int(np.argmin(ys[apex:e + 1]))
            peaks.append([s, apex, e])
            i = max(e, i + 1)
        else:
            i += 1
    out = []
    for s, a, e in peaks:
        a = s + int(np.argmax(ys[s:e + 1]))
        lim = a - s
        ss = s
        while ss > 0 and a - ss < 2 * lim and ys[ss - 1] < ys[ss]:
            ss -= 1
        lim = e - a
        ee = e
        while ee < n - 1 and ee - a < 2 * lim and ys[ee + 1] < ys[ee]:
            ee += 1
        out.append([ss, a, ee])
    for p, q in zip(out, out[1:]):
        if p[2] > q[0]:
            v = p[1] + int(np.argmin(ys[p[1]:q[1] + 1]))
            p[2] = v
            q[0] = v
    while True:
        groups, cur = [], []
        for p in out:
            if cur and p[0] <= cur[-1][2]:
                cur.append(p)
            else:
                if cur:
                    groups.append(cur)
                cur = [p]
        if cur:
            groups.append(cur)
        cands, dropped = [], False
        for gi, grp in enumerate(groups):
            gs, ge = grp[0][0], grp[-1][2]
            gb = _base(y, gs, ge, m)
            for ci, (s, a, e) in enumerate(grp):
                if e <= s + 2:
                    continue
                # the half-height walk stops at an edge shared with an
                # excluded member of the group, and runs on elsewhere
                lo = s if ci > 0 and keep is not None and not keep[grp[ci - 1][1]] else 0
                hi = e if ci + 1 < len(grp) and keep is not None and not keep[grp[ci + 1][1]] else n - 1
                if keep is not None and not keep[a]:
                    # an apex inside an excluded span is another analyte's
                    # peak: it is left out of the output only, its group and
                    # baseline stay as built with it in place
                    continue
                if ys[a] - max(ys[gs], ys[ge]) < hmin:
                    # the recovery from a dip is not a peak; the group is
                    # rebuilt without it so it cannot pull the baseline down
                    out.remove([s, a, e])
                    dropped = True
                    break
                cands.append((s, a, e, gb, gs, ge, gi, ysm, lo, hi))
            if dropped:
                break
        if not dropped:
            return cands


def _line(t, gs, ge, gb, i):
    return float(np.interp(t[i], [t[gs], t[ge]], gb))


def _measure(t, y, s, a, e, b, h, ys=None, lo=None, hi=None, signed=False):
    """b is the baseline [left, right] over t[s]..t[e]. The half-height
    walk runs between lo and hi (default the whole trace); a crossing not
    found there gives no width. The area is never negative, unless
    `signed` (over levels set by hand: a part below the line counts
    against it)."""
    ys = y if ys is None else ys
    base_at = lambda i: float(np.interp(t[i], [t[s], t[e]], b))
    if 0 < a < len(t) - 1:
        y0, y1, y2 = ys[a - 1], ys[a], ys[a + 1]
        den = y0 - 2 * y1 + y2
        off = min(0.5, max(-0.5, 0.5 * (y0 - y2) / den)) if den < 0 else 0.0
        rt = t[a] + off * (t[a + 1] - t[a])
    else:
        rt = t[a]
    seg = slice(s, e + 1)
    base = np.interp(t[seg], [t[s], t[e]], b)
    area = float(np.trapezoid(y[seg] - base, t[seg]))
    area = area if signed else max(area, 0.0)
    half = base_at(a) + h / 2.0
    i = a
    lo = 0 if lo is None else lo
    hi = len(y) - 1 if hi is None else hi
    while i > lo and y[i] > half:
        i -= 1
    j = a
    while j < hi and y[j] > half:
        j += 1
    w = None
    if h > 0 and y[i] <= half and y[j] <= half and i > 0 and j < len(y) - 1:
        tl = np.interp(half, [y[i], y[i + 1]], [t[i], t[i + 1]])
        tr = np.interp(half, [y[j], y[j - 1]], [t[j], t[j - 1]])
        w = float(tr - tl)
    tail = None
    lvl = base_at(a) + 0.05 * h
    i = a
    while i > s and y[i] > lvl:
        i -= 1
    j = a
    while j < e and y[j] > lvl:
        j += 1
    if y[i] <= lvl and y[j] <= lvl:
        f = rt - t[i]
        tail = float((t[j] - t[i]) / (2 * f)) if f > 0 else None
    dt = float(np.median(np.diff(t)))
    return {
        "rt": float(rt), "area": area, "height": float(h),
        "start": float(t[s]), "end": float(t[e]), "base": [float(v) for v in b],
        "fwhm_s": w * 60 if w is not None and w > 0 else None, "tailing": tail,
        "plates": 5.54 * (rt / w) ** 2 if w is not None and w > 0 else None,
        "points_fwhm": w / dt if w is not None and w > 0 else None,
    }


def _arrays(t, y):
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    if np.isnan(t).any() or np.isnan(y).any():
        raise ValueError("trace contains NaN")
    return t, y


def _mask(t, spans):
    keep = np.ones(len(t), bool)
    for t0, t1 in spans:
        keep &= ~((t >= min(t0, t1)) & (t <= max(t0, t1)))
    return keep


def _pass(t, y, m, k, min_sn, shoulder, exclude):
    # The first noise estimate uses every point and gates the peaks. The
    # second estimate masks the spans of the peaks kept so far and the
    # excluded spans.
    sigma = robust_sigma(y)
    # the dip gate uses the noise outside the excluded spans
    outside = _mask(t, exclude)
    gate = robust_sigma(y, outside) or sigma
    cands = _candidates(t, y, m, k, shoulder, min_sn * gate, outside)
    spans = [(t[c[0]], t[c[2]]) for c in cands
             if c[7][c[1]] - _line(t, c[4], c[5], c[3], c[1]) >= min_sn * sigma]
    sigma2 = robust_sigma(y, _mask(t, list(spans) + list(exclude)))
    if sigma2 > 0:
        sigma = sigma2
    kept = []
    for s, a, e, gb, gs, ge, gi, ys, lo, hi in cands:
        b = [_line(t, gs, ge, gb, s), _line(t, gs, ge, gb, e)]
        h = float(ys[a] - _line(t, gs, ge, gb, a))
        if h >= min_sn * sigma:
            kept.append((s, a, e, b, h, gi, gs, ge, lo, hi))
    return kept, sigma, cands


def _local_noise(y, keep):
    """The point noise from second differences over kept points: a smooth
    slope or curve, such as a dip's flank or a tail, is not noise."""
    k = np.asarray(keep, bool)
    trip = k[:-2] & k[1:-1] & k[2:]
    d2 = (y[2:] - 2 * y[1:-1] + y[:-2])[trip]
    if len(d2) < 3:
        return 0.0
    return float(1.4826 * np.median(np.abs(d2 - np.median(d2))) / math.sqrt(6))


# a dip is judged on a side of at least this many baseline points; the
# baseline's scatter is read at least one peak width from every edge; the
# outer share of a side is the level it climbs back to; a side falls away
# when its median lies this share of the peak's height below the end; a
# side across standing this share of the height above the end is another
# peak's flank
DIP_MIN_POINTS = 5
DIP_FAR_POINTS = 10
DIP_OUTER = 0.25
DIP_FALL = 0.05
DIP_RIDER = 0.5


def _dips(t, y, kept, sigma, min_sn, exclude):
    """The indices of the kept peaks with a baseline end in a dip.

    The baseline is the trace outside every kept peak and excluded span.
    Each end is judged against the sides of its peak: its own side, the one
    beyond the end, and the side across the peak. A side's level is its
    median; its limit is min_sn times the largest of sigma, the scatter of
    the baseline at least a peak width from every edge (1.4826 x MAD), and
    the side's own point noise (_local_noise). An end is in a dip when it
    lies more than its own side's limit below the level of the outer
    quarter of its own side, where a dip has climbed back to the baseline,
    and more than the side across's limit below that side's level: an end
    below one side only is a step, a drift or a tail. An own side whose
    level lies far below the end is the dip running on past it: the end is
    then judged on the side across alone, unless that side stands more than
    half the peak's height above it, the flank of another peak, or the own
    side lies level, its outer quarter at its median, a lower baseline the
    end steps up from. An end with no baseline on its own side is not
    judged; one with fewer than DIP_MIN_POINTS points across the peak is
    judged on its own side alone."""
    base = _mask(t, [(t[k[0]], t[k[2]]) for k in kept] + list(exclude))
    far = base.copy()
    for k in kept:
        reach = t[k[2]] - t[k[0]]
        for edge in (t[k[0]], t[k[2]]):
            far &= ~((t >= edge - reach) & (t <= edge + reach))
    scatter = (1.4826 * float(np.median(np.abs(y[far] - np.median(y[far]))))
               if far.sum() >= DIP_FAR_POINTS else 0.0)
    floor = max(sigma, scatter)
    out = set()
    for i, (s, a, e, b, h, gi, gs, ge, lo, hi) in enumerate(kept):
        sides = []
        for n, mk in enumerate((base & (t < t[s]), base & (t > t[e]))):
            x = y[mk]
            if len(x) < DIP_MIN_POINTS:
                sides.append(None)
                continue
            outer_n = max(DIP_MIN_POINTS, int(round(DIP_OUTER * len(x))))
            outer = x[:outer_n] if n == 0 else x[-outer_n:]
            sides.append((float(np.median(outer)), float(np.median(x)),
                          min_sn * max(floor, _local_noise(y, mk))))
        for n, bv in enumerate(b):
            own, other = sides[n], sides[1 - n]
            if own is None:
                continue
            falls = own[1] < bv - DIP_FALL * h
            if falls and (other is None or other[1] - bv > DIP_RIDER * h):
                continue
            # an own side lying level below the end, its outer quarter at its
            # median, is a lower baseline: the end stands on a step
            if falls and abs(own[0] - own[1]) <= own[2]:
                continue
            if not falls and not bv < own[0] - own[2]:
                continue
            if other is not None and not bv < other[1] - other[2]:
                continue
            out.add(i)
    return out


def _build(t, y, kept, sigma, m, min_sn, exclude=()):
    out = []
    ys = _smooth(y, m)
    # a baseline end in a dip makes the area suspect: flagged for review.
    # Every end is a point on the group's line at the edge and is compared
    # there.
    dips = _dips(t, y, kept, sigma, min_sn, exclude) if len(y) >= 4 else set()
    for i, (s, a, e, b, h, gi, gs, ge, lo, hi) in enumerate(kept):
        p = _measure(t, y, s, a, e, b, h, ys, lo, hi)
        p["sn"] = h / sigma if sigma else float("inf")
        p["group"] = gi
        if i in dips:
            p["note"] = "baseline dip"
        out.append(p)
    return out


def find_peaks(t, y, k, min_sn, m=None, shoulder=0.10, exclude=()):
    """All peaks in a trace as (peaks, sigma, m_used). m None is adaptive:
    first pass m = 2 (then 3, then 5 while nothing is kept), then about
    points_fwhm / 3 of the largest peaks.
    `exclude` is a list of (t0, t1) spans left out of the noise estimate and
    out of detection: no peak is reported with its apex inside one. The
    other analyte's own call, with its exclude set to this analyte's span,
    detects and measures the peaks there."""
    t, y = _arrays(t, y)
    m0 = 2 if m is None else max(int(m), 1)
    if len(y) < 2:
        return [], 0.0, m0
    kept, sigma, _c = _pass(t, y, m0, k, min_sn, shoulder, exclude)
    if m is None and not kept:
        # an adaptive first pass that keeps nothing is retried with wider
        # windows before the trace is reported empty
        for m_retry in (3, 5):
            k_retry, s_retry, _c = _pass(t, y, m_retry, k, min_sn, shoulder, exclude)
            if k_retry:
                kept, sigma, m0 = k_retry, s_retry, m_retry
                break
    if m is None and kept:
        top = sorted(kept, key=lambda p: -p[4])[:3]
        ws = [_measure(t, y, *p[:5], lo=p[8], hi=p[9])["points_fwhm"] for p in top]
        ws = [w for w in ws if w]
        if ws:
            m1 = int(max(1, round(np.median(ws) / 3.0)))
            if m1 != m0:
                kept, sigma, _c = _pass(t, y, m1, k, min_sn, shoulder, exclude)
                m0 = m1
    return _build(t, y, kept, sigma, m0, min_sn, exclude), sigma, m0


def learn_m(t, y, rt, k, min_sn):
    """Half-width m learnt from the peak nearest rt, or None."""
    pk, _s, _m = find_peaks(t, y, k, min_sn)
    pk = [p for p in pk if p["points_fwhm"]]
    if not pk:
        return None
    p = min(pk, key=lambda q: abs(q["rt"] - rt))
    return int(max(1, round(p["points_fwhm"] / 3.0)))


def between(t, y, start, end, m, exclude=(), baseline="valley", sigma=None, levels=None, bounds=None, amp=None):
    """The peak between given edge times (manual re-integration), with the
    same measures as find_peaks. The S/N is the height over `sigma`, given
    (a manual peak is judged against the automatic call's noise, the number
    the review previewed), or else the noise with the integrated span and
    `exclude` masked. The width at half height is measured between the given
    edges: no crossing there gives no width. None when the span holds too
    few points. `baseline` is one of BASELINES, its levels the straight
    line of find_peaks (_base) read at the points the baseline reads
    (raw_integrate.manual_line): "valley" that line; "flat" flat at the
    lower of its two edge levels, a drop line to it from each edge, as the
    classic engine's; "drop" the line under the pair from its outer edges
    (`bounds`, else found from the neighbours, each rising `amp`, the
    peak search amplitude, times the noise above its valley); "skim" from
    the smoothed signal at the start to the smoothed signal at the end.
    `levels` [left, right] in counts replace the two levels, and the area
    then counts a part below the line against it. The peak carries its
    baseline, its levels, a drop's valley share and a skim's height over
    its parent's."""
    if baseline not in BASELINES:
        raise ValueError("baseline is one of %s" % ", ".join(BASELINES))
    levels = check_levels(levels)
    t, y = _arrays(t, y)
    if len(y) < 2:
        return None
    s = int(np.argmin(np.abs(t - min(start, end))))
    e = int(np.argmin(np.abs(t - max(start, end))))
    if e < s + 3:
        return None
    m = max(int(m), 1)
    ys = _smooth(y, m)
    a = s + int(np.argmax(ys[s:e + 1]))
    if sigma is None:
        sigma = robust_sigma(y, _mask(t, [(t[s], t[e])] + list(exclude)))
        if sigma <= 0:
            sigma = robust_sigma(y)
    rise = neighbour_rise(sigma, amp)
    ln, h, valley, skim = settled_line(
        t, ys, s, e, a, lambda skip: manual_line(t, ys, s, e, baseline, lambda i, j: _base(y, i, j, m), levels,
                                                 bounds, rise, skip))
    b = ln["b"]
    # the half-height walk stays between the analyst's edges
    p = _measure(t, y, s, a, e, b, h, ys, s, e, signed=levels is not None)
    p["sn"] = h / sigma if sigma else float("inf")
    p["group"] = 0
    p["valley_share"], p["skim_share"] = valley, skim
    p.update(baseline=baseline, levels=levels)
    return p
