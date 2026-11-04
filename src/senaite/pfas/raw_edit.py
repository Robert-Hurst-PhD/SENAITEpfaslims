# -*- coding: utf-8 -*-
"""An analyst's edit of one raw trace, posted from Data Review's Raw Data
tab, judged before anything is written.

    decide(form, traces, rows, overrides, integration, labelled=(), open_changes=())
        (refusal, None) when the edit is refused, nothing to be written;
        (None, plan) when it may be made: the trace's key parts, the edit
        to keep beside the run, and the automatic and edited peak for the
        list of manual changes
    method_baseline(peak, integration)
        the baseline the automatic peak was measured on
    edge_tolerance(t, full_res)
        how far past the full-resolution region an edge may sit
    edited_reads(overrides, dropped)
        the traces to read for whether the edits are processed
    waiting(edited_at, imports, overrides, unshown)
        whether the run's edits wait for it to be processed again
    submit_refusal(waiting, imports)
        why submit and release wait on the run: its failure, or its edits

The form's fields: injection, analyte, transition (empty for the
quantifier), kind (integrate, apex, delete, revert), start and end
(integrate), apex (apex), baseline (integrate or apex: valley, drop, flat or
skim, empty for the method's), level_start and level_end (integrate: the
baseline's two levels set by hand, in counts, both or neither), confirm (1
to delete an isotope standard's quantifier peak). No reason is asked when
an edit is made.

`traces` are the injection's raw_traces rows for the analyte (t / y
unpacked, peak parsed), `rows` the run's result rows as the tab shows them,
`overrides` the run's edits, `integration` the method's Integration block,
`labelled` the method's labelled standards (its grid's keywords),
`open_changes` the (injection, analyte, transition) of the Manual changes
records still open (transition None for the quantifier). Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

from senaite.pfas import raw_preview, raw_review

KINDS = ("integrate", "apex", "delete", "revert")
# the automatic peak's measures the list of manual changes keeps
PEAK_FIELDS = ("start", "end", "apex", "base_start", "base_end", "area")
# a result row's role for an isotope standard, as each side stores it
IS_ROLES = ("is", "internal standard")
# the stored measures the preview of a manual peak reads, by engine
PREVIEW_FIELDS = {"classic": ("smooth_points", "edge_points"), "adaptive": ("smoothing",)}

STORED_BEFORE = "This trace was stored before it could be edited: process the run again."
# an Adaptive trace whose smoothing was never set keeps none to preview with
NO_SMOOTHING = "Set the compound's smoothing on the Integration tab, then process the run again."
# a qualifier is read only beside a quantifier peak: its edit would change nothing
NO_QUANT_TEXT = "The quantifier has no peak in %s: a qualifier edit would have no effect."
WAITING_TEXT = "Edits are waiting for the run to be processed again. Submit once it has."
BASELINE_TEXT = "The baseline is Valley, Drop, Flat or Skim."
# the posted levels of a re-integration's baseline, at its start and its end
LEVEL_FIELDS = ("level_start", "level_end")


def sentence(clause):
    """The worker's clause (raw_review's words for an edit kept with no
    effect) as a refusal: capitalised, with a full stop."""
    return clause[:1].upper() + clause[1:] + "."


# a re-integration the worker would keep with no effect, refused here first
# in the worker's own words: fewer points than the compound's fewest, levels
# set by hand outside the trace's counts
FEWEST_POINTS_TEXT = sentence(raw_review.TOO_FEW_POINTS)
# a drop or a skim whose neighbour walk, and the points read beyond it,
# leave the samples the stored trace keeps at full resolution: the review
# would measure on thinned samples what the run measures on all of them
REACH_TEXT = ("A %s from these edges reads past the trace's full-resolution region, %.3f to %.3f min: "
              "choose other edges or another baseline.")
# a trace stored before it kept the neighbours' reach
REACH_BEFORE = "This trace was stored before a %s could be measured on it: process the run again."
# an edge nearer the apex than the method's edges past the tail
EDGE_NOTE = "The %s lies %s sigma from the apex, under the method's %g sigma for an edge."
# the notes a decision returns for the card: a drop whose valley stands too
# high, a skim whose peak is too tall beside its parent; never a refusal
VALLEY_NOTE = ("The valley stands at %.0f %% of the smaller peak's height, above the method's %g %% "
               "for a perpendicular drop.")
SKIM_NOTE = "The peak is %.0f %% of its parent's height, above the method's %g %% for a tangent skim."


def text(form, name):
    """A posted field as stripped text ("" when absent); bytes read as UTF-8."""
    value = form.get(name)
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return ("%s" % value).strip()


def _number(form, name, what):
    given = text(form, name)
    if not given:
        raise ValueError("Give the %s." % what)
    try:
        value = float(given)
    except ValueError:
        raise ValueError("The %s is a number." % what)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("The %s is a number." % what)
    return value


def parse(form):
    """(kind, edit, confirm): the posted edit with only its kind's own
    fields. ValueError says what is wrong."""
    kind = text(form, "kind")
    if kind not in KINDS:
        raise ValueError("Choose re-integrate, another apex, delete or undo.")
    edit = {"kind": kind}
    if kind == "integrate":
        edit["start"] = _number(form, "start", "start")
        edit["end"] = _number(form, "end", "end")
        if not edit["start"] < edit["end"]:
            raise ValueError("The start is before the end.")
    elif kind == "apex":
        edit["apex"] = _number(form, "apex", "apex")
    if kind in ("integrate", "apex") and text(form, "baseline"):
        if text(form, "baseline") not in raw_preview.BASELINES:
            raise ValueError(BASELINE_TEXT)
        edit["baseline"] = text(form, "baseline")
    given = [name for name in LEVEL_FIELDS if text(form, name)]
    if given and kind != "integrate":
        raise ValueError("A baseline level is set on a re-integration only.")
    if given:
        if len(given) != len(LEVEL_FIELDS):
            raise ValueError("Give both baseline levels.")
        edit["levels"] = [_number(form, name, "baseline level") for name in LEVEL_FIELDS]
    return kind, edit, text(form, "confirm") in ("1", "true", "on")


def method_baseline(peak, integration):
    """The baseline the automatic peak was measured on: Adaptive's line is
    the valley; Classic's is the method's Integration baseline, valley or
    flat (raw_preview.method_baseline: a "drop" stored before the
    perpendicular drop is the flat line); a stored peak edited with its own
    baseline no longer carries the method's. None when it cannot be
    read."""
    peak = peak or {}
    if (peak.get("engine") or "classic") == "adaptive":
        return "valley"
    named = raw_preview.method_baseline((integration or {}).get("baseline"))
    if named:
        return named
    if not (peak.get("manual") or {}).get("baseline"):
        return raw_preview.method_baseline(peak.get("baseline"))
    return None


def edge_tolerance(t, full_res):
    """Half the median spacing of the points stored at full resolution: an
    edge set at the window's bound may sit that far outside the region."""
    lo, hi = full_res
    inside = [x for x in t or [] if lo <= x <= hi]
    steps = sorted(b - a for a, b in zip(inside, inside[1:]))
    if not steps:
        return 0.0
    mid = len(steps) // 2
    median = steps[mid] if len(steps) % 2 else (steps[mid - 1] + steps[mid]) / 2.0
    return median / 2.0


