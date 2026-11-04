# -*- coding: utf-8 -*-
"""An in-house (gravimetric) pipette calibration, worked out from the
weighings: per test volume, five weighings of water in
mg; volume = mass x Z at the water's temperature. Z (uL/mg) is worked out,
never typed: the density of air-free water from the Kell equation (Kell
1975, J. Chem. Eng. Data 20, 97-105), corrected for air buoyancy as ISO 8655-6
does (air 0.0012 g/mL, balance weights 8.0 g/mL; docs/REFERENCES.md).
Per test volume (ISO 8655-6 terms): the average volume, the accuracy
(average / nominal), the standard deviation, the RSD (the CV: SD / average)
and the PE, the systematic error ((average - nominal) / nominal). A volume
passes when the PE is within the pipette's permissible systematic error and
the RSD within its permissible random error (Equipment settings; the lab's
values, from ISO 8655-2 or the manufacturer); the calibration passes when
every volume does. Without
the water temperature or the limits nothing is judged: the result is "not
evaluated", never a pass. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

import math

WEIGHINGS = 5

# ISO 8655-6 conditions for Z: air density and the density of the balance's
# reference weights (g/mL)
AIR_DENSITY = 0.0012
WEIGHT_DENSITY = 8.0
# the water temperatures a lab measures; outside them nothing is worked out
TEMP_RANGE = (0.0, 40.0)


def water_density(temp):
    """Density of air-free water (g/mL) at `temp` deg C, Kell (1975)."""
    t = temp
    rho = (999.83952 + 16.945176 * t - 7.9870401e-3 * t ** 2 - 46.170461e-6 * t ** 3
           + 105.56302e-9 * t ** 4 - 280.54253e-12 * t ** 5) / (1 + 16.879850e-3 * t)
    return rho / 1000.0


def z_factor(temp):
    """Z (uL/mg) at the water temperature, or None without one or outside
    TEMP_RANGE."""
    if temp is None or not (TEMP_RANGE[0] <= temp <= TEMP_RANGE[1]):
        return None
    return (1.0 / (water_density(temp) - AIR_DENSITY)) * (1.0 - AIR_DENSITY / WEIGHT_DENSITY)


from senaite.pfas.rounding import number as _num


def from_grams(values):
    """Weighings typed in g, as the balance shows them, in mg (what the
    calibration works in); a blank or unreadable one is None."""
    out = []
    for v in values or []:
        g = _num(v)
        out.append(round(g * 1000.0, 6) if g is not None else None)
    return out


def evaluate(volumes, z, systematic_limit, random_limit):
    """volumes: [{"volume": uL, "weighings": [mg] * 5}]. Returns
    (rows, passed, problems): each row with mean_ul, sd_ul, accuracy_pct,
    rsd_pct, systematic_pct (the PE) and passed (True / False / None = not
    evaluated); passed is True only when every volume passed."""
    problems, out = [], []
    if not volumes:
        problems.append(u"Enter at least one test volume with its five weighings.")
    for r in volumes or []:
        vol = _num(r.get("volume"))
        masses = [_num(w) for w in (r.get("weighings") or [])]
        row = {"volume": vol, "weighings": masses, "mean_ul": None, "sd_ul": None,
               "accuracy_pct": None, "rsd_pct": None, "systematic_pct": None, "passed": None}
        if vol is None or vol <= 0:
            problems.append(u"Each row needs its test volume.")
        elif len(masses) != WEIGHINGS or any(m is None for m in masses):
            problems.append(u"%g µL needs %d weighings." % (vol, WEIGHINGS))
        elif z is not None:
            vols = [m * z for m in masses]
            mean = sum(vols) / len(vols)
            sd = math.sqrt(sum((v - mean) ** 2 for v in vols) / (len(vols) - 1))
            row["mean_ul"] = round(mean, 3)
            row["sd_ul"] = round(sd, 3)
            row["accuracy_pct"] = round(mean / vol * 100.0, 2)
            row["systematic_pct"] = round((mean - vol) / vol * 100.0, 2)
            row["rsd_pct"] = round(sd / mean * 100.0, 2) if mean else None
            if systematic_limit is not None and random_limit is not None and row["rsd_pct"] is not None:
                row["passed"] = (abs(row["systematic_pct"]) <= systematic_limit
                                 and row["rsd_pct"] <= random_limit)
        out.append(row)
    verdicts = [r["passed"] for r in out]
    passed = None if (not out or None in verdicts) else all(verdicts)
    return out, passed, problems
