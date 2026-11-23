# -*- coding: utf-8 -*-
"""Corrections to a finalised extraction record: amend one fact, send the
batch back to an earlier step, or withhold members for re-extraction.

The finalised record (the members, the extraction table, the session) is
never edited: what the bench signed stays as signed. A correction is an
entry in one append-only log, a worksheet annotation (KEY), kept beside it
with the shape the injection identity correction uses
(injection_identity): who, when, a required reason, the sign-offs it
cleared, and a confirmation by a different person at verification.

    {"log": [{"id": "EA-1", "action": "amend", "member": <member id>,
              "field": "level", "from": "Mid", "to": "High",
              "also": {"amount": ["80", "160"]}, "name": [old, new],
              "reason", "by", "at"[, "before"][, "cleared"][, "after_release"]},
             {"id": "EA-2", "action": "amend", "sample": <sample id>,
              "field": "amount", "from", "to", ...},
             {"id": "EA-3", "action": "revert", "reverts": "EA-1", "reason", "by", "at"},
             {"id": "EA-4", "action": "reextract", "what": "surrogate",
              "scope": "sample", "members": [ids], "sample_left": true,
              "reason", "by", "at"},
             {"id": "EA-5", "action": "send_back", "to": "stages",
              "stage": "3", "from_state", "reason", "by", "at"},
             {"id": "EA-6", "action": "confirm", "confirms": "EA-1", "by",
              "name", "at"},
             {"id": "EA-7", "action": "link", "links": "EA-4",
              "ws": "WS-371", "by", "at"}]}

What everything downstream reads is the record in force: the stored
members with the amendments in force applied (members_in_force), and the
extraction table's rows likewise (samples_in_force). An amendment is in
force while it is not undone and the stored value is still the one it
corrected: a fact recorded again after a send back closes it.

The rules decided with the lab:
  - an amendment offers only what the method defines: a QC type, a spike
    level of an LFB or LCS, a parent or a sample of the batch, a spike lot;
    never a typed spike amount;
  - the wrong amount added is always a re-extraction, never a
    recalculation: an LFSM or LFSMD spiked other than recorded is
    re-extracted, not amended;
  - a sample amount or final volume copied wrongly is amended (nothing was
    added wrongly; the reason names the primary record);
  - a renamed member keeps its issued name as an alias, so a file already
    acquired still matches;
  - who: anyone the extraction page lets record (Bench, Analyst, Lab
    Manager), never an automated account; a send back while the worksheet
    is open by an Analyst or a Lab Manager, once submitted by a Lab Manager
    only; after release only a Lab Manager amends, and that amendment is
    signed as the record's next revision;
  - each correction is confirmed at verification by a Lab Manager with the
    reviewer sign right who did not make it; Verify waits until each is.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json

import six

from senaite.pfas import injection_identity as ii

KEY = "senaite.pfas.extraction_amendments"

AMEND, REVERT, CONFIRM = "amend", "revert", "confirm"
SEND_BACK, REEXTRACT, LINK = "send_back", "reextract", "link"
# the entries a verifier confirms
CONFIRMED_KINDS = (AMEND, SEND_BACK, REEXTRACT)

# a member's facts that can be amended
ROLE, LEVEL, PARENT, SAMPLE, SPIKE_LOT = "role", "level", "parent", "sample", "spike_lot"
MEMBER_FIELDS = (ROLE, LEVEL, PARENT, SAMPLE, SPIKE_LOT)
# an extraction table row's facts (a sample's amount and final volume)
AMOUNT, FINAL_VOLUME = "amount", "final_volume_ml"
SAMPLE_FIELDS = (AMOUNT, FINAL_VOLUME)
FIELD_LABELS = {ROLE: "QC type", LEVEL: "Level", PARENT: "Parent", SAMPLE: "Sample",
                SPIKE_LOT: "Spike lot", AMOUNT: "Amount", FINAL_VOLUME: "Final volume"}

# the levels an amendment may change: a fortified blank's. A sample's spike
# given at another level than recorded is the wrong amount added.
LEVEL_ROLES = ("LFB", "LCS")
REEXTRACT_LEVEL_ROLES = ("LFSM", "LFSMD")
PARENT_ROLES = ("LFSM", "LFSMD", "Dup", "MxB")
SPIKE_LOT_ROLES = ("LFB", "LCS", "LFSM")

# what went wrong, and how much is re-extracted
WHAT = (("surrogate", "Surrogate"), ("spike", "Spike"), ("amount", "Sample amount"), ("other", "Other"))
SCOPES = (("sample", "This sample"), ("sample_qc", "Sample and its QC"), ("batch", "Whole batch"))
# where a send back returns to
TARGETS = (("members", "Members"), ("stages", "Stages"), ("run", "Run build"), ("import", "Data import"))

OPEN_STATES = ("open",)
SUBMITTED = "to_be_verified"
RELEASED_STATES = ("verified", "published")
REJECTED = "rejected"

NO_REASON = "A reason is required. Nothing was saved."
NOT_ALLOWED = "Only a person who records the extraction corrects it."
AUTOMATED = "An automated account does not correct an extraction record."
NOT_FINALISED = ("The extraction is not finalised: its members are edited on the extraction "
                 "worksheet. Nothing was saved.")
CLOSED = "The worksheet is {0}: send it back first. Nothing was saved."
REJECTED_CLOSED = "The worksheet is rejected: its record is not corrected. Nothing was saved."
RELEASED_MANAGER = ("The worksheet is {0}: only a Lab Manager amends a released record, "
                    "signed as its next revision. Nothing was saved.")
NO_MEMBER = "{0} is not a member of this extraction batch."
NO_SAMPLE_ROW = "{0} is not a sample of this extraction batch."
NOT_FIELD = "{0} is not amended here."
FIELD_ROLE = "The {0} of {1}, a {2}, is not amended."
LFSM_LEVEL = ("{0} was spiked other than recorded: that is the wrong amount added, so it is "
              "re-extracted. Use Needs re-extraction.")
NOT_OFFERED = "{0} is not one of the values this method allows here."
SAME = "{0} is already {1}."
WITHHELD = "{0} is withheld for re-extraction: it is not amended."
NOT_A_NUMBER = "{0} must be a number greater than zero."
NOTHING_TO_UNDO = "{0} is not a correction in force."
UNDO_CONFIRMED = ("{0} is confirmed: it is not undone. Send the batch back to record "
                  "the fact again.")
# a whole batch re-extracted is final: every analysis leaves the worksheet
NO_WHAT = "Choose what went wrong."
NO_SCOPE = "Choose what is re-extracted."
NOTHING_WITHHELD = "Nothing to re-extract: no member is named."
ALREADY_WITHHELD = "{0} is already withheld for re-extraction."
NO_TARGET = "Choose where the batch goes back to."
NO_STAGE = "Choose the stage the extraction is reopened from."
SEND_BACK_MANAGER = "The worksheet is submitted: only a Lab Manager sends it back."
SEND_BACK_RELEASED = "The worksheet is {0}: it is not sent back."
SEND_BACK_NOT_ALLOWED = "Only an Analyst or a Lab Manager sends a batch back."
NOT_VERIFIER = "Only a Lab Manager confirms an extraction correction."
CONFIRM_STATE = "A correction is confirmed at verification, once the worksheet is submitted."
OWN = "{0} was made by you: a different person confirms it."
NO_SIGN_RIGHT = "{0} has no reviewer sign right in People & Roles, so does not confirm a correction."
ALREADY = "{0} is already confirmed."
NOT_TO_CONFIRM = "{0} is not a correction waiting to be confirmed."
UNCONFIRMED = ("Confirm each extraction correction before verifying, or send the batch back: "
               "not confirmed: {0}.")
NOT_WITHHELD = "{0} is not withheld for re-extraction in this batch."

STATE_WORDS = dict(ii.STATE_WORDS)


def _text(value):
    return ii._text(value)


# ── the record ──────────────────────────────────────────────────────────────

def empty():
    return {"log": []}


def load(raw):
    """The record from its stored JSON (or a dict); empty when unreadable."""
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            data = {}
    log = data.get("log") if isinstance(data, dict) else None
    return {"log": [dict(e) for e in log if isinstance(e, dict)] if isinstance(log, list) else []}


def dump(state):
    return json.dumps(load(state), sort_keys=True)


def _next_id(state):
    n = 0
    for e in load(state)["log"]:
        try:
            n = max(n, int((e.get("id") or "").split("-")[-1]))
        except ValueError:
            continue
    return "EA-%d" % (n + 1)


def _by_id(state):
    return dict((e.get("id"), e) for e in load(state)["log"])


def _reverted(state):
    return set(e.get("reverts") for e in load(state)["log"] if e.get("action") == REVERT)


def _fact(value):
    return _text(value if value is not None else "")


def entries_in_force(state, kinds=CONFIRMED_KINDS):
    """The amend, send back and re-extract entries not undone, oldest first."""
    gone = _reverted(state)
    return [e for e in load(state)["log"] if e.get("action") in kinds and e.get("id") not in gone]


# ── the record in force ─────────────────────────────────────────────────────

def _stale(entry, stored):
    """An amendment whose stored value is no longer the one it corrected
    (recorded again after a send back) is closed."""
    return _fact(stored) != _fact(entry.get("from"))


def amendments_in_force(state, members=(), rows=()):
    """{(target, field): the amend entry in force}: the latest amendment of
    each member's or sample row's fact, not undone, whose stored value is
    still the one it corrected."""
    by_member = dict((m.get("id"), m) for m in members or ())
    by_row = dict((r.get("sample_id"), r) for r in rows or ())
    out = {}
    for e in entries_in_force(state, (AMEND,)):
        field = e.get("field")
        if e.get("member"):
            m = by_member.get(e["member"])
            stored = _member_value(m, field) if m is not None else None
            key = (e["member"], field)
        else:
            r = by_row.get(e.get("sample"))
            stored = r.get(field) if r is not None else None
            key = ("sample:" + _text(e.get("sample")), field)
        # every amendment records the stored value it corrected, so a later
        # one of the same fact wins while the stored value is unchanged
        if stored is not None and not _stale(e, stored):
            out[key] = e
    return out


def _member_value(m, field):
    if field == SAMPLE:
        return m.get("sample_id") or ""
    return m.get(field) or ""


def withheld(state, members=()):
    """{member id: the re-extract entry withholding it}."""
    ids = set(m.get("id") for m in members or ())
    out = {}
    for e in entries_in_force(state, (REEXTRACT,)):
        for mid in e.get("members") or ():
            if not ids or mid in ids:
                out.setdefault(mid, e)
    return out


def links(state):
    """{re-extract entry id: the worksheet its members were re-extracted in}."""
    return dict((e.get("links"), e.get("ws")) for e in load(state)["log"] if e.get("action") == LINK)


def members_in_force(members, state):
    """The members as everything downstream reads them: each amended fact
    replaced by its amendment in force. A member gains "amended" (the entry
    ids), "aliases" (its issued names an amendment renamed) and "withheld"
    (the re-extract entry id), where it has them."""
    members = [dict(m) for m in members or ()]
    forced = amendments_in_force(state, members)
    by_id = dict((m.get("id"), m) for m in members)
    original = dict((m.get("id"), dict(m)) for m in members)
    for (mid, field), e in sorted(forced.items(), key=lambda kv: kv[1].get("id") or ""):
        m = by_id[mid]
        if field == SAMPLE:
            other = by_id.get(e.get("swap_with"))
            if other is not None:
                a, b = original[mid], original[other.get("id")]
                for k in ("sample_uid", "sample_id", "client_sid", "matrix"):
                    m[k], other[k] = b.get(k), a.get(k)
                other.setdefault("amended", []).append(e.get("id"))
        else:
            m[field] = e.get("to")
            for k, pair in (e.get("also") or {}).items():
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    m[k] = pair[1]
        name = e.get("name")
        if isinstance(name, (list, tuple)) and len(name) == 2 and name[1] and name[1] != m.get("injection"):
            m.setdefault("aliases", []).append(m.get("injection"))
            m["injection"] = name[1]
        m.setdefault("amended", []).append(e.get("id"))
    held = withheld(state, members)
    for mid, e in held.items():
        if mid in by_id:
            by_id[mid]["withheld"] = e.get("id")
    return members


def samples_in_force(rows, state):
    """The extraction table's sample rows with their amendments in force."""
    rows = [dict(r) for r in rows or ()]
    forced = amendments_in_force(state, (), rows)
    by_sid = dict((r.get("sample_id"), r) for r in rows)
    for (key, field), e in forced.items():
        r = by_sid[key[len("sample:"):]]
        r[field] = e.get("to")
        r.setdefault("amended", []).append(e.get("id"))
    return rows


