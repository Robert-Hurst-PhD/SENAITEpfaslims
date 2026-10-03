# -*- coding: utf-8 -*-
"""Analysis Specifications grouped (GAPS §96): matrices with the same ranges
share a row; each window is listed once with its analytes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "src", "senaite", "pfas"))

import spec_groups as sg  # noqa: E402


def _rows(spec):
    return [{"keyword": kw, "min": str(lo), "max": str(hi)} for kw, (lo, hi) in sorted(spec.items())]


TIGHT = {"PFOA": (80, 120), "PFOS": (80, 120), "PFBA": (65, 135)}
LOOSE = {"PFOA": (65, 135), "PFOS": (65, 135), "PFBA": (65, 135)}


def test_matrices_with_identical_ranges_share_one_row():
    entries = [{"matrix": "Eggs", "url": "u1", "rows": _rows(TIGHT)},
               {"matrix": "Milk", "url": "u2", "rows": _rows(LOOSE)},
               {"matrix": "Meat", "url": "u3", "rows": list(reversed(_rows(TIGHT)))},
               {"matrix": "Feed", "url": "u4", "rows": _rows(LOOSE)}]
    groups = sg.group(entries)
    assert [g["matrices"] for g in groups] == [["Eggs", "Meat"], ["Milk", "Feed"]]
    assert [s["url"] for s in groups[0]["specs"]] == ["u1", "u3"]


def test_each_window_once_with_its_analytes_widest_share_first():
    w = sg.windows(_rows(TIGHT))
    assert [x["text"] for x in w] == [u"80–120 %", u"65–135 %"]
    assert w[0]["analytes"] == ["PFOA", "PFOS"] and w[1]["analytes"] == ["PFBA"]
    assert [x["text"] for x in sg.windows(_rows(LOOSE))] == [u"65–135 %"]


def test_a_one_analyte_difference_keeps_matrices_apart():
    other = dict(TIGHT, PFBA=(70, 130))
    groups = sg.group([{"matrix": "A", "rows": _rows(TIGHT)}, {"matrix": "B", "rows": _rows(other)}])
    assert len(groups) == 2


def test_a_low_level_tier_never_becomes_the_spec_window():
    """EPA 537.1 LFSM: 70-130 %, and 50-150 % only within 2 x MRL (§9.3.6.3).
    The low-level tier must not overwrite the ordinary window, whichever
    order the tiers are listed in."""
    import spec_sync
    ordinary = {"analyte_group": "all", "recovery_min": 70.0, "recovery_max": 130.0}
    low = {"analyte_group": "all", "recovery_min": 50.0, "recovery_max": 150.0,
           "low_level_x_rl": 2.0}
    for tiers in ([ordinary, low], [low, ordinary]):
        lims = spec_sync._tier_limits({"LFSM": {"enabled": True, "tiers": tiers}}, "LFSM")
        assert lims[2] == {"min": 70.0, "max": 130.0}, tiers
    only_low = spec_sync._tier_limits({"LFSM": {"enabled": True, "tiers": [low]}}, "LFSM")
    assert only_low is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
