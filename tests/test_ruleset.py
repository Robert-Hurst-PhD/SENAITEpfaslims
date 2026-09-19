# -*- coding: utf-8 -*-
"""Regression tests for senaite.pfas.method_baselines / senaite.pfas.ruleset.

Both modules under test are deliberately free of Zope imports (ruleset.py
falls back to a path-relative import of method_baselines when the
senaite.pfas package -- which needs zope.i18nmessageid -- is not
importable), so both are loaded straight from their path here rather than as
`senaite.pfas.*`. Runs under both Python 2.7 (the add-on runtime) and Python 3
(developer machines / this test).

This layer is UNWIRED -- zero call sites -- see GAPS.md. These tests pin its
correctness ahead of that wiring, most importantly the shape taxonomy: a
floor (SHAPE_MIN), a ceiling (SHAPE_MAX) and a two-sided window
(SHAPE_WINDOW) are looser in OPPOSITE directions for MIN vs MAX, and a window
judges each end independently.

    python3 tests/test_ruleset.py
"""
from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, os.pardir, "src", "senaite", "pfas")


def _load(path, name):
    """Py2 `imp` is gone in 3.12; this works on both."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except ImportError:
        import imp
        return imp.load_source(name, path)


mb = _load(os.path.join(_SRC, "method_baselines.py"), "pfas_method_baselines_under_test")
# ruleset.py's `from senaite.pfas import method_baselines` fails here (no
# Zope/zope.i18nmessageid) and it falls back to a bare `import
# method_baselines`. Register the SAME module object under that bare name
# first, so ruleset.py's fallback import resolves to the identical instance
# `mb` above rather than re-executing the file into a second, distinct
# module object -- otherwise monkeypatching `mb._REGISTRY` in a test would
# have no effect on what rs.resolve() actually consults.
sys.modules.setdefault("method_baselines", mb)
rs = _load(os.path.join(_SRC, "ruleset.py"), "pfas_ruleset_under_test")
assert rs.method_baselines is mb, "ruleset.py loaded a second, distinct copy of method_baselines"


# ── method_baselines.compare() -- shape taxonomy ─────────────────────────────

def test_shape_min_conforms_and_departs_in_the_right_direction():
    """SHAPE_MIN: a floor. Looser means LOWER. Resolved >= baseline conforms;
    resolved < baseline (a lower floor -- looser) departs."""
    baseline = mb.Baseline("X", "k", None, None, mb.SHAPE_MIN, 3.0, None, "cite")
    conformance, verdicts = mb.compare(baseline, 3.0)
    assert conformance == mb.CONFORMS, conformance
    conformance, verdicts = mb.compare(baseline, 5.0)
    assert conformance == mb.CONFORMS, "a tighter (higher) floor must conform"
    conformance, verdicts = mb.compare(baseline, 1.0)
    assert conformance == mb.DEPARTS, "a lower (looser) floor must depart"
    assert verdicts[0].end == "min"
    assert verdicts[0].baseline_value == 3.0
    assert verdicts[0].resolved_value == 1.0


def test_shape_max_conforms_and_departs_in_the_right_direction_not_inverted():
    """SHAPE_MAX: a ceiling. Looser means HIGHER -- the OPPOSITE direction
    from SHAPE_MIN. This is the assertion that catches a copy-pasted
    comparator that kept MIN's "<" instead of switching to ">"."""
    baseline = mb.Baseline("X", "k", None, None, mb.SHAPE_MAX, None, 30.0, "cite")
    conformance, _ = mb.compare(baseline, 30.0)
    assert conformance == mb.CONFORMS, conformance
    conformance, _ = mb.compare(baseline, 20.0)
    assert conformance == mb.CONFORMS, "a tighter (lower) ceiling must conform"
    conformance, verdicts = mb.compare(baseline, 40.0)
    assert conformance == mb.DEPARTS, "a higher (looser) ceiling must depart"
    assert verdicts[0].end == "max"
    assert verdicts[0].baseline_value == 30.0
    assert verdicts[0].resolved_value == 40.0


