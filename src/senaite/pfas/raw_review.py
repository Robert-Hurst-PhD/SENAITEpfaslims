# -*- coding: utf-8 -*-
"""What Data Review's Raw Data tab shows for a run imported from raw data.

    injections(result_rows)                        the run's injections, in order
    analytes(result_rows)                          the run's analytes, in order
    injection_view(name, traces, result_rows, lots) one injection: each analyte's
        quantifier and qualifier traces with their peaks, its isotope standard
        beside it, its values and flags, the peak's measures (engine, width,
        tailing, plates, smoothing, the file's transition, its note, a refused
        fit), and the calibration lots it was quantified against
    run_files(manifest)                            the raw files, their checksums
        and the conversion, for the Instrument Report, and the injections
        acquired out of sequence order
    edit_of / set_edit / clear_edit   the analyst's edits of one trace (re-integrate,
        another apex, delete) and their undo, keyed injection|analyte|transition;
        a record of this version (EDIT_VERSION) names one of the four
        baselines and may set the levels by hand; an older record's "drop"
        is the flat line (stored_baseline reads a stored peak the same way)
    edit_state / pending / no_effect   what the last processing made of each
        edit: shown, waiting for the run, or kept with no effect and why
    line_text / change_text   a manual peak's line and an edit in the panel's
        words, for the Manual changes list and the worker's row alike
    levels_outside(y, levels)   why levels set by hand lie off the trace
    read_overrides / write_overrides   the edits, kept beside the run
        (<stem>.overrides.json) and replayed whenever the run is processed

`traces` are raw_traces rows with t / y unpacked and peak parsed, keyed by
the analyte's keyword; `result_rows` are the run's injection_results, named
by the compound library's display name, keyed (keyed_rows, with
library_keyword_of) before they are paired with traces or edits. Pure;
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import os


def library_keyword_of(export):
    """The resolver a run's rows are paired with its traces by: a row's
    analyte name (the compound library's display name the worker names a
    row by) to the keyword its traces and edits are keyed by. An isomer
    peak (lr-, br-) keeps its own name, as the worker names both its row
    and its trace by it; a name the library does not know is itself."""
    from senaite.pfas import compound_library as cl, isomers
    n2k = cl.name_to_keyword(export)

    def keyword_of(name):
        if not name or isomers.is_peak_name(name):
            return name
        return cl.keyword_of(export, name, n2k) or name
    return keyword_of


def library_label(export):
    """The name a keyword is shown under, as the worker names its row: the
    compound library's display name; an isomer peak (lr-, br-) and a
    keyword the library does not know are themselves."""
    from senaite.pfas import compound_library as cl, isomers

    def label(keyword):
        if not keyword or isomers.is_peak_name(keyword):
            return keyword
        return cl.canonical_name(export, keyword)
    return label


def keyed_rows(result_rows, keyword_of):
    """The run's rows with each analyte the keyword `keyword_of` resolves
    its name to, so rows pair with traces and edit keys; the name as the
    row carried it is kept as "label", which every display reads. A row
    already keyed keeps its label."""
    out = []
    for r in result_rows or []:
        name = r.get("analyte")
        out.append(dict(r, analyte=keyword_of(name) if name else name, label=r.get("label") or name))
    return out


def label_of(rows, analyte):
    """The display name of the analyte (a keyword) on the run's rows: the
    first row's label; the keyword itself when no row labels it."""
    for r in rows or []:
        if r.get("analyte") == analyte and r.get("label"):
            return r["label"]
    return analyte


def injections(result_rows):
    out, seen = [], {}
    for r in result_rows or []:
        name = r.get("injection_name")
        if name not in seen:
            seen[name] = {"name": name, "type": r.get("qc_type") or u"", "flagged": 0}
            out.append(seen[name])
        if r.get("passed") == 0:
            seen[name]["flagged"] += 1
    return out


def analytes(result_rows):
    """The run's analytes in the order of its rows, each with how many of
    its rows failed: the overview's list by compound. "name" is the
    analyte (its keyword, on keyed rows), "label" what the list shows."""
    out, seen = [], {}
    for r in result_rows or []:
        name = r.get("analyte")
        if name not in seen:
            seen[name] = {"name": name, "label": r.get("label") or name, "flagged": 0}
            out.append(seen[name])
        if r.get("passed") == 0:
            seen[name]["flagged"] += 1
    return out


def _trace(t):
    return {"analyte": t["analyte"], "transition": t["transition"], "t": t["t"], "y": t["y"],
            "peak": t["peak"]}


def _state(r):
    if r.get("conc_qualifier") == u"N.D." or r.get("response") is None:
        return u"nd"
    if r.get("passed") == 0:
        return u"fail"
    return u"warn" if r.get("flag") else u""


