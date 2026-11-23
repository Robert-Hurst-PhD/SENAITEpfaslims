# -*- coding: utf-8 -*-
"""The lots one worksheet used, read once for every document that lists them.

The guided extraction's session is the record of the lots each stage used;
the run manifest is the record of the lots the instrument was loaded with.
The batch record prints both, Data Review's traceability walk judges both
and the QC Review report lists what the walk found. They read the lots
here, so one worksheet's documents name the same lots:

    stage_rows(stage_data)          a stage's lot rows, as every reader sees them
    extraction_tables(session)      the stages' lots as the three tables the
                                    traceability walk reads (reagents,
                                    standards, extraction_materials)
    loaded_lots(manifest, resolve)  the lots the run was loaded with, each
                                    looked up in the inventory by `resolve`
    loaded_kind(kind, found)        the words both prints use for a loaded lot
    stage_kind(kind, lot, found)    the same for a lot a stage recorded
    trace_rows(tree)                the QC Review's traceability table: every
                                    lot of the walk, none left out
    spikes(members)                 the spiked QC members' lots (an LFSMD
                                    its LFSM's), as the walk, the record
                                    view and the usage ledger read them
    spike_standards(members)        those lots as the walk's standards rows
    spike_ledger_rows(members, resolve)  those uses as usage ledger rows
    analysis_lots(members, requests, item)  the other lots the analysis
                                    used: each dilution's diluent, internal
                                    standard and surrogate, each matrix
                                    blank's blank-matrix lot
    other_lot_rows(members, requests, item)  those lots as the batch
                                    record lists and prints them
    solutions(session)              the solutions the stages prepared

A lot the stages recorded with no lot number is not a lot: it is printed on
the batch record as recorded and is not traced.

Pure, standard library only. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.bench_queue import is_consumable_row, is_standard_row

REAGENTS, STANDARDS, MATERIALS = "reagents", "standards", "extraction_materials"
TABLES = (REAGENTS, STANDARDS, MATERIALS)

# a lot a record names that the inventory does not hold
NOT_IN_INVENTORY = "not in the inventory"
NO_LOT = "no lot recorded"
PREPARED_TYPE = "PreparedStandard"


def _t(value):
    return ("%s" % (value if value is not None else "")).strip()


def table_of(row):
    """The table a stage's lot row belongs to: a consumable is an
    extraction material, a standard resolves a prepared standard or a
    reagent, anything else resolves a reagent."""
    if is_consumable_row(row):
        return MATERIALS
    return STANDARDS if is_standard_row(row) else REAGENTS


def stage_rows(stage_data):
    """A recorded stage's lot rows in the order recorded, each with what
    every reader prints or judges: name (the role when the row has no
    name), lot, supplier, qty, expiry, the table it is traced in and its
    inventory status when used. `row` is the stored row itself."""
    out = []
    for r in (stage_data or {}).get("reagents") or []:
        if not isinstance(r, dict):
            continue
        out.append({"name": r.get("name") or r.get("role") or "", "lot": _t(r.get("lot")),
                    "supplier": r.get("supplier") or "",
                    "qty": r.get("volume") or r.get("qty_used") or "",
                    "volume": r.get("volume") or "", "expiry": r.get("expiry") or "",
                    "status_at_use": r.get("status_at_use") or "",
                    "consumable": r.get("group") == "consumable",
                    "table": table_of(r), "row": r})
    return out


def _order_key(order):
    text = "%s" % order
    return (0, int(text), text) if text.isdigit() else (1, 0, text)


def extraction_rows(session):
    """[(stage order, row)] of every lot row the session's stages recorded,
    the stages in order."""
    stages = (session or {}).get("stages") or {}
    out = []
    for order in sorted(stages, key=_order_key):
        out.extend(("%s" % order, row) for row in stage_rows(stages[order]))
    return out


def extraction_tables(session):
    """{"reagents", "standards", "extraction_materials"}: the stages' lots
    as the traceability walk reads them, a lot used at several stages once.
    A row with no lot number is left out. Every table is present, empty
    when the stages name no such lot, so a lot removed by a correction does
    not stay behind."""
    out = dict((name, []) for name in TABLES)
    for _order, row in extraction_rows(session):
        if not row["lot"]:
            continue
        if row["table"] == MATERIALS:
            entry = {"name": row["name"], "lot": row["lot"], "notes": "",
                     "status_at_use": row["status_at_use"]}
        elif row["table"] == STANDARDS:
            entry = {"name": row["name"], "lot": row["lot"], "conc": "", "volume": row["volume"],
                     "status_at_use": row["status_at_use"]}
        else:
            entry = {"name": row["name"], "lot": row["lot"], "supplier": row["supplier"],
                     "volume": row["volume"], "status_at_use": row["status_at_use"]}
        if entry not in out[row["table"]]:
            out[row["table"]].append(entry)
    return out


def recorded(session):
    """True when the session has a recorded stage: its stages are then the
    record of the lots the extraction used."""
    return bool((session or {}).get("stages"))


def extraction_lot_numbers(session):
    """The lot numbers the stages recorded, each once, in order."""
    out = []
    for _order, row in extraction_rows(session):
        if row["lot"] and row["lot"] not in out:
            out.append(row["lot"])
    return out


# ── the spikes the QC members were made with ────────────────────────────────

# the usage ledger's stage for the spikes of an extraction batch: saving its
# Parents and levels replaces these rows, and no other stage's
SPIKE_STAGE = "spikes"
SPIKE_STAGE_NAME = "Spikes"


def spikes(members):
    """[{"member", "injection", "role", "lot", "volume"}] for each spiked QC
    member with a spike lot recorded, in batch order: its own lot and
    volume, an LFSMD its LFSM's (extraction_batch.spike_of). A lot is a
    standard used in the analysis, so it is traced and counted."""
    from senaite.pfas.extraction_batch import SPIKED, spike_of
    out = []
    for m in members or []:
        if not isinstance(m, dict) or m.get("role") not in SPIKED:
            continue
        lot, volume = spike_of(m, members)
        if lot:
            out.append({"member": m.get("id") or "", "injection": _t(m.get("injection")),
                        "role": m.get("role") or "", "lot": lot, "volume": volume})
    return out


def spike_standards(members):
    """The spike lots as the traceability walk's standards rows, a lot
    spiked into several members once, naming each member."""
    out, by_lot = [], {}
    for sp in spikes(members):
        row = by_lot.get(sp["lot"])
        if row is None:
            row = by_lot[sp["lot"]] = {"name": "Spike", "lot": sp["lot"], "conc": "", "volume": "",
                                       "status_at_use": "", "members": []}
            out.append(row)
        row["members"].append(sp["injection"])
    for row in out:
        row["name"] = "Spike: %s" % ", ".join(n for n in row.pop("members") if n)
    return out


def spike_ledger_rows(members, resolve):
    """One usage ledger row per spiked member (inventory_ledger.record_stage):
    the lot, resolved by `resolve(lot number)` to (kind, uid) or None, and
    the volume in uL. A lot the inventory does not hold is not a use of an
    inventory lot and is left out (the walk reports it)."""
    out = []
    for sp in spikes(members):
        found = resolve(sp["lot"]) if resolve is not None else None
        if not found:
            continue
        kind, uid = found
        out.append({"from_inventory": True, "inventory_uid": uid, "kind": kind, "lot": sp["lot"],
                    "name": "Spike", "role": ("%s %s" % (sp["role"], sp["injection"])).strip(),
                    "qty_used": ("%s uL" % sp["volume"]) if sp["volume"] else ""})
    return out


# ── the other lots an analysis used ─────────────────────────────────────────

# a dilution's prep names its lots by inventory uid: the diluent a reagent,
# the internal standard and the surrogate prepared standards
_DILUTION_LOTS = (("diluent_lot", "reagent", REAGENTS, "diluent"),
                  ("is_lot", "prepared_standard", STANDARDS, "internal standard"),
                  ("sur_lot", "prepared_standard", STANDARDS, "surrogate"))


def _named_lot(item, kind, uid):
    """(lot number, name) of the inventory lot (kind, uid) names; a lot the
    inventory no longer holds keeps its id, so the walk reports it."""
    found = item(kind, uid) if item is not None else None
    if not found:
        return _t(uid), ""
    return _t(found.get("lot_number")) or _t(uid), _t(found.get("name"))


# the words the batch record lists each kind under
_DILUTION_KINDS = {"diluent_lot": "Diluent", "is_lot": "Internal standard", "sur_lot": "Surrogate"}
MATRIX_BLANK_KIND = "Blank matrix"


def _other_lots(members, requests):
    """Each lot an analysis used outside the stages, the spikes and the
    run's loading, as (table, inventory kind, uid, what, where, kind, qty):
    each made dilution's diluent, and its internal standard and surrogate
    unless not added, then each matrix blank's blank-matrix lot."""
    for r in requests or []:
        prep = (r or {}).get("prep") if isinstance(r, dict) else None
        if r.get("kind") != "dilution" or r.get("status") not in ("made", "run") or not isinstance(prep, dict):
            continue
        injection = _t(r.get("new_injection"))
        for key, kind, table, what in _DILUTION_LOTS:
            handled = prep.get(key.replace("_lot", "_handling"))
            if _t(prep.get(key)) and (key == "diluent_lot" or handled != "not_added"):
                ul = _t(prep.get(key.replace("_lot", "_ul"))) if key != "diluent_lot" else ""
                yield (table, kind, _t(prep.get(key)), "Dilution %s %s" % (injection, what),
                       "Dilution %s" % injection, _DILUTION_KINDS[key], ("%s \u00b5L" % ul) if ul else "")
    for m in members or []:
        if isinstance(m, dict) and m.get("role") == "MxB" and _t(m.get("lot")):
            injection = _t(m.get("injection"))
            yield (REAGENTS, "reagent", _t(m["lot"]), "Matrix blank %s" % injection,
                   "Matrix blank %s" % injection, MATRIX_BLANK_KIND, "")


