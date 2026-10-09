"""
QC Engine — the instrument-level checks, each against the method profile's
configured criteria (sources:):

  IS response      → is_raw_check()
  RT deviation     → rt_deviation_check()
  Ion ratio        → qual_quan_check()
  Calibration %dev → calibration_check()
  LFSM / LFSMD     → evaluated in run_queue.auto_evaluate()
                     (the lfsm_check/lfsmd_check twins here were dead and
                      were removed 2026-08-07)
"""

from __future__ import annotations
import statistics
from datetime import datetime
from typing import Optional

from .constants import CRITERIA, QUALIFIER_NC, QUALIFIER_ND
from .models import reported_conc
from .models import (
    InstrumentRow, QCFlag,
    ISRawResult, RTResult, QualQuanResult, CalibrationResult,
    LFSMResult, LFSMDResult, MDLResult,
)

# ─────────────────────────────────────────────────────────────────────────────
# Check identities.
#
# These name WHICH CHECK raised a flag, independently of the human-readable
# `source` string. The review queue matches on these; nothing matches on the
# display text. Renaming a source label is now cosmetic -- previously it
# silently turned four review checks into permanent passes.
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _numeric_rows(rows: list[InstrumentRow], value_fn) -> list[float]:
    """Extract a list of non-None floats from rows using value_fn."""
    result = []
    for r in rows:
        v = value_fn(r)
        if v is not None:
            result.append(v)
    return result


def _format_val(v: Optional[float]) -> str:
    if v is None:
        return QUALIFIER_ND
    return f"{v:.6g}"


# ─────────────────────────────────────────────────────────────────────────────
# IS response
#   ratio = response_ratio / mean(response_ratio of the calibration standards
#           for that compound); "N.D." when there is no response
# ─────────────────────────────────────────────────────────────────────────────

