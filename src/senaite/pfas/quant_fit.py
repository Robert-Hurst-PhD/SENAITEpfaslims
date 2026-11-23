# -*- coding: utf-8 -*-
"""The calibration fit for runs integrated from raw data.

A curve is fitted to its calibrators' (concentration, response ratio)
points the way the method profile says (calibration_fit): linear or
quadratic with no, 1/x or 1/x2 weighting, or the mean response factor. The
curve card fits and reads every curve the same way
(browser/static/calibration_fit.js):

* Origin, for a line and a quadratic alike. Exclude: the curve has a
  constant term. Force: it has none, no point is added and the calibrators
  keep their weights. Include: the origin is added as one point weighted as
  the lowest calibrator (origin_weight), so the curve does not change with
  the concentration unit.
* The mean response factor passes through the origin by definition: its
  origin is Force whatever the method says, unweighted, its R² that of the
  line through the origin with every weight 1.
* A quadratic is weighted least squares by a QR decomposition, R² with the
  fit's own weights, and must rise across its whole calibration range, from
  its lowest calibrator to its highest; one that turns within it is refused
  (TURNS). A standard reads a ratio on the curve's rising branch
  (concentration); a native in a sample reads only between the lowest and
  the highest calibrator (sample_reading).

Pure; Python 2.7 and 3, no numpy.
"""
from __future__ import absolute_import, division, unicode_literals

import math

# the distinct concentrations each fit needs; fewer leaves the curve unfit
CONCENTRATIONS_NEEDED = {"linear": 2, "quadratic": 3, "mean_response_factor": 1}
# what a value's record says when its ratio has no reading on the curve
NO_READING = "the response ratio is not reached on the rising branch of this run's quadratic curve"
# why a quadratic is refused: it turns within its calibration range
TURNS = "turns"
# where a sample's ratio lies against the curve's calibration range
BELOW, ABOVE = "below", "above"
# what a sample's record says when its ratio is below the lowest calibrator
BELOW_READING = "below the lowest calibrator on this run's quadratic curve"
# what the pipeline found when it judged that reading against the MDL: the
# number is kept at or above it, never below it nor with no MDL to judge by
BELOW_AT_MDL = "at or above the MDL: read on the curve between zero and the lowest calibrator"
BELOW_UNDER_MDL = "below the MDL: no number"
BELOW_NO_MDL = "no MDL is set for this analyte and matrix: no number below the lowest calibrator"
BELOW_NO_ROOT = "no reading at or above zero on the rising branch: no number"
BELOW_OTHER_UNIT = "the reading and the MDL are in different units: no number"


def _weight(x, weighting):
    if weighting == "1/x":
        return 1.0 / x
    if weighting == "1/x2":
        return 1.0 / (x * x)
    return 1.0


def _r2(points, weights, slope, intercept):
    sw = sum(weights)
    ymean = sum(w * y for w, (x, y) in zip(weights, points)) / sw
    ss_res = sum(w * (y - (intercept + slope * x)) ** 2 for w, (x, y) in zip(weights, points))
    ss_tot = sum(w * (y - ymean) ** 2 for w, (x, y) in zip(weights, points))
    return 1.0 - ss_res / ss_tot if ss_tot else None


def origin_weight(points, weighting):
    """The weight of the origin included as a point: the lowest calibrator's
    (1 unweighted, 1/x_low under 1/x, 1/x_low² under 1/x²), which does not
    depend on the concentration unit as a weight of 1 would."""
    return _weight(min(x for x, _ in points), weighting)


def concentrations_needed(kind):
    return CONCENTRATIONS_NEEDED.get(kind, CONCENTRATIONS_NEEDED["linear"])


