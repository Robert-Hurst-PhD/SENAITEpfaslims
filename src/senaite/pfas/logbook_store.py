# -*- coding: utf-8 -*-
"""
PFAS logbook definition store.

Logbook definitions (title, form number, active state, custom fields) are
stored in ZODB portal annotations so managers can rename, reorder, add, and
remove logbooks through the admin UI without touching source code.

Annotation key:  "senaite.pfas.logbook_defs"  on the portal object.
Value: JSON-encoded list of definition dicts.

Each definition dict:
  slug       str   — unique ID; "250"–"253" for built-ins, "custom-<hex>" for new
  form_num   str   — display code shown in the index (e.g. "FM-ENV-250")
  title      str   — human-readable name
  builtin    bool  — True for the original four (can rename, cannot delete)
  active     bool  — False hides from the logbook index
  table_columns  list[str]  — (custom only) column names for the data table

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.logbook_store")

LOGBOOK_DEFS_KEY = u"senaite.pfas.logbook_defs"

DEFAULT_LOGBOOK_DEFS = [
    {
        "slug":          "250",
        "form_num":      "FM-ENV-250",
        "title":         "Solvent / Reagent Prep Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
    },
    {
        "slug":          "251",
        "form_num":      "FM-ENV-251",
        "title":         "Calibration Curve Prep Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
    },
    {
        "slug":          "252",
        "form_num":      "FM-ENV-252",
        "title":         "Extraction Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
    },
    {
        "slug":          "253",
        "form_num":      "FM-ENV-253",
        "title":         "Sample Processing Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
    },
]

_BUILTIN_SLUGS = frozenset(d["slug"] for d in DEFAULT_LOGBOOK_DEFS)


def get_logbook_defs(portal):
    """Return list of all logbook definition dicts (active and inactive)."""
    try:
        ann = IAnnotations(portal)
        raw = ann.get(LOGBOOK_DEFS_KEY)
        if raw:
            return _merge_defaults(json.loads(raw))
        return [dict(d) for d in DEFAULT_LOGBOOK_DEFS]
    except Exception as exc:
        logger.warning("Cannot load logbook defs: %s", exc)
        return [dict(d) for d in DEFAULT_LOGBOOK_DEFS]


def get_active_logbook_defs(portal):
    """Return only active logbook definitions."""
    return [d for d in get_logbook_defs(portal) if d.get("active", True)]


def save_logbook_defs(portal, defs):
    """Persist the logbook definition list."""
    try:
        ann = IAnnotations(portal)
        ann[LOGBOOK_DEFS_KEY] = json.dumps(defs)
    except Exception as exc:
        logger.error("Cannot save logbook defs: %s", exc)


def seed_defaults(portal):
    """Idempotently seed the default logbook definitions."""
    try:
        ann = IAnnotations(portal)
        if LOGBOOK_DEFS_KEY not in ann:
            save_logbook_defs(portal, [dict(d) for d in DEFAULT_LOGBOOK_DEFS])
    except Exception as exc:
        logger.warning("Cannot seed logbook defaults: %s", exc)


def is_builtin(slug):
    return slug in _BUILTIN_SLUGS


def _merge_defaults(saved_defs):
    """Ensure every built-in slug appears in the saved list."""
    saved_slugs = {d["slug"] for d in saved_defs}
    result = list(saved_defs)
    for default in DEFAULT_LOGBOOK_DEFS:
        if default["slug"] not in saved_slugs:
            result.append(dict(default))
    return result
