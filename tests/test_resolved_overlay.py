"""Regression tests for the worker-side half of GAPS.md Sec20: per-batch
RESOLVED (project -> lab -> baseline) criteria overlaid onto the global
method-profile cache pfas_pipeline.method_profiles already loads from
data/qc/method_profiles.json.

The add-on (senaite.pfas.resolved_criteria_store, tested separately in
tests/test_resolved_criteria_store.py) does the actual tier resolution and
writes one JSON file per project-linked batch. This file proves the OTHER
half: pfas_pipeline.method_profiles.reload_from_profiles(batch_id=...) reads
that file back and injects it into _profile_data_cache -- and, just as
importantly, proves the safety property the whole feature depends on: a
batch with no resolved file (every batch today) is affected NOT AT ALL.

    python3 tests/test_resolved_overlay.py
"""
from __future__ import print_function

import copy
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pfas_pipeline import method_profiles as mp


_GLOBAL_PROFILES = {
    "FDA_32PFAS": {
        "instrument_verification": {
            "calibration": {"r2_min": 0.995},
            "confirmation": {"sn_quan_min": 3.0},
            "ccv": {"recovery_min": 70.0, "recovery_max": 130.0},
        },
        "qc_acceptance": {
            "Dup": {"tiers": [{"rpd_max": 20.0}]},
        },
        "eis_overrides": [],
    },
    "EPA_537_1": copy.deepcopy(mp._DEFAULT_PROFILE_CACHE["EPA_537_1"]),
    "EPA_1633A": {
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
        ],
    },
}


def _reset_cache():
    mp._profile_data_cache.clear()
    mp._profile_data_cache.update(copy.deepcopy(mp._DEFAULT_PROFILE_CACHE))


def _write_global(tmp):
    path = os.path.join(tmp, "method_profiles.json")
    with open(path, "w") as fh:
        json.dump(_GLOBAL_PROFILES, fh)
    return path


def _write_resolved(tmp, batch_id, payload):
    d = os.path.join(tmp, "resolved")
    if not os.path.exists(d):
        os.makedirs(d)
    with open(os.path.join(d, batch_id + ".json"), "w") as fh:
        if isinstance(payload, str):
            fh.write(payload)
        else:
            json.dump(payload, fh)


def _cal_r2(method_id="FDA_32PFAS"):
    return mp._profile_data_cache[method_id]["instrument_verification"]["calibration"]["r2_min"]


# ── The safety property: no batch_id / no file changes nothing ─────────────

def test_no_batch_id_behaves_exactly_as_before():
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath)
        without_overlay = copy.deepcopy(mp._profile_data_cache)

        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id=None)
        with_none = copy.deepcopy(mp._profile_data_cache)

        assert without_overlay == with_none, "batch_id=None must change nothing"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_batch_id_with_no_resolved_file_is_a_silent_no_op():
    """Every batch today: no project, so no file was ever exported for it.
    Passing its id must be indistinguishable from not passing one."""
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath)
        baseline = copy.deepcopy(mp._profile_data_cache)

        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-NO-PROJECT")
        after = copy.deepcopy(mp._profile_data_cache)

        assert baseline == after, (
            "a batch with no resolved file must produce an IDENTICAL profile "
            "cache to one where batch_id was never passed at all")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── The overlay itself ──────────────────────────────────────────────────────

def test_a_well_formed_resolved_file_overlays_scalar_and_window_criteria():
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0100", {
            "batch_id": "B-0100", "method_id": "FDA_32PFAS", "matrix": "Eggs",
            "criteria": [
                {"key": "cal_r2_min", "analyte": None, "value": 0.980,
                 "tier": "project", "source_doc": "QAPP-7", "source_rev": 3,
                 "conformance": "UNKNOWN", "departure": None},
                {"key": "ccv_recovery", "analyte": None,
                 "value": {"min": 75.0, "max": 125.0}, "tier": "project",
                 "source_doc": "QAPP-7", "source_rev": 3,
                 "conformance": "UNKNOWN", "departure": None},
                {"key": "dup_rpd_max", "analyte": None, "value": 15.0,
                 "tier": "lab", "source_doc": None, "source_rev": None,
                 "conformance": "UNKNOWN", "departure": None},
            ],
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0100")
        data = mp._profile_data_cache["FDA_32PFAS"]
        assert data["instrument_verification"]["calibration"]["r2_min"] == 0.980
        assert data["instrument_verification"]["ccv"]["recovery_min"] == 75.0
        assert data["instrument_verification"]["ccv"]["recovery_max"] == 125.0
        assert data["qc_acceptance"]["Dup"]["tiers"][0]["rpd_max"] == 15.0
        # A criterion the file did NOT mention (sn_quan_min) is untouched.
        assert data["instrument_verification"]["confirmation"]["sn_quan_min"] == 3.0
        # Other methods are untouched by a file scoped to FDA_32PFAS.
        assert mp._profile_data_cache["EPA_1633A"]["instrument_verification"][
            "calibration"]["r2_min"] == 0.990
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_eis_recovery_overlay_applies_per_analyte():
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0200", {
            "batch_id": "B-0200", "method_id": "EPA_1633A",
            "matrix": "Drinking Water",
            "criteria": [
                {"key": "eis_recovery", "analyte": "13C4-PFBA",
                 "value": {"min": 1.0, "max": 200.0}, "tier": "project",
                 "source_doc": "QAPP-9", "source_rev": 1,
                 "conformance": "DEPARTS", "departure": {"citation": "x"}},
            ],
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0200")
        eis = mp._profile_data_cache["EPA_1633A"]["eis_overrides"]
        assert eis["13C4-PFBA"] == {"recovery_min": 1.0, "recovery_max": 200.0}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_null_value_row_is_not_applied():
    """tier=baseline with no seeded baseline resolves value=None -- that is
    "nothing to overlay", not "overlay nothing" (a bug would be writing None
    over a perfectly good lab value)."""
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0300", {
            "batch_id": "B-0300", "method_id": "FDA_32PFAS", "matrix": "Eggs",
            "criteria": [
                {"key": "cal_r2_min", "analyte": None, "value": None,
                 "tier": "baseline", "source_doc": None, "source_rev": None,
                 "conformance": "UNKNOWN", "departure": None},
            ],
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0300")
        assert _cal_r2() == 0.995, "a None-valued row must not clobber the lab value"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Malformed / partial files: reject the whole file, never half-apply ──────