def _wls(points, weights, powers):
    """{power: coefficient} minimising sum w (y - sum c_k x^k)^2, by a
    Householder QR of sqrt(w) X (as ml-matrix solves it for the card); None
    when the columns are not independent."""
    a = [[math.sqrt(w) * x ** k for k in powers] for w, (x, _y) in zip(weights, points)]
    b = [math.sqrt(w) * y for w, (_x, y) in zip(weights, points)]
    m, n = len(a), len(powers)
    if m < n:
        return None
    diag = []
    for k in range(n):
        norm = math.sqrt(sum(a[i][k] ** 2 for i in range(k, m)))
        if norm == 0.0:
            return None
        alpha = -norm if a[k][k] >= 0 else norm
        v = [a[i][k] for i in range(k, m)]
        v[0] -= alpha
        vv = sum(t * t for t in v)
        for j in range(k, n):
            f = 2.0 * sum(v[i - k] * a[i][j] for i in range(k, m)) / vv
            for i in range(k, m):
                a[i][j] -= f * v[i - k]
        f = 2.0 * sum(v[i - k] * b[i] for i in range(k, m)) / vv
        for i in range(k, m):
            b[i] -= f * v[i - k]
        diag.append(abs(a[k][k]))
    if min(diag) <= 1e-12 * max(diag):
        return None
    c = [0.0] * n
    for k in reversed(range(n)):
        c[k] = (b[k] - sum(a[k][j] * c[j] for j in range(k + 1, n))) / a[k][k]
    return dict(zip(powers, c))


def rises_across(curve, low, high):
    """A quadratic's slope c1 + 2·c2·x is above zero at its lowest and its
    highest calibrator, and so everywhere between: the curve is continuous
    and monotonic across its calibration range."""
    a, b = curve.get("quadratic") or 0.0, curve.get("slope") or 0.0
    return b + 2.0 * a * low > 0 and b + 2.0 * a * high > 0


def _quadratic(points, weighting, origin, curve, why=None):
    """A weighted quadratic: three distinct concentrations at least; with
    the origin forced, no constant term; included, the point (0, 0)
    weighted as the lowest calibrator. A curve that turns within its
    calibration range is refused, TURNS appended to `why`."""
    if len(set(x for x, _ in points)) < concentrations_needed("quadratic"):
        return None
    low, high = min(x for x, _ in points), max(x for x, _ in points)
    weights = [_weight(x, weighting) for x, _ in points]
    if origin == "include":
        weights = [origin_weight(points, weighting)] + weights
        points = [(0.0, 0.0)] + points
    powers = (1, 2) if origin == "force" else (0, 1, 2)
    coef = _wls(points, weights, powers)
    if coef is None:
        return None
    c0, c1, c2 = coef.get(0, 0.0), coef[1], coef[2]
    sw = sum(weights)
    ymean = sum(w * y for w, (x, y) in zip(weights, points)) / sw
    ss_res = sum(w * (y - (c0 + c1 * x + c2 * x * x)) ** 2 for w, (x, y) in zip(weights, points))
    ss_tot = sum(w * (y - ymean) ** 2 for w, (x, y) in zip(weights, points))
    curve.update(slope=c1, intercept=c0, quadratic=c2, r2=1.0 - ss_res / ss_tot if ss_tot else None)
    if not rises_across(curve, low, high):
        if why is not None:
            why.append(TURNS)
        return None
    return curve


def fit(points, kind, weighting, origin, why=None):
    """The curve, or None when it cannot be fitted: fewer than two points,
    a linear fit with every point at one concentration, a quadratic with
    fewer than three, or a quadratic that turns within its calibration
    range (TURNS appended to the list `why`, when one is given). A
    quadratic's curve holds its x² term as `quadratic`; a straight line
    holds none. The mean response factor's curve is unweighted and forced
    through the origin, whatever weighting and origin are asked."""
    points = [(float(x), float(y)) for x, y in points if x is not None and y is not None and x > 0]
    curve = {"kind": kind, "weighting": weighting, "origin": origin}
    if kind == "quadratic":
        return _quadratic(points, weighting, origin, curve, why)
    if kind == "mean_response_factor":
        # a labelled compound is at one concentration in every calibrator
        if len(points) < 2:
            return None
        slope = sum(y / x for x, y in points) / len(points)
        weights = [1.0] * len(points)
        curve.update(origin="force", slope=slope, intercept=0.0, r2=_r2(points, weights, slope, 0.0))
        return curve
    if len(set(x for x, _ in points)) < 2:
        return None
    weights = [_weight(x, weighting) for x, _ in points]
    if origin == "force":
        sxx = sum(w * x * x for w, (x, _) in zip(weights, points))
        sxy = sum(w * x * y for w, (x, y) in zip(weights, points))
        slope = sxy / sxx
        curve.update(slope=slope, intercept=0.0, r2=_r2(points, weights, slope, 0.0))
        return curve
    if origin == "include":
        # the origin as a point, weighted as the lowest calibrator
        weights = [origin_weight(points, weighting)] + weights
        points = [(0.0, 0.0)] + points
    s = sum(weights)
    sx = sum(w * x for w, (x, _) in zip(weights, points))
    sy = sum(w * y for w, (_, y) in zip(weights, points))
    sxx = sum(w * x * x for w, (x, _) in zip(weights, points))
    sxy = sum(w * x * y for w, (x, y) in zip(weights, points))
    slope = (s * sxy - sx * sy) / (s * sxx - sx * sx)
    intercept = (sy - slope * sx) / s
    curve.update(slope=slope, intercept=intercept, r2=_r2(points, weights, slope, intercept))
    return curve


