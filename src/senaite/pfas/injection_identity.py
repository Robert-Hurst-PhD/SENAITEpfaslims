# -*- coding: utf-8 -*-
"""An injection's identity, corrected at Data Review.

The run says what each injection is: the Run Builder's plan, the extraction
batch's members, else the name. When that is wrong (a CCV judged by the
lowest-level window on a method that runs one CCV level; a CCV that is not
one) a reviewer corrects it here, with a reason. The correction is an overlay kept on the worksheet:
the raw data, the run plan, the members and the stored results are never
edited. The worker reads the corrections in force with the run plan and
judges the whole run again with them.

The record, one worksheet annotation (KEY), is an append-only log:

    {"log": [{"id": "IC-1", "action": "correct" | "revert", "injection",
              "from", "to", "reason", "by", "at"[, "origin"][, "reverts"]
              [, "cleared"]},
             {"id": "IC-2", "action": "confirm", "injection", "confirms",
              "by", "name", "at"},
             ...]}

The correction in force for an injection is its latest "correct" entry not
followed by a "revert". A correction made over another keeps the run's own
judgement as its "origin": an undo returns the injection to it. "cleared"
names the sign-offs the entry cleared (reset_signoffs).

Roles are the engine's own spellings (Sample, CCV, ICV, CCB) plus CCV_LOW, a CCV judged by the method's Low-Level window
(the worker receives it as role CCV at level "low"; a CCV corrected to CCV
is at level "standard", judged by the Recovery window whatever its level
column or expected concentration says), and NotJudged: the injection keeps
its record, but no QC or result uses it.

What can be corrected: an injection judged as one of CORRECTABLE, but not
  - one of the extraction batch's members, nor a dilution (their role is
    the extraction record's);
  - a calibrator, nor extraction QC (a calibrator's identity is its
    curve's, reviewed on the Calibration tab; extraction QC is judged from
    the extraction record's parent, spike or lot);

A sample whose results are already filed on a SENAITE sample is corrected
too: its entry carries "retract", and the caller retracts those results in
the same transaction (identity_retract), keeping them on the entry
("retracted"). An undo does not restore them: they stay retracted, and the
run judged again files new results on their retests ("refiled").

Who: an Analyst or a Lab Manager (Data Review's own can_act), never an
automated account. When: while the worksheet is open; never once it is
submitted, verified, published or rejected. A rejected worksheet is
terminal: a correction the verifier will not confirm is not released.

At verification the verifier confirms each correction in force (confirm):
a Lab Manager with the reviewer sign right in People & Roles, never the
person who made it. Verify is refused while one is unconfirmed
(verify_refusal).

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import os
import shutil

import six

KEY = "senaite.pfas.injection_identity"

SAMPLE, CCV, CCV_LOW, ICV, CCB = "Sample", "CCV", "CCV_LOW", "ICV", "CCB"
NOT_JUDGED = "NotJudged"
CORRECTABLE = (SAMPLE, CCV, CCV_LOW, ICV, CCB, NOT_JUDGED)
LABELS = {SAMPLE: "Sample", CCV: "CCV", CCV_LOW: "CCV, lowest level", ICV: "ICV", CCB: "CCB",
          NOT_JUDGED: "Not judged"}
# the standards whose verdict needs the export's expected concentration
CHECK_STANDARDS = (CCV, CCV_LOW, ICV)
# what the worker is told: the engine's role and the CCV level it is judged at
WORKER = {SAMPLE: (SAMPLE, ""), CCV: (CCV, "standard"), CCV_LOW: (CCV, "low"),
          ICV: (ICV, "standard"), CCB: (CCB, ""), NOT_JUDGED: (NOT_JUDGED, "")}
# the run template's tokens that are offered when the template holds them
TEMPLATE_ROLES = (ICV, CCB)
# the checklist sign-offs a correction judges again: the results (Final
# Data Summary, and the blank and duplicate results signed on their own tabs)
# and the run's injections (Instrument Report). Chain of Custody is not
# judged again; the automatic items recompute themselves.
AFFECTED_SIGNOFFS = ("final_data", "instrument_report", "blank_results", "duplicate_results")
# the names of the result sign-offs asked only when their rows exist (Data
# Review's Blanks and Spike QC tabs), as every record prints them
RESULT_SIGNOFF_LABELS = {"blank_results": u"Blank Results", "duplicate_results": u"Duplicate Results"}
# the People & Roles sign right a confirmation needs
REVIEWER = "reviewer"

# the worksheet states a correction is refused in: submitted, verified or
# published (the review record is read-only) and rejected (no run is
# imported into it again)
CLOSED_STATES = frozenset(("to_be_verified", "verified", "published", "rejected"))

CORRECT, REVERT, CONFIRM = "correct", "revert", "confirm"

NO_REASON = "A reason is required. Nothing was saved."
NOT_ALLOWED = "Only an Analyst or a Lab Manager corrects an injection's identity."
AUTOMATED = "An automated account does not correct or confirm an injection's identity."
CLOSED = "The worksheet is {0}: an injection's identity is not corrected now."
NOT_IN_RUN = "{0} is not an injection of this run."
MEMBER = ("{0} is one of the extraction batch's members: its role is the extraction "
          "record's. Correct it there.")
DILUTION = "{0} is a dilution recorded on the extraction record: correct it there."
NOT_CORRECTABLE = ("{0} is judged as {1}: its identity is not corrected here. A calibrator is "
                   "reviewed on the Calibration tab; extraction QC on the extraction record.")
# what an undo window says of results a correction retracted
UNDO_RETRACTED = ("Results the correction retracted stay retracted; the run judged again files "
                  "new results on their retests.")
NOT_OFFERED = "{0} is not a role this method runs."
SAME = "{0} is already judged as {1}."
NOT_CORRECTED = "{0} has no correction in force."
NO_RUN = "This worksheet has no run file to judge again: upload the run first."
NOT_VERIFIER = "Only a Lab Manager confirms an identity correction."
CONFIRM_STATE = "A correction is confirmed at verification, once the worksheet is submitted."
OWN = "{0} was corrected by you: a different person confirms it."
NO_SIGN_RIGHT = "{0} has no reviewer sign right in People & Roles, so does not confirm a correction."
ALREADY = "The correction of {0} is already confirmed."
UNCONFIRMED = ("Confirm each identity correction before verifying, or reject the run: "
               "not confirmed: {0}.")

STATE_WORDS = {"to_be_verified": "submitted", "verified": "verified", "published": "published",
               "rejected": "rejected"}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, six.binary_type):
        return value.decode("utf-8")
    return six.text_type(value).strip()


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


def label(code):
    return LABELS.get(code, code or "")


def in_force(state):
    """{injection: the correct entry in force}."""
    out = {}
    for e in load(state)["log"]:
        inj = e.get("injection") or ""
        if e.get("action") == CORRECT:
            out[inj] = e
        elif e.get("action") == REVERT:
            out.pop(inj, None)
    return out


def history(state):
    """Every entry, newest first, with its codes, its labels and its change
    in words ("CCV, lowest level to CCV", "Undone: ...", "Confirmed: ...")."""
    log = load(state)["log"]
    by_id = dict((e.get("id"), e) for e in log)
    out = []
    for e in reversed(log):
        shown = by_id.get(e.get("confirms"), {}) if e.get("action") == CONFIRM else e
        change = "{0} to {1}".format(label(shown.get("from")), label(shown.get("to")))
        if e.get("action") == REVERT:
            change = "Undone: " + change
        elif e.get("action") == CONFIRM:
            change = "Confirmed: " + change
        out.append(dict(e, from_label=label(shown.get("from")), to_label=label(shown.get("to")),
                        from_code=shown.get("from") or "", to_code=shown.get("to") or "",
                        change=change))
    return out


def overlay(state):
    """What the worker is told ({injection: {"id", "role", "level", "from",
    "to", "by", "at", "reason"}}): the corrections in force, each as the
    engine's role and level (WORKER)."""
    out = {}
    for inj, e in in_force(state).items():
        role, level = WORKER.get(e.get("to"), (e.get("to") or "", ""))
        out[inj] = {"id": e.get("id") or "", "role": role, "level": level,
                    "from": e.get("from") or "", "to": e.get("to") or "",
                    "by": e.get("by") or "", "at": e.get("at") or "", "reason": e.get("reason") or ""}
    return out


