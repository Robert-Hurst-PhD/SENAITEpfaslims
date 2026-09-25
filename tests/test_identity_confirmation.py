# -*- coding: utf-8 -*-
"""FDA §10.2(4): single-transition positives require LC-HRMS confirmation.

PFBA and PFPeA have one usable MS/MS transition, so their identity cannot be
established by ion ratio the way every other analyte's is. A POSITIVE therefore
has to be confirmed by an orthogonal technique.

`single_transition_confirm_needed` computed this correctly and had NO CALLER
from the day it was written — its own docstring said "NOT WIRED" and GAPS.md §13
ranked it the most consequential remaining code gap. Same shape as §30: a
function that is right and is never asked.

These tests assert REACH, and the two things reach alone would get wrong:

  * it must be silent on the EPA methods, whose single_transition_analytes are
    empty — method-conditional by DATA, not by an `if method ==`
  * "detected" must mean detected, not quantified: BLoQ is a detection below the
    quantitation limit, and §10.2(4) is about identity, not the number
"""
from __future__ import print_function

import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

os.environ.setdefault("PFAS_PROFILES_PATH",
                      os.path.join(_ROOT, "data", "qc", "method_profiles.json"))

from pfas_pipeline.constants import (                          # noqa: E402
    QUALIFIER_CONF, QUALIFIER_ND, QUALIFIER_BLOQ,
)
from pfas_pipeline.models import Batch, InstrumentRow          # noqa: E402
from pfas_pipeline.pipeline import build_summary               # noqa: E402
from pfas_pipeline.run_queue import RunQueue, CheckStatus      # noqa: E402
from pfas_pipeline.injection_builder import REVIEW_CHECKS      # noqa: E402
from pfas_pipeline.qc_engine import (                          # noqa: E402
    single_transition_confirm_needed,
)
from pfas_pipeline import method_profiles as mp                # noqa: E402

mp.reload_from_profiles()

_SAMPLE = "260925-01"


def _row(compound, conc, qualifier="", injection=_SAMPLE):
    return InstrumentRow(
        compound_name=compound, compound_type="Target", compound_group="PFAS",
        sample_description=injection, injection_name=injection,
        sample_group="G1", sample_type="Unknown", included_in_cal=False,
        level=None, linked_is=None, cal_ref_compound=None, observed_rt=5.0,
        rt_relative_to_is=1.0, response=1000.0, is_response=1000.0,
        response_ratio=1.0, expected_conc=None, calculated_conc=conc,
        pct_deviation=None, pct_recovery_is=None, ion_ratios=None,
        expected_ion_ratios=None, r2=None, signal_to_noise=None, qual_sn=None,
        quant_status=None, reporting_limit=None, measured_conc=conc,
        acquisition_datetime=datetime(2026, 9, 25, 10, 0, 0),
        concat_id="{0}|20260925100000".format(injection),
        conc_qualifier=qualifier,
    )


def _summary(rows, method_id="FDA_32PFAS", matrix="Eggs"):
    batch = Batch(batch_id="B-CONF", analyst="RT", date=datetime(2026, 9, 25),
                  matrix=matrix, method_id=method_id,
                  instrument_file="synthetic.csv", injections=rows)
    build_summary(batch)
    return batch


def _result_for(batch, analyte, injection=_SAMPLE):
    hits = [s for s in batch.summary
            if s.analyte == analyte and s.sample_injection == injection]
    assert len(hits) == 1, (analyte, [s.analyte for s in batch.summary][:8])
    return hits[0]


def _owed(batch):
    return {(e["analyte"], e["sample_injection"])
            for e in batch.confirmations_required}


# ── The rule itself ──────────────────────────────────────────────────────────

def test_the_rule_names_the_analyte_the_technique_and_the_tolerance():
    profile = mp.get_profile("FDA_32PFAS")
    prompt = single_transition_confirm_needed(profile, "PFBA", True)
    assert prompt, "FDA must require confirmation for a PFBA positive"
    for fragment in ("PFBA", "LC-HRMS", "single MS/MS transition"):
        assert fragment in prompt, (fragment, prompt)


def test_the_technique_is_the_labs_to_name_not_hardcoded():
    """FDA §10.2(4) cites LC-HRMS as an example; it is not the only orthogonal
    route to confirming PFBA. A second column, a different ionisation mode or an
    alternative transition can also establish identity, so the prompt must quote
    whatever the lab configured rather than insisting on an instrument it may not
    own. CLAUDE.md §1 rule 1: configurable, not hardcoded.
    """
    class Stub(mp.FDA32PFASProfile):
        def __init__(self, technique):
            # The other confirmation criteria have to be present: this
            # method refuses to judge on an unconfigured one rather than
            # substituting a value, which is the behaviour §2 relies on.
            self._data = {"instrument_verification": {
                "confirmation": {
                    "confirm_technique": technique,
                    "ion_ratio_tol_pct": 30.0,
                    "rrt_tol_pct": 1.0,
                    "sn_quan_min": 3.0,
                    "sn_confirm_min": 3.0,
                }}}

        def _profile_data(self):
            return self._data

    prompt = single_transition_confirm_needed(
        Stub("second-column GC-MS/MS"), "PFBA", True)
    assert "second-column GC-MS/MS" in prompt, prompt
    assert "LC-HRMS" not in prompt, (
        "the prompt named LC-HRMS anyway", prompt)
    assert "orthogonal technique" in prompt, prompt

    # blank falls back to the method's cited example rather than naming nothing
    assert "LC-HRMS" in single_transition_confirm_needed(Stub(""), "PFBA", True)


