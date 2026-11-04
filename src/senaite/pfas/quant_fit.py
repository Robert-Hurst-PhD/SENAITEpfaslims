# -*- coding: utf-8 -*-
"""The calibration fit for runs integrated from raw data.

A curve is fitted to its calibrators' (concentration, response ratio)
points the way the method profile says (calibration_fit): linear with no,
1/x or 1/x2 weighting, or the mean response factor; the origin excluded,
included as a point, or forced. Pure; Python 2.7 and 3, no numpy.
"""
from __future__ import absolute_import, division, unicode_literals


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


def fit(points, kind, weighting, origin):
    """The curve, or None when it cannot be fitted: fewer than two points,
    or a linear fit with every point at one concentration."""
    points = [(float(x), float(y)) for x, y in points if x is not None and y is not None and x > 0]
    curve = {"kind": kind, "weighting": weighting, "origin": origin}
    if kind == "mean_response_factor":
        # a labelled compound is at one concentration in every calibrator
        if len(points) < 2:
            return None
        slope = sum(y / x for x, y in points) / len(points)
        weights = [1.0] * len(points)
        curve.update(slope=slope, intercept=0.0, r2=_r2(points, weights, slope, 0.0))
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
        weights = [max(weights)] + weights
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


def concentration(curve, ratio):
    """The concentration a response ratio reads on the curve."""
    if ratio is None or not curve or not curve.get("slope"):
        return None
    return (float(ratio) - curve.get("intercept", 0.0)) / curve["slope"]


def pct_deviation(curve, conc, ratio):
    """A calibrator's deviation from its nominal, as a fraction."""
    found = concentration(curve, ratio)
    if found is None or not conc:
        return None
    return (found - conc) / conc