# the peak record's measures the card shows when the peak has them
PEAK_MEASURES = ("fwhm_s", "tailing", "plates", "smoothing_from", "file_transition", "fit_note")
ENGINES = {u"adaptive": u"Adaptive", u"classic": u"Classic"}
# the worker's own wording on a peak record
FIT_REFUSED = u"trapezoid, fit refused"
PAIR_FIT_FAILED = u"pair fit failed"
OVERFLOW_NOTE = u"overflow at the apex: the stored value is above the file's number range"
# the worker's other wording, still read on stored peaks
OVERFLOW_NOTES = (OVERFLOW_NOTE, u"saturated: the stored signal tops out at the apex")
# the stored qualifier token of an overflowed trace, and what the analyst reads
QUALIFIER_TEXT = {u"Saturated": u"Overflow"}


def qualifier_text(token):
    """A stored result qualifier as the analyst reads it."""
    return QUALIFIER_TEXT.get(token, token)


def _note(peak):
    """The peak's note without the saturation part, which the card says on its own."""
    parts = [p.strip() for p in (peak.get("note") or u"").split(u";")]
    return u"; ".join(p for p in parts if p and p not in OVERFLOW_NOTES)


def _fit_text(peak):
    """What the card says of the peak's fit: "Fit refused: <why>" when the
    area fell back to the trapezoid; "Pair fit failed" when only the pair fit
    failed and the area kept its own fit; "" when the fit stands."""
    note = peak.get("fit_note") or u""
    if FIT_REFUSED in (peak.get("area_method") or u""):
        return u"Fit refused: " + (note or u"the trapezoid is used")
    if note.startswith(PAIR_FIT_FAILED):
        rest = note[len(PAIR_FIT_FAILED):].lstrip(u"; ")
        return u"Pair fit failed" + (u": " + rest if rest else u"")
    return u"Fit refused: " + note if note else u""


def _measures(peak, row):
    out = dict((k, peak.get(k)) for k in PEAK_MEASURES)
    out["engine"] = ENGINES.get(peak.get("engine") or u"classic", peak.get("engine"))
    # the record's smoothing is the half-width m; the filter runs over 2m + 1 points
    m = peak.get("smoothing")
    out["smoothing_points"] = 2 * int(m) + 1 if m is not None else None
    out["qual_sn"] = row.get("qual_sn")
    out["note"] = _note(peak)
    out["fit_text"] = _fit_text(peak)
    out["fit_flag"] = bool(out["fit_text"])
    return out


# a deleted quantifier peak, as a card or thumbnail says it
PEAK_DELETED_TEXT = u"Peak deleted"
# the states a card or thumbnail carries, and what each says
STATE_TEXT = {u"": u"", u"nd": u"Not detected", u"fail": u"Failed", u"warn": u"Check",
              u"missing": u"No trace"}
# the reasons a calibrator is dropped from its curve by a deleted peak (the
# worker's wording; the add-on cannot import the worker package)
PEAK_DELETED = u"peak deleted"
IS_PEAK_DELETED = u"isotope standard peak deleted"
MANUAL_DROP_REASONS = (PEAK_DELETED, IS_PEAK_DELETED)
# the stored peak's fields a trace carries to the client when present: the
# preview of a manual peak reads the engine and its smoothing as stored, and
# full_res_reach says where the stored trace is at full resolution
TRACE_FIELDS = ("candidates", "full_res", "full_res_reach", "sigma", "edge_points", "smoothing", "smooth_points",
                "engine", "baseline", "deleted")
EDGE_TOLERANCE = 0.01


def state_text(state, deleted=False):
    """What the card or thumbnail says of its state; a deleted peak says so."""
    return PEAK_DELETED_TEXT if deleted else STATE_TEXT.get(state, u"")


def _near(a, b, tol=EDGE_TOLERANCE):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


# why a qualifier's edit was not replayed: a qualifier is read only beside a
# quantifier peak, the worker's wording on the stored trace (manual.unapplied)
NO_QUANT_PEAK = u"the quantifier has no peak in %s"


def no_quant_peak(injection):
    """Why a qualifier edit in this injection has no effect."""
    return NO_QUANT_PEAK % injection


# why a re-integration is kept with no effect, the trace staying automatic:
# the worker's wording on the stored trace (manual.unapplied), the words of
# the review's own refusals
TOO_FEW_POINTS = u"a manual peak needs at least %d points between its edges: %d here"
LEVELS_OUTSIDE = u"the baseline levels %s and %s lie outside the trace's range, %s to %s counts"
NOT_MEASURED = u"the peak cannot be measured between %.2f and %.2f min: %s"
# an apex choice whose candidate the trace no longer offers, as when a
# raised candidate floor leaves it out
NO_LONGER_A_PEAK = u"the chosen apex is no longer a peak in its window"


def counts(value):
    """A count as the panel writes it: "4,000"."""
    return u"{0:,.0f}".format(value)


def levels_outside(y, levels):
    """Why baseline levels set by hand are refused on a trace whose counts
    are `y`, or None: each level lies between the trace's lowest and
    highest count. A stored trace holds some of the whole trace's counts,
    so levels within the stored trace's range are within the whole
    trace's."""
    if levels is None or not len(y):
        return None
    lo, hi = float(min(y)), float(max(y))
    if all(lo <= float(v) <= hi for v in levels):
        return None
    return LEVELS_OUTSIDE % (counts(levels[0]), counts(levels[1]), counts(lo), counts(hi))


