# -*- coding: utf-8 -*-
"""Regression tests for senaite.pfas.worksheet_criteria_snapshot -- the
write-once freeze of a worksheet's governing QC criteria at the ISO 17025
Sec7.8.4 technical review (GAPS.md Sec26; the problem it fixes is Sec24).

Loaded by path, exactly like tests/test_resolved_criteria_store.py, since
worksheet_criteria_snapshot's thin ZODB shells fall back to nothing -- they
import zope.annotation / senaite.pfas.* lazily, INSIDE the function bodies,
for exactly this reason: this module can be loaded standalone with no Zope
container present.

The pure functions (build_snapshot_payload / build_unresolved_marker /
build_failure_marker / store_snapshot / read_snapshot) need no faking at
all -- they operate on any dict-like `store`, which is the whole point of
keeping them Zope-free (same "pure core, thin shell" split as ruleset.py /
resolved_criteria_store.py).

freeze_resolved_criteria()/get_frozen_criteria() are the thin ZODB shells.
Rather than leaving them fully unexercised ("proven live" only, the
convention resolved_criteria_store.py's own equivalents use), this file
fakes the two things they touch -- zope.annotation.interfaces.IAnnotations
and the senaite.pfas.{resolved_criteria_store,project_ref,method_profile_
store} imports -- via sys.modules, so the actual write-once code path (not
just the store_snapshot() primitive it calls) is exercised end to end,
including the exact "retract -> re-verify" scenario the freeze point exists
to protect against. This is safe here (and only here, in this one
subprocess) because the test suite runs each tests/*.py file as its own
`python3` invocation -- see README/CLAUDE.md's test-running note -- so
faking `sys.modules["zope"]` etc. cannot leak into any other test file.

    python3 tests/test_worksheet_criteria_snapshot.py
"""
from __future__ import print_function

import copy
import json
import os
import sys
import types

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
wcs = _load(os.path.join(_SRC, "worksheet_criteria_snapshot.py"),
            "pfas_worksheet_criteria_snapshot_under_test")


# ── Fakes: only used by the freeze_resolved_criteria()/get_frozen_criteria ──
# ── thin-shell tests below; the pure-function tests need none of this. ──────

def _fake_iannotations(obj):
    """Stands in for zope.annotation.interfaces.IAnnotations: a persistent
    per-object dict -- exactly the "annotate the object, get the same store
    back next time" contract the real adapter provides, which is what makes
    write-once meaningful across two separate freeze_resolved_criteria()
    calls on the SAME ws object.

    Stored as an attribute ON the object (like the real AttributeAnnotations
    adapter), not keyed by id(obj) in a module-level registry -- id() is
    only unique for the lifetime of the object, and a registry keyed on it
    would silently collide if a GC'd _FakeWorksheet's address were reused by
    a later one, corrupting an unrelated test's "no snapshot" assertion."""
    if not hasattr(obj, "_fake_annotations"):
        obj._fake_annotations = {}
    return obj._fake_annotations


def _install_fakes():
    fake_project_ref = types.ModuleType("senaite.pfas.project_ref")
    fake_project_ref.get_project = lambda portal, batch: None
    fake_project_ref.get_project_uid = lambda batch: None

    fake_method_profile_store = types.ModuleType("senaite.pfas.method_profile_store")
    fake_method_profile_store.get_profile = lambda portal, method_id: {}

    fake_senaite_pfas = types.ModuleType("senaite.pfas")
    fake_senaite_pfas.__path__ = []
    fake_senaite_pfas.resolved_criteria_store = rcs
    fake_senaite_pfas.project_ref = fake_project_ref
    fake_senaite_pfas.method_profile_store = fake_method_profile_store

    fake_senaite = types.ModuleType("senaite")
    fake_senaite.__path__ = []
    fake_senaite.pfas = fake_senaite_pfas

    fake_zope_annotation_interfaces = types.ModuleType("zope.annotation.interfaces")
    fake_zope_annotation_interfaces.IAnnotations = _fake_iannotations
    fake_zope_annotation = types.ModuleType("zope.annotation")
    fake_zope_annotation.interfaces = fake_zope_annotation_interfaces
    fake_zope = types.ModuleType("zope")
    fake_zope.annotation = fake_zope_annotation

    sys.modules["senaite"] = fake_senaite
    sys.modules["senaite.pfas"] = fake_senaite_pfas
    sys.modules["senaite.pfas.resolved_criteria_store"] = rcs
    sys.modules["senaite.pfas.project_ref"] = fake_project_ref
    sys.modules["senaite.pfas.method_profile_store"] = fake_method_profile_store
    sys.modules["zope"] = fake_zope
    sys.modules["zope.annotation"] = fake_zope_annotation
    sys.modules["zope.annotation.interfaces"] = fake_zope_annotation_interfaces


