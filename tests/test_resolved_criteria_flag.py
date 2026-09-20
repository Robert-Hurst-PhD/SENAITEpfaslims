# -*- coding: utf-8 -*-
"""Proves the JOIN between the two halves of QC criterion resolution that
`tests/test_ruleset.py` and `tests/test_fault_injection.py` each prove in
isolation, but that nothing proves together:

    senaite.pfas.ruleset.resolve()  --(resolved value)-->  pfas_pipeline.qc_engine's
    real recovery_check_profiled() / rpd_check_profiled()

`test_ruleset.py` proves resolution picks the right tier and the right
CONFORMS/DEPARTS/UNKNOWN verdict, in isolation, against fixture profile
dicts. `test_fault_injection.py` proves the QC engine flags an injected
deviation correctly, in isolation, given criteria it was handed directly.
Neither proves that a criterion resolved THROUGH THE TIERS, when handed to a
real QC check, produces the right flag -- or, just as importantly, the right
absence of one. That is what the lab asked to see ("verify ... values
exceeding tolerances are flagged correctly" / "verify when the numbers are
populated and the QC is called then it will correctly work"), and it is what
this file composes.

PROCESS BOUNDARY (read before drawing conclusions from a green run here):
`senaite.pfas.ruleset` is Python-2.7 add-on code; `pfas_pipeline.qc_engine`
is Python-3 worker code. They are one system (CLAUDE.md Sec7) but two
processes that never share memory -- resolved criteria cross that boundary
only as JSON, and nothing does that crossing today (ruleset.py has zero call
sites; GAPS.md Sec15/Sec16). This file runs BOTH halves in-process, in one
Python 3 interpreter, and glues them with a tiny duck-typed adapter
(`_ResolvedProfile` below) that satisfies the narrow interface
`recovery_check_profiled()` / `rpd_check_profiled()` actually need
(`.method_id`, `.qc_rules(...)`). That is composition, not stubbing: every
comparison, every flag/no-flag decision, and every message string below is
produced by the REAL, UNMODIFIED qc_engine functions and the REAL,
UNMODIFIED ruleset.resolve(). What this file does NOT prove is that a
project-tier value resolved by the live add-on would actually REACH the
live worker process -- that plumbing does not exist yet. See GAPS.md Sec17.

The adapter is narrow on purpose and that narrowness has a cost: a live
`MethodProfile.qc_rules()` also sets `is_guidance_only`, `verify_against_method`,
and `notes` on the `QCRule` it returns, and `recovery_check_profiled()` /
`rpd_check_profiled()` append those to a failing flag's message (e.g. "[VERIFY
limits vs method tables]", "[guidance only]", the trailing "-- {notes}").
`_ResolvedProfile` leaves all three at their dataclass defaults, so every flag
asserted below is proven correct on the COMPARISON (the min/max/limit test
that decides flag-or-no-flag) and the base message shape, not on that
decoration. This matters concretely for EPA_1633A: GAPS.md Sec16.3 already
records that the live `EPA1633AProfile.qc_rules()` sets
`verify_against_method=True` on its EIS branch, which a real run would surface
as an extra suffix that this test's case 5 does not exercise.

Case 5 carries a second, independent process-boundary caveat of its own --
see its docstring below (the EIS qc_type path it drives has no live call
site in `pfas_pipeline/run_queue.py` today).

Loads ruleset.py / method_baselines.py by path exactly as test_ruleset.py
does (Zope is not installed here), and imports pfas_pipeline normally (pure
Python 3, no Zope dependency).

    python3 tests/test_resolved_criteria_flag.py
"""
from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SRC = os.path.join(_ROOT, "src", "senaite", "pfas")

sys.path.insert(0, _ROOT)


def _load(path, name):
    """Py2 `imp` is gone in 3.12; this works on both. Copied verbatim from
    test_ruleset.py's loader so both files load the identical module shape."""
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
sys.modules.setdefault("method_baselines", mb)
rs = _load(os.path.join(_SRC, "ruleset.py"), "pfas_ruleset_under_test")
assert rs.method_baselines is mb, "ruleset.py loaded a second, distinct copy of method_baselines"

from pfas_pipeline.method_profiles import QCRule  # noqa: E402  (after sys.path insert)
from pfas_pipeline.qc_engine import recovery_check_profiled, rpd_check_profiled  # noqa: E402


