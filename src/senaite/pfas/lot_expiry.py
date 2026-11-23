# -*- coding: utf-8 -*-
"""When a lot is out of date: the one date comparison, and the gate on a
preparation that consumes lots.

A lot is in date on day D when its expiry is on or after D: a lot expiring
on the day it is used is still in date. An unknown expiry or an unknown day
is not evidence of expiry, so it answers False here; each caller says
separately what an undated lot means for it.

A preparation may use a lot that was out of date on the day it was made
only with a reason. The reason is kept on that parent in the record's
parents (so the preparer signs it with the record) and printed on it:

    expired_on(expiry, day)                -> True when expiry < day
    shown_expiry(expiry, no_expiry)        -> the printed expiry, "No expiry"
                                              for a lot whose category has none
    source_after_save(old, new, old_source, assigned_now)
                                           -> where a reagent's expiry came from
    assigned_by_note(rec) / migrated_source(rec)
                                           -> the one-off migration's rule
    gate(parents, expiries, day, reason)   -> (parents with the reason kept, [problem])
    gate_edit(posted, stored, expiries, day, reason)
                                           -> gate for the parents an edit adds;
                                              the parents already on the lot
                                              keep what they carry
    stage_reasons(session, day_of)         -> {lot: the stage's deviation note}
                                              for each lot a stage used out
                                              of date with a note
    statement(parents, day)                -> the printed line, or "" (parents
                                              may carry their "expiry" in force)

`parents` are the record's parent dicts ("lot", "name"); `expiries` their
effective expiries (YYYY-MM-DD) in the same order, as the inventory has them.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from datetime import date, datetime

# the keys a parent record keeps when it was used out of date
EXPIRED_KEY = "expired_at_use"
REASON_KEY = "expired_reason"
# what labels and records print for a lot in a category with no expiry (a
# lab setting on the category, vocab_store FLAGS): such a lot never expires,
# whatever date it carries, so its expiry in force is ""
NO_EXPIRY = u"No expiry"


def shown_expiry(expiry, no_expiry):
    """What a label or record prints for a lot's expiry."""
    return NO_EXPIRY if no_expiry else (expiry or u"")


# Where a reagent lot's expiry_date came from, kept on the lot under
# SOURCE_KEY: ENTERED (typed or scanned) or ASSIGNED (the default period from
# receipt, or the opened shelf life, set by a save). An assigned date is not
# a recorded one: a supplier's date may still replace it (the edit rule).
SOURCE_KEY = "senaite.pfas.reagent.expiry_source"
ENTERED, ASSIGNED = u"entered", u"assigned"
_ASSIGNED_NOTE = r"Expiry assigned from global default \((\d+) days from receipt\)"


def source_after_save(old_expiry, new_expiry, old_source, assigned_now):
    """The source a save records: ASSIGNED when the save assigned the date;
    for a date posted, the source it had when it is the same date, else
    ENTERED; "" when the lot has no expiry_date."""
    if assigned_now:
        return ASSIGNED
    new = (u"%s" % (new_expiry or u""))[:10]
    if not new:
        return u""
    if old_source and new == (u"%s" % (old_expiry or u""))[:10]:
        return old_source
    return ENTERED


def assigned_by_note(rec):
    """The migration's rule for a lot saved before the source was kept: its
    expiry_date was assigned when its notes carry "Expiry assigned from
    global default (N days from receipt)" and the date is exactly received
    plus N, with no manufacturer's expiry."""
    import re
    exp = (rec.get("expiry_date") or u"")[:10]
    if not exp or rec.get("manufacturer_expiry") or not rec.get("received_date"):
        return False
    m = re.search(_ASSIGNED_NOTE, rec.get("notes") or u"")
    if not m:
        return False
    received = _day(rec.get("received_date"))
    if received is None:
        return False
    from datetime import timedelta
    return (received + timedelta(days=int(m.group(1)))).isoformat() == exp