# a manual peak's line and an edit, in the panel's words: the Manual
# changes list and the worker's row (manual_changes) say them the same way
LINE_WORDS = {u"valley": u"valley to valley", u"drop": u"perpendicular drop", u"flat": u"flat baseline",
              u"skim": u"tangent skim"}
EDIT_WORDS = {u"integrate": u"re-integrated", u"apex": u"apex chosen", u"delete": u"peak deleted"}


def line_text(baseline, levels=None):
    """The line a manual peak is measured above: "perpendicular drop",
    "tangent skim"; with levels set by hand "valley to valley, baseline
    4,000 and 4,500", or flat at the lower of them, "flat baseline at
    4,000"; "" with neither. `baseline` is one of BASELINES as an edit of
    this version names it (edit_of)."""
    words = LINE_WORDS.get(baseline, baseline or u"")
    if levels is None:
        return words
    if baseline == u"flat":
        return u"flat baseline at %s" % counts(min(levels))
    return (words + u", " if words else u"") + u"baseline %s and %s" % (counts(levels[0]), counts(levels[1]))


def change_text(edit):
    """An edit in the panel's words: "re-integrated, perpendicular drop,
    11.16 to 11.34 min", "re-integrated, flat baseline at 4,000, 11.16 to
    11.34 min", "apex chosen at 4.34 min", "apex chosen at 4.34 min, flat
    baseline", "peak deleted". `edit` holds its "kind" and the kind's
    fields: "start" and "end" (integrate), "apex" (apex), "baseline" and
    "levels" where it has them."""
    kind = edit.get("kind")
    parts = [EDIT_WORDS.get(kind, kind or u"")]
    if kind == u"delete":
        return parts[0]
    if kind == u"apex" and edit.get("apex") is not None:
        parts[0] += u" at %.2f min" % edit["apex"]
    line = line_text(edit.get("baseline"), edit.get("levels"))
    if line:
        parts.append(line)
    if kind == u"integrate" and edit.get("start") is not None and edit.get("end") is not None:
        parts.append(u"%.2f to %.2f min" % (edit["start"], edit["end"]))
    return u", ".join(parts)


def _stored_state(peak):
    manual = (peak or {}).get("manual")
    if not manual:
        return u"auto"
    if manual.get("unapplied"):
        return u"no_effect"
    return u"deleted" if (peak.get("deleted") or manual.get("kind") == u"delete") else u"edited"


def stored_baseline(peak):
    """The baseline a stored peak was measured on, as an edit of this
    version names it: its edit's own where the stored edit names one, else
    the trace's (the method's). A peak stored from an edit without a
    version, or before any edit had one, names the flat line "drop"."""
    peak = peak or {}
    manual = peak.get("manual") or {}
    named = manual.get("baseline") or peak.get("baseline")
    if named and not manual.get("version"):
        return LEGACY_BASELINES.get(named, named)
    return named


def edit_state(peak, override=None):
    """One of "auto", "edited", "deleted", "no_effect", "pending" for one
    trace. The stored peak shows what the last processing made of the edit;
    an override that the stored peak does not yet show (another kind, edges,
    apex, baseline or time), or an override removed while the peak still
    shows one, is "pending": the run has not been processed again since. An
    edit the last processing kept but could not apply (manual.unapplied) is
    "no_effect": processing again changes nothing."""
    peak = peak or {}
    manual = peak.get("manual")
    if override is None:
        return u"pending" if manual else u"auto"
    try:
        edit = edit_of(override)
    except ValueError:
        return u"pending"
    if not manual or manual.get("kind") != edit["kind"]:
        return u"pending"
    if edit.get("at") and manual.get("at") != edit["at"]:
        return u"pending"
    if manual.get("unapplied"):
        return u"no_effect"
    if edit["kind"] == u"integrate":
        if not (_near(peak.get("start"), edit["start"]) and _near(peak.get("end"), edit["end"])):
            return u"pending"
    elif edit["kind"] == u"apex":
        if not _near(manual.get("apex"), edit["apex"], 1e-9):
            return u"pending"
    # the stored peak always carries a baseline (the method's); only an
    # edit that names one is compared with it, and levels with its own
    if edit.get("baseline") and edit["baseline"] != stored_baseline(peak):
        return u"pending"
    if edit.get("levels") != manual.get("levels"):
        return u"pending"
    return u"deleted" if edit["kind"] == u"delete" else u"edited"


def pending(overrides, traces):
    """[{injection, analyte, transition}] of the traces whose edit is
    pending (edit_state), in the order of `traces`. A trace is checked
    against its own override, or against none."""
    quant = dict(((t["injection"], t["analyte"]), t["transition"])
                 for t in traces or [] if t.get("role") == u"quant")
    out = []
    for t in traces or []:
        qt = quant.get((t["injection"], t["analyte"]))
        override = edit_for(overrides, t["injection"], t["analyte"], t["transition"], qt)
        if edit_state(t.get("peak"), override) == u"pending":
            out.append({"injection": t["injection"], "analyte": t["analyte"], "transition": t["transition"]})
    return out


