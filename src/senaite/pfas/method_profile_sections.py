# -*- coding: utf-8 -*-
"""Method Profile editor sections declared for config_forms.

Each section is saved on its own from its own tab. Only fields that have an
input on that tab are declared: a declared field with no input would be
cleared by every save of the tab. So instrument_verification.sequence (no
input anywhere; the Run Builder reads ccv.frequency) is deliberately absent.

Required fields: calibration r², CCV frequency and the CCV recovery window;
a blank in one is refused with the field named. Every other number is
optional and blank means "no limit" (None).
Python 2.7 compatible.
"""
from __future__ import absolute_import

from collections import OrderedDict

from senaite.pfas import config_forms as cf
from senaite.pfas import lab_time
from senaite.pfas import calibration_fit as _cfit
from senaite.pfas import method_proposals as _mp
from senaite.pfas.qc_names import QC_NAMES
from senaite.pfas.qc import rules as _rules

def _analytes_fit_words(profile):
    """The words of the method's curve fit, which a labelled compound on
    "the same fit as the analytes" is fitted with."""
    cal = (((profile or {}).get("instrument_verification") or {}).get("calibration") or {})
    return _cfit.fit_label(_cfit.fit(cal))


PCT = u"%"
PCT_SCALE = (0, 200)       # a display range for a % recovery window, never a limit
RPD_SCALE = (0, 100)

CALIBRATION_CCV = cf.Section(
    id=u"cal", title=u"Calibration & CCV", base=("instrument_verification",),
    groups=[
        (u"Calibration", [
            cf.Field("calibration.r2_min", u"R² Minimum", blank=u"none",
                     minimum=0.9, maximum=1.0, step=u"0.01",
                     help=u"Blank: the method sets no r² criterion."),
            cf.Field("calibration.point_pct_dev_max", u"Largest calibration point deviation",
                     unit=PCT, minimum=0,
                     help=u"Each calibration point within ±N % of the curve. Blank: no limit."),
            cf.Field("calibration.low_point_pct_dev_max", u"Largest deviation at the lowest level",
                     unit=PCT, minimum=0,
                     help=u"Wider limit for the lowest calibration level."),
            # a raw run: past it the analyte's curve check fails; the
            # deletions themselves stand
            cf.Field("calibration.max_cal_dropped", u"Most calibrators dropped", kind=cf.INT, minimum=0,
                     help=u"Calibrators one analyte's curve may lose to deleted peaks, its own or its "
                          u"isotope standard's; more fails its calibration check. Blank: no limit."),
            cf.Field("calibration.origin", u"Origin", kind=cf.CHOICE, widget=u"seg",
                     choices=lambda profile, env=None: list(_cfit.ORIGINS),
                     help=u"Include weights the origin as the lowest calibrator; an average RF is "
                          u"always forced through it."),
            cf.Field("calibration.weighting", u"Weighting", kind=cf.CHOICE, widget=u"seg",
                     choices=lambda profile, env=None: list(_cfit.WEIGHTINGS)),
            # where every new curve starts: the worker fits a raw run with it,
            # the curve card opens on it; unset reads as linear
            cf.Field("calibration.fit", u"Curve fit", kind=cf.CHOICE, widget=u"seg",
                     choices=lambda profile, env=None: list(_cfit.FITS), default=_cfit.FIT_WHEN_UNSET,
                     help=u"Every new curve starts here. Data Review can change one curve."),
            cf.Field("calibration.level_unit",
                     u"Do the calibration levels reflect the value in the sample?",
                     kind=cf.CHOICE, widget=u"seg",
                     choices=lambda profile, env=None: [
                         (u"ppt", u"Yes: ppt in the sample (ng/L, ng/kg)"),
                         (u"ng/mL", u"No: ng/mL in the extract")],
                     help=u"No: the derived RL is the lowest level \u00d7 the matrix factor "
                          u"on Sample Corrections; without a factor there is none."),
            # in the ladder's unit; a lot's stated value wins
            cf.Field("calibration.labelled_conc", u"Isotope standards in every calibrator and CCV",
                     greater_than=0,
                     help=u"In the calibration levels' unit. Used when the standard's lot states none."),
        ]),
        (u"Chromatographic Confirmation & Signal Quality", [
            cf.Field("confirmation.ion_ratio_tol_pct", u"Ion Ratio Tolerance ±",
                     unit=PCT, minimum=0,
                     help=u"Blank: no ion ratio criterion."),
            cf.Field("confirmation.rrt_tol_pct", u"Relative RT Tolerance",
                     unit=PCT, minimum=0,
                     help=u"Against the standard's relative retention time."),
            cf.Field("confirmation.rt_tol_abs_min", u"Absolute RT Tolerance",
                     unit=u"min", minimum=0,
                     help=u"The lab's own window, from the spread of its retention times."),
            cf.Field("confirmation.sn_quan_min", u"S/N Min — Quantitation Ion", minimum=0),
            cf.Field("confirmation.sn_confirm_min", u"S/N Min — Confirm Ion", minimum=0),
            cf.Field("surrogate_window.recovery_min", u"Surrogate recovery min", unit=PCT, minimum=0,
                     range_hi="recovery_max", scale=PCT_SCALE, empty=u"",
                     kept_if_absent=True),
            cf.Field("surrogate_window.recovery_max", u"Surrogate recovery max", unit=PCT, minimum=0,
                     help=u"Blank: the method text's window.", kept_if_absent=True),
        ]),
        # the qualifier ion check's limits (single_transition_confirm): greyed
        # while it is Off, still editable, values kept
        (u"Single-Transition Confirmation", [
            # the method's own analytes, stored as keywords: a typed name
            # cannot miss the check
            cf.Field("confirmation.single_transition_analytes",
                     u"Single-transition analytes", rule="single_transition_confirm",
                     kind=cf.MULTI, choices=lambda profile, env=None: _panel_choices(profile, env),
                     help=u"A positive needs a second technique."),
            cf.Field("confirmation.confirm_technique",
                     u"Confirmation technique", rule="single_transition_confirm",
                     kind=cf.TEXT, blank=u"remove", placeholder=u"LC-HRMS",
                     help=u"The review prompt quotes it (Help: Identity confirmation)."),
            cf.Field("confirmation.confirm_pct_diff_max", u"Largest difference between the two techniques",
                     rule="single_transition_confirm", unit=PCT, minimum=0),
        ]),
        (u"Continuing Calibration Verification (CCV)", [
            cf.Field("ccv.recovery_min", u"Recovery Min", unit=PCT, required=True, minimum=0,
                     range_hi="recovery_max", scale=PCT_SCALE),
            cf.Field("ccv.recovery_max", u"Recovery Max", unit=PCT, required=True, minimum=0),
            cf.Field("ccv.low_level_min", u"Low-Level Min", unit=PCT, minimum=0,
                     range_hi="low_level_max", scale=PCT_SCALE,
                     help=u"Wider window for the lowest CCV level."),
            cf.Field("ccv.low_level_max", u"Low-Level Max", unit=PCT, minimum=0),
            cf.Field("ccv.opens_run", u"A CCV opens the run", kind=cf.CHOICE,
                     blank=u"remove", choices=[(u"", u"No"), (u"yes", u"Yes")],
                     help=u"Yes: samples before the first CCV are not bracketed."),
            cf.Field("ccv.counts_extracted_qc", u"Extracted QC counts towards the CCV interval",
                     kind=cf.CHOICE, blank=u"remove",
                     choices=[(u"", u"Yes: field samples and extracted QC"),
                              (u"no", u"No: field samples only")],
                     help=u"No: only field samples count; the extracted QC does not."),
            cf.Field("ccv.surrogate_recovery", u"Surrogate recovery judged in CCVs", kind=cf.CHOICE,
                     blank=u"remove", choices=[(u"", u"No"), (u"yes", u"Yes")],
                     help=u"Yes: the CCV carries the surrogates."),
            # a window of their own for the labelled standards in a CCV; blank
            # = the sample window (a method may set a narrower window in its
            # continuing calibration check than in samples)
            cf.Field("ccv.surrogate_window_min", u"Surrogate recovery min in CCVs", unit=PCT, minimum=0,
                     range_hi="surrogate_window_max", scale=PCT_SCALE, empty=u""),
            cf.Field("ccv.surrogate_window_max", u"Surrogate recovery max in CCVs", unit=PCT, minimum=0,
                     help=u"Blank: the sample window."),
            cf.Field("icv.criteria", u"ICV limits", kind=cf.CHOICE, blank=u"remove",
                     widget=u"seg",
                     choices=[(u"ccv", u"Same as CCV"), (u"", u"Own limit")],
                     help=u"Same as CCV: the ICV must recover within the CCV recovery window above. "
                          u"Own limit: within its largest deviation below."),
            cf.Field("icv.pct_dev_max", u"Largest ICV deviation", unit=PCT, minimum=0,
                     show_if=("icv.criteria", u""),
                     help=u"Initial calibration verification, judged on the Calibrations page."),
            # how often a CCV is run: judged with the CCV's limits, after them
            cf.Field("ccv.frequency", u"CCV Frequency (every N samples)", kind=cf.INT,
                     required=True, minimum=1),
        ]),
        # When the run carries a new curve, and what verifies a reused one.
        # The Run Builder applies these and asks the bench chemist.
        (u"New calibration curve", [
            cf.Field("calibration.new_curve", u"A new curve is run", kind=cf.CHOICE,
                     blank=u"remove",
                     choices=[(u"", u"Analyst discretion"),
                              (u"every_run", u"Every run"),
                              (u"when_due", u"Required after time interval")],
                     help=u"The Run Builder asks the bench chemist unless every run needs one "
                          u"or the last curve is due."),
            cf.Field("calibration.max_age_days", u"A curve may be reused for", kind=cf.INT,
                     unit=u"days", minimum=1, help=u"Blank: no limit."),
            cf.Field("icv.after_new_curve", u"ICV after a new curve", kind=cf.CHOICE,
                     blank=u"remove", choices=[(u"", u"Yes"), (u"no", u"No")]),
            cf.Field("icv.when_reused", u"A run on a reused curve opens with", kind=cf.CHOICE,
                     blank=u"remove", choices=[(u"", u"A CCV"), (u"ICV", u"An ICV")]),
        ]),
        (u"IS / Surrogate Response", [
            cf.Field("is_response.vs_ical_avg_min", u"Initial Calibration Average Min", unit=PCT, minimum=0,
                     range_hi="vs_ical_avg_max", scale=PCT_SCALE),
            cf.Field("is_response.vs_ical_avg_max", u"Initial Calibration Average Max", unit=PCT, minimum=0),
            cf.Field("is_response.vs_last_ccv_min", u"Compared to the most recent CCV Min",
                     unit=PCT, minimum=0, range_hi="vs_last_ccv_max", scale=PCT_SCALE, rule="is_vs_ccv"),
            cf.Field("is_response.vs_last_ccv_max", u"Compared to the most recent CCV Max",
                     unit=PCT, minimum=0, rule="is_vs_ccv"),
        ]),
    ])

def _library():
    """(compound_library, the library the services hold)."""
    from senaite.pfas import compound_library, compound_library_store
    return compound_library, compound_library_store.library()


def _global_titles():
    """{native keyword: display name}, the compound library's."""
    cl, lib = _library()
    return cl.native_names(lib)


from senaite.pfas import isomers as _iso


class _Labels(dict):
    """{keyword: label} for ONE method: a summed analyte shows its reported
    name (the Isomers tab), every other analyte its display name. Every tab
    labels analytes through this, so an isomer change reaches all of them."""

    def __init__(self, profile):
        dict.__init__(self)
        self.profile, self.titles = profile, _global_titles()

    def get(self, kw, default=None):
        return _iso.label(self.profile, kw, self.titles)


def _analyte_titles(profile):
    return _Labels(profile)


def _limits_for(profile, env):
    """{(matrix, keyword): [info entry]}: every regulatory limit naming one of
    the method's matrices, on each analyte it covers: the action level / MCL
    beside the RL. Values stay on Regulatory Limits; this
    only shows them, marked when not verified (never printed) or switched off
    for this method x matrix (the list under the table)."""
    store = (env or {}).get("regulatory") or {}
    names = store.get("programs") or {}
    out = {}
    for lim in store.get("limits") or []:
        if not lim.get("id") or lim.get("retired"):
            continue
        prog = (names.get(lim.get("program")) or {}).get("name") or lim.get("program") or u""
        analytes = lim.get("analytes") or []
        text = u"%s %s %s · %s" % (_sig(lim.get("value")) if lim.get("value") is not None
                                       else u"?", lim.get("unit") or u"", lim.get("kind") or u"", prog)
        if len(analytes) > 1:
            text += u" · %s" % (lim.get("label") or lim["id"])
        for m in _limit_matrices(profile, lim):
            off = lim["id"] in _rf.limits_off(profile, m)
            entry = {"text": text + (u" · not evaluated" if off else u"")
                             + (u" · not confirmed" if not lim.get("verified") else u""),
                     "warn": not lim.get("verified"), "off": off}
            for kw in analytes:
                out.setdefault((m, kw), []).append(entry)
    return out


def reporting_limit_rows(profile, env=None):
    """One group per supported matrix, one row per analyte that matrix REPORTS
    (the analyte x matrix inclusion grid decides). The group's unit is the matrix's unit_map
    entry: a limit is entered in, and printed with, the unit the method
    reports that matrix in. Beside it, the regulatory limits for the analyte
    in that matrix (read-only, from env)."""
    titles = _analyte_titles(profile)
    limits = _limits_for(profile, env)
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    units = profile.get("unit_map") or {}
    groups, rows = [], []
    for matrix in profile.get("supported_matrices") or []:
        groups.append({"key": matrix, "label": matrix, "unit": units.get(matrix, u"")})
        for kw in profile.get("master_analyte_set") or []:
            if (inclusion.get(kw) or {}).get(matrix, True) is False:
                continue
            row = {"key": (matrix, kw), "group": matrix,
                   "label": titles.get(kw, kw), "sublabel": kw,
                   "info": {"al": limits.get((matrix, kw)) or []}}
            rl = _cal.derived_rl(profile, matrix, kw)
            if rl is not None:
                # blank = the analyte's lowest calibrator; a typed RL overrides it
                row["placeholders"] = {"rl": u"%s (lowest cal.)" % derived_rl_hint(rl, profile, matrix)}
                row["derived_rl"] = rl
            rows.append(row)
    return groups, rows


def _mdl_not_above_rl(row, values):
    rl, mdl = values.get(u"f__rl"), values.get(u"f__mdl")
    if rl is None:
        rl = row.get("derived_rl")                 # the lowest calibrator
    if rl is not None and mdl is not None and mdl > rl:
        return u"%s in %s: the MDL (%s) is above the RL (%s)." % (
            row["sublabel"], row["group"], mdl, rl)
    return None


# Calibration levels: sample-equivalent ppt, lowest
# first. The lowest is every analyte's default RL; the curve suggests the
# spike levels.
from senaite.pfas import calibration_levels as _cal


def _sig(v):
    return _cal.fmt(v)


def derived_rl_hint(rl, profile=None, matrix=None):
    """The lowest calibrator as an RL field shows it when no RL is typed:
    the one text every RL cell and editor uses for it, rounded as the
    certificate prints that matrix's RL (reported_text)."""
    return reported_text(rl, profile, matrix)


# The Reporting Limits columns that print on the certificate and the EDD
# (coa_format.format_rl): each is saved rounded as it prints, so the stored
# value is the printed one.
REPORTED_COLUMNS = (u"rl", u"mdl")


def reported_figures(profile, matrix=None):
    """(significant figures, rounding rule) a reported value of `matrix`
    prints with: the method x matrix certificate format as the certificate
    resolves it (report_format.resolve, coa_format.format_params); a value
    with no matrix takes the "All matrices" row, then the built-in
    default."""
    from senaite.pfas import coa_format
    fmt = _rf.resolve(profile or {}, matrix or _rf.ALL)
    _nd, n, rule = coa_format.format_params(fmt)
    return n, rule


def reported_text(value, profile=None, matrix=None):
    """A reported value as the certificate prints it (coa_format.format_rl
    at the matrix's figures and rule); u"" for none."""
    from senaite.pfas import coa_format
    if value is None:
        return u""
    n, rule = reported_figures(profile, matrix)
    return coa_format.format_rl(value, n, rule)


def reported_value(value, profile=None, matrix=None):
    """The number a reported value is stored as: rounded as it prints
    (reported_text), kept a number. Anything that is not a number (None, a
    word, a removal) is returned as it is."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    text = reported_text(value, profile, matrix)
    return float(text) if text else value


def _store_reported(stored, row, column, value):
    """Reporting Limits: an RL or MDL is saved rounded to its matrix's
    significant figures by its rounding rule; the row's group is its
    matrix."""
    if column.path[0] not in REPORTED_COLUMNS:
        return value
    return reported_value(value, stored, row.get("group"))


def rounded_on_save(profile, env=None):
    """{(matrix, keyword): {column: (stored, saved as text)}} for each
    stored RL or MDL the Reporting Limits rows list that the next save
    stores differently (_store_reported): what the editor shows before a
    save."""
    out = {}
    entries = (profile or {}).get("reporting_limits") or {}
    for row in reporting_limit_rows(profile or {}, env)[1]:
        matrix, kw = row["key"]
        entry = (entries.get(matrix) or {}).get(kw) or {}
        for col in REPORTED_COLUMNS:
            v = entry.get(col)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if reported_value(v, profile, matrix) != v:
                out.setdefault((matrix, kw), {})[col] = (v, reported_text(v, profile, matrix))
    return out


def read_cal_levels(profile):
    return [{"name": r.get("name") or u"CAL-%d" % (i + 1), "conc": r.get("conc")}
            for i, r in enumerate(_cal.rows(profile))]


def write_cal_levels(profile, rows):
    calib = profile.setdefault("instrument_verification", {}).setdefault("calibration", {})
    calib["levels"] = sorted(({"name": r["name"], "conc": r.get("conc")} for r in rows),
                             key=lambda r: (r["conc"] is None, r["conc"]))
    return profile


def check_cal_levels(profile, rows):
    errors = [u"%s: enter its concentration." % r["name"] for r in rows if r.get("conc") is None]
    vals = [r["conc"] for r in rows if r.get("conc") is not None]
    if len(vals) != len(set(vals)):
        errors.append(u"Two calibration levels have the same concentration.")
    return errors


CAL_LEVELS = cf.Collection(
    id=u"cal_levels", title=u"Calibration levels", noun=u"level", allow_empty=True,
    columns=[cf.Field("name", u"Level", kind=cf.TEXT, placeholder=u"CAL-n"),
             cf.Field("conc", u"Concentration", greater_than=0,
                      placeholder=u"in the level unit")],
    read=read_cal_levels, write=write_cal_levels, check=check_cal_levels)


def _levels_text(lv):
    if not lv:
        return u"no levels"
    return u"%s to %s (%d points)" % (_sig(lv[0]), _sig(lv[-1]), len(lv))


def analyte_scale_rows(profile):
    """One row per analyte in the method: its multiple of the base ladder and
    its highest standard; the note shows the ladder that results."""
    titles = _analyte_titles(profile)
    rows = [{"key": (kw,), "group": u"cal_scale", "label": titles.get(kw, kw), "sublabel": kw,
             "note": _levels_text(_cal.levels(profile, kw)), "warn": False}
            for kw in profile.get("master_analyte_set") or []]
    return _one_group(u"cal_scale", u"Per-analyte range"), rows


ANALYTE_SCALE = cf.Table(
    id=u"cal_scale", title=u"Per-analyte calibration range",
    base=("instrument_verification", "calibration", "analyte_scale"),
    columns=[cf.Field("factor", u"Multiple of the method\u2019s ladder", greater_than=0, placeholder=u"1"),
             cf.Field("max", u"Highest standard", greater_than=0, help=u"Blank: no cap.")],
    rows=analyte_scale_rows)


# QC composition: what a run must contain beyond
# the run template, read by the Run Builder (ruleset composition keys).
# Blank = the method does not require it. A project can override both.
# The QC an extraction batch can hold, in batch order: its one list.
from senaite.pfas.extraction_batch import QC_ROLES as EXTRACTION_QC_TYPES, blank_count as _blank_count


PER_BATCH = u"Per worksheet"


def _per_batch_field(qc):
    # how many of each QC an extraction batch is given when its QC is
    # populated from the method profile or project plan; an empty box shows
    # what the batch then gets (extraction_batch.blank_count)
    return cf.Field("%s.per_batch" % qc, u"%s per worksheet" % qc, kind=cf.INT, minimum=0,
                    resolved=lambda profile, env=None: _blank_count(profile, qc))


QC_COMPOSITION = cf.Section(
    id=u"qc_comp", title=u"QC composition", base=("qc_acceptance",),
    groups=[(u"QC composition", [
        cf.Field("LFSM.frequency", u"LFSM every N field samples", kind=cf.INT, minimum=1,
                 help=u"The Run Builder adds one LFSM after every Nth field sample; "
                      u"blank = only what the run template holds."),
        cf.Field("Dup.duplicate_all_samples", u"Duplicate every field sample",
                 kind=cf.CHOICE, blank=u"remove",
                 choices=[(u"", u"No (not required)"), (u"yes", u"Yes")],
                 help=u"The Run Builder injects a duplicate straight after each field sample."),
    ]), (PER_BATCH, [_per_batch_field(qc) for qc in EXTRACTION_QC_TYPES])],
    # the rule every empty per-batch box follows: one line above the boxes
    group_help={PER_BATCH: u"Blank: one for a QC type the method switches on, else none; "
                                         u"none for the sample duplicate, which stands in for the LFSMD."})
# the rule an empty per-batch box follows, as the group's help line says it
PER_BATCH_HELP = QC_COMPOSITION.group_help[PER_BATCH]


# How many an extraction batch may hold, its QC counted or not. Blank = no
# limit. A batch over it is held: its labels are not issued
# (extraction_batch.problems).
EXTRACTION_BATCH = cf.Section(
    id=u"xbatch", title=u"Worksheet size", base=("extraction_batch",),
    groups=[(u"Worksheet size", [
        cf.Field("max_size", u"Most per worksheet", kind=cf.INT, minimum=1,
                 help=u"Blank: no limit."),
        cf.Field("count_qc", u"QC samples count towards the worksheet size", kind=cf.BOOL,
                 help=u"On: the QC samples count towards the most per worksheet."),
    ])])


# The labels an extraction batch issues: each container (vial, sample
# bottle, centrifuge tubes), how many of it, and whether it is labelled for
# every member or for samples only (a blank has no sample bottle). Read by
# the batch page's labels step.
LABEL_FOR = [(u"all", u"Every member"), (u"samples", u"Samples only")]


def _labels_read(profile):
    return [dict(r) for r in profile.get("extraction_labels") or [] if isinstance(r, dict)]


def _labels_write(profile, rows):
    out = []
    for r in rows:
        name = (r.get("container") or u"").strip()
        if not name:
            continue
        out.append({"container": name, "count": int(r.get("count") or 1),
                    "for": r.get("for") or u"all"})
    _set(profile, "extraction_labels", out)
    return profile


EXTRACTION_LABELS = cf.Collection(
    id=u"lbl", title=u"Extraction labels", noun=u"container", allow_empty=True,
    columns=[cf.Field("container", u"Container", kind=cf.TEXT, placeholder=u"e.g. Centrifuge tube"),
             cf.Field("count", u"Labels each", kind=cf.INT, minimum=1, placeholder=u"1"),
             cf.Field("for", u"For", kind=cf.CHOICE, choices=LABEL_FOR)],
    read=_labels_read, write=_labels_write)


# ── Solvent channels: what the LC and an automated SPE system run on ─────────

SOLVENT_PLACES = [(u"lc", u"LC"), (u"spe", u"SPE")]


def _solvents_read(profile):
    return [{"channel": r.get("channel") or u"", "what": r.get("what") or u"",
             "used_on": r.get("used_on") or u"lc", "stage": r.get("stage")}
            for r in profile.get("solvent_channels") or [] if isinstance(r, dict)]


def _solvents_write(profile, rows):
    out = []
    for r in rows:
        ch = (u"%s" % (r.get("channel") or u"")).strip()
        if not ch:
            continue
        place = r.get("used_on") if r.get("used_on") in dict(SOLVENT_PLACES) else u"lc"
        stage = r.get("stage")
        out.append({"channel": ch, "what": (r.get("what") or u"").strip(), "used_on": place,
                    "stage": int(stage) if place == u"spe" and stage not in (None, u"") else None})
    _set(profile, "solvent_channels", out)
    return profile


def _solvents_check(profile, rows):
    errors, seen = [], set()
    for r in rows:
        ch, place = (u"%s" % (r.get("channel") or u"")).strip(), r.get("used_on") or u"lc"
        if place == u"spe" and r.get("stage") in (None, u""):
            errors.append(u"SPE channel %s: enter the extraction stage it is used at." % ch)
        if (place, ch) in seen:
            errors.append(u"Channel %s is listed twice for the %s." % (ch, dict(SOLVENT_PLACES)[place]))
        seen.add((place, ch))
    return errors


def solvent_channels(profile, used_on):
    """[{"channel", "what", "stage"}] the method names for the LC ("lc") or
    an automated SPE system ("spe")."""
    return [{"channel": r["channel"], "what": r["what"], "stage": r["stage"]}
            for r in _solvents_read(profile) if r["used_on"] == used_on and r["channel"]]


def _solvents_at(place, columns, title):
    """One place's channels (LC on Run Template, SPE on Lab Workflow) under
    the one stored list: a save rewrites its own rows and keeps the others'."""
    def read(profile):
        return [dict((k, r[k]) for k in (u"channel", u"what", u"stage")) for r in _solvents_read(profile)
                if r["used_on"] == place]

    def write(profile, rows):
        mine = [dict(r, used_on=place) for r in rows]
        others = [r for r in _solvents_read(profile) if r["used_on"] != place]
        return _solvents_write(profile, mine + others if place == u"lc" else others + mine)

    def check(profile, rows):
        return _solvents_check(profile, [dict(r, used_on=place) for r in rows])
    return cf.Collection(id=u"solv" if place == u"lc" else u"solv_" + place, title=title,
                         noun=u"channel", allow_empty=True, columns=columns,
                         read=read, write=write, check=check)