def snap(t, x, full_res):
    """The stored sample time nearest x among those inside full_res, the
    first of two equally near: the edge the worker stores (it takes the
    nearest sample of the whole trace, and inside full_res the stored
    samples are all of the trace's). None when full_res holds no sample."""
    lo, hi = full_res
    best = None
    for v in t or []:
        if lo <= v <= hi and (best is None or abs(v - x) < abs(best - x)):
            best = v
    return best


def _find(traces, injection, analyte, transition, label=None):
    """(trace, quantifier transition) of the posted trace (`analyte` its
    keyword, `label` the name a refusal shows); ValueError when the run
    holds none."""
    label = label or analyte
    mine = [t for t in traces or [] if t.get("injection") == injection and t.get("analyte") == analyte]
    quant = [t for t in mine if t.get("role") == "quant"]
    if not quant:
        raise ValueError("%s / %s is not in this worksheet's raw run." % (injection, label))
    qt = quant[0]["transition"]
    if not transition or transition == qt:
        return quant[0], qt
    qual = [t for t in mine if t.get("role") == "qual" and t.get("transition") == transition]
    if not qual:
        raise ValueError("%s / %s has no qualifier %s." % (injection, label, transition))
    return qual[0], qt


def _preview(peak, trace, start, end, baseline, levels=None, amp=None):
    engine = peak.get("engine") or "classic"
    return raw_preview.preview(engine, trace["t"], trace["y"], start, end, baseline, peak.get("sigma"),
                               smooth_points=peak.get("smooth_points"), edge_points=peak.get("edge_points"),
                               m=peak.get("smoothing"), levels=levels, amp=amp)