def test_shape_min_and_max_mirror_each_other():
    """Same numbers, opposite shapes, opposite verdicts -- if MIN and MAX ever
    shared a comparator by accident this pins that they must not."""
    min_baseline = mb.Baseline("X", "k", None, None, mb.SHAPE_MIN, 10.0, None, "c")
    max_baseline = mb.Baseline("X", "k", None, None, mb.SHAPE_MAX, None, 10.0, "c")
    # Looser for MIN (5 < 10) is CONFORMS-incompatible; looser for MAX would be
    # a value ABOVE 10, not below -- so 5.0 must depart MIN and conform MAX.
    c_min, _ = mb.compare(min_baseline, 5.0)
    c_max, _ = mb.compare(max_baseline, 5.0)
    assert c_min == mb.DEPARTS, c_min
    assert c_max == mb.CONFORMS, c_max
    # And the mirror value the other way.
    c_min, _ = mb.compare(min_baseline, 15.0)
    c_max, _ = mb.compare(max_baseline, 15.0)
    assert c_min == mb.CONFORMS, c_min
    assert c_max == mb.DEPARTS, c_max


def test_window_looser_at_one_end_tighter_at_the_other():
    """The case the task calls out explicitly: a window can be looser at one
    end while tighter at the other, and each end gets its own verdict."""
    baseline = mb.Baseline("EPA_1633A", "eis_recovery", "X", "aqueous",
                            mb.SHAPE_WINDOW, 40.0, 130.0, "cite")
    # min lowered from 40 to 30 (looser) AND max lowered from 130 to 120
    # (tighter) at the same time.
    conformance, verdicts = mb.compare(baseline, (30.0, 120.0))
    assert conformance == mb.DEPARTS, conformance
    by_end = dict((v.end, v) for v in verdicts)
    assert by_end["min"].conformance == mb.DEPARTS, "the loosened floor must depart"
    assert by_end["max"].conformance == mb.CONFORMS, "the tightened ceiling must conform"


def test_window_conforming_both_ends():
    baseline = mb.Baseline("EPA_1633A", "eis_recovery", "X", "aqueous",
                            mb.SHAPE_WINDOW, 40.0, 130.0, "cite")
    conformance, verdicts = mb.compare(baseline, (40.0, 130.0))
    assert conformance == mb.CONFORMS, conformance
    assert all(v.conformance == mb.CONFORMS for v in verdicts)


def test_window_departing_both_ends_reports_both():
    baseline = mb.Baseline("EPA_1633A", "eis_recovery", "X", "aqueous",
                            mb.SHAPE_WINDOW, 40.0, 130.0, "cite")
    conformance, verdicts = mb.compare(baseline, (10.0, 200.0))
    assert conformance == mb.DEPARTS
    ends = sorted(v.end for v in verdicts)
    assert ends == ["max", "min"], ends
    assert all(v.conformance == mb.DEPARTS for v in verdicts)


def test_compare_refuses_a_missing_baseline():
    """compare() is not the place UNKNOWN is decided -- the caller (resolve())
    must check for a None baseline itself. Calling compare() with one anyway
    is a programming error, not a resolvable case."""
    try:
        mb.compare(None, 5.0)
        raise AssertionError("compare(None, ...) should have raised")
    except ValueError:
        pass


# ── method_baselines seeding: EIS is real, everything else is absent ────────

def test_eis_recovery_is_the_only_seeded_baseline():
    assert mb.get_baseline("EPA_1633A", "eis_recovery", analyte="13C4-PFBA") is not None
    # Nothing else has a closed, citable verification (Q-004 is the only one).
    assert mb.get_baseline("EPA_1633A", "cal_r2_min") is None
    assert mb.get_baseline("EPA_1633A", "dup_rpd_max") is None
    assert mb.get_baseline("EPA_1633A", "ccv_recovery") is None
    assert mb.get_baseline("EPA_537_1", "eis_recovery", analyte="13C4-PFBA") is None, (
        "EIS is an EPA_1633A concept only; EPA_537_1 profile is unseeded (_seeded: true)")
    assert mb.get_baseline("FDA_32PFAS", "cal_r2_min") is None


def test_eis_recovery_known_analyte_matches_aqueous_table_6():
    b = mb.get_baseline("EPA_1633A", "eis_recovery", analyte="13C4-PFBA")
    assert b.shape == mb.SHAPE_WINDOW
    assert (b.min_value, b.max_value) == (5.0, 130.0), b
    assert "820-R-24-007" in b.citation


def test_eis_recovery_matrix_override_wins_over_aqueous_default():
    aqueous = mb.get_baseline("EPA_1633A", "eis_recovery", analyte="13C7-PFUnA",
                               matrix="Drinking Water")
    leachate = mb.get_baseline("EPA_1633A", "eis_recovery", analyte="13C7-PFUnA",
                                matrix="Landfill Leachate")
    assert (aqueous.min_value, aqueous.max_value) == (30.0, 130.0), aqueous
    assert (leachate.min_value, leachate.max_value) == (40.0, 130.0), leachate
    assert leachate.matrix_class == "leachate"
    assert aqueous.matrix_class == "aqueous"


