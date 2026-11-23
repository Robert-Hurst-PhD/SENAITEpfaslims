# -*- coding: utf-8 -*-
"""What the retired logbook pool's purge would delete, and the sentence that
says it (tools/purge_logbook_pool.py prints both before it deletes).

Only the pool's own data is purged: a preparation entry made on a prep
logbook form (it carries the form's keys, POOL_ENTRY_KEYS, which a record
made from a recipe never does) and a Prepared Standard lot made on one (its
logbook slug is set, or it belongs to such an entry). Every other entry and
lot is listed as kept and never deleted, so a run after the reseed deletes
nothing made from a recipe. A kept record or lot made from a pool lot would
lose its parent: the plan names each one (kept_uses) and the purge refuses
to delete anything while there is one (refusal).

    pool_entries(entries)          -> (pool ids, kept ids)
    pool_lots(lots, pool_entry_ids, kept_entry_ids=()) -> (pool ids, kept ids)
        lots           [(id, logbook slug, entry id)] of every Prepared Standard
    plan(entries, lots, defs, coc_batches, designs=(), coc_worksheets=(),
         ledger_rows=0, lot_uses=0, kept_entries=(), kept_lots=()) -> dict
        entries        the pool's preparation entries ({id: record}, or ids)
        lots           the pool's Prepared Standard ids
        defs           the pfas_prep_logbooks folder's child ids, None when
                       the folder is gone
        coc_batches    the batches carrying the batch receipt form
        designs        the stored designs of the retired logbook kinds
        coc_worksheets the worksheets carrying the same form (Data Review
                       corrected it there)
        ledger_rows    the usage ledger's rows of the preparation records
        lot_uses       the usage ledger's other rows naming a purged lot (the
                       extraction stages that used it)
        kept_entries, kept_lots  what is not the pool's, listed under "kept"
        kept_uses      kept_uses()'s list, under "kept" as "uses_pool_lots"
    kept_uses(pool_lot_ids, kept_parents) -> [{"kept", "lot"}]
        kept_parents   {kept entry or lot id: [parent {"kind", "uid"}]}
    refusal(plan)  -> the reason --yes deletes nothing, or ""
    summary(plan)  -> "5 preparation records, 42 prepared lots, ..."
    retired_designs(store, kinds) -> [template id] whose kind is not a kind
    mode(args)     -> "dry" | "delete"

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals


# the keys every entry made on a prep logbook form carries, set or blank;
# a record made from a recipe carries none of them
POOL_ENTRY_KEYS = ("form_code", "logbook_slug")


def _ids(items):
    return sorted(u"%s" % i for i in (items or ()))


def pool_entries(entries):
    """(pool ids, kept ids): an entry is the pool's when it carries a prep
    logbook form's keys; every other entry is kept."""
    pool, kept = [], []
    for eid, entry in (entries or {}).items():
        (pool if any(k in (entry or {}) for k in POOL_ENTRY_KEYS) else kept).append(eid)
    return _ids(pool), _ids(kept)


def pool_lots(lots, pool_entry_ids, kept_entry_ids=()):
    """(pool ids, kept ids): a lot of a kept entry is kept whatever it
    carries; otherwise a lot is the pool's when it belongs to a pool entry
    or its logbook slug is set. Any other lot is kept."""
    pool_entry_ids, kept_entry_ids = set(pool_entry_ids or ()), set(kept_entry_ids or ())
    pool, kept = [], []
    for lot_id, slug, entry_id in lots or ():
        if entry_id and entry_id in kept_entry_ids:
            kept.append(lot_id)
        elif (entry_id and entry_id in pool_entry_ids) or (slug or u"").strip():
            pool.append(lot_id)
        else:
            kept.append(lot_id)
    return _ids(pool), _ids(kept)


