# -*- coding: utf-8 -*-
"""A thermometer's correction to the reference thermometer.

A fixed sensor (a fridge's, a freezer's, a room's) adds a single correction
factor, from its latest passed study. An IR gun or a handheld thermometer is
calibrated at each of its working temperatures (for example -20, 4 and
20 deg C): one study per temperature, four paired readings over two days, gives
a point -- probe average, reference average. A reading is corrected by
linear interpolation between the points around it; outside them, by the
end segment extended, and marked outside the studied range (the reading is
taken). With some working temperatures not yet studied the points there are
are used (one point: its offset) and the missing temperatures named; with
none the reading is uncorrected. Which a unit uses is its equipment type's
option (equipment_types: correction_model).

    study_point(points)                 -> (probe avg, reference avg) | None
    in_force(studies, working_temps, as_of)
                                        -> {"model", "points", "missing"}
    single(current_correction)          -> {"model", "correction", ...}
    correct(reading, cal)               -> (corrected | None, outside)
    last_study_dates(studies, temps) / oldest(dates)   (due, per temperature)
    describe(cal)                       -> one line for the reports

A study: {"id", "study_temp", "study_date", "status", "points": [{
"sensor_reading", "nist_reading"}]}. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

SINGLE, MULTI = u"single", u"multi_point"
STUDY_POINTS = 4


def study_point(points):
    pairs = [(p.get("sensor_reading"), p.get("nist_reading")) for p in points or []
             if p.get("sensor_reading") is not None and p.get("nist_reading") is not None]
    if len(pairs) < STUDY_POINTS:
        return None
    n = float(len(pairs))
    return (round(sum(a for a, _b in pairs) / n, 3), round(sum(b for _a, b in pairs) / n, 3))


def _same(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


def _latest(studies, temp, as_of):
    """The latest passed study at this working temperature on or before the
    date that has its four readings, else None."""
    ok = [s for s in studies or [] if s.get("status") == u"pass" and _same(s.get("study_temp"), temp)
          and (s.get("study_date") or u"") <= (as_of or u"9999") and study_point(s.get("points"))]
    return max(ok, key=lambda s: (s.get("study_date") or u"", s.get("id") or 0)) if ok else None


def in_force(studies, working_temps, as_of):
    points, missing = [], []
    for t in working_temps or []:
        s = _latest(studies, t, as_of)
        if s is None:
            missing.append(t)
            continue
        probe, ref = study_point(s.get("points"))
        points.append({"working_temp": t, "probe": probe, "reference": ref,
                       "study_id": s.get("id"), "study_date": s.get("study_date")})
    return {"model": MULTI, "points": sorted(points, key=lambda p: p["probe"]), "missing": missing}


def single(current):
    """A single factor (facility_qc.current_correction's record) as a calibration."""
    cal = {"model": SINGLE, "correction": None, "study_id": None, "study_date": None}
    cal.update(current or {})
    return cal


def _line(p, q, x):
    return p["reference"] + (x - p["probe"]) * (q["reference"] - p["reference"]) / (q["probe"] - p["probe"])


def correct(reading, cal):
    """(corrected, outside the studied range). A record without "points"
    adds its "correction" (a single factor, or a CoC frozen with one)."""
    if reading is None or not cal:
        return None, False
    x = float(reading)
    if cal.get("model") != MULTI:
        c = cal.get("correction")
        return (round(x + c, 3), False) if c is not None else (None, False)
    pts = []
    for p in sorted(cal.get("points") or [], key=lambda p: p["probe"]):
        if pts and _same(pts[-1]["probe"], p["probe"]):
            continue                      # two studies reading the same: one point
        pts.append(p)
    if not pts:
        return None, False
    if len(pts) == 1:
        return round(x + pts[0]["reference"] - pts[0]["probe"], 3), False
    if x < pts[0]["probe"]:
        return round(_line(pts[0], pts[1], x), 3), True
    if x > pts[-1]["probe"]:
        return round(_line(pts[-2], pts[-1], x), 3), True
    for p, q in zip(pts, pts[1:]):
        if p["probe"] <= x <= q["probe"]:
            return round(_line(p, q, x), 3), False
    return None, False


def last_study_dates(studies, working_temps):
    """{working temperature: date of its latest passed study}; a temperature
    never studied is left out."""
    out = {}
    for t in working_temps or []:
        s = _latest(studies, t, None)
        if s is not None:
            out[t] = s.get("study_date")
    return out


def oldest(dates, working_temps=None):
    """The date the unit's due is counted from: the oldest of its working
    temperatures' latest studies; None while any temperature has none."""
    temps = working_temps if working_temps is not None else list(dates or {})
    if not dates or any(t not in dates for t in temps):
        return None
    return min(dates[t] for t in temps)


def _t(v):
    return (u"%g" % float(v)) if v is not None else u"?"


def _v(v):
    """A reading: up to three decimals, at least one ("4.0", "20.35")."""
    s = u"%.3f" % float(v)
    s = s.rstrip(u"0")
    return s + u"0" if s.endswith(u".") else s


def describe(cal):
    """"4 °C: 4.5 → 4.0; 20 °C: 20.3 → 20.0" (probe → reference per working
    temperature), or "+0.300 °C" for a single factor; "" for none."""
    cal = cal or {}
    if cal.get("model") != MULTI:
        c = cal.get("correction")
        return u"%+.3f \u00b0C" % c if c is not None else u""
    out = u"; ".join(u"%s \u00b0C: %s \u2192 %s" % (_t(p["working_temp"]), _v(p["probe"]), _v(p["reference"]))
                     for p in sorted(cal.get("points") or [], key=lambda p: p["working_temp"]))
    if cal.get("missing"):
        out += u"%snot studied: %s" % (u"; " if out else u"",
                                        u", ".join(u"%s \u00b0C" % _t(t) for t in cal["missing"]))
    return out