def test_eis_recovery_unknown_analyte_is_absent_not_a_fallback():
    """An analyte in neither the aqueous table nor any matrix override must
    resolve to no baseline -- never CONFORMS by some default window."""
    assert mb.get_baseline("EPA_1633A", "eis_recovery", analyte="NOT-A-REAL-COMPOUND") is None


def test_matrix_class_mirrors_the_pipeline_worker():
    assert mb.matrix_class("Landfill Leachate") == "leachate"
    assert mb.matrix_class("Aquatic Tissue") == "tissue"
    assert mb.matrix_class("Biosolid") == "biosolid"
    assert mb.matrix_class("Soil") == "solid"
    assert mb.matrix_class("Sediment") == "solid"
    assert mb.matrix_class("Drinking Water") == "aqueous"
    assert mb.matrix_class("Groundwater") == "aqueous"
    assert mb.matrix_class(None) == "aqueous"


# ── ruleset.resolve() -- tier resolution ─────────────────────────────────────

_FDA_PROFILE = {
    "instrument_verification": {
        "calibration": {"r2_min": 0.995},
        "confirmation": {"sn_quan_min": 3.0},
        "ccv": {"recovery_min": 70.0, "recovery_max": 130.0},
    },
    "qc_acceptance": {
        "Dup": {"tiers": [{"rpd_max": 20.0}]},
    },
}

_EPA1633A_PROFILE = {
    "instrument_verification": {
        "calibration": {"r2_min": 0.990},
        "confirmation": {"sn_quan_min": 3.0},
        "ccv": {"recovery_min": 70.0, "recovery_max": 130.0},
    },
    "qc_acceptance": {
        "Dup": {"tiers": [{"rpd_max": 30.0}]},
    },
    "eis_overrides": [
        {"analyte": "13C4-PFBA", "recovery_min": 5.0, "recovery_max": 130.0},
        {"analyte": "13C5-PFPeA", "recovery_min": 40.0, "recovery_max": 130.0},
    ],
    "eis_matrix_overrides": {
        "leachate": {
            "13C4-PFBA": {"recovery_min": 8.0, "recovery_max": 130.0},
        },
    },
}


def test_unregistered_key_raises():
    try:
        rs.resolve("FDA_32PFAS", "Eggs", "not_a_real_key")
        raise AssertionError("should have raised")
    except ValueError:
        pass


def test_no_baseline_never_conforms_even_when_project_and_lab_agree():
    """Rule 1. cal_r2_min has no seeded baseline anywhere (Q-005: lab-owned,
    not method-derived) -- so even a perfectly resolved lab value must be
    UNKNOWN, not CONFORMS."""
    r = rs.resolve("FDA_32PFAS", "Eggs", "cal_r2_min", profile=_FDA_PROFILE)
    assert r.value == 0.995, r
    assert r.tier == rs.TIER_LAB
    assert r.conformance == mb.UNKNOWN, r.conformance
    assert r.departure is None


def test_batch_with_no_project_resolves_through_lab_then_baseline():
    """Rule 3. No project_ruleset at all (the None-project default)."""
    r = rs.resolve("FDA_32PFAS", "Eggs", "cal_r2_min",
                    profile=_FDA_PROFILE, project_ruleset=None)
    assert r.tier == rs.TIER_LAB
    assert r.value == 0.995
    assert r.source_doc is None and r.source_rev is None

    # And a key with NO lab value and NO baseline falls all the way through
    # to "baseline" with value=None -- cleanly, not an error.
    r2 = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max",
                     profile={}, project_ruleset=None)
    assert r2.tier == rs.TIER_BASELINE
    assert r2.value is None
    assert r2.conformance == mb.UNKNOWN


def test_project_ruleset_silent_on_a_key_inherits_the_lab_value():
    """Rule 2. The project ruleset exists (governs OTHER keys/matrices) but
    says nothing about this one -- it must inherit lab, not null it."""
    project_ruleset = {
        "FDA_32PFAS": {
            "Eggs": {"dup_rpd_max": 15.0},   # a different key, same method+matrix
            "Milk": {"cal_r2_min": 0.999},   # same key, different matrix
        },
    }
    r = rs.resolve("FDA_32PFAS", "Eggs", "cal_r2_min",
                    profile=_FDA_PROFILE, project_ruleset=project_ruleset)
    assert r.tier == rs.TIER_LAB, "silence at the project tier must inherit lab"
    assert r.value == 0.995, "silence must not null the criterion"


