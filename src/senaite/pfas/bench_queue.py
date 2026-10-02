# -*- coding: utf-8 -*-
"""What the Bench landing shows a chemist first (docs/BENCH_WORKFLOW_REVIEW.md
phase 1, DECISIONS 2026-10-02): which batches need extracting, where each one
is, and which inventory items need attention. Pure; Python 2.7 and 3.

    extraction_state(session, stage_orders) -> {"state", "done", "total", "label"}
    inventory_alerts(items, today, soon_days=30) -> {"expired", "expiring",
                                                     "quarantined", "low"}
    is_usable(item, today)                    -> may this lot be used today?
    rank_lots(lots, role, remembered)         -> lots, best candidates first
    default_pick(lots, role, remembered)      -> the lot to preselect, or None
    suggested(lots, role, remembered)         -> the ranked lots worth listing
                                                 first (remembered item or a
                                                 shared word with the role)
    resolve_rows(index, rows)                 -> rows as the inventory has them
    is_standard_row(row)                      -> FM-ENV-003 standards[] or reagents[]
    is_consumable_row(row)                    -> FM-ENV-003 extraction_materials[]
    equipment_family(label)                   -> "balance" | "pipette" | ""
    lot_on_file(items, lot)                   -> the inventory lot with that
                                                 number (any status), or None
    units_for(label, units)                   -> registered units of that family
    stage_warnings(rows, balances, today)     -> what a deviation note must
                                                 explain before the stage is
                                                 complete (DB4)

The last three are phase 2 (DECISIONS 2026-10-02 "Bench phase 2"): a stage
role offers every usable lot, role-name matches first, and the lab's last
pick for that method role is preselected -- or, once that lot is no longer
usable, the newest usable lot of the same item.

`items` = dicts with "name", "lot_number", "status", "expiry" (YYYY-MM-DD)
and, when quantities are tracked, "quantity_value" / "low_stock_level";
for picking also "uid" and "received" (YYYY-MM-DD; prepared date for a
prepared standard).
"""
from __future__ import absolute_import, division, unicode_literals

import re
import unicodedata
from datetime import datetime, timedelta

NOT_STARTED, IN_PROGRESS, FINISHED = u"not_started", u"in_progress", u"finished"
_UNUSABLE = (u"exhausted", u"archived")
_BLOCKED = (u"quarantine", u"expired")


def extraction_state(session, stage_orders):
    """Where a batch's extraction is: not started / stage N of M / finished."""
    total = len(stage_orders or [])
    if not session:
        return {"state": NOT_STARTED, "done": 0, "total": total, "label": u"Not started"}
    done = len([o for o in stage_orders or []
                if u"%s" % o in (session.get("stages") or {})])
    if session.get("finalized") or (total and done >= total):
        return {"state": FINISHED, "done": done, "total": total, "label": u"Finished"}
    return {"state": IN_PROGRESS, "done": done, "total": total,
            "label": u"Stage %d of %d" % (min(done + 1, total), total) if total else u"Started"}


