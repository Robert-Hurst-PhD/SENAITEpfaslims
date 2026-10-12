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
     "caps": ["required", "width", "correctable", "pattern", "message"]},
    {"type": "date",        "label": "Date",
     "caps": ["required", "width", "correctable"]},
    {"type": "time",        "label": "Time",
     "caps": ["required", "width", "correctable"]},
    {"type": "datetime",    "label": "Date and time",
     "caps": ["required", "width", "correctable"]},
    {"type": "number",      "label": "Number",
     "caps": ["required", "width", "correctable", "min", "max", "message"]},
    {"type": "textarea",    "label": "Long text",
     "caps": ["correctable"]},
    {"type": "checkbox",    "label": "Checkbox",
     "caps": []},
    # one answer from a list (radio buttons or a dropdown), or several
    # (checkboxes); options are [{value, label}]
    {"type": "choice",      "label": "Choice",
     "caps": ["required", "options", "display"]},
    # a heading with a line of text between groups of fields; holds no value
    {"type": "section",     "label": "Section",
     "caps": ["description"]},
    {"type": "lot_ref",     "label": "Prepared-standard lot",
     "caps": ["correctable", "lot_type"]},
    {"type": "reagent_ref", "label": "Reagent lot",
     "caps": ["correctable"]},
    {"type": "table",       "label": "Table",
     "caps": ["columns", "default_rows"]},
    # : the instrument a temperature was taken with; on save the
    # correction factor in force is frozen beside it and applied to the
    # number columns that name it (column key `corrected_by`).
    {"type": "thermometer", "label": "Thermometer used",
     "caps": ["required"]},
]

TYPE_NAMES = tuple(t["type"] for t in FIELD_TYPES)
CAPS_BY_TYPE = dict((t["type"], set(t["caps"])) for t in FIELD_TYPES)

# Every type that holds a value takes a help line and a show-if condition.
VALUELESS = ("section",)
for _t in TYPE_NAMES:
    CAPS_BY_TYPE[_t].add("help")
    if _t not in VALUELESS:
        CAPS_BY_TYPE[_t].add("show_if")

# How a choice is drawn; "checkboxes" takes several answers (a list).
DISPLAYS = ("radio", "dropdown", "checkboxes")
# show_if: {"field": an EARLIER field's name, "op": one of OPS, "value": ...}
#   eq / ne   the answer is / is not `value` (for checkboxes: includes)
#   in        the answer is one of `value` (a list)
#   filled    the field has any answer
OPS = ("eq", "ne", "in", "filled")
# A multiple-answer choice posts one input per option under this prefix
# (a leading underscore is reserved for the form's own parameters).
OPTION_PARAM = "_opt_%s_%d"

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
    each re-deciding what a struck row means.
    """
    return [r for r in (rows or [])
            if isinstance(r, dict) and not r.get(NA_KEY)]


def _num(v):
    """A number from a schema or form value, else None."""
    if isinstance(v, bool):
        return None
    try:
        return float(u"%s" % v) if (u"%s" % v).strip() not in (u"", u"None") else None
    except (TypeError, ValueError):
        return None


def _empty(value):
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return not [v for v in value if (u"%s" % v).strip()]
    return (u"%s" % value).strip() == u""


def condition_met(cond, answer):
    """Whether a show_if condition holds for the controlling field's answer."""
    op = (cond or {}).get("op") or "eq"
    want = (cond or {}).get("value")
    if op == "filled":
        return not _empty(answer)
    answers = [u"%s" % a for a in answer] if isinstance(answer, (list, tuple)) else \
        ([] if _empty(answer) else [u"%s" % answer])
    if op == "in":
        wanted = [u"%s" % w for w in (want if isinstance(want, (list, tuple)) else [want])]
        return bool(set(answers) & set(wanted))
    hit = (u"%s" % want) in answers
    return hit if op == "eq" else not hit


def visible_names(fields, data):
    """The names of the fields shown for these answers: a field with a
    show_if is shown when its controlling field is shown and the condition
    holds (so hiding a field hides what depends on it)."""
    shown = set()
    for f in fields or []:
        if not isinstance(f, dict) or not f.get("name"):
            continue
        cond = f.get("show_if")
        if isinstance(cond, dict) and cond.get("field"):
            ctl = cond["field"]
            if ctl not in shown or not condition_met(cond, (data or {}).get(ctl)):
                continue
        shown.add(f["name"])
    return shown