def _auto_area(peak, trace, baseline):
    """The trapezoid over the automatic peak's edges and baseline, as the
    manual one is measured; None when the automatic call found no peak."""
    auto = peak.get("auto") or peak
    if auto.get("start") is None or auto.get("end") is None:
        return None
    try:
        return _preview(peak, trace, auto["start"], auto["end"], baseline)["area"]
    except (TypeError, ValueError):
        return None


def _before(peak, trace, baseline):
    """The automatic peak: the stored automatic peak of an edited trace,
    else the trace's own peak. Its "area" is the trapezoid over its edges
    and the method's baseline, the basis the manual area is measured and
    judged on (None when it cannot be measured); "stored_area" is the area
    the run recorded."""
    auto = peak.get("auto") or peak
    out = dict((k, auto.get(k)) for k in PEAK_FIELDS)
    out["stored_area"] = auto.get("area")
    out["area"] = _auto_area(peak, trace, baseline) if baseline else None
    return out


LIMITS_TEXT = "The method's limits on a manual change are not numbers."
RULES_TEXT = "The method's rules for a manual peak cannot be read: %s."


def review_rules(integration, analyte):
    """(rules, None): the compound's rules for a manual peak
    (raw_preview.review_limits: its fewest points, its peak search
    amplitude, its limits for a drop and a skim), or (None, why) when they
    or the method's limits on a manual change cannot be read. The card
    carries both, so the dialog refuses in the server's words."""
    try:
        raw_preview.manual_limits(integration, analyte)
    except (TypeError, ValueError):
        return None, LIMITS_TEXT
    try:
        return raw_preview.review_limits(integration, analyte), None
    except (TypeError, ValueError) as exc:
        return None, RULES_TEXT % (exc.args[0] if exc.args else "")


def _row(rows, injection, analyte=None):
    """The injection's row of the analyte, or its first row when no analyte
    is named (its sample type is the injection's)."""
    return next((r for r in rows or [] if r.get("injection_name") == injection
                 and (analyte is None or r.get("analyte") == analyte)), None)


def is_standard(rows, injection, analyte, labelled=()):
    """True for an isotope standard: a labelled standard of the method, or a
    row stored with the isotope standard role. Deleting its peak is
    confirmed, and the card says so up front."""
    return bool(analyte in (labelled or ())
                or (_row(rows, injection, analyte) or {}).get("role") in IS_ROLES)


