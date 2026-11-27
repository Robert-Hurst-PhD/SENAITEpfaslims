"""A run imported from raw data: the run record (manifest) and one mzML or
MassLynx .raw folder per injection, integrated and quantified into the same
InstrumentRows a vendor export gives, each row carrying its peak's provenance.

    {"run": "...", "injections": [{"name", "type", "level", "expected_conc":
      {compound: concentration},
      "file": "<rel>.mzML" or "<rel>.raw", "sha256", "acquired": ISO time}], "converter": {...}}

A folder's sha256 is folder_digest over its files. Traces are kept per
analyte ({injection: {analyte: {transition: (t, y)}}}): a transition
scheduled in two windows is read, for each analyte, in the one holding its
retention time, so one transition can serve two analytes in different
windows. A calibrator with no reading is left off its analyte's curve, and
the curve lists it under "excluded" and names the highest calibrator still
on it (top_conc, top_level, top_injection), where the run's reporting range
ends (pipeline.raw_range): a reading above it is above the calibration
range.

The integration settings are the method's (its Integration tab):
{"engine": "classic" | "adaptive", "method": raw_integrate.Settings (classic)
or raw_integrate.AdaptiveSettings (adaptive), "analytes": {name: {"quant": (q1, q3),
"quals": [(q1, q3)], "rt", "window", "mode": single|pair|summed, "partner",
"expected_ion_ratio", "labelled": True for a labelled standard}}}. Each native is quantified on its labelled
standard's response ratio (the surrogate map) against this run's
calibrators, fitted as the method's calibration rule says (quant_fit).

Under the adaptive engine (raw_adaptive) each quantifier trace is searched
whole and the analyte's peak is the detected one nearest its expected time
within its window; a qualifier's is the detected one within the method's
apex tolerance of the quantifier apex; a re-integration is measured between
the analyst's edges at the smoothing the automatic peak used. An auto
smoothing is learnt per analyte from its median-concentration calibrator
(learn_smoothing) and named on each peak (smoothing_from). Under relative
retention (rt_anchor "labelled") the labelled standards are found first, at
their configured times, and each native is expected at its configured time
scaled by its quantitation standard's found apex over that standard's
configured time.

Isomer peaks (lr-, br-) are separate analytes, each on its own curve, and
keep their names on the rows; they are summed only at reporting. A
branched peak no calibrator states a concentration for (a linear-only
standard) is read on its linear partner's curve, which its peak names
(curve_of); the two must share a quantitation standard. A summed
analyte with a partner (a branched isomer) is, under either engine, the sum
of the peaks in its own window less the peak chosen for its partner. A
partner's window, less the analyte's own, is left out of the analyte's noise.

A reading below zero has no concentration: a detected peak reads BLoQ and
its reading is kept on the peak's record (quant.reading). On a straight
line, a native's reading in a sample under the lowest calibrator still on
its curve (bottom_conc, bottom_level) keeps its number, with that
calibrator's concentration as its reporting limit, so the summary reads it
BLoQ. On a quadratic, a native in a sample whose ratio is below the curve's
response at the lowest calibrator reads BLoQ with no number here; its
reading on the rising branch between zero and that calibrator is kept on the
record (quant.below, bottom_response, below_reading), and the pipeline gives
it the number only where, on the sample basis, it is at or above the MDL
(pipeline.raw_below_mdl). Standards, check
standards and blanks are read on the whole rising branch. A native in any
injection but a calibrator whose ratio is above the curve's response at its
highest calibrator is above the calibration range (quant.above_range,
top_response), whatever the fit; a sample's with no reading on the curve
reads ALoQ here, a spike's or blank's from pipeline.raw_range, and a check
standard's stays N.Q. and fails its window.
A quadratic that turns within its calibration range is not fitted, and the
run names the analyte.

The analyst's edits (<stem>.overrides.json, read through the add-on's
raw_review record) replace a trace's automatic peak every time the run is
processed, the automatic peak kept on the row's record: a re-integration
between given edges, another apex (a single peak only: the candidate whose
own apex is nearest it, found as the automatic peak was), either with its own
baseline (raw_integrate.BASELINES; a re-integration also with levels set by
hand), or a deleted peak. A peak measured on a line the analyst chose (a
re-integration, another apex with its own baseline) has as its area the
trapezoid of the raw signal above that line, whatever the method's area
measure: its record says so (MANUAL_LINE_AREA). A re-integration the run
cannot make (levels off the trace, fewer points than the method's fewest
points in a peak, a span the engine cannot measure) is kept with no
effect and the reason, the trace staying automatic. A deleted quantifier is N.D.; a calibrator's comes
off its curve ("peak deleted"), and an isotope standard's takes its
natives' concentrations in that injection (each native's record says
quant.is_deleted, which a QC check fails) and its calibrators off their
curves ("isotope standard peak deleted"). A deleted qualifier is not
confirmed (the row's record lists it under qual_deleted, which the
confirmation and lowest-calibrator checks read), its S/N is the
first qualifier's still present and the ion ratio the other qualifiers'.
A deleted linear isomer leaves its branched partner's sum as it was
beside the automatic linear peak.

A processing change (<stem>.processing.json, "Apply to all", read through
the add-on's raw_review record and never written here) is applied to every
injection of one trace before the edits: its edges are the change's
offsets from each injection's own automatic apex, measured on its baseline
and the method's area measure. The peak it makes is automatic (the
manual-change limits never judge it), and an edit of the trace keeps its
manual peak over it. An injection with no apex, too few points between
the edges or a drop or a skim reading past the stored trace's
full-resolution region keeps its automatic peak, and its record says why.
The method's own processing entry (method_proposals, countersigned from a
run) takes every trace the file holds no change of, through the same path,
and its peak's change says "from": "method".

Nothing is quantified from a partial run: a file missing, not matching its
checksum or not readable, a transition missing from a file, a native or
isomer peak with no quantitation standard, or a curve that cannot be fitted
refuses the whole run, naming the injection and the analyte.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import math
import os
from datetime import datetime, timezone

import numpy as np

from .addon import load


def _row_name(keyword):
    """A raw row is named as a vendor export's row is, the library's display
    name; the keyword itself where no library export is at hand (the
    pipeline refuses a run without one before this is reached). An isomer
    peak (lr-, br-) keeps its own name: it is quantified apart and summed
    only at reporting."""
    if load("isomers").is_peak_name(keyword):
        return keyword
    from .analyte_alias import LibraryUnavailable, canonical_name
    try:
        return canonical_name(keyword)
    except LibraryUnavailable:
        return keyword
from .constants import IS_PEAK_DELETED, PEAK_DELETED, QUALIFIER_ALOQ, QUALIFIER_BLOQ, QUALIFIER_NQ
from .models import InstrumentRow
from . import masslynx_raw
from . import peak_asymmetry
from . import peak_score
from . import raw_adaptive
from . import raw_integrate as ri


class RawRunError(Exception):
    pass


class Unapplied(RawRunError):
    """An edit the run keeps but cannot apply: the trace stays automatic,
    and the edit is kept with this reason (raw_review's wording)."""


class Skipped(Unapplied):
    """An injection that cannot take a processing change ("Apply to all"):
    its trace keeps the automatic peak, and the change names the injection
    with this reason (raw_review's SKIP_* words)."""


# the run record's injection types as the rows carry them (a vendor
# export's names, which the pipeline reads)
SAMPLE_TYPES = {"QC": "Quality Control"}
# the run record's injection types that are no sample: calibrators, check
# standards and spikes, blanks
NOT_SAMPLES = ("Standard", "QC", "Blank")
# the worker's run area: a manifest may name a run folder only directly under it
RUN_ROOT = os.environ.get("RAW_RUN_DIR", "/data/raw_runs")


def _expected(inj, name):
    """A compound's concentration in a calibrator or check standard: each
    compound its own (a scaled ladder, a labelled standard at one level)."""
    exp = inj.get("expected_conc")
    return exp.get(name) if isinstance(exp, dict) else None


# the run roles whose labelled concentrations are stated amounts: a check
# standard is prepared with them, as a calibrator is
CHECK_STANDARD_ROLES = ("CCV", "ICV")
# why a labelled standard in an injection has no recovery
NO_FOUND_AMOUNT = "no amount found on its internal standard"
NO_CAL_LEVEL = "the calibrators state no level of it, the level every sample is spiked to"
SEVERAL_CAL_LEVELS = "the calibrators state it at more than one level, so the level a sample is spiked to is not one"
# where the amount spiked is stated
FROM_CALIBRATORS = "calibrators"


def calibrator_levels(calibrators):
    """{compound: set of the concentrations the calibrators state for it}."""
    out = {}
    for inj in calibrators:
        for name, value in (inj.get("expected_conc") or {}).items():
            if value is not None:
                out.setdefault(name, set()).add(round(float(value), 12))
    return out


def _spiked(inj, name, levels):
    """(amount, where it is stated, why none) of a labelled standard added to
    an injection, in the ladder's unit. The run record's `spiked_conc` wins;
    a check standard's is its own stated concentration; every other
    injection taken through the extraction is spiked so its final extract
    holds the surrogate at the calibrators' level (a method fact), which
    must be one level. A calibrator's is a point of its curve, never a
    recovery, and is not asked here."""
    stated = inj.get("spiked_conc")
    value = stated.get(name) if isinstance(stated, dict) else None
    if value is not None:
        return float(value), "spiked_conc", ""
    if (inj.get("role") or "").upper() in CHECK_STANDARD_ROLES:
        own = _expected(inj, name)
        return (float(own), "expected_conc", "") if own is not None else (None, "", NO_CAL_LEVEL)
    found = (levels or {}).get(name) or set()
    if not found:
        return None, "", NO_CAL_LEVEL
    if len(found) > 1:
        return None, "", SEVERAL_CAL_LEVELS
    return next(iter(found)), FROM_CALIBRATORS, ""


def surrogate_recovery(found, spiked, source, why, link):
    """(percent or None, record) of a labelled standard read on the standard
    it is linked to: Recovery = C_found / C_spiked x 100. The record keeps
    both amounts, where the spiked one is stated and the internal standard;
    with no recovery, why."""
    if spiked is None or spiked <= 0:
        return None, {"none": why or NO_CAL_LEVEL, "is": link}
    if found is None:
        return None, {"none": NO_FOUND_AMOUNT, "is": link, "spiked": spiked, "from": source}
    pct = 100.0 * found / spiked
    return pct, {"found": found, "spiked": spiked, "from": source, "is": link, "pct": pct}


def safe_join(base, rel):
    """`rel` joined onto `base`, or None when it is empty, absolute or
    would leave `base`."""
    if not rel or os.path.isabs(rel):
        return None
    root = os.path.realpath(base)
    path = os.path.realpath(os.path.join(root, rel))
    if path == root or not path.startswith(root + os.sep):
        return None
    return os.path.join(base, os.path.normpath(rel))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _checksums(folder):
    """[{"name", "size", "sha256", "mtime"}] for every file under a folder
    injection, names relative to it."""
    source = []
    for root, _dirs, files in os.walk(folder):
        for f in sorted(files):
            p = os.path.join(root, f)
            source.append({"name": os.path.relpath(p, folder), "size": os.path.getsize(p),
                           "sha256": _sha256(p),
                           "mtime": datetime.fromtimestamp(os.path.getmtime(p), timezone.utc)
                           .strftime("%Y-%m-%dT%H:%M:%S")})
    return source


def folder_digest(source):
    """The sha256 recorded for a folder injection: over the sorted
    "<name>:<sha256>" lines of its checksum list, so it follows every file's
    name and content and not the order they were listed in."""
    lines = sorted("%s:%s\n" % (f["name"], f["sha256"]) for f in source)
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _label(q):
    """A transition as the traces name it, by the add-on's one rule
    (method_proposals.transition_label), which its saved processing keys on."""
    return load("method_proposals").transition_label(q)


def _matches_checksum(path, expected):
    """A folder injection is checked by its files' digest (folder_digest),
    recomputed from the folder as it is now; a file by its own sha256."""
    if os.path.isdir(path):
        return folder_digest(_checksums(path)) == expected
    return _sha256(path) == expected


def _chromatograms(path):
    """A folder injection is a MassLynx .raw folder, read natively; a file is mzML."""
    if os.path.isdir(path):
        return masslynx_raw.read_chromatograms(path)
    return load("raw_mzml").read_chromatograms(path)


def _span(c):
    return "%.2f-%.2f min" % (c["t"][0], c["t"][-1]) if c["t"] else "empty"


def _covering(found, rt):
    """Of a transition's chromatograms, the first whose recorded span holds
    `rt`: a transition scheduled in two windows is read in the one the
    analyte elutes in, never in whichever was read last."""
    for c in found:
        if c["t"] and c["t"][0] <= rt <= c["t"][-1]:
            return c
    return None


# used when the integration block states no m/z tolerance
DEFAULT_MZ_TOLERANCE = 0.1
# a file transition this far from the configured one (two-decimal resolution) is named in the provenance
FILE_TRANSITION_NOTED = 0.005


def _traces(base, injections, analytes, tolerance=DEFAULT_MZ_TOLERANCE):
    """({injection: {analyte: {transition: (t, y)}}}, {injection: {analyte:
    {transition: file transition}}}), after every file is checked. Each analyte has its own traces: one transition scheduled in two
    windows can serve two analytes, each from the window it elutes in. Each
    configured transition is matched to the file's nearest within `tolerance`
    on Q1 and Q3 and stored under the configured one's key; the third result
    names, per injection and analyte, the file transition where it differs."""
    mzml = load("raw_mzml")
    out, renamed, problems = {}, {}, []
    tol = float(tolerance)
    for inj in injections:
        path = safe_join(base, inj.get("file"))
        if path is None:
            problems.append("%s: the file %s is outside the run" % (inj["name"], inj.get("file")))
            continue
        if not os.path.exists(path):
            problems.append("%s: the file %s is missing" % (inj["name"], inj["file"]))
            continue
        if not _matches_checksum(path, inj.get("sha256")):
            problems.append("%s: %s does not match its checksum" % (inj["name"], inj["file"]))
            continue
        try:
            records = _chromatograms(path)
        except masslynx_raw.MassLynxError as exc:
            # a folder that matches its checksum can still be unreadable: the
            # run is refused whole, every such injection named
            problems.append("%s: %s cannot be read: %s" % (inj["name"], inj["file"], exc))
            continue
        by_key = {}
        for c in records:
            by_key.setdefault((float(c["q1"]), float(c["q3"])), []).append(c)
        out[inj["name"]], renamed[inj["name"]] = {}, {}
        for name in sorted(analytes):
            a = analytes[name]
            chosen, differs = {}, {}
            for q in [a["quant"]] + list(a.get("quals") or []):
                key = mzml.transition_key(*q)
                try:
                    file_q = mzml.match_transition(q, by_key, tol)
                except mzml.AmbiguousTransition as exc:
                    problems.append("%s: %s for %s is ambiguous: %s" % (inj["name"], _label(q), name, exc))
                    continue
                found = by_key.get(file_q)
                if not found:
                    problems.append("%s: no %s chromatogram for %s" % (inj["name"], _label(q), name))
                    continue
                c = _covering(found, a["rt"])
                if c is None:
                    # a scheduled acquisition records a segment: the expected
                    # time must be in it (a window running past its ends is kept)
                    problems.append("%s: %s, expected at %.2f min, is outside its %s chromatogram (%s)" % (
                        inj["name"], name, a["rt"], _label(q), ", ".join(_span(x) for x in found)))
                else:
                    chosen[key] = c
                    if max(abs(file_q[0] - q[0]), abs(file_q[1] - q[1])) >= FILE_TRANSITION_NOTED:
                        differs[key] = "%.2f > %.2f" % (file_q[0], file_q[1])
            out[inj["name"]][name] = dict((k, (c["t"], c["y"])) for k, c in chosen.items())
            renamed[inj["name"]][name] = differs
    if problems:
        raise RawRunError("The raw run cannot be quantified: " + "; ".join(problems))
    return out, renamed


def settings_for(a, settings, name):
    """The integration settings of one compound: the method's, with those
    the compound sets for itself. A compound setting its engine does not use
    is left out (UNUSED_COMPOUND_SETTINGS); under Adaptive its smoothing in
    points is the half-width m = (n - 1) / 2, or auto; a stored "drop"
    baseline is the flat line (raw_integrate.method_baseline). A value the
    method would refuse, or a setting no engine knows, refuses the run,
    naming the compound."""
    adaptive = isinstance(settings, ri.AdaptiveSettings)
    unused = UNUSED_COMPOUND_SETTINGS["adaptive" if adaptive else "classic"]
    own = dict((k, v) for k, v in (a.get("settings") or {}).items() if k not in unused)
    try:
        if "baseline" in own:
            own["baseline"] = ri.method_baseline(own["baseline"])
        if adaptive and "smooth_points" in own:
            own["smooth"] = _half_width(own.pop("smooth_points"))
        return dataclasses.replace(settings, **own)
    except (TypeError, ValueError) as exc:
        raise RawRunError("%s: %s" % (name, exc))


# compound settings an engine's settings do not carry: the confirmation-ion
# S/N is the qualifiers' floor (_qual_floor), not the quantifier's; the slope
# sensitivity is Adaptive's; the limits on a manual change judge an edit when
# it is made, never a peak the engine finds; the rules for a dropped baseline
# and for the candidates offered are the review's (the candidates' own are
# read by _candidate_floor), and only the edge points are the classic
# engine's own
MANUAL_LIMITS = ("min_manual_change_pct", "min_manual_sn")
# the largest residual of a fit of overlapping peaks, in times the trace's
# baseline noise: the method's, judging a fit when the run is processed
# (_fit_limits), never an engine setting
FIT_LIMITS = ("fit_noise_multiple",)
REVIEW_RULES = ("min_peak_points", "edge_sigma", "drop_valley_max_pct", "skim_ratio_pct",
                "search_amp_sn", "candidate_min_points", "candidate_min_fwhm_pct")
UNUSED_COMPOUND_SETTINGS = {"classic": ("min_qual_sn", "sensitivity", "shoulder_pct", "qual_apex_tol",
                                        "rt_anchor") + MANUAL_LIMITS + FIT_LIMITS + REVIEW_RULES,
                            "adaptive": ("min_qual_sn", "edge_points") + MANUAL_LIMITS + FIT_LIMITS
                            + REVIEW_RULES}


def _fit_limits(a, integration):
    """{"fit_noise_multiple": the method's largest fit residual, in times
    the trace's baseline noise (None when unset: no fit is made), "min_manual_change_pct", "min_manual_sn": the
    limits on a manual change, the compound's own where it sets one, else
    the method's (raw_preview.manual_limits: the change defaults, an unset
    S/N is no limit)}. A fit is judged by them when the run is processed:
    the add-on cannot fit."""
    own = a.get("settings") or {}
    out = {"fit_noise_multiple": integration.get("fit_noise_multiple")}
    defaults = {"min_manual_change_pct": load("raw_preview").DEFAULT_MIN_MANUAL_CHANGE_PCT, "min_manual_sn": None}
    for key in MANUAL_LIMITS:
        value = own.get(key)
        if value is None:
            value = integration.get(key)
        out[key] = defaults[key] if value is None else float(value)
    return out


def _half_width(points):
    """"auto", or the half-width m = (n - 1) / 2 of an odd number of points n, 3 or more."""
    if points == "auto":
        return "auto"
    n = int(points)
    if n < 3 or n % 2 == 0:
        raise ValueError("smoothing is auto or an odd number of points, 3 or more")
    return (n - 1) // 2


def _level_order(inj):
    """A calibrator's level as a number where it is one, so 10 follows 2."""
    level = inj.get("level")
    try:
        return (0, float(level), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(level))


def learn_smoothing(chroms, calibrators, analytes, settings):
    """{analyte: (m, calibrator name)} for each analyte whose adaptive
    smoothing is auto; (None, None) where no calibrator qualifies.

    The m is learnt (raw_adaptive.learn_m) from the median-concentration
    calibrator, ranked by the analyte's stated concentration, among those
    whose quantifier holds a detected peak within its window; of two middle calibrators, or equal concentrations, the lower
    level. An analyte no calibrator states a concentration for (a labelled
    standard at one level) is ranked by level alone; otherwise a calibrator
    stating none is not ranked. With none, each trace uses its own adaptive
    m, the weaker estimate: a rough region beside a small peak can drive it
    too low."""
    mzml = load("raw_mzml")
    out = {}
    for n in sorted(analytes):
        a = analytes[n]
        own = settings_for(a, settings, n)
        if not isinstance(own, ri.AdaptiveSettings) or own.smooth != "auto":
            continue
        key = mzml.transition_key(*a["quant"])
        by_level = not any(_expected(inj, n) for inj in calibrators)
        ranked = []
        for inj in calibrators:
            conc = 0 if by_level else _expected(inj, n)
            if not by_level and not conc:
                continue
            t, y = chroms[inj["name"]][n][key]
            peaks, _m, _sigma = _adaptive_peaks(t, y, own)
            if any(abs(p["rt"] - a["rt"]) <= a["window"] for p in peaks):
                ranked.append((conc, _level_order(inj), inj["name"]))
        out[n] = (None, None)
        if ranked:
            ranked.sort()
            chosen = ranked[(len(ranked) - 1) // 2][2]
            t, y = chroms[chosen][n][key]
            m = raw_adaptive.learn_m(t, y, a["rt"], own.sensitivity, own.min_sn)
            if m is not None:
                out[n] = (m, chosen)
    return out


def _smoothed(settings, smooth):
    """(settings, smoothing_from): an auto smoothing with a learnt (m, source)
    runs at m; with no m, at the trace's own, named after `source`."""
    if not isinstance(settings, ri.AdaptiveSettings) or settings.smooth != "auto" or not smooth:
        return settings, None
    m, source = smooth
    return (settings if m is None else dataclasses.replace(settings, smooth=m)), source


def _adaptive_m(settings):
    """find_peaks's m: None learns it from the trace."""
    return None if settings.smooth == "auto" else int(settings.smooth)


def _adaptive_peaks(t, y, settings, exclude=()):
    """(peaks, m used, sigma) of the adaptive engine over a whole trace, sigma
    the noise every peak's S/N is read against; the `exclude` spans are
    another analyte's."""
    peaks, sigma, m = raw_adaptive.find_peaks(t, y, settings.sensitivity, settings.min_sn,
                                              m=_adaptive_m(settings),
                                              shoulder=settings.shoulder_pct / 100.0, exclude=exclude)
    return peaks, m, sigma


def _adaptive_peak(t, y, p, m, settings, manual=False, pad=None, sigma=None):
    """A Peak from an adaptive peak dict, `sigma` the noise its S/N was read
    against. A fitted area is the method's shape fitted over the found
    edges, as the classic engine fits it, and falls back to the found
    trapezoid as the classic engine's does (raw_integrate.gated_fit)."""
    t, y = np.asarray(t, dtype=float), np.asarray(y, dtype=float)
    area, fit_note = p["area"], None
    if settings.area != "trapezoid":
        s, e = int(np.argmin(abs(t - p["start"]))), int(np.argmin(abs(t - p["end"])))
        apex = int(np.argmin(abs(t - p["rt"])))
        area, fit_note = ri.gated_fit(t, y, s, e, apex, settings, p["area"], pad=pad)
    return ri.Peak(area, p["rt"], p["start"], p["end"], p["base"][0], p["base"][1], p["sn"],
                   ri.area_method(settings, manual, fit_note is not None), True, p.get("note", ""),
                   fwhm_s=p["fwhm_s"], tailing=p["tailing"], plates=p["plates"], smoothing=m,
                   engine="adaptive", fit_note=fit_note, noise=sigma, baseline=p.get("baseline"),
                   levels=p.get("levels"), valley_share=p.get("valley_share"), skim_share=p.get("skim_share"),
                   height=p.get("height"))


def _adaptive_not_detected(settings, m, note, sigma=None):
    return ri.Peak(None, None, None, None, None, None, None, settings.area, False, note,
                   smoothing=m, engine="adaptive", noise=sigma)


def _adaptive_window(t, y, centre, tol, settings, exclude=()):
    """(peaks, m, sigma): the adaptive engine's detected peaks whose apexes
    lie within centre +/- tol, in the finder's order, the smoothing m it
    used and the trace's noise sigma. The nearest peak and the analyst's
    choices are both read here."""
    peaks, m, sigma = _adaptive_peaks(t, y, settings, exclude)
    return [p for p in peaks if abs(p["rt"] - centre) <= tol], m, sigma


def _adaptive_candidate_peaks(t, y, centre, tol, settings, exclude=(), floor=None):
    """The peaks an analyst may choose among in centre +/- tol under the
    adaptive engine, in time order, each a Peak measured as the automatic
    peak is (_adaptive_peak), kept when wide enough
    (raw_integrate.wide_enough on the trace smoothed at the m used, each
    edge level over m points, at `floor`, None for the review's defaults);
    two that share one apex are offered once (raw_integrate.distinct_apexes),
    the automatic peak kept when it is one of them: the peak nearest the
    centre, the first of two equally near, as _adaptive_nearest takes it."""
    near, m, sigma = _adaptive_window(t, y, centre, tol, settings, exclude)
    peaks = [_adaptive_peak(t, y, p, m, settings, sigma=sigma) for p in near]
    auto = min(range(len(near)), key=lambda i: abs(near[i]["rt"] - centre)) if near else None
    auto = peaks[auto] if auto is not None else None
    if peaks:
        t, y = np.asarray(t, dtype=float), np.asarray(y, dtype=float)
        # each edge level over the m points the adaptive baseline reads
        peaks = ri.wide_enough(t, y, raw_adaptive._smooth(y, m), peaks, auto, floor, max(int(m), 1))
    return ri.distinct_apexes(peaks, auto=auto)


def _adaptive_candidates(t, y, centre, tol, settings, exclude=(), floor=None):
    """_adaptive_candidate_peaks, each given as raw_integrate.as_candidate."""
    return [ri.as_candidate(p, t, y) for p in _adaptive_candidate_peaks(t, y, centre, tol, settings, exclude, floor)]


def _choices(t, y, centre, tol, settings, exclude=(), floor=None):
    """The peaks an analyst may choose another apex among, apexes within
    centre +/- tol, in time order, each a Peak measured as the automatic
    peak is, under the trace's engine, each wide enough at `floor` (the
    compound's, _candidate_floor; None for the review's defaults): the one
    code path for the replay of an apex choice and for the candidates kept
    on the trace for review."""
    if isinstance(settings, ri.AdaptiveSettings):
        return _adaptive_candidate_peaks(t, y, centre, tol, settings, exclude, floor)
    return ri.candidate_peaks(t, y, centre, tol, settings, exclude, floor)


# the compound settings that decide which peaks are offered as another apex
CANDIDATE_FLOOR = ("candidate_min_points", "candidate_min_fwhm_pct")


def _candidate_floor(a, rules=None):
    """(fewest points, smallest width in % of the automatic peak's) a
    candidate of the compound `a` is offered at: its own where it sets one,
    else the method's (`rules`, the Integration block's review_rules), else
    the review's defaults (raw_preview.REVIEW_DEFAULTS)."""
    own = a.get("settings") or {}
    rules = rules or {}
    defaults = load("raw_preview").REVIEW_DEFAULTS
    return tuple(own[k] if own.get(k) is not None else rules.get(k, defaults[k]) for k in CANDIDATE_FLOOR)


def _adaptive_nearest(t, y, rt, tol, settings, note, exclude=()):
    """The detected peak whose apex is nearest rt, within rt +/- tol; none
    there is not detected."""
    near, m, sigma = _adaptive_window(t, y, rt, tol, settings, exclude)
    if not near:
        return _adaptive_not_detected(settings, m, note, sigma)
    return _adaptive_peak(t, y, min(near, key=lambda p: abs(p["rt"] - rt)), m, settings, sigma=sigma)


def _adaptive_between(t, y, start, end, settings, m, where, exclude=(), baseline="valley", sigma=None,
                      levels=None, amp=None):
    """A re-integration under the adaptive engine: its measure between the
    analyst's edges, on its `baseline` (raw_adaptive.between) or the
    `levels` set by hand, a drop's or a skim's neighbours rising `amp`
    times the noise, its S/N the height over `sigma` (the automatic call's
    noise; None reads the noise about the span); a fitted area is the
    method's shape fitted to those points."""
    p = raw_adaptive.between(t, y, start, end, m, exclude=exclude, baseline=baseline, sigma=sigma, levels=levels,
                             amp=amp)
    if p is None:
        raise Unapplied(load("raw_review").NOT_MEASURED % (start, end, "the span holds too few points"))
    if sigma is None:
        # the noise between() read its S/N against: its height over that S/N
        sigma = p["height"] / p["sn"] if p["sn"] and math.isfinite(p["sn"]) else None
    return _adaptive_peak(t, y, p, m, settings, manual=True, pad=0, sigma=sigma)


def _partner_span(analytes, name, rt=None):
    """[(t0, t1)]: the isomer partner's time +/- its window less this
    analyte's own time +/- its window, left out of this analyte's noise; []
    without a partner. A partner's window never hides the analyte's own
    peak. Where relative retention moved this analyte's expected time to
    `rt`, the partner's moves by the same factor: both are quantified on one
    labelled standard."""
    a = analytes[name]
    partner = analytes.get(a.get("partner")) if a.get("partner") else None
    if not partner:
        return []
    factor = 1.0 if rt is None else rt / a["rt"]
    centre = partner["rt"] * factor
    own = a["rt"] if rt is None else rt
    p0, p1 = centre - partner["window"], centre + partner["window"]
    o0, o1 = own - a["window"], own + a["window"]
    if o1 <= p0 or o0 >= p1:
        return [(p0, p1)]
    return [(lo, hi) for lo, hi in ((p0, o0), (o1, p1)) if hi > lo]


def _partner_bound(partner_peak):
    """(start, end, apex) of the partner's chosen peak, or None."""
    if partner_peak is None or not partner_peak.detected or partner_peak.start is None:
        return None
    return (partner_peak.start, partner_peak.end, partner_peak.rt)


def _clipped(t, y, p, bound):
    """Peak `p` less the stretch of the partner's peak (`bound`) it reaches
    into: cut at the partner's edge on the peak's own baseline line, the
    area the trapezoid above that line from its start to the cut (or from
    the cut to its end), its other measures and note kept. A baseline end
    read at the cut would sit on the partner's flank. None when too little
    is left."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    start, end = p["start"], p["end"]
    if end > bound[0] and start < bound[0]:
        s = int(np.argmin(abs(t - start)))
        e = int(np.searchsorted(t, bound[0], side="right")) - 1
    elif start < bound[1] and end > bound[1]:
        s = int(np.searchsorted(t, bound[1], side="left"))
        e = int(np.argmin(abs(t - end)))
    else:
        return p
    if e < s + 1:
        return None
    line = [p["start"], p["end"]]
    seg = slice(s, e + 1)
    base = np.interp(t[seg], line, p["base"])
    return dict(p, start=float(t[s]), end=float(t[e]), base=[float(base[0]), float(base[-1])],
                area=max(float(np.trapezoid(y[seg] - base, t[seg])), 0.0))


def _adaptive_summed(t, y, rt, tol, settings, note, exclude=(), bound=None):
    """The detected peaks whose apexes lie within rt +/- tol, less what the
    partner's chosen peak covers (`bound`, its (start, end, apex)): every
    peak with its apex inside those edges is left out, and one reaching into
    them is measured again up to them, so no stretch is counted in both. As
    one peak: the areas summed, from the first one's start to the last one's
    end, timed at the tallest."""
    peaks, m, sigma = _adaptive_peaks(t, y, settings, exclude)
    near = sorted((p for p in peaks if abs(p["rt"] - rt) <= tol), key=lambda p: p["rt"])
    if bound is not None:
        near = [p for p in near if not bound[0] <= p["rt"] <= bound[1]]
        near = [q for q in (_clipped(t, y, p, bound) for p in near) if q is not None]
    if not near:
        return _adaptive_not_detected(settings, m, note, sigma)
    top = max(near, key=lambda p: p["height"])
    notes = []
    for p in near:
        if p.get("note") and p["note"] not in notes:
            notes.append(p["note"])
    # one peak's width and shape are its own; a cluster's are not one peak's
    one = near[0] if len(near) == 1 else {}
    return ri.Peak(sum(p["area"] for p in near), top["rt"], near[0]["start"], near[-1]["end"],
                   near[0]["base"][0], near[-1]["base"][1], max(p["sn"] for p in near), "summed", True,
                   "; ".join(notes), fwhm_s=one.get("fwhm_s"), tailing=one.get("tailing"),
                   plates=one.get("plates"), smoothing=m, engine="adaptive", noise=sigma,
                   height=top["height"])


def _adaptive_group(t, y, rt, tol, settings, note, exclude=()):
    """The touching-peak group (one shared baseline) holding the detected peak
    nearest rt within rt +/- tol, as one peak: the members' areas summed, from
    the group's start to its end, timed at and with the S/N of the tallest
    member."""
    peaks, m, sigma = _adaptive_peaks(t, y, settings, exclude)
    near = [p for p in peaks if abs(p["rt"] - rt) <= tol]
    if not near:
        return _adaptive_not_detected(settings, m, note, sigma)
    seed = min(near, key=lambda p: abs(p["rt"] - rt))
    members = sorted((p for p in peaks if p["group"] == seed["group"]), key=lambda p: p["rt"])
    top = max(members, key=lambda p: p["height"])
    notes = []
    for p in members:
        if p.get("note") and p["note"] not in notes:
            notes.append(p["note"])
    notes.append("summed %d peak%s" % (len(members), "" if len(members) == 1 else "s"))
    one = members[0] if len(members) == 1 else {}
    return ri.Peak(sum(p["area"] for p in members), top["rt"], members[0]["start"], members[-1]["end"],
                   members[0]["base"][0], members[-1]["base"][1], top["sn"], "summed", True,
                   "; ".join(notes), fwhm_s=one.get("fwhm_s"), tailing=one.get("tailing"),
                   plates=one.get("plates"), smoothing=m, engine="adaptive", noise=sigma,
                   height=top["height"])


def _summed_on(t, y, a, partner, settings, rt, exclude, partner_peak):
    """A summed analyte's peak on one of its traces, the quantifier's or a
    qualifier's, so both are integrated alike: with a partner, the peaks in
    its own window less the partner's chosen peak (`partner_peak`); without
    one, the touching group nearest its expected time (Adaptive) or one peak
    across the window (Classic). `settings` are the trace's own, smoothed."""
    if isinstance(settings, ri.AdaptiveSettings):
        note = "no peak above the signal-to-noise of %g in the window" % settings.min_sn
        centre = a["rt"] if rt is None else rt
        if partner is not None:
            return _adaptive_summed(t, y, centre, a["window"], settings, note, exclude,
                                    _partner_bound(partner_peak))
        return _adaptive_group(t, y, centre, a["window"], settings, note, exclude)
    if partner is not None:
        return ri.integrate_cluster(t, y, a["rt"], a["window"], settings, exclude, _partner_bound(partner_peak))
    return ri.integrate_summed(t, y, [a["rt"]], a["window"], settings)


def _peak(traces, analytes, name, settings, smooth=None, rt=None, partner_peak=None):
    """The analyte's quantifier peak. Under Adaptive, `smooth` is its learnt
    (m, source) and `rt` its expected time where relative retention moved it.
    An isomer partner's span is left out of its noise. A summed analyte with
    a partner is the sum of the peaks in its own window, less the partner's
    chosen peak (`partner_peak`), under either engine. Without a partner,
    the adaptive engine sums the touching group nearest its expected time."""
    mzml = load("raw_mzml")
    a = analytes[name]
    settings = settings_for(a, settings, name)
    t, y = traces[mzml.transition_key(*a["quant"])]
    exclude = _partner_span(analytes, name, rt)
    partner = analytes.get(a.get("partner")) if a.get("partner") else None
    if isinstance(settings, ri.AdaptiveSettings):
        settings, source = _smoothed(settings, smooth)
        if a.get("mode") == "summed":
            peak = _summed_on(t, y, a, partner, settings, rt, exclude, partner_peak)
        else:
            # the detected peak nearest the expected time, within its window
            note = "no peak above the signal-to-noise of %g in the window" % settings.min_sn
            peak = _adaptive_nearest(t, y, a["rt"] if rt is None else rt, a["window"], settings, note, exclude)
        peak.smoothing_from = source
        return peak
    # a pair is fitted with its partner, and a summed peak integrated, as signal
    if a.get("mode") == "pair" and partner:
        try:
            return ri.integrate_pair(t, y, a["rt"], partner["rt"], a["window"], settings, exclude)[0]
        except (RuntimeError, ValueError):
            # a pair fit that fails: the analyte's own peak, its partner's
            # span left out of the noise
            peak = ri.integrate_excluding(t, y, a["rt"], a["window"], settings, exclude)
            peak.fit_note = PAIR_FIT_FAILED + ("; " + peak.fit_note if peak.fit_note else "")
            return peak
    if a.get("mode") == "summed":
        return _summed_on(t, y, a, partner, settings, rt, exclude, partner_peak)
    if exclude:
        return ri.integrate_excluding(t, y, a["rt"], a["window"], settings, exclude)
    return ri.integrate(t, y, a["rt"], a["window"], settings)


ANCHOR_NOT_FOUND = "anchor not found"
RESUMMED = "re-summed beside the re-integrated linear peak"
RESUMMED_PROCESSED = "re-summed beside the processed linear peak"
RESUMMED_FITTED = "re-summed beside the fitted linear peak"
PAIR_FIT_FAILED = "pair fit failed"


def _edits(overrides, analytes, peaks):
    """({(injection, analyte): edit} of the quantifiers, {(injection,
    analyte): {transition label: edit}} of the qualifiers): the run's
    overrides read through the add-on's record (raw_review.edit_of), a v1
    record (edges only) as a re-integration; a record without a version
    (v1, v2) is marked "legacy". A key naming the quantifier's
    own transition is the quantifier's. A key or record that cannot be
    read, a transition the analyte does not have, or two keys for one
    quantifier refuse the run, naming the key; so does a trace the run
    does not hold."""
    review = load("raw_review")
    quant, quals, keys = {}, {}, {}
    for key in sorted(overrides):
        try:
            inj, n, label = review.parse_edit_key(key)
            edit = review.edit_of(overrides[key])
        except ValueError as exc:
            raise RawRunError("The edit %s cannot be replayed: %s" % (key, exc))
        if isinstance(overrides[key], dict) and overrides[key].get("version") is None:
            # an unversioned record is not judged by the fewest points (_replay)
            edit["legacy"] = True
        if (inj, n) not in peaks:
            raise RawRunError("An edit names %s / %s, which this run does not hold" % (inj, n))
        a = analytes[n]
        if label is None or label == _label(a["quant"]):
            if (inj, n) in quant:
                raise RawRunError("The edits %s and %s both name %s / %s's quantifier"
                                  % (keys[(inj, n)], key, inj, n))
            quant[(inj, n)], keys[(inj, n)] = edit, key
        elif label in [_label(q) for q in a.get("quals") or []]:
            quals.setdefault((inj, n), {})[label] = edit
        else:
            raise RawRunError("The edit %s cannot be replayed: %s has no transition %s" % (key, n, label))
    return quant, quals


def _deleted(auto):
    """The automatic peak deleted by the analyst: not detected, with no
    area, time, edges, S/N or processing change; its engine and smoothing
    kept."""
    return dataclasses.replace(auto, area=None, rt=None, start=None, end=None, base_start=None, base_end=None,
                               sn=None, detected=False, note=PEAK_DELETED, fwhm_s=None, tailing=None,
                               plates=None, fit_note=None, processing=None, processing_skipped=None, fit=None)


# how a manual peak's area is measured: the trapezoid of the raw signal
# above the line the analyst chose, whatever the method's area measure (a
# fitted shape is the automatic peaks' measure)
MANUAL_LINE_AREA = "trapezoid, manual line"


def _review_rules(a):
    """The compound's rules for a manual peak (method_profiles stores them
    as its "review"), the review's defaults where none is stored."""
    return dict(load("raw_preview").REVIEW_DEFAULTS, **(a.get("review") or {}))


def _search_time(a, rt):
    """The time a compound's peak is searched about in one injection: the
    one relative retention moved it to (_expected_rt), else its configured
    time."""
    return a["rt"] if rt is None else rt


def _span_points(t, start, end):
    """The samples between the edges, both included, each edge on its
    nearest sample: as the review counts them on the stored trace."""
    tt = np.asarray(t, dtype=float)
    return int(np.argmin(abs(tt - end))) - int(np.argmin(abs(tt - start))) + 1


def _fit(t, y, start, end, apexes, shape, pick, limit, noise, refuse, min_sn=None, alone=False):
    """The component `pick` (the index among `apexes`, fixed before the
    fit, never chosen again from where the fitted peaks fell) of the fit of
    overlapping peaks over [start, end] (raw_integrate.fit_peaks,
    fitted_peak), or `refuse(why)` raised: no fit limit set
    (FIT_NO_LIMIT_TEXT), a fit the engine refuses (FitRefused: one that
    did not converge or collapsed, or why it cannot be made), or one
    fit_problem refuses: its residual's RMS over `limit` times the trace's
    baseline `noise` (the noise its S/N is read against), the picked
    area's resampled interval wider than the area. Under the engine's
    detection floor `min_sn` the peak reads not detected."""
    review = load("raw_review")
    if limit is None:
        raise refuse(review.FIT_NO_LIMIT_TEXT)
    try:
        result = ri.fit_peaks(t, y, start, end, apexes, shape, alone=alone)
    except ValueError as exc:                 # FitRefused is a ValueError
        raise refuse(str(exc))
    problem = ri.fit_problem(result, pick, float(limit), noise)
    if problem:
        raise refuse(problem)
    return ri.fitted_peak(result, pick, apexes, noise, float(limit), min_sn)


# why the fitted shapes are left unscored without a method fit limit
NOT_TRIED_NO_LIMIT = "not tried: no fit limit"
# a fit scored but over the method's fit limit: its residual check fails
OVER_FIT_LIMIT = "the fit leaves %.1f times the noise, over the method's fit limit of %g"


def _clean(value):
    """`value` with every float finite (_finite), through lists and dicts, so
    the record is JSON."""
    if isinstance(value, float):
        return _finite(value)
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _clean(v)) for k, v in value.items())
    return value


