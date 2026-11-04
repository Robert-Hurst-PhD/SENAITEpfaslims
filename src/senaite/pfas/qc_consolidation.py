# -*- coding: utf-8 -*-
"""How a method profile's QC rules are kept as it is saved. Pure; Python 2.7 and 3.

  sync_rule_switches(profile)   the rule states, then the on/off switches
                                derived from them
  sync_qc_enabled(profile)      each QC type's `enabled` flag from its row
  tiers_own_matrices / patch_tiers_own_matrices
                                each tier lists its own matrices (a project's
                                patch too)
  as_saved(profile)             all of the above, as a save stores it
  toggle_changes_as_states / history_changes
                                a history entry's changes as the profile
                                holds them now, for a revert
"""
from __future__ import absolute_import, unicode_literals

import logging

from senaite.pfas.qc import rules

logger = logging.getLogger("senaite.pfas.qc_consolidation")


def rule_states_from_toggles(profile):
    """A rule has one of three states (Enforced / Evaluate / Off). Where a
    profile holds only the on/off `rule_toggles`, every switch becomes a
    state (on = enforced, off = off), keys the library no longer knows
    included. True if changed. Idempotent: does nothing once `rule_states`
    holds a rule's state (a QC type's or blank's row is no rule) or while
    there are no switches to read."""
    held = profile.get("rule_states", {})
    if not isinstance(held, dict) or not isinstance(profile.get("rule_toggles"), dict):
        return False
    if any(not rules.is_profile_row_key(k) for k in held):
        return False
    states = dict((k, "enforced" if v else "off") for k, v in profile["rule_toggles"].items())
    states.update(held)
    if held == states:
        return False
    profile["rule_states"] = states
    return True


def toggles_from_rule_states(profile):
    """The on/off `rule_toggles` follow `rule_states` (on = enforced or
    evaluate), so a reader of the switches sees the same rules judged. A
    switch with no state is left as stored. A QC type's or blank's row is
    no rule switch (its type's `enabled` flag is). True if changed."""
    states = profile.get("rule_states")
    if not isinstance(states, dict):
        return False
    toggles = dict(profile.get("rule_toggles") or {})
    derived = dict((k, v != "off") for k, v in states.items() if not rules.is_profile_row_key(k))
    if all(toggles.get(k) is d for k, d in derived.items()) and "rule_toggles" in profile:
        return False
    toggles.update(derived)
    profile["rule_toggles"] = toggles
    return True


def sync_rule_switches(profile):
    """The rule states and switches as a save stores them: the states
    migrated from the switches where the profile has none, then the switches
    derived from the states. Returns the profile."""
    rule_states_from_toggles(profile)
    toggles_from_rule_states(profile)
    return profile


def qc_states_from_enabled(profile):
    """A QC type's run row and a blank's row hold a state like any rule:
    where a type has its `enabled` flag but no state, the flag becomes one
    (on = enforced, off = off). A type with no row (an instrument check, the
    surrogates) gets none. True if changed; idempotent."""
    qca = profile.get("qc_acceptance")
    if not isinstance(qca, dict):
        return False
    states = dict(profile.get("rule_states") or {})
    changed = False
    for code, entry in sorted(qca.items()):
        key = rules.qc_row_key(code)
        if key is None or not isinstance(entry, dict) or "enabled" not in entry:
            continue
        if states.get(key) in rules.STATES:
            continue
        states[key] = "enforced" if entry["enabled"] else "off"
        changed = True
    if changed:
        profile["rule_states"] = states
    return changed


def sync_qc_enabled(profile):
    """Each QC type's `enabled` flag follows its row's state (on unless
    Off), for the readers of the flag. A type the method does not hold is
    not created. True if changed."""
    qca = profile.get("qc_acceptance")
    states = profile.get("rule_states")
    if not isinstance(qca, dict) or not isinstance(states, dict):
        return False
    changed = False
    for key, state in states.items():
        code = rules.qc_row_code(key)
        entry = qca.get(code) if code is not None else None
        if not isinstance(entry, dict) or state not in rules.STATES:
            continue
        on = state != "off"
        if entry.get("enabled") is not on:
            entry["enabled"] = on
            changed = True
    return changed