# ── The adapter that crosses the boundary INSIDE this test only ─────────────
#
# recovery_check_profiled()/rpd_check_profiled() only ever call
# `profile.qc_rules(analyte, matrix, qc_type)` and read `profile.method_id`
# for the flag's `source` label -- they do not care which class supplies
# those, so this is enough to hand a ruleset.ResolvedCriterion's `.value`
# to the real check functions without touching a line of qc_engine.py or
# reimplementing any comparison it makes.
class _ResolvedProfile(object):
    def __init__(self, method_id, **rule_kwargs):
        self.method_id = method_id
        self._rule = QCRule(**rule_kwargs)

    def qc_rules(self, analyte, matrix="", qc_type="LFSM"):
        return self._rule


def _window_profile(resolved, method_id):
    """A resolved SHAPE_WINDOW value ({"min":, "max":}) -> an adapter usable
    with recovery_check_profiled()."""
    return _ResolvedProfile(method_id, recovery_min=resolved.value["min"],
                             recovery_max=resolved.value["max"])


def _max_profile(resolved, method_id):
    """A resolved SHAPE_MAX value (a bare number) -> an adapter usable with
    rpd_check_profiled()."""
    return _ResolvedProfile(method_id, rpd_max=resolved.value)


# ── Fixture lab profile (method_profile_store.get_profile() shape) ──────────
_LAB_PROFILE = {
    "instrument_verification": {
        "ccv": {"recovery_min": 70.0, "recovery_max": 130.0},
    },
    "qc_acceptance": {
        "Dup": {"tiers": [{"rpd_max": 20.0}]},
    },
}


# ── 1. Value INSIDE a lab-tier criterion -> no flag ──────────────────────────

def test_value_inside_lab_tier_criterion_is_not_flagged():
    resolved = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max", profile=_LAB_PROFILE)
    assert resolved.tier == rs.TIER_LAB
    assert resolved.value == 20.0

    flag = rpd_check_profiled(_max_profile(resolved, "FDA_32PFAS"),
                               "PFOA", "Eggs", "Dup", 15.0, "inj1")
    assert flag is None, (
        "a value comfortably inside the resolved lab-tier limit must not "
        "be flagged -- a harness that flags everything proves nothing")


# ── 2. Value OUTSIDE a lab-tier criterion -> flagged, right kind ─────────────

def test_value_outside_lab_tier_criterion_is_flagged_with_the_right_kind():
    resolved = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max", profile=_LAB_PROFILE)
    flag = rpd_check_profiled(_max_profile(resolved, "FDA_32PFAS"),
                               "PFOA", "Eggs", "Dup", 25.0, "inj1")
    assert flag is not None
    assert flag.issue.startswith("(RPD)"), flag.issue
    assert "exceeds" in flag.issue
    assert flag.value == "RPD=25.0%"
    assert flag.source == "FDA_32PFAS Dup"


# ── 3. Project QAPP LOOSENS a criterion: a lab-tier failure now passes ───────

def test_project_qapp_loosens_criterion_turns_a_lab_tier_failure_into_a_pass():
    project_ruleset = {"FDA_32PFAS": {"Eggs": {"dup_rpd_max": 30.0}}}

    lab_only = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max", profile=_LAB_PROFILE)
    project = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max",
                          profile=_LAB_PROFILE, project_ruleset=project_ruleset,
                          project_doc="QAPP-100", project_rev=2)

    assert project.tier == rs.TIER_PROJECT
    assert project.value == 30.0
    assert project.source_doc == "QAPP-100"
    assert project.source_rev == 2

    # Confirm the fixture actually fails at the lab tier first -- otherwise
    # "now passes" proves nothing about the loosening.
    flag_lab = rpd_check_profiled(_max_profile(lab_only, "FDA_32PFAS"),
                                   "PFOA", "Eggs", "Dup", 25.0, "inj1")
    assert flag_lab is not None, "fixture must fail at the lab tier to begin with"

    flag_project = rpd_check_profiled(_max_profile(project, "FDA_32PFAS"),
                                       "PFOA", "Eggs", "Dup", 25.0, "inj1")
    assert flag_project is None, "the loosened project criterion must clear the flag"


# ── 4. Project QAPP TIGHTENS a criterion: a lab-tier pass now fails ──────────