def _fit_residual_noise(result, noise):
    """The fit's residual RMS over the baseline noise, the figure _fit
    judges (raw_integrate.noise_multiple); None without a noise."""
    return ri.noise_multiple(result, noise)


def _score_settings(settings, found):
    """The classic settings a candidate is measured under: the trace's own,
    or, for the adaptive engine, a window of the peak's smoothing with
    the engine's edge points."""
    if isinstance(settings, ri.AdaptiveSettings):
        m = found.smoothing if found.smoothing is not None else _adaptive_m(settings)
        m = 2 if m is None else max(int(m), 1)
        return ri.Settings(smooth_points=max(2 * m + 1, 5), baseline="valley", area="trapezoid",
                           min_sn=settings.min_sn, edge_points=max(m, 1))
    return dataclasses.replace(settings, area="trapezoid")


def _scored(t, y, method, start, end, apex, base_start, base_end, height, sn, noise, min_sn,
            residual_noise=None):
    """peak_score.score of one candidate (edges and apex in minutes), with
    the edges and baseline levels it was scored on. The checks carry their
    key and points only: a label is read from peak_limits on display."""
    tt = np.asarray(t, dtype=float)
    factor, _why = peak_asymmetry.measure(tt, y, apex, start, end, base_start, base_end)
    got = peak_score.score(tt, y, {
        "method": method, "start": int(np.argmin(abs(tt - start))), "end": int(np.argmin(abs(tt - end))),
        "apex_i": int(np.argmin(abs(tt - apex))), "base_start": base_start, "base_end": base_end,
        "height": height, "asymmetry": factor, "sn": sn, "residual_noise": residual_noise}, noise, min_sn)
    return {"method": got["method"], "score": got["score"],
            "checks": [dict((k, c[k]) for k in ("key", "points", "max", "ok")) for c in got["checks"]],
            "start": start, "end": end, "base_start": base_start, "base_end": base_end}