def _next_id(state):
    n = 0
    for e in load(state)["log"]:
        try:
            n = max(n, int((e.get("id") or "").split("-")[-1]))
        except ValueError:
            continue
    return "IC-%d" % (n + 1)


# ── what the method offers ──────────────────────────────────────────────────

def low_window(profile):
    """Whether the method judges a CCV by a Low-Level window: set and not
    Off (limit_states box ccv_low_level)."""
    from senaite.pfas import limit_states as ls
    data = profile or {}
    try:
        return (ls.box_state(data, "ccv_low_level") != "off"
                and not ls.is_empty(data, ls.BOX["ccv_low_level"]))
    except Exception:                                       # noqa: BLE001
        return False


def _template(profile):
    tpl = (profile or {}).get("run_template")
    if isinstance(tpl, dict) and tpl.get("sequence"):
        return [_text(c).upper() for c in tpl["sequence"]], _text(tpl.get("bracket_qc")).upper() or CCV
    if isinstance(tpl, dict) and (tpl.get("opening") or tpl.get("closing")):
        seq = [_text(c).upper() for c in (tpl.get("opening") or []) + (tpl.get("closing") or [])]
        return seq, _text(tpl.get("bracket_qc")).upper() or CCV
    # the Run Builder's default template opens with CAL, ICV
    return ["MB", "CAL", "ICV", "MB"], CCV


