# -*- coding: utf-8 -*-
"""Equipment types (GAPS §100): what a type obliges, balance acceptance at
0.2 % of nominal in grams, and the split due dates."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "src", "senaite", "pfas"))

import equipment_types as et  # noqa: E402


def test_a_balance_reads_in_grams_at_two_tenths_of_a_percent():
    """Lab, 2026-10-03: "Balances should always be in g with acceptable
    tolerances of 0.2%". Seeded, and grams survive a stored other unit."""
    for kind in et.BALANCE_KINDS:
        req = et.seed(kind)
        assert req["unit"] == "g" and req["tolerance_pct"] == 0.2
        assert et.normalise({"kind": kind, "unit": "mg"})["unit"] == "g"


def test_nothing_else_is_guessed():
    """Frequencies, factors and certificates are the lab's to enter."""
    for kind in et.KIND_KEYS:
        req = et.seed(kind)
        assert req["cal_frequency_days"] is None
        assert req["external_cert_required"] is False and req["correction_factor_required"] is False
        if kind not in et.BALANCE_KINDS:
            assert req["tolerance_pct"] is None and req["unit"] == ""
    assert et.seed("analytical")["in_worksheets"] is True
    assert et.seed("refrigerator")["in_worksheets"] is False


def test_acceptance_is_relative_and_exact_at_the_limit():
    # 10 g at 0.2 %: +/- 0.02 g
    assert et.within(10, 10.019, 0.2) and et.within(10, 9.981, 0.2)
    assert not et.within(10, 10.021, 0.2) and not et.within(10, 9.979, 0.2)
    # exactly on the limit passes, despite 0.501 - 0.5 = 0.0010000000000000009
    assert et.within(0.5, 0.501, 0.2) and et.within(10, 10.02, 0.2)
    assert not et.within(0.5, 0.5011, 0.2)


def test_parse_refuses_nonsense_and_keeps_the_rest():
    req, errors = et.parse({"kind": "refrigerator", "cal_frequency_days": "365",
                            "external_cert_required": "on", "tolerance_pct": ""})
    assert not errors and req["cal_frequency_days"] == 365 and req["external_cert_required"]
    _req, errors = et.parse({"kind": "pipette", "cal_frequency_days": "0"})
    assert errors and "whole number of days" in errors[0]
    _req, errors = et.parse({"kind": "balance_prep", "tolerance_pct": "-1"})
    assert errors and "positive" in errors[0]
    _req, errors = et.parse({"kind": "spaceship"})
    assert errors


def test_due_dates_split_internal_and_external():
    req = {"kind": "pipette", "cal_frequency_days": 90, "external_cert_required": True}
    d = et.due(req, last_internal="2026-07-01", cert_valid_to="2027-01-01", today="2026-10-03")
    assert d["internal"]["due"] == "2026-09-29" and d["internal"]["status"] == "overdue"
    assert d["external"]["status"] == "ok" and d["status"] == "overdue"
    d = et.due(req, last_internal="2026-09-20", cert_valid_to=None, today="2026-10-03")
    assert d["external"]["status"] == "missing" and d["status"] == "missing"
    d = et.due(req, last_internal="2026-07-10", cert_valid_to="2027-01-01", today="2026-10-03")
    assert d["internal"]["status"] == "due_soon"           # due 2026-10-08
    assert et.due({"kind": "eyewash"}, today="2026-10-03")["status"] == "not_set"
    # no internal record at all, when a frequency is set: missing, not ok
    assert et.due({"kind": "pipette", "cal_frequency_days": 90}, today="2026-10-03")["status"] == "missing"
