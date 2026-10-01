# -*- coding: utf-8 -*-
"""Per-method labelled-standards grid (DECISIONS 2026-09-30).

The migration must be FAITHFUL: for a profile in the legacy shape
(surrogate_is / surrogate_is_chain), the pipeline decides exactly the same
things from the migrated grid -- which compounds it monitors, which are
injection standards (not dilution-corrected, not recovery-checked), and what
each is linked to. Plus the save checks. Runs the real modules (no Zope).
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "senaite", "pfas"))

import labelled_standards as ls                       # noqa: E402
from pfas_pipeline import method_profiles as mp       # noqa: E402
from pfas_pipeline.analyte_alias import injection_is_names   # noqa: E402

GLOBAL_INJECTION = ["M4PFOA"]
FDA_LIKE = {  # a chain: every surrogate -> M4PFOA, plus the old field
    "surrogate_map": [{"analyte": "PFOA", "surrogate_is": "M8PFOA"},
                      {"analyte": "PFNA", "surrogate_is": "M5PFNA"},
                      {"analyte": "PFOS", "surrogate_is": "M8PFOS"}],
    "surrogate_is": "M4PFOA",
    "surrogate_is_chain": {"M8PFOA": "M4PFOA", "M5PFNA": "M4PFOA", "M8PFOS": "M4PFOA"},
}
EPA_LIKE = {  # no chain, empty old field: the pipeline fell back to global roles
    "surrogate_map": [{"analyte": "PFOA", "surrogate_is": "M8PFOA"},
                      {"analyte": "PFHxA", "surrogate_is": "M5PFHxA"}],
    "surrogate_is": "",
}


def _decisions(profile):
    """What the pipeline decides for a method holding `profile`."""
    mp._profile_data_cache["TEST_M"] = profile
    try:
        return (set(mp.get_is_list("TEST_M")),
                mp.get_injection_standards("TEST_M"),
                mp.get_surrogate_is_chain("TEST_M"))
    finally:
        mp._profile_data_cache.pop("TEST_M", None)


def _migrated(profile):
    p = copy.deepcopy(profile)
    assert ls.migrate(p, GLOBAL_INJECTION)
    return p


def test_the_migration_changes_no_pipeline_decision():
    for legacy in (FDA_LIKE, EPA_LIKE):
        assert _decisions(copy.deepcopy(legacy)) == _decisions(_migrated(legacy)), legacy


def test_the_legacy_fallback_matches_the_global_roles():
    """Sanity for the test above: a legacy profile's injection set really is
    the global one (so a faithful grid must reproduce it)."""
    assert _decisions(copy.deepcopy(EPA_LIKE))[1] == injection_is_names()


def test_migration_is_idempotent_and_retires_the_legacy_keys():
    p = _migrated(FDA_LIKE)
    assert "surrogate_is" not in p and "surrogate_is_chain" not in p
    before = copy.deepcopy(p)
    assert not ls.migrate(p, GLOBAL_INJECTION)
    assert p == before


def test_a_grid_can_carry_several_injection_standards_and_any_link():
    p = _migrated(EPA_LIKE)
    p["labelled_standards"]["M2PFOA"] = {"role": "injection_is", "reference": ""}
    p["labelled_standards"]["M5PFHxA"]["reference"] = "M8PFOA"      # EIS -> EIS
    names, injection, chain = _decisions(p)
    assert len(injection) == 2
    assert chain["M5PFHxA"] == "M8PFOA"
    assert ls.check(p) == []


def test_the_checks_refuse_bad_links_loops_and_map_disagreement():
    p = _migrated(FDA_LIKE)
    g = p["labelled_standards"]
    g["M8PFOA"]["reference"] = "M8PFOA"
    assert any("linked to itself" in e for e in ls.check(p))
    g["M8PFOA"]["reference"] = "M2PFDA"                              # not used
    assert any("does not use" in e for e in ls.check(p))
    g["M8PFOA"]["reference"] = "M5PFNA"
    g["M5PFNA"]["reference"] = "M8PFOA"                              # a loop
    loops = [e for e in ls.check(p) if "loop" in e]
    assert len(loops) == 1, loops
    p = _migrated(FDA_LIKE)
    del p["labelled_standards"]["M8PFOS"]                            # map still uses it
    assert any("not ticked Used" in e for e in ls.check(p))
    p = _migrated(FDA_LIKE)
    p["labelled_standards"]["M8PFOA"]["role"] = "injection_is"       # map needs extracted
    assert any("must be extracted" in e for e in ls.check(p))


def test_the_seeds_hold_a_grid_and_no_legacy_keys():
    with open(os.path.join(ROOT, "src", "senaite", "pfas", "method_profile_store.py")) as fh:
        body = fh.read()
    assert "_convert_seeds()" in body, "seeds would re-add surrogate_is_chain via export back-fill"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