def offered_roles(profile):
    """The roles a reviewer may give an injection on this method, in order:
    Sample, the bracketing QC (CCV), its lowest level where the method has a
    Low-Level window, ICV and CCB where the run template holds them, then
    Not judged."""
    seq, bracket = _template(profile)
    out = [SAMPLE]
    if bracket == CCV or CCV in seq:
        out.append(CCV)
        if low_window(profile):
            out.append(CCV_LOW)
    for code in TEMPLATE_ROLES:
        if code in seq or bracket == code:
            out.append(code)
    out.append(NOT_JUDGED)
    return out


def judged_role(qc_type, low=False):
    """The role code of an injection as the run judged it: its stored
    qc_type, CCV_LOW for a CCV judged by the Low-Level window."""
    qc = _text(qc_type)
    if qc.upper() == CCV:
        return CCV_LOW if low else CCV
    for code in CORRECTABLE:
        if qc.upper() == code.upper():
            return code
    return qc


# ── what will be judged again ───────────────────────────────────────────────

def rejudged(current, target):
    """The sentences the window shows for a change from `current` to
    `target`: what is withdrawn, what is judged, what follows."""
    out = []
    if current in (CCV, CCV_LOW) and target not in (CCV, CCV_LOW):
        out.append("Its CCV recovery checks are withdrawn.")
        out.append("The samples it bracketed are bracketed by the CCVs on either side, and their "
                   "internal standard responses are judged against the CCV before them.")
    elif current == ICV and target != ICV:
        out.append("Its ICV check is withdrawn: the calibration is verified by any other ICV.")
    elif current == CCB and target != CCB:
        out.append("Its blank check is withdrawn.")
    elif current == SAMPLE:
        out.append("It is no longer reported as a sample. Results already filed on its sample "
                   "are retracted (SENAITE keeps them, shown as retracted) and the sample waits "
                   "for a new result.")
    if target == CCV:
        out.append("Judged by the method's CCV Recovery window, at every level.")
    elif target == CCV_LOW:
        out.append("Judged by the method's CCV Low-Level window.")
    elif target == ICV:
        out.append("Judged by the method's ICV criterion.")
    elif target == CCB:
        out.append("Judged as a continuing calibration blank.")
    elif target == SAMPLE:
        out.append("Reported as a sample. With no sample of this worksheet under its name, "
                   "its results are not filed.")
    elif target == NOT_JUDGED:
        out.append("No QC or result uses it: it stays in the record with its reason.")
    if target in (CCV, CCV_LOW) and current not in (CCV, CCV_LOW):
        out.append("It brackets the samples around it.")
    if target in CHECK_STANDARDS:
        out.append("Where the export gives no expected concentration it cannot be judged, "
                   "and release waits.")
    out.append("The whole run is judged again; release waits until it is.")
    out.append("The Final Data Summary and Instrument Report sign-offs are cleared, to be "
               "made again.")
    return out


# ── the refusals ────────────────────────────────────────────────────────────

def actor_refusal(can_act, actor_kind):
    """Why this person may not correct, or None."""
    if actor_kind == "automated":
        return AUTOMATED
    if not can_act:
        return NOT_ALLOWED
    return None


def state_refusal(ws_state):
    if ws_state in CLOSED_STATES:
        return CLOSED.format(STATE_WORDS.get(ws_state, ws_state))
    return None


