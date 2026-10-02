# -*- coding: utf-8 -*-
"""A method's calibration levels, and what follows from them
(DECISIONS 2026-10-02, "Calibration levels own the RL" and "Calibration
ladders in ng/mL; the matrix factor converts").

    instrument_verification.calibration = {
        "level_unit": "ng/mL" | "ppt",
        "levels": [{"name": "CAL-1", "conc": 0.0390625}, ...],      # lowest first
        "analyte_scale": {"PFBA": {"factor": 4.0, "max": 250.0}, ...},
        "levels_source": "EPA 1633A (Dec 2024) Table 4 ...",
    }

`levels` is the method's base ladder. An analyte with an `analyte_scale`
entry runs base x factor, keeping only the points at or below its `max`
(EPA 1633A: PFBA 0.8-204.8 where most analytes are 0.2-51.2). From them:

  * the RL of an analyte in a matrix = its LOWEST level in the matrix's
    reporting unit -- for an ng/mL (extract) ladder that is x the method's
    matrix factor, the same number the pipeline multiplies results by; no
    factor, no RL. A typed RL overrides (report_limits.limits_for);
  * recommended spike levels: Low = lowest, High = highest, Mid = the level
    nearest the midpoint (2, 80, 160 for a 2-160 curve). Suggestions only.

The worker loads THIS file (pfas_pipeline.method_profiles._cal), so the add-on
and the pipeline cannot disagree. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

# ppt (ng/L, ng/kg) in one unit of a reporting unit
PPT_PER_UNIT = {"ng/l": 1.0, "ng/kg": 1.0, "pg/g": 1.0, "pg/ml": 1.0,
                "ng/ml": 1000.0, "ng/g": 1000.0, "ug/l": 1000.0, "ug/kg": 1000.0,
                "µg/l": 1000.0, "µg/kg": 1000.0, "mg/kg": 1e6}
PATH = ("instrument_verification", "calibration")
PPT, EXTRACT = "ppt", "ng/mL"
UNITS = (EXTRACT, PPT)

# What the levels were seeded from (lab instruction 2026-10-02: "every
# calibration point doubled from the last"). EPA 1633A ranges are Table 4 of
# the December 2024 method (CS1 to the highest listed standard); each
# analyte's factor is its CS1 / 0.2, its max the highest standard listed.
SEEDS = {
    "FDA_32PFAS": {"low": 20.0 / 512, "high": 20.0, "scale": {},
                   "source": "Lab instruction 2026-10-02: 0.039 to 20 ng/mL, each "
                             "point double the last (10 points)."},
    "EPA_1633A": {"low": 0.2, "high": 62.5,
                  "scale": {"PFBA": (4.0, 250.0), "GenX": (4.0, 250.0), "DONA": (4.0, 250.0),
                            "9ClPF3ONS": (4.0, 250.0), "11ClPF3OUdS": (4.0, 250.0),
                            "PFPeA": (2.0, 125.0), "PFMPA": (2.0, 125.0), "PFMBA": (2.0, 125.0),
                            "NFDHA": (2.0, 125.0), "PFEESA": (2.0, 125.0),
                            "4:2FTS": (4.0, 50.0), "6:2FTS": (4.0, 50.0), "8:2FTS": (4.0, 50.0),
                            "NMeFOSE": (10.0, 625.0), "NEtFOSE": (10.0, 625.0),
                            "3:3FTCA": (5.0, 312.0), "5:3FTCA": (25.0, 1560.0),
                            "7:3FTCA": (25.0, 1560.0)},
                  "source": "EPA Method 1633A (December 2024) Table 4: each analyte from "
                            "its CS1 to its highest listed standard, each point double the "
                            "last (lab instruction 2026-10-02)."},
}


def _calib(profile):
    node = profile or {}
    for k in PATH:
        node = node.get(k) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def unit(profile):
    return _calib(profile).get("level_unit") or PPT


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def rows(profile):
    """[{"name", "conc"}] as stored (a pre-unit row kept its value in "ppt")."""
    out = []
    for r in _calib(profile).get("levels") or []:
        if isinstance(r, dict):
            out.append({"name": r.get("name"), "conc": r.get("conc", r.get("ppt"))})
    return out


def levels(profile, keyword=None):
    """The ladder in the level unit, lowest first -- the analyte's own when it
    has a scale entry."""
    base = sorted(v for v in (_num(r["conc"]) for r in rows(profile)) if v is not None)
    scale = (_calib(profile).get("analyte_scale") or {}).get(keyword) if keyword else None
    if not isinstance(scale, dict):
        return base
    factor = _num(scale.get("factor")) or 1.0
    top = _num(scale.get("max"))
    return [v * factor for v in base if top is None or v * factor <= top * (1 + 1e-9)]


def calibrators(profile):
    """[(level number, concentration in the level unit)], lowest first -- the
    calibrators a run injects and the logbook prepares (Run Builder,
    FM-ENV-251). One list for every consumer (QC consolidation P1)."""
    return [(i + 1, v) for i, v in enumerate(levels(profile))]


def lowest(profile, keyword=None):
    lv = levels(profile, keyword)
    return lv[0] if lv else None


def matrix_factor(profile, matrix):
    """The method's extract -> sample multiplier for `matrix` (exact title,
    then the legacy substring match -- MethodProfile.sample_factor), or None."""
    m = (matrix or u"").lower().strip()
    entries = [e for e in (profile or {}).get("matrix_factors") or [] if isinstance(e, dict)]
    for exact in (True, False):
        for e in entries:
            key = (e.get("matrix") or u"").lower().strip()
            if key and (key == m if exact else key in m):
                return _num(e.get("factor"))
    return None


def in_unit(ppt, reporting_unit):
    """`ppt` expressed in a reporting unit, or None if the unit is unknown."""
    factor = PPT_PER_UNIT.get((reporting_unit or u"").strip().lower())
    return None if ppt is None or not factor else ppt / factor


def to_reporting(conc, profile, matrix):
    """A level concentration in the matrix's reporting unit, or None."""
    if conc is None:
        return None
    if unit(profile) == EXTRACT:
        f = matrix_factor(profile, matrix)
        return conc * f if f else None
    return in_unit(conc, ((profile or {}).get("unit_map") or {}).get(matrix))


