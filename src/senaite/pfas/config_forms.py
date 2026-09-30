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
                 choices=None, blank=u"unset"):
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
        self.choices = list(choices or [])
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
    vals = current(section, stored)
    return _history.fingerprint(dict((k, v) for k, v in vals.items() if v not in (None, u"", "")))


def render(section, stored):
    """What the template draws: one dict per field, grouped."""
    vals = current(section, stored)
    groups = []
    for title, fields in section.groups:
        rows = []
        for f in fields:
            v = vals[f.name]
            choices = list(f.choices)
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


def parse(section, form, stored):
    """(updates {path: value|REMOVE}, errors [text]) for the submitted section.

    `stored` is the value as saved on the server: a choice field accepts its
    stored value even when it is not a listed option (it was offered on the
    page for that reason), and nothing sent by the browser can widen that.

    Call only when the form says it is this section (form["_section"]). A
    checkbox that is not submitted is False: the section's own form always
    carries all of its fields, so absence can only mean unchecked.
    """
    updates, errors = {}, []
    saved = current(section, stored)
    for f in section.fields():
        raw = form.get(f.name)
        if f.kind == BOOL:
            updates[f.path] = raw is True or _text(raw).lower() in (u"1", u"on", u"true", u"yes")
            continue
        text = _text(raw)
        if text == u"":
            if f.required:
                errors.append(u"%s is required." % f.label)
            elif f.blank == u"remove":
                updates[f.path] = REMOVE
            else:
                updates[f.path] = u"" if f.kind in (TEXT, TEXTAREA) else None
            continue
        if f.kind in (NUMBER, INT):
            try:
                num = float(text)
                if f.kind == INT:
                    if num != int(num):
                        raise ValueError
                    num = int(num)
            except ValueError:
                errors.append(u"%s must be %s, not %r." % (
                    f.label, u"a whole number" if f.kind == INT else u"a number", text))
                continue
            if f.minimum is not None and num < f.minimum:
                errors.append(u"%s must be at least %s." % (f.label, f.minimum))
                continue
            if f.maximum is not None and num > f.maximum:
                errors.append(u"%s must be at most %s." % (f.label, f.maximum))
                continue
            updates[f.path] = num
        elif f.kind == CHOICE:
            allowed = [c[0] for c in f.choices]
            if allowed and text not in allowed and text != _text(saved[f.name]):
                errors.append(u"%s: %r is not one of the options." % (f.label, text))
                continue
            updates[f.path] = text
        else:
            updates[f.path] = text
    return updates, errors


def apply(section, stored, updates):
    """A copy of `stored` with the section's updates written in."""
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
