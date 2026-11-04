# -*- coding: utf-8 -*-
"""What a run records: the lots loaded on the instrument -- each calibration
level, the ICV (QCS) and CCV, and one lot per LC solvent channel the method
names -- chosen when the run is built. The same slots, with "SPE:" keys,
serve the guided extraction's SPE solvent channels.

A slot's key: "CAL-1" ... "CAL-n", "ICV", "CCV", "LC:<channel>",
"SPE:<channel>". A chosen lot is named by its inventory key "kind:uid"
(bench_inventory items).

A lot is in date on day D when its expiry is on or after D (a lot expiring
on the run date is usable, as bench_queue.is_usable has it); a lot pending
verification may be chosen (the parentage review flags it).

    slots(n_levels, channels, qc_names=None, new_curve=True, prefix="LC")
    from_form(form, slots) / from_entry(entry, slots)
    levels_by_uid(entries)                           -> {lot uid: level it was made for}
    slot_of(level, slots, qc_names=None)             -> slot key or None
    lots_for_slot(key, items, levels, slots, qc_names=None) -> the lots made for one slot
    problems(chosen, slots, lots_by_key, run_date)  -> [message]
    for_manifest(chosen, lots_by_key)               -> (standards, solvents)
    ledger_rows(standards, solvents)                -> usage ledger rows
    spe_roles(channels, stage_order)                -> the extraction stage's
                                                       SPE channel picker roles
    chosen_from_rows(rows, roles)                   -> {slot: "kind:uid"}
    injection_list(manifest)                        -> the built run, header first (the backup CSV)

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

FIELD = u"lot__%s"
# bench_inventory's kind for a prepared lot (its REAGENT, PREPARED)
PREPARED = u"prepared_standard"


def slots(n_levels, channels, qc_names=None, new_curve=True, prefix=u"LC"):
    """[(key, label)]: the calibration levels and the ICV only for a run
    that makes a new curve; the CCV always; one per solvent channel. A
    check is labelled ICV / CCV; the method's own codes (`qc_names`) belong
    to the injection names it issues only."""
    out = []
    if new_curve:
        out.extend((u"CAL-%d" % i, u"CAL-%d" % i) for i in range(1, (n_levels or 0) + 1))
        out.append((u"ICV", u"ICV"))
    out.append((u"CCV", u"CCV"))
    out.extend((u"%s:%s" % (prefix, c["channel"]), c["channel"]) for c in channels or [])
    return out


def from_form(form, slot_list):
    out = {}
    for key, _label in slot_list:
        value = (u"%s" % ((form or {}).get(FIELD % key) or u"")).strip()
        if value:
            out[key] = value
    return out


def from_entry(entry, slot_list):
    """An FM-ENV-002 entry's lots on the calibration levels they were made for."""
    keys = set(k for k, _l in slot_list)
    out = {}
    for row, uid in zip(entry.get("rows") or [], entry.get("lots") or []):
        level = (row.get("level") or u"").strip()
        if level in keys and uid:
            out[level] = u"%s:%s" % (PREPARED, uid)
    return out


# a purchased lot loaded on an LC channel as it is: a bottle of solvent
PURCHASED_SOLVENT = u"Mobile Phase / Solvent"


def levels_by_uid(entries):
    """{lot uid: the level its prep entry row was made for} ("CAL-3", "QCS",
    a channel name); a prep entry's rows and lots are in step."""
    out = {}
    for e in entries or []:
        for row, uid in zip(e.get("rows") or [], e.get("lots") or []):
            level = (row.get("level") or u"").strip()
            if uid and level:
                out[uid] = level
    return out


def slot_of(level, slot_list, qc_names=None):
    """The slot a level names: a slot's key ("CAL-3", "CCV"), its label (a
    channel name) or the method's code for the check (`qc_names`, e.g.
    {"CCV": "CCC"}), case aside."""
    want = (level or u"").strip().upper()
    if not want:
        return None
    codes = dict(((v or u"").strip().upper(), k) for k, v in (qc_names or {}).items() if v)
    for key, label in slot_list or []:
        if want in (key.upper(), (label or u"").upper()) or codes.get(want) == key:
            return key
    return None


