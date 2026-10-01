# -*- coding: utf-8 -*-
"""Every switch changes something (DECISIONS 2026-10-01, GAPS §74).

Run-level tests (a synthetic batch through RunQueue.auto_evaluate) for each
switch that used to change nothing: the check fires when ON, is silent when
OFF, and -- where it needs an RL, an MDL or a spike -- reports "not
evaluated" instead of passing. Plus the pure checks and the store migration.
"""
from __future__ import print_function

import copy
import io
import json
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "senaite", "pfas"))
os.environ.setdefault("PFAS_PROFILES_PATH", os.path.join(ROOT, "data", "qc", "method_profiles.json"))
os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")

from pfas_pipeline import method_profiles as mp                 # noqa: E402
from pfas_pipeline import run_queue as rq                       # noqa: E402
from pfas_pipeline.models import Batch, InstrumentRow           # noqa: E402
from pfas_pipeline.injection_builder import REVIEW_CHECKS       # noqa: E402
from pfas_pipeline.qc_engine import (                           # noqa: E402
    ccv_frequency_check, KIND_BLANK, KIND_LCS, KIND_CCV_FREQ, KIND_MDL, KIND_SURROGATE, KIND_DUP)

mp.reload_from_profiles()
MID, MATRIX = "EPA_537_1", "Drinking Water"
T0 = datetime(2026, 10, 1, 8, 0, 0)


def _profile():
    import labelled_standards
    import low_level_tiers
    with open(os.environ["PFAS_PROFILES_PATH"]) as fh:
        data = json.load(fh)
    p = copy.deepcopy(data.get("profiles", data)[MID])
    p["method_id"] = MID
    from pfas_pipeline.analyte_alias import injection_is_names
    labelled_standards.migrate(p, sorted(injection_is_names()))
    low_level_tiers.seed_537_1(p)
    qca = p.setdefault("qc_acceptance", {})
    qca.setdefault("LRB", {"enabled": True, "tiers": [{"name": "default", "analyte_group": "all",
                                                      "matrix_scope": "all", "max_conc_x_rl": 1.0}]})
    qca["LRB"]["enabled"] = True
    p["unit_map"] = dict(p.get("unit_map") or {}, **{MATRIX: "ng/L"})
    p["reporting_limits"] = {MATRIX: {"PFOA": {"rl": 4.0, "mdl": 1.0}}}
    p.setdefault("instrument_verification", {}).setdefault("ccv", {})["frequency"] = 3
    sl = p.setdefault("spike_levels", {}).setdefault(MATRIX, {})
    sl["LFB"] = [{"label": "Mid", "ppt": 40.0}]
    return p


def _row(compound, injection, i, conc=None, units="ng/L", recovery=None, ctype="Target"):
    return InstrumentRow(
        compound_name=compound, compound_type=ctype, compound_group=ctype,
        sample_description=injection, injection_name=injection,
        sample_group="G1", sample_type="Unknown", included_in_cal=False,
        level=None, linked_is=None, cal_ref_compound=None, observed_rt=5.0,
        rt_relative_to_is=1.0, response=1000.0, is_response=1000.0,
        response_ratio=1.0, expected_conc=None, calculated_conc=conc,
        pct_deviation=None, pct_recovery_is=recovery, ion_ratios=None,
        expected_ion_ratios=None, r2=None, signal_to_noise=None, qual_sn=None,
        quant_status=None, reporting_limit=None, measured_conc=None,
        acquisition_datetime=T0 + timedelta(minutes=i), conc_units=units,
        concat_id="{0}|{1}".format(injection, i))