def to_ppt(conc, profile, matrix):
    """A level concentration as sample ppt (the spike-level unit), or None."""
    v = to_reporting(conc, profile, matrix)
    per = PPT_PER_UNIT.get((((profile or {}).get("unit_map") or {}).get(matrix) or u"").strip().lower())
    return v * per if v is not None and per else None


def derived_rl(profile, matrix, keyword=None):
    """The analyte's lowest level in the matrix's reporting unit, or None."""
    return to_reporting(lowest(profile, keyword), profile, matrix)


def fmt(v):
    """4 significant figures, never in exponent form (10000, not 1e+04)."""
    if v is None:
        return u""
    s = u"%.4g" % v
    if u"e" in s:
        s = (u"%.10f" % float(s)).rstrip(u"0").rstrip(u".")
    return s


def _pick(lv):
    if len(lv) < 2:
        return {}
    lo, hi = lv[0], lv[-1]
    target = (lo + hi) / 2.0
    mid = sorted(lv, key=lambda v: (abs(v - target), -v))[0]
    return {"Low": lo, "Mid": mid, "High": hi}


def recommended_spikes(profile):
    """{"Low", "Mid", "High"} of the base ladder in the level unit, or {}."""
    return _pick(levels(profile))


def recommended_spikes_ppt(profile, matrix):
    """The same three as sample ppt for `matrix`, or {} when not convertible."""
    rec = recommended_spikes(profile)
    out = dict((k, to_ppt(v, profile, matrix)) for k, v in rec.items())
    return out if out and all(v is not None for v in out.values()) else {}


def doubling(low, high):
    """low, 2 x low, 4 x low ... while at or below high."""
    out, v = [], float(low)
    while v <= high * (1 + 1e-9):
        out.append(v)
        v *= 2
    return out


def migrate(profile, method_id):
    """Bring a profile's calibration block to the unit-aware form, once (the
    marker is `level_unit`). Existing levels are kept as ppt; an EMPTY ladder
    for a method in SEEDS is seeded in ng/mL. True if changed."""
    calib = profile.setdefault("instrument_verification", {}).setdefault("calibration", {})
    if calib.get("level_unit"):
        return False
    kept = [r for r in rows(profile) if _num(r["conc"]) is not None]
    seed = SEEDS.get(method_id)
    if kept or not seed:
        calib["level_unit"] = PPT
        if "levels" in calib:
            calib["levels"] = kept
        return True
    calib["level_unit"] = EXTRACT
    calib["levels"] = [{"name": u"CAL-%d" % (i + 1), "conc": v}
                       for i, v in enumerate(doubling(seed["low"], seed["high"]))]
    if seed["scale"]:
        calib["analyte_scale"] = dict((kw, {"factor": f, "max": m})
                                      for kw, (f, m) in seed["scale"].items())
    calib["levels_source"] = seed["source"]
    return True