def aliases(members):
    """{issued name: name in force} for every renamed member in force."""
    out = {}
    for m in members or ():
        for old in m.get("aliases") or ():
            if old and old != m.get("injection"):
                out[old] = m.get("injection")
    return out


def renamed(name, role, level, new_role, new_level):
    """An issued injection name with its QC part ("LFB-M") replaced by the
    amended role and level; a name without that part (never issued) is
    kept."""
    from senaite.pfas import injection_names as nm
    name = _text(name)
    old = nm.role_part(role, level)
    new = nm.role_part(new_role, new_level)
    token = "_%s_" % old
    if not old:
        return name
    padded = ("_%s_" % name).replace(token, "_%s_" % new, 1)
    return padded[1:-1]


# ── refusals shared by every correction ─────────────────────────────────────

def actor_refusal(can_act, actor_kind):
    if actor_kind == "automated":
        return AUTOMATED
    if not can_act:
        return NOT_ALLOWED
    return None


def state_refusal(ws_state, is_manager=False):
    """Why an amendment or a re-extraction is refused in this worksheet
    state: submitted (send it back first), rejected; released unless a Lab
    Manager amends it as the record's next revision."""
    if ws_state == REJECTED:
        return REJECTED_CLOSED
    if ws_state == SUBMITTED:
        return CLOSED.format(STATE_WORDS.get(ws_state, ws_state))
    if ws_state in RELEASED_STATES and not is_manager:
        return RELEASED_MANAGER.format(STATE_WORDS.get(ws_state, ws_state))
    return None


