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
KINDS = ("backup", "restore", "restore_test", "method_restore", "prune", "store_backup")
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


# ── the status page: one line, four figures ─────────────────────────────────

def stamp(value):
    """A recorded stamp ("2026-11-06T08:43:00") as the backup tool's host
    clock wrote it, to the minute: "2026-11-06 08:43"."""
    value = value or u""
    return u"%s %s" % (value[:10], value[11:16]) if len(value) > 10 else value


def status_line(sm, st):
    """The one line that says whether backups are working; tone is is-bad,
    is-warn or is-ok."""
    failed = sm["last_failed"]
    if failed:
        why = u", ".join(failed.get("failures") or []) or failed.get("note") or u""
        return {"tone": u"is-bad", "text": u"Last backup failed %s%s" % (
            stamp(failed.get("ended")), u": %s" % why if why else u"")}
    if sm["restore_test_due"]:
        return {"tone": u"is-warn", "text": u"The restore test is due."}
    if not sm["last_ok"]:
        return {"tone": u"is-warn", "text": u"No backup has run yet."}
    return {"tone": u"is-ok", "text": u"Backups are running."}


def figures(sm, st, run_at, label_of):
    """The four figures: (label, value, detail, flagged). `label_of` names an
    event's level."""
    failed = sm["last_failed"]
    done = sorted(sm["last_ok"].values(), key=lambda e: e.get("ended") or u"")
    last = failed or (done[-1] if done else None)
    if last:
        when = stamp(last.get("ended"))
        detail = u"%s, %s" % (when, label_of(last) or last.get("level") or u"")
        first = (u"Failed" if failed else u"Done", detail.rstrip(u", "), bool(failed))
    else:
        first = (u"None yet", u"", False)
    nxt = (u"Scheduled" if st.get("timers") is True else u"Not scheduled",
           u"Set for %s every night" % run_at if run_at else u"", False)
    free = st.get("free_gb")
    test, due = sm["last_restore_test"], sm["restore_test_due"]
    full = sm["last_ok"].get("full_install")
    return [
        (u"Last backup",) + first,
        (u"Next backup",) + nxt,
        (u"Free space", (u"%.0f GB" % free) if free is not None else u"\u2014", u"At the destination", False),
        (u"Restore test", u"Due" if due else (test["ended"][:10] if test else u"Never"),
         u"Last full install: %s" % (full["ended"][:10] if full else u"none"), bool(due)),
    ]


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
