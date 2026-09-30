# -*- coding: utf-8 -*-
"""Configuration change history (R1, docs/CONFIG_ARCHITECTURE_REVIEW.md).

The pure half of config_history: the diff that becomes an entry, the revert
that puts an entry back, and the conflict check that refuses a revert when a
later change touched the same paths. Runs the real module (no Zope).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src", "senaite", "pfas"))

import config_history as ch   # noqa: E402

BEFORE = {"method_id": "EPA_537_1", "updated_at": "t1", "_seeded": True,
          "qc_acceptance": {"LFSM": {"tiers": [
              {"name": "default", "analyte_group": "all", "recovery_min": 70, "recovery_max": 130}]}},
          "unit_map": {"Drinking Water": "ng/L"},
          "holding_times": {"Drinking Water": 14},
          "required_logbooks": ["250", "252"],
          "notes": ""}


def _after(**edits):
    import copy
    a = copy.deepcopy(BEFORE)
    for path, value in edits.items():
        node = a
        keys = path.split("/")
        for k in keys[:-1]:
            node = node[int(k)] if isinstance(node, list) else node[k]
        last = keys[-1]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return a


def test_a_nested_edit_is_one_precise_change():
    after = _after(**{"qc_acceptance/LFSM/tiers/0/recovery_max": 131})
    assert ch.diff(BEFORE, after) == [
        (("qc_acceptance", "LFSM", "tiers", 0, "recovery_max"), 130, 131)]


def test_no_change_records_nothing():
    assert ch.diff(BEFORE, dict(BEFORE)) == []


def test_ignored_and_shape_only_differences_record_nothing():
    after = _after(updated_at="t2", _seeded=None)
    after["matrix_uid_map"] = {"Drinking Water": "abc"}
    after["notes"] = None                         # "" -> None: shape only
    after["reporting_limits"] = {}                # missing -> {}: shape only
    assert ch.diff(BEFORE, after) == []


def test_clearing_a_value_is_a_change():
    after = _after(**{"holding_times/Drinking Water": None})
    assert ch.diff(BEFORE, after) == [(("holding_times", "Drinking Water"), 14, None)]


def test_a_list_that_changes_length_is_one_change():
    after = _after(required_logbooks=["250", "252", "251"])
    assert ch.diff(BEFORE, after) == [(("required_logbooks",), ["250", "252"], ["250", "252", "251"])]


def _entry(before, after):
    return [{"path": list(p), "before": b, "after": a} for p, b, a in ch.diff(before, after)]


def test_revert_puts_the_before_values_back():
    after = _after(**{"qc_acceptance/LFSM/tiers/0/recovery_max": 131,
                      "holding_times/Drinking Water": 28})
    changes = _entry(BEFORE, after)
    assert ch.revert_conflicts(after, changes) == []
    assert ch.diff(BEFORE, ch.reverted(after, changes)) == []


def test_revert_removes_a_key_the_change_added():
    after = _after()
    after["holding_times"]["Groundwater"] = 14
    back = ch.reverted(after, _entry(BEFORE, after))
    assert "Groundwater" not in back["holding_times"]


def test_a_later_change_to_the_same_path_blocks_the_revert():
    first = _after(**{"qc_acceptance/LFSM/tiers/0/recovery_max": 131})
    changes = _entry(BEFORE, first)
    later = _after(**{"qc_acceptance/LFSM/tiers/0/recovery_max": 125})
    assert ch.revert_conflicts(later, changes) == [("qc_acceptance", "LFSM", "tiers", 0, "recovery_max")]


def test_a_later_change_elsewhere_does_not_block():
    first = _after(**{"qc_acceptance/LFSM/tiers/0/recovery_max": 131})
    changes = _entry(BEFORE, first)
    later = _after(**{"qc_acceptance/LFSM/tiers/0/recovery_max": 131,
                      "holding_times/Drinking Water": 21})
    assert ch.revert_conflicts(later, changes) == []
    back = ch.reverted(later, changes)
    assert back["holding_times"]["Drinking Water"] == 21          # the later edit survives
    assert back["qc_acceptance"]["LFSM"]["tiers"][0]["recovery_max"] == 130


def test_fingerprint_is_stable_and_sensitive():
    assert ch.fingerprint(BEFORE) == ch.fingerprint(dict(BEFORE))
    assert ch.fingerprint(BEFORE) != ch.fingerprint(_after(notes="x"))


def test_json_text_is_compared_by_meaning():
    a = {"schema": '[{"name": "x", "type": "text"}]'}
    b = {"schema": '[{"type": "text", "name": "x"}]'}          # same, keys reordered
    assert ch.diff(ch.decode_json_strings(a), ch.decode_json_strings(b)) == []
    c = {"schema": '[{"type": "date", "name": "x"}]'}
    assert ch.diff(ch.decode_json_strings(a), ch.decode_json_strings(c)) == [
        (("schema", 0, "type"), "text", "date")]


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
