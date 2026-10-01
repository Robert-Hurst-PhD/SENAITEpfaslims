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

def _global_titles():
    try:
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
    except Exception:          # tests: loaded without the package
        from analyte_reference import NATIVE_ANALYTES
    return dict((row[0], row[1]) for row in NATIVE_ANALYTES)


try:
    from senaite.pfas import isomers as _iso
except Exception:              # tests: loaded without the package
    import isomers as _iso


class _Labels(dict):
    """{keyword: label} for ONE method: a summed analyte shows its reported
    name (the Isomers tab), every other analyte its display name. Every tab
    labels analytes through this, so an isomer change reaches all of them --
    the global table alone named a summed PFOS "lr-PFOS" (DECISIONS 2026-10-01)."""

    def __init__(self, profile):
        dict.__init__(self)
        self.profile, self.titles = profile, _global_titles()

    def get(self, kw, default=None):
        return _iso.label(self.profile, kw, self.titles)


def _analyte_titles(profile):
    return _Labels(profile)


def reporting_limit_rows(profile):
    """One group per supported matrix, one row per analyte that matrix REPORTS
    (the analyte x matrix inclusion grid decides -- PFODA is not listed under
    FDA x Eggs, CLAUDE.md §3 rule 2). The group's unit is the matrix's unit_map
    entry: a limit is entered in, and printed with, the unit the method
    reports that matrix in."""
    titles = _analyte_titles(profile)
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

# ── Matrices & Units: one row per matrix, five stored keys ───────────────────

COMMON_UNITS = [u"ng/kg", u"ug/kg", u"ng/L", u"ng/mL", u"ug/L", u"mg/kg", u"pg/g"]


def unit_choices(profile, env=None):
    """Every common unit plus every unit already in use, so an existing choice
    is never silently dropped from the list it was chosen from."""
    used = sorted(set(u for u in (profile.get("unit_map") or {}).values()
                      if u and u not in COMMON_UNITS))
    return [(u, u) for u in COMMON_UNITS + used]


def read_matrices(profile):
    tight = set(profile.get("tight_matrices") or [])
    aliases = profile.get("matrix_aliases") or {}
    units = profile.get("unit_map") or {}
    holding = profile.get("holding_times") or {}
    return [{"name": m, "tight": m in tight,
             "aliases": u", ".join(aliases.get(m) or []),
             "unit": units.get(m) or None,
             "holding_days": holding.get(m)}
            for m in profile.get("supported_matrices") or []]


def _set(profile, key, value):
    """Write a key, but leave a MISSING key missing when the new value is
    empty: an unchanged save must not turn "absent" into "[]" (EPA 537.1 has
    no tight_matrices or matrix_aliases key at all)."""
    if value or key in profile:
        profile[key] = value


def write_matrices(profile, rows):
    names = [r["name"] for r in rows]
    aliases, units, holding = {}, {}, {}
    for r in rows:
        parts = [a.strip() for a in (r.get("aliases") or u"").split(u",") if a.strip()]
        if parts:
            aliases[r["name"]] = parts
        if r.get("unit"):
            units[r["name"]] = r["unit"]
        days = r.get("holding_days")
        if days is not None and days == int(days):
            days = int(days)
        # Kept as an explicit None: the matrix is listed as deliberately unset,
        # and the review refuses to judge rather than passing it.
        holding[r["name"]] = days
    profile["supported_matrices"] = names
    _set(profile, "tight_matrices", [r["name"] for r in rows if r.get("tight")])
    _set(profile, "matrix_aliases", aliases)
    _set(profile, "unit_map", units)
    _set(profile, "holding_times", holding)
    if "matrix_uid_map" in profile:
        profile["matrix_uid_map"] = dict((k, v) for k, v in
                                         (profile.get("matrix_uid_map") or {}).items()
                                         if k in names)
    return profile


def matrix_references(profile, removed):
    """What still points at a matrix title that is going away. Reported as a
    refusal rather than cleaned up: a matrix factor, spike level or reporting
    limit is lab data, and deciding it is disposable because a title changed
    is not this form's call (CLAUDE.md §3 rule 4)."""
    removed = set(removed)
    found = []
    factors = [e.get("matrix") for e in (profile.get("matrix_factors") or [])
               if isinstance(e, dict)]
    hit = sorted(set(f for f in factors if f in removed))
    if hit:
        found.append(u"matrix factors for %s" % u", ".join(hit))
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