def _scored_fit(t, y, peak, shape, limit, noise, min_sn):
    """One apex fitted under `shape` over the automatic peak's own edges,
    scored there like the baseline candidates: the fit's line gives the
    baseline levels, its component the height and apex. The fit is a point
    estimate, never kept; judged on its residual alone (the interval is the
    applied fit's). A residual over the method's fit limit still scores, its
    residual check failing, with the reason as the note."""
    result = ri.fit_peaks(t, y, peak.start, peak.end, [peak.rt], shape, resamples=0, alone=True)
    comp = result.components[0]
    tt = np.asarray(t, dtype=float)
    s, e = int(np.argmin(abs(tt - peak.start))), int(np.argmin(abs(tt - peak.end)))
    base = [result.b0 + result.b1 * (float(tt[i]) - result.t0) for i in (s, e)]
    multiple = _fit_residual_noise(result, noise)
    note, residual = None, multiple
    if multiple is None:
        note = ri.FIT_NO_NOISE
    elif not multiple <= limit:
        note, residual = OVER_FIT_LIMIT % (multiple, limit), None
    got = _scored(t, y, shape, peak.start, peak.end, comp.apex, base[0], base[1], comp.height,
                  ri._sn(comp.height, noise) if noise is not None else None, noise, min_sn, residual)
    if note:
        got["note"] = note
    return got


