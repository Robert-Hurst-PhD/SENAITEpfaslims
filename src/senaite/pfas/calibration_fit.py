# -*- coding: utf-8 -*-
"""How a method's calibration curve is fitted: Curve fit, Origin and Weighting.

The instrument software fits the curve of a vendor export; the worker fits
a raw run's. The method profile says how every new curve is fitted, and
Data Review's curve card starts from it (a per-curve change is that curve's
alone). Stored on instrument_verification.calibration:

    fit         "linear" | "quadratic" | "mean_response_factor"
    origin      "exclude" | "include" | "force"
    weighting   "none" | "1/x" | "1/x2"

A profile without a fit is fitted linear. A profile with only the
force_origin switch reads it as on -> force, off -> exclude. A profile with
no weighting takes WEIGHTING_AT_MIGRATION, the value the lab gave for its
methods. FITS holds the fits and the words the field, the worker's records
and the curve card name them by. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

FITS = (("linear", u"Linear"), ("quadratic", u"Quadratic"), ("mean_response_factor", u"Average RF"))
# a profile that names no fit
FIT_WHEN_UNSET = "linear"
ORIGINS = (("exclude", u"Exclude"), ("include", u"Include"), ("force", u"Force"))
# an Average RF passes through the origin by definition: its origin is Force
# whatever the method's Origin says, and it is not weighted
FIXED_ORIGIN_FIT, FIXED_ORIGIN = "mean_response_factor", "force"
FIXED_ORIGIN_WORDS = u"An average RF passes through the origin"
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


def fit(cal):
    """The method's curve fit; a profile without one (or with a value no fit
    names) is fitted linear."""
    cal = cal or {}
    return cal["fit"] if cal.get("fit") in dict(FITS) else FIT_WHEN_UNSET


def fit_label(value):
    """A fit's words ("Average RF"); a value no fit names, as it is."""
    return dict(FITS).get(value, value or u"")


def missing_fit(profile):
    """True when a profile's calibration block names no fit: the upgrade
    step writes FIT_WHEN_UNSET there, what such a profile is fitted with. A
    profile with no calibration block is left alone (nothing is seeded)."""
    iv = (profile or {}).get("instrument_verification")
    cal = iv.get("calibration") if isinstance(iv, dict) else None
    return isinstance(cal, dict) and cal.get("fit") in (None, u"")