def no_effect(overrides, traces):
    """{(injection, analyte, transition): why} of the traces whose edit
    the run kept but could not apply (edit_state "no_effect"); the
    transition is None for the quantifier, as the Manual changes records
    name it."""
    quant = dict(((t["injection"], t["analyte"]), t["transition"])
                 for t in traces or [] if t.get("role") == u"quant")
    out = {}
    for t in traces or []:
        qt = quant.get((t["injection"], t["analyte"]))
        override = edit_for(overrides, t["injection"], t["analyte"], t["transition"], qt)
        if override is not None and edit_state(t.get("peak"), override) == u"no_effect":
            transition = None if t.get("role") == u"quant" else t["transition"]
            out[(t["injection"], t["analyte"], transition)] = t["peak"]["manual"]["unapplied"]
    return out


# an apex choice names its peak by the peak's apex, never by the edges that
# hold it: a shoulder split off a bigger peak can top out on its own edge, or
# just outside it. How many samples either side of the apex its local spacing
# is read over: fewer than any engine's margin beyond the edges, so the stored
# trace and the whole trace read the same samples there.
APEX_SPACING_POINTS = 2
SHARED_APEX_TEXT = u"Two peaks share the apex at %.3f min: choose one by its edges instead."


def apex_tolerance(t, apex):
    """Half the median spacing of the samples within APEX_SPACING_POINTS
    either side of the sample of `t` nearest `apex` (the first of two
    equally near): how far a chosen apex may lie from a peak's own. 0.0
    with fewer than two samples."""
    t = [float(x) for x in (t if t is not None else [])]
    if len(t) < 2:
        return 0.0
    near = 0
    for i in range(1, len(t)):
        if abs(t[i] - apex) < abs(t[near] - apex):
            near = i
    lo, hi = max(near - APEX_SPACING_POINTS, 0), min(near + APEX_SPACING_POINTS, len(t) - 1)
    steps = sorted(t[k + 1] - t[k] for k in range(lo, hi))
    mid = len(steps) // 2
    median = steps[mid] if len(steps) % 2 else (steps[mid - 1] + steps[mid]) / 2.0
    return median / 2.0


def nearest_apex(apexes, apex, tol):
    """The index in `apexes` of the one nearest `apex`, no further than
    `tol` from it; None when none is that near (a None apex is no peak's).
    Two equally near name no peak: ValueError (SHARED_APEX_TEXT)."""
    best, best_d, shared = None, None, False
    for i, a in enumerate(apexes):
        if a is None:
            continue
        d = abs(float(a) - apex)
        if d > tol:
            continue
        if best is None or d < best_d:
            best, best_d, shared = i, d, False
        elif d == best_d:
            shared = True
    if shared:
        raise ValueError(SHARED_APEX_TEXT % apex)
    return best


def match_candidate(peak, apex, t):
    """The stored candidate whose own apex is nearest `apex`, within
    apex_tolerance of the trace's samples `t`; None when none is.
    ValueError (SHARED_APEX_TEXT) when two candidates are equally near."""
    cands = [c for c in (peak or {}).get("candidates") or []
             if c.get("start") is not None and c.get("end") is not None]
    i = nearest_apex([c.get("apex") for c in cands], apex, apex_tolerance(t, apex))
    return None if i is None else cands[i]


def _quant_of(row):
    """The quant record of a raw run row (its derived_from), {} for any other."""
    derived = row.get("derived_from") or u""
    if not derived.startswith(u"raw:"):
        return {}
    try:
        rec = json.loads(derived[len(u"raw:"):])
    except ValueError:
        return {}
    return (rec.get("quant") or {}) if isinstance(rec, dict) else {}


def natives_of(rows, is_name, injection):
    """The analytes of that injection quantified against the isotope standard
    `is_name` (the keyword each row's record names), by the name they are
    shown under (label), sorted."""
    return sorted(set(r.get("label") or r.get("analyte") for r in rows or []
                      if r.get("injection_name") == injection and r.get("analyte") != is_name
                      and _quant_of(r).get("is") == is_name))


def manual_excluded(rows, analyte, levels=None):
    """[{injection, level, reason}] of the calibrators off the analyte's curve
    by a deleted peak, its own or its isotope standard's: the curve's
    excluded entries with a manual reason (MANUAL_DROP_REASONS), each
    injection once, lowest level first (levels are `levels`, {injection
    name: level}; a level that is not a number sorts last, by name).
    Saturation and any other exclusion are not listed."""
    levels, found = levels or {}, {}
    for r in rows or []:
        if r.get("analyte") != analyte:
            continue
        for x in (_quant_of(r).get("curve") or {}).get("excluded") or []:
            if x.get("reason") in MANUAL_DROP_REASONS:
                found.setdefault(x.get("injection"), x.get("reason"))

    def order(inj):
        try:
            return (0, float(levels.get(inj)), inj)
        except (TypeError, ValueError):
            return (1, 0.0, inj)
    return [{"injection": inj, "level": levels.get(inj), "reason": found[inj]}
            for inj in sorted(found, key=order)]


