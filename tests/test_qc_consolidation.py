# -*- coding: utf-8 -*-
"""QC profile consolidation P1 + P2 (docs/QC_PROFILE_CONSOLIDATION.md,
DECISIONS 2026-10-02).

Every QC fact has one home, the method profile:
  * retired keys go (sequence, extraction_corrections, empty spec_overrides);
  * rule switches, the ICV limit and the CCV warning line move in from
    qc_rules.json once, and that file can never take criteria back;
  * the worker judges nothing without an exported profile, and its flat
    CRITERIA describe the RUN's method (ion ratio 50 % for 1633A; not
    judged for 537.1, which sets none);
  * the calibration ladder and CCV interval are read from one place each;
  * no module reads the moved qc_rules.json sections any more.
"""
from __future__ import unicode_literals

import ast
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)
sys.path.insert(0, ROOT)

import calibration_levels as cl            # noqa: E402
import config_forms as cf                  # noqa: E402
import method_profile_sections as mps      # noqa: E402
import qc_consolidation as qcc             # noqa: E402

PY3 = sys.version_info[0] >= 3


def _rules_module():
    """qc/rules.py with its one Zope-side import faked."""
    saved = dict((k, sys.modules.get(k)) for k in
                 ("senaite", "senaite.pfas", "senaite.pfas.analyte_reference"))
    ref = types.ModuleType(str("senaite.pfas.analyte_reference"))
    ref.get_method_ids = lambda: ["FDA_32PFAS", "EPA_537_1", "EPA_1633A"]
    pkg = types.ModuleType(str("senaite.pfas"))
    pkg.analyte_reference = ref
    sys.modules.update({"senaite": types.ModuleType(str("senaite")), "senaite.pfas": pkg,
                        "senaite.pfas.analyte_reference": ref})
    try:
        path = os.path.join(PKG, "qc", "rules.py")
        if PY3:
            import importlib.util
            spec = importlib.util.spec_from_file_location("qc_rules_under_test", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        import imp
        return imp.load_source(str("qc_rules_under_test"), path)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


RULES = _rules_module()

OLD_FILE = {
    "version": 1,
    "global": {"cal_r2_min": 0.995, "sn_quan_min": 10.0},
    "method_overrides": {"EPA_1633A": {"qq_ratio_matching_pct": 20.0}},
    "method_rule_toggles": {"EPA_537_1": {"cal_r2": False, "ion_ratio": True}},
    "qc_types": {"CAL": {"pct_deviation_max": 25, "chart_type": "levey_jennings", "label": "Cal"},
                 "ICV": {"pct_deviation_max": 20, "label": "ICV"},
                 "CCV": {"pct_deviation_max": 20, "pct_deviation_warn": 10, "label": "CCV"},
                 "LCS": {"recovery_min": 40, "recovery_max": 140},
                 "MB": {"threshold_units": "ng/mL", "chart_type": "threshold"}},
}


def test_dead_keys_go_and_lab_data_is_never_dropped():
    p = {"instrument_verification": {"sequence": {"ccv_frequency": 10}, "ccv": {"frequency": 10}},
         "extraction_corrections": {"salt_factors": []}, "spec_overrides": {}}
    assert qcc.drop_dead_keys(p, "X")
    assert p == {"instrument_verification": {"ccv": {"frequency": 10}}}
    assert not qcc.drop_dead_keys(p, "X")                                  # idempotent
    held = {"spec_overrides": {"LFSM": {"Eggs": {"PFOA": {"min": 60, "max": 140}}}},
            "extraction_corrections": {"salt_factors": [{"analyte": "PFOA", "factor": 0.96}]}}
    before = copy.deepcopy(held)
    assert not qcc.drop_dead_keys(held, "X") and held == before            # kept, reported


def test_switches_and_two_limits_move_in_once_and_complete():
    defaults = RULES.method_toggles({}, "EPA_537_1")
    p = {"instrument_verification": {"ccv": {"recovery_min": 70.0}}}
    assert qcc.move_from_rules(p, "EPA_537_1", OLD_FILE, defaults)
    tog = p["rule_toggles"]
    assert tog["cal_r2"] is False and tog["ion_ratio"] is True             # the lab's choice
    assert set(tog) >= set(r["key"] for r in RULES.RULE_LIBRARY)           # complete
    assert tog["sn_min"] is False                                          # 537.1 library default
    iv = p["instrument_verification"]
    assert iv["icv"]["pct_dev_max"] == 20.0 and iv["ccv"]["pct_dev_warn"] == 10.0
    assert "cal_r2_min" not in json.dumps(p) and "qq_ratio" not in json.dumps(p)   # D1: not copied
    before = copy.deepcopy(p)
    assert not qcc.move_from_rules(p, "EPA_537_1", OLD_FILE, defaults) and p == before
    kept = {"instrument_verification": {"icv": {"pct_dev_max": 15.0}}}
    qcc.move_from_rules(kept, "FDA_32PFAS", OLD_FILE, {})
    assert kept["instrument_verification"]["icv"]["pct_dev_max"] == 15.0   # never replaced


def test_the_rules_file_keeps_only_chart_presentation():
    saved = copy.deepcopy(OLD_FILE)
    assert RULES.strip_moved_sections(saved)
    assert set(saved) == {"version", "qc_types"}
    assert saved["qc_types"]["CAL"] == {"chart_type": "levey_jennings", "label": "Cal"}
    assert saved["qc_types"]["LCS"] == {} and saved["qc_types"]["MB"]["chart_type"] == "threshold"
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "qc_rules.json")
        store = RULES.QCRulesStore(path)
        store.save(copy.deepcopy(OLD_FILE), updated_by="t")          # e.g. reverting an old entry
        with open(path) as fh:
            on_disk = json.load(fh)
        assert "method_rule_toggles" not in on_disk and "global" not in on_disk
        assert "pct_deviation_max" not in json.dumps(on_disk)
        with open(path, "w") as fh:                                  # a hand-edited old file
            json.dump(OLD_FILE, fh)
        loaded = store.load()
        assert "method_rule_toggles" not in loaded and "method_overrides" not in loaded
        assert "pct_deviation_max" not in json.dumps(loaded["qc_types"])
    finally:
        shutil.rmtree(tmp)