# ── amend ───────────────────────────────────────────────────────────────────

def offered(field, member, members, profile_levels=(), qc_types=(), spike_lots=()):
    """The values an amendment of `field` on `member` may take: the
    method's QC types, the method's levels for a fortified blank, the
    batch's samples for a parent or a vial's sample, the spike lots usable."""
    member = member or {}
    role = member.get("role") or ""
    if field == ROLE:
        return [r for r in qc_types if r != role] if role != "Sample" else []
    if field == LEVEL:
        return [l for l in profile_levels] if role in LEVEL_ROLES else []
    if field == PARENT:
        return [m.get("id") for m in members or () if m.get("role") == "Sample"] if role in PARENT_ROLES else []
    if field == SAMPLE:
        return [m.get("id") for m in members or ()
                if m.get("role") == "Sample" and m.get("id") != member.get("id")] if role == "Sample" else []
    if field == SPIKE_LOT:
        return list(spike_lots) if role in SPIKE_LOT_ROLES else []
    return []


def amend(state, members, member_id, field, to, reason, who, when, ws_state, can_act,
          actor_kind, finalised, offered_values, is_manager=False, level_amounts=None,
          before=None, name=""):
    """(problem, state, entry): one fact of a finalised member amended.
    `offered_values` is what offered() gives; `level_amounts` maps a level
    to its amount in the method ({"High": "160"}), which a member with a
    recorded amount takes with its level (a recorded amount is what the
    expected value is worked from). `before` is what the stored run judged,
    kept to show before and after."""
    state = load(state)
    reason, who = _text(reason), _text(who)
    members = list(members or ())
    current = members_in_force(members, state)
    m = dict((x.get("id"), x) for x in current).get(_text(member_id))
    problem = actor_refusal(can_act, actor_kind)
    if problem is None and not finalised:
        problem = NOT_FINALISED
    if problem is None:
        problem = state_refusal(ws_state, is_manager)
    if problem is None and not reason:
        problem = NO_REASON
    if problem is None and m is None:
        problem = NO_MEMBER.format(_text(member_id) or "The member")
    if problem is None and field not in MEMBER_FIELDS:
        problem = NOT_FIELD.format(field or "That")
    if problem is None and m.get("withheld"):
        problem = WITHHELD.format(m.get("injection") or m.get("id"))
    if problem is None and field == LEVEL and m.get("role") in REEXTRACT_LEVEL_ROLES:
        problem = LFSM_LEVEL.format(m.get("injection") or m.get("id"))
    to = _text(to)
    if problem is None and not offered_values:
        problem = FIELD_ROLE.format(FIELD_LABELS.get(field, field).lower(),
                                    m.get("injection") or m.get("id"), m.get("role"))
    if problem is None and to not in [_text(v) for v in offered_values]:
        problem = NOT_OFFERED.format(to or "That")
    stored_m = dict((x.get("id"), x) for x in members).get(m.get("id")) if m else None
    now = _member_value(m, field) if m else ""
    if problem is None and _fact(now) == to:
        problem = SAME.format(FIELD_LABELS.get(field, field), to)
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": AMEND, "member": m.get("id"), "field": field,
             "from": _fact(_member_value(stored_m, field)), "to": to, "reason": reason,
             "by": who, "name_by": _text(name) or who, "at": _text(when)}
    if field == LEVEL and _fact(m.get("amount")) and level_amounts and to in level_amounts:
        entry["also"] = {"amount": [_fact(m.get("amount")), _fact(level_amounts[to])]}
    if field == SAMPLE:
        entry["swap_with"] = to
        other = dict((x.get("id"), x) for x in current).get(to) or {}
        entry["to"] = _fact(other.get("sample_id"))
    if field in (ROLE, LEVEL) and m.get("named"):
        new_role = to if field == ROLE else m.get("role")
        new_level = to if field == LEVEL else m.get("level")
        new = renamed(m.get("injection"), m.get("role"), m.get("level"), new_role, new_level)
        if new != m.get("injection"):
            entry["name"] = [m.get("injection"), new]
    if ws_state in RELEASED_STATES:
        entry["after_release"] = True
    if before:
        entry["before"] = before
    state["log"].append(entry)
    return None, state, entry


