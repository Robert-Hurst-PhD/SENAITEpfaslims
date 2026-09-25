# -*- coding: utf-8 -*-
"""Surrogate / extracted-internal-standard recovery: does the check RUN?

Two defects met here, and both were invisible to a value-based test:

  * `get_is_list()` read a profile key (`internal_standards`) that nothing has
    ever written, so it returned [] for both EPA methods and the IS loop
    iterated nothing — no surrogate was checked at all (GAPS.md §19).

  * `recovery_check_profiled` had exactly ONE call site, passing the literal
    "LFSM". No call ever asked for a surrogate window, so EPA 1633A's
    per-analyte Tables 6/8 limits — resolvable through all three tiers,
    exported across the process boundary, overlaid per batch — were unreachable
    from a live run (GAPS.md §30).

So these tests assert REACH, not values. The discriminator is chosen so it can
only pass if the Table 6 name join works: EPA 1633A gives PFBA's EIS a 5% floor
and PFPeA's a 40% floor, and the lab's catalogue spells both differently from
EPA (13C3-PFBA vs Table 6's 13C4-PFBA). One run, both compounds at 20%
recovery: PFBA must pass and PFPeA must fail. A lookup on the instrument's own
name finds neither and applies the generic window to both, which fails PFBA too.
"""
from __future__ import print_function

import csv
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

os.environ.setdefault("PFAS_PROFILES_PATH",
                      os.path.join(_ROOT, "data", "qc", "method_profiles.json"))

from pfas_pipeline.models import Batch, InstrumentRow          # noqa: E402
from pfas_pipeline.run_queue import RunQueue, CheckStatus      # noqa: E402
from pfas_pipeline.injection_builder import REVIEW_CHECKS      # noqa: E402
from pfas_pipeline import method_profiles as mp                # noqa: E402
from pfas_pipeline.analyte_alias import injection_is_names     # noqa: E402

mp.reload_from_profiles()


def _service_universe():
    """Every labelled-compound name that exists as an AnalysisService.

    setupdata/internal_standards.csv is the ONLY thing that creates them, so it
    is the authority on which names an instrument row can ever match.
    """
    path = os.path.join(_ROOT, "src", "senaite", "pfas", "setupdata",
                        "internal_standards.csv")
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    return {r["Title"] for r in rows} | {r["Keyword"] for r in rows}


def _row(compound, injection, recovery, sample_type="Unknown"):
    return InstrumentRow(
        compound_name=compound, compound_type="IS", compound_group="IS",
        sample_description=injection, injection_name=injection,
        sample_group="G1", sample_type=sample_type, included_in_cal=False,
        level=None, linked_is=None, cal_ref_compound=None, observed_rt=5.0,
        rt_relative_to_is=1.0, response=1000.0, is_response=1000.0,
        response_ratio=1.0, expected_conc=None, calculated_conc=None,
        pct_deviation=None, pct_recovery_is=recovery, ion_ratios=None,
        expected_ion_ratios=None, r2=None, signal_to_noise=None, qual_sn=None,
        quant_status=None, reporting_limit=None, measured_conc=None,
        acquisition_datetime=datetime(2026, 9, 25, 10, 0, 0),
        concat_id="{0}|20260925100000".format(injection),
    )


def _run(rows, plan, method_id="EPA_1633A", matrix="Wastewater"):
    batch = Batch(batch_id="B-EIS-1", analyst="RT", date=datetime(2026, 9, 25),
                  matrix=matrix, method_id=method_id,
                  instrument_file="synthetic.csv", injections=rows)
    q = RunQueue(batch, plan, method_id=method_id)
    q.auto_evaluate()
    return q, batch


def _sample_plan(injection):
    return [{"injection_name": injection, "qc_type": "Sample",
             "checks": list(REVIEW_CHECKS["Sample"])}]


def _surrogate_flags(q, injection):
    chk = [c for c in q.checks
           if c.injection_name == injection
           and c.check_name == "surrogate_recovery"]
    assert len(chk) == 1, ("surrogate_recovery is not on a Sample injection's "
                           "review checks", [c.check_name for c in q.checks])
    return chk[0]


