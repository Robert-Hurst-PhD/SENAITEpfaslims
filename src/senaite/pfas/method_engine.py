# -*- coding: utf-8 -*-
"""How a method is judged, as profile settings: the "Engine" section.

The worker has ONE rule interpreter for every method
(pfas_pipeline.method_profiles.ConfiguredProfile); what differs between
methods is read here, from the profile:

  engine.grouped_recovery_tiers  bool   tiers chosen by analyte group and
                                        Tier 1 matrices (else the first
                                        ordinary tier for every analyte)
  engine.qc_type_aliases         {qc: qc}  a QC type judged as another
                                        ({"OPR": "LFB"})
  engine.surrogate_guidance_only bool   surrogate recovery is guidance only
  engine.surrogate_fallback      {min, max, citation} | None  the method
                                        text's surrogate window, used when
                                        the profile sets none
  engine.eis_recovery_limits     bool   SUR / EIS judged per analyte and
                                        matrix class (eis_overrides)
  engine.eis_default_window      "lfsm_tier" | "surrogate_window" | None
  engine.eis_verify_flag         bool   EIS rules carry the "verify" flag
  engine.required_keys           {rule: [keys]}  instrument criteria whose
                                        absence refuses (calibration,
                                        is_response, confirmation)
  engine.aliases                 [names] other names the method is called by
  engine.rule_notes              {rule: text}  the note each rule carries
  engine.labelled_compound_fit   "mean_response_factor" | ""  the fit for a
                                        labelled compound's calibration
  engine.inclusion_needs_verification bool  the analyte x matrix inclusion
                                        is to be confirmed against the
                                        published method (editor notice)

and at profile level: matrix_classes {matrix: class}, blank_role_name,
study_kinds and idc.

A profile with no settings has every feature OFF: no grouping, no aliases,
no surrogate fallback, no EIS limits, nothing required beyond what a rule
cannot be built without, no notes. Nothing here borrows another method's
values.

migrate(profile, method_id) writes, once, the behaviour the three shipped
methods had when they were code -- no number changes.

Pure; Python 2.7 and 3 (the worker loads it by path).
"""
from __future__ import absolute_import, unicode_literals

import copy

ENGINE_KEY = "engine"
VERSION_KEY = "engine_v"
STUDY_KINDS = ("mdl", "pt", "pa", "mrl", "dl", "idc")
EIS_WINDOWS = ("lfsm_tier", "surrogate_window")
RULES = ("calibration", "is_response", "confirmation")

_TRUE = (True, 1, "1", "yes", "on", "true", "True")

# Profile keys the migration writes once and the lab may clear: the export
# never back-fills them from the shipped seeds (a cleared value stays cleared)
NOT_BACKFILLED = ("blank_role_name", "study_kinds", "idc", "matrix_classes")


def _text(v):
    try:
        return u"%s" % v if v is not None else u""
    except Exception:                                     # noqa: BLE001
        return u""


def _bool(v):
    return v in _TRUE


def _names(v):
    """A list typed as text ("A, B; C") or stored as a list."""
    if isinstance(v, (list, tuple)):
        items = v
    else:
        items = _text(v).replace(u";", u",").split(u",")
    out = []
    for x in items:
        x = _text(x).strip()
        if x and x not in out:
            out.append(x)
    return out


def _pairs(v):
    """{a: b} from a dict or from text "A=B, C=D"."""
    if isinstance(v, dict):
        return dict((_text(k).strip(), _text(x).strip()) for k, x in v.items()
                    if _text(k).strip() and _text(x).strip())
    out = {}
    for item in _names(v):
        if u"=" in item:
            a, b = item.split(u"=", 1)
            if a.strip() and b.strip():
                out[a.strip()] = b.strip()
    return out


