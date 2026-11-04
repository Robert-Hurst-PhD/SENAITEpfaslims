# -*- coding: utf-8 -*-
"""The backup log: every backup, restore, restore test and method restore,
recorded in the LIMS. The backup tool
(tools/backup/pfasbackup.py) writes each event through
tools/backup/record_event.py, also into a stack it has just restored; each
event is also a Configuration History entry (store "backup").

An event: {"kind", "status", "level", "point", "chain", "started", "ended",
"who", "bytes", "parts", "failures", "note", "destination"}.

    event_problems(event)   -> [why it cannot be recorded]
    summary(events, today)  -> {"last_ok": {level: event}, "last_failed",
                                "last_restore_test", "restore_test_due"}
    load(portal) / record(portal, event)

The quarterly restore test is due once the last passed one is over
RESTORE_TEST_DAYS old (none yet, once anything has been backed up).
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json

KEY = "senaite.pfas.backup_log"
KINDS = ("backup", "restore", "restore_test", "method_restore", "prune")
LEVELS = ("full_install", "quarterly", "daily")
STATUSES = ("ok", "failed")
RESTORE_TEST_DAYS = 100


def event_problems(event):
    out = []
    if event.get("kind") not in KINDS:
        out.append(u"unknown kind: %s" % event.get("kind"))
    if event.get("status") not in STATUSES:
        out.append(u"unknown status: %s" % event.get("status"))
    if event.get("kind") == "backup" and event.get("level") not in LEVELS:
        out.append(u"unknown level: %s" % event.get("level"))
    if not (event.get("ended") or u"").strip():
        out.append(u"no end time")
    return out


def label(event):
    """"Backup, daily: ok" -- the Configuration History entry's label."""
    what = (event.get("kind") or u"").replace(u"_", u" ").capitalize()
    if event.get("level"):
        what += u", " + event["level"].replace(u"_", u" ")
    return u"%s: %s" % (what, event.get("status"))


def _d(value):
    return datetime.datetime.strptime((value or u"")[:10], "%Y-%m-%d").date()


# what each level holds, when it is made and how long it is kept: as
# tools/backup/levels.py sets them (tests/test_backup_log.py holds the two
# together)
LEVEL_ROWS = [
    {"level": "full_install", "label": u"Full install",
     "holds": u"The whole system and a full copy of the data. Starts a chain.",
     "when": u"On demand", "kept": u"5 years"},
    {"level": "quarterly", "label": u"Full", "holds": u"A full copy of the data. Starts a chain.",
     "when": u"First day of each quarter", "kept": u"5 years"},
    {"level": "daily", "label": u"Incremental",
     "holds": u"What changed since the previous backup of its chain. Needs the full and every earlier incremental.",
     "when": u"Every other day", "kept": u"90 days, a whole chain at a time"},
]
_LEVEL_LABEL = dict((r["level"], r["label"]) for r in LEVEL_ROWS)


def level_label(event, events):
    """A backup's level as the Runs table says it: "Full", "Full install",
    "Incremental 6" (its place on its chain); a failed incremental has none."""
    if event.get("kind") != "backup":
        return u""
    label = _LEVEL_LABEL.get(event.get("level"), event.get("level") or u"")
    if event.get("level") != "daily" or event.get("status") != "ok":
        return label
    chain = [e for e in sorted(events or [], key=lambda e: e.get("ended") or u"")
             if e.get("kind") == "backup" and e.get("level") == "daily" and e.get("status") == "ok"
             and e.get("chain") == event.get("chain")]
    n = [e.get("point") for e in chain].index(event.get("point")) + 1 if event in chain else 0
    return u"%s %d" % (label, n) if n else label


def summary(events, today):
    events = sorted(events or [], key=lambda e: e.get("ended") or u"")
    last_ok, last_failed, last_test, any_backup = {}, None, None, False
    for e in events:
        if e.get("kind") == "backup":
            if e.get("status") == "ok":
                any_backup = True
                last_ok[e.get("level")] = e
                last_failed = None             # a later success clears it
            else:
                last_failed = e
        elif e.get("kind") == "restore_test" and e.get("status") == "ok":
            last_test = e
    due = any_backup and (last_test is None or
                          (_d(today) - _d(last_test["ended"])).days > RESTORE_TEST_DAYS)
    if not any_backup and last_test is None:
        due = False
    return {"last_ok": last_ok, "last_failed": last_failed, "last_restore_test": last_test,
            "restore_test_due": bool(due)}


# ── storage (Zope) ───────────────────────────────────────────────────────────

def load(portal):
    from zope.annotation.interfaces import IAnnotations
    try:
        return [json.loads(e) for e in IAnnotations(portal).get(KEY) or []]
    except ValueError:
        return []


def record(portal, event):
    """Keep the event and add its Configuration History entry. Refuses
    (ValueError) an event with problems."""
    problems = event_problems(event)
    if problems:
        raise ValueError(u"; ".join(problems))
    from persistent.list import PersistentList
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import config_history
    ann = IAnnotations(portal)
    if KEY not in ann:
        ann[KEY] = PersistentList()
    ann[KEY].append(json.dumps(event, sort_keys=True))
    config_history.append(portal, {
        "store": "backup", "key": event["kind"], "who": event.get("who") or u"system",
        "label": label(event),
        "changes": [], "note": u"%s%s" % (event.get("point") or u"",
                                          (u": " + u"; ".join(event.get("failures") or []))
                                          if event.get("failures") else u"")})
    return event