def _fit_scores(t, y, peak, settings, limits, labelled, amp=None):
    """The automatic peak scored under each of peak_limits.METHODS, in that
    order, all on its own edges: [{"method", "score", "checks", "start",
    "end", "base_start", "base_end"[, "note"]} or {"method", "score": None,
    "note"}]. Valley, drop, flat and skim are measured between the edges
    (raw_integrate.integrate_between); Gaussian and EMG are one apex fitted
    over them (_scored_fit). A fit is left unscored with no fit limit set,
    and a labelled compound has no fitted candidate at all. A candidate the
    engine refuses, or that cannot be scored, has no score, its reason as
    the note, and never stops the run. The score reads no QC outcome."""
    limits_mod = load("peak_limits")
    line = _score_settings(settings, peak)
    noise, min_sn = peak.noise, settings.min_sn
    out = []
    for method in limits_mod.METHODS:
        fitted = method in ("gaussian", "emg")
        if fitted and labelled:
            continue
        limit = (limits or {}).get("fit_noise_multiple")
        if fitted and limit is None:
            out.append({"method": method, "score": None, "note": NOT_TRIED_NO_LIMIT})
            continue
        try:
            if fitted:
                out.append(_scored_fit(t, y, peak, method, float(limit), noise, min_sn))
                continue
            cand = ri.integrate_between(t, y, peak.start, peak.end, ri.with_baseline(line, method),
                                        noise=noise, amp=amp)
            out.append(_scored(t, y, method, cand.start, cand.end, cand.rt, cand.base_start, cand.base_end,
                               cand.height, cand.sn, noise, min_sn))
        except Exception as exc:       # one candidate's failure leaves the rest and the run
            out.append({"method": method, "score": None, "note": str(exc) or exc.__class__.__name__})
    return out


def _drop_rt(peak, t, neighbours, adaptive=False):
    """The edge a drop baseline shares with a neighbouring peak, in minutes:
    the start where a neighbour ends there, the end where one starts there,
    within one sample; None for any other baseline or no such neighbour. The
    adaptive engine's own peaks are split from the group they touch by drop
    lines, so an automatic one (`adaptive`, no baseline of its own) has the
    edge it shares with a neighbour; a manual peak only on a drop baseline.
    `neighbours` are the (start, end) of the other peaks."""
    if peak is None or not peak.detected or peak.start is None:
        return None
    if not (peak.baseline == "drop" or (adaptive and peak.baseline is None)):
        return None
    tt = np.asarray(t, dtype=float)
    tol = float(np.median(np.diff(tt))) if len(tt) > 1 else 0.0
    for n_start, n_end in neighbours:
        if abs(n_end - peak.start) <= tol:
            return peak.start
        if abs(n_start - peak.end) <= tol:
            return peak.end
    return None


def _fit_edit(edit, auto, t, y, a, where, limits, min_sn=None):
    """The peak an analyst's fit of overlapping peaks makes (_replay, kind
    fit), kept with no effect (Unapplied) on an isotope standard, with
    fewer samples than the compound's fewest points in a peak or than the
    fit is made over, for any refusal of _fit, or under the smallest manual
    change or the manual S/N floor (raw_preview.edit_problem: the fitted
    area against the automatic peak's, its height over the automatic call's
    noise). Under the engine's detection floor (`min_sn`) the fitted peak
    reads not detected. The add-on refuses what it can see before writing;
    the fit itself is made here."""
    review = load("raw_review")
    if a.get("labelled"):
        raise Unapplied(review.FIT_LABELLED_TEXT % where)
    start, end, shape = edit["start"], edit["end"], edit["shape"]
    points = _span_points(t, start, end)
    fewest = max(int(_review_rules(a)["min_peak_points"]), review.fit_fewest(shape, len(edit["apexes"])))
    if points < fewest:
        raise Unapplied(review.TOO_FEW_POINTS % (fewest, points))
    peak = _fit(t, y, start, end, edit["apexes"], shape, edit["pick"], limits.get("fit_noise_multiple"),
                auto.noise, Unapplied, min_sn, alone=bool(edit.get("alone")))
    problem = load("raw_preview").edit_problem("fit", auto.area, peak.area, peak.sn,
                                               limits.get("min_manual_change_pct"), limits.get("min_manual_sn"))
    if problem:
        raise Unapplied(problem)
    return dataclasses.replace(peak, engine=auto.engine, smoothing=auto.smoothing,
                               smoothing_from=auto.smoothing_from)


def _replay(edit, auto, t, y, settings, a, where, exclude, choices=None, limits=None):
    """The peak the analyst's edit makes of one trace, whose automatic peak
    is `auto`, under `settings` (the automatic call's own):
      delete     not detected (_deleted);
      integrate  measured between the analyst's edges, on the edit's
                 baseline or the method's and the edit's levels where set
                 by hand (Classic integrate_between; Adaptive between, at
                 the automatic peak's smoothing): valley to valley, a
                 perpendicular drop over the pair (its outer edges found
                 from the neighbours rising the compound's peak search
                 amplitude times the automatic call's noise), flat at the
                 lower edge level or a tangent skim; levels set by hand
                 replace the levels the line reads. Its area is the
                 trapezoid above the line (MANUAL_LINE_AREA). Kept with no
                 effect (Unapplied): levels outside the trace's range
                 (raw_review.levels_outside), fewer samples between the
                 edges than the compound's fewest points in a peak
                 (min_peak_points; not for a "legacy" record), a span the
                 engine cannot measure;
      apex       of `choices`, the trace's candidates found as the automatic
                 peak was, the one whose own apex is nearest the chosen
                 one, within half the local sample spacing
                 (raw_review.nearest_apex): as measured, or with the
                 edit's baseline measured again over its own edges, as a
                 re-integration's line is. Only a single peak may have
                 another apex chosen; a chosen apex two candidates' are
                 equally near refuses the run; one no candidate's is that
                 near is kept with no effect (Unapplied);
      fit        the component picked of the chosen shape fitted at each
                 apex clicked over the edges (_fit_edit), judged by the
                 method's fit limit and the manual-change limits in
                 `limits` (_fit_limits)."""
    kind = edit["kind"]
    if kind == "delete":
        return _deleted(auto)
    if kind == "fit":
        return _fit_edit(edit, auto, t, y, a, where, limits or {}, settings.min_sn)
    adaptive = isinstance(settings, ri.AdaptiveSettings)
    baseline = edit.get("baseline")
    if kind == "apex":
        mode = a.get("mode") or "single"
        if mode != "single":
            raise RawRunError("Another apex is chosen only on a single peak: %s is %s" % (where, mode))
        review = load("raw_review")
        choices = list(choices or [])
        try:
            i = review.nearest_apex([p.rt for p in choices], edit["apex"],
                                    review.apex_tolerance(t, edit["apex"]))
        except ValueError:
            raise RawRunError("The apex chosen for %s at %.2f min is shared by two peaks in its window"
                              % (where, edit["apex"]))
        if i is None:
            raise Unapplied(review.NO_LONGER_A_PEAK)
        chosen = choices[i]
        if baseline is None:
            return dataclasses.replace(chosen, smoothing_from=auto.smoothing_from, method=ri.area_method(
                settings, manual=True, refused=chosen.fit_note is not None))
        start, end = chosen.start, chosen.end
    else:
        start, end = edit["start"], edit["end"]
        review = load("raw_review")
        why = review.levels_outside(y, edit.get("levels"))
        if why:
            raise Unapplied(why)
        # the samples between the edges, both included, each edge on its
        # nearest sample: as the review counts them on the stored trace
        tt = np.asarray(t, dtype=float)
        points = int(np.argmin(abs(tt - end))) - int(np.argmin(abs(tt - start))) + 1
        fewest = int(_review_rules(a)["min_peak_points"])
        if points < fewest and not edit.get("legacy"):
            raise Unapplied(review.TOO_FEW_POINTS % (fewest, points))
    # a manual peak's S/N is its height over the automatic call's noise: the
    # S/N the edit was judged on in review (raw_preview) is the one recorded;
    # a drop's or a skim's neighbours rise the compound's peak search
    # amplitude above their valley, as the review read them; its area is the
    # trapezoid above the line, as the review previewed it
    amp = _review_rules(a)["search_amp_sn"]
    line = dataclasses.replace(settings, area="trapezoid")
    if adaptive:
        # at the automatic peak's smoothing, which its window's candidates share
        peak = _adaptive_between(t, y, start, end, line, auto.smoothing, where, exclude, baseline or "valley",
                                 auto.noise, edit.get("levels"), amp)
        return dataclasses.replace(peak, smoothing_from=auto.smoothing_from, method=MANUAL_LINE_AREA)
    try:
        peak = ri.integrate_between(t, y, start, end, ri.with_baseline(line, baseline), exclude, auto.noise,
                                    edit.get("levels"), amp=amp)
    except ValueError as exc:
        raise Unapplied(load("raw_review").NOT_MEASURED % (start, end, exc))
    return dataclasses.replace(peak, method=MANUAL_LINE_AREA)


def _processed(rec, auto, t, y, settings, a, where, exclude, kept=None, limits=None, expected=None):
    """The peak a processing change (raw_review.processing_of: one trace's
    change applied to every injection) makes of one injection's trace,
    whose automatic peak is `auto`, under `settings` (the automatic call's
    own):
      integrate  measured between the injection's own apex plus the
                 change's start and end offsets, on its baseline and the
                 method's own area measure (Classic integrate_between;
                 Adaptive between, at the automatic peak's smoothing), its
                 S/N over the automatic call's noise, a drop's or a skim's
                 neighbours rising the compound's peak search amplitude
                 times that noise, as a manual peak's;
      fit        the change's shape fitted at the injection's `expected`
                 time (the time its peak is searched about, after any
                 relative-retention shift) plus each of its apex offsets,
                 over that time plus the start and end offsets (_fit),
                 the component the change's pick names reported (the
                 click nearest the expected time, fixed when the change
                 was made): a MAJOR processing change. Placed from the
                 expected time, never the automatic apex, so a taller
                 interference does not carry the fit. An isotope standard
                 is never fitted; no expected time (SKIP_NO_TIME), an
                 unset fit limit (in `limits`, _fit_limits), a fit the
                 engine refuses (one collapsed among them), a residual
                 over the limit or an interval wider than the area is
                 skipped (Skipped) with its reason, as are fewer samples
                 than the fit is made over (raw_review.fit_fewest:
                 SKIP_FEW_POINTS); a fitted peak under the engine's
                 detection floor reads not detected.
    A processing change is not an analyst's edit: the smallest manual change
    and the manual S/N floor never judge it, and the peak it makes is
    automatic, its area named by the method's measure. The hard limits do
    judge it: an injection that cannot take it raises Skipped and keeps its
    automatic peak, for no detected apex to place the edges on
    (SKIP_NO_APEX), an edge more than half a sample past either end of the
    trace (SKIP_OUTSIDE), fewer samples between the edges than the
    compound's fewest points in a peak or than the engine measures
    (SKIP_FEW_POINTS), or a drop or a skim whose neighbours read past what
    the stored trace holds at full resolution (SKIP_REACH; `kept(peak)`
    gives those times [t0, t1] for the peak, as _keep_trace stores it; None
    judges nothing). Any other refusal of the engine refuses the run with
    its reason. The peak's change names who applied it and when."""
    review = load("raw_review")
    if rec["kind"] == "fit":
        if a.get("labelled"):
            raise Skipped(review.FIT_LABELLED_TEXT % where)
        if expected is None:
            raise Skipped(review.SKIP_NO_TIME)
        anchor = expected
    elif not auto.detected or auto.rt is None:
        raise Skipped(review.SKIP_NO_APEX)
    else:
        anchor = auto.rt
    start, end = anchor + rec["start_offset"], anchor + rec["end_offset"]
    tt = np.asarray(t, dtype=float)
    # an edge is placed on its nearest sample: one more than half a sample
    # past an end of the trace has none, and is not moved onto the end
    if len(tt) < 2 or start < tt[0] - (tt[1] - tt[0]) / 2 or end > tt[-1] + (tt[-1] - tt[-2]) / 2:
        raise Skipped(review.SKIP_OUTSIDE)
    # the samples between the edges, both included, each edge on its nearest
    # sample: as a manual peak's are counted, against the fewest the
    # engine measures (raw_review.ENGINE_FEWEST)
    adaptive = isinstance(settings, ri.AdaptiveSettings)
    points = int(np.argmin(abs(tt - end))) - int(np.argmin(abs(tt - start))) + 1
    fewest = review.ENGINE_FEWEST["adaptive" if adaptive else "classic"]
    if rec["kind"] == "fit":
        fewest = max(fewest, review.fit_fewest(rec["shape"], len(rec["apex_offsets"])))
    if points < max(int(_review_rules(a)["min_peak_points"]), fewest):
        raise Skipped(review.SKIP_FEW_POINTS)
    stamp = [(k, rec[k]) for k in ("by", "at", "from") if rec.get(k)]
    if rec["kind"] == "fit":
        apexes = [anchor + off for off in rec["apex_offsets"]]
        peak = _fit(t, y, start, end, apexes, rec["shape"], rec["pick"], (limits or {}).get("fit_noise_multiple"),
                    auto.noise, Skipped, settings.min_sn, alone=bool(rec.get("alone")))
        # a detected fitted peak drops the automatic call's note (such as no
        # peak above the floor); one under the floor says so itself
        return dataclasses.replace(
            peak, engine=auto.engine, smoothing=auto.smoothing, smoothing_from=auto.smoothing_from,
            processing=dict([(k, rec[k]) for k in ("kind", "start_offset", "end_offset", "shape", "apex_offsets",
                                                     "pick", "alone") if rec.get(k) is not None] + [("expected", anchor)] + stamp))
    baseline = rec["baseline"]
    amp = _review_rules(a)["search_amp_sn"]
    try:
        if adaptive:
            peak = _adaptive_between(t, y, start, end, settings, auto.smoothing, where, exclude, baseline,
                                     auto.noise, None, amp)
        else:
            peak = ri.integrate_between(t, y, start, end, ri.with_baseline(settings, baseline), exclude,
                                        auto.noise, amp=amp)
    except ValueError as exc:
        raise RawRunError("%s: the processing change cannot be measured: %s" % (where, exc))
    if baseline in ("drop", "skim") and kept is not None and auto.noise is not None:
        region = kept(peak)
        reach = _reach(settings, auto, y)
        if region is not None and reach is not None:
            margin = _engine_fields(settings, auto)[1]
            r0, r1 = reach(int(np.argmin(abs(tt - peak.start))), int(np.argmin(abs(tt - peak.end))))
            if tt[max(r0 - margin, 0)] < region[0] or tt[min(r1 + margin, len(tt) - 1)] > region[1]:
                raise Skipped(review.SKIP_REACH)
    return dataclasses.replace(
        peak, method=ri.area_method(settings, refused=peak.fit_note is not None), note=auto.note,
        smoothing_from=auto.smoothing_from,
        processing=dict([("kind", rec["kind"]), ("start_offset", rec["start_offset"]),
                         ("end_offset", rec["end_offset"]), ("baseline", baseline)] + stamp))


def _processed_or_skipped(rec, auto, t, y, settings, a, where, exclude, kept=None, limits=None, expected=None):
    """_processed's peak, or the automatic peak marked with why this
    injection did not take the change."""
    try:
        return _processed(rec, auto, t, y, settings, a, where, exclude, kept, limits, expected)
    except Skipped as exc:
        return dataclasses.replace(auto, processing_skipped=str(exc))


