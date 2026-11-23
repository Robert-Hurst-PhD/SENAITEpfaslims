# -*- coding: utf-8 -*-
"""A lot's expiry extended by QA: the entries kept on the lot, and the date
in force they give.

An extension is QA's decision that a lot is fit for use until a new date.
It is kept on the lot (reagent or prepared standard) as a list under KEY,
newest last, one entry per extension; an entry is appended or changes
state and is never deleted. The lot's own dates (expiry_date,
manufacturer_expiry) are never overwritten.

The date in force is the latest approved extension's new expiry, counted
from the laboratory day it was approved ("approved_on"): a use on that day
or later is in date until the new expiry; a use before it is judged
against the date then in force. A withdrawn extension counted from its
approval up to its withdrawal ("withdrawn_on", the laboratory day of the
ledger's withdrawal row): a use in that window stays in date, a later one
is judged on the earlier date. A refused extension never counts.

    entries(stored)                  -> the list, from the annotation's text
    in_force_entry(entries, as_of)   -> the approved entry in force on as_of
    in_force(recorded, entries, as_of=None)
                                     -> the expiry in force: the extension's
                                        new date, else `recorded`
    printed(recorded, entries, as_of=None)
                                     -> what a record prints: the extension's
                                        note, else the date
    label_values(entries) / label_row(row, shows_extended)
                                     -> a label's extension fields

`as_of` is a "YYYY-MM-DD" laboratory day; None is now (every approved
extension counts). Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

KEY = "senaite.pfas.lot.extension"

REQUESTED, APPROVED, REFUSED, WITHDRAWN = u"requested", u"approved", u"refused", u"withdrawn"


def _d(value):
    return (u"%s" % (value or u""))[:10]


def entries(stored):
    """The entries from what the lot stores: JSON text, a list, or nothing."""
    if not stored:
        return []
    if isinstance(stored, (list, tuple)):
        return [e for e in stored if isinstance(e, dict)]
    try:
        out = json.loads(stored)
    except (TypeError, ValueError):
        return []
    return [e for e in out if isinstance(e, dict)] if isinstance(out, list) else []


def _counts(e, day):
    """Whether an entry gives the date in force on `day` (None: now). An
    approved entry counts from its approval day; a withdrawn one counted
    from its approval day up to the day before its withdrawal, so a use in
    that window stays in date and one from the withdrawal day on is judged
    on the earlier date; now, a withdrawn entry never counts."""
    approved = _d(e.get("approved_on"))
    if e.get("state") == APPROVED:
        return not day or (bool(approved) and approved <= day)
    if e.get("state") == WITHDRAWN and day:
        gone = _d(e.get("withdrawn_on"))
        return bool(approved and gone) and approved <= day < gone
    return False


def in_force_entry(items, as_of=None):
    """The entry in force on `as_of`: of those that count that day
    (_counts), the last approved; None when none."""
    day = _d(as_of)
    found = None
    for e in items or []:
        if not isinstance(e, dict) or not _d(e.get("new_expiry")) or not _counts(e, day):
            continue
        if found is None or (_d(e.get("approved_on")), e.get("approved_at") or u"") >= \
                (_d(found.get("approved_on")), found.get("approved_at") or u""):
            found = e
    return found


def in_force(recorded, items, as_of=None):
    """The lot's expiry in force on `as_of`: the approved extension's new
    date, else the recorded date (as the caller resolved it)."""
    e = in_force_entry(items, as_of)
    return _d(e.get("new_expiry")) if e is not None else (recorded or u"")


# ── the request, QA's decision and its signature ────────────────────────────
#
# Anyone who may record work asks for an extension: the lot, the new date,
# the reason and the evidence. A person holding the QA approver sign right
# approves it with an e-signature (ledger kind KIND, meaning MEANING) or
# refuses it with a reason; the person who asked may not approve. The
# signature binds the entry's content (signed_content): the lot, both
# dates, the reason, the evidence, who asked, and every lot made from it
# that the approval extends with it (the children, each capped at the
# parent's new date). Withdrawing that one signature withdraws them all.

KIND = u"lot_extension"
MEANING = u"qa_approved"
REVISION = 1
LABELS = ((REQUESTED, u"Waiting for QA"), (APPROVED, u"Approved"), (REFUSED, u"Refused"),
          (WITHDRAWN, u"Withdrawn"))
MARK = u"ext."

OPEN_REQUEST = u"Lot %s already has an extension waiting for QA."
NO_REASON = u"Give the reason for the extension."
NO_EVIDENCE = u"Name the evidence: the re-check or the supplier's re-certification."
NO_DATE = u"Enter the new expiry date."
NOT_LATER = u"The new expiry must be after the date in force, %s."
AFTER_PARENTS = u"The new expiry is after its parent lots' date in force, %s: extend the parent lot first."
NOT_REQUESTED = u"Only an extension waiting for QA can be approved or refused."
OWN_REQUEST = u"The person who asked for the extension cannot approve it."
NO_REFUSAL = u"Give the reason for refusing the extension."
CHILD_AFTER_PARENT = u"Lot %s: the new expiry may not be after the parent's new expiry, %s."
CHILD_NOT_LATER = u"Lot %s: the new expiry must be after its date in force, %s."
CHILD_AFTER_ITS_PARENTS = u"Lot %s: the new expiry is after its other parent lots' date in force, %s."
CHILD_OPEN = u"Lot %s has an extension of its own waiting for QA."
NO_EXPIRY_LOT = u"Lot %s has no expiry: there is nothing to extend."


def _valid_day(value):
    import datetime
    try:
        datetime.datetime.strptime(_d(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def label(state):
    return dict(LABELS).get(state, state or u"")


def waiting(items):
    """The entry waiting for QA, or None."""
    return next((e for e in items or [] if e.get("state") == REQUESTED), None)


def new_id(lot_uid, items):
    """"<lot uid>-x<n>": the lot an extension belongs to is read from its id."""
    return u"%s-x%d" % (lot_uid, len(items or []) + 1)


def lot_uid_of(entry_id):
    head, sep, tail = (entry_id or u"").rpartition(u"-x")
    return head if sep and tail.isdigit() else u""


def original_expiry(items, recorded):
    """The lot's date before its first extension."""
    first = next((e for e in items or [] if e.get("original_expiry")), None)
    return _d(first.get("original_expiry")) if first else _d(recorded)


