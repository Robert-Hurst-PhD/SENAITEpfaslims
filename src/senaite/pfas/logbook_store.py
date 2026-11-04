# -*- coding: utf-8 -*-
"""
PFAS logbook definition store.

Source: PrepLogbookDef objects in ``portal/pfas_prep_logbooks/``.
The four built-in logbooks (250/251/252/253) are seeded there by
``seed_builtin_logbook_defs()`` called from ``post_install``.

With no pfas_prep_logbooks folder, definitions are read from and written to
the portal annotation ``senaite.pfas.logbook_defs``, seeded from
DEFAULT_LOGBOOK_DEFS.

Public API dict format:
  slug       str   — logbook_slug from PrepLogbookDef
  form_num   str   — logbook_code from PrepLogbookDef
  title      str   — title
  builtin    bool  — cannot delete
  active     bool  — shown in batch logbook index
  table_columns  list[str]  — always [] (columns live in field_schema_json)
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
        "scope":         "library",
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
        "scope":         "library",
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
        "scope":         "batch",
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
        "scope":         "batch",
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

# A template's scope: a BATCH logbook is filled for each batch (FM-ENV-003,
# FM-ENV-004, the lab's own); a LIBRARY logbook (FM-ENV-001 / 002) is a prep
# entry that makes Prepared Standard lots (prep_entries.py).
BATCH, LIBRARY = "batch", "library"


def scope_of(d):
    return (d or {}).get("scope") or BATCH


def batch_only(defs):
    """The logbooks filled per batch: not a library prep, and not sample
    receipt, which is recorded on the samples' CoC records (Data Review still
    reads an older batch's CoC logbook)."""
    from senaite.pfas.logbook_roles import role_of
    return [d for d in defs or [] if scope_of(d) != LIBRARY
            and role_of(dict(d, logbook_slug=d.get("slug"))) != u"receipt"]


# ── Conversion helpers ─────────────────────────────────────────────────────────

def _prep_def_to_logbook_def(d):
    """Convert a PrepLogbookDef dict to the standard logbook_store dict format."""
    return {
        "slug":          d["logbook_slug"],
        "form_num":      d.get("logbook_code") or d["logbook_slug"],
        "title":         d.get("title") or d["logbook_slug"],
        "builtin":       bool(d.get("builtin", False)),
        "active":        bool(d.get("active", True)),
        "scope":         d.get("scope") or BATCH,
        "table_columns": [],
        "field_schema_json": d.get("field_schema_json") or "[]",
        "method_slug":   d.get("method_slug") or "",
        # 0 is the first place, not unset: only a missing value sorts last
        "sort_order":    int(d["sort_order"]) if d.get("sort_order") not in (None, u"", "") else 100,
    }


def _merge_defaults(saved_defs):
    """Ensure every built-in slug appears in the saved list (the annotation store)."""
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
    Without the folder: the portal annotation, else DEFAULT_LOGBOOK_DEFS.
    """
    from senaite.pfas.browser.prep_logbooks import _get_active_families
    families = _get_active_families(portal)
    if families:
        return [_prep_def_to_logbook_def(d) for d in families]

    # the portal annotation
    try:
        ann = IAnnotations(portal)
        raw = ann.get(LOGBOOK_DEFS_KEY)
        if raw:
            return _merge_defaults(json.loads(raw))
    except (ValueError, TypeError) as exc:
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


def print_control(portal, slug, entry=None, method=None):
    """What a logbook prints as, for the control block: the form number the
    lab gave it, the revision of its template and the day that revision was
    last changed, the entry (the worksheet or batch it was filled for) and the
    method. One answer for the browser print and the PDFs."""
    out = {"doc_id": form_code(portal, slug), "title": u"", "revision": u"",
           "date": u"", "date_label": u"Template dated"}
    obj = _find_prep_def_by_slug(portal, slug)
    if obj is not None:
        out["revision"] = u"%s" % (getattr(obj, "revision", None) or 1)
        out["title"] = obj.title or u""
        from senaite.pfas import print_doc
        out["date"] = print_doc.lab_or(obj.modified(), u"%s" % obj.modified().strftime("%Y-%m-%d"), u"%Y-%m-%d")
    cells = []
    if entry:
        cells.append((u"Entry", u"%s" % entry))
    if method:
        cells.append((u"Method", u"%s" % method))
    out["cells"] = cells
    return out


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
    # change history: track() itself decides whether a failure blocks the save
    from senaite.pfas import config_history
    config_history.track(portal, 'logbook_defs', "all", lambda: get_logbook_defs(portal), label=u"Logbook definitions")
    folder = portal.get("pfas_prep_logbooks")
    if folder is None:
        # no folder: the annotation store
        ann = IAnnotations(portal)
        ann[LOGBOOK_DEFS_KEY] = json.dumps(defs)
        return

    saved_slugs = set()
    for i, d in enumerate(defs):
        slug = d.get("slug")
        if not slug:
            continue
        saved_slugs.add(slug)

        obj = _find_prep_def_by_slug(portal, slug)

        if obj is None:
            # a custom logbook
            new_id = "lbdef-" + uuid.uuid4().hex[:8]
            title = d.get("title") or slug
            folder.invokeFactory("PrepLogbookDef", id=new_id, title=title)
            obj = folder[new_id]
            obj.logbook_slug = slug
            obj.revision = 1
            obj.status = u"active"
            obj.builtin = False
            # a new logbook's fields (its table columns among them)
            obj.field_schema_json = d.get("field_schema_json") or u"[]"

        obj.title = d.get("title") or obj.title or slug
        obj.logbook_code = d.get("form_num") or u""
        obj.sort_order = i
        raw_active = d.get("active", True)
        obj.active = bool(raw_active)

        obj.reindexObject()

    # Delete custom (non-builtin) PrepLogbookDefs not in the saved list
    for obj in list(folder.objectValues()):
        if obj.portal_type != "PrepLogbookDef":
            continue
        slug = getattr(obj, "logbook_slug", "") or ""
        if slug and slug not in saved_slugs and not bool(getattr(obj, "builtin", False)):
            folder._delObject(obj.getId())
            logger.info("save_logbook_defs: deleted custom def slug=%s", slug)


def seed_defaults(portal):
    """Idempotently seed the default logbook definitions.

    Delegates to seed_builtin_logbook_defs(), which writes PrepLogbookDef
    objects; the annotation store when the Dexterity folder is absent.
    """
    folder = portal.get("pfas_prep_logbooks")
    if folder is not None:
        from senaite.pfas.browser.prep_logbooks import seed_builtin_logbook_defs
        try:
            seed_builtin_logbook_defs(portal)
        except Exception as exc:
            logger.warning("seed_defaults: seed_builtin_logbook_defs failed: %s", exc)
        return

    # no folder: the annotation store
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
    seeded slug ("fda-32-pfas") and a method ID ("FDA_32PFAS") compare equal."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())
