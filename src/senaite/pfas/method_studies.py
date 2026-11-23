# -*- coding: utf-8 -*-
"""Method studies: the calculations.

Sources, quoted in:
  EPA 537.1 v2.0 (EPA/600/R-20/006) §9.2 -- Initial Demonstration of
      Capability: precision (§9.2.3: the RSD of the replicates, against
      the method profile's LFB RSD limit), accuracy (§9.2.4: the mean
      recovery, against the LFB tier's recovery window), MRL confirmation
      (§9.2.6), detection limit (§9.2.8.1), MRL from blanks (§9.2.8.2),
      low system background (§9.2.2 -> §9.3.1), QCS (§9.2.7 -> §9.3.10),
      peak asymmetry (§9.2.5).
  40 CFR 136 Appendix B, Revision 2 (EPA 821-R-16-006, December 2016) --
      the MDL: MDL_s from spiked samples, MDL_b from method blanks, the
      greater of the two; ongoing annual verification.

Every function is pure: values in, a result dict out, with each number the
verdict rests on. Python 2.7 and 3; no dependencies.

    t99(df)                                 one-tailed 99 % Student t
    precision_accuracy(measured, fortified, rsd_max, recovery_window=)  §9.2.3 / §9.2.4
    mrl_confirmation(measured, fortified)    §9.2.6
    detection_limit(results)                 §9.2.8.1
    mrl_from_blanks(blanks)                  §9.2.8.2
    low_background(values, mrl)              §9.2.2 / §9.3.1
    qcs(measured, true)                      §9.2.7 / §9.3.10
    peak_asymmetry(factors)                  §9.2.5
    mdl_rev2(spikes, blanks, existing=None)  App. B Rev. 2 §2(d)-(e), §4(f)
"""
from __future__ import absolute_import, division, unicode_literals

import math

# ── Student t ────────────────────────────────────────────────────────────────


