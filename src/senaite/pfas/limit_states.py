# -*- coding: utf-8 -*-
"""Every limit box of a method profile carries its own state: Enforced (a
failure holds release), Evaluate (judged and filed as advisory) or Off
(not judged; the limit is kept and stays editable).

Where a state is stored:
  profile["limit_states"] {box key: state}   the instrument boxes of BOXES,
                                             the rule tiles, the worksheet size,
                                             the lowest EIS recovery in a
                                             diluted extract
  tier["state"]                              each tier of a QC type, and a
                                             blank's limit (its default tier)

A box with no stored state reads its seed: the state its rule, QC type or
blank held before boxes had states (rule_states, rule_toggles,
engine.required_keys, engine.surrogate_guidance_only, the Low-level
recoveries row), by these rules:

  - a rule that was Off seeds Off, a Required limit too;
  - an optional limit that is empty and was not Required seeds Off, but
    where neither RT tolerance is set the Relative one keeps its rule's
    state (the rule cannot run without one);
  - an optional limit that is empty and was Required seeds Enforced, so it
    still refuses when empty;
  - otherwise the box takes its rule's state;
  - a surrogate box of a method whose surrogate recovery was guidance only
    seeds Evaluate;
  - a tier takes its type's state, a low-level tier its type's and the
    Low-level recoveries row's together.

migrate(profile) writes every seed not yet stored, once: it never
overwrites a stored state and never deletes an old key, so the old keys stay
readable; once a box is stored they no longer touch it. The worker reads
this module (pfas_pipeline.addon.load), so both processes judge alike.

A limit that is empty: Enforced refuses the run (a gap that holds release),
Evaluate lets it go on with an advisory, Off is not judged. A box whose
empty value means another window applies ("uses") never refuses.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

STATES = ("enforced", "evaluate", "off")
STATE_WORDS = {"enforced": "Enforced", "evaluate": "Evaluate", "off": "Off"}
STORE_KEY = "limit_states"
TIER_KEY = "state"
TIER_PREFIX = "tier."

# what a box's empty limit means (see the module docstring)
NEEDED, OPTIONAL, USES, RULE, OWN = "needed", "optional", "uses", "rule", "own"

# the Calibration rules a point deviation or the dropped-calibrator count runs
# under: either one on runs it
CAL_RULES = ("cal_r2", "ccv_recovery")


def _box(key, label, rule, fields, kind, uses=None, group=None):
    return {"key": key, "label": label, "rule": rule, "fields": tuple(fields), "kind": kind,
            "uses": uses, "group": group}


# fields are (instrument_verification section, key); the worksheet size is
# (None, key) under extraction_batch
BOXES = [
    _box("is_response", "IS Response", "is_response",
         [("is_response", "vs_ical_avg_min"), ("is_response", "vs_ical_avg_max")], NEEDED, group="is_response"),
    _box("is_vs_ccv", "IS response vs. the most recent CCV", "is_vs_ccv",
         [("is_response", "vs_last_ccv_min"), ("is_response", "vs_last_ccv_max")], OPTIONAL, group="is_response"),
    _box("rrt_deviation.relative", "Relative RT Tolerance", "rrt_deviation",
         [("confirmation", "rrt_tol_pct")], OPTIONAL, group="confirmation"),
    _box("rrt_deviation.absolute", "Absolute RT Tolerance", "rrt_deviation",
         [("confirmation", "rt_tol_abs_min")], OPTIONAL, group="confirmation"),
    _box("ion_ratio", "Ion Ratio Tolerance ±", "ion_ratio",
         [("confirmation", "ion_ratio_tol_pct")], NEEDED, group="confirmation"),
    _box("sn_min.quan", "S/N Min — Quantitation Ion", "sn_min",
         [("confirmation", "sn_quan_min")], NEEDED, group="confirmation"),
    _box("sn_min.confirm", "S/N Min — Confirm Ion", "sn_min",
         [("confirmation", "sn_confirm_min")], NEEDED, group="confirmation"),
    _box("cal_r2", "R² Minimum", "cal_r2", [("calibration", "r2_min")], OPTIONAL, group="calibration"),
    _box("cal_point", "Largest calibration point deviation", CAL_RULES,
         [("calibration", "point_pct_dev_max")], OPTIONAL, group="calibration"),
    _box("cal_low_point", "Largest deviation at the lowest level", CAL_RULES,
         [("calibration", "low_point_pct_dev_max")], OPTIONAL, group="calibration"),
    _box("cal_dropped", "Most calibrators dropped", CAL_RULES,
         [("calibration", "max_cal_dropped")], OPTIONAL, group="calibration"),
    _box("ccv_recovery", "CCV Recovery", "ccv_recovery",
         [("ccv", "recovery_min"), ("ccv", "recovery_max")], NEEDED),
    _box("ccv_low_level", "CCV Low-Level", "ccv_recovery",
         [("ccv", "low_level_min"), ("ccv", "low_level_max")], USES, uses="Uses the Recovery window"),
    _box("icv", "Largest ICV deviation", "ccv_recovery", [("icv", "pct_dev_max")], NEEDED),
    _box("ccv_frequency", "CCV Frequency", "ccv_frequency", [("ccv", "frequency")], NEEDED),
    _box("surrogate_recovery", "Surrogate Recovery", "surrogate_recovery",
         [("surrogate_window", "recovery_min"), ("surrogate_window", "recovery_max")], OWN),
    _box("surrogate_ccv", "Surrogate recovery in CCVs", "surrogate_recovery",
         [("ccv", "surrogate_window_min"), ("ccv", "surrogate_window_max")], USES,
         uses="Uses the sample window"),
    _box("single_transition_confirm", "Qualifier ion check", "single_transition_confirm",
         [("confirmation", "confirm_pct_diff_max")], RULE),
    _box("over_range", "Above the Calibration Range", "over_range", [], RULE),
    _box("mdl_check", "MDL Check", "mdl_check", [], RULE),
    _box("worksheet_size", "Most per worksheet", None, [(None, "max_size")], OPTIONAL),
    _box("dilution_eis_floor", "Lowest EIS recovery in a diluted extract", None,
         [("dilution", "eis_floor_pct")], OPTIONAL),
]
BOX = dict((b["key"], b) for b in BOXES)
SURROGATE_BOXES = ("surrogate_recovery", "surrogate_ccv")
# two tolerances of which the rule needs one: (the other box, whether this
# one keeps the rule's state when both are empty)
ALTERNATES = {"rrt_deviation.relative": ("rrt_deviation.absolute", True),
              "rrt_deviation.absolute": ("rrt_deviation.relative", False)}
# what each box's gap is filed under (the QC type of its unevaluated row)
GAP_TYPES = {"is_response": "IS Response", "is_vs_ccv": "IS Response",
             "rrt_deviation.relative": "RT", "rrt_deviation.absolute": "RT",
             "ion_ratio": "Ion Ratio", "sn_min.quan": "Signal-to-Noise", "sn_min.confirm": "Signal-to-Noise",
             "cal_r2": "Calibration", "cal_point": "Calibration", "cal_low_point": "Calibration",
             "cal_dropped": "Calibration", "ccv_recovery": "CCV", "icv": "ICV", "ccv_frequency": "CCV frequency",
             "dilution_eis_floor": "Dilution"}
# what an Evaluate box with no limit is filed under: a QC type no rule card
# holds, so no rule's flag code prints for it (rule_flags.rule_for_qc_row);
# the row is advisory and holds nothing
ADVISORY_GAP_TYPE = "No limit set"
# the boxes set on the Isotope standards tab and on Run & reporting; every
# other on QC criteria
STANDARDS_BOXES = ("is_response", "is_vs_ccv", "surrogate_recovery", "surrogate_ccv")
RUN_BOXES = ("dilution_eis_floor", "worksheet_size")
# the boxes whose limit a project may set for its batches (Project Specs):
# while the method's own limit is empty, migrate stores no state for them,
# so a batch reads the seed of the profile it runs to (a project's floor
# applies) until a person sets the box
PROJECT_BOXES = ("dilution_eis_floor",)
# the sections a box's field is read from directly on the profile, not under
# instrument_verification (a box's group None is extraction_batch)
OWN_SECTIONS = ("dilution",)


def _rules():
    from senaite.pfas.qc import rules
    return rules


def _rules_of(box):
    r = box["rule"]
    if r is None:
        return ()
    return tuple(r) if isinstance(r, (list, tuple)) else (r,)


def owner(box):
    """The rule a box belongs to: its rule, the first where it seeds from
    two (the point deviations are Calibration r²'s)."""
    rules = _rules_of(box)
    return rules[0] if rules else None


def boxes_of(rule):
    """The boxes a rule's state is read from, in BOXES' order."""
    return [b for b in BOXES if owner(b) == rule]


def box_for_field(group, key):
    """The key of the box an instrument field (its section, its key) is
    judged in, or None."""
    for b in BOXES:
        if (group, key) in b["fields"]:
            return b["key"]
    return None


def either(states):
    """The state of what runs while any of `states` is on: Off when every
    one is Off; Evaluate when every one that is on is Evaluate; else
    Enforced (a failure holds while one that is on is Enforced)."""
    on = [s for s in states if s != "off"]
    if not on:
        return "off"
    return "evaluate" if all(s == "evaluate" for s in on) else "enforced"


def both(states):
    """The state of what runs only while every one of `states` is on: Off
    when any is Off; Evaluate when any is Evaluate; else Enforced."""
    states = list(states)
    if "off" in states:
        return "off"
    return "evaluate" if "evaluate" in states else "enforced"


# ── reading a box's value ──────────────────────────────────────────────────

def _iv(profile):
    iv = (profile or {}).get("instrument_verification")
    return iv if isinstance(iv, dict) else (profile or {})


def _section(profile, group):
    if group is None:
        s = (profile or {}).get("extraction_batch")
    elif group in OWN_SECTIONS:
        s = (profile or {}).get(group)
    else:
        s = _iv(profile).get(group)
    return s if isinstance(s, dict) else {}


def _unset(v):
    return v is None or (not isinstance(v, (int, float)) and u"{0}".format(v).strip() == u"")


def is_empty(profile, box):
    """Whether the box holds no limit: any end of a window unset. A box with
    no fields (a rule's own tile) is never empty."""
    if not box["fields"]:
        return False
    return any(_unset(_section(profile, g).get(k)) for g, k in box["fields"])


def applies(profile, box):
    """Whether the method judges this box at all: the ICV's own deviation
    only while the ICV is not judged by the CCV window."""
    if box["key"] == "icv":
        return (_section(profile, "icv").get("criteria") or "") != "ccv"
    return True


# ── the seed: the state before boxes ───────────────────────────────────────

def _legacy(profile, rule):
    """A rule's or row's state as stored before boxes (qc.rules.rule_state)."""
    return _rules().rule_state(profile, None, rule)


def _required(profile, box):
    g = box.get("group")
    if not g:
        return False
    eng = (profile or {}).get("engine")
    req = ((eng.get("required_keys") if isinstance(eng, dict) else None) or {}).get(g) or ()
    if not isinstance(req, (list, tuple)):
        req = [x.strip() for x in u"{0}".format(req).replace(";", ",").split(",")]
    keys = set(k for _g, k in box["fields"])
    if box["key"] == "cal_r2" and "r2_min" not in _section(profile, "calibration"):
        return True                       # never configured: refused whatever the list
    return bool(keys & set(req))


def _guidance(profile):
    eng = (profile or {}).get("engine")
    return isinstance(eng, dict) and eng.get("surrogate_guidance_only") in (True, 1, "1", "yes", "on", "true", "True")


def seed(profile, box):
    """The state `box` reads before one is stored (the module's rules)."""
    if not isinstance(box, dict):
        box = BOX[box]
    rules = _rules_of(box)
    if not rules:
        # judged whenever set: Enforced with a limit, Off without
        return "off" if is_empty(profile, box) else "enforced"
    rule = either([_legacy(profile, r) for r in rules])
    if rule == "off":
        return "off"
    if box["kind"] == OPTIONAL and is_empty(profile, box):
        if _required(profile, box):
            return "enforced"
        alt = ALTERNATES.get(box["key"])
        if alt and alt[1] and is_empty(profile, BOX[alt[0]]):
            # neither RT tolerance is set: the rule cannot run without one,
            # so Relative keeps the rule's state (Enforced still refuses)
            return rule
        return "off"
    if box["key"] in SURROGATE_BOXES and _guidance(profile):
        return "evaluate"
    return rule


def _is_low_level(tier):
    return isinstance(tier, dict) and tier.get("low_level_x_rl") not in (None, "")


def tier_seed(profile, code, tier):
    rules = _rules()
    key = rules.qc_row_key(code)
    typed = _legacy(profile, key) if key else "enforced"
    if _is_low_level(tier):
        return both([typed, _legacy(profile, rules.LOW_LEVEL_ROW)])
    return typed


# ── the state in force ─────────────────────────────────────────────────────

def stored(profile):
    s = (profile or {}).get(STORE_KEY)
    return s if isinstance(s, dict) else {}


def is_stored(profile, key):
    return stored(profile).get(key) in STATES


def box_state(profile, key):
    """The state of box `key`: as stored, else its seed."""
    st = stored(profile).get(key)
    if st in STATES:
        return st
    return seed(profile, BOX[key])


def tier_state(profile, code, tier):
    st = tier.get(TIER_KEY) if isinstance(tier, dict) else None
    if st in STATES:
        return st
    return tier_seed(profile, code, tier)


def tier_key(code, tier_or_name):
    name = tier_or_name.get("name") if isinstance(tier_or_name, dict) else tier_or_name
    return u"{0}{1}.{2}".format(TIER_PREFIX, code, name or u"")


def parse_tier_key(key):
    """(code, name) of a tier box's key, or None for any other box."""
    if not key.startswith(TIER_PREFIX):
        return None
    rest = key[len(TIER_PREFIX):]
    if "." not in rest:
        return None
    code, name = rest.split(".", 1)
    return code, name


def _entry(profile, code):
    e = ((profile or {}).get("qc_acceptance") or {}).get(code)
    return e if isinstance(e, dict) else None


def tiers(profile, code):
    e = _entry(profile, code)
    return [t for t in (e.get("tiers") or []) if isinstance(t, dict)] if e else []


def find_tier(profile, code, name):
    for t in tiers(profile, code):
        if (t.get("name") or u"") == name:
            return t
    return None


def removed(profile, code):
    """A QC type or blank the method does not hold, or holds Removed: its
    row Off as stored before boxes (its row's state, else its `enabled`
    flag; qc.rules.rule_state). Remove and Restore keep the row so."""
    if _entry(profile, code) is None:
        return True
    key = _rules().qc_row_key(code)
    if key:
        return _legacy(profile, key) == "off"
    return _entry(profile, code).get("enabled", True) is False


def rule_state(profile, rule):
    """A rule's state over its boxes (`either`): Off when every box is Off.
    A rule with no box reads its stored state."""
    boxes = boxes_of(rule)
    if not boxes:
        return _legacy(profile, rule)
    return either([box_state(profile, b["key"]) for b in boxes if applies(profile, b)] or ["off"])


def qc_type_state(profile, code):
    """A QC type's or blank's state over its tiers: Off when Removed or not
    held; a held type with no tiers reads its row as stored."""
    if removed(profile, code):
        return "off"
    ts = tiers(profile, code)
    if not ts:
        rules = _rules()
        key = rules.qc_row_key(code)
        return _legacy(profile, key) if key else "enforced"
    return either([tier_state(profile, code, t) for t in ts])


def rule_states(profile):
    """{rule key: state} for every rule of the library, over its boxes."""
    return dict((r["key"], rule_state(profile, r["key"])) for r in _rules().RULE_LIBRARY)


# ── empty limits ───────────────────────────────────────────────────────────

def empty_boxes(profile):
    """[(box, state)]: the boxes the method judges, in a state other than
    Off, that hold no limit and whose empty value means no limit (a box
    that uses another window, a rule's own tile and the surrogate windows,
    whose check says itself when none resolves, are left out)."""
    out = []
    for b in BOXES:
        if b["kind"] not in (NEEDED, OPTIONAL) or b["key"] == "worksheet_size":
            continue
        st = box_state(profile, b["key"])
        if st == "off" or not applies(profile, b) or not is_empty(profile, b):
            continue
        out.append((b, st))
    return out


def no_limit_words(box):
    """What a gap names: the box and where it is set."""
    tab = u"Isotope standards" if box["key"] in STANDARDS_BOXES else (
        u"Run & reporting" if box["key"] in RUN_BOXES else u"QC criteria")
    return u"{0} has no limit set. Set it on the method's {1} tab, or set the box Off.".format(box["label"], tab)


# ── writing ────────────────────────────────────────────────────────────────

def set_box(profile, key, state):
    """Store `state` on box `key` (a tier's key stores on that tier). True if
    stored; an unknown state, box or tier stores nothing."""
    if state not in STATES:
        return False
    parsed = parse_tier_key(key)
    if parsed is not None:
        t = find_tier(profile, parsed[0], parsed[1])
        if t is None:
            return False
        t[TIER_KEY] = state
        return True
    if key not in BOX:
        return False
    s = dict(stored(profile))
    s[key] = state
    profile[STORE_KEY] = s
    return True


def state_of(profile, key):
    """The state any box key reads, a tier's too; None for an unknown key."""
    parsed = parse_tier_key(key)
    if parsed is not None:
        t = find_tier(profile, parsed[0], parsed[1])
        return tier_state(profile, parsed[0], t) if t is not None else None
    return box_state(profile, key) if key in BOX else None


def encode_key(key):
    """A box key as a form name carries it: a tier's name may hold a colon,
    which Zope reads as a converter, so ":" and "%" are escaped."""
    return key.replace(u"%", u"%25").replace(u":", u"%3A")


def decode_key(name):
    return name.replace(u"%3A", u":").replace(u"%25", u"%")


def apply_posted(profile, form, tiers_only=False):
    """Store each posted `limitstate.<box>` that differs from what the box
    reads, so an untouched page writes nothing. True if anything changed.
    `tiers_only`: the tiers' boxes alone."""
    changed = False
    for name in sorted(k for k in (form or {}) if k.startswith(POST_PREFIX)):
        key, state = decode_key(name[len(POST_PREFIX):]), form.get(name)
        if tiers_only and parse_tier_key(key) is None:
            continue
        if state not in STATES or state_of(profile, key) in (None, state):
            continue
        changed = set_box(profile, key, state) or changed
    return changed


POST_PREFIX = "limitstate."


def set_type_presence(profile, code, on):
    """A QC type or blank Removed sets each tier Off; Restored, each tier
    that is Off comes back Enforced, as Restore always brought the type
    back. True if a tier changed."""
    changed = False
    for t in tiers(profile, code):
        st = tier_state(profile, code, t)
        want = st if on and st != "off" else ("enforced" if on else "off")
        if t.get(TIER_KEY) != want:
            t[TIER_KEY] = want
            changed = True
    return changed


def migrate(profile):
    """Write each box's and tier's seed where no state is stored (a project
    box whose limit is empty keeps reading its seed: PROJECT_BOXES). True if
    anything was written; idempotent; no old key is touched."""
    if not isinstance(profile, dict):
        return False
    s = dict(stored(profile))
    changed = False
    for b in BOXES:
        if b["key"] in PROJECT_BOXES and is_empty(profile, b):
            continue
        if s.get(b["key"]) not in STATES:
            s[b["key"]] = seed(profile, b)
            changed = True
    for code, entry in sorted(((profile.get("qc_acceptance") or {}).items())):
        if not isinstance(entry, dict):
            continue
        for t in entry.get("tiers") or []:
            if isinstance(t, dict) and t.get(TIER_KEY) not in STATES:
                t[TIER_KEY] = tier_seed(profile, code, t)
                changed = True
    if changed:
        profile[STORE_KEY] = s
    return changed