def amend_sample(state, rows, sample_id, field, to, reason, who, when, ws_state, can_act,
                 actor_kind, finalised, is_manager=False, name=""):
    """(problem, state, entry): a sample's amount or final volume copied
    wrongly, amended to the value on the primary record (named in the
    reason). Nothing added wrongly is amended here: that is re-extracted."""
    state = load(state)
    reason, who, to = _text(reason), _text(who), _text(to)
    row = dict((r.get("sample_id"), r) for r in rows or ()).get(_text(sample_id))
    problem = actor_refusal(can_act, actor_kind)
    if problem is None and not finalised:
        problem = NOT_FINALISED
    if problem is None:
        problem = state_refusal(ws_state, is_manager)
    if problem is None and not reason:
        problem = NO_REASON
    if problem is None and row is None:
        problem = NO_SAMPLE_ROW.format(_text(sample_id) or "The sample")
    if problem is None and field not in SAMPLE_FIELDS:
        problem = NOT_FIELD.format(field or "That")
    if problem is None:
        try:
            ok = float(to) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            problem = NOT_A_NUMBER.format(FIELD_LABELS.get(field, field))
    if problem is None:
        now = samples_in_force(rows, state)
        cur = dict((r.get("sample_id"), r) for r in now).get(row.get("sample_id")) or {}
        if _fact(cur.get(field)) == to:
            problem = SAME.format(FIELD_LABELS.get(field, field), to)
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": AMEND, "sample": row.get("sample_id"), "field": field,
             "from": _fact(row.get(field)), "to": to, "reason": reason, "by": who,
             "name_by": _text(name) or who, "at": _text(when)}
    if ws_state in RELEASED_STATES:
        entry["after_release"] = True
    state["log"].append(entry)
    return None, state, entry