def test_project_qapp_tightens_criterion_turns_a_lab_tier_pass_into_a_failure():
    project_ruleset = {"FDA_32PFAS": {"Eggs": {"dup_rpd_max": 10.0}}}

    lab_only = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max", profile=_LAB_PROFILE)
    project = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max",
                          profile=_LAB_PROFILE, project_ruleset=project_ruleset,
                          project_doc="QAPP-101", project_rev=1)
    assert project.tier == rs.TIER_PROJECT
    assert project.value == 10.0

    flag_lab = rpd_check_profiled(_max_profile(lab_only, "FDA_32PFAS"),
                                   "PFOA", "Eggs", "Dup", 15.0, "inj1")
    assert flag_lab is None, "fixture must pass at the lab tier to begin with"

    flag_project = rpd_check_profiled(_max_profile(project, "FDA_32PFAS"),
                                       "PFOA", "Eggs", "Dup", 15.0, "inj1")
    assert flag_project is not None, "the tightened project criterion must now flag it"
    assert flag_project.issue.startswith("(RPD)")


# ── 5. Seeded baseline (EPA 1633A EIS recovery): project departs from it ────

def test_project_departure_from_seeded_baseline_qc_outcome_correct_and_departs_reported():
    """13C4-PFBA / Drinking Water has a REAL method baseline (5.0-130.0,
    method_baselines._EIS_AQUEOUS, EPA 1633A Table 6). A project ruleset
    loosens the floor to 1.0. A recovery of 2.0% therefore:
      - FAILS if evaluated against the baseline alone (2.0 < 5.0), and
      - PASSES once the project criterion is what is actually evaluated
        (2.0 >= 1.0) -- the QC engine correctly applies the tier that
        resolution says is in force,
      - while conformance independently reports that tier as DEPARTS from
        the method floor, with the departure detail populated.
    Both facts must be visible at once: an accreditation-relevant departure
    is not the same axis as a pass/fail QC outcome, and this is the case
    where mixing them up would matter to a certificate.

    A SEPARATE finding, not fixed here: this composes with
    `recovery_check_profiled()`, the same generic window-comparison function
    `run_queue.py:500` calls live for LFSM/LFB recovery -- but no call site in
    `pfas_pipeline/run_queue.py` invokes it with qc_type="EIS" today.
    `EPA1633AProfile.qc_rules(qc_type="EIS")` (method_profiles.py:986) is a
    real branch that reads this exact eis_overrides/eis_matrix_overrides data
    and would return a matching QCRule if called -- it is simply never
    called. Live EIS monitoring instead runs through `is_raw_check()` /
    `profile.is_rule()`, which applies ONE blanket vs-ICAL-average window to
    every internal standard, not the per-analyte Tables 6/8 recovery windows
    this baseline cites (`is_rule()`'s own docstring even says "EIS uses
    per-analyte limits", describing the branch that nothing calls). This test
    proves the window-comparison mechanism for an eis_recovery-shaped
    resolved value; it does not prove that mechanism is what runs against
    real EIS results today -- that is a second, pre-existing wiring gap,
    older than and independent of ruleset.py's, recorded in GAPS.md Sec17.
    """
    project_ruleset = {
        "EPA_1633A": {
            "Drinking Water": {
                "eis_recovery": {"13C4-PFBA": {"min": 1.0, "max": 130.0}},
            },
        },
    }

    baseline_only = rs.resolve("EPA_1633A", "Drinking Water", "eis_recovery",
                                analyte="13C4-PFBA", profile=None,
                                project_ruleset=None)
    assert baseline_only.tier == rs.TIER_BASELINE
    assert baseline_only.value == {"min": 5.0, "max": 130.0}
    assert baseline_only.conformance == mb.CONFORMS

    project = rs.resolve("EPA_1633A", "Drinking Water", "eis_recovery",
                          analyte="13C4-PFBA", profile=None,
                          project_ruleset=project_ruleset,
                          project_doc="QAPP-9", project_rev=1)
    assert project.tier == rs.TIER_PROJECT
    assert project.value == {"min": 1.0, "max": 130.0}
    assert project.conformance == mb.DEPARTS, project
    assert project.departure is not None
    assert project.departure["baseline_value"] == {"min": 5.0, "max": 130.0}
    assert project.departure["resolved_value"] == {"min": 1.0, "max": 130.0}
    assert project.departure["citation"] == mb.EIS_CITATION
    ends = project.departure["ends"]
    assert [e["end"] for e in ends] == ["min"], (
        "only the min end was loosened; the max end (130 == 130) must not "
        "be reported as a departure")
    assert ends[0]["baseline_value"] == 5.0
    assert ends[0]["resolved_value"] == 1.0
    assert ends[0]["detail"] is not None

    # Now the QC outcome, evaluated with the REAL check function.
    flag_against_baseline = recovery_check_profiled(
        _window_profile(baseline_only, "EPA_1633A"),
        "13C4-PFBA", "Drinking Water", "EIS", 2.0, "inj1")
    assert flag_against_baseline is not None, (
        "2.0% is below the real method floor of 5.0% and must be flagged "
        "when nothing has loosened it")

    flag_against_project = recovery_check_profiled(
        _window_profile(project, "EPA_1633A"),
        "13C4-PFBA", "Drinking Water", "EIS", 2.0, "inj1")
    assert flag_against_project is None, (
        "once the project tier resolves the floor to 1.0%, 2.0% is inside "
        "it and the QC engine must not flag it -- even though that same "
        "resolution independently reports DEPARTS from the method")