def test_corrupt_json_is_ignored_entirely():
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0400", "{not valid json")
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath)
        baseline = copy.deepcopy(mp._profile_data_cache)

        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0400")
        after = copy.deepcopy(mp._profile_data_cache)
        assert after == baseline
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unknown_method_id_is_ignored_entirely():
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0500", {
            "batch_id": "B-0500", "method_id": "NOT_A_REAL_METHOD",
            "matrix": "Eggs",
            "criteria": [{"key": "cal_r2_min", "analyte": None, "value": 0.5,
                          "tier": "project", "source_doc": None,
                          "source_rev": None, "conformance": "UNKNOWN",
                          "departure": None}],
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath)
        baseline = copy.deepcopy(mp._profile_data_cache)

        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0500")
        after = copy.deepcopy(mp._profile_data_cache)
        assert after == baseline
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_one_malformed_row_rejects_the_whole_file_not_just_that_row():
    """The GAPS.md Sec7.1 partial-write shape, one layer over: a file with
    one good row and one broken row must apply NEITHER -- never leave the
    cache in a state where it is unclear which criteria came from the
    project tier and which did not."""
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0600", {
            "batch_id": "B-0600", "method_id": "FDA_32PFAS", "matrix": "Eggs",
            "criteria": [
                {"key": "cal_r2_min", "analyte": None, "value": 0.980,
                 "tier": "project", "source_doc": "QAPP-1", "source_rev": 1,
                 "conformance": "UNKNOWN", "departure": None},
                "this-is-not-even-a-dict",
            ],
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath)
        baseline = copy.deepcopy(mp._profile_data_cache)

        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0600")
        after = copy.deepcopy(mp._profile_data_cache)
        assert after == baseline, (
            "the well-formed cal_r2_min row must NOT have been applied -- "
            "the malformed sibling must reject the whole file")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_criteria_not_a_list_is_ignored_entirely():
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0700", {
            "batch_id": "B-0700", "method_id": "FDA_32PFAS", "matrix": "Eggs",
            "criteria": {"cal_r2_min": 0.5},
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath)
        baseline = copy.deepcopy(mp._profile_data_cache)

        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0700")
        after = copy.deepcopy(mp._profile_data_cache)
        assert after == baseline
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_unmapped_key_is_a_harmless_per_row_no_op_not_a_file_rejection():
    """A criterion key ruleset.py registers that this worker version does
    not (yet) apply anywhere is forward-compatible -- it must not sink the
    other, applicable rows in the same file."""
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0800", {
            "batch_id": "B-0800", "method_id": "FDA_32PFAS", "matrix": "Eggs",
            "criteria": [
                {"key": "cal_r2_min", "analyte": None, "value": 0.980,
                 "tier": "project", "source_doc": None, "source_rev": None,
                 "conformance": "UNKNOWN", "departure": None},
                {"key": "some_future_criterion_key", "analyte": None,
                 "value": 42, "tier": "project", "source_doc": None,
                 "source_rev": None, "conformance": "UNKNOWN",
                 "departure": None},
            ],
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0800")
        assert _cal_r2() == 0.980
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── The CRITERIA wrinkle: a second live consumer of the same two keys ──────
#
# qc_engine.signal_to_noise_check() (unconditionally) and the no-profile
# fallback branch of qc_engine.calibration_check() read constants.CRITERIA
# directly -- a dict reload_criteria() builds by re-reading the global file,
# never through _profile_data_cache. Without also overlaying CRITERIA, a
# project override of cal_r2_min/sn_quan_min would reach the profiled
# consumer but not this one: the same batch, the same criterion, two
# different answers depending which check asked.

