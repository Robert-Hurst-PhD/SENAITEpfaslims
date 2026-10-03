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

NUMBER, INT, BOOL, TEXT, TEXTAREA, CHOICE, MULTI = (
    "number", "int", "bool", "text", "textarea", "choice", "multi")


def option_name(f, value):
    """One checkbox per option (MULTI): a list-valued field would be collapsed
    to its first value by flatten_form."""
    return u"%s__opt__%s" % (f.name, _enc(value))


class Field(object):

    def __init__(self, path, label, kind=NUMBER, unit=u"", help=u"",
                 placeholder=u"", required=False, minimum=None, maximum=None,
                 choices=None, blank=u"unset", greater_than=None):
        self.path = (tuple(int(x) if x.isdigit() else x for x in path.split("."))
                     if isinstance(path, _STR) else tuple(path))
        self.name = u"f__" + u"__".join(u"%s" % p for p in self.path)
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
    """Walk dict keys -- and list positions, for an int segment (e.g. the
    first tier of a QC type: ("tiers", 0, "rpd_max"))."""
    for p in path:
        if isinstance(value, list) and isinstance(p, int):
            if p >= len(value):
                return None
            value = value[p]
        elif isinstance(value, dict) and p in value:
            value = value[p]
        else:
            return None
    return value


def _descend(node, p):
    """The child at `p`, created if missing (a dict, or a list slot)."""
    if isinstance(node, list) and isinstance(p, int):
        while len(node) <= p:
            node.append({})
        if not isinstance(node[p], dict):
            node[p] = {}
        return node[p]
    return node.setdefault(p, {})


def _bound(obj, stored):
    """A table / collection whose columns depend on the stored value (e.g.
    one column per matrix) resolved for this value; others returned as is."""
    if callable(getattr(obj, "columns", None)):
        bound = copy.copy(obj)
        bound.columns = obj.columns(stored or {})
        return bound
    return obj


def current(section, stored):
    """{field.name: stored value (or None)} for the section's fields."""
    base = _get(stored or {}, section.base) or {}
    return dict((f.name, _get(base, f.path)) for f in section.fields())


def stamp(section, stored, env=None):
    """Version stamp of THIS section's values only."""
    if isinstance(section, Table):
        return stamp_table(section, stored, env)
    if isinstance(section, Collection):
        return _history.fingerprint(section.read(stored or {}))
    vals = current(section, stored)
    return _history.fingerprint(dict((k, v) for k, v in vals.items() if v not in (None, u"", "")))