_install_fakes()


class _FakeWorksheet(object):
    """A stand-in for a Worksheet object: freeze_resolved_criteria() only
    ever calls .getId() on it and hands it to IAnnotations(), both of which
    this satisfies."""
    def __init__(self, ws_id):
        self._id = ws_id

    def getId(self):
        return self._id


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


# ── Pure: payload shape ──────────────────────────────────────────────────────

def test_build_snapshot_payload_shape():
    rows = [{"key": "dup_rpd_max", "analyte": None, "value": 20.0}]
    payload = wcs.build_snapshot_payload("WS-1", "FDA_32PFAS", "Eggs", rows,
                                          frozen_at="2026-09-23T00:00:00Z")
    assert payload["status"] == wcs.STATUS_FROZEN
    assert payload["batch_id"] == "WS-1"
    assert payload["method_id"] == "FDA_32PFAS"
    assert payload["matrix"] == "Eggs"
    assert payload["frozen_at"] == "2026-09-23T00:00:00Z"
    assert payload["criteria"] == rows


def test_build_unresolved_marker_shape():
    payload = wcs.build_unresolved_marker(
        "WS-2", u"", u"Eggs", reason="method_id not known",
        attempted_at="2026-09-23T00:00:00Z")
    assert payload["status"] == wcs.STATUS_UNRESOLVED
    assert payload["reason"] == "method_id not known"
    assert "criteria" not in payload


def test_build_failure_marker_carries_superseded_marker_forward():
    first = wcs.build_failure_marker("WS-3", "FDA_32PFAS", "Eggs",
                                      error=RuntimeError("boom"),
                                      attempted_at="2026-09-23T00:00:00Z")
    assert first["status"] == wcs.STATUS_FAILED
    assert first["error"] == "boom"
    assert "superseded" not in first

    second = wcs.build_failure_marker("WS-3", "FDA_32PFAS", "Eggs",
                                       error=RuntimeError("boom again"),
                                       attempted_at="2026-09-23T00:05:00Z",
                                       superseded=first)
    assert second["superseded"] == first
    assert second["error"] == "boom again"


# ── Pure: write-once semantics on store_snapshot() ───────────────────────────

def test_store_snapshot_write_once_does_not_overwrite_frozen():
    store = {}
    first = wcs.build_snapshot_payload("WS-4", "FDA_32PFAS", "Eggs", [{"key": "a"}],
                                        frozen_at="T1")
    written1, effective1 = wcs.store_snapshot(store, first)
    assert written1 is True
    assert effective1 == first

    second = wcs.build_snapshot_payload("WS-4", "EPA_1633A", "Drinking Water",
                                         [{"key": "b"}], frozen_at="T2")
    written2, effective2 = wcs.store_snapshot(store, second)
    assert written2 is False, "a second freeze must never overwrite a frozen snapshot"
    assert effective2 == first, "the ORIGINAL payload must come back, untouched"
    assert effective2["frozen_at"] == "T1"
    assert store[wcs.SNAPSHOT_KEY] == first, "the store itself must still hold the original"


def test_store_snapshot_replaces_unresolved_and_failed_markers():
    store = {}
    unresolved = wcs.build_unresolved_marker("WS-5", u"", u"", reason="nothing known")
    written1, _ = wcs.store_snapshot(store, unresolved)
    assert written1 is True

    frozen = wcs.build_snapshot_payload("WS-5", "FDA_32PFAS", "Eggs", [{"key": "a"}])
    written2, effective2 = wcs.store_snapshot(store, frozen)
    assert written2 is True, "an 'unresolved' marker is not judgement history -- it may be replaced"
    assert effective2 == frozen
    assert store[wcs.SNAPSHOT_KEY] == frozen

    # Once frozen, it is protected again.
    another = wcs.build_snapshot_payload("WS-5", "EPA_1633A", "Soil", [{"key": "z"}])
    written3, effective3 = wcs.store_snapshot(store, another)
    assert written3 is False
    assert effective3 == frozen


# ── Pure: reading ─────────────────────────────────────────────────────────────

def test_read_snapshot_returns_none_when_nothing_frozen():
    """A worksheet with no snapshot must report 'not recorded' -- this is
    read_snapshot()'s contract: None, never a live-resolved substitute."""
    store = {}
    assert wcs.read_snapshot(store) is None


