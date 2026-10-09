# -*- coding: utf-8 -*-
"""The settings report: every QC setting, how it is applied and where.


Two halves:

* APPLICATION -- for each QC type and instrument check: what criterion the
  method stores, and whether the pipeline JUDGES it, with how. This is a
  statement about the code, so tests/test_settings_report.py checks it
  against the pipeline (a check marked evaluated must exist there; one marked
  not evaluated must not), and the report goes stale loudly, not silently.
* SETTINGS -- every declared Method Profile section (method_profile_sections.
  SECTIONS, the same declarations the editor draws), dumped generically, so
  a setting added to the editor appears in the report with no change here.

Pure: plain dicts in and out (the view gathers the stores). Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import hashlib
import json

try:
    from senaite.pfas import config_forms as cf
    from senaite.pfas import method_profile_sections as mps
except Exception:          # tests: loaded without the package
    import config_forms as cf
    import method_profile_sections as mps

# (code, criterion, evaluated, how the pipeline applies it / why not, check kind)
QC_APPLICATION = [
    ("LFSM", u"Recovery window per tier", True,
     u"Each LFSM injection x analyte: (fortified - unfortified) / spike x 100, against "
     u"the tier for the analyte's group and the batch matrix; a low-level tier at or "
     u"below N x RL. Not judged without a spike level.", "lfsm"),
    ("LFSMD", u"RPD per tier", True,
     u"RPD of the LFSM and LFSMD recoveries, against the tier's maximum RPD (low-level "
     u"tier at or below N x RL).", "lfsmd"),
    ("SUR", u"Surrogate recovery", True,
     u"Every injection's labelled surrogate recovery (FDA: guidance only; EPA 537.1 "
     u"70-130%; EPA 1633A per analyte x matrix class). Rule switch: "
     u"surrogate_recovery.", "surrogate"),
    ("Dup", u"Maximum RPD", True,
     u"Each sample / duplicate pair (paired by the extraction record, else the name "
     u"'<sample> Dup') where both results reach the RL, against the Dup tier; low-level "
     u"tier at or below N x RL of the pair's mean. One detected only: flagged for review.",
     "dup"),
    ("LFB", u"Recovery window per tier", True,
     u"Each LFB injection x analyte: measured / spike x 100 (spike from the LFB "
     u"spike levels or the extraction record) against the LFB tiers, low-level tier "
     u"at or below N x RL. Not judged without a spike level.", "lcs"),
    ("LCS", u"Recovery window per tier", True,
     u"Its own QC type: an injection named LCS, against the LCS tiers; not judged "
     u"by a method that does not run LCS.", "lcs"),
    ("MB", u"Maximum concentration (x RL)", True,
     u"Each blank analyte against N x RL for the matrix (also used for the < LOD "
     u"comparison). Not judged without an RL.", "blank"),
    ("LRB", u"Maximum concentration (x RL)", True, u"As MB.", "blank"),
    ("MxB", u"Maximum concentration (x RL)", True, u"As MB.", "blank"),
]

# (check, criterion, evaluated, how, check kind, the rule switch that gates it)
INSTRUMENT_APPLICATION = [
    (u"Calibration", u"r² minimum, point % deviation", True,
     u"Per analyte from the calibration standards in the run (runs if the calibration "
     u"or the CCV switch is on).", "calibration", "cal_r2"),
    (u"CCV", u"Recovery window, frequency", True,
     u"Each CCV injection's calculated / expected concentration.", "ccv", "ccv_recovery"),
    (u"Internal standard response", u"Area window vs calibration / last CCV", True,
     u"Every injection's IS area.", "is_response", "is_response"),
    (u"Retention time", u"RRT deviation", True, u"Every peak's relative RT.", "rt", "rrt_deviation"),
    (u"Ion ratio", u"Qualifier / quantifier tolerance", True, u"Every detected peak.",
     "ion_ratio", "ion_ratio"),
    (u"Signal to noise", u"Minimum S/N (quantitation)", True, u"Every reported peak.", "sn", "sn_min"),
    (u"CCV frequency", u"A CCV every N injections (Calibration & CCV)", True,
     u"Every injection in the bracketed body (field samples and extracted QC) more "
     u"than N after the last CCV, or with no closing CCV.", "ccv_frequency", "ccv_frequency"),
    (u"MDL", u"Detections at or above the MDL", True,
     u"Every reported detection below the analyte's MDL for the matrix. Not judged "
     u"without an MDL.", "mdl", "mdl_check"),
]

# The rule switches the pipeline actually reads (pinned against the code by
# tests/test_settings_report.py). A switch outside this set changes nothing.
CONSUMED_TOGGLES = frozenset(["is_response", "rrt_deviation", "ion_ratio", "cal_r2",
                              "ccv_recovery", "sn_min", "single_transition_confirm",
                              "ccv_frequency", "mdl_check", "surrogate_recovery"])


def _switch_labels():
    try:
        from senaite.pfas.qc.rules import RULE_LIBRARY
    except Exception:                                       # noqa: BLE001
        return {}
    return dict((r["key"], r.get("label") or r["key"]) for r in RULE_LIBRARY)


def toggle_report(toggles):
    """[{"key", "label", "on", "read"}] for a method's rule switches; a key
    no rule defines is shown readably, marked as unknown."""
    labels = _switch_labels()
    return [{"key": k, "label": labels.get(k) or u"%s (not a known rule)" % k.replace("_", " "),
             "on": bool(v), "read": k in CONSUMED_TOGGLES}
            for k, v in sorted((toggles or {}).items())]


def _text(value, field=None):
    if value is None or value == u"":
        return u""
    if field is not None and field.kind == cf.BOOL:
        return u"Yes" if value else u"No"
    if isinstance(value, (list, tuple)):
        return u", ".join(u"%s" % v for v in value)
    if isinstance(value, float):
        return u"%g" % value
    return u"%s" % value


def _choice_label(field, value, profile, env):
    if field.kind == cf.CHOICE and value not in (None, u""):
        for v, label in cf._choices(field, profile, env):
            if v == value:
                return label
    return value


def section_dump(section, profile, env=None):
    """{"title", "columns", "rows": [[label, value, ...]]} -- the section's
    STORED values as text (blank = unset / the default applies)."""
    profile = profile or {}
    if isinstance(section, cf.Table):
        t = cf._bound(section, profile)
        _groups, rows = cf._rows(t, profile, env)
        out = []
        for r in rows:
            vals = cf._cells(t, profile, r["key"])
            cells = [_text(_choice_label(c, vals[c.name], profile, env), c) for c in t.columns]
            # a value that applies without being typed (an RL from the lowest
            # calibrator) prints as the editor shows it, e.g. "2 (lowest cal.)"
            derived = r.get("placeholders") or {}
            cells = [v or derived.get(c.path[0], u"") for v, c in zip(cells, t.columns)]
            if any(cells):
                label = r.get("label") or u" / ".join(r["key"])
                if r.get("group") and r.get("group") not in (t.id,) and len(r["key"]) > 1:
                    label = u"%s — %s" % (r["key"][0], label)
                out.append([label] + cells)
        return {"title": section.title, "columns": [t.row_heading] + [c.label for c in t.columns],
                "rows": out}
    if isinstance(section, cf.Collection):
        c = cf._bound(section, profile)
        return {"title": section.title, "columns": [f.label for f in c.columns],
                "rows": [[_text(_choice_label(f, row.get(f.path[0]), profile, env), f) for f in c.columns]
                         for row in c.read(profile)]}
    vals = cf.current(section, profile)
    rows = []
    for f in section.fields():
        v = _text(_choice_label(f, vals[f.name], profile, env), f)
        rows.append([f.label, (v + (u" " + f.unit if v and f.unit else u""))])
    return {"title": section.title, "columns": [u"Setting", u"Value"], "rows": rows}


def _tier_text(t):
    parts = []
    if t.get("recovery_min") is not None:
        parts.append(u"%g–%g%%" % (t["recovery_min"], t["recovery_max"]))
    for key, label in (("rsd_max", u"RSD ≤ %g"), ("rpd_max", u"RPD ≤ %g%%"),
                       ("max_conc_x_rl", u"< %g × RL" if t.get("fails_at_limit") else u"≤ %g × RL")):
        if t.get(key) is not None:
            parts.append(label % t[key])
    return u", ".join(parts) or u"no criterion"


def qc_application(profile):
    """One row per QC type the method stores (or the table names): enabled,
    evaluated, how, and each tier as text with its scope and source."""
    qca = profile.get("qc_acceptance") or {}
    groups, scopes = dict(mps.GROUP_CHOICES), dict(mps.SCOPE_CHOICES)
    rows = []
    for code, criterion, evaluated, how, _kind in QC_APPLICATION:
        entry = qca.get(code)
        if code == "SUR" and not isinstance(entry, dict):
            entry = {}                  # runs for every method, window from the method text
        if not isinstance(entry, dict):
            continue
        tiers = []
        for t in entry.get("tiers") or []:
            if not isinstance(t, dict):
                continue
            when = (u"at or below %g × RL" % t[mps.LOW_LEVEL_KEY]
                    if t.get(mps.LOW_LEVEL_KEY) is not None else u"")
            tiers.append({"name": t.get("name") or u"", "criterion": _tier_text(t),
                          "applies": u"%s; %s%s" % (groups.get(t.get("analyte_group") or u"all", t.get("analyte_group")),
                                                   scopes.get(t.get("matrix_scope") or u"all", t.get("matrix_scope")),
                                                   (u"; " + when) if when else u""),
                          "source": t.get("citation") or (u"VERIFY against the method"
                                                          if t.get("verify_against_method") else u"method profile")})
        rows.append({"code": code, "criterion": criterion, "enabled": entry.get("enabled", True) is not False,
                     "evaluated": evaluated, "how": how, "tiers": tiers})
    return rows


def instrument_application(toggles):
    toggles = toggles or {}
    labels = _switch_labels()
    return [{"check": c, "criterion": crit, "evaluated": ev, "how": how, "switch": sw,
             "switch_label": labels.get(sw) or sw, "on": bool(toggles.get(sw, True))}
            for c, crit, ev, how, _kind, sw in INSTRUMENT_APPLICATION]


def method_report(profile, env=None, toggles=None):
    secs = [mps.SECTIONS[sid] for sid in _section_order() if sid in mps.SECTIONS]
    return {
        "instrument": instrument_application(toggles),
        "switches": toggle_report(toggles),
        "method_id": profile.get("method_id") or u"",
        "name": profile.get("display_name") or profile.get("method_id") or u"",
        "matrices": list(profile.get("supported_matrices") or []),
        "panel": len(profile.get("master_analyte_set") or []),
        "qc": qc_application(profile),
        "grid": mps.recovery_grid(profile),
        "sections": [d for d in (section_dump(s, profile, env) for s in secs) if d["rows"]],
    }


def _section_order():
    """The editor's tab order; any section not named here follows."""
    first = ["cal", "cal_levels", "cal_scale", "rl", "mtx", "corr", "salt", "mf", "rf", "al", "groups", "tiers", "tiers_lfb",
             "dup", "lfsmd", "ls", "sur", "iso", "eis_grid"]
    return first + sorted(k for k in mps.SECTIONS if k not in first)


def fingerprint(*stores):
    """A short, stable id of the configuration the report was made from."""
    blob = json.dumps(stores, sort_keys=True, default=str)
    if not isinstance(blob, bytes):
        blob = blob.encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