def _measured(peak, trace, start, end, baseline, analyte, levels=None, amp=None):
    """The manual peak previewed between start and end (a drop's or a
    skim's neighbours rising `amp`, the peak search amplitude, times the
    trace's sigma); ValueError says why the edges cannot be measured."""
    full = peak.get("full_res")
    engine = peak.get("engine") or "classic"
    if not full:
        raise ValueError(STORED_BEFORE)
    if engine == "adaptive" and peak.get("smoothing") is None:
        raise ValueError(NO_SMOOTHING)
    if any(peak.get(k) is None for k in PREVIEW_FIELDS.get(engine, ())):
        raise ValueError(STORED_BEFORE)
    tol = edge_tolerance(trace["t"], full)
    if start < full[0] - tol or end > full[1] + tol:
        raise ValueError("The edges lie in the trace's full-resolution region, %.3f to %.3f min. To go "
                         "further, widen the method's window for %s." % (full[0], full[1], analyte))
    try:
        return _preview(peak, trace, start, end, baseline, levels, amp)
    except ValueError as exc:
        raise ValueError("The peak cannot be measured between these edges: %s." % (exc.args[0] if exc.args else ""))


def decide(form, traces, rows, overrides, integration, labelled=(), open_changes=()):
    """(refusal, None) or (None, plan). plan: {"injection", "analyte",
    "transition" (None for the quantifier), "quant_transition", "kind",
    "edit" (None for an undo), "before", "after", "qc_type"}; an undo's
    plan also says whether its edit is already "gone": removed from the run
    while its record stayed open, so only the record is closed.

    Refused, in this order: an injection, analyte or trace the run does not
    hold; an edit that names no kind or whose numbers are not numbers;
    an undo of a trace with neither an edit nor an open record; a
    qualifier edit while the quantifier has no peak (deleted, not
    detected, or its deletion waiting), as a qualifier is read only beside
    a quantifier peak; the deletion of an isotope standard's
    quantifier peak not confirmed, naming the natives that lose their
    concentration; edges outside the full-resolution region (by half a
    sample's spacing) or that cannot be measured; another apex on a trace
    that is not a single peak, or one no candidate holds; a re-integration
    whose edges hold fewer samples than the method's fewest points in a
    peak (min_peak_points, the compound's own over the method's), or whose
    levels set by hand lie outside the stored trace's counts (both in the
    worker's words, raw_review: the worker keeps such an edit with no
    effect); a perpendicular drop or a tangent skim whose neighbour walk
    reads past the stored trace's full resolution (_within_reach); a
    re-integration or another apex under the method's smallest manual
    change or smallest S/N for a manual peak (raw_preview.edit_problem).
    The change is the trapezoid over the manual edges and baseline against
    the trapezoid over the automatic edges and baseline, whatever the
    method's area, and its S/N the preview's height over the trace's
    sigma; except another apex on the method's baseline, which is the
    candidate's own area and S/N
    (raw_preview.apex_preview: the peak the worker replays; none S/N reads
    as no limit) against the automatic peak's own stored area. A deletion
    and an undo are not judged by the limits. A planned re-integration or
    another apex carries "notes" (notes, edge_notes): a drop's valley or a
    skim's height beside its parent past the method's limit, an edge
    nearer its apex than the method's edges past the tail, never a
    refusal. Its "after" names the line it is measured on (the edit's own
    or the method's; none for another apex as found), any levels and the
    record's version, for the list of manual changes."""
    try:
        return None, _plan(form, traces, rows, overrides, integration, labelled, open_changes)
    except ValueError as exc:
        return (exc.args[0] if exc.args else ""), None


def _quant_has_no_peak(traces, overrides, injection, analyte, qt):
    """True when the analyte's quantifier has no peak in this injection: its
    stored peak deleted or with no area, or a deletion of it waiting."""
    quant = [t for t in traces or [] if t.get("injection") == injection and t.get("analyte") == analyte
             and t.get("role") == "quant"][0]
    peak = quant.get("peak") or {}
    waiting = raw_review.edit_for(overrides, injection, analyte, None, qt) or {}
    return bool(peak.get("deleted") or not peak.get("area") or waiting.get("kind") == "delete")


