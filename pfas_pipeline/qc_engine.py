"""
QC Engine — the instrument-level checks, each against the method profile's
configured criteria (a criterion the method leaves unset raises
UnconfiguredCriterion: not judged, and the gap holds release):

  IS response      → is_raw_check()
  RT deviation     → rrt_check_profiled()
  Ion ratio        → qual_quan_check()
  Calibration      → calibration_check_profiled()
  S/N              → signal_to_noise_check()
  LFSM / LFSMD     → evaluated in run_queue.auto_evaluate()
"""

from __future__ import annotations
import json
import statistics
from typing import Optional

from .constants import IS_PEAK_DELETED, MANUAL_DROP_REASONS, QUALIFIER_BLOQ, QUALIFIER_ND
from .models import reported_conc
from .models import (
    InstrumentRow,
    QCFlag,
    ISRawResult,
    RTResult,
    QualQuanResult,
    CalibrationResult,
)

# ─────────────────────────────────────────────────────────────────────────────
# Check identities: WHICH check raised a flag, independent of the display
# `source` string. The review queue matches on these, never on display text.
# ─────────────────────────────────────────────────────────────────────────────
KIND_IS_RESPONSE = "is_response"
KIND_RT          = "rt"
KIND_ION_RATIO   = "ion_ratio"
KIND_CALIBRATION = "calibration"
KIND_CCV         = "ccv"
KIND_SN          = "sn"
KIND_LFSM        = "lfsm"
KIND_LFSMD       = "lfsmd"
# Recovery of a labelled compound added BEFORE extraction. Distinct from
# KIND_IS_RESPONSE, which is the same compound's raw peak area against the ICAL
# average: a surrogate can hold its area and still fail recovery, and vice
# versa, so one kind could not stand for both.
KIND_SURROGATE   = "surrogate"
# Every Rule Toggles switch changes something
KIND_BLANK       = "blank"
KIND_LCS         = "lcs"
KIND_CCV_FREQ    = "ccv_frequency"
KIND_MDL         = "mdl"
KIND_DUP         = "dup"
KIND_OVER_RANGE  = "over_range"   # above the top calibration level (pipeline.over_range)
# a raw run's native with no concentration: its isotope standard's peak deleted (raw_is_deleted)
KIND_IS_DELETED  = "is_deleted"
# a raw run's native whose linked response ratio could not be formed
# (raw_run.linked_standard; ratio_held)
KIND_RATIO_HELD = "linked_ratio_held"
# a calibrator on the curve with no reading: why its point fails
CAL_NOT_READ = "not read on the curve"
CAL_NO_CONCENTRATION = "the instrument reported no concentration"
# the instrument's word a standard's row loses (pipeline.standard_tokens)
STANDARD_TOKENS = ("ALoQ", "BLoQ")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def raw_no_reading(row) -> Optional[str]:
    """A raw run's row with no concentration: its qualifier, BLoQ or N.D.;
    None for a row with a number or a vendor export's row. A spiked or check
    standard row with no reading is judged at 0 % recovery."""
    if row is None or not (getattr(row, "derived_from", "") or "").startswith("raw:"):
        return None
    if reported_conc(row) is not None:
        return None
    qualifier = getattr(row, "conc_qualifier", "") or ""
    return qualifier if qualifier in (QUALIFIER_BLOQ, QUALIFIER_ND) else None


def check_no_reading(row) -> Optional[str]:
    """A check standard's row (ICV, CCV) with no concentration, raw or
    vendor: what it reads instead (BLoQ, N.D., N.Q., or "no concentration");
    None for a row with a number. A check standard is judged against its
    window, so one with no number fails it instead of being skipped."""
    if row is None or getattr(row, "calculated_conc", None) is not None or reported_conc(row) is not None:
        return None
    return getattr(row, "conc_qualifier", "") or "no concentration"


def _raw_record(row) -> dict:
    """A raw run's row record (its derived_from); {} for any other row."""
    derived = getattr(row, "derived_from", "") or ""
    if not derived.startswith("raw:"):
        return {}
    try:
        rec = json.loads(derived[len("raw:"):])
    except ValueError:
        return {}
    return rec if isinstance(rec, dict) else {}


def raw_is_deleted(rows) -> list[QCFlag]:
    """A failing flag for each analyte of a raw run left with no
    concentration because the analyst deleted the peak of the isotope
    standard it is quantified on, in that injection (its record's
    quant.is_deleted): a native, or a labelled standard quantified on an
    injection standard (its recovery then unjudged). The QC store files each
    as a failing QC result, so release waits for it whatever rule switch is
    set. A calibrator is not flagged here: it comes off its curve, which
    names it. A standard merely not detected is not this check's."""
    flags = []
    for r in rows or []:
        quant = _raw_record(r).get("quant") or {}
        if not quant.get("is_deleted") or r.sample_type == "Standard":
            continue
        flags.append(QCFlag(
            source="Isotope standard", check_kind=KIND_IS_DELETED, analyte=r.compound_name,
            injection_name=r.injection_name, value=quant.get("is") or "",
            issue="%s: not quantified, %s in %s" % (r.compound_name, IS_PEAK_DELETED, r.injection_name)))
    return flags


def ratio_held(rows) -> list[QCFlag]:
    """A failing flag for each raw result held because the method reads it
    on the linked response ratio and the ratio could not be formed (the
    row's ratio_held names why: no Linked to, members linked to different
    internal standards, the internal standard not detected). The QC store
    files each as a failing QC result, so release waits for it whatever
    rule switch is set."""
    flags = []
    for r in rows or []:
        why = getattr(r, "ratio_held", "") or ""
        if not why:
            continue
        flags.append(QCFlag(
            source="Linked response ratio", check_kind=KIND_RATIO_HELD, analyte=r.compound_name,
            injection_name=r.injection_name, value="",
            issue="%s: held, %s" % (r.compound_name, why)))
    return flags


def no_reading_issue(tag, qualifier):
    return "({0}) no reading: {1}".format(tag, qualifier)


def _format_val(v: Optional[float]) -> str:
    if v is None:
        return QUALIFIER_ND
    return f"{v:.6g}"


# ─────────────────────────────────────────────────────────────────────────────
# IS response
#   ratio = response_ratio / mean(response_ratio of the calibration standards
#           for that compound); "N.D." when there is no response
# ─────────────────────────────────────────────────────────────────────────────

# what a window records for a tier in the state Off
TIER_OFF_BASIS = "not judged: its tier is Off"


def _box_state(profile, key):
    """A limit box's state on the method (MethodProfile.limit_state);
    Enforced without a method."""
    get = getattr(profile, "limit_state", None) if profile is not None else None
    return get(key) if get is not None else "enforced"


def _advisory_of(profile, boxes):
    """A flag raised by failures judged in `boxes` is advisory only when
    every one of them is in the state Evaluate."""
    states = [_box_state(profile, b) for b in boxes]
    return bool(states) and all(st == "evaluate" for st in states)


