"""A QC check may only be gated by a switch somebody can actually reach.

There are two switch stores, and they own different things:

  * `qc/rules.py RULE_LIBRARY` -- INSTRUMENT-level rules (IS response, RT, ion
    ratio, calibration r2, CCV, S/N, MDL). Its own header says so.
  * the method profile's `qc_acceptance[QC_TYPE].enabled` -- EXTRACTION and
    matrix QC (LFSM, LFSMD, MB, LRB, LFB, Dup, MxB), where the limits also live.

`run_queue._rule_enabled` defaults an ABSENT key to True. That is the right
default -- a missing toggle must not silently switch a check off -- but it means
a key absent from every table is indistinguishable from one a lab deliberately
enabled. `lfsm_recovery` and `lfsmd_rpd` lived exactly there: read by the
engine, present in NO library, NO defaults table and NO UI. So a lab that
switched LFSM off in the Method Profile was ignored -- the switch it was given
did nothing, and the switch that worked did not exist. Both checks always ran.

They now gate on `qc_acceptance`, the producer that already existed.

These tests parse the AST rather than the text, because the first version of
this reconciliation matched `_rule_enabled(toggles, "lfsm_recovery")` inside a
COMMENT describing the fix and reported the defect as still present.
"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "src", "senaite", "pfas", "qc", "rules.py")
QUEUE = os.path.join(ROOT, "pfas_pipeline", "run_queue.py")
# Every module that gates a check on a rule toggle, not just the queue. Added
# 2026-09-25: the FDA §10.2(4) confirmation prompt is gated in `pipeline.py`,
# because build_summary is the only place that knows whether an analyte was
# detected — and this guard scanned run_queue.py ALONE, so a toggle read there
# would have been invisible to the very test that exists to catch an unreachable
# toggle. The blind spot was in the checker, not the checked.
GATING_MODULES = [
    QUEUE,
    os.path.join(ROOT, "pfas_pipeline", "pipeline.py"),
]


def _module_literal(path, name):
    """A module-level literal assignment, without importing the module."""
    with open(path) as fh:
        tree = ast.parse(fh.read(), path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("%s not found in %s" % (name, path))


def _keys_read_by_engine():
    """Every literal key passed to `_rule_enabled` anywhere in GATING_MODULES --
    from the AST, so a mention in a comment or docstring does not count."""
    found = set()
    for path in GATING_MODULES:
        with open(path) as fh:
            tree = ast.parse(fh.read(), path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if getattr(func, "id", getattr(func, "attr", None)) != "_rule_enabled":
                continue
            for arg in node.args[1:]:
                value = (arg.value if hasattr(arg, "value")
                         else getattr(arg, "s", None))
                if isinstance(value, str):
                    found.add(value)
    return found


LIBRARY = {r["key"] for r in _module_literal(RULES, "RULE_LIBRARY")}
MAPPING = _module_literal(RULES, "LIBRARY_KEY_TO_ENGINE_CHECKS")
DEFAULTS = _module_literal(RULES, "DEFAULT_METHOD_RULE_TOGGLES")


def test_the_engine_never_gates_on_a_key_no_one_can_set():
    """The defect this file exists for. A key absent from RULE_LIBRARY has no
    UI, so the toggle is unreachable and permanently ON by default."""
    unreachable = sorted(_keys_read_by_engine() - LIBRARY)
    assert not unreachable, (
        "run_queue gates checks on %s, which are absent from RULE_LIBRARY -- "
        "no UI can set them and _rule_enabled defaults them to True forever. "
        "Either add them to the library or gate on the method profile's "
        "qc_acceptance, which owns extraction QC." % unreachable)


def test_the_three_tables_agree():
    """RULE_LIBRARY, the engine-check mapping and every method's defaults
    describe one set of rules. Drift between them is how a toggle ends up
    displayed but unread, or read but undisplayed."""
    assert sorted(LIBRARY) == sorted(MAPPING), (
        "RULE_LIBRARY and LIBRARY_KEY_TO_ENGINE_CHECKS disagree: "
        "library-only=%s mapping-only=%s"
        % (sorted(LIBRARY - set(MAPPING)), sorted(set(MAPPING) - LIBRARY)))
    for method, toggles in sorted(DEFAULTS.items()):
        assert sorted(toggles) == sorted(LIBRARY), (
            "%s default toggles drift from RULE_LIBRARY: missing=%s extra=%s"
            % (method, sorted(LIBRARY - set(toggles)),
               sorted(set(toggles) - LIBRARY)))


def test_extraction_qc_is_gated_by_the_method_profile_not_the_rule_library():
    """RULE_LIBRARY is instrument-level by its own definition. LFSM/LFSMD
    acceptance lives in the method profile, and so must its on/off switch --
    otherwise the limits and the switch are two sources for one fact."""
    for qc_type in ("LFSM", "LFSMD", "MB", "Dup", "LRB", "LFB", "MxB"):
        assert qc_type.lower() not in {k.lower() for k in LIBRARY}, (
            "%s is extraction/matrix QC; its toggle belongs in the method "
            "profile's qc_acceptance, not the instrument rule library" % qc_type)
    with open(QUEUE) as fh:
        body = fh.read()
    assert "_qc_type_enabled(profile, \"LFSM\")" in body, (
        "LFSM no longer gates on the method profile")
    assert "_qc_type_enabled(profile, \"LFSMD\")" in body, (
        "LFSMD no longer gates on the method profile")


def test_a_disabled_qc_type_is_honoured_and_an_absent_one_defaults_on():
    """Absent must default ON: a missing entry silently switching a check off
    is the failure mode that matters. An explicit False must be obeyed.

    `profile` in run_queue is a MethodProfile OBJECT, not a dict. The first
    version of this fix called `.get()` on it and the fault-injection suite
    caught the AttributeError -- which is why the flag is read through a method
    on the profile class rather than by reaching into its data here.
    """
    import sys
    sys.path.insert(0, ROOT)
    os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")
    from pfas_pipeline.method_profiles import MethodProfile
    from pfas_pipeline.run_queue import _qc_type_enabled

    class Stub(MethodProfile):
        def __init__(self, data):
            self._data = data

        def _profile_data(self):
            return self._data

    assert _qc_type_enabled(None, "LFSM") is True, "no profile -> run the check"
    assert _qc_type_enabled(Stub({}), "LFSM") is True, "no qc_acceptance -> run"
    assert _qc_type_enabled(Stub({"qc_acceptance": {}}), "LFSM") is True
    assert _qc_type_enabled(
        Stub({"qc_acceptance": {"LFSM": {}}}), "LFSM") is True, "no flag -> run"
    assert _qc_type_enabled(
        Stub({"qc_acceptance": {"LFSM": {"enabled": True}}}), "LFSM") is True
    assert _qc_type_enabled(
        Stub({"qc_acceptance": {"LFSM": {"enabled": False}}}), "LFSM") is False, (
        "an explicit disable in the method profile must be obeyed")
    # malformed data must not crash a run
    assert _qc_type_enabled(Stub({"qc_acceptance": {"LFSM": "yes"}}), "LFSM") is True
    # an object with no such method (an older profile) still runs the check
    assert _qc_type_enabled(object(), "LFSM") is True


def test_the_real_profiles_report_their_configured_state():
    """Against the actual shipped profiles, not a stub."""
    import sys
    sys.path.insert(0, ROOT)
    from pfas_pipeline.method_profiles import get_profile
    for mid in ("FDA_32PFAS", "EPA_537_1", "EPA_1633A"):
        profile = get_profile(mid)
        for qc_type in ("LFSM", "LFSMD"):
            assert profile.qc_type_enabled(qc_type) is True, (
                "%s %s is configured enabled=True and must report so"
                % (mid, qc_type))


def test_the_confirmation_toggle_is_reachable_and_enforced():
    """The FDA §10.2(4) prompt must be switchable off — a lab may confirm PFBA by
    a route other than the LC-HRMS the method cites, and the prompt should not
    insist on an instrument it may not own.

    Pins all three halves of "reachable": in the library (so it has a UI), in
    every method's defaults, and actually READ by a gating module. Any one
    missing is the §8 defect — a switch that is displayed but unread, or read but
    undisplayed.
    """
    key = "single_transition_confirm"
    assert key in LIBRARY, "no UI: the toggle would be permanently ON"
    assert key in MAPPING and MAPPING[key], (
        "mapped to no engine check, so it would be declared UI-only while "
        "actually gating something")
    for method, toggles in sorted(DEFAULTS.items()):
        assert key in toggles, method
    assert key in _keys_read_by_engine(), (
        "the toggle is displayed but nothing reads it")


def test_switching_the_confirmation_off_suppresses_the_qualifier():
    """Behavioural, not structural: with the rule OFF, a PFBA positive gets no
    confirmation qualifier and nothing is recorded as owed."""
    import sys
    import json
    import tempfile
    from datetime import datetime
    sys.path.insert(0, ROOT)
    os.environ.setdefault("PFAS_ALLOW_LEGACY_VENDOR_MAP", "1")
    os.environ.setdefault(
        "PFAS_PROFILES_PATH",
        os.path.join(ROOT, "data", "qc", "method_profiles.json"))
    from pfas_pipeline import method_profiles as mp
    from pfas_pipeline import pipeline as pl
    from pfas_pipeline.constants import QUALIFIER_CONF
    from pfas_pipeline.models import Batch, InstrumentRow
    mp.reload_from_profiles()

    def _row():
        return InstrumentRow(
            compound_name="PFBA", compound_type="Target", compound_group="PFAS",
            sample_description="i", injection_name="260925-01",
            sample_group="G1", sample_type="Unknown", included_in_cal=False,
            level=None, linked_is=None, cal_ref_compound=None, observed_rt=5.0,
            rt_relative_to_is=1.0, response=1000.0, is_response=1000.0,
            response_ratio=1.0, expected_conc=None, calculated_conc=12.0,
            pct_deviation=None, pct_recovery_is=None, ion_ratios=None,
            expected_ion_ratios=None, r2=None, signal_to_noise=None,
            qual_sn=None, quant_status=None, reporting_limit=None,
            measured_conc=12.0,
            acquisition_datetime=datetime(2026, 9, 25, 10, 0, 0),
            concat_id="260925-01|20260925100000")

    def _summary_flags(rules_payload):
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as fh:
            json.dump(rules_payload, fh)
            rules_path = fh.name
        from pfas_pipeline import run_queue as rq
        original = rq._load_rule_toggles
        rq._load_rule_toggles = lambda mid, rules_path=rules_path: (
            original(mid, rules_path))
        try:
            batch = Batch(batch_id="B-T", analyst="RT",
                          date=datetime(2026, 9, 25), matrix="Eggs",
                          method_id="FDA_32PFAS", instrument_file="x.csv",
                          injections=[_row()])
            pl.build_summary(batch)
            hit = [s for s in batch.summary if s.analyte == "PFBA"][0]
            return hit.flags, batch.confirmations_required
        finally:
            rq._load_rule_toggles = original
            os.unlink(rules_path)

    on_flags, on_owed = _summary_flags(
        {"method_rule_toggles": {"FDA_32PFAS":
                                 {"single_transition_confirm": True}}})
    assert QUALIFIER_CONF in on_flags, ("rule ON must qualify", on_flags)
    assert on_owed, "rule ON must record the confirmation as owed"

    off_flags, off_owed = _summary_flags(
        {"method_rule_toggles": {"FDA_32PFAS":
                                 {"single_transition_confirm": False}}})
    assert QUALIFIER_CONF not in off_flags, (
        "the switch did nothing — the qualifier was applied with the rule OFF",
        off_flags)
    assert not off_owed, ("the switch did nothing — a confirmation was still "
                          "recorded as owed", off_owed)


def test_ui_only_rules_are_declared_as_such():
    """`ccv_frequency` and `mdl_check` gate no engine check. That is recorded
    in the mapping as an empty list -- which is honest, and is the difference
    between a documented gap and a lying switch. If either ever acquires a
    check, this test is the reminder to wire the mapping too."""
    ui_only = sorted(k for k, v in MAPPING.items() if not v)
    assert ui_only == ["ccv_frequency", "mdl_check"], (
        "the set of unenforced toggles changed: %s. A toggle a QAO can switch "
        "ON while nothing checks it must be declared, not silent." % ui_only)
    for key in ui_only:
        assert key in LIBRARY, "%s is unenforced AND absent from the UI" % key


def test_lfsmd_without_lfsm_is_reported_as_unsatisfiable():
    """The spike/duplicate RPD is computed FROM the LFSM recovery, so LFSMD
    with LFSM off evaluates nothing. Verified live: disabling LFSM alone took a
    run from 32 lfsm + 32 lfsmd flags to zero of both. A Method Profile showing
    LFSMD enabled while it can never fire is the silent-no-op shape again, so
    the run says so."""
    with open(QUEUE) as fh:
        body = fh.read()
    assert "lfsmd_enabled and not lfsm_enabled" in body, (
        "run_queue no longer detects the LFSMD-without-LFSM combination")
    assert "NO LFSMD result will be evaluated" in body, (
        "the warning no longer states the consequence")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
