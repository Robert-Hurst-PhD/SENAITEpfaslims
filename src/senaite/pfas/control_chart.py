# -*- coding: utf-8 -*-
"""Levey-Jennings control charts, with the Westgard rules as an optional view
written here because the one maintained SPC package is GPLv3.

    points = [{"id": <qc_results id>, "value": float, ...}, ...]   oldest first

* limits(values)          mean, SD and the +/-1/2/3 SD lines from the first
                          20 values (the baseline); None below 5 values
* lj_warnings(points, L)  one warning per point beyond +/-2 SD, marked as
                          beyond the +/-3 SD control limit when it is
* westgard(points, L)     the multi-rule set (1-2s, 1-3s, 2-2s, R-4s, 4-1s,
                          10x) for the Westgard view
* active(warnings, dismissed)  warnings not dismissed
* ready(L)                the limits stand: drawn and judged only from
                          BASELINE_N results; fewer, and the chart says so
* insight_title(points, flags, ...)   the chart's heading: what it shows,
                          not what it plots
* point_marks / threshold_marks       each point's severity and the rule
                          lines its tooltip leads with
* check_window(lim, qc)   the method's recovery window for a CCV / ICV
* axis_window(judged, fb) the y axis while there are too few points: the
                          windows the points were judged in
* point_rows / points_csv the plotted points as the Download gives them

A warning's `key` is "<point id>:<rule>" -- what a dismissal is recorded
against, so dismissing one rule on a point leaves its other rules standing.
Removed (excluded) points are taken out BEFORE any of this: they are off the
chart, out of the baseline and raise nothing. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

import math

BASELINE_N = 20
MIN_POINTS = 5


def limits(values, n_baseline=BASELINE_N):
    valid = [float(v) for v in values
             if v is not None and not (math.isinf(v) or math.isnan(v))]
    if len(valid) < MIN_POINTS:
        return None
    base = valid[:n_baseline]
    n = len(base)
    mean = sum(base) / n
    sd = (sum((x - mean) ** 2 for x in base) / (n - 1)) ** 0.5
    if sd == 0.0:
        sd = max(abs(mean) * 0.01, 0.01)
    out = {"mean": round(mean, 4), "sd": round(sd, 4), "n_baseline": n}
    for k in (1, 2, 3):
        out["ucl_%d" % k] = round(mean + k * sd, 4)
        out["lcl_%d" % k] = round(mean - k * sd, 4)
    return out


def _sigmas(points, lim):
    mean, sd = lim["mean"], lim["sd"]
    return [(p["value"] - mean) / sd if sd else 0.0 for p in points]


def _warning(points, indices, rule, message, severity):
    first = points[indices[-1]]
    return {"key": u"%s:%s" % (first.get("id"), rule), "rule": rule,
            "message": message, "severity": severity,
            "indices": list(indices), "point_id": first.get("id")}


def lj_warnings(points, lim):
    """Every point beyond +/-2 SD -- the Levey-Jennings view's warnings."""
    if not lim or not points:
        return []
    out = []
    for i, s in enumerate(_sigmas(points, lim)):
        if abs(s) > 3.0:
            out.append(_warning(points, [i], u"3SD",
                                u"Beyond the ±3 SD control limit", u"reject"))
        elif abs(s) > 2.0:
            out.append(_warning(points, [i], u"2SD",
                                u"Beyond ±2 SD", u"warning"))
    return out


