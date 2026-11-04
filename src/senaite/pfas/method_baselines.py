# -*- coding: utf-8 -*-
"""
Published-method baseline criteria -- the outer boundary of the lab's
three-tier quality hierarchy (see senaite.pfas.ruleset):

    project QAPP ruleset  ->  lab method profile  ->  PUBLISHED-METHOD BASELINE

This module owns the third tier only: the value the published method itself
specifies, independent of what a lab or a client project configures. Module
data plus small accessors, no mutable state, no Plone/Zope imports, so it
loads and tests by path like holding_time.py. Read by ruleset.py (the
CONFORMS / DEPARTS verdict) and project_specs.py.

SEEDING (Sec8: never fabricate a regulatory value)
------------------------------------------------------------------------
"The lab uses this number" is not "the published method specifies this
number". A value is seeded here only after a recorded value-by-value check
against the method text. `verify_against_method: true` on a qc_acceptance
tier, or `_seeded: true` on a profile, marks a value not checked; the absence
of either flag is no proof of the opposite.

  Seeded: the EPA_1633A EIS recovery windows, checked against EPA 1633A
  (EPA 820-R-24-007, December 2024, Tables 6 and 8).

  Not seeded:
    - qc_acceptance.LFB / LFSM / LFSMD (EPA_1633A): not verified against the
      method text.
    - The EPA_537_1 profile: `_seeded: true`.
    - cal_r2_min: the lab's own number, set in the UI. Not a baseline.
    - holding_times (EPA_537_1 = 14 days): cited to Sec10; owned by
      holding_time.py / method_profile_store.
    - Every other qc_acceptance / instrument_verification number (rpd_max,
      sn_quan_min, ccv recovery, r2_min, ...): nothing ties them to method
      text, so `get_baseline` returns None (ruleset.py's UNKNOWN rule).

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, unicode_literals

import collections

# ── Comparison shapes ─────────────────────────────────────────────────────────
# Every comparison dispatches on shape (compare()): a single
# `value < baseline` test gets ceilings backwards and means nothing for windows.
SHAPE_MIN = "min"        # a floor: looser means LOWER      (e.g. cal_r2_min, sn_min)
SHAPE_MAX = "max"        # a ceiling: looser means HIGHER   (e.g. rpd_max)
SHAPE_WINDOW = "window"  # two-sided range: looser means WIDER; each end is
                          # judged independently -- a window can be loosened
                          # at one end and tightened at the other at once.

SHAPES = (SHAPE_MIN, SHAPE_MAX, SHAPE_WINDOW)

# ── Conformance verdicts ───────────────────────────────────────────────────────
CONFORMS = "CONFORMS"
DEPARTS = "DEPARTS"
UNKNOWN = "UNKNOWN"


Baseline = collections.namedtuple(
    "Baseline",
    ["method_id", "key", "analyte", "matrix_class", "shape",
     "min_value", "max_value", "citation"],
)

EndVerdict = collections.namedtuple(
    "EndVerdict",
    ["end", "conformance", "baseline_value", "resolved_value", "detail"],
)


# ── EPA 1633A EIS/OPR recovery -- the one seeded baseline ────────────────────
# Source: EPA 1633A, December 2024 (EPA 820-R-24-007), Tables 6 and 8, checked
# value by value; the same values as method_profile_store.DEFAULT_PROFILES
# ["EPA_1633A"]["eis_overrides"] / ["eis_matrix_overrides"]. Keyed by the
# labelled compound's keyword, as the method profile's EIS rows are
# ("13C4-PFBA", "D3-NMeFOSA"; Table 6's 13C8-PFOSA under the library's
# 13C8-FOSA).
# A citation is client-facing (disclosure.format_departure prints it on a
# certificate): it names the regulatory source and nothing internal.
EIS_CITATION = "EPA 1633A (December 2024, EPA 820-R-24-007), Tables 6 and 8"

# Table 6, aqueous column. Also the fallback for any 1633A matrix whose class
# has no override for a given analyte in _EIS_MATRIX_OVERRIDES below.
_EIS_AQUEOUS = {
    "13C4-PFBA":     (5.0, 130.0),
    "13C5-PFPeA":    (40.0, 130.0),
    "13C5-PFHxA":    (40.0, 130.0),
    "13C4-PFHpA":    (40.0, 130.0),
    "13C8-PFOA":     (40.0, 130.0),
    "13C9-PFNA":     (40.0, 130.0),
    "13C6-PFDA":     (40.0, 130.0),
    "13C7-PFUnA":    (30.0, 130.0),
    "13C2-PFDoA":    (10.0, 130.0),
    "13C2-PFTeDA":   (10.0, 130.0),
    "13C3-PFBS":     (40.0, 135.0),
    "13C3-PFHxS":    (40.0, 130.0),
    "13C8-PFOS":     (40.0, 130.0),
    "13C2-4:2FTS":   (40.0, 200.0),
    "13C2-6:2FTS":   (40.0, 200.0),
    "13C2-8:2FTS":   (40.0, 300.0),
    "13C8-FOSA" :    (40.0, 130.0),
    "D3-NMeFOSA":    (10.0, 130.0),
    "D5-NEtFOSA":    (10.0, 130.0),
    "D3-NMeFOSAA":   (40.0, 170.0),
    "D5-NEtFOSAA":   (25.0, 135.0),
    "D7-NMeFOSE":    (10.0, 130.0),
    "D9-NEtFOSE":    (10.0, 130.0),
    "13C3-HFPO-DA":  (40.0, 130.0),
}

# Tables 6 (leachate column) and 8 (solid / tissue / biosolid columns).
# Only analytes whose limit differs from the aqueous default above are
# listed under each matrix class; everything else in that class falls
# through to _EIS_AQUEOUS.
_EIS_MATRIX_OVERRIDES = {
    "leachate": {
        "13C7-PFUnA":   (40.0, 130.0),
        "13C2-PFDoA":   (35.0, 130.0),
        "13C2-PFTeDA":  (25.0, 130.0),
        "13C3-PFBS":    (40.0, 130.0),
        "13C2-4:2FTS":  (40.0, 220.0),
        "13C2-6:2FTS":  (40.0, 170.0),
        "13C2-8:2FTS":  (40.0, 145.0),
        "D3-NMeFOSA":   (40.0, 130.0),
        "D5-NEtFOSA":   (35.0, 130.0),
        "D3-NMeFOSAA":  (35.0, 130.0),
        "D5-NEtFOSAA":  (30.0, 130.0),
        "D7-NMeFOSE":   (20.0, 130.0),
        "D9-NEtFOSE":   (20.0, 130.0),
    },
    "solid": {
        "13C4-PFBA":    (8.0, 130.0),
        "13C5-PFPeA":   (35.0, 130.0),
        "13C2-PFTeDA":  (20.0, 130.0),
        "13C2-4:2FTS":  (40.0, 165.0),
        "13C2-6:2FTS":  (40.0, 215.0),
        "13C2-8:2FTS":  (40.0, 275.0),
        "13C8-FOSA" :   (40.0, 130.0),
        "D3-NMeFOSAA":  (40.0, 135.0),
        "D5-NEtFOSAA":  (40.0, 150.0),
        "D7-NMeFOSE":   (20.0, 130.0),
        "D9-NEtFOSE":   (15.0, 130.0),
    },
    "tissue": {
        "13C4-PFBA":    (5.0, 130.0),
        "13C5-PFPeA":   (10.0, 185.0),
        "13C5-PFHxA":   (25.0, 170.0),
        "13C4-PFHpA":   (25.0, 150.0),
        "13C8-PFOA":    (25.0, 150.0),
        "13C9-PFNA":    (35.0, 185.0),
        "13C6-PFDA":    (30.0, 150.0),
        "13C7-PFUnA":   (30.0, 180.0),
        "13C2-PFDoA":   (35.0, 180.0),
        "13C2-PFTeDA":  (20.0, 160.0),
        "13C3-PFBS":    (25.0, 190.0),
        "13C3-PFHxS":   (35.0, 175.0),
        "13C8-PFOS":    (40.0, 160.0),
        "13C2-4:2FTS":  (30.0, 300.0),
        "13C2-6:2FTS":  (35.0, 300.0),
        "13C2-8:2FTS":  (40.0, 365.0),
        "13C8-FOSA" :   (25.0, 180.0),
        "D3-NMeFOSA":   (5.0, 130.0),
        "D5-NEtFOSA":   (5.0, 130.0),
        "D3-NMeFOSAA":  (30.0, 250.0),
        "D5-NEtFOSAA":  (30.0, 235.0),
        "D7-NMeFOSE":   (5.0, 160.0),
        "D9-NEtFOSE":   (5.0, 130.0),
        "13C3-HFPO-DA": (20.0, 185.0),
    },
    "biosolid": {
        "13C4-PFBA":    (5.0, 130.0),
        "13C5-PFPeA":   (35.0, 130.0),
        "13C9-PFNA":    (40.0, 145.0),
        "13C2-PFTeDA":  (10.0, 160.0),
        "13C3-PFBS":    (40.0, 150.0),
        "13C3-PFHxS":   (40.0, 140.0),
        "13C2-4:2FTS":  (40.0, 300.0),
        "13C2-6:2FTS":  (40.0, 300.0),
        "13C2-8:2FTS":  (40.0, 300.0),
        "13C8-FOSA" :   (20.0, 140.0),
        "D3-NMeFOSA":   (20.0, 130.0),
        "D5-NEtFOSA":   (20.0, 130.0),
        "D3-NMeFOSAA":  (30.0, 150.0),
        "D5-NEtFOSAA":  (20.0, 140.0),
        "D7-NMeFOSE":   (25.0, 130.0),
        "D9-NEtFOSE":   (20.0, 130.0),
    },
}

MATRIX_CLASSES = ("aqueous", "leachate", "solid", "tissue", "biosolid")


def _method_engine():
    from senaite.pfas import method_engine
    return method_engine


def matrix_class(matrix_title, profile=None):
    """The EIS table class ("leachate", "solid", ... or "aqueous") of a
    matrix / SampleType title.

    With a profile that classifies its matrices (matrix_classes, Matrices &
    Units), the profile's class -- exactly what the worker's engine applies;
    a matrix it does not classify takes no class override ("aqueous").
    Without one, EPA 1633A's table classes from the title
    (method_engine.default_matrix_class: the rule the Engine migration writes
    into the profile).
    """
    me = _method_engine()
    classes = (profile or {}).get("matrix_classes")
    if isinstance(classes, dict) and classes:
        return me.matrix_class(profile, matrix_title) or "aqueous"
    return me.default_matrix_class(matrix_title)


def _eis_baseline(analyte, matrix):
    if not analyte:
        return None
    mclass = matrix_class(matrix) if matrix else "aqueous"
    bounds = None
    if mclass != "aqueous":
        bounds = _EIS_MATRIX_OVERRIDES.get(mclass, {}).get(analyte)
    if bounds is None:
        bounds = _EIS_AQUEOUS.get(analyte)
    if bounds is None:
        return None
    lo, hi = bounds
    return Baseline("EPA_1633A", "eis_recovery", analyte, mclass,
                     SHAPE_WINDOW, lo, hi, EIS_CITATION)


# key -> handler(analyte, matrix) -> Baseline or None. A criterion key with no
# entry here is not verified against a method text: get_baseline returns None.
_REGISTRY = {
    ("EPA_1633A", "eis_recovery"): _eis_baseline,
}


def get_baseline(method_id, key, analyte=None, matrix=None):
    """The published-method baseline for (method_id, key[, analyte, matrix]),
    or None when nothing has been verified against the method text.

    None is never a permissive default: the caller (senaite.pfas.ruleset)
    treats it as UNKNOWN, never CONFORMS. An entry in _REGISTRY needs a
    citation to the method text and a record that it was checked against it.
    """
    handler = _REGISTRY.get((method_id, key))
    if handler is None:
        return None
    return handler(analyte, matrix)


# ── Shape-aware comparison ─────────────────────────────────────────────────────

def _verdict_min(end, baseline_value, resolved_value):
    """SHAPE_MIN semantics: baseline_value is a floor. Departure = the
    resolved value sets the floor LOWER (looser) than the baseline."""
    if resolved_value < baseline_value:
        detail = ("{0} floor loosened: method requires >= {1}, resolved "
                   "value allows >= {2}".format(end, baseline_value,
                                                 resolved_value))
        return EndVerdict(end, DEPARTS, baseline_value, resolved_value, detail)
    return EndVerdict(end, CONFORMS, baseline_value, resolved_value, None)


def _verdict_max(end, baseline_value, resolved_value):
    """SHAPE_MAX semantics: baseline_value is a ceiling. Departure = the
    resolved value sets the ceiling HIGHER (looser) than the baseline."""
    if resolved_value > baseline_value:
        detail = ("{0} ceiling loosened: method requires <= {1}, resolved "
                   "value allows <= {2}".format(end, baseline_value,
                                                 resolved_value))
        return EndVerdict(end, DEPARTS, baseline_value, resolved_value, detail)
    return EndVerdict(end, CONFORMS, baseline_value, resolved_value, None)


def compare(baseline, resolved_value):
    """Compare a resolved criterion value against `baseline`, shape-aware.

    `resolved_value` is a plain number for SHAPE_MIN / SHAPE_MAX. For
    SHAPE_WINDOW it is a (low, high) 2-tuple/list, OR a {"min": low, "max":
    high} dict (the shape ruleset.py's ResolvedCriterion.value actually uses)
    -- either element/key may be None: that end was not resolved and is
    skipped, not a departure. A dict is read by key: unpacked as a tuple,
    Python 2.7 would compare its key strings to floats.

    Returns (conformance, [EndVerdict, ...]). SHAPE_WINDOW may return up to
    two EndVerdicts, one per end, EACH JUDGED INDEPENDENTLY -- a window can be
    looser at one end and tighter at the other simultaneously; conformance is
    DEPARTS if either end departs.

    `baseline=None` (no verified published value) raises: the caller resolves
    UNKNOWN itself (ruleset.resolve()).
    """
    if baseline is None:
        raise ValueError(
            "compare() requires a Baseline; a None baseline means UNKNOWN "
            "and must be handled by the caller, not compared against")
    verdicts = []
    if baseline.shape == SHAPE_MIN:
        if resolved_value is not None:
            verdicts.append(_verdict_min("min", baseline.min_value, resolved_value))
    elif baseline.shape == SHAPE_MAX:
        if resolved_value is not None:
            verdicts.append(_verdict_max("max", baseline.max_value, resolved_value))
    elif baseline.shape == SHAPE_WINDOW:
        if isinstance(resolved_value, dict):
            lo, hi = resolved_value.get("min"), resolved_value.get("max")
        else:
            lo, hi = resolved_value
        if lo is not None and baseline.min_value is not None:
            verdicts.append(_verdict_min("min", baseline.min_value, lo))
        if hi is not None and baseline.max_value is not None:
            verdicts.append(_verdict_max("max", baseline.max_value, hi))
    else:
        raise ValueError("Unknown comparison shape: {0!r}".format(baseline.shape))

    if not verdicts:
        return UNKNOWN, verdicts
    conformance = DEPARTS if any(v.conformance == DEPARTS for v in verdicts) \
        else CONFORMS
    return conformance, verdicts