def analysis_lots(members, requests, item):
    """{"reagents": [...], "standards": [...]}: the lots the analysis used
    outside the stages' rows and the spikes, as the walk's table rows: each
    made dilution's diluent, internal standard and surrogate, and each
    matrix blank's blank-matrix lot. `item(kind, uid)` is the inventory lot
    (bench_inventory.item_index), or None."""
    out = {REAGENTS: [], STANDARDS: []}
    for table, kind, uid, what, _where, _kind, _qty in _other_lots(members, requests):
        lot, name = _named_lot(item, kind, uid)
        entry = {"name": "%s: %s" % (what, name) if name else what, "lot": lot, "supplier": "",
                 "conc": "", "volume": "", "status_at_use": ""}
        if lot and entry not in out[table]:
            out[table].append(entry)
    return out


def other_lot_rows(members, requests, item):
    """The same lots as the batch record lists them, its matrix blanks'
    first, then each dilution's: [{"where", "kind", "name", "lot", "qty"}].
    Shown and printed beside the record, never part of what it hashes."""
    rows = []
    for _table, kind, uid, _what, where, label, qty in _other_lots(members, requests):
        lot, name = _named_lot(item, kind, uid)
        row = {"where": where, "kind": label, "name": name, "lot": lot or NO_LOT.capitalize(), "qty": qty}
        if row not in rows:
            rows.append(row)
    return ([r for r in rows if r["kind"] == MATRIX_BLANK_KIND]
            + [r for r in rows if r["kind"] != MATRIX_BLANK_KIND])