SOLVENT_LC = _solvents_at(u"lc", [cf.Field("channel", u"Channel", kind=cf.TEXT, placeholder=u"A1"),
                                  cf.Field("what", u"What it is", kind=cf.TEXT, placeholder=u"Methanol")],
                          u"LC channels")
SOLVENT_SPE = _solvents_at(u"spe", [cf.Field("channel", u"Channel", kind=cf.TEXT, placeholder=u"1"),
                                    cf.Field("what", u"What it is", kind=cf.TEXT, placeholder=u"Methanol"),
                                    cf.Field("stage", u"Extraction stage", kind=cf.INT, minimum=1)],
                           u"SPE channels")


REPORTING_LIMITS = cf.Table(
    id=u"rl", title=u"Reporting Limits", base=("reporting_limits",),
    columns=[cf.Field("rl", u"RL", minimum=0), cf.Field("mdl", u"MDL", minimum=0)],
    rows=reporting_limit_rows, rows_take_env=True, check=_mdl_not_above_rl,
    info=[(u"al", u"Action level / MCL")], store=_store_reported)

# ── Matrices & Units: one row per matrix, five stored keys ───────────────────

COMMON_UNITS = [u"ng/kg", u"ug/kg", u"ng/L", u"ng/mL", u"ug/L", u"mg/kg", u"pg/g"]


def unit_choices(profile, env=None):
    """Every common unit plus every unit already in use, so an existing choice
    is never silently dropped from the list it was chosen from."""
    used = sorted(set(u for u in (profile.get("unit_map") or {}).values()
                      if u and u not in COMMON_UNITS))
    return [(u, u) for u in COMMON_UNITS + used]


def core_sample_types():
    """Titles of the core Sample Types: a method's matrices are picked from
    them (core owns the name). [] outside Plone, where no API with a
    catalog tool is found."""
    try:
        from bika.lims import api
    except ImportError:
        return []
    if not hasattr(api, "get_tool"):
        return []
    cat = api.get_tool("senaite_catalog_setup")
    return sorted(set(b.getObject().Title() for b in cat(portal_type="SampleType", is_active=True)))


def matrix_choices(profile, env=None):
    """The core Sample Types; a matrix already on the method that core does
    not have is kept and marked, never silently dropped."""
    core = core_sample_types()
    out = [(t, t) for t in core]
    for m in profile.get("supported_matrices") or []:
        if m not in core:
            out.append((m, u"%s (not a core Sample Type)" % m))
    return out


def read_matrices(profile):
    aliases = profile.get("matrix_aliases") or {}
    units = profile.get("unit_map") or {}
    classes = profile.get("matrix_classes") or {}
    codes = profile.get("matrix_codes") or {}
    return [{"name": m,
             "injection_code": codes.get(m) or None,
             "aliases": u", ".join(aliases.get(m) or []),
             "unit": units.get(m) or None,
             "matrix_class": classes.get(m) or None}
            for m in profile.get("supported_matrices") or []]


def _none_set(value):
    """The method sets no holding time (holding_time.NONE_SET)."""
    return isinstance(value, (type(u""), type(""))) and value.strip().lower() == u"none"


def _set(profile, key, value):
    """Write a key, but leave a MISSING key missing when the new value is
    empty: an unchanged save must not turn "absent" into "[]" (EPA 537.1 has
    no matrix_aliases key at all)."""
    if value or key in profile:
        profile[key] = value


def write_matrices(profile, rows):
    """The matrix list and what each row carries. The clocks are set on
    Storage and holding; here a matrix's clocks follow it: a removed matrix
    leaves every clock, a new one is listed in the sample clock as unset
    (the review refuses to judge rather than passing it)."""
    names = [r["name"] for r in rows]
    aliases, units = {}, {}
    # drawn elsewhere or only for some methods: a row without the
    # column keeps what is stored for its matrix
    classes = dict((m, v) for m, v in (profile.get("matrix_classes") or {}).items() if m in names)
    codes = dict((m, v) for m, v in (profile.get("matrix_codes") or {}).items() if m in names)
    old = profile.get("holding_times") or {}
    holding = dict((m, old.get(m)) for m in names)
    for key in ("extract_holding_times", "processed_holding_times"):
        kept = dict((m, v) for m, v in (profile.get(key) or {}).items() if m in names)
        _set(profile, key, kept)
    for r in rows:
        if "injection_code" in r:
            code = (r.get("injection_code") or u"").strip().upper()
            if code:
                codes[r["name"]] = code
            else:
                codes.pop(r["name"], None)
        if "matrix_class" in r:
            if r.get("matrix_class"):
                classes[r["name"]] = r["matrix_class"]
            else:
                classes.pop(r["name"], None)
        parts = [a.strip() for a in (r.get("aliases") or u"").split(u",") if a.strip()]
        if parts:
            aliases[r["name"]] = parts
        if r.get("unit"):
            units[r["name"]] = r["unit"]
    profile["supported_matrices"] = names
    _set(profile, "matrix_aliases", aliases)
    _set(profile, "unit_map", units)
    _set(profile, "holding_times", holding)
    _set(profile, "matrix_classes", classes)
    _set(profile, "matrix_codes", codes)
    if "matrix_uid_map" in profile:
        profile["matrix_uid_map"] = dict((k, v) for k, v in
                                         (profile.get("matrix_uid_map") or {}).items()
                                         if k in names)
    return profile


def matrix_references(profile, removed):
    """What still points at, or holds data for, a matrix title that is going
    away. Reported as a refusal rather than cleaned up: a matrix factor,
    nominal amount, holding time, injection code, matrix class, spike level
    or reporting limit is lab data, and deciding it is disposable is not
    this form's call. A holding time of "none" is no value: the
    method sets none, so it holds nothing."""
    removed = set(removed)
    found = []
    factors = [e.get("matrix") for e in (profile.get("matrix_factors") or [])
               if isinstance(e, dict)]
    hit = sorted(set(f for f in factors if f in removed))
    if hit:
        found.append(u"matrix factors for %s" % u", ".join(hit))
    hit = sorted(m for m in (profile.get("nominal_amounts") or {}) if m in removed)
    if hit:
        found.append(u"a nominal amount for %s" % u", ".join(hit))
    held = set()
    for _key, _l, _c, _st, hold in KEPT:
        held.update(m for m, v in ((profile or {}).get(hold) or {}).items()
                    if m in removed and v not in (None, u"") and not _none_set(v))
    if held:
        found.append(u"holding times for %s" % u", ".join(sorted(held)))
    from senaite.pfas import matrix_temperature as mt
    hit = sorted(m for m in removed if any(mt.is_set(profile, k, m) for k in mt.KEYS))
    if hit:
        found.append(u"its own temperature ranges for %s" % u", ".join(hit))
    hit = sorted(m for m, v in (profile.get("matrix_codes") or {}).items() if m in removed and v)
    if hit:
        found.append(u"an injection code for %s" % u", ".join(hit))
    hit = sorted(m for m, v in (profile.get("matrix_classes") or {}).items() if m in removed and v)
    if hit:
        found.append(u"a matrix class for %s" % u", ".join(hit))
    hit = sorted(m for m in (profile.get("spike_levels") or {}) if m in removed)
    if hit:
        found.append(u"spike levels for %s" % u", ".join(hit))
    included = set()
    for per_matrix in (profile.get("analyte_matrix_inclusion") or {}).values():
        if isinstance(per_matrix, dict):
            included.update(m for m in per_matrix if m in removed)
    if included:
        found.append(u"analyte x matrix inclusion for %s" % u", ".join(sorted(included)))
    hit = sorted(m for m, v in (profile.get("reporting_limits") or {}).items()
                 if m in removed and v)
    if hit:
        found.append(u"reporting limits for %s" % u", ".join(hit))
    for qc, entry in sorted((profile.get("qc_acceptance") or {}).items()):
        for t in (entry.get("tiers") or []) if isinstance(entry, dict) else []:
            hit = sorted(m for m in _listed_matrices(profile, t) if m in removed) if isinstance(t, dict) else []
            if hit:
                found.append(u"the matrix list of tier %s (%s) on QC criteria for %s" % (
                    t.get("name") or u"", qc, u", ".join(hit)))
        cells = (entry.get(CELLS_KEY) or []) if isinstance(entry, dict) else []
        hit = sorted(set(c.get("matrix") for c in cells if isinstance(c, dict) and c.get("matrix") in removed))
        if hit:
            found.append(u"%s settings on one cell on QC criteria for %s" % (qc, u", ".join(hit)))
    hit = sorted(m for m in ((profile.get("report_format") or {})) if m in removed)
    if hit:
        found.append(u"the certificate format on Run & reporting for %s" % u", ".join(hit))
    return found


def check_matrices(profile, rows):
    names = set(r["name"] for r in rows)
    removed = [m for m in (profile.get("supported_matrices") or []) if m not in names]
    orphans = matrix_references(profile, removed) if removed else []
    if orphans:
        return [u"Removing or renaming %s would orphan %s. Move or clear that data "
                u"first, or restore the matrix name." % (
                    u", ".join(sorted(removed)), u"; ".join(orphans))]
    return []


_MATRIX_COLUMNS = [
    # a core Sample Type: core owns matrix names
    cf.Field("name", u"Matrix (Sample Type)", kind=cf.CHOICE, choices=matrix_choices),
    cf.Field("aliases", u"Aliases (comma-separated)", kind=cf.TEXT, widget=u"chips",
             placeholder=u"deer muscle, venison, beef"),
    cf.Field("unit", u"Reporting Unit", kind=cf.CHOICE, choices=unit_choices)]
# the class an extracted standard's matrix limits are taken from (SUR
# Limits): drawn only when the Engine judges them
_MATRIX_CLASS = cf.Field("matrix_class", u"Matrix class (SUR limits)", kind=cf.CHOICE,
                         blank=u"remove", choices=lambda profile, env=None: matrix_class_choices())


def _matrix_columns(profile):
    judged = _engine_module().engine(profile or {})["eis_recovery_limits"]
    return _MATRIX_COLUMNS + ([_MATRIX_CLASS] if judged else [])


# a matrix is added here; it is never renamed here (core owns Sample Type
# names) nor removed (the Matrices tab's remove action, refused while
# matrix_references names anything)
MATRICES = cf.Collection(
    id=u"mtx", title=u"Matrices & Units", noun=u"matrix",
    columns=_matrix_columns, read=read_matrices, write=write_matrices, check=check_matrices,
    keep_keys=True)


# the matrix in injection names (injection_names.py): DW, GW, MILK -- on
# Engine, Method & names, one row per matrix of the method
def _mcode_rows(profile, env=None):
    return ([{"key": u"mcodes", "label": u"Matrix codes in injection names", "unit": u""}],
            [{"key": (m,), "group": u"mcodes", "label": m} for m in (profile or {}).get("supported_matrices") or []])


def _mcode_read(profile):
    codes = (profile or {}).get("matrix_codes") or {}
    return dict(((m,), {"code": codes.get(m) or None}) for m in (profile or {}).get("supported_matrices") or [])


def _mcode_write(profile, updates, env=None):
    codes = dict(profile.get("matrix_codes") or {})
    for (m,), vals in updates.items():
        code = (vals.get((u"code",)) or u"").strip().upper()
        if code:
            codes[m] = code
        else:
            codes.pop(m, None)
    _set(profile, "matrix_codes", codes)
    return profile


MATRIX_CODES = cf.Table(
    id=u"engine_mcodes", title=u"Matrix codes", base=(),
    columns=[cf.Field("code", u"Injection code", kind=cf.TEXT, placeholder=u"DW")],
    rows=_mcode_rows, read=_mcode_read, write=_mcode_write, row_heading=u"Matrix")

# ── Sample Corrections: salt factors and matrix factors ──────────────────────
# Both are stored as LISTS holding only rows that change something; the
# default factor 1.0 is a placeholder, never written as a value.


def _one_group(key, label):
    return [{"key": key, "label": label, "unit": u""}]


def salt_rows(profile):
    titles = _analyte_titles(profile)
    rows = [{"key": (kw,), "group": u"salt", "label": titles.get(kw, kw), "sublabel": kw}
            for kw in profile.get("master_analyte_set") or []]
    return _one_group(u"salt", u"Salt adjustment"), rows


def read_salt(profile):
    out = {}
    for r in profile.get("salt_adjustment_factors") or []:
        if isinstance(r, dict) and r.get("analyte"):
            out[(r["analyte"],)] = {"factor": r.get("factor"),
                                    "lot_uid": r.get("lot_uid") or r.get("source") or None}
    return out


_SALT = "salt_adjustment_factors"
_COPIES = ("lot_number", "lot_name")


def recorded_lots(entries, profile):
    """{lot id: {"lot_number", "lot_name"}}: the copy of each salt row's lot
    its configuration history last recorded (`entries`, the method
    profile's history, newest first), for a row that no longer carries its
    own. A change to one row's copy names the row by its place in the list,
    read against the rows as they are now only while no newer change has
    reordered the list."""
    rows = [r for r in (profile or {}).get(_SALT) or [] if isinstance(r, dict)]
    out = {}

    def keep(uid, key, value):
        if uid and value and key not in out.setdefault(uid, {}):
            out[uid][key] = value
    in_place = True
    for e in entries or []:
        moved = False
        for ch in (e or {}).get("changes") or []:
            path = [u"%s" % x for x in ch.get("path") or []]
            if not path or path[0] != _SALT:
                continue
            if len(path) == 1:
                for value in (ch.get("after"), ch.get("before")):
                    for r in value if isinstance(value, list) else []:
                        if isinstance(r, dict):
                            for key in _COPIES:
                                keep(r.get("lot_uid") or r.get("source"), key, r.get(key))
                moved = True
            elif len(path) == 3 and path[2] in _COPIES and path[1].isdigit():
                i = int(path[1])
                if in_place and i < len(rows):
                    keep(rows[i].get("lot_uid") or rows[i].get("source"), path[2],
                         ch.get("after") or ch.get("before"))
            else:
                moved = True
        if moved:
            in_place = False
    return dict((k, v) for k, v in out.items() if v)


def _gone_lot_label(row, recorded=None):
    """What a salt row calls a lot the inventory no longer lists: the name and
    number copied onto the row when it was saved, else the copy its
    configuration history recorded (recorded_lots), else that it is gone."""
    copy_ = (recorded or {}).get(row.get("lot_uid") or row.get("source")) or {}
    name = row.get("lot_name") or copy_.get("lot_name") or u""
    number = row.get("lot_number") or copy_.get("lot_number") or u""
    if not (name or number):
        return u"Lot no longer in the inventory"
    return (u"%s \u2014 lot %s" % (name, number) if name and number else name or u"Lot %s" % number) \
        + u", no longer in the inventory"


def lot_choices(profile, env=None):
    """Standard / reference-material lots from the reagent inventory (the page
    supplies them in env; their labels already say EXPIRED where it applies,
    and an expired lot stays pickable). A lot a row names that the inventory
    no longer lists is offered by the number and name its row copied when it
    was saved, else as gone (its internal id is never shown), so the row keeps
    it."""
    out = [(o["uid"], o["label"]) for o in ((env or {}).get("standard_lots") or [])]
    known = set(uid for uid, _label in out)
    for r in profile.get("salt_adjustment_factors") or []:
        lot = (r.get("lot_uid") or r.get("source")) if isinstance(r, dict) else None
        if lot and lot not in known:
            out.append((lot, _gone_lot_label(r, (env or {}).get("recorded_lots"))))
            known.add(lot)
    return out


def _merge_rows(existing, key_field, updates, order, build):
    """Existing rows in their stored ORDER, each updated (or dropped when
    build() returns None); then new rows in panel order. A row the page did
    not list is kept as it was -- e.g. an analyte no longer in the panel."""
    out, done = [], set()
    for row in existing:
        key = (row.get(key_field),)
        if key in updates:
            new = build(key[0], updates[key], row)
            if new is not None:
                out.append(new)
            done.add(key)
        else:
            out.append(row)
    for key in order:
        if key in updates and key not in done:
            new = build(key[0], updates[key], {})
            if new is not None:
                out.append(new)
    return out


def write_salt(profile, updates, env=None):
    return _write_salt(profile, updates, env, profile.get("master_analyte_set") or [])


def _write_salt(profile, updates, env, order):
    # The lot is the reagent inventory's: the row names it by id and shows the
    # live lot while it exists. It also keeps a copy of the lot's number and
    # name, taken when saved, so a lot deleted later can still be named.
    # A row the page did not post (an analyte's on the standards tab, a
    # standard's on the analytes tab) is kept as stored.
    live = dict((o.get("uid"), o) for o in (env or {}).get("standard_lots") or [])

    def build(kw, vals, old):
        factor, lot = vals.get(("factor",)), vals.get(("lot_uid",)) or u""
        if (factor is None or factor == 1.0) and not lot:
            return None                     # no correction and no lot: no row
        row = {"analyte": kw, "factor": 1.0 if factor is None else factor}
        if lot:
            row["lot_uid"] = lot
            src = live.get(lot)
            if src is None and (old.get("lot_uid") or old.get("source")) == lot:
                src = {"lot_number": old.get("lot_number"), "name": old.get("lot_name")}
            for key, val in (("lot_number", (src or {}).get("lot_number")),
                             ("lot_name", (src or {}).get("name"))):
                if val:
                    row[key] = val
        return row

    existing = [r for r in (profile.get("salt_adjustment_factors") or []) if isinstance(r, dict)]
    ordered = [(kw,) for kw in order if (kw,) in updates]
    out = _merge_rows(existing, "analyte", updates, ordered, build)
    if out or "salt_adjustment_factors" in profile:
        profile["salt_adjustment_factors"] = out
    return profile


SALT_COLUMNS = [cf.Field("factor", u"Factor", greater_than=0, maximum=1, placeholder=u"1.0"),
                cf.Field("lot_uid", u"CoA Lot", kind=cf.CHOICE, choices=lot_choices)]

SALT = cf.Table(
    id=u"salt", title=u"Salt Adjustment Factors", base=("salt_adjustment_factors",),
    columns=SALT_COLUMNS, rows=salt_rows, read=read_salt, write=write_salt)


# A labelled standard's salt factor: kept in the same list as an analyte's,
# keyed by the standard, and posted by the Isotope standards tab. It turns
# the standard's stated amounts to the acid form before its response ratio
# is formed (the worker's raw_run); unset reads 1.0.
def salt_std_rows(profile):
    rows = [{"key": (kw,), "group": u"salt_std", "label": kw, "sublabel": u""}
            for kw in sorted(_ls.grid(profile))]
    return _one_group(u"salt_std", u"Salt adjustment"), rows


def read_salt_std(profile):
    grid = _ls.grid(profile)
    return dict((k, v) for k, v in read_salt(profile).items() if k[0] in grid)


def write_salt_std(profile, updates, env=None):
    return _write_salt(profile, updates, env, sorted(_ls.grid(profile)))


SALT_STD = cf.Table(
    id=u"salt_std", title=u"Salt Adjustment Factors of the isotope standards", base=("salt_adjustment_factors",),
    columns=SALT_COLUMNS, rows=salt_std_rows, read=read_salt_std, write=write_salt_std, row_heading=u"Standard")


def matrix_factor_rows(profile):
    uid_map = profile.get("matrix_uid_map") or {}
    rows = []
    for m in profile.get("supported_matrices") or []:
        linked = bool(uid_map.get(m))
        rows.append({"key": (m,), "group": u"mf", "label": m,
                     "note": None if linked else u"not a core sample type",
                     "warn": not linked})
    return _one_group(u"mf", u"Matrix adjustment"), rows


def nominal_amount_rows(profile):
    rows = [{"key": (m,), "group": u"nom", "label": m}
            for m in profile.get("supported_matrices") or []]
    return _one_group(u"nom", u"Nominal amount"), rows


def read_nominal_amounts(profile):
    return dict(((m,), dict(v)) for m, v in (profile.get("nominal_amounts") or {}).items()
                if isinstance(v, dict))


def write_nominal_amounts(profile, updates, env=None):
    """{matrix: {"amount", "unit"}}; a matrix with no amount has no row."""
    out = dict(profile.get("nominal_amounts") or {})
    for (m,), vals in updates.items():
        amount, unit = vals.get(("amount",)), vals.get(("unit",))
        if amount is None:
            out.pop(m, None)
        else:
            out[m] = {"amount": amount, "unit": unit or u"g"}
    if out or "nominal_amounts" in profile:
        profile["nominal_amounts"] = out
    return profile


def read_matrix_factors(profile):
    out = {}
    for e in profile.get("matrix_factors") or []:
        if isinstance(e, dict) and e.get("matrix"):
            out[(e["matrix"],)] = {"factor": e.get("factor")}
    return out


def write_matrix_factors(profile, updates, env=None):
    uid_map = profile.get("matrix_uid_map") or {}

    def build(m, vals, old):
        factor = vals.get(("factor",))
        if factor is None or factor == 1.0:
            return None                     # 1.0 is no correction: no row
        return {"matrix": m, "factor": factor,
                "sampletype_uid": uid_map.get(m) or old.get("sampletype_uid", u"")}

    existing = [e for e in (profile.get("matrix_factors") or []) if isinstance(e, dict)]
    ordered = [(m,) for m in profile.get("supported_matrices") or [] if (m,) in updates]
    out = _merge_rows(existing, "matrix", updates, ordered, build)
    if out or "matrix_factors" in profile:
        profile["matrix_factors"] = out
    return profile