def _betacf(a, b, x):
    """Continued fraction for the regularised incomplete beta (Lentz)."""
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _ibeta(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _t_cdf(t, df):
    x = df / (df + t * t)
    tail = 0.5 * _ibeta(df / 2.0, 0.5, x)
    return 1.0 - tail if t >= 0 else tail


# App. B Rev. 2, Addendum Table 1: degrees of freedom (n - 1) -> t(n-1, 0.99)
TABLE_1 = {6: 3.143, 7: 2.998, 8: 2.896, 9: 2.821, 10: 2.764, 15: 2.602, 20: 2.528,
           25: 2.485, 30: 2.457, 31: 2.453, 47: 2.408, 49: 2.405, 60: 2.390, 63: 2.387,
           79: 2.374, 95: 2.366, 99: 2.365}


def t_source(df):
    """Where t99(df) comes from: Table 1, or the §2(d)(ii) definition for
    degrees of freedom the table does not list."""
    return u"Table 1" if df in TABLE_1 else u"calculated, not in Table 1"


def t99(df):
    """The single-tailed 99th percentile t statistic for `df` degrees of
    freedom (App. B Rev. 2 §2(d)(ii)): the Table 1 value where the table
    lists `df`, else the same statistic from the t distribution."""
    if df in TABLE_1:
        return TABLE_1[df]
    return t99_exact(df)


def t99_exact(df):
    """The single-tailed 99th percentile of Student's t with `df` degrees of
    freedom, from the distribution itself."""
    lo, hi = 0.0, 100.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _t_cdf(mid, df) < 0.99:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ── small statistics ─────────────────────────────────────────────────────────

def _mean(xs):
    return sum(xs) / len(xs)


def _sd(xs):
    """Sample standard deviation (n - 1)."""
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _nums(values):
    return [float(v) for v in values if v is not None]


# ── EPA 537.1 §9.2 ───────────────────────────────────────────────────────────

NO_PRECISION_LIMIT = u"no RSD limit for the LFB at this level in the method profile (QC criteria)"
NO_ACCURACY_WINDOW = u"no recovery window for the LFB at this level in the method profile (QC criteria)"

# the places a percentage is compared at: float noise never decides a value at its limit
JUDGED_PLACES = 6


# The notes, reasons and rules a study shows carry no section number: the
# Help entry (method-studies) names the sources.
_CITED = (u"\u00a7", u"App. B")


def plain_note(text):
    """A study's note as shown: a bracketed section reference ("(\u00a72(b))",
    "(App. B 4(f))") left out, so a result stored before the notes were
    plain reads as a fresh one; the stored record is not changed."""
    text = text or u""
    out, i = [], 0
    while i < len(text):
        if text[i] == u"(" and text[i + 1:].lstrip().startswith(_CITED):
            depth, j = 0, i
            while j < len(text):
                depth += {u"(": 1, u")": -1}.get(text[j], 0)
                if depth == 0:
                    break
                j += 1
            if depth == 0:
                while out and out[-1] == u" ":
                    out.pop()
                i = j + 1
                continue
        out.append(text[i])
        i += 1
    return u"".join(out).strip()


def precision_accuracy(measured, fortified, rsd_max=None, limit_problem=None, recovery_window=None):
    """§9.2.3 / §9.2.4: four to seven replicate LFBs near mid-calibration.
    Precision is their RSD, at most `rsd_max`; accuracy is their mean
    recovery, within `recovery_window` (low, high), both ends included.
    Both limits are the method profile's LFB tier at the fortified level,
    never numbers of this module's; one not set (`limit_problem` says why
    when the tier itself is missing) is not evaluated."""
    xs = _nums(measured)
    out = {"n": len(xs), "fortified": fortified, "rsd_max": rsd_max,
           "recovery_window": list(recovery_window) if recovery_window else None}
    if not 4 <= len(xs) <= 7:
        out.update(verdict="not evaluated", reason="needs 4 to 7 replicates")
        return out
    mean, sd = _mean(xs), _sd(xs)
    rsd = 100.0 * sd / mean if mean else None
    rec = 100.0 * mean / fortified
    if rsd_max is None:
        precision = "not evaluated"
    else:
        precision = "pass" if rsd is not None and round(rsd, JUDGED_PLACES) <= float(rsd_max) else "fail"
    if not recovery_window:
        accuracy = "not evaluated"
    else:
        lo, hi = float(recovery_window[0]), float(recovery_window[1])
        accuracy = "pass" if lo <= round(rec, JUDGED_PLACES) <= hi else "fail"
    out.update(mean=mean, sd=sd, rsd_pct=rsd, mean_recovery_pct=rec,
               precision=precision, accuracy=accuracy)
    if "fail" in (precision, accuracy):
        out["verdict"] = "fail"
    elif "not evaluated" in (precision, accuracy):
        why = [t for t, judged in ((NO_PRECISION_LIMIT, precision), (NO_ACCURACY_WINDOW, accuracy))
               if judged == "not evaluated"]
        out.update(verdict="not evaluated", reason=limit_problem or u"; ".join(why))
    else:
        out["verdict"] = "pass"
    return out


HR_PIR_7 = 3.963     # §9.2.6.1: "a constant value for seven replicates"


def mrl_confirmation(measured, fortified):
    """§9.2.6: seven replicate LFBs at the proposed MRL; HR_PIR = 3.963 s;
    Upper PIR <= 150 %, Lower PIR >= 50 % of the fortified concentration."""
    xs = _nums(measured)
    out = {"n": len(xs), "fortified": fortified}
    if len(xs) != 7:
        out.update(verdict="not evaluated", reason="needs seven replicates")
        return out
    mean, s = _mean(xs), _sd(xs)
    hr = HR_PIR_7 * s
    upper, lower = 100.0 * (mean + hr) / fortified, 100.0 * (mean - hr) / fortified
    ok = upper <= 150.0 and lower >= 50.0
    out.update(mean=mean, sd=s, hr_pir=hr, upper_pir_pct=upper, lower_pir_pct=lower,
               verdict="pass" if ok else "fail",
               reason=u"" if ok else u"the MRL is set too low; determine it again at a "
                                     u"higher concentration")
    return out


def detection_limit(results):
    """§9.2.8.1: at least seven replicate LFBs near the DL, prepared and
    analysed over at least three days; DL = s x t(n-1, 0.99). No blank is
    subtracted; no accuracy criterion. `results` = [(value, date)]."""
    xs = _nums(v for v, _d in results)
    days = sorted(set(d for v, d in results if v is not None and d))
    out = {"n": len(xs), "days": len(days)}
    if len(xs) < 7:
        out.update(verdict="not evaluated", reason="needs at least seven replicates")
        return out
    s, t = _sd(xs), t99(len(xs) - 1)
    out.update(sd=s, t=t, dl=s * t, mean=_mean(xs), verdict="calculated",
               reason=u"" if len(days) >= 3 else u"fewer than three days")
    return out


def mrl_from_blanks(blanks):
    """§9.2.8.2 (recommended): the greater of mean LRB + 3 sigma and three
    times the mean LRB, over a period of time."""
    xs = _nums(blanks)
    if len(xs) < 2:
        return {"n": len(xs), "verdict": "not evaluated", "reason": "needs blank results"}
    mean, s = _mean(xs), _sd(xs)
    return {"n": len(xs), "mean": mean, "sd": s, "mrl": max(mean + 3.0 * s, 3.0 * mean),
            "verdict": "calculated"}


def low_background(values, mrl):
    """§9.2.2 -> §9.3.1: every LRB analyte below one third of the MRL."""
    limit = mrl / 3.0
    over = [v for v in _nums(values) if v >= limit]
    return {"limit": limit, "over": over, "verdict": "pass" if not over else "fail"}


def qcs(measured, true):
    """§9.2.7 -> §9.3.10: a second-source standard within 70-130 %."""
    rec = 100.0 * measured / true
    return {"recovery_pct": rec, "verdict": "pass" if 70.0 <= rec <= 130.0 else "fail"}


def peak_asymmetry(factors):
    """§9.2.5: the first two eluting peaks of a mid-level CAL, 0.8-1.5."""
    xs = _nums(factors)
    bad = [x for x in xs if not 0.8 <= x <= 1.5]
    return {"factors": xs, "verdict": "pass" if xs and not bad else ("fail" if bad else "not evaluated")}


# ── 40 CFR 136 Appendix B, Revision 2 ────────────────────────────────────────

def _rank_99(blanks):
    """§2(d)(iii)(B): n >= 100 -- the (n x 0.99)-th ranked result, the rank
    rounded to the nearest whole number (164 -> 162nd)."""
    xs = sorted(blanks)
    rank = int(math.floor(len(xs) * 0.99 + 0.5))
    return xs[max(rank, 1) - 1]


def mdl_rev2(spikes, blanks, existing=None):
    """MDL_s, MDL_b and the MDL (the greater), per App. B Rev. 2.

    No blank is subtracted from a spiked result: MDL_s is t x S of the
    spiked results as measured (§2(d)(ii)), and the background is assessed
    by MDL_b from the method blanks (§2(d)(iii)). Spiked samples are made
    in a clean reference matrix (Scope and Application), so a low-level
    matrix spike made in blank matrix is pooled as it is measured.

    spikes  [(value, date, batch)] -- spiked samples (value None = no
            numerical result)
    blanks  [value or None] -- method blank results; None = "ND" (no peak).
            A numerical result includes negatives and values below the
            current MDL (§2(d)(iii)(A)).
    existing  the MDL in force, for the §4(f) comparison.
    """
    out = {"n_spikes": 0, "n_blanks": len(blanks or []), "notes": []}
    vals = [v for v, _d, _b in spikes]
    if any(v is None or v <= 0 for v in vals):
        out["notes"].append(u"a spiked sample gave no numerical result above zero: "
                            u"repeat the spikes at a higher concentration")
    xs = _nums(v for v in vals if v is not None and v > 0)
    out["n_spikes"] = len(xs)
    batches = set(b for v, _d, b in spikes if v is not None and b)
    dates = set(d for v, d, _b in spikes if v is not None and d)
    if len(xs) < 7 or len(blanks or []) < 7:
        out["notes"].append(u"at least seven spiked samples and seven method blanks")
    if len(batches) < 3 or len(dates) < 3:
        out["notes"].append(u"spiked samples from at least three batches on three dates")
    if len(xs) >= 2:
        s_s, t_s = _sd(xs), t99(len(xs) - 1)
        out.update(sd_spikes=s_s, t_spikes=t_s, t_spikes_source=t_source(len(xs) - 1),
                   mdl_s=t_s * s_s, mean_spikes=_mean(xs))
    numeric = _nums(blanks or [])
    if not numeric:
        out["mdl_b"] = None
        out["mdl_b_rule"] = u"no method blank gave a numerical result: MDLb does not apply"
    elif len(numeric) < len(blanks):
        if len(blanks) >= 100:
            v = _rank_99(numeric + [float("-inf")] * (len(blanks) - len(numeric)))
            # an ND at the 99th rank is no number, never -inf
            out["mdl_b"] = None if v == float("-inf") else v
            out["mdl_b_rule"] = (u"99th percentile by rank, n >= 100" if out["mdl_b"] is not None
                                 else u"the blank at the 99th percentile gave no numerical result")
        else:
            out["mdl_b"] = max(numeric)
            out["mdl_b_rule"] = u"some blanks numerical: the highest result"
    elif len(numeric) < 2:
        # one blank has no standard deviation
        out["mdl_b"] = None
        out["mdl_b_rule"] = u"one method blank: no standard deviation"
    else:
        mean_b, s_b, t_b = _mean(numeric), _sd(numeric), t99(len(numeric) - 1)
        out.update(mean_blanks=mean_b, sd_blanks=s_b, t_blanks=t_b,
                   t_blanks_source=t_source(len(numeric) - 1),
                   mdl_b=max(mean_b, 0.0) + t_b * s_b,
                   mdl_b_rule=u"all blanks numerical: mean (zero if negative) + t x S")
    candidates = [v for v in (out.get("mdl_s"), out.get("mdl_b")) if v is not None]
    out["mdl"] = max(candidates) if candidates else None
    if existing and out["mdl"] is not None:
        ratio = out["mdl"] / existing
        above = len([v for v in numeric if v > existing])
        share = 100.0 * above / len(blanks) if blanks else 0.0
        out.update(ratio_to_existing=ratio, pct_blanks_above_existing=share,
                   may_keep_existing=0.5 <= ratio <= 2.0 and share < 3.0)
    out["verdict"] = "calculated" if out["mdl"] is not None and not out["notes"] else (
        "calculated with notes" if out["mdl"] is not None else "not evaluated")
    return out