def _rising_root(curve, ratio):
    """c2 x^2 + c1 x + (c0 - R) = 0 on the curve's rising branch (where
    c1 + 2 c2 x > 0), by the cancellation-free form the card uses; None
    when R has no root there. A root below zero is returned as it is, as a
    straight line's reading below zero is."""
    a, b = curve["quadratic"], curve.get("slope") or 0.0
    c = (curve.get("intercept") or 0.0) - float(ratio)
    disc = b * b - 4.0 * a * c
    if disc < 0:
        return None
    q = -0.5 * (b + (1.0 if b >= 0 else -1.0) * math.sqrt(disc))
    roots = [q / a] + ([c / q] if q != 0 else [])
    rising = [x for x in roots if b + 2.0 * a * x > 0]
    return min(rising) if rising else None


def concentration(curve, ratio):
    """The concentration a response ratio reads on the curve; None when it
    has none (no curve, or a quadratic the ratio never reaches on its
    rising branch)."""
    if ratio is None or not curve:
        return None
    if curve.get("quadratic"):
        return _rising_root(curve, ratio)
    if not curve.get("slope"):
        return None
    return (float(ratio) - curve.get("intercept", 0.0)) / curve["slope"]


def pct_deviation(curve, conc, ratio):
    """A calibrator's deviation from its nominal, as a fraction."""
    found = concentration(curve, ratio)
    if found is None or not conc:
        return None
    return (found - conc) / conc


def response_at(curve, conc):
    """The response ratio the curve gives at a concentration."""
    c = float(conc)
    return ((curve.get("intercept") or 0.0) + (curve.get("slope") or 0.0) * c
            + (curve.get("quadratic") or 0.0) * c * c)


def above_range(curve, ratio, top):
    """A ratio above the curve's response at its highest calibrator still on
    it, R > f(top): above the calibration range, whatever the fit, whether
    or not the curve has a reading for it."""
    if not curve or ratio is None or top is None:
        return False
    at_top = response_at(curve, top)
    return float(ratio) > at_top + 1e-9 * abs(at_top)


def sample_reading(curve, ratio, bottom, top):
    """(concentration, place) of a native's ratio in a sample: place is
    ABOVE for a ratio above the curve's response at its highest calibrator
    (above_range), BELOW for a quadratic's ratio below its response at its
    lowest, else None. Below a quadratic's lowest calibrator the reading is
    the one on the curve between zero and that calibrator, on the rising
    branch, None where there is none at or above zero: the caller keeps it
    as a number only at or above the MDL. Above, the extrapolated reading
    is kept where the curve reaches the ratio (None where it never does). A
    straight line reads as concentration() does."""
    if ratio is None or not curve:
        return None, None
    if curve.get("quadratic") and bottom is not None and float(ratio) < response_at(curve, bottom):
        reading = concentration(curve, ratio)
        return (reading if reading is not None and reading >= 0 else None), BELOW
    return concentration(curve, ratio), (ABOVE if above_range(curve, ratio, top) else None)