def holding_none_to_cells(profile):
    """No holding time is said per matrix: the retired method-wide switch
    `sample_holding_none`, when on, sets every supported matrix's sample
    holding to "none" (whatever days it held: the switch overrode them),
    then the key goes, on or off. True if changed; idempotent."""
    if "sample_holding_none" not in profile:
        return False
    if profile.pop("sample_holding_none"):
        days = profile.get("holding_times")
        days = dict(days) if isinstance(days, dict) else {}
        for m in profile.get("supported_matrices") or []:
            days[m] = u"none"
        profile["holding_times"] = days
    return True


PENDING = u"pending"


def tiers_own_matrices(profile, projects_migrated=False):
    """Each tier lists its own matrices: every "Tier 1 matrices only" tier
    (scope "tight"), of every QC type, becomes a "listed" tier with its own
    copy of the one global Tier 1 list (top-level `tight_matrices`) where it
    lists none yet. A tight tier with no global list lists none: it applied
    nowhere, and still does. The global list goes only once the projects'
    patches have taken their copy (`projects_migrated`,
    project_specs.migrate_tier_lists); until then it is kept and the step
    says PENDING. True if changed; idempotent."""
    has_list = "tight_matrices" in profile
    shared = list(profile.get("tight_matrices") or [])
    changed = False
    for entry in (profile.get("qc_acceptance") or {}).values():
        for t in (entry.get("tiers") or []) if isinstance(entry, dict) else []:
            if isinstance(t, dict) and t.get("matrix_scope") == "tight":
                t["matrix_scope"] = "listed"
                if "matrices" not in t:
                    t["matrices"] = list(shared)
                changed = True
    if has_list and not projects_migrated:
        return PENDING                         # the list stays: a project still needs it
    if has_list:
        profile.pop("tight_matrices")
        changed = True
    return changed


def patch_tiers_own_matrices(method_specs, shared):
    """A project's patches for one method ({scope: {section: patch}}),
    migrated: every tier a patch adds, or whose cells it
    changes, with scope "tight" becomes "listed". With the method's one
    Tier 1 list `shared` (before the method's list goes, tiers_own_matrices)
    each takes its own copy where it lists none, so a project's tier keeps
    the matrices it was judged in. With none left (None): a changed tier
    keeps the method tier's own list (nothing written: the patch applies
    onto it), an added one lists none. In place; True if changed; idempotent."""
    changed = False
    for patches in (method_specs or {}).values():
        for patch in (patches or {}).values() if isinstance(patches, dict) else []:
            if not isinstance(patch, dict):
                continue
            rows = [(r, True) for r in patch.get("added") or []]
            rows += [(r, False) for r in (patch.get("changed") or {}).values()]
            for row, added in rows:
                if isinstance(row, dict) and row.get("matrix_scope") == "tight":
                    row["matrix_scope"] = "listed"
                    if row.get("matrices") is None and (shared is not None or added):
                        row["matrices"] = list(shared or [])
                    changed = True
    return changed


# The migrations every save runs, in order: (name, step(profile) -> changed);
# the tiers step also takes whether the projects' patches are migrated.
PASS2_STEPS = [
    ("qc_states", qc_states_from_enabled),
    ("holding_none", holding_none_to_cells),
]


def changed_by(names):
    """Did migrate_pass2 change what a save must keep? A pending tiers step
    does not: it runs again on the next save or start."""
    return any(not n.endswith(u"(%s)" % PENDING) for n in names)


