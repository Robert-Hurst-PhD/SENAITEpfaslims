# -*- coding: utf-8 -*-
"""Consumables are recorded by lot, from the inventory, not as equipment
with a serial number ("Bench phase 2").

Each extraction stage carries a `consumables` list beside `reagent_roles`
and `equipment`. This moves the stage "equipment" entries that are
consumables -- tubes, vials, syringes, filters -- into it, once, keeping
their order; every stage gets the key so the stage editor shows the list.

    is_consumable(name)        -> bool
    split_consumables(profile) -> True when the profile changed

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import re

CONSUMABLE_WORDS = (u"tube", u"vial", u"syringe", u"filter")


def is_consumable(name):
    words = re.findall(r"[a-z]+", (name or u"").lower())
    return any(w.rstrip(u"s") in CONSUMABLE_WORDS for w in words)


def split_consumables(profile):
    changed = False
    for st in (profile or {}).get("extraction_stages") or []:
        if "consumables" not in st:
            st["consumables"] = []
            changed = True
        keep, moved = [], []
        for e in st.get("equipment") or []:
            (moved if is_consumable(e) else keep).append(e)
        if moved:
            st["equipment"] = keep
            st["consumables"] = list(st["consumables"]) + [
                m for m in moved if m not in st["consumables"]]
            changed = True
    return changed
