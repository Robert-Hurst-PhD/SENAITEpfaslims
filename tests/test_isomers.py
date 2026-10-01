# -*- coding: utf-8 -*-
"""Per-method isomers (DECISIONS 2026-10-01).

The migration from `isomer_summation` must change no pipeline decision: the
same groups are summed under the same keywords, and the salt factor still
reaches every component. Labels follow the method's isomers (a summed PFOS is
"PFOS", not the linear-peak name "lr-PFOS"), and the save checks refuse what
would double-count or silently drop a peak. Runs the real modules (no Zope).
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "senaite", "pfas"))

import analyte_reference as ar                   # noqa: E402
import isomers                                   # noqa: E402
from pfas_pipeline import method_profiles as mp  # noqa: E402

TITLES = dict((r[0], r[1]) for r in ar.NATIVE_ANALYTES)
LEGACY = {
    "master_analyte_set": ["PFOA", "PFOS", "PFHxS", "PFNA"],
    "isomer_summation": [
        {"linear": "lr-PFOS", "branched": "br-PFOS", "reported": "PFOS", "enabled": True},
        {"linear": "lr-PFHxS", "branched": "br-PFHxS", "reported": "PFHxS", "enabled": True},
        {"linear": "lr-PFNA", "branched": "br-PFNA", "reported": "PFNA", "enabled": True}],
    "salt_adjustment_factors": [{"analyte": "PFOS", "factor": 0.956}],
}


def _pipeline(profile):
    mp._profile_data_cache["TEST_I"] = profile
    try:
        groups = sorted((g["linear"], tuple(g["branched_list"]), g["reported"])
                        for g in mp.get_isomer_summation("TEST_I"))
        return groups, mp.get_salt_factors("TEST_I")
    finally:
        mp._profile_data_cache.pop("TEST_I", None)


def _migrated(p):
    p = copy.deepcopy(p)
    isomers.migrate(p)
    return p


def test_the_migration_changes_no_pipeline_decision():
    assert _pipeline(copy.deepcopy(LEGACY)) == _pipeline(_migrated(LEGACY))


def test_the_migration_changes_nothing_on_the_live_profiles():
    path = os.environ.get("PFAS_PROFILES_PATH") or os.path.join(ROOT, "data", "qc", "method_profiles.json")
    with open(path) as fh:
        data = json.load(fh)
    data = data.get("profiles", data)
    for mid, p in data.items():
        if isomers.KEY in p and isomers.LEGACY not in p:
            continue                                         # already migrated
        assert _pipeline(copy.deepcopy(p)) == _pipeline(_migrated(p)), mid


def test_reporting_is_always_one_analyte_out():
    """A legacy pair switched off is summed after migration: reporting is one
    analyte out; the peaks stay for internal review (revised 2026-10-01)."""
    legacy = copy.deepcopy(LEGACY)
    legacy["isomer_summation"][2]["enabled"] = False
    groups, _salt = _pipeline(_migrated(legacy))
    assert ("lr-PFNA", ("br-PFNA",), "PFNA") in groups
    assert all("summed" not in e for e in _migrated(legacy)["isomers"].values())


def test_migration_is_idempotent_and_retires_the_legacy_key():
    p = _migrated(LEGACY)
    assert isomers.LEGACY not in p
    before = copy.deepcopy(p)
    assert not isomers.migrate(p) and p == before


def test_several_branched_peaks_reach_the_pipeline_and_the_salt_factor():
    p = _migrated(LEGACY)
    p["isomers"]["PFOS"]["branched"] = ["br-PFOS", "br2-PFOS"]
    groups, salt = _pipeline(p)
    assert ("lr-PFOS", ("br-PFOS", "br2-PFOS"), "PFOS") in groups
    assert salt.get("br2-PFOS") == 0.956 and salt.get("lr-PFOS") == 0.956


def test_a_summed_analyte_is_labelled_by_its_reported_name():
    p = _migrated(LEGACY)
    assert TITLES["PFOS"] == "PFOS"                          # no longer the linear-peak name
    assert ar.COMPOUND_NAME_TO_KEYWORD["lr-PFOS"] == "PFOS"  # ... which still resolves
    assert isomers.label(p, "PFOS", TITLES) == "PFOS"
    p["isomers"]["PFOS"]["reported"] = "Total PFOS"
    assert isomers.label(p, "PFOS", TITLES) == "Total PFOS"
    assert isomers.label(p, "PFOA", TITLES) == TITLES["PFOA"]


def test_the_checks():
    p = _migrated(LEGACY)
    assert isomers.check(p, TITLES) == []
    p["isomers"]["PFHxS"]["branched"] = ["br-PFOS"]                   # PFOS's peak
    assert any("counted twice" in e for e in isomers.check(p, TITLES))
    p = _migrated(LEGACY)
    p["isomers"]["PFOS"]["reported"] = "PFOA"                         # another analyte's name
    assert any("both be reported as" in e for e in isomers.check(p, TITLES))
    p = _migrated(LEGACY)
    p["isomers"]["PFOS"]["linear"] = ""
    assert any("needs its linear peak" in e for e in isomers.check(p, TITLES))



def test_lr_names_only_the_linear_peak():
    """One analyte out (DECISIONS 2026-10-01): the reported analyte, the core
    service title and the EDD parameter carry the plain name; "lr-" survives
    only as the linear PEAK's name (alias for instrument matching)."""
    assert not [r[1] for r in ar.NATIVE_ANALYTES if r[1].lower().startswith("lr-")]
    assert set(ar.LINEAR_PEAK_ALIASES) == {"lr-PFOS", "lr-PFHxS"}
    for name, kw in ar.LINEAR_PEAK_ALIASES.items():
        assert ar.COMPOUND_NAME_TO_KEYWORD[name] == kw
    with open(os.path.join(ROOT, "src", "senaite", "pfas", "setupdata", "analysis_services.csv")) as fh:
        assert ",lr-" not in fh.read()
    with open(os.path.join(ROOT, "src", "senaite", "pfas", "egad_store.py")) as fh:
        body = fh.read()
    assert "PFOS_A_L" not in body and "PFHXS_A_L" not in body


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
