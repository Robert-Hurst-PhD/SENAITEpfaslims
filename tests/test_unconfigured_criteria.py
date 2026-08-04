"""A criterion nothing configured must not be quietly met.

The FDA tier resolver used to end with an unconditional
``QCRule(65.0, 135.0, rsd_max=25.0)`` and carried ~59 inline fallbacks of the
form ``tier.get("recovery_min", 40.0)``. A profile that said nothing produced a
believable limit and no one was told. That is the CCV defect inverted: not a
wrong number displayed, but a wrong criterion silently satisfied -- and unlike
a wrong number, a passing result never draws a second look.

Decision (2026-08-03): refuse to judge. The trade was chosen with its cost
stated -- this hard-blocks a run against a profile that is not fully populated.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")

from pfas_pipeline.method_profiles import get_profile, UnconfiguredCriterion


def _fda():
    profile = get_profile("FDA")
    return profile, profile._profile_data()


def test_configured_tiers_still_resolve():
    """The refusal must not be so eager that a populated profile trips it."""
    profile, data = _fda()
    if not data.get("qc_acceptance"):
        print("  (skipped: no method profile export loaded)")
        return
    for analyte, matrix, expected in (
            ("PFOA", "deer muscle", (80.0, 120.0)),
            ("PFOA", "water", (65.0, 135.0)),
            ("PFTrDA", "deer muscle", (40.0, 140.0))):
        rule = profile.qc_rules(analyte, matrix, "LFSM")
        assert (rule.recovery_min, rule.recovery_max) == expected, (
            analyte, matrix, rule)


def test_rpd_only_tier_is_configured_not_empty():
    """A duplicate is judged by RPD and legitimately carries no recovery
    window. Demanding recovery limits everywhere refused a correctly
    configured Dup tier -- the criterion that applies depends on the QC type."""
    profile, data = _fda()
    if not data.get("qc_acceptance", {}).get("Dup"):
        print("  (skipped: no Dup criteria in the loaded profile)")
        return
    rule = profile.qc_rules("PFOA", "deer", "Dup")
    assert rule.rpd_max is not None, rule
    assert rule.recovery_min is None, rule


def test_empty_tier_refuses_rather_than_substituting():
    profile, data = _fda()
    tiers = data.get("qc_acceptance", {}).get("LFSM", {}).get("tiers")
    if not tiers:
        print("  (skipped: no LFSM tiers in the loaded profile)")
        return
    saved = [dict(t) for t in tiers]
    try:
        for tier in tiers:
            for key in ("recovery_min", "recovery_max", "rsd_max", "rpd_max"):
                tier.pop(key, None)
        try:
            rule = profile.qc_rules("PFOA", "water", "LFSM")
        except UnconfiguredCriterion as exc:
            assert "PFOA" in str(exc) and "Method Profiles" in str(exc), exc
        else:
            raise AssertionError(
                "substituted %r instead of refusing" % (rule,))
    finally:
        tiers[:] = saved


def test_half_configured_window_refuses():
    """One end blank would judge against an open interval."""
    profile, data = _fda()
    tiers = data.get("qc_acceptance", {}).get("LFSM", {}).get("tiers")
    if not tiers:
        print("  (skipped: no LFSM tiers in the loaded profile)")
        return
    saved = [dict(t) for t in tiers]
    try:
        for tier in tiers:
            tier.pop("recovery_max", None)
        try:
            profile.qc_rules("PFOA", "water", "LFSM")
        except UnconfiguredCriterion as exc:
            assert "Incomplete recovery window" in str(exc), exc
        else:
            raise AssertionError("accepted a half-configured window")
    finally:
        tiers[:] = saved


def test_confirmation_criteria_resolve_from_the_profile():
    """The ion-ratio window, RT tolerance and S/N minima were inline fallbacks
    (`conf.get("ion_ratio_tol_pct", 30.0)`) — an ion-ratio check against a
    window nobody chose passes or fails on a number the lab never set."""
    from pfas_pipeline.method_profiles import available_profiles
    for mid in available_profiles():
        profile = get_profile(mid)
        if not profile._profile_data().get("instrument_verification"):
            print("  (skipped %s: no profile export loaded)" % mid)
            continue
        profile.confirmation_rule()          # must not raise


def test_a_deliberately_absent_criterion_is_not_a_gap():
    """EPA 537.1 stores ion_ratio_tol_pct: null because the method HAS no
    qual-ion ratio criterion. Present-but-null is a decision; absent is a gap.
    The same distinction the Dup and MB tiers turned on."""
    profile = get_profile("EPA_537_1")
    conf = (profile._profile_data().get("instrument_verification")
            or {}).get("confirmation")
    if not conf:
        print("  (skipped: no profile export loaded)")
        return
    assert "ion_ratio_tol_pct" in conf, "the editor should write the key"
    assert conf["ion_ratio_tol_pct"] is None, conf
    assert profile.confirmation_rule().ion_ratio_tol_pct is None


def test_absent_confirmation_criterion_refuses():
    profile, data = _fda()
    conf = (data.get("instrument_verification") or {}).get("confirmation")
    if not conf:
        print("  (skipped: no profile export loaded)")
        return
    saved = dict(conf)
    try:
        del conf["ion_ratio_tol_pct"]
        try:
            profile.confirmation_rule()
        except UnconfiguredCriterion as exc:
            assert "ion_ratio_tol_pct" in str(exc), exc
        else:
            raise AssertionError("substituted an ion-ratio window")
        # and a wholly missing section refuses too
        data["instrument_verification"]["confirmation"] = {}
        try:
            profile.confirmation_rule()
        except UnconfiguredCriterion as exc:
            assert "confirmation" in str(exc), exc
        else:
            raise AssertionError("substituted a whole confirmation section")
    finally:
        data["instrument_verification"]["confirmation"] = saved


def test_calibration_and_is_criteria_resolve_from_the_profile():
    """r2_min gates whether a calibration is acceptable at all, and the IS
    response window gates the run. Both were inline fallbacks."""
    from pfas_pipeline.method_profiles import available_profiles
    for mid in available_profiles():
        profile = get_profile(mid)
        if not profile._profile_data().get("instrument_verification"):
            print("  (skipped %s: no profile export loaded)" % mid)
            continue
        assert profile.calibration_rule().r2_min is not None
        assert profile.is_rule().vs_ical_avg_min is not None
        # a labelled compound uses a different fit but the same criteria
        profile.calibration_rule("M8PFOA")


def test_absent_r2_min_refuses():
    profile, data = _fda()
    cal = (data.get("instrument_verification") or {}).get("calibration")
    if not cal:
        print("  (skipped: no profile export loaded)")
        return
    saved = dict(cal)
    try:
        del cal["r2_min"]
        try:
            profile.calibration_rule()
        except UnconfiguredCriterion as exc:
            assert "r2_min" in str(exc), exc
        else:
            raise AssertionError("substituted an r2 threshold")
    finally:
        data["instrument_verification"]["calibration"] = saved


def test_null_is_window_is_a_decision_not_a_gap():
    """FDA records vs_last_ccv_min/max as null: the method sets no numeric
    IS-area limit against the last CCV. That must resolve, not refuse."""
    profile, data = _fda()
    if not data.get("instrument_verification"):
        print("  (skipped: no profile export loaded)")
        return
    rule = profile.is_rule()
    assert rule.vs_ical_avg_min is not None
    assert rule.vs_last_ccv_min is None, rule


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