def is_raw_check(
    rows: list[InstrumentRow],
    is_compound: str,
    dilutions: "dict | None" = None,
    method_id: str = "",
    matrix: str = "",
) -> list[ISRawResult]:
    """
    Labelled-compound PEAK AREA against the ICAL average (the profile's
    ``is_response: vs_ical_avg``).

    Dilution is handled by ROLE, not by injection type:

      * a SURROGATE (extracted internal standard) is added before extraction
        and diluted with the sample: its area is scaled back by the recorded
        factor before comparison.

      * the INJECTION INTERNAL STANDARD is added at reconstitution, AFTER the
        dilution: it is compared as measured, and a drop is a real finding.

    Roles come from the method, else the AnalysisService's `pfas_role`.
    """
    from .analyte_alias import injection_is_names, keyword_for
    from .method_profiles import get_surrogate_is_chain

    dilutions = dilutions or {}
    # The METHOD decides which labelled compound is the injection standard.
    # surrogate_is_chain maps each surrogate to the IS it is quantified
    # against, so a compound that appears only as a VALUE is the injection
    # standard and every KEY is a surrogate. The compound library's global
    # roles are the fallback: not method-scoped, and under a method that uses a
    # different injection standard it would scale the wrong compound.
    from .method_profiles import get_labelled_roles
    roles = get_labelled_roles(method_id) if method_id else {}
    chain = get_surrogate_is_chain(method_id) if method_id else {}
    if roles:
        # The method's grid names each standard's role outright;
        # no inference from the chain needed.
        keyword = keyword_for(is_compound) or is_compound
        is_injection_standard = roles.get(keyword) == "injection_is"
    elif chain:
        keyword = keyword_for(is_compound) or is_compound
        surrogates = {keyword_for(k) or k for k in chain}
        injection_stds = {keyword_for(v) or v for v in chain.values()}
        is_injection_standard = (keyword in injection_stds
                                 and keyword not in surrogates)
    else:
        is_injection_standard = is_compound in injection_is_names()

    def corrected(row):
        """Area, undiluted-equivalent. A dilution made at the bench records
        how each labelled standard was handled (is_handling / sur_handling:
        not_added, topped_up, added): one not added was diluted with the
        extract, so its area is read at 1 / fold and scaled back; one added or
        topped up is read as measured. Without a record: a surrogate is
        scaled, the injection IS read as measured (added after dilution)."""
        if row.response is None:
            return None
        entry = dilutions.get(row.injection_name)
        if not entry:
            return row.response
        factor = entry.get("factor")
        handling = entry.get("is_handling" if is_injection_standard else "sur_handling") or ""
        if handling == "not_added":
            scale = True
        elif handling in ("added", "topped_up"):
            scale = False
        else:
            scale = not is_injection_standard
        return row.response * factor if (scale and factor) else row.response

    from .importer import classify_injection
    # Judged in ACQUISITION order: "the most recent CCC" is the CCC that
    # opened this injection's bracket, whatever order the export lists rows
    # in. Undated rows keep their file order, after the dated ones.
    mine = [r for r in rows if r.compound_name == is_compound]
    mine = [r for _i, r in sorted(enumerate(mine), key=lambda p: (
        p[1].acquisition_datetime is None, p[1].acquisition_datetime or 0, p[0]))]
    # The ICAL average is the CALIBRATORS' (EPA 537.1 §9.3.4): by the run's
    # roles, not by the export's "Standard" sample type, which some software
    # also gives a CCC. The sample type is the fallback for a run with no
    # roles recorded.
    std_rows = calibrator_rows(mine, is_compound, lambda r: r.response is not None)
    if not std_rows:
        return []
    avg_response = statistics.mean(r.response for r in std_rows)
    if not avg_response:
        return []

    # Limits from the METHOD: the ICAL-average window and, where the method
    # sets one, EPA 537.1 §9.3.4's second window against the bracket's CCV.
    rule = None
    prof = None
    if method_id:
        from .method_profiles import get_profile
        prof = get_profile(method_id)
        rule = prof.is_rule()

    def judge(pct):
        """The % judged as the report states it: a whole percent by the
        method's rule; without a method, the default rule."""
        if prof is not None:
            return prof.judged_pct(pct, matrix)
        from .addon import load
        return load("rounding").judged_pct(pct)
    # each window is its own box (limit_states): one that is Off reads
    # None here; an empty one is filed once by the run queue (Enforced
    # refuses, Evaluate advises), and its results are stored not evaluated
    lo = rule.vs_ical_avg_min if rule else None
    hi = rule.vs_ical_avg_max if rule else None
    configured = lo is not None and hi is not None
    ccv_lo = rule.vs_last_ccv_min if rule else None
    ccv_hi = rule.vs_last_ccv_max if rule else None
    ical_evaluate = _box_state(prof, "is_response") == "evaluate"
    ccv_evaluate = _box_state(prof, "is_vs_ccv") == "evaluate"
    # an unset window against the ICAL average holds release (stored not
    # evaluated) only while its box is Enforced; Off, or Evaluate (its gap
    # filed as an advisory), a result no window judged is not recorded
    ical_owed = _box_state(prof, "is_response") == "enforced" if prof is not None else True

    results: list[ISRawResult] = []
    last_ccv_response = None
    for r in mine:
        value = corrected(r)
        pct_from_cal = None
        judged = None
        flag = None
        by_ccv = False                # judged against the bracket's CCV
        if value is not None:
            pct_from_cal = value / avg_response
            judged = judge(pct_from_cal * 100.0)
            fails = []
            fail_evaluate = []      # per failure: its rule is in the state Evaluate
            # judged only against a window the METHOD sets; without one the
            # result is stored "not evaluated"
            if configured and not (lo <= judged <= hi):
                fails.append("{0:.0f}% of ICAL average (limit {1:g}-{2:g}%)"
                             .format(judged, lo, hi))
                fail_evaluate.append(ical_evaluate)
            # 537.1's second condition. Only applied once a CCV has been seen,
            # and only when the method configures the window.
            if ccv_lo is not None and ccv_hi is not None and last_ccv_response:
                by_ccv = True
                pct_ccv = judge(value / last_ccv_response * 100.0)
                if not (ccv_lo <= pct_ccv <= ccv_hi):
                    fails.append(
                        "{0:.0f}% of the bracket's CCV (limit {1:.0f}-{2:.0f}%)".format(
                            pct_ccv, ccv_lo, ccv_hi))
                    fail_evaluate.append(ccv_evaluate)
            if fails:
                note = ""
                if r.injection_name in dilutions:
                    note = (" (injection IS — not diluted)"
                            if is_injection_standard
                            else " (surrogate, dilution-corrected)")
                flag = QCFlag(
                    source="SUR-IS Response Table",
                check_kind=KIND_IS_RESPONSE,
                    analyte=is_compound,
                    injection_name=r.injection_name,
                    value="; ".join(fails) + note,
                    issue="(SUR)",
                    # advisory only when every rule that failed is Evaluate
                    advisory=all(fail_evaluate),
                )
        if value and classify_injection(r.injection_name) == "CCV":
            last_ccv_response = value
        if not configured and not ical_owed and not by_ccv:
            continue                  # judged by no window, and owed none

        results.append(ISRawResult(
            is_compound=is_compound,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            response=value,
            pct_from_cal=pct_from_cal,
            average_response=avg_response,
            flag=flag,
            window_min=lo, window_max=hi, configured=configured or not ical_owed, judged_pct=judged,
            ccv_min=ccv_lo, ccv_max=ccv_hi,
            std_role="injection_is" if is_injection_standard else "surrogate",
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Ion ratio (qualifier / quantifier)
#   ratio relative to the calibrators' mean; flagged outside the method's
#   tolerance (a method-profile setting)
# ─────────────────────────────────────────────────────────────────────────────


_NOT_CALCULATED = ("not calculated", "n.c.", "nc")


def _parts(v):
    """A pipe-separated cell, one entry per qualifier ion: a float, the
    marker "uncalculable", or None."""
    if v is None:
        return []
    out = []
    for part in str(v).split("|"):
        part = part.strip()
        if part.lower() in _NOT_CALCULATED:
            out.append("uncalculable")
            continue
        try:
            out.append(float(part))
        except (TypeError, ValueError):
            out.append(None)
    return out


def observed_ratios(r):
    """Each qualifier ion's observed ratio: the ratio column, else qualifier
    response / quantifier response (the same number)."""
    obs, resp = _parts(r.ion_ratios), _parts(getattr(r, "qual_ions_responses", None))
    quan = r.response
    out = []
    for i in range(max(len(obs), len(resp))):
        o = obs[i] if i < len(obs) else None
        if not isinstance(o, float):
            q = resp[i] if i < len(resp) else None
            if isinstance(q, float) and quan:
                o = q / quan
        out.append(o)
    return out


EXPECTED_SOURCES = (("expected_ion_ratios", ""), ("quan_ref_expected_ion_ratios", "quantitation reference"),
                    ("method_expected_ion_ratios", "method"))
# the expected ratio's last source, the mean of the run's calibrators; each
# source as the Raw Data card names it
CALIBRATORS_SOURCE = "this run's calibrators"
ION_SOURCE_WORDS = {"": "export", "quantitation reference": "quantitation reference", "method": "method",
                    CALIBRATORS_SOURCE: "calibrators"}


def expected_ratios(r, calibrators=None):
    """[(expected, source)] per qualifier ion, first present of: Expected Ion
    Ratios, the quantitation reference's, the method's, then the mean ratio of
    this run's calibrators (`calibrators` = [means per ion])."""
    cols = [_parts(getattr(r, name, None)) for name, _src in EXPECTED_SOURCES]
    n = max([len(c) for c in cols] + [len(calibrators or [])])
    out = []
    for i in range(n):
        got = (None, "")
        for c, (_name, src) in zip(cols, EXPECTED_SOURCES):
            v = c[i] if i < len(c) else None
            if isinstance(v, float) and v:
                got = (v, src)
                break
        if got[0] is None and calibrators and i < len(calibrators) and calibrators[i]:
            got = (calibrators[i], CALIBRATORS_SOURCE)
        out.append(got)
    return out


def _off_the_curve(r):
    """A raw run's calibrator the curve left out (no reading, or a peak the
    analyst deleted): not a calibrator of this run. A vendor export's "Used" column is not read
    here -- an export without one says False for every row."""
    return (getattr(r, "derived_from", "") or "").startswith("raw:") and not r.included_in_cal


def calibrator_rows(rows, analyte, keep=None, off_curve=False):
    """The run's calibrators of an analyte: by their role in the run plan
    (CAL), whatever word the export uses for them; the export's "Standard"
    only for a run with no role recorded. A calibrator a raw run left off
    its curve is judged nowhere as one, but for the lowest level's S/N
    (`off_curve` keeps it)."""
    from .importer import classify_injection
    mine = [r for r in rows if r.compound_name == analyte and (keep is None or keep(r))
            and (off_curve or not _off_the_curve(r))]
    by_role = [r for r in mine if classify_injection(r.injection_name) == "CAL"]
    return by_role or [r for r in mine if r.sample_type == "Standard"]


def calibrator_ratio_means(rows, analyte, counts=False):
    """Mean observed ratio per qualifier ion over the run's calibrators;
    with `counts`, (means, the calibrators each mean was taken over)."""
    sums = {}
    for r in calibrator_rows(rows, analyte):
        for i, o in enumerate(observed_ratios(r)):
            if isinstance(o, float):
                sums.setdefault(i, []).append(o)
    n = max(sums) + 1 if sums else 0
    means = [(sum(sums[i]) / len(sums[i])) if i in sums else None for i in range(n)]
    if counts:
        return means, [len(sums.get(i, ())) for i in range(n)]
    return means


def ion_lines(r, exp, n_cal):
    """Each qualifier ion of a row: its observed ratio, the expected one, the
    expected ratio's source in the card's words and, for the mean of this
    run's calibrators, how many calibrators it was taken over."""
    obs = observed_ratios(r)
    out = []
    for i in range(max(len(obs), len(exp))):
        e, src = exp[i] if i < len(exp) else (None, "")
        out.append({"observed": obs[i] if i < len(obs) else None, "expected": e,
                    "source": ION_SOURCE_WORDS[src] if e is not None else "",
                    "n_cal": (n_cal[i] if i < len(n_cal) else 0) if src == CALIBRATORS_SOURCE else 0})
    return out


def qual_quan_check(
    rows: list[InstrumentRow],
    analyte: str,
    tol_pct: float,
) -> list[QualQuanResult]:
    """
    Ion-ratio confirmation: the OBSERVED qualifier/quantifier ratio against the
    EXPECTED one, within the method's tolerance. Never ``response_ratio``
    (analyte area over IS area), which tracks concentration. Rows carrying no
    ratio data are left unjudged, never passed.
    """
    tol = tol_pct / 100.0

    results: list[QualQuanResult] = []
    cal_means, n_cal = calibrator_ratio_means(rows, analyte, counts=True)
    for r in [row for row in rows if row.compound_name == analyte]:
        # observed: the ratio column, else qualifier / quantifier response;
        # expected: the first column the export fills, else the calibrators'
        # mean
        exp = expected_ratios(r, cal_means)
        ions = ion_lines(r, exp, n_cal)
        pairs, sources = [], []
        for o, (e, src) in zip(observed_ratios(r), exp):
            if o is not None and (e not in (None, 0) or o == "uncalculable"):
                pairs.append((o, e))
                sources.append(src)
        source = next((s for s in sources if s), "")
        flag = None
        worst = None

        if not pairs:
            # No ion-ratio data for this row — say nothing rather than pass it.
            results.append(QualQuanResult(
                analyte=analyte, injection_name=r.injection_name,
                concat_id=r.concat_id, response_ratio=None,
                avg_response_ratio=None, pct_of_cal=None, flag=None, ions=ions))
            continue

        uncalculable = any(o == "uncalculable" for o, _e in pairs)
        for obs, exp in pairs:
            if obs == "uncalculable":
                continue
            dev = obs / exp
            if worst is None or abs(dev - 1.0) > abs(worst - 1.0):
                worst = dev
        if worst is None:
            worst = 1.0

        if uncalculable:
            # "Not calculated" means the qualifier ion was too small to
            # integrate. That is a confirmation FAILURE when the analyte was
            # actually detected — and nothing at all when it was not, because
            # there is no peak to confirm. The instrument draws exactly this
            # distinction: Fail on a detection, N/A on a blank.
            detected = (reported_conc(r) is not None
                        or getattr(r, "conc_qualifier", "") in ("BLoQ", "ALoQ"))
            if not detected:
                results.append(QualQuanResult(
                    analyte=analyte, injection_name=r.injection_name,
                    concat_id=r.concat_id, response_ratio=None,
                    avg_response_ratio=None, pct_of_cal=None, flag=None, ions=ions))
                continue
            flag = QCFlag(
                source="Qual-Quan Table",
                check_kind=KIND_ION_RATIO, analyte=analyte,
                injection_name=r.injection_name,
                value="qualifier ion not calculable", issue="(QQ)",
            )
        elif abs(worst - 1.0) > tol:
            flag = QCFlag(
                source="Qual-Quan Table",
                check_kind=KIND_ION_RATIO, analyte=analyte,
                injection_name=r.injection_name,
                value="{0:+.1f}% from expected ion ratio{1}".format(
                    (worst - 1.0) * 100.0, " ({0})".format(source) if source else ""),
                issue="(QQ)",
            )

        results.append(QualQuanResult(
            analyte=analyte,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            response_ratio=(pairs[0][0] if pairs[0][0] != "uncalculable" else None),
            avg_response_ratio=(pairs[0][1] if pairs[0][1] not in (None, 0) else None),
            pct_of_cal=worst,
            flag=flag,
            ions=ions,
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Signal-to-Noise check  (Signal-to-Noise sheet)
# ─────────────────────────────────────────────────────────────────────────────

def qualifiers_deleted(r):
    """The qualifier transitions whose peak the analyst deleted on a raw
    run's row (its record's qual_deleted); [] for any other row."""
    return list(_raw_record(r).get("qual_deleted") or [])


# the remark token on a result whose quantifier peak was split from its
# co-eluting partner (coelution_split): the QAO's "coelution" qualifier marks it
COELUTION_FLAG = "COELUTION"
# the worker's note on a pair whose fit failed (raw_run.PAIR_FIT_FAILED)
PAIR_FIT_FAILED = "pair fit failed"
# the lines a hand-drawn peak is split from its neighbour on
SPLIT_LINES = ("drop", "skim")


def _on_pair(rec) -> bool:
    """The peak record was measured as a co-eluting pair: by the pair's fit,
    or as a single peak where that fit failed."""
    return rec.get("area_method") == "pair" or (rec.get("fit_note") or "").startswith(PAIR_FIT_FAILED)


def coelution_split(r) -> bool:
    """True when a raw run's row holds a detected peak split from its
    co-eluting partner, so its value is an estimate: measured by the pair's
    fit (raw_integrate.integrate_pair: two exponentially modified Gaussians
    on one baseline), measured as a single peak where that fit failed, or
    drawn by the analyst on a perpendicular drop or a tangent skim where the
    automatic peak was the pair's. Any other line drawn by hand, or another
    apex chosen as found, splits nothing from the neighbour."""
    rec = _raw_record(r)
    if rec.get("area") is None:
        return False
    if rec.get("manual"):
        return _on_pair(rec.get("auto") or {}) and rec.get("baseline") in SPLIT_LINES
    return _on_pair(rec)


# the remark token on a result whose quantifier peak was separated by curve
# fitting (fitted_estimate): the QAO's "fitted" qualifier marks it
FITTED_FLAG = "FITTED"


def fitted_estimate(r) -> bool:
    """True when a raw run's row holds a detected quantifier peak measured by
    a curve fit, so its value is an estimate: the row's own record carries
    the fit and an area, whether the analyst fitted this one injection or a
    processing change fitted every injection. A fitted peak under the
    detection floor keeps its fit's record but has no area, and is not
    marked; a fit on a qualifier ion only sits in the qualifier's own
    record, and a hand-drawn peak's fitted automatic peak in "auto", so
    neither marks the result."""
    rec = _raw_record(r)
    return rec.get("area") is not None and bool(rec.get("fit"))


def qualifier_deleted_check(rows: list[InstrumentRow], analyte: str) -> list[QCFlag]:
    """N.C. for each raw run row of the analyte with a qualifier the analyst
    deleted (qualifiers_deleted): a deleted confirmation ion confirms
    nothing, whatever limit the method sets on the qualifier S/N and
    whatever the S/N rule's switch or state, so it is judged on every run
    and never advisory. An estimated quantifier (J) beside it is still N.C."""
    flags: list[QCFlag] = []
    for r in rows:
        deleted = qualifiers_deleted(r) if r.compound_name == analyte else []
        if deleted:
            flags.append(QCFlag(
                source="Signal-to-Noise",
                check_kind=KIND_SN,
                analyte=analyte,
                injection_name=r.injection_name,
                value="qualifier deleted: " + ", ".join(deleted),
                issue="(N.C.)",
            ))
    return flags


def signal_to_noise_check(rows: list[InstrumentRow], analyte: str,
                          quan_min, confirm_min) -> list[QCFlag]:
    """Judge the QUANTITATION ion and the CONFIRMATION ion on their own limits
    (the method's ConfirmationRule):

      * quantitation ion below `quan_min` -> the peak is there but the value
        is an estimate, "(J)" (the `sn` failure type's code), filed only
        for a row with a number: an estimate needs a value, and a row with
        none (BLoQ, N.D.) carries no J;
      * qualifier ion below `confirm_min` -> the identification is not
        confirmed, "(N.C.)". It is never judged on the quantitation limit.

    A limit given as None is not judged here; the run queue files the gap.
    """
    flags: list[QCFlag] = []
    for r in rows:
        if r.compound_name != analyte:
            continue
        sn = r.signal_to_noise
        qual_sn = r.qual_sn
        if sn is not None and quan_min is not None and sn < quan_min:
            if reported_conc(r) is None:
                continue
            flags.append(QCFlag(
                source="Signal-to-Noise",
                check_kind=KIND_SN,
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{sn:.2f}",
                issue="(J)",
            ))
        elif qualifiers_deleted(r):
            # already N.C. on its own, always (qualifier_deleted_check): the
            # S/N of a qualifier left adds nothing
            pass
        elif (qual_sn is not None and confirm_min is not None
                and qual_sn < confirm_min):
            flags.append(QCFlag(
                source="Signal-to-Noise",
                check_kind=KIND_SN,
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{qual_sn:.2f}",
                issue="(N.C.)",
            ))
    return flags


# ═════════════════════════════════════════════════════════════════════════════
# Method-profile-aware checks
# ═════════════════════════════════════════════════════════════════════════════

from .method_profiles import MethodProfile


def recovery_check_profiled(
    profile: MethodProfile,
    analyte: str,
    matrix: str,
    qc_type: str,
    recovery_pct: float,
    injection_name: str = "",
    conc: Optional[float] = None,
    rl: Optional[float] = None,
    window: Optional[dict] = None,
    rule=None,
) -> Optional[QCFlag]:
    """
    Resolve recovery limits via the method profile and flag if outside.
    `window`, when given, receives the window applied ({lo, hi, basis,
    low_level: whether it is a low-level tier's}):
    Data Review shows each result against the criterion it was judged by.
    `rule`, when given, is the rule already resolved for this row (a
    labelled standard in a CCV judged with the CCV window).
    Handles FDA's three-tier (analyte × matrix) table automatically:
      PFOA in deer muscle  → 80–120%
      PFOA in feed         → 65–135%
      PFTrDA anywhere      → 40–140%
    """
    resolved = rule is not None
    if rule is None:
        rule = (profile.qc_rules(analyte, matrix, qc_type, conc=conc, rl=rl)
                if conc is not None or rl is not None else profile.qc_rules(analyte, matrix, qc_type))
    if rule is None or rule.recovery_min is None:
        return None
    # the tier's own state (limit_states): Off is not judged, Evaluate files
    # its failure as advisory
    state = getattr(rule, "state", "enforced")
    if window is not None:
        low = getattr(profile, "low_level_tier_applies", None)
        low_level = bool(not resolved and low is not None and low(analyte, matrix, qc_type, conc=conc, rl=rl))
        window.update(lo=rule.recovery_min, hi=rule.recovery_max,
                      basis="{0} recovery {1:g}-{2:g} %".format(
                          qc_type, rule.recovery_min, rule.recovery_max),
                      low_level=low_level, state=state)
    if state == "off":
        if window is not None:
            window.update(lo=None, hi=None, basis=TIER_OFF_BASIS)
        return None
    # judged as the report states it: at the method's decimal places for
    # recoveries by its rule, computed from the full-precision recovery
    judged = profile.judged_recovery(recovery_pct, matrix)
    if rule.recovery_min <= judged <= rule.recovery_max:
        return None
    shown = profile.recovery_text(judged)
    issue = f"(REC) {shown}% outside " \
            f"{rule.recovery_min:g}–{rule.recovery_max:g}%"
    return QCFlag(
        source=f"{profile.method_id} {qc_type}",
        analyte=analyte,
        injection_name=injection_name,
        value=f"{shown}%",
        issue=issue + (f" — {rule.notes}" if rule.notes else ""),
        advisory=state == "evaluate",
    )


def rpd_check_profiled(
    profile: MethodProfile,
    analyte: str,
    matrix: str,
    qc_type: str,
    rpd_pct: float,
    injection_name: str = "",
    conc: Optional[float] = None,
    rl: Optional[float] = None,
    window: Optional[dict] = None,
) -> Optional[QCFlag]:
    """Duplicate / LFSMD RPD against the profile limit (FDA dup: 20%).
    `window` receives the limit applied ({lo: None, hi, basis})."""
    rule = (profile.qc_rules(analyte, matrix, qc_type, conc=conc, rl=rl)
            if conc is not None or rl is not None else profile.qc_rules(analyte, matrix, qc_type))
    if rule is None:
        return None
    limit = rule.rpd_max
    if limit is None:
        return None
    state = getattr(rule, "state", "enforced")
    if window is not None:
        window.update(lo=None, hi=limit, basis="{0} RPD \u2264 {1:g} %".format(qc_type, limit), state=state)
    if state == "off":
        if window is not None:
            window.update(hi=None, basis=TIER_OFF_BASIS)
        return None
    # the RPD comes from unrounded values; it is JUDGED as a whole percent
    judged = profile.judged_pct(rpd_pct, matrix)
    if judged <= limit:
        return None
    return QCFlag(
        source=f"{profile.method_id} {qc_type}",
        analyte=analyte,
        injection_name=injection_name,
        value=f"RPD={judged:.0f}%",
        issue=f"(RPD) exceeds {limit:g}% — {rule.notes}",
        advisory=state == "evaluate",
    )


# Spikes of one QC type at one level, at least this many, are judged for
# precision by the RSD of their recoveries, not by a pair's RPD: two values
# give no standard deviation an RPD does not already state.
RSD_MIN_SPIKES = 3


def rsd_pct(values) -> Optional[float]:
    """The sample relative standard deviation (n - 1) of `values`, as a
    percent of their mean; None for fewer than two values or a mean of 0."""
    values = [float(v) for v in values or []]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if not mean:
        return None
    return statistics.stdev(values) / abs(mean) * 100.0


def rsd_check_profiled(
    profile: MethodProfile,
    analyte: str,
    matrix: str,
    qc_type: str,
    precision_type: str,
    rsd: float,
    injection_name: str = "",
    conc: Optional[float] = None,
    rl: Optional[float] = None,
    window: Optional[dict] = None,
) -> Optional[QCFlag]:
    """The RSD of several `qc_type` spikes' recoveries against the method's
    RPD limit of `precision_type` (an LFSM's: the LFSMD's): one limit, never a
    separate setting. `window` receives the limit applied ({lo: None, hi,
    basis}); untouched when no limit is set (nothing judged)."""
    rule = (profile.qc_rules(analyte, matrix, precision_type, conc=conc, rl=rl)
            if conc is not None or rl is not None else profile.qc_rules(analyte, matrix, precision_type))
    if rule is None or rule.rpd_max is None:
        return None
    limit = rule.rpd_max
    state = getattr(rule, "state", "enforced")
    if state == "off":
        return None                   # its tier is Off: not judged
    if window is not None:
        window.update(lo=None, hi=limit, basis="{0} RSD \u2264 {1:g} % (the {2} RPD limit)".format(
            qc_type, limit, precision_type), state=state)
    judged = profile.judged_pct(rsd, matrix)
    if judged <= limit:
        return None
    return QCFlag(
        source=f"{profile.method_id} {qc_type}",
        analyte=analyte,
        injection_name=injection_name,
        value=f"RSD={judged:.0f}%",
        issue=f"(RSD) exceeds {limit:g}%" + (f" — {rule.notes}" if rule.notes else ""),
        advisory=state == "evaluate",
    )


def ccv_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
    matrix: str = "",
    verdicts: "list | None" = None,
) -> list[QCFlag]:
    """
    CCV recovery per profile (FDA 70–130%; 537.1 70–130% with 50–150% at the
    lowest CCC level).  Uses calculated vs expected concentration.

    `verdicts`, when given, receives every CCV judged -- passing or not -- so
    the run's QC results carry them and Data Review's gate judges them.
    """
    rule = profile.ccv_rule()
    flags: list[QCFlag] = []
    # by ROLE (the Run Builder's record, else the name tokens): EPA 537.1
    # calls its CCVs CCC
    from .importer import classify_injection
    ccv_rows = [r for r in rows
                if r.compound_name == analyte
                and classify_injection(r.injection_name) == "CCV"]
    for r in ccv_rows:
        missing = check_no_reading(r) if r.expected_conc else None
        if not r.expected_conc or (r.calculated_conc is None and missing is None):
            continue
        # judged at the method's decimal places for recoveries by its rule;
        # a CCV with no reading, raw or vendor, at 0 %
        if _low_level_off(profile, r, analyte, matrix):
            continue                     # CCV Low-Level Off: not judged at all
        rec = profile.judged_recovery(0.0 if missing else r.calculated_conc / r.expected_conc * 100.0, matrix)
        lo, hi = _ccv_window(profile, rule, r, analyte, matrix)
        ok = lo <= rec <= hi and not missing
        why = (no_reading_issue("CCV", missing) if missing
               else "(CCV) outside {0:g}-{1:g}%".format(lo, hi))
        low = (lo, hi) != (rule.recovery_min, rule.recovery_max)
        # filed by the box whose window judged it
        advisory = _advisory_of(profile, ["ccv_low_level" if low else "ccv_recovery"])
        if verdicts is not None:
            verdicts.append({"analyte": analyte, "injection_name": r.injection_name,
                             "concat_id": getattr(r, "concat_id", "") or r.injection_name,
                             "calculated": r.calculated_conc, "expected": r.expected_conc,
                             "recovery": rec, "passed": ok, "lo": lo, "hi": hi,
                             "basis": "CCV recovery {0:g}-{1:g} %{2}".format(
                                 lo, hi, " (lowest level)" if low else ""),
                             "issue": "" if ok else why, "advisory": advisory})
        if not ok:
            flags.append(QCFlag(
                source=f"{profile.method_id} CCV",
                check_kind=KIND_CCV,
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{profile.recovery_text(rec)}%",
                issue=(no_reading_issue("CCV", missing) if missing else f"(CCV) outside {lo:g}–{hi:g}%")
                      + " — rerun curve and reinject samples since last passing CCV",
                advisory=advisory,
            ))
    return flags


def _low_level(profile, r, analyte, matrix):
    """A check standard at or below the analyte's MRL (EPA 537.1 §10.3.3).
    Its own level when the run records one; else its expected concentration
    against the analyte's RL, in the same unit (the Run Builder records no
    level on a CCC). A reviewer's identity correction fixes the level of
    the injection it names, whatever its row says."""
    from .importer import level_override
    forced = level_override(r.injection_name)
    if forced is not None:
        return forced == "low"
    if r.level in ("1", "low", "MRL"):
        return True
    rl, _mdl, unit = profile.reporting_limits(analyte, matrix)
    if rl is None or not r.expected_conc:
        return False
    row_unit = (getattr(r, "conc_units", "") or "").strip().lower()
    if row_unit and unit and row_unit != unit.strip().lower():
        return False
    return r.expected_conc <= rl * (1 + 1e-9)


def _low_level_off(profile, r, analyte, matrix):
    """A check standard at the low level while CCV Low-Level is Off: the
    box borrows the Recovery window only while it is empty and on; Off, a
    low-level check standard is not judged at all (a method that runs no
    low-level CCV sets the box Off)."""
    return _box_state(profile, "ccv_low_level") == "off" and _low_level(profile, r, analyte, matrix)


def _ccv_window(profile, rule, r, analyte, matrix):
    lo, hi = rule.recovery_min, rule.recovery_max
    if rule.low_level_min is not None and _low_level(profile, r, analyte, matrix):
        lo, hi = rule.low_level_min, rule.low_level_max
    return lo, hi


def icv_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
    matrix: str = "",
    verdicts: "list | None" = None,
) -> list[QCFlag]:
    """ICV (EPA 537.1: QCS -- the second-source check of the calibration):
    calculated vs expected within the method's ICV deviation (Calibration &
    CCV, `icv.pct_dev_max`)."""
    from .importer import classify_injection
    same = profile.icv_same_as_ccv()
    limit = profile.icv_pct_dev_max()
    mine = [r for r in rows if r.compound_name == analyte
            and classify_injection(r.injection_name) == "ICV"]
    if not same and limit is None:
        # its box is Off, or empty, which the run queue files once
        # (limit_states.empty_boxes): Enforced refuses, Evaluate advises
        return []
    flags: list[QCFlag] = []
    for r in mine:
        missing = check_no_reading(r) if r.expected_conc else None
        if not r.expected_conc or (r.calculated_conc is None and missing is None):
            continue
        # an ICV with no reading, raw or vendor, at 0 %; judged at the method's decimal
        # places for recoveries
        rec = profile.judged_recovery(0.0 if missing else r.calculated_conc / r.expected_conc * 100.0, matrix)
        if same and _low_level_off(profile, r, analyte, matrix):
            continue                     # judged with the CCV's windows: its low level Off, not judged
        if same:
            ccv_rule = profile.ccv_rule()
            lo, hi = _ccv_window(profile, ccv_rule, r, analyte, matrix)
            box = "ccv_recovery" if (lo, hi) == (ccv_rule.recovery_min, ccv_rule.recovery_max) else "ccv_low_level"
        else:
            lo, hi = 100.0 - limit, 100.0 + limit
            box = "icv"
        advisory = _advisory_of(profile, [box])
        ok = lo <= rec <= hi and not missing
        why = (no_reading_issue("ICV", missing) if missing
               else "(ICV) outside {0:g}-{1:g}%".format(lo, hi))
        if verdicts is not None:
            verdicts.append({"analyte": analyte, "injection_name": r.injection_name,
                             "concat_id": getattr(r, "concat_id", "") or r.injection_name,
                             "calculated": r.calculated_conc, "expected": r.expected_conc,
                             "recovery": rec, "passed": ok, "qc_type": "ICV", "lo": lo, "hi": hi,
                             "basis": ("ICV recovery {0:g}-{1:g} % (the CCV window)" if same
                                       else "ICV recovery {0:g}-{1:g} %").format(lo, hi),
                             "issue": "" if ok else why, "advisory": advisory})
        if not ok:
            flags.append(QCFlag(
                source=f"{profile.method_id} ICV",
                check_kind=KIND_CCV,
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{profile.recovery_text(rec)}%",
                issue=(no_reading_issue("ICV", missing) if missing else f"(ICV) outside {lo:g}–{hi:g}%")
                      + " — the calibration is not verified",
                advisory=advisory,
            ))
    return flags


def lowest_raw_calibrators(cal_rows):
    """The rows of the lowest calibrator level a raw run holds for the curve
    (raw provenance, a stated concentration, a curve), fitted or not: a level
    left off the curve does not hand the place to the next. A raw row names
    its analyte's curve r2 on every calibrator; a standard with no curve (an
    injection standard) has none and is no curve's calibrator."""
    present = [r for r in cal_rows
               if (getattr(r, "derived_from", "") or "").startswith("raw:") and r.expected_conc
               and getattr(r, "r2", None) is not None]
    if not present:
        return []
    lowest = min(r.expected_conc for r in present)
    return [r for r in present if r.expected_conc == lowest]


def raw_not_detected(r):
    """A raw calibrator with no quantifier peak."""
    return getattr(r, "conc_qualifier", "") == QUALIFIER_ND


def _lowest_raw_calibrator_sn(cal_rows, analyte, sn_quan_min, sn_confirm_min):
    """{id(row): [issue]} for the lowest calibrator level a raw run holds for
    the curve (lowest_raw_calibrators). Its quantifier S/N must reach
    `sn_quan_min` and, where it has a qualifier, its qualifier S/N
    `sn_confirm_min`; with no quantifier peak it fails as not detected. A
    qualifier the analyst deleted there (qualifiers_deleted), any one of
    them, fails the level wherever the method sets `sn_confirm_min`: a
    deleted confirmation ion confirms nothing. A limit the method does not
    set is not judged, and with neither set the level is not judged."""
    if sn_quan_min is None and sn_confirm_min is None:
        return {}
    out = {}
    for r in lowest_raw_calibrators(cal_rows):
        issues = []
        where = f"{analyte} lowest calibrator level {r.level}"
        sn, qual_sn = getattr(r, "signal_to_noise", None), getattr(r, "qual_sn", None)
        if raw_not_detected(r):
            issues.append(f"{where}: not detected")
        else:
            if sn_quan_min is not None and sn is not None and sn < sn_quan_min:
                issues.append(f"{where}: quantifier S/N {sn:g}<{sn_quan_min:g}")
            if sn_confirm_min is not None and qual_sn is not None and qual_sn < sn_confirm_min:
                issues.append(f"{where}: qualifier S/N {qual_sn:g}<{sn_confirm_min:g}")
            if sn_confirm_min is not None and qualifiers_deleted(r):
                issues.append(f"{where}: qualifier deleted: {', '.join(qualifiers_deleted(r))}")
        if issues:
            out[id(r)] = issues
    return out


def manual_cal_drops(rows, analyte):
    """[(injection, level)] of the calibrators the analyst dropped from the
    analyte's curve by deleting a peak, its own or its isotope standard's:
    the entries of the curve its raw rows name (quant.curve.excluded) with
    those reasons (MANUAL_DROP_REASONS). A calibrator off the curve for any
    other reason the run found itself is not counted. Each injection once, by level."""
    levels, dropped = {}, set()
    for r in rows:
        if r.compound_name != analyte:
            continue
        levels.setdefault(r.injection_name, r.level)
        curve = (_raw_record(r).get("quant") or {}).get("curve") or {}
        for x in curve.get("excluded") or []:
            if x.get("reason") in MANUAL_DROP_REASONS:
                dropped.add(x.get("injection"))

    def order(inj):
        level = levels.get(inj)
        try:
            return (0, float(level), inj)
        except (TypeError, ValueError):
            return (1, 0.0, inj)
    return [(inj, levels.get(inj)) for inj in sorted(dropped, key=order)]


def _manual_drops_issue(rows, analyte, most):
    """The curve's issue when more of its calibrators were dropped by hand
    (manual_cal_drops) than the method's `most`, naming the analyte and the
    levels, and the dropped injections, lowest level first; ("", []) within
    it or with no limit set (None). A limit of 0 is a limit."""
    if most is None:
        return "", []
    dropped = manual_cal_drops(rows, analyte)
    if not len(dropped) > most:
        return "", []
    names = [str(level) if level not in (None, "") else inj for inj, level in dropped]
    return ("{0}: {1} calibrator{2} dropped by hand, more than the method's {3}: level{2} {4}".format(
        analyte, len(dropped), "" if len(dropped) == 1 else "s", most, ", ".join(names)),
        [inj for inj, _level in dropped])


def calibration_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
    judge_r2: bool = True,
    sn_quan_min: float | None = None,
    sn_confirm_min: float | None = None,
) -> list[CalibrationResult]:
    """Calibration check with profile r² (FDA 0.990) and
    per-point %dev where the method defines one (537.1: 30%/50%).
    r² is judged only when the method sets a minimum and its "Calibration
    r²" rule switch is on (judge_r2); the point deviations either way.
    On a raw run the lowest calibrator level it holds, on the curve or not,
    must be detected and reach the method's quantifier and confirmation S/N
    limits (`sn_quan_min`, `sn_confirm_min`, its ConfirmationRule) where the
    method sets them, and
    no more of its calibrators may be dropped by hand than the method's
    max_cal_dropped(): past it the curve fails once, on its lowest dropped
    calibrator, naming every dropped level."""
    rule = profile.calibration_rule(analyte)
    r2_min = rule.r2_min if judge_r2 else None
    # the run's CALIBRATORS (their role in the run plan), not every row the
    # export calls "Standard" -- some software also labels a CCC so;
    # the sample type is the fallback for a run with no roles recorded
    cal_rows = calibrator_rows(rows, analyte)
    results: list[CalibrationResult] = []
    # the lowest calibrator by its expected concentration, not by how the
    # export spells its level: EPA 537.1 §10.2.7 allows +/-50 % at or below
    # the MRL
    expected = [r.expected_conc for r in cal_rows if r.expected_conc]
    lowest_expected = min(expected) if expected else None
    every = calibrator_rows(rows, analyte, off_curve=True)
    sn_issues = _lowest_raw_calibrator_sn(every, analyte, sn_quan_min, sn_confirm_min)
    # too many calibrators dropped by hand fails the curve once: one result,
    # on its lowest dropped calibrator, names the analyte and every level
    drops, dropped = _manual_drops_issue(rows, analyte, profile.max_cal_dropped())
    holder = next((r for inj in dropped for r in every if r.injection_name == inj), None)
    if drops and holder is not None:
        sn_issues.setdefault(id(holder), []).append(drops)
    # each issue is judged in a box (limit_states); the flag is advisory only
    # when every box that failed is in the state Evaluate
    calibration_boxes = [b for b in ("cal_r2", "cal_point", "cal_low_point")
                         if _box_state(profile, b) != "off"] or ["cal_point"]

    def _issue_box(text):
        if text == drops:
            return "cal_dropped"
        if ": quantifier S/N " in text or text.endswith(": not detected"):
            return "sn_min.quan"
        return "sn_min.confirm"
    # a lowest level left off the curve is judged on its S/N alone, a
    # calibrator dropped by hand on the count of them
    on_curve = set(id(r) for r in cal_rows)
    off = [r for r in every if id(r) in sn_issues and id(r) not in on_curve]
    for r in cal_rows + off:
        issues = []
        boxes = []
        limit, lowest = None, False
        fitted = id(r) in on_curve
        if fitted and r2_min is not None and r.r2 is not None and r.r2 < r2_min:
            issues.append(f"R²={r.r2:.4f}<{r2_min}")
            boxes.append("cal_r2")
        # a calibrator on the curve is always judged: one with no reading on
        # it fails its point instead of being skipped
        unread = fitted and r.expected_conc and r.pct_deviation is None
        if unread and _raw_record(r):
            issues.append(CAL_NOT_READ)
            boxes += calibration_boxes
        elif unread and r.calculated_conc is None:
            issues.append(CAL_NO_CONCENTRATION)
            boxes += calibration_boxes
        # the lowest level by its own box where it has a limit, every other
        # point (the lowest too, where its box has none) by the point box
        low_point = bool(rule.low_point_pct_dev_max) and fitted and r.pct_deviation is not None and (
            r.level in ("1", "low", "MRL")
            or (lowest_expected is not None and r.expected_conc == lowest_expected)
            or _low_level(profile, r, analyte, ""))
        if low_point:
            limit, lowest = rule.low_point_pct_dev_max, True
        elif fitted and rule.point_pct_dev_max is not None and r.pct_deviation is not None:
            limit = rule.point_pct_dev_max
        if limit is not None:
            # instrument criteria are judged unrounded, but not on
            # floating-point noise: 30.000000004 % is a calibrator AT 30 %
            if round(abs(r.pct_deviation) * 100, 9) > limit:
                issues.append(f"dev={r.pct_deviation*100:+.1f}%>{limit:.0f}%")
                boxes.append("cal_low_point" if lowest else "cal_point")
        for text in sn_issues.get(id(r), []):
            issues.append(text)
            boxes.append(_issue_box(text))
        flag = None
        if issues:
            flag = QCFlag(
                source=f"{profile.method_id} Calibration",
                check_kind=KIND_CALIBRATION,
                analyte=analyte,
                injection_name=r.injection_name,
                value=_format_val(r.pct_deviation),
                issue="(CAL) " + "; ".join(issues),
                advisory=_advisory_of(profile, boxes),
            )
        results.append(CalibrationResult(
            analyte=analyte, injection_name=r.injection_name,
            concat_id=r.concat_id, r2=r.r2,
            calculated_conc=r.calculated_conc,
            pct_deviation=r.pct_deviation, flag=flag, limit=limit, r2_min=r2_min, lowest=lowest,
        ))
    return results


def rrt_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
) -> list[RTResult]:
    """
    Retention-time check using the profile's rule:
      FDA:   relative RT deviation ≤1% of the standard's RT
      537.1: absolute ±0.05 min
    A method that sets neither is not judged: the gap holds release.
    """
    conf = profile.confirmation_rule()
    if conf.rrt_tol_pct is None and conf.rt_tol_abs_min is None:
        # neither tolerance is judged: each box is Off, or empty, which the
        # run queue files (limit_states.empty_boxes)
        return []
    # the tolerance used: Relative where it is set, else Absolute; a flag is
    # advisory while its box is in the state Evaluate
    box = "rrt_deviation.relative" if conf.rrt_tol_pct is not None else "rrt_deviation.absolute"
    advisory = _advisory_of(profile, [box])
    std_rows = calibrator_rows(rows, analyte, lambda r: r.observed_rt)
    if not std_rows:
        return []
    avg_rt = statistics.mean(r.observed_rt for r in std_rows)

    results: list[RTResult] = []
    for r in [x for x in rows if x.compound_name == analyte]:
        rt = r.observed_rt
        flag = None
        pct_dev = None
        if rt and avg_rt:
            pct_dev = (rt / avg_rt) - 1.0
            if conf.rrt_tol_pct is not None:
                if abs(pct_dev) * 100 > conf.rrt_tol_pct:
                    flag = QCFlag(
                        source=f"{profile.method_id} RRT",
                check_kind=KIND_RT,
                        analyte=analyte, injection_name=r.injection_name,
                        value=f"{rt:.3f}",
                        issue=f"(RT) RRT dev {pct_dev*100:+.2f}% "
                              f"> ±{conf.rrt_tol_pct}%",
                        advisory=advisory,
                    )
            elif abs(rt - avg_rt) > conf.rt_tol_abs_min:
                flag = QCFlag(
                    source=f"{profile.method_id} RT",
                    check_kind=KIND_RT,
                    analyte=analyte, injection_name=r.injection_name,
                    value=f"{rt:.3f}",
                    issue=f"(RT) dev {rt-avg_rt:+.3f} min "
                          f"> ±{conf.rt_tol_abs_min} min",
                    advisory=advisory,
                )
        results.append(RTResult(
            analyte=analyte, injection_name=r.injection_name,
            concat_id=r.concat_id, observed_rt=rt,
            average_rt=avg_rt, pct_deviation=pct_dev, flag=flag,
        ))
    return results