def correct(state, injection, target, reason, who, when, ws_state, can_act, actor_kind,
            judged, offered, members=(), dilutions=(), can_requeue=True, filed=()):
    """(problem, new state, entry). `judged` is {injection: role code} as the
    run judged it; `offered` the method's roles (offered_roles); `filed` the
    injections whose results are filed on a SENAITE sample (the push log).
    Nothing is changed when there is a problem."""
    state = load(state)
    injection, target, reason = _text(injection), _text(target), _text(reason)
    problem = (actor_refusal(can_act, actor_kind) or state_refusal(ws_state)
               or (None if reason else NO_REASON))
    if problem is None and injection not in (judged or {}):
        problem = NOT_IN_RUN.format(injection or "The injection")
    if problem is None and injection in set(dilutions or ()):
        problem = DILUTION.format(injection)
    if problem is None and injection in set(members or ()):
        problem = MEMBER.format(injection)
    forced = in_force(state).get(injection)
    # an injection already corrected is judged as its correction says,
    # whatever the stored run (judged again or not yet) says
    current = forced.get("to") if forced else (judged or {}).get(injection)
    if problem is None and current not in CORRECTABLE:
        problem = NOT_CORRECTABLE.format(injection, label(current) or "nothing")
    if problem is None and target not in (offered or ()):
        problem = NOT_OFFERED.format(label(target) or "That")
    if problem is None and target == current:
        problem = SAME.format(injection, label(current))
    if problem is None and not can_requeue:
        problem = NO_RUN
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": CORRECT, "injection": injection,
             "from": current, "to": target, "reason": reason, "by": _text(who), "at": _text(when)}
    if forced:
        # a correction over a correction: an undo returns to what the run judged
        entry["origin"] = forced.get("origin") or forced.get("from")
    if current == SAMPLE and target != SAMPLE and injection in set(filed or ()):
        # its results filed on a sample are retracted with the correction
        entry["retract"] = True
    state["log"].append(entry)
    return None, state, entry


def revert(state, injection, reason, who, when, ws_state, can_act, actor_kind, can_requeue=True):
    """(problem, new state, entry): the correction in force on `injection`
    undone, the run judging it as it did before."""
    state = load(state)
    injection, reason = _text(injection), _text(reason)
    problem = (actor_refusal(can_act, actor_kind) or state_refusal(ws_state)
               or (None if reason else NO_REASON))
    forced = in_force(state).get(injection)
    if problem is None and forced is None:
        problem = NOT_CORRECTED.format(injection or "The injection")
    if problem is None and not can_requeue:
        problem = NO_RUN
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": REVERT, "injection": injection,
             "from": forced.get("to"), "to": forced.get("origin") or forced.get("from"), "reason": reason,
             "by": _text(who), "at": _text(when), "reverts": forced.get("id")}
    gone = [r.get("analysis") for r in forced.get("retracted") or [] if r.get("analysis")]
    if gone:
        # never restored: the run judged again files their retests
        entry["refiled"] = gone
    state["log"].append(entry)
    return None, state, entry


# ── judged again yet? ───────────────────────────────────────────────────────

def pending(state, applied):
    """The injections whose correction the stored run has not applied: the
    corrections in force against `applied` ({injection: correction id}, the
    stored run's ID records). A worker that could not read them applied
    none, so release keeps waiting."""
    forced = dict((inj, e.get("id")) for inj, e in in_force(state).items())
    applied = dict(applied or {})
    return sorted(inj for inj in set(forced) | set(applied) if forced.get(inj) != applied.get(inj))


def marker(entry, waiting, when_text=None):
    """The small marker on a corrected injection's row: {"text", "title",
    "waiting"}."""
    at = when_text or entry.get("at") or ""
    title = "{0} to {1}, by {2}, {3}: {4}".format(label(entry.get("from")), label(entry.get("to")),
                                                  entry.get("by") or "", at, entry.get("reason") or "")
    return {"text": "Corrected, not yet judged" if waiting else "Corrected",
            "title": title, "waiting": bool(waiting)}


_PART_KEYS = ("id", "action", "injection", "from", "to", "reason", "by", "at")
# kept in the part only where an entry has them
_PART_EXTRA = ("origin", "reverts", "cleared", "confirms", "name", "retracted", "refiled")


def record_part(state):
    """The batch record's identity part: every entry, oldest first, as
    plain text fields, an entry's own extras only where it has them; []
    without one (the record's hash is then unchanged)."""
    out = []
    for e in load(state)["log"]:
        part = dict((k, e.get(k) or "") for k in _PART_KEYS)
        part.update((k, e[k]) for k in _PART_EXTRA if e.get(k))
        out.append(part)
    return out