def test_a_rule_is_a_switch_with_no_second_copy_of_its_limits():
    assert all(r.get("params") == [] for r in RULES.RULE_LIBRARY)
    assert RULES.method_toggles({"rule_toggles": {"cal_r2": False}}, "FDA_32PFAS")["cal_r2"] is False
    assert RULES.method_toggles({}, "FDA_32PFAS")["sn_min"] is False       # library default


def test_nothing_reads_the_moved_sections():
    """Only the migration and the rules store may name them."""
    allowed = {os.path.join(PKG, "qc", "rules.py"), os.path.join(PKG, "qc_consolidation.py")}
    moved = ("method_rule_toggles", "method_overrides")
    hits = []
    for base in (PKG, os.path.join(ROOT, "pfas_pipeline")):
        for dirpath, _d, files in os.walk(base):
            if "tests" in dirpath or "migrations" in dirpath:
                continue
            for name in files:
                if not name.endswith((".py", ".pt", ".js")):
                    continue
                path = os.path.join(dirpath, name)
                if path in allowed:
                    continue
                with io.open(path, encoding="utf-8") as fh:
                    text = fh.read()
                for key in moved:
                    # a READ names the key as a string: "key" or 'key'
                    if ('"%s"' % key) in text or ("'%s'" % key) in text:
                        hits.append((name, key))
                if name.endswith(".py") and ('get("global")' in text or "['global']" in text
                                              or '["global"]' in text):
                    hits.append((name, "global"))
    assert not hits, hits


def test_the_calibration_ladder_lives_only_on_the_profile():
    for base in (PKG, os.path.join(ROOT, "pfas_pipeline")):
        for dirpath, _d, files in os.walk(base):
            for name in files:
                if name.endswith(".py"):
                    with io.open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                        text = fh.read()
                    assert "CAL_LADDERS" not in text and "get_cal_ladder" not in text, name
    p = {"instrument_verification": {"calibration": {"level_unit": "ng/mL", "levels": [
        {"conc": 0.4}, {"conc": 0.2}, {"conc": 0.8}]}}}
    assert cl.calibrators(p) == [(1, 0.2), (2, 0.4), (3, 0.8)]
    with io.open(os.path.join(PKG, "browser", "run_builder.py"), encoding="utf-8") as fh:
        assert "cl.calibrators(self._profile(method_id))" in fh.read()


