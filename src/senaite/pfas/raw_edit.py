# -*- coding: utf-8 -*-
"""An analyst's edit of one raw trace, posted from Data Review's Integration Review
tab, judged before anything is written.

    decide(form, traces, rows, overrides, integration, labelled=(), open_changes=())
        (refusal, None) when the edit is refused, nothing to be written;
        (None, plan) when it may be made: the trace's key parts, the edit
        to keep beside the run, and the automatic and edited peak for the
        list of manual changes
    plan_all(form, traces, rows, overrides, integration, labelled=(), first_mid=None, branched=())
        (refusal, None) or (None, plan): one trace's change applied to
        every injection ("Apply to all"), each injection judged by the hard
        limits, those that cannot take it listed with why; with
        "smoothing", the compound's smoothing changed for the run, one of
        its Low, Mid or High
    smoothing_steps_of(traces, analyte, first_mid=None)
        the compound's Low, Mid and High, which the card offers and the
        plan takes
    manual_kept(traces, overrides, analyte, transitions=None)
        the injections holding an analyst's edit of the analyte, whose
        manual peaks keep their edit under a change applied to all
    applies_text(plan)
        the card's line before "Apply to all": how many injections take it,
        which do not and why, how many manual peaks keep their edit
    method_baseline(peak, integration)
        the baseline the method measures on, and an edit naming none
    auto_baseline(peak, integration)
        the baseline the automatic peak was measured on: a processing
        change's where one made it
    edge_tolerance(t, full_res)
        how far past the full-resolution region an edge may sit
    edited_reads(overrides, dropped)
        the traces to read for whether the edits are processed
    waiting(edited_at, imports, overrides, unshown)
        whether the run's edits wait for it to be processed again
    submit_refusal(waiting, imports)
        why submit and release wait on the run: its failure, or its edits

The form's fields: injection, analyte, transition (empty for the
quantifier), kind (integrate, apex, fit, delete, revert), start and end
(integrate, fit), apex (apex), baseline (integrate or apex: valley, drop,
flat or skim, empty for the method's), level_start and level_end
(integrate: the baseline's two levels set by hand, in counts, both or
neither), shape (fit: gaussian or emg), apexes (fit: two or three times,
comma-separated), pick (fit: the index among the apexes of the component
reported), confirm (1 to delete an isotope standard's quantifier peak). A
change to one injection also posts reason_id, from the lab's active list,
and detail, the comment, both required; an undo asks for neither (Data
Review's raw edit post checks them).

`traces` are the injection's raw_traces rows for the analyte (t / y
unpacked, peak parsed), `rows` the run's result rows as the tab shows them,
`overrides` the run's edits, `integration` the method's Integration block,
`labelled` the method's labelled standards (its grid's keywords),
`open_changes` the (injection, analyte, transition) of the Manual changes
records still open (transition None for the quantifier). Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

from senaite.pfas import raw_preview, raw_review

KINDS = ("integrate", "apex", "fit", "delete", "revert")
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
NO_BASELINE_TEXT = "The method's Integration names no baseline."
# the posted levels of a re-integration's baseline, at its start and its end
LEVEL_FIELDS = ("level_start", "level_end")
# a fit of overlapping peaks, refused before writing in the words the card
# and the worker share (raw_review): an isotope standard's peak is never
# fitted, two or three apexes lie between the edges, the method sets its fit
# limit; the worker fits, and keeps a fit it cannot accept with no effect
FIT_LABELLED_TEXT = raw_review.FIT_LABELLED_TEXT
FIT_APEXES_TEXT = raw_review.FIT_APEXES_TEXT
FIT_NO_LIMIT_TEXT = raw_review.FIT_NO_LIMIT_TEXT
FIT_SHAPE_TEXT = "The shape is Gaussian or EMG."
FIT_PICK_TEXT = "Pick the fitted peak to report."
# a fit applied to all is placed from each injection's expected time, which
# its edges hold
FIT_EXPECTED_TEXT = "The fit's edges lie either side of the expected time, %.3f min."
FIT_LIMIT = "fit_noise_multiple"


def fit_accept_score(integration, portal=None):
    """The score a fit must reach to be accepted: the method's, else the
    lab's, else the default where there is no site (tests)."""
    from senaite.pfas import fit_accept
    own = fit_accept.whole((integration or {}).get("fit_accept_score"))
    if own is not None:
        return own
    return fit_accept.load(portal) if portal is not None else fit_accept.DEFAULT


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


