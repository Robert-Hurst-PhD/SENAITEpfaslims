# -*- coding: utf-8 -*-
"""Regression tests for senaite.pfas.resolved_criteria_store -- the file
bridge that carries a batch's fully-resolved (project -> lab -> baseline)
QC criteria to the pipeline worker (GAPS.md Sec20).

Loaded by path, exactly like tests/test_ruleset.py, since this module falls
back to a bare `import ruleset` when the senaite.pfas package (which needs
zope.i18nmessageid) is not importable. Only the PURE functions
(build_resolved_rows / write_resolved_file / _analytes_for_key) are
exercised here -- export_resolved_criteria()/remove_resolved_criteria() are
thin ZODB shells with no Zope available in this environment, proven live
against the running instance instead (see this file's report).

    python3 tests/test_resolved_criteria_store.py
"""
from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, os.pardir, "src", "senaite", "pfas")


def _load(path, name):
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
assert rs.method_baselines is mb
sys.modules.setdefault("ruleset", rs)
rcs = _load(os.path.join(_SRC, "resolved_criteria_store.py"),
            "pfas_resolved_criteria_store_under_test")
assert rcs.ruleset is rs, "resolved_criteria_store loaded a second copy of ruleset"


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
}


# ── build_resolved_rows: enumeration + shape ─────────────────────────────────

def test_every_non_analyte_scoped_key_produces_exactly_one_row():
    rows = rcs.build_resolved_rows("FDA_32PFAS", "Eggs", profile=_FDA_PROFILE)
    keys = [r["key"] for r in rows]
    for key in rs.SHAPES_BY_KEY:
        if key in rs.ANALYTE_SCOPED_KEYS:
            continue
        assert keys.count(key) == 1, (key, keys)


def test_eis_recovery_enumerates_every_lab_configured_analyte():
    rows = rcs.build_resolved_rows("EPA_1633A", "Drinking Water",
                                    profile=_EPA1633A_PROFILE)
    eis_rows = [r for r in rows if r["key"] == "eis_recovery"]
    analytes = sorted(r["analyte"] for r in eis_rows)
    assert analytes == ["13C4-PFBA", "13C5-PFPeA"], analytes


def test_eis_recovery_also_enumerates_a_project_only_analyte():
    """A project ruleset can name an analyte the lab profile never
    configured (e.g. a QAPP-mandated additional surrogate) -- that analyte
    must still be enumerated, not silently dropped."""
    project_ruleset = {
        "EPA_1633A": {
            "Drinking Water": {
                "eis_recovery": {"13C7-PFUnA": {"min": 10.0, "max": 150.0}},
            },
        },
    }
    rows = rcs.build_resolved_rows("EPA_1633A", "Drinking Water",
                                    profile=_EPA1633A_PROFILE,
                                    project_ruleset=project_ruleset)
    analytes = sorted(r["analyte"] for r in rows if r["key"] == "eis_recovery")
    assert analytes == ["13C4-PFBA", "13C5-PFPeA", "13C7-PFUnA"], analytes


def test_row_shape_carries_every_field_the_worker_needs():
    project_ruleset = {"FDA_32PFAS": {"Eggs": {"cal_r2_min": 0.980}}}
    rows = rcs.build_resolved_rows("FDA_32PFAS", "Eggs", profile=_FDA_PROFILE,
                                    project_ruleset=project_ruleset,
                                    project_doc="QAPP-007", project_rev=3)
    row = next(r for r in rows if r["key"] == "cal_r2_min")
    assert row["value"] == 0.980
    assert row["tier"] == rs.TIER_PROJECT
    assert row["source_doc"] == "QAPP-007"
    assert row["source_rev"] == 3
    assert row["conformance"] == mb.UNKNOWN   # no seeded baseline for cal_r2_min
    assert row["departure"] is None
    assert set(row.keys()) == {
        "key", "analyte", "value", "tier", "source_doc", "source_rev",
        "conformance", "departure",
    }


def test_a_departing_eis_row_carries_full_departure_detail():
    project_ruleset = {
        "EPA_1633A": {
            "Drinking Water": {
                "eis_recovery": {"13C4-PFBA": {"min": 1.0, "max": 200.0}},
            },
        },
    }
    rows = rcs.build_resolved_rows("EPA_1633A", "Drinking Water",
                                    profile=_EPA1633A_PROFILE,
                                    project_ruleset=project_ruleset)
    row = next(r for r in rows
               if r["key"] == "eis_recovery" and r["analyte"] == "13C4-PFBA")
    assert row["tier"] == rs.TIER_PROJECT
    assert row["conformance"] == mb.DEPARTS, row
    ends = sorted(e["end"] for e in row["departure"]["ends"])
    assert ends == ["max", "min"], ends
    assert row["departure"]["citation"] and "820-R-24-007" in row["departure"]["citation"]


# ── write_resolved_file / resolved_file_path ─────────────────────────────────

def test_write_resolved_file_round_trips_every_field():
    tmp = tempfile.mkdtemp()
    try:
        rows = rcs.build_resolved_rows(
            "FDA_32PFAS", "Eggs", profile=_FDA_PROFILE,
            project_ruleset={"FDA_32PFAS": {"Eggs": {"cal_r2_min": 0.98}}},
            project_doc="QAPP-1", project_rev=2)
        path = rcs.write_resolved_file("WS-0099", "FDA_32PFAS", "Eggs", rows,
                                        directory=tmp)
        assert path == os.path.join(tmp, "WS-0099.json")
        assert os.path.exists(path)
        with open(path) as fh:
            payload = json.load(fh)
        assert payload["batch_id"] == "WS-0099"
        assert payload["method_id"] == "FDA_32PFAS"
        assert payload["matrix"] == "Eggs"
        assert len(payload["criteria"]) == len(rows)
        by_key = dict((r["key"], r) for r in payload["criteria"]
                      if r["analyte"] is None)
        assert by_key["cal_r2_min"]["value"] == 0.98
        assert by_key["cal_r2_min"]["tier"] == "project"
        assert by_key["cal_r2_min"]["source_doc"] == "QAPP-1"
        assert by_key["cal_r2_min"]["source_rev"] == 2
        # No .tmp file left behind (atomic rename).
        assert not os.path.exists(path + ".tmp")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_resolved_file_path_sanitizes_the_batch_id():
    path = rcs.resolved_file_path("../../etc/WS 0099!", directory="/x")
    assert path == "/x/....etcWS0099.json", path
    # No path separator survives -- whatever the mangled name looks like, it
    # cannot escape `directory` (no traversal via a "/" component).
    assert os.path.dirname(path) == "/x"
    assert "/" not in os.path.basename(path)


def test_write_resolved_file_creates_the_directory():
    tmp = tempfile.mkdtemp()
    try:
        target = os.path.join(tmp, "resolved")
        assert not os.path.exists(target)
        rcs.write_resolved_file("WS-1", "FDA_32PFAS", "Eggs", [], directory=target)
        assert os.path.isdir(target)
        assert os.path.exists(os.path.join(target, "WS-1.json"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_resolved_dir_honours_the_profiles_path_env_var(monkeypatch=None):
    old = os.environ.get("PFAS_PROFILES_PATH")
    try:
        os.environ["PFAS_PROFILES_PATH"] = "/custom/place/method_profiles.json"
        assert rcs._resolved_dir() == "/custom/place/resolved"
    finally:
        if old is None:
            os.environ.pop("PFAS_PROFILES_PATH", None)
        else:
            os.environ["PFAS_PROFILES_PATH"] = old


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
