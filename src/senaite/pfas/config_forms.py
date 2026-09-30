# -*- coding: utf-8 -*-
"""Declarative configuration sections (docs/CONFIG_ARCHITECTURE_REVIEW.md, R2).

A section of a settings page is DECLARED once -- its fields, their kinds,
units, limits, whether they are required, and where they live in the stored
value -- and this module does the rest the same way for every page:

  render   the stored value as the field's value; a default is only a
           placeholder, never a value (a value is saved as a choice);
           a choice field always offers the stored value, even when it is
           not among the usual options (a missing option silently saved the
           first one instead);
  parse    only the section that was submitted (a field of another section
           is never touched); a blank number is UNSET (None), never 0, and
           blank text is empty;
           a required field left blank, a non-number, or a value outside its
           limits is REFUSED with the field named -- nothing is coerced;
  stamp    a version stamp of this section's own values, so a save made from
           a page opened before someone else changed THIS section is refused,
           while edits to other sections do not collide;
  save     through the store's own save function, so the change history
           (config_history) and every side effect of a normal save apply.

Every save defect found on 2026-09-30 (GAPS §51) was one of those rules broken
by a hand-written page. Here they are written once. Pure; no Zope imports.
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function

import copy

try:
    _STR = basestring              # noqa: F821  (Py2.7)
except NameError:                  # pragma: no cover  (Py3 tests)
    _STR = str

try:                       # Plone
    from senaite.pfas import config_history as _history
except Exception:          # tests: loaded without the package
    import config_history as _history   # noqa: F401

REMOVE = object()          # a parsed value meaning "delete this key"

NUMBER, INT, BOOL, TEXT, TEXTAREA, CHOICE = (
    "number", "int", "bool", "text", "textarea", "choice")


class Field(object):

    def __init__(self, path, label, kind=NUMBER, unit=u"", help=u"",
                 placeholder=u"", required=False, minimum=None, maximum=None,
                 choices=None, blank=u"unset", greater_than=None):
        self.path = tuple(path.split(".")) if isinstance(path, _STR) else tuple(path)
        self.name = u"f__" + u"__".join(self.path)
        self.label = label
        self.kind = kind
        self.unit = unit
        self.help = help
        self.placeholder = placeholder
        self.required = required
        self.minimum = minimum
        self.maximum = maximum
        # a list of (value, label), or callable(stored) -> that list when the
        # options depend on the stored value (e.g. every unit already in use)
        self.choices = choices if callable(choices) else list(choices or [])
        self.greater_than = greater_than  # a strict lower bound (0 < days)
        self.blank = blank          # "unset" -> None, "remove" -> key deleted


class Section(object):

    def __init__(self, id, title, base, groups, intro=u""):
        self.id = id
        self.title = title
        self.base = tuple(base)     # path of the section inside the stored value
        self.groups = groups        # [(group title, [Field, ...]), ...]
        self.intro = intro

    def fields(self):
        return [f for _title, fields in self.groups for f in fields]


# ── reading the stored value ─────────────────────────────────────────────────

def _get(value, path):
    for p in path:
        if not isinstance(value, dict) or p not in value:
            return None
        value = value[p]
    return value


def current(section, stored):
    """{field.name: stored value (or None)} for the section's fields."""
    base = _get(stored or {}, section.base) or {}
    return dict((f.name, _get(base, f.path)) for f in section.fields())


def stamp(section, stored):
    """Version stamp of THIS section's values only."""
    if isinstance(section, Table):
        return stamp_table(section, stored)
    if isinstance(section, Collection):
        return _history.fingerprint(section.read(stored or {}))
    vals = current(section, stored)
    return _history.fingerprint(dict((k, v) for k, v in vals.items() if v not in (None, u"", "")))


def render(section, stored):
    """What the template draws: one dict per field, grouped."""
    if isinstance(section, Table):
        return render_table(section, stored)
    if isinstance(section, Collection):
        return render_collection(section, stored)
    vals = current(section, stored)
    groups = []
    for title, fields in section.groups:
        rows = []
        for f in fields:
            v = vals[f.name]
            choices = _choices(f, stored)
            if f.kind == CHOICE and v not in (None, u"", "") and v not in [c[0] for c in choices]:
                choices.append((v, u"%s (stored value)" % v))
            rows.append({
                "name": f.name, "label": f.label, "kind": f.kind, "unit": f.unit,
                "help": f.help, "placeholder": f.placeholder, "required": f.required,
                "min": f.minimum, "max": f.maximum, "choices": choices,
                "value": (u"" if v is None else (v if f.kind in (BOOL,) else u"%s" % v)),
                "checked": bool(v) if f.kind == BOOL else False,
            })
        groups.append({"title": title, "fields": rows})
    return groups


