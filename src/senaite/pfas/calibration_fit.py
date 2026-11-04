# -*- coding: utf-8 -*-
"""How a method's calibration curve is fitted: Origin and Weighting.

The instrument software fits the curve; the method profile says how it is
fitted, and Data Review's curve card starts from it (a per-curve change is
that curve's alone). Stored on instrument_verification.calibration:

    origin      "exclude" | "include" | "force"
    weighting   "none" | "1/x" | "1/x2"

A profile with only the force_origin switch reads it as on -> force, off ->
exclude. A profile with no weighting takes WEIGHTING_AT_MIGRATION, the value
the lab gave for its methods. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

ORIGINS = (("exclude", u"Exclude"), ("include", u"Include"), ("force", u"Force"))
WEIGHTINGS = (("none", u"None"), ("1/x", u"1/x"), ("1/x2", u"1/x²"))
# the lab's weighting for every method it runs
WEIGHTING_AT_MIGRATION = "1/x"


def _cal(profile):
    iv = profile.get("instrument_verification")
    if not isinstance(iv, dict):
        iv = profile["instrument_verification"] = {}
    cal = iv.get("calibration")
    if not isinstance(cal, dict):
        cal = iv["calibration"] = {}
    return cal


def origin(cal):
    """The curve's origin rule; a profile not yet migrated reads its old switch."""
    cal = cal or {}
    if cal.get("origin") in dict(ORIGINS):
        return cal["origin"]
    return "force" if cal.get("force_origin") else "exclude"


def weighting(cal):
    cal = cal or {}
    return cal["weighting"] if cal.get("weighting") in dict(WEIGHTINGS) else None