def request(items, lot, recorded, in_force_now, new_expiry, reason, evidence, who, who_name, at, cap=u""):
    """(entry, problems): a new extension asked for. `lot` = {"kind", "uid",
    "lot_number", "name"}; `recorded` the lot's own date before any
    extension; `in_force_now` its date in force; `cap` (a prepared lot) the
    earliest date in force of its parents, which an extension never passes."""
    problems = []
    if lot.get("no_expiry"):
        # a lot whose category has no expiry never expires
        problems.append(NO_EXPIRY_LOT % (lot.get("lot_number") or u"?"))
    if waiting(items):
        problems.append(OPEN_REQUEST % (lot.get("lot_number") or u"?"))
    reason, evidence, new = (reason or u"").strip(), (evidence or u"").strip(), _d(new_expiry)
    if not reason:
        problems.append(NO_REASON)
    if not evidence:
        problems.append(NO_EVIDENCE)
    if not _valid_day(new):
        problems.append(NO_DATE)
    elif lot.get("no_expiry"):
        pass
    elif _d(in_force_now) and new <= _d(in_force_now):
        problems.append(NOT_LATER % _d(in_force_now))
    elif _d(cap) and new > _d(cap):
        problems.append(AFTER_PARENTS % _d(cap))
    entry = {"id": new_id(lot.get("uid") or u"", items), "lot_kind": lot.get("kind") or u"",
             "lot_uid": lot.get("uid") or u"", "lot_number": lot.get("lot_number") or u"",
             "lot_name": lot.get("name") or u"", "original_expiry": original_expiry(items, recorded),
             "from_expiry": _d(in_force_now), "new_expiry": new, "reason": reason, "evidence": evidence,
             "requested_by": who or u"", "requested_name": who_name or who or u"", "requested_at": at,
             "state": REQUESTED}
    return entry, problems