def _plan(form, traces, rows, overrides, integration, labelled, open_changes=()):
    injection, analyte = text(form, "injection"), text(form, "analyte")
    if not injection or not analyte:
        raise ValueError("Name the injection and the analyte.")
    # the rows are keyed (raw_review.keyed_rows): `analyte` is the keyword
    # the traces and edits carry, `label` the name every refusal shows
    label = raw_review.label_of(rows, analyte)
    trace, qt = _find(traces, injection, analyte, text(form, "transition"), label)
    transition = None if trace["role"] == "quant" else trace["transition"]
    kind, edit, confirm = parse(form)
    peak = trace.get("peak") or {}
    auto_base = method_baseline(peak, integration)
    plan = {"injection": injection, "analyte": analyte, "transition": transition, "quant_transition": qt,
            "kind": kind, "edit": edit, "before": _before(peak, trace, auto_base), "after": None,
            "qc_type": (_row(rows, injection) or {}).get("qc_type") or ""}
    if kind == "revert":
        gone = raw_review.edit_for(overrides, injection, analyte, transition, qt) is None
        if gone and (injection, analyte, transition) not in set(open_changes or ()):
            raise ValueError("%s / %s has no edit to undo." % (injection, label))
        plan["edit"], plan["gone"] = None, gone
        return plan
    if transition is not None and _quant_has_no_peak(traces, overrides, injection, analyte, qt):
        raise ValueError(NO_QUANT_TEXT % injection)
    if kind == "delete":
        if transition is None and not confirm:
            natives = raw_review.natives_of(rows, analyte, injection)
            if natives:
                raise ValueError("Deleting the isotope standard peak of %s in %s leaves %s without a "
                                 "concentration. Confirm to delete it." % (label, injection, ", ".join(natives)))
            if is_standard(rows, injection, analyte, labelled):
                raise ValueError("%s is an isotope standard. Confirm to delete its peak in %s."
                                 % (label, injection))
        plan["after"] = {"deleted": True}
        return plan
    if auto_base is None:
        raise ValueError("The method's Integration names no baseline.")
    base = edit.get("baseline") or auto_base
    as_found = False
    rules, problem = review_rules(integration, analyte)
    if problem:
        raise ValueError(problem)
    if kind == "integrate":
        levels = edit.get("levels")
        manual = _measured(peak, trace, edit["start"], edit["end"], base, label, levels, rules["search_amp_sn"])
        # kept as the worker stores them, each on its nearest sample, so the
        # processed trace shows the edit it was given; measured on the same
        # samples, so the preview is unchanged
        full = peak["full_res"]
        edit["start"], edit["end"] = snap(trace["t"], edit["start"], full), snap(trace["t"], edit["end"], full)
        manual = _preview(peak, trace, edit["start"], edit["end"], base, levels, rules["search_amp_sn"])
        # the worker's order: the levels, then the fewest points
        outside = raw_review.levels_outside(trace["y"], levels)
        if outside:
            raise ValueError(sentence(outside))
        points = manual["e"] - manual["s"] + 1
        if points < rules["min_peak_points"]:
            raise ValueError(FEWEST_POINTS_TEXT % (rules["min_peak_points"], points))
        _within_reach(peak, trace, manual, base)
        sn = manual["sn"]
        area = manual["area"]
        after = {"start": edit["start"], "end": edit["end"], "area": area, "baseline": base}
        if levels is not None:
            after["levels"] = levels
    else:
        if "candidates" not in peak:
            raise ValueError("Another apex is chosen only on a single peak.")
        chosen = raw_review.match_candidate(peak, edit["apex"], trace["t"])
        if chosen is None:
            raise ValueError("No peak of %s / %s has its apex at %.3f min: choose one of its candidates."
                             % (injection, label, edit["apex"]))
        manual = _measured(peak, trace, chosen["start"], chosen["end"], base, label, None, rules["search_amp_sn"])
        if edit.get("baseline"):
            _within_reach(peak, trace, manual, base)
            sn = manual["sn"]
        else:
            # as found: the candidate's own measures, the peak the worker
            # replays, judged against the automatic peak's own area; none
            # S/N being no limit
            manual = raw_preview.apex_preview(trace["t"], chosen)
            sn = chosen.get("sn") if chosen.get("sn") is not None else float("inf")
            as_found = True
        area = manual["area"]
        after = {"apex": edit["apex"], "start": chosen["start"], "end": chosen["end"], "area": area}
        if not as_found:
            after["baseline"] = base
    # the record names the line in this version's words (raw_review.line_text)
    after["version"] = raw_review.EDIT_VERSION
    auto_area = plan["before"]["stored_area"] if as_found else plan["before"]["area"]
    min_change, min_sn = raw_preview.manual_limits(integration, analyte)
    problem = raw_preview.edit_problem(kind, auto_area, area, sn, min_change, min_sn)
    if problem:
        raise ValueError(problem)
    plan["after"] = after
    plan["notes"] = notes(manual, rules) + edge_notes(peak, trace, auto_base, manual, rules)
    return plan