def westgard(points, lim):
    """The Westgard multi-rule set over the points, oldest first."""
    if not lim or not points:
        return []
    sig = _sigmas(points, lim)
    out, seen = [], set()

    def add(rule, message, severity, idx):
        if (rule, tuple(idx)) not in seen:
            seen.add((rule, tuple(idx)))
            out.append(_warning(points, idx, rule, message, severity))

    for i, s in enumerate(sig):                       # every point, the first too
        if abs(s) > 3.0:
            add(u"1-3s", u"One value beyond ±3 SD", u"reject", [i])
        elif abs(s) > 2.0:
            add(u"1-2s", u"One value beyond ±2 SD (warning)", u"warning", [i])
        if i >= 1:
            p = sig[i - 1]
            if (s > 2.0 and p > 2.0) or (s < -2.0 and p < -2.0):
                add(u"2-2s", u"Two consecutive values beyond the same 2 SD", u"reject", [i - 1, i])
            if abs(s - p) >= 4.0:
                add(u"R-4s", u"Adjacent values 4 SD or more apart", u"reject", [i - 1, i])
        if i >= 3:
            run = sig[i - 3:i + 1]
            if all(v > 1.0 for v in run) or all(v < -1.0 for v in run):
                add(u"4-1s", u"Four consecutive values beyond the same 1 SD",
                    u"reject", list(range(i - 3, i + 1)))
        if i >= 9:
            run = sig[i - 9:i + 1]
            if all(v > 0 for v in run) or all(v < 0 for v in run):
                add(u"10x", u"Ten consecutive values on one side of the mean",
                    u"reject", list(range(i - 9, i + 1)))
    return out


def active(warnings, dismissed_keys):
    """The warnings still standing (not dismissed)."""
    dismissed_keys = set(dismissed_keys or ())
    return [w for w in warnings if w["key"] not in dismissed_keys]


def ready(lim):
    """Control limits stand on BASELINE_N in-control results; on fewer the
    chart draws no limit and judges no point."""
    return bool(lim) and lim.get("n_baseline", 0) >= BASELINE_N


# ── The heading, each point's rule and the download ─────────────────────────

# a count reads as a word up to twelve, then in digits
_COUNT_WORDS = (u"None", u"One", u"Two", u"Three", u"Four", u"Five", u"Six", u"Seven",
                u"Eight", u"Nine", u"Ten", u"Eleven", u"Twelve")
_MONTHS = (u"Jan", u"Feb", u"Mar", u"Apr", u"May", u"Jun", u"Jul", u"Aug", u"Sep",
           u"Oct", u"Nov", u"Dec")
MINUS = u"\u2212"
# the rules that judge one value against one limit, and that limit in SD
_ONE_VALUE = {u"3SD": 3, u"1-3s": 3, u"2SD": 2, u"1-2s": 2}
_LJ_RULES = (u"3SD", u"2SD")


def count_words(n, capital=True):
    word = _COUNT_WORDS[n] if 0 < n < len(_COUNT_WORDS) else u"%d" % n
    return word if capital else word.lower()


def _counted(n, noun, capital=True):
    return u"%s %s%s" % (count_words(n, capital), noun, u"" if n == 1 else u"s")


def day_month(iso):
    """"2026-10-03" reads "3 Oct"; anything else reads ""."""
    try:
        _y, m, d = (iso or u"")[:10].split(u"-")
        if not 1 <= int(d) <= 31:
            return u""
        return u"%d %s" % (int(d), _MONTHS[int(m) - 1]) if 1 <= int(m) <= 12 else u""
    except (ValueError, IndexError):
        return u""


def rule_label(rule):
    """A Westgard rule as it is written: "1-3s" reads "1-3S", "10x" "10X"."""
    return rule[:-1] + rule[-1].upper() if rule and rule[-1] in u"sx" else rule


def _crossed(rule, value, lim):
    """The limit a one-value rule says the point crossed ("above +3 SD",
    "below \u22122 SD"); None for a rule over several values."""
    k = _ONE_VALUE.get(rule)
    if k is None or not lim or value is None:
        return None
    return u"above +%d SD" % k if value > lim["mean"] else u"below %s%d SD" % (MINUS, k)


def rule_line(w, value, lim):
    """The line a flagged point's tooltip leads with: "Westgard 1-3S: above
    +3 SD", "Levey-Jennings: below \u22122 SD"."""
    rule = w.get("rule") or u""
    head = u"Levey-Jennings" if rule in _LJ_RULES else u"Westgard " + rule_label(rule)
    msg = w.get("message") or u""
    what = _crossed(rule, value, lim) or (msg[:1].lower() + msg[1:])
    return u"%s: %s" % (head, what)


