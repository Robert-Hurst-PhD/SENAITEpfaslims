# -*- coding: utf-8 -*-
"""Method Profile editor sections declared for config_forms (R2).

Each section is saved on its own from its own tab. Only fields that have an
input on that tab are declared: a declared field with no input would be
cleared by every save of the tab. So instrument_verification.sequence (no
input anywhere; the Run Builder reads ccv.frequency) is deliberately absent.

Required fields (DECISIONS.md, 2026-09-30): calibration r², CCV frequency and
the CCV recovery window. Before R2 a blank in these kept the old value silently; now a blank is
refused with the field named. Every other number is optional and blank means
"no limit" (None), as before.
Python 2.7 compatible.
"""
from __future__ import absolute_import

try:
    from senaite.pfas import config_forms as cf
except Exception:          # tests: loaded without the package
    import config_forms as cf

PCT = u"%"

CALIBRATION_CCV = cf.Section(
    id=u"cal", title=u"Calibration & CCV", base=("instrument_verification",),
    groups=[
        (u"Calibration", [
            cf.Field("calibration.r2_min", u"R² Minimum", required=True,
                     minimum=0.9, maximum=1.0, placeholder=u"0.990",
                     help=u"e.g. 0.990 (FDA) or 0.995 (generic)"),
            cf.Field("calibration.point_pct_dev_max", u"Point % Deviation Max",
                     unit=PCT, minimum=0,
                     help=u"Each cal point must be within ±N% of curve. Leave blank for no limit."),
            cf.Field("calibration.low_point_pct_dev_max", u"Low-Level Point % Dev Max",
                     unit=PCT, minimum=0,
                     help=u"Wider limit for lowest calibration level (e.g. 50 for EPA 537.1)."),
            cf.Field("calibration.force_origin", u"Force through origin", kind=cf.BOOL,
                     help=u"Required by EPA 537.1 IS calibration technique"),
        ]),
        (u"Chromatographic Confirmation & Signal Quality", [
            cf.Field("confirmation.ion_ratio_tol_pct", u"Ion Ratio Tolerance ±",
                     unit=PCT, minimum=0,
                     help=u"30 for FDA; 50 for EPA 1633A; blank for 537.1 (no criterion)"),
            cf.Field("confirmation.rrt_tol_pct", u"Relative RT Tolerance",
                     unit=PCT, minimum=0,
                     help=u"1.0 for FDA (RRT ±1% of standard RT)."),
            cf.Field("confirmation.rt_tol_abs_min", u"Absolute RT Tolerance",
                     unit=u"min", minimum=0, help=u"0.05 for EPA 537.1."),
            cf.Field("confirmation.sn_quan_min", u"S/N Min — Quantitation Ion", minimum=0),
            cf.Field("confirmation.sn_confirm_min", u"S/N Min — Confirm Ion (optional)",
                     minimum=0, help=u"1.0 for EPA 1633A."),
            cf.Field("confirmation.require_confirm_ion_check",
                     u"Require qualifier ion check for all analytes", kind=cf.BOOL,
                     help=u"ON for FDA 32-PFAS and EPA 1633A; OFF for EPA 537.1."),
            cf.Field("confirmation.confirm_technique",
                     u"Confirmation technique for single-transition analytes",
                     kind=cf.TEXT, blank=u"remove", placeholder=u"LC-HRMS",
                     help=u"FDA §10.2(4) requires a positive for a single-transition analyte "
                          u"(PFBA, PFPeA) to be confirmed by an orthogonal technique, and cites "
                          u"LC-HRMS as an example — it is not the only route. Name the one this "
                          u"lab uses; the review prompt quotes it. Switch the prompt off "
                          u"entirely under QC Rules → Single-Transition Confirmation."),
        ]),
        (u"Continuing Calibration Verification (CCV)", [
            cf.Field("ccv.frequency", u"CCV Frequency (every N samples)", kind=cf.INT,
                     required=True, minimum=1,
                     help=u"6 for FDA 32-PFAS; 10 for EPA 537.1 / 1633A"),
            cf.Field("ccv.recovery_min", u"Recovery Min", unit=PCT, required=True, minimum=0),
            cf.Field("ccv.recovery_max", u"Recovery Max", unit=PCT, required=True, minimum=0),
            cf.Field("ccv.low_level_min", u"Low-Level Min (optional)", unit=PCT, minimum=0,
                     help=u"Wider window for the lowest CCC/CCV level."),
            cf.Field("ccv.low_level_max", u"Low-Level Max (optional)", unit=PCT, minimum=0),
        ]),
        (u"IS / Surrogate Response", [
            cf.Field("is_response.vs_ical_avg_min", u"vs. ICAL Average Min", unit=PCT, minimum=0),
            cf.Field("is_response.vs_ical_avg_max", u"vs. ICAL Average Max", unit=PCT, minimum=0),
            cf.Field("is_response.vs_last_ccv_min", u"vs. Last CCV Min (optional)",
                     unit=PCT, minimum=0,
                     help=u"EPA 537.1 §9.3.4 requires this second condition."),
            cf.Field("is_response.vs_last_ccv_max", u"vs. Last CCV Max (optional)",
                     unit=PCT, minimum=0),
            cf.Field("is_response.notes", u"Notes", kind=cf.TEXT),
        ]),
    ])

def _analyte_titles():
    try:
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
    except Exception:          # tests: loaded without the package
        from analyte_reference import NATIVE_ANALYTES
    return dict((row[0], row[1]) for row in NATIVE_ANALYTES)


def reporting_limit_rows(profile):
    """One group per supported matrix, one row per analyte that matrix REPORTS
    (the analyte x matrix inclusion grid decides -- PFODA is not listed under
    FDA x Eggs, CLAUDE.md §3 rule 2). The group's unit is the matrix's unit_map
    entry: a limit is entered in, and printed with, the unit the method
    reports that matrix in."""
    titles = _analyte_titles()
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    units = profile.get("unit_map") or {}
    groups, rows = [], []
    for matrix in profile.get("supported_matrices") or []:
        groups.append({"key": matrix, "label": matrix, "unit": units.get(matrix, u"")})
        for kw in profile.get("master_analyte_set") or []:
            if (inclusion.get(kw) or {}).get(matrix, True) is False:
                continue
            rows.append({"key": (matrix, kw), "group": matrix,
                         "label": titles.get(kw, kw), "sublabel": kw})
    return groups, rows


def _mdl_not_above_rl(row, values):
    rl, mdl = values.get(u"f__rl"), values.get(u"f__mdl")
    if rl is not None and mdl is not None and mdl > rl:
        return u"%s in %s: the MDL (%s) is above the RL (%s)." % (
            row["sublabel"], row["group"], mdl, rl)
    return None


REPORTING_LIMITS = cf.Table(
    id=u"rl", title=u"Reporting Limits", base=("reporting_limits",),
    columns=[cf.Field("rl", u"RL", minimum=0), cf.Field("mdl", u"MDL", minimum=0)],
    rows=reporting_limit_rows, check=_mdl_not_above_rl)

SECTIONS = dict((s.id, s) for s in [CALIBRATION_CCV, REPORTING_LIMITS])