MATRICES = cf.Collection(
    id=u"mtx", title=u"Matrices & Units", noun=u"matrix", new_rows=3,
    columns=[
        cf.Field("name", u"Matrix", kind=cf.TEXT, placeholder=u"new matrix"),
        cf.Field("tight", u"Tier 1", kind=cf.BOOL),
        cf.Field("aliases", u"Aliases (comma-separated)", kind=cf.TEXT,
                 placeholder=u"deer muscle, venison, beef"),
        cf.Field("unit", u"Reporting Unit", kind=cf.CHOICE, choices=unit_choices),
        cf.Field("holding_days", u"Holding Time (days)", greater_than=0,
                 placeholder=u"not set"),
    ],
    read=read_matrices, write=write_matrices, check=check_matrices)

# ── Sample Corrections: salt factors and matrix factors ──────────────────────
# Both are stored as LISTS holding only rows that change something; the
# default factor 1.0 is a placeholder, never written as a value (GAPS §51).


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


def lot_choices(profile, env=None):
    """Standard / reference-material lots from the reagent inventory (the page
    supplies them in env; their labels already say EXPIRED where it applies,
    and an expired lot stays pickable)."""
    return [(o["uid"], o["label"]) for o in ((env or {}).get("standard_lots") or [])]


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
    lot_numbers = dict((o["uid"], o.get("lot_number", u""))
                       for o in ((env or {}).get("standard_lots") or []))

    def build(kw, vals, old):
        factor, lot = vals.get(("factor",)), vals.get(("lot_uid",)) or u""
        if (factor is None or factor == 1.0) and not lot:
            return None                     # no correction and no lot: no row
        same_lot = lot == (old.get("lot_uid") or old.get("source"))
        return {"analyte": kw, "factor": 1.0 if factor is None else factor,
                "lot_uid": lot,
                # a stored lot number survives a lot that has since left the
                # inventory; a new pick takes the inventory's number
                "lot_number": old.get("lot_number", u"") if same_lot else lot_numbers.get(lot, u"")}

    existing = [r for r in (profile.get("salt_adjustment_factors") or []) if isinstance(r, dict)]
    ordered = [(kw,) for kw in profile.get("master_analyte_set") or [] if (kw,) in updates]
    out = _merge_rows(existing, "analyte", updates, ordered, build)
    if out or "salt_adjustment_factors" in profile:
        profile["salt_adjustment_factors"] = out
    return profile


SALT = cf.Table(
    id=u"salt", title=u"Salt Adjustment Factors", base=("salt_adjustment_factors",),
    columns=[cf.Field("factor", u"Factor", greater_than=0, maximum=1, placeholder=u"1.0"),
             cf.Field("lot_uid", u"CoA Lot", kind=cf.CHOICE, choices=lot_choices)],
    rows=salt_rows, read=read_salt, write=write_salt)


def matrix_factor_rows(profile):
    uid_map = profile.get("matrix_uid_map") or {}
    rows = []
    for m in profile.get("supported_matrices") or []:
        linked = bool(uid_map.get(m))
        rows.append({"key": (m,), "group": u"mf", "label": m,
                     "note": u"core type" if linked else u"unlinked",
                     "warn": not linked})
    return _one_group(u"mf", u"Matrix adjustment"), rows


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


MATRIX_FACTORS = cf.Table(
    id=u"mf", title=u"Matrix Adjustment Factors", base=("matrix_factors",),
    columns=[cf.Field("factor", u"Factor", greater_than=0, placeholder=u"1.0")],
    rows=matrix_factor_rows, read=read_matrix_factors, write=write_matrix_factors,
    row_heading=u"Sample Type (core)")

# ── EIS limits (EPA 1633A only) ──────────────────────────────────────────────
# eis_overrides: [{"analyte", "recovery_min", "recovery_max"}], keyed by EPA's
# Table 6 designation (the engine joins the lab's compound to it through the
# native, eis_criteria_name). eis_matrix_overrides: {class: {designation:
# {...}}} -- a class limit overrides the per-analyte one, looked up under the
# SAME designation, so a class row may only name a designation that exists.


def _min_not_above_max(label_key):
    def check(profile, rows):
        out = []
        for r in rows:
            lo, hi = r.get("recovery_min"), r.get("recovery_max")
            if lo is not None and hi is not None and lo > hi:
                out.append(u"%s: recovery min (%s) is above max (%s)." % (r[label_key], lo, hi))
        return out
    return check


def read_eis(profile):
    return [{"analyte": r.get("analyte"), "recovery_min": r.get("recovery_min"),
             "recovery_max": r.get("recovery_max")}
            for r in (profile.get("eis_overrides") or []) if isinstance(r, dict)]