def _date(s):
    try:
        return datetime.strptime((s or u"")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def inventory_alerts(items, today, soon_days=30):
    """The items a chemist should know about before starting work."""
    out = {"expired": [], "expiring": [], "quarantined": [], "low": []}
    soon = today + timedelta(days=soon_days)
    for it in items or []:
        status = (it.get("status") or u"").lower()
        if status in _UNUSABLE or it.get("is_archived"):
            continue
        if status == u"quarantine":
            out["quarantined"].append(it)
            continue
        exp = _date(it.get("expiry"))
        if _expired(it, today):
            out["expired"].append(it)
        elif exp is not None and exp <= soon:
            out["expiring"].append(it)
        qty, low = _num(it.get("quantity_value")), _num(it.get("low_stock_level"))
        if qty is not None and low is not None and qty <= low:
            out["low"].append(it)
    for key in out:
        out[key].sort(key=lambda i: (i.get("expiry") or u"9999", i.get("name") or u""))
    return out


def _expired(it, today):
    exp = _date(it.get("expiry"))
    return (it.get("status") or u"").lower() == u"expired" or (
        exp is not None and exp < today)


def is_usable(item, today):
    """Not used up, archived, quarantined or expired. A lot expiring TODAY is
    still usable (the Bench lists it as expiring, not expired)."""
    status = (item.get("status") or u"").lower()
    if status in _UNUSABLE or status in _BLOCKED or item.get("is_archived"):
        return False
    return not _expired(item, today)


_SUBSCRIPTS = dict((ord(c), u"%d" % i) for i, c in enumerate(u"\u2080\u2081\u2082\u2083\u2084"
                                                            u"\u2085\u2086\u2087\u2088\u2089"))
_STOP = frozenset([u"grade", u"lc", u"ms", u"lcms", u"hplc", u"the", u"and", u"in",
                   u"of", u"if", u"for", u"solution", u"mix"])


def _tokens(text):
    """Words of a name, folded: "MgSO\u2084 (anhydrous)" -> {"mgso4", "anhydrous"}."""
    text = text or u""
    if isinstance(text, bytes):                     # a Py2 str from a stored field
        text = text.decode("utf-8", "replace")
    t = unicodedata.normalize("NFKD", text.translate(_SUBSCRIPTS)).lower()
    return frozenset(w for w in re.findall(r"[a-z0-9]+", t)
                     if w not in _STOP and len(w) > 1)


def _same_item(a, b):
    return (a or u"").strip().lower() == (b or u"").strip().lower() and bool(a)


def match_score(role, name):
    """Share of the role's words found in the item's name (0..1)."""
    r = _tokens(role)
    return len(r & _tokens(name)) / float(len(r)) if r else 0.0


def rank_lots(lots, role, remembered=None):
    """Remembered lot, then other lots of the remembered item, then by how
    well the name matches the role (share of its words, then fewest extra
    words); within that the newest lot first, undated lots last."""
    rem = remembered or {}

    def key(it):
        if rem.get("uid") and it.get("uid") == rem.get("uid"):
            tier = 0
        elif _same_item(it.get("name"), rem.get("name")):
            tier = 1
        else:
            tier = 2
        received = it.get("received") or u""
        return (tier, -match_score(role, it.get("name")),
                len(_tokens(it.get("name")) - _tokens(role)),   # fewer extra words
                not received, [-ord(c) for c in received],    # newest; undated last
                (it.get("name") or u"").lower(), it.get("lot_number") or u"")
    return sorted(lots or [], key=key)


def suggested(lots, role, remembered=None):
    rem = remembered or {}
    return [it for it in rank_lots(lots, role, rem)
            if (rem.get("uid") and it.get("uid") == rem.get("uid"))
            or _same_item(it.get("name"), rem.get("name"))
            or match_score(role, it.get("name")) > 0]


def default_pick(lots, role, remembered=None):
    """The lot to preselect: the remembered lot or the newest lot of the
    remembered item; with no memory, the best name match only if it holds
    MORE than half the role's words (one shared word such as "anhydrous" is
    not a match). None rather than a guess: the chemist picks, and the pick
    is remembered."""
    ranked = rank_lots(lots, role, remembered)
    if not ranked:
        return None
    top = ranked[0]
    rem = remembered or {}
    if (rem.get("uid") and top.get("uid") == rem.get("uid")) or \
            _same_item(top.get("name"), rem.get("name")):
        return top
    return top if match_score(role, top.get("name")) > 0.5 else None


def resolve_rows(index, rows):
    """Each reagent row as the inventory has it NOW, never as the browser sent
    it (a typed or stale expiry is not evidence). `index` = {(kind, uid): item}.
    A linked row takes name, lot, expiry, status, category, supplier and
    catalogue number from its record (kind defaults to "reagent", the only
    kind before phase 2); an unlinked row keeps what was typed and says so
    (from_inventory False); a link to a lot that no longer exists is kept and
    marked inventory_missing."""
    out = []
    for r in rows or []:
        row = dict(r)
        uid = row.get("inventory_uid") or u""
        kind = row.get("kind") or u"reagent"
        item = (index or {}).get((kind, uid)) if uid else None
        if item is not None:
            row.update({"kind": kind, "name": item.get("name") or u"",
                        "lot": item.get("lot_number") or u"",
                        "expiry": item.get("expiry") or u"",
                        "status_at_use": item.get("status") or u"",
                        "category": item.get("category") or u"",
                        "supplier": item.get("supplier") or u"",
                        "cat_number": item.get("cat_number") or u"",
                        "from_inventory": True})
        else:
            row["from_inventory"] = False
            if uid:
                row["inventory_missing"] = True
        out.append(row)
    return out


STANDARD_CATEGORIES = (u"Standard / Reference Material", u"Internal Standard")


def is_consumable_row(row):
    """A stage consumable, or an inventory lot filed as a Consumable."""
    return row.get("group") == u"consumable" or (
        row.get("from_inventory") and (row.get("category") or u"") == u"Consumable")


def is_standard_row(row):
    """FM-ENV-003 standards[] (resolves a prepared standard OR a reagent) or
    reagents[] (resolves a reagent only), decided by the stored kind: a
    prepared standard filed in reagents[] could never resolve. Rows saved
    before phase 2 carry no kind and keep the old name test."""
    kind = row.get("kind")
    if kind == u"prepared_standard":
        return True
    if kind == u"reagent" and row.get("from_inventory"):
        return (row.get("category") or u"") in STANDARD_CATEGORIES
    name = (row.get("name") or u"").lower()
    return row.get("supplier") == u"In-house" or u"standard" in name or u"spike" in name


def _why_unusable(row, today):
    status = (row.get("status_at_use") or u"").lower()
    if status == u"quarantine":
        return u"quarantined"
    if status in _UNUSABLE:
        return u"used up" if status == u"exhausted" else status
    if _expired({"status": status, "expiry": row.get("expiry")}, today):
        return u"expired (%s)" % (row.get("expiry") or status)
    return u""


def stage_warnings(rows, balances, today):
    """Everything about a stage that DB4 (DECISIONS 2026-10-02) lets the
    chemist go ahead with only after writing a deviation note: a role with no
    lot, a lot typed rather than picked from the inventory or no longer in it,
    a lot expired / quarantined / used up at the time of use, and a balance
    that is not identified or not verified today.

    `rows` = resolved reagent rows (resolve_rows); `balances` = one per stage
    equipment entry that is a balance: {"label", "serial", "unit_name"
    (None when no registered unit has that serial), "verified"}."""
    out = []
    for r in rows or []:
        what = r.get("role") or r.get("name") or u"Item"
        lot = (r.get("lot") or u"").strip()
        if r.get("inventory_missing"):
            out.append(u"%s: lot %s is no longer in the inventory" % (what, lot or u"?"))
        elif not lot:
            out.append(u"%s: no lot recorded" % what)
        elif not r.get("from_inventory"):
            out.append(u"%s: lot %s was typed, not picked from the inventory" % (what, lot))
        else:
            why = _why_unusable(r, today)
            if why:
                out.append(u"%s: lot %s is %s" % (what, lot, why))
    for b in balances or []:
        label = b.get("label") or u"Balance"
        if not b.get("unit_name"):
            serial = (b.get("serial") or u"").strip()
            out.append(u"%s: %s" % (label, (
                u"no registered balance has serial %s (register it in Facility QC)" % serial)
                if serial else u"no serial number recorded"))
        elif not b.get("verified"):
            out.append(u"%s (%s): not verified today" % (label, b["unit_name"]))
    return out


def equipment_family(label):
    """The Facility QC unit family a stage equipment label names: a balance
    (verified daily) or a pipette (calibrated on a period); "" for equipment
    Facility QC does not register (vortex, centrifuge, manifold...)."""
    words = _tokens(label)
    if any(w.startswith(u"balance") for w in words):
        return u"balance"
    if any(w.startswith(u"pipet") for w in words):
        return u"pipette"
    return u""


def units_for(label, units):
    """Registered, active units of the family the label names."""
    fam = equipment_family(label)
    if not fam:
        return []
    return [u for u in units or []
            if (u.get("unit_type") or u"").startswith(fam) and u.get("active", 1)]


def lot_on_file(items, lot):
    """The inventory lot with this lot number, whatever its status. A lot the
    picker did not offer may still be on file -- expired or quarantined --
    and receiving it again would make a second record of the same lot."""
    want = (lot or u"").strip().lower()
    if not want:
        return None
    for it in items or []:
        if (it.get("lot_number") or u"").strip().lower() == want:
            return it
    return None