def _within_reach(peak, trace, manual, baseline):
    """ValueError when a perpendicular drop or a tangent skim measured on
    the stored trace (`manual`, the preview) reads past the samples the
    record keeps at full resolution (raw_preview.read_reach against its
    full_res_reach): there the stored trace is thinned, and the review
    would measure what the run measures differently. A trace with no
    noise judges no neighbour, so reads nothing past its edges' own
    points; one stored before it kept the reach is measured only inside
    its full_res, else processed again."""
    if baseline not in ("drop", "skim") or peak.get("sigma") is None:
        return
    t = trace["t"]
    i0, i1 = raw_preview.read_reach(peak.get("engine") or "classic", t, trace["y"], manual["s"], manual["e"],
                                    smooth_points=peak.get("smooth_points"), edge_points=peak.get("edge_points"),
                                    m=peak.get("smoothing"))
    region = peak.get("full_res_reach") or peak["full_res"]
    if region[0] <= t[i0] and t[i1] <= region[1]:
        return
    words = raw_review.LINE_WORDS[baseline]
    if not peak.get("full_res_reach"):
        raise ValueError(REACH_BEFORE % words)
    raise ValueError(REACH_TEXT % (words, region[0], region[1]))


def notes(manual, rules):
    """What the card notes of a manual peak, never a refusal: a drop whose
    valley stands higher than the method's valley limit for a
    perpendicular drop (drop_valley_max_pct), a skim whose peak stands
    taller beside its parent than the method's tangent skim ratio
    (skim_ratio_pct). `manual` is the preview."""
    out = []
    valley, skim = manual.get("valley_share"), manual.get("skim_share")
    if valley is not None and valley > rules["drop_valley_max_pct"]:
        out.append(VALLEY_NOTE % (valley, rules["drop_valley_max_pct"]))
    if skim is not None and skim > rules["skim_ratio_pct"]:
        out.append(SKIM_NOTE % (skim, rules["skim_ratio_pct"]))
    return out