def fit_limit(integration):
    """The method's largest fit residual, in times the trace's baseline
    noise, or None while it is unset (no fit is made): the lab's own
    setting, with no default."""
    value = (integration or {}).get(FIT_LIMIT)
    if value is None or ("%s" % value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _apexes(form, name, what):
    """The comma-separated numbers posted in `name`; ValueError naming `what`."""
    out = []
    for part in text(form, name).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError:
            raise ValueError("The %s are numbers." % what)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("The %s are numbers." % what)
        out.append(value)
    return out


def _pick(given, count):
    """The index of the fitted peak to report among `count`, from the posted
    text `given`; ValueError (FIT_PICK_TEXT) for none or another."""
    if not given.isdigit() or not int(given) < count:
        raise ValueError(FIT_PICK_TEXT)
    return int(given)


def in_time_order(apexes, pick):
    """(apexes in time order, the index of the picked one among them)."""
    chosen = apexes[pick]
    ordered = sorted(apexes)
    return ordered, ordered.index(chosen)


def parse(form):
    """(kind, edit, confirm): the posted edit with only its kind's own
    fields. ValueError says what is wrong. A fit's apexes and pick are
    judged with the trace (_fit_after), which keeps them in time order."""
    kind = text(form, "kind")
    if kind not in KINDS:
        raise ValueError("Choose re-integrate, another apex, fit, delete or undo.")
    edit = {"kind": kind}
    if kind == "fit":
        edit["start"] = _number(form, "start", "start")
        edit["end"] = _number(form, "end", "end")
        if not edit["start"] < edit["end"]:
            raise ValueError("The start is before the end.")
        if text(form, "shape") not in raw_review.FIT_SHAPES:
            raise ValueError(FIT_SHAPE_TEXT)
        edit["shape"] = text(form, "shape")
        # their count and place are judged with the trace (_fit_after)
        edit["apexes"], edit["pick"] = _apexes(form, "apexes", "apexes"), text(form, "pick")
        # one apex is a fit alone (the fits stepper's candidate); the fit tool's own clicks are two or three
        if text(form, "alone") == "1":
            edit["alone"] = True
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


def auto_baseline(peak, integration):
    """The baseline the stored automatic peak was measured on: the line of
    the processing change that made it (under an analyst's edit, the
    automatic peak beneath it), else the method's (method_baseline). An
    edit that names no line is still measured on the method's: the worker
    replays it so."""
    shown = raw_review.processing_shown(peak)[0]
    if shown and shown.get("baseline"):
        return shown["baseline"]
    return method_baseline(peak, integration)


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


def _in_full_res(peak, trace, start, end, analyte):
    """ValueError unless the edges lie in the stored trace's full-resolution
    region, within half a sample's spacing (edge_tolerance)."""
    full = peak.get("full_res")
    if not full:
        raise ValueError(STORED_BEFORE)
    tol = edge_tolerance(trace["t"], full)
    if start < full[0] - tol or end > full[1] + tol:
        raise ValueError("The edges lie in the trace's full-resolution region, %.3f to %.3f min. To go "
                         "further, widen the method's window for %s." % (full[0], full[1], analyte))


def _fit_after(edit, peak, trace, integration, analyte, label):
    """The fit as the list of manual changes keeps it before the worker has
    fitted it: {"start", "end", "shape", "apexes", "pick", "version"}, its
    edges on their nearest stored samples, its apexes in time order.
    Refused, in this order: not two or three apexes (one for a fit marked
    "alone", the fits stepper's candidate) apart between the
    edges (FIT_APEXES_TEXT), or a pick that is none of them; no fit limit
    set on the method (FIT_NO_LIMIT_TEXT); edges outside the
    full-resolution region; fewer samples than the compound's fewest
    points in a peak or than the fit is made over (raw_review.fit_fewest),
    in the worker's words. The
    fit itself, its residual, interval and the manual-change limits are
    the worker's to judge (it fits; this side cannot)."""
    apexes = edit["apexes"]
    if (len(apexes) not in ((1,) if edit.get("alone") else (2, 3)) or len(set(apexes)) != len(apexes)
            or not all(edit["start"] < a < edit["end"] for a in apexes)):
        raise ValueError(FIT_APEXES_TEXT)
    edit["apexes"], edit["pick"] = in_time_order(apexes, _pick(edit["pick"], len(apexes)))
    if fit_limit(integration) is None:
        raise ValueError(FIT_NO_LIMIT_TEXT)
    _in_full_res(peak, trace, edit["start"], edit["end"], label)
    rules, problem = review_rules(integration, analyte)
    if problem:
        raise ValueError(problem)
    full = peak["full_res"]
    edit["start"], edit["end"] = snap(trace["t"], edit["start"], full), snap(trace["t"], edit["end"], full)
    if not edit["start"] < edit["apexes"][0] or not edit["apexes"][-1] < edit["end"]:
        raise ValueError(FIT_APEXES_TEXT)
    points = _nearest(trace["t"], edit["end"]) - _nearest(trace["t"], edit["start"]) + 1
    fewest = max(int(rules["min_peak_points"]), raw_review.fit_fewest(edit["shape"], len(edit["apexes"])))
    if points < fewest:
        raise ValueError(FEWEST_POINTS_TEXT % (fewest, points))
    return dict([(k, edit[k]) for k in ("start", "end", "shape", "apexes", "pick")]
                + ([("alone", True)] if edit.get("alone") else []) + [("version", raw_review.EDIT_VERSION)])


def _measured(peak, trace, start, end, baseline, analyte, levels=None, amp=None):
    """The manual peak previewed between start and end (a drop's or a
    skim's neighbours rising `amp`, the peak search amplitude, times the
    trace's sigma); ValueError says why the edges cannot be measured."""
    engine = peak.get("engine") or "classic"
    if not peak.get("full_res"):
        raise ValueError(STORED_BEFORE)
    if engine == "adaptive" and peak.get("smoothing") is None:
        raise ValueError(NO_SMOOTHING)
    if any(peak.get(k) is None for k in PREVIEW_FIELDS.get(engine, ())):
        raise ValueError(STORED_BEFORE)
    _in_full_res(peak, trace, start, end, analyte)
    try:
        return _preview(peak, trace, start, end, baseline, levels, amp)
    except ValueError as exc:
        raise ValueError("The peak cannot be measured between these edges: %s." % (exc.args[0] if exc.args else ""))


def decide(form, traces, rows, overrides, integration, labelled=(), open_changes=(), follows=False):
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
    record's version, for the list of manual changes.

    `follows` (never a posted field) is True for a partner's
    re-integration that only follows a shared edge moved on its partner
    (decide_pair): the smallest manual change does not judge it, its
    points, reach and S/N are judged as any edit's."""
    try:
        return None, _plan(form, traces, rows, overrides, integration, labelled, open_changes, follows)
    except ValueError as exc:
        return (exc.args[0] if exc.args else ""), None


# the fields a drop line's drag adds to a re-integration: the method's partner of the analyte and
# the partner's edges, the shared edge moved
PARTNER_FIELDS = ("partner_analyte", "partner_start", "partner_end")


def partner_name(integration, analyte, partners=None):
    """The analyte's partner as the pipeline reads it: an isomer peak's from
    the Isomers tab (`partners`, isomers.partners(profile)), any other row's
    as typed on the row; None when it has none."""
    row = ((integration or {}).get("analytes") or {}).get(analyte)
    return (partners or {}).get(analyte) or (row.get("partner") if isinstance(row, dict) else None) or None


def partner_of(integration, analyte, traces, injection, partners=None):
    """{"analyte", "start", "end"}: the method's partner of the analyte and
    the edges of its quantifier's peak in this injection, which a dragged
    drop line moves together with the analyte's own; None where the method
    names no partner or the partner has no peak here."""
    name = partner_name(integration, analyte, partners)
    for t in traces or []:
        if t.get("injection") == injection and t.get("analyte") == name and t.get("role") == "quant":
            peak = t.get("peak") or {}
            if peak.get("deleted") or peak.get("start") is None or peak.get("end") is None:
                return None
            return {"analyte": name, "start": peak["start"], "end": peak["end"]}
    return None


SHARED_TEXT = u"The shared edge is moved on both peaks, in the method's partner of this compound, in a re-integration."
PARTNER_WAITING_TEXT = (u"%s has a change waiting for the run to be processed: wait for that, then move the "
                        u"shared edge again.")
PARTNER_EDGE_TEXT = u"The partner's edge is not this peak's shared edge."
# the shared edge moved onto or past the partner's other edge, on the samples the worker keeps
PARTNER_CROSS_TEXT = u"The shared edge passes the other edge of %s: move it less far."


def _partner_keeps(partner_trace, overrides, injection, partner, integration):
    """(baseline, levels) the partner's re-integration keeps: the line and the
    levels set by hand of its edit in force, else its stored peak's own line
    where that is not the method's; ValueError when its edit is still
    waiting for the run (the stored peak does not show it yet)."""
    peak = partner_trace.get("peak") or {}
    qt = partner_trace.get("transition")
    cur = raw_review.edit_for(overrides, injection, partner, None, qt)
    if cur is not None:
        if (peak.get("manual") or {}).get("at") != cur.get("at"):
            raise ValueError(PARTNER_WAITING_TEXT % partner)
        return cur.get("baseline") or u"", cur.get("levels")
    own = peak.get("baseline")
    line = method_baseline(peak, integration)
    return (own if own and own != line else u""), None


def decide_pair(form, traces, rows, overrides, integration, labelled=(), open_changes=(), partners=None,
                shared_with=None):
    """(refusal, None) or (None, [plan, ...]): decide() for the edit posted
    and, when it names a partner (partner_analyte, partner_start,
    partner_end: a drop line dragged or a shared edge typed), for the
    partner's own re-integration on those edges in the same injection: the
    partner keeps its own line and levels, only the shared edge moves. Each
    is its own edit, planned and recorded as any edit is, naming the other
    in "shared_with"; the posted reason and comment serve both. The partner
    only follows the shared edge, so the smallest manual change does not
    judge it (decide's `follows`). Refused as a whole when either is: a partner that is not the method's partner of the
    analyte, a change that is not a re-integration, partner edges that
    meet or cross (PARTNER_CROSS_TEXT), a partner edge that is
    not this peak's shared edge (within one sample), a partner edit waiting
    for the run, or the partner's own refusal (named by its label).

    An undo of a quantifier whose edge is shared (`shared_with`, the
    partner both open records name: manual_integration.shared_partner,
    never a posted field) undoes the partner's edit too, its own plan:
    the edge stays shared, or neither moved it."""
    problem, plan = decide(form, traces, rows, overrides, integration, labelled, open_changes)
    if problem:
        return problem, None
    if plan["kind"] == u"revert":
        if not shared_with or plan["transition"] is not None:
            return None, [plan]
        undo = dict((k, form.get(k)) for k in form.keys())
        undo.update(analyte=shared_with, transition=u"")
        problem, other = decide(undo, traces, rows, overrides, integration, labelled, open_changes)
        if problem:
            return u"The partner %s: %s" % (raw_review.label_of(rows, shared_with), problem), None
        plan["shared_with"], other["shared_with"] = shared_with, plan["analyte"]
        return None, [plan, other]
    partner = text(form, "partner_analyte")
    if not partner:
        return None, [plan]
    if plan["kind"] != u"integrate" or plan["transition"] is not None \
            or partner_name(integration, plan["analyte"], partners) != partner:
        return SHARED_TEXT, None
    label = raw_review.label_of(rows, partner)
    injection = plan["injection"]
    ptrace = [t for t in traces or [] if t.get("injection") == injection and t.get("analyte") == partner
              and t.get("role") == "quant"]
    if not ptrace:
        return u"The partner %s has no trace in %s." % (label, injection), None
    try:
        baseline, levels = _partner_keeps(ptrace[0], overrides, injection, partner, integration)
    except ValueError as exc:
        return exc.args[0] % label if u"%s" in exc.args[0] else exc.args[0], None
    if _crossed(ptrace[0], form):
        return PARTNER_CROSS_TEXT % label, None
    both = dict((k, form.get(k)) for k in form.keys())
    both.update(analyte=partner, transition=u"", start=form.get("partner_start"), end=form.get("partner_end"),
                baseline=baseline or u"", level_start=u"" if not levels else levels[0],
                level_end=u"" if not levels else levels[1])
    problem, other = decide(both, traces, rows, overrides, integration, labelled, open_changes, follows=True)
    if problem:
        return u"The partner %s: %s" % (label, problem), None
    # the partner's moved edge is this peak's shared edge, within one sample
    tol = 2 * edge_tolerance(ptrace[0]["t"], (ptrace[0].get("peak") or {}).get("full_res") or
                             [ptrace[0]["t"][0], ptrace[0]["t"][-1]])
    shared = (abs(other["edit"]["start"] - plan["edit"]["end"]) <= tol + 1e-9
              or abs(other["edit"]["end"] - plan["edit"]["start"]) <= tol + 1e-9)
    if not shared:
        return PARTNER_EDGE_TEXT, None
    plan["shared_with"], other["shared_with"] = partner, plan["analyte"]
    if other.get("notes"):
        plan["notes"] = list(plan.get("notes") or []) + [u"%s: %s" % (label, n) for n in other["notes"]]
    return None, [plan, other]


def _crossed(ptrace, form):
    """True when the partner's posted edges, numbers both, meet or cross,
    as given or on the samples the worker keeps them on (snap)."""
    try:
        start, end = _number(form, "partner_start", "start"), _number(form, "partner_end", "end")
    except ValueError:
        return False                       # the partner's own refusal names what is missing
    if not start < end:
        return True
    full = (ptrace.get("peak") or {}).get("full_res")
    kept = [snap(ptrace.get("t"), x, full) for x in (start, end)] if full else [None]
    if None in kept:
        return False                       # the edges' reach is judged by the partner's own plan
    return not kept[0] < kept[1]


def edit_notes(plans):
    """What the method notes of an edit made, one per line: the first
    plan's, which carry its partner's labelled (decide_pair), never the
    partner's a second time."""
    return list((plans[0].get("notes") if plans else None) or [])


def _quant_has_no_peak(traces, overrides, injection, analyte, qt):
    """True when the analyte's quantifier has no peak in this injection: its
    stored peak deleted or with no area, or a deletion of it waiting."""
    quant = [t for t in traces or [] if t.get("injection") == injection and t.get("analyte") == analyte
             and t.get("role") == "quant"][0]
    peak = quant.get("peak") or {}
    waiting = raw_review.edit_for(overrides, injection, analyte, None, qt) or {}
    return bool(peak.get("deleted") or not peak.get("area") or waiting.get("kind") == "delete")


def _plan(form, traces, rows, overrides, integration, labelled, open_changes=(), follows=False):
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
    line = method_baseline(peak, integration)
    # the automatic peak is compared, and its width read, on the line it was
    # measured on; the edit on its own line, or the method's
    auto_base = auto_baseline(peak, integration)
    if kind == "fit" and (is_standard(rows, injection, analyte, labelled)
                          or raw_review.natives_of(rows, analyte, injection)):
        # an isotope standard's peak, quantifier or qualifier, is never fitted
        raise ValueError(FIT_LABELLED_TEXT % label)
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
    if kind == "fit":
        plan["after"] = _fit_after(edit, peak, trace, integration, analyte, label)
        plan["notes"] = []
        return plan
    if line is None:
        raise ValueError(NO_BASELINE_TEXT)
    base = edit.get("baseline") or line
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
    if follows:
        # a partner only follows the shared edge: how far its area moves is
        # its partner's edit, judged there
        min_change = None
    problem = raw_preview.edit_problem(kind, auto_area, area, sn, min_change, min_sn)
    if problem:
        raise ValueError(problem)
    plan["after"] = after
    plan["notes"] = notes(manual, rules) + edge_notes(peak, trace, auto_base, manual, rules)
    return plan


# ── "Apply to all": one trace's change made the compound's processing ─────
# the kinds a change applied to every injection may be: a fit is the one
# major processing change (countersigned at release)
ALL_KINDS = ("integrate", "fit")
SINGLE_TEXT = "Apply to all is for a single peak: %s is %s."
LEVELS_ALL_TEXT = "Levels set by hand apply to this injection only."
ONE_INJECTION_TEXT = "Choosing an apex or deleting applies to this injection only."
KIND_ALL_TEXT = "Choose re-integrate or fit to apply to all."
OFFSETS_TEXT = "The start lies before the apex and the end after it."
IS_ALL_TEXT = "%s is an isotope standard: applying to all changes %s. Confirm to apply."
IS_ALL_NATIVES = "the analytes it quantifies"
NONE_TAKES_TEXT = "No injection can take this change: %s."
APPLIES_TEXT = "Applies to %d of %d"
MANUAL_KEPT_TEXT = " %d manual peaks keep their edit."
MANUAL_KEPT_ONE = " 1 manual peak keeps its edit."
# a smoothing change is the compound's window in points, every trace of it
# in every injection: no edges, line or apexes, and an odd number of 5 or
# more (raw_review.processing_of)
SMOOTHING_POINTS_TEXT = "Smoothing is an odd number of points, 5 or more."
SMOOTHING_EDGES_TEXT = "A smoothing change sets no edges, line or apexes."
# the stepper offers Low, Mid and High only: any other window is refused
SMOOTHING_STEP_TEXT = "The smoothing of %s is Low, Mid or High: %s points."
SMOOTHING_NO_STEP_TEXT = "The stored peaks of %s name no smoothing, so no step is offered: process the run again."
SMOOTHING_FIELDS = ("start_offset", "end_offset", "start", "end", "apex", "apexes", "baseline", "shape", "pick",
                    "alone") + LEVEL_FIELDS


def manual_kept(traces, overrides, analyte, transitions=None):
    """[injection] holding an analyst's edit of the analyte, in the order of
    `traces`: of any of its traces, or of those `transitions` name (None
    for the quantifier). Those manual peaks keep their edit under a change
    applied to all."""
    quant = dict((t["injection"], t["transition"]) for t in traces or []
                 if t.get("analyte") == analyte and t.get("role") == "quant")
    out = []
    for t in traces or []:
        if t.get("analyte") != analyte or t["injection"] in out:
            continue
        transition = None if t.get("role") == "quant" else t.get("transition")
        if transitions is not None and transition not in transitions:
            continue
        qt = quant.get(t["injection"])
        if raw_review.edit_for(overrides, t["injection"], analyte, transition, qt) is not None:
            out.append(t["injection"])
    return out


def smoothing_mid(traces):
    """The window in points the stored quantifier peaks were smoothed over,
    the analyte's Mid: Adaptive's half-width m as 2m + 1, Classic's points
    as they are; the most of the injections where they differ (a width
    learnt per injection), None where no peak says."""
    counts = {}
    for t in traces or []:
        if t.get("role") != "quant":
            continue
        peak = t.get("peak") or {}
        auto = peak.get("auto") or {}
        m = peak.get("smoothing", auto.get("smoothing"))
        n = peak.get("smooth_points", auto.get("smooth_points"))
        engine = peak.get("engine") or auto.get("engine")
        try:
            points = 2 * int(m) + 1 if engine == "adaptive" and m is not None else int(n) if n else None
        except (TypeError, ValueError):
            points = None
        if points:
            counts[points] = counts.get(points, 0) + 1
    if not counts:
        return None
    return sorted(counts, key=lambda p: (-counts[p], p))[0]


def smoothing_card(traces, overrides, analyte, first_mid=None, in_force=None):
    """The card's smoothing fields: {"smoothing_steps" (peak_limits.
    smoothing_steps of Mid's half-width m: low, mid and high, None where the
    step is not allowed), "smoothing_in_force_points" (the window of the
    change in force, which the stepper opens on; None with none) and "manual_kept" (how
    many injections hold a hand-integrated peak of the compound, which a
    smoothing change leaves as they are)}. Mid is the window of the
    compound's first smoothing change (`first_mid`, in points) where there
    is one: its stored peaks are smoothed over the changed window already, so
    their own smoothing is no longer Mid. Otherwise it is the window the
    stored peaks were smoothed over, run-wide as the plan records it
    (smoothing_mid of the quantifiers among `traces`, the compound's traces
    in every injection). `in_force` is the points of the change in force,
    or None."""
    return {"smoothing_steps": smoothing_steps_of(traces, analyte, first_mid),
            "smoothing_in_force_points": in_force,
            "manual_kept": len(manual_kept(traces, overrides, analyte))}


def smoothing_steps_of(traces, analyte, first_mid=None):
    """peak_limits.smoothing_steps of the compound's Mid: its first
    smoothing change's (`first_mid`, in points) where there is one, else
    the window its stored quantifier peaks were smoothed over
    (smoothing_mid). The one choice the card's stepper and the plan make."""
    from senaite.pfas import peak_limits
    quants = [t for t in traces or [] if t.get("analyte") == analyte and t.get("role") == "quant"]
    mid = first_mid or smoothing_mid(quants)
    m = (int(mid) - 1) // 2 if mid else None
    return peak_limits.smoothing_steps(m)


def smoothing_windows(steps):
    """The windows, in points (2m + 1), of the steps offered, in order."""
    return sorted(2 * s + 1 for s in (steps or {}).values() if s is not None)


def _or_list(numbers):
    """"7, 9 or 17"."""
    words = ["%d" % n for n in numbers]
    return words[0] if len(words) == 1 else "%s or %s" % (", ".join(words[:-1]), words[-1])


def plan_all(form, traces, rows, overrides, integration, labelled=(), first_mid=None, branched=()):
    """(refusal, None) or (None, plan): the posted change (analyte,
    transition, kind; a re-integration's baseline, start_offset and
    end_offset from each injection's own apex; a fit's shape, and the
    injection, start, end and apexes, two or three comma-separated, as
    clicked on that injection's trace, kept as offsets from its expected
    time (_fit_record_all); confirm) applied to that trace in every
    injection. `traces` are the analyte's raw_traces rows of every
    injection, the rest as decide takes them.

    plan: {"analyte", "transition" (None for the quantifier),
    "quant_transition", "kind", "record" (the processing record to keep,
    raw_review.processing_of), "applies" [injection], "skipped"
    [[injection, why]], "manual_kept" [injection], "natives" (an isotope
    standard's), "major"}. A manual peak keeps its edit: its automatic
    peak takes the change beneath it, so it is among "applies" and named
    in "manual_kept".

    Refused, in this order: an analyte or trace the run does not hold; a
    pair or summed compound; another apex or a deletion; levels set by
    hand (counts in one injection); for a fit, what _fit_record_all
    refuses (an isotope standard first, its peak never fitted, so no
    confirm is asked); for a re-integration, offsets that are no numbers or
    do not hold the apex, a line not known; an isotope standard's
    quantifier not confirmed, naming the natives it quantifies; no
    injection that can take it. A fit is a major change ("major"). The
    manual-change limits never judge it: it is processing, not an
    analyst's edit. Each injection is judged by
    the hard limits as the worker judges it (raw_review's SKIP_* words):
    no apex detected (a fit: no expected time), or a qualifier beside no
    quantifier peak; an edge
    more than half a sample past the trace; fewer samples between the
    edges than the compound's fewest points or the engine measures; a drop
    or a skim reading past the stored full-resolution reach. The worker's
    own skip on the stored trace (processing_skipped) is the record.

    With "smoothing" posted (a window in points) the plan is the
    compound's smoothing change instead (_plan_smoothing; `first_mid` the
    Mid of the compound's first smoothing change on record, in points, or
    None). `branched` are the profile's branched isomer peaks, summed
    (peak_mode)."""
    try:
        if text(form, "smoothing"):
            return None, _plan_smoothing(form, traces, rows, overrides, integration, labelled, first_mid, branched)
        return None, _plan_all(form, traces, rows, overrides, integration, labelled, branched)
    except ValueError as exc:
        return (exc.args[0] if exc.args else ""), None


def _nearest(t, x):
    """The index of the sample nearest x, the first of two equally near (as
    the worker places an edge)."""
    best = 0
    for i, v in enumerate(t):
        if abs(v - x) < abs(t[best] - x):
            best = i
    return best


def _skip(trace, record, rules, no_quant_peak):
    """Why one injection's trace cannot take the change, or None. A fit is
    placed from the trace's expected time, any other change from its
    automatic apex."""
    peak = trace.get("peak") or {}
    auto = peak.get("auto") or peak
    if no_quant_peak:
        return raw_review.SKIP_NO_APEX
    if record["kind"] == "fit":
        anchor = peak.get("expected_rt")
        if anchor is None:
            return raw_review.SKIP_NO_TIME
    elif auto.get("apex") is None:
        return raw_review.SKIP_NO_APEX
    else:
        anchor = auto["apex"]
    t, y = trace["t"], trace["y"]
    start, end = anchor + record["start_offset"], anchor + record["end_offset"]
    if len(t) < 2 or start < t[0] - (t[1] - t[0]) / 2.0 or end > t[-1] + (t[-1] - t[-2]) / 2.0:
        return raw_review.SKIP_OUTSIDE
    s, e = _nearest(t, start), _nearest(t, end)
    engine = peak.get("engine") or "classic"
    fewest = raw_review.ENGINE_FEWEST
    fewest = fewest.get(engine, fewest["classic"])
    if record["kind"] == "fit":
        fewest = max(fewest, raw_review.fit_fewest(record["shape"], len(record["apex_offsets"])))
    if e - s + 1 < max(int(rules["min_peak_points"]), fewest):
        return raw_review.SKIP_FEW_POINTS
    region = peak.get("full_res_reach")
    if record.get("baseline") in ("drop", "skim") and peak.get("sigma") is not None and region:
        try:
            i0, i1 = raw_preview.read_reach(engine, t, y, s, e, smooth_points=peak.get("smooth_points"),
                                            edge_points=peak.get("edge_points"), m=peak.get("smoothing"))
        except (TypeError, ValueError):
            return None                    # not judged here: the worker judges it on the whole trace
        if t[i0] < region[0] or t[i1] > region[1]:
            return raw_review.SKIP_REACH
    return None


def peak_mode(integration, analyte, branched=()):
    """The method's mode for an analyte (single, pair or summed), as the
    worker reads it: a branched isomer peak (`branched`, isomers.
    branched_peaks of the profile) is summed whatever its row says; else
    the row's mode, "single" when the method names none."""
    if analyte in (branched or ()):
        return "summed"
    row = ((integration or {}).get("analytes") or {}).get(analyte)
    return (row.get("mode") if isinstance(row, dict) else None) or "single"


def all_traces(traces, analyte, transition):
    """(quants, mine, transition): the analyte's quantifier rows, the rows
    "Apply to all" changes (the quantifier's, or the qualifier's of the
    posted transition) and that transition (None for the quantifier). The
    one choice the preview, the apply and the card's count all make."""
    quants = [t for t in traces or [] if t.get("analyte") == analyte and t.get("role") == "quant"]
    qt = quants[0]["transition"] if quants else None
    if not transition or transition == qt:
        return quants, quants, None
    return quants, [t for t in traces if t.get("analyte") == analyte and t.get("role") == "qual"
                    and t.get("transition") == transition], transition


def apply_all_count(traces, analyte, transition):
    """How many injections hold the trace "Apply to all" would change."""
    return len(set(t["injection"] for t in all_traces(traces, analyte, transition)[1]))


def _skip_list(skipped):
    return ", ".join("%s %s" % (inj, why) for inj, why in skipped)


def _plan_all(form, traces, rows, overrides, integration, labelled, branched=()):
    analyte = text(form, "analyte")
    if not analyte:
        raise ValueError("Name the analyte.")
    label = raw_review.label_of(rows, analyte)
    quants, mine, transition = all_traces(traces, analyte, text(form, "transition"))
    if not quants:
        raise ValueError("%s is not in this worksheet's raw run." % label)
    qt = quants[0]["transition"]
    if not mine:
        raise ValueError("%s has no qualifier %s." % (label, transition))
    mode = peak_mode(integration, analyte, branched)
    if mode != "single":
        raise ValueError(SINGLE_TEXT % (label, mode))
    kind = text(form, "kind")
    if kind in ("apex", "delete"):
        raise ValueError(ONE_INJECTION_TEXT)
    if any(text(form, name) for name in LEVEL_FIELDS):
        raise ValueError(LEVELS_ALL_TEXT)
    if kind not in ALL_KINDS:
        raise ValueError(KIND_ALL_TEXT)
    injections = []
    for t in mine:
        if t["injection"] not in injections:
            injections.append(t["injection"])
    if kind == "fit":
        record = _fit_record_all(form, mine, rows, analyte, label, injections, labelled, integration)
    else:
        start, end = _number(form, "start_offset", "start"), _number(form, "end_offset", "end")
        if not start < 0 < end:
            raise ValueError(OFFSETS_TEXT)
        # the method's line read off an injection with a peak: a peakless one
        # names no engine
        found = [t for t in quants
                 if ((t.get("peak") or {}).get("auto") or t.get("peak") or {}).get("apex") is not None]
        baseline = text(form, "baseline") or method_baseline((found or quants)[0].get("peak"), integration)
        if not baseline:
            raise ValueError(NO_BASELINE_TEXT)
        if baseline not in raw_preview.BASELINES:
            raise ValueError(BASELINE_TEXT)
        record = raw_review.processing_of({"kind": kind, "baseline": baseline, "start_offset": start,
                                           "end_offset": end})
    natives = []
    if transition is None:
        natives = _confirmed_standard(form, rows, analyte, label, injections, labelled)
    try:
        rules = raw_preview.review_limits(integration, analyte)
    except (TypeError, ValueError) as exc:
        raise ValueError(RULES_TEXT % (exc.args[0] if exc.args else ""))
    applies, skipped = [], []
    kept = manual_kept(mine, overrides, analyte, [transition])
    for t in mine:
        inj = t["injection"]
        no_quant = transition is not None and _quant_has_no_peak(traces, overrides, inj, analyte, qt)
        why = _skip(t, record, rules, no_quant)
        if why:
            skipped.append([inj, why])
        else:
            applies.append(inj)
    if not applies:
        raise ValueError(NONE_TAKES_TEXT % _skip_list(skipped))
    from senaite.pfas import manual_integration as mi
    return {"analyte": analyte, "transition": transition, "quant_transition": qt, "kind": kind,
            "record": record, "applies": applies, "skipped": skipped, "manual_kept": kept,
            "natives": natives, "major": kind in mi.PROCESSING_MAJOR_KINDS}


def _confirmed_standard(form, rows, analyte, label, injections, labelled):
    """The natives an isotope standard quantifies; ValueError while a change
    of its quantifier applied to all is not confirmed."""
    natives = sorted(set(n for inj in injections for n in raw_review.natives_of(rows, analyte, inj)))
    standard = natives or any(is_standard(rows, inj, analyte, labelled) for inj in injections)
    if standard and text(form, "confirm") not in ("1", "true", "on"):
        raise ValueError(IS_ALL_TEXT % (label, ", ".join(natives) or IS_ALL_NATIVES))
    return natives


def _plan_smoothing(form, traces, rows, overrides, integration, labelled, first_mid=None, branched=()):
    """A smoothing change for the compound (the form's analyte and
    smoothing, its window in points): every trace of it in every injection,
    none skipped, as no edges are placed. Refused, in this order: an
    analyte the run does not hold; a pair or summed compound (its peak is
    split or summed with its partner's); edges, a line or apexes posted
    with it; a window that is not an odd number of 5 or more; a window
    that is not one of the compound's Low, Mid or High (smoothing_steps_of,
    the card's stepper: Mid the first change's, `first_mid`, else the
    stored peaks'), or none offered; an isotope standard not confirmed. A major change; the manual peaks of the
    compound keep their edges ("manual_kept"); "mid" the window its stored
    peaks were smoothed over (smoothing_mid)."""
    analyte = text(form, "analyte")
    if not analyte:
        raise ValueError("Name the analyte.")
    label = raw_review.label_of(rows, analyte)
    quants = all_traces(traces, analyte, None)[0]
    if not quants:
        raise ValueError("%s is not in this worksheet's raw run." % label)
    mode = peak_mode(integration, analyte, branched)
    if mode != "single":
        raise ValueError(SINGLE_TEXT % (label, mode))
    if text(form, "kind") not in ("", raw_review.SMOOTHING_KIND) or any(text(form, n) for n in SMOOTHING_FIELDS):
        raise ValueError(SMOOTHING_EDGES_TEXT)
    posted = text(form, "smoothing")
    try:
        record = raw_review.processing_of({"kind": raw_review.SMOOTHING_KIND,
                                           "points": int(posted) if posted.isdigit() else posted})
    except ValueError:
        raise ValueError(SMOOTHING_POINTS_TEXT)
    offered = smoothing_windows(smoothing_steps_of(quants, analyte, first_mid))
    if not offered:
        raise ValueError(SMOOTHING_NO_STEP_TEXT % label)
    if record["points"] not in offered:
        raise ValueError(SMOOTHING_STEP_TEXT % (label, _or_list(offered)))
    injections = []
    for t in quants:
        if t["injection"] not in injections:
            injections.append(t["injection"])
    natives = _confirmed_standard(form, rows, analyte, label, injections, labelled)
    from senaite.pfas import manual_integration as mi
    return {"analyte": analyte, "transition": None, "quant_transition": quants[0]["transition"],
            "kind": raw_review.SMOOTHING_KIND, "record": record, "applies": injections, "skipped": [],
            "manual_kept": manual_kept(traces, overrides, analyte), "natives": natives,
            "major": raw_review.SMOOTHING_KIND in mi.PROCESSING_MAJOR_KINDS, "mid": smoothing_mid(quants)}


def _fit_record_all(form, mine, rows, analyte, label, injections, labelled, integration):
    """The processing record of a fit applied to all (raw_review.processing_of)
    from the fit as clicked on one injection's trace (the form's injection,
    start, end and apexes, in its times): every time kept as an offset from
    that trace's expected time ("expected_rt", the time its peak is searched
    about), so each injection is fitted about its own expected time and
    reports the component nearest it; the offsets in time order. Refused
    on an isotope standard in any injection, before any confirm
    (FIT_LABELLED_TEXT); then for a shape not known, a trace the run does
    not hold, edges that are no numbers or out of order, not two or three
    apexes apart between the edges (FIT_APEXES_TEXT), an unset fit limit
    (FIT_NO_LIMIT_TEXT), a trace stored without its expected time, and
    edges that do not hold it (FIT_EXPECTED_TEXT)."""
    if any(is_standard(rows, inj, analyte, labelled) or raw_review.natives_of(rows, analyte, inj)
           for inj in injections):
        raise ValueError(FIT_LABELLED_TEXT % label)
    if text(form, "shape") not in raw_review.FIT_SHAPES:
        raise ValueError(FIT_SHAPE_TEXT)
    injection = text(form, "injection")
    clicked = [t for t in mine if t["injection"] == injection]
    if not clicked:
        raise ValueError("%s / %s is not in this worksheet's raw run." % (injection, label))
    start, end = _number(form, "start", "start"), _number(form, "end", "end")
    if not start < end:
        raise ValueError("The start is before the end.")
    apexes = _apexes(form, "apexes", "apexes")
    alone = text(form, "alone") == "1"
    if len(apexes) not in ((1,) if alone else (2, 3)) or len(set(apexes)) != len(apexes) or not all(start < a < end for a in apexes):
        raise ValueError(FIT_APEXES_TEXT)
    if fit_limit(integration) is None:
        raise ValueError(FIT_NO_LIMIT_TEXT)
    expected = (clicked[0].get("peak") or {}).get("expected_rt")
    if expected is None:
        raise ValueError(STORED_BEFORE)
    if not start < expected < end:
        raise ValueError(FIT_EXPECTED_TEXT % expected)
    offsets = [round(a - expected, 6) for a in sorted(apexes)]
    # the component reported in every injection: the click nearest the expected time
    record = {"kind": "fit", "shape": text(form, "shape"), "apex_offsets": offsets,
              "pick": raw_review.expected_pick(offsets),
              "start_offset": round(start - expected, 6), "end_offset": round(end - expected, 6)}
    if alone:
        record["alone"] = True
    return raw_review.processing_of(record)


def applies_text(plan):
    """"Applies to 15 of 17: DW-0960 has no peak, CAL-1 too few points",
    then " 2 manual peaks keep their edit." where manual peaks are kept."""
    out = APPLIES_TEXT % (len(plan["applies"]), len(plan["applies"]) + len(plan["skipped"]))
    if plan["skipped"]:
        out += ": " + _skip_list(plan["skipped"])
    kept = len(plan.get("manual_kept") or ())
    if kept:
        out += "." + (MANUAL_KEPT_ONE if kept == 1 else MANUAL_KEPT_TEXT % kept)
    return out


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


class RawNotJudged(ValueError):
    """What the run applied cannot be judged from its stored peaks; the
    message is the whole sentence the person reads."""


PROCESSING_TEXT = "The run is still being processed; submit it when processing has finished."
AWAITING_TEXT = "The run's instrument data have not arrived yet"


def unprocessed_text(imports, arrived=True):
    """Why a raw run with no stored peak waits, from its import log
    (`imports`, newest first; None when the log cannot be read) and whether
    its .rawrun has arrived (`arrived`: the pull handed the instrument data
    over): nothing on record yet, AWAITING_TEXT before the data arrive and
    PROCESSING_TEXT after; being tried again, PROCESSING_TEXT; failed or
    refused, FAILED_TEXT and the error, as submit_refusal names a failed
    run; None when it imported, or the log is unread (no peak is stored,
    plainly)."""
    if imports is None:
        return None
    latest = (imports or [None])[0]
    if not latest and not arrived:
        return AWAITING_TEXT
    if not latest or latest.get("status") == "retrying":
        return PROCESSING_TEXT
    if latest.get("status") in ("failed", "refused"):
        return "%s %s" % (FAILED_TEXT, short_error(latest.get("error")) or "no reason was recorded.")
    return None


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