def solutions(session):
    """[{"name", "lot", "stage"}]: each solution a stage prepared at the
    bench with a lot number, in stage order, each lot once."""
    stages = (session or {}).get("stages") or {}
    out, seen = [], set()
    for order in sorted(stages, key=_order_key):
        for sol in (stages[order] or {}).get("solutions_prepared") or []:
            lot = _t((sol or {}).get("lot")) if isinstance(sol, dict) else ""
            if lot and lot not in seen:
                seen.add(lot)
                out.append({"name": "Solution prepared: %s" % _t(sol.get("name")), "lot": lot,
                            "stage": "%s" % order})
    return out


# ── the lots the run was loaded with ────────────────────────────────────────

def loaded_lots(manifest, resolve=None):
    """One row per lot the run was loaded with (run_lots.run_loaded: the
    standards by slot, then the LC solvent channels): {"label", "snap",
    "lot", "name", "expiry", "kind", "obj", "inventory_kind", "found"}.
    `kind` is what the run recorded when the lot was loaded.
    `resolve(snap)` looks the lot up in the inventory and returns (object,
    inventory kind); without it nothing is looked up and `found` is None."""
    from senaite.pfas.run_lots import run_loaded
    out = []
    for label, snap in run_loaded(manifest):
        if not isinstance(snap, dict):
            continue
        obj, inv_kind = resolve(snap) if resolve is not None else (None, "")
        out.append({"label": label, "snap": snap, "lot": _t(snap.get("lot")),
                    "name": snap.get("name") or "", "expiry": snap.get("expiry") or "",
                    "kind": snap.get("kind") or "", "obj": obj, "inventory_kind": inv_kind or "",
                    "found": (obj is not None) if resolve is not None else None})
    return out