def test_an_unset_field_never_creates_a_block():
    stored = {"instrument_verification": {"ccv": {"frequency": 10, "recovery_min": 70.0,
                                                  "recovery_max": 130.0},
                                          "calibration": {"r2_min": 0.99}}}
    form = cf.form_values(mps.CALIBRATION_CCV, stored) if hasattr(cf, "form_values") else None
    updates = {("icv", "pct_dev_max"): None, ("ccv", "pct_dev_warn"): None}
    after = cf.apply(mps.CALIBRATION_CCV, stored, updates)
    assert "icv" not in after["instrument_verification"]
    assert "pct_dev_warn" not in after["instrument_verification"]["ccv"]      # nor a key
    after = cf.apply(mps.CALIBRATION_CCV, stored, {("icv", "pct_dev_max"): 20.0})
    assert after["instrument_verification"]["icv"] == {"pct_dev_max": 20.0}
    del form


def test_spec_ranges_compare_as_numbers():
    sys.path.insert(0, PKG)
    import spec_sync
    a = [{"keyword": "PFOA", "min": "70.0", "max": "130"}, {"keyword": "PFOS", "min": "65", "max": "135"}]
    b = [{"keyword": "PFOS", "min": 65.0, "max": 135.0}, {"keyword": "PFOA", "min": 70, "max": 130.0}]
    assert spec_sync.same_ranges(a, b)
    b[0]["max"] = 140
    assert not spec_sync.same_ranges(a, b)
    assert not spec_sync.same_ranges(a, a[:1])


def _worker():
    from pfas_pipeline import method_profiles as mp
    from pfas_pipeline import constants
    return mp, constants


def test_the_worker_judges_nothing_without_an_exported_profile():
    if not PY3:
        return
    mp, _c = _worker()
    assert all(v == {} for v in mp._DEFAULT_PROFILE_CACHE.values())          # no built-in criteria
    saved_cache, saved_loaded = copy.deepcopy(mp._profile_data_cache), set(mp._LOADED)
    tmp = tempfile.mkdtemp()
    try:
        mp.reload_from_profiles(os.path.join(tmp, "missing.json"))
        assert not mp.profile_configured("FDA_32PFAS")
        path = os.path.join(tmp, "method_profiles.json")
        with open(path, "w") as fh:
            json.dump({"EPA_537_1": {"instrument_verification": {}}}, fh)
        mp.reload_from_profiles(path)
        assert mp.profile_configured("EPA_537_1") and not mp.profile_configured("FDA_32PFAS")
        assert mp._profile_data_cache["FDA_32PFAS"] == {}
        from pfas_pipeline import pipeline as pl
        old_env = os.environ.get("PFAS_PROFILES_PATH")
        old_path = mp.PROFILES_PATH
        mp.PROFILES_PATH = path
        try:
            pl.run_pipeline(os.path.join(tmp, "none.csv"), output_dir=tmp, batch_id="B",
                            analyst="T", matrix="Eggs", method_id="FDA_32PFAS")
            assert False, "ran an unconfigured method"
        except RuntimeError as exc:
            assert "No exported method profile for FDA_32PFAS" in str(exc)
        finally:
            mp.PROFILES_PATH = old_path
            if old_env is not None:
                os.environ["PFAS_PROFILES_PATH"] = old_env
    finally:
        mp._profile_data_cache.clear()
        mp._profile_data_cache.update(saved_cache)
        mp._LOADED.clear()
        mp._LOADED.update(saved_loaded)
        shutil.rmtree(tmp)