def write_eis(profile, rows):
    old = dict((r.get("analyte"), r) for r in (profile.get("eis_overrides") or [])
               if isinstance(r, dict))
    out = []
    for r in rows:
        entry = dict(old.get(r["analyte"]) or {})     # keep any other keys a row had
        entry.update({"analyte": r["analyte"], "recovery_min": r.get("recovery_min"),
                      "recovery_max": r.get("recovery_max")})
        out.append(entry)
    _set(profile, "eis_overrides", out)
    return profile


EIS = cf.Collection(
    id=u"eis", title=u"SUR Recovery Overrides", noun=u"SUR row", new_rows=2,
    allow_empty=True,
    columns=[cf.Field("analyte", u"Surrogate (SUR)", kind=cf.TEXT,
                      placeholder=u"new designation"),
             cf.Field("recovery_min", u"Recovery Min (%)", minimum=0),
             cf.Field("recovery_max", u"Recovery Max (%)", minimum=0)],
    read=read_eis, write=write_eis, check=_min_not_above_max("analyte"))


EIS_MATRIX_CLASSES = [(u"solid", u"Solid (soil, sediment)"), (u"biosolid", u"Biosolid"),
                      (u"leachate", u"Landfill leachate"), (u"tissue", u"Tissue")]


def eis_designations(profile, env=None):
    names = [r.get("analyte") for r in (profile.get("eis_overrides") or [])
             if isinstance(r, dict) and r.get("analyte")]
    return [(n, n) for n in names]


def _eis_class(key, label):
    def read(profile):
        entries = (profile.get("eis_matrix_overrides") or {}).get(key) or {}
        return [{"analyte": a, "recovery_min": (entries[a] or {}).get("recovery_min"),
                 "recovery_max": (entries[a] or {}).get("recovery_max")}
                for a in sorted(entries)]

    def write(profile, rows):
        allc = dict(profile.get("eis_matrix_overrides") or {})
        entries = {}
        for r in rows:
            if r.get("recovery_min") is None and r.get("recovery_max") is None:
                continue                            # no limit: no row
            entry = {}
            for f in ("recovery_min", "recovery_max"):
                if r.get(f) is not None:
                    entry[f] = r[f]
            entries[r["analyte"]] = entry
        if entries:
            allc[key] = entries
        else:
            allc.pop(key, None)
        _set(profile, "eis_matrix_overrides", allc)
        return profile

    return cf.Collection(
        id=u"eis_" + key, title=u"SUR limits: %s" % label, noun=u"row", new_rows=2,
        allow_empty=True,
        columns=[cf.Field("analyte", u"Surrogate (SUR)", kind=cf.CHOICE,
                          choices=eis_designations),
                 cf.Field("recovery_min", u"Recovery Min (%)", minimum=0),
                 cf.Field("recovery_max", u"Recovery Max (%)", minimum=0)],
        read=read, write=write, check=_min_not_above_max("analyte"))


EIS_CLASSES = [(_eis_class(k, l), l) for k, l in EIS_MATRIX_CLASSES]


# ── Surrogate Map: injection IS, native -> surrogate, surrogate -> injection IS
# Each method owns its map (DECISIONS 2026-09-30). The page supplies the core
# services in env["services"] = {keyword: {"role", "name", "quant_surrogate"}}.

def _map_rows(profile):
    return [r for r in (profile.get("surrogate_map") or [])
            if isinstance(r, dict) and r.get("analyte")]


def surrogate_choices(profile, env=None):
    """Every labelled standard, this method's extracted standards first -- a
    method may pick any (the save then requires it ticked Used with the
    extracted role in the Internal Standards grid)."""
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
    return [(k, svcs[k].get("name") or k) for k in own + rest]


def surrogate_map_rows(profile, env=None):
    titles = _analyte_titles(profile)
    linked = set(r["analyte"] for r in _map_rows(profile) if r.get("surrogate_is"))
    svcs = (env or {}).get("services") or {}
    rows = []
    for kw in profile.get("master_analyte_set") or []:
        row = {"key": (kw,), "group": u"sur", "label": titles.get(kw, kw), "sublabel": kw}
        hint = (svcs.get(kw) or {}).get("quant_surrogate")
        if kw not in linked and hint:
            row["suggest"] = (hint, (svcs.get(hint) or {}).get("name") or hint)
        rows.append(row)
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


# ── Labelled standards grid (MS Quan style; DECISIONS 2026-09-30) ────────────

try:
    from senaite.pfas import labelled_standards as _ls
except Exception:          # tests: loaded without the package
    import labelled_standards as _ls


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
        quantifies.setdefault(r.get("surrogate_is"), []).append(r["analyte"])

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
    return _one_group(u"ls", u"Labelled standards"), rows