def test_project_tier_overrides_lab_and_carries_provenance():
    project_ruleset = {"FDA_32PFAS": {"Eggs": {"cal_r2_min": 0.980}}}
    r = rs.resolve("FDA_32PFAS", "Eggs", "cal_r2_min",
                    profile=_FDA_PROFILE, project_ruleset=project_ruleset,
                    project_doc="QAPP-007", project_rev=3)
    assert r.tier == rs.TIER_PROJECT
    assert r.value == 0.980
    assert r.source_doc == "QAPP-007"
    assert r.source_rev == 3


def test_lab_tier_source_doc_is_none_not_fabricated():
    r = rs.resolve("FDA_32PFAS", "Eggs", "cal_r2_min", profile=_FDA_PROFILE)
    assert r.tier == rs.TIER_LAB
    assert r.source_doc is None
    assert r.source_rev is None


def test_ceiling_departure_via_full_resolution_is_not_inverted():
    """dup_rpd_max has no baseline, so build a temporary one directly to drive
    a full resolve() through a real DEPARTS on a SHAPE_MAX key, end to end."""
    key = "dup_rpd_max"
    original = mb._REGISTRY.get(("FDA_32PFAS", key))
    mb._REGISTRY[("FDA_32PFAS", key)] = (
        lambda analyte, matrix: mb.Baseline(
            "FDA_32PFAS", key, None, None, mb.SHAPE_MAX, None, 20.0, "test-cite"))
    try:
        conforms = rs.resolve("FDA_32PFAS", "Eggs", key, profile=_FDA_PROFILE)
        assert conforms.tier == rs.TIER_LAB
        assert conforms.value == 20.0
        assert conforms.conformance == mb.CONFORMS, conforms

        loosened_profile = {"qc_acceptance": {"Dup": {"tiers": [{"rpd_max": 35.0}]}}}
        departs = rs.resolve("FDA_32PFAS", "Eggs", key, profile=loosened_profile)
        assert departs.conformance == mb.DEPARTS, departs
        assert departs.departure["baseline_value"] == 20.0
        assert departs.departure["resolved_value"] == 35.0
        assert departs.departure["ends"][0]["detail"] is not None

        tightened_profile = {"qc_acceptance": {"Dup": {"tiers": [{"rpd_max": 10.0}]}}}
        tight = rs.resolve("FDA_32PFAS", "Eggs", key, profile=tightened_profile)
        assert tight.conformance == mb.CONFORMS, (
            "a TIGHTER (lower) rpd_max must conform, not depart -- inverted "
            "ceiling check")
    finally:
        if original is None:
            del mb._REGISTRY[("FDA_32PFAS", key)]
        else:
            mb._REGISTRY[("FDA_32PFAS", key)] = original


def test_eis_recovery_end_to_end_lab_tier_conforms_against_real_baseline():
    """The one criterion with a REAL baseline, resolved from a lab profile
    whose eis_overrides happens to equal the method (as the real shipped
    profile does) -- must land on CONFORMS, not just resolve a value."""
    r = rs.resolve("EPA_1633A", "Drinking Water", "eis_recovery",
                    analyte="13C4-PFBA", profile=_EPA1633A_PROFILE)
    assert r.tier == rs.TIER_LAB
    assert r.value == {"min": 5.0, "max": 130.0}
    assert r.conformance == mb.CONFORMS, r


def test_eis_recovery_end_to_end_lab_tier_departs_when_loosened():
    """13C4-PFBA has no leachate-specific method baseline, so the applicable
    baseline for "Landfill Leachate" falls through to the aqueous default,
    5.0/130.0 (asserted below). This lab profile sets its OWN leachate
    override for that analyte to 1.0/200.0 -- wider on both ends -- so both
    ends must report DEPARTS."""
    loosened = {
        "eis_overrides": [{"analyte": "13C4-PFBA", "recovery_min": 5.0, "recovery_max": 130.0}],
        "eis_matrix_overrides": {
            "leachate": {"13C4-PFBA": {"recovery_min": 1.0, "recovery_max": 200.0}},
        },
    }
    r = rs.resolve("EPA_1633A", "Landfill Leachate", "eis_recovery",
                    analyte="13C4-PFBA", profile=loosened)
    assert r.tier == rs.TIER_LAB
    # Method baseline for 13C4-PFBA/leachate is not overridden in the real
    # table (falls to aqueous 5.0/130.0); the lab widened it to 1.0/200.0.
    baseline = mb.get_baseline("EPA_1633A", "eis_recovery", analyte="13C4-PFBA",
                                matrix="Landfill Leachate")
    assert (baseline.min_value, baseline.max_value) == (5.0, 130.0)
    assert r.conformance == mb.DEPARTS, r
    ends = sorted(e["end"] for e in r.departure["ends"])
    assert ends == ["max", "min"], "both ends were loosened, both must be named"