def point_marks(points, flags, lim):
    """(severity, rule lines) per point: severity "reject", "warning" or
    "" (a reject is never downgraded by a warning on the same point)."""
    sev = [u""] * len(points)
    lines = [[] for _p in points]
    for w in flags or []:
        for i in w.get("indices") or []:
            if not 0 <= i < len(points):
                continue
            if sev[i] != u"reject" and (w["severity"] == u"reject" or not sev[i]):
                sev[i] = w["severity"]
            lines[i].append(rule_line(w, points[i].get("value"), lim))
    return sev, lines


def _g(v):
    return u"%g" % v


def threshold_marks(points, threshold):
    """A threshold chart judges one thing: a point above the threshold."""
    sev, lines = [], []
    for p in points:
        over = threshold is not None and p.get("value") is not None and p["value"] > threshold
        sev.append(u"reject" if over else u"")
        lines.append([u"Above the threshold of %s" % _g(threshold)] if over else [])
    return sev, lines


def _when(points, idx):
    days = sorted(set(points[i].get("date") or u"" for i in idx))
    day = day_month(days[-1]) if days else u""
    if not day:
        return u""
    return (u" on %s" if len(days) == 1 else u", latest on %s") % day


def _reject_phrase(i, flags, points, lim):
    rules = [w["rule"] for w in flags if w["severity"] == u"reject" and i in w["indices"]]
    for rule in rules:
        crossed = _crossed(rule, points[i].get("value"), lim)
        if crossed:
            return crossed
    return u"fail " + rule_label(rules[0])


def insight_title(points, flags, noun=u"result", lim=None, chart=u"levey_jennings",
                  threshold=None, dismissed=0, recorded=None):
    """The chart's heading as what it shows: "Two CCVs above +3 SD on 10
    Oct", "One CCV in the warning band on 10 Oct", "All 20 CCVs within
    limits", "Six CCVs shown; control limits need 20 in-control results".
    `flags` are the warnings still standing; `recorded` is how many the
    store holds under the page's filters, said when more than are shown. A
    threshold chart names what is above its threshold and never claims
    limits it does not judge."""
    n = len(points)
    if not n:
        return u"No %ss recorded yet" % noun
    if chart == u"threshold":
        if threshold is None:
            return u"%s shown; no threshold set" % _counted(n, noun)
        over = [i for i, p in enumerate(points) if p.get("value") is not None and p["value"] > threshold]
        if over:
            return u"%s above the threshold%s" % (_counted(len(over), noun), _when(points, over))
        if n == 1:
            return u"The one %s is within the threshold" % noun
        return u"All %s within the threshold" % _counted(n, noun, capital=False)
    if not ready(lim):
        shown = u"%s shown" % _counted(n, noun)
        if recorded is not None and recorded > n:
            shown += u" of %d recorded" % recorded
        return u"%s; control limits need %d in-control results" % (shown, BASELINE_N)
    flags = flags or []
    rejects = sorted(set(i for w in flags if w["severity"] == u"reject"
                         for i in w["indices"] if 0 <= i < n))
    if rejects:
        phrases = set(_reject_phrase(i, flags, points, lim) for i in rejects)
        # one limit names them all, or they are simply out of control (a
        # rule over several values rejects a point that crossed no limit)
        what = phrases.pop() if len(phrases) == 1 else u"out of control"
        return u"%s %s%s" % (_counted(len(rejects), noun), what, _when(points, rejects))
    warned = sorted(set(i for w in flags if w["severity"] == u"warning"
                        for i in w["indices"] if 0 <= i < n))
    if warned:
        return u"%s in the warning band%s" % (_counted(len(warned), noun), _when(points, warned))
    if dismissed:
        return u"No open warnings on %d %ss; %s dismissed" % (n, noun, count_words(dismissed, capital=False))
    return u"All %s within limits" % _counted(n, noun, capital=False)