def read_labelled(profile):
    return dict(((kw,), {"used": True, "role": v.get("role") or None,
                         "reference": v.get("reference") or None})
                for kw, v in _ls.grid(profile).items())


def write_labelled(profile, updates, env=None):
    grid = dict(_ls.grid(profile))
    for (kw,), vals in updates.items():
        if vals.get(("used",)):
            grid[kw] = {"role": vals.get(("role",)) or u"",
                        "reference": vals.get(("reference",)) or u""}
        else:
            grid.pop(kw, None)
    profile[_ls.KEY] = grid
    profile.pop("surrogate_is", None)           # retired: the grid replaces them
    profile.pop("surrogate_is_chain", None)
    return profile


def _row_consistent(row, values):
    used = values.get(u"f__used")
    if not used and (values.get(u"f__role") or values.get(u"f__reference")):
        return u"%s: tick Used, or clear its role and link." % row["sublabel"]
    return None


LABELLED_STANDARDS = cf.Table(
    id=u"ls", title=u"Internal Standards", base=(_ls.KEY,),
    columns=[cf.Field("used", u"Used", kind=cf.BOOL),
             cf.Field("role", u"Role in this method", kind=cf.CHOICE, choices=role_choices),
             cf.Field("reference", u"Linked to", kind=cf.CHOICE, choices=standard_choices)],
    rows=labelled_rows, rows_take_env=True, read=read_labelled, write=write_labelled,
    check=_row_consistent, row_heading=u"Labelled Standard")


def check_profile(profile):
    """Checks on the WHOLE profile after a tab's sections are applied: the
    grid's links and loops, and its agreement with the surrogate map."""
    return _ls.check(profile)

# ── Isomers (DECISIONS 2026-10-01) ───────────────────────────────────────────

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
    profile.pop(_iso.LEGACY, None)
    return profile


ISOMERS = cf.Table(
    id=u"iso", title=u"Isomers", base=(_iso.KEY,),
    columns=[cf.Field("linear", u"Linear peak", kind=cf.TEXT, placeholder=u"e.g. lr-PFOS"),
             cf.Field("branched", u"Branched peak(s), comma-separated", kind=cf.TEXT,
                      placeholder=u"e.g. br-PFOS"),
             cf.Field("reported", u"Reported as", kind=cf.TEXT,
                      placeholder=u"plain name (e.g. PFOS)")],
    rows=isomer_rows, read=read_isomers, write=write_isomers, row_heading=u"Analyte")


def check_isomers(profile):
    return _iso.check(profile, _global_titles())


# ── QC Types tab: every QC type the lab defines (2026-10-01) ────────────────
# The lab's QC types are the TAGGED core Reference Definitions ([QC:CODE] in the
# description, editable in Setup). The tab used to list only the types already
# in the method's qc_acceptance, so a type the lab defines but a method had
# never had could not be switched on at all.

QC_KIND = {"MB": "blank", "LRB": "blank", "MXB": "blank",
           "LFB": "recovery", "LFSM": "recovery",
           "LFSMD": "rpd", "DUP": "rpd",
           "CAL": "instrument", "ICV": "instrument", "CCV": "instrument", "CCB": "instrument",
           "SUR": "surrogate"}
# qc_acceptance keys keep the spellings the pipeline matches on.
PROFILE_KEY = {"DUP": "Dup", "MXB": "MxB"}
CONFIGURED_ON = {"instrument": ("pane-cal", u"Calibration & CCV"),
                 "surrogate": ("pane-sur", u"Internal Standards")}


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
    """Write the tab's toggles. `offered` = the keys the page showed with a
    toggle; a type switched on that the method never had is created ENABLED
    with NO limits -- the engine then refuses to judge it until criteria are
    set, rather than this tab inventing a recovery window."""
    qca = profile.setdefault("qc_acceptance", {})
    for key in offered:
        on = key in enabled
        if key in qca:
            qca[key]["enabled"] = on
        elif on:
            qca[key] = {"enabled": True, "tiers": []}
    return profile


# Whole-profile checks, run after a tab's sections are applied, keyed by the
# sections whose save must pass them.
PROFILE_CHECKS = [((u"sur", u"ls"), check_profile), ((u"iso",), check_isomers)]

SECTIONS = dict((s.id, s) for s in [CALIBRATION_CCV, REPORTING_LIMITS, MATRICES,
                                    SALT, MATRIX_FACTORS, EIS, SURROGATE_MAP,
                                    LABELLED_STANDARDS, ISOMERS] +
                [c for c, _l in EIS_CLASSES])
