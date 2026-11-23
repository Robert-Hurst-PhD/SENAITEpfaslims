# -*- coding: utf-8 -*-
"""What a method profile tab's own form carries besides its declared
sections: the check switches beside their limits, the QC-type switches, the
method's name and description, the analyte grids. Each is applied only when
the form carries it, so saving one tab never changes another tab's setting.

    apply_loose(profile, form, rule_keys) -> profile (changed in place)

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

from senaite.pfas.qc.rules import (LOW_LEVEL_ROW, STATES, is_profile_row_key, qc_row_key,
                                   rule_state, set_qc_row_state, set_row_state)

from senaite.pfas.config_forms import _enc, _text

SAMPLES_TOKEN = u"SAMPLES"          # the Run Builder's field-samples block

# The Calibration & CCV criteria groups, keyed by the group's first field:
# the flag notes a group carries (each rule's flag note is on its card's
# Flag tile). No group carries Required toggles: each limit box has its own
# state (limit_states). Which rules a group's limits belong to is the rule
# library's `editor`.
CAL_GROUP_PARTS = {
    u"f__calibration__r2_min": {"notes": None},
    u"f__confirmation__ion_ratio_tol_pct": {"notes": None},
    u"f__confirmation__single_transition_analytes": {"notes": None},
    u"f__ccv__recovery_min": {"notes": None},
    u"f__is_response__vs_ical_avg_min": {"notes": None},
}


def panel_switch_names(keyword, matrix):
    """(switch name, present marker) of the Analytes tab's panel switch for
    one analyte x matrix. Both parts are encoded as a section's row keys are:
    a keyword may carry a colon, which Zope reads as a type converter, and a
    matrix a space or a slash."""
    tail = u"%s.%s" % (_enc(keyword), _enc(matrix))
    return u"ami." + tail, u"ami_present." + tail


def _ticked(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return (u"%s" % (value or u"")).strip().lower() in (u"1", u"on", u"true", u"yes")


def _panel_switches(profile, form):
    """The panel switches the form carries (its present marker posted), for
    the method's own analytes and matrices only. An analyte is reported in a
    matrix unless stored False (absent means included), so a switch posted
    as the method already reads writes nothing; one that changes it is
    stored as it was set."""
    inclusion = profile.get("analyte_matrix_inclusion") or {}
    changed = {}
    for kw in profile.get("master_analyte_set") or []:
        for matrix in profile.get("supported_matrices") or []:
            name, marker = panel_switch_names(kw, matrix)
            if not form.get(marker):
                continue
            on = _ticked(form.get(name))
            if bool((inclusion.get(kw) or {}).get(matrix, True)) != on:
                changed.setdefault(kw, {})[matrix] = on
    if changed:
        inclusion = dict(inclusion)
        for kw, per_matrix in changed.items():
            row = dict(inclusion.get(kw) or {})
            row.update(per_matrix)
            inclusion[kw] = row
        profile["analyte_matrix_inclusion"] = inclusion


def posted_panel(profile, form):
    """A copy of `profile` with the analyte x matrix panel as the form sets
    it (the panel switches it carries); everything else as stored. A tab's
    sections are parsed against it, so the reporting limits read the rows of
    the matrices each analyte is reported in after the save: an RL typed for
    a cell reported in the same save is stored, and a matrix left out lists
    no RL row (its stored RL stays as it is, never shown or reported)."""
    out = dict(profile or {})
    _panel_switches(out, form or {})
    return out


def _qc_toggles(profile, offered, form):
    """The QC types the page offered, each set as its row's state was posted
    (`rulestate.qc_type.<CODE>` / `rulestate.blank.<CODE>`: enforced /
    evaluate / off); a type whose state is not posted is left as it is. A
    state is stored only where it differs from what the row reads, and no
    `qc_acceptance` entry is created (rules.set_qc_row_state). A type whose
    row reads Off carries no spike levels."""
    for key in offered:
        row = qc_row_key(key)
        state = form.get("rulestate." + row) if row else None
        if state in STATES:
            set_qc_row_state(profile, key, state)
    qca = profile.get("qc_acceptance") or {}
    # the row's state, as the worker reads it (an entry with no flag runs)
    disabled = set(k for k in qca if qc_row_key(k) and rule_state(profile, None, qc_row_key(k)) == "off")
    for _matrix, per_qc in (profile.get("spike_levels") or {}).items():
        if isinstance(per_qc, dict):
            for qc in list(per_qc):
                if qc in disabled:
                    del per_qc[qc]


def apply_loose(profile, form, rule_keys, current=None):
    """`current`: {rule key: on} as the method reads now (stored over the
    default); a switch the method never stored, posted at that state, stays
    unstored, so an untouched tab writes nothing. A rule is posted either as
    its state (`rulestate.<key>`: enforced / evaluate / off) or, by the older
    form, as a switch (`ruletoggle.<key>`: enforced / off); `rule_toggles`
    follows `rule_states` either way."""
    form = form or {}
    current = current or {}
    toggles = dict(profile.get("rule_toggles") or {})
    held = profile.get("rule_states") or {}
    if "rule_states" in profile and any(not is_profile_row_key(k) for k in held):
        states = dict(held)
    else:
        # no rule's state held yet (a QC type's, a blank's or the Low-level
        # recoveries row is no rule):
        # the rules read their switches
        states = dict((k, "enforced" if v else "off") for k, v in toggles.items())
        states.update(held)
    changed = False
    for k in [k for k in rule_keys or [] if form.get("ruletoggle_present." + k)]:
        on = bool(form.get("ruletoggle." + k))
        if k in toggles or on != current.get(k):
            changed = changed or toggles.get(k) != on
            toggles[k] = on
            # a rule in the state Evaluate is on: a switch left on keeps it
            if k not in states or (states[k] != "off") != on:
                states[k] = "enforced" if on else "off"
                changed = True
    for k in rule_keys or []:
        state = form.get("rulestate." + k)
        if state not in STATES:
            continue
        was = ("enforced" if current[k] else "off") if k in current else None
        if k in states or k in toggles or state != was:
            changed = changed or states.get(k) != state or toggles.get(k) != (state != "off")
            states[k] = state
            toggles[k] = state != "off"
    if changed:
        profile["rule_toggles"] = toggles
        profile["rule_states"] = states
    # each limit box's state (limitstate.<box>, one input per box), stored
    # where it differs from what the box reads; Required is no longer
    # posted: an Enforced box with no limit refuses the run
    from senaite.pfas import limit_states
    limit_states.apply_posted(profile, form)
    # the QC criteria tab's QC-type and blank rows: only the form that drew them names them
    offered = [k for k in (form.get("qc_offered") or "").split(",") if k]
    if offered:
        _qc_toggles(profile, offered, form)
    # the Low-level recoveries row, stored where it differs from what it reads
    set_row_state(profile, LOW_LEVEL_ROW, form.get("rulestate." + LOW_LEVEL_ROW))
    for key in ("display_name", "description"):
        if key in form:
            value = _text(form.get(key))
            if value != (profile.get(key) or u""):
                profile[key] = value
    # the run template, from the Run Template tab: the field samples
    # are never optional, the bracketing check is the CCV unless named
    seq = [c.strip() for c in _text(form.get("sequence_codes")).split(",") if c.strip()]
    drawn = [c.strip() for c in _text(form.get("run_template_drawn")).split(",") if c.strip()]
    # a method on the default template, posted as the page drew it
    untouched = seq == drawn and "run_template" not in profile
    if form.get("run_template_present") and seq and not untouched:   # an empty list is a page that did not draw
        if SAMPLES_TOKEN not in seq:
            seq.append(SAMPLES_TOKEN)
        profile["run_template"] = {"sequence": seq,
                                   "bracket_qc": _text(form.get("bracket_qc")) or u"CCV"}
    # the extraction stages, from Lab Workflow's own form: the caller turns
    # them into stages (method_profiles._stages_from_form)
    raw = _text(form.get("extraction_stages_json"))
    if raw:
        profile["extraction_stages_json_raw"] = json.loads(raw)
    _panel_switches(profile, form)
    # a note left from the retired Per-Analyte table, discarded by analyte
    # once it has been moved by hand
    discard = _text(form.get("discard_note"))
    if discard:
        rows = [r for r in profile.get("per_analyte") or []
                if not (isinstance(r, dict) and r.get("analyte") == discard)]
        if rows:
            profile["per_analyte"] = rows
        else:
            profile.pop("per_analyte", None)
    return profile


# the tables whose rows are keyed by a tier's name (its flag)
TIER_KEYED_SECTIONS = ("flags_qc",)


def carry_renamed_tiers(profile, form, parsed, env=None):
    """What a tab posts under a tier's stored name, applied before its
    sections: a tier renamed in the same save then carries the state and
    flag set for it (each is posted under the name the page drew; applied
    after the rename, it would find no tier). `parsed`: [(section,
    updates)] as the save parsed them. Returns the profile."""
    from senaite.pfas import config_forms as cf
    from senaite.pfas import limit_states
    limit_states.apply_posted(profile, form or {}, tiers_only=True)
    for section, updates in parsed or []:
        if section.id in TIER_KEYED_SECTIONS:
            profile = cf.apply(section, profile, updates, env)
    return profile

