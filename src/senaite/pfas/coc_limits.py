# -*- coding: utf-8 -*-
"""What a client may do with chain of custody records (Lab Settings, System).

    daily_cap        how many new CoCs one client may start in a lab day
    unsubmitted_days how many days a digital CoC may stay open, never
                     submitted, before it is removed
    unsubmitted_paper_days  the same for a paper CoC (the kit CoC the lab
                     prints, filled in on paper)

The cap and the digital days are unset until a manager enters them: unset,
there is no cap and no digital CoC is removed. The paper days read
PAPER_DAYS_DEFAULT until a manager enters another number. Only a CoC that is
still open, holds no samples and carries no receipt, scan, transcription or
transfer is ever removed; a submitted or received CoC never is. Each removal
is kept in Configuration History. The worker's tick
(@@pfas-notice-reminders) runs the removal.

Pure helpers first; the store and the removal import Plone lazily.
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
from datetime import datetime, timedelta

KEY = "senaite.pfas.coc_limits"
FIELDS = ("daily_cap", "unsubmitted_days", "unsubmitted_paper_days")
HISTORY_STORE = u"coc_removed"
# the days a paper CoC is kept unsubmitted while no other number is entered
PAPER_DAYS_DEFAULT = 60


def settings(stored):
    stored = stored or {}
    return dict((k, stored.get(k)) for k in FIELDS)


def paper_days(limits):
    """The days a paper CoC is kept unsubmitted: the number entered, else
    the default."""
    return (limits or {}).get("unsubmitted_paper_days") or PAPER_DAYS_DEFAULT


def from_form(form):
    """(settings, errors) from the System form; blank is unset."""
    out, errors = {}, []
    for field, name, words in (
            ("daily_cap", "coc_daily_cap", u"The daily cap is a whole number of CoCs, 1 or more."),
            ("unsubmitted_days", "coc_unsubmitted_days",
             u"The days an unsubmitted CoC is kept is a whole number, 1 or more."),
            ("unsubmitted_paper_days", "coc_unsubmitted_paper_days",
             u"The days an unsubmitted paper CoC is kept is a whole number, 1 or more.")):
        raw = (form.get(name) or u"").strip()
        value = None
        if raw:
            try:
                value = int(raw)
                if value < 1:
                    raise ValueError(raw)
            except ValueError:
                value = None
                errors.append(words)
        out[field] = value
    return out, errors


def as_saved(values, stored):
    """The limits to store from the form's `values`: the paper days shown at
    their default and never entered stay unset, so a save that changes
    nothing records nothing."""
    out = dict(values)
    if (out.get("unsubmitted_paper_days") == PAPER_DAYS_DEFAULT
            and (stored or {}).get("unsubmitted_paper_days") is None):
        out["unsubmitted_paper_days"] = None
    return out


def cap_reached(records, client_uid, day, cap, day_of):
    """Has this client started `cap` CoCs on lab day `day`? `day_of(created_at)`
    names the lab day a record was made on. No cap is never reached."""
    if not cap:
        return False
    made = [r for r in records or ()
            if r.get("client_uid") == client_uid and day_of(r.get("created_at")) == day]
    return len(made) >= int(cap)


def removable(record):
    """May this CoC be removed for being left unsubmitted? Only one that is
    open and has gone nowhere: no samples, receipt, scan, transcription or
    transfer. Digital or paper alike; each has its own period."""
    r = record or {}
    return (r.get("status") == u"open"
            and not r.get("samples") and not r.get("receipt") and not r.get("scan")
            and not r.get("transcribed") and not r.get("transfers"))


def period(record, days, paper):
    """The days this CoC may stay unsubmitted: a paper CoC's `paper`, any
    other's `days`; None where its period is unset."""
    return paper if (record or {}).get("origin") == u"paper" else days


def expired(records, days, now, paper=None):
    """The numbers of the CoCs left unsubmitted longer than their period at
    `now` (a naive UTC datetime): `days` for a digital CoC, `paper` for a
    paper one; none of a kind whose period is unset."""
    out = []
    for r in records or ():
        if not removable(r):
            continue
        keep = period(r, days, paper)
        if not keep:
            continue
        limit = now - timedelta(days=int(keep))
        try:
            made = datetime.strptime((r.get("created_at") or u"")[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        if made <= limit:
            out.append(r["number"])
    return out


def history_note(record, days):
    return (u"Removed after %d days unsubmitted; started by %s for %s on %s." % (
        int(days), record.get("created_by") or u"", record.get("client") or u"",
        (record.get("created_at") or u"")[:10]))


# ── storage (Plone) ─────────────────────────────────────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def load(portal):
    try:
        return settings(json.loads(_ann(portal).get(KEY) or "{}"))
    except ValueError:
        return settings({})


def save(portal, values):
    _ann(portal)[KEY] = json.dumps(settings(values), sort_keys=True)


def cap_for(portal, client_uid, now_text):
    """(reached, cap) for a client about to start a CoC at `now_text`."""
    from senaite.pfas import coc_records, lab_time
    cap = load(portal).get("daily_cap")
    if not cap:
        return False, None

    def day_of(at):
        return lab_time.show(at, fmt=u"%Y-%m-%d")

    return cap_reached(coc_records.for_client(portal, client_uid), client_uid,
                       day_of(now_text), cap, day_of), cap


def remove_unsubmitted(portal, now=None):
    """Remove every CoC left unsubmitted past its period (digital or paper);
    returns their numbers. Each removal is written to Configuration History in the same
    transaction as the removal."""
    from senaite.pfas import coc_records, config_history
    limits = load(portal)
    days, paper = limits.get("unsubmitted_days"), paper_days(limits)
    now = now or datetime.utcnow()
    records = [r for r in (coc_records.load(portal, n) for n in coc_records.numbers(portal)) if r]
    gone = expired(records, days, now, paper)
    by_number = dict((r["number"], r) for r in records)
    for number in gone:
        rec = by_number[number]
        config_history.append(portal, {
            "store": HISTORY_STORE, "key": number, "who": u"system", "label": u"CoC %s" % number,
            "changes": [], "note": history_note(rec, period(rec, days, paper))})
        coc_records.delete(portal, number)
    return gone