# ── parsing a submitted section ──────────────────────────────────────────────

def _text(raw):
    """A submitted value as stripped unicode (Zope hands over UTF-8 bytes)."""
    if raw is None:
        return u""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return (u"%s" % raw).strip()


_SKIP = object()           # a field whose submitted value was refused


def _choices(f, stored):
    return list(f.choices(stored or {})) if callable(f.choices) else list(f.choices)


def _value(f, raw, saved, label=None, choices=None):
    """(value | REMOVE | _SKIP, error or None) for one submitted field.

    `saved` is the value stored on the server (a choice accepts it even when
    it is not a listed option). `label` names the field in an error; a table
    cell passes "<row> <column>"."""
    label = label or f.label
    if f.kind == BOOL:
        return raw is True or _text(raw).lower() in (u"1", u"on", u"true", u"yes"), None
    text = _text(raw)
    if text == u"":
        if f.required:
            return _SKIP, u"%s is required." % label
        if f.blank == u"remove":
            return REMOVE, None
        return (u"" if f.kind in (TEXT, TEXTAREA) else None), None
    if f.kind in (NUMBER, INT):
        try:
            num = float(text)
            if f.kind == INT:
                if num != int(num):
                    raise ValueError
                num = int(num)
        except ValueError:
            return _SKIP, u"%s must be %s, not %r." % (
                label, u"a whole number" if f.kind == INT else u"a number", text)
        if f.minimum is not None and num < f.minimum:
            return _SKIP, u"%s must be at least %s." % (label, f.minimum)
        if f.maximum is not None and num > f.maximum:
            return _SKIP, u"%s must be at most %s." % (label, f.maximum)
        if f.greater_than is not None and num <= f.greater_than:
            return _SKIP, u"%s must be more than %s." % (label, f.greater_than)
        return num, None
    if f.kind == CHOICE:
        allowed = [c[0] for c in (f.choices if choices is None else choices)]
        if allowed and text not in allowed and text != _text(saved):
            return _SKIP, u"%s: %r is not one of the options." % (label, text)
    return text, None


def parse(section, form, stored):
    """(updates {path: value|REMOVE}, errors [text]) for the submitted section.

    `stored` is the value as saved on the server: a choice field accepts its
    stored value even when it is not a listed option (it was offered on the
    page for that reason), and nothing sent by the browser can widen that.

    Call only when the form says it is this section (form["_section"]). A
    checkbox that is not submitted is False: the section's own form always
    carries all of its fields, so absence can only mean unchecked.
    """
    if isinstance(section, Table):
        return parse_table(section, form, stored)
    if isinstance(section, Collection):
        return parse_collection(section, form, stored)
    updates, errors = {}, []
    saved = current(section, stored)
    for f in section.fields():
        value, error = _value(f, form.get(f.name), saved[f.name],
                              choices=_choices(f, stored))
        if error:
            errors.append(error)
        elif value is not _SKIP:
            updates[f.path] = value
    return updates, errors


def apply(section, stored, updates):
    """A copy of `stored` with the section's updates written in."""
    if isinstance(section, Table):
        return apply_table(section, stored, updates)
    if isinstance(section, Collection):
        return section.write(copy.deepcopy(stored or {}), updates)
    value = copy.deepcopy(stored or {})
    base = value
    for p in section.base:
        base = base.setdefault(p, {})
    for path, new in updates.items():
        node = base
        for p in path[:-1]:
            node = node.setdefault(p, {})
        if new is REMOVE:
            node.pop(path[-1], None)
        else:
            node[path[-1]] = new
    return value


# ── tables: the same rules, one row per key ──────────────────────────────────
#
# A Table is a grid of the same fields (columns) repeated for a set of rows
# that the stored value itself decides -- e.g. one row per analyte the matrix
# reports, grouped by matrix. Declared with a `rows(stored)` function that
# returns (groups, rows):
#
#     groups  [{"key", "label", "unit"}]         -- e.g. one per matrix
#     rows    [{"key": (k1, k2, ...), "group", "label", "sublabel"}]
#
# Values live at stored[base][k1][k2]...[column path]. Only the rows listed
# are parsed or written: a row not on the page (an analyte excluded from a
# matrix) keeps its stored value, where the hand-written reporting-limits save
# replaced the whole matrix and dropped it. A row whose columns are all unset
# is removed, and an emptied parent with it, so an untouched page stores
# nothing. Row keys travel ENCODED in field names: Zope reads ":<letter>" in a
# name as a type converter, and analyte keywords carry colons.


