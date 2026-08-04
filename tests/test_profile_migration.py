"""The migration must not delete a lab's configured limits.

`migrate_profile_structure` drops flat keys the nested structure superseded.
Two hazards were found in it on 2026-08-04:

  * `salt_adjustment_factors` was listed as obsolete and is not — it is the
    authoritative salt-correction key, applied since 2026-08-03, and it carries
    the CoA lot behind each factor. Running the migration would have deleted a
    lab's salt corrections together with their §6.6 traceability. Worse, the
    `UnconfiguredCriterion` message points users straight at this script.
  * `duplicate` and `recovery_tiers` were deleted without their values being
    carried anywhere, so a profile configured only on the flat key was silently
    reset to the seed.

§8: migrate existing configured data into the new structure without loss — not
just define the new schema.
"""
import copy
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.join(_HERE, os.pardir, "src", "senaite", "pfas", "migrations",
                    "migrate_profile_structure.py")

_spec = importlib.util.spec_from_file_location("mps", _MOD)
mps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mps)


def test_salt_factors_are_not_treated_as_obsolete():
    assert "salt_adjustment_factors" not in mps.OLD_KEYS, (
        "salt_adjustment_factors is the authoritative salt key — removing it "
        "deletes the correction AND its CoA lot traceability")


def test_duplicate_rpd_is_carried_not_dropped():
    profile = {"duplicate": {"rpd_max": 17.0}}
    moved = mps.carry_legacy_values(profile)
    tiers = profile["qc_acceptance"]["Dup"]["tiers"]
    assert tiers[0]["rpd_max"] == 17.0, profile
    # and the tier must be a valid catch-all, or the engine will not match it
    assert tiers[0]["analyte_group"] == "all", tiers
    assert tiers[0]["matrix_scope"] == "all", tiers
    assert moved, "the move should be reported"


def test_recovery_tiers_are_carried_not_dropped():
    legacy = [{"name": "t1", "recovery_min": 82.0, "recovery_max": 118.0}]
    profile = {"recovery_tiers": copy.deepcopy(legacy)}
    mps.carry_legacy_values(profile)
    assert profile["qc_acceptance"]["LFSM"]["tiers"] == legacy, profile


def test_an_existing_value_is_never_overwritten():
    """The enforced structure wins; the flat key is only a source for what is
    missing. Overwriting would silently revert a deliberate newer edit."""
    profile = {
        "duplicate": {"rpd_max": 17.0},
        "recovery_tiers": [{"name": "old", "recovery_min": 1.0}],
        "qc_acceptance": {
            "Dup": {"enabled": True, "tiers": [{"rpd_max": 20.0}]},
            "LFSM": {"enabled": True, "tiers": [{"name": "current"}]},
        },
    }
    mps.carry_legacy_values(profile)
    assert profile["qc_acceptance"]["Dup"]["tiers"][0]["rpd_max"] == 20.0
    assert profile["qc_acceptance"]["LFSM"]["tiers"][0]["name"] == "current"


def test_is_idempotent():
    profile = {"duplicate": {"rpd_max": 17.0},
               "recovery_tiers": [{"name": "t1"}]}
    mps.carry_legacy_values(profile)
    first = copy.deepcopy(profile["qc_acceptance"])
    assert not mps.carry_legacy_values(profile), "second pass should move nothing"
    assert profile["qc_acceptance"] == first


def test_nothing_to_carry_is_a_no_op():
    profile = {"qc_acceptance": {"Dup": {"tiers": [{"rpd_max": 20.0}]}}}
    before = copy.deepcopy(profile)
    assert not mps.carry_legacy_values(profile)
    assert profile == before


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