def undo_lines():
    """What the undo window says will follow."""
    return ["Judged again as the run says.", UNDO_RETRACTED,
            "The Final Data Summary and Instrument Report sign-offs are cleared, to be made again."]


# ── the sign-offs a correction judges again ─────────────────────────────────

def reset_signoffs(checklist):
    """(checklist, cleared): Data Review's checklist with the sign-offs a
    correction judges again (AFFECTED_SIGNOFFS) cleared, and what was
    cleared ([{"item", "by", "initials", "at"}]); the others are kept."""
    import copy
    cl = copy.deepcopy(checklist or {})
    items = cl.setdefault("items", {})
    cleared = []
    for key in AFFECTED_SIGNOFFS:
        item = items.get(key) or {}
        if not item.get("checked"):
            continue
        cleared.append({"item": key, "by": item.get("checked_by") or "",
                        "initials": item.get("initials") or "", "at": item.get("checked_at") or ""})
        items[key] = dict((k, v) for k, v in item.items()
                          if k not in ("checked", "checked_by", "checked_by_kind", "initials", "checked_at"))
    return cl, cleared


# ── confirmed at verification ───────────────────────────────────────────────

def confirmed(state):
    """{injection: the confirm entry} of the corrections in force that the
    verifier confirmed."""
    forced = dict((e.get("id"), inj) for inj, e in in_force(state).items())
    out = {}
    for e in load(state)["log"]:
        if e.get("action") == CONFIRM and e.get("confirms") in forced:
            out[forced[e["confirms"]]] = e
    return out


def unconfirmed(state):
    """The injections whose correction in force is not yet confirmed."""
    done = confirmed(state)
    return sorted(inj for inj in in_force(state) if inj not in done)


def verify_refusal(state):
    """Why the worksheet is not verified yet, or None."""
    todo = unconfirmed(state)
    return UNCONFIRMED.format(", ".join(todo)) if todo else None


def confirm(state, injection, who, when, ws_state, is_manager, actor_kind, sign_as, name=""):
    """(problem, new state, entry): the verifier confirms the correction in
    force on `injection`. A Lab Manager with the reviewer sign right
    (`sign_as`, People & Roles), never an automated account nor the person
    who made it, once the worksheet is submitted."""
    state = load(state)
    injection, who = _text(injection), _text(who)
    problem = None
    if actor_kind == "automated":
        problem = AUTOMATED
    elif not is_manager:
        problem = NOT_VERIFIER
    elif ws_state != "to_be_verified":
        problem = CONFIRM_STATE
    elif REVIEWER not in list(sign_as or ()):
        problem = NO_SIGN_RIGHT.format(name or who)
    forced = in_force(state).get(injection)
    if problem is None and forced is None:
        problem = NOT_CORRECTED.format(injection or "The injection")
    if problem is None and injection in confirmed(state):
        problem = ALREADY.format(injection)
    if problem is None and forced.get("by") == who:
        problem = OWN.format(injection)
    if problem:
        return problem, state, None
    entry = {"id": _next_id(state), "action": CONFIRM, "injection": injection,
             "confirms": forced.get("id"), "by": who, "name": _text(name) or who, "at": _text(when)}
    state["log"].append(entry)
    return None, state, entry


# ── queued again ────────────────────────────────────────────────────────────

def requeue_target(upload_dir, raw_stem, run_files):
    """(kind, path) of the file that makes the worker judge the run again:
    a raw run's record (<stem>.rawrun), else the worksheet's latest run file
    in the upload folder or its archive (a full or supplementary run joins
    the others). None when there is none."""
    from senaite.pfas import instrument_files
    if raw_stem:
        path = os.path.join(upload_dir, raw_stem + ".rawrun")
        if os.path.isfile(path):
            return "raw", path
    for entry in reversed(list(run_files or [])):
        if not isinstance(entry, dict) or entry.get("deleted") or not entry.get("file"):
            continue
        found = instrument_files.locate(upload_dir, entry["file"])
        if found:
            return "export", found
    return None


def requeue(upload_dir, raw_stem, run_files):
    """Queue the run again: the file requeue_target names is touched where
    the worker watches; an archived export is copied back first. Returns
    the path touched, or None."""
    target = requeue_target(upload_dir, raw_stem, run_files)
    if target is None:
        return None
    _kind, path = target
    here = os.path.join(upload_dir, os.path.basename(path))
    if os.path.abspath(path) != os.path.abspath(here):
        shutil.copyfile(path, here)
    os.utime(here, None)
    return here
