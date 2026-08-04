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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