def _region_of(xy, settings, a, rt, search, choices):
    """A function of a processed peak giving the times its trace, stored as
    _keep_trace stores it, holds at full resolution: the peak's span first,
    then its window about `rt` (the expected time searched; None the
    configured one), the span `search`ed and the candidates offered beside
    it (`choices()`, read only when asked, so the result is the same
    whether or not the run's traces are kept)."""
    centre = a["rt"] if rt is None else rt

    def region(peak):
        found = choices()
        offered = _offered(found, peak)[0] if found else ()
        window = (centre - a["window"], centre + a["window"])
        return _kept(xy, settings, peak, _stored_spans(window, peak, None, search, offered))[3]
    return region


def _quant_choices(t, y, a, searched, own, smooth, exclude, rules=None):
    """A quantifier's candidates (_choices), found as its automatic peak
    was: about its expected time (`searched` where relative retention moved
    it), within its window, at its compound settings and smoothing, its
    partner's span left out, at its candidate floor (_candidate_floor over
    the method's `rules`); None for a row that is not a single peak."""
    if (a.get("mode") or "single") != "single":
        return None
    centre = a["rt"] if searched is None else searched
    return _choices(t, y, centre, a["window"], _smoothed(own, smooth)[0], exclude, _candidate_floor(a, rules))


def _expected_rt(peaks, inj, analytes, name, settings, surrogate_map, composites=None):
    """(expected time or None for the configured one, note or None). Under
    relative retention a native is expected at its configured time times its
    quantitation standard's found apex over that standard's configured time;
    a labelled standard, or a native with no quantitation standard, at its
    configured time; a standard not detected in the injection leaves the
    configured time and the note "anchor not found". A composite anchors on
    its first member found, in its members' order (`composites`: {id:
    [members]})."""
    a = analytes[name]
    own = settings_for(a, settings, name)
    if not isinstance(own, ri.AdaptiveSettings) or own.rt_anchor != "labelled" or a.get("labelled"):
        return None, None
    anchor = surrogate_map.get(name)
    if not anchor:
        return None, None
    for std in (composites or {}).get(anchor) or [anchor]:
        found = peaks.get((inj, std))
        if std in analytes and found is not None and found.detected and found.rt is not None:
            return a["rt"] * found.rt / analytes[std]["rt"], None
    return None, ANCHOR_NOT_FOUND


def _qual_floor(a, settings, confirm_min):
    """The S/N a qualifier is found at: the compound's qualifier detection
    S/N, else the method's confirmation limit, else the smallest S/N. It
    decides only whether the qualifier is found; N.C. is judged against the
    method's confirmation limit alone."""
    own = (a.get("settings") or {}).get("min_qual_sn")
    floor = own if own is not None else confirm_min
    return settings.min_sn if floor is None else float(floor)


def _qual_peaks(traces, analytes, name, peak, settings, smooth=None, confirm_min=None, rt=None,
                edits=None, autos=None, where=None, review=None, rules=None, unapplied=None,
                partner_peak=None, processing=None, limits=None):
    """[(transition, qualifier peak or None)]: each qualifier integrated at
    the quantifier's apex (None when the quantifier has no peak); a summed
    analyte's qualifier is summed as its quantifier is, over the same group
    or window beside the same partner peak (`partner_peak`, _summed_on),
    unless the analyst's edit splits it. Each is read at the
    analyte's learnt smoothing under Adaptive, found down to its own floor
    (_qual_floor; `confirm_min` is the method's confirmation limit), with an
    isomer partner's span left out of its noise (`rt` as for _peak).

    `edits` {transition label: edit} are the analyst's edits of the
    qualifiers, replayed (_replay) with the automatic qualifier's own
    parameters: centred on the quantifier's apex, at the qualifier's floor
    and window (Classic) or apex tolerance and smoothing (Adaptive). Each
    edited qualifier's automatic peak is put in `autos`; an edit the run
    cannot apply (Unapplied) leaves the automatic peak, and its reason goes
    in `unapplied` by transition label. A qualifier is read only beside a
    quantifier peak: with none, its edit has nothing to act on.

    `review`, when given, receives {transition label: (its settings, its
    candidates or None, the (t0, t1) it was searched in or None)}, for the
    trace kept for review; the candidates are the ones an apex choice is
    replayed among, of a single peak only, at the compound's candidate
    floor (_candidate_floor over the method's `rules`), and a qualifier not
    read has neither.

    `processing` {transition label: change} are the run's processing
    changes of the qualifiers ("Apply to all"), each applied (_processed)
    to the qualifier's automatic peak on its own apex before its edit is
    replayed, so an edit keeps its manual peak over the processed one; an
    injection that cannot take a change keeps the automatic peak, marked
    with why. `limits` judge a fit (_fit_limits)."""
    mzml = load("raw_mzml")
    out = []
    a = analytes[name]
    settings = settings_for(a, settings, name)
    adaptive = isinstance(settings, ri.AdaptiveSettings)
    settings, source = _smoothed(settings, smooth)
    settings = dataclasses.replace(settings, min_sn=_qual_floor(a, settings, confirm_min))
    exclude = _partner_span(analytes, name, rt)
    single = (a.get("mode") or "single") == "single"
    partner = analytes.get(a.get("partner")) if a.get("partner") else None
    for q in a.get("quals") or []:
        qp = None
        if review is not None:
            review[_label(q)] = (settings, None, None)
        if peak.detected and peak.area:
            t, y = traces[mzml.transition_key(*q)]
            # a qualifier is sought about the quantifier's apex, within the
            # apex tolerance (Adaptive) or the analyte's window (Classic)
            tol = settings.qual_apex_tol if adaptive else a["window"]
            if a.get("mode") == "summed":
                qp = _summed_on(t, y, a, partner, settings, rt, exclude, partner_peak)
                if adaptive:
                    qp.smoothing_from = source
            elif adaptive:
                # the qualifier is the detected peak within the apex
                # tolerance of the quantifier's apex
                qp = _adaptive_nearest(t, y, peak.rt, settings.qual_apex_tol, settings,
                                       "no peak within %g min of the quantifier apex" % settings.qual_apex_tol,
                                       exclude)
                qp.smoothing_from = source
            else:
                qp = ri.integrate_excluding(t, y, peak.rt, a["window"], settings, exclude)
            edit = (edits or {}).get(_label(q))
            choices = None
            if single and (review is not None or (edit is not None and edit["kind"] == "apex")):
                choices = _choices(t, y, peak.rt, tol, settings, exclude, _candidate_floor(a, rules))
            if review is not None:
                review[_label(q)] = (settings, choices, (peak.rt - tol, peak.rt + tol))
            change = (processing or {}).get(_label(q))
            if change is not None:
                qp = _processed_or_skipped(
                    change, qp, t, y, settings, a, "%s, qualifier %s" % (where or name, _label(q)), exclude,
                    _region_of((t, y), settings, a, rt, (peak.rt - tol, peak.rt + tol),
                               functools.partial(_choices, t, y, peak.rt, tol, settings, exclude,
                                                 _candidate_floor(a, rules)) if single else lambda: None),
                    limits, _search_time(a, rt))
            if edit is not None:
                try:
                    made = _replay(edit, qp, t, y, settings, a, "%s, qualifier %s" % (where or name, _label(q)),
                                   exclude, choices if edit["kind"] == "apex" else None, limits)
                except Unapplied as exc:
                    if unapplied is not None:
                        unapplied[_label(q)] = str(exc)
                else:
                    if autos is not None:
                        autos[_label(q)] = qp
                    qp = made
        out.append((q, qp))
    return out


def _ion_ratios(quals, peak, deleted=()):
    """Each qualifier's area over the quantifier's, "uncalculable" for one
    not found. A qualifier whose peak the analyst deleted (`deleted`, its
    transition labels) leaves its place empty, so the ratio is judged on the
    qualifiers left; none left is no ratio."""
    if not quals or not peak.detected or not peak.area:
        return None
    parts = ["" if _label(q) in deleted
             else "%.6g" % (qp.area / peak.area) if qp is not None and qp.detected else "uncalculable"
             for q, qp in quals]
    return "|".join(parts) if any(parts) else None


def _qual_sn(quals, deleted=()):
    """The S/N of the first qualifier still present (the first is the ion
    the expected ion ratio describes); one the analyst deleted (`deleted`,
    its transition labels) is passed over, and with none left, or without a
    qualifier or a quantifier peak, there is none. An adaptive qualifier not
    found beside a detected quantifier is 0.0, so the confirmation limit
    judges it. A deletion is judged on its own marker (qual_deleted)."""
    left = [qp for q, qp in quals or [] if _label(q) not in deleted]
    if not left or left[0] is None:
        return None
    qp = left[0]
    if qp.engine == "adaptive" and not qp.detected:
        return 0.0
    return _finite(qp.sn)


def _finite(v):
    """A number JSON and the review page can carry: an unbounded S/N is none."""
    return v if v is None or math.isfinite(v) else None


def _peak_record(a, peak, revision):
    rec = {"window": [a["rt"] - a["window"], a["rt"] + a["window"]], "apex": peak.rt,
           "start": peak.start, "end": peak.end, "base_start": peak.base_start,
           "base_end": peak.base_end, "area": peak.area, "area_method": peak.method,
           "sn": _finite(peak.sn), "note": peak.note, "settings_revision": revision}
    # the adaptive engine's measures are written only when present: a
    # classic record carries none
    for key in ("fwhm_s", "tailing", "plates", "smoothing", "smoothing_from", "engine", "fit_note"):
        value = getattr(peak, key)
        if value is not None:
            rec[key] = _finite(value) if isinstance(value, float) else value
    # the asymmetry factor of any engine's peak, or why it has none
    for key in ("asymmetry", "asymmetry_note"):
        value = getattr(peak, key)
        if value is not None:
            rec[key] = _finite(value) if isinstance(value, float) else value
    # the height over the baseline, the drop line's shared edge, the
    # baseline's levels and valley share, and the peak scored under each
    # fitting method: written only when present, so an older record reads
    for key in ("height", "valley_share", "levels", "drop_rt", "fit_scores"):
        value = getattr(peak, key)
        if value is not None:
            rec[key] = _clean(value)
    # a change applied to every injection: the change the peak was measured
    # by, or why this injection kept its automatic peak (_processed)
    for key in ("processing", "processing_skipped"):
        value = getattr(peak, key)
        if value is not None:
            rec[key] = value
    # a fitted peak: the fit it was separated by, so its value can be reproduced
    if peak.fit is not None:
        rec["fit"] = peak.fit
    return rec


# why a summed peak has no asymmetry factor: its area spans several peaks
SUMMED_NO_FACTOR = "a summed peak has no single apex"


def _with_asymmetry(peak, xy, a):
    """The peak with its asymmetry factor (peak_asymmetry, EPA 537.1
    §9.3.9) read on its quantifier trace `xy` above its own baseline, or
    the reason it has none; a peak not detected is returned as it is."""
    if not peak.detected or peak.rt is None:
        return peak
    if a.get("mode") == "summed":
        return dataclasses.replace(peak, asymmetry=None, asymmetry_note=SUMMED_NO_FACTOR)
    factor, why = peak_asymmetry.measure(xy[0], xy[1], peak.rt, peak.start, peak.end,
                                         peak.base_start, peak.base_end)
    return dataclasses.replace(peak, asymmetry=factor, asymmetry_note=why)


def _line_of(edit, peak):
    """The line a replayed edit measured its peak on, {"baseline",
    "levels"?}: the peak's own (the edit's, else the method's), with the
    levels set by hand; {} for a deletion or another apex as found."""
    # a fit is measured on its own fitted line, kept in its record
    if (edit["kind"] in ("delete", "fit") or (edit["kind"] == "apex" and not edit.get("baseline"))
            or peak is None):
        return {}
    out = {"baseline": peak.baseline or edit.get("baseline")}
    if peak.levels is not None:
        out["levels"] = list(peak.levels)
    return out


def _unapplied_record(edit, why):
    """An edit kept with no effect, as a row's record names it."""
    return dict([(k, edit[k]) for k in ("kind", "start", "end", "apex", "baseline", "levels", "shape", "apexes",
                                        "pick", "alone", "by", "at")
                 if edit.get(k) is not None] + [("why", why)])


def _provenance(a, peak, revision, auto=None, override=None, quant=None, file_transition=None,
                qual_edits=None, qual_deleted=None, unapplied=None, qual_processing=None):
    rec = _peak_record(a, peak, revision)
    if file_transition:
        rec["file_transition"] = file_transition     # the file's transition, where it differs from the configured one
    if quant is not None:
        rec["quant"] = quant                    # how the concentration was read: ratio, standard, curve
    if auto is not None:
        # edited by hand: the automatic peak is kept beside it, with the
        # kind of edit, the apex chosen and the line the peak was measured
        # on (its baseline, the levels set by hand)
        rec.update(manual=True, auto=_peak_record(a, auto, revision), by=override.get("by"),
                   reason=override.get("reason"), at=override.get("at"), kind=override["kind"])
        if override.get("apex") is not None:
            rec["chosen_apex"] = override["apex"]
        rec.update(_line_of(override, peak))
    if unapplied is not None:
        # an edit kept with no effect: the peak is the automatic one
        rec["unapplied"] = unapplied
    if qual_edits:
        # the analyst's qualifier edits: each with its automatic and its edited peak
        rec["qual_edits"] = qual_edits
    if qual_deleted:
        # the qualifiers whose peak the analyst deleted beside a quantifier
        # peak: the identification is not confirmed (qc_engine.qualifiers_deleted)
        rec["qual_deleted"] = qual_deleted
    if qual_processing:
        # the qualifiers a processing change made the peak of, each with its
        # change: the ion ratio is read on them
        rec["qual_processing"] = qual_processing
    return "raw:" + json.dumps(rec, sort_keys=True)


def _qual_edit_record(a, label, edit, auto, peak, revision, unapplied=None):
    """A qualifier's edit on the row's record: the edit, its automatic and
    its edited peak, the line it was measured on; an edit kept with no
    effect says why ("unapplied") and has no automatic peak beside it."""
    rec = dict((k, edit[k]) for k in ("kind", "start", "end", "baseline", "levels", "shape", "apexes", "pick", "alone", "by",
                                      "at", "reason")
               if k in edit)
    if edit.get("apex") is not None:
        rec["chosen_apex"] = edit["apex"]
    if auto is not None:
        rec.update(_line_of(edit, peak))
    if unapplied:
        rec["unapplied"] = unapplied
    rec.update(transition=label, auto=_peak_record(a, auto, revision) if auto is not None else None,
               peak=_peak_record(a, peak, revision) if peak is not None else None)
    return rec


def _change_text(edit, peak=None, unapplied=None):
    """One edit in the panel's words (raw_review.change_text), "by X", with
    ": <reason>" when the record carries one: "re-integrated, perpendicular
    drop, 4.10 to 4.29 min by AN1". An applied edit is named by the peak it
    made (`peak`: its edges and the line it was measured on, the method's
    for an edit that names none); one kept with no effect by its own
    fields, and ", no effect: <why>"."""
    shown = dict(edit)
    if peak is not None and unapplied is None and edit["kind"] != "delete":
        if edit["kind"] == "integrate":
            shown.update(start=peak.start, end=peak.end)
        shown.pop("levels", None)
        shown.update(_line_of(edit, peak))
    text = "%s by %s" % (load("raw_review").change_text(shown), edit.get("by"))
    text += ": %s" % edit["reason"] if edit.get("reason") else ""
    return text + (", no effect: %s" % unapplied if unapplied else "")


