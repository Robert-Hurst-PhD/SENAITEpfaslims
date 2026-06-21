# -*- coding: utf-8 -*-
"""
PFAS logbook definition store.

Logbook definitions live as ``LogbookDef`` Dexterity content objects inside
``portal/pfas_logbook_defs/``.  Before that folder is created (pre-migration)
the store falls back to the portal annotation key below so the system works
immediately after add-on install even before ``post_install`` runs.

Annotation key (legacy / fallback):  "senaite.pfas.logbook_defs"  on portal.
Value: JSON-encoded list of definition dicts.

Each definition dict (same shape whether read from Dexterity or annotations):
  slug       str   — unique ID; object id in pfas_logbook_defs/
  form_num   str   — display code shown in the index (e.g. "FM-ENV-250")
  title      str   — human-readable name (from plone.dublincore)
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


# ── internal helpers ──────────────────────────────────────────────────────────

def _get_folder(portal):
    """Return the pfas_logbook_defs Folder or None (pre-migration)."""
    return portal.get("pfas_logbook_defs")


def _obj_to_dict(obj):
    """Convert a LogbookDef content object to the standard def dict."""
    return {
        "slug":          obj.getId(),
        "form_num":      getattr(obj, "form_num", u"") or u"",
        "title":         obj.Title() or obj.getId(),
        "builtin":       bool(getattr(obj, "builtin", False)),
        "active":        bool(getattr(obj, "active", True)),
        "table_columns": list(getattr(obj, "table_columns", None) or []),
    }


def _merge_defaults(saved_defs):
    """Ensure every built-in slug appears in the saved list."""
    saved_slugs = {d["slug"] for d in saved_defs}
    result = list(saved_defs)
    for default in DEFAULT_LOGBOOK_DEFS:
        if default["slug"] not in saved_slugs:
            result.append(dict(default))
    return result


# ── public API — same signatures as before ────────────────────────────────────

def get_logbook_defs(portal):
    """Return list of all logbook definition dicts (active and inactive)."""
    folder = _get_folder(portal)
    if folder is not None:
        # Dexterity path
        try:
            objs = [folder[oid] for oid in folder.objectIds()]
            objs.sort(key=lambda o: (getattr(o, "sort_order", 0) or 0))
            return _merge_defaults([_obj_to_dict(o) for o in objs])
        except Exception as exc:
            logger.warning("Cannot load logbook defs from content: %s", exc)

    # Annotation fallback
    try:
        ann = IAnnotations(portal)
        raw = ann.get(LOGBOOK_DEFS_KEY)
        if raw:
            return _merge_defaults(json.loads(raw))
    except Exception as exc:
        logger.warning("Cannot load logbook defs from annotations: %s", exc)

    return [dict(d) for d in DEFAULT_LOGBOOK_DEFS]


def get_active_logbook_defs(portal):
    """Return only active logbook definitions."""
    return [d for d in get_logbook_defs(portal) if d.get("active", True)]


def save_logbook_defs(portal, defs):
    """Persist the logbook definition list."""
    folder = _get_folder(portal)
    if folder is None:
        # Annotation fallback (pre-migration)
        try:
            ann = IAnnotations(portal)
            ann[LOGBOOK_DEFS_KEY] = json.dumps(defs)
        except Exception as exc:
            logger.error("Cannot save logbook defs to annotations: %s", exc)
        return

    # Dexterity path
    try:
        existing_ids = set(folder.objectIds())
        new_slugs = {d.get("slug") for d in defs if d.get("slug")}

        for i, d in enumerate(defs):
            slug = d.get("slug", "")
            if not slug:
                continue

            if slug not in existing_ids:
                folder.invokeFactory("LogbookDef", id=slug,
                                     title=d.get("title") or slug)
                existing_ids.add(slug)

            obj = folder[slug]
            obj.title = d.get("title") or slug
            obj.form_num = d.get("form_num") or u""
            obj.builtin = bool(d.get("builtin", False))
            obj.active = bool(d.get("active", True))
            obj.sort_order = i
            obj.table_columns = [c for c in (d.get("table_columns") or []) if c]
            try:
                obj.reindexObject()
            except Exception:
                pass

        # Remove objects no longer in the list; never delete built-ins.
        for slug in list(existing_ids):
            if slug not in new_slugs and not is_builtin(slug):
                try:
                    folder._delObject(slug)
                except Exception as exc:
                    logger.warning("Cannot delete logbook def %r: %s", slug, exc)

    except Exception as exc:
        logger.error("Cannot save logbook defs to content: %s", exc)


def seed_defaults(portal):
    """Idempotently seed the default logbook definitions (annotation path only)."""
    folder = _get_folder(portal)
    if folder is not None:
        # Dexterity folder is authoritative; nothing to seed here.
        return
    try:
        ann = IAnnotations(portal)
        if LOGBOOK_DEFS_KEY not in ann:
            ann[LOGBOOK_DEFS_KEY] = json.dumps(
                [dict(d) for d in DEFAULT_LOGBOOK_DEFS]
            )
    except Exception as exc:
        logger.warning("Cannot seed logbook defaults: %s", exc)


def is_builtin(slug):
    return slug in _BUILTIN_SLUGS