def test_the_qualifier_code_does_not_assert_a_technique():
    """`HRMS` on a certificate claims the identification needs one specific
    instrument. `CONF` says what is true: confirmation is outstanding."""
    assert QUALIFIER_CONF == "CONF", QUALIFIER_CONF


def test_a_non_detect_needs_no_confirmation():
    profile = mp.get_profile("FDA_32PFAS")
    assert single_transition_confirm_needed(profile, "PFBA", False) is None


def test_an_analyte_with_two_transitions_needs_no_confirmation():
    """PFOA is identified by ion ratio; §10.2(4) does not reach it."""
    profile = mp.get_profile("FDA_32PFAS")
    assert single_transition_confirm_needed(profile, "PFOA", True) is None


def test_the_epa_methods_are_silent_because_their_analyte_list_is_empty():
    """Method-conditional by DATA. If this ever starts returning a prompt, the
    cause is a profile change, not a code change — and that is the point:
    CLAUDE.md §3 forbids a criterion scoped by an `if method ==`."""
    for method in ("EPA_537_1", "EPA_1633A"):
        profile = mp.get_profile(method)
        assert profile.confirmation_rule().single_transition_analytes == (), (
            method, "expected no single-transition analytes")
        assert single_transition_confirm_needed(profile, "PFBA", True) is None


# ── Reach: it is called, and the result carries the qualifier ────────────────

def test_a_pfba_positive_is_qualified_on_the_result():
    batch = _summary([_row("PFBA", 12.0)])
    res = _result_for(batch, "PFBA")
    assert res.result_ppt == 12.0
    assert QUALIFIER_CONF in res.flags, (
        "a single-transition positive reached the summary with no confirmation "
        "qualifier", res.flags)


def test_a_pfba_non_detect_is_not_qualified():
    batch = _summary([_row("PFBA", None, qualifier=QUALIFIER_ND)])
    res = _result_for(batch, "PFBA")
    assert res.qualifier == QUALIFIER_ND
    assert QUALIFIER_CONF not in res.flags, res.flags
    assert not _owed(batch)


def test_bloq_counts_as_a_detection():
    """BLoQ is 'detected below the quantitation limit' — the code says so in
    build_summary. §10.2(4) is about identity, so it still needs confirming."""
    batch = _summary([_row("PFPeA", 0.4, qualifier=QUALIFIER_BLOQ)])
    res = _result_for(batch, "PFPeA")
    assert QUALIFIER_CONF in res.flags, (res.qualifier, res.flags)
    assert ("PFPeA", _SAMPLE) in _owed(batch)


def test_a_two_transition_positive_is_not_qualified():
    batch = _summary([_row("PFOA", 50.0)])
    assert QUALIFIER_CONF not in _result_for(batch, "PFOA").flags
    assert not _owed(batch)


def test_nothing_is_owed_on_an_epa_batch():
    batch = _summary([_row("PFBA", 12.0)], method_id="EPA_1633A",
                     matrix="Wastewater")
    assert not _owed(batch), (
        "EPA 1633A raised an FDA §10.2(4) confirmation", batch.confirmations_required)
    assert QUALIFIER_CONF not in _result_for(batch, "PFBA").flags


# ── The review prompt ────────────────────────────────────────────────────────

def _plan(injection=_SAMPLE, qc_type="Sample"):
    return [{"injection_name": injection, "qc_type": qc_type,
             "checks": list(REVIEW_CHECKS[qc_type])}]


def _check(q, injection=_SAMPLE):
    hits = [c for c in q.checks
            if c.injection_name == injection
            and c.check_name == "identity_confirmation"]
    assert len(hits) == 1, [c.check_name for c in q.checks]
    return hits[0]


def test_the_check_is_declared_on_every_reported_role_and_no_other():
    """The same four roles build_summary calls REPORTED_ROLES."""
    for role in ("Sample", "MB", "LFSM", "LFSMD"):
        assert "identity_confirmation" in REVIEW_CHECKS[role], role
    for role in ("CAL", "ICV", "CCV", "CCB", "Dup", "LFB", "MxB", "LRB"):
        assert "identity_confirmation" not in REVIEW_CHECKS[role], role


def test_an_owed_confirmation_leaves_the_check_pending_with_the_prompt():
    batch = _summary([_row("PFBA", 12.0)])
    q = RunQueue(batch, _plan(), method_id="FDA_32PFAS")
    q.auto_evaluate()
    n = q.resolve_confirmations()
    assert n == 1, n
    chk = _check(q)
    assert chk.status == CheckStatus.PENDING, chk.status
    assert chk.flags, "pending with no prompt attached tells the reviewer nothing"
    assert "LC-HRMS" in chk.flags[0]["Issue"], chk.flags