def test_read_snapshot_returns_a_deep_copy_not_the_live_dict():
    store = {}
    payload = wcs.build_snapshot_payload("WS-6", "FDA_32PFAS", "Eggs",
                                          [{"key": "a", "departure": {"ends": []}}])
    wcs.store_snapshot(store, payload)

    got = wcs.read_snapshot(store)
    got["criteria"][0]["value"] = "TAMPERED"
    got["criteria"][0]["departure"]["ends"].append("TAMPERED")

    got_again = wcs.read_snapshot(store)
    assert got_again["criteria"][0].get("value") is None or \
        got_again["criteria"][0]["value"] != "TAMPERED"
    assert got_again["criteria"][0]["departure"]["ends"] == [], (
        "mutating what a reader was handed back must never touch the frozen record")


# ── Provenance round-trip through the real resolver ──────────────────────────

def test_provenance_round_trips_through_build_and_store():
    project_ruleset = {"FDA_32PFAS": {"Eggs": {"cal_r2_min": 0.980}}}
    rows = rcs.build_resolved_rows("FDA_32PFAS", "Eggs", profile=_FDA_PROFILE,
                                    project_ruleset=project_ruleset,
                                    project_doc="QAPP-007", project_rev=3)

    payload = wcs.build_snapshot_payload("B-100", "FDA_32PFAS", "Eggs", rows)
    store = {}
    wcs.store_snapshot(store, payload)

    # Round-trip through JSON too -- proves the shape actually stored on a
    # ZODB annotation (or exported anywhere else) survives serialization.
    reloaded = json.loads(json.dumps(wcs.read_snapshot(store)))

    row = next(r for r in reloaded["criteria"] if r["key"] == "cal_r2_min")
    assert row["value"] == 0.980
    assert row["tier"] == rs.TIER_PROJECT
    assert row["source_doc"] == "QAPP-007"
    assert row["source_rev"] == 3
    assert row["conformance"] == mb.UNKNOWN
    assert row["departure"] is None

    departing = next(r for r in rcs.build_resolved_rows(
        "EPA_1633A", "Drinking Water",
        profile={"eis_overrides": [{"analyte": "13C4-PFBA",
                                     "recovery_min": 5.0, "recovery_max": 130.0}]},
        project_ruleset={"EPA_1633A": {"Drinking Water": {
            "eis_recovery": {"13C4-PFBA": {"min": 1.0, "max": 200.0}}}}})
        if r["key"] == "eis_recovery" and r["analyte"] == "13C4-PFBA")
    payload2 = wcs.build_snapshot_payload("B-101", "EPA_1633A", "Drinking Water",
                                           [departing])
    store2 = {}
    wcs.store_snapshot(store2, payload2)
    reloaded2 = json.loads(json.dumps(wcs.read_snapshot(store2)))
    row2 = reloaded2["criteria"][0]
    assert row2["tier"] == rs.TIER_PROJECT
    assert row2["conformance"] == mb.DEPARTS
    assert row2["departure"]["citation"] and "820-R-24-007" in row2["departure"]["citation"]
    ends = sorted(e["end"] for e in row2["departure"]["ends"])
    assert ends == ["max", "min"]


# ── Thin shell: freeze_resolved_criteria() end to end ────────────────────────

def test_freeze_writes_a_snapshot_at_verification():
    ws = _FakeWorksheet("WS-200")
    result = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None,
        method_id="FDA_32PFAS", matrix="Eggs")
    assert result["status"] == wcs.STATUS_FROZEN
    assert result["method_id"] == "FDA_32PFAS"
    assert result["matrix"] == "Eggs"
    assert result["criteria"], "resolution against the (faked) baseline tier must produce rows"

    stored = wcs.get_frozen_criteria(ws)
    assert stored == result


def test_second_verification_does_not_overwrite_the_frozen_snapshot():
    """The exact scenario the freeze point exists to protect: a worksheet is
    verified, then later retracted and re-verified (or a project is
    re-linked and someone re-triggers the handler). The SECOND
    freeze_resolved_criteria() call on the SAME worksheet must be a no-op."""
    ws = _FakeWorksheet("WS-201")
    first = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None,
        method_id="FDA_32PFAS", matrix="Eggs")
    assert first["status"] == wcs.STATUS_FROZEN
    first_frozen_at = first["frozen_at"]

    # Simulate the criteria having changed in the meantime (e.g. a project
    # re-link) by calling again with a DIFFERENT method/matrix -- if
    # write-once were broken this would silently replace the first result.
    second = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None,
        method_id="EPA_1633A", matrix="Drinking Water")

    assert second["status"] == wcs.STATUS_FROZEN
    assert second["method_id"] == "FDA_32PFAS", (
        "a second verification must never rewrite the basis of the first "
        "judgement -- got {0!r}".format(second["method_id"]))
    assert second["matrix"] == "Eggs"
    assert second["frozen_at"] == first_frozen_at

    stored = wcs.get_frozen_criteria(ws)
    assert stored["method_id"] == "FDA_32PFAS"


