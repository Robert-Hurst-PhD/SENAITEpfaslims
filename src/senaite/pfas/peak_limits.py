# -*- coding: utf-8 -*-
"""The limits a peak's fit score and its verdict colours share.

One definition for both sides: the worker reads this module through
addon.load("peak_limits") to score a fit, and the add-on imports it to draw
the verdicts. Pure, Python 2.7 and 3, standard library only.
"""

# the points each check of a fit's score is worth; the residual counts for
# the two fitted shapes only, so the other six total 100
WEIGHTS = {
    "edges": 25,
    "inner_rise": 20,
    "asymmetry": 15,
    "sn": 15,
    "slope": 10,
    "apex": 15,
    "residual": 20,
}

# the asymmetry factor is in range between these two
ASYM_RANGE = (0.8, 1.8)
# an edge is back to the baseline within this many times the noise
EDGE_NOISE = 3.0
# a rise (or a fall on the way up) inside the peak counts above this many
# times the noise
RISE_NOISE = 3.0
# the apex counts a change of direction only once the signal has moved
# this many times the noise from its last turning value
APEX_NOISE = 4.0
# the baseline slope is small when its end levels differ by no more than this
# share of the peak's height
SLOPE_SHARE = 0.10
# a fit's residual is acceptable within this many times the baseline noise
FIT_RESIDUAL_NOISE = 3.0

CHECK_LABELS = {
    "edges": "Edges back to the baseline",
    "inner_rise": "No rise or shoulder inside",
    "asymmetry": "Asymmetry in range",
    "sn": "S/N above the method's floor",
    "slope": "Baseline slope",
    "apex": "Apex roughness",
    "residual": "Fit residual",
}

# the fitting methods a peak can be scored under
METHODS = ("valley", "drop", "flat", "skim", "gaussian", "emg")

# the least window, in points, a smoothing may use
_MIN_POINTS = 5


def smoothing_steps(m):
    """Low, Mid and High smoothing for a current half-width m: Low is m - 1
    and High 2 * m. Low is None when its window (2 * low + 1 points) would
    be under five; with no current smoothing (None or under 2) no change is
    offered."""
    if m is None or m < 2:
        return {"low": None, "mid": None, "high": None}
    low = m - 1
    if 2 * low + 1 < _MIN_POINTS:
        low = None
    return {"low": low, "mid": m, "high": 2 * m}