# ── The list ─────────────────────────────────────────────────────────────────

def test_every_method_monitors_at_least_one_labelled_compound():
    """The original defect in one line: [] for both EPA methods."""
    for method in ("FDA_32PFAS", "EPA_537_1", "EPA_1633A"):
        names = mp.get_is_list(method)
        assert names, "{0} monitors no labelled compound".format(method)
        assert len(names) >= 10, (method, len(names))


def test_every_monitored_name_exists_as_a_service():
    """A name the instrument file can never contain is a check on nothing.

    This is the cross-reference the advisor called for and the reason the list
    is derived from surrogate_map (keywords from the reference table) rather
    than from a published method's own EIS designations: ten of EPA 1633A's
    Table 6 names exist as no AnalysisService at all.
    """
    universe = _service_universe()
    for method in ("FDA_32PFAS", "EPA_537_1", "EPA_1633A"):
        for name in mp.get_is_list(method):
            assert name in universe, (
                "{0} monitors {1!r}, which no AnalysisService is created "
                "under".format(method, name))


def test_the_injection_standard_is_in_the_list():
    """It belongs to the IS RESPONSE check (raw area), and it is the one
    compound whose area must NOT be dilution-corrected — so leaving it out
    would silently drop that distinction."""
    for method in ("FDA_32PFAS", "EPA_1633A"):
        names = set(mp.get_is_list(method))
        assert injection_is_names() & names, (method, sorted(names)[:5])


# ── The name join ────────────────────────────────────────────────────────────

def test_the_table_6_join_is_total_and_one_to_one():
    """24 surrogates, 24 Table 6 rows, no leftovers on either side.

    If this drifts, some compounds silently fall back to the generic window
    instead of their own limit — which is exactly the failure this replaced.
    """
    overrides = mp._profile_data_cache["EPA_1633A"]["eis_overrides"]
    keys = (set(overrides) if isinstance(overrides, dict)
            else {r["analyte"] for r in overrides})
    inj = injection_is_names()

    claimed = {}
    for name in mp.get_is_list("EPA_1633A"):
        if name in inj:
            continue
        key = mp.eis_criteria_name("EPA_1633A", name)
        assert key in keys, (
            "{0} joined to {1!r}, which is not a Table 6 row".format(name, key))
        claimed.setdefault(key, []).append(name)

    assert set(claimed) == keys, (
        "Table 6 rows matched by no surrogate", sorted(keys - set(claimed)))
    doubled = {k: v for k, v in claimed.items() if len(v) > 1}
    assert not doubled, ("two surrogates claim one Table 6 limit", doubled)


def test_a_method_with_no_overrides_is_identity():
    """FDA and 537.1 carry no eis_overrides; the join must not invent one."""
    for method in ("FDA_32PFAS", "EPA_537_1"):
        for name in mp.get_is_list(method)[:5]:
            assert mp.eis_criteria_name(method, name) == name


# ── Reach: the check actually runs on a run queue ─────────────────────────────

def test_a_failing_surrogate_recovery_reaches_the_review_check():
    """The whole point. A bad recovery must produce a flag AND fail the check."""
    inj = "260925-01"
    q, _ = _run([_row("13C3-PFPeA", inj, 2.0)], _sample_plan(inj))
    chk = _surrogate_flags(q, inj)
    # AUTO_FAIL is itself the proof that the flag carried KIND_SURROGATE:
    # auto_evaluate only fails a check whose flags' check_kind is in
    # _CHECK_KINDS[check_name], and for this check that set is {KIND_SURROGATE}.
    # A flag with no kind, or the wrong one, leaves the check PENDING.
    assert chk.status == CheckStatus.AUTO_FAIL, chk.status
    assert chk.flags, "failed with no flag attached"
    assert any("(REC)" in f["Issue"] for f in chk.flags), chk.flags


def test_a_good_surrogate_recovery_auto_passes():
    inj = "260925-02"
    q, _ = _run([_row("13C3-PFPeA", inj, 95.0)], _sample_plan(inj))
    chk = _surrogate_flags(q, inj)
    assert chk.status == CheckStatus.AUTO_PASS, chk.status
    assert not chk.flags, chk.flags


