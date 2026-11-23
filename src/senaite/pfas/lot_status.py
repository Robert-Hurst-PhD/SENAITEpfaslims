# -*- coding: utf-8 -*-
"""A reagent or prepared lot is accepted before use.

A new lot starts "pending" (Pending acceptance). Accepting it records who,
when, how (a passing method blank for a reagent, a comparison against a lot
already fit for use for a standard) and the evidence, and makes it active. A
lot the reviewer rejects is quarantined with who, when and why; a manager
releases or discards it. An existing lot keeps its status (initial_status).

    initial_status(is_new)                      -> "pending" or None
    verify(status, who, at, how, evidence)      -> ("active", record)
    reject(status, who, at, why)                -> ("quarantine", record)
    status_change_problem(current, new, is_manager) -> why a manual status
                                                    change is refused, or ""
    review_lot(status, action, who, at, form)   -> (new status, annotation key,
                                                    record): the reviewer's
                                                    approve / reject in Data Review

The records are stored on the lot object under VERIFY_KEY / QUARANTINE_KEY.
Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

ACTIVE = u"active"
PENDING = u"pending"
QUARANTINE = u"quarantine"

LABELS = {PENDING: u"Pending acceptance", QUARANTINE: u"Quarantine", ACTIVE: u"Active"}
HOW = ((u"method_blank", u"Method blank"), (u"comparison", u"Comparison with a fit-for-use lot"))

VERIFY_KEY = "senaite.pfas.lot.verification"
QUARANTINE_KEY = "senaite.pfas.lot.quarantine"


def initial_status(is_new):
    """The status a lot starts with: a new lot waits for its acceptance;
    an existing lot keeps the status it has (None)."""
    return PENDING if is_new else None


def verify(status, who, at, how, evidence):
    if status != PENDING:
        raise ValueError(u"Only a lot pending acceptance can be accepted.")
    if how not in [k for k, _l in HOW]:
        raise ValueError(u"Say how the lot was accepted: a method blank or a comparison.")
    evidence = (evidence or u"").strip()
    if not evidence:
        raise ValueError(u"Name the blank or the lot it was compared against.")
    return ACTIVE, {"by": who, "at": at, "how": how, "evidence": evidence}


def status_change_problem(current, new, is_manager):
    """A status set by hand never skips acceptance, never makes a lot
    pending, and only a manager releases a quarantined lot."""
    if new == PENDING and current != PENDING:
        return u"A lot is pending acceptance only when it is made."
    if current == PENDING and new == ACTIVE:
        return u"Accept the lot to make it active: it is pending acceptance."
    if current == QUARANTINE and new != QUARANTINE and not is_manager:
        return u"Only a manager can release a quarantined lot."
    return u""


def matches_filter(status, wanted):
    """A list's status filter: "active" also shows lots pending acceptance
    (a new lot stays in view until accepted); "" shows every status."""
    if not wanted:
        return True
    if wanted == ACTIVE:
        return status in (ACTIVE, PENDING)
    return status == wanted


def review_lot(status, action, who, at, form):
    """The reviewer's approve_lot / reject_lot on a lot's node."""
    form = form or {}
    if action == u"approve_lot":
        st, rec = verify(status, who, at, form.get("how"), form.get("evidence"))
        return st, VERIFY_KEY, rec
    if action == u"reject_lot":
        st, rec = reject(status, who, at, form.get("why"))
        return st, QUARANTINE_KEY, rec
    raise ValueError(u"Unknown lot action.")


def reviewable(unresolved, uid, kind):
    """The lot (uid, kind) is one the traceability check names as pending
    acceptance: the only lots its approve / reject act on."""
    return any(u.get("pending") and u.get("uid") == uid and u.get("kind") == kind
               for u in unresolved or [] if uid)


def rejected_after_use(record, used_on):
    """A lot rejected at review (its QUARANTINE_KEY record) on or after the
    day it was used, or with the use day unknown."""
    import json
    try:
        rec = json.loads(record) if record else None
    except ValueError:
        rec = None
    if not rec:
        return False
    used_on = (used_on or u"")[:10]
    return not used_on or (rec.get("at") or u"")[:10] >= used_on


def reject(status, who, at, why):
    why = (why or u"").strip()
    if not why:
        raise ValueError(u"Say why the lot is rejected.")
    return QUARANTINE, {"by": who, "at": at, "why": why}