def revert(state, entry_id, reason, who, when, ws_state, can_act, actor_kind, is_manager=False):
    """(problem, state, entry): an amendment undone before it is confirmed,
    with a reason. A re-extraction is not undone: its analyses have left the
    worksheet for the next batch."""
    state = load(state)
    reason, entry_id = _text(reason), _text(entry_id)
    target = dict((e.get("id"), e) for e in entries_in_force(state, (AMEND,))).get(entry_id)
    problem = actor_refusal(can_act, actor_kind) or state_refusal(ws_state, is_manager)
    if problem is None and not reason:
        problem = NO_REASON
    if problem is None and target is None:
        problem = NOTHING_TO_UNDO.format(entry_id or "That")
    if problem is None and entry_id in confirmed(state):
        problem = UNDO_CONFIRMED.format(entry_id)
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": REVERT, "reverts": entry_id, "reason": reason,
             "by": _text(who), "at": _text(when)}
    if ws_state in RELEASED_STATES:
        entry["after_release"] = True
    state["log"].append(entry)
    return None, state, entry


# ── re-extract ──────────────────────────────────────────────────────────────

def scope_members(members, member_id, scope):
    """The member ids a re-extraction withholds: the sample alone, the
    sample with the QC made on it (LFSM, LFSMD, Dup, MxB naming it as
    parent, and the LFSMD of a withheld LFSM), or the whole batch."""
    members = list(members or ())
    if scope == "batch":
        return [m.get("id") for m in members]
    target = dict((m.get("id"), m) for m in members).get(member_id)
    if target is None:
        return []
    if scope == "sample" or target.get("role") != "Sample":
        out = [target.get("id")]
        if target.get("role") == "LFSM":
            out += [m.get("id") for m in members if m.get("lfsm_of") == target.get("id")]
        return out
    out = [target.get("id")]
    out += [m.get("id") for m in members if m.get("parent") == target.get("id")]
    return out


