# -*- coding: utf-8 -*-
"""The inventory as the bench sees it: reagents and prepared standards in one
shape, which lots may be used today, and the lab's remembered pick per method
role (DECISIONS 2026-10-02 "Bench phase 2").

    inventory_items(portal)          -> [item]   every lot, one shape
    usable_lots(portal, today)       -> [item]   bench_queue.is_usable only
    item_index(portal)               -> {(kind, uid): item}
    role_picks(portal, method_id)    -> {role: {"uid", "kind", "name"}}
    remember_picks(portal, method_id, rows)

item = {"uid", "kind" ("reagent" | "prepared_standard"), "kind_label", "name",
        "lot_number", "expiry", "status", "category", "received", "supplier",
        "cat_number", "barcode", "is_archived", "quantity_value",
        "low_stock_level", "quantity_unit", "remaining_text"}

quantity_value is what is LEFT (received less every recorded use,
inventory_ledger), in quantity_unit; low_stock_level is in that unit.

`uid` is the object id inside its own folder, so a lot is named by
(kind, uid). Expiry is the effective one each folder already computes
(a reagent's inheritance chain with the lab's defaults; a prepared standard's
parent-tightened date) -- read, never recomputed here.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.browser.bench_inventory")

ROLE_PICKS_KEY = u"senaite.pfas.extraction.role_picks"
REAGENT, PREPARED = u"reagent", u"prepared_standard"
KIND_LABELS = {REAGENT: u"Reagent", PREPARED: u"Prepared standard"}


def _stock(received_text, unit, low_text, uses):
    """quantity_value / quantity_unit = what is left (inventory_ledger.
    remaining); low_stock_level converted to that unit; remaining_text for
    display. All None/"" when the received amount is not a number + unit."""
    from senaite.pfas.inventory_ledger import convert, parse_amount, remaining
    left = remaining(received_text, unit, uses)
    if left is None:
        return {"quantity_value": None, "quantity_unit": unit or u"",
                "low_stock_level": None, "remaining_text": u""}
    low = parse_amount(low_text, left["unit"]) if low_text else None
    low_v = convert(low[0], low[1], left["unit"]) if low else None
    return {"quantity_value": left["value"], "quantity_unit": left["unit"],
            "low_stock_level": low_v,
            "remaining_text": u"{0:g} {1} left".format(left["value"], left["unit"])}


def inventory_items(portal):
    items = []
    try:
        from senaite.pfas.inventory_ledger import uses_for_items
        uses = uses_for_items()
    except Exception as exc:                                # noqa: BLE001
        logger.warning("inventory usage ledger unavailable: %s", exc)
        uses = {}
    try:
        from senaite.pfas.browser.reagents import (
            _list_reagents, _effective_expiry, get_expiry_defaults)
        defaults = get_expiry_defaults(portal)
        for r in _list_reagents(portal, show_archived=True):
            item = {
                "uid": r.get("uid") or u"", "kind": REAGENT,
                "kind_label": KIND_LABELS[REAGENT],
                "name": r.get("name") or u"", "lot_number": r.get("lot_number") or u"",
                "expiry": _effective_expiry(r, defaults) or u"",
                "status": r.get("status") or u"", "category": r.get("category") or u"",
                "received": r.get("received_date") or u"",
                "supplier": r.get("supplier") or u"", "cat_number": r.get("cat_number") or u"",
                "barcode": r.get("barcode") or u"",
                "is_archived": bool(r.get("is_archived")),
            }
            item.update(_stock(r.get("quantity"), r.get("unit"), r.get("low_stock_level"),
                               uses.get((REAGENT, r.get("uid") or u""))))
            items.append(item)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("inventory (reagents): %s", exc)
    try:
        from senaite.pfas.browser.prepared_standards import _list
        for s in _list(portal):
            item = {
                "uid": s.get("uid") or u"", "kind": PREPARED,
                "kind_label": KIND_LABELS[PREPARED],
                "name": s.get("title") or u"", "lot_number": s.get("lot_number") or u"",
                "expiry": s.get("effective_expiry") or u"",
                "status": s.get("status") or u"", "category": s.get("standard_type") or u"",
                "received": s.get("prepared_date") or u"",
                "supplier": u"In-house", "cat_number": u"", "barcode": u"",
                "is_archived": False,
            }
            # a prepared standard's received amount is the volume prepared
            item.update(_stock(s.get("volume_prepared"), u"", u"",
                               uses.get((PREPARED, s.get("uid") or u""))))
            items.append(item)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("inventory (prepared standards): %s", exc)
    return items


def usable_lots(portal, today):
    from senaite.pfas.bench_queue import is_usable
    return [i for i in inventory_items(portal) if is_usable(i, today)]


def item_index(portal):
    return dict(((i["kind"], i["uid"]), i) for i in inventory_items(portal))


def _load(portal):
    try:
        return json.loads(IAnnotations(portal).get(ROLE_PICKS_KEY) or u"{}")
    except (TypeError, ValueError):
        return {}


def role_picks(portal, method_id):
    return _load(portal).get(method_id or u"", {})


def remember_picks(portal, method_id, rows):
    """Remember, per method role, the lot each inventory-linked row used."""
    if not method_id:
        return
    data = _load(portal)
    picks = data.setdefault(method_id, {})
    changed = False
    for r in rows or []:
        role, uid = r.get("role") or u"", r.get("inventory_uid") or u""
        if role and uid:
            new = {"uid": uid, "kind": r.get("kind") or REAGENT, "name": r.get("name") or u""}
            if picks.get(role) != new:
                picks[role] = new
                changed = True
    if changed:
        IAnnotations(portal)[ROLE_PICKS_KEY] = json.dumps(data)