def lots_for_slot(key, items, levels, slot_list, qc_names=None):
    """The usable `items` made for slot `key`, newest verified first, then
    the lots pending verification (marked "pending"). An LC channel also
    takes purchased solvent loaded as it is. Nothing else is offered: a
    slot no lot was made for is empty."""
    picked = []
    for i in items or []:
        if i.get("kind") == PREPARED:
            ok = slot_of(levels.get(i.get("uid")), slot_list, qc_names) == key
        else:
            ok = key.startswith(u"LC:") and i.get("category") == PURCHASED_SOLVENT
        if ok:
            lot = dict(i)
            lot["pending"] = (i.get("status") or u"") == u"pending"
            picked.append(lot)
    picked.sort(key=lambda l: _d(l.get("received")), reverse=True)
    picked.sort(key=lambda l: l["pending"])           # stable: newest first within each
    return picked


def series_options(entries, slot_list):
    """[{"id", "label"}]: the calibration sittings (FM-ENV-002 entries) that
    made every level the run loads, in the order given (newest first)."""
    levels = set(k for k, _l in slot_list or [] if k.startswith(u"CAL-"))
    out = []
    for e in entries or []:
        made = set((r.get("level") or u"").strip() for r in e.get("rows") or [])
        if levels and levels <= made:
            out.append({"id": e.get("id") or u"",
                        "label": u"%s \u00b7 prepared %s \u00b7 %d levels" % (
                            e.get("id") or u"", e.get("prepared_date") or u"?", len(levels))})
    return out


def from_series(form, entries, slot_list):
    """The build form's lots, the calibration levels filled from the chosen
    sitting (one Calibration series box)."""
    chosen = from_form(form, slot_list)
    want = (u"%s" % ((form or {}).get("cal_series") or u"")).strip()
    for e in entries or []:
        if want and e.get("id") == want:
            chosen.update(from_entry(e, slot_list))
    return chosen


def _d(v):
    return (u"%s" % (v or u""))[:10]


def problems(chosen, slot_list, lots_by_key, run_date):
    out = []
    run_date = _d(run_date)
    for key, label in slot_list:
        ref = (chosen or {}).get(key)
        if not ref:
            out.append(u"Choose the %s lot." % label)
            continue
        lot = (lots_by_key or {}).get(ref)
        if lot is None:
            out.append(u"%s: the chosen lot is not in the inventory." % label)
            continue
        number, status, expiry = lot.get("lot_number") or u"?", lot.get("status") or u"", _d(lot.get("expiry"))
        if status == u"quarantine":
            out.append(u"%s: lot %s is quarantined." % (label, number))
        elif status in (u"exhausted", u"archived"):
            out.append(u"%s: lot %s is used up." % (label, number))
        elif not expiry:
            out.append(u"%s: lot %s has no expiry date." % (label, number))
        elif expiry < run_date or status == u"expired":
            out.append(u"%s: lot %s expired on %s." % (label, number, expiry))
    return out


def _snap(lot):
    return {"kind": lot.get("kind"), "uid": lot.get("uid"), "lot": lot.get("lot_number"),
            "name": lot.get("name") or u"", "expiry": _d(lot.get("expiry")),
            # a prepared lot's received date is its prep date (bench_inventory)
            "prepared_date": _d(lot.get("received")) if lot.get("kind") == PREPARED else u""}


def for_manifest(chosen, lots_by_key):
    """({slot: lot}, {channel: lot}) as the run manifest keeps them."""
    standards, solvents = {}, {}
    for key, ref in sorted((chosen or {}).items()):
        lot = (lots_by_key or {}).get(ref)
        if lot is None:
            continue
        if u":" in key:
            solvents[key.split(u":", 1)[1]] = _snap(lot)
        else:
            standards[key] = _snap(lot)
    return standards, solvents


def curve_batch(calibration_rows, run_date):
    """The batch whose run made the curve of `run_date` (the curve a reuse
    run is judged on): the stored calibrations of that day, else ""."""
    day = (u"%s" % (run_date or u""))[:10]
    for r in calibration_rows or []:
        if day and (u"%s" % (r.get("run_date") or u""))[:10] == day and r.get("batch_id"):
            return r["batch_id"]
    return u""