def test_worksheet_with_no_snapshot_reports_not_recorded():
    ws = _FakeWorksheet("WS-202-never-verified")
    assert wcs.get_frozen_criteria(ws) is None, (
        "a worksheet verified before this feature existed must report "
        "'not recorded' -- never a live-resolved substitute")


# ── The subscriber guard ─────────────────────────────────────────────────────
# data_review.on_after_transition itself imports Zope at module load, so only
# its guard is exercised here. The guard is the part that must be exact: this
# handler runs on EVERY workflow transition in the site.

def test_should_freeze_only_on_a_worksheet_verify():
    assert wcs.should_freeze("Worksheet", "verify") is True


def test_should_freeze_ignores_other_transitions_on_a_worksheet():
    for t in ("submit", "retract", "reject", "unassign", "reinstate",
              "cancel", "publish", "receive", "verified", "Verify"):
        assert wcs.should_freeze("Worksheet", t) is False, t


def test_should_freeze_ignores_verify_on_other_types():
    """A sample and an analysis both have a `verify` transition, and both fire
    this subscriber. Freezing on either would write the annotation onto an
    object whose criteria nobody asked about."""
    for pt in ("AnalysisRequest", "Analysis", "Batch", "DuplicateAnalysis",
               "ReferenceAnalysis", "PFASProject", None, ""):
        assert wcs.should_freeze(pt, "verify") is False, pt


def test_failed_then_fixed_retry_carries_the_failure_forward_as_superseded():
    """A resolution failure is not judgement history, so a later retry MAY
    replace it -- but the fact that the first attempt failed must survive
    the retry that fixed it, or requirement 3 (record a marker distinct from
    'never attempted') is undone the moment someone actually reverifies."""
    ws = _FakeWorksheet("WS-204")
    original = rcs.resolve_rows_for_batch

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated resolution failure")

    rcs.resolve_rows_for_batch = _boom
    try:
        first = wcs.freeze_resolved_criteria(
            portal=None, ws=ws, batch=None,
            method_id="FDA_32PFAS", matrix="Eggs")
    finally:
        rcs.resolve_rows_for_batch = original

    assert first["status"] == wcs.STATUS_FAILED
    assert "superseded" not in first

    second = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None,
        method_id="FDA_32PFAS", matrix="Eggs")

    assert second["status"] == wcs.STATUS_FROZEN, (
        "the retry succeeded and is not itself judgement history yet -- it "
        "must be allowed to replace a non-frozen marker")
    assert second["superseded"]["status"] == wcs.STATUS_FAILED, (
        "the first attempt's failure must not be silently erased by the "
        "success that followed it")
    assert second["superseded"]["error"] == "simulated resolution failure"

    stored = wcs.get_frozen_criteria(ws)
    assert stored["superseded"]["status"] == wcs.STATUS_FAILED

    # And now write-once protects the SUCCESSFUL one, as normal.
    third = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None,
        method_id="EPA_1633A", matrix="Drinking Water")
    assert third["method_id"] == "FDA_32PFAS", "frozen means frozen, even after a supersession"


def test_already_frozen_early_return_is_also_a_deep_copy():
    ws = _FakeWorksheet("WS-205")
    first = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None,
        method_id="FDA_32PFAS", matrix="Eggs")
    second = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None,
        method_id="FDA_32PFAS", matrix="Eggs")
    second["criteria"].append("TAMPERED")
    third = wcs.get_frozen_criteria(ws)
    assert "TAMPERED" not in third["criteria"], (
        "the already-frozen early return must hand back a copy, not the "
        "live annotation dict")


def test_unresolved_when_method_or_matrix_unknown_never_an_empty_frozen_payload():
    ws = _FakeWorksheet("WS-203")
    result = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None, method_id=u"", matrix=u"Eggs")
    assert result["status"] == wcs.STATUS_UNRESOLVED, (
        "an unknown method_id must never be stamped 'frozen' with an empty "
        "criteria list -- that would assert a judgement that was never made")
    assert "criteria" not in result

    # And it is NOT write-once in the same way "frozen" is: a later attempt
    # with the method now known may resolve it.
    result2 = wcs.freeze_resolved_criteria(
        portal=None, ws=ws, batch=None, method_id="FDA_32PFAS", matrix="Eggs")
    assert result2["status"] == wcs.STATUS_FROZEN


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