def _manual_changes(edit, qual_edits, peak=None, unapplied=None, qual_peaks=None, qual_unapplied=None):
    """The row's edits, the quantifier's first, then each qualifier's by its
    transition, each with the peak it made (`peak`, `qual_peaks` by
    transition label) or why it had no effect (`unapplied`,
    `qual_unapplied`); None without one."""
    qual_peaks, qual_unapplied = qual_peaks or {}, qual_unapplied or {}
    parts = ([_change_text(edit, peak, unapplied)] if edit is not None else []) + [
        "qualifier %s: %s" % (label, _change_text(e, qual_peaks.get(label), qual_unapplied.get(label)))
        for label, e in sorted((qual_edits or {}).items())]
    return "; ".join(parts) or None


def overrides_path(manifest_path):
    """The run's manual re-integrations, beside its record."""
    return os.path.splitext(manifest_path)[0] + ".overrides.json"


def processing_path(manifest_path):
    """The run's processing changes ("Apply to all"), beside its record:
    the add-on writes it, the worker only reads it."""
    return os.path.splitext(manifest_path)[0] + ".processing.json"


def _processings(proc, analytes):
    """({analyte: change} of the quantifiers, {analyte: {transition label:
    change}} of the qualifiers): the run's processing file
    (raw_review.read_processing's whole dict) read through the add-on's
    record (raw_review.processing_of). A file of another version, a key or
    change that cannot be read, an analyte the run does not hold, a
    transition it does not have, two keys for one quantifier, or a compound
    that is not a single peak refuse the run, naming the key."""
    review = load("raw_review")
    if not proc:
        return {}, {}
    if proc.get("version") != review.PROCESSING_VERSION or not isinstance(proc.get("traces"), dict):
        raise RawRunError("The run's processing changes cannot be read: the file is not one of version %d"
                          % review.PROCESSING_VERSION)
    quant, quals, keys = {}, {}, {}
    for key in sorted(proc["traces"]):
        try:
            n, label = review.parse_processing_key(key)
            change = review.processing_of(proc["traces"][key])
        except ValueError as exc:
            raise RawRunError("The processing change %s cannot be applied: %s" % (key, exc))
        if n not in analytes:
            raise RawRunError("A processing change names %s, which this run does not hold" % n)
        a = analytes[n]
        mode = a.get("mode") or "single"
        if mode != "single":
            # a pair or a summed peak is split or summed with its partner: no
            # one apex places its edges
            raise RawRunError("The processing change %s cannot be applied: %s is %s, not a single peak"
                              % (key, n, mode))
        if label is None or label == _label(a["quant"]):
            if n in quant:
                raise RawRunError("The processing changes %s and %s both name %s's quantifier" % (keys[n], key, n))
            quant[n], keys[n] = change, key
        elif label in [_label(q) for q in a.get("quals") or []]:
            quals.setdefault(n, {})[label] = change
        else:
            raise RawRunError("The processing change %s cannot be applied: %s has no transition %s"
                              % (key, n, label))
    return quant, quals


def _run_smoothing(proc, analytes):
    """The analytes with the run's smoothing changes (the processing file's
    "smoothing", raw_review.read_processing) set as each compound's own
    smoothing, before its settings are read (settings_for): {analyte:
    analyte entry}, copied where changed, the method's entries never
    altered. Every trace of the compound is then smoothed over that window
    in every injection, and its learnt width is not used; an analyst's edit
    is replayed on it as before, keeping its edges. A change that cannot be
    read, one naming an analyte the run does not hold, or one of a pair or
    summed compound (split or summed with its partner) refuses the run."""
    smoothing = (proc or {}).get("smoothing")
    if not smoothing:
        return analytes
    if not isinstance(smoothing, dict):
        raise RawRunError("The run's smoothing changes cannot be read")
    review = load("raw_review")
    out = dict(analytes)
    for n in sorted(smoothing):
        try:
            change = review.processing_of(smoothing[n])
            if change["kind"] != review.SMOOTHING_KIND:
                raise ValueError("it is not a smoothing change")
        except ValueError as exc:
            raise RawRunError("The smoothing change %s cannot be applied: %s" % (n, exc))
        if n not in analytes:
            raise RawRunError("A smoothing change names %s, which this run does not hold" % n)
        mode = analytes[n].get("mode") or "single"
        if mode != "single":
            raise RawRunError("The smoothing change %s cannot be applied: %s is %s, not a single peak"
                              % (n, n, mode))
        a = dict(analytes[n])
        a["settings"] = dict(a.get("settings") or {}, smooth_points=change["points"])
        # each stored trace of the compound names the change it was smoothed
        # by, so the review waits on a run not yet processed with the file's
        a["smoothing_change"] = change
        out[n] = a
    return out


def _mark_from_method(quant, quals, keys):
    """Each change taken from the method's entry (`keys`, processing keys)
    says so: "from": "method" on the peak's processing, its parentage, and
    the review never waits on it as on an undone change of the run."""
    review = load("raw_review")
    for key in keys:
        n, label = review.parse_processing_key(key)
        change = quant.get(n) if label is None else (quals.get(n) or {}).get(label)
        if change is None and label is not None:
            # a qualifier named by the quantifier's transition is the quantifier
            change = quant.get(n)
        if change is not None:
            change["from"] = "method"


# the automatic peak's measures an edited trace keeps beside the manual one
AUTO_MEASURES = ("start", "end", "base_start", "base_end", "area")
# what the record keeps of the analyst's edit
EDIT_FIELDS = ("kind", "by", "at", "apex", "baseline", "levels", "shape", "apexes", "pick", "alone", "version")


def _offered(choices, auto):
    """The candidates the record offers, in time order: every one, or past
    raw_traces.MAX_CANDIDATES, the one whose apex is the automatic peak's
    (the nearest) and then the rest by S/N, highest first; and how many
    were left out."""
    most = load("raw_traces").MAX_CANDIDATES
    if len(choices) <= most:
        return list(choices), 0
    first = ([min(choices, key=lambda c: abs(c.rt - auto.rt))]
             if auto is not None and auto.rt is not None and choices else [])
    rest = sorted((c for c in choices if c not in first), key=lambda c: -(c.sn or 0.0))
    return sorted(first + rest[:most - len(first)], key=lambda c: c.rt), len(choices) - most


def _engine_fields(settings, found):
    """(fields, margin, smoothing window) of the trace's engine: what the
    review's preview of a manual peak needs, and how many points beyond an
    edge, and about the apex, the engine's manual measure reads
    (raw_preview.read_margin, the margin the review's safety net reads a
    drop or a skim against)."""
    if isinstance(settings, ri.AdaptiveSettings):
        m = found.smoothing if found is not None and found.smoothing is not None else _adaptive_m(settings)
        fields = {"engine": "adaptive", "baseline": "valley"}
        if m is None:
            return fields, ri.EDGE_POINTS, 0
        m = int(m)
        fields.update(smoothing=m, edge_points=max(m, 1))
        return fields, load("raw_preview").read_margin("adaptive", m=m), 2 * m + 1
    n = int(settings.smooth_points)
    return ({"engine": "classic", "baseline": settings.baseline, "smooth_points": n,
             "edge_points": settings.edge_points},
            load("raw_preview").read_margin("classic", n, settings.edge_points), n)


def _reach(settings, found, y):
    """A function of the edge range (e0, e1) giving (r0, r1), the farthest
    indices a perpendicular drop's or a tangent skim's neighbour walk from
    an edge in it reads on the trace's engine (raw_preview.walk_reach on
    its smoothed signal: Classic at its smoothing window, Adaptive at the
    peak's m), one more each way (the walk compares the sample beyond
    where it stops); None without the settings or m to smooth with."""
    if settings is None:
        return None
    y = np.asarray(y, dtype=float)
    if isinstance(settings, ri.AdaptiveSettings):
        m = found.smoothing if found is not None and found.smoothing is not None else _adaptive_m(settings)
        if m is None:
            return None
        ys = raw_adaptive._smooth(y, max(int(m), 1))
    else:
        ys = ri._smooth(y, settings)
    n, walk = len(ys), load("raw_preview").walk_reach

    def sm(i):
        return float(ys[i])

    def reach(e0, e1):
        return max(walk(sm, n, e0, -1) - 1, 0), min(walk(sm, n, e1, 1) + 1, n - 1)
    return reach


def _stored_spans(window, peak, auto=None, search=None, offered=()):
    """The (t0, t1) spans a stored trace keeps at full resolution: the
    peak's own first (the automatic and the manual peak's, as one), as past
    the size limit the rest is cut back around it; then its `window`, the
    span it was searched in and each candidate `offered`."""
    own = [p for p in (peak, auto) if p is not None and p.start is not None]
    spans = [(min(p.start for p in own), max(p.end for p in own))] if own else []
    # a fitted peak's whole fitted span, so the fit can be drawn and judged
    # on the points it was made over
    spans += [tuple(p.fit["span"]) for p in (peak, auto) if p is not None and p.fit]
    return spans + [tuple(window)] + ([tuple(search)] if search else []) + [(c.start, c.end) for c in offered]


def _kept(xy, settings, found, spans):
    """(t, y, full_res, full_res_reach) of the trace `xy` as stored for
    `spans` (raw_traces.keep_reach) on its engine: `settings` the trace's
    own, `found` the peak whose smoothing a drop's or a skim's neighbours
    are walked at (_reach)."""
    margin, window = ri.EDGE_POINTS, 0
    if settings is not None:
        _fields, margin, window = _engine_fields(settings, found)
    return load("raw_traces").keep_reach(xy[0], xy[1], spans, margin, window, _reach(settings, found, xy[1]))


def _with_review_measures(xy, a, peak, auto, settings, limits, neighbours, choices):
    """The quantifier peak with its drop line's shared edge and the
    automatic peak scored under each fitting method, for the review. A
    summed peak has no single apex to score, and a peak not detected has no
    edges. `neighbours` are the (start, end) of peaks beside it; the
    candidates of its window count too."""
    t = xy[0]
    others = list(neighbours) + [(c.start, c.end) for c in (choices or []) if c.detected]
    peak = dataclasses.replace(peak, drop_rt=_drop_rt(peak, t, others, isinstance(settings, ri.AdaptiveSettings)))
    found = auto if auto is not None else peak
    if (settings is None or a.get("mode") == "summed" or not found.detected or found.rt is None
            or found.start is None):
        return peak
    amp = _review_rules(a)["search_amp_sn"]
    return dataclasses.replace(peak, fit_scores=_fit_scores(t, xy[1], found, settings, limits,
                                                            bool(a.get("labelled")), amp))


def _keep_trace(out, inj, name, q, role, xy, a, peak, revision, linked, file_transition=None,
                auto=None, settings=None, edit=None, choices=None, search=None, unapplied=None,
                members=None, skipped=None, expected=None, limits=None, neighbours=()):
    """One trace with its peak for review. `auto` is the automatic peak an
    edit replaced: its noise sigma is the trace's, so a manual peak's S/N
    is judged against the noise the automatic call read. `settings` are the
    trace's own (the automatic call's), `edit` the analyst's edit of it,
    `choices` its candidates (a single peak only; _choices) and `search`
    the (t0, t1) its peak was searched in.

    Beside the peak the record keeps, for review: the engine, the baseline
    in use (the edit's own, else the method's; Adaptive's line is
    "valley"), the edge points and smoothing the preview of a manual peak
    needs; the candidates (each as raw_integrate.as_candidate); for an
    edit, "manual" (the edit) and "auto" (the automatic peak's apex, edges,
    baseline ends, area and S/N), and "deleted" for a deleted peak;
    "full_res", the times an edge may lie between, and "full_res_reach",
    the times held at full resolution: full_res widened by every
    neighbour a drop or a skim from an edge in it reaches (_reach), so
    each is measured on the stored trace as the worker measures it
    (raw_traces.keep_reach). An
    edit kept but not applied (`unapplied`, why) is still "manual", with
    that reason and no automatic peak: the review reads it as having no
    effect rather than as waiting for the run. A processing change shows
    where it acted: on the peak, or on "auto" under an edit; `skipped` is
    why a trace with no peak did not take one. `expected` is the time its
    peak was searched about ("expected_rt", after any relative-retention
    shift): a fit applied to all is placed from it. Every number is
    finite, so the record is JSON."""
    if peak is not None and role == "quant":
        peak = _with_review_measures(xy, a, peak, auto, settings, limits, neighbours, choices)
    rec = _peak_record(a, peak, revision) if peak is not None else {
        "window": [a["rt"] - a["window"], a["rt"] + a["window"]]}
    if peak is None and skipped:
        rec["processing_skipped"] = skipped
    found = auto if auto is not None else peak
    if found is not None and found.noise is not None:
        rec["sigma"] = _finite(float(found.noise))
    if file_transition:
        rec["file_transition"] = file_transition
    rec["linked_is"] = linked                      # the standard it was quantified on
    if a.get("smoothing_change"):
        rec["smoothing_change"] = dict(a["smoothing_change"])   # the run's smoothing (_run_smoothing)
    if expected is not None:
        rec["expected_rt"] = _finite(float(expected))
    if members:
        rec["linked_members"] = list(members)      # a composite's, averaged
    if settings is not None:
        rec.update(_engine_fields(settings, found)[0])
        # the trace's detection floor: a fitted peak under it reads not
        # detected (raw_integrate.fitted_peak), which the card's preview says
        rec["min_sn"] = _finite(float(settings.min_sn))
        if edit is not None and auto is not None and edit.get("baseline"):
            # the edit's baseline, where the edit was replayed
            rec["baseline"] = edit["baseline"]
    offered = ()
    if choices is not None:
        offered, cut = _offered(choices, auto if auto is not None else peak)
        rec["candidates"] = [dict((k, _finite(v)) for k, v in ri.as_candidate(c, *xy).items()) for c in offered]
        if cut:
            rec["candidates_cut"] = cut
    if edit is not None and auto is not None:
        rec["manual"] = dict((k, edit[k]) for k in EDIT_FIELDS if edit.get(k) is not None)
        rec["auto"] = dict([(k, _finite(getattr(auto, k))) for k in AUTO_MEASURES]
                           + [("apex", _finite(auto.rt)), ("sn", _finite(auto.sn))]
                           # the automatic peak a processing change made, or why it kept its own
                           + [(k, getattr(auto, k)) for k in ("processing", "processing_skipped")
                              if getattr(auto, k) is not None])
        if edit["kind"] == "delete":
            rec["deleted"] = True
    elif edit is not None and unapplied:
        rec["manual"] = dict([(k, edit[k]) for k in EDIT_FIELDS if edit.get(k) is not None]
                             + [("unapplied", unapplied)])
    t, y, rec["full_res"], rec["full_res_reach"] = _kept(xy, settings, found,
                                                         _stored_spans(rec["window"], peak, auto, search, offered))
    if rec.get("candidates") and rec["full_res"]:
        # past the size limit the stretch is cut back around the peak's own
        # span: a candidate it no longer holds is not offered, as its edges
        # would be judged on thinned points
        lo, hi = rec["full_res"]
        inside = [c for c in rec["candidates"] if lo <= c["start"] and c["end"] <= hi]
        cut = rec.get("candidates_cut", 0) + len(rec["candidates"]) - len(inside)
        rec["candidates"] = inside
        if cut:
            rec["candidates_cut"] = cut
    out.append({"injection": inj, "analyte": name, "transition": _label(q), "role": role,
                "t": t, "y": y, "peak": json.dumps(rec, sort_keys=True)})