def edge_notes(peak, trace, auto_base, manual, rules):
    """What the card notes of a manual peak's edges, never a refusal: an
    edge nearer its apex than the method's edges past the tail
    (edge_sigma), in the peak's standard deviations on that side, its half
    width at half height over HALF_WIDTH_SIGMA (raw_preview.half_widths).
    The width is the automatic peak's, measured over its own edges and
    line, when the manual apex lies within it at half height (the same
    peak: an edge set short cannot narrow the width it is judged by);
    else the manual peak's own (another peak: a rider, a peak added). A
    side whose half height is not reached takes the other side's; no note
    without a width. An edge's reach is its distance from the apex."""
    engine = peak.get("engine") or "classic"
    apex = manual.get("apex")
    if apex is None:
        return []

    def widths(measured):
        try:
            return raw_preview.half_widths(engine, trace["t"], trace["y"], measured,
                                           smooth_points=peak.get("smooth_points"), m=peak.get("smoothing"))
        except (TypeError, ValueError, ZeroDivisionError):
            return [None, None]
    auto = peak.get("auto") or peak
    w = [None, None]
    if auto.get("start") is not None and auto.get("end") is not None and auto_base:
        try:
            ref = _preview(peak, trace, auto["start"], auto["end"], auto_base)
        except (TypeError, ValueError):
            ref = None
        if ref is not None:
            w = widths(ref)
            if not (w[0] is not None and w[1] is not None and ref["apex"] - w[0] <= apex <= ref["apex"] + w[1]):
                w = [None, None]
    if w == [None, None]:
        w = widths(manual)
    w0, w1 = (w[0] if w[0] is not None else w[1]), (w[1] if w[1] is not None else w[0])
    limit = rules["edge_sigma"]
    out = []
    # a distance: a shoulder found with its apex on or past its own edge
    # lies that near it, never a negative number of sigmas
    for name, reach, width in (("start", abs(apex - manual["start"]), w0), ("end", abs(manual["end"] - apex), w1)):
        if width is None or not width > 0:
            continue
        sigmas = reach / (width / raw_preview.HALF_WIDTH_SIGMA)
        if sigmas < limit:
            out.append(EDGE_NOTE % (name, raw_preview._below(sigmas, limit), limit))
    return out


def edited_reads(overrides, dropped=()):
    """{injection: [analytes]} whose traces show whether the run's edits are
    processed: every edited key's, and every undone change's (`dropped`, the
    Manual-changes records undone), each read once."""
    out = {}
    pairs = [raw_review.parse_edit_key(k)[:2] for k in sorted(overrides or {})]
    pairs += [(r.get("injection"), r.get("analyte")) for r in dropped or []]
    for injection, analyte in pairs:
        if injection and analyte and analyte not in out.setdefault(injection, []):
            out[injection].append(analyte)
    return out


def waiting(edited_at, imports, overrides, unshown=()):
    """(waiting, edits): whether the run's edits wait for it to be processed
    again, and how many traces are edited. `edited_at` is when the run's
    edits were last written (UTC, "%Y-%m-%dT%H:%M:%S"; None when it has
    none written), `imports` the import log's entries for the run's file,
    newest first, `overrides` the edits, `unshown` the traces whose stored
    peak does not show its edit or its undo (raw_review.pending over the
    edited and undone traces).

    They wait while any trace does not show its edit or undo: an edit
    written while an import was already reading the run is not in it,
    though that import completes after it. Otherwise they wait unless the
    run's latest import completed after the edits were written: an import
    that failed or is being tried again, none on record, or one completed
    before or within the same second as the edits leaves them waiting."""
    edits = len(overrides or {})
    if unshown:
        return True, edits
    if not edited_at:
        return False, edits
    latest = (imports or [None])[0]
    done = bool(latest) and latest.get("status") == "imported" and (latest.get("updated_at") or "") > edited_at
    return not done, edits


# the start of the refusal naming a failed processing, and how much of the
# worker's error it quotes
FAILED_TEXT = "The run's last processing failed:"
ERROR_CHARS = 200


def short_error(error):
    """The worker's error, its first line, cut to ERROR_CHARS."""
    line = ("%s" % (error or "")).strip().splitlines()
    line = line[0].strip() if line else ""
    return line if len(line) <= ERROR_CHARS else line[:ERROR_CHARS - 3].rstrip() + "..."


def submit_refusal(is_waiting, imports):
    """Why submit and release wait on the raw run, or None: (message key,
    detail). While its latest import failed: "raw_run_failed" with the
    error (FAILED_TEXT); else while edits wait, "raw_edits_waiting"
    (WAITING_TEXT)."""
    if not is_waiting:
        return None
    latest = (imports or [None])[0]
    if latest and latest.get("status") == "failed":
        return "raw_run_failed", short_error(latest.get("error")) or "no reason was recorded."
    return "raw_edits_waiting", None