def _num(v):
    if v in (None, u"", ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fallback(v):
    """{min, max, citation} when both ends are set, else None."""
    if not isinstance(v, dict):
        return None
    lo, hi = _num(v.get("min")), _num(v.get("max"))
    if lo is None or hi is None:
        return None
    return {"min": lo, "max": hi, "citation": _text(v.get("citation"))}


def _required(v):
    if not isinstance(v, dict):
        return {}
    return dict((_text(k), _names(x)) for k, x in v.items() if _names(x))


def _notes(v):
    if not isinstance(v, dict):
        return {}
    return dict((_text(k), _text(x)) for k, x in v.items() if x not in (None, u"", ""))


def engine(profile):
    """The profile's Engine settings, normalised, every feature OFF when
    unset."""
    e = (profile or {}).get(ENGINE_KEY)
    e = e if isinstance(e, dict) else {}
    window = e.get("eis_default_window")
    return {
        "grouped_recovery_tiers": _bool(e.get("grouped_recovery_tiers")),
        "qc_type_aliases": _pairs(e.get("qc_type_aliases")),
        "surrogate_guidance_only": _bool(e.get("surrogate_guidance_only")),
        "surrogate_fallback": _fallback(e.get("surrogate_fallback")),
        "eis_recovery_limits": _bool(e.get("eis_recovery_limits")),
        "eis_default_window": window if window in EIS_WINDOWS else None,
        "eis_verify_flag": _bool(e.get("eis_verify_flag")),
        "required_keys": _required(e.get("required_keys")),
        "aliases": _names(e.get("aliases")),
        "rule_notes": _notes(e.get("rule_notes")),
        "labelled_compound_fit": (u"mean_response_factor"
                                  if e.get("labelled_compound_fit") == u"mean_response_factor"
                                  else u""),
        "inclusion_needs_verification": _bool(e.get("inclusion_needs_verification")),
    }


def _profile_key(profile, key):
    """A profile-level setting: at the top level (where the migration writes
    it), else inside the Engine section."""
    profile = profile or {}
    if key in profile:
        return profile.get(key)
    eng = profile.get(ENGINE_KEY)
    return eng.get(key) if isinstance(eng, dict) else None


# the method-blank role names a profile may use, in the order tried when the
# profile does not name one; the study kinds every method may run
BLANK_ROLE_NAMES = ("MB", "LRB")
DEFAULT_STUDY_KINDS = ("mdl", "pt")


def blank_role(profile):
    """The method's name for its method blank ("MB", "LRB"): the profile's
    blank_role_name, else the first of BLANK_ROLE_NAMES the method runs
    (enabled QC type), else None. Never another method's."""
    v = _text(_profile_key(profile, "blank_role_name")).strip()
    if v:
        return v
    types = (profile or {}).get("qc_acceptance") or {}
    for code in BLANK_ROLE_NAMES:
        cfg = types.get(code)
        if isinstance(cfg, dict) and cfg.get("enabled"):
            return code
    return None


def study_kinds(profile):
    """The study kinds the method offers (among STUDY_KINDS): the profile's,
    else DEFAULT_STUDY_KINDS (MDL and PT apply to every method)."""
    named = [k for k in _names(_profile_key(profile, "study_kinds")) if k in STUDY_KINDS]
    return named or list(DEFAULT_STUDY_KINDS)


def idc_spec(profile):
    """{"elements": [(key, label)], "asymmetry": (min, max) | None} from the
    profile's idc ({"elements": [[key, label], ...], "asymmetry": [lo, hi]}),
    or None when the method defines no IDC."""
    idc = _profile_key(profile, "idc")
    if not isinstance(idc, dict):
        return None
    elements = []
    for row in idc.get("elements") or []:
        if isinstance(row, dict):
            key, label = row.get("key"), row.get("label")
        elif isinstance(row, (list, tuple)) and len(row) == 2:
            key, label = row
        else:
            continue
        if key:
            elements.append((_text(key), _text(label) or _text(key)))
    if not elements:
        return None
    asym = idc.get("asymmetry")
    if isinstance(asym, (list, tuple)) and len(asym) == 2:
        lo, hi = _num(asym[0]), _num(asym[1])
    elif isinstance(asym, dict):
        lo, hi = _num(asym.get("min")), _num(asym.get("max"))
    else:
        lo = hi = None
    return {"elements": elements,
            "asymmetry": (lo, hi) if lo is not None and hi is not None else None}


def matrix_class(profile, matrix):
    """The matrix's class (matrix_classes), by its title or one of its
    aliases, case-insensitive; None when the profile gives it none."""
    classes = (profile or {}).get("matrix_classes") or {}
    if not isinstance(classes, dict) or not matrix:
        return None
    m = _text(matrix).lower().strip()
    by_title = dict((_text(k).lower().strip(), v) for k, v in classes.items())
    if m in by_title:
        return by_title[m] or None
    for title, aliases in ((profile or {}).get("matrix_aliases") or {}).items():
        if m in [_text(a).lower().strip() for a in aliases or []]:
            return by_title.get(_text(title).lower().strip()) or None
    return None


def default_matrix_class(matrix):
    """EPA 1633A's matrix classes (Tables 6 / 8) from a matrix title: what a
    migration writes into matrix_classes, and the baselines' classification
    of a title with no profile at hand."""
    m = _text(matrix).lower().strip()
    if u"leachate" in m:
        return u"leachate"
    if u"tissue" in m:
        return u"tissue"
    if u"biosolid" in m:
        return u"biosolid"
    if u"solid" in m or u"sediment" in m or u"soil" in m:
        return u"solid"
    return u"aqueous"


# ── what the shipped methods did as code (migrate) ─────────────────────────
# Moved, not changed: the values and texts the engine classes held.

def _load_shipped():
    import io
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "method_engine_shipped.json")
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)["methods"]


# {method id: {"engine": {...}, "blank_role_name", "study_kinds", "idc",
# "matrix_classes_from_titles"}} -- data (method_engine_shipped.json)
SHIPPED = _load_shipped()


def migrate(profile, method_id):
    """Once (VERSION_KEY): the Engine settings, blank role, study kinds, IDC
    and matrix classes the shipped method had as code. A setting the profile
    already holds is kept. A method this does not know gets nothing."""
    spec = SHIPPED.get(method_id)
    if spec is None or profile.get(VERSION_KEY) == 1:
        return False
    eng = profile.get(ENGINE_KEY)
    eng = eng if isinstance(eng, dict) else {}
    for key, value in spec["engine"].items():
        if key not in eng:
            eng[key] = copy.deepcopy(value)
    profile[ENGINE_KEY] = eng
    for key in ("blank_role_name", "study_kinds", "idc"):
        if key in spec and key not in profile:
            profile[key] = copy.deepcopy(spec[key])
    if spec.get("matrix_classes_from_titles"):
        classes = profile.get("matrix_classes")
        classes = classes if isinstance(classes, dict) else {}
        for m in profile.get("supported_matrices") or []:
            classes.setdefault(m, default_matrix_class(m))
        profile["matrix_classes"] = classes
    if method_id == "EPA_537_1":
        # the engine read an absent force-through-origin as on for this
        # method; written down so the profile says what applies
        cal = (profile.get("instrument_verification") or {}).get("calibration")
        if isinstance(cal, dict) and "force_origin" not in cal:
            cal["force_origin"] = True
    profile[VERSION_KEY] = 1
    return True