def test_no_owed_confirmation_auto_passes_rather_than_pending_forever():
    """A check that is always PENDING is one nobody reads — GAPS §30.5."""
    batch = _summary([_row("PFOA", 50.0)])
    q = RunQueue(batch, _plan(), method_id="FDA_32PFAS")
    q.auto_evaluate()
    assert q.resolve_confirmations() == 0
    chk = _check(q)
    assert chk.status == CheckStatus.AUTO_PASS, chk.status
    assert not chk.flags


def test_auto_pass_here_does_not_mean_the_confirmation_was_done():
    """It means §10.2(4) does not apply. An owed confirmation stays PENDING and
    is closed by a human recording the LC-HRMS result, never by this pass."""
    batch = _summary([_row("PFBA", 12.0)])
    q = RunQueue(batch, _plan(), method_id="FDA_32PFAS")
    q.auto_evaluate()
    q.resolve_confirmations()
    assert _check(q).status != CheckStatus.AUTO_PASS


def test_resolve_confirmations_is_idempotent():
    batch = _summary([_row("PFBA", 12.0)])
    q = RunQueue(batch, _plan(), method_id="FDA_32PFAS")
    q.auto_evaluate()
    first = q.resolve_confirmations()
    before = (_check(q).status, len(_check(q).flags))
    assert q.resolve_confirmations() == first
    assert (_check(q).status, len(_check(q).flags)) == before


def test_the_resolve_step_runs_after_build_summary_in_run_pipeline():
    """resolve_confirmations() reads batch.confirmations_required, which only
    build_summary populates. Called first, every confirmation silently
    AUTO_PASSes — the check would report "does not apply" for a batch full of
    PFBA positives.

    Scans `run_pipeline` BY NAME. An earlier version fell back to the whole
    module when a guessed function name was absent, which passed for the wrong
    reason: it was finding the first occurrence of each string anywhere in the
    file rather than in the orchestration.
    """
    import inspect
    from pfas_pipeline import pipeline
    assert hasattr(pipeline, "run_pipeline"), (
        "run_pipeline is gone; this test is scanning nothing")
    src = inspect.getsource(pipeline.run_pipeline)
    i_summary = src.find("build_summary(batch)")
    i_resolve = src.find("resolve_confirmations()")
    assert i_summary != -1, "build_summary is not called in run_pipeline"
    assert i_resolve != -1, "resolve_confirmations is not called in run_pipeline"
    assert i_summary < i_resolve, (
        "resolve_confirmations() runs BEFORE build_summary(); every "
        "confirmation would silently AUTO_PASS")


def test_an_empty_owed_list_is_only_trusted_because_the_summary_ran():
    """Behavioural companion to the ordering test: with no summary built, the
    owed list is empty and the check reads AUTO_PASS. That is only CORRECT
    because run_pipeline guarantees the summary ran first — which is precisely
    why the ordering above is asserted rather than assumed."""
    batch = Batch(batch_id="B-NOSUM", analyst="RT",
                  date=datetime(2026, 9, 25), matrix="Eggs",
                  method_id="FDA_32PFAS", instrument_file="x.csv",
                  injections=[_row("PFBA", 12.0)])
    assert batch.confirmations_required == []
    q = RunQueue(batch, _plan(), method_id="FDA_32PFAS")
    assert q.resolve_confirmations() == 0


# ── What a client actually reads ─────────────────────────────────────────────

def test_the_displayed_value_reproduces_the_documented_real_output():
    """build_summary's docstring records three strings taken from REAL output:
    `8.39 (BLoQ)`, `0.0537 (BLoQ; N.C.)`, `10.6 (BLoQ; SUR)`. That is an
    independent reference, not this test's idea of the format — which matters,
    because display() matched NONE of the two-code forms: it put each group in
    its own parenthesis and joined flags with the empty string.
    """
    from pfas_pipeline.models import SummaryResult

    def shown(value, qualifier, flags):
        return SummaryResult(analyte="X", sample_injection="i",
                             result_ppt=value, qualifier=qualifier,
                             flags=list(flags)).display()

    assert shown(8.39, QUALIFIER_BLOQ, []) == "8.39 (BLoQ)"
    assert shown(0.0537, QUALIFIER_BLOQ, ["N.C."]) == "0.0537 (BLoQ; N.C.)"
    assert shown(10.6, QUALIFIER_BLOQ, ["SUR"]) == "10.6 (BLoQ; SUR)"


def test_two_qualifier_codes_never_run_together():
    """`12 (N.C.HRMS)` is not two codes, it is a third thing that is not a code.
    Wiring §10.2(4) made a second code common; the defect predated it."""
    from pfas_pipeline.models import SummaryResult
    line = SummaryResult(analyte="PFBA", sample_injection="i", result_ppt=12.0,
                         qualifier="", flags=["N.C.", QUALIFIER_CONF]).display()
    assert line == "12 (N.C.; CONF)", line
    assert "N.C.CONF" not in line
    assert ") (" not in line, ("each code group got its own parenthesis", line)


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