def cal_dropped(rows, analyte, levels, failing):
    """[{injection, level}] of the calibrators dropped by hand from the
    analyte's curve when the worker failed it for them: `failing` are the
    run's failing Calibration QC rows that name calibrators dropped by hand
    (run_calibration.failed_rule_rows). The verdict is theirs and is not
    counted again here; the calibrators are listed from the curve's excluded
    entries (manual_excluded), or, where the rows name none, as the injection
    the worker failed the curve on. [] for a curve the worker did not fail."""
    names = set([analyte] + [r.get("label") for r in rows or [] if r.get("analyte") == analyte])
    mine = [q for q in failing or [] if q.get("analyte") in names]
    if not mine:
        return []
    listed = [{"injection": x["injection"], "level": x["level"]}
              for x in manual_excluded(rows, analyte, levels)]
    if listed:
        return listed
    out = []
    for q in mine:
        inj = (q.get("qc_level") or u"").split(u"|")[0]
        if inj and inj not in [x["injection"] for x in out]:
            out.append({"injection": inj, "level": (levels or {}).get(inj)})
    return out


def _edit_of_trace(overrides, t, quant_transition):
    """The trace's edit state: against its override when the run's overrides
    are known, else from the stored peak alone."""
    if overrides is None:
        return _stored_state(t.get("peak"))
    return edit_state(t.get("peak"), edit_for(overrides, t["injection"], t["analyte"], t["transition"],
                                              quant_transition))


# what a card draws of an edit waiting for the run: its kind and the kind's fields
PENDING_FIELDS = ("kind", "start", "end", "apex", "baseline", "levels")
# an undo waiting for the run: the card draws the automatic peak again
PENDING_REVERT = u"revert"
REVERT_TEXT = u"back to the automatic integration"


def _pending_edit(overrides, t, quant_transition):
    """The edit the card draws while the run has not been processed since
    it was made: the override as an edit of this version (edit_of), its
    kind and fields; {"kind": "revert"} for an undo; None for a record
    that cannot be read."""
    record = edit_for(overrides, t["injection"], t["analyte"], t["transition"], quant_transition)
    if record is None:
        return {"kind": PENDING_REVERT}
    try:
        edit = edit_of(record)
    except ValueError:
        return None
    return dict((k, edit[k]) for k in PENDING_FIELDS if edit.get(k) is not None)


def pending_text(edit, method_baseline):
    """A waiting edit in the panel's words (change_text), a re-integration
    on the method's line naming that line: "re-integrated, valley to
    valley, 11.17 to 11.27 min"; an undo "back to the automatic
    integration"."""
    if edit.get("kind") == PENDING_REVERT:
        return REVERT_TEXT
    if edit.get("kind") == u"integrate" and not edit.get("baseline") and method_baseline:
        edit = dict(edit, baseline=method_baseline)
    return change_text(edit)


def name_pending(found, method_baseline):
    """The card's traces with each waiting edit named (pending_text), the
    method's line read for one that names none."""
    for tr in [found["quant"]] + list(found.get("quals") or []):
        if tr.get("pending_edit"):
            tr["pending_text"] = pending_text(tr["pending_edit"], method_baseline)
    return found


def _review_trace(t, overrides, quant_transition):
    out = _trace(t)
    peak = t.get("peak") or {}
    manual = peak.get("manual") or {}
    for name in TRACE_FIELDS:
        if peak.get(name) is not None:
            out[name] = peak[name]
    if peak.get("baseline") is not None:
        out["baseline"] = stored_baseline(peak)
    if manual:
        out["auto"] = peak.get("auto")
    if manual.get("levels") is not None and not manual.get("unapplied"):
        out["levels"] = manual["levels"]                      # the levels the stored peak was measured on
    if out.get("baseline"):
        out["line"] = line_text(out["baseline"], out.get("levels"))
    out["edit"] = _edit_of_trace(overrides, t, quant_transition)
    if out["edit"] == u"no_effect":
        out["no_effect"] = manual["unapplied"]                # why the card says it had none
    if out["edit"] == u"pending" and overrides is not None:
        waiting = _pending_edit(overrides, t, quant_transition)
        if waiting:
            out["pending_edit"] = waiting
    return out


