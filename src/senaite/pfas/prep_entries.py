# -*- coding: utf-8 -*-
"""Preparation records: a recipe filled in.

A preparation record is one prep sitting of one recipe revision: the recipe
(id, revision, code, kind, name), who, when, the equipment, the parent lots
consumed, and the lots it made. It is numbered from the recipe's code and
the prep day. Making a record makes one Prepared Standard lot per row
(prepared_standards._save: pending acceptance, the record's parents, the
record's id) and writes the parents consumed to the usage ledger, so a
parent lot's Usage lists the preparations that used it.

A record is built from its recipe (prep_sitting.build) and stored once, on
the pfas_prepared_standards folder (ENTRIES_KEY, {record id: record}); lots
point to it, nothing is copied onto them.

    new_entry_id(existing_ids, code, day) -> "PDS-A-261105-01"
    entry_problems(entry, rows)           -> [message]
    review(entry, who, at, sign=None)     -> entry (refuses the preparer)
    verify(entry, status)                 -> None, or why its signatures fail
    record_hash(entry)                    -> sha256 hex of its content
    make(portal, entry, rows, who, at, sign=None, uids=None, held=None) -> (record id, [lot uid])
    held_in_ledger(record_id, record_hash) -> the id is signed for other content
    lot_uids(nonce, n)                    -> the lot uids a Make form's nonce gives
    sign_made(portal, request, record_id, record_hash, note) -> its signature cache
    signature_status(entry)               -> (its hash now, esig.signing.status)

`sign(record_id, record_hash)` signs the content (esig.signing) and returns
the display cache of the rows it wrote; the record keeps that cache under
"signatures", the ledger stays the truth. A refused signature raises
before anything is saved.
    load(portal) / save(portal, entries)
    list_entries(portal, recipe_id=None, kind=None, since=None, until=None)

Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import re
import uuid

from senaite.pfas.esig import canonical
# Verify's answers, one wording for every signed record
from senaite.pfas.esig.signing import CACHE_MISMATCH, CONTENT_CHANGED, NO_SIGNATURES, WITHDRAWN  # noqa: F401

ENTRIES_KEY = "senaite.pfas.prep_entries"
FOLDER = "pfas_prepared_standards"
LEDGER_STAGE = 0
# a preparation record is stored once and never revised: its signatures
# name revision 1
REVISION = 1


def new_entry_id(existing_ids, code, day):
    """"<recipe code>-<YYMMDD>-<nn>", numbered per code per day: one more
    than the highest that code holds that day (a gap is never refilled)."""
    prefix = u"%s-%s-" % (code, (day or u"").replace(u"-", u"")[2:8])
    pattern = re.compile(u"^%s(\\d+)$" % re.escape(prefix))
    taken = [int(m.group(1)) for m in (pattern.match(i or u"") for i in existing_ids or []) if m]
    return u"%s%02d" % (prefix, max(taken or [0]) + 1)


def entry_problems(entry, rows):
    out = [u"A parent lot is not in the inventory: %s." % k for k in entry.get("unknown_parents") or []]
    if not ((entry.get("recipe") or {}).get("code") or u"").strip():
        # a record is numbered from its recipe's code
        out.append(u"The recipe has no code: give it one on the Recipes page.")
    if not (entry.get("prepared_by") or u"").strip():
        out.append(u"Enter who prepared it.")
    if not (entry.get("prepared_date") or u"").strip():
        out.append(u"Enter the date it was prepared.")
    if not entry.get("parents"):
        out.append(u"Choose at least one parent lot.")
    if not rows:
        out.append(u"Add at least one lot made.")
    needs = (("title", u"the name"), ("lot_number", u"the lot number"),
             ("standard_type", u"the type"), ("storage_conditions", u"the storage conditions"),
             ("volume_prepared", u"the volume made"))
    for i, r in enumerate(rows or []):
        for key, what in needs:
            if not (u"%s" % (r.get(key) or u"")).strip():
                out.append(u"Row %d: enter %s." % (i + 1, what))
    return out


def review(entry, who, at, sign=None):
    """Mark the record reviewed by who; with `sign`, the review is signed
    first, so a refused signature reviews nothing."""
    if who and who == entry.get("made_by"):
        raise ValueError(u"The preparer cannot review their own entry.")
    if callable(sign):
        entry["signatures"] = merge_cache(entry.get("signatures"), sign(entry.get("id"), record_hash(entry)))
    entry["reviewed_by"], entry["reviewed_at"] = who, at
    return entry


def merge_cache(cached, rows):
    """The display cache with rows added, one per ledger seq
    (esig.signing.merge_cache)."""
    from senaite.pfas.esig import signing
    return signing.merge_cache(cached, rows)


# what a signature does not bind: the review, and the signatures themselves
_UNHASHED = ("reviewed_by", "reviewed_at", "signatures")


def record_hash(entry):
    """The sha256 hex of the record's canonical JSON, without its review and
    signatures: the stable content a signature binds to."""
    body = dict((k, v) for k, v in (entry or {}).items() if k not in _UNHASHED)
    return canonical.sha256_of(body)


ID_TAKEN = u"Another preparation already carries this record id: save again."
# the namespace of the lot uids a Make form's nonce gives (lot_uids)
_LOT_NS = uuid.UUID("5f0c8d3e-9a41-4b6e-8f27-3c1d2e4a6b70")


def lot_uids(nonce, n):
    """The uids of the n lots a Make form makes, from the nonce the form
    carries: the same form posted again (a retry after a conflict) names the
    same lots, so it signs the same content."""
    return [uuid.uuid5(_LOT_NS, (u"%s:%d" % (nonce, i)).encode("utf-8") if bytes is str
                       else u"%s:%d" % (nonce, i)).hex for i in range(n)]


def signature_status(entry, path=None):
    """(the record's hash now, esig.signing.status of its signatures read
    against it): what the card, Verify and the print all read."""
    from senaite.pfas.esig import signing
    current = record_hash(entry)
    return current, signing.status("preparation", entry["id"], current, path=path)


def held_in_ledger(record_id, record_hash_, path=None):
    """True when the signature ledger holds a row on record_id for other
    content: a Make that signed that id and was never saved. Such an id is
    numbered past (make's held), never signed again for another sitting; a
    row on this very content is a retry of this Make, which reuses it."""
    from senaite.pfas.esig import ledger
    return any(((r.get("entry") or {}).get("record_hash") != record_hash_)
               for r in ledger.for_record("preparation", record_id, path=path))


def sign_made(portal, request, record_id, record_hash_, note=u"", path=None):
    """Sign a record being made as its preparer; its display cache. A new
    record supersedes nothing: when the ledger already holds a live
    signature by someone else under this id (another preparation saved it
    first), the step is refused so the save takes the next id."""
    from senaite.pfas.esig import signing
    userid = signing.current_userid(request)
    st = signing.status("preparation", record_id, record_hash_, path=path)
    if [r for r in st["live"] if ((r.get("entry") or {}).get("signer") or {}).get("userid") != userid]:
        raise signing.SignatureRefused([ID_TAKEN])
    return signing.cache([signing.sign(portal, request, "preparation", record_id, REVISION, record_hash_,
                                       "preparer", note=note, auto_supersede=False, path=path)])


def verify(entry, st):
    """None when the record's signatures hold, else why not
    (esig.signing.verify_rows over the record's display cache)."""
    from senaite.pfas.esig import signing
    return signing.verify_rows(st, entry.get("signatures"))


def lot_data(entry, entry_id, row):
    """The Prepared Standard a row makes (prepared_standards._save data),
    pinned to the recipe revision that made it when there is one."""
    data = {
        "uid": None,
        "title": row.get("title") or u"",
        "lot_number": row.get("lot_number") or u"",
        "standard_type": row.get("standard_type") or u"",
        "prepared_by": entry.get("prepared_by") or u"",
        "prepared_date": entry.get("prepared_date") or u"",
        "expiry_date": row.get("expiry_date") or u"",
        "expiry_notes": u"",
        "storage_location": row.get("storage_location") or entry.get("storage_location") or u"",
        "storage_conditions": row.get("storage_conditions") or u"",
        "volume_prepared": row.get("volume_prepared") or u"",
        "notes": row.get("notes") or u"",
        "parent_reagents": list(entry.get("parents") or []),
        "analyte_concentrations": list(row.get("analyte_concentrations") or []),
        "equipment": list(entry.get("equipment") or []),
        "entry_id": entry_id,
    }
    if row.get("recipe"):
        data["recipe"] = dict(row["recipe"])
    return data


def ledger_rows(entry):
    return [{"from_inventory": True, "inventory_uid": p.get("uid"), "lot": p.get("lot"),
             "kind": p.get("kind") or u"reagent", "name": p.get("name") or u"",
             "role": u"Parent",
             "qty_used": (u"%s %s" % (p.get("qty") or u"", p.get("unit") or u"")).strip()}
            for p in entry.get("parents") or []]


# ── storage (Zope) ───────────────────────────────────────────────────────────

def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal[FOLDER])


def load(portal):
    raw = _ann(portal).get(ENTRIES_KEY)
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def save(portal, entries):
    _ann(portal)[ENTRIES_KEY] = json.dumps(entries, sort_keys=True)


def list_entries(portal, recipe_id=None, kind=None, since=None, until=None):
    """The records, newest first: of one recipe, of one kind, in a date range."""
    out = [e for e in load(portal).values()
           if (not recipe_id or (e.get("recipe") or {}).get("id") == recipe_id)
           and (not kind or (e.get("recipe") or {}).get("kind") == kind)
           and (not since or (e.get("prepared_date") or u"") >= since)
           and (not until or (e.get("prepared_date") or u"") <= until)]
    return sorted(out, key=lambda e: (e.get("prepared_date") or u"", e.get("id") or u""), reverse=True)


def make(portal, entry, rows, who, at, _save=None, ledger_path=None, sign=None, uids=None, held=None):
    """Store the record, make its lots, write its parents to the ledger.
    Refuses (ValueError) a record with problems. With `sign`, the record's
    content is signed before any lot, the record or a usage row is saved:
    each lot's uid is chosen first, so the signed content names the lots.
    uids: the lot uids to use, in row order (lot_uids of the form's nonce,
    or the ids a seed pins); new ones when not given. held(record_id,
    record_hash): True when an id is taken outside the records
    (held_in_ledger); the record is numbered past it."""
    problems = entry_problems(entry, rows)
    if problems:
        raise ValueError(u" ".join(problems))
    if _save is None:
        from senaite.pfas.browser.prepared_standards import _save
    entries = load(portal)
    code = entry["recipe"]["code"]
    if uids is None:
        uids = [uuid.uuid4().hex for _r in rows]
    uids = list(uids)
    if len(uids) != len(rows):
        raise ValueError(u"%d lots, %d lot ids." % (len(rows), len(uids)))
    taken = list(entries)
    for _n in range(100):
        entry_id = new_entry_id(taken, code, entry.get("prepared_date"))
        if entry_id in entries:
            # a record id names one sitting: never overwrite one
            raise ValueError(u"The record %s already exists." % entry_id)
        lots = [dict(lot_data(entry, entry_id, r), uid=uid) for r, uid in zip(rows, uids)]
        body = dict((k, v) for k, v in entry.items() if k != "unknown_parents")
        stored = dict(body, id=entry_id, made_by=who, made_at=at, lots=uids,
                      rows=[dict(r) for r in rows], reviewed_by=u"", reviewed_at=u"")
        if not (callable(held) and held(entry_id, record_hash(stored))):
            break
        # signed for another sitting that was never saved: a gap, never refilled
        taken.append(entry_id)
    else:
        raise ValueError(u"No free record id for %s on %s." % (code, entry.get("prepared_date")))
    entry = body
    if callable(sign):
        stored["signatures"] = sign(entry_id, record_hash(stored))
    for uid, data in zip(uids, lots):
        # the signed content names these uids: a lot saved under another
        # would leave the signature on a record that does not exist
        if _save(portal, data) != uid:
            raise RuntimeError(u"Lot %s was not saved under its own id." % data.get("lot_number"))
    entries[entry_id] = stored
    save(portal, entries)
    from senaite.pfas import inventory_ledger as led
    led.record_stage(ledger_path, u"prep:%s" % entry_id, entry_id, LEDGER_STAGE,
                     u"Prep %s" % code, ledger_rows(entry), who, at)
    return entry_id, uids