def test_the_per_analyte_limit_is_the_one_applied_not_the_generic_window():
    """The discriminator, and the only test here that can tell the name join
    apart from a plain lookup.

    EPA 1633A Table 6 floors PFBA's EIS at 5% and PFPeA's at 40%; the generic
    qc_acceptance.LFSM window floors both at 40%. The lab spells them 13C3-PFBA
    and 13C3-PFPeA, EPA spells them 13C4-PFBA and 13C5-PFPeA. At 20% recovery:

      * a name-based lookup misses both, applies 40-130 to each, fails BOTH
      * the native join applies 5-130 and 40-130, so PFBA passes, PFPeA fails
    """
    good, bad = "260925-03", "260925-04"
    plan = _sample_plan(good) + _sample_plan(bad)
    q, _ = _run([_row("13C3-PFBA", good, 20.0),
                 _row("13C3-PFPeA", bad, 20.0)], plan)

    assert _surrogate_flags(q, good).status == CheckStatus.AUTO_PASS, (
        "13C3-PFBA at 20% must pass: Table 6 floors PFBA's EIS at 5%, so a "
        "failure here means the generic 40% window was applied instead")
    assert _surrogate_flags(q, bad).status == CheckStatus.AUTO_FAIL, (
        "13C3-PFPeA at 20% must fail against its 40% floor")


def test_the_flag_names_the_compound_the_lab_spiked_not_epas():
    """A certificate has to name what is in the vial. The limit comes from
    Table 6; the identity does not."""
    inj = "260925-05"
    q, _ = _run([_row("13C3-PFPeA", inj, 2.0)], _sample_plan(inj))
    analytes = {f["Analyte"] for f in _surrogate_flags(q, inj).flags}
    assert analytes == {"13C3-PFPeA"}, analytes


def test_the_injection_standard_gets_no_recovery_check():
    """It is added at reconstitution, after extraction: there is no recovery to
    measure, so a number against a recovery window would be meaningless."""
    inj = "260925-06"
    q, _ = _run([_row("13C4-PFOA", inj, 1.0)], _sample_plan(inj))
    chk = _surrogate_flags(q, inj)
    assert not chk.flags, ("the injection standard was given a recovery flag",
                           chk.flags)
    assert chk.status != CheckStatus.AUTO_FAIL, chk.status


def test_a_calibrator_is_never_given_a_surrogate_recovery_check():
    """A calibration standard is not extracted, so it has no recovery."""
    assert "surrogate_recovery" not in REVIEW_CHECKS["CAL"]
    assert "surrogate_recovery" not in REVIEW_CHECKS["CCV"]
    assert "surrogate_recovery" not in REVIEW_CHECKS["ICV"]
    assert "surrogate_recovery" not in REVIEW_CHECKS["CCB"], (
        "CCB is a solvent blank — nothing was extracted into it")
    for extracted in ("Sample", "LFSM", "LFSMD", "Dup", "LFB", "MB", "MxB",
                      "LRB"):
        assert "surrogate_recovery" in REVIEW_CHECKS[extracted], extracted


def test_a_row_with_no_recovery_column_stays_pending_not_passed():
    """An export without the % recovery column must not read as a pass."""
    inj = "260925-07"
    q, _ = _run([_row("13C3-PFPeA", inj, None)], _sample_plan(inj))
    chk = _surrogate_flags(q, inj)
    assert chk.status == CheckStatus.PENDING, chk.status


def test_both_epa_methods_evaluate_a_surrogate_recovery():
    """§19 was 'no IS check runs on EITHER EPA method'. Both, explicitly."""
    for method, matrix, compound in (("EPA_537_1", "Drinking Water",
                                      "13C3-PFHxS"),
                                     ("EPA_1633A", "Wastewater",
                                      "13C3-PFPeA")):
        inj = "260925-{0}".format(method)
        q, _ = _run([_row(compound, inj, 1.0)], _sample_plan(inj),
                    method_id=method, matrix=matrix)
        chk = _surrogate_flags(q, inj)
        assert chk.status == CheckStatus.AUTO_FAIL, (method, chk.status)


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