def test_eis_recovery_baseline_tier_self_compares_and_conforms():
    """No project, no lab profile at all -- value resolves straight from the
    baseline itself. Comparing a value against itself is deliberately
    CONFORMS (nothing has loosened anything); this pins that the baseline
    branch is a real self-comparison, not an accidental short-circuit."""
    r = rs.resolve("EPA_1633A", "Drinking Water", "eis_recovery",
                    analyte="13C4-PFBA", profile=None, project_ruleset=None)
    assert r.tier == rs.TIER_BASELINE
    assert r.value == {"min": 5.0, "max": 130.0}
    assert r.conformance == mb.CONFORMS, r


def test_eis_recovery_absent_everywhere_is_unknown():
    r = rs.resolve("EPA_1633A", "Drinking Water", "eis_recovery",
                    analyte="NOT-A-REAL-COMPOUND", profile=None, project_ruleset=None)
    assert r.tier == rs.TIER_BASELINE
    assert r.value is None
    assert r.conformance == mb.UNKNOWN


def test_project_ruleset_analyte_scoping_is_silent_for_other_analytes():
    """eis_recovery is analyte-scoped: a project override for one analyte
    must not leak onto another, and the untouched analyte still inherits."""
    project_ruleset = {
        "EPA_1633A": {
            "Drinking Water": {
                "eis_recovery": {"13C4-PFBA": {"min": 1.0, "max": 200.0}},
            },
        },
    }
    overridden = rs.resolve("EPA_1633A", "Drinking Water", "eis_recovery",
                             analyte="13C4-PFBA", profile=_EPA1633A_PROFILE,
                             project_ruleset=project_ruleset)
    assert overridden.tier == rs.TIER_PROJECT
    assert overridden.value == {"min": 1.0, "max": 200.0}

    other = rs.resolve("EPA_1633A", "Drinking Water", "eis_recovery",
                        analyte="13C5-PFPeA", profile=_EPA1633A_PROFILE,
                        project_ruleset=project_ruleset)
    assert other.tier == rs.TIER_LAB, "an untouched analyte must still inherit"


def test_set_project_criterion_merges_and_does_not_null_siblings():
    """The GAPS.md Sec7.1 shape, defended structurally: setting one criterion
    must not clobber another already stored for the same or a different
    method/matrix."""
    class FakeAnnotations(dict):
        pass

    store = {}

    class FakeProject(object):
        pass

    project = FakeProject()

    # Patch _annotations() for this test only, so it never touches zope.
    original = rs._annotations
    rs._annotations = lambda proj: store.setdefault(id(proj), FakeAnnotations())
    try:
        rs.set_project_criterion(project, "FDA_32PFAS", "Eggs", "cal_r2_min", 0.98)
        rs.set_project_criterion(project, "FDA_32PFAS", "Eggs", "dup_rpd_max", 15.0)
        rs.set_project_criterion(project, "FDA_32PFAS", "Milk", "cal_r2_min", 0.99)

        ruleset = rs.get_project_ruleset(project)
        assert ruleset["FDA_32PFAS"]["Eggs"]["cal_r2_min"] == 0.98
        assert ruleset["FDA_32PFAS"]["Eggs"]["dup_rpd_max"] == 15.0, (
            "setting cal_r2_min must not have nulled the sibling dup_rpd_max")
        assert ruleset["FDA_32PFAS"]["Milk"]["cal_r2_min"] == 0.99, (
            "setting Eggs must not have nulled Milk")
    finally:
        rs._annotations = original


if __name__ == "__main__":
    ok = fail = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                fail += 1
                print("FAIL", name, "--", exc)
            else:
                ok += 1
                print("PASS", name)
    print("{0} passed, {1} failed".format(ok, fail))
    if fail:
        sys.exit(1)