def record_lot_rows(record, other=()):
    """The lots a batch record names, as its record view lists them: each
    stage's reagents and consumables in stage order, the spikes the QC
    members were made with, the matrix blanks' and dilutions' lots
    (`other`, other_lot_rows), then the lots the run was loaded with by
    slot. [{"where", "kind", "name", "lot", "qty"}]; a row with no lot
    number says so."""
    parts = (record or {}).get("parts") or {}
    out = []
    for st in parts.get("stages") or []:
        if not isinstance(st, dict):
            continue
        for kind, key in (("Reagent", "reagents"), ("Consumable", "consumables")):
            for r in st.get(key) or []:
                out.append({"where": "Stage %s" % _t(st.get("order")), "kind": kind,
                            "name": _t(r.get("name")) or _t(r.get("role")),
                            "lot": _t(r.get("lot")) or NO_LOT.capitalize(), "qty": _t(r.get("qty"))})
    for sp in spikes(parts.get("members")):
        out.append({"where": SPIKE_STAGE_NAME, "kind": "Spike", "name": sp["injection"], "lot": sp["lot"],
                    "qty": ("%s \u00b5L" % sp["volume"]) if sp["volume"] else ""})
    out += [dict(r) for r in other or ()]
    for row in loaded_lots(parts.get("loaded")):
        out.append({"where": _t(row["label"]), "kind": _t(kind_label(row["kind"])), "name": _t(row["name"]),
                    "lot": row["lot"] or NO_LOT.capitalize(), "qty": ""})
    return out


def _lots(n):
    return "%d lot" % n if n == 1 else "%d lots" % n


def lots_summary(record, rows):
    """What the record's Lots card counts, in words: every row it lists, and
    how many of those the run loaded on the instrument (the listing's
    Loaded on instrument column). "" when the card has no rows."""
    if not rows:
        return ""
    loaded = len(loaded_lots(((record or {}).get("parts") or {}).get("loaded")))
    return "%s recorded, %d loaded on the instrument." % (_lots(len(rows)), loaded)


def kind_label(kind):
    from senaite.pfas.run_lots import KIND_LABELS
    return KIND_LABELS.get(kind, kind or "")


def loaded_kind(kind, found):
    """The kind of a loaded lot as both prints say it: the kind the run
    recorded, and that the inventory no longer holds the lot when it does
    not. `found` None: not looked up, the kind alone."""
    label = _t(kind_label(kind))
    if found is False:
        return ("%s, %s" % (label, NOT_IN_INVENTORY)) if label else NOT_IN_INVENTORY.capitalize()
    return label


