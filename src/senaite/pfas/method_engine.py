# -*- coding: utf-8 -*-
"""How a method is judged, as profile settings: the "Engine" section.

The worker has ONE rule interpreter for every method
(pfas_pipeline.method_profiles.ConfiguredProfile); what differs between
methods is read here, from the profile:

  grouped_recovery_tiers         bool   tiers chosen by analyte group and
                                        each tier's own matrices (else the first
                                        ordinary tier for every analyte):
                                        derived, never stored -- on when
                                        any QC type's tier names an analyte
                                        group or matrix scope other than all
  engine.qc_type_aliases         {qc: qc}  a QC type judged as another
                                        ({"OPR": "LFB"})
  engine.surrogate_guidance_only bool   surrogate recovery is guidance only
  engine.surrogate_fallback      {min, max} | None  the method
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
  engine.rule_flags              {rule: {code, attach, output, note}}  each
                                        rule's flag (rule_flags); engine() gives
                                        the worker its notes as rule_notes
  engine.rule_flags_more         {rule: [flag]}  a rule's further flags
  engine.rule_kinds              {rule: kind | ""}  a rule's kind of
                                        exceedance where it differs from
                                        flag_kinds.DEFAULT_KINDS
  engine.labelled_compound_fit   "mean_response_factor" | ""  the fit for a
                                        labelled compound's calibration
  engine.inclusion_needs_verification bool  the analyte x matrix inclusion
                                        is to be confirmed against the
                                        published method (editor notice)
  engine.recovery_decimals       int    the decimal places a recovery
                                        percent is judged, shown and printed
                                        at (recovery_decimals); unset: whole
                                        percent

and at profile level: matrix_classes {matrix: class}, blank_role_name,
study_kinds and idc.

A profile with no settings has every feature OFF: no grouping, no aliases,
no surrogate fallback, no EIS limits, nothing required beyond what a rule
cannot be built without, no notes. Nothing here borrows another method's
values.

migrate(profile, method_id) writes, once, the shipped methods' engine
settings into a profile.

Pure; Python 2.7 and 3 (the worker loads it by path).
"""
from __future__ import absolute_import, unicode_literals


ENGINE_KEY = "engine"
STUDY_KINDS = ("mdl", "pt", "pa", "mrl", "dl", "idc")
EIS_WINDOWS = ("lfsm_tier", "surrogate_window")
RULES = ("calibration", "is_response", "confirmation")

_TRUE = (True, 1, "1", "yes", "on", "true", "True")

# Profile keys the migration writes once and the lab may clear: the export
# never back-fills them from the shipped seeds (a cleared value stays cleared)
# (a composite standard a seed ships is for new installs only: a stored
# profile is the lab's, and its surrogate map would not name it)
NOT_BACKFILLED = ("blank_role_name", "study_kinds", "idc", "matrix_classes", "composite_standards")


def _text(v):
    try:
        return u"%s" % v if v is not None else u""
    except UnicodeError:
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


from senaite.pfas.rounding import number as _num


def _fallback(v):
    """{min, max} when both ends are set, else None."""
    if not isinstance(v, dict):
        return None
    lo, hi = _num(v.get("min")), _num(v.get("max"))
    if lo is None or hi is None:
        return None
    return {"min": lo, "max": hi}


def _required(v):
    if not isinstance(v, dict):
        return {}
    return dict((_text(k), _names(x)) for k, x in v.items() if _names(x))


def _notes(v):
    if not isinstance(v, dict):
        return {}
    return dict((_text(k), _text(x)) for k, x in v.items() if x not in (None, u"", ""))


def tiers_grouped(tiers):
    """Does any of these tiers pick by analyte group or matrix scope? A
    missing or blank group / scope is "all"."""
    for t in tiers or []:
        if not isinstance(t, dict):
            continue
        if (t.get("analyte_group") or "all") != "all" or (t.get("matrix_scope") or "all") != "all":
            return True
    return False


def profile_tiers(profile, replace=None):
    """Every QC type's tiers in the profile; `replace` {qc: tiers} stands in
    for the stored tiers of those QC types (a save being checked)."""
    replace = replace or {}
    qca = (profile or {}).get("qc_acceptance")
    qca = qca if isinstance(qca, dict) else {}
    out = []
    for qc in set(qca) | set(replace):
        if qc in replace:
            out.extend(replace[qc] or [])
            continue
        entry = qca.get(qc)
        if isinstance(entry, dict) and isinstance(entry.get("tiers"), list):
            out.extend(entry["tiers"])
    return out


