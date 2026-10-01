# -*- coding: utf-8 -*-
"""Low-level QC tiers (DECISIONS 2026-10-01; EPA 537.1 v2.0 §9.3.3, §9.3.6.3,
§9.3.7.4).

A tier with low_level_x_rl = N replaces the ordinary tier when the spike is
at or below N x RL. What must hold: no low-level tier = nothing changes; the
engine picks the low-level window only at a low spike, and refuses without
the spike or the RL; the editor's mirror (grid, departures) picks what the
engine picks; the 537.1 seed fixes LFB being judged at 50-150% throughout;
the editor round-trips the tiers. Real modules, no Zope.
"""
from __future__ import unicode_literals

import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, ROOT)
sys.path.insert(0, PKG)

import config_forms as cf                 # noqa: E402
import config_history as ch               # noqa: E402
import low_level_tiers as llt             # noqa: E402
import method_profile_sections as mps     # noqa: E402

PY3 = sys.version_info[0] >= 3


def _profiles():
    path = os.environ.get("PFAS_PROFILES_PATH") or os.path.join(ROOT, "data", "qc", "method_profiles.json")
    with open(path) as fh:
        data = json.load(fh)
    return data.get("profiles", data)


PROFILES = _profiles()


def _seeded(mid="EPA_537_1"):
    p = copy.deepcopy(PROFILES[mid])
    p["method_id"] = mid
    llt.seed_537_1(p)
    return p


def _engine(mid, profile):
    """(get_profile, restore) with `profile` in the pipeline's cache."""
    from pfas_pipeline import method_profiles as mp
    old = mp._profile_data_cache.get(mid)
    mp._profile_data_cache[mid] = profile

    def restore():
        if old is None:
            mp._profile_data_cache.pop(mid, None)
        else:
            mp._profile_data_cache[mid] = old
    return mp.get_profile(mid), restore


def test_the_seed_follows_the_method_text_and_is_idempotent():
    p = _seeded()
    qca = p["qc_acceptance"]
    lows = dict((qc, [t for t in qca[qc]["tiers"] if t.get("low_level_x_rl")]) for qc in ("LFSM", "LFSMD", "LFB"))
    assert [(t["low_level_x_rl"], t["recovery_min"], t["recovery_max"]) for t in lows["LFSM"]] == [(2.0, 50.0, 150.0)]
    assert [(t["low_level_x_rl"], t["rpd_max"]) for t in lows["LFSMD"]] == [(2.0, 50.0)]
    assert [(t["low_level_x_rl"], t["recovery_min"]) for t in lows["LFB"]] == [(2.0, 50.0)]
    assert all("§9.3" in t["citation"] for v in lows.values() for t in v)
    before = copy.deepcopy(p)
    assert not llt.seed_537_1(p) and p == before
    removed = copy.deepcopy(p)                       # the lab deletes one on purpose
    removed["qc_acceptance"]["LFSM"]["tiers"] = [t for t in removed["qc_acceptance"]["LFSM"]["tiers"]
                                                if not t.get("low_level_x_rl")]
    assert not llt.seed_537_1(removed)               # ... it stays deleted
    other = copy.deepcopy(PROFILES["FDA_32PFAS"])
    other["method_id"] = "FDA_32PFAS"
    assert not llt.seed_537_1(other)


def test_no_low_level_tier_changes_nothing():
    if not PY3:
        return
    for mid, p in PROFILES.items():
        if mid == "EPA_537_1":
            continue
        prof, restore = _engine(mid, copy.deepcopy(p))
        try:
            for kw in (p.get("master_analyte_set") or [])[:6]:
                for m in p.get("supported_matrices") or []:
                    a = prof.qc_rules(kw, m, "LFSM")
                    b = prof.qc_rules(kw, m, "LFSM", conc=1.0, rl=1.0)
                    assert (a.recovery_min, a.recovery_max) == (b.recovery_min, b.recovery_max)
        finally:
            restore()


