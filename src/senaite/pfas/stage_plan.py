# -*- coding: utf-8 -*-
"""The stage plan an extraction follows.

An extraction session records each completed stage under the stage's
position ("1", "2", ...). The position only means something against the
list of stages it was taken from, so a session keeps its own copy of that
list -- the plan -- taken when the session starts:

    session["plan"] = {"method_id", "revision", "fingerprint", "taken_at",
                       "stages": [the method's extraction stages, as they were]}

Everything that reads a session's stages reads them through stages_for():
the session's plan when it has one, else the method's stages now (a session
started before plans existed). A manager may then reorder, rename or
redesign the method's stages without moving any record of an extraction
already started, and every record names the method revision it was made
under.

Pure, standard library only. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy

PLAN = "plan"


def _ordered(stages):
    return sorted([s for s in stages or [] if isinstance(s, dict)],
                  key=lambda s: s.get("order", 0))


def take(profile, method_id, revision=None, fingerprint=u"", taken_at=u""):
    """A plan from the method's profile as it is now."""
    return {"method_id": method_id or u"", "revision": revision,
            "fingerprint": fingerprint or u"", "taken_at": taken_at or u"",
            "stages": copy.deepcopy(_ordered((profile or {}).get("extraction_stages")))}


def has_plan(session):
    plan = (session or {}).get(PLAN)
    return isinstance(plan, dict) and isinstance(plan.get("stages"), list)


def stages_for(session, profile):
    """The stages this session's records refer to, in order."""
    if has_plan(session):
        return _ordered(session[PLAN]["stages"])
    return _ordered((profile or {}).get("extraction_stages"))


def revision_of(session):
    """(revision number or None, fingerprint) the session was started under."""
    plan = (session or {}).get(PLAN) or {}
    return plan.get("revision"), plan.get("fingerprint") or u""


def ensure(session, profile, method_id, revision=None, fingerprint=u"", taken_at=u""):
    """Give a session without a plan one from the profile now; True when one
    was added. A session that has a plan keeps it."""
    if session is None or has_plan(session):
        return False
    session[PLAN] = take(profile, method_id, revision, fingerprint, taken_at)
    session[PLAN]["backfilled"] = True
    return True


def drift(session, profile):
    """What changed in the method's stages since the session's plan was
    taken, as short sentences (empty when nothing did, or no plan)."""
    if not has_plan(session):
        return []
    then = dict((s.get("id") or u"%s" % s.get("order"), s) for s in stages_for(session, None))
    now = dict((s.get("id") or u"%s" % s.get("order"), s)
               for s in _ordered((profile or {}).get("extraction_stages")))
    out = []
    for key, s in sorted(then.items(), key=lambda kv: kv[1].get("order", 0)):
        n = now.get(key)
        if n is None:
            out.append(u"Stage %s (%s) is no longer in the method." % (s.get("order"), s.get("name") or key))
        elif n.get("order") != s.get("order"):
            out.append(u"%s moved from stage %s to %s." % (s.get("name") or key, s.get("order"), n.get("order")))
    for key, n in sorted(now.items(), key=lambda kv: kv[1].get("order", 0)):
        if key not in then:
            out.append(u"%s was added as stage %s." % (n.get("name") or key, n.get("order")))
    return out
