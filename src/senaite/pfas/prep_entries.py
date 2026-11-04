# -*- coding: utf-8 -*-
"""Prep entries: the reagent and standards library's logbooks.

An FM-ENV-001 (solvent / reagent prep) or FM-ENV-002 (calibration standard
prep) entry is one prep sitting: who, when, the equipment, the parent lots
consumed, and the lots it made. Making an entry makes one Prepared Standard
lot per row (prepared_standards._save: pending verification, the entry's
parents, the entry's id) and writes the parents consumed to the usage
ledger, so a parent lot's Usage lists the preps that used it.

An entry is built from its recipe (prep_sitting.build) and stored once, on
the pfas_prepared_standards folder (ENTRIES_KEY, {entry id: entry}); lots
point to it, nothing is copied onto them.

    new_entry_id(existing_ids, form_code, day) -> "FM-ENV-002-261014-01"
    entry_problems(entry, rows)                -> [message]
    review(entry, who, at)                     -> entry (refuses the preparer)
    make(portal, entry, rows, who, at)         -> (entry id, [lot uid])
    load(portal) / save(portal, entries) / list_entries(portal, ...)

Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json

ENTRIES_KEY = "senaite.pfas.prep_entries"
FOLDER = "pfas_prepared_standards"
LEDGER_STAGE = 0


def new_entry_id(existing_ids, form_code, day):
    prefix = u"%s-%s-" % (form_code, (day or u"").replace(u"-", u"")[2:8])
    n = len([i for i in existing_ids or [] if (i or u"").startswith(prefix)]) + 1
    return u"%s%02d" % (prefix, n)


def entry_problems(entry, rows):
    out = [u"A parent lot is not in the inventory: %s." % k for k in entry.get("unknown_parents") or []]
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


def review(entry, who, at):
    if who and who == entry.get("made_by"):
        raise ValueError(u"The preparer cannot review their own entry.")
    entry["reviewed_by"], entry["reviewed_at"] = who, at
    return entry


def lot_data(entry, entry_id, row):
    """The Prepared Standard a row makes (prepared_standards._save data),
    pinned to the recipe revision that made it when there is one."""
    data = {
        "uid": None,
        "title": row.get("title") or u"",
        "lot_number": row.get("lot_number") or u"",
        "standard_type": row.get("standard_type") or u"",
        "logbook_slug": entry.get("logbook_slug") or u"",
        "logbook_revision": entry.get("logbook_revision") or 1,
        "logbook_title": entry.get("logbook_title") or u"",
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


def list_entries(portal, form_code=None, since=None, until=None):
    out = [e for e in load(portal).values()
           if (not form_code or e.get("form_code") == form_code)
           and (not since or (e.get("prepared_date") or u"") >= since)
           and (not until or (e.get("prepared_date") or u"") <= until)]
    return sorted(out, key=lambda e: (e.get("prepared_date") or u"", e.get("id") or u""), reverse=True)


def make(portal, entry, rows, who, at, _save=None, ledger_path=None):
    """Store the entry, make its lots, write its parents to the ledger.
    Refuses (ValueError) an entry with problems."""
    problems = entry_problems(entry, rows)
    if problems:
        raise ValueError(u" ".join(problems))
    if _save is None:
        from senaite.pfas.browser.prepared_standards import _save
    entries = load(portal)
    entry_id = new_entry_id(list(entries), entry.get("form_code") or u"FM-ENV", entry.get("prepared_date"))
    uids = [_save(portal, lot_data(entry, entry_id, r)) for r in rows]
    entry = dict((k, v) for k, v in entry.items() if k != "unknown_parents")
    stored = dict(entry, id=entry_id, made_by=who, made_at=at, lots=uids,
                  rows=[dict(r) for r in rows], reviewed_by=u"", reviewed_at=u"")
    entries[entry_id] = stored
    save(portal, entries)
    from senaite.pfas import inventory_ledger as led
    led.record_stage(ledger_path, u"prep:%s" % entry_id, entry_id, LEDGER_STAGE,
                     u"Prep %s" % (entry.get("form_code") or u""), ledger_rows(entry), who, at)
    return entry_id, uids