def is_raw_check(
    rows: list[InstrumentRow],
    is_compound: str,
    dilutions: "dict | None" = None,
    method_id: str = "",
    matrix: str = "",
) -> list[ISRawResult]:
    """
    Labelled-compound response against the ICAL average.

    The quantity is the PEAK AREA, which is what the method profile's
    ``is_response: vs_ical_avg`` describes. It was comparing ``response_ratio``
    — this compound divided by another — so a failure never said which of the
    two had moved.

    Dilution is handled by ROLE, not by injection type, because the two kinds
    of labelled compound behave differently:

      * a SURROGATE (extracted internal standard) is added before extraction,
        so a 1:10 dilution dilutes it with the sample and its area falls by the
        factor. Its area is corrected by the recorded factor before comparison,
        recovering what it would have read undiluted.

      * the INJECTION INTERNAL STANDARD is added at reconstitution, AFTER the
        dilution, so its area does NOT scale. It is compared as measured, and a
        drop in a dilution is a real finding rather than arithmetic.

    Both roles are recorded on the AnalysisService (`pfas_role`) and in
    analyte_reference; the pipeline previously held a flat list with no roles
    and applied one rule to all of them.
    """
    from .analyte_alias import injection_is_names, keyword_for
    from .method_profiles import get_surrogate_is_chain

    dilutions = dilutions or {}
    # The METHOD decides which labelled compound is the injection standard.
    # surrogate_is_chain maps each surrogate to the IS it is quantified
    # against, so a compound that appears only as a VALUE is the injection
    # standard and every KEY is a surrogate. The global analyte_reference table
    # is the fallback: it is not method-scoped, and under a method that uses a
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
        """Area, undiluted-equivalent."""
        if row.response is None:
            return None
        entry = dilutions.get(row.injection_name)
        if entry and not is_injection_standard:
            factor = entry.get("factor")
            if factor:
                return row.response * factor
        return row.response

    from .importer import classify_injection
    # Judged in ACQUISITION order: "the most recent CCC" is the CCC that
    # opened this injection's bracket, whatever order the export lists rows
    # in (a file sorted by name put a later CCC first). Undated rows keep
    # their file order, after the dated ones.
    mine = [r for r in rows if r.compound_name == is_compound]
    mine = [r for _i, r in sorted(enumerate(mine), key=lambda p: (
        p[1].acquisition_datetime is None, p[1].acquisition_datetime or 0, p[0]))]
    # The ICAL average is the CALIBRATORS' (EPA 537.1 §9.3.4): by the run's
    # roles, not by the export's "Standard" sample type, which some software
    # also gives a CCC. The sample type is the fallback for a run with no
    # roles recorded.
    std_rows = [r for r in mine if r.response is not None
                and classify_injection(r.injection_name) == "CAL"]
    if not std_rows:
        std_rows = [r for r in mine if r.response is not None
                    and r.sample_type == "Standard"]
    if not std_rows:
        return []
    avg_response = statistics.mean(r.response for r in std_rows)
    if not avg_response:
        return []

    # Limits from the METHOD, not from the constants table. The two agreed
    # numerically for FDA (CRITERIA's ±50% drift is the profile's 50-150%
    # window), which is why enforcing the constant went unnoticed -- but 537.1
    # §9.3.4 requires the IS to hold against BOTH the ICAL average AND the most
    # recent CCV, and `vs_last_ccv` was consumed only by a function nothing
    # called. This merges the profile's dual conditions into the check that
    # already knows the surrogate/injection-IS distinction, rather than
    # swapping in the profiled variant, which does not handle dilutions.
    rule = None
    prof = None
    if method_id:
        try:
            from .method_profiles import get_profile
            prof = get_profile(method_id)
            rule = prof.is_rule()
        except Exception:                                  # noqa: BLE001
            rule = None

    def judge(pct):
        """The % judged as the report states it: a whole percent by the
        method's rule; without a method, the default rule."""
        if prof is not None:
            return prof.judged_pct(pct, matrix)
        from .addon import load
        return load("rounding").judged_pct(pct)
    lo = rule.vs_ical_avg_min if rule else None
    hi = rule.vs_ical_avg_max if rule else None
    configured = lo is not None and hi is not None
    if lo is None or hi is None:
        tol = CRITERIA["is_response_drift_pct"]
        lo, hi = (1.0 - tol) * 100.0, (1.0 + tol) * 100.0
    ccv_lo = rule.vs_last_ccv_min if rule else None
    ccv_hi = rule.vs_last_ccv_max if rule else None

    results: list[ISRawResult] = []
    last_ccv_response = None
    for r in mine:
        value = corrected(r)
        pct_from_cal = None
        judged = None
        flag = None
        if value is not None:
            pct_from_cal = value / avg_response
            judged = judge(pct_from_cal * 100.0)
            fails = []
            # judged only against a window the METHOD sets: the built-in
            # fallback flagged runs against limits nobody configured; such a
            # result is stored "not evaluated" instead
            if configured and not (lo <= judged <= hi):
                fails.append("{0:.0f}% of ICAL average (limit {1:g}-{2:g}%)"
                             .format(judged, lo, hi))
            # 537.1's second condition. Only applied once a CCV has been seen,
            # and only when the method configures the window.
            if ccv_lo is not None and ccv_hi is not None and last_ccv_response:
                pct_ccv = judge(value / last_ccv_response * 100.0)
                if not (ccv_lo <= pct_ccv <= ccv_hi):
                    fails.append(
                        "{0:.0f}% of the bracket's CCV (limit {1:.0f}-{2:.0f}%)".format(
                            pct_ccv, ccv_lo, ccv_hi))
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
                )
        if value and classify_injection(r.injection_name) == "CCV":
            last_ccv_response = value

        results.append(ISRawResult(
            is_compound=is_compound,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            response=value,
            pct_from_cal=pct_from_cal,
            average_response=avg_response,
            flag=flag,
            window_min=lo, window_max=hi, configured=configured, judged_pct=judged,
            ccv_min=ccv_lo, ccv_max=ccv_hi,
            std_role="injection_is" if is_injection_standard else "surrogate",
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# RT deviation
#   dev = observed_rt / mean(observed_rt of the calibration standards) - 1
# ─────────────────────────────────────────────────────────────────────────────

def rt_deviation_check(
    rows: list[InstrumentRow],
    analyte: str,
) -> list[RTResult]:
    """
    Compute RT % deviation from batch average (Standards) for every injection.
    Flags deviations beyond ±rt_dev_abs_min minutes.
    """
    std_rows = [r for r in rows
                if r.compound_name == analyte
                and r.sample_type == "Standard"
                and r.observed_rt is not None]
    if not std_rows:
        return []

    avg_rt = statistics.mean(r.observed_rt for r in std_rows)  # type: ignore
    tol = CRITERIA["rt_dev_abs_min"]

    results: list[RTResult] = []
    for r in [row for row in rows if row.compound_name == analyte]:
        rt = r.observed_rt
        if rt is None or rt == 0:
            pct_dev = None
            flag = None
        else:
            try:
                pct_dev = (rt / avg_rt) - 1.0
            except ZeroDivisionError:
                pct_dev = None
            flag = None
            dev_abs = abs(rt - avg_rt)
            if dev_abs > tol:
                flag = QCFlag(
                    source="RT Deviation",
                check_kind=KIND_RT,
                    analyte=analyte,
                    injection_name=r.injection_name,
                    value=_format_val(rt),
                    issue=f"RT dev {rt - avg_rt:+.3f} min (±{tol} tol.)",
                )

        results.append(RTResult(
            analyte=analyte,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            observed_rt=rt,
            average_rt=avg_rt,
            pct_deviation=pct_dev,
            flag=flag,
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Ion ratio (qualifier / quantifier)
#   ratio relative to the calibrators' mean; flagged outside the method's
#   tolerance (a method-profile setting)
# ─────────────────────────────────────────────────────────────────────────────

def _ratio_pairs(observed, expected):
    """[(obs, exp), ...] from the ion-ratio columns.

    A compound with two qualifier ions reports both, pipe-separated
    ("0.484|0.507" against "0.509|0.477"), so each transition is compared on
    its own. Returns [] when either side is absent or unparseable.
    """
    NOT_CALCULATED = ("not calculated", "n.c.", "nc")

    def split(v):
        if v is None:
            return []
        out = []
        for part in str(v).split("|"):
            part = part.strip()
            if part.lower() in NOT_CALCULATED:
                out.append("uncalculable")
                continue
            try:
                out.append(float(part))
            except (TypeError, ValueError):
                out.append(None)
        return out

    obs, exp = split(observed), split(expected)
    if not obs or not exp:
        return []
    return [(o, e) for o, e in zip(obs, exp)
            if o is not None and (e not in (None, 0) or o == "uncalculable")]


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
    response / quantifier response (the same number: the lab's FDA exports
    agree on all 2,315 rows)."""
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
            got = (calibrators[i], "this run's calibrators")
        out.append(got)
    return out


def calibrator_ratio_means(rows, analyte):
    """Mean observed ratio per qualifier ion over the run's calibrators."""
    sums = {}
    for r in rows:
        if r.compound_name != analyte or r.sample_type != "Standard":
            continue
        for i, o in enumerate(observed_ratios(r)):
            if isinstance(o, float):
                sums.setdefault(i, []).append(o)
    if not sums:
        return []
    return [(sum(sums[i]) / len(sums[i])) if i in sums else None for i in range(max(sums) + 1)]


def qual_quan_check(
    rows: list[InstrumentRow],
    analyte: str,
    non_iso_set: frozenset | None = None,
) -> list[QualQuanResult]:
    """
    Ion-ratio confirmation: the OBSERVED qualifier/quantifier ratio against the
    EXPECTED one, within the method's tolerance.

    This previously compared ``response_ratio`` — analyte area over IS area,
    which tracks CONCENTRATION — against the mean of that quantity across every
    calibration level, a span of 20 to 0.039 ng/mL. Any sample differing from
    that arbitrary mean by more than the tolerance was flagged, which on a real
    run meant 658 of 1254 rows. It was not an ion-ratio check at all.

    Comparing the columns actually meant for it reproduces the instrument's own
    Ion Ratio Check verdict exactly (474 pass / 23 fail on the 497 rows where
    both are present). Rows carrying no ratio data are left unjudged rather
    than silently passed.
    """
    # non_iso_set is accepted for signature compatibility but no longer used:
    # "no labelled standard" is a reporting qualifier applied in build_summary,
    # not an ion-ratio verdict.
    if CRITERIA.get("ion_ratio_tol_pct") is None:
        return []          # the method sets no ion-ratio criterion: not judged
    tol = CRITERIA["ion_ratio_tol_pct"] / 100.0

    results: list[QualQuanResult] = []
    cal_means = calibrator_ratio_means(rows, analyte)
    for r in [row for row in rows if row.compound_name == analyte]:
        # observed: the ratio column, else qualifier / quantifier response;
        # expected: the first column the export fills, else the calibrators'
        # mean ("redundancies ... fall back logic of using the
        # response column for the quant and qualifier")
        exp = expected_ratios(r, cal_means)
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
                avg_response_ratio=None, pct_of_cal=None, flag=None))
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
                    avg_response_ratio=None, pct_of_cal=None, flag=None))
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
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Calibration
#   per-point % deviation (calculated vs expected concentration) and the
#   curve's r² against the method profile's calibration criteria
#   Flags: CAL = % deviation > 20%, R² < 0.995
# ─────────────────────────────────────────────────────────────────────────────