def card(injection, analyte, traces, rows, lots, overrides=None):
    """One analyte of one injection: its values and traces (the injection
    view's card), and for the quantifier and each qualifier the transition,
    candidates, edit state, full-resolution span, sigma, edge points,
    smoothing, baseline, the line its stored peak was measured on in the
    panel's words ("line") and the levels set by hand on it, the automatic
    peak (when edited), whether the peak is deleted and, for an edit the
    run has not been processed since, the edit the card draws meanwhile
    ("pending_edit"). An isotope standard also names the natives it
    quantifies. None when the analyte has no row or no quantifier trace here.
    `overrides` (the run's) let a not-yet-processed edit read as pending."""
    mine = [t for t in traces or [] if t["injection"] == injection and t["analyte"] == analyte]
    quant = [t for t in mine if t["role"] == u"quant"]
    r = next((x for x in rows or [] if x.get("injection_name") == injection and x.get("analyte") == analyte), None)
    if r is None or not quant:
        return None
    q = quant[0]
    qt = q["transition"]
    allq = dict((t["analyte"], t) for t in traces or [] if t["injection"] == injection and t["role"] == u"quant")
    linked = (q.get("peak") or {}).get("linked_is")
    out = {
        "analyte": analyte, "label": r.get("label") or analyte, "quant": _review_trace(q, overrides, qt),
        "quals": [_review_trace(t, overrides, qt) for t in mine if t["role"] == u"qual"],
        "is": dict(_trace(allq[linked]), label=label_of(rows, linked)) if linked in allq else None,
        "area": r.get("response"), "rt": r.get("rt"), "sn": r.get("sn"),
        "ion_ratio": r.get("ion_ratio_obs"), "ion_expected": r.get("ion_ratio_exp"),
        "conc": r.get("calc_conc"), "qualifier": qualifier_text(r.get("conc_qualifier") or u""),
        "flags": [f for f in [r.get("flag")] if f], "state": _state(r), "lots": list(lots or [])}
    out.update(_measures(q.get("peak") or {}, r))
    if out["fit_flag"] and not out["state"]:
        out["state"] = u"warn"             # a refused or failed fit is for review
    if (q.get("peak") or {}).get("saturated"):
        out["overflowed"] = True           # the quantifier's stored value overflowed at the apex
    out["state_text"] = state_text(out["state"], bool((q.get("peak") or {}).get("deleted")))
    natives = natives_of(rows, analyte, injection)
    if natives:
        out["natives"] = natives
    return out


def injection_view(name, traces, result_rows, lots, overrides=None):
    mine = [t for t in traces or [] if t["injection"] == name]
    names = set(t["analyte"] for t in mine if t["role"] == u"quant")
    analytes = []
    for r in result_rows or []:
        if r.get("injection_name") != name or r.get("analyte") not in names:
            continue
        c = card(name, r["analyte"], mine, result_rows, lots, overrides)
        if c is not None:
            analytes.append(c)
    return {"injection": name, "analytes": analytes}


PEAK_EDGES = ("start", "end", "base_start", "base_end")


def _thumb(injection, analyte, qc_type, r, q, overrides, label=None):
    th = {"injection": injection, "analyte": analyte, "label": label or analyte, "type": qc_type}
    if q is None:
        th.update(state=u"missing", qualifier=u"", conc=(r or {}).get("calc_conc"), edit=u"auto",
                  deleted=False, state_text=state_text(u"missing"))
        return th
    peak = q.get("peak") or {}
    r = r or {}
    state = _state(r)
    deleted = bool(peak.get("deleted"))
    window = peak.get("window")
    if window:
        th["t"], th["y"] = raw_traces_envelope(q["t"], q["y"], window[0], window[1])
    else:
        th["t"], th["y"] = raw_traces_envelope(q["t"], q["y"], float("-inf"), float("inf"))
    th.update(state=state, qualifier=qualifier_text(r.get("conc_qualifier") or u""), conc=r.get("calc_conc"),
              edit=_edit_of_trace(overrides, q, q["transition"]), deleted=deleted,
              state_text=state_text(state, deleted),
              peak=dict((k, peak.get(k)) for k in PEAK_EDGES))
    if peak.get("manual") and peak.get("auto"):
        th["auto"] = dict((k, peak["auto"].get(k)) for k in PEAK_EDGES)
    return th


def raw_traces_envelope(t, y, lo, hi):
    from senaite.pfas import raw_traces
    return raw_traces.envelope(t, y, lo, hi)


def thumbs(mode, key, traces, rows, overrides=None):
    """The overview's thumbnails. mode "compound": `key` is an analyte, one
    thumbnail per injection in run order. mode "injection": `key` is an
    injection, one per analyte in the order of the injection's rows. Each
    carries the quantifier's window reduced to an envelope; a trace that is
    missing reads state "missing" with no points."""
    quant = dict(((t["injection"], t["analyte"]), t) for t in traces or [] if t["role"] == u"quant")
    by_row = {}
    for r in rows or []:
        by_row.setdefault((r.get("injection_name"), r.get("analyte")), r)
    if mode == u"compound":
        pairs = [(i["name"], key, i["type"]) for i in injections(rows)]
    elif mode == u"injection":
        seen, pairs = set(), []
        for r in rows or []:
            if r.get("injection_name") == key and r.get("analyte") not in seen:
                seen.add(r.get("analyte"))
                pairs.append((key, r.get("analyte"), r.get("qc_type") or u""))
    else:
        raise ValueError(u"%s: the overview is by compound or by injection" % mode)
    return [_thumb(i, a, ty, by_row.get((i, a)), quant.get((i, a)), overrides, label_of(rows, a))
            for i, a, ty in pairs]


def read_line(conv, modes):
    """How the run's raw data was read, from each injection's own mode: the
    run's converter mode is the reader's, not what each folder needed."""
    at, args = conv.get("at") or u"", u" ".join(conv.get("args") or [])
    modes = list(modes) or [conv.get("mode") or u""]
    converted = len([m for m in modes if m != u"masslynx"])
    if not converted:
        return u"Read from the MassLynx folder on %s" % at
    if converted == len(modes):
        return u"Converted %s with msconvert %s" % (at, args)
    return u"Read from the MassLynx folder on %s, %s converted with msconvert %s" % (
        at, u"1 injection" if converted == 1 else u"%d injections" % converted, args)