def reextract(state, members, member_id, what, scope, sample_left, reason, who, when, ws_state,
              can_act, actor_kind, finalised, is_manager=False):
    """(problem, state, entry): members withheld for re-extraction. From
    then on nothing they gave is filed or reported; their analyses go to
    the next extraction batch."""
    state = load(state)
    reason = _text(reason)
    problem = actor_refusal(can_act, actor_kind)
    if problem is None and not finalised:
        problem = NOT_FINALISED
    if problem is None:
        if ws_state == REJECTED:
            problem = REJECTED_CLOSED
        elif ws_state in RELEASED_STATES:
            problem = SEND_BACK_RELEASED.format(STATE_WORDS.get(ws_state, ws_state))
        elif ws_state == SUBMITTED and not is_manager:
            problem = SEND_BACK_MANAGER
    if problem is None and not reason:
        problem = NO_REASON
    if problem is None and what not in dict(WHAT):
        problem = NO_WHAT
    if problem is None and scope not in dict(SCOPES):
        problem = NO_SCOPE
    ids = scope_members(members, _text(member_id), scope) if problem is None else []
    if problem is None and not ids:
        problem = NOTHING_WITHHELD
    held = withheld(state, members)
    if problem is None:
        already = [i for i in ids if i in held]
        if already and len(already) == len(ids):
            problem = ALREADY_WITHHELD.format(", ".join(already))
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": REEXTRACT, "what": what, "scope": scope,
             "member": _text(member_id), "members": [i for i in ids if i not in held],
             "sample_left": bool(sample_left), "reason": reason, "by": _text(who), "at": _text(when)}
    state["log"].append(entry)
    return None, state, entry


def link(state, entry_id, ws_id, who, when):
    """(problem, state, entry): a re-extraction's members finalised again in
    another worksheet: the two records name each other."""
    state = load(state)
    if _text(entry_id) not in dict((e.get("id"), e) for e in entries_in_force(state, (REEXTRACT,))):
        return NOT_WITHHELD.format(_text(entry_id) or "That"), state, None
    entry = {"id": _next_id(state), "action": LINK, "links": _text(entry_id), "ws": _text(ws_id),
             "by": _text(who), "at": _text(when)}
    state["log"].append(entry)
    return None, state, entry


# ── send back ───────────────────────────────────────────────────────────────

def send_back(state, to, stage, reason, who, when, ws_state, can_act, actor_kind, is_manager,
              finalised=True):
    """(problem, state, entry): the batch returned to an earlier step. While
    the worksheet is open an Analyst or a Lab Manager sends it back; once
    submitted only a Lab Manager; never once released or rejected."""
    state = load(state)
    reason, to = _text(reason), _text(to)
    problem = None
    if actor_kind == "automated":
        problem = AUTOMATED
    elif not can_act:
        problem = SEND_BACK_NOT_ALLOWED
    elif ws_state == REJECTED or ws_state in RELEASED_STATES:
        problem = SEND_BACK_RELEASED.format(STATE_WORDS.get(ws_state, ws_state))
    elif ws_state == SUBMITTED and not is_manager:
        problem = SEND_BACK_MANAGER
    if problem is None and not reason:
        problem = NO_REASON
    if problem is None and to not in dict(TARGETS):
        problem = NO_TARGET
    if problem is None and to == "stages" and not _text(stage):
        problem = NO_STAGE
    if problem is None and to in ("members", "stages") and not finalised:
        problem = NOT_FINALISED
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": SEND_BACK, "to": to, "stage": _text(stage),
             "from_state": _text(ws_state), "reason": reason, "by": _text(who), "at": _text(when)}
    state["log"].append(entry)
    return None, state, entry