def _reset_criteria():
    from pfas_pipeline.constants import CRITERIA, _DEFAULT_CRITERIA, _build_criteria_from_profile
    CRITERIA.clear()
    CRITERIA.update(_build_criteria_from_profile(_GLOBAL_PROFILES["FDA_32PFAS"]))
    CRITERIA["mdl_min_replicates"] = _DEFAULT_CRITERIA["mdl_min_replicates"]
    CRITERIA["t_values"] = _DEFAULT_CRITERIA["t_values"]


def test_a_project_override_of_cal_r2_min_also_reaches_criteria():
    from pfas_pipeline.constants import CRITERIA
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-0900", {
            "batch_id": "B-0900", "method_id": "FDA_32PFAS", "matrix": "Eggs",
            "criteria": [
                {"key": "cal_r2_min", "analyte": None, "value": 0.980,
                 "tier": "project", "source_doc": "QAPP-1", "source_rev": 1,
                 "conformance": "UNKNOWN", "departure": None},
                {"key": "sn_quan_min", "analyte": None, "value": 2.5,
                 "tier": "project", "source_doc": "QAPP-1", "source_rev": 1,
                 "conformance": "UNKNOWN", "departure": None},
            ],
        })
        _reset_cache()
        _reset_criteria()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-0900")
        # The profiled consumer's source of truth:
        assert _cal_r2() == 0.980
        # The UNCONDITIONAL consumer's source of truth -- must agree, not
        # silently keep the un-overridden lab value.
        assert CRITERIA["cal_r2_min"] == 0.980
        assert CRITERIA["sn_quan_min"] == 2.5
        assert CRITERIA["sn_min"] == 2.5, "sn_min is the back-compat alias"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_criteria_overlay_is_scoped_to_fda_32pfas_only():
    """reload_criteria() is called with no method_id anywhere in this
    codebase, so it always builds CRITERIA from FDA_32PFAS -- a pre-existing
    behaviour (GAPS.md Sec20), not something this overlay should paper over
    by writing a different method's resolved value into a dict that does
    not represent that method today regardless of any project link."""
    from pfas_pipeline.constants import CRITERIA
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-1000", {
            "batch_id": "B-1000", "method_id": "EPA_1633A",
            "matrix": "Drinking Water",
            "criteria": [
                {"key": "cal_r2_min", "analyte": None, "value": 0.5,
                 "tier": "project", "source_doc": None, "source_rev": None,
                 "conformance": "UNKNOWN", "departure": None},
            ],
        })
        _reset_cache()
        _reset_criteria()
        before = dict(CRITERIA)
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-1000")
        assert dict(CRITERIA) == before, (
            "an EPA_1633A resolved payload must not touch CRITERIA, which "
            "only ever represents FDA_32PFAS today")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── No cross-batch leak in the long-lived worker process ───────────────────

def test_a_project_overlay_does_not_leak_into_the_next_batch_without_one():
    """The worker process is long-lived and processes runs back-to-back
    against the same module-global _profile_data_cache. Run A (project-
    linked, overlay applied) must not leave any trace for run B (no
    project) in the same process -- proven WITHOUT the _reset_cache() every
    other test uses, because production never resets between batches
    either; the wholesale `_profile_data_cache[method_id] = data` replace
    in the global-file loop is what has to do this job instead."""
    tmp = tempfile.mkdtemp()
    try:
        gpath = _write_global(tmp)
        _write_resolved(tmp, "B-1100", {
            "batch_id": "B-1100", "method_id": "FDA_32PFAS", "matrix": "Eggs",
            "criteria": [
                {"key": "cal_r2_min", "analyte": None, "value": 0.900,
                 "tier": "project", "source_doc": "QAPP-X", "source_rev": 1,
                 "conformance": "UNKNOWN", "departure": None},
            ],
        })
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-1100")
        assert _cal_r2() == 0.900, "sanity: run A's overlay applied"

        # Run B: same process, NO _reset_cache() in between, no project.
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-1101-NO-PROJECT")
        assert _cal_r2() == 0.995, (
            "run A's project-tier cal_r2_min leaked into run B, which has "
            "no project link at all")

        # Cross-check against a fresh cache that never saw run A.
        _reset_cache()
        mp.reload_from_profiles(profiles_path=gpath, batch_id="B-1101-NO-PROJECT")
        assert _cal_r2() == 0.995
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    ok = fail = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                fail += 1
                print("FAIL", name, "--", exc)
            except Exception as exc:
                fail += 1
                print("ERROR", name, "--", repr(exc))
            else:
                ok += 1
                print("PASS", name)
    print("{0} passed, {1} failed".format(ok, fail))
    if fail:
        sys.exit(1)