def acid_analytes(cal_lots):
    """The analytes whose calibration lots all state them as acid, with a
    value (prep_sitting: calculated from certificate values as the acid).
    `cal_lots`: each loaded calibration lot's analyte concentrations. An
    analyte any lot states as typed, or leaves blank, is not on an acid
    basis: the method's salt factor still applies to it."""
    acid, not_acid = set(), set()
    for concs in cal_lots or []:
        for c in concs or []:
            name = (c.get("analyte") or u"").strip()
            if not name:
                continue
            if c.get("basis") == u"acid" and (u"%s" % (c.get("concentration") or u"")).strip():
                acid.add(name)
            else:
                not_acid.add(name)
    return sorted(acid - not_acid)


def spe_roles(channels, stage_order):
    """One picker role per automated SPE solvent channel used at this stage."""
    out = []
    for c in channels or []:
        if u"%s" % c.get("stage") != u"%s" % stage_order:
            continue
        ch = c.get("channel") or u""
        out.append({"role": (u"SPE %s: %s" % (ch, c.get("what") or u"")).rstrip(u": "),
                    "slot": u"SPE:%s" % ch, "label": u"SPE %s" % ch})
    return out


def chosen_from_rows(rows, roles):
    """The lots a stage's picker rows hold for the SPE channel roles."""
    by_role = dict((r["role"], r["slot"]) for r in roles or [])
    out = {}
    for row in rows or []:
        slot = by_role.get(row.get("role"))
        if slot and row.get("inventory_uid"):
            out[slot] = u"%s:%s" % (row.get("kind") or u"reagent", row["inventory_uid"])
    return out


def run_loaded(manifest):
    """[(label, lot snapshot)] the run was loaded with: its standards by
    slot, then its LC solvent channels ("LC A1")."""
    m = manifest or {}
    return (sorted((m.get("standards") or {}).items(), key=lambda kv: _slot_order(kv[0]))
            + [(u"LC %s" % ch, lot) for ch, lot in sorted((m.get("solvents") or {}).items())])


def _slot_order(key):
    if key.startswith(u"CAL-") and key[4:].isdigit():
        return (0, int(key[4:]), key)
    return (1, 0, key)


def late_injections(last_acquired, solvents):
    """The solvent lots the run was still injecting on after they expired:
    the run's last acquisition (QC record) later than a lot's expiry."""
    last = _d(last_acquired)
    if not last:
        return []
    out = []
    for ch, lot in sorted((solvents or {}).items()):
        exp = _d(lot.get("expiry"))
        if exp and last > exp:
            out.append({"channel": ch, "lot": lot.get("lot") or u"", "expiry": exp,
                        "reason": u"injected after %s lot %s expired (%s)" % (ch, lot.get("lot") or u"", exp)})
    return out


def ledger_rows(standards, solvents, prefix=u"LC"):
    rows = []
    for role, lot in sorted((standards or {}).items()) + sorted(
            (u"%s %s" % (prefix, ch), lot) for ch, lot in (solvents or {}).items()):
        rows.append({"from_inventory": True, "inventory_uid": lot.get("uid"), "lot": lot.get("lot"),
                     "kind": lot.get("kind"), "name": lot.get("name") or u"", "role": role,
                     "qty_used": u""})
    return rows


INJECTION_LIST_HEADINGS = [u"Vial", u"Injection name", u"Lot", u"Description", u"Type"]


def row_lot(row, standards):
    """The lot an injection was made from, as the run recorded it: a
    calibration level's, the ICV's or the CCV's; else none."""
    role = (row.get("role") or u"").upper()
    if role == u"CAL" and row.get("level") not in (None, u""):
        key = u"CAL-%s" % row.get("level")
    elif role in (u"ICV", u"CCV"):
        key = role
    else:
        return u""
    return ((standards or {}).get(key) or {}).get("lot") or u""


def injection_list(manifest):
    """The built run as the table on screen shows it, header first: Vial,
    Injection name, Lot, Description, Type (the backup CSV)."""
    std = (manifest or {}).get("standards") or {}
    out = [list(INJECTION_LIST_HEADINGS)]
    for r in (manifest or {}).get("rows") or []:
        out.append([r.get("vial"), r.get("name") or u"", row_lot(r, std), r.get("description") or u"",
                    r.get("type") or u""])
    return out