def hidden_names(fields, data):
    """Value fields NOT shown for these answers: neither required nor kept."""
    shown = visible_names(fields, data)
    return [f["name"] for f in fields or [] if isinstance(f, dict) and f.get("name")
            and f["name"] not in shown and (f.get("type") or "text") not in VALUELESS]


def missing_required(fields, data, only=None):
    """Labels of the required fields with no value in `data`: the server's
    copy of the browser's `required`, so a post that skips the form cannot
    save an entry without them. `only`: the field names this post covers
    (guided mode saves one step at a time); None = every field. A field
    whose type does not honour "required", or that its show-if hides, is
    never asked for."""
    shown = visible_names(fields, data)
    out = []
    for f in fields or []:
        if not isinstance(f, dict) or not f.get("required"):
            continue
        name = f.get("name")
        if not name or (only is not None and name not in only) or name not in shown:
            continue
        if "required" not in CAPS_BY_TYPE.get(f.get("type", "text"), ()):
            continue
        if _empty((data or {}).get(name)):
            out.append(f.get("label") or name)
    return out


def value_errors(fields, data, only=None):
    """Sentences for answers outside a field's rule: a number below its
    minimum or above its maximum, text not matching its pattern, a choice
    that is not one of its options. Only shown fields with an answer."""
    shown = visible_names(fields, data)
    out = []
    for f in fields or []:
        if not isinstance(f, dict):
            continue
        name = f.get("name")
        if not name or name not in shown or (only is not None and name not in only):
            continue
        value = (data or {}).get(name)
        if _empty(value):
            continue
        label = f.get("label") or name
        ftype = f.get("type") or "text"
        msg = (f.get("message") or u"").strip()
        if ftype == "number":
            x, lo, hi = _num(value), _num(f.get("min")), _num(f.get("max"))
            if x is None:
                out.append(u"%s: not a number." % label)
            elif (lo is not None and x < lo) or (hi is not None and x > hi):
                rng = u"%s to %s" % (u"%g" % lo if lo is not None else u"any",
                                     u"%g" % hi if hi is not None else u"any")
                out.append(u"%s: %s" % (label, msg or u"outside %s." % rng))
        elif ftype == "text" and (f.get("pattern") or u"").strip():
            if not re.match(u"(?:%s)\\Z" % f["pattern"], u"%s" % value):
                out.append(u"%s: %s" % (label, msg or u"not in the expected form."))
        elif ftype == "choice":
            allowed = set(u"%s" % o.get("value") for o in f.get("options") or [] if isinstance(o, dict))
            given = value if isinstance(value, (list, tuple)) else [value]
            if [g for g in given if u"%s" % g not in allowed]:
                out.append(u"%s: not one of its options." % label)
    return out


def column_name(label, taken=()):
    """A field / column name (NAME_RE) from a label, unique against `taken`."""
    base = re.sub(r"[^a-z0-9]+", u"_", (label or u"").lower()).strip(u"_") or u"col"
    if not base[0].isalpha():
        base = u"c_" + base
    base = base[:56]
    for suffix in RESERVED_SUFFIXES:
        if base.endswith(suffix):
            base = base[:-len(suffix)] + u"_col"
    name, n = base, 2
    while name in taken:
        name, n = u"%s_%d" % (base, n), n + 1
    return name