def test_criteria_describe_the_runs_method():
    if not PY3:
        return
    mp, constants = _worker()
    from pfas_pipeline.qc_engine import qual_quan_check
    saved = dict(constants.CRITERIA)
    try:
        constants.set_criteria_from_profile({"instrument_verification": {"confirmation": {
            "ion_ratio_tol_pct": 50.0, "sn_quan_min": 3.0}}}, "EPA_1633A")
        assert constants.CRITERIA["ion_ratio_tol_pct"] == 50.0
        assert constants.CRITERIA_METHOD == ["EPA_1633A"]
        constants.set_criteria_from_profile({"instrument_verification": {"confirmation": {
            "ion_ratio_tol_pct": None, "sn_quan_min": 3.0}}}, "EPA_537_1")
        assert constants.CRITERIA["ion_ratio_tol_pct"] is None
        from datetime import datetime
        from pfas_pipeline.models import InstrumentRow
        row = InstrumentRow(
            compound_name="PFOA", compound_type="Target", compound_group="PFAS",
            sample_description="s", injection_name="261002-01", sample_group="G1",
            sample_type="Unknown", included_in_cal=False, level=None, linked_is=None,
            cal_ref_compound=None, observed_rt=5.0, rt_relative_to_is=1.0, response=1000.0,
            is_response=1000.0, response_ratio=1.0, expected_conc=None, calculated_conc=5.0,
            pct_deviation=None, pct_recovery_is=None, ion_ratios="0.90",
            expected_ion_ratios="0.50", r2=None, signal_to_noise=None, qual_sn=None,
            quant_status=None, reporting_limit=None, measured_conc=5.0,
            acquisition_datetime=datetime(2026, 10, 2, 10, 0, 0),
            concat_id="261002-01|20261002100000")
        assert qual_quan_check([row], "PFOA") == []                        # 537.1: not judged
        constants.set_criteria_from_profile({"instrument_verification": {"confirmation": {
            "ion_ratio_tol_pct": 30.0}}}, "FDA_32PFAS")
        assert any(r.flag for r in qual_quan_check([row], "PFOA"))         # 80 % off: flagged
        src = io.open(os.path.join(ROOT, "pfas_pipeline", "pipeline.py"), encoding="utf-8").read()
        body = src[src.index("    reload_from_profiles(batch_id=senaite_batch_id or None)"):]
        assert body.index("set_criteria_from_profile(") < body.index("csv_path = Path(csv_path)")
    finally:
        constants.CRITERIA.clear()
        constants.CRITERIA.update(saved)


def test_one_ccv_interval():
    if not PY3:
        return
    mp, _c = _worker()
    saved = copy.deepcopy(mp._profile_data_cache.get("EPA_537_1"))
    try:
        mp._profile_data_cache["EPA_537_1"] = {"instrument_verification": {
            "ccv": {"frequency": 7}, "sequence": {"ccv_frequency": 10}}}
        assert mp.get_profile("EPA_537_1").sequence_rule().ccv_frequency == 7
    finally:
        mp._profile_data_cache["EPA_537_1"] = saved


def test_the_worker_reads_switches_from_the_profile():
    if not PY3:
        return
    mp, _c = _worker()
    from pfas_pipeline import run_queue as rq
    saved = copy.deepcopy(mp._profile_data_cache.get("EPA_1633A"))
    try:
        mp._profile_data_cache["EPA_1633A"] = {"rule_toggles": {"sn_min": False}}
        assert rq._load_rule_toggles("EPA_1633A") == {"sn_min": False}
        assert rq._load_rule_toggles("1633A") == {"sn_min": False}            # alias
    finally:
        mp._profile_data_cache["EPA_1633A"] = saved


def test_startup_creates_reference_definitions_with_the_right_call():
    """setuphandlers called _get_or_create_ref_def(folder, title, ...) after
    the signature became (folder, code, title, ...): every code failed."""
    with io.open(os.path.join(PKG, "browser", "setuprefs.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read().encode("utf-8"))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == "_get_or_create_ref_def"][0]
    positional = len(fn.args.args) - len(fn.args.defaults)
    with io.open(os.path.join(PKG, "setuphandlers.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read().encode("utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_get_or_create_ref_def"]
    assert calls and all(len(c.args) >= positional for c in calls), positional


def test_the_calibrations_page_reads_the_profile():
    with io.open(os.path.join(PKG, "browser", "calibrations.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "get_rules" not in src
    assert 'get("qc_types"' not in src and '["qc_types"]' not in src
    tree = ast.parse(src.encode("utf-8"))
    names = set(n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    assert {"method_limits", "r2_minimum", "cal_pct_max", "qc_type_limits"} <= names


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
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
