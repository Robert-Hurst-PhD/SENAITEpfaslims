# -*- coding: utf-8 -*-
"""
Published-method baseline criteria -- the outer boundary of the lab's
three-tier quality hierarchy (see senaite.pfas.ruleset):

    project QAPP ruleset  ->  lab method profile  ->  PUBLISHED-METHOD BASELINE

This module owns the third tier only: the value the published analytical
method itself specifies, independent of anything a lab or a client project
configures. It is a versioned reference table in the style of
analyte_reference.py -- module-level data plus small accessor functions, no
mutable state, no Plone/Zope imports, so it can be loaded and tested by path
(`importlib.util.spec_from_file_location`) exactly like holding_time.py.

Nothing in this add-on calls this module yet. See GAPS.md for the entry
recording that. Do not add a docstring anywhere that claims a consumer exists
until one does.

SEEDING DISCIPLINE (CLAUDE.md Sec8: never fabricate a regulatory value)
------------------------------------------------------------------------
A method profile in data/qc/method_profiles.json (read-only; never write it)
carries many numeric criteria, but "the lab currently uses this number" is
not the same claim as "the published method specifies this number". Two
signals in that data distinguish them:

  * `verify_against_method: true` on a qc_acceptance tier, or `_seeded: true`
    on a whole profile, both mean explicitly NOT verified against the method
    text -- a placeholder the lab has not checked.
  * The ABSENCE of either flag is not by itself proof of the opposite. The
    bar this module holds to is a closed, citable verification: QUESTIONS.md
    Q-004 (closed 2026-06-19, DECISIONS.md same date) records that
    `eis_overrides` / `eis_matrix_overrides` for EPA_1633A were fetched from
    the official EPA 1633A PDF (EPA 820-R-24-007, December 2024, Tables 6 and
    8) and checked value-by-value -- after which the `verify_against_method`
    flag was deliberately REMOVED from that data because it was no longer
    true. That closed verification is the only thing seeded below.

  Deliberately left OUT, and why:
    - qc_acceptance.LFB / LFSM (EPA_1633A): carry `verify_against_method:
      true` in the live data -- explicitly unverified.
    - qc_acceptance.LFSMD (EPA_1633A): carries the SAME 40/130 window as the
      flagged LFB/LFSM tiers but the flag itself is absent on this one tier.
      That is a data inconsistency (found, not fixed here -- out of scope for
      an additive module), not a second verification; it is left out for the
      same reason as LFB/LFSM.
    - The entire EPA_537_1 profile: `_seeded: true` at the profile root.
    - cal_r2_min (Q-005): closed as "per-method, lab-set via the UI" -- the
      lab OWNS this number, the method does not hand it down. Not a baseline.
    - holding_times (EPA_537_1 = 14 days): cited to CLAUDE.md Sec10, not to a
      Table in the method text the way EIS is, and it already has its own
      single-source-of-truth home in holding_time.py / method_profile_store.
      Duplicating it here would create a second source for one fact (CLAUDE.md
      Sec3) for no benefit this module needs. Left to its existing owner.
    - Every other qc_acceptance / instrument_verification number (rpd_max,
      sn_quan_min, ccv recovery, r2_min, ...): no Q-xxx closure ties any of
      them to method text. `get_baseline` returns None for all of them, which
      is the correct, intended answer -- see ruleset.py's UNKNOWN rule.

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, unicode_literals

import collections

# ── Comparison shapes ─────────────────────────────────────────────────────────
# This distinction is the most important thing in this module. A single
# `value < baseline` test gets ceilings backwards and is meaningless for
# windows -- so shape is carried explicitly and every comparison dispatches
# on it. See `compare()`.
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
# Source: EPA 1633A, December 2024 (EPA 820-R-24-007), Tables 6 and 8.
# QUESTIONS.md Q-004, closed 2026-06-19. Values transcribed from
# method_profile_store.DEFAULT_PROFILES["EPA_1633A"]["eis_overrides"] /
# ["eis_matrix_overrides"], which is itself the verified transcription of the
# official PDF -- this module does not re-derive them, it cites the same
# closed verification. Keyed by the compound display name as it appears on
# the instrument export and in the method profile ("13C4-PFBA", "D3-NMeFOSA",
# ...), NOT the internal M-prefix SENAITE keyword.
# A citation is CLIENT-FACING: it travels through disclosure.format_departure
# onto a certificate, so it names the regulatory authority and stops there. The
# internal verification trail (QUESTIONS.md Q-004, closed 2026-06-19, and the
# DECISIONS.md entry of the same date) belongs in the comment above and in those
# registers — not on a document a client reads. It was previously appended here
# and did print, which is both a leak and a duplication of the comment above.
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
    "13C8-PFOSA":    (40.0, 130.0),
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
        "13C8-PFOSA":   (40.0, 130.0),
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
        "13C8-PFOSA":   (25.0, 180.0),
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
        "13C8-PFOSA":   (20.0, 140.0),
        "D3-NMeFOSA":   (20.0, 130.0),
        "D5-NEtFOSA":   (20.0, 130.0),
        "D3-NMeFOSAA":  (30.0, 150.0),
        "D5-NEtFOSAA":  (20.0, 140.0),
        "D7-NMeFOSE":   (25.0, 130.0),
        "D9-NEtFOSE":   (20.0, 130.0),
    },
}

MATRIX_CLASSES = ("aqueous", "leachate", "solid", "tissue", "biosolid")


def matrix_class(matrix_title):
    """Map a full matrix / SampleType title (e.g. "Landfill Leachate") to the
    EIS table class used by _EIS_MATRIX_OVERRIDES ("leachate"). Mirrors
    pfas_pipeline/method_profiles.py's `_1633a_matrix_class` substring rules
    so the add-on and the worker classify matrices identically; kept as a
    separate copy because the worker module is Python-3-only pipeline code
    and this module must stay dependency-free.

    Falls through to "aqueous" for any name that matches nothing else -- the
    Table 6 aqueous column is EPA 1633A's default class.
    """
    m = (matrix_title or "").lower().strip()
    if "leachate" in m:
        return "leachate"
    if "tissue" in m:
        return "tissue"
    if "biosolid" in m:
        return "biosolid"
    if "solid" in m or "sediment" in m or "soil" in m:
        return "solid"
    return "aqueous"


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
# entry here has never been verified against a method text; get_baseline
# returns None for it unconditionally, which is correct, not incomplete.
_REGISTRY = {
    ("EPA_1633A", "eis_recovery"): _eis_baseline,
}


def get_baseline(method_id, key, analyte=None, matrix=None):
    """The published-method baseline for (method_id, key[, analyte, matrix]),
    or None when nothing has been verified against the method text.

    None is not "no opinion" and must never be read as a permissive default --
    the caller (senaite.pfas.ruleset) treats it as UNKNOWN, never CONFORMS.
    Do not add an entry to _REGISTRY without a citation to the method text and
    a record (a QUESTIONS.md Q-xxx closure, as with Q-004) that it was
    actually checked against that text -- "the lab has used this number for a
    while" is not that record.
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
    -- either element/key may be None, meaning that end was not resolved and
    is skipped, not treated as a departure. Passing a dict where a 2-tuple was
    expected is a common mix-up (Python 2.7 would otherwise silently unpack
    dict KEYS as if they were the bounds and compare strings to floats), so
    it is detected and handled explicitly rather than left to fail loudly
    only sometimes.

    Returns (conformance, [EndVerdict, ...]). SHAPE_WINDOW may return up to
    two EndVerdicts, one per end, EACH JUDGED INDEPENDENTLY -- a window can be
    looser at one end and tighter at the other simultaneously; conformance is
    DEPARTS if either end departs.

    `baseline=None` means no published-method value was ever verified for
    this criterion; that is not this function's concern (a comparison needs
    something to compare against) -- callers must check for it and resolve
    UNKNOWN themselves rather than calling compare() with no baseline. See
    ruleset.resolve().
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