def child_entry(parent, child, items):
    """The entry a child lot gets when its parent's approval extends it:
    `child` = {"kind", "uid", "lot_number", "name", "recorded", "in_force",
    "new_expiry"}; `items` the child's own entries."""
    return {"id": new_id(child.get("uid") or u"", items), "lot_kind": child.get("kind") or u"",
            "lot_uid": child.get("uid") or u"", "lot_number": child.get("lot_number") or u"",
            "lot_name": child.get("name") or u"",
            "original_expiry": original_expiry(items, child.get("recorded")),
            "from_expiry": _d(child.get("in_force")), "new_expiry": _d(child.get("new_expiry")),
            "reason": u"Extended with its parent lot %s: %s" % (parent.get("lot_number") or u"?",
                                                                parent.get("reason") or u""),
            "evidence": parent.get("evidence") or u"", "requested_by": parent.get("requested_by") or u"",
            "requested_name": parent.get("requested_name") or u"",
            "requested_at": parent.get("requested_at") or u"", "with": parent.get("id") or u"",
            "state": REQUESTED}


def _signed_child(c):
    return dict((k, c.get(k) or u"") for k in ("id", "lot_kind", "lot_uid", "lot_number", "from_expiry",
                                                "new_expiry"))


def signed_content(entry, children=None):
    """What the QA approver's signature binds: the lot, both dates, the
    reason, the evidence, who asked, and each child lot extended with it.
    `children` default to the ones the entry records."""
    if children is None:
        children = entry.get("children") or []
    return {"kind": KIND, "id": entry.get("id") or u"", "revision": REVISION,
            "lot": {"kind": entry.get("lot_kind") or u"", "uid": entry.get("lot_uid") or u"",
                    "lot_number": entry.get("lot_number") or u"", "name": entry.get("lot_name") or u""},
            "original_expiry": entry.get("original_expiry") or u"",
            "from_expiry": entry.get("from_expiry") or u"", "new_expiry": entry.get("new_expiry") or u"",
            "reason": entry.get("reason") or u"", "evidence": entry.get("evidence") or u"",
            "requested_by": entry.get("requested_by") or u"",
            "children": [_signed_child(c) for c in children]}


def record_hash(entry, children=None):
    from senaite.pfas.esig import canonical
    return canonical.sha256_of(signed_content(entry, children))


def approve_problems(entry, approver, children=(), child_items=None):
    """Why `approver` may not approve this entry with these children
    (child_entry dicts, each with "cap": the earliest date in force of its
    other parents, or ""). `child_items` {child uid: its entries}."""
    out = []
    if (entry or {}).get("state") != REQUESTED:
        return [NOT_REQUESTED]
    # the person who asked never approves, whatever rights they hold
    if approver and approver == entry.get("requested_by"):
        out.append(OWN_REQUEST)
    parent_new = _d(entry.get("new_expiry"))
    for c in children or []:
        lot, new = c.get("lot_number") or u"?", _d(c.get("new_expiry"))
        if waiting((child_items or {}).get(c.get("lot_uid")) or []):
            out.append(CHILD_OPEN % lot)
        if not _valid_day(new):
            out.append(u"Lot %s: %s" % (lot, NO_DATE))
        elif new > parent_new:
            out.append(CHILD_AFTER_PARENT % (lot, parent_new))
        elif _d(c.get("from_expiry")) and new <= _d(c.get("from_expiry")):
            out.append(CHILD_NOT_LATER % (lot, _d(c.get("from_expiry"))))
        elif _d(c.get("cap")) and new > _d(c.get("cap")):
            out.append(CHILD_AFTER_ITS_PARENTS % (lot, _d(c.get("cap"))))
    return out


def _decided(entry, state, who, who_name, at, day, signature):
    out = dict(entry, state=state, approved_by=who or u"", approved_name=who_name or who or u"",
               approved_at=at, approved_on=_d(day), signature=dict(signature or {}))
    out.pop("cap", None)
    return out


def approve(entry, approver, approver_name, at, day, signature, children=()):
    """(the entry approved, [each child's entry approved]): `day` the
    laboratory day of the approval, from which the new date counts;
    `signature` {"seq", "hash", "record_hash"} of the ledger row."""
    kids = [_decided(c, APPROVED, approver, approver_name, at, day, signature) for c in children or []]
    parent = _decided(entry, APPROVED, approver, approver_name, at, day, signature)
    parent["children"] = [_signed_child(c) for c in kids]
    return parent, kids