class Table(object):

    def __init__(self, id, title, base, columns, rows, check=None, intro=u""):
        self.id = id
        self.title = title
        self.base = tuple(base)
        self.columns = columns      # [Field] with paths relative to the row
        self.rows = rows            # callable(stored) -> (groups, rows)
        self.check = check          # callable(row, {column name: value}) -> error | None
        self.intro = intro

    def fields(self):
        return list(self.columns)


def _enc(key):
    """A form-name-safe token: letters and digits kept, anything else _hh
    (so "__", the separator, never occurs inside a token)."""
    if isinstance(key, bytes):
        key = key.decode("utf-8")
    out = []
    for ch in u"%s" % key:
        if (u"a" <= ch <= u"z") or (u"A" <= ch <= u"Z") or (u"0" <= ch <= u"9"):
            out.append(ch)
        else:
            out.extend(u"_%02x" % b for b in bytearray(ch.encode("utf-8")))
    return u"".join(out)


def cell_name(table, row_key, column):
    return u"__".join([u"t", _enc(table.id)] + [_enc(k) for k in row_key] +
                      [_enc(p) for p in column.path])


def _row_node(table, stored, row_key):
    return _get(stored or {}, table.base + tuple(row_key)) or {}


def _cells(table, stored, row_key):
    node = _row_node(table, stored, row_key)
    return dict((c.name, _get(node, c.path)) for c in table.columns)


def stamp_table(table, stored):
    """The listed rows' keys AND values: a change to which rows the page shows
    (e.g. the inclusion grid) also makes an open page stale, so no field can
    be read against a row set it was not drawn for."""
    _groups, rows = table.rows(stored or {})
    blob = []
    for r in rows:
        vals = dict((k, v) for k, v in _cells(table, stored, r["key"]).items()
                    if v not in (None, u"", ""))
        blob.append([list(r["key"]), vals])
    return _history.fingerprint(blob)


def render_table(table, stored):
    groups, rows = table.rows(stored or {})
    by_group = dict((g["key"], dict(g, rows=[], set=0)) for g in groups)
    order = [g["key"] for g in groups]
    for r in rows:
        vals = _cells(table, stored, r["key"])
        cells = []
        for c in table.columns:
            v = vals[c.name]
            cells.append({"name": cell_name(table, r["key"], c), "kind": c.kind,
                          "label": c.label, "min": c.minimum, "max": c.maximum,
                          "placeholder": c.placeholder,
                          "value": u"" if v is None else u"%s" % v,
                          "checked": bool(v) if c.kind == BOOL else False})
        g = by_group.get(r.get("group"))
        if g is None:
            continue
        g["rows"].append({"label": r.get("label"), "sublabel": r.get("sublabel"),
                          "cells": cells})
        if any(vals[c.name] not in (None, u"", "") for c in table.columns):
            g["set"] += 1
    out = []
    for i, key in enumerate(order):
        g = by_group[key]
        g["index"] = i
        g["total"] = len(g["rows"])
        g["columns"] = [{"label": c.label, "unit": g.get("unit") or c.unit}
                        for c in table.columns]
        out.append(g)
    return out


def parse_table(table, form, stored):
    """(updates {row key: {column path: value}}, errors) for the listed rows."""
    _groups, rows = table.rows(stored or {})
    updates, errors = {}, []
    for r in rows:
        saved = _cells(table, stored, r["key"])
        vals, ok = {}, True
        for c in table.columns:
            value, error = _value(c, form.get(cell_name(table, r["key"], c)),
                                  saved[c.name], u"%s %s" % (r.get("label"), c.label))
            if error:
                errors.append(error)
                ok = False
            elif value is not _SKIP:
                vals[c.path] = value
        if ok and table.check is not None:
            error = table.check(r, dict((c.name, vals.get(c.path)) for c in table.columns))
            if error:
                errors.append(error)
        updates[tuple(r["key"])] = vals
    return updates, errors


def apply_table(table, stored, updates):
    value = copy.deepcopy(stored or {})
    existed = _get(value, table.base) is not None
    for row_key, vals in updates.items():
        path = table.base + tuple(row_key)
        parent = value
        for p in path[:-1]:
            parent = parent.setdefault(p, {})
        node = dict(parent.get(path[-1]) or {})
        for cpath, new in vals.items():
            leaf = node
            for p in cpath[:-1]:
                leaf = leaf.setdefault(p, {})
            if new is REMOVE:
                leaf.pop(cpath[-1], None)
            else:
                leaf[cpath[-1]] = new
        if all(_get(node, c.path) in (None, u"") for c in table.columns):
            for c in table.columns:            # nothing set: no row at all
                node.pop(c.path[0], None)
        if node:
            parent[path[-1]] = node
        else:
            parent.pop(path[-1], None)
    _prune(value, table.base, keep_base=existed)
    return value