def _run(rows, profile, toggles=None, matrix=MATRIX):
    old_cache, old_tog = mp._profile_data_cache.get(MID), rq._load_rule_toggles
    mp._profile_data_cache[MID] = profile
    rq._load_rule_toggles = lambda mid, *a, **k: dict(toggles or {})
    try:
        plan, seen = [], []
        for r in rows:
            if r.injection_name in seen:
                continue
            seen.append(r.injection_name)
            role = rq.classify_injection(r.injection_name, {})
            plan.append({"injection_name": r.injection_name, "qc_type": role,
                         "checks": list(REVIEW_CHECKS.get(role, REVIEW_CHECKS["Sample"]))})
        batch = Batch(batch_id="B-SW", analyst="RT", date=T0, matrix=matrix, method_id=MID,
                      instrument_file="synthetic.csv", injections=rows)
        q = rq.RunQueue(batch, plan, method_id=MID)
        q.auto_evaluate()
        return q, batch
    finally:
        mp._profile_data_cache[MID] = old_cache
        rq._load_rule_toggles = old_tog


def _flags(batch, kind):
    return [f for f in batch.qc_flags if getattr(f, "check_kind", "") == kind]


def _check(q, inj, name):
    return next(c for c in q.checks if c.injection_name == inj and c.check_name == name)


def _gaps(batch, word):
    return [g for g in getattr(batch, "unconfigured", []) if word in g.get("reason", "")]


# ── pure ─────────────────────────────────────────────────────────────────────

def test_ccv_frequency_counts_the_bracketed_body_only():
    seq = [("MeOH blank MB", "MB"), ("CAL-1", "CAL"), ("CCV 1", "CCV"), ("ICV", "ICV"),
           ("S1", "Sample"), ("LRB", "LRB"), ("S2", "Sample"), ("CCV 2", "CCV"),
           ("S3", "Sample"), ("S4", "Sample"), ("S5", "Sample"), ("S6", "Sample"), ("CCV 3", "CCV")]
    flags = ccv_frequency_check(seq, 3)
    assert [f.injection_name for f in flags] == ["S6"], [f.injection_name for f in flags]
    open_end = ccv_frequency_check(seq[:-1], 3)          # no closing CCV
    assert set(f.injection_name for f in open_end) == {"S3", "S4", "S5", "S6"}


# ── run level ────────────────────────────────────────────────────────────────

def test_a_blank_above_its_limit_fails_and_below_passes():
    p = _profile()
    q, b = _run([_row("PFOA", "LRB 1", 1, conc=5.0)], p)
    assert _flags(b, KIND_BLANK) and _check(q, "LRB 1", "blank_contamination").status.name == "AUTO_FAIL"
    q, b = _run([_row("PFOA", "LRB 1", 1, conc=3.0)], p)
    assert not _flags(b, KIND_BLANK) and _check(q, "LRB 1", "blank_contamination").status.name == "AUTO_PASS"


def test_a_blank_without_an_rl_is_not_evaluated_and_a_disabled_type_is_not_run():
    p = _profile()
    p["reporting_limits"] = {}
    q, b = _run([_row("PFOA", "LRB 1", 1, conc=50.0)], p)
    assert not _flags(b, KIND_BLANK) and _gaps(b, "no RL")
    assert _check(q, "LRB 1", "blank_contamination").status.name == "PENDING"
    p = _profile()
    p["qc_acceptance"]["LRB"]["enabled"] = False         # the QC Types switch
    q, b = _run([_row("PFOA", "LRB 1", 1, conc=50.0)], p)
    assert not _flags(b, KIND_BLANK)