def calibration_check(
    rows: list[InstrumentRow],
    analyte: str,
) -> list[CalibrationResult]:
    """
    Check calibration % deviation and R² for each calibration standard injection.
    Flags: (CAL) if |% dev| > 20% or R² < 0.995.
    """
    cal_rows = [r for r in rows
                if r.compound_name == analyte
                and r.sample_type == "Standard"]

    r2_max = CRITERIA["cal_r2_min"]
    pct_max = CRITERIA["cal_pct_dev_max"]

    results: list[CalibrationResult] = []
    for r in cal_rows:
        flag = None
        issues = []
        if r.r2 is not None and r.r2 < r2_max:
            issues.append(f"R²={r.r2:.4f}<{r2_max}")
        if r.pct_deviation is not None and abs(r.pct_deviation) > pct_max:
            issues.append(f"dev={r.pct_deviation*100:+.1f}%")
        if issues:
            flag = QCFlag(
                source="Calibration %",
                check_kind=KIND_CALIBRATION,
                analyte=analyte,
                injection_name=r.injection_name,
                value=_format_val(r.pct_deviation),
                issue="(CAL) " + "; ".join(issues),
            )

        results.append(CalibrationResult(
            analyte=analyte,
            injection_name=r.injection_name,
            concat_id=r.concat_id,
            r2=r.r2,
            calculated_conc=r.calculated_conc,
            pct_deviation=r.pct_deviation,
            flag=flag,
        ))

    return results