def single_transition_confirm_needed(
    profile: MethodProfile,
    analyte: str,
    detected: bool,
) -> Optional[str]:
    """
    FDA §10.2(4): PFBA/PFPeA positives must be confirmed by LC-HRMS
    (%diff < 20%). Returns a review-prompt string when confirmation is
    required. Called from `pipeline.build_summary`, the only place that knows
    whether an analyte was detected.

    `detected` must mean DETECTED, not quantified: BLoQ and ALoQ both count,
    because §10.2(4) is about establishing identity, not about the number.

    Which analytes need confirming comes from the method's confirmation_rule:
    None on EPA 537.1 and EPA 1633A, whose `single_transition_analytes` are
    empty.
    """
    conf = profile.confirmation_rule()
    if not detected or not conf.single_transition_analytes:
        return None
    # the setting holds keywords; a reported name is any spelling of one
    from .analyte_alias import LibraryUnavailable, keyword_of
    try:
        kw = keyword_of(analyte) or analyte
    except LibraryUnavailable:                          # no library: the name as given
        kw = analyte
    if analyte in conf.single_transition_analytes or kw in conf.single_transition_analytes:
        return (f"{analyte} positive detect: single MS/MS transition — "
                f"confirm by an orthogonal technique "
                f"({conf.confirm_technique})"
                + (f"; %diff between techniques must be \u2264 {conf.confirm_pct_diff_max:g}%"
                   if conf.confirm_pct_diff_max is not None else
                   "; no %diff limit is set (the method's QC criteria tab, Qualifier ion check)"))
    return None