def run_files(manifest):
    manifest = manifest or {}
    conv = manifest.get("converter") or {}
    injections = [{"name": i.get("name"), "folder": i.get("source_folder") or u"",
                   "read": os.path.basename(i.get("file") or u""),
                   "mode": i.get("mode") or conv.get("mode") or u"",
                   "sha256": i.get("sha256") or u"", "files": list(i.get("source") or [])}
                  for i in manifest.get("injections") or []]
    return {"converter": {"mode": conv.get("mode") or u"", "args": u" ".join(conv.get("args") or []),
                          "image": conv.get("image") or u"", "at": conv.get("at") or u""},
            "read": read_line(conv, [i["mode"] for i in injections]),
            "out_of_order": out_of_order(manifest.get("injections") or []),
            "injections": injections}


def out_of_order(injections):
    """"Acquired out of sequence order: <names>" for the injections acquired
    before one earlier in the sequence; "" when the times rise. An injection
    with no acquisition time is passed over."""
    late, latest = [], None
    for i in injections:
        when = (i.get("acquired") or u"")[:19]
        if not when:
            continue
        if latest is not None and when < latest:
            late.append(i.get("name") or u"")
        else:
            latest = when
    return u"Acquired out of sequence order: " + u", ".join(late) if late else u""


def page_json(data):
    """JSON safe inside a <script> element."""
    return (json.dumps(data, sort_keys=True).replace(u"<", u"\\u003c").replace(u">", u"\\u003e")
            .replace(u"&", u"\\u0026"))


# the edits an analyst makes to one trace, and the baselines a peak may be
# set to (raw_preview.BASELINES)
EDIT_KINDS = ("integrate", "apex", "delete")
BASELINES = ("valley", "drop", "flat", "skim")
# the version set_edit stamps on a record: in a record without one, "drop"
# names the flat line at the lower edge (LEGACY_BASELINES)
EDIT_VERSION = 3
LEGACY_BASELINES = {"valley": "valley", "drop": "flat"}


def edit_key(injection, analyte, transition, quant_transition):
    """The overrides key of one trace. The quantifier has one spelling,
    "injection|analyte" (a transition that is None, empty or the quantifier's
    own); a qualifier is "injection|analyte|transition". quant_transition is
    the analyte's quantifier transition text, as the trace row holds it."""
    for part in (injection, analyte):
        if not part or u"|" in part:
            raise ValueError(u"an edit names an injection and an analyte without '|'")
    if transition is None or transition == u"" or transition == quant_transition:
        return u"%s|%s" % (injection, analyte)
    if u"|" in transition:
        raise ValueError(u"%s / %s: the transition has no '|'" % (injection, analyte))
    return u"%s|%s|%s" % (injection, analyte, transition)


def parse_edit_key(key):
    """(injection, analyte, transition) of an overrides key; the transition is
    None for a key that reads as the quantifier's."""
    parts = key.split(u"|")
    if len(parts) not in (2, 3) or not parts[0] or not parts[1] or (len(parts) == 3 and not parts[2]):
        raise ValueError(u"%s: an edit key is injection|analyte or injection|analyte|transition" % key)
    return parts[0], parts[1], (parts[2] if len(parts) == 3 else None)


def _number(record, name, what):
    value = record.get(name)
    if isinstance(value, bool) or value is None:
        raise ValueError(u"%s: %s is a number" % (what, name))
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(u"%s: %s is a number" % (what, name))


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and value == value and value not in (float("inf"), float("-inf")))