# ─────────────────────────────────────────────────────────────────────────────

def calculate_mdl(
    analyte: str,
    matrix: str,
    replicate_concs: list[float],
    blank_values: list[float | None] | None = None,
) -> MDLResult | None:
    """
    Calculate Method Detection Limit per EPA/FDA guidance.
    replicate_concs: list of spike replicate concentrations (n ≥ 7).
    blank_values:    corresponding blank concentrations (may contain None = ND).

    NOT WIRED -- no caller. An MDL is determined by a PERIODIC study over >=7
    replicates, not per run, and no such feature exists; the `mdl_check` rule
    toggle is declared UI-only in LIBRARY_KEY_TO_ENGINE_CHECKS for the same
    reason. The arithmetic (40 CFR 136 App B) is correct and is kept for
    whenever that study is built.
    """
    n = len(replicate_concs)
    min_n = CRITERIA["mdl_min_replicates"]
    if n < min_n:
        return None

    stdev = statistics.stdev(replicate_concs)
    t_table = CRITERIA["t_values"]
    t_val = t_table.get(n) or t_table.get(max(t_table.keys()))

    mdl_s = t_val * stdev

    # MDLb: subtract blank if blanks are available
    mdl_b = None
    blank_max = None
    note = ""
    if blank_values:
        numeric_blanks = [b for b in blank_values if b is not None and b > 0]
        if not numeric_blanks:
            note = "All blanks ND — no blank subtraction applied"
            mdl_b = mdl_s
        else:
            blank_max = max(numeric_blanks)
            mdl_b = mdl_s  # reported separately; blank flagging is separate
            # Flag if blank ≥ sample (< LOD rule)

    return MDLResult(
        analyte=analyte,
        matrix=matrix,
        n=n,
        stdev=stdev,
        t_value=t_val,
        mdl_s=mdl_s,
        mdl_b=mdl_b,
        blank_max=blank_max,
        note=note,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Signal-to-Noise check  (Signal-to-Noise sheet)
# ─────────────────────────────────────────────────────────────────────────────

def signal_to_noise_check(rows: list[InstrumentRow], analyte: str) -> list[QCFlag]:
    """Judge the QUANTITATION ion and the CONFIRMATION ion on their own limits.

    Two thresholds answering two questions, and until 2026-08-07 both branches
    used one of them:

      * quantitation ion below `sn_quan_min` -> the peak is there but the value
        is an estimate. That is what the `sn` failure type means: it carries
        code J, and its certificate statement says "the affected results are
        estimated". Both branches used to report "(N.C.)", which says something
        different -- that the identification was not confirmed.
      * qualifier ion below `sn_confirm_min` -> the identification is NOT
        confirmed, "(N.C.)". This limit was configured (EPA 1633A sets it to
        1.0) and read by nothing, so the qualifier ion was judged against the
        quantitation threshold of 3.0 instead -- failing ions between 1 and 3
        against a criterion the method does not apply to them.

    An unconfigured `sn_confirm_min` means the qualifier ion is NOT judged. It
    is not silently given the quantitation limit; that substitution is the bug
    this docstring exists to prevent coming back.
    """
    flags: list[QCFlag] = []
    quan_min = CRITERIA.get("sn_quan_min", CRITERIA["sn_min"])
    confirm_min = CRITERIA.get("sn_confirm_min")
    for r in rows:
        if r.compound_name != analyte:
            continue
        sn = r.signal_to_noise
        qual_sn = r.qual_sn
        if sn is not None and quan_min is not None and sn < quan_min:
            flags.append(QCFlag(
                source="Signal-to-Noise",
                check_kind=KIND_SN,
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{sn:.2f}",
                issue="(J)",
            ))
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
# Method-profile-aware checks (Pass 2 of the re-evaluation)
# These supersede the flat-criteria functions above when a method profile is
# supplied; the legacy functions remain for backwards compatibility.
# ═════════════════════════════════════════════════════════════════════════════

from .method_profiles import MethodProfile, get_profile


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
) -> Optional[QCFlag]:
    """
    Resolve recovery limits via the method profile and flag if outside.
    `window`, when given, receives the window applied ({lo, hi, basis}):
    Data Review shows each result against the criterion it was judged by.
    Handles FDA's three-tier (analyte × matrix) table automatically:
      PFOA in deer muscle  → 80–120%
      PFOA in feed         → 65–135%
      PFTrDA anywhere      → 40–140%
    """
    rule = (profile.qc_rules(analyte, matrix, qc_type, conc=conc, rl=rl)
            if conc is not None or rl is not None else profile.qc_rules(analyte, matrix, qc_type))
    if rule is None or rule.recovery_min is None:
        return None
    if window is not None:
        window.update(lo=rule.recovery_min, hi=rule.recovery_max,
                      basis="{0} recovery {1:g}-{2:g} %{3}".format(
                          qc_type, rule.recovery_min, rule.recovery_max,
                          " (guidance only)" if rule.is_guidance_only else ""))
    # judged as the report states it: a whole percent by the method's rule,
    # computed from the full-precision recovery
    judged = profile.judged_pct(recovery_pct, matrix)
    if rule.recovery_min <= judged <= rule.recovery_max:
        return None
    issue = f"(REC) {judged:.0f}% outside " \
            f"{rule.recovery_min:g}–{rule.recovery_max:g}%"
    if rule.is_guidance_only:
        issue += " [guidance only]"
    if rule.verify_against_method:
        issue += " [VERIFY limits vs method tables]"
    return QCFlag(
        source=f"{profile.method_id} {qc_type}",
        analyte=analyte,
        injection_name=injection_name,
        value=f"{judged:.0f}%",
        issue=issue + (f" — {rule.notes}" if rule.notes else ""),
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
    if window is not None:
        window.update(lo=None, hi=limit, basis="{0} RPD at most {1:g} %".format(qc_type, limit))
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
    the run's QC results carry them and Data Review's gate judges them (2026-10-06: a failing CCV lived only in the review queue; which SENAITE
    never reads).
    """
    rule = profile.ccv_rule()
    flags: list[QCFlag] = []
    # by ROLE (the Run Builder's record, else the name tokens): EPA 537.1
    # calls its CCVs CCC, and a name test never judged one
    from .importer import classify_injection
    ccv_rows = [r for r in rows
                if r.compound_name == analyte
                and classify_injection(r.injection_name) == "CCV"]
    for r in ccv_rows:
        if not r.expected_conc or r.calculated_conc is None:
            continue
        # judged as a whole percent by the method's rule
        rec = profile.judged_pct(r.calculated_conc / r.expected_conc * 100.0, matrix)
        lo, hi = _ccv_window(profile, rule, r, analyte, matrix)
        ok = lo <= rec <= hi
        if verdicts is not None:
            verdicts.append({"analyte": analyte, "injection_name": r.injection_name,
                             "concat_id": getattr(r, "concat_id", "") or r.injection_name,
                             "calculated": r.calculated_conc, "expected": r.expected_conc,
                             "recovery": rec, "passed": ok, "lo": lo, "hi": hi,
                             "basis": "CCV recovery {0:g}-{1:g} %{2}".format(
                                 lo, hi, " (lowest level)" if (lo, hi) != (rule.recovery_min, rule.recovery_max) else ""),
                             "issue": "" if ok else "(CCV) outside {0:g}-{1:g}%".format(lo, hi)})
        if not ok:
            flags.append(QCFlag(
                source=f"{profile.method_id} CCV",
                check_kind=KIND_CCV,
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{rec:.0f}%",
                issue=f"(CCV) outside {lo:g}–{hi:g}% — rerun curve and "
                      f"reinject samples since last passing CCV",
            ))
    return flags


def _low_level(profile, r, analyte, matrix):
    """A check standard at or below the analyte's MRL (EPA 537.1 §10.3.3).
    Its own level when the run records one; else its expected concentration
    against the analyte's RL, in the same unit. The Run Builder records no
    level on a CCC, so the low-level window was never applied."""
    if r.level in ("1", "low", "MRL"):
        return True
    try:
        rl, _mdl, unit = profile.reporting_limits(analyte, matrix)
    except Exception:                                      # noqa: BLE001
        return False
    if rl is None or not r.expected_conc:
        return False
    row_unit = (getattr(r, "conc_units", "") or "").strip().lower()
    if row_unit and unit and row_unit != unit.strip().lower():
        return False
    return r.expected_conc <= rl * (1 + 1e-9)


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
    CCV, `icv.pct_dev_max`). Found 2026-10-07 with synthetic runs: the limit
    was on every profile and nothing judged an ICV."""
    from .importer import classify_injection
    from .method_profiles import UnconfiguredCriterion
    same = profile.icv_same_as_ccv()
    limit = profile.icv_pct_dev_max()
    mine = [r for r in rows if r.compound_name == analyte
            and classify_injection(r.injection_name) == "ICV"]
    if not same and limit is None:
        if mine:
            # an ICV in the run and no criterion: not judged, and said so
            #  -- it holds like any unset criterion
            raise UnconfiguredCriterion(
                "{0} / {1}: the run has an ICV but the method sets no ICV criterion "
                "(Method Profiles -> Calibration & CCV).".format(profile.method_id, analyte))
        return []
    flags: list[QCFlag] = []
    for r in mine:
        if not r.expected_conc or r.calculated_conc is None:
            continue
        rec = profile.judged_pct(r.calculated_conc / r.expected_conc * 100.0, matrix)
        if same:
            lo, hi = _ccv_window(profile, profile.ccv_rule(), r, analyte, matrix)
        else:
            lo, hi = 100.0 - limit, 100.0 + limit
        ok = lo <= rec <= hi
        if verdicts is not None:
            verdicts.append({"analyte": analyte, "injection_name": r.injection_name,
                             "concat_id": getattr(r, "concat_id", "") or r.injection_name,
                             "calculated": r.calculated_conc, "expected": r.expected_conc,
                             "recovery": rec, "passed": ok, "qc_type": "ICV", "lo": lo, "hi": hi,
                             "basis": ("ICV recovery {0:g}-{1:g} % (the CCV window)" if same
                                       else "ICV recovery {0:g}-{1:g} %").format(lo, hi),
                             "issue": "" if ok else "(ICV) outside {0:g}-{1:g}%".format(lo, hi)})
        if not ok:
            flags.append(QCFlag(
                source=f"{profile.method_id} ICV",
                check_kind=KIND_CCV,
                analyte=analyte,
                injection_name=r.injection_name,
                value=f"{rec:.0f}%",
                issue=f"(ICV) outside {lo:g}–{hi:g}% — the calibration is not verified",
            ))
    return flags


def calibration_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
) -> list[CalibrationResult]:
    """Calibration check with profile r² (FDA 0.990, not 0.995) and
    per-point %dev where the method defines one (537.1: 30%/50%)."""
    rule = profile.calibration_rule(analyte)
    from .importer import classify_injection
    # the run's CALIBRATORS (their role in the run plan), not every row the
    # export calls "Standard" -- some software also labels a CCC so;
    # the sample type is the fallback for a run with no roles recorded
    cal_rows = [r for r in rows if r.compound_name == analyte
                and classify_injection(r.injection_name) == "CAL"]
    if not cal_rows:
        cal_rows = [r for r in rows
                    if r.compound_name == analyte and r.sample_type == "Standard"]
    results: list[CalibrationResult] = []
    # the lowest calibrator by its expected concentration, not by how the
    # export spells its level: "CAL-1" / "L1" / none were judged at +/-30 %
    # where EPA 537.1 §10.2.7 allows +/-50 % at or below the MRL (MEDIUM-2)
    expected = [r.expected_conc for r in cal_rows if r.expected_conc]
    lowest_expected = min(expected) if expected else None
    for r in cal_rows:
        issues = []
        limit, lowest = None, False
        if r.r2 is not None and r.r2 < rule.r2_min:
            issues.append(f"R²={r.r2:.4f}<{rule.r2_min}")
        if rule.point_pct_dev_max is not None and r.pct_deviation is not None:
            limit = rule.point_pct_dev_max
            if rule.low_point_pct_dev_max and (
                    r.level in ("1", "low", "MRL")
                    or (lowest_expected is not None and r.expected_conc == lowest_expected)
                    or _low_level(profile, r, analyte, "")):
                limit, lowest = rule.low_point_pct_dev_max, True
            # instrument criteria are judged unrounded, but not on
            # floating-point noise: 30.000000004 % is a calibrator AT 30 %
            if round(abs(r.pct_deviation) * 100, 9) > limit:
                issues.append(f"dev={r.pct_deviation*100:+.1f}%>{limit:.0f}%")
        flag = None
        if issues:
            flag = QCFlag(
                source=f"{profile.method_id} Calibration",
                check_kind=KIND_CALIBRATION,
                analyte=analyte,
                injection_name=r.injection_name,
                value=_format_val(r.pct_deviation),
                issue="(CAL) " + "; ".join(issues),
            )
        results.append(CalibrationResult(
            analyte=analyte, injection_name=r.injection_name,
            concat_id=r.concat_id, r2=r.r2,
            calculated_conc=r.calculated_conc,
            pct_deviation=r.pct_deviation, flag=flag, limit=limit, r2_min=rule.r2_min, lowest=lowest,
        ))
    return results