# ── 6. Criterion with NO baseline: UNKNOWN, but QC still flags normally ─────

def test_unknown_conformance_does_not_contaminate_the_qc_pass_fail_outcome():
    """dup_rpd_max has no seeded baseline anywhere (method_baselines._REGISTRY
    only carries EPA_1633A eis_recovery) -- conformance must be UNKNOWN
    regardless of the value tested against it, in BOTH directions, proving
    the two axes (conformance vs QC pass/fail) do not leak into each other."""
    resolved = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max", profile=_LAB_PROFILE)
    assert resolved.conformance == mb.UNKNOWN
    assert resolved.departure is None

    profile = _max_profile(resolved, "FDA_32PFAS")

    flag_fail = rpd_check_profiled(profile, "PFOA", "Eggs", "Dup", 25.0, "inj1")
    assert flag_fail is not None, "UNKNOWN conformance must not suppress a real QC flag"

    flag_pass = rpd_check_profiled(profile, "PFOA", "Eggs", "Dup", 5.0, "inj1")
    assert flag_pass is None, "UNKNOWN conformance must not manufacture a QC flag either"

    # The SAME ResolvedCriterion was used for both -- confirm it never changed.
    assert resolved.conformance == mb.UNKNOWN


# ── 7. Boundary values: inclusive/exclusive as the engine implements it ─────

def test_boundary_values_are_inclusive_as_the_engine_actually_implements_it():
    """rpd_check_profiled's own comparison is `rpd_pct <= limit` (SHAPE_MAX,
    inclusive pass); recovery_check_profiled's own comparison is
    `min <= pct <= max` (SHAPE_WINDOW, inclusive at both ends). Proven here
    against the engine's source, not assumed."""
    dup = rs.resolve("FDA_32PFAS", "Eggs", "dup_rpd_max", profile=_LAB_PROFILE)
    assert dup.value == 20.0
    dup_profile = _max_profile(dup, "FDA_32PFAS")
    assert rpd_check_profiled(dup_profile, "PFOA", "Eggs", "Dup", 20.0, "inj1") is None, (
        "exactly at the limit must pass -- the engine's own comparison is "
        "`rpd_pct <= limit`, inclusive")
    assert rpd_check_profiled(dup_profile, "PFOA", "Eggs", "Dup", 20.01, "inj1") is not None, (
        "a value over the limit must fail (20.01 is a convenient value over "
        "the limit, not asserted to be the smallest representable one)")

    ccv = rs.resolve("FDA_32PFAS", "Eggs", "ccv_recovery", profile=_LAB_PROFILE)
    assert ccv.value == {"min": 70.0, "max": 130.0}
    ccv_profile = _window_profile(ccv, "FDA_32PFAS")
    assert recovery_check_profiled(ccv_profile, "PFOA", "Eggs", "CCV", 70.0, "inj1") is None, (
        "exactly at the floor must pass -- the engine's own comparison is "
        "`min <= pct <= max`, inclusive at both ends")
    assert recovery_check_profiled(ccv_profile, "PFOA", "Eggs", "CCV", 130.0, "inj1") is None, (
        "exactly at the ceiling must pass -- inclusive")
    assert recovery_check_profiled(ccv_profile, "PFOA", "Eggs", "CCV", 69.99, "inj1") is not None, (
        "a value under the floor must fail")
    assert recovery_check_profiled(ccv_profile, "PFOA", "Eggs", "CCV", 130.01, "inj1") is not None, (
        "a value over the ceiling must fail")


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