# ── Checks behind the rule switches ──────────────────────────────────────────
# Pure: the caller has already resolved the limit and confirmed the result
# and the limit are in the same unit family (run_queue._units_compatible).

def blank_check(analyte: str, injection_name: str, conc: Optional[float],
                rl: float, max_x_rl: float, unit: str, role: str = "MB",
                fails_at_limit: bool = False) -> Optional[QCFlag]:
    """A blank's analyte above max_x_rl x RL (QC Types tier); AT the limit
    too where the method says so (EPA 537.1 §9.3.1: an LRB "equal to or
    greater than" 1/3 MRL invalidates the batch)."""
    if conc is None:
        return None                       # not detected: clean
    limit = max_x_rl * rl
    # "at the limit" within floating-point noise: 0.83 is 1/3 of 2.49 though
    # 2.49 / 3 is 0.8300000000000001
    at = abs(conc - limit) <= 1e-9 * max(abs(limit), 1.0)
    if (conc < limit and not at) or (at and not fails_at_limit):
        return None
    word = "at or above" if fails_at_limit else "above"
    return QCFlag(source=f"{role} blank", check_kind=KIND_BLANK, analyte=analyte,
                  injection_name=injection_name, value=f"{conc:g} {unit}".strip(),
                  issue=f"(BLK) {word} {max_x_rl:g} x RL = {limit:g} {unit}".strip())


