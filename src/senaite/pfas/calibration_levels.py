# -*- coding: utf-8 -*-
"""A method's calibration levels, and what follows from them
(DECISIONS 2026-10-02).

    instrument_verification.calibration.levels = [{"name": "CAL-1", "ppt": 2.0}, ...]

Levels are sample-equivalent concentrations in ppt (ng/L for aqueous, ng/kg
for solids), stored lowest first. From them:

  * the RL of every analyte in every matrix = the LOWEST calibrator,
    expressed in the matrix's reporting unit (a typed RL overrides it --
    report_limits.limits_for);
  * recommended spike levels: Low = lowest, High = highest, Mid = the
    calibrator nearest the midpoint (2, 80, 160 for a 2-160 curve).
    Suggestions only.

The worker reads the same rule (pfas_pipeline.method_profiles
.MethodProfile.reporting_limits); tests/test_calibration_levels.py pins
that the two agree. Pure; Python 2.7.
"""
from __future__ import absolute_import, division, unicode_literals

# ppt (ng/L, ng/kg) in one unit of a reporting unit
PPT_PER_UNIT = {"ng/l": 1.0, "ng/kg": 1.0, "pg/g": 1.0, "pg/ml": 1.0,
                "ng/ml": 1000.0, "ng/g": 1000.0, "ug/l": 1000.0, "ug/kg": 1000.0,
                "µg/l": 1000.0, "µg/kg": 1000.0, "mg/kg": 1e6}
PATH = ("instrument_verification", "calibration", "levels")


def rows(profile):
    node = profile or {}
    for k in PATH:
        node = (node or {}).get(k) if isinstance(node, dict) else None
    return [r for r in (node or []) if isinstance(r, dict)]


def levels(profile):
    """The calibrator concentrations in ppt, lowest first."""
    out = []
    for r in rows(profile):
        try:
            v = float(r.get("ppt"))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out.append(v)
    return sorted(out)


def lowest(profile):
    lv = levels(profile)
    return lv[0] if lv else None


def in_unit(ppt, unit):
    """`ppt` expressed in a reporting unit, or None if the unit is unknown."""
    factor = PPT_PER_UNIT.get((unit or u"").strip().lower())
    return None if ppt is None or not factor else ppt / factor


def derived_rl(profile, matrix):
    """The lowest calibrator in the matrix's reporting unit, or None."""
    unit = ((profile or {}).get("unit_map") or {}).get(matrix)
    return in_unit(lowest(profile), unit)


def recommended_spikes(profile):
    """{"Low", "Mid", "High"} in ppt, or {} without at least two levels."""
    lv = levels(profile)
    if len(lv) < 2:
        return {}
    lo, hi = lv[0], lv[-1]
    mid_target = (lo + hi) / 2.0
    mid = sorted(lv, key=lambda v: (abs(v - mid_target), -v))[0]
    return {"Low": lo, "Mid": mid, "High": hi}


def seed_from_ladder(profile, ladder, unit_is_ppt):
    """Give a profile its levels once from the legacy ladder -- only when that
    ladder is already sample-equivalent ppt (EPA 537.1). An extract ladder
    (ng/mL) is not converted: that needs the extract volume and sample
    amount, which the lab states (never invented). True if seeded."""
    calib = profile.setdefault("instrument_verification", {}).setdefault("calibration", {})
    if "levels" in calib:
        return False
    vals = sorted(float(v) for v in (ladder or [])) if unit_is_ppt else []
    calib["levels"] = [{"name": u"CAL-%d" % (i + 1), "ppt": v} for i, v in enumerate(vals)]
    return True