def edit_of(record):
    """A stored record as a normalised edit of this version: {"kind", the
    kind's fields, "baseline"?, "levels"?, "version", "by"?, "at"?,
    "reason"?}. A record with no kind and a start and end is a v1
    re-integration; a record with no version names its baseline as it was
    then, "valley" or "drop", and its "drop" is the flat line at the lower
    edge ("flat"); one of this version names any of BASELINES, and a
    re-integration of it may set "levels", [left, right] in counts, two
    finite numbers. ValueError names what is wrong."""
    if not isinstance(record, dict):
        raise ValueError(u"an edit is a record")
    version = record.get("version")
    if version is not None and (isinstance(version, bool) or version != EDIT_VERSION):
        raise ValueError(u"%s: an edit's version is %d" % (version, EDIT_VERSION))
    kind = record.get("kind")
    if kind is None:
        kind = u"integrate"        # v1: edges only; start and end are then required below
    if kind not in EDIT_KINDS:
        raise ValueError(u"%s: the kind of edit is one of %s" % (kind, u", ".join(EDIT_KINDS)))
    allowed = {"integrate": ("start", "end", "baseline", "levels"), "apex": ("apex", "baseline"),
               "delete": ()}[kind]
    for name in ("start", "end", "apex", "baseline", "levels"):
        if name not in allowed and record.get(name) not in (None, u""):
            raise ValueError(u"%s: %s does not belong to this kind of edit" % (kind, name))
    out = {"kind": kind}
    if kind == u"integrate":
        out["start"], out["end"] = _number(record, "start", kind), _number(record, "end", kind)
        if not out["start"] < out["end"]:
            raise ValueError(u"integrate: the start is before the end")
    elif kind == u"apex":
        out["apex"] = _number(record, "apex", kind)
    if kind != u"delete" and record.get("baseline") not in (None, u""):
        known = BASELINES if version is not None else tuple(LEGACY_BASELINES)
        if record["baseline"] not in known:
            raise ValueError(u"%s: the baseline is one of %s" % (record["baseline"], u", ".join(known)))
        out["baseline"] = record["baseline"] if version is not None else LEGACY_BASELINES[record["baseline"]]
    if record.get("levels") is not None:
        levels = record["levels"]
        if version is None:
            raise ValueError(u"integrate: levels belong to an edit of version %d" % EDIT_VERSION)
        if not isinstance(levels, (list, tuple)) or len(levels) != 2 or not all(_finite(v) for v in levels):
            raise ValueError(u"integrate: the levels are two numbers")
        out["levels"] = [float(levels[0]), float(levels[1])]
    out["version"] = EDIT_VERSION
    for name in ("by", "at", "reason"):
        if record.get(name):
            out[name] = record[name]
    return out


def set_edit(overrides, injection, analyte, transition, quant_transition, edit, who, when):
    """The run's overrides with this trace's edit set, an edit of this
    version (EDIT_VERSION: its baseline is one of BASELINES); an earlier
    edit of the trace is replaced. No reason is asked when an edit is
    made."""
    clean = edit_of(dict(edit, version=EDIT_VERSION))
    clean.pop("reason", None)
    clean["by"], clean["at"] = who, when
    out = dict(overrides or {})
    out[edit_key(injection, analyte, transition, quant_transition)] = clean
    return out


def edit_for(overrides, injection, analyte, transition, quant_transition):
    """The stored record of this trace, or None."""
    return (overrides or {}).get(edit_key(injection, analyte, transition, quant_transition))


def clear_edit(overrides, injection, analyte, transition, quant_transition):
    """(overrides without this trace's edit, the record removed); ValueError
    when the trace has none."""
    out = dict(overrides or {})
    key = edit_key(injection, analyte, transition, quant_transition)
    if key not in out:
        raise ValueError(u"%s / %s: there is no edit to undo" % (injection, analyte))
    return out, out.pop(key)


def set_override(overrides, injection, analyte, start, end, who, when, reason):
    """The run's overrides with this peak's edges set by hand, as a v1
    record (no kind; edit_of reads it as a re-integration). The add-on
    writes set_edit's records; this kind stays readable."""
    start, end = float(start), float(end)
    if not start < end:
        raise ValueError(u"%s / %s: the start is before the end" % (injection, analyte))
    if not (reason or u"").strip():
        raise ValueError(u"%s / %s: give the reason" % (injection, analyte))
    out = dict(overrides or {})
    out[u"%s|%s" % (injection, analyte)] = {"start": start, "end": end, "by": who, "at": when,
                                             "reason": reason.strip()}
    return out


def read_overrides(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (IOError, OSError, ValueError):
        return {}


def write_overrides(path, overrides):
    tmp = path + ".part"
    with open(tmp, "w") as fh:
        fh.write(json.dumps(overrides, indent=1, sort_keys=True))
    os.rename(tmp, path)


def run_status(stem_path, expect_error=None):
    """{"state": "" | "waiting" | "failed" | "pulled", "text"} of a raw run the
    Run Builder expects (the pull's files beside it), or of one
    whose expectation could not be written."""
    import os.path
    if expect_error:
        return {"state": u"failed", "text": u"What the raw run expects was not written: %s" % expect_error}
    if os.path.exists(stem_path + ".rawrun"):
        return {"state": u"pulled", "text": u""}
    if os.path.exists(stem_path + ".rawfail"):
        return {"state": u"failed", "text": read_overrides(stem_path + ".rawfail").get("error") or u""}
    status = read_overrides(stem_path + ".rawstatus.json")
    if not status:
        return {"state": u"", "text": u""}
    if status.get("setup"):
        return {"state": u"waiting", "text": status["setup"]}
    parts = []
    if status.get("missing"):
        parts.append(u"not on the share: " + u", ".join(status["missing"]))
    if status.get("unsettled"):
        parts.append(u"not yet unchanged for the settle time: " + u", ".join(status["unsettled"]))
    return {"state": u"waiting", "text": u"Waiting for the raw data; " + u"; ".join(parts)}


def pull_again(stem_path):
    """Ask the worker to pull a failed raw run again: its failure and
    status are removed (the worker then waits for the folders afresh).
    False when nothing had failed."""
    import os
    if not os.path.exists(stem_path + ".rawfail"):
        return False
    os.remove(stem_path + ".rawfail")
    if os.path.exists(stem_path + ".rawstatus.json"):
        os.remove(stem_path + ".rawstatus.json")
    return True