def _instant(value):
    """A stored time comparable as text: ISO 8601 without its zone mark."""
    return _text(value).replace("Z", "").replace("T", " ")[:19]


def send_back_pending(state, filed_at):
    """The send back to the data import not yet followed by a run filed
    after it (`filed_at`, when the run's QC was last written; a run never
    filed reads earlier than any send back), or None. A send back to the
    members, a stage or the run build waits on the run built again instead
    (send_back.blocks_release)."""
    sends = [e for e in entries_in_force(state, (SEND_BACK,)) if e.get("to") == "import"]
    if not sends:
        return None
    last = sends[-1]
    return last if _instant(filed_at) <= _instant(last.get("at")) else None


def reset_all(checklist):
    """(checklist, cleared): every manual sign-off cleared, Chain of Custody
    too: a send back reopens the record they were made over."""
    cl = copy.deepcopy(checklist or {})
    items = cl.setdefault("items", {})
    cleared = []
    for key in sorted(items):
        item = items.get(key) or {}
        if not item.get("checked"):
            continue
        cleared.append({"item": key, "by": item.get("checked_by") or "",
                        "initials": item.get("initials") or "", "at": item.get("checked_at") or ""})
        items[key] = dict((k, v) for k, v in item.items()
                          if k not in ("checked", "checked_by", "checked_by_kind", "initials", "checked_at"))
    for k in ("submitted_by", "submitted_at"):
        cl.pop(k, None)
    return cl, cleared


def reset_signoffs(checklist, entry=None):
    """(checklist, cleared): the sign-offs an amendment or a re-extraction
    judges again, as for an identity correction (Final Data Summary and
    Instrument Report); an amendment of which sample a vial is also clears
    Chain of Custody."""
    cl, cleared = ii.reset_signoffs(checklist)
    if entry and entry.get("field") == SAMPLE:
        items = cl.setdefault("items", {})
        item = items.get("coc") or {}
        if item.get("checked"):
            cleared.append({"item": "coc", "by": item.get("checked_by") or "",
                            "initials": item.get("initials") or "", "at": item.get("checked_at") or ""})
            items["coc"] = dict((k, v) for k, v in item.items()
                                if k not in ("checked", "checked_by", "checked_by_kind", "initials", "checked_at"))
    return cl, cleared


# ── confirmed at verification ───────────────────────────────────────────────

def confirmed(state):
    """The entry ids confirmed."""
    return set(e.get("confirms") for e in load(state)["log"] if e.get("action") == CONFIRM)


def to_confirm(state):
    """The corrections in force a verifier confirms, oldest first; a send
    back stays to confirm, as an amendment does."""
    done = confirmed(state)
    return [e for e in entries_in_force(state) if e.get("id") not in done
            and not e.get("after_release")]


def unconfirmed(state):
    return [e.get("id") for e in to_confirm(state)]


def verify_refusal(state):
    left = unconfirmed(state)
    return UNCONFIRMED.format(", ".join(left)) if left else None


def confirm(state, entry_id, who, when, ws_state, is_manager, actor_kind, sign_as, name=""):
    """(problem, state, entry): the verifier confirms one correction: a Lab
    Manager with the reviewer sign right, never an automated account nor
    the person who made it, once the worksheet is submitted (the rule of
    injection_identity.confirm)."""
    state = load(state)
    entry_id, who = _text(entry_id), _text(who)
    problem = None
    if actor_kind == "automated":
        problem = AUTOMATED
    target = dict((e.get("id"), e) for e in entries_in_force(state)).get(entry_id)
    # a whole batch re-extracted never reaches verification: it is
    # confirmed while the worksheet is open
    whole = bool(target and target.get("action") == REEXTRACT and target.get("scope") == "batch")
    if problem is None and not is_manager:
        problem = NOT_VERIFIER
    if problem is None and ws_state != SUBMITTED and not (whole and ws_state in OPEN_STATES):
        problem = CONFIRM_STATE
    if problem is None and ii.REVIEWER not in list(sign_as or ()):
        problem = NO_SIGN_RIGHT.format(name or who)
    if problem is None and entry_id in confirmed(state):
        problem = ALREADY.format(entry_id)
    if problem is None and target is None:
        problem = NOT_TO_CONFIRM.format(entry_id or "That")
    if problem is None and target.get("by") == who:
        problem = OWN.format(entry_id)
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": CONFIRM, "confirms": entry_id, "by": who,
             "name": _text(name) or who, "at": _text(when)}
    state["log"].append(entry)
    return None, state, entry