def stage_kind(kind, lot, found):
    """The kind of a lot the extraction recorded as the batch record
    prints it: the kind, and that the inventory does not hold the lot when
    it does not (`found`: {lot: bool}, as the traceability walk resolves
    them; a lot not in it, or with no number, is not looked up)."""
    if lot and found and found.get(lot) is False:
        return "%s, %s" % (kind, NOT_IN_INVENTORY)
    return kind


# ── the QC Review's traceability table ──────────────────────────────────────

NO_EXPIRY = "no expiry recorded"


def _direct(entry, what):
    lot = _t(entry.get("lot"))
    res = entry.get("resolved") or {}
    if res:
        resolves = _t(res.get("category")) or ("prepared standard" if res.get("type") == PREPARED_TYPE
                                                else what)
    else:
        resolves = NOT_IN_INVENTORY.capitalize() if lot else NO_LOT.capitalize()
    return {"item": _t(entry.get("name")), "lot": lot, "resolves": resolves,
            "found": bool(res), "source": "extraction"}


def _parent_text(parent):
    """"LOT NAME, expires DATE": a parent lot as the traceability table
    names it, saying so when the inventory does not hold it."""
    words = [" ".join(x for x in (_t(parent.get("lot")), _t(parent.get("name"))) if x)]
    if parent.get("resolved") is None:
        words.append(NOT_IN_INVENTORY)
    expiry = _t(parent.get("expiry"))
    words.append(("expires %s" % expiry) if expiry else NO_EXPIRY)
    return ", ".join(w for w in words if w)


def _resolves(node):
    """What a lot the run was loaded with resolves to: its inventory
    category, then each parent lot with its expiry. A node that carries
    neither (a walk from before both were kept) reads as the kind it is."""
    category = _t(node.get("category"))
    parents = [p for p in node.get("parent_reagents") or [] if _t(p.get("lot"))]
    if not category and not parents:
        if node.get("kind") == "reagent":
            return "reagent lot"
        return "prepared standard, %d parent lot(s)" % len(node.get("parent_reagents") or [])
    head = category or kind_label(node.get("kind"))
    if not parents:
        return head
    return "%s. %s %s" % (head, "Parent" if len(parents) == 1 else "Parents",
                          "; ".join(_parent_text(p) for p in parents))


def trace_rows(tree):
    """Every lot of Data Review's traceability walk, one row each: the lots
    the run was loaded with, then the standards and the reagents and
    materials the extraction recorded. {"item", "lot", "resolves", "found",
    "source"}. A lot reads by its inventory category, a lot made here
    naming each parent lot with its expiry; a loaded lot the inventory does
    not hold says so beside the kind the run recorded (loaded_kind)."""
    tree = tree or {}
    out = []
    for p in tree.get("prepared_standards") or []:
        found = bool(p.get("found"))
        resolves = _resolves(p) if found else loaded_kind(p.get("kind"), False)
        out.append({"item": _t(p.get("title") or p.get("field")), "lot": _t(p.get("lot")),
                    "resolves": resolves, "found": found, "source": "run"})
    out.extend(_direct(s, "reagent lot") for s in tree.get("direct_standards") or [])
    out.extend(_direct(r, "reagent lot") for r in tree.get("direct_reagents") or [])
    return out


def untraced(session, tree, members=None):
    """The lot numbers the stages recorded, and the spike lots of the
    members, that the walk's tree does not list: a lot the batch record
    prints and the traceability table would leave out. Empty when the two
    agree."""
    listed = set(_t(e.get("lot")) for key in ("direct_reagents", "direct_standards")
                 for e in (tree or {}).get(key) or [])
    lots = extraction_lot_numbers(session)
    for sp in spikes(members):
        if sp["lot"] not in lots:
            lots.append(sp["lot"])
    return [lot for lot in lots if lot not in listed]