def test_lfb_recovery_uses_the_spike_grid_and_the_level_window():
    p = _profile()                                       # LFB Mid = 40 ppt, RL 4: ordinary 70-130
    q, b = _run([_row("PFOA", "Batch 7; LFB Mid", 1, conc=20.0)], p)
    assert _flags(b, KIND_LCS) and _check(q, "Batch 7; LFB Mid", "recovery").status.name == "AUTO_FAIL"
    q, b = _run([_row("PFOA", "Batch 7; LFB Mid", 1, conc=36.0)], p)
    assert not _flags(b, KIND_LCS) and _check(q, "Batch 7; LFB Mid", "recovery").status.name == "AUTO_PASS"
    p["spike_levels"][MATRIX]["LFB"] = [{"label": "Mid", "ppt": 6.0}]   # <= 2 x RL: low level 50-150
    q, b = _run([_row("PFOA", "Batch 7; LFB Mid", 1, conc=3.6)], p)     # 60%
    assert not _flags(b, KIND_LCS)
    p["spike_levels"][MATRIX]["LFB"] = [{"label": "Mid", "ppt": None}]
    q, b = _run([_row("PFOA", "Batch 7; LFB Mid", 1, conc=36.0)], p)
    assert not _flags(b, KIND_LCS) and _gaps(b, "spike concentration")
    assert _check(q, "Batch 7; LFB Mid", "recovery").status.name == "PENDING"


def test_ccv_frequency_switch():
    p = _profile()
    rows = [_row("PFOA", n, i, conc=1.0) for i, n in enumerate(
        ["CCV 1", "S1", "S2", "S3", "S4", "CCV 2"])]
    _q, b = _run(rows, p)
    assert [f.injection_name for f in _flags(b, KIND_CCV_FREQ)] == ["S4"]
    _q, b = _run(rows, p, {"ccv_frequency": False})
    assert not _flags(b, KIND_CCV_FREQ)


def test_mdl_switch():
    p = _profile()
    rows = [_row("PFOA", "Client sample A", 1, conc=0.5)]
    _q, b = _run(rows, p)
    assert _flags(b, KIND_MDL)
    _q, b = _run(rows, p, {"mdl_check": False})
    assert not _flags(b, KIND_MDL)
    p["reporting_limits"][MATRIX]["PFOA"].pop("mdl")
    _q, b = _run(rows, p)
    assert not _flags(b, KIND_MDL) and _gaps(b, "no MDL")


def test_surrogate_switch():
    p = _profile()
    old = mp._profile_data_cache.get(MID)
    mp._profile_data_cache[MID] = p
    try:
        injection = set(mp.get_injection_standards(MID))
        sur = next(s for s in mp.get_is_list(MID) if s not in injection)
    finally:
        mp._profile_data_cache[MID] = old
    rows = [_row(sur, "Client sample A", 1, recovery=20.0, ctype="IS")]
    _q, b = _run(rows, p)
    assert _flags(b, KIND_SURROGATE), "the surrogate check did not run"
    _q, b = _run(rows, p, {"surrogate_recovery": False})
    assert not _flags(b, KIND_SURROGATE)


def test_duplicate_rpd_both_detected_one_detected_and_none():
    p = _profile()                                       # RL 4; Dup 30%, low tier 50% at <= 2 x RL
    pair = lambda c1, c2: [_row("PFOA", "Client sample A", 1, conc=c1),            # noqa: E731
                           _row("PFOA", "Client sample A Dup.", 2, conc=c2)]
    q, b = _run(pair(20.0, 30.0), p)                     # RPD 40% at a mean of 25 (> 8): fails 30%
    assert _flags(b, KIND_DUP) and _check(q, "Client sample A Dup.", "duplicate_rpd").status.name == "AUTO_FAIL"
    q, b = _run(pair(20.0, 22.0), p)                     # RPD 9.5%
    assert not _flags(b, KIND_DUP) and _check(q, "Client sample A Dup.", "duplicate_rpd").status.name == "AUTO_PASS"
    q, b = _run(pair(5.0, 7.5), p)                       # RPD 40% at a mean of 6.25 (<= 8): low tier 50%
    assert not _flags(b, KIND_DUP)
    q, b = _run(pair(20.0, 2.0), p)                      # one below the RL
    fl = _flags(b, KIND_DUP)
    assert fl and "one of the pair only" in fl[0].issue
    q, b = _run(pair(1.0, None), p)                      # both below the RL: nothing to judge
    assert not _flags(b, KIND_DUP) and _check(q, "Client sample A Dup.", "duplicate_rpd").status.name == "PENDING"