# ── what the worker applied, and the record's parts ─────────────────────────

def judged_ids(state):
    """The ids of the corrections in force the run is judged with: the
    amendments and re-extractions (a send back is judged by a new import)."""
    return sorted(e.get("id") for e in entries_in_force(state, (AMEND, REEXTRACT)))


def pending(state, applied):
    """The corrections in force the stored run has not been judged with
    (`applied`: the ids the worker recorded). A worker that read none
    applied none, so release keeps waiting."""
    applied = set(applied or ())
    return [i for i in judged_ids(state) if i not in applied]


_PART_KEYS = ("id", "action", "member", "sample", "field", "from", "to", "reason", "by", "at")
_PART_EXTRA = ("also", "name", "swap_with", "reverts", "confirms", "what", "scope", "members",
               "sample_left", "stage", "from_state", "links", "ws", "cleared", "retracted",
               "after_release")


def record_part(state, after_release=False):
    """The batch record's corrections part, oldest first: every entry made
    before release ([] without one, so the record's hash is unchanged), or
    with `after_release` the entries made after it, an undo included (the
    next revision). Links are left out of both."""
    out = []
    for e in load(state)["log"]:
        # a link names the worksheet a re-extraction was finalised in: a
        # cross-reference written whenever that happens, shown, never hashed
        if e.get("action") == LINK:
            continue
        if bool(e.get("after_release")) != bool(after_release):
            continue
        part = dict((k, e.get(k) or "") for k in _PART_KEYS)
        part.update((k, e[k]) for k in _PART_EXTRA if e.get(k))
        out.append(part)
    return out


def revision(state):
    """The record's revision: 1 as released, one more for each amendment
    made after release."""
    return 1 + len([e for e in entries_in_force(state, (AMEND,)) if e.get("after_release")])


# ── words ───────────────────────────────────────────────────────────────────

def rejudged(field, member):
    """What an amendment of `field` judges again, in the lab's words."""
    role = (member or {}).get("role") or ""
    out = []
    if field == LEVEL:
        out += ["Expected value for every analyte at the new level",
                "%s recovery and its verdict" % role, "The %s flag on the batch's samples" % role]
    elif field == ROLE:
        out += ["Which rules judge it: the new QC type's", "The flags it gave the batch's samples"]
    elif field == PARENT:
        out += ["Which sample's native amount is subtracted", "Its recovery and its verdict",
                "Which sample carries its matrix code"]
    elif field == SAMPLE:
        out += ["Which sample receives the results, filed again", "Chain of Custody is signed off again"]
    elif field == SPIKE_LOT:
        out += ["The lot traced on the record"]
    elif field in SAMPLE_FIELDS:
        out += ["The sample's results, worked from the amended value"]
    if field in (LEVEL, ROLE) and (member or {}).get("named"):
        out.append("Its name follows; the issued name still matches the file")
    out.append("Final Data and Instrument Report sign-offs are cleared")
    return out


def describe(entry, members=()):
    """One line for an entry, for the record page and the print."""
    by_id = dict((m.get("id"), m) for m in members or ())
    act = entry.get("action")
    who = (by_id.get(entry.get("member")) or {}).get("injection") or entry.get("member") \
        or entry.get("sample") or ""
    if act == AMEND:
        return "Amended %s %s" % (who, FIELD_LABELS.get(entry.get("field"), entry.get("field")).lower())
    if act == REEXTRACT:
        return "Re-extraction: %s" % ", ".join(
            (by_id.get(i) or {}).get("injection") or i for i in entry.get("members") or ())
    if act == SEND_BACK:
        from senaite.pfas import review_send_back as rsb
        target = dict(TARGETS).get(entry.get("to"), entry.get("to"))
        return "%s to %s%s" % (rsb.SENT_BACK_LABEL, target.lower(),
                               (" from stage %s" % entry["stage"]) if entry.get("stage") else "")
    if act == REVERT:
        return "Undone: %s" % entry.get("reverts")
    if act == CONFIRM:
        return "Confirmed: %s" % entry.get("confirms")
    if act == LINK:
        return "%s re-extracted in %s" % (entry.get("links"), entry.get("ws"))
    return act or ""