def check_window(lim, qc_type):
    """(low, high) recovery % the method judges a CCV or an ICV in, from its
    limits (the Calibration Archive's method_limits, read as the worker
    judges): the CCV window; an ICV's own +/- deviation unless it takes the
    CCV's. None when the method sets no whole window, when it also sets a
    low-level window (a check standard at or below the MRL is judged in
    that one, and which applies is not known here), or when the type is
    not a check standard."""
    ccv = (lim or {}).get("CCV") or {}
    low = ccv.get("low_min") is not None or ccv.get("low_max") is not None
    win = ((ccv["min"], ccv["max"]) if ccv.get("min") is not None and ccv.get("max") is not None
           and not low else None)
    if qc_type == u"CCV":
        return win
    if qc_type == u"ICV":
        icv = (lim or {}).get("ICV") or {}
        if icv.get("same_as_ccv"):
            return win
        m = icv.get("max")
        return None if m is None else (100.0 - m, 100.0 + m)
    return None


def _whole(w):
    return bool(w) and w[0] is not None and w[1] is not None


def axis_window(judged, fallback=None):
    """The y axis while there are too few points for limits: the span of the
    windows the points were judged in (each check standard and spike records
    its own; a CCV at or below the MRL its low-level one). A point that
    recorded none takes `fallback` (the method's window); with none for it,
    None: the axis is the data's own, never an invented window."""
    wins = []
    for w in judged or []:
        w = w if _whole(w) else fallback
        if not _whole(w):
            return None
        wins.append(w)
    if not wins:
        return None
    return (min(w[0] for w in wins), max(w[1] for w in wins))


POINT_COLUMNS = (u"date", u"run", u"injection", u"analyte", u"value", u"unit", u"verdict", u"rule")


def _verdict(d, i, sev):
    if d.get("chart_type") == u"threshold":
        if d.get("threshold") is None:
            base = u"not judged"
        else:
            base = u"above threshold" if sev == u"reject" else u"at or below threshold"
    elif d.get("too_few_points"):
        base = u"not judged"
    else:
        base = sev or u"in control"
    status = (d.get("point_status") or [])[i:i + 1]
    status = status[0] if status else u"active"
    if status not in (u"", u"active"):
        base = u"%s \u00b7 %s" % (base, status)
    # a blank's non-detect is charted at 0, hollow; the file says so
    nd = (d.get("point_nd") or [])[i:i + 1]
    return u"%s \u00b7 not detected" % base if nd and nd[0] else base


def point_rows(d):
    """The points the chart draws (its own dict), one row each: date, run,
    injection, analyte, value, unit, verdict, rule."""
    def at(key, i, default=u""):
        seq = d.get(key) or []
        return seq[i] if i < len(seq) else default
    out = []
    for i, v in enumerate(d.get("values") or []):
        sev = at("point_severity", i)
        # a non-detect has no value (the store's null), never a measured 0
        nd = at("point_nd", i, False)
        out.append({u"date": at("dates", i), u"run": at("batch_ids", i),
                    u"injection": at("injections", i), u"analyte": d.get("analyte") or u"",
                    u"value": None if nd else v, u"unit": d.get("unit") or u"",
                    u"verdict": _verdict(d, i, sev),
                    u"rule": u"; ".join(at("point_rules", i, []))})
    return out


def _csv_cell(v):
    """A CSV cell; text a spreadsheet would run as a formula is quoted."""
    from senaite.pfas.raw_compare import _cell
    if isinstance(v, (str, type(u""))) and v[:1] in (u"=", u"+", u"-", u"@", u"\t", u"\r"):
        v = u"'" + v
    return _cell(v)


def points_csv(rows):
    out = [u",".join(POINT_COLUMNS)]
    for r in rows:
        out.append(u",".join(_csv_cell(r.get(k)) for k in POINT_COLUMNS))
    return u"\r\n".join(out) + u"\r\n"