def render(section, stored, env=None):
    """What the template draws: one dict per field, grouped."""
    if isinstance(section, Table):
        return render_table(section, stored, env)
    if isinstance(section, Collection):
        return render_collection(section, stored, env)
    vals = current(section, stored)
    groups = []
    for title, fields in section.groups:
        rows = []
        for f in fields:
            v = vals[f.name]
            choices = _choices(f, stored, env)
            if f.kind == CHOICE and v not in (None, u"", "") and v not in [c[0] for c in choices]:
                choices.append((v, u"%s (stored value)" % v))
            options = []
            if f.kind == MULTI:
                chosen = set(v or [])
                options = [{"value": c[0], "label": c[1], "name": option_name(f, c[0]),
                            "checked": c[0] in chosen} for c in choices]
                options += [{"value": x, "label": u"%s (stored value)" % x, "name": option_name(f, x),
                             "checked": True} for x in (v or []) if x not in [c[0] for c in choices]]
            rows.append({
                "name": f.name, "label": f.label, "kind": f.kind, "unit": f.unit,
                "options": options,
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


def _choices(f, stored, env=None):
    """A field's options; callable choices get the stored value and `env`,
    what the page knows that the store does not (e.g. the inventory's lots)."""
    return list(f.choices(stored or {}, env)) if callable(f.choices) else list(f.choices)


def _value(f, raw, saved, label=None, choices=None):
    """(value | REMOVE | _SKIP, error or None) for one submitted field.

    `saved` is the value stored on the server (a choice accepts it even when
    it is not a listed option). `label` names the field in an error; a table
    cell passes "<row> <column>"."""
    label = label or f.label
    if f.kind == BOOL:
        return raw is True or _text(raw).lower() in (u"1", u"on", u"true", u"yes"), None
    if f.kind == MULTI:
        return raw, None                 # parse() hands over the chosen list
    text = _text(raw)
    if text == u"":
        if f.required:
            return _SKIP, u"%s is required." % label
        if f.blank == u"remove":
            return REMOVE, None
        if saved in (u"", ""):
            return saved, None            # stored empty stays empty: not "" -> None
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


def parse(section, form, stored, env=None):
    """(updates {path: value|REMOVE}, errors [text]) for the submitted section.

    `stored` is the value as saved on the server: a choice field accepts its
    stored value even when it is not a listed option (it was offered on the
    page for that reason), and nothing sent by the browser can widen that.

    Call only when the form says it is this section (form["_section"]). A
    checkbox that is not submitted is False: the section's own form always
    carries all of its fields, so absence can only mean unchecked.
    """
    if isinstance(section, Table):
        return parse_table(section, form, stored, env)
    if isinstance(section, Collection):
        return parse_collection(section, form, stored, env)
    updates, errors = {}, []
    saved = current(section, stored)
    for f in section.fields():
        if f.kind == MULTI:
            offered = [c[0] for c in _choices(f, stored, env)] + list(saved[f.name] or [])
            ticked = set(v for v in offered if _text(form.get(option_name(f, v))).lower()
                         in (u"1", u"on", u"true", u"yes"))
            old = list(saved[f.name] or [])
            # stored order kept; newly ticked ones follow in option order
            updates[f.path] = ([v for v in old if v in ticked] +
                               [v for v in offered if v in ticked and v not in old])
            continue
        value, error = _value(f, form.get(f.name), saved[f.name],
                              choices=_choices(f, stored, env))
        if error:
            errors.append(error)
        elif value is not _SKIP:
            updates[f.path] = value
    return updates, errors


def apply(section, stored, updates, env=None):
    """A copy of `stored` with the section's updates written in."""
    if isinstance(section, Table):
        return apply_table(section, stored, updates, env)
    if isinstance(section, Collection):
        return section.write(copy.deepcopy(stored or {}), updates)
    value = copy.deepcopy(stored or {})
    base = value
    for p in section.base:
        base = _descend(base, p)
    for path, new in updates.items():
        node = base
        if new is None or new is REMOVE:
            # an unset value never CREATES a missing block: an untouched save
            # of a field the profile has no parent for stores nothing
            for p in path[:-1]:
                node = node.get(p) if isinstance(node, dict) else None
                if node is None:
                    break
            if not isinstance(node, dict):
                continue
        else:
            for p in path[:-1]:
                node = node.setdefault(p, {})
        if new is REMOVE:
            node.pop(path[-1], None)
        elif new is None and path[-1] not in node:
            continue                    # an unset value never creates a key either
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
    """`read(stored) -> {row key: {column name: value}}` and
    `write(stored, {row key: {column path: value}}, env) -> stored` replace the
    default nested-dict storage under `base` when the store keeps its rows
    another way -- e.g. a list of {"analyte", "factor"} dicts holding only the
    rows that differ from the default."""

    def __init__(self, id, title, base, columns, rows, check=None, intro=u"",
                 read=None, write=None, rows_take_env=False, row_heading=u"Analyte",
                 info=None):
        self.id = id
        # [(id, heading)]: read-only columns after the inputs, showing what
        # another owner holds (e.g. the regulatory limits beside an RL). A
        # row gives {id: [{"text", "warn", "off"}]}; nothing here is saved.
        self.info = list(info or [])
        self.row_heading = row_heading      # the first column's heading
        # rows(stored, env) when the rows show page data (a suggestion, or
        # site records such as the regulatory limits); the stamp is taken
        # with the same env, so a change to which rows are listed makes an
        # open page stale. rows(stored, None) must still work (tests).
        self.rows_take_env = rows_take_env
        self.title = title
        self.read = read
        self.write = write
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


def _rows(table, stored, env=None):
    if table.rows_take_env:
        return table.rows(stored or {}, env)
    return table.rows(stored or {})


def _cells(table, stored, row_key):
    if table.read is not None:
        vals = table.read(stored or {}).get(tuple(row_key)) or {}
        return dict((c.name, vals.get(c.path[0])) for c in table.columns)
    node = _row_node(table, stored, row_key)
    return dict((c.name, _get(node, c.path)) for c in table.columns)


def stamp_table(table, stored, env=None):
    """The listed rows' keys AND values: a change to which rows the page shows
    (e.g. the inclusion grid) also makes an open page stale, so no field can
    be read against a row set it was not drawn for."""
    table = _bound(table, stored)
    _groups, rows = _rows(table, stored, env)
    blob = []
    for r in rows:
        vals = dict((k, v) for k, v in _cells(table, stored, r["key"]).items()
                    if v not in (None, u"", ""))
        blob.append([list(r["key"]), vals])
    return _history.fingerprint(blob)


def render_table(table, stored, env=None):
    table = _bound(table, stored)
    groups, rows = _rows(table, stored, env)
    info_labels = [label for _i, label in getattr(table, "info", [])]
    by_group = dict((g["key"], dict(g, rows=[], set=0, info_labels=info_labels))
                    for g in groups)
    order = [g["key"] for g in groups]
    for r in rows:
        vals = _cells(table, stored, r["key"])
        cells = []
        for c in table.columns:
            v = vals[c.name]
            choices = _choices(c, stored, env)
            if c.kind == CHOICE and v not in (None, u"", "") and v not in [x[0] for x in choices]:
                choices.append((v, u"%s (stored value)" % v))
            cells.append({"name": cell_name(table, r["key"], c), "kind": c.kind,
                          "label": c.label, "min": c.minimum, "max": c.maximum,
                          # a row may say what blank means for it (e.g. a derived RL)
                          "placeholder": (r.get("placeholders") or {}).get(c.path[0], c.placeholder),
                          "choices": choices,
                          "value": u"" if v is None else u"%s" % v,
                          "checked": bool(v) if c.kind == BOOL else False})
        g = by_group.get(r.get("group"))
        if g is None:
            continue
        suggest = r.get("suggest")          # (value, label): shown, never pre-selected
        g["rows"].append({"label": r.get("label"), "sublabel": r.get("sublabel"),
                          "note": r.get("note"), "warn": r.get("warn"), "cells": cells,
                          "info": [(r.get("info") or {}).get(i) or []
                                   for i, _l in getattr(table, "info", [])],
                          "suggest": ({"value": suggest[0], "label": suggest[1],
                                       "target": cells[0]["name"]}
                                      if suggest and not vals[table.columns[0].name] else None)})
        if any(vals[c.name] not in (None, u"", "") for c in table.columns):
            g["set"] += 1
    out = []
    for i, key in enumerate(order):
        g = by_group[key]
        g["index"] = i
        g["total"] = len(g["rows"])
        g["row_heading"] = table.row_heading
        g["columns"] = [{"label": c.label, "unit": g.get("unit") or c.unit}
                        for c in table.columns]
        out.append(g)
    return out


def parse_table(table, form, stored, env=None):
    """(updates {row key: {column path: value}}, errors) for the listed rows."""
    table = _bound(table, stored)
    _groups, rows = _rows(table, stored, env)
    updates, errors = {}, []
    for r in rows:
        saved = _cells(table, stored, r["key"])
        vals, ok = {}, True
        for c in table.columns:
            value, error = _value(c, form.get(cell_name(table, r["key"], c)),
                                  saved[c.name], u"%s %s" % (r.get("label"), c.label),
                                  choices=_choices(c, stored, env))
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


def apply_table(table, stored, updates, env=None):
    table = _bound(table, stored)
    if table.write is not None:
        return table.write(copy.deepcopy(stored or {}), updates, env)
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
# The page draws every existing row and a "+ Add <noun>" button (lab,
# 2026-10-03: no spare blank rows). The button clones a template row whose
# index is NEW_INDEX, numbered from len(rows) upward in the browser; the parse
# reads every index the form carries. Clearing a row's name removes it. Rows
# are addressed by POSITION, which is safe because the stamp is the whole
# read() list: if anyone changed the collection after the page was drawn, the
# save is stale.

NEW_INDEX = u"NEW"   # alphanumeric: the page swaps "__NEW__" for "__<n>__"


class Collection(object):

    def __init__(self, id, title, columns, read, write, check=None,
                 noun=u"row", intro=u"", allow_empty=False):
        self.id = id
        self.title = title
        self.columns = columns
        self.read = read
        self.write = write
        self.check = check
        self.noun = noun
        self.intro = intro
        self.allow_empty = allow_empty    # False: removing every row is refused

    def fields(self):
        return list(self.columns)

    @property
    def key(self):
        return self.columns[0]


def collection_name(coll, index, column):
    return u"__".join([u"c", _enc(coll.id), u"%s" % index] + [_enc(p) for p in column.path])


def _new_indices(coll, form, start):
    """Indices >= start that any field of the form names (rows added with
    "+ Add" -- a row with values but no name must still be seen, and
    refused), in order."""
    head = u"c__%s__" % _enc(coll.id)
    found = set()
    for k in (form or {}).keys():
        k = k.decode("utf-8") if isinstance(k, bytes) else u"%s" % k
        if k.startswith(head):
            mid = k[len(head):].partition(u"__")[0]
            if mid.isdigit() and int(mid) >= start:
                found.add(int(mid))
    return sorted(found)


def render_collection(coll, stored, env=None):
    coll = _bound(coll, stored)
    rows = coll.read(stored or {})
    out = []
    for i in list(range(len(rows))) + [NEW_INDEX]:
        vals = rows[i] if i != NEW_INDEX else {}
        cells = []
        for c in coll.columns:
            v = vals.get(c.path[0])
            choices = _choices(c, stored, env)
            if c.kind == CHOICE and v not in (None, u"", "") and v not in [x[0] for x in choices]:
                choices.append((v, u"%s (stored value)" % v))
            cells.append({"name": collection_name(coll, i, c), "kind": c.kind,
                          "label": c.label, "min": c.minimum, "max": c.maximum,
                          "placeholder": c.placeholder if i != NEW_INDEX or c is coll.key
                                         else u"",
                          "choices": choices,
                          "value": u"" if v is None else u"%s" % v,
                          "checked": bool(v) if c.kind == BOOL else False})
        out.append({"index": i, "new": i == NEW_INDEX, "template": i == NEW_INDEX,
                    "noun": coll.noun, "next": len(rows), "cells": cells})
    return out


def parse_collection(coll, form, stored, env=None):
    """(rows [{column: value}], errors) -- the collection as submitted."""
    coll = _bound(coll, stored)
    before = coll.read(stored or {})
    rows, errors, seen = [], [], set()
    added = _new_indices(coll, form, len(before))
    for i in list(range(len(before))) + added:
        old = before[i] if i < len(before) else {}
        name, error = _value(coll.key, form.get(collection_name(coll, i, coll.key)),
                             old.get(coll.key.path[0]),
                             choices=_choices(coll.key, stored, env))
        if name in (None, u"", REMOVE, _SKIP):
            if error:
                errors.append(error)
            elif i >= len(before):
                filled = [c.label for c in coll.columns[1:] if c.kind != BOOL and
                          _text(form.get(collection_name(coll, i, c)))]
                if filled:
                    errors.append(u"New %s %d: give it a name, or clear %s." % (
                        coll.noun, added.index(i) + 1, u", ".join(filled)))
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
                                  choices=_choices(c, stored, env))
            if error:
                errors.append(error)
            elif value is not _SKIP:
                row[c.path[0]] = None if value is REMOVE else value
        rows.append(row)
    if not errors and not rows and not coll.allow_empty:
        errors.append(u"At least one %s is needed; nothing was removed." % coll.noun)
    if not errors and coll.check is not None:
        errors.extend(coll.check(stored or {}, rows) or [])
    return rows, errors