def run_folder(manifest, manifest_path, run_root=None):
    """Where the run's files are: the manifest's `run_dir`, which must sit
    directly under the worker's run area; without one, beside the manifest."""
    run_dir = manifest.get("run_dir")
    if not run_dir:
        return os.path.dirname(os.path.abspath(manifest_path))
    root = os.path.realpath(run_root or RUN_ROOT)
    name = os.path.basename(os.path.normpath(run_dir))
    if os.path.dirname(os.path.realpath(run_dir)) != root or safe_join(root, name) is None:
        raise RawRunError("The run folder %s is outside the worker's run area" % run_dir)
    return os.path.join(root, name)


def load_raw_run(manifest_path, integration, cal_rule, surrogate_map, traces=None, run_root=None,
                 composites=None, linked=False, roles=None, salt_factors=None, acid_basis=None):
    """The run's rows. `cal_rule` is the method's CalibrationRule, or a
    callable giving it per analyte (Profile.calibration_rule). A `traces`
    list receives each quantifier and qualifier trace with its peak, for
    review (raw_traces). `composites` ({id: [member keywords]}): an analyte
    whose surrogate map names one is read on the mean of its members' areas
    in each injection (EPA 1633A §15.2). `linked` (the method's linked
    response ratio on) with `roles` ({keyword: "surrogate" | "injection_is"}):
    an analyte quantified on a surrogate is read on its area over the
    surrogate's own response ratio on the internal standard it is linked
    to, in every injection, calibrators included (linked_standard).
    `salt_factors` ({labelled standard: factor}): a labelled standard's
    stated amounts, its level in the calibrators and the amount spiked, are
    turned to the acid form by its factor, so its found and spiked amounts
    are acid; its recovery, their quotient, does not move, nor does any
    native's result (in RR = A x C_L / A_L, C_L is one level in every
    injection and folds into the slope). A standard the run's calibration
    lots state as the acid (`acid_basis`) takes none; unset is 1.0."""
    composites = composites or {}
    roles = roles or {}
    acid = set((a or "").strip().upper() for a in acid_basis or [])
    salt = dict((k, float(f)) for k, f in (salt_factors or {}).items()
                if f and float(f) != 1.0 and (k or "").strip().upper() not in acid)

    def stated(inj, n):
        """A compound's stated concentration in a calibrator or check
        standard, a labelled standard's as acid."""
        value = _expected(inj, n)
        return value * salt[n] if value is not None and n in salt and analytes[n].get("labelled") else value
    quant = load("quant_fit")
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    base = run_folder(manifest, manifest_path, run_root)
    injections = manifest.get("injections") or []
    if not injections:
        raise RawRunError("The run record lists no injections")
    settings = integration["method"]
    # the run's processing changes ("Apply to all"), read before any peak
    # is found: a compound's smoothing changed for the run is its smoothing
    # from the start. The worker only reads the file, which the add-on writes.
    try:
        proc = load("raw_review").read_processing(processing_path(manifest_path))
    except ValueError as exc:
        raise RawRunError(str(exc))
    analytes = _run_smoothing(proc, integration["analytes"])
    revision = integration.get("revision")
    # a qualifier's floor when its compound sets none
    confirm_min = integration.get("sn_confirm_min")
    # the candidates offered as another apex
    rules = integration.get("review_rules")
    chroms, renamed = _traces(base, injections, analytes, integration.get("mz_tolerance", DEFAULT_MZ_TOLERANCE))
    mzml = load("raw_mzml")

    calibrators = [inj for inj in injections if inj.get("type") == "Standard" and inj.get("level")]
    learnt = learn_smoothing(chroms, calibrators, analytes, settings)

    def smooth_of(inj, n):
        """The analyte's learnt (m, calibrator); with none, the trace's own m
        named after its injection."""
        if n not in learnt:
            return None
        m, source = learnt[n]
        return (m, source) if m is not None else (None, inj)

    # the labelled standards first, at their configured times: a native under
    # relative retention is expected where its quantitation standard was
    # found; a summed analyte after the rest, beside its partner's chosen peak
    peaks, searched, notes = {}, {}, {}

    def found(inj, n, rt, note):
        p = _peak(chroms[inj][n], analytes, n, settings, smooth_of(inj, n), rt,
                  peaks.get((inj, analytes[n].get("partner"))))
        if note:
            p.note = p.note + "; " + note if p.note else note
        return p

    order = sorted(analytes, key=lambda n: (not analytes[n].get("labelled"),
                                            analytes[n].get("mode") == "summed", n))
    for inj in injections:
        for n in order:
            rt, note = _expected_rt(peaks, inj["name"], analytes, n, settings, surrogate_map, composites)
            if rt is not None:
                searched[(inj["name"], n)] = rt
            notes[(inj["name"], n)] = note
            peaks[(inj["name"], n)] = found(inj["name"], n, rt, note)
    # a change applied to every injection of a trace ("Apply to all") is
    # placed on each injection's own automatic apex and measured before the
    # analyst's edits: an edited trace keeps its manual peak over it, and an
    # injection that cannot take it keeps its automatic peak, saying why.
    # the method's own processing entry (countersigned from a run) takes
    # each trace the run's file holds no change of, through the same path;
    # the run's own change wins. Merged here only: the file is never written
    proc, from_method = load("method_proposals").with_method_processing(
        proc, dict((n, a.get("processing")) for n, a in analytes.items() if a.get("processing")))
    processing, qual_processing = _processings(proc, analytes)
    _mark_from_method(processing, qual_processing, from_method)
    processed = set()
    for (inj_name, n) in sorted(k for k in peaks if k[1] in processing):
        a = analytes[n]
        xy = chroms[inj_name][n][mzml.transition_key(*a["quant"])]
        own = settings_for(a, settings, n)
        rt = searched.get((inj_name, n))
        exclude = _partner_span(analytes, n, rt)
        region = _region_of(xy, _smoothed(own, smooth_of(inj_name, n))[0], a, rt, None,
                            functools.partial(_quant_choices, xy[0], xy[1], a, rt, own, smooth_of(inj_name, n),
                                              exclude, rules))
        p = peaks[(inj_name, n)] = _processed_or_skipped(processing[n], peaks[(inj_name, n)], xy[0], xy[1], own, a,
                                                         "%s / %s" % (inj_name, n), exclude, region,
                                                         _fit_limits(a, integration), _search_time(a, rt))
        if p.processing:
            processed.add((inj_name, n))
    # a summed peak beside a processed partner is summed again, as beside a
    # re-integrated one (below), so no area is counted in both rows
    for (inj_name, n) in sorted(processed):
        for b in sorted(analytes):
            if analytes[b].get("partner") == n and analytes[b].get("mode") == "summed":
                p = found(inj_name, b, searched.get((inj_name, b)), notes.get((inj_name, b)))
                fitted = (peaks[(inj_name, n)].processing or {}).get("kind") == "fit"
                p.note = (p.note + "; " if p.note else "") + (RESUMMED_FITTED if fitted else RESUMMED_PROCESSED)
                peaks[(inj_name, b)] = p
    # the analyst's edits replace those peaks, every time the run is processed
    overrides = load("raw_review").read_overrides(overrides_path(manifest_path))
    edits, qual_edits = _edits(overrides, analytes, peaks)
    # each applied edit's automatic peak; why each edit kept with no effect was not applied
    autos, unapplied = {}, {}
    for (inj_name, n), edit in sorted(edits.items()):
        a = analytes[n]
        t, y = chroms[inj_name][n][mzml.transition_key(*a["quant"])]
        auto = peaks[(inj_name, n)]
        own = settings_for(a, settings, n)
        exclude = _partner_span(analytes, n, searched.get((inj_name, n)))
        choices = None
        if edit["kind"] == "apex":
            choices = _quant_choices(t, y, a, searched.get((inj_name, n)), own, smooth_of(inj_name, n), exclude,
                                     rules)
        try:
            peaks[(inj_name, n)] = _replay(edit, auto, t, y, own, a, "%s / %s" % (inj_name, n), exclude, choices,
                                           _fit_limits(a, integration))
        except Unapplied as exc:
            unapplied[(inj_name, n)] = str(exc)
            continue
        autos[(inj_name, n)] = auto
    deleted = set(k for k, e in edits.items() if e["kind"] == "delete")
    # a summed peak beside a re-integrated partner, or one given another
    # apex (a branched cluster beside its linear peak), is summed again as at
    # first, less whatever the partner now covers, so no peak is counted in
    # both rows; one the analyst edited too stays as set, unless its edit had
    # no effect (it is then automatic, and summed again like one unedited).
    # Beside a deleted partner it keeps the sum it was given beside the
    # partner's automatic peak: the deleted area is counted in neither row.
    for (inj_name, n) in sorted(edits):
        if (inj_name, n) in deleted or (inj_name, n) in unapplied:
            continue
        for b in sorted(analytes):
            if (analytes[b].get("partner") == n and analytes[b].get("mode") == "summed"
                    and ((inj_name, b) not in edits or (inj_name, b) in unapplied)):
                p = found(inj_name, b, searched.get((inj_name, b)), notes.get((inj_name, b)))
                p.note = (p.note + "; " if p.note else "") + (
                    RESUMMED_FITTED if edits[(inj_name, n)]["kind"] == "fit" else RESUMMED)
                peaks[(inj_name, b)] = p

    def std_of(n):
        """The standards the analyte is read on: a composite's members, else
        its one standard."""
        isn = surrogate_map.get(n)
        return list(composites[isn]) if isn in composites else ([isn] if isn else [])

    def linked_standard(n):
        """(the internal standard an analyte's ratio is linked through, None),
        (None, why it cannot be) or (None, None) for the plain ratio.

        Under the linked response ratio RR = A x C_sur / RR_sur, RR_sur =
        A_sur x C_IS / A_IS, so RR = A x A_IS / A_sur x C_sur / C_IS. C_sur
        and C_IS are each one level in every injection (the calibrators'
        level, every sample spiked to it; the internal standard at its one
        level), so their quotient is a constant of the analyte's curve: it
        folds into the slope and the ratio is formed as A x A_IS / A_sur.
        Only an analyte on a surrogate (or a composite of surrogates) is
        linked; one on an injection standard keeps its plain ratio. A
        composite's members must share their internal standard: the mean of
        their areas has one A_IS only then."""
        if not linked or analytes[n].get("labelled"):
            return None, None
        stds = std_of(n)
        if not stds:
            return None, None
        found = set(roles.get(s) for s in stds)
        if found == {"injection_is"}:
            return None, None
        if found != {"surrogate"}:
            return None, ("%s is quantified on %s, which has no single role in the method's labelled "
                          "standards, so its linked response ratio cannot be formed" % (n, surrogate_map.get(n)))
        for s in stds:
            if not surrogate_map.get(s):
                return None, ("%s has no Linked to, so the linked response ratio of %s cannot be formed"
                              % (s, n))
        links = sorted(set(surrogate_map.get(s) for s in stds))
        if len(links) > 1:
            return None, ("the members of %s are linked to different internal standards (%s), so the mean "
                          "of their areas has no one internal standard" % (surrogate_map.get(n), ", ".join(links)))
        return links[0], None

    link_of = dict((n, linked_standard(n)) for n in analytes)
    # an analyte whose linked ratio cannot be formed at all: no curve, every
    # detection held, naming why
    unlinked = dict((n, v[1]) for n, v in link_of.items() if v[1])

    def is_area_of(inj, n):
        """The area of the internal standard an analyte's ratio is linked
        through, in this injection; None while it is not detected."""
        lk = link_of.get(n, (None, None))[0]
        ip = peaks.get((inj, lk)) if lk else None
        return ip.area if ip is not None and ip.detected and ip.area else None

    def std_area(inj, n):
        """The denominator: the standard's area, or the mean of a composite's
        members' areas; None while any member is not detected (no reading
        is made on part of the denominator the curve was fitted on)."""
        stds = std_of(n)
        ips = [peaks.get((inj, s)) for s in stds]
        if not stds or any(ip is None or not ip.detected or (len(ips) > 1 and not ip.area) for ip in ips):
            return None
        return sum(ip.area for ip in ips) / len(ips)

    def ratio(inj, n):
        """(the response ratio, the standard's area): A / A_sur, or, linked,
        A x A_IS / A_sur (linked_standard)."""
        p, is_area = peaks[(inj, n)], std_area(inj, n)
        if not (p.detected and is_area) or n in unlinked:
            return None, is_area
        lk = link_of.get(n, (None, None))[0]
        if lk:
            a_is = is_area_of(inj, n)
            return (p.area * a_is / is_area if a_is else None), is_area
        return p.area / is_area, is_area

    def std_missing(inj_name, n):
        """Why the standard gives no area here, naming a composite's member:
        (reason, member or None)."""
        stds = std_of(n)
        one = len(stds) == 1
        for s in stds:
            if (inj_name, s) in deleted:
                return IS_PEAK_DELETED, None if one else s
        for s in stds:
            ip = peaks.get((inj_name, s))
            if ip is None or not ip.detected or not ip.area:
                return ("isotope standard not detected", None) if one else (
                    "%s not detected, a member of its standard" % s, s)
        lk = link_of.get(n, (None, None))[0]
        if lk and (inj_name, lk) in deleted:
            return IS_PEAK_DELETED, None
        if lk and not is_area_of(inj_name, n):
            return linked_missing(n), None
        return "isotope standard not detected", None

    def linked_missing(n):
        return ("%s not detected, the internal standard its surrogate is linked to, so the linked "
                "response ratio cannot be formed" % link_of[n][0])

    if not calibrators:
        raise RawRunError("This run has no calibrators: a raw run on a reused curve cannot be "
                          "quantified yet (the stored curve keeps no responses). Run a new curve.")
    # every native of the method's panel, isomer peaks included, is
    # quantified on its standard: one with none refuses the run, never a row
    # left without a curve. A row off the panel is integrated, not
    # quantified; an analyte not marked either way is on it unless labelled.
    bare = sorted(n for n in analytes if analytes[n].get("panel", not analytes[n].get("labelled"))
                  and not surrogate_map.get(n))
    if bare:
        raise RawRunError("%s %s no quantitation standard: set one in the method's surrogate map"
                          % (", ".join(bare), "has" if len(bare) == 1 else "have"))
    # (injection, analyte) of each calibrator left off its curve for want of a reading
    unread = set()
    curves, unfit, one_level, few_for_quadratic, excluded, ends = {}, [], [], [], {}, {}
    # a quadratic that turns within its calibration range is not usable
    turns = []
    # a branched peak no calibrator states (a linear-only standard) reads on
    # its linear partner's curve
    borrowed = dict((n, analytes[n]["partner"]) for n in analytes
                    if n.lower().startswith("br-") and analytes[n].get("partner") in analytes
                    and surrogate_map.get(n) and not any(_expected(inj, n) for inj in calibrators))
    for n in sorted(analytes):
        if not surrogate_map.get(n) or n in borrowed:
            continue
        if n in unlinked:
            curves[n], excluded[n], ends[n] = None, [], {}
            continue
        excluded[n] = []
        fitted = [(stated(inj, n), ratio(inj["name"], n)[0], inj) for inj in calibrators
                  if _expected(inj, n)]
        # a calibrator with no quantifier peak, or none of its isotope
        # standard, has no response: it is off the curve, and the curve names
        # it; a peak the analyst deleted, its own before its standard's, is
        # named as deleted
        for p in fitted:
            if p[1] is None:
                inj_name = p[2]["name"]
                unread.add((inj_name, n))
                own = (PEAK_DELETED if (inj_name, n) in deleted
                       else "not detected" if not peaks[(inj_name, n)].detected else None)
                reason, member = (own, None) if own else std_missing(inj_name, n)
                excluded[n].append(dict({"injection": inj_name, "reason": reason},
                                        **({"member": member} if member else {})))
        fitted = [p for p in fitted if p[1] is not None]
        rule = cal_rule(n) if callable(cal_rule) else cal_rule
        refused = []
        curve = quant.fit([p[:2] for p in fitted], rule.default_fit,
                          rule.default_weighting, rule.origin, refused)
        if curve is None:
            # a quadratic needs three concentrations, a straight line two: a
            # compound every calibrator states at one level is named apart,
            # with the setting that fits it; a quadratic must rise across its
            # whole calibration range
            if quant.TURNS in refused:
                turns.append(n)
            elif rule.default_fit == "quadratic" and len(fitted) >= 2:
                few_for_quadratic.append(n)
            elif len(fitted) >= 2 and len(set(p[0] for p in fitted)) < 2:
                one_level.append(n)
            else:
                unfit.append(n)
        curves[n] = curve
        # the reporting range ends at the highest calibrator still on the
        # curve and starts at the lowest
        top = max(fitted, key=lambda p: p[0]) if fitted else None
        bottom = min(fitted, key=lambda p: p[0]) if fitted else None
        ends[n] = ({"top_conc": top[0], "top_level": top[2].get("level"), "top_injection": top[2]["name"],
                    "bottom_conc": bottom[0], "bottom_level": bottom[2].get("level")} if top else {})
    for n, partner in sorted(borrowed.items()):
        if n in unlinked:
            curves[n], excluded[n], ends[n] = None, [], {}
            continue
        if surrogate_map.get(partner) != surrogate_map[n]:
            raise RawRunError("%s has no calibrator concentrations of its own, and its linear partner %s "
                              "is quantified on another standard, so its curve cannot be used"
                              % (n, partner))
        if curves.get(partner) is None:
            (turns if partner in turns else unfit).append(n)
        curves[n], excluded[n], ends[n] = curves.get(partner), excluded.get(partner, []), ends.get(partner, {})
    why = []
    if unfit:
        why.append("No calibration curve can be fitted for %s: fewer than two calibrators "
                   "with a peak and a stated concentration" % ", ".join(sorted(unfit)))
    if few_for_quadratic:
        why.append("No calibration curve can be fitted for %s: the method's curve fit is Quadratic, "
                   "which needs calibrators with a peak at three concentrations or more"
                   % ", ".join(sorted(few_for_quadratic)))
    if turns:
        why.append(("The quadratic for %s turns within its calibration range. Choose Linear, or narrow "
                    "the range at its ends" if len(turns) == 1 else
                    "The quadratics for %s turn within their calibration ranges. Choose Linear, or narrow "
                    "each range at its ends") % ", ".join(sorted(turns)))
    if one_level:
        why.append("No calibration curve can be fitted for %s: every calibrator states %s at one "
                   "concentration, and a straight line needs two. A labelled compound at one level "
                   "is fitted only where the method's Engine says: Labelled compounds are calibrated "
                   "by their mean response factor"
                   %(", ".join(sorted(one_level)), "it" if len(one_level) == 1 else "each"))
    if why:
        raise RawRunError("; ".join(why))

    rows = []
    # each compound's level in the calibrators: what a sample is spiked to
    cal_levels = calibrator_levels(calibrators)
    run = manifest.get("run") or os.path.splitext(os.path.basename(manifest_path))[0]
    for inj in injections:
        name = inj["name"]
        acquired = datetime.fromisoformat(inj["acquired"]) if inj.get("acquired") else None
        stamp = acquired.strftime("%Y%m%d%H%M%S") if acquired else run
        for n in sorted(analytes):
            a = analytes[n]
            p = peaks[(name, n)] = _with_asymmetry(peaks[(name, n)],
                                                   chroms[name][n][mzml.transition_key(*a["quant"])], a)
            if (name, n) in searched:
                # the window written is the one searched
                a = dict(a, rt=searched[(name, n)])
            r, is_area = ratio(name, n)
            curve = curves.get(n)
            bottom = ends.get(n, {}).get("bottom_conc")
            top = ends.get(n, {}).get("top_conc")
            # a native in a sample reads a quadratic only between its lowest
            # and its highest calibrator: below the lowest it is BLoQ with no
            # number, no root taken (quant_fit.sample_reading). Standards,
            # check standards and blanks are read on the whole rising branch.
            in_sample = not a.get("labelled") and inj.get("type") not in NOT_SAMPLES
            place = None
            if in_sample and curve and r is not None:
                reading, place = quant.sample_reading(curve, r, bottom, top)
            else:
                reading = quant.concentration(curve, r) if curve and r is not None else None
                # above the range, judged on the ratio for every fit: a
                # native in a blank or a spike too (pipeline.raw_range
                # judges the injections with a sample basis); never a
                # calibrator, a point of the curve itself
                if (not a.get("labelled") and inj.get("type") != "Standard"
                        and quant.above_range(curve, r, top)):
                    place = quant.ABOVE
            below = place == quant.BELOW
            above = place == quant.ABOVE
            # below a quadratic's lowest calibrator the reading on the rising
            # branch is kept on the record, not as the row's number: the
            # pipeline gives it the number on the sample basis only at or
            # above the MDL (pipeline.raw_below_mdl)
            below_reading = reading if below else None
            if below:
                reading = None
            # a ratio a quadratic never reaches on its rising branch has no
            # reading: not quantified, never not detected, which the record
            # says; in a sample above the range it reads ALoQ
            no_reading = bool(curve and curve.get("quadratic") and r is not None and reading is None
                              and not below)
            # a reading below zero is no concentration: a detection below the
            # curve, its reading kept on the peak's record
            negative = reading is not None and reading < 0
            conc = None if negative else reading
            # a native's reading in a sample under the lowest calibrator keeps
            # its number, that calibrator its reporting limit (a straight
            # line); a standard, check standard or blank keeps the method's
            limit = (bottom if conc is not None and bottom is not None and conc < bottom and in_sample
                     else None)
            expected = stated(inj, n)
            # a labelled standard read on the one it is linked to, in an
            # injection that states the amount added: its recovery, the
            # amount spiked as acid where the standard has a salt factor
            recovery, rec = None, None
            if a.get("labelled") and surrogate_map.get(n) and not (inj.get("type") == "Standard"
                                                                  and inj.get("level")):
                spiked, source, why = _spiked(inj, n, cal_levels)
                if spiked is not None and n in salt:
                    spiked = spiked * salt[n]
                recovery, rec = surrogate_recovery(conc, spiked, source, why, surrogate_map.get(n))
            q_edits, q_autos, q_why = qual_edits.get((name, n), {}), {}, {}
            q_review = {} if traces is not None else None
            quals = _qual_peaks(chroms[name][n], analytes, n, p, settings, smooth_of(name, n), confirm_min,
                                searched.get((name, n)), q_edits, q_autos, "%s / %s" % (name, n), q_review,
                                rules, q_why, peaks.get((name, analytes[n].get("partner"))),
                                qual_processing.get(n), _fit_limits(a, integration))
            # a qualifier is read only beside a quantifier peak: with none, its
            # edit is kept on the trace as one with no effect, saying why
            if not (p.detected and p.area):
                q_why = dict((label, load("raw_review").no_quant_peak(name)) for label in q_edits)
            # a deletion is applied unless the qualifier was not read
            q_deleted = set(label for label, e in q_edits.items() if e["kind"] == "delete" and label not in q_why)
            # a deletion beside a quantifier peak, the only place a qualifier is read
            q_marker = [_label(q) for q, qp in quals if _label(q) in q_deleted and qp is not None]
            q_records = [_qual_edit_record(a, _label(q), q_edits[_label(q)], q_autos.get(_label(q)), qp, revision,
                                           q_why.get(_label(q)))
                         for q, qp in sorted(quals, key=lambda x: _label(x[0])) if _label(q) in q_edits]
            # its own peak beside its standard's deleted peak: not quantified,
            # which the record says (qc_engine.raw_is_deleted)
            lk = link_of.get(n, (None, None))[0]
            is_deleted = bool(p.detected and any((name, s) in deleted for s in std_of(n) + ([lk] if lk else [])))
            calibrator = bool(inj.get("type") == "Standard" and inj.get("level"))
            # under the linked response ratio: a detection with no ratio for
            # want of the link, or of its internal standard here, is held
            held = ""
            if p.detected and not calibrator and not is_deleted and (name, n) not in deleted:
                if n in unlinked:
                    held = unlinked[n]
                elif lk and is_area and not is_area_of(name, n):
                    held = linked_missing(n)
            if traces is not None:
                # the trace's own settings and candidates, as its automatic call had them
                xy = chroms[name][n][mzml.transition_key(*a["quant"])]
                own = settings_for(analytes[n], settings, n)
                _keep_trace(traces, name, n, a["quant"], "quant", xy, a, p, revision, surrogate_map.get(n),
                            renamed[name][n].get(mzml.transition_key(*a["quant"])), autos.get((name, n)),
                            _smoothed(own, smooth_of(name, n))[0], edits.get((name, n)),
                            _quant_choices(xy[0], xy[1], analytes[n], searched.get((name, n)), own, smooth_of(name, n),
                                           _partner_span(analytes, n, searched.get((name, n))), rules),
                            unapplied=unapplied.get((name, n)), members=composites.get(surrogate_map.get(n)),
                            expected=_search_time(a, searched.get((name, n))),
                            limits=_fit_limits(a, integration),
                            neighbours=([(pp.start, pp.end)] if (pp := peaks.get((name, a.get("partner"))))
                                        is not None and pp.detected and pp.start is not None else []))
                for q, qp in quals:
                    q_settings, q_choices, q_search = q_review.get(_label(q), (None, None, None))
                    _keep_trace(traces, name, n, q, "qual", chroms[name][n][mzml.transition_key(*q)], a, qp, revision,
                                surrogate_map.get(n), renamed[name][n].get(mzml.transition_key(*q)), q_autos.get(_label(q)),
                                q_settings, q_edits.get(_label(q)), q_choices, q_search, q_why.get(_label(q)),
                                # a qualifier not read beside no quantifier peak has no apex for a change
                                skipped=(load("raw_review").SKIP_NO_APEX
                                         if _label(q) in qual_processing.get(n, {}) else None),
                                expected=_search_time(a, searched.get((name, n))))
            rows.append(InstrumentRow(
                compound_name=_row_name(n), compound_type="Internal Standard" if a.get("labelled") else "Analyte",
                compound_group="",
                sample_description=name, injection_name=name, sample_group="",
                # a calibrator left off the curve for want of a reading is not
                # in it, nor one of an analyte read on its partner's curve,
                # nor of a native with no curve; a labelled
                # standard with none (an injection standard) stays one, its
                # response and time the reference
                sample_type=SAMPLE_TYPES.get(inj.get("type"), inj.get("type") or ""),
                included_in_cal=bool(calibrator and n not in borrowed
                                     and (name, n) not in unread
                                     and (curve or a.get("labelled"))),
                level=inj.get("level"), linked_is=surrogate_map.get(n), cal_ref_compound=None,
                observed_rt=p.rt, rt_relative_to_is=None,
                response=p.area, is_response=is_area, response_ratio=r,
                expected_conc=expected, calculated_conc=conc,
                # a calibrator left off the curve has no deviation from it
                pct_deviation=(quant.pct_deviation(curve, expected, r)
                               if curve and r is not None and expected else None),
                pct_recovery_is=recovery, ion_ratios=_ion_ratios(quals, p, q_deleted),
                expected_ion_ratios=None, r2=curve["r2"] if curve else None,
                signal_to_noise=_finite(p.sn), qual_sn=_qual_sn(quals, q_deleted), quant_status=None,
                reporting_limit=limit,
                measured_conc=conc, acquisition_datetime=acquired, concat_id="%s|%s" % (name, stamp),
                # a peak the analyst deleted is not detected; its own peak
                # beside its standard's deleted one is not quantified (a
                # calibrator is off its curve, which names it)
                conc_qualifier=("N.D." if (name, n) in deleted
                                else QUALIFIER_NQ if is_deleted and not calibrator
                                else QUALIFIER_NQ if held
                                # a sample above the range with no reading: a
                                # detection above it, never not quantified nor
                                # not detected (a spike or blank reads it from
                                # raw_range; a check standard never does)
                                else QUALIFIER_ALOQ if above and no_reading and p.detected and in_sample
                                else QUALIFIER_BLOQ if below and p.detected
                                else QUALIFIER_NQ if no_reading and p.detected and not calibrator
                                else QUALIFIER_BLOQ if negative and p.detected
                                else "" if p.detected else "N.D."),
                method_expected_ion_ratios=(None if a.get("expected_ion_ratio") is None
                                            else "%g" % a["expected_ion_ratio"]),
                source_file=os.path.basename(inj["file"]),
                derived_from=_provenance(a, p, revision, autos.get((name, n)), edits.get((name, n)),
                                         dict({"ratio": r, "is": surrogate_map.get(n), "is_area": is_area,
                                               # a labelled standard's salt factor, its amounts as acid
                                               **({"salt": salt[n]} if n in salt and a.get("labelled") else {}),
                                               # a composite's members and their areas here
                                               **({"members": [{"kw": s, "area": _finite(peaks[(name, s)].area)
                                                                if peaks.get((name, s)) is not None
                                                                and peaks[(name, s)].detected else None}
                                                               for s in std_of(n)]}
                                                  if surrogate_map.get(n) in composites else {}),
                                               "curve": dict([(k, curve[k]) for k in ("slope", "intercept",
                                                                                        "quadratic", "kind",
                                                                                        "weighting", "origin",
                                                                                        "r2") if k in curve],
                                                             excluded=excluded[n], **ends[n])
                                               if curve else None},
                                              **dict({"curve_of": borrowed[n]} if n in borrowed else {},
                                                     **({"reading": reading} if negative else {}),
                                                     **({"no_reading": quant.NO_READING} if no_reading else {}),
                                                     # above the range: the curve's
                                                     # response at its top, the
                                                     # reading kept where there is one
                                                     **({"above_range": True,
                                                         "top_response": quant.response_at(curve, top)}
                                                        if above else {}),
                                                     # below a quadratic's lowest
                                                     # calibrator in a sample: no number
                                                     # here, its reading kept for the
                                                     # MDL judgement
                                                     **({"below": quant.BELOW_READING,
                                                         "bottom_response": quant.response_at(curve, bottom),
                                                         "below_reading": below_reading}
                                                        if below else {}),
                                                     **({"recovery": rec} if rec else {}),
                                                     **({"is_deleted": True} if is_deleted else {}),
                                                     # the linked response ratio's internal standard
                                                     **({"linked": {"is": lk, "is_area": _finite(is_area_of(name, n))}}
                                                        if lk else {}),
                                                     **({"held": held} if held else {}))),
                                         renamed[name][n].get(mzml.transition_key(*a["quant"])), q_records,
                                         q_marker,
                                         _unapplied_record(edits[(name, n)], unapplied[(name, n)])
                                         if (name, n) in unapplied else None,
                                         dict((_label(q), qp.processing) for q, qp in quals
                                              if qp is not None and qp.processing)),
                ratio_held=held,
                manual_integration=True if (name, n) in edits or q_edits else None,
                manual_changes=_manual_changes(edits.get((name, n)), q_edits, p, unapplied.get((name, n)),
                                               dict((_label(q), qp) for q, qp in quals), q_why),
            ))
    return rows