def test_duplicate_pairs_by_the_extraction_record_first():
    p = _profile()
    rows = [_row("PFOA", "KCP Silage 7", 1, conc=20.0), _row("PFOA", "Field Dup 3", 2, conc=30.0)]
    # the name "Field Dup 3" does not name its parent; the extraction record does
    old = rq.classify_injection
    rq.classify_injection = lambda n, d=None: "Dup" if n == "Field Dup 3" else old(n, d)
    try:
        def run_with(spikes):
            mp._profile_data_cache[MID], keep = p, mp._profile_data_cache.get(MID)
            tog, rq._load_rule_toggles = rq._load_rule_toggles, (lambda mid, *a, **k: {})
            try:
                plan = [{"injection_name": n, "qc_type": rq.classify_injection(n, {}),
                         "checks": list(REVIEW_CHECKS.get(rq.classify_injection(n, {}), REVIEW_CHECKS["Sample"]))}
                        for n in ("KCP Silage 7", "Field Dup 3")]
                batch = Batch(batch_id="B-SW", analyst="RT", date=T0, matrix=MATRIX, method_id=MID,
                              instrument_file="synthetic.csv", injections=rows)
                batch.spikes = spikes
                rq.RunQueue(batch, plan, method_id=MID).auto_evaluate()
                return batch
            finally:
                mp._profile_data_cache[MID] = keep
                rq._load_rule_toggles = tog
        b = run_with({})
        assert not _flags(b, KIND_DUP) and _gaps(b, "no sample to pair")
        b = run_with({"Field Dup 3": {"parent": "KCP Silage 7"}})
        assert _flags(b, KIND_DUP)                       # RPD 40% judged against the record's parent
    finally:
        rq.classify_injection = old


def test_the_dup_parent_name_fallback():
    for name, parent in (("KCP Silage A Dup.", "KCP Silage A"), ("Lot 7; Duplicate", "Lot 7"),
                         ("Lot 7 dup", "Lot 7"), ("Lot 7", "")):
        assert rq._dup_parent_name(name) == parent, (name, rq._dup_parent_name(name))


# ── store and screens ────────────────────────────────────────────────────────

def test_the_store_migration_removes_dead_switches_and_retired_parameters():
    import ast
    path = os.path.join(ROOT, "src", "senaite", "pfas", "qc", "rules.py")
    with io.open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == "migrate_rule_store")
            or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "").startswith("RETIRED_"))]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), ns)   # rules.py needs Zope
    migrate_rule_store, RETIRED_TOGGLES = ns["migrate_rule_store"], ns["RETIRED_TOGGLES"]
    rules = {"method_rule_toggles": {MID: {"mb_blank": True, "lfsm_recovery": True, "cal_r2": False}},
             "method_overrides": {MID: {"ccv_frequency_n": 10, "mdl_n_min": 7, "sn_min": 3.0}},
             "global": {"ccv_frequency_n": 10, "cal_r2_min": 0.99}}
    assert migrate_rule_store(rules)
    assert rules["method_rule_toggles"][MID] == {"cal_r2": False}
    assert rules["method_overrides"][MID] == {"sn_min": 3.0} and rules["global"] == {"cal_r2_min": 0.99}
    assert not migrate_rule_store(rules)
    assert "lfsm_recovery" in RETIRED_TOGGLES


def test_the_qc_type_switch_is_one_form_field_in_two_tabs():
    with io.open(os.path.join(ROOT, "src", "senaite", "pfas", "browser", "templates",
                              "method_profile_edit.pt"), encoding="utf-8") as fh:
        tpl = fh.read()
    assert tpl.count("name string:qc_enabled_${q/key}") == 2, "QC Types and Rule Toggles must share the field"
    assert 'name^="qc_enabled_"' in tpl                       # kept in step


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
