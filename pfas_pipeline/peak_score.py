"""The one score of a peak's fit, 0 to 100, by checks on the fit alone.

Each check reads the trace and the fitted edges; none reads a QC outcome.
The weights and limits are peak_limits', shared with the add-on and read
through addon.load; besides it, numpy alone.

`noise` is the standard deviation of the trace's point-to-point baseline
noise, in the trace's own units (raw_adaptive's sigma; raw_integrate's Peak
noise), the figure S/N is read against. The three checks that compare the
trace with it (edges, inner rise, apex) are tolerant of random noise at that
level: a single point's scatter reaches several sigma on a long trace, so
the inner-rise check reads a 3-point mean and the apex a hysteresis of
APEX_NOISE sigma. With no noise (None or not above zero) those three checks
are not applicable and are left out of the score.
"""
from __future__ import annotations

import numpy as np

from pfas_pipeline import addon

L = addon.load("peak_limits")

# the share of the highest signal that makes the top of a peak
_TOP = 0.8
_FITS = ("gaussian", "emg")


def _line(t, start_i, end_i, base_start, base_end):
    """The baseline under start_i..end_i, straight between its two levels."""
    t0, t1 = t[start_i], t[end_i]
    if t1 == t0:
        return np.full(end_i - start_i + 1, float(base_start))
    return base_start + (base_end - base_start) * (t[start_i:end_i + 1] - t0) / (t1 - t0)


def apex_reversals(y, start_i, end_i, base, noise):
    """How many times the top fifth of the peak changes direction.

    The top fifth is the samples from start_i to end_i whose signal above
    the baseline line `base` (one level per sample of the span, or a single
    number) is at least 0.8 of the highest, in order. A move counts only
    once it exceeds `noise` from the last turning value (hysteresis), and
    every change of direction after that is a reversal: a clean peak gives
    1, its apex; more than 1 is jagged. The hysteresis is
    peak_limits.APEX_NOISE times `noise` (the trace's point noise sigma), so
    scatter at the noise level is not a reversal."""
    noise = L.APEX_NOISE * noise
    seg = np.asarray(y[start_i:end_i + 1], dtype=float) - base
    if seg.size == 0:
        return 0
    top = seg[seg >= _TOP * seg.max()]
    if top.size < 2:
        return 0
    direction = 0
    ref = top[0]
    reversals = 0
    for v in top[1:]:
        if direction == 0:
            if v - ref > noise:
                direction, ref = 1, v
            elif ref - v > noise:
                direction, ref = -1, v
        elif direction == 1:
            if v > ref:
                ref = v
            elif ref - v > noise:
                direction, ref = -1, v
                reversals += 1
        else:
            if v < ref:
                ref = v
            elif v - ref > noise:
                direction, ref = 1, v
                reversals += 1
    return reversals


def _inner_rise_ok(seg, apex, noise):
    """No rise on the way down and no fall on the way up beyond the limit,
    read on a 3-point mean so that scatter at the noise level stays inside it."""
    tol = L.RISE_NOISE * noise
    if seg.size >= 3:
        seg = np.convolve(np.pad(seg, 1, mode="edge"), np.ones(3) / 3.0, "valid")
    up = seg[:apex + 1]
    down = seg[apex:]
    worst_fall = float(np.max(np.maximum.accumulate(up) - up)) if up.size else 0.0
    worst_rise = float(np.max(down - np.minimum.accumulate(down))) if down.size else 0.0
    return worst_fall <= tol and worst_rise <= tol


def score(t, y, cand, noise, min_sn):
    """The fit score of one candidate: {"method", "score", "checks"}.

    cand: method, start, end, apex_i (trace indices), base_start, base_end
    (baseline levels at the edges), height, asymmetry, sn, residual_noise
    (the fit's residual over the baseline noise, None for the other
    methods). The total is round(100 * points / maximum) over the checks
    that apply. `noise` is the point-noise sigma (see the module docstring);
    without one the edges, inner-rise and apex checks do not apply. `min_sn`
    None means the method sets no floor, so the S/N check passes; a candidate
    with no S/N of its own fails it."""
    has_noise = noise is not None and noise > 0
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    s, e, a = int(cand["start"]), int(cand["end"]), int(cand["apex_i"])
    base = _line(t, s, e, cand["base_start"], cand["base_end"])
    seg = y[s:e + 1] - base
    height = float(cand["height"])
    edge_tol = L.EDGE_NOISE * (noise or 0.0)

    results = {
        "edges": has_noise and (abs(float(seg[0])) <= edge_tol and abs(float(seg[-1])) <= edge_tol),
        "inner_rise": has_noise and _inner_rise_ok(seg, min(max(a - s, 0), seg.size - 1), noise),
        "asymmetry": (cand.get("asymmetry") is not None
                      and L.ASYM_RANGE[0] <= cand["asymmetry"] <= L.ASYM_RANGE[1]),
        "sn": (cand.get("sn") is not None
               and (min_sn is None or cand["sn"] >= min_sn)),
        "slope": (abs(float(cand["base_end"]) - float(cand["base_start"]))
                  <= L.SLOPE_SHARE * height),
        "apex": has_noise and apex_reversals(y, s, e, base, noise) <= 1,
    }
    order = ["edges", "inner_rise", "asymmetry", "sn", "slope", "apex"]
    if not has_noise:
        order = [k for k in order if k not in ("edges", "inner_rise", "apex")]
    if cand["method"] in _FITS:
        rn = cand.get("residual_noise")
        results["residual"] = rn is not None and rn <= L.FIT_RESIDUAL_NOISE
        order.append("residual")

    checks = []
    for key in order:
        mx = L.WEIGHTS[key]
        ok = bool(results[key])
        checks.append({"key": key, "label": L.CHECK_LABELS[key],
                       "points": mx if ok else 0, "max": mx, "ok": ok})
    total = sum(c["max"] for c in checks)
    got = sum(c["points"] for c in checks)
    return {"method": cand["method"],
            "score": int(round(100.0 * got / total)),
            "checks": checks}