def kept_uses(pool_lot_ids, kept_parents):
    """[{"kept", "lot"}]: each kept record or lot that names a pool lot as a
    parent (a prepared lot's parent; a parent of no kind is taken as one)."""
    pool = set(pool_lot_ids or ())
    out = []
    for kid, parents in (kept_parents or {}).items():
        for p in parents or ():
            p = p if isinstance(p, dict) else {}
            if p.get("uid") in pool and (p.get("kind") or u"prepared_standard") == u"prepared_standard":
                out.append({"kept": u"%s" % kid, "lot": u"%s" % p["uid"]})
    return sorted(out, key=lambda u: (u["kept"], u["lot"]))


def refusal(p):
    """Why --yes must delete nothing: a kept record or lot made from a lot
    the purge would delete."""
    uses = (p.get("kept") or {}).get("uses_pool_lots") or []
    if not uses:
        return u""
    return u"%s made from a lot the purge would delete, so nothing is deleted: %s." % (
        _count(len(uses), u"kept record or lot is", u"kept records or lots are"),
        u", ".join(u"%s from %s" % (u["kept"], u["lot"]) for u in uses))


def plan(entries, lots, defs, coc_batches, designs=(), coc_worksheets=(), ledger_rows=0, lot_uses=0,
         kept_entries=(), kept_lots=(), kept_uses=()):
    entry_ids = _ids(entries)
    return {"entries": len(entry_ids), "entry_ids": entry_ids,
            "lots": _ids(lots),
            # the folder is purged whether or not it still holds definitions
            "folder": defs is not None, "folder_children": _ids(defs),
            "coc_batches": _ids(coc_batches), "coc_worksheets": _ids(coc_worksheets),
            "designs": _ids(designs), "ledger_rows": int(ledger_rows or 0),
            "lot_uses": int(lot_uses or 0),
            "kept": {"entries": _ids(kept_entries), "lots": _ids(kept_lots),
                     "uses_pool_lots": list(kept_uses or [])}}


def _count(n, one, many):
    return u"%d %s" % (n, one if n == 1 else many)


def _kept(p):
    kept = p.get("kept") or {}
    n, m = len(kept.get("entries") or ()), len(kept.get("lots") or ())
    if not (n or m):
        return u""
    return u"; kept: %s, %s" % (_count(n, u"preparation record", u"preparation records"),
                                _count(m, u"prepared lot", u"prepared lots"))


def summary(p):
    if not (p["entries"] or p["lots"] or p["folder"] or p["coc_batches"] or p["coc_worksheets"]
            or p["designs"] or p["ledger_rows"] or p["lot_uses"]):
        return u"Nothing to purge%s." % _kept(p)
    parts = [_count(p["entries"], u"preparation record", u"preparation records"),
             _count(len(p["lots"]), u"prepared lot", u"prepared lots"),
             u"1 logbook folder" if p["folder"] else u"no logbook folder",
             _count(len(p["coc_batches"]), u"batch receipt form", u"batch receipt forms")]
    if p["coc_worksheets"]:
        parts.append(_count(len(p["coc_worksheets"]), u"worksheet receipt form", u"worksheet receipt forms"))
    if p["designs"]:
        parts.append(_count(len(p["designs"]), u"retired design", u"retired designs"))
    if p["ledger_rows"]:
        parts.append(_count(p["ledger_rows"], u"usage row", u"usage rows"))
    if p["lot_uses"]:
        parts.append(_count(p["lot_uses"], u"use of a purged lot", u"uses of purged lots"))
    return u", ".join(parts) + _kept(p)


def retired_designs(store, kinds):
    """The designs the designer refuses to act on: their kind is no longer
    one of its kinds (a retired logbook's)."""
    return sorted(tid for tid, entry in (store or {}).items()
                  if (entry or {}).get("kind") not in (kinds or {}))


def mode(args):
    """Read-only unless the one argument is --yes; anything else is refused."""
    args = list(args or [])
    if not args:
        return u"dry"
    if args == [u"--yes"]:
        return u"delete"
    raise ValueError(u"The only argument is --yes; without it nothing is deleted.")