# is_check_profiled was removed on 2026-08-05. Its profile logic was MERGED into
# is_raw_check (which alone knows the surrogate-vs-injection-IS distinction and
# the dilution correction), leaving this a dead twin of live code. A merge that
# leaves the original in place is the §1.3 duplication this project keeps
# rediscovering -- delete the twin, do not leave it for the next reader to
# choose between.

def rrt_check_profiled(
    profile: MethodProfile,
    rows: list[InstrumentRow],
    analyte: str,
) -> list[RTResult]:
    """
    Retention-time check using the profile's rule:
      FDA:   relative RT deviation ≤1% of the standard's RT
      537.1: absolute ±0.05 min
    Falls back to legacy ±0.10 min absolute when the profile sets neither.
    """
    conf = profile.confirmation_rule()
    std_rows = [r for r in rows
                if r.compound_name == analyte
                and r.sample_type == "Standard" and r.observed_rt]
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
                    )
            elif conf.rt_tol_abs_min is not None:
                if abs(rt - avg_rt) > conf.rt_tol_abs_min:
                    flag = QCFlag(
                        source=f"{profile.method_id} RT",
                check_kind=KIND_RT,
                        analyte=analyte, injection_name=r.injection_name,
                        value=f"{rt:.3f}",
                        issue=f"(RT) dev {rt-avg_rt:+.3f} min "
                              f"> ±{conf.rt_tol_abs_min} min",
                    )
            elif abs(rt - avg_rt) > CRITERIA["rt_dev_abs_min"]:
                flag = QCFlag(
                    source="RT Deviation",
                check_kind=KIND_RT, analyte=analyte,
                    injection_name=r.injection_name, value=f"{rt:.3f}",
                    issue=f"(RT) dev {rt-avg_rt:+.3f} min (legacy ±0.10)",
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
    (%diff < 20%).  Returns a review-prompt string when confirmation is
    required.

    WIRED 2026-09-25, from `pipeline.build_summary` — the only place that knows
    whether an analyte was detected. It had no caller from the day it was
    written; this docstring claimed "used by the run queue" and
    ranked it the most consequential remaining code gap.

    `detected` must mean DETECTED, not quantified: BLoQ and ALoQ both count,
    because §10.2(4) is about establishing identity, not about the number.

    Which analytes need confirming comes from the method's confirmation_rule, so
    this returns None on EPA 537.1 and EPA 1633A, whose
    `single_transition_analytes` are empty. Method-conditional by data.
    """
    conf = profile.confirmation_rule()
    if detected and analyte in conf.single_transition_analytes:
        return (f"{analyte} positive detect: single MS/MS transition — "
                f"confirm by an orthogonal technique "
                f"({conf.confirm_technique})"
                + (f"; %diff between techniques must be < {conf.confirm_pct_diff_max:g}%"
                   if conf.confirm_pct_diff_max is not None else
                   "; no %diff limit is set (Method Profiles -> Calibration & CCV)"))
    return None



# ── Checks behind the rule switches ──────────────────────────────────────────
# Pure: the caller has already resolved the limit and confirmed the result
# and the limit are in the same unit family (run_queue._units_compatible).

def blank_check(analyte: str, injection_name: str, conc: Optional[float],
                rl: float, max_x_rl: float, unit: str, role: str = "MB",
                fails_at_limit: bool = False) -> Optional[QCFlag]:
    """A blank's analyte above max_x_rl x RL (QC Types tier); AT the limit
    too where the method says so (EPA 537.1 §9.3.1: an LRB "equal to or
    greater than" 1/3 MRL invalidates the batch;)."""
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


# the blanks judged against the Blank limits (the field reagent blank borrows
# the method blank's rule): one list for the check and the stored rows
BLANK_ROLES = frozenset(("MB", "LRB", "MxB", "CCB"))
# what a method may leave out of the "CCV every N" count: EPA 537.1 §10.3,
# "a 'sample' is considered to be a Field Sample. LRBs, CCCs, LFBs, LFSMs,
# FDs, FRBs and LFSMDs are not counted as samples" -- the extraction batch's
# QC roles (their one list, extraction_batch.QC_ROLES) and the field QC
def _extracted_qc_roles():
    from .addon import load
    return frozenset(load("extraction_batch").QC_ROLES) | frozenset(("FRB", "FD"))


EXTRACTED_QC_ROLES = _extracted_qc_roles()


def ccv_frequency_check(sequence: list, n: int, opening_required: bool = False,
                        counts_extracted_qc: bool = True) -> list:
    """`sequence`: [(injection_name, role)] in run order. A counting
    injection (everything in the bracketed body: field samples AND extracted
    QC -- the Run Builder's rule) is flagged when more than `n` counting
    injections have run since the last CCV, or when no CCV follows it (the
    run was not closed). With `opening_required` (the method's Calibration &
    CCV setting; EPA 537.1 §10.3 opens every analysis batch with a CCC), a
    counting injection before any CCV was never bracketed and is flagged
    (end-to-end suite finding F1); without it, as before, those
    are pre-bracket. Calibrators, ICVs and solvent blanks are never counted;
    extracted QC and field reagent blanks only where the method counts them
    (its Calibration & CCV setting)."""
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
                        f"only (parent {parent}) -- no RPD; review")
