# -*- coding: utf-8 -*-
"""Where every inventory lot was used, and how much is left.

One row per lot per extraction stage: lot, batch, stage, role, amount, who,
when. A lot's page lists where it was used; a recall search by lot number
answers "which batches used methanol lot X?".

What is left is DERIVED -- the amount received less every recorded use,
converted to the stock unit -- never decremented in place. A stage that is
completed again replaces its own rows (record_stage), so nothing is counted
twice and nothing drifts.

Cross-object, time-indexed data, so SQLite, beside the other
QC databases. Pure apart from sqlite3; Python 2.7 and 3.

    parse_amount(text, default_unit="")  -> (value, unit) or None
    convert(value, from_unit, to_unit)   -> value or None (different kinds)
    remaining(received_text, stock_unit, uses) -> {"value", "unit", "used",
                                                   "unconverted"} or None
    record_stage(path, batch_uid, batch_id, stage_order, stage_name, rows, by, at)
    uses_of(path, kind, uid) / uses_by_lot(path, text) / uses_for_items(path)
"""
from __future__ import absolute_import, division, unicode_literals

import os
import re
import sqlite3

DB_PATH = os.environ.get("PFAS_INVENTORY_DB", "/data/qc/inventory_usage.db")

# Physical conversions (not lab values): each unit -> (kind, factor to base).
_UNITS = {
    u"ul": (u"volume", 1e-3), u"µl": (u"volume", 1e-3), u"μl": (u"volume", 1e-3),
    u"ml": (u"volume", 1.0), u"l": (u"volume", 1e3),
    u"mg": (u"mass", 1e-3), u"g": (u"mass", 1.0), u"kg": (u"mass", 1e3),
}
_COUNT = frozenset([u"ea", u"each", u"pc", u"pcs", u"piece", u"pieces", u"unit", u"units",
                    u"cartridge", u"cartridges", u"tube", u"tubes", u"vial", u"vials",
                    u"syringe", u"syringes", u"filter", u"filters", u"box", u"boxes"])

_AMOUNT = re.compile(
    u"^\\s*(?:(\\d+(?:\\.\\d+)?)\\s*[x×]\\s*)?(\\d+(?:\\.\\d+)?|\\.\\d+)\\s*([^\\d\\s][^\\s]*)?\\s*$",
    re.I | re.U)


def _norm_unit(unit):
    u = (unit or u"").strip().lower().rstrip(u".")
    if isinstance(u, bytes):
        u = u.decode("utf-8", "replace")
    return u


def _kind(unit):
    u = _norm_unit(unit)
    if u in _UNITS:
        return _UNITS[u]
    if u in _COUNT:
        return (u"count", 1.0)
    return None


def parse_amount(text, default_unit=u""):
    """"5 mL" -> (5.0, "mL"); "10 x 1 mL" -> (10.0, "mL"); "3" with a default
    unit -> (3.0, default). None when there is no number or no unit."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return (float(text), default_unit) if default_unit else None
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    m = _AMOUNT.match(text)
    if not m:
        return None
    mult = float(m.group(1)) if m.group(1) else 1.0
    unit = (m.group(3) or default_unit or u"").strip()
    if not unit:
        return None
    return (mult * float(m.group(2)), unit)


def convert(value, from_unit, to_unit):
    a, b = _kind(from_unit), _kind(to_unit)
    if a is None or b is None or a[0] != b[0]:
        return None
    if a[0] == u"count":
        return float(value)                 # any count word is one item
    return float(value) * a[1] / b[1]


def remaining(received_text, stock_unit, uses):
    """What is left of a lot. `uses` = [{"amount_value", "amount_unit"}].
    None when the received amount is not a number with a unit (free text
    such as "1 case" is shown as it is, never counted down)."""
    got = parse_amount(received_text, stock_unit)
    if got is None or _kind(got[1]) is None:
        return None
    total, unit = got
    used, unconverted = 0.0, 0
    for u in uses or []:
        if u.get("amount_value") is None:
            continue
        v = convert(u["amount_value"], u.get("amount_unit"), unit)
        if v is None:
            unconverted += 1
        else:
            used += v
    return {"value": round(total - used, 6), "unit": unit, "used": round(used, 6),
            "received": total, "unconverted": unconverted}


# ── SQLite ledger ─────────────────────────────────────────────────────────────

_SCHEMA = u"""
CREATE TABLE IF NOT EXISTS inventory_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, uid TEXT NOT NULL, lot TEXT, item_name TEXT,
    batch_uid TEXT NOT NULL, batch_id TEXT, stage_order TEXT NOT NULL, stage_name TEXT,
    role TEXT, amount_text TEXT, amount_value REAL, amount_unit TEXT,
    used_by TEXT, used_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_usage_item ON inventory_usage (kind, uid);
