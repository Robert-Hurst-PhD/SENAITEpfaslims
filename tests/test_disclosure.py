# -*- coding: utf-8 -*-
"""The accreditation disclosure derived from a frozen worksheet snapshot.

The lab's rule is that non-conforming data is always released, but must be
qualified as outside accreditation AND state exactly how it non-conforms. These
tests pin the three things the module must REFUSE to say, because each of them
would be a confident false assurance on a certificate:

  * it never claims a sample IS accredited
  * "no departure detected" is never reported as "conforms" while criteria
    remain uncompared for want of a baseline
  * no snapshot means "not recorded" and never falls back to live criteria
"""
from __future__ import print_function

import os
import sys

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


dis = _load(os.path.join(_SRC, "disclosure.py"), "pfas_disclosure_under_test")


def _row(key, conformance, **kw):
    row = {
        "key": key,
        "analyte": kw.get("analyte"),
        "value": kw.get("value"),
        "tier": kw.get("tier", "lab"),
        "source_doc": kw.get("source_doc"),
        "source_rev": kw.get("source_rev"),
        "conformance": conformance,
        "departure": kw.get("departure"),
    }
    return row


def _frozen(rows, **kw):
    return {
        "status": "frozen",
        "batch_id": kw.get("batch_id", "B-0001"),
        "method_id": kw.get("method_id", "EPA_1633A"),
        "matrix": kw.get("matrix", "Wastewater"),
        "frozen_at": kw.get("frozen_at", "2026-09-23T12:00:00Z"),
        "criteria": rows,
    }


# ── The three refusals ───────────────────────────────────────────────────────

def test_no_snapshot_is_not_recorded_and_never_claims_scope():
    d = dis.build_disclosure(None)
    assert d["outcome"] == dis.NOT_RECORDED, d
    assert d["out_of_scope"] is False, "absence of a record is not a departure"
    assert d["in_scope_claimed"] is False, (
        "a missing record must never read as an accreditation claim")
    assert d["items"] == []
    assert "cannot be stated" in d["reason"]


def test_an_unresolved_marker_is_not_an_absence_of_departures():
    """'unresolved'/'failed' mean resolution produced no basis. Reporting that
    as 'no departure' would turn a record-keeping failure into an assurance."""
    for status in ("unresolved", "failed", None, "", "something_new"):
        snap = _frozen([])
        snap["status"] = status
        d = dis.build_disclosure(snap)
        assert d["outcome"] == dis.NOT_RECORDED, (status, d)
        assert d["out_of_scope"] is False, status
        assert d["in_scope_claimed"] is False, status


def test_in_scope_is_never_claimed_even_when_everything_conforms():
    rows = [_row("cal_r2_min", "CONFORMS"), _row("dup_rpd_max", "CONFORMS")]
    d = dis.build_disclosure(_frozen(rows))
    assert d["outcome"] == dis.FULLY_COMPARED, d
    assert d["out_of_scope"] is False
    assert d["in_scope_claimed"] is False, (
        "accreditation scope is a property of the lab's scope of "
        "accreditation, not of criteria conformance")


def test_uncompared_criteria_are_not_reported_as_conforming():
    """Today only EPA 1633A EIS recovery carries a published-method baseline;
    everything else resolves UNKNOWN for want of one, not because it passed."""
    rows = [_row("eis_recovery", "CONFORMS"),
            _row("dup_rpd_max", "UNKNOWN"),
            _row("cal_r2_min", "UNKNOWN")]
    d = dis.build_disclosure(_frozen(rows))
    assert d["outcome"] == dis.NO_DEPARTURE_DETECTED, d
    assert d["compared"] == 1, d
    assert d["uncompared"] == 2, d
    assert "not established" in d["reason"], d["reason"]
    assert d["out_of_scope"] is False


# ── Departures ───────────────────────────────────────────────────────────────

def test_a_departure_takes_the_sample_out_of_scope_and_is_itemised():
    dep = {
        "baseline_value": {"min": 50.0, "max": 130.0},
        "resolved_value": {"min": 40.0, "max": 140.0},
        "citation": "EPA 1633A Table 8",
        "ends": [
            {"end": "min", "baseline_value": 50.0, "resolved_value": 40.0,
             "detail": "lower bound looser by 10.0"},
            {"end": "max", "baseline_value": 130.0, "resolved_value": 140.0,
             "detail": "upper bound looser by 10.0"},
        ],
    }
    rows = [_row("eis_recovery", "DEPARTS", analyte="13C4-PFBA",
                 tier="project", source_doc="QAPP-001", source_rev=3,
                 departure=dep),
            _row("dup_rpd_max", "UNKNOWN")]
    d = dis.build_disclosure(_frozen(rows))

    assert d["outcome"] == dis.DEPARTS_FROM_METHOD, d
    assert d["out_of_scope"] is True
    assert d["in_scope_claimed"] is False
    assert len(d["items"]) == 1, d["items"]
    item = d["items"][0]
    assert item["key"] == "eis_recovery"
    assert item["analyte"] == "13C4-PFBA"
    assert item["source_doc"] == "QAPP-001"
    assert item["source_rev"] == 3
    assert item["method_value"] == {"min": 50.0, "max": 130.0}
    assert item["applied_value"] == {"min": 40.0, "max": 140.0}
    assert len(item["ends"]) == 2


def test_only_departing_rows_are_itemised():
    rows = [_row("a", "CONFORMS"), _row("b", "UNKNOWN"),
            _row("c", "DEPARTS", departure={"baseline_value": 1,
                                            "resolved_value": 2})]
    d = dis.build_disclosure(_frozen(rows))
    assert [i["key"] for i in d["items"]] == ["c"], d["items"]


def test_snapshot_identity_is_carried_through():
    d = dis.build_disclosure(_frozen([], batch_id="B-77",
                                     method_id="FDA_32PFAS", matrix="Eggs",
                                     frozen_at="2026-01-02T03:04:05Z"))
    assert d["batch_id"] == "B-77"
    assert d["method_id"] == "FDA_32PFAS"
    assert d["matrix"] == "Eggs"
    assert d["frozen_at"] == "2026-01-02T03:04:05Z"


# ── The statement itself ─────────────────────────────────────────────────────

def test_format_departure_names_value_authority_and_method_requirement():
    line = dis.format_departure({
        "key": "eis_recovery", "analyte": "13C4-PFBA",
        "source_doc": "QAPP-001", "source_rev": 3,
        "applied_value": "40-140%", "method_value": "50-130%",
        "citation": "EPA 1633A Table 8",
        "ends": [{"detail": "lower bound looser by 10.0"}],
    })
    for fragment in ("eis_recovery", "13C4-PFBA", "40-140%", "QAPP-001",
                     "rev 3", "50-130%", "lower bound looser by 10.0",
                     "EPA 1633A Table 8"):
        assert fragment in line, (fragment, line)


def test_format_departure_does_not_invent_a_document_for_the_lab_tier():
    """The lab tier has no controlled-document link today -- the method profile
    carries values with no QAM/SOP revision. Say so; never synthesize one."""
    line = dis.format_departure({
        "key": "dup_rpd_max", "applied_value": 40.0, "method_value": 30.0,
        "source_doc": None, "source_rev": None,
    })
    assert "no controlled document recorded" in line, line
    assert "rev None" not in line, line


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