def migrated_source(rec):
    """The source the migration records for a lot that has none."""
    if not (rec.get("expiry_date") or u""):
        return u""
    return ASSIGNED if assigned_by_note(rec) else ENTERED


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime((u"%s" % (value or u""))[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def expired_on(expiry, day):
    """True when a lot with this expiry is out of date on `day`. Both may be
    dates or ISO strings; either unknown answers False."""
    exp, on = _day(expiry), _day(day)
    return exp is not None and on is not None and exp < on


def refusal(parent, expiry, day):
    return (u"Lot %s of %s expired on %s, before the preparation date %s. Enter the reason it is used, "
            u"or choose another lot." % (parent.get("lot") or u"?", parent.get("name") or u"the parent",
                                         (u"%s" % expiry)[:10], (u"%s" % day)[:10]))


def gate(parents, expiries, day, reason):
    """(parents, problems): a parent out of date on `day` is refused unless
    a reason is given; with one, that parent keeps its expiry at use and
    the reason. The parents in date are returned unchanged."""
    reason = (reason or u"").strip()
    out, problems = [], []
    expiries = list(expiries or [])
    for i, p in enumerate(parents or []):
        expiry = expiries[i] if i < len(expiries) else None
        if not expired_on(expiry, day):
            out.append(p)
        elif not reason:
            problems.append(refusal(p, expiry, day))
            out.append(p)
        else:
            kept = dict(p)
            kept[EXPIRED_KEY], kept[REASON_KEY] = (u"%s" % expiry)[:10], reason
            out.append(kept)
    return out, problems


def _same_parent(a, b):
    ua, ub = (a.get("uid") or u"").strip(), (b.get("uid") or u"").strip()
    if ua and ub:
        return ua == ub
    la, lb = (a.get("lot") or u"").strip(), (b.get("lot") or u"").strip()
    return bool(la) and la == lb


def gate_edit(posted, stored, expiries, day, reason):
    """(parents, problems) for an edit of a lot's parents: a parent already
    on the lot (same uid, else same lot number) keeps the expiry at use and
    the reason it was stored with and is not judged again; a parent the
    edit adds is judged as a preparation's (gate). `expiries` follow
    `posted`."""
    expiries = list(expiries or [])
    out, problems = [], []
    for i, p in enumerate(posted or []):
        was = next((s for s in stored or [] if _same_parent(p, s)), None)
        if was is not None:
            kept = dict(p)
            for key in (EXPIRED_KEY, REASON_KEY):
                if was.get(key):
                    kept[key] = was[key]
            out.append(kept)
            continue
        added, refused = gate([p], [expiries[i] if i < len(expiries) else None], day, reason)
        out.extend(added)
        problems.extend(refused)
    return out, problems


def stage_reasons(session, day_of):
    """{lot number: reason} for the lots an extraction's stages used out of
    date: at the bench the stage's deviation note is the reason. A lot is
    covered only by a stage whose row was out of date on that stage's day
    (`day_of(stage data)`) and that carries a note; the first such stage
    gives the reason."""
    out = {}
    stages = (session or {}).get("stages") or {}
    for order in sorted(stages, key=lambda o: (u"%s" % o).zfill(6)):
        data = stages[order] or {}
        note = (data.get("deviations") or u"").strip()
        if not note:
            continue
        day = day_of(data)
        for r in data.get("reagents") or []:
            lot = (r.get("lot") or u"").strip()
            if lot and expired_on(r.get("expiry"), day):
                out.setdefault(lot, note)
    return out


def statement(parents, day):
    """What a record prints about the parents it used out of date: each lot
    and its expiry, then the reason given. A parent kept with a reason is
    named with its expiry at use; a parent whose "expiry" (its expiry in
    force, when the caller resolved it) is before `day` and that carries no
    reason -- a record made before reasons were asked -- is named as having
    none, so an out-of-date use never prints as a clean one."""
    used, reasons = [], []
    for p in parents or []:
        if p.get(REASON_KEY):
            used.append(u"lot %s of %s expired %s" % (p.get("lot") or u"?", p.get("name") or u"the parent",
                                                      p.get(EXPIRED_KEY) or u"?"))
            if p[REASON_KEY] not in reasons:
                reasons.append(p[REASON_KEY])
        elif expired_on(p.get("expiry"), day):
            used.append(u"lot %s of %s expired %s, no reason recorded" % (
                p.get("lot") or u"?", p.get("name") or u"the parent", (u"%s" % p.get("expiry"))[:10]))
    if not used:
        return u""
    when = (u" before the preparation date %s" % (u"%s" % day)[:10]) if day else u""
    tail = (u". Reason: %s" % u" ".join(reasons)) if reasons else u"."
    return u"Used out of date%s: %s%s" % (when, u"; ".join(used), tail)
