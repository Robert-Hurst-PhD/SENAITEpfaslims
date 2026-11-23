# -*- coding: utf-8 -*-
"""Backup settings set in Configuration > Backups.

The backup tool (tools/backup/pfasbackup.py) runs on the server; the LIMS
only records what a site administrator asks for. Each change -- the
destination, the time the backups run, the days old backups are removed,
the public keys they are encrypted to, where the system snapshots and the
store backups are kept -- is saved with a reason and waits;
at its next run the tool reads the waiting changes, applies each it can
(a destination must be mounted and writable; at least two public keys, no
private key) and reports back, applied or refused with its reason. One site
administrator and the change log, no second approver. A
waiting change can be withdrawn; a newer change to the same setting
replaces it.

    state = {"current": {dest, run_at, prune {days, at}, recipients [{fpr, holder}],
                         snapshots, store_backups},
             "changes": [{id, at, by, setting, before, after, reason,
                          state waiting|applied|refused|withdrawn|replaced,
                          applied_at, why}]}

    request(state, setting, value, reason, who, at) -> (state, error)
    withdraw(state, change_id, who, at)           -> (state, error)
    waiting(state) / requested(state)
    report(state, results, at)                    -> state
    from_status(state, status)                    -> state (what the tool reports in force)
    describe(setting, value)                      -> text

Pure, plus the annotation shell. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json
import re

KEY = "senaite.pfas.backup_settings"
SETTINGS = ((u"dest", u"Destination"), (u"run_at", u"Backup runs at"),
            (u"prune", u"Old backups removed on"), (u"recipients", u"Encrypted to"),
            (u"snapshots", u"System snapshots kept in"), (u"store_backups", u"Store backups kept in"))
# the settings that name a folder on the server: the tool applies one only
# where it is mounted and writable
PATHS = (u"dest", u"snapshots", u"store_backups")
LABEL = dict(SETTINGS)
DAYS = (u"Mon", u"Tue", u"Wed", u"Thu", u"Fri", u"Sat", u"Sun")
MIN_KEYS = 2
_HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_FPR = re.compile(r"^[0-9A-Fa-f]{40}$")


def problem(setting, value):
    if setting == u"dest":
        return u"" if (value or u"").startswith(u"/") else u"The destination is a full path, from /."
    if setting in PATHS:
        return u"" if (value or u"").startswith(u"/") else u"The folder is a full path, from /."
    if setting == u"run_at":
        return u"" if _HHMM.match(value or u"") else u"Give the time as HH:MM."
    if setting == u"prune":
        v = value or {}
        if not [d for d in v.get("days") or [] if d in DAYS]:
            return u"Choose at least one day."
        return u"" if _HHMM.match(v.get("at") or u"") else u"Give the time as HH:MM."
    if setting == u"recipients":
        for k in value or []:
            if not _FPR.match(k.get("fpr") or u""):
                return u"%s: a key fingerprint is 40 hexadecimal characters." % (k.get("holder") or u"A key")
        if len(set((k.get("fpr") or u"").upper() for k in value or [])) < MIN_KEYS:
            return u"Backups are encrypted to at least two public keys."
        return u""
    return u"No such setting."


def waiting(state):
    return [c for c in (state or {}).get("changes") or [] if c.get("state") == u"waiting"]


def requested(state):
    """The settings as they will be once every waiting change applies."""
    out = copy.deepcopy((state or {}).get("current") or {})
    for c in waiting(state):
        out[c["setting"]] = copy.deepcopy(c["after"])
    return out


def request(state, setting, value, reason, who, at):
    state = copy.deepcopy(state or {"current": {}, "changes": []})
    if not (reason or u"").strip():
        return state, u"Give the reason for the change."
    why = problem(setting, value)
    if why:
        return state, why
    if setting == u"prune":
        value = {"days": [d for d in DAYS if d in (value or {}).get("days")], "at": value["at"]}
    if requested(state).get(setting) == value:
        return state, u"That is the setting already."
    for c in state["changes"]:
        if c.get("state") == u"waiting" and c.get("setting") == setting:
            c["state"] = u"replaced"
    state["changes"].append({"id": u"C%d" % (len(state["changes"]) + 1), "at": at, "by": who,
                             "setting": setting, "before": copy.deepcopy(state["current"].get(setting)),
                             "after": copy.deepcopy(value), "reason": reason.strip(), "state": u"waiting"})
    return state, u""


def withdraw(state, change_id, who, at):
    state = copy.deepcopy(state)
    for c in state.get("changes") or []:
        if c.get("id") == change_id:
            if c.get("state") != u"waiting":
                return state, u"Only a waiting change is withdrawn."
            c.update(state=u"withdrawn", withdrawn_by=who, withdrawn_at=at)
            return state, u""
    return state, u"No such change."


def report(state, results, at):
    """The tool's results: [{"id", "status": applied|refused, "why"}]."""
    state = copy.deepcopy(state)
    by_id = dict((c["id"], c) for c in state.get("changes") or [])
    for r in results or []:
        c = by_id.get(r.get("id"))
        if c is None or c.get("state") != u"waiting":
            continue
        if r.get("status") == u"applied":
            c.update(state=u"applied", applied_at=at)
            state.setdefault("current", {})[c["setting"]] = copy.deepcopy(c["after"])
        else:
            c.update(state=u"refused", applied_at=at, why=r.get("why") or u"")
    return state


def from_status(state, status):
    """What is in force is what the tool reports after a run: its
    destination, keys and schedule (a key keeps the holder's name it was
    given here)."""
    state = copy.deepcopy(state or {"current": {}, "changes": []})
    cur = state.setdefault("current", {})
    status = status or {}
    names = {}
    for k in (cur.get("recipients") or []) + [k for c in state.get("changes") or []
                                              if c.get("setting") == u"recipients" for k in c.get("after") or []]:
        if k.get("holder"):
            names[(k.get("fpr") or u"").upper()] = k["holder"]
    if status.get("destination"):
        cur["dest"] = status["destination"]
    if status.get("recipients") is not None:
        cur["recipients"] = [{"fpr": f, "holder": names.get((f or u"").upper()) or u"Key %s" % (f or u"")[-8:]}
                             for f in status["recipients"]]
    for k in (u"run_at", u"prune", u"snapshots", u"store_backups"):
        if status.get(k):
            cur[k] = status[k]
    return state


def describe(setting, value):
    if setting == u"run_at":
        return u"%s every night" % value if value else u"—"
    if setting == u"prune":
        v = value or {}
        days = [d for d in DAYS if d in (v.get("days") or [])]
        return u"%s at %s" % (u", ".join(days), v.get("at") or u"") if days else u"\u2014"
    if setting == u"recipients":
        return u", ".join(k.get("holder") or k.get("fpr") or u"" for k in value or []) or u"—"
    return value or u"—"


# ── storage (Plone) ───────────────────────────────────────────────────────

def load(portal):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(portal).get(KEY) or "{}") or {"current": {}, "changes": []}
    except (TypeError, ValueError):
        return {"current": {}, "changes": []}


def save(portal, state):
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import config_history
    config_history.track(portal, "backup_settings", "all", lambda: load(portal), label=u"Backup settings")
    IAnnotations(portal)[KEY] = json.dumps(state, sort_keys=True)