def columns_schema(labels):
    """The field schema of a simple logbook made from a list of column
    labels (Logbooks > Templates, "Table columns"): who and when, the table,
    notes, review -- the shape the old custom logbook page drew."""
    taken, cols = set(), []
    for label in labels or []:
        label = (label or u"").strip()
        if not label:
            continue
        name = column_name(label, taken)
        taken.add(name)
        cols.append({"name": name, "label": label, "type": "text"})
    fields = [{"name": "analyst", "label": "Analyst", "type": "text"},
              {"name": "log_date", "label": "Date", "type": "date"}]
    if cols:
        fields.append({"name": "rows", "label": "Entries", "type": "table", "columns": cols})
    fields += [{"name": "notes", "label": "Notes", "type": "textarea"},
               {"name": "reviewed_by", "label": "Reviewed By", "type": "text"},
               {"name": "reviewed_date", "label": "Reviewed Date", "type": "date"}]
    return fields


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

        if ftype == "choice":
            opts = f.get("options")
            if not isinstance(opts, list) or not opts:
                errors.append("{0} ('{1}'): a choice needs at least one option.".format(where, name))
            else:
                vals = [(o.get("value") if isinstance(o, dict) else None) for o in opts]
                if any(not (u"%s" % (v or u"")).strip() for v in vals):
                    errors.append("{0} ('{1}'): every option needs a value.".format(where, name))
                elif len(set(vals)) != len(vals):
                    errors.append("{0} ('{1}'): two options share a value.".format(where, name))
            disp = f.get("display") or "radio"
            if disp not in DISPLAYS:
                errors.append("{0} ('{1}'): display must be one of {2}.".format(
                    where, name, ", ".join(DISPLAYS)))

        lo, hi = _num(f.get("min")), _num(f.get("max"))
        if f.get("min") not in (None, u"", "") and lo is None:
            errors.append("{0} ('{1}'): minimum is not a number.".format(where, name))
        if f.get("max") not in (None, u"", "") and hi is None:
            errors.append("{0} ('{1}'): maximum is not a number.".format(where, name))
        if lo is not None and hi is not None and lo > hi:
            errors.append("{0} ('{1}'): minimum is above maximum.".format(where, name))
        if (f.get("pattern") or u"").strip():
            try:
                re.compile(f.get("pattern"))
            except re.error:
                errors.append("{0} ('{1}'): the pattern is not valid.".format(where, name))

        cond = f.get("show_if")
        if cond:
            earlier = [(g.get("name") or "").strip() for g in fields[:idx] if isinstance(g, dict)]
            if not isinstance(cond, dict) or (cond.get("field") or "") not in earlier:
                errors.append("{0} ('{1}'): show only if must name an earlier field.".format(where, name))
            elif cond.get("op", "eq") not in OPS:
                errors.append("{0} ('{1}'): show only if must use one of {2}.".format(
                    where, name, ", ".join(OPS)))
            elif cond.get("op", "eq") != "filled" and cond.get("value") in (None, u"", [], ""):
                errors.append("{0} ('{1}'): show only if needs the answer to compare.".format(where, name))

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
                    src = (c.get("corrected_by") or "").strip()
                    if src and src not in _thermometer_names(fields):
                        errors.append(
                            "{0} ('{1}'): corrected by '{2}', which is not a "
                            "thermometer field of this logbook.".format(cw, cname, src))
                    elif src and ctype != "number":
                        errors.append(
                            "{0} ('{1}'): only a number column can be corrected.".format(
                                cw, cname))
    return errors


def _thermometer_names(fields):
    return set((f.get("name") or "").strip() for f in fields or []
               if isinstance(f, dict) and (f.get("type") or "").strip() == "thermometer")


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
        if "help" in caps and (f.get("help") or "").strip():
            clean["help"] = f.get("help").strip()
        if "description" in caps and (f.get("description") or "").strip():
            clean["description"] = f.get("description").strip()
        if "options" in caps:
            clean["options"] = [{"value": (u"%s" % o.get("value")).strip(),
                                 "label": (u"%s" % (o.get("label") or o.get("value"))).strip()}
                                for o in f.get("options") or [] if isinstance(o, dict)
                                and (u"%s" % (o.get("value") or u"")).strip()]
        if "display" in caps:
            clean["display"] = f.get("display") if f.get("display") in DISPLAYS else "radio"
        for k in ("min", "max"):
            if k in caps and _num(f.get(k)) is not None:
                clean[k] = _num(f.get(k))
        if "pattern" in caps and (f.get("pattern") or "").strip():
            clean["pattern"] = f.get("pattern").strip()
        if "message" in caps and (f.get("message") or "").strip():
            clean["message"] = f.get("message").strip()
        cond = f.get("show_if")
        if "show_if" in caps and isinstance(cond, dict) and (cond.get("field") or "").strip():
            op = cond.get("op") if cond.get("op") in OPS else "eq"
            clean["show_if"] = {"field": cond["field"].strip(), "op": op}
            if op != "filled":
                clean["show_if"]["value"] = cond.get("value")
        if "columns" in caps:
            cols = []
            for c in (f.get("columns") or []):
                if not isinstance(c, dict):
                    continue
                ctype = (c.get("type") or "text").strip()
                col = {
                    "name": (c.get("name") or "").strip(),
                    "label": (c.get("label") or "").strip()
                             or (c.get("name") or "").strip(),
                    "type": ctype if ctype in COLUMN_TYPES else "text",
                }
                src = (c.get("corrected_by") or "").strip()
                if src and src in _thermometer_names(fields) and col["type"] == "number":
                    col["corrected_by"] = src
                cols.append(col)
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