def _prune(value, base, keep_base=False):
    """Drop dicts left empty under base (a matrix with no limits), and base
    itself only if this save created it -- an untouched page changes nothing,
    not even an empty map into a missing one."""
    def walk(node):
        if not isinstance(node, dict):
            return
        for k in list(node):
            walk(node[k])
            if isinstance(node[k], dict) and not node[k]:
                node.pop(k)
    top = _get(value, base[:-1]) if len(base) > 1 else value
    if isinstance(top, dict) and base[-1] in top:
        walk(top[base[-1]])
        if isinstance(top[base[-1]], dict) and not top[base[-1]] and not keep_base:
            top.pop(base[-1])


# ── collections: rows the user adds, renames and removes ─────────────────────
#
# A Collection is a list of items edited as rows -- e.g. a method's matrices,
# where one row's settings live under several stored keys. It is declared
# with columns (Fields, one-segment paths; the first is the row's NAME) and
# two functions that map rows onto the stored value and back:
#
#     read(stored)        -> [{column name: value}]   in display order
#     write(stored, rows) -> stored                   (given a deep copy)
#     check(stored, rows) -> [error]                  optional: e.g. what a
#                                                     removal or rename orphans
#
# The page draws every existing row plus `new_rows` blank ones. Clearing a
# row's name removes it; a blank row with a name adds one. Rows are addressed
# by POSITION, which is safe because the stamp is the whole read() list: if
# anyone changed the collection after the page was drawn, the save is stale.


class Collection(object):

    def __init__(self, id, title, columns, read, write, check=None, new_rows=3,
                 noun=u"row", intro=u""):
        self.id = id
        self.title = title
        self.columns = columns
        self.read = read
        self.write = write
        self.check = check
        self.new_rows = new_rows
        self.noun = noun
        self.intro = intro

    def fields(self):
        return list(self.columns)

    @property
    def key(self):
        return self.columns[0]


def collection_name(coll, index, column):
    return u"__".join([u"c", _enc(coll.id), u"%d" % index] + [_enc(p) for p in column.path])


def render_collection(coll, stored):
    rows = coll.read(stored or {})
    out = []
    for i in range(len(rows) + coll.new_rows):
        vals = rows[i] if i < len(rows) else {}
        cells = []
        for c in coll.columns:
            v = vals.get(c.path[0])
            choices = _choices(c, stored)
            if c.kind == CHOICE and v not in (None, u"", "") and v not in [x[0] for x in choices]:
                choices.append((v, u"%s (stored value)" % v))
            cells.append({"name": collection_name(coll, i, c), "kind": c.kind,
                          "label": c.label, "min": c.minimum, "max": c.maximum,
                          "placeholder": c.placeholder if i < len(rows) or c is coll.key
                                         else u"",
                          "choices": choices,
                          "value": u"" if v is None else u"%s" % v,
                          "checked": bool(v) if c.kind == BOOL else False})
        out.append({"index": i, "new": i >= len(rows), "cells": cells})
    return out


def parse_collection(coll, form, stored):
    """(rows [{column: value}], errors) -- the collection as submitted."""
    before = coll.read(stored or {})
    rows, errors, seen = [], [], set()
    for i in range(len(before) + coll.new_rows):
        old = before[i] if i < len(before) else {}
        name, error = _value(coll.key, form.get(collection_name(coll, i, coll.key)),
                             old.get(coll.key.path[0]))
        if name in (None, u"", REMOVE, _SKIP):
            if error:
                errors.append(error)
            elif i >= len(before):
                filled = [c.label for c in coll.columns[1:] if c.kind != BOOL and
                          _text(form.get(collection_name(coll, i, c)))]
                if filled:
                    errors.append(u"New %s %d: give it a name, or clear %s." % (
                        coll.noun, i - len(before) + 1, u", ".join(filled)))
            continue                    # cleared name: removed (or an unused blank row)
        label = name
        if name.lower() in seen:
            errors.append(u"%s is listed twice." % name)
            continue
        seen.add(name.lower())
        row = {coll.key.path[0]: name}
        for c in coll.columns[1:]:
            value, error = _value(c, form.get(collection_name(coll, i, c)),
                                  old.get(c.path[0]), u"%s: %s" % (label, c.label),
                                  choices=_choices(c, stored))
            if error:
                errors.append(error)
            elif value is not _SKIP:
                row[c.path[0]] = None if value is REMOVE else value
        rows.append(row)
    if not errors and not rows:
        errors.append(u"At least one %s is needed; nothing was removed." % coll.noun)
    if not errors and coll.check is not None:
        errors.extend(coll.check(stored or {}, rows) or [])
    return rows, errors
