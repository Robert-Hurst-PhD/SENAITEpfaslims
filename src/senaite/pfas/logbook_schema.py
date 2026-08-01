# -*- coding: utf-8 -*-
"""
Canonical vocabulary + validation for logbook field schemas and guided steps.

Until now the set of legal field types existed ONLY as `tal:condition` guards
inside logbook_dynamic.pt and a 10px hint string in prep_logbooks.pt — an
unknown type silently rendered nothing, and malformed JSON was persisted
verbatim then degraded to an empty form. This module is the single source of
truth for:

  * which field types exist and which keys each one actually honours (`caps`),
  * what a valid field name / step looks like,
  * how fields are grouped into guided steps at render time.

`caps` mirrors the AUDITED behaviour of the renderer, not an aspiration:
  - "required" / "width" are honoured only for text/date/number
  - "correctable" is ignored for table and checkbox
  - table columns are coerced to text/date/number
Keeping it here means the builder UI, the server-side validator and the help
text all derive from one list.

Deliberately free of Zope/Plone imports so it can be exercised from a plain
`bin/instance run` script (and reasoned about) without a site.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import re

# ── Field type vocabulary ────────────────────────────────────────────────────
# caps: which optional keys this type actually honours in the renderer.
FIELD_TYPES = [
    {"type": "text",        "label": "Text",
     "caps": ["required", "width", "correctable"]},
    {"type": "date",        "label": "Date",
     "caps": ["required", "width", "correctable"]},
    {"type": "number",      "label": "Number",
     "caps": ["required", "width", "correctable"]},
    {"type": "textarea",    "label": "Long text",
     "caps": ["correctable"]},
    {"type": "checkbox",    "label": "Checkbox",
     "caps": []},
    {"type": "lot_ref",     "label": "Prepared-standard lot",
     "caps": ["correctable", "lot_type"]},
    {"type": "reagent_ref", "label": "Reagent lot",
     "caps": ["correctable"]},
    {"type": "table",       "label": "Table",
     "caps": ["columns", "default_rows"]},
]

TYPE_NAMES = tuple(t["type"] for t in FIELD_TYPES)
CAPS_BY_TYPE = dict((t["type"], set(t["caps"])) for t in FIELD_TYPES)

# Table columns are coerced to these three by the renderer.
COLUMN_TYPES = ("text", "date", "number")
WIDTHS = ("sm", "md", "lg")

# Field names become POST parameter names and dict keys.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# A leading underscore is reserved for bookkeeping keys (_corrections,
# _steps_done) and for the correction POST params (_newval_*, _corr_by_*).
# A _json suffix would collide with a table's hidden input (<name>_json).
# Banning both kills the entire collision class in two rules.
RESERVED_SUFFIXES = ("_json",)

STEP_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
UNASSIGNED_STEP_ID = "_unassigned"

# Reserved keys stored INSIDE a table row to mark it struck as not-applicable
# ("we did not prepare this one today"). Safe from collision because NAME_RE
# forces a column name to start with a lowercase LETTER, so no user-authored
# column can ever begin with an underscore.
NA_KEY = "_na"
NA_BY_KEY = "_na_by"
NA_AT_KEY = "_na_at"
ROW_RESERVED_KEYS = (NA_KEY, NA_BY_KEY, NA_AT_KEY)


def is_row_struck(row):
    """True if this table row was struck as not-applicable."""
    return bool(isinstance(row, dict) and row.get(NA_KEY))


def active_rows(rows):
    """The rows that COUNT.

    A struck row is recorded and printed, but it is inert: nothing consumes it,
    nothing is created from it, and it must never be treated as a real entry.
    Defined once here so every consumer inherits the same meaning rather than
    each re-deciding what a struck row means (CLAUDE.md §1.3).
    """
    return [r for r in (rows or [])
            if isinstance(r, dict) and not r.get(NA_KEY)]


def field_type_labels():
    """[(type, label)] for building a <select>."""
    return [(t["type"], t["label"]) for t in FIELD_TYPES]


# ── Validation ───────────────────────────────────────────────────────────────

def validate_schema(fields):
    """Validate a parsed field_schema_json list.

    Returns a list of human-readable error strings; empty means valid.
    """
    errors = []
    if not isinstance(fields, list):
        return ["Field schema must be a list."]

    seen = set()
    for idx, f in enumerate(fields):
        where = "Field {0}".format(idx + 1)
        if not isinstance(f, dict):
            errors.append("{0}: not an object.".format(where))
            continue

        name = (f.get("name") or "").strip()
        if not name:
            errors.append("{0}: name is required.".format(where))
        elif not NAME_RE.match(name):
            errors.append(
                "{0} ('{1}'): name must start with a letter and use only "
                "lowercase letters, digits and underscores.".format(where, name))
        elif name.startswith("_"):
            errors.append(
                "{0} ('{1}'): names may not start with an underscore "
                "(reserved).".format(where, name))
        elif name.endswith(RESERVED_SUFFIXES):
            errors.append(
                "{0} ('{1}'): names may not end with '_json' "
                "(reserved).".format(where, name))
        elif name in seen:
            errors.append("{0}: duplicate name '{1}'.".format(where, name))
        else:
            seen.add(name)

        ftype = (f.get("type") or "text").strip()
        if ftype not in TYPE_NAMES:
            errors.append("{0} ('{1}'): unknown type '{2}'. Valid: {3}.".format(
                where, name or "?", ftype, ", ".join(TYPE_NAMES)))
            continue

        width = f.get("width")
        if width and width not in WIDTHS:
            errors.append("{0} ('{1}'): width must be one of {2}.".format(
                where, name, ", ".join(WIDTHS)))

        if ftype == "table":
            cols = f.get("columns")
            if not isinstance(cols, list) or not cols:
                errors.append(
                    "{0} ('{1}'): a table needs at least one column.".format(
                        where, name))
            else:
                cseen = set()
                for cidx, c in enumerate(cols):
                    cw = "{0} ('{1}') column {2}".format(where, name, cidx + 1)
                    if not isinstance(c, dict):
                        errors.append("{0}: not an object.".format(cw))
                        continue
                    cname = (c.get("name") or "").strip()
                    if not cname:
                        errors.append("{0}: name is required.".format(cw))
                    elif not NAME_RE.match(cname):
                        errors.append("{0} ('{1}'): invalid name.".format(cw, cname))
                    elif cname in cseen:
                        errors.append("{0}: duplicate column name '{1}'.".format(
                            cw, cname))
                    else:
                        cseen.add(cname)
                    ctype = (c.get("type") or "text").strip()
                    if ctype not in COLUMN_TYPES:
                        errors.append(
                            "{0} ('{1}'): column type must be one of {2}.".format(
                                cw, cname, ", ".join(COLUMN_TYPES)))
    return errors


def canonicalize_schema(fields):
    """Strip keys a type does not honour, so stored JSON stays truthful.

    e.g. width/required on a textarea are silently ignored by the renderer;
    keeping them in the stored schema implies behaviour that does not exist.
    """
    out = []
    for f in fields or []:
        if not isinstance(f, dict):
            continue
        ftype = (f.get("type") or "text").strip()
        caps = CAPS_BY_TYPE.get(ftype, set())
        clean = {
            "name": (f.get("name") or "").strip(),
            "label": (f.get("label") or "").strip() or (f.get("name") or "").strip(),
            "type": ftype,
        }
        if "required" in caps and f.get("required"):
            clean["required"] = True
        if "width" in caps and f.get("width") in WIDTHS:
            clean["width"] = f.get("width")
        if "correctable" in caps and f.get("correctable"):
            clean["correctable"] = True
        if "lot_type" in caps and (f.get("lot_type") or "").strip():
            clean["lot_type"] = f.get("lot_type").strip()
        if "columns" in caps:
            cols = []
            for c in (f.get("columns") or []):
                if not isinstance(c, dict):
                    continue
                ctype = (c.get("type") or "text").strip()
                cols.append({
                    "name": (c.get("name") or "").strip(),
                    "label": (c.get("label") or "").strip()
                             or (c.get("name") or "").strip(),
                    "type": ctype if ctype in COLUMN_TYPES else "text",
                })
            clean["columns"] = cols
            rows = f.get("default_rows")
            clean["default_rows"] = rows if isinstance(rows, list) else []
        out.append(clean)
    return out


def validate_steps(steps, fields):
    """Validate parsed steps_json against the field schema."""
    errors = []
    if steps in (None, ""):
        return errors
    if not isinstance(steps, list):
        return ["Steps must be a list."]

    # NB: a step may reference a field name that no longer exists in the
    # schema (the field was deleted). That is deliberately NOT an error —
    # build_steps drops such names silently — so the schema is not consulted
    # for validity here, only for duplicate-claim detection.
    seen_ids = set()
    claimed = {}
    for idx, s in enumerate(steps):
        where = "Step {0}".format(idx + 1)
        if not isinstance(s, dict):
            errors.append("{0}: not an object.".format(where))
            continue
        sid = (s.get("id") or "").strip()
        if not sid:
            errors.append("{0}: id is required.".format(where))
        elif not STEP_ID_RE.match(sid):
            errors.append(
                "{0} ('{1}'): id may use only lowercase letters, digits, "
                "'-' and '_'.".format(where, sid))
        elif sid in seen_ids:
            errors.append("{0}: duplicate id '{1}'.".format(where, sid))
        else:
            seen_ids.add(sid)

        if not (s.get("title") or "").strip():
            errors.append("{0}: title is required.".format(where))

        names = s.get("fields")
        if names is not None and not isinstance(names, list):
            errors.append("{0}: fields must be a list of field names.".format(where))
            continue
        for n in (names or []):
            n = (n or "").strip()
            if not n:
                continue
            # An unknown name is NOT an error — the field may have been
            # deleted since; build_steps drops it silently.
            if n in claimed:
                errors.append(
                    "{0}: field '{1}' is already used by step '{2}'.".format(
                        where, n, claimed[n]))
            else:
                claimed[n] = sid or where
    return errors


def build_steps(fields, steps):
    """Resolve steps against the schema for rendering.

    Returns a list of {id, title, instructions, media, media_alt, fields}
    where `fields` holds the RESOLVED field dicts (in schema order), not names.

    Guarantees:
      * a name that no longer exists in the schema is dropped silently
      * a field claimed by two steps belongs to the first one
      * every field not claimed by any step lands in a trailing synthetic step,
        so no field can ever become unreachable (and therefore un-fillable)
    """
    by_name = {}
    order = []
    for f in (fields or []):
        if not isinstance(f, dict):
            continue
        n = (f.get("name") or "").strip()
        if n:
            by_name[n] = f
            order.append(n)

    out = []
    used = set()
    for s in (steps or []):
        if not isinstance(s, dict):
            continue
        resolved = []
        for n in (s.get("fields") or []):
            n = (n or "").strip()
            if n and n in by_name and n not in used:
                used.add(n)
                resolved.append(by_name[n])
        out.append({
            "id": (s.get("id") or "").strip(),
            "title": (s.get("title") or "").strip(),
            "instructions": s.get("instructions") or "",
            "media": (s.get("media") or "").strip(),
            "media_alt": (s.get("media_alt") or "").strip(),
            "fields": resolved,
        })

    leftover = [by_name[n] for n in order if n not in used]
    if leftover:
        out.append({
            "id": UNASSIGNED_STEP_ID,
            "title": "Additional fields",
            "instructions": "",
            "media": "",
            "media_alt": "",
            "fields": leftover,
        })
    return out


def unassigned_names(fields, steps):
    """Field names not claimed by any step (what build_steps would sweep up)."""
    claimed = set()
    for s in (steps or []):
        if isinstance(s, dict):
            for n in (s.get("fields") or []):
                n = (n or "").strip()
                if n:
                    claimed.add(n)
    out = []
    for f in (fields or []):
        if isinstance(f, dict):
            n = (f.get("name") or "").strip()
            if n and n not in claimed:
                out.append(n)
    return out
