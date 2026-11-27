# -*- coding: utf-8 -*-
"""What Data Review's Integration Review tab shows for a run imported from raw data.

    injections(result_rows)                        the run's injections, in order
    analytes(result_rows)                          the run's analytes, in order
    injection_view(name, traces, result_rows, lots) one injection: each analyte's
        quantifier and qualifier traces with their peaks, its isotope standard
        beside it, its values and flags, the peak's measures (engine, width,
        tailing, plates, asymmetry, smoothing, the file's transition, its note,
        a refused fit), and the calibration lots it was quantified against
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
    processing_of / set_processing / clear_processing / read_processing /
        update_processing   a change applied to every injection of one trace
        ("Apply to all"), kept apart from the edits (<stem>.processing.json)

`traces` are raw_traces rows with t / y unpacked and peak parsed, keyed by
the analyte's keyword; `result_rows` are the run's injection_results, named
by the compound library's display name, keyed (keyed_rows, with
library_keyword_of) before they are paired with traces or edits. Pure;
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import contextlib
import fcntl
import json
import numbers
import os
import re


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


def failed_checks(result_rows, injection):
    """The checks an injection failed, each read as words: "Ion ratio: PFHxS".
    The check is the one the flag's tag names (qc_qualification.INJECTION_FLAG_TAGS,
    and (REC) as Recovery); a flag with no known tag is given as its own text."""
    out = []
    for r in result_rows or []:
        if r.get("injection_name") == injection and r.get("passed") == 0:
            label = r.get("label") or r.get("analyte") or u""
            out.extend(u"%s: %s" % (check, label) for check in _checks(r))
    return out


def _checks(row):
    """The failed checks of one failed row, as words (failed_checks)."""
    from senaite.pfas import qc_qualification as qq
    flag = row.get("flag") or u""
    found = []
    for tag, check in list(qq.INJECTION_FLAG_TAGS) + [(u"(REC)", u"Recovery")]:
        if tag in flag and check not in found:
            found.append(check)
    return found or [flag.strip() or u"Failed"]


def injections(result_rows, record_injections=None):
    """The run's injections in the order they were acquired (ties and a
    missing time by position in the run's record). Each carries its 1-based
    "position" in the record, its "acquired" time and the checks it "failed"."""
    out, seen = [], {}
    for r in result_rows or []:
        name = r.get("injection_name")
        if name not in seen:
            seen[name] = {"name": name, "type": r.get("qc_type") or u"", "flagged": 0, "warned": 0,
                          "acquired": u"", "position": len(out) + 1}
            out.append(seen[name])
        if r.get("passed") == 0:
            seen[name]["flagged"] += 1
        elif r.get("flag"):
            seen[name]["warned"] += 1
    for n, rec in enumerate(record_injections or [], 1):
        if rec.get("name") in seen:
            seen[rec["name"]].update(position=n, acquired=rec.get("acquired") or u"")
    for i in out:
        i["failed"] = failed_checks(result_rows, i["name"])
    return sorted(out, key=lambda i: (0 if i["acquired"] else 1, (i["acquired"] or u"")[:19], i["position"]))


def clock_order_warning(injections):
    """out_of_order over the injections in position order: "Acquired out of
    sequence order: <names>", or "" when the times rise."""
    return out_of_order(sorted(injections or [], key=lambda i: i.get("position") or 0))


SECTIONS = (("analyte", u"Analytes"), ("surrogate", u"Surrogates"), ("internal_standard", u"Internal standards"))
SECTION_INDEX = dict((k, n) for n, (k, _t) in enumerate(SECTIONS))
# a labelled standard's name: its isotope prefix (13C4-, 13C2,D4-, 13C2-D4-, D3-, d3-, 18O2-);
# 9Cl-PF3ONS and 11Cl-PF3OUdS are natives
LABELLED_RE = re.compile(r"^(?:\d+C\d*(?:[,-]D\d+)?|[dD]\d+|18O2)-")
_ROLE_SECTION = {"surrogate": "surrogate", "injection_is": "internal_standard"}


def section_of(keyword, roles, row=None):
    """The section a compound is listed in: the method's labelled standards
    grid first, then the role the worker stored on the compound's own row
    (std_role), else the name. A labelled name neither lists is a surrogate,
    never an analyte."""
    roles = roles or {}
    found = _ROLE_SECTION.get(roles.get(keyword)) or _ROLE_SECTION.get((row or {}).get("std_role"))
    if found:
        return found
    if keyword not in roles and LABELLED_RE.match(keyword or u""):
        return "surrogate"
    return "analyte"


def sort_key(label):
    """The natural order of a compound's name, numbers as numbers and the
    isotope prefix left off, so 13C4-PFBA sorts as PFBA and 4:2 FTS comes
    before 10:2 FTS. Each part is (0, number) or (1, text): comparable alike
    in Python 2 and 3."""
    name = LABELLED_RE.sub(u"", label or u"")
    out = []
    for part in re.split(r"(\d+)", name):
        if part.isdigit():
            out.append((0, int(part), u""))
        elif part:
            out.append((1, 0, part.lower()))
    return tuple(out)


def _sectioned(items, key):
    """`items` by section, then by the natural order of the name `key` reads."""
    return sorted(items, key=lambda i: (SECTION_INDEX[i["section"]], sort_key(key(i))))


def analytes(result_rows, roles=None):
    """The run's analytes in the overview's order (analytes, surrogates, internal
    standards; each in natural order), each with how many of its rows failed:
    the list by compound. "name" is the analyte (its keyword, on keyed rows),
    "label" what the list shows, "section" the section it is under."""
    out, seen = [], {}
    for r in result_rows or []:
        name = r.get("analyte")
        if name not in seen:
            seen[name] = {"name": name, "label": r.get("label") or name, "flagged": 0, "failed": [],
                          "section": section_of(name, roles, r)}
            out.append(seen[name])
        if r.get("passed") == 0:
            seen[name]["flagged"] += 1
            seen[name]["failed"].extend(u"%s: %s" % (c, r.get("injection_name") or u"") for c in _checks(r))
    return _sectioned(out, lambda a: a["label"])


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
PEAK_MEASURES = ("fwhm_s", "tailing", "plates", "smoothing_from", "file_transition", "fit_note",
                 "asymmetry", "asymmetry_note", "height", "drop_rt", "valley_share")
