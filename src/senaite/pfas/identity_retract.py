# -*- coding: utf-8 -*-
"""Results already filed on a SENAITE sample, retracted when an identity
correction takes their injection off Sample.

SENAITE retracts only a submitted result (to_be_verified). A result filed
on an open worksheet sits on an assigned analysis, so it is submitted and
then retracted: core keeps the retracted analysis with its value, shown as
Retracted on the sample, and adds a retest without a result to the same
worksheet. The correction's reason is added to the retracted analysis's
remarks. A result already retracted is skipped; one verified or published
is never retracted here (RetractRefused).

The workflow is handed in, as run_reject does: do(obj, transition) ->
True when the transition was made, state_of(obj) -> review state,
has_result(obj), note(obj, text). A refusal raises RetractRefused; the
caller aborts the transaction, so nothing is kept.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

# the states a filed result is retracted from, and the transitions it takes
STEPS = {"unassigned": ("submit", "retract"), "assigned": ("submit", "retract"),
         "to_be_verified": ("retract",)}
DONE = ("retracted",)

REFUSED_STATE = "{0} ({1}) is {2}: a released result is not retracted by a correction."
REFUSED_STEP = "SENAITE refused to {0} {1} ({2})."


class RetractRefused(ValueError):
    """A filed result could not be retracted; nothing is to be kept."""


def _uid(obj):
    return getattr(obj, "uid", None) or (obj.UID() if hasattr(obj, "UID") else "")


def _keyword(obj):
    kw = getattr(obj, "keyword", None)
    if kw is None and hasattr(obj, "getKeyword"):
        kw = obj.getKeyword()
    return kw or ""


def _value(obj):
    v = getattr(obj, "result", None)
    if v is None and hasattr(obj, "getResult"):
        v = obj.getResult()
    return "%s" % (v if v is not None else "")


def retract(analyses, do, state_of, has_result, note, reason):
    """Retract each filed analysis; returns [{"analysis", "keyword",
    "value", "from_state"}] of those retracted here."""
    out = []
    for an in analyses:
        state = state_of(an)
        if state in DONE or not has_result(an):
            continue
        steps = STEPS.get(state)
        if steps is None:
            raise RetractRefused(REFUSED_STATE.format(_uid(an), _keyword(an), state))
        rec = {"analysis": _uid(an), "keyword": _keyword(an), "value": _value(an), "from_state": state}
        for transition in steps:
            if not do(an, transition):
                raise RetractRefused(REFUSED_STEP.format(transition, _uid(an), _keyword(an)))
        note(an, "Retracted: %s" % (reason or ""))
        out.append(rec)
    return out
