# -*- coding: utf-8 -*-
"""Where Import Studio's layout profiles live (one portal annotation), and the
lookup the pipeline worker's import makes (@@pfas-instrument-profile).

    IAnnotations(portal)["senaite.pfas.import_layouts"]
        = PersistentMapping {layout id: json text of the profile}

The profile's shape and every rule about reading and matching a file are
senaite.pfas.import_layouts (pure, shared with the worker). Every save,
retirement and deletion is recorded in Configuration History (store
"import_profile") and in Import Studio's own audit list.

The profiles saved before layouts existed ("vendor:version" at
senaite.pfas.vendor_profiles) are moved here once per site (migrate), keeping
what they mapped; each instrument's own earlier profiles
(senaite.pfas.instrument_profiles, never read by the worker) come too, as
retired layouts bound to it. The old annotations are left as they were.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging


from senaite.pfas import import_layouts
from senaite.pfas.annotation_store import mapping

logger = logging.getLogger("senaite.pfas.import_layouts_store")

LAYOUTS_KEY = "senaite.pfas.import_layouts"
HISTORY_STORE = "import_profile"


def _store(portal):
    return mapping(portal, LAYOUTS_KEY)


def _peek(portal):
    """The store without creating it (reads never write)."""
    return mapping(portal, LAYOUTS_KEY, create=False)


def _load(raw):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def list_profiles(portal):
    """Every saved layout profile, by name."""
    out = []
    for lid, raw in _peek(portal).items():
        p = _load(raw)
        if p:
            p["id"] = lid
            out.append(p)
    return sorted(out, key=lambda p: (p.get("name") or "").lower())


def get(portal, layout_id):
    raw = _peek(portal).get(layout_id)
    p = _load(raw) if raw else None
    if p:
        p["id"] = layout_id
    return p


def _track(portal, layout_id, name, action, reason=""):
    from senaite.pfas import config_history
    config_history.track(portal, HISTORY_STORE, layout_id, lambda: get(portal, layout_id),
                         label="Import layout %s" % (name or layout_id), action=action, reason=reason)


def _new_id(store):
    n = 1
    while "layout-%d" % n in store:
        n += 1
    return "layout-%d" % n


def save(portal, profile):
    """Save a layout profile (a new one gets an id); returns its id."""
    store = _store(portal)
    lid = profile.get("id") or _new_id(store)
    _track(portal, lid, profile.get("name"), "save layout")
    data = dict(profile, id=lid)
    store[lid] = json.dumps(data, sort_keys=True)
    return lid


def delete(portal, layout_id, reason=""):
    """Delete a layout profile (its history keeps what it was). False when
    there is no such profile."""
    store = _store(portal)
    if layout_id not in store:
        return False
    name = (get(portal, layout_id) or {}).get("name") or layout_id
    _track(portal, layout_id, name, "delete layout", reason)
    del store[layout_id]
    return True


def set_retired(portal, layout_id, retired, reason=""):
    p = get(portal, layout_id)
    if p is None:
        return False
    _track(portal, layout_id, p.get("name"), "retire layout" if retired else "reactivate layout", reason)
    p["retired"] = bool(retired)
    _store(portal)[layout_id] = json.dumps(p, sort_keys=True)
    return True


def match_file(portal, head="", instrument_uid="", columns=None):
    """The layout profile a file fits (raises import_layouts.LayoutRefused).
    `columns` (a header row an older worker sent) is matched as a
    comma-separated header line."""
    if not head and columns:
        head = ",".join('"%s"' % ("%s" % c).replace('"', '""') for c in columns) + "\n"
    return import_layouts.match(list_profiles(portal), head or "", instrument_uid or "")