ENGINES = {u"adaptive": u"Adaptive", u"classic": u"Classic"}
# the worker's own wording on a peak record
FIT_REFUSED = u"trapezoid, fit refused"
PAIR_FIT_FAILED = u"pair fit failed"
def _note(peak):
    """The peak's note, its parts trimmed."""
    parts = [p.strip() for p in (peak.get("note") or u"").split(u";")]
    return u"; ".join(p for p in parts if p)


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
    # the baseline levels the stored peak was measured on, apart from the
    # analyst's manual levels the trace carries as "levels"
    out["baseline_levels"] = peak.get("levels")
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
                "engine", "baseline", "deleted", "fit", "expected_rt", "min_sn")
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
EDIT_WORDS = {u"integrate": u"re-integrated", u"apex": u"apex chosen", u"delete": u"peak deleted",
              u"fit": u"peaks fitted"}


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
    baseline", "peak deleted", "peaks fitted, EMG, 2 peaks, 4.10 to 4.50
    min". `edit` holds its "kind" and the kind's fields: "start" and "end"
    (integrate, fit), "apex" (apex), "shape" and "apexes" (fit), "baseline"
    and "levels" where it has them."""
    kind = edit.get("kind")
    parts = [EDIT_WORDS.get(kind, kind or u"")]
    if kind == u"delete":
        return parts[0]
    if kind == u"fit":
        parts.append(fit_words(edit.get("shape"), len(edit.get("apexes") or ())))
        if edit.get("start") is not None and edit.get("end") is not None:
            parts.append(u"%.2f to %.2f min" % (edit["start"], edit["end"]))
        return u", ".join(parts)
    if kind == u"apex" and edit.get("apex") is not None:
        parts[0] += u" at %.2f min" % edit["apex"]
    line = line_text(edit.get("baseline"), edit.get("levels"))
    if line:
        parts.append(line)
    if kind == u"integrate" and edit.get("start") is not None and edit.get("end") is not None:
        parts.append(u"%.2f to %.2f min" % (edit["start"], edit["end"]))
    return u", ".join(parts)


def stored_state(peak):
    """What a stored peak's review left it as: auto, edited, deleted, or
    no_effect for an edit that did not apply. The package's chromatogram
    captions read it too."""
    manual = (peak or {}).get("manual")
    if not manual:
        return u"auto"
    if manual.get("unapplied"):
        return u"no_effect"
    return u"deleted" if (peak.get("deleted") or manual.get("kind") == u"delete") else u"edited"


def stored_baseline(peak):
    """The baseline a stored peak was measured on, as an edit of this
    version names it: its edit's own where the stored edit names one, else
    a processing change's where one made the peak, else the trace's (the
    method's). A peak stored from an edit without a version, or before any
    edit had one, names the flat line "drop"; a processing change names
    its baseline as an edit of this version does."""
    peak = peak or {}
    manual = peak.get("manual") or {}
    if not manual and (peak.get("processing") or {}).get("baseline"):
        return peak["processing"]["baseline"]
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
    elif edit["kind"] == u"fit":
        # a fitted peak's edges are its component's, not the span clicked:
        # the fit is matched by what was clicked and the span it was made over
        span = (peak.get("fit") or {}).get("span") or [None, None]
        if (manual.get("shape"), manual.get("apexes"), manual.get("pick")) != (
                edit["shape"], edit["apexes"], edit["pick"]):
            return u"pending"
        if not (_near(span[0], edit["start"]) and _near(span[1], edit["end"])):
            return u"pending"
    # the stored peak always carries a baseline (the method's); only an
    # edit that names one is compared with it, and levels with its own
    if edit.get("baseline") and edit["baseline"] != stored_baseline(peak):
        return u"pending"
    if edit.get("levels") != manual.get("levels"):
        return u"pending"
    return u"deleted" if edit["kind"] == u"delete" else u"edited"


def edited_injections(overrides):
    """The names of the injections with an edit on record, sorted: the
    sidebar's per-injection status reads them without reading every trace."""
    names = set()
    for key in overrides or {}:
        try:
            names.add(parse_edit_key(key)[0])
        except ValueError:
            continue
    return sorted(names)


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
    `is_name` (the keyword each row's record names, or a member of the
    composite it names), by the name they are shown under (label), sorted."""
    def on(q):
        return q.get("is") == is_name or is_name in [(m or {}).get("kw") for m in q.get("members") or []]
    return sorted(set(r.get("label") or r.get("analyte") for r in rows or []
                      if r.get("injection_name") == injection and r.get("analyte") != is_name
                      and on(_quant_of(r))))


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


def off_curve(rows, analyte):
    """The calibrators off the analyte's own curve in a raw run, by name,
    sorted: those its rows' curve names as left out (for any reason), and
    every calibrator of an analyte with no curve of its own (none fitted,
    or read on its partner's), as the worker leaves them off."""
    out = set()
    for r in rows or []:
        if r.get("analyte") != analyte:
            continue
        q = _quant_of(r)
        for x in (q.get("curve") or {}).get("excluded") or []:
            if x.get("injection"):
                out.add(x["injection"])
        raw = (r.get("derived_from") or u"").startswith(u"raw:")
        if raw and r.get("qc_type") == u"CAL" and (not q.get("curve") or q.get("curve_of")):
            out.add(r.get("injection_name"))
    return sorted(out)


def _ratio_parts(row):
    """A row's observed ratio per qualifier: a float, or None (not
    calculated, or none)."""
    text = row.get("ion_ratio_text")
    if not text:
        return [row.get("ion_ratio_obs")] if isinstance(row.get("ion_ratio_obs"), float) else []
    out = []
    for part in text.split(u"|"):
        try:
            out.append(float(part))
        except (TypeError, ValueError):
            out.append(None)
    return out


def feeds_expected(rows, injection, analyte, integration, dropped, sources=None):
    """(feeds, samples): whether a change of this injection moves an
    expected ion ratio of the analyte -- a calibrator on the curve (not
    among `dropped`) while any qualifier's expected ratio is the mean of
    the run's calibrators -- and how many of the analyte's other injections
    that moves the verdict of: those with an observed ratio for such a
    qualifier. `injection` None is a change to every injection ("Apply to
    all"), which feeds while any calibrator on the curve does. `sources`
    are the qualifiers' sources as the run's ION record names them
    (ion_lines); without them, the method's one fixed ratio covers its
    first qualifier only."""
    mine = [r for r in rows or [] if r.get("analyte") == analyte]
    cals = [r for r in mine if r.get("qc_type") == u"CAL" and r.get("injection_name") not in (dropped or ())
            and (injection is None or r.get("injection_name") == injection)]
    if sources:
        mean = lambda i: i < len(sources) and sources[i] == u"calibrators"   # noqa: E731
        any_mean = u"calibrators" in sources
    else:
        row = ((integration or {}).get("analytes") or {}).get(analyte)
        row = row if isinstance(row, dict) else {}
        fixed = row.get("expected_ion_ratio") not in (None, u"")
        mean = lambda i: not fixed or i > 0                                  # noqa: E731
        any_mean = not fixed or len(row.get("quals") or []) > 1
    samples = len([r for r in mine if r.get("qc_type") != u"CAL"
                   and any(v is not None and mean(i) for i, v in enumerate(_ratio_parts(r)))])
    return bool(cals) and any_mean, samples


def ion_tolerance(profile):
    """The method's ion-ratio tolerance in %, as the worker reads it: None
    while its limit box is Off (limit_states), or none is set."""
    from senaite.pfas import limit_states as ls
    box = ls.box_for_field("confirmation", "ion_ratio_tol_pct")
    if box is not None and ls.box_state(profile or {}, box) == u"off":
        return None
    return (((profile or {}).get("instrument_verification") or {}).get("confirmation") or {}).get(
        "ion_ratio_tol_pct")


def ion_lines(record, quals=None):
    """The card's ion-ratio lines from the run's ION record (its rule's
    "ions": each qualifier's observed and expected ratio, the expected
    ratio's source and the calibrators it is the mean of), each named by
    its qualifier's transition ("label"; `quals`, the card's qualifier
    traces, are in the order the worker read the ratios); [] with no
    record or none kept."""
    ions = ((record or {}).get("rule") or {}).get("ions") or []
    quals = quals or []
    return [dict(ion, label=quals[i].get("transition") or u"" if i < len(quals) else u"")
            for i, ion in enumerate(ions) if isinstance(ion, dict)]


ION_WITHIN, ION_OUTSIDE = u"within", u"outside"
VERDICT_TEXT = {ION_WITHIN: u"%s: %s now passes the ion ratio", ION_OUTSIDE: u"%s: %s now fails the ion ratio"}


def _ion_verdicts(rows):
    """{injection: verdict} of ION records (injection, verdict, value), keyed
    on the injection as recorded (its name and acquisition stamp, so a
    re-injection is its own); a ratio recorded within with no value was not
    judged and is left out. Rows in the order kept: of two copies kept in
    the same second, the later wins."""
    out = {}
    for inj, verdict, value in rows:
        if verdict == ION_OUTSIDE or (verdict == ION_WITHIN and value is not None):
            out[inj or u""] = verdict
        else:
            out.pop(inj or u"", None)
    return out


def _copy_rows(conn, batch_id, analyte, at):
    return _ion_verdicts(conn.execute(
        "SELECT injection, verdict, value FROM superseded_value_provenance WHERE batch_id=? AND superseded_at=? "
        "AND kind='ION' AND analyte=? ORDER BY id", (batch_id, at, analyte)))


def kept_times(conn, batch_id):
    """The times the worksheet's value records were kept as superseded
    copies (each processing's, each import's), oldest first; [] where the
    store keeps none."""
    if not conn.execute("SELECT name FROM sqlite_master WHERE name='superseded_value_provenance'").fetchone():
        return []
    return [r[0] for r in conn.execute("SELECT DISTINCT superseded_at FROM superseded_value_provenance "
                                       "WHERE batch_id=? ORDER BY superseded_at", (batch_id,))]


def ion_verdict_changes(conn, batch_id, analyte, since):
    """[{"injection", "was", "now"}]: the injections whose ion-ratio verdict
    for `analyte` (the name its records are kept under) the processing of
    the change made at `since` changed: the copy that processing kept (the
    first one kept after the change, qc_schema.REPROCESS) against the state
    it left -- the next copy kept, by a later processing or an import, else
    the records now -- so a later processing never moves it. [] when the
    first copy after the change is an import's (the import's differences
    are not the change's), when none is kept yet, or where the store keeps
    none. The injection is named without its acquisition stamp."""
    from senaite.pfas import qc_schema
    if not conn.execute("SELECT name FROM sqlite_master WHERE name='superseded_value_provenance'").fetchone():
        return []
    events = conn.execute(
        "SELECT superseded_at, MAX(CASE WHEN superseded_by=? THEN 1 ELSE 0 END), MIN(CASE WHEN superseded_by=? "
        "THEN 1 ELSE 0 END) FROM superseded_value_provenance WHERE batch_id=? AND superseded_at>? "
        "GROUP BY superseded_at ORDER BY superseded_at LIMIT 2",
        (qc_schema.REPROCESS, qc_schema.REPROCESS, batch_id, since or u"")).fetchall()
    # the first copy after the change must be a processing's alone
    if not events or not events[0][2]:
        return []
    was = _copy_rows(conn, batch_id, analyte, events[0][0])
    if len(events) > 1:
        now = _copy_rows(conn, batch_id, analyte, events[1][0])
    else:
        now = _ion_verdicts(conn.execute(
            "SELECT injection, verdict, value FROM value_provenance WHERE batch_id=? AND kind='ION' AND analyte=? "
            "ORDER BY id", (batch_id, analyte)))
    return [{"injection": inj.split(u"|")[0], "was": was[inj], "now": now[inj]}
            for inj in sorted(was) if inj in now and now[inj] != was[inj]]


def verdict_texts(analyte, changes):
    """Each change of ion_verdict_changes as the lists say it: "PFOA:
    MILK-0027 now fails the ion ratio"."""
    return [VERDICT_TEXT[c["now"]] % (analyte, c["injection"]) for c in changes or []]


def _edit_of_trace(overrides, t, quant_transition):
    """The trace's edit state: against its override when the run's overrides
    are known, else from the stored peak alone."""
    if overrides is None:
        return stored_state(t.get("peak"))
    return edit_state(t.get("peak"), edit_for(overrides, t["injection"], t["analyte"], t["transition"],
                                              quant_transition))


# what a card draws of an edit waiting for the run: its kind and the kind's fields
PENDING_FIELDS = ("kind", "start", "end", "apex", "baseline", "levels", "shape", "apexes", "pick", "alone")
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
    out["fit_scores"] = peak.get("fit_scores")                # None on a run processed before scores were stored
    for name in TRACE_FIELDS:
        if peak.get(name) is not None:
            out[name] = peak[name]
    if peak.get("baseline") is not None:
        out["baseline"] = stored_baseline(peak)
    if manual:
        out["auto"] = peak.get("auto")
    shown = processing_shown(peak)[0]
    if shown:
        out["processing"] = shown                             # the change the automatic peak was measured on
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


def _composite_is(q, allq, rows):
    """The standard of an analyte read on a composite (its peak names the
    members it was averaged on): named after them, each member's own trace
    beside it; None when the peak names none."""
    from senaite.pfas import composite_standards as cmp
    members = (q.get("peak") or {}).get("linked_members") or []
    if not members:
        return None
    return {"label": cmp.name_of([label_of(rows, m) for m in members]),
            "members": [dict(_trace(allq[m]), label=label_of(rows, m)) for m in members if m in allq]}


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
        "is": (dict(_trace(allq[linked]), label=label_of(rows, linked)) if linked in allq
               else _composite_is(q, allq, rows)),
        "area": r.get("response"), "rt": r.get("rt"), "sn": r.get("sn"),
        "ion_ratio": r.get("ion_ratio_obs"), "ion_expected": r.get("ion_ratio_exp"),
        "conc": r.get("calc_conc"), "qualifier": r.get("conc_qualifier") or u"",
        "detected": r.get("calc_conc") is not None or r.get("conc_qualifier") in (u"BLoQ", u"ALoQ"),
        "flags": [f for f in [r.get("flag")] if f], "state": _state(r), "lots": list(lots or [])}
    out.update(_measures(q.get("peak") or {}, r))
    if out["fit_flag"] and not out["state"]:
        out["state"] = u"warn"             # a refused or failed fit is for review
    out["state_text"] = state_text(out["state"], bool((q.get("peak") or {}).get("deleted")))
    natives = natives_of(rows, analyte, injection)
    if natives:
        out["natives"] = natives
    return out


def _verdict(value, low=None, high=None):
    """"pass" or "fail" for `value` against [low, high] (either bound may be
    None); None with no value or no bound."""
    if value is None or (low is None and high is None):
        return None
    if (low is not None and value < low) or (high is not None and value > high):
        return u"fail"
    return u"pass"


def _number_of(value):
    """The value as a float, None when it is not a number."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    return float(value)


def _blank(value):
    return value is None or (u"%s" % value).strip() == u""


def qual_floor(profile, integration, analyte):
    """The S/N a qualifier of `analyte` is found at, as the worker resolves
    it: the compound's own qualifier detection S/N, else the method's
    confirmation S/N, else the compound's smallest S/N (its own, else the
    method's); None when none is set."""
    row = (integration or {}).get("analytes", {}).get(analyte) or {}
    confirm = (((profile or {}).get("instrument_verification") or {}).get("confirmation") or {}).get(
        "sn_confirm_min")
    for value in (row.get("min_qual_sn"), confirm, row.get("min_sn"), (integration or {}).get("min_sn")):
        if not _blank(value):
            return value
    return None


def ion_verdict(ion, tolerance, detected):
    """One ion-ratio line's verdict as the worker judges it: "fail" when
    |observed / expected - 1| in % is over `tolerance`, or when the ratio
    is not calculable beside a detection; "pass" otherwise; None while the
    tolerance is Off or there is nothing to judge."""
    tol = _number_of(tolerance)
    if tol is None:
        return None
    ion = ion or {}
    if ion.get("observed") == u"uncalculable":
        return u"fail" if detected else None
    obs, exp = _number_of(ion.get("observed")), _number_of(ion.get("expected"))
    if obs is None or not exp:
        return None
    return u"fail" if abs(obs / exp - 1) * 100 > tol else u"pass"


def verdicts(card, integration, tolerance, qual_floor):
    """{"rt", "sn", "qual_sn", "ion_ratio", "asymmetry"}: each card value
    judged against the one limit the method sets for it, "pass", "warn" or
    "fail", and None where the method sets no limit or the card has no value.
    The retention time is judged against the window the worker searches
    (rt_window: the method's tolerance, else the stored window) about the
    expected time the engine applied; it warns only inside that window's
    outer tenth. "ion_ratio" is a list, one verdict per line of card["ions"].
    Asymmetry is judged by peak_limits.ASYM_RANGE. Only the card's measures
    are read: never a concentration or a QC outcome; "detected" is the card's
    own statement that the compound was detected."""
    from senaite.pfas import peak_limits, rt_window
    intg = integration or {}
    row = (intg.get("analytes") or {}).get(card.get("analyte")) or {}
    out = {"rt": None, "sn": None, "qual_sn": None, "ion_ratio": [], "asymmetry": None}
    centre = _number_of((card.get("quant") or {}).get("expected_rt"))
    if centre is None:
        centre = _number_of(card.get("expected_rt"))
    if centre is None:
        centre = _number_of(row.get("rt"))
    try:
        window = rt_window.half_width(row.get("rt"), row.get("window"), rt_window.tolerance(intg))[0]
    except (TypeError, ValueError):
        window = None
    rt = _number_of(card.get("rt"))
    if centre is not None and window is not None and window > 0 and rt is not None:
        dev = abs(rt - centre)
        out["rt"] = u"fail" if dev > window else (u"warn" if dev > 0.9 * window else u"pass")
    min_sn = _number_of(row.get("min_sn") if not _blank(row.get("min_sn")) else intg.get("min_sn"))
    out["sn"] = _verdict(_number_of(card.get("sn")), low=min_sn)
    out["qual_sn"] = _verdict(_number_of(card.get("qual_sn")), low=_number_of(qual_floor))
    out["ion_ratio"] = [ion_verdict(ion, tolerance, bool(card.get("detected"))) for ion in card.get("ions") or []]
    lo, hi = peak_limits.ASYM_RANGE
    out["asymmetry"] = _verdict(_number_of(card.get("asymmetry")), low=lo, high=hi)
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


def foot_of(section, row, rule=None, places=0):
    """The card's foot for a labelled standard, None when the rows hold no
    value (the foot then shows nothing): a surrogate's "rec 92 %" is the
    recovery as the run judged it (rec_judged), else as the QC tab does (recovery.recovery_pct); an internal
    standard's "resp 104 %" its response against the initial calibration's
    mean as the QC engine stored it, never recomputed. An analyte's foot is
    its concentration, drawn from the thumbnail's own values."""
    row = row or {}
    if section == "surrogate":
        pct = row.get("rec_judged")
        if pct is None:
            from senaite.pfas import recovery
            pct = recovery.recovery_pct(row, rule, places)
        return None if pct is None else u"rec %s %%" % _pct_text(pct, places)
    if section == "internal_standard":
        pct = row.get("resp_judged")
        if pct is None:
            pct = row.get("resp_pct")
            if pct is not None:
                from senaite.pfas import rounding
                pct = rounding.judged_pct(pct, rule or rounding.DEFAULT_RULE, 0)
        return None if pct is None else u"resp %s %%" % _pct_text(pct, 0)
    return None


def _pct_text(pct, places):
    return u"%.*f" % (max(int(places or 0), 0), float(pct))


def _thumb(injection, analyte, qc_type, r, q, overrides, label=None, section=u"analyte", foot=None):
    th = {"injection": injection, "analyte": analyte, "label": label or analyte, "type": qc_type,
          "section": section, "foot": foot}
    if q is None:
        th.update(state=u"missing", qualifier=u"", conc=(r or {}).get("calc_conc"), rt=None, failed=[], edit=u"auto",
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
    th.update(state=state, qualifier=r.get("conc_qualifier") or u"", conc=r.get("calc_conc"), rt=r.get("rt"),
              failed=_checks(r) if r.get("passed") == 0 else [],
              edit=_edit_of_trace(overrides, q, q["transition"]), deleted=deleted,
              state_text=state_text(state, deleted),
              peak=dict((k, peak.get(k)) for k in PEAK_EDGES))
    if peak.get("manual") and peak.get("auto"):
        th["auto"] = dict((k, peak["auto"].get(k)) for k in PEAK_EDGES)
    return th


def raw_traces_envelope(t, y, lo, hi):
    from senaite.pfas import raw_traces
    return raw_traces.envelope(t, y, lo, hi)


def thumbs(mode, key, traces, rows, overrides=None, record_injections=None, roles=None, rule=None, places=0):
    """The overview's thumbnails. mode "compound": `key` is an analyte, one
    thumbnail per injection in run order. mode "injection": `key` is an
    injection, one per analyte, analytes then surrogates then internal
    standards, each in natural order. Each carries the quantifier's window
    reduced to an envelope, its "section" (from `roles`, the method's labelled
    standards) and its "foot" (foot_of, judged by `rule` at `places`); a trace
    that is missing reads state "missing" with no points."""
    quant = dict(((t["injection"], t["analyte"]), t) for t in traces or [] if t["role"] == u"quant")
    by_row = {}
    for r in rows or []:
        by_row.setdefault((r.get("injection_name"), r.get("analyte")), r)
    if mode == u"compound":
        pairs = [(i["name"], key, i["type"]) for i in injections(rows, record_injections)]
    elif mode == u"injection":
        seen, pairs = set(), []
        for r in rows or []:
            if r.get("injection_name") == key and r.get("analyte") not in seen:
                seen.add(r.get("analyte"))
                pairs.append((key, r.get("analyte"), r.get("qc_type") or u""))
    else:
        raise ValueError(u"%s: the overview is by compound or by injection" % mode)
    out = []
    for i, a, ty in pairs:
        row = by_row.get((i, a))
        section = section_of(a, roles, row)
        out.append(_thumb(i, a, ty, row, quant.get((i, a)), overrides, label_of(rows, a), section,
                          foot_of(section, row, rule, places)))
    return _sectioned(out, lambda th: th["label"]) if mode == u"injection" else out


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
EDIT_KINDS = ("integrate", "apex", "delete", "fit")
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
    finite numbers. A fit (of this version only) holds its "start", "end",
    "shape", "apexes" and "pick" (_fit_fields). ValueError names what is
    wrong."""
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
               "delete": (), "fit": ("start", "end", "shape", "apexes", "pick", "alone")}[kind]
    for name in ("start", "end", "apex", "baseline", "levels", "shape", "apexes", "pick", "alone"):
        if name not in allowed and record.get(name) not in (None, u""):
            raise ValueError(u"%s: %s does not belong to this kind of edit" % (kind, name))
    out = {"kind": kind}
    if kind in (u"integrate", u"fit"):
        out["start"], out["end"] = _number(record, "start", kind), _number(record, "end", kind)
        if not out["start"] < out["end"]:
            raise ValueError(u"%s: the start is before the end" % kind)
    if kind == u"fit":
        if version is None:
            raise ValueError(u"fit: a fit is an edit of version %d" % EDIT_VERSION)
        out.update(_fit_fields(record))
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


def _fit_fields(record):
    """A fit's own fields, checked: its shape (FIT_SHAPES), two or three
    apexes (one, for a fit marked "alone"), apart, in time order and between its start and end, and the
    index of the component reported among them."""
    if record.get("shape") not in FIT_SHAPES:
        raise ValueError(u"%s: the shape is one of %s" % (record.get("shape"), u", ".join(FIT_SHAPES)))
    apexes = record.get("apexes")
    # one apex only for a fit marked alone (the fits stepper's); the fit tool's own clicks are two or three
    alone = record.get("alone") is True
    if (not isinstance(apexes, (list, tuple)) or len(apexes) not in ((1,) if alone else (2, 3))
            or not all(_finite(v) for v in apexes)):
        raise ValueError(u"fit: the apexes are one number for a fit alone, else two or three" if alone
                         else u"fit: the apexes are two or three numbers")
    apexes = [float(v) for v in apexes]
    if not all(a < b for a, b in zip(apexes, apexes[1:])):
        raise ValueError(u"fit: the apexes lie apart, in time order")
    if not float(record["start"]) < apexes[0] or not apexes[-1] < float(record["end"]):
        raise ValueError(u"fit: every apex lies between the edges")
    pick = record.get("pick")
    if isinstance(pick, bool) or not isinstance(pick, int) or not 0 <= pick < len(apexes):
        raise ValueError(u"fit: the component picked is one of the apexes")
    out = {"shape": record["shape"], "apexes": apexes, "pick": pick}
    if alone:
        out["alone"] = True
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
    """The unlocked primitive: a caller must hold locked(path), or use
    update_overrides, which reads and writes under it."""
    tmp = path + ".part"
    with open(tmp, "w") as fh:
        fh.write(json.dumps(overrides, indent=1, sort_keys=True))
    os.rename(tmp, path)


def _read_locked(path):
    """The overrides to change: {} only when the file is missing. A file that
    cannot be read raises ValueError, so nothing is written over the edits
    of the other traces."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            current = json.load(fh)
    except (IOError, OSError, ValueError):
        current = None
    if not isinstance(current, dict):
        raise ValueError(u"The run's edits cannot be read; nothing was changed.")
    return current


@contextlib.contextmanager
def locked(path):
    """Hold the exclusive lock of the overrides file at `path` (flock on
    path + ".lock"): a second writer waits until the first lets go."""
    with open(path + ".lock", "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def update_overrides(path, change):
    """Read the overrides under the lock, write change(current) atomically
    and return it. `change` may raise ValueError: the file stays as it was.
    Two edits to two traces, made together, are both kept."""
    with locked(path):
        new = change(_read_locked(path))
        write_overrides(path, new)
        return new


# ── processing changes: one trace's change applied to every injection ──────
# (the file's shape: read_processing)
PROCESSING_VERSION = 1
PROCESSING_KINDS = ("integrate", "fit", "smoothing")
# a smoothing change is the compound's, not one trace's: its window in
# points, odd and 5 or more (the smallest window the steps allow), kept in
# the file under "smoothing" by analyte
SMOOTHING_KIND = "smoothing"
SMOOTHING_FEWEST = 5
# a smoothing change's key where the list, the gate and an undo name it
# beside the traces' keys (which never hold this prefix: an analyte keyword
# holds no colon)
SMOOTHING_KEY = u"smoothing:"
FIT_SHAPES = ("gaussian", "emg")
# why an injection does not take a processing change: the trace keeps its
# automatic peak, and the change is listed with these words
SKIP_NO_APEX = u"has no peak"
SKIP_FEW_POINTS = u"too few points"
SKIP_REACH = u"reads past the full-resolution region"
SKIP_OUTSIDE = u"the change runs past the trace"
# a fit applied to all is placed from each injection's expected time
SKIP_NO_TIME = u"has no expected time"
# the fewest samples between the edges each engine measures a peak over
# (raw_integrate.manual_measure: the end after the start; raw_adaptive.between):
# the worker and the card judge a processing change by these alone
ENGINE_FEWEST = {"classic": 2, "adaptive": 4}

# ── a fit of overlapping peaks (raw_integrate.fit_peaks) ───────────────────
# The words of each refusal, kept here once: the worker keeps a fit it
# cannot accept with no effect, or skips an injection that cannot take a
# fit applied to all, in these words; the add-on refuses what it can see
# before writing in its own sentences; the card's preview repeats both.
FIT_NOT_CONVERGED = u"the fit did not converge"
# the RMS of the fit's residual over the trace's baseline noise, written
# with the fewest decimals that read above the limit (raw_preview._above),
# then the method's largest multiple
FIT_RESIDUAL = u"the fit leaves %s times the noise, over the method's %g"
# a fitted peak gone to nothing or to a bound of its shape: its area at
# none, or its centre, width or tail held at a bound
FIT_COLLAPSED = u"a fitted peak collapsed"
# the resampled interval is read on enough refits that converged only
FIT_FEW_REFITS = u"too few resampled fits converged"
# the samples or the start the fit is given cannot be computed on
FIT_NOT_COMPUTED = u"the fit could not be computed"
FIT_NO_NOISE = u"the trace's baseline noise cannot be read"
# the resampled interval's ends written as counts() writes them: "1,101 to 1,367"
FIT_INTERVAL = u"the fitted area's 95 %% interval, %s to %s, is wider than the area"
FIT_NO_LIMIT_TEXT = u"Set the fit limit on the method's Integration tab."
FIT_LABELLED_TEXT = u"%s is an isotope standard: its peak is not fitted."
FIT_APEXES_TEXT = u"Click two or three apexes between the edges."
# why the engine cannot make a fit it is given (raw_integrate.fit_peaks)
FIT_COUNT = u"two or three apexes"
FIT_APART = u"the apexes lie apart, between the edges"
FIT_FEW = u"too few samples between the edges for the fit"
# the reported peak of a fit under the engine's detection floor reads not
# detected, with this note (raw_integrate.fitted_peak)
FIT_FLOOR = u"no peak above the signal-to-noise of %g"
SHAPE_WORDS = {u"gaussian": u"Gaussian", u"emg": u"EMG"}
# a fit's free parameters: area, centre and width per Gaussian, and the
# tail of an EMG, then the line's level and slope
FIT_PARAMETERS = {"gaussian": 3, "emg": 4}


def fit_fewest(shape, peaks):
    """The fewest samples a fit of `peaks` peaks of `shape` is made over:
    one more than its parameters, so its covariance can be read."""
    return FIT_PARAMETERS[shape] * peaks + 2 + 1


def fit_preview_words():
    """What the card's preview of a fit refuses with, in the worker's own
    words, so the card never retypes them: {"texts": {key: text}, "fewest":
    {shape: {"1": n, "2": n, "3": n}} (fit_fewest; "1" is a fit alone)}. In "residual" the %s is the
    multiple written as raw_preview._above writes it and the %g the
    method's limit; in "floor" the %g is the trace's detection floor."""
    texts = {"not_converged": FIT_NOT_CONVERGED, "collapsed": FIT_COLLAPSED, "not_computed": FIT_NOT_COMPUTED,
             "residual": FIT_RESIDUAL, "no_noise": FIT_NO_NOISE, "few": FIT_FEW, "apart": FIT_APART,
             "floor": FIT_FLOOR}
    fewest = dict((shape, dict((str(n), fit_fewest(shape, n)) for n in (1, 2, 3))) for shape in FIT_SHAPES)
    return {"texts": texts, "fewest": fewest}


def fit_words(shape, peaks):
    """"EMG, 2 peaks"."""
    return u"%s, %d peak%s" % (SHAPE_WORDS.get(shape, shape), peaks, u"" if peaks == 1 else u"s")


def processing_key(analyte, transition, quant_transition):
    """The processing file's key of one trace: the bare analyte for the
    quantifier (a transition that is None, empty or the quantifier's own),
    "analyte|transition" for a qualifier."""
    if not analyte or u"|" in analyte:
        raise ValueError(u"a processing change names an analyte without '|'")
    if transition is None or transition == u"" or transition == quant_transition:
        return analyte
    if u"|" in transition:
        raise ValueError(u"%s: the transition has no '|'" % analyte)
    return u"%s|%s" % (analyte, transition)


def parse_processing_key(key):
    """(analyte, transition) of a processing key; the transition is None
    for the quantifier's."""
    parts = key.split(u"|")
    if len(parts) not in (1, 2) or not all(parts):
        raise ValueError(u"%s: a processing key is analyte or analyte|transition" % key)
    return parts[0], (parts[1] if len(parts) == 2 else None)


def processing_of(record):
    """A stored processing record, normalised (its shapes: read_processing);
    ValueError names what is wrong. The edges sit either side of the
    anchor (the apex; a fit's expected time): the start offset below 0,
    the end offset above."""
    if not isinstance(record, dict):
        raise ValueError(u"a processing change is a record")
    kind = record.get("kind")
    if kind not in PROCESSING_KINDS:
        raise ValueError(u"%s: the kind of processing change is one of %s" % (kind, u", ".join(PROCESSING_KINDS)))
    if kind == SMOOTHING_KIND:
        return _smoothing_of(record)
    allowed = {"integrate": ("baseline",), "fit": ("shape", "apex_offsets", "pick", "alone")}[kind]
    for name in ("baseline", "shape", "apex_offsets", "pick", "levels", "start", "end", "apex", "alone"):
        if name not in allowed and record.get(name) is not None:
            raise ValueError(u"%s: %s does not belong to this kind of processing change" % (kind, name))
    out = {"kind": kind}
    for name in ("start_offset", "end_offset"):
        out[name] = _number(record, name, kind)
        if not _finite(out[name]):
            raise ValueError(u"%s: %s is a number" % (kind, name))
    if not out["start_offset"] < 0 < out["end_offset"]:
        raise ValueError(u"%s: the start lies before the apex and the end after it" % kind)
    if kind == u"integrate":
        if record.get("baseline") not in BASELINES:
            raise ValueError(u"%s: the baseline is one of %s" % (record.get("baseline"), u", ".join(BASELINES)))
        out["baseline"] = record["baseline"]
    else:
        if record.get("shape") not in FIT_SHAPES:
            raise ValueError(u"%s: the shape is one of %s" % (record.get("shape"), u", ".join(FIT_SHAPES)))
        offsets = record.get("apex_offsets")
        alone = record.get("alone") is True
        if (not isinstance(offsets, (list, tuple)) or len(offsets) not in ((1,) if alone else (2, 3))
                or not all(_finite(v) for v in offsets)):
            raise ValueError(u"fit: the apex offsets are one number for a fit alone, else two or three")
        offsets = [float(v) for v in offsets]
        if not all(a < b for a, b in zip(offsets, offsets[1:])):
            raise ValueError(u"fit: the apex offsets lie apart, in time order")
        if not all(out["start_offset"] < v < out["end_offset"] for v in offsets):
            raise ValueError(u"fit: every apex lies between the edges")
        if record.get("pick") != expected_pick(offsets):
            raise ValueError(u"fit: the component reported is the apex nearest the expected time, %d"
                             % expected_pick(offsets))
        out.update(shape=record["shape"], apex_offsets=offsets, pick=record["pick"])
        if alone:
            out["alone"] = True
    for name in ("by", "at"):
        if record.get(name):
            out[name] = record[name]
    return out


def _smoothing_of(record):
    """A smoothing record normalised: {"kind": "smoothing", "points": n},
    n an odd whole number of 5 or more, with no edges, line or apexes."""
    for name in ("baseline", "shape", "apex_offsets", "pick", "levels", "start", "end", "apex", "alone",
                 "start_offset", "end_offset"):
        if record.get(name) is not None:
            raise ValueError(u"smoothing: %s does not belong to a smoothing change" % name)
    points = record.get("points")
    # a whole number only: True, 7.0 or "7" are not a window of points
    if (isinstance(points, bool) or not isinstance(points, numbers.Integral)
            or points < SMOOTHING_FEWEST or points % 2 == 0):
        raise ValueError(u"smoothing: the window is an odd number of points, %d or more" % SMOOTHING_FEWEST)
    out = {"kind": SMOOTHING_KIND, "points": int(points)}
    for name in ("by", "at"):
        if record.get(name):
            out[name] = record[name]
    return out


def smoothing_key(analyte):
    """The key a compound's smoothing change is named by: "smoothing:PFOS"."""
    if not analyte or u"|" in analyte:
        raise ValueError(u"a smoothing change names an analyte without '|'")
    return SMOOTHING_KEY + analyte


def parse_smoothing_key(key):
    """The analyte of a smoothing change's key, or None for a trace's key."""
    if key and key.startswith(SMOOTHING_KEY) and len(key) > len(SMOOTHING_KEY):
        return key[len(SMOOTHING_KEY):]
    return None


def smoothing_applied(traces):
    """{analyte: change} of the run's smoothing changes its stored peaks
    name ("smoothing_change", which the worker stores on each trace of the
    compound), read from the quantifier traces, the first injection's."""
    out = {}
    for t in traces or []:
        mark = (t.get("peak") or {}).get("smoothing_change")
        if t.get("role") == u"quant" and isinstance(mark, dict) and t.get("analyte") not in out:
            out[t["analyte"]] = mark
    return out


def processing_applied(traces):
    """{processing key: record} of the run's own processing changes its
    stored peaks show (processing_shown: not marked "from": "method"), the
    first injection's record naming the trace, without the injection's own
    expected time; one the record shape refuses is kept as stored. A trace
    whose key cannot be named raises ValueError: the gate refuses rather
    than pass a change it cannot name."""
    quant = dict(((t["injection"], t["analyte"]), t["transition"])
                 for t in traces or [] if t.get("role") == u"quant")
    out = {}
    for t in traces or []:
        shown = processing_shown(t.get("peak"))[0]
        if not isinstance(shown, dict) or shown.get("from") == u"method":
            continue
        key = processing_key(t["analyte"], t["transition"], quant.get((t["injection"], t["analyte"])))
        if key in out:
            continue
        record = dict((k, v) for k, v in shown.items() if k != "expected")
        try:
            record = processing_of(record)
        except ValueError:
            pass
        out[key] = record
    return out


def processing_dict(traces, smoothing=None):
    """The whole processing file dict of these traces' changes and, where
    there are any, the compounds' smoothing changes."""
    out = {"version": PROCESSING_VERSION, "traces": dict(traces or {})}
    if smoothing:
        out["smoothing"] = dict(smoothing)
    return out


def _smoothing(proc):
    return (proc or {}).get("smoothing") or {}


def with_smoothing(proc, analyte, record):
    """A new processing file dict with the compound's smoothing change set
    (an earlier one replaced), the traces' changes kept. `record` is a
    smoothing record (processing_of), stamped by its caller."""
    clean = processing_of(record)
    if clean["kind"] != SMOOTHING_KIND:
        raise ValueError(u"%s: a smoothing change is of the kind smoothing" % analyte)
    smoothing_key(analyte)                  # an analyte a key can name
    smoothing = dict(_smoothing(proc))
    smoothing[analyte] = clean
    return processing_dict((proc or {}).get("traces"), smoothing)


def without_smoothing(proc, analyte):
    """A new processing file dict without the compound's smoothing change;
    ValueError when it has none."""
    smoothing = dict(_smoothing(proc))
    if analyte not in smoothing:
        raise ValueError(u"%s: there is no smoothing change to undo" % analyte)
    del smoothing[analyte]
    return processing_dict((proc or {}).get("traces"), smoothing)


def set_processing(proc, analyte, transition, quant_transition, record, who, when):
    """A new processing file dict with this trace's change set (an earlier
    one of the trace replaced), stamped by `who` at `when`. `proc` is the
    whole file dict, {} for none."""
    clean = processing_of(record)
    clean["by"], clean["at"] = who, when
    if clean["kind"] == SMOOTHING_KIND:
        raise ValueError(u"%s: a smoothing change is the compound's (with_smoothing)" % analyte)
    traces = dict((proc or {}).get("traces") or {})
    traces[processing_key(analyte, transition, quant_transition)] = clean
    return processing_dict(traces, _smoothing(proc))


def clear_processing(proc, analyte, transition, quant_transition):
    """A new processing file dict without this trace's change; ValueError
    when the trace has none."""
    traces = dict((proc or {}).get("traces") or {})
    key = processing_key(analyte, transition, quant_transition)
    if key not in traces:
        raise ValueError(u"%s: there is no processing change to undo" % analyte)
    del traces[key]
    return processing_dict(traces, _smoothing(proc))


def processing_shown(peak):
    """(processing, processing_skipped) a stored peak shows: its own, or,
    under an analyst's edit, its automatic peak's, which the change was
    applied to."""
    peak = peak or {}
    auto = peak.get("auto") or {}
    return (peak.get("processing") or auto.get("processing"),
            peak.get("processing_skipped") or auto.get("processing_skipped"))


def _same_processing(shown, record):
    """Whether a stored peak's change is the file's record: the same kind,
    offsets and line, made at the same time."""
    if not shown or shown.get("kind") != record.get("kind"):
        return False
    if record.get("at") and shown.get("at") != record.get("at"):
        return False
    if not all(_near(shown.get(k), record.get(k), 1e-9) for k in ("start_offset", "end_offset")):
        return False
    return all(shown.get(k) == record.get(k) for k in ("baseline", "shape", "apex_offsets", "pick", "alone")
               if record.get(k) is not None)


def processing_pending(proc, traces, method=None):
    """[{injection, analyte, transition}] of the traces whose stored peak
    does not yet show the run's processing file (`proc`, the whole dict):
    a trace with a change whose peak shows neither that change nor why it
    was skipped, and a trace with none whose peak still shows one (an
    undone change), in the order of `traces`. `method` {keyword: the
    method's processing entry} (method_proposals): a trace the file holds
    no change of may show the method's instead, or why it was skipped, or,
    processed before the method had it, none; it waits only while it shows
    another change. A compound's smoothing change ("smoothing") keeps each
    of its quantifier traces waiting until its stored peak names that change
    ("smoothing_change", which the worker stores), and an undone one until
    it names none."""
    from senaite.pfas.method_proposals import with_method_processing
    records = (proc or {}).get("traces") or {}
    own = with_method_processing({}, method)[0]
    method_records = (own or {}).get("traces") or {}
    quant = dict(((t["injection"], t["analyte"]), t["transition"])
                 for t in traces or [] if t.get("role") == u"quant")
    out = []
    for t in traces or []:
        try:
            key = processing_key(t["analyte"], t["transition"], quant.get((t["injection"], t["analyte"])))
        except ValueError:
            continue
        shown, skipped = processing_shown(t.get("peak"))
        record = records.get(key)
        if record is None and (shown or {}).get("from") == "method":
            waiting = False
        elif record is None and key in method_records:
            waiting = bool(shown) and not _same_processing(shown, method_records[key])
        elif record is None:
            waiting = bool(shown or skipped)
        else:
            waiting = not (skipped or _same_processing(shown, record))
        if waiting:
            out.append({"injection": t["injection"], "analyte": t["analyte"], "transition": t["transition"]})
    # a compound's smoothing change: each quantifier trace of it waits while
    # its stored peak names another smoothing change of the run, or none,
    # and, the change undone, while it still names one
    smoothing = (proc or {}).get("smoothing") or {}
    for t in traces or []:
        if t.get("role") != u"quant":
            continue
        record = smoothing.get(t.get("analyte"))
        shown = (t.get("peak") or {}).get("smoothing_change")
        if (record or shown) and not _same_smoothing(shown, record):
            out.append({"injection": t["injection"], "analyte": t["analyte"], "transition": t["transition"]})
    return out


def _same_smoothing(shown, record):
    """Whether a stored trace's smoothing change is the file's: the same
    window, made at the same time."""
    if not isinstance(shown, dict) or not isinstance(record, dict):
        return False
    return shown.get("points") == record.get("points") and shown.get("at") == record.get("at")


def method_applied(proc, traces):
    """{processing key: record} of the method's processing changes the run
    applied, read from its stored peaks (`traces`, each {injection,
    analyte, transition, role, peak}): a peak whose change is marked
    "from": "method" (processing_shown), for a trace the run's own
    processing file (`proc`, the whole dict) holds no change of. The record
    is the one stored, without the injection's own expected time, so what
    is listed and countersigned is what was applied, whatever the method
    holds now; one the record shape refuses is kept as stored. The first
    injection's record names the trace."""
    own = (proc or {}).get("traces") or {}
    quant = dict(((t["injection"], t["analyte"]), t["transition"])
                 for t in traces or [] if t.get("role") == u"quant")
    out = {}
    for t in traces or []:
        shown = processing_shown(t.get("peak"))[0]
        if not isinstance(shown, dict) or shown.get("from") != u"method":
            continue
        try:
            key = processing_key(t["analyte"], t["transition"], quant.get((t["injection"], t["analyte"])))
        except ValueError:
            continue
        if key in own or key in out:
            continue
        record = dict((k, v) for k, v in shown.items() if k not in ("from", "expected"))
        try:
            record = processing_of(record)
        except ValueError:
            pass
        out[key] = record
    return out


def expected_pick(offsets):
    """The index of the apex offset nearest the expected time (0), the first
    of two equally near: the component a fit applied to all reports in
    every injection, fixed when the change is made."""
    return min(range(len(offsets)), key=lambda k: (abs(offsets[k]), k))


def fit_processing_text(change):
    """A fit applied to all in words, the one wording of the list and the
    value's provenance: "fitted for all injections: EMG, 2 peaks, -0.15 to
    +0.25 min from the expected time"; where the change names the
    injection's expected time, the span there: "fitted for all
    injections: EMG, 2 peaks, from 4.05 to 4.45 min, placed from the
    expected time 4.20 min"."""
    words = u"fitted for all injections: " + fit_words(change.get("shape"), len(change.get("apex_offsets") or ()))
    expected = change.get("expected")
    if expected is None:
        return u"%s, %+.2f to %+.2f min from the expected time" % (words, change["start_offset"],
                                                                    change["end_offset"])
    return u"%s, from %.2f to %.2f min, placed from the expected time %.2f min" % (
        words, expected + change["start_offset"], expected + change["end_offset"], expected)


def processing_text(record):
    """A processing change in the list's words: "perpendicular drop, -0.05
    to +0.08 min from the apex"; "automatic" for none. A change made over
    the method's own processing says so in the list itself (Data Review's
    METHOD_BEFORE), never here."""
    if not record:
        return u"automatic"
    if record.get("kind") == SMOOTHING_KIND:
        return u"smoothing over %d points" % record["points"]
    if record.get("kind") == u"fit":
        return fit_processing_text(record)
    return u"%s, %+.2f to %+.2f min from the apex" % (line_text(record.get("baseline")), record["start_offset"],
                                                     record["end_offset"])


def read_processing(path):
    """The whole processing file dict; {} when the file is absent. A file
    that cannot be read raises ValueError: a run is never processed as
    though its processing changes were not there.

    The run's processing file, <stem>.processing.json beside the overrides
    and kept apart from them (every overrides key is a trace edit), is
        {"version": PROCESSING_VERSION,
         "traces": {processing_key(analyte, transition, quant_transition): record}}
    and a record is one of
        {"kind": "integrate", "baseline": one of BASELINES,
         "start_offset": below 0, "end_offset": above 0, "by", "at"}
        {"kind": "fit", "shape": one of FIT_SHAPES, "apex_offsets": two or
         three offsets in time order, "start_offset", "end_offset", "pick":
         the index of the offset nearest the expected time (expected_pick),
         "by", "at"}
    every offset in minutes from each injection's own automatic apex; a
    fit's from each injection's expected time (the time its peak is
    searched about), the component its pick names reported.
    and beside "traces", where a compound's smoothing is changed for the
    run, "smoothing": {analyte: {"kind": "smoothing", "points": an odd
    number, 5 or more, "by", "at"}}, the window every trace of that
    compound is smoothed over in every injection.
    set_processing, clear_processing, with_smoothing, without_smoothing and
    update_processing's `change` take and return this whole dict, each
    keeping what it does not change."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            current = json.load(fh)
    except (IOError, OSError, ValueError):
        current = None
    if not isinstance(current, dict) or not _smoothing_readable(current.get("smoothing")):
        raise ValueError(u"The run's processing changes cannot be read.")
    return current


def _smoothing_readable(smoothing):
    """Whether a file's "smoothing" can be read: absent, or a dict keyed by
    analytes a smoothing key can name."""
    if smoothing is None:
        return True
    if not isinstance(smoothing, dict):
        return False
    try:
        for analyte in smoothing:
            smoothing_key(analyte)
    except (TypeError, ValueError):
        return False
    return True


def update_processing(path, change):
    """update_overrides for the processing file: read it under its own
    lock, write change(current) atomically and return it. `change` gets
    and returns the whole file dict ({} when there is none) and may raise
    ValueError, leaving the file as it was."""
    with locked(path):
        new = change(read_processing(path))
        write_overrides(path, new)
        return new


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