def migrate_pass2(profile, projects_migrated=False):
    """Run every migration in PASS2_STEPS, then tiers_own_matrices, on
    `profile` (in place); the names of those that changed it, and
    "tiers_own_matrices (pending)" while the global Tier 1 list is kept for
    the projects (`projects_migrated` False: none could be migrated here).
    Idempotent: a second run returns [] (or the same pending name)."""
    out = [name for name, step in PASS2_STEPS if step(profile)]
    tiers = tiers_own_matrices(profile, projects_migrated)
    if tiers == PENDING:
        out.append(u"tiers_own_matrices (%s)" % PENDING)
    elif tiers:
        out.append(u"tiers_own_matrices")
    return out


def as_saved(profile, projects_migrated=False):
    """The profile as a save stores it: the rule states and switches
    (sync_rule_switches), the migrations of migrate_pass2 (the global Tier
    1 list kept unless the projects' patches are migrated:
    project_specs.as_saved_with_projects), then each QC type's `enabled`
    flag from its row's state. Returns the profile."""
    sync_rule_switches(profile)
    migrate_pass2(profile, projects_migrated)
    sync_qc_enabled(profile)
    return profile


NOT_A_STATE = (u"Not reverted: this change to the rule switches cannot be put "
               u"back as a rule state. Set the rule's state in the method "
               u"profile instead.")


def toggle_changes_as_states(current, changes):
    """A history entry's changes, with each rule switch it recorded before the
    rule states existed (`rule_toggles/<rule>`) put as that rule's state
    (`rule_states/<rule>`: on = enforced, off = off). A save derives the
    switches from the states, so reverting the switch alone would store
    nothing. Returns (changes, refusal); the refusal is empty unless a
    switch change cannot be a state (a switch added or removed, or the whole
    set). A profile without states is left as recorded; an entry that also
    records the rule's state reverts the state alone. A QC type's `enabled`
    flag (`qc_acceptance/<type>/enabled`, on / off) is put as its row's state
    the same way, since a save derives the flag from the state."""
    changes = list(changes or [])
    if not isinstance((current or {}).get("rule_states"), dict):
        return changes, u""
    stated = set(ch["path"][1] for ch in changes
                 if len(ch.get("path") or ()) == 2 and ch["path"][0] == "rule_states")
    out = []
    for ch in changes:
        path = list(ch.get("path") or ())
        row = (rules.qc_row_key(path[1]) if len(path) == 3 and path[0] == "qc_acceptance"
               and path[2] == "enabled" else None)
        if row is not None:
            before, after = ch.get("before"), ch.get("after")
            if row in stated:
                continue
            if isinstance(before, bool) and isinstance(after, bool):
                ch = {"path": ["rule_states", row],
                      "before": "enforced" if before else "off",
                      "after": "enforced" if after else "off"}
            out.append(ch)
            continue
        if not path or path[0] != "rule_toggles":
            out.append(ch)
            continue
        if len(path) == 2 and path[1] in stated:
            continue
        before, after = ch.get("before"), ch.get("after")
        if len(path) != 2 or not isinstance(before, bool) or not isinstance(after, bool):
            return None, NOT_A_STATE
        out.append({"path": ["rule_states", path[1]],
                    "before": "enforced" if before else "off",
                    "after": "enforced" if after else "off"})
    return out, u""


NOT_A_TIER_LIST = (u"Not reverted: this change is to the one Tier 1 matrix list, which "
                   u"each tier now holds as its own. Set the matrices a tier lists on QC "
                   u"criteria, under Who each tier applies to.")


def history_changes(current, changes):
    """A history entry's changes as the stored model reads them, or the
    reason they cannot be reverted: (changes, refusal). A change to the one
    top-level Tier 1 list (gone: each tier lists its own) is refused; a
    tier's matrix scope recorded as "tight" reads as "listed"; then the rule
    switches as states (toggle_changes_as_states)."""
    out = []
    for ch in list(changes or []):
        path = list(ch.get("path") or ())
        if path and path[0] == "tight_matrices":
            return None, NOT_A_TIER_LIST
        if path and path[-1] == "matrix_scope":
            ch = dict(ch, **dict((k, u"listed") for k in ("before", "after") if ch.get(k) == "tight"))
        out.append(ch)
    return toggle_changes_as_states(current, out)