def test_the_engine_picks_the_low_window_only_at_a_low_spike():
    if not PY3:
        return
    from pfas_pipeline.method_profiles import UnconfiguredCriterion
    prof, restore = _engine("EPA_537_1", _seeded())
    try:
        win = lambda qc, conc: (lambda r: (r.recovery_min, r.recovery_max, r.rpd_max))(  # noqa: E731
            prof.qc_rules("PFOA", "Drinking Water", qc, conc=conc, rl=4.0))
        assert win("LFSM", 8.0)[:2] == (50.0, 150.0)          # exactly 2 x RL: low level
        assert win("LFSM", 8.1)[:2] == (70.0, 130.0)          # above: ordinary
        assert win("LFB", 4.0)[:2] == (50.0, 150.0)
        assert win("LFB", 40.0)[:2] == (70.0, 130.0)          # was 50-150 for every LFB
        assert win("LFSMD", 6.0)[2] == 50.0 and win("LFSMD", 60.0)[2] == 30.0
        for conc, rl in ((None, 4.0), (8.0, None)):
            try:
                prof.qc_rules("PFOA", "Drinking Water", "LFSM", conc=conc, rl=rl)
                assert False, "guessed a window without %s" % ("conc" if conc is None else "RL")
            except UnconfiguredCriterion as exc:
                assert "does not guess" in str(exc)
    finally:
        restore()


def test_grouped_tiers_honour_the_low_tiers_group():
    if not PY3:
        return
    p = copy.deepcopy(PROFILES["FDA_32PFAS"])
    p["method_id"] = "FDA_32PFAS"
    p["qc_acceptance"]["LFSM"]["tiers"].append(
        {"name": "low_no_std", "analyte_group": "no_std", "matrix_scope": "all",
         "low_level_x_rl": 2.0, "recovery_min": 30.0, "recovery_max": 150.0})
    prof, restore = _engine("FDA_32PFAS", p)
    try:
        assert prof.qc_rules("PFTrDA", "Eggs", "LFSM", conc=1.0, rl=1.0).recovery_min == 30.0   # no-std
        assert prof.qc_rules("PFOA", "Eggs", "LFSM", conc=1.0, rl=1.0).recovery_min == 80.0     # key: untouched
    finally:
        restore()


def test_the_editor_mirror_picks_what_the_engine_picks():
    """The grid and the project departures read resolve_tier/low_level_tier;
    they must choose the engine's tier at a low and a high spike."""
    if not PY3:
        return
    import analyte_reference as ar
    display = dict((r[0], r[1]) for r in ar.NATIVE_ANALYTES)
    no_std = dict((r[0], bool(r[7])) for r in ar.NATIVE_ANALYTES)
    fda = copy.deepcopy(PROFILES["FDA_32PFAS"])
    fda["method_id"] = "FDA_32PFAS"
    fda["qc_acceptance"]["LFSM"]["tiers"] += [
        {"name": "low_all", "analyte_group": "all", "matrix_scope": "all",
         "low_level_x_rl": 3.0, "recovery_min": 45.0, "recovery_max": 155.0},
        {"name": "low_no_std", "analyte_group": "no_std", "matrix_scope": "all",
         "low_level_x_rl": 2.0, "recovery_min": 30.0, "recovery_max": 160.0},
        {"name": "low_key_tight", "analyte_group": "key", "matrix_scope": "tight",
         "low_level_x_rl": 2.0, "recovery_min": 75.0, "recovery_max": 125.0}]
    checked = 0
    for mid, p in (("EPA_537_1", _seeded()), ("FDA_32PFAS", fda)):
        prof, restore = _engine(mid, p)
        try:
            keys = mps.key_analytes(p)
            for kw in p.get("master_analyte_set") or []:
                for m in p.get("supported_matrices") or []:
                    for qc in ("LFSM", "LFSMD"):
                        base = mps.resolve_tier(p, kw in keys, no_std.get(kw, False), m, qc)
                        lows = mps.low_level_tier(p, base, m, qc)
                        for conc in (1.0, 100.0):
                            want = next((t for t in lows if conc <= t["low_level_x_rl"]), base)
                            rule = prof.qc_rules(display.get(kw, kw), m, qc, conc=conc, rl=1.0)
                            got = (rule.recovery_min, rule.recovery_max, rule.rpd_max) if rule else None
                            exp = (want.get("recovery_min"), want.get("recovery_max"),
                                   want.get("rpd_max")) if want else None
                            assert got == exp, (mid, kw, m, qc, conc, got, exp)
                            checked += 1
        finally:
            restore()
    assert checked > 500, checked


