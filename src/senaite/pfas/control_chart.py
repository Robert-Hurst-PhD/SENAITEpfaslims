# -*- coding: utf-8 -*-
"""Levey-Jennings control charts, with the Westgard rules as an optional view
(DECISIONS 2026-10-02; docs/REUSE_REVIEW.md U7 -- no maintained library fits:
the one SPC package is GPLv3).

    points = [{"id": <qc_results id>, "value": float, ...}, ...]   oldest first

* limits(values)          mean, SD and the +/-1/2/3 SD lines from the first
                          20 values (the baseline); None below 5 values
* lj_warnings(points, L)  one warning per point beyond +/-2 SD, marked as
                          beyond the +/-3 SD control limit when it is
* westgard(points, L)     the multi-rule set (1-2s, 1-3s, 2-2s, R-4s, 4-1s,
                          10x) for the Westgard view
* active(warnings, dismissed)  warnings not dismissed

A warning's `key` is "<point id>:<rule>" -- what a dismissal is recorded
against, so dismissing one rule on a point leaves its other rules standing.
Removed (excluded) points are taken out BEFORE any of this: they are off the
chart, out of the baseline and raise nothing. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

import math

BASELINE_N = 20
MIN_POINTS = 5


def limits(values, n_baseline=BASELINE_N):
    valid = [float(v) for v in values
             if v is not None and not (math.isinf(v) or math.isnan(v))]
    if len(valid) < MIN_POINTS:
        return None
    base = valid[:n_baseline]
    n = len(base)
    mean = sum(base) / n
    sd = (sum((x - mean) ** 2 for x in base) / (n - 1)) ** 0.5
    if sd == 0.0:
        sd = max(abs(mean) * 0.01, 0.01)
    out = {"mean": round(mean, 4), "sd": round(sd, 4), "n_baseline": n}
    for k in (1, 2, 3):
        out["ucl_%d" % k] = round(mean + k * sd, 4)
        out["lcl_%d" % k] = round(mean - k * sd, 4)
    return out


def _sigmas(points, lim):
    mean, sd = lim["mean"], lim["sd"]
    return [(p["value"] - mean) / sd if sd else 0.0 for p in points]


def _warning(points, indices, rule, message, severity):
    first = points[indices[-1]]
    return {"key": u"%s:%s" % (first.get("id"), rule), "rule": rule,
            "message": message, "severity": severity,
            "indices": list(indices), "point_id": first.get("id")}


def lj_warnings(points, lim):
    """Every point beyond +/-2 SD -- the Levey-Jennings view's warnings."""
    if not lim or not points:
        return []
    out = []
    for i, s in enumerate(_sigmas(points, lim)):
        if abs(s) > 3.0:
            out.append(_warning(points, [i], u"3SD",
                                u"Beyond the ±3 SD control limit", u"reject"))
        elif abs(s) > 2.0:
            out.append(_warning(points, [i], u"2SD",
                                u"Beyond ±2 SD", u"warning"))
    return out


def westgard(points, lim):
    """The Westgard multi-rule set over the points, oldest first."""
    if not lim or not points:
        return []
    sig = _sigmas(points, lim)
    out, seen = [], set()

    def add(rule, message, severity, idx):
        if (rule, tuple(idx)) not in seen:
            seen.add((rule, tuple(idx)))
            out.append(_warning(points, idx, rule, message, severity))

    for i, s in enumerate(sig):                       # every point, the first too
        if abs(s) > 3.0:
            add(u"1-3s", u"One value beyond ±3 SD", u"reject", [i])
        elif abs(s) > 2.0:
            add(u"1-2s", u"One value beyond ±2 SD (warning)", u"warning", [i])
        if i >= 1:
            p = sig[i - 1]
            if (s > 2.0 and p > 2.0) or (s < -2.0 and p < -2.0):
                add(u"2-2s", u"Two consecutive values beyond the same 2 SD", u"reject", [i - 1, i])
            if abs(s - p) >= 4.0:
                add(u"R-4s", u"Adjacent values 4 SD or more apart", u"reject", [i - 1, i])
        if i >= 3:
            run = sig[i - 3:i + 1]
            if all(v > 1.0 for v in run) or all(v < -1.0 for v in run):
                add(u"4-1s", u"Four consecutive values beyond the same 1 SD",
                    u"reject", list(range(i - 3, i + 1)))
        if i >= 9:
            run = sig[i - 9:i + 1]
            if all(v > 0 for v in run) or all(v < 0 for v in run):
                add(u"10x", u"Ten consecutive values on one side of the mean",
                    u"reject", list(range(i - 9, i + 1)))
    return out


def active(warnings, dismissed_keys):
    """The warnings still standing (not dismissed)."""
    dismissed_keys = set(dismissed_keys or ())
    return [w for w in warnings if w["key"] not in dismissed_keys]
