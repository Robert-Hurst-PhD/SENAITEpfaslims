# -*- coding: utf-8 -*-
"""The settings report (DECISIONS 2026-10-01) states how the pipeline applies
each criterion. Those statements are about the CODE, so they are pinned here:
a switch the report calls "read" must be read by the pipeline, a criterion
called "judged" must have a check there and one called "not judged" must not.
Plus: every declared section reaches the report. Real modules, no Zope."""
from __future__ import unicode_literals

import copy
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)

import method_profile_sections as mps   # noqa: E402
import settings_report as sr            # noqa: E402

PIPE = os.path.join(ROOT, "pfas_pipeline")


def _code(name):
    """A pipeline file without comments and docstrings' comment lines."""
    with io.open(os.path.join(PIPE, name), encoding="utf-8") as fh:
        return "\n".join(l for l in fh.read().splitlines() if not l.strip().startswith("#"))


def _profiles():
    path = os.environ.get("PFAS_PROFILES_PATH") or os.path.join(ROOT, "data", "qc", "method_profiles.json")
    with open(path) as fh:
        data = json.load(fh)
    return data.get("profiles", data)


def test_the_switches_called_read_are_exactly_the_ones_the_pipeline_reads():
    read = set()
    for name in os.listdir(PIPE):
        if name.endswith(".py"):
            read |= set(re.findall(r'_rule_enabled\([^,]+,\s*"([a-z0-9_]+)"', _code(name)))
            read |= set(re.findall(r'_rule_enabled\(_load_rule_toggles\([^)]*\),\s*"([a-z0-9_]+)"', _code(name)))
    assert read == set(sr.CONSUMED_TOGGLES), (sorted(read), sorted(sr.CONSUMED_TOGGLES))


def test_what_the_report_calls_judged_has_a_check_and_the_rest_do_not():
    engine, queue = _code("qc_engine.py"), _code("run_queue.py")
    kinds = dict(re.findall(r'^(KIND_[A-Z_]+)\s*=\s*"([a-z_]+)"', engine, re.M))
    used = set(kinds[k] for k in re.findall(r"check_kind=(KIND_[A-Z_]+)", queue + engine) if k in kinds)
    judged_types = set(re.findall(r'(?:recovery|rpd)_check_profiled\(\s*profile,\s*\w+,\s*\w+,\s*"(\w+)"', queue))
    judged_types |= set(re.findall(r'qc_rules\(\w+,\s*\w+,\s*"(\w+)"\)', queue))
    for code, _c, evaluated, _how, kind in sr.QC_APPLICATION:
        if evaluated:
            assert kind in used, (code, kind)
        else:
            assert kind is None and code not in judged_types, (code, sorted(judged_types))
    for _check, _c, evaluated, _how, kind, switch in sr.INSTRUMENT_APPLICATION:
        assert evaluated and kind in used, kind
        assert switch in sr.CONSUMED_TOGGLES, switch


def test_every_declared_section_reaches_the_report():
    order = sr._section_order()
    assert set(mps.SECTIONS) <= set(order)
    for mid, p in _profiles().items():
        p = dict(p, method_id=mid)
        rep = sr.method_report(p, {}, {"cal_r2": True, "mb_blank": False})
        titles = [s["title"] for s in rep["sections"]]
        assert "Calibration & CCV" in titles and "Recovery tiers" in titles, (mid, titles)
        assert [q["code"] for q in rep["qc"]][0] == "LFSM"
        assert "SUR" in [q["code"] for q in rep["qc"]]          # runs for every method
        assert [s for s in rep["switches"] if s["key"] == "mb_blank" and not s["read"]]


def test_a_stored_value_appears_and_blank_rows_do_not():
    p = copy.deepcopy(_profiles()["EPA_537_1"])
    p["reporting_limits"] = {"Drinking Water": {"PFOA": {"rl": 4.0}}}
    dump = sr.section_dump(mps.REPORTING_LIMITS, p)
    assert dump["rows"] == [["Drinking Water — PFOA", "4", ""]], dump["rows"]


def test_the_fingerprint_moves_with_any_setting():
    a = _profiles()
    b = copy.deepcopy(a)
    b["EPA_537_1"]["qc_acceptance"]["Dup"]["tiers"][0]["rpd_max"] = 31.0
    assert sr.fingerprint(a, {}) == sr.fingerprint(copy.deepcopy(a), {})
    assert sr.fingerprint(a, {}) != sr.fingerprint(b, {})


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