def _rule_flags():
    from senaite.pfas import rule_flags
    return rule_flags


def engine(profile):
    """The profile's Engine settings, normalised, every feature OFF when
    unset; grouped recovery tiers derived from the tiers themselves."""
    e = (profile or {}).get(ENGINE_KEY)
    e = e if isinstance(e, dict) else {}
    window = e.get("eis_default_window")
    return {
        "grouped_recovery_tiers": tiers_grouped(profile_tiers(profile)),
        "qc_type_aliases": _pairs(e.get("qc_type_aliases")),
        "surrogate_guidance_only": _bool(e.get("surrogate_guidance_only")),
        "surrogate_fallback": _fallback(e.get("surrogate_fallback")),
        "eis_recovery_limits": _bool(e.get("eis_recovery_limits")),
        "eis_default_window": window if window in EIS_WINDOWS else None,
        "eis_verify_flag": _bool(e.get("eis_verify_flag")),
        "required_keys": _required(e.get("required_keys")),
        "aliases": _names(e.get("aliases")),
        # the notes the worker's rules carry, read from the rules' flags
        # (rule_flags.legacy_notes; a profile not yet migrated, its own)
        "rule_notes": _notes(_rule_flags().legacy_notes(profile)),
        "labelled_compound_fit": (u"mean_response_factor"
                                  if e.get("labelled_compound_fit") == u"mean_response_factor"
                                  else u""),
        "inclusion_needs_verification": _bool(e.get("inclusion_needs_verification")),
    }


# the words every page uses where a limit is reported but does not fail the
# sample (its box's state, Evaluate: guidance only folded into it), and
# where a value is the method's own default
GUIDANCE_WORDS = u"Evaluate"
METHOD_DEFAULT_WORDS = u"Method default"

# the Engine setting that makes a rule guidance only, and the rule it governs
_GUIDANCE_SETTINGS = (("surrogate_guidance_only", "surrogate_recovery"),)


def guidance_only_rules(profile):
    """The keys of the rules the method reports without failing a sample:
    the surrogate recovery while its window's box is in the state Evaluate
    (limit_states; guidance only folded into Evaluate, and a method that had
    the Engine setting on seeds its box so). The one reader: the rules grid,
    Effective QC and surrogate_window all ask here."""
    from senaite.pfas import limit_states
    return frozenset(rule for _setting, rule in _GUIDANCE_SETTINGS
                     if limit_states.box_state(profile or {}, rule) == "evaluate")


RECOVERY_DECIMALS_MAX = 3


def recovery_decimals(profile):
    """The decimal places a recovery percent is judged at by the worker's
    checks and shown with on every page and printout: the Engine's
    recovery_decimals, a whole number from 0 to RECOVERY_DECIMALS_MAX; 0, a
    whole percent, when the method sets none or sets something else. A
    stored value or verdict is never rewritten by a change: the run records
    the places it was judged at (rounding.judged_rule) and a certificate
    refuses a run judged at others until it is reprocessed."""
    e = (profile or {}).get(ENGINE_KEY)
    v = e.get("recovery_decimals") if isinstance(e, dict) else None
    if isinstance(v, bool) or v is None:
        return 0
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    if n != int(n) or not 0 <= n <= RECOVERY_DECIMALS_MAX:
        return 0
    return int(n)


def surrogate_window(profile):
    """The method's one surrogate window, as the worker judges every
    surrogate of a method whose standards are not judged per matrix class:
    the profile's own (instrument_verification.surrogate_window, both ends
    set), else the window the method text states (engine.surrogate_fallback),
    else None. {min, max, source, guidance_only}: `source` is "profile" or
    "method_text". The one reader of that precedence: the worker, the
    Isotope standards grid, the rule table and Effective QC all ask here."""
    eng = engine(profile)
    guidance = "surrogate_recovery" in guidance_only_rules(profile)
    win = ((profile or {}).get("instrument_verification") or {}).get("surrogate_window")
    win = win if isinstance(win, dict) else {}
    if win.get("recovery_min") is not None and win.get("recovery_max") is not None:
        return {"min": float(win["recovery_min"]), "max": float(win["recovery_max"]),
                "source": "profile", "guidance_only": guidance}
    fallback = eng["surrogate_fallback"]
    if fallback is None:
        return None
    return {"min": fallback["min"], "max": fallback["max"], "source": "method_text",
            "guidance_only": guidance}


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


# ── the shipped methods' engine settings (migrate) ─────────────────────────