SAMPLE_CORRECTION = cf.Section(
    id=u"scorr", title=u"Sample correction", base=(),
    groups=[(u"Where results are put on the sample basis", [
        cf.Field("sample_correction", u"Per-sample correction", kind=cf.CHOICE, blank=u"remove",
                 placeholder=u"Nominal matrix factor per sample type (below)",
                 choices=[(u"instrument", u"In the MS software: results arrive per sample, no factor applied"),
                          (u"lims", u"Back-calculated in the LIMS: final volume / sample amount, per sample")],
                 help=u"Uses each sample's logged amount and extract volume; without both, "
                      u"the nominal factor applies and the sample is flagged."),
        #: either; matters only when the LIMS corrects per sample
        cf.Field("spike_basis", u"Spike levels are entered", kind=cf.CHOICE, blank=u"remove",
                 placeholder=u"After the adjustment: used as entered",
                 choices=[(u"before", u"Before the adjustment: scaled by nominal / actual amount")],
                 help=u"Before: each spiked portion's expected level is scaled by the "
                      u"matrix's nominal amount (below) over the portion's actual amount."),
    ]), (u"Method blank", [
        # a per-method switch, off by default (EPA 537.1 does
        # not subtract); off, a result at or below the blank reads "< LOD"
        cf.Field("blank_subtraction", u"Subtract the worksheet's method blank from each result",
                 kind=cf.BOOL,
                 help=u"Off: a result at or below the blank reads < LOD. On: subtracted, "
                      u"stated on the certificate."),
    ])])


# What the method calls its check standards in LIMS-issued injection names:
# EPA 537.1 says CCC (continuing calibration check, the
# CCV role) and QCS (quality control sample, the ICV role). The ROLE is what
# the pipeline judges -- read from the Run Builder's record, never the name.
QC_NAME_CODES = cf.Section(
    id=u"qcnames", title=u"Check standard names", base=("qc_name_codes",),
    groups=[(u"Injection names (naming only)", [
        # the method's code that starts every injection name (injection_names.py)
        cf.Field("METHOD", u"Method", kind=cf.TEXT, placeholder=u"code", blank=u"remove"),
        cf.Field("CCV", u"Continuing check", kind=cf.TEXT, placeholder=u"CCV", blank=u"remove"),
        cf.Field("ICV", u"Initial / second-source check", kind=cf.TEXT, placeholder=u"ICV", blank=u"remove"),
        cf.Field("CCB", u"Solvent blank", kind=cf.TEXT, placeholder=u"CCB", blank=u"remove"),
    ])])


def name_code(profile, code):
    """The method's name for a check role in injection names, else the role."""
    v = ((profile or {}).get("qc_name_codes") or {}).get((code or u"").upper())
    v = (u"%s" % v).strip() if v else u""
    return v.upper().replace(u" ", u"") if v else (code or u"").upper()


# The allowed temperature on receipt, one range per method: the receipt
# judges each sample's CORRECTED temperature against its method's range
# (coc_records.judge_temperatures). Blank = not judged; nothing is seeded --
# the lab enters its method's values.
SAMPLE_RECEIPT = cf.Section(
    id=u"rtemp", title=u"Sample receipt", base=("receipt_temperature",),
    groups=[(u"Allowed temperature on receipt (corrected)", [
        cf.Field("min_c", u"Minimum", unit=u"\u00b0C", range_hi="max_c", scale=(-20, 40)),
        cf.Field("max_c", u"Maximum", unit=u"\u00b0C"),
        # No requirement: nothing is judged on receipt (not a gap to fill)
        cf.Field("none", u"No requirement", kind=cf.CHOICE, choices=[(u"on", u"No requirement")]),
        cf.Field("same_day_on_ice", u"Same-day samples received on ice are not flagged above the maximum",
                 kind=cf.BOOL),
    ])])


# ── Storage and holding ───────────────────────────────────────
# Each kept item -- the sample, the processed (homogenised) sample, the
# extract -- its storage range and its holding days per matrix. The
# Monitoring page judges a fridge or freezer against the range for what it
# holds (facility monitoring). Nothing is seeded: the lab enters every value.
KEPT = [(u"sample", u"Sample", u"Collection to extraction", u"storage_temperature", u"holding_times"),
        (u"processed", u"Processed sample", u"Homogenisation complete to extraction",
         u"storage_temperature_processed", u"processed_holding_times"),
        (u"extract", u"Extract", u"Extraction to analysis", u"storage_temperature_extract",
         u"extract_holding_times")]
_KEPT = dict((k, (st, hold)) for k, _l, _c, st, hold in KEPT)


def storage_range(profile, kept):
    """{"min_c", "max_c"} for a kept item ("sample", "processed", "extract")."""
    return (profile or {}).get(_KEPT.get(kept, (u"storage_temperature",))[0]) or {}


def kept_ranges(entries, profile_of, held=None):
    """[(label, lo, hi)] a monitored unit is judged against: per entry it
    stores, one per distinct range of the matrices it holds (each matrix's
    own over All matrices, matrix_temperature.held_rows), the entry alone
    when they share one. An entry is "MID" (the method's samples, as stored
    before kept items) or "MID:processed" / "MID:extract"; `held` {MID:
    [matrices]} names the matrices held, a method with none all of them."""
    from senaite.pfas import matrix_temperature as mt
    out = []
    for entry in entries or []:
        mid = (u"%s" % entry).partition(u":")[0]
        out.extend(r[:3] for r in mt.held_rows(entry, profile_of(mid) or {}, (held or {}).get(mid)))
    return out


def _hold_columns(profile):
    cols = [cf.Field("min_c", u"Stored at", unit=u"\u00b0C", range_hi="max_c", scale=(-90, 40)),
            cf.Field("max_c", u"Stored at, maximum", unit=u"\u00b0C"),
            # No requirement: the kept item's storage is not judged
            cf.Field("none", u"No requirement", kind=cf.CHOICE, choices=[(u"on", u"No requirement")])]
    return cols + [cf.Field((m,), m, unit=u"days", greater_than=0, words=[u"none"])
                   for m in (profile or {}).get("supported_matrices") or []]


def _hold_rows(profile, env=None):
    matrices = (profile or {}).get("supported_matrices") or []
    homogenised = None if env is None else set((env or {}).get("homogenised") or [])
    rows = []
    for key, label, clock, _st, _h in KEPT:
        ph = {}
        for m in matrices:
            if key == u"processed" and homogenised is not None and m not in homogenised:
                ph[m] = u"not homogenised"
        rows.append({"key": (key,), "group": u"hold", "label": label, "sublabel": clock,
                     "placeholders": ph})
    return [{"key": u"hold", "label": u"Storage and holding", "unit": u""}], rows


def _hold_read(profile):
    out = {}
    for key, _l, _c, st, hold in KEPT:
        rng = (profile or {}).get(st) or {}
        days = (profile or {}).get(hold) or {}
        vals = {"min_c": rng.get("min_c"), "max_c": rng.get("max_c"),
                "none": u"on" if _mt().no_requirement(rng) else None}
        for m in (profile or {}).get("supported_matrices") or []:
            v = days.get(m)
            vals[m] = u"none" if _none_set(v) else v
        out[(key,)] = vals
    return out


def _whole(v):
    return int(v) if isinstance(v, float) and v == int(v) else v


def _hold_write(profile, updates, env=None):
    for key, _l, _c, st, hold in KEPT:
        vals = updates.get((key,))
        if vals is None:
            continue
        rng = dict(profile.get(st) or {})
        for end in (u"min_c", u"max_c"):
            v = vals.get((end,))
            if v is not None or end in rng:
                rng[end] = v
        if vals.get((u"none",)) == u"on":
            rng = {u"none": True}
        else:
            rng.pop(u"none", None)
        if rng or st in profile:
            profile[st] = rng
        days = dict(profile.get(hold) or {})
        for m in profile.get("supported_matrices") or []:
            if (m,) not in vals:
                continue
            v = _whole(vals[(m,)])
            if v is None and key != u"sample":
                days.pop(m, None)
            elif v is not None or m in days:
                days[m] = v
        _set(profile, hold, days)
    return profile


def _hold_row(row, values):
    """Only the sample's clock can be none: the processed sample and the
    extract are judged by days or not at all."""
    if tuple(row["key"]) != (u"sample",) and any(_none_set(v) for v in values.values()):
        return u"%s: only the Sample holding can be none." % row.get("label")
    return None


STORAGE_HOLDING = cf.Table(
    id=u"hold", title=u"Storage and holding", base=(), columns=_hold_columns,
    rows=_hold_rows, rows_take_env=True, read=_hold_read, write=_hold_write, check=_hold_row,
    row_heading=u"Kept")


# ── A matrix's own temperature ranges ─────────────────────────
# Each matrix may set its own storage range for each kept item, its own
# receipt range and its own same-day on ice; what it leaves blank follows
# All matrices (the method's keys above). Stored only where set, in
# <key>_by_matrix {matrix: {min_c, max_c[, same_day_on_ice]}}
# (matrix_temperature); posted from the matrix's row on the Matrices tab.
MX_ICE = ((u"on", u"On"), (u"off", u"Off"))


def _mx_items():
    """[(column prefix, label, method key, scale)]: the kept items, then receipt."""
    from senaite.pfas import matrix_temperature as mt
    store = tuple(_hold_columns({})[0].scale)
    receipt = tuple(SAMPLE_RECEIPT.fields()[0].scale)
    return ([(key, u"%s stored at" % label, mt.storage_key(key), store) for key, label, _c, _st, _h in KEPT] +
            [(u"receipt", u"Allowed on receipt", mt.RECEIPT, receipt)])


def _mt():
    from senaite.pfas import matrix_temperature
    return matrix_temperature


def _mx_columns(profile=None):
    cols = []
    for pre, label, _key, scale in _mx_items():
        # a matrix not homogenised draws no processed range: kept as stored
        kept = pre == u"processed"
        cols += [cf.Field(pre + u"_min", label, unit=u"\u00b0C", range_hi=pre + u"_max", scale=scale,
                          kept_if_absent=kept),
                 cf.Field(pre + u"_max", label + u", maximum", unit=u"\u00b0C", kept_if_absent=kept),
                 cf.Field(pre + u"_none", label + u", no requirement", kind=cf.CHOICE,
                          choices=[(u"on", u"No requirement")], kept_if_absent=kept)]
    return cols + [cf.Field(u"on_ice", u"Same-day on ice", kind=cf.CHOICE, choices=list(MX_ICE))]


def _mx_rows(profile):
    return ([{"key": u"mxtemp", "label": u"Temperature by matrix", "unit": u""}],
            [{"key": (m,), "group": u"mxtemp", "label": m}
             for m in (profile or {}).get("supported_matrices") or []])


def _mx_read(profile):
    from senaite.pfas import matrix_temperature as mt
    out = {}
    for m in (profile or {}).get("supported_matrices") or []:
        vals = {}
        for pre, _l, key, _s in _mx_items():
            mine = mt.own(profile, key, m)
            vals[pre + u"_min"] = mt.number(mine.get("min_c"))
            vals[pre + u"_max"] = mt.number(mine.get("max_c"))
            vals[pre + u"_none"] = u"on" if mt.no_requirement(mine) else None
            if key == mt.RECEIPT and isinstance(mine.get(mt.ICE), bool):
                vals[u"on_ice"] = u"on" if mine[mt.ICE] else u"off"
        out[(m,)] = vals
    return out


def _mx_write(profile, updates, env=None):
    from senaite.pfas import matrix_temperature as mt
    for pre, _l, key, _s in _mx_items():
        mkey = mt.by_matrix(key)
        mapping = dict(profile.get(mkey) or {}) if isinstance(profile.get(mkey), dict) else {}
        for row_key, vals in updates.items():
            m = row_key[0]
            stored = next((k for k in mapping if (u"%s" % k).strip().lower() == m.strip().lower()), m)
            if not any((path,) in vals for path in (pre + u"_min", pre + u"_max", pre + u"_none")):
                continue                # not drawn for this matrix: kept as stored
            entry = {}
            for end, path in ((u"min_c", pre + u"_min"), (u"max_c", pre + u"_max")):
                v = mt.number(vals.get((path,)))
                if v is not None:
                    entry[end] = v
            if key == mt.RECEIPT and vals.get((u"on_ice",)) in (u"on", u"off"):
                entry[mt.ICE] = vals[(u"on_ice",)] == u"on"
            if vals.get((pre + u"_none",)) == u"on":
                entry = {mt.NONE: True}
            if entry:
                mapping[stored] = entry
            else:
                mapping.pop(stored, None)
        _set(profile, mkey, mapping)
    return profile


MATRIX_TEMPERATURES = cf.Table(
    id=u"mxtemp", title=u"Temperature by matrix", base=(), columns=_mx_columns,
    rows=_mx_rows, read=_mx_read, write=_mx_write, row_heading=u"Matrix")

# What a surrogate failure qualifies: the analytes
# linked to it, or -- EPA 537.1 §9.3.5.3, "report all data for that sample as
# suspect" -- every result on the sample.
SURROGATE_SCOPE = cf.Section(
    id=u"surscope", title=u"Surrogate failure", base=(),
    groups=[(u"A surrogate outside its window qualifies", [
        cf.Field("surrogate_failure_scope", u"Results qualified", kind=cf.CHOICE,
                 blank=u"remove",
                 choices=[(u"", u"The analytes linked to the surrogate"),
                          (u"sample", u"Every result on that sample")]),
    ])])


# ── Engine: how this method is judged (method_engine) ────────────────────────
# The worker has one rule interpreter for every method; these settings are
# what differs between methods. Blank / unticked = the feature is off.

def _engine_module():
    from senaite.pfas import method_engine
    return method_engine


ENGINE = cf.Section(
    id=u"engine", title=u"Engine", base=("engine",),
    groups=[
        (u"Surrogates and extracted internal standards", [
            cf.Field("eis_recovery_limits",
                     u"Extracted standards judged per analyte and matrix class",
                     kind=cf.BOOL,
                     help=u"Isotope dilution: shows each SUR's limits per matrix class on "
                          u"Isotope standards; the matrix class is set per matrix on Matrices & Units."),
            cf.Field("eis_default_window", u"An extracted standard's window starts from",
                     kind=cf.CHOICE, blank=u"remove",
                     choices=[(u"", u"Not chosen"),
                              (u"lfsm_tier", u"The first LFSM tier"),
                              (u"surrogate_window", u"The surrogate window")]),
            cf.Field("eis_verify_flag", u"Mark those limits to be confirmed against the method",
                     kind=cf.BOOL),
        ]),
        (u"Calibration", [
            cf.Field("labelled_compound_fit", u"Labelled compounds are calibrated by",
                     kind=cf.CHOICE, blank=u"remove",
                     choices=lambda profile, env=None: [
                         (u"", u"The same fit as the analytes: " + _analytes_fit_words(profile)),
                         (u"mean_response_factor", u"Their mean response factor")]),
        ]),
        (u"Analyte × matrix", [
            cf.Field("inclusion_needs_verification",
                     u"Inclusion is to be confirmed against the published method",
                     kind=cf.BOOL),
        ]),
        # the places a recovery is judged at and every page and printout
        # shows it with (method_engine.recovery_decimals); a save that does
        # not post it keeps the stored value
        (u"Recoveries", [
            cf.Field("recovery_decimals", u"Decimal places for recoveries", kind=cf.INT,
                     minimum=0, maximum=_engine_module().RECOVERY_DECIMALS_MAX, blank=u"remove",
                     resolved=0, kept_if_absent=True, help=u"Blank: whole percent. Checks judge recoveries at these places; reprocess runs after a change."),
        ]),
    ])

STUDY_KIND_CHOICES = [(u"mdl", u"Method detection limit"), (u"pt", u"Proficiency test"),
                      (u"pa", u"Precision and accuracy"), (u"mrl", u"MRL confirmation"),
                      (u"dl", u"Detection limit"), (u"idc", u"Initial demonstration of capability")]

ENGINE_STUDIES = cf.Section(
    id=u"engine_studies", title=u"Studies", base=(),
    groups=[(u"Studies", [
        # what this sets is the QC type a study's blanks come from
        cf.Field("blank_role_name", u"Studies take their blanks from", kind=cf.CHOICE,
                 blank=u"remove",
                 choices=[(u"", u"The first of MB and LRB this method runs"),
                          (u"MB", u"Method Blank (MB)"), (u"LRB", u"Laboratory Reagent Blank (LRB)")]),
        cf.Field("study_kinds", u"Studies this method offers", kind=cf.MULTI,
                 choices=STUDY_KIND_CHOICES),
    ])])


def _fallback_rows(profile):
    return (_one_group(u"fb", u"Surrogate window the method text states"),
            [{"key": (u"surrogate_fallback",), "group": u"fb",
              "label": u"Used when Calibration & CCV sets none"}])


def read_fallback(profile):
    fb = ((profile.get("engine") or {}).get("surrogate_fallback")) or {}
    return {(u"surrogate_fallback",): {"min": fb.get("min"), "max": fb.get("max")}}


def write_fallback(profile, updates, env=None):
    vals = updates.get((u"surrogate_fallback",))
    if vals is None:
        return profile
    lo, hi = vals.get(("min",)), vals.get(("max",))
    eng = profile.get("engine")
    if lo is None and hi is None:
        if isinstance(eng, dict) and "surrogate_fallback" in eng:
            eng["surrogate_fallback"] = None
        return profile
    if not isinstance(eng, dict):
        eng = profile["engine"] = {}
    # the window alone: its source is on the Help page, never stored beside it
    eng["surrogate_fallback"] = {"min": lo, "max": hi}
    return profile


def _check_fallback(row, values):
    lo, hi = values.get(u"f__min"), values.get(u"f__max")
    if (lo is None) != (hi is None):
        return u"Set both ends of the method text's surrogate window, or neither."
    if lo is not None and lo > hi:
        return u"The method text's surrogate window: min is above max."
    return None


ENGINE_FALLBACK = cf.Table(
    id=u"engine_fallback", title=u"Surrogate window the method text states", base=(),
    # the window is one column, a min / max pair; the row says when it applies
    columns=[cf.Field("min", u"Min", unit=PCT, minimum=0, range_hi="max", scale=PCT_SCALE, range_label=u"Window"),
             cf.Field("max", u"Max", unit=PCT, minimum=0)],
    rows=_fallback_rows, read=read_fallback, write=write_fallback, check=_check_fallback,
    row_heading=u"Applies")

# Lists and maps, typed as text: "OPR=LFB, IPR=LFB". No required criteria:
# each limit box has its own state (limit_states), and an Enforced box with
# no limit refuses the run; engine.required_keys is kept, read only as the
# seed of a box not yet stored.
ENGINE_TEXT_ROWS = [
    ((u"aliases",), u"Other names of this method", u"comma-separated"),
    ((u"qc_type_aliases",), u"QC types judged as another", u"OPR=LFB, IPR=LFB"),
]


def _text_rows(profile, env=None):
    codes = (env or {}).get("qc_codes") or []
    widgets = {
        (u"aliases",): {"widget": u"chips"},
        (u"qc_type_aliases",): {"widget": u"pairs", "options": [(c, c) for c in codes] or None},
    }
    return (_one_group(u"txt", u"Names"),
            [{"key": key, "group": u"txt", "label": label,
              "placeholders": {"value": hint}, "widgets": {"value": widgets[key]}}
             for key, label, hint in ENGINE_TEXT_ROWS])