def refuse(entry, who, who_name, at, why):
    """The entry refused, with who, when and why; ValueError without a
    reason or when it is not waiting."""
    why = (why or u"").strip()
    if (entry or {}).get("state") != REQUESTED:
        raise ValueError(NOT_REQUESTED)
    if not why:
        raise ValueError(NO_REFUSAL)
    return dict(entry, state=REFUSED, refused_by=who or u"", refused_name=who_name or who or u"",
                refused_at=at, refused_reason=why)


def withdrawn(entry, who, at, reason, seq=None, day=None):
    """The entry withdrawn (its signature was withdrawn): from `day` (the
    laboratory day of the ledger's withdrawal row, whose time `at` is) the
    lot returns to its previous date in force. An entry already withdrawn
    is kept."""
    if entry.get("state") == WITHDRAWN:
        return entry
    return dict(entry, state=WITHDRAWN, withdrawn_by=who or u"", withdrawn_at=at,
                withdrawn_on=_d(day or at), withdrawn_reason=(reason or u"").strip(), withdrawn_seq=seq)


def put(items, entry):
    """The list with `entry` in place of the one with its id, else added."""
    out, done = [], False
    for e in items or []:
        if e.get("id") == entry.get("id"):
            out.append(entry)
            done = True
        else:
            out.append(e)
    if not done:
        out.append(entry)
    return out


def find(items, entry_id):
    return next((e for e in items or [] if e.get("id") == entry_id), None)


def printed(recorded, items, as_of=None):
    """The expiry a record prints on `as_of`: the extension's note
    ("DATE, extended from ORIGINAL, approved by NAME on DATE") when one is
    in force, else the date in force."""
    e = in_force_entry(items, as_of)
    return note(e) if e is not None else (recorded or u"")


def label_values(items):
    """The label fields of an extended lot: {"exp_original": the date before
    the first extension, "extended": MARK}; {} when none is in force."""
    e = in_force_entry(items)
    if e is None:
        return {}
    return {"exp_original": _d(e.get("original_expiry") or e.get("from_expiry")), "extended": MARK}


def label_row(row, design_shows_extended):
    """A label's values for a design: one that does not place the
    "extended" field prints the mark after the expiry ("Exp DATE · ext."),
    as a design issued before the field was there."""
    if not row.get("extended") or design_shows_extended:
        return row
    return dict(row, exp=u"%s \u00b7 %s" % (row.get("exp") or u"", row["extended"]))


EDIT_LATER = u"%s may move earlier only, not past %s. Ask QA for an extension instead."
EDIT_CLEARED = u"%s cannot be cleared once recorded. Ask QA for an extension instead."


def edit_problems(fields, old, new, computed=()):
    """Why an edit of a lot's dates is refused: a recorded date (`fields`,
    [(key, label)], set before the edit and not in `computed`, a date the
    system assigned) may move earlier, as a correction, but never later
    and never be cleared: a later date comes only through an extension. A
    date set for the first time is free."""
    out = []
    for key, label in fields:
        was, now = _d((old or {}).get(key)), _d((new or {}).get(key))
        if not was or key in (computed or ()):
            continue
        if not now:
            out.append(EDIT_CLEARED % label)
        elif now > was:
            out.append(EDIT_LATER % (label, was))
    return out


def extension_for(items, expiry):
    """The extension a use recorded with this expiry was in date under: an
    entry approved (now approved or since withdrawn) whose new date is that
    expiry, the last approved; None when none."""
    exp, found = _d(expiry), None
    for e in items or []:
        if not isinstance(e, dict) or e.get("state") not in (APPROVED, WITHDRAWN):
            continue
        if not exp or _d(e.get("new_expiry")) != exp or not _d(e.get("approved_on")):
            continue
        if found is None or (_d(e.get("approved_on")), e.get("approved_at") or u"") >= \
                (_d(found.get("approved_on")), found.get("approved_at") or u""):
            found = e
    return found


def note(entry, show=None):
    """What a record prints of the extension in force:
    "2027-03-13, extended from 2026-09-13, approved by NAME on 2026-11-10";
    "" without one. `show(day)` formats a date (default: as stored)."""
    if not entry:
        return u""
    show = show or (lambda v: _d(v))
    return u"%s, extended from %s, approved by %s on %s" % (
        show(entry.get("new_expiry")), show(entry.get("original_expiry") or entry.get("from_expiry")),
        entry.get("approved_name") or entry.get("approved_by") or u"?", show(entry.get("approved_on")))