# the blanks judged against the Blank limits (a field or trip blank only
# against its own row): one list for the check and the stored rows
BLANK_ROLES = frozenset(("MB", "LRB", "MxB", "CCB"))
# what a method may leave out of the "CCV every N" count: EPA 537.1 §10.3,
# "a 'sample' is considered to be a Field Sample. LRBs, CCCs, LFBs, LFSMs,
# FDs, FRBs and LFSMDs are not counted as samples" -- the extraction batch's
# QC roles (their one list, extraction_batch.QC_ROLES) and the field QC
def _extracted_qc_roles():
    from .addon import load
    return frozenset(load("extraction_batch").QC_ROLES) | frozenset(("FRB", "FD"))


EXTRACTED_QC_ROLES = _extracted_qc_roles()
# the run's calibration standards and the instrument's checks: the
# calibrators, the initial and continuing calibration verifications and the
# continuing calibration blank
RUN_CHECK_ROLES = frozenset(("CAL", "ICV", "CCV", "CCB"))


def ccv_frequency_check(sequence: list, n: int, opening_required: bool = False,
                        counts_extracted_qc: bool = True) -> list:
    """`sequence`: [(injection_name, role)] in run order. A counting
    injection (everything in the bracketed body: field samples AND extracted
    QC -- the Run Builder's rule) is flagged when more than `n` counting
    injections have run since the last CCV, or when no CCV follows it (the
    run was not closed). With `opening_required` (the method's Calibration &
    CCV setting; EPA 537.1 §10.3 opens every analysis batch with a CCC), a
    counting injection before any CCV was never bracketed and is flagged;
    without it those are pre-bracket. Calibrators, ICVs and solvent blanks are
    never counted; extracted QC and field reagent blanks only where the method
    counts them (its Calibration & CCV setting)."""
    NON_COUNTING = {"CAL", "CCV", "ICV", "CCB"}
    if not counts_extracted_qc:
        NON_COUNTING |= EXTRACTED_QC_ROLES
    flags, since, opened, pending = [], 0, False, []
    for name, role in sequence:
        if role == "CCV":
            opened, since, pending = True, 0, []
            continue
        if role in NON_COUNTING:
            continue
        if not opened:
            if opening_required:
                flags.append(QCFlag(source="CCV frequency", check_kind=KIND_CCV_FREQ, analyte="",
                                    injection_name=name, value="before the first CCV",
                                    issue="(CCV) run before any CCV: the run was not opened"))
            continue
        since += 1
        pending.append(name)
        if since > n:
            flags.append(QCFlag(source="CCV frequency", check_kind=KIND_CCV_FREQ, analyte="",
                                injection_name=name, value=f"{since} since last CCV",
                                issue=f"(CCV) run {since} "
                                      f"{'injections' if counts_extracted_qc else 'field samples'} "
                                      f"after the last CCV; the method brackets every {n}"))
    flagged = set(f.injection_name for f in flags)
    for name in pending:                  # after the last CCV, never closed
        if name not in flagged:
            flags.append(QCFlag(source="CCV frequency", check_kind=KIND_CCV_FREQ, analyte="",
                                injection_name=name, value="no closing CCV",
                                issue="(CCV) no CCV after this injection: the run was not closed"))
    return flags


def mdl_check(analyte: str, injection_name: str, conc: Optional[float],
              mdl: float, unit: str) -> Optional[QCFlag]:
    """A detected result below the analyte's MDL."""
    if conc is None or conc <= 0 or conc >= mdl:
        return None
    return QCFlag(source="MDL", check_kind=KIND_MDL, analyte=analyte,
                  injection_name=injection_name, value=f"{conc:g} {unit}".strip(),
                  issue=f"(MDL) detected below the MDL ({mdl:g} {unit})".strip())


def dup_one_detected_flag(analyte: str, injection_name: str, parent: str,
                          sample_conc, dup_conc, rl: float, unit: str) -> QCFlag:
    """A sample / duplicate pair where only one result reached the RL: no RPD
    can be computed, but a reviewer should see it."""
    fmt = lambda v: "ND" if v is None else f"{v:g}"          # noqa: E731
    return QCFlag(source="Sample duplicate", check_kind=KIND_DUP, analyte=analyte,
                  injection_name=injection_name,
                  value=f"sample {fmt(sample_conc)} / dup {fmt(dup_conc)} {unit}".strip(),
                  issue=f"(RPD) detected at or above the RL ({rl:g} {unit}) in one of the pair "
                        f"only (parent {parent}): no RPD; review")
