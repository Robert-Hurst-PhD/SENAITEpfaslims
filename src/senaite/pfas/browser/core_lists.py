# -*- coding: utf-8 -*-
"""Reagent suppliers and storage places come from core SENAITE's lists
(: one owner per fact).

The reagent and prepared-standard forms used to take free text, so the same
supplier appeared under two spellings and three storage lists existed. Now:

    supplier          a core Supplier (Setup -> Suppliers), or "In-house" for
                      what the lab makes itself
    storage_location  a core Storage Location (Setup -> Storage Locations)

The records keep the name (a title), so every existing reader is unchanged;
renaming a Supplier or Storage Location in core renames it on every reagent
and prepared standard (on_core_list_modified). Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.core_lists")

IN_HOUSE = u"In-house"
TITLES_KEY = "senaite.pfas.core_list_titles"        # {uid: title last seen}
_FOLDERS = {"supplier": "suppliers", "storage_location": "storagelocations"}


def titles(kind):
    """Sorted titles of the active core objects behind `kind`."""
    try:
        from bika.lims import api
        folder = api.get_senaite_setup()[_FOLDERS[kind]]
        return sorted(o.Title() for o in folder.objectValues() if api.is_active(o))
    except Exception:                                       # noqa: BLE001
        logger.warning("core list %s unreadable", kind, exc_info=True)
        return []


def supplier_titles():
    return titles("supplier")


def storage_titles():
    return titles("storage_location")


def problems(data, kinds=("supplier", "storage_location")):
    """[message] for a value that is not on its core list (blank is allowed;
    "In-house" is a supplier)."""
    out = []
    for kind in kinds:
        value = (data.get(kind) or u"").strip()
        if not value or (kind == "supplier" and value == IN_HOUSE):
            continue
        if value not in titles(kind):
            out.append(u"%s is not a core %s: pick one from the list, or add it in Setup -> %s first."
                       % (value, u"Supplier" if kind == "supplier" else u"Storage Location",
                          u"Suppliers" if kind == "supplier" else u"Storage Locations"))
    return out


def remember_titles(portal):
    """Record every Supplier / Storage Location title, so a later rename is
    recognised (on_core_list_modified)."""
    from bika.lims import api
    from persistent.mapping import PersistentMapping
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    store = ann.get(TITLES_KEY)
    if store is None:
        store = ann[TITLES_KEY] = PersistentMapping()
    for kind, fid in _FOLDERS.items():
        for o in api.get_senaite_setup()[fid].objectValues():
            store[api.get_uid(o)] = o.Title()
    return store


def rename_on_records(portal, kind, old, new):
    """Rename `old` to `new` in the `kind` field of every reagent and prepared
    standard. Returns how many changed."""
    n = 0
    folders = ["pfas_reagents"] + (["pfas_prepared_standards"] if kind == "storage_location" else [])
    for fid in folders:
        folder = getattr(portal, fid, None)
        for obj in (folder.objectValues() if folder is not None else []):
            if (getattr(obj, kind, u"") or u"") == old:
                setattr(obj, kind, new)
                obj.reindexObject()
                n += 1
    return n


def on_core_list_modified(obj, event):
    """IObjectModifiedEvent on a core Supplier / Storage Location: follow a
    title change onto the reagents and prepared standards."""
    try:
        from bika.lims import api
        from zope.annotation.interfaces import IAnnotations
        portal = api.get_portal()
        store = IAnnotations(portal).get(TITLES_KEY)
        if store is None:
            store = remember_titles(portal)
        uid, new = api.get_uid(obj), obj.Title()
        old = store.get(uid)
        kind = "supplier" if obj.portal_type == "Supplier" else "storage_location"
        if old and old != new:
            n = rename_on_records(portal, kind, old, new)
            logger.info("core %s renamed %s -> %s on %d record(s)", kind, old, new, n)
        store[uid] = new
    except Exception:                                       # noqa: BLE001
        logger.exception("core list rename not followed")
