# -*- coding: utf-8 -*-
"""
PFAS logbook definition store.

NOW authoritative source: PrepLogbookDef objects in ``portal/pfas_prep_logbooks/``.
The four built-in logbooks (250/251/252/253) are seeded there by
``seed_builtin_logbook_defs()`` called from ``post_install``.

Legacy fallback (pre-migration): portal annotation key ``senaite.pfas.logbook_defs``
and the hardcoded DEFAULT_LOGBOOK_DEFS list are still consulted if the
pfas_prep_logbooks folder is empty.

Public API dict format (unchanged for callers):
  slug       str   — logbook_slug from PrepLogbookDef
  form_num   str   — logbook_code from PrepLogbookDef
  title      str   — title
  builtin    bool  — cannot delete
  active     bool  — shown in batch logbook index
  table_columns  list[str]  — always [] (columns now live in field_schema_json)
  field_schema_json  str    — raw JSON string (for dynamic renderer routing)
  method_slug  str          — owning method slug

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import re
import logging
import uuid

from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.logbook_store")

LOGBOOK_DEFS_KEY = u"senaite.pfas.logbook_defs"

DEFAULT_LOGBOOK_DEFS = [
    {
        "slug":          "250",
        "form_num":      "FM-ENV-001",
        "title":         "Solvent / Reagent Prep Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
        "field_schema_json": "[]",
        "method_slug":   "",
    },
    {
        "slug":          "251",
        "form_num":      "FM-ENV-002",
        "title":         "Calibration Curve Prep Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
        "field_schema_json": "[]",
        "method_slug":   "",
    },
    {
        "slug":          "252",
        "form_num":      "FM-ENV-003",
        "title":         "Extraction Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
        "field_schema_json": "[]",
        "method_slug":   "",
    },
    {
        "slug":          "253",
        "form_num":      "FM-ENV-004",
        "title":         "Sample Processing Log",
        "builtin":       True,
        "active":        True,
        "table_columns": [],
        "field_schema_json": "[]",
        "method_slug":   "",
    },
]

_BUILTIN_SLUGS = frozenset(d["slug"] for d in DEFAULT_LOGBOOK_DEFS)


# ── Conversion helpers ─────────────────────────────────────────────────────────

def _prep_def_to_logbook_def(d):
    """Convert a PrepLogbookDef dict to the standard logbook_store dict format."""
    return {
        "slug":          d["logbook_slug"],
        "form_num":      d.get("logbook_code") or d["logbook_slug"],
        "title":         d.get("title") or d["logbook_slug"],
        "builtin":       bool(d.get("builtin", False)),
        "active":        bool(d.get("active", True)),
        "table_columns": [],
        "field_schema_json": d.get("field_schema_json") or "[]",
        "method_slug":   d.get("method_slug") or "",
        # 0 is the FIRST place: `or 100` read it back as 100 and sent the
        # first logbook (FM-ENV-001) to the end of every list
        "sort_order":    int(d["sort_order"]) if d.get("sort_order") not in (None, u"", "") else 100,
    }


def _merge_defaults(saved_defs):
    """Ensure every built-in slug appears in the saved list (legacy fallback)."""
    saved_slugs = {d["slug"] for d in saved_defs}
    result = list(saved_defs)
    for default in DEFAULT_LOGBOOK_DEFS:
        if default["slug"] not in saved_slugs:
            result.append(dict(default))
    return result


# ── PrepLogbookDef helpers ─────────────────────────────────────────────────────

def _find_prep_def_by_slug(portal, slug):
    """Find the best PrepLogbookDef for a given slug (active preferred)."""
    folder = portal.get("pfas_prep_logbooks")
    if folder is None:
        return None
    best = None
    best_rev = -1
    status_order = {"active": 0, "draft": 1, "archived": 2}
    best_status = 9
    for obj in folder.objectValues():
        if obj.portal_type != "PrepLogbookDef":
            continue
        if (getattr(obj, "logbook_slug", "") or "") != slug:
            continue
        rev = int(getattr(obj, "revision", 1) or 1)
        st = status_order.get(getattr(obj, "status", "") or "", 9)
        if st < best_status or (st == best_status and rev > best_rev):
            best = obj
            best_rev = rev
            best_status = st
    return best


# ── Public API ─────────────────────────────────────────────────────────────────

def get_logbook_defs(portal):
    """Return list of all logbook definition dicts (active and inactive).

    Source: PrepLogbookDef objects in pfas_prep_logbooks/ (one per slug family,
    the highest active/draft/archived revision).
    Falls back to legacy annotation store or DEFAULT_LOGBOOK_DEFS.
    """
    try:
        from senaite.pfas.browser.prep_logbooks import _get_active_families
        families = _get_active_families(portal)
        if families:
            return [_prep_def_to_logbook_def(d) for d in families]
    except Exception as exc:
        logger.warning("get_logbook_defs: PrepLogbookDef read failed: %s", exc)

    # Legacy annotation fallback
    try:
        ann = IAnnotations(portal)
        raw = ann.get(LOGBOOK_DEFS_KEY)
        if raw:
            return _merge_defaults(json.loads(raw))
    except Exception as exc:
        logger.warning("get_logbook_defs: annotation fallback failed: %s", exc)

    return [dict(d) for d in DEFAULT_LOGBOOK_DEFS]


def form_code(portal, slug, default=None):
    """The form number the lab gave a logbook (FM-ENV-003...), read from the
    pool -- the one source for every label ("Form
    numbers"). The slug (250-253) is a storage key, never shown as one."""
    for d in get_logbook_defs(portal):
        if u"%s" % d.get("slug") == u"%s" % slug:
            return d.get("form_num") or default or u"%s" % slug
    return default or u"%s" % slug


def normalise_form_codes(portal):
    """Startup: each form number used once (a custom logbook sharing a
    built-in's number takes the next free one), the pool in number order.
    Idempotent; returns [(slug, old, new)]."""
    from senaite.pfas.form_codes import normalise
    defs = get_logbook_defs(portal)
    ordered, renamed = normalise(defs)
    if renamed or [d.get("slug") for d in ordered] != [d.get("slug") for d in defs]:
        save_logbook_defs(portal, ordered)
        for slug, old, new in renamed:
            logger.info("logbook %s: form number %s was already used; now %s", slug, old, new)
    return renamed


def get_active_logbook_defs(portal):
    """Return only logbook defs with active=True."""
    return [d for d in get_logbook_defs(portal) if d.get("active", True)]


def save_logbook_defs(portal, defs):
    """Persist logbook definition changes back to PrepLogbookDef objects.

    Handles: rename (title/form_num), toggle active, add custom, delete
    custom. Never deletes built-in slugs. Refuses (ValueError) a form number
    used twice; stores the pool in form-number order.
    """
    from senaite.pfas.form_codes import duplicates, normalise
    dup = duplicates(defs)
    if dup:
        raise ValueError(u"Form number {0} is already used by another logbook.".format(
            u", ".join(dup)))
    defs, _renamed = normalise(defs)
    try:   # change history (R1)
        from senaite.pfas import config_history
        config_history.track(portal, 'logbook_defs', "all", lambda: get_logbook_defs(portal), label=u"Logbook definitions")
    except Exception:
        pass
    folder = portal.get("pfas_prep_logbooks")
    if folder is None:
        # Annotation fallback (pre-migration)
        try:
            ann = IAnnotations(portal)
            ann[LOGBOOK_DEFS_KEY] = json.dumps(defs)
        except Exception as exc:
            logger.error("save_logbook_defs: annotation write failed: %s", exc)
        return

    saved_slugs = set()
    for i, d in enumerate(defs):
        slug = d.get("slug")
        if not slug:
            continue
        saved_slugs.add(slug)

        # Find existing PrepLogbookDef for this slug
        obj = _find_prep_def_by_slug(portal, slug)

        if obj is None:
            # Create new PrepLogbookDef for a custom logbook
            new_id = "lbdef-" + uuid.uuid4().hex[:8]
            title = d.get("title") or slug
            try:
                folder.invokeFactory("PrepLogbookDef", id=new_id, title=title)
                obj = folder[new_id]
                obj.logbook_slug = slug
                obj.revision = 1
                obj.status = u"active"
                obj.builtin = False
            except Exception as exc:
                logger.error("save_logbook_defs: create failed for slug=%s: %s", slug, exc)
                continue

        # Update editable fields
        obj.title = d.get("title") or obj.title or slug
        obj.logbook_code = d.get("form_num") or u""
        obj.sort_order = i
        raw_active = d.get("active", True)
        obj.active = bool(raw_active)

        try:
            obj.reindexObject()
        except Exception:
            pass

    # Delete custom (non-builtin) PrepLogbookDefs not in the saved list
    for obj in list(folder.objectValues()):
        if obj.portal_type != "PrepLogbookDef":
            continue
        slug = getattr(obj, "logbook_slug", "") or ""
        if slug and slug not in saved_slugs and not bool(getattr(obj, "builtin", False)):
            try:
                folder._delObject(obj.getId())
                logger.info("save_logbook_defs: deleted custom def slug=%s", slug)
            except Exception as exc:
                logger.warning("save_logbook_defs: delete failed slug=%s: %s", slug, exc)


def seed_defaults(portal):
    """Idempotently seed the default logbook definitions.

    Now delegates to seed_builtin_logbook_defs() which writes PrepLogbookDef
    objects.  Falls back to annotation store if the Dexterity folder is absent.
    """
    folder = portal.get("pfas_prep_logbooks")
    if folder is not None:
        try:
            from senaite.pfas.browser.prep_logbooks import seed_builtin_logbook_defs
            seed_builtin_logbook_defs(portal)
        except Exception as exc:
            logger.warning("seed_defaults: seed_builtin_logbook_defs failed: %s", exc)
        return

    # Pre-migration: write to annotation store
    try:
        ann = IAnnotations(portal)
        if LOGBOOK_DEFS_KEY not in ann:
            ann[LOGBOOK_DEFS_KEY] = json.dumps(
                [dict(d) for d in DEFAULT_LOGBOOK_DEFS]
            )
    except Exception as exc:
        logger.warning("seed_defaults: annotation write failed: %s", exc)


def is_builtin(slug):
    return slug in _BUILTIN_SLUGS


def method_key(value):
    """A method reference reduced to letters and digits, lower case, so a
    seeded slug ("fda-32-pfas") and a method ID ("FDA_32PFAS") compare equal.
    Logbook definitions were seeded with the slug while the pool matched the
    ID exactly, so the seeded FDA logbooks were never offered."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())