def _as_text(value):
    if isinstance(value, dict):
        return u", ".join(u"%s=%s" % (k, v) for k, v in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return u", ".join(u"%s" % v for v in value)
    return value


def read_engine_text(profile):
    eng = profile.get("engine") or {}
    out = {}
    for key, _l, _h in ENGINE_TEXT_ROWS:
        v = eng.get(key[0])
        if len(key) == 2:
            v = (v or {}).get(key[1]) if isinstance(v, dict) else None
        out[key] = {"value": _as_text(v) if v not in (None, [], {}) else None}
    return out


def write_engine_text(profile, updates, env=None):
    me = _engine_module()
    eng = profile.get("engine")
    eng = eng if isinstance(eng, dict) else {}
    for key, vals in updates.items():
        text = vals.get(("value",))
        text = u"" if text is None else text
        if key == (u"aliases",):
            new = me._names(text)
        elif key == (u"qc_type_aliases",):
            new = me._pairs(text)
        else:
            continue
        if new or key[0] in eng:
            eng[key[0]] = new
    if eng or "engine" in profile:
        profile["engine"] = eng
    return profile


def _check_engine_text(row, values):
    text = values.get(u"f__value") or u""
    if tuple(row["key"]) == (u"qc_type_aliases",):
        bad = [p for p in _engine_module()._names(text) if u"=" not in p]
        if bad:
            return u"QC types judged as another: write each as FROM=TO (%s)." % u", ".join(bad)
    return None


ENGINE_TEXT = cf.Table(
    id=u"engine_text", title=u"Names and required criteria", base=(),
    columns=[cf.Field("value", u"Value", kind=cf.TEXT)],
    rows=_text_rows, rows_take_env=True, read=read_engine_text, write=write_engine_text,
    check=_check_engine_text, row_heading=u"Setting")

MATRIX_FACTORS = cf.Table(
    id=u"mf", title=u"Matrix Adjustment Factors", base=("matrix_factors",),
    columns=[cf.Field("factor", u"Factor", greater_than=0, placeholder=u"1.0")],
    rows=matrix_factor_rows, read=read_matrix_factors, write=write_matrix_factors,
    row_heading=u"Sample Type (core)")

# the test portion each matrix's spike levels assume (spike basis "before")
NOMINAL_AMOUNTS = cf.Table(
    id=u"nom", title=u"Nominal sample amount", base=("nominal_amounts",),
    columns=[cf.Field("amount", u"Amount", greater_than=0),
             cf.Field("unit", u"Unit", kind=cf.CHOICE, choices=[(u"g", u"g"), (u"mL", u"mL")])],
    rows=nominal_amount_rows, read=read_nominal_amounts, write=write_nominal_amounts,
    row_heading=u"Sample Type (core)")

# ── Blank limits: the most each blank may hold, x RL ─────
# A solvent blank (CCB) is reviewed on its chromatogram; with a limit entered
# here it is also judged (against the export's own, extract-basis RL). Each
# value is the default tier (all analytes, all matrices) the worker reads.
# A trip blank (Field QC on the CoC) is judged only against its own row: it
# never borrows another blank's limit, and with none set it is not evaluated.
# A field reagent blank (Field QC on the CoC) is judged against its own row
# alone, its "fails at the limit" included (a method may fail it above, not
# at, its limit); without one it is flagged not judged, never judged against
# another blank's row.
BLANK_TYPES = [(c, QC_NAMES[c]) for c in (u"MB", u"LRB", u"MxB", u"CCB", u"FRB", u"TB")]


def _default_tier(cfg):
    for t in (cfg or {}).get("tiers") or []:
        if isinstance(t, dict) and (t.get("analyte_group") or u"all") == u"all" \
                and (t.get("matrix_scope") or u"all") == u"all":
            return t
    return None


def blank_limit_rows(profile):
    qca = profile.get("qc_acceptance") or {}
    rows = []
    for code, label in BLANK_TYPES:
        off = code in qca and not (qca.get(code) or {}).get("enabled", True)
        rows.append({"key": (code,), "group": u"blk", "label": label,
                     "note": u"switched off on QC Types" if off else None, "warn": False})
    return _one_group(u"blk", u"Most a blank may hold"), rows


def read_blank_limits(profile):
    qca = profile.get("qc_acceptance") or {}
    out = {}
    for code, _label in BLANK_TYPES:
        t = _default_tier(qca.get(code))
        if t is not None and t.get("max_conc_x_rl") is not None:
            out[(code,)] = {"max_conc_x_rl": t.get("max_conc_x_rl"),
                            "fails_at_limit": bool(t.get("fails_at_limit"))}
    return out


def write_blank_limits(profile, updates, env=None):
    qca = profile.setdefault("qc_acceptance", {})
    for (code,), vals in updates.items():
        value = vals.get(("max_conc_x_rl",))
        at_limit = bool(vals.get(("fails_at_limit",)))
        cfg = qca.get(code)
        if cfg is None:
            if value is None:
                continue                 # nothing entered for a type the method lacks
            cfg = qca[code] = {"enabled": True, "tiers": []}
        tier = _default_tier(cfg)
        if tier is None:
            if value is None:
                continue
            tier = {"name": u"default", "analyte_group": u"all", "matrix_scope": u"all"}
            cfg.setdefault("tiers", []).append(tier)
        if value is None:
            tier.pop("max_conc_x_rl", None)     # blank: not judged on a limit
            tier.pop("fails_at_limit", None)
        else:
            tier["max_conc_x_rl"] = value
            # EPA 537.1 §9.3.1: an LRB AT 1/3 MRL already invalidates the
            # batch; other methods fail only above
            if at_limit:
                tier["fails_at_limit"] = True
            else:
                tier.pop("fails_at_limit", None)
    return profile


BLANK_LIMITS = cf.Table(
    id=u"blk", title=u"Blank limits", base=("qc_acceptance",),
    columns=[cf.Field("max_conc_x_rl", u"x RL", greater_than=0, decimals=3),
             cf.Field("fails_at_limit", u"Fails at the limit", kind=cf.BOOL)],
    rows=blank_limit_rows, read=read_blank_limits, write=write_blank_limits,
    row_heading=u"Blank")

# A matrix blank follows its blank limit (above). Where its lot carries
# reference (assigned) values, the lab may judge it as a recovery against
# them with the LFSM recovery tolerances instead.
MATRIX_BLANKS = cf.Section(
    id=u"mxb", title=u"Matrix blanks", base=(),
    groups=[(u"Matrix blanks", [
        cf.Field("mxb_reference_recovery",
                 u"Where the lot has reference values, judge recovery against the LFSM recovery tolerances",
                 kind=cf.BOOL,
                 help=u"Off, or no reference value for an analyte in the result's unit: "
                      u"judged against the matrix blank limit."),
    ])])

# ── EIS limits (EPA 1633A only) ──────────────────────────────────────────────
# eis_overrides: [{"analyte", "recovery_min", "recovery_max"}], keyed by the
# labelled compound's keyword (a published method's designations are
# compounds of the library). eis_matrix_overrides: {class: {keyword: {...}}}
# -- a class limit overrides the per-analyte one, looked up under the SAME
# keyword, so a class row may only name a compound that has a row.


EIS_MATRIX_CLASSES = [(u"solid", u"Solid (soil, sediment)"), (u"biosolid", u"Biosolid"),
                      (u"leachate", u"Landfill leachate"), (u"tissue", u"Tissue")]


def matrix_class_choices():
    return [(u"", u"None")] + [(u"aqueous", u"Aqueous")] + list(EIS_MATRIX_CLASSES)


_EIS_COLS = [(u"aq", u"Aqueous")] + [(k, l.split(" (")[0]) for k, l in EIS_MATRIX_CLASSES]

from senaite.pfas import labelled_standards as _ls
from senaite.pfas import rt_window as _rtw
from senaite.pfas import composite_standards as _cmp

# a class not assessed (labelled_standards.not_assessed): the marker at both
# ends; Aqueous never holds it
NOT_ASSESSED = _ls.NOT_ASSESSED
NOT_ASSESSED_LIMITS = {"recovery_min": NOT_ASSESSED, "recovery_max": NOT_ASSESSED}
not_assessed = _ls.not_assessed


def read_eis_grid(profile):
    """One row per labelled standard: aqueous limits (eis_overrides) and each
    matrix class's (eis_matrix_overrides), side by side; a class not
    assessed reads "none" at both ends and its `<class>_none` True."""
    classes = profile.get("eis_matrix_overrides") or {}
    rows = []
    for r in profile.get("eis_overrides") or []:
        if not isinstance(r, dict) or not r.get("analyte"):
            continue
        row = {"analyte": r["analyte"], "aq_min": r.get("recovery_min"),
               "aq_max": r.get("recovery_max")}
        for key, _l in EIS_MATRIX_CLASSES:
            lim = (classes.get(key) or {}).get(r["analyte"]) or {}
            row[key + "_none"] = not_assessed(lim)
            if row[key + "_none"]:
                row[key + "_min"] = row[key + "_max"] = NOT_ASSESSED
            else:
                row[key + "_min"], row[key + "_max"] = lim.get("recovery_min"), lim.get("recovery_max")
        rows.append(row)
    return rows


def _class_none(r, key):
    """A grid row's class marked not assessed: its box, or the marker."""
    return bool(r.get(key + "_none")) or NOT_ASSESSED in (r.get(key + "_min"), r.get(key + "_max"))


def write_eis_grid(profile, rows):
    old = dict((r.get("analyte"), r) for r in (profile.get("eis_overrides") or [])
               if isinstance(r, dict))
    # a row with no limit is no row: a standard offered blank and left blank
    # gets none, and a stored row cleared to blank is removed (a row stored
    # with no limit, untouched, stays as it was)
    def limited(r):
        return any(r.get(key + "_" + end) is not None for key, _l in _EIS_COLS for end in ("min", "max")) or \
            any(_class_none(r, key) for key, _l in EIS_MATRIX_CLASSES)
    before = dict((r["analyte"], r) for r in read_eis_grid(profile))
    rows = [r for r in rows if limited(r) or (r["analyte"] in before and not limited(before[r["analyte"]]))]
    out = []
    for r in rows:
        entry = dict(old.get(r["analyte"]) or {})     # keep any other keys a row had
        entry.update({"analyte": r["analyte"], "recovery_min": r.get("aq_min"),
                      "recovery_max": r.get("aq_max")})
        out.append(entry)
    _set(profile, "eis_overrides", out)
    allc = dict(profile.get("eis_matrix_overrides") or {})
    for key, _l in EIS_MATRIX_CLASSES:
        # a class limit for a standard the grid never showed is kept
        entries = dict((a, lim) for a, lim in (allc.get(key) or {}).items() if a not in old)
        for r in rows:
            if _class_none(r, key):
                entries[r["analyte"]] = dict(NOT_ASSESSED_LIMITS)
                continue
            lim = {}
            for f, col in (("recovery_min", key + "_min"), ("recovery_max", key + "_max")):
                if r.get(col) is not None:
                    lim[f] = r[col]
            if lim:
                entries[r["analyte"]] = lim
        if entries:
            allc[key] = entries
        else:
            allc.pop(key, None)
    _set(profile, "eis_matrix_overrides", allc)
    return profile


def eis_resolver():
    """name -> the keyword a SUR limits row's name resolves to in the compound
    library, as the pipeline reads the row (a published spelling, 13C8-PFOSA,
    reaches 13C8-FOSA); the name itself when the library does not know it."""
    cl, library = _library()
    n2k = cl.name_to_keyword(library)
    return lambda name: cl.keyword_of(library, name, n2k) or name


def eis_names_for(profile, keyword):
    """The names `keyword`'s SUR limits are stored under: its own and any the
    library resolves to it."""
    resolve = eis_resolver()
    names = set(r.get("analyte") for r in profile.get("eis_overrides") or [] if isinstance(r, dict))
    for table in (profile.get("eis_matrix_overrides") or {}).values():
        names.update(table if isinstance(table, dict) else ())
    return sorted(n for n in names if n and (n == keyword or resolve(n) == keyword))


def drop_eis_limits(profile, names):
    """Removes the SUR limits stored under `names` (rows and class limits),
    in place; returns the columns, aqueous and each class, that held one."""
    held = set()
    if isinstance(profile.get("eis_overrides"), list):
        kept = []
        for r in profile["eis_overrides"]:
            if isinstance(r, dict) and r.get("analyte") in names:
                if r.get("recovery_min") is not None or r.get("recovery_max") is not None:
                    held.add(u"aq")
            else:
                kept.append(r)
        profile["eis_overrides"] = kept
    classes = profile.get("eis_matrix_overrides")
    for key in list(classes or {}):
        table = classes[key]
        if isinstance(table, dict) and any(n in table for n in names):
            held.add(key)
            classes[key] = dict((n, lim) for n, lim in table.items() if n not in names)
            if not classes[key]:
                classes.pop(key)
    return [k for k, _l in _EIS_COLS if k in held]


def _eis_grid_check(profile, rows):
    out = []
    for r in rows:
        for key, label in _EIS_COLS:
            if key != u"aq" and _class_none(r, key):
                continue                        # not assessed: no window to order
            lo, hi = r.get(key + "_min"), r.get(key + "_max")
            if lo is not None and hi is not None and lo > hi:
                out.append(u"%s %s: recovery min (%s) is above max (%s)." % (
                    r["analyte"], label, lo, hi))
    return out


# One grid for every SUR limit: the standards down the side,
# aqueous and each 1633A matrix class across. A class limit overrides the
# aqueous one for that class; a blank class cell uses the aqueous limit.
EIS_GRID = cf.Collection(
    id=u"eis_grid", title=u"SUR recovery limits", noun=u"SUR row",
    allow_empty=True,
    columns=[cf.Field("analyte", u"Surrogate (SUR)", kind=cf.TEXT, placeholder=u"isotope standard keyword")] +
            [cf.Field(key + "_" + end, u"%s %s %%" % (label, end), minimum=0, unit=PCT,
                      range_hi=(key + "_max") if end == "min" else None,
                      scale=PCT_SCALE if end == "min" else None)
             for key, label in _EIS_COLS for end in ("min", "max")] +
            [cf.Field(key + "_none", u"%s not assessed" % label.split(" (")[0], kind=cf.BOOL)
             for key, label in EIS_MATRIX_CLASSES],
    read=read_eis_grid, write=write_eis_grid, check=_eis_grid_check)


# ── Surrogate Map: injection IS, native -> surrogate, surrogate -> injection IS
# Each method owns its map, and nothing else holds the link: the page supplies
# the core services in env["services"] = {keyword: {"role", "name"}}.

def _map_rows(profile):
    return [r for r in (profile.get("surrogate_map") or [])
            if isinstance(r, dict) and r.get("analyte")]


def surrogate_choices(profile, env=None):
    """Every labelled standard, this method's extracted standards first -- a
    method may pick any (the save then requires it ticked Used with the
    extracted role on the Labelled standards tab)."""
    svcs = dict((k, v) for k, v in ((env or {}).get("services") or {}).items()
                if v.get("role") in ("surrogate", "injection_is"))
    grid = (profile.get("labelled_standards") or {})
    own = []
    for r in _map_rows(profile):
        s = r.get("surrogate_is")
        if s in svcs and s not in own:
            own.append(s)
    own += sorted(k for k, v in grid.items()
                  if k in svcs and k not in own and (v or {}).get("role") == "surrogate")
    rest = sorted(k for k in svcs if k not in own)
    # then the method's composites, by the name built from their members
    return ([(k, svcs[k].get("name") or k) for k in own + rest] +
            [(cid, _cmp.name(profile, cid)) for cid in _cmp.ordered(profile)])


def surrogate_map_rows(profile, env=None):
    titles = _analyte_titles(profile)
    rows = [{"key": (kw,), "group": u"sur", "label": titles.get(kw, kw), "sublabel": kw}
            for kw in profile.get("master_analyte_set") or []]
    return _one_group(u"sur", u"Surrogate map"), rows


def read_surrogate_map(profile):
    return dict(((r["analyte"],), {"surrogate_is": r.get("surrogate_is") or None})
                for r in _map_rows(profile))


def write_surrogate_map(profile, updates, env=None):
    def build(kw, vals, old):
        sur = vals.get(("surrogate_is",))
        if not sur:
            return None                     # none chosen: no row
        entry = dict(old)
        entry.update({"analyte": kw, "surrogate_is": sur})
        return entry
    existing = _map_rows(profile)
    order = [(kw,) for kw in profile.get("master_analyte_set") or [] if (kw,) in updates]
    out = _merge_rows(existing, "analyte", updates, order, build)
    _set(profile, "surrogate_map", out)
    return profile


SURROGATE_MAP = cf.Table(
    id=u"sur", title=u"Surrogate Map", base=("surrogate_map",),
    columns=[cf.Field("surrogate_is", u"Quantifying Surrogate", kind=cf.CHOICE,
                      choices=surrogate_choices)],
    rows=surrogate_map_rows, rows_take_env=True,
    read=read_surrogate_map, write=write_surrogate_map, row_heading=u"Native Analyte")


# ── Labelled standards grid (MS Quan style) ────────────

def _labelled_services(env):
    return dict((k, v) for k, v in ((env or {}).get("services") or {}).items()
                if v.get("role") in _ls.ROLES)


def role_choices(profile, env=None):
    return list(_ls.ROLE_LABELS)


def standard_choices(profile, env=None):
    """Link targets: every labelled standard (the save refuses one the method
    does not use), this method's own first."""
    svcs = _labelled_services(env)
    own = sorted(k for k in _ls.grid(profile) if k in svcs)
    rest = sorted(k for k in svcs if k not in own)
    return [(k, svcs[k].get("name") or k) for k in own + rest]


def labelled_rows(profile, env=None):
    """Every isotopically labelled standard in core plus any the grid already
    names: used ones first (injection standards, then extracted), then the
    rest -- each noting which natives it quantifies in this method."""
    svcs = _labelled_services(env)
    g = _ls.grid(profile)
    quantifies = {}
    for r in _map_rows(profile):
        # a composite's natives are each member's too
        for kw in _cmp.members(profile, r.get("surrogate_is")):
            quantifies.setdefault(kw, []).append(r["analyte"])

    def order(kw):
        role = (g.get(kw) or {}).get("role")
        return (0 if role == "injection_is" else 1 if kw in g else 2,
                (svcs.get(kw) or {}).get("name") or kw)

    rows = []
    for kw in sorted(set(svcs) | set(g), key=order):
        natives = quantifies.get(kw) or []
        rows.append({"key": (kw,), "group": u"ls", "label": (svcs.get(kw) or {}).get("name") or kw,
                     "sublabel": kw,
                     "note": (u"quantifies " + u", ".join(natives[:4]) +
                              (u" +%d" % (len(natives) - 4) if len(natives) > 4 else u""))
                             if natives else None})
    return _one_group(u"ls", u"Isotope standards"), rows


def read_labelled(profile):
    return dict(((kw,), {"used": True, "role": v.get("role") or None,
                         "reference": v.get("reference") or None})
                for kw, v in _ls.grid(profile).items())


def write_labelled(profile, updates, env=None):
    grid = dict(_ls.grid(profile))
    for (kw,), vals in updates.items():
        if vals.get(("used",)):
            # a standard's role and link; the source of its limits is on the
            # Help page, never stored beside them
            grid[kw] = {"role": vals.get(("role",)) or u"",
                        "reference": vals.get(("reference",)) or u""}
        else:
            grid.pop(kw, None)
    profile[_ls.KEY] = grid
    return profile


def _row_consistent(row, values):
    used = values.get(u"f__used")
    if not used and (values.get(u"f__role") or values.get(u"f__reference")):
        return u"%s: tick Used, or clear its role and link." % row["sublabel"]
    return None


LABELLED_STANDARDS = cf.Table(
    id=u"ls", title=u"Isotope standards", base=(_ls.KEY,),
    columns=[cf.Field("used", u"Used", kind=cf.BOOL),
             cf.Field("role", u"Role in this method", kind=cf.CHOICE, choices=role_choices),
             cf.Field("reference", u"Linked to", kind=cf.CHOICE, choices=standard_choices)],
    rows=labelled_rows, rows_take_env=True, read=read_labelled, write=write_labelled,
    check=_row_consistent, row_heading=u"Isotope Standard")


# ── Composite standards: the mean of two or more standards' areas ──────
# Saved with Isotope standards: one row per composite, its id and its
# members (keywords, comma-separated, in the lab's order). A row posted with
# an id the profile does not hold is a new composite: the server gives it a
# fresh id (composite_standards.new_id), so no id is ever chosen by the page.
# Clearing a row's id removes the composite; the whole-profile check refuses
# that while an analyte's Quantified by names it.

def read_composites(profile):
    return [{"id": cid, "members": u", ".join(_cmp.members(profile, cid))} for cid in _cmp.ordered(profile)]


def _members_from(text):
    return [m.strip() for m in (u"%s" % (text or u"")).split(u",") if m.strip()]


def write_composites(profile, rows):
    before = _cmp.entries(profile)
    cl, lib = _library()
    n2k = cl.name_to_keyword(lib or {}) or {}
    taken = list(before) + list(n2k) + list(n2k.values())
    out = {}
    for r in rows:
        cid = (r.get("id") or u"").strip()
        members = _members_from(r.get("members"))
        if cid not in before:
            cid = _cmp.new_id(taken + list(out))
        old = before.get(cid) or {}
        if old and list(old.get("members") or []) == members:
            out[cid] = old                   # as stored, every key kept
            continue
        out[cid] = dict(old, members=members, averaged=old.get("averaged") or u"area")
    if out:
        profile[_cmp.KEY] = out
    elif _cmp.KEY in profile:
        profile[_cmp.KEY] = {}
    return profile


COMPOSITES = cf.Collection(
    id=u"cmp", title=u"Composite standards", noun=u"composite",
    allow_empty=True,
    columns=[cf.Field("id", u"Composite", kind=cf.TEXT),
             cf.Field("members", u"Members", kind=cf.TEXT)],
    read=read_composites, write=write_composites)


def check_profile(profile):
    """Checks on the WHOLE profile after a tab's sections are applied: the
    grid's links and loops, its agreement with the surrogate map, and the
    composites (no id of one may be a keyword the compound library holds)."""
    cl, lib = _library()
    n2k = cl.name_to_keyword(lib or {}) or {}
    return _ls.check(profile, keywords=list(n2k) + list(n2k.values()))


# ── How results are corrected: the response ratio ─────────────
# What an analyte's Quantified by names decides its calculation (a surrogate:
# isotope dilution; an internal standard: internal-standard quantitation).
# The one choice: whether a surrogate's response is first normalised to the
# injection standard its Linked to names (a response ratio linked to that
# standard), the same ratio for calibrators, QC and samples. Top-level key
# `linked_response_ratio`, "off" or "on"; missing or blank reads "off" (the
# worker reads the same key). A profile holding the retired
# `surrogate_amount: "measured"` reads "on" and is written anew on Save.
LINKED_RATIO_KEY = "linked_response_ratio"
LINKED_RATIOS = [(u"off", u"Off"), (u"on", u"On")]
LINKED_RATIO_DEFAULT = u"off"
LEGACY_AMOUNT_KEY = "surrogate_amount"
# the help line under the choice, for the state it is in: Off in the board's
# words, On in the equation window's own words for On
LINKED_RATIO_HELP = {
    u"off": u"Off: the surrogate as spiked. Open the box for both calculations.",
    u"on": u"On: the surrogate first measured against the internal standard. Open the box for both calculations.",
}

LINKED_RATIO = cf.Section(
    id=u"lrr", title=u"How results are corrected", base=(),
    groups=[(u"How results are corrected", [
        cf.Field(LINKED_RATIO_KEY, u"Response ratio linked to the injection standard", kind=cf.CHOICE,
                 widget=u"seg", blank=u"remove", default=LINKED_RATIO_DEFAULT, choices=LINKED_RATIOS,
                 state_help=LINKED_RATIO_HELP),
    ])])


def linked_response_ratio(profile):
    """The method's linked response ratio, "on" or "off": the key as
    stored, else "on" for the retired surrogate_amount "measured", else
    "off"."""
    profile = profile or {}
    v = u"%s" % (profile.get(LINKED_RATIO_KEY) or u"")
    if v in dict(LINKED_RATIOS):
        return v
    return u"on" if u"%s" % (profile.get(LEGACY_AMOUNT_KEY) or u"") == u"measured" else LINKED_RATIO_DEFAULT


def migrate_linked_ratio(profile):
    """On a Save of the section: the retired surrogate_amount goes. It was
    drawn as On ("measured"); posted On, the section stores the new key (a
    value unlike its default), posted Off, nothing (the default)."""
    profile.pop(LEGACY_AMOUNT_KEY, None)
    return profile


# ── A diluted sample's surrogate recovery ─────────────────────
# How a diluted field sample's surrogate recovery is taken, one setting for
# every analyte, read where the response ratio is linked to the injection
# standard: corrected for the dilution, as measured, or the parent
# sample's. Top-level key `dilution_recovery`, "fold", "measured" or
# "parent"; nothing is preset: blank is not set, and a diluted sample's
# surrogate recovery is not judged. Saved by the Analytes tab.
DILUTION_RECOVERY_KEY = "dilution_recovery"
DILUTION_RECOVERIES = [(u"fold", u"Corrected for the dilution"), (u"measured", u"As measured"),
                       (u"parent", u"Parent's recovery")]

DILUTION_RECOVERY = cf.Section(
    id=u"dilrec", title=u"Surrogate recovery in a diluted sample", base=(),
    groups=[(u"Surrogate recovery in a diluted sample", [
        cf.Field(DILUTION_RECOVERY_KEY, u"Surrogate recovery in a diluted sample", kind=cf.CHOICE, widget=u"seg",
                 blank=u"remove", choices=DILUTION_RECOVERIES,
                 help=u"Used when the response ratio is linked to the injection standard. Applies to every "
                      u"analyte. Dilutions are never performed on extracted QC."),
    ])])


def dilution_recovery(profile):
    """"fold", "measured" or "parent"; u"" while not set (anything else
    stored reads not set)."""
    v = u"%s" % ((profile or {}).get(DILUTION_RECOVERY_KEY) or u"")
    return v if v in dict(DILUTION_RECOVERIES) else u""


# ── Every standard and analyte names what corrects it ─────────
# All surrogates must be linked to an internal standard; all analytes must
# be linked to an internal standard or surrogate. The tab that holds each
# link refuses its Save while one is missing: Isotope standards a Used
# surrogate with no Linked to, Analytes an analyte reported in at least one
# matrix with no Quantified by (an analyte left out of every matrix is not
# required). Each tab checks only its own links, so a method missing both
# can be mended one tab at a time. A surrogate's Linked to names an
# internal standard, never another surrogate nor a composite (a composite's
# members each carry their own link to an internal standard).

def unlinked_surrogates(profile):
    """The method's surrogates, by keyword, whose Linked to is blank."""
    return sorted(kw for kw, v in _ls.grid(profile or {}).items()
                  if v.get("role") == u"surrogate" and not (v.get("reference") or u"").strip())


def misdirected_surrogates(profile):
    """[(surrogate, its Linked to, "surrogate" | "composite")], by keyword,
    for each surrogate linked to another surrogate or to a composite."""
    profile = profile or {}
    g = _ls.grid(profile)
    out = []
    for kw in sorted(g):
        ref = (g[kw].get("reference") or u"").strip()
        if g[kw].get("role") != u"surrogate" or not ref:
            continue
        if _cmp.is_composite(profile, ref) or _cmp.is_id(ref):
            out.append((kw, ref, u"composite"))
        elif (g.get(ref) or {}).get("role") == u"surrogate":
            out.append((kw, ref, u"surrogate"))
    return out


def unquantified_analytes(profile):
    """The panel's analytes, in panel order, reported in at least one of the
    method's matrices and with no Quantified by."""
    profile = profile or {}
    matrices = list(profile.get("supported_matrices") or [])
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    quantified = set(r["analyte"] for r in _map_rows(profile) if (r.get("surrogate_is") or u"").strip())
    return [kw for kw in profile.get("master_analyte_set") or []
            if kw not in quantified and any((inclusion.get(kw) or {}).get(m, True) for m in matrices)]


SURROGATE_LINK_REFUSED = u"%s: set its Linked to internal standard before Save."
SURROGATE_LINK_MISDIRECTED = u"%s: link it to an internal standard, not a %s."
ANALYTE_LINK_REFUSED = u"%s: set its Quantified by surrogate or internal standard before Save."


def check_surrogate_links(profile):
    return ([SURROGATE_LINK_REFUSED % kw for kw in unlinked_surrogates(profile)] +
            [SURROGATE_LINK_MISDIRECTED % (kw, kind) for kw, _ref, kind in misdirected_surrogates(profile)])


def check_analyte_links(profile):
    return [ANALYTE_LINK_REFUSED % kw for kw in unquantified_analytes(profile)]

# ── Isomers ───────────────────────────────────────────

def isomer_rows(profile):
    """Every panel analyte, those with isomers first."""
    titles = _global_titles()
    groups = _iso.entries(profile)
    panel = list(profile.get("master_analyte_set") or [])
    rows = []
    for kw in [k for k in panel if k in groups] + [k for k in panel if k not in groups]:
        rows.append({"key": (kw,), "group": u"iso", "label": _iso.label(profile, kw, titles),
                     "sublabel": kw})
    return _one_group(u"iso", u"Isomers"), rows


def read_isomers(profile):
    out = {}
    for kw, e in _iso.entries(profile).items():
        out[(kw,)] = {"linear": e.get("linear") or None,
                      "branched": u", ".join(e.get("branched") or []) or None,
                      "reported": e.get("reported") or None}
    return out


def write_isomers(profile, updates, env=None):
    groups = dict(_iso.entries(profile))
    for (kw,), vals in updates.items():
        linear = (vals.get(("linear",)) or u"").strip()
        branched = [b.strip() for b in (vals.get(("branched",)) or u"").split(u",") if b.strip()]
        if not linear and not branched:
            groups.pop(kw, None)            # no peaks: the analyte has no isomers here
            continue
        old = groups.get(kw) or {}
        groups[kw] = dict(old, linear=linear, branched=branched,
                          reported=(vals.get(("reported",)) or u"").strip())
        groups[kw].pop("summed", None)
    profile[_iso.KEY] = groups
    return profile


ISOMERS = cf.Table(
    id=u"iso", title=u"Isomers", base=(_iso.KEY,),
    columns=[cf.Field("linear", u"Linear peak", kind=cf.TEXT, placeholder=u"e.g. lr-PFOS"),
             cf.Field("branched", u"Branched peak(s), comma-separated", kind=cf.TEXT,
                      widget=u"chips", placeholder=u"e.g. br-PFOS"),
             cf.Field("reported", u"Reported as", kind=cf.TEXT,
                      placeholder=u"plain name (e.g. PFOS)")],
    rows=isomer_rows, read=read_isomers, write=write_isomers, row_heading=u"Analyte")


def check_isomers(profile):
    cl, lib = _library()
    return _iso.check(profile, _global_titles(), lib)


# ── Recovery Tiers tab: spike levels, recovery tiers, Dup RPD ──
# Spike levels are one grid per spiked
# QC type (levels x matrices); recovery tiers a compact table holding ONLY what
# the engine reads; a read-only grid shows the window applied per analyte group
# x matrix, computed the way the engine computes it (cross-checked in tests).

SPIKE_QC_TYPES = (u"LFSM", u"LFB", u"LCS")
SPIKE_LABELS = {u"LFSM": u"LFSM / LFSMD", u"LFB": u"LFB", u"LCS": u"LCS"}


def _cl():
    from senaite.pfas import calibration_levels
    return calibration_levels


def _spike_levels(profile, qc):
    """Level labels used for `qc`, in first-seen order across matrices."""
    labels = []
    for m in profile.get("supported_matrices") or []:
        for r in ((profile.get("spike_levels") or {}).get(m) or {}).get(qc) or []:
            if isinstance(r, dict) and r.get("label") and r["label"] not in labels:
                labels.append(r["label"])
    return labels


def _spike_collection(qc):
    def columns(profile):
        return ([cf.Field("label", u"Level", kind=cf.TEXT, placeholder=u"new level")] +
                # each matrix in its own reporting unit (soil in ng/g, water
                # in ng/L), drawn on the heading's second line; the box holds
                # the value or nothing
                [cf.Field((m,), m, unit=_cl().matrix_unit(profile, m), minimum=0)
                 for m in profile.get("supported_matrices") or []])

    def read(profile):
        sl = profile.get("spike_levels") or {}
        rows = []
        for label in _spike_levels(profile, qc):
            row = {"label": label}
            for m in profile.get("supported_matrices") or []:
                for r in (sl.get(m) or {}).get(qc) or []:
                    if isinstance(r, dict) and r.get("label") == label:
                        row[m] = _cl().level_value(r, _cl().matrix_unit(profile, m))
            rows.append(row)
        return rows

    def write(profile, rows):
        sl = dict(profile.get("spike_levels") or {})
        for m in profile.get("supported_matrices") or []:
            per = dict(sl.get(m) or {})
            had = qc in per
            unit = _cl().matrix_unit(profile, m)
            stored = dict((e.get("label"), e) for e in per.get(qc) or [] if isinstance(e, dict))
            levels = []
            for r in rows:
                old = stored.get(r["label"])
                if old is not None and _cl().level_value(old, unit) == r.get(m):
                    levels.append(old)              # unchanged: kept as stored
                else:
                    levels.append({"label": r["label"], "value": r.get(m)})
            if not had and all(_cl().level_value(l, unit) is None for l in levels):
                continue                     # nothing entered: nothing created
            per[qc] = levels
            sl[m] = per
        _set(profile, "spike_levels", sl)
        return profile

    return cf.Collection(id=u"spk_" + qc, title=u"Spike levels: %s" % SPIKE_LABELS[qc],
                         columns=columns, read=read, write=write, noun=u"level", allow_empty=True)


SPIKE_LEVELS = dict((qc, _spike_collection(qc)) for qc in SPIKE_QC_TYPES)

RECOVERY_QC = u"LFSM"
GROUP_CHOICES = [(u"all", u"All analytes"), (u"key", u"Regulated analytes"),
                 (u"linked", u"Other analytes"), (u"no_std", u"No isotope standard")]
LISTED = u"listed"
SCOPE_CHOICES = [(u"all", u"All matrices"), (LISTED, u"Listed below")]


def grouped_tiers(profile, replace=None):
    """Does this method pick a tier by analyte group and the tier's own
    matrices, or apply its FIRST ordinary tier to every analyte and
    matrix? Derived: any tier of any QC type with a group or matrix scope
    other than all.
    `replace` {qc: tiers} judges a save of those QC types' tiers."""
    me = _engine_module()
    return me.tiers_grouped(me.profile_tiers(profile, replace))


def _tiers(profile, qc=RECOVERY_QC):
    return [t for t in (((profile.get("qc_acceptance") or {}).get(qc) or {})
                        .get("tiers") or []) if isinstance(t, dict)]


LOW_LEVEL_KEY = u"low_level_x_rl"     # the engine's name (pfas_pipeline)


def _scope(tier):
    """A tier's matrix scope as the editor offers it: all, or listed (a
    stored "tight" scope reads as listed)."""
    return LISTED if _qc_tiers().is_listed(tier) else u"all"


def _listed_matrices(profile, tier):
    """A tier's own matrix list as the engine reads it (qc_tiers._own_list):
    a tier stored "tight" with no list of its own lists the Tier 1 list. Drawn and
    saved so, an untouched save keeps every window; never an empty list
    that would apply the tier nowhere."""
    return _qc_tiers()._own_list(profile, tier) if _scope(tier) == LISTED else []


def _tier_reader(qc, fields):
    def read(profile):
        out = []
        for i, t in enumerate(_tiers(profile, qc)):
            row = {"name": t.get("name") or u"tier %d" % (i + 1),
                   "analyte_group": t.get("analyte_group") or u"all",
                   "matrix_scope": _scope(t), "matrices": _listed_matrices(profile, t)}
            for key in fields:
                row[key] = t.get(key)
            out.append(row)
        return out
    return read


def _tier_writer(qc, fields):
    def write(profile, rows):
        if not rows and qc not in (profile.get("qc_acceptance") or {}):
            return profile                            # not run here: nothing created
        old = dict(((t.get("name") or u"tier %d" % (i + 1)), t)
                   for i, t in enumerate(_tiers(profile, qc)))
        tiers = []
        for r in rows:
            # a renamed tier keeps what is stored on it (its state, flag,
            # verify_against_method, citation): matched by the name it was
            # stored under, unless its rename was posted to start afresh
            was = r["name"] if r.get(cf.FRESH_KEY) else (r.get(cf.STORED_KEY) or r["name"])
            t = dict(old.get(was) or {})
            t.update({"name": r["name"], "analyte_group": r.get("analyte_group") or u"all",
                      "matrix_scope": _scope(r)})
            if t["matrix_scope"] == LISTED:
                # a row posted from the page carries its list; one from a
                # project patch stored "tight" with no list takes the Tier 1
                # list, as the engine reads it
                t["matrices"] = _listed_matrices(profile, r)
            else:
                t.pop("matrices", None)               # a tier for all matrices lists none
            for key in fields:
                if r.get(key) is not None or key in t:  # absent stays absent
                    t[key] = r.get(key)
            if t.get(LOW_LEVEL_KEY) is None:
                t.pop(LOW_LEVEL_KEY, None)            # an ordinary tier carries no condition
            tiers.append(t)
        entry = profile.setdefault("qc_acceptance", {}).setdefault(qc, {"enabled": True})
        entry["tiers"] = tiers
        return profile
    return write


CORE_GROUPS = (u"all", u"linked")


def core_tier(ordinary):
    """The QC type's core tier: the ordinary tier the engine falls back to
    for an analyte no other tier takes (qc_tiers.base_tier), the first whose
    analyte group is all or linked; None where no tier is. It is never
    removed, and applies to all or linked analytes only, so a QC type that
    is on always has a tier for every analyte."""
    for t in ordinary:
        if (t.get("analyte_group") or u"all") in CORE_GROUPS:
            return t
    return None


def _tier_checker(qc, window):
    def check(profile, rows):
        errors = []
        stored = dict(((t.get("name") or u"tier %d" % (i + 1)), (_scope(t), _listed_matrices(profile, t)))
                      for i, t in enumerate(_tiers(profile, qc)))
        for r in rows:
            # a listed tier with an empty list applies nowhere: refused only
            # where this save sets it so -- a stored one (a migrated tier
            # whose matrices the lab has not listed yet) is kept as it is
            # (a renamed row is matched by the name it was stored under)
            if (_scope(r) == LISTED and not r.get("matrices")
                    and stored.get(r.get(cf.STORED_KEY) or r["name"]) != (LISTED, [])):
                errors.append(u"Tier %s lists no matrices." % r["name"])
            if window:
                lo, hi = r.get("recovery_min"), r.get("recovery_max")
                if (lo is None) != (hi is None):
                    errors.append(u"%s: set both ends of the recovery window, or neither." % r["name"])
                elif lo is not None and lo > hi:
                    errors.append(u"%s: min (%s) is above max (%s)." % (r["name"], lo, hi))
                if r.get(LOW_LEVEL_KEY) is not None and lo is None:
                    errors.append(u"%s: a low-level tier needs its recovery window." % r["name"])
            elif r.get(LOW_LEVEL_KEY) is not None and r.get("rpd_max") is None:
                errors.append(u"%s: a low-level tier needs its RPD limit." % r["name"])
        # the stored core tier stays: matched by the name it was stored under
        # (a renamed row keeps it), still for all or linked analytes
        held = _tiers(profile, qc)
        core = core_tier([t for t in held if not t.get(LOW_LEVEL_KEY)])
        if core is not None and rows:
            # the name the reader gives it (an unnamed tier reads "tier N")
            name = core.get("name") or u"tier %d" % (next(i for i, t in enumerate(held) if t is core) + 1)
            kept = [r for r in rows if (r.get(cf.STORED_KEY) or r.get("name")) == name
                    and r.get(LOW_LEVEL_KEY) is None]
            if not kept:
                errors.append(u"%s: tier %s is the core tier, the one every analyte no other tier takes "
                              u"falls back to; it cannot be removed. Edit it instead." % (qc, name))
            elif core_tier([r for r in rows if r.get(LOW_LEVEL_KEY) is None]) is None:
                # a regrouping may move the core to another tier; one must remain
                errors.append(u"%s: keep one tier for all or other analytes: every analyte no other tier "
                              u"takes falls back to it." % qc)
        # a QC type this save adds to the method (no entry stored): nothing
        # regulatory is filled in for the lab, so each tier's limit is typed
        # before the type is stored
        if rows and not isinstance(((profile or {}).get("qc_acceptance") or {}).get(qc), dict):
            for r in rows:
                if window and r.get("recovery_min") is None and r.get("recovery_max") is None:
                    errors.append(u"%s is new to this method: type tier %s's recovery window before Save."
                                  % (qc, r["name"]))
                elif not window and r.get("rpd_max") is None:
                    errors.append(u"%s is new to this method: type tier %s's RPD limit before Save."
                                  % (qc, r["name"]))
        ordinary = [r for r in rows if r.get(LOW_LEVEL_KEY) is None]
        if not grouped_tiers(profile, {qc: rows}) and len(ordinary) > 1:
            errors.append(u"This method's QC engine applies its FIRST ordinary tier to every "
                          u"analyte and matrix; a second would never be used. Keep one, plus "
                          u"any low-level tiers (Low level \u2264 \u00d7 RL).")
        if not ordinary and rows:
            errors.append(u"Keep one ordinary tier (Low level blank): it applies above the "
                          u"low level.")
        return errors
    return check


_LOW_LEVEL_FIELD = cf.Field(LOW_LEVEL_KEY, u"Low level \u2264 \u00d7 RL", greater_than=0,
                            help=u"Blank: the ordinary tier. N: applies instead to spikes at "
                                 u"or below N \u00d7 RL.")
_TIER_HEAD = [cf.Field("name", u"Tier", kind=cf.TEXT, placeholder=u"new tier"),
              cf.Field("analyte_group", u"Applies to", kind=cf.CHOICE, choices=GROUP_CHOICES),
              cf.Field("matrix_scope", u"Matrices", kind=cf.CHOICE, choices=SCOPE_CHOICES),
              # a listed tier's own list: posted in the tier's row, edited in
              # the search picker named after the tier (Who each tier applies to)
              cf.Field("matrices", u"Matrices", kind=cf.MULTI, widget=u"picker", noun=u"matrices",
                       choices=lambda profile, env=None: _matrix_choices(profile, env),
                       show_if=("matrix_scope", LISTED)),
              _LOW_LEVEL_FIELD]
_RECOVERY_FIELDS = ("recovery_min", "recovery_max", "rsd_max", LOW_LEVEL_KEY)


def _recovery_collection(qc, id_):
    return cf.Collection(
        id=id_, title=u"%s recovery tiers" % qc if qc != RECOVERY_QC else u"Recovery tiers",
        noun=u"tier", allow_empty=(qc != RECOVERY_QC),
        columns=_TIER_HEAD + [cf.Field("recovery_min", u"Recovery min", minimum=0, unit=PCT,
                                       range_hi="recovery_max", scale=PCT_SCALE, range_label=u"Window"),
                              cf.Field("recovery_max", u"Recovery max", minimum=0, unit=PCT),
                              # an empty RSD max is unset: the precision is not judged
                              cf.Field("rsd_max", u"RSD max", minimum=0, unit=PCT, placeholder=u"not set")],
        read=_tier_reader(qc, _RECOVERY_FIELDS), write=_tier_writer(qc, _RECOVERY_FIELDS),
        carry_stored_key=True, check=_tier_checker(qc, True))


RECOVERY_TIERS = _recovery_collection(RECOVERY_QC, u"tiers")
# LFB (537.1 \u00a79.3.3: low level <= 2 x MRL 50-150%, medium/high 70-130%) and
# LCS carry tiers too; their tab section shows only where the method runs them.
LFB_TIERS = _recovery_collection(u"LFB", u"tiers_lfb")
read_tiers = RECOVERY_TIERS.read
write_tiers = RECOVERY_TIERS.write
check_tiers = RECOVERY_TIERS.check





# LFSMD RPD tiers, read by the engine (qc_rules(..., "LFSMD").rpd_max); a
# low-level tier carries 537.1 §9.3.7.4 (<= 50% within 2 x MRL).
_RPD_FIELDS = ("rpd_max", LOW_LEVEL_KEY)

# Sample duplicate RPD tiers: a tier list like LFSMD, so a low-level tier
# (EPA 537.1 §9.3.7.2, <= 50% within 2 x MRL) is editable.
DUP_RPD = cf.Collection(
    id=u"dup", title=u"Sample Duplicate RPD", noun=u"tier", allow_empty=True,
    columns=_TIER_HEAD + [cf.Field("rpd_max", u"Max RPD %", minimum=0)],
    read=_tier_reader(u"Dup", _RPD_FIELDS), write=_tier_writer(u"Dup", _RPD_FIELDS),
    carry_stored_key=True, check=_tier_checker(u"Dup", False))

LFSMD_RPD = cf.Collection(
    id=u"lfsmd", title=u"LFSMD RPD", noun=u"tier", allow_empty=True,
    columns=_TIER_HEAD + [cf.Field("rpd_max", u"Max RPD %", minimum=0)],
    read=_tier_reader(u"LFSMD", _RPD_FIELDS), write=_tier_writer(u"LFSMD", _RPD_FIELDS),
    carry_stored_key=True, check=_tier_checker(u"LFSMD", False))


# Additional analytes -- PROJECT specs only: a defined
# core service (pfas_role "analyte") that is not in the method panel joins the
# project's panel. The effective profile lists them under EXTRAS_KEY so the
# editor can tell them from the method's own analytes (never removable here).
EXTRAS_KEY = "project_extra_analytes"


def extra_rows(profile, env=None):
    svcs = (env or {}).get("services") or {}
    extras = list(profile.get(EXTRAS_KEY) or [])
    method_panel = set(k for k in profile.get("master_analyte_set") or [] if k not in extras)
    peaks = set()                      # isomer peaks are reviewed, never reported alone
    for e in _iso.entries(profile).values():
        peaks.update([e.get("linear")] + list(e.get("branched") or []))
    kws = set(k for k, v in svcs.items() if v.get("role") == u"analyte" and k not in method_panel
              and not _iso.is_peak_name(k) and k not in peaks)
    kws |= set(extras)
    rows = []
    for kw in sorted(kws, key=lambda k: ((svcs.get(k) or {}).get("name") or k).lower()):
        gone = kw not in svcs
        rows.append({"key": (kw,), "group": u"px", "label": (svcs.get(kw) or {}).get("name") or kw,
                     "sublabel": kw, "note": u"no longer a defined service" if gone else None,
                     "warn": gone})
    return _one_group(u"px", u"Additional analytes"), rows


def read_extras(profile):
    return dict(((kw,), {"include": True}) for kw in profile.get(EXTRAS_KEY) or [])


def write_extras(profile, updates, env=None):
    extras = list(profile.get(EXTRAS_KEY) or [])
    panel = list(profile.get("master_analyte_set") or [])
    inclusion = profile.setdefault("analyte_matrix_inclusion", {})
    for (kw,), vals in sorted(updates.items()):
        if vals.get(("include",)):
            if kw not in panel:
                extras.append(kw)
                panel.append(kw)
                inclusion[kw] = dict((m, True) for m in profile.get("supported_matrices") or [])
        elif kw in extras:                              # never a method analyte
            extras.remove(kw)
            panel.remove(kw)
            inclusion.pop(kw, None)
    profile["master_analyte_set"] = panel
    if extras:
        profile[EXTRAS_KEY] = extras
    else:
        profile.pop(EXTRAS_KEY, None)
    return profile


PANEL_EXTRAS = cf.Table(
    id=u"px", title=u"Additional analytes", base=(),
    columns=[cf.Field("include", u"Add to this project", kind=cf.BOOL)],
    rows=extra_rows, rows_take_env=True, read=read_extras, write=write_extras,
    row_heading=u"Defined service")


def _matrix_choices(profile, env=None):
    return [(m, m) for m in profile.get("supported_matrices") or []]


def _panel_choices(profile, env=None):
    labels = _analyte_titles(profile)
    return [(kw, labels.get(kw)) for kw in profile.get("master_analyte_set") or []]


GROUPS_TITLE = u"Who each tier applies to"
GROUPS = cf.Section(
    id=u"groups", title=u"Groups", base=(),
    groups=[(GROUPS_TITLE, [
        cf.Field("key_analytes", u"Regulated analytes", kind=cf.MULTI, choices=_panel_choices,
                 widget=u"picker", noun=u"analytes",
                 help=u"Analytes a \u201cRegulated analytes\u201d tier applies to; other analytes "
                      u"with an isotope standard are \u201cOther analytes\u201d."),
    ])])


def key_analytes(profile):
    """The method's key analytes (its own list), or the compound library's
    key-analyte flag where a profile has no list."""
    if isinstance(profile.get("key_analytes"), list):
        return set(profile["key_analytes"])
    cl, lib = _library()
    return set(cl.key_keywords(lib))


def _qc_tiers():
    from senaite.pfas import qc_tiers
    return qc_tiers


def resolve_tier(profile, is_key, is_no_std, matrix, qc=RECOVERY_QC):
    """The ORDINARY tier the engine applies above the low level (None = it
    refuses: unconfigured) -- qc_tiers, the engine's own selection."""
    qt = _qc_tiers()
    try:
        chosen = qt.base_tier(profile, qc, matrix, is_key, is_no_std)
    except qt.Unconfigured:
        return None
    return chosen[0] if chosen else None


def low_level_tier(profile, base, matrix, qc=RECOVERY_QC):
    """The low-level tiers that may replace `base` at a low spike, smallest
    N first -- the engine's choice with the spike not yet known."""
    return _qc_tiers().low_level_candidates(profile, qc, base, matrix)


def no_std_set(profile):
    """Keywords with no labelled standard of their own in THIS method,
    derived from its surrogate links (senaite.pfas.labelled_coverage) and
    the compound library's labelled-form links."""
    from senaite.pfas import labelled_coverage as lc
    cl, lib = _library()
    return lc.no_labelled_standard(profile, cl.analog_map(lib))


RPD_QC_TYPES = (u"LFSMD", u"Dup")      # judged on an RPD limit, not a recovery window
GRID_LEVELS = (u"ordinary", u"low")
_GRID_GROUPS = [(u"key", u"Regulated analytes", lambda k, n: k and not n),
                (u"linked", u"Other analytes", lambda k, n: not k and not n),
                (u"no_std", u"No isotope standard", lambda k, n: n)]


def tier_window(tier, qc=RECOVERY_QC):
    """What a tier judges for `qc`: (min, max) recovery, or the RPD limit of
    an RPD type; None when the tier sets none."""
    if tier is None:
        return None
    if qc in RPD_QC_TYPES:
        return tier.get("rpd_max")
    if tier.get("recovery_min") is None:
        return None
    return (tier["recovery_min"], tier.get("recovery_max"))


def window_text(window, qc=RECOVERY_QC):
    if window is None:
        return u""
    if qc in RPD_QC_TYPES:
        return u"\u2264 %g" % window
    return u"%g \u2013 %g" % window


def tier_matrices(profile, tier):
    """The matrices `tier` applies in: every matrix the method supports, or
    the tier's own list (qc_tiers, the engine's own reading)."""
    return _qc_tiers().tier_matrices(profile, tier)


def tier_names_matrix(profile, tier, matrix):
    """Is `tier` scoped to `matrix` by its own matrix list (listed, and the
    list or an alias of a listed matrix names it)? Such a tier sets the
    window of the cells it applies to there on those cells; it names no
    analyte but through its group, which the engine has already matched."""
    if tier is None or _scope(tier) != LISTED:
        return False
    return _qc_tiers().in_scope(profile, tier, matrix)


def _grid_tier(profile, k, n, matrix, qc, level):
    """The tier the engine applies to a (key, no-standard) analyte in
    `matrix`: the ordinary tier, or at a low spike the low-level tier that
    replaces it (the smallest N with a window), else the ordinary one."""
    base = resolve_tier(profile, k, n, matrix, qc)
    if level == u"low":
        for x in low_level_tier(profile, base, matrix, qc):
            if tier_window(x, qc) is not None:
                return x
    return base


def _without_tier(profile, qc, tier):
    """The profile as it would be with `tier` removed from `qc`."""
    p = dict(profile)
    qca = dict(p.get("qc_acceptance") or {})
    entry = dict(qca.get(qc) or {})
    entry["tiers"] = [t for t in entry.get("tiers") or [] if t is not tier]
    qca[qc] = entry
    p["qc_acceptance"] = qca
    return p


def _method_default_tier(profile, qc):
    """The tier an analyte with its own labelled standard gets outside the
    matrices a key-analyte tier lists: the first ordinary "linked" / "all" tier."""
    for t in _tiers(profile, qc):
        if not t.get(LOW_LEVEL_KEY) and (t.get("analyte_group") or u"all") in (u"linked", u"all"):
            return t
    return None


def analyte_flags(profile):
    """{panel keyword: (is_key, is_no_std)}: the method's analyte groups.
    Key analytes are the method's own list (else the library's flag); no
    labelled standard comes from its own surrogate links."""
    keys = key_analytes(profile)
    no_std = no_std_set(profile)
    return dict((kw, (kw in keys, kw in no_std)) for kw in profile.get("master_analyte_set") or [])


def engine_flags(profile, flags=None):
    """The (is_key, is_no_std) the engine selects a tier with, per panel
    keyword: the analyte's groups while the Engine groups tiers, both off
    otherwise (it then applies its first ordinary tier to every analyte)."""
    flags = analyte_flags(profile) if flags is None else flags
    if not grouped_tiers(profile):
        return dict((kw, (False, False)) for kw in flags)
    return flags



def _tier_words(name):
    """A tier's name as the editor shows it (limit_placard.tier_words): the
    seeded keys read as words, a typed name as typed."""
    from senaite.pfas.limit_placard import tier_words
    return tier_words(name or u"")

def _own_cell(profile, own, k, n, m, qc_type, level, tiers, default):
    """The cell of an analyte whose own setting applies in `m`
    (qc_tiers.cell_setting): its window, or off ("off": True, no window),
    set by the cell itself ("own"); `fallback` is the tier that applies
    without it, which removing the setting leaves."""
    base = resolve_tier(profile, k, n, m, qc_type)
    window = None if own.get("off") else tier_window(_qc_tiers().cell_tier(base, own), qc_type)
    back = tier_window(base, qc_type)
    if window is None:
        text = u"off" if own.get("off") else u"not set"
    elif qc_type in RPD_QC_TYPES:
        text = u"\u2264 %g%%" % window
    else:
        text = u"%g\u2013%g%%" % window
    return {"text": text, "warn": window is None and not own.get("off"), "tier": None, "swatch": None,
            "source": u"This cell", "window": window, "off": bool(own.get("off")),
            "fallback": (u"Tier: %s" % _tier_words(base.get("name"))) if back is not None else None,
            "fallback_window": back, "default": False, "index": None, "set_by": u"own",
            "fallback_tier": base.get("name") if back is not None else None,
            "fallback_default": base is not None and base is default, "low": u""}


def _grid_cell(profile, k, n, m, qc_type, level, tiers, default, kw=None):
    """One cell of the grid: the window the engine applies to an analyte
    with flags (k, n) in matrix `m`, the tier that sets it and what applies
    with that tier removed (`fallback`, and that tier's own name
    `fallback_tier` where it sets a window; `fallback_default` where that
    tier is the method's default tier). `set_by` says what sets it: the
    analyte's own setting on this cell ("own", _own_cell; `kw` the analyte),
    the method's default tier ("method"), a tier listing the cell's matrix
    ("cell": its own matrix list names `m`, tier_names_matrix), another tier
    ("tier"), or nothing (None). At a low spike a low-level tier replaces an
    own window, as the engine does; an own "off" holds at every level."""
    own = _qc_tiers().cell_setting(profile, qc_type, kw, m) if kw else None
    if own is not None:
        low = None
        if level == u"low" and not own.get("off"):
            base = resolve_tier(profile, k, n, m, qc_type)
            low = next((x for x in (low_level_tier(profile, base, m, qc_type) if base else [])
                        if tier_window(x, qc_type) is not None), None)
        if low is None:
            return _own_cell(profile, own, k, n, m, qc_type, level, tiers, default)
    t = _grid_tier(profile, k, n, m, qc_type, level)
    window = tier_window(t, qc_type)
    if t is None:
        return {"text": u"not set", "warn": True, "tier": None, "swatch": None, "source": None,
                "window": None, "fallback": None, "fallback_window": None, "default": False,
                "index": None, "set_by": None, "fallback_tier": None,
                "fallback_default": False}
    set_by = u"method" if t is default else (u"cell" if tier_names_matrix(profile, t, m) else u"tier")
    back = _grid_tier(_without_tier(profile, qc_type, t), k, n, m, qc_type, level)
    back_name = back.get("name") if tier_window(back, qc_type) is not None else None
    back_default = back is not None and back is default
    if window is None:                    # the tier that applies sets no window: still the cell's tier
        return {"text": u"not set", "warn": True, "tier": t.get("name"), "swatch": None,
                "source": u"Tier: %s" % _tier_words(t.get("name")), "window": None,
                "fallback": (u"Tier: %s" % _tier_words(back.get("name"))) if tier_window(back, qc_type) is not None else None,
                "fallback_window": tier_window(back, qc_type), "default": t is default,
                "index": tiers.index(t), "set_by": set_by, "fallback_tier": back_name,
                "fallback_default": back_default}
    if qc_type in RPD_QC_TYPES:
        text = u"\u2264 %g%%" % window
    else:
        text = u"%g\u2013%g%%" % window
    if t.get("rsd_max") is not None and qc_type not in RPD_QC_TYPES:
        text += u" \u00b7 RSD \u2264 %g" % t["rsd_max"]
    low = u"; ".join(u"\u2264 %g\u00d7RL: %g\u2013%g%%" % (
        float(x[LOW_LEVEL_KEY]), x["recovery_min"], x["recovery_max"])
        for x in low_level_tier(profile, t, m, qc_type)
        if x.get("recovery_min") is not None) if level != u"low" else u""
    return {"text": text, "warn": False, "tier": t.get("name"), "low": low,
            "swatch": u"tier-c%d" % (tiers.index(t) % 6), "source": u"Tier: %s" % _tier_words(t.get("name")),
            "window": window,
            "fallback": (u"Tier: %s" % _tier_words(back.get("name"))) if tier_window(back, qc_type) is not None else None,
            "fallback_window": tier_window(back, qc_type), "default": t is default,
            "index": tiers.index(t), "set_by": set_by, "fallback_tier": back_name,
                "fallback_default": back_default}


def recovery_grid(profile, env=None, qc_type=RECOVERY_QC, level=u"ordinary"):
    """Analyte group rows x matrix columns, each cell the window the engine
    applies there for `qc_type` (a recovery window, or the RPD limit of an
    RPD type) at an ordinary or a low (level "low") spike. A group's cell is
    what an analyte of that group alone gets; `analytes` holds each member's
    own cells, resolved with the flags the engine uses for it
    (engine_flags), so an analyte in two groups (a key analyte with no
    labelled standard) shows the tier that actually applies to it. A cell
    names the tier that sets it (`source`) and what applies with that tier
    removed (`fallback`), which is what resetting it would leave."""
    flags = analyte_flags(profile)
    applied = engine_flags(profile, flags)
    grouped = grouped_tiers(profile)
    labels = _analyte_titles(profile)
    panel = profile.get("master_analyte_set") or []
    matrices = profile.get("supported_matrices") or []
    tiers = _tiers(profile, qc_type)
    default = _method_default_tier(profile, qc_type)
    pure = {u"key": (True, False), u"linked": (False, False), u"no_std": (False, True)}
    rows = []
    for gkey, title, member in _GRID_GROUPS:
        names = [kw for kw in panel if member(*flags.get(kw, (False, False)))]
        if not names:
            continue
        k, n = pure[gkey] if grouped else (False, False)
        cells = [_grid_cell(profile, k, n, m, qc_type, level, tiers, default) for m in matrices]
        analytes = OrderedDict()
        for kw in names:
            ak, an = applied[kw]
            own = any(_qc_tiers().cell_setting(profile, qc_type, kw, m) for m in matrices)
            analytes[kw] = (cells if (ak, an) == (k, n) and not own else
                            [_grid_cell(profile, ak, an, m, qc_type, level, tiers, default, kw)
                             for m in matrices])
        rows.append({"key": gkey, "title": title, "members": [labels.get(kw) for kw in names],
                     "keys": names, "cells": cells, "analytes": analytes})
    return {"matrices": matrices, "rows": rows}


# A setting on one analyte's cell in one matrix (qc_tiers.cell_setting): a
# window for an analyte outside its analyte group, or the check off for it
# there; stored beside the QC type's tiers (qc_acceptance[qc]["cells"]),
# set from the window grid's cell (its drawer writes this collection's rows)
# and saved with the tab. A recovery type takes a window, an RPD type an
# RPD limit, an extracted blank only Off.
CELLS_KEY = u"cells"
CELL_WINDOW_TYPES = (u"LFB", u"LFSM")
CELL_BLANK_TYPES = (u"MB", u"LRB", u"MxB", u"FRB")
CELL_TYPES = CELL_WINDOW_TYPES + RPD_QC_TYPES + CELL_BLANK_TYPES
CELL_SEP = u" \u00b7 "


def cell_label(qc_type, analyte, matrix):
    """The name a cell setting's row goes by: "LFSM · PFOA · Eggs"."""
    return CELL_SEP.join([qc_type or u"", analyte or u"", matrix or u""])


def cell_qc_choices(profile, env=None):
    """The QC types a cell may be set for: those the method holds."""
    qca = (profile or {}).get("qc_acceptance") or {}
    return [(q, QC_NAMES.get(q, q)) for q in CELL_TYPES if q in qca]


def read_cells(profile):
    out = []
    qca = (profile or {}).get("qc_acceptance") or {}
    for q in CELL_TYPES:
        for c in ((qca.get(q) or {}).get(CELLS_KEY) or []) if isinstance(qca.get(q), dict) else []:
            if not isinstance(c, dict):
                continue
            out.append({"cell": cell_label(q, c.get("analyte"), c.get("matrix")), "qc_type": q,
                        "analyte": c.get("analyte"), "matrix": c.get("matrix"),
                        "recovery_min": c.get("recovery_min"), "recovery_max": c.get("recovery_max"),
                        "rpd_max": c.get("rpd_max"), "off": bool(c.get("off"))})
    return out


def _stored_cell(q, r):
    cell = {"analyte": r.get("analyte"), "matrix": r.get("matrix")}
    if r.get("off"):
        cell["off"] = True
    elif q in RPD_QC_TYPES:
        cell["rpd_max"] = r.get("rpd_max")
    else:
        cell.update(recovery_min=r.get("recovery_min"), recovery_max=r.get("recovery_max"))
    return cell


def write_cells(profile, rows):
    qca = profile.setdefault("qc_acceptance", {})
    by = OrderedDict()
    for r in rows:
        by.setdefault(r.get("qc_type"), []).append(_stored_cell(r.get("qc_type"), r))
    for q in CELL_TYPES:
        entry = qca.get(q)
        if not isinstance(entry, dict):
            continue
        if by.get(q):
            entry[CELLS_KEY] = by[q]
        else:
            entry.pop(CELLS_KEY, None)            # none set: none stored
    return profile


def check_cells(profile, rows):
    errors, seen = [], set()
    offered = set(q for q, _l in cell_qc_choices(profile))
    panel = set(profile.get("master_analyte_set") or [])
    matrices = set(profile.get("supported_matrices") or [])
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    for r in rows:
        q, kw, m = r.get("qc_type"), r.get("analyte"), r.get("matrix")
        name = cell_label(q, kw, m)
        if q not in offered or kw not in panel or m not in matrices:
            errors.append(u"%s: choose a QC type, an analyte and a matrix of this method." % name)
            continue
        if not (inclusion.get(kw) or {}).get(m, True):
            errors.append(u"%s: %s is not reported in %s." % (name, kw, m))
        if (q, kw, m) in seen:
            errors.append(u"%s is set twice." % name)
        seen.add((q, kw, m))
        if r.get("off"):
            continue
        if q in CELL_BLANK_TYPES:
            errors.append(u"%s: a blank's cell is only switched off." % name)
        elif q in RPD_QC_TYPES:
            if r.get("rpd_max") is None:
                errors.append(u"%s: set its RPD limit, or switch it off." % name)
        else:
            lo, hi = r.get("recovery_min"), r.get("recovery_max")
            if lo is None or hi is None:
                errors.append(u"%s: set both ends of its window, or switch it off." % name)
            elif lo > hi:
                errors.append(u"%s: min (%s) is above max (%s)." % (name, lo, hi))
    return errors


QC_CELLS = cf.Collection(
    id=u"qc_cells", title=u"Set on one cell", noun=u"cell", allow_empty=True,
    empty=u"No cell is set on its own. Click a cell in the grid to set one.",
    columns=[cf.Field("cell", u"Cell", kind=cf.TEXT, placeholder=u"QC type \u00b7 analyte \u00b7 matrix"),
             cf.Field("qc_type", u"QC type", kind=cf.CHOICE, choices=cell_qc_choices),
             cf.Field("analyte", u"Analyte", kind=cf.CHOICE, choices=_panel_choices),
             cf.Field("matrix", u"Matrix", kind=cf.CHOICE, choices=_matrix_choices),
             cf.Field("recovery_min", u"Recovery min", minimum=0, unit=PCT,
                      range_hi="recovery_max", scale=PCT_SCALE, range_label=u"Window"),
             cf.Field("recovery_max", u"Recovery max", minimum=0, unit=PCT),
             cf.Field("rpd_max", u"Max RPD %", minimum=0),
             cf.Field("off", u"Not judged", kind=cf.BOOL)],
    read=read_cells, write=write_cells, check=check_cells)


# ── Reporting tab: certificate format per method x matrix ─────

from senaite.pfas import report_format as _rf


def report_rows(profile):
    """All matrices first: the method's default, drawn as the built-in
    settings it starts from (a choice selected, a text's default as its
    placeholder); each matrix row after it inherits a blank cell from it."""
    rows = [{"key": (_rf.ALL,), "group": u"rf", "label": u"All matrices (method default)",
             "defaults": dict((k, d) for k, _l, choices, d in _rf.SETTINGS if choices),
             "placeholders": dict((k, d) for k, _l, choices, d in _rf.SETTINGS if not choices)}]
    rows += [{"key": (m,), "group": u"rf", "label": m}
             for m in profile.get("supported_matrices") or []]
    return _one_group(u"rf", u"Certificate format"), rows


def read_report_format(profile):
    fmt = profile.get(_rf.KEY) or {}
    return dict(((scope,), dict((k, v) for k, v in (vals or {}).items()))
                for scope, vals in fmt.items() if isinstance(vals, dict))


def write_report_format(profile, updates, env=None):
    """A method with no format stored keeps none until a setting is made:
    an unchanged save writes nothing."""
    fmt = dict(profile.get(_rf.KEY) or {})
    for (scope,), vals in updates.items():
        row = dict(fmt.get(scope) or {})
        for (key,), value in vals.items():
            if value in (None, u""):
                row.pop(key, None)          # blank = inherit
            else:
                row[key] = value
        if row or (scope == _rf.ALL and scope in fmt):
            fmt[scope] = row
        else:
            fmt.pop(scope, None)
    if fmt or _rf.KEY in profile:
        profile[_rf.KEY] = fmt
    return profile


REPORT_FORMAT = cf.Table(
    id=u"rf", title=u"Certificate format", base=(_rf.KEY,),
    # a matrix row's blank cell inherits the All matrices row: a muted ·
    columns=[cf.Field(key, label, kind=cf.CHOICE if choices else cf.TEXT,
                      choices=choices, placeholder=cf.INHERITED)
             for key, label, choices, d in _rf.SETTINGS],
    rows=report_rows, read=read_report_format, write=write_report_format,
    row_heading=u"Matrix")


# Action levels / MCLs on the Reporting tab: the values
# stay on Regulatory Limits; per method x matrix the lab picks which of the
# limits naming that matrix the certificate evaluates. env carries the
# regulatory store ({"limits": [...], "programs": {...}}).

def _limit_matrices(profile, limit):
    named = set((m or u"").strip().lower() for m in (limit.get("matrices") or []))
    return [m for m in profile.get("supported_matrices") or [] if m.strip().lower() in named]


def action_level_rows(profile, env=None):
    store = (env or {}).get("regulatory") or {}
    names = store.get("programs") or {}
    rows = []
    for m in profile.get("supported_matrices") or []:
        for lim in store.get("limits") or []:
            if not lim.get("id") or lim.get("retired") or m not in _limit_matrices(profile, lim):
                continue
            prog = (names.get(lim.get("program")) or {}).get("name") or lim.get("program") or u""
            # not verified is a status, a grey tag: the limit is never
            # printed, and nothing here blocks a certificate
            note = u"%s %s \u00b7 %s %s" % (prog, lim.get("kind") or u"", lim.get("value"), lim.get("unit") or u"")
            if not lim.get("verified"):
                note += u" \u00b7 not confirmed: never printed"
            rows.append({"key": (lim["id"], m), "group": u"al", "label": lim.get("label") or lim["id"],
                         "sublabel": m, "note": note, "warn": False, "tag": not lim.get("verified")})
    return _one_group(u"al", u"Action levels & MCLs"), rows


def read_action_levels(profile):
    out = {}
    for m, row in ((profile.get(_rf.KEY) or {}).items()):
        if isinstance(row, dict):
            for lid in row.get(_rf.LIMITS_OFF) or []:
                out[(lid, m)] = {"applies": u"off"}
    return out


def write_action_levels(profile, updates, env=None):
    for (lid, m), vals in updates.items():
        _rf.set_limit(profile, m, lid, vals.get((u"applies",)) != u"off")
    return profile


# an action level is printed (Evaluate, blank) or left off (Off): a placard
# set by a right click; Enforced is never offered, it holds no release
ACTION_LEVELS = cf.Table(
    id=u"al", title=u"Action levels & MCLs", base=(_rf.KEY,),
    columns=[cf.Field("applies", u"On this method\u2019s certificates", kind=cf.CHOICE, widget=u"placard",
                      choices=[(u"", u"Evaluate"), (u"off", u"Off")],
                      states=[(u"evaluate", u""), (u"off", u"off")])],
    rows=action_level_rows, rows_take_env=True, read=read_action_levels,
    write=write_action_levels, row_heading=u"Limit")


# ── QC Types tab: every QC type the lab defines ────────────────
# The lab's QC types are the TAGGED core Reference Definitions ([QC:CODE] in the
# description, editable in Setup): every one is listed, not only those in the
# method's qc_acceptance, so any can be switched on.

QC_KIND = {"MB": "blank", "LRB": "blank", "MXB": "blank",
           "LFB": "recovery", "LCS": "recovery", "LFSM": "recovery",   # LCS: its own type
           "LFSMD": "rpd", "DUP": "rpd",
           "CAL": "instrument", "ICV": "instrument", "CCV": "instrument", "CCB": "instrument",
           "SUR": "surrogate"}
# qc_acceptance keys keep the spellings the pipeline matches on.
PROFILE_KEY = {"DUP": "Dup", "MXB": "MxB"}
CONFIGURED_ON = {"instrument": ("pane-qc", u"QC criteria"),
                 "surrogate": ("pane-standards", u"Isotope standards")}


def qc_type_rows(profile, label_map):
    """One row per QC type: every tagged type (label_map = {CODE: name}) plus
    any the method already carries. Batch QC types toggle here; instrument and
    surrogate types are shown with where they are configured."""
    qca = profile.get("qc_acceptance") or {}
    by_code = dict((k.upper(), k) for k in qca)
    codes = sorted(set(label_map) | set(by_code), key=lambda c: (
        ["blank", "recovery", "rpd", "instrument", "surrogate"].index(QC_KIND.get(c, "rpd")), c))
    rows = []
    for code in codes:
        kind = QC_KIND.get(code, "other")
        key = by_code.get(code) or PROFILE_KEY.get(code, code)
        cfg = qca.get(key) or {}
        tiers = cfg.get("tiers") or []
        rows.append({
            "code": code, "key": key, "label": label_map.get(code) or code, "kind": kind,
            "toggle": kind in ("blank", "recovery", "rpd", "other"),
            "enabled": bool(cfg.get("enabled")),
            "present": key in qca,
            "has_criteria": any(any(t.get(f) is not None for f in (
                "recovery_min", "recovery_max", "rpd_max", "max_conc_x_rl")) for t in tiers),
            "configured_on": CONFIGURED_ON.get(kind),
        })
    return rows


def apply_qc_toggles(profile, offered, enabled):
    """Write the wizard's QC-type choices. `offered` = the keys the page
    showed with a toggle; each sets its row's state and its `enabled` flag
    together (a switch left on keeps Evaluate). A type switched on that the
    method never had is created ENABLED with NO limits -- the engine then
    refuses to judge it until criteria are set, rather than this page
    inventing a recovery window."""
    for key in offered:
        if key in enabled and not isinstance((profile.get("qc_acceptance") or {}).get(key), dict):
            profile.setdefault("qc_acceptance", {})[key] = {"enabled": True, "tiers": []}
        _rules.set_qc_row_state(profile, key, _rules.qc_row_switched(profile, key, key in enabled))
    return profile


# ── Integration (a run imported from raw data) ───────────────────────────────
# How the LIMS integrates the instrument's raw chromatograms for this method:
# nothing is seeded, and a raw run of a method with any of it unset is
# refused, naming what is missing (pfas_pipeline get_integration). Each
# analyte and labelled standard has its transitions, retention time and
# window; a co-eluting pair is fitted together; an analyte with isomers is
# its linear and branched peaks, the branched peak every peak in its window
# but its linear partner's, summed.

INTEGRATION_MODES = [(u"vendor", u"Instrument software"), (u"validation", u"Validation"),
                     (u"lims", u"LIMS integration")]

INTEGRATION_HELP = {
    u"vendor": u"the vendor's exported results are reported; nothing below applies",
    u"validation": (u"the vendor's results are reported; the LIMS also integrates the raw data "
                    u"and keeps its results for comparison"),
    u"lims": u"the LIMS's results are reported; the vendor's export is kept for comparison"}

# how a peak's area is measured: the method default and a compound's own
INTEGRATION_AREAS = [(u"trapezoid", u"Baseline and trapezoid"), (u"gaussian", u"Gaussian fit"),
                     (u"emg", u"Exponentially modified Gaussian fit")]

# how the peaks are found: an unset engine is Classic
INTEGRATION_ENGINES = [(u"classic", u"Classic"), (u"adaptive", u"Adaptive")]
ADAPTIVE = (u"engine", u"adaptive")
# Adaptive draws each group's baseline itself: the Baseline choice is Classic's
CLASSIC = (u"engine", u"classic")
# a fitted area, under either engine, has its largest deviation from the trapezoid
FITTED = (u"area", (u"gaussian", u"emg"))
# smoothing may be the word, under Adaptive: the half-width is then learned
AUTO = u"auto"
# where a peak is expected under Adaptive: unset is fixed
RT_ANCHORS = [(u"fixed", u"Fixed"), (u"labelled", u"Isotope standard")]

from senaite.pfas import raw_preview as _preview


def _default_manual_change(profile, env=None):
    """What a blank smallest manual change resolves to: the default."""
    return _preview.DEFAULT_MIN_MANUAL_CHANGE_PCT


def _lab_fit_accept_score(profile, env=None):
    """What a blank score to accept a fit resolves to: the lab's default."""
    from senaite.pfas import fit_accept
    return (env or {}).get("fit_accept_default") or fit_accept.DEFAULT


# a saved apex choice whose candidate a raised floor no longer offers is
# kept with no effect, the trace automatic, until that choice is undone
APEX_CHOICE_FLOOR = u"Raising it can leave a saved apex choice unapplied until it is undone."

# the rules for a dropped baseline and the candidates offered, and Classic's
# edge points, which set the automatic peaks' baselines: (key, label, whole
# number, unit, smallest allowed for a whole number, help); a blank is the
# default, drawn muted, and a compound may override all but the search slope
# and its smoothing
REVIEW_FIELDS = [
    ("edge_points", u"Edge points", True, u"points", 1,
     u"Each automatic baseline end is the mean of this many raw points just outside the peak, so it "
     u"changes the automatic peaks."),
    ("min_peak_points", u"Fewest points in a peak", True, u"points", 3,
     u"A manual peak with fewer samples between its edges is refused; the trapezoid needs four or "
     u"five points above the baseline."),
    ("edge_sigma", u"Edges past the tail", False, u"sigma", None,
     u"How far from the apex, in standard deviations, the automatic edges reach at least; a "
     u"broadened peak takes more on the tailing side."),
    ("drop_valley_max_pct", u"Valley limit for a perpendicular drop", False, u"%", None,
     u"A perpendicular drop between two peaks is flagged when the valley is higher than this share "
     u"of the smaller peak."),
    ("skim_ratio_pct", u"Tangent skim ratio", False, u"%", None,
     u"A peak riding on another takes a tangent skim when it is under this share of the parent's "
     u"height."),
    ("search_slope", u"Peak search slope", False, u"", None,
     u"The slope threshold of the smoothed derivative that marks a peak, for a peak of unit height, as "
     u"a multiple of one over the squared width in points."),
    ("search_amp_sn", u"Peak search amplitude", False, u"S/N", None,
     u"A found peak must rise this many noise deviations above the baseline."),
    ("search_smooth_pct", u"Peak search smoothing", False, u"%", None,
     u"The smoothing width used to find edges and apexes, as a share of the points in the "
     u"half-width."),
    ("candidate_min_points", u"Fewest points in a candidate", True, u"points", 2,
     u"A candidate peak with fewer raw samples at or above half its height is not offered. At coarse "
     u"sampling a narrow real peak can fall under it: lower the value for that compound, or set its edges "
     u"by hand. " + APEX_CHOICE_FLOOR),
    ("candidate_min_fwhm_pct", u"Smallest candidate width", False, u"%", None,
     u"A candidate narrower than this share of the automatic peak's half-width is not offered. " +
     APEX_CHOICE_FLOOR)]
# the edge points set Classic's automatic peaks: a field of the method's
# defaults beside the smoothing, not of the review's group
ENGINE_REVIEW_FIELDS = ("edge_points",)


def _review_default(key, own=False):
    """What a blank `key` resolves to: with `own`, the method's value when
    set (a compound's blank), else the default. An unset peak search
    amplitude is the smallest S/N for a manual peak where one is set."""
    def resolved(profile, env=None):
        intg = (profile or {}).get(u"integration") or {}
        value = intg.get(key) if own else None
        if value in (None, u""):
            value = _preview.REVIEW_DEFAULTS[str(key)]
        if value is None:
            sn = intg.get(u"min_manual_sn")
            value = _preview.DEFAULT_SEARCH_AMP_SN if sn in (None, u"") else sn
        return value
    return resolved


def _review_field(field, show_if=None):
    """The method's field of one of REVIEW_FIELDS, its blank drawn as the
    default."""
    key, label, whole, unit, low, hlp = field
    return cf.Field(key, label, kind=cf.INT if whole else cf.NUMBER, unit=unit, help=hlp,
                    minimum=low if whole else None, greater_than=None if whole else 0,
                    resolved=_review_default(key), show_if=show_if)


RT_TOL_LABEL = u"Retention time tolerance"
RT_UNIT_LABEL = u"Retention time tolerance in"
RT_TOL_HELP = (u"Every compound's window is its retention time plus or minus this; blank: "
               u"each transition's own window")
RT_UNIT_HELP = {_rtw.PCT: u"the window is the retention time times this value, each side",
                _rtw.MIN: u"the window is the retention time plus or minus the value"}

INTEGRATION = cf.Section(
    id=u"intg", title=u"Integration", base=(u"integration",),
    groups=[(u"Results", [
        cf.Field("mode", u"Results come from", kind=cf.CHOICE, choices=INTEGRATION_MODES,
                 widget=u"seg", choice_help=INTEGRATION_HELP)]),
        (u"Peak integration: method defaults", [
            # unset is integrated as Classic, so it is drawn as Classic and its
            # Baseline shows
            cf.Field("engine", u"Engine", kind=cf.CHOICE, choices=INTEGRATION_ENGINES, widget=u"seg",
                     default=u"classic",
                     choice_help={u"classic": u"a fixed smoothing finds each peak in its window",
                                  u"adaptive": u"the slope of the signal finds each peak and its shoulders"}),
            cf.Field("smooth_points", u"Smoothing", kind=cf.INT, unit=u"points", words=[AUTO],
                     help=u"Savitzky-Golay width, an odd number of points, or auto under Adaptive; "
                          u"finds the peak, never measures it"),
        ] + [_review_field(f, show_if=CLASSIC) for f in REVIEW_FIELDS if f[0] in ENGINE_REVIEW_FIELDS] + [
            cf.Field("baseline", u"Baseline", kind=cf.CHOICE, show_if=CLASSIC,
                     choices=[(u"valley", u"Valley to valley"), (u"drop", u"Flat at the lower edge")]),
            cf.Field("area", u"Area", kind=cf.CHOICE, choices=INTEGRATION_AREAS),
            cf.Field("min_sn", u"Smallest signal-to-noise reported", greater_than=0),
            cf.Field("mz_tolerance", u"Transition tolerance", unit=u"m/z", greater_than=0,
                     help=u"How far a file's transition may be from the method's, on Q1 and Q3"),
            # one window rule for every compound (rt_window); blank keeps
            # each transition's stored window
            cf.Field(_rtw.TOL_KEY, RT_TOL_LABEL, greater_than=0, help=RT_TOL_HELP),
            cf.Field(_rtw.UNIT_KEY, RT_UNIT_LABEL, kind=cf.CHOICE, choices=list(_rtw.UNITS), widget=u"seg",
                     default=_rtw.PCT, choice_help=RT_UNIT_HELP),
            cf.Field("sensitivity", u"Sensitivity", greater_than=0, show_if=ADAPTIVE,
                     help=u"The slope that starts a peak, as a multiple of the noise"),
            cf.Field("shoulder_pct", u"Shoulder split", unit=u"%", greater_than=0, show_if=ADAPTIVE,
                     help=u"A flat stretch above this share of the peak height splits a shoulder; below 100"),
            cf.Field("qual_apex_tol", u"Qualifier apex tolerance", unit=u"min", greater_than=0,
                     show_if=ADAPTIVE, help=u"The qualifier peak's apex lies this close to the quantifier's"),
            cf.Field("fit_max_dev_pct", u"Largest fit deviation", unit=u"%", greater_than=0,
                     show_if=FITTED,
                     help=u"A Gaussian or EMG area further than this from the trapezoid falls back to it"),
            cf.Field("rt_anchor", u"Expected time", kind=cf.CHOICE, choices=RT_ANCHORS, widget=u"seg",
                     show_if=ADAPTIVE,
                     choice_help={u"fixed": u"each peak is sought at its own retention time",
                                  u"labelled": u"a native's time moves with its isotope standard's "
                                               u"found time in each injection"}),
            # an analyst's re-integration or apex choice, on a quantifier or
            # a qualifier, is refused under either limit; a deletion never is
            cf.Field("min_manual_change_pct", u"Smallest manual change", unit=u"%", greater_than=0,
                     resolved=_default_manual_change,
                     help=u"A re-integration or another apex that moves the area less than this "
                          u"from the automatic area is refused; a deleted peak is not"),
            cf.Field("min_manual_sn", u"Smallest S/N for a manual peak", greater_than=0,
                     help=u"A re-integrated or chosen peak under it is refused; blank: not judged"),
            # the lab's own limit on a fit of overlapping peaks, the RMS of
            # what it leaves over the trace's baseline noise: no default, and
            # no fit is made until it is set
            cf.Field("fit_noise_multiple", u"Largest fit residual, times the baseline noise", greater_than=0,
                     help=u"A fit of overlapping peaks leaving more than this many times the baseline noise is "
                          u"refused; blank: no fit is allowed"),
            # a fit scoring this or more is accepted; it colours the score
            # badge and gates nothing
            cf.Field("fit_accept_score", u"Score to accept a fit", kind=cf.INT, minimum=1, maximum=100,
                     resolved=_lab_fit_accept_score,
                     help=u"A fit scoring this or more is accepted; blank uses the lab's default")]),
        # the rules the review applies when a baseline is dropped or a
        # candidate is offered: a blank is the default drawn muted in the box
        (u"Peak review: baseline and candidates", [
            _review_field(f) for f in REVIEW_FIELDS if f[0] not in ENGINE_REVIEW_FIELDS])])

INTEGRATION_PEAK_MODES = [(u"single", u"Single peak"), (u"pair", u"Co-eluting pair"),
                          (u"summed", u"Summed isomers")]


def _compound_label(profile):
    """label(keyword): a compound by the name the certificate and the QC
    Review print: an analyte by its display name in this method
    (_analyte_titles), a labelled standard by the compound library's; an
    isomer peak by its own name, which says which peak it is."""
    titles = _analyte_titles(profile)
    cl, lib = _library()
    labelled = cl.labelled_names(lib)
    peaks = _iso.peak_names(profile)

    def label(kw):
        if kw in peaks:
            return kw
        return labelled.get(kw) or titles.get(kw) or kw
    return label


def integration_rows(profile):
    """The method's analytes, then its labelled standards. An analyte with
    isomers is its linear and branched peaks, each partnered with the other
    from the Isomers tab, a branched peak summed; a row stored for the
    analyte itself stays listed, marked unused, until it is cleared."""
    panel = list(profile.get("master_analyte_set") or [])
    names = _iso.integration_names(profile, panel)
    labelled = [k for k in sorted(_ls.grid(profile)) if k not in names]
    partners, branched = _iso.partners(profile), _iso.branched_peaks(profile)
    label = _compound_label(profile)
    rows = []
    for kw in names + labelled:
        row = {"key": (kw,), "group": u"intg_an", "label": label(kw), "sublabel": u""}
        if kw in partners:
            row["sublabel"] = u"%s %s" % (_iso.summed_of(profile, kw), u"branched" if kw in branched else u"linear")
            # a branched peak is summed, its linear partner a single peak
            row["defaults"] = {"partner": partners[kw],
                               "mode": u"summed" if kw in branched else u"single"}
        rows.append(row)
    stored = (profile.get(u"integration") or {}).get(u"analytes") or {}
    for kw in panel:
        peaks = _iso.peaks_of(profile, kw)
        if peaks and kw in stored:
            rows.append({"key": (kw,), "group": u"intg_an", "label": label(kw), "sublabel": u"", "warn": True,
                         "note": u"Not used: integrated as %s" % u" and ".join(peaks)})
    return _one_group(u"intg_an", u"Transitions and windows"), rows


def partner_choices(profile, env=None):
    _groups, rows = integration_rows(profile)
    return [(r["key"][0], r["label"]) for r in rows]


def transition(text):
    """(q1, q3) from "413.0 > 369.0"; ValueError when it is not one."""
    parts = [p.strip() for p in (text or u"").split(u">")]
    if len(parts) != 2:
        raise ValueError(text)
    return (float(parts[0]), float(parts[1]))


def transitions(text):
    return [transition(t) for t in (text or u"").split(u";") if t.strip()]


def _transition_text(q):
    return u"%r > %r" % (float(q[0]), float(q[1]))


def read_integration(profile):
    rows = ((profile.get(u"integration") or {}).get(u"analytes") or {})
    out = {}
    for kw, row in rows.items():
        vals = dict(row)
        if row.get(u"quant"):
            vals[u"quant"] = _transition_text(row[u"quant"])
        vals[u"quals"] = u"; ".join(_transition_text(q) for q in row.get(u"quals") or [])
        out[(kw,)] = vals
    return out


def write_integration(profile, updates, env=None):
    intg = profile.get(u"integration")
    intg = dict(intg) if isinstance(intg, dict) else {}
    rows = dict(intg.get(u"analytes") or {})
    for (kw,), vals in updates.items():
        # a compound's processing entry is set only by a countersigned
        # proposal (method_proposals), never on this table: a save keeps it,
        # and a row left with an empty one and nothing else is cleared
        kept = (rows.get(kw) or {}).get(u"processing") if isinstance(rows.get(kw), dict) else None
        row = {}
        for (name,), value in vals.items():
            if value in (None, u"", cf.REMOVE):
                continue
            if name == u"quant":
                value = list(transition(value))
            elif name == u"quals":
                value = [list(q) for q in transitions(value)]
            row[name] = value
        if kept is not None and (row or not _mp.empty_processing(kept)):
            row[u"processing"] = kept
        if row:
            rows[kw] = row
        else:
            rows.pop(kw, None)
    if rows:
        intg[u"analytes"] = rows
    else:
        intg.pop(u"analytes", None)
    if intg:
        profile[u"integration"] = intg
    else:
        profile.pop(u"integration", None)
    return profile


def _integration_row(row, values):
    kw = row["key"][0]
    try:
        if values.get(u"f__quant"):
            transition(values.get(u"f__quant"))
        transitions(values.get(u"f__quals"))
    except ValueError:
        return u"%s: a transition is Q1 > Q3, e.g. 413.0 > 369.0; qualifiers are separated by ;" % kw
    # an isomer peak's partner and a branched peak's mode are the Isomers tab's
    derived = row.get("defaults") or {}
    for name, what in ((u"partner", u"partner"), (u"mode", u"peak")):
        typed = values.get(u"f__" + name)
        if derived.get(name) and typed not in (None, u"") and typed != derived[name]:
            return u"%s: its %s is %s, set by the Isomers tab." % (kw, what, dict(
                INTEGRATION_PEAK_MODES).get(derived[name], derived[name]))
    if values.get(u"f__mode") == u"pair" and not (values.get(u"f__partner") or derived.get(u"partner")):
        return u"%s: name its partner, the peak it is fitted with." % kw
    # what no engine takes; each engine's own rule is check_integration's,
    # which sees the engine saved with it
    n = values.get(u"f__smooth_points")
    if n not in (None, AUTO) and (int(n) % 2 == 0 or int(n) < 3):
        return u"%s: smoothing is auto or an odd number of points, 3 or more." % kw
    return None


def _method_default(key, default=None):
    """What a compound's blank `key` resolves to: the method's own default,
    else `default`."""
    def resolved(profile, env=None):
        value = ((profile or {}).get(u"integration") or {}).get(key)
        return default if value in (None, u"") else value
    return resolved


def _confirmation_sn(profile, env=None):
    """What a compound's blank confirmation-ion S/N resolves to: the method's
    confirmation value."""
    return (((profile or {}).get(u"instrument_verification") or {}).get(u"confirmation") or {}).get(
        u"sn_confirm_min")


INTEGRATION_ANALYTES = cf.Table(
    id=u"intg_an", title=u"Transitions and windows", base=(u"integration", u"analytes"),
    # a compound's smoothing, area, smallest S/N, sensitivity, expected time
    # and manual-peak limits override the method defaults for its quantifier
    # and qualifiers, its
    # qualifier detection S/N the method's confirmation value as the floor a
    # qualifier is found at (the method's value alone judges N.C.); a blank uses the
    # default, shown muted in the empty cell. A row's "processing" entry, the
    # processing changes countersigned from a run (method_proposals), is read
    # only: no column edits it and write_integration keeps it
    columns=[cf.Field("smooth_points", u"Smoothing", kind=cf.INT, unit=u"points", words=[AUTO],
                      resolved=_method_default(u"smooth_points")),
             cf.Field("area", u"Area", kind=cf.CHOICE, choices=INTEGRATION_AREAS,
                      resolved=_method_default(u"area")),
             cf.Field("min_sn", u"Smallest S/N", greater_than=0, resolved=_method_default(u"min_sn")),
             cf.Field("sensitivity", u"Sensitivity", greater_than=0, resolved=_method_default(u"sensitivity")),
             cf.Field("min_qual_sn", u"Qualifier detection S/N", greater_than=0, resolved=_confirmation_sn,
                      help=u"Below it a qualifier counts as not found; the method's confirmation S/N "
                           u"decides whether the identity is confirmed"),
             cf.Field("rt_anchor", u"Expected time", kind=cf.CHOICE, choices=RT_ANCHORS,
                      resolved=_method_default(u"rt_anchor")),
             cf.Field("min_manual_change_pct", u"Smallest manual change", unit=u"%", greater_than=0,
                      resolved=_method_default(u"min_manual_change_pct",
                                               _preview.DEFAULT_MIN_MANUAL_CHANGE_PCT)),
             cf.Field("min_manual_sn", u"Smallest S/N for a manual peak", greater_than=0,
                      resolved=_method_default(u"min_manual_sn"))
             ] + [cf.Field(key, label, kind=cf.INT if whole else cf.NUMBER, unit=unit,
                           minimum=low if whole else None, greater_than=None if whole else 0,
                           resolved=_review_default(key, own=True))
                  for key, label, whole, unit, low, _help in REVIEW_FIELDS
                  if key not in _preview.REVIEW_METHOD_ONLY] + [
             cf.Field("quant", u"Quantifier", kind=cf.TEXT, placeholder=u"Q1 > Q3"),
             cf.Field("quals", u"Qualifiers", kind=cf.TEXT, placeholder=u"Q1 > Q3; Q1 > Q3"),
             cf.Field("rt", u"Retention time", unit=u"min", greater_than=0),
             cf.Field("window", u"Window", unit=u"\u00b1 min", greater_than=0,
                      help=u"Used while the method's Retention time tolerance is blank"),
             cf.Field("mode", u"Peak", kind=cf.CHOICE, choices=INTEGRATION_PEAK_MODES),
             cf.Field("partner", u"Partner", kind=cf.CHOICE, choices=partner_choices),
             cf.Field("expected_ion_ratio", u"Expected ion ratio", greater_than=0)],
    rows=integration_rows, read=read_integration, write=write_integration,
    check=_integration_row, row_heading=u"Compound")


def _smoothing_error(n, engine):
    """Why `n` is not a smoothing `engine` takes, or None. Classic: an odd
    number of points, 5 or more. Adaptive: auto or an odd number, 3 or more."""
    if n in (None, u""):
        return None
    if engine == u"adaptive":
        if n == AUTO or (int(n) % 2 == 1 and int(n) >= 3):
            return None
        return u"smoothing is auto or an odd number of points, 3 or more"
    if n != AUTO and int(n) % 2 == 1 and int(n) >= 5:
        return None
    return u"smoothing is an odd number of points, 5 or more; auto is Adaptive only"


def _partner_pairs(profile):
    """[(a, b)]: each pair of partnered rows once, an isomer peak's partner
    from the Isomers tab, any other row's as typed."""
    rows = ((profile or {}).get(u"integration") or {}).get(u"analytes") or {}
    derived = _iso.partners(profile or {})
    pairs = []
    for kw in sorted(rows):
        partner = derived.get(kw) or (rows.get(kw) or {}).get(u"partner")
        if partner and partner != kw and tuple(sorted((kw, partner))) not in pairs:
            pairs.append(tuple(sorted((kw, partner))))
    return pairs


def check_integration(profile):
    """Smoothing, the method's and each compound's, follows the engine's
    rule; the shoulder split is below 100 %. Where the LIMS integrates,
    partnered rows' windows do not overlap, so each peak has one window, a
    row stored for an analyte with isomers, which is not used, is refused
    until cleared, and under Adaptive a co-eluting pair is refused. Where results come from has no check: it can change at
    any time."""
    intg = (profile or {}).get(u"integration") or {}
    engine = intg.get(u"engine") or u"classic"
    errors = []
    why = _smoothing_error(intg.get(u"smooth_points"), engine)
    if why:
        errors.append(u"Integration: %s." % why)
    for kw in sorted(intg.get(u"analytes") or {}):
        why = _smoothing_error(((intg.get(u"analytes") or {}).get(kw) or {}).get(u"smooth_points"), engine)
        if why:
            errors.append(u"Integration: %s: %s." % (kw, why))
    shoulder = intg.get(u"shoulder_pct")
    if shoulder not in (None, u"") and not float(shoulder) < 100:
        errors.append(u"Integration: the shoulder split is below 100 %.")
    try:
        tol = _rtw.tolerance(intg)
    except (TypeError, ValueError):
        tol = None
        errors.append(u"Integration: the Retention time tolerance is a number above 0, in % or min.")
    # the compound rows are shown, and can be put right, only where the LIMS
    # integrates: under Instrument software they are kept as stored
    if intg.get(u"mode") not in (u"validation", u"lims"):
        return errors
    rows = intg.get(u"analytes") or {}
    for a, b in _partner_pairs(profile):
        ra, rb = rows.get(a) or {}, rows.get(b) or {}
        # each peak's window as the worker searches it: the method's
        # tolerance where it is set, else the window stored with the row
        try:
            wa = _rtw.half_width(ra.get(u"rt"), ra.get(u"window"), tol)[0]
            wb = _rtw.half_width(rb.get(u"rt"), rb.get(u"window"), tol)[0]
            if wa is None or wb is None:
                continue
            lo = max(float(ra[u"rt"]) - wa, float(rb[u"rt"]) - wb)
            hi = min(float(ra[u"rt"]) + wa, float(rb[u"rt"]) + wb)
        except (KeyError, TypeError, ValueError):
            continue
        if lo < hi:
            errors.append(u"Integration: the windows of %s and %s overlap from %.3g to %.3g min: "
                          u"narrow one so each peak has one window." % (a, b, lo, hi))
    unused = []
    for kw in (profile or {}).get(u"master_analyte_set") or []:
        peaks = _iso.peaks_of(profile, kw)
        if peaks and kw in rows:
            unused.append(kw)
            errors.append(u"Integration: %s is integrated as %s: clear its own row, which is not "
                          u"used, and enter theirs." % (kw, u" and ".join(peaks)))
    # Adaptive fits no pair: such a row would be integrated as the nearest
    # single peak; a branched peak is summed whatever its row says
    if engine == u"adaptive":
        branched = _iso.branched_peaks(profile or {})
        for kw in sorted(rows):
            if ((rows.get(kw) or {}).get(u"mode") == u"pair" and kw not in branched
                    and kw not in unused):
                errors.append(u"Integration: %s is a co-eluting pair, which the Adaptive engine does "
                              u"not fit: make it a single peak, or choose Classic." % kw)
    return errors


# ── Integration's change log ─────────────────────────────────────────────────
# The method profile's configuration history, kept to where results come
# from, the method defaults and each compound's smoothing, area, smallest
# S/N, sensitivity, qualifier detection S/N, expected time and manual-peak
# limits; transitions, times and windows are not in it.

INTEGRATION_LOG_LIMIT = 50
INTEGRATION_OVERRIDES = (u"smooth_points", u"area", u"min_sn", u"sensitivity", u"min_qual_sn", u"rt_anchor",
                         u"min_manual_change_pct", u"min_manual_sn") + tuple(
    f[0] for f in REVIEW_FIELDS if f[0] not in _preview.REVIEW_METHOD_ONLY)


def _log_leaves(path, before, after):
    """[(path, before, after)] down to single values: a first save is
    recorded as one change carrying the whole dict."""
    if isinstance(before, dict) or isinstance(after, dict):
        b = before if isinstance(before, dict) else {}
        a = after if isinstance(after, dict) else {}
        out = []
        for k in sorted(set(b) | set(a)):
            out += _log_leaves(path + (k,), b.get(k), a.get(k))
        return out
    blank = (None, u"")
    if before == after or (before in blank and after in blank):
        return []
    return [(path, before, after)]


def _log_value(field, value, blank):
    if value in (None, u""):
        return blank
    if u"%s" % value in field.words:
        return u"%s" % value
    if field.kind == cf.CHOICE:
        return dict(field.choices).get(value, u"%s" % value)
    if field.kind in (cf.INT, cf.NUMBER) and not isinstance(value, bool):
        try:
            value = u"{0:g}".format(float(value))
        except (TypeError, ValueError):
            pass
    return u"%s %s" % (value, field.unit) if field.unit else u"%s" % value


def _log_row(path):
    """(order, setting, field, blank) for a logged path, else None."""
    if len(path) == 2:
        for i, f in enumerate(INTEGRATION.fields()):
            if f.path == (path[1],):
                # an unset value the worker applies reads as that value
                blank = {(u"mode",): dict(INTEGRATION_MODES)[u"vendor"],
                         (u"engine",): dict(INTEGRATION_ENGINES)[u"classic"],
                         (u"min_manual_change_pct",): _log_value(
                             f, _preview.DEFAULT_MIN_MANUAL_CHANGE_PCT, u"")}
                default = _preview.REVIEW_DEFAULTS.get(f.path[0])
                if default is not None:
                    blank[f.path] = _log_value(f, default, u"")
                blank = blank.get(f.path, u"not set")
                return (0, u"", i), f.label, f, blank
    if len(path) == 4 and path[1] == u"analytes" and path[3] in INTEGRATION_OVERRIDES:
        f = [c for c in INTEGRATION_ANALYTES.columns if c.path == (path[3],)][0]
        return ((1, path[2], INTEGRATION_OVERRIDES.index(path[3])),
                u"%s \u00b7 %s" % (path[2], f.label), f, u"method default")
    return None


def _log_rows(entry):
    rows = []
    for change in entry.get(u"changes") or []:
        path = tuple(change.get(u"path") or ())
        if not path or path[0] != u"integration":
            continue
        for leaf, before, after in _log_leaves(path, change.get(u"before"), change.get(u"after")):
            spec = _log_row(leaf)
            if spec is None:
                continue
            order, setting, field, blank = spec
            rows.append((order, {"when": lab_time.show(entry.get(u"at") or u""),
                                 "who": entry.get(u"who") or u"system", "setting": setting,
                                 "from": _log_value(field, before, blank),
                                 "to": _log_value(field, after, blank)}))
    # the section's order: the choice, the defaults, then compounds by name,
    # each one's settings in column order
    rows.sort(key=lambda r: r[0])
    return [r for _o, r in rows]


def integration_log(fetch, limit=INTEGRATION_LOG_LIMIT, page=1000):
    """The Integration section's change log, newest first, at most `limit`
    rows of {"when" (YYYY-MM-DD HH:MM), "who", "setting", "from", "to"}:
    values as the page names them, a compound's blank as the method default.
    fetch(offset, n) gives the method profile's history entries, newest
    first (config_history.entries)."""
    rows, offset = [], 0
    while len(rows) < limit:
        batch = fetch(offset, page) or []
        for entry in batch:
            rows.extend(_log_rows(entry))
            if len(rows) >= limit:
                break
        if len(batch) < page:
            break
        offset += page
    return rows[:limit]


# Whole-profile checks, run after a tab's sections are applied, keyed by the
# sections whose save must pass them.
# ── one home per setting: Calibration & CCV and Engine carved into
# the tabs that hold each setting -- same bases, same keys ──────────────────
ORIGINAL_PATHS = {u"cal": [f.path for f in CALIBRATION_CCV.fields()], u"engine": [f.path for f in ENGINE.fields()]}


def _carve(section, new_id, title, take):
    """The fields `take(path)` picks, as their own section on the same base;
    the rest stay in `section`. Group titles are kept."""
    picked, rest = [], []
    for gtitle, fields in section.groups:
        p = [f for f in fields if take(f.path)]
        r = [f for f in fields if not take(f.path)]
        if p:
            picked.append((gtitle, p))
        if r:
            rest.append((gtitle, r))
    section.groups = rest
    return cf.Section(id=new_id, title=title, base=section.base, groups=picked)


# what shapes a run, set on Run & reporting; the CCV frequency judges a CCV
# and stays with the CCV's limits on QC criteria
_RUN_PATHS = set([(u"ccv", u"opens_run"), (u"ccv", u"counts_extracted_qc"),
                  (u"calibration", u"new_curve"), (u"calibration", u"max_age_days"),
                  (u"icv", u"after_new_curve"), (u"icv", u"when_reused")])
RUN_RULES = _carve(CALIBRATION_CCV, u"run_rules", u"Run rules", lambda p: tuple(p) in _RUN_PATHS)
# on Run & reporting the CCV's run rules read as what they are
RUN_RULES.groups = [(u"Run rules" if t == u"Continuing Calibration Verification (CCV)" else t, f)
                    for t, f in RUN_RULES.groups]
CAL_SURROGATES = _carve(CALIBRATION_CCV, u"cal_sur", u"Surrogates",
                        lambda p: p[0] == u"surrogate_window" or tuple(p) in (
                            (u"ccv", u"surrogate_recovery"), (u"ccv", u"surrogate_window_min"),
                            (u"ccv", u"surrogate_window_max")))
# the internal standards' response windows: on the Isotope standards tab,
# saved by its form with the rules they belong to
CAL_IS = _carve(CALIBRATION_CCV, u"cal_is", u"IS response", lambda p: p[0] == u"is_response")
# the labelled compounds' fit with them: shown on the Surrogates card and
# saved by the Isotope standards tab, no longer on Engine
ENGINE_SURROGATES = _carve(ENGINE, u"engine_sur", u"Surrogates and extracted standards",
                           lambda p: p[0] in (u"eis_recovery_limits",
                                              u"eis_default_window", u"eis_verify_flag",
                                              u"labelled_compound_fit"))
ENGINE_AMI = _carve(ENGINE, u"engine_ami", u"Analyte \u00d7 matrix", lambda p: p[0] == u"inclusion_needs_verification")
ENGINE_RECOVERY = _carve(ENGINE, u"engine_rec", u"Recoveries", lambda p: p[0] == u"recovery_decimals")


# \u2500\u2500 Analyte x matrix inclusion: the Analytes tab's panel switches \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# The switches post ami.<keyword>.<matrix> (profile_form.panel_switch_names)
# and profile_form.apply_loose writes them. This declaration gives the tab
# the inclusion's stale-save stamp: a save opened before someone else
# changed the panel is refused. It writes nothing itself.

def _ami_columns(profile):
    return [cf.Field((m,), m, kind=cf.BOOL) for m in profile.get("supported_matrices") or []]


def _ami_rows(profile):
    titles = _analyte_titles(profile)
    rows = [{"key": (kw,), "group": u"ami", "label": titles.get(kw, kw), "sublabel": kw}
            for kw in profile.get("master_analyte_set") or []]
    return _one_group(u"ami", u"Analyte \u00d7 matrix"), rows


def read_inclusion(profile):
    """{(keyword,): {matrix: stored switch}}; an absent matrix reads None
    (reported: absent means included)."""
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    return dict(((kw,), dict(inclusion.get(kw) or {})) for kw in profile.get("master_analyte_set") or [])


def _ami_write(profile, updates, env=None):
    return profile


AMI = cf.Table(
    id=u"ami", title=u"Analyte \u00d7 matrix panel", base=("analyte_matrix_inclusion",),
    columns=_ami_columns, rows=_ami_rows, read=read_inclusion, write=_ami_write)


def _names_rows(profile, env=None):
    groups, rows = _text_rows(profile, env)
    return groups, [r for r in rows if r["key"] in ((u"aliases",), (u"qc_type_aliases",))]


ENGINE_NAMES = cf.Table(
    id=u"engine_names", title=u"Method & names", base=(),
    columns=[cf.Field("value", u"Value", kind=cf.TEXT)],
    rows=_names_rows, rows_take_env=True, read=read_engine_text, write=write_engine_text,
    check=_check_engine_text, row_heading=u"Setting")


# ── Each QC rule's flag (rule_flags) ──────────────────────────
# One row per rule card: its code (a QC Qualifiers entry, read only there),
# where the code attaches and the reviewers' note. Two tables, one per form,
# as the rules are held: the Isotope standards tab posts its three rules',
# QC criteria every other rule's and each recovery tier's.
FLAG_GROUP = (u"flags", u"Flags")


def flag_code_choices(stored=None, env=None):
    """[(entry key, "NC \u00b7 Ion ratio / confirmation")]: the QC Qualifiers
    entries that carry a code, code first then the failure it was written
    for; "No code" is the blank choice."""
    return [(e["key"], u"%s \u00b7 %s" % (e["code"], e["label"]))
            for e in _rule_flags().code_entries(qualifier_library(env))]


def qualifier_library(env=None):
    """The QC Qualifiers library the page was given (env "qualifiers"), else
    its seeds."""
    lib = (env or {}).get("qualifiers")
    if lib:
        return lib
    from senaite.pfas.qc_qualification import library_from
    return library_from({})


def _rule_flags():
    from senaite.pfas import rule_flags
    return rule_flags


FLAG_COLUMNS = [
    cf.Field("code", u"Code", kind=cf.CHOICE, choices=flag_code_choices, placeholder=u"No code",
             kept_if_absent=True),
    cf.Field("attach", u"Attaches to", kind=cf.CHOICE, kept_if_absent=True, choices=[(k, w) for k, w in
                                                              (("result", u"Result"), ("analyte", u"Analyte row"),
                                                               ("injection", u"Injection"),
                                                               ("batch", u"Batch or report"))]),
    # where the code is issued: blank = the certificate and the EDD
    cf.Field("output", u"Output", kind=cf.CHOICE, placeholder=u"Certificate and EDD", kept_if_absent=True,
             choices=[(u"coa", u"Certificate only"), (u"edd", u"EDD only")]),
    cf.Field("note", u"Internal note", kind=cf.TEXT, placeholder=u"No note", kept_if_absent=True),
]


def tier_flag_key(qc_type, name):
    """The flags table's row key of a recovery tier."""
    return (u"tier", qc_type, name)


def flag_rows_of(profile, env=None, standard=False):
    """[(row key, label)]: the rule cards' flags a tab posts. Isotope
    standards: its rules. QC criteria: every rule row its Rules list draws,
    then each tier of the QC types whose tiers it draws as cards."""
    from senaite.pfas import profile_grids as pg
    if standard:
        labels = dict((r["key"], r["label"]) for r in _qc_rules().RULE_LIBRARY)
        return [((k,), labels.get(k, k)) for k in pg.STANDARD_RULES]
    out = [((r.key,), r.label) for r in pg.rules_table(profile, env).rows]
    rf = _rule_flags()
    for qc, label in pg.QC_TYPES:
        for i, t in enumerate(rf.tiers_of(profile, qc)):
            if t.get(LOW_LEVEL_KEY):
                continue
            name = rf.tier_name(t, i)
            from senaite.pfas.limit_placard import tier_words
            out.append((tier_flag_key(qc, name), u"%s \u00b7 %s" % (label, tier_words(name))))
    return out


def _qc_rules():
    from senaite.pfas.qc import rules
    return rules


def _flag_table(table_id, standard):
    def rows(profile, env=None):
        return (_one_group(*FLAG_GROUP),
                [{"key": key, "group": FLAG_GROUP[0], "label": label, "defaults": {"attach": u"result"}}
                 for key, label in flag_rows_of(profile, env, standard)])

    def read(profile):
        rf = _rule_flags()
        view = rf._view(profile)
        out = dict(((k,), v) for k, v in rf.flags(view).items())
        for qc, _label in _tier_types():
            for i, t in enumerate(rf.tiers_of(view, qc)):
                out[tier_flag_key(qc, rf.tier_name(t, i))] = rf.tier_flag(t)
        # a choice drawn as the default writes nothing: the default place reads blank
        return dict((k, dict(v, attach=None if v["attach"] == rf.DEFAULT_ATTACH else v["attach"]))
                    for k, v in out.items())

    def write(profile, updates, env=None):
        rf = _rule_flags()
        rf.migrate(profile)
        for key, vals in updates.items():
            if not vals:
                continue                        # nothing of the row posted: as stored
            if len(key) == 3 and key[0] == u"tier":
                tier = rf.find_tier(profile, key[1], key[2])
                if tier is not None:
                    rf.set_tier_flag(tier, _posted_flag(rf.tier_flag(tier), vals))
            elif len(key) == 1:
                rf.set_flag(profile, key[0], _posted_flag(rf.flag_of(profile, key[0]), vals))
        return profile
    return cf.Table(id=table_id, title=u"Flags", base=(), columns=FLAG_COLUMNS, rows=rows,
                    rows_take_env=True, read=read, write=write, row_heading=u"Rule")


def _posted_flag(stored, vals):
    """A flag as posted: each field the form carried, the others as stored."""
    flag = dict(stored)
    for path, value in vals.items():
        flag[path[0]] = value
    return flag


def _tier_types():
    from senaite.pfas import profile_grids as pg
    return pg.QC_TYPES


# QC criteria: every rule but the Isotope standards tab's, and each tier
FLAGS_QC = _flag_table(u"flags_qc", False)
# Isotope standards: Surrogate Recovery, IS Response, IS vs CCV
FLAGS_STD = _flag_table(u"flags_std", True)

# ── Dilutions ─────────────────────────────────────────────────
# How an over-range sample may be diluted for this method: the routes it
# allows and their limits. Nothing is preset -- every value is the lab's,
# from its SOP; a project may override any of them (Project Specs). With no
# routes stored the extract is diluted.
DILUTION_ROUTES = [(u"extract", u"Dilute the extract"),
                   (u"reprep", u"Smaller aliquot, re-prepared"),
                   (u"respike", u"EIS re-spiked into the diluted extract")]

DILUTION = cf.Section(
    id=u"dil", title=u"Dilutions", base=("dilution",),
    groups=[(u"Routes this method allows", [
        cf.Field("routes", u"Routes", kind=cf.MULTI, choices=DILUTION_ROUTES, default=[u"extract"]),
    ]), (u"Limits", [
        cf.Field("max_fold", u"Largest dilution", unit=u"fold", greater_than=1,
                 help=u"Blank: no cap."),
        cf.Field("eis_floor_pct", u"Lowest EIS recovery in a diluted extract", unit=u"%", minimum=0,
                 maximum=100, help=u"Blank: the method's EIS window."),
        cf.Field("min_aliquot", u"Smallest aliquot for a re-prep", unit=u"mL or g", greater_than=0,
                 help=u"Blank: no minimum."),
        cf.Field("client_approval", u"A smaller aliquot needs the client's approval", kind=cf.BOOL),
        # the code and wording are the QAO's, in QC Qualifiers
        cf.Field("qualify_respike", u"Qualify a re-spiked result", kind=cf.BOOL,
                 help=u"With the code and wording set in QC Qualifiers."),
        # the lab's choice: always, or only when the
        # standard that quantifies the analyte was added to the dilution
        cf.Field("fold_rule", u"Apply the fold to a diluted reading", kind=cf.CHOICE, blank=u"remove",
                 choices=[(u"", u"Always"), (u"added", u"Only when the quantifying standard was added")]),
    ])])


def dilution_settings(profile):
    """The method's (or a project's effective) dilution settings, unset
    values as None / False / u""."""
    d = (profile or {}).get("dilution") or {}
    num = lambda v: None if v in (None, u"") else v                       # noqa: E731
    return {"routes": list(d.get("routes") or [u"extract"]),
            "max_fold": num(d.get("max_fold")), "eis_floor_pct": num(d.get("eis_floor_pct")),
            "min_aliquot": num(d.get("min_aliquot")), "client_approval": bool(d.get("client_approval")),
            "qualify_respike": bool(d.get("qualify_respike")), "fold_rule": d.get("fold_rule") or u""}


# ENGINE_FALLBACK (the surrogate window the method text states) is declared
# but is no section of the editor: no tab draws or saves it. The Isotope
# standards grid shows that window as what a blank Recovery limits cell
# inherits, and a window typed there is the profile's own, which wins.
def check_cells_reported(profile):
    """An analyte left out of a matrix, or out of the panel, while a setting
    on its cell there names it: refused, naming the setting to clear first
    on QC criteria (Set on one cell)."""
    panel = set(profile.get("master_analyte_set") or [])
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    out = []
    for r in read_cells(profile):
        kw, m = r["analyte"], r["matrix"]
        if kw not in panel or not (inclusion.get(kw) or {}).get(m, True):
            out.append(u"%s is left out of %s, but QC criteria sets %s on its cell there: clear that "
                       u"setting first (Set on one cell)." % (kw, m, r["qc_type"]))
    return out


PROFILE_CHECKS = [((u"sur", u"ls", u"cmp"), check_profile), ((u"iso",), check_isomers),
                  ((u"ami", u"rl"), check_cells_reported),
                  ((u"intg", u"intg_an"), check_integration)]
# Refusals of a tab's Save alone, never of an action: adding a standard
# makes a surrogate linked to nothing, which the tab's next Save requires
# linked; removing one never leaves a link missing that was not missing.
LINK_CHECKS = [((u"ls",), check_surrogate_links), ((u"sur", u"ami"), check_analyte_links)]

SECTIONS = dict((s.id, s) for s in [CALIBRATION_CCV, CAL_LEVELS, ANALYTE_SCALE, QC_COMPOSITION, REPORTING_LIMITS, MATRICES,
                                    SALT, SAMPLE_CORRECTION, NOMINAL_AMOUNTS, SAMPLE_RECEIPT, QC_NAME_CODES, MATRIX_FACTORS, EIS_GRID, SURROGATE_MAP,
                                    SURROGATE_SCOPE, ENGINE, ENGINE_STUDIES,
                                    ENGINE_TEXT,
                                    LABELLED_STANDARDS, COMPOSITES, LINKED_RATIO, DILUTION_RECOVERY, ISOMERS, RECOVERY_TIERS, DUP_RPD,
                                    REPORT_FORMAT, ACTION_LEVELS, GROUPS, LFSMD_RPD, LFB_TIERS, QC_CELLS,
                                    EXTRACTION_LABELS, EXTRACTION_BATCH, BLANK_LIMITS, MATRIX_BLANKS,
                                    STORAGE_HOLDING, MATRIX_TEMPERATURES, DILUTION, MATRIX_CODES, SOLVENT_LC, SOLVENT_SPE, RUN_RULES, CAL_SURROGATES, CAL_IS,
                                    ENGINE_SURROGATES, ENGINE_AMI, ENGINE_RECOVERY, AMI, ENGINE_NAMES,
                                    FLAGS_QC, FLAGS_STD, SALT_STD,
                                    INTEGRATION, INTEGRATION_ANALYTES] +
                list(SPIKE_LEVELS.values()))


# ── A project's extraction QC checks ──────────────────────────
# Same / On / Off per extraction QC type with the reason (the QAPP clause).
# Calibration, CCV and internal-standard checks always come from the method,
# so they are never rows here. The effective profile carries the switch on
# the type (qc_acceptance[code]["project_switch"]); a type switched on that
# the method has no limits for is judged "not set", never passed.
PROJECT_QC_CODES = (u"LFSM", u"LFSMD", u"MB", u"LRB", u"MxB", u"LFB", u"LCS", u"Dup")
_SWITCH = u"project_switch"


def _projqc_rows(profile, env=None):
    qca = (profile or {}).get("qc_acceptance") or {}
    rows = []
    for code in PROJECT_QC_CODES:
        q = qca.get(code) or {}
        sw = q.get(_SWITCH) or {}
        # what the method sets: before this project's switch
        on = (sw.get("to") == u"off") if sw else bool(q.get("enabled"))
        rows.append({"key": (code,), "group": u"projqc", "label": QC_NAMES.get(code, code),
                     "sublabel": u"Method: %s" % (u"On" if on else u"Off")})
    return [{"key": u"projqc", "label": u"Extraction QC checks", "unit": u""}], rows


def _projqc_read(profile):
    qca = (profile or {}).get("qc_acceptance") or {}
    out = {}
    for code in PROJECT_QC_CODES:
        sw = (qca.get(code) or {}).get(_SWITCH) or {}
        out[(code,)] = {"state": sw.get("to") or u"", "reason": sw.get("reason") or u""}
    return out


def _projqc_write(profile, updates, env=None):
    qca = profile.setdefault("qc_acceptance", {})
    for (code,), vals in sorted(updates.items()):
        state = vals.get((u"state",)) or u""
        if state not in (u"on", u"off"):
            continue                    # Same: the method's
        q = qca.setdefault(code, {"enabled": False, "tiers": []})
        # the row's state with its flag: a project's switch is what its
        # batches run, whatever state the method holds: On is Enforced (a
        # failure holds release), Off is Off
        _rules.set_qc_row_state(profile, code, u"enforced" if state == u"on" else u"off")
        q.setdefault("tiers", [])
        q[_SWITCH] = {"to": state, "reason": (vals.get((u"reason",)) or u"").strip()}
    return profile


def _projqc_check(row, values):
    if values.get(u"f__state") in (u"on", u"off") and not (values.get(u"f__reason") or u"").strip():
        return u"%s: a project switch needs its reason, such as the QAPP clause." % row.get("label")
    return None


PROJECT_QC = cf.Table(
    id=u"projqc", title=u"Extraction QC checks", base=(),
    columns=[cf.Field("state", u"This project", kind=cf.CHOICE, widget=u"seg", blank=u"remove",
                      choices=[(u"", u"Same"), (u"on", u"On"), (u"off", u"Off")]),
             cf.Field("reason", u"Reason", kind=cf.TEXT, placeholder=u"QAPP clause")],
    rows=_projqc_rows, read=_projqc_read, write=_projqc_write, check=_projqc_check,
    row_heading=u"Extraction QC check")


# What a Project may override: its extraction QC -- what each batch
# contains, recovery and RPD, the extraction QC checks -- and its dilutions.
# Calibration, CCV, internal standards, reporting limits, standards and the
# analyte panel always come from the method.
PROJECT_SECTIONS = [QC_COMPOSITION, RECOVERY_TIERS, LFB_TIERS, DUP_RPD, LFSMD_RPD, PROJECT_QC, DILUTION]