CREATE INDEX IF NOT EXISTS ix_usage_lot ON inventory_usage (lot);
CREATE INDEX IF NOT EXISTS ix_usage_stage ON inventory_usage (batch_uid, stage_order);
"""


def _connect(path=None):
    path = path or DB_PATH
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def record_stage(path, batch_uid, batch_id, stage_order, stage_name, rows, by, at,
                 stock_units=None):
    """Replace what one extraction stage used. Only inventory-linked rows
    with a lot are recorded; the amount is parsed in the lot's stock unit
    when the chemist gave a bare number (`stock_units` = {(kind, uid): unit})."""
    stock_units = stock_units or {}
    conn = _connect(path)
    try:
        with conn:
            conn.execute("DELETE FROM inventory_usage WHERE batch_uid=? AND stage_order=?",
                         (batch_uid, u"%s" % stage_order))
            for r in rows or []:
                if not (r.get("from_inventory") and r.get("inventory_uid") and r.get("lot")):
                    continue
                kind = r.get("kind") or u"reagent"
                text = (r.get("qty_used") or u"").strip()
                amt = parse_amount(text, stock_units.get((kind, r["inventory_uid"]), u""))
                conn.execute(
                    "INSERT INTO inventory_usage (kind, uid, lot, item_name, batch_uid, batch_id, "
                    "stage_order, stage_name, role, amount_text, amount_value, amount_unit, "
                    "used_by, used_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (kind, r["inventory_uid"], r.get("lot"), r.get("name"), batch_uid, batch_id,
                     u"%s" % stage_order, stage_name, r.get("role"), text,
                     amt[0] if amt else None, amt[1] if amt else None, by, at))
    finally:
        conn.close()


def _rows(conn, sql, args):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def uses_of(path, kind, uid):
    conn = _connect(path)
    try:
        return _rows(conn, "SELECT * FROM inventory_usage WHERE kind=? AND uid=? "
                           "ORDER BY used_at DESC, id DESC", (kind, uid))
    finally:
        conn.close()


def uses_for_batch(path, batch_id):
    """Every lot one extraction batch (worksheet) used, stage by stage: what
    the blank history compares."""
    conn = _connect(path)
    try:
        return _rows(conn, "SELECT * FROM inventory_usage WHERE batch_id=? "
                           "ORDER BY stage_order, id", (batch_id,))
    finally:
        conn.close()


def uses_by_lot(path, text):
    """Recall: every use of a lot whose number contains `text` (case-blind)."""
    conn = _connect(path)
    try:
        return _rows(conn, "SELECT * FROM inventory_usage WHERE lower(lot) LIKE ? "
                           "ORDER BY used_at DESC, id DESC",
                     (u"%{0}%".format((text or u"").strip().lower()),))
    finally:
        conn.close()


def uses_for_items(path=None):
    """{(kind, uid): [use, ...]} for every lot, for the remaining stock."""
    conn = _connect(path)
    try:
        out = {}
        for r in _rows(conn, "SELECT kind, uid, amount_value, amount_unit FROM inventory_usage", ()):
            out.setdefault((r["kind"], r["uid"]), []).append(r)
        return out
    finally:
        conn.close()