def test_rl_is_converted_to_the_spike_unit():
    if not PY3:
        return
    p = _seeded()
    p["reporting_limits"] = {"Drinking Water": {"PFOA": {"rl": 4.0}}}
    p["unit_map"] = dict(p.get("unit_map") or {}, **{"Drinking Water": "ng/L", "Groundwater": "ug/L"})
    p["reporting_limits"]["Groundwater"] = {"PFOA": {"rl": 0.004}}
    prof, restore = _engine("EPA_537_1", p)
    try:
        assert prof.reporting_limit_ppt("PFOA", "Drinking Water") == 4.0
        assert abs(prof.reporting_limit_ppt("PFOA", "Groundwater") - 4.0) < 1e-9
        assert prof.reporting_limit_ppt("PFNA", "Drinking Water") is None
    finally:
        restore()


def test_the_editor_round_trips_and_checks_the_tiers():
    p = _seeded()
    for coll in (mps.RECOVERY_TIERS, mps.LFB_TIERS, mps.LFSMD_RPD):
        form = {}
        for row in cf.render(coll, p):
            for cell in row["cells"]:
                form[cell["name"]] = cell["value"]
        rows, errors = cf.parse(coll, form, p)
        assert not errors, (coll.id, errors)
        assert ch.diff(p, cf.apply(coll, p, rows)) == [], (coll.id, ch.diff(p, cf.apply(coll, p, rows))[:3])
    rows = mps.RECOVERY_TIERS.read(p)
    assert mps.check_tiers(p, rows) == []                       # one ordinary + one low-level: fine
    extra = rows + [dict(rows[0], name="second")]
    assert any("FIRST ordinary" in e for e in mps.check_tiers(p, extra))
    bare = [dict(r, recovery_min=None, recovery_max=None) if r.get("low_level_x_rl") else r for r in rows]
    assert any("needs its recovery window" in e for e in mps.check_tiers(p, bare))
    assert any("ordinary tier" in e for e in mps.check_tiers(p, [r for r in rows if r.get("low_level_x_rl")]))


def test_a_project_widening_a_low_window_is_a_departure():
    import project_specs as ps
    p = _seeded()
    eff = copy.deepcopy(p)
    [t for t in eff["qc_acceptance"]["LFSM"]["tiers"] if t.get("low_level_x_rl")][0]["recovery_min"] = 40.0
    deps = ps.departures(p, eff, "EPA_537_1")
    assert [d for d in deps if "low-level tier low_level" in d["what"] and d["project"] == "40"], deps
    tight = copy.deepcopy(p)
    [t for t in tight["qc_acceptance"]["LFSM"]["tiers"] if t.get("low_level_x_rl")][0]["recovery_min"] = 60.0
    assert not [d for d in ps.departures(p, tight, "EPA_537_1") if "low-level" in d["what"]]


def test_a_refusal_is_recorded_not_raised_in_the_run():
    """Each LFSM / LFSMD check that can now refuse sits in a try that records
    the gap -- an unguarded refusal would abort the whole batch's QC."""
    import io
    with io.open(os.path.join(ROOT, "pfas_pipeline", "run_queue.py"), encoding="utf-8") as fh:
        src = fh.read()
    for call in ('"LFSM",\n', '"LFSMD", rpd_pct'):
        i = src.index(call)
        before, after = src[max(0, i - 300):i], src[i:i + 500]
        assert re.search(r"try:\s*\n\s*raw_flag = (recovery|rpd)_check_profiled\($", before.rstrip()[-120:] + "(", re.M) \
            or "try:" in before[-200:], call
        assert "except UnconfiguredCriterion" in after and "_record_gap" in after, call


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
