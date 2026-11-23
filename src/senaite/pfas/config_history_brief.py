# -*- coding: utf-8 -*-
"""Configuration History, said briefly: the one line a change's row shows,
and the full change, value by value, its dialog shows
(@@pfas-config-history).

A change is config_history's list of {"path", "before", "after"}, each the
smallest path that changed: a whole dict or list appears only where it was
set or cleared at once. The line names the setting and, where it fits,
the value before and after; a value set or cleared as a whole is counted
by its entries. Nothing here reads or writes the history.
Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import json

import six

# a value longer than this is not repeated in the row's line
SHORT = 28
# the row's line is cut at this length
LINE = 72
ARROW = "→"


def _text(value):
    if isinstance(value, six.binary_type):
        return value.decode("utf-8")
    return six.text_type(value)


def where(path):
    """A change's path in words: its parts joined, an underscore read as a space."""
    words = " / ".join(_text(p).replace("_", " ") for p in (path or ()))
    return words[:1].upper() + words[1:] if words else "The setting"


def shown(value):
    """A value as the dialog shows it, whole."""
    if value is None:
        return "not set"
    if value in ("", b""):
        return "empty"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return _text(value)


def _entries(n):
    return "1 entry" if n == 1 else "%d entries" % n


def _one(change):
    """One change in a few words, its setting first."""
    before, after = change.get("before"), change.get("after")
    name = where(change.get("path"))
    if isinstance(after, dict) and not before:
        return "%s: %s set" % (name, _entries(len(after)))
    if isinstance(before, dict) and not after:
        return "%s: %s cleared" % (name, _entries(len(before)))
    if isinstance(before, (list, tuple)) or isinstance(after, (list, tuple)):
        return "%s: %s %s %s" % (name, _entries(len(before or ())), ARROW, _entries(len(after or ())))
    b, a = shown(before), shown(after)
    if len(b) <= SHORT and len(a) <= SHORT:
        return "%s: %s %s %s" % (name, b, ARROW, a)
    return "%s changed" % name


def brief(changes):
    """The row's line: the first change in words, and how many more."""
    changes = list(changes or ())
    if not changes:
        return "No values changed"
    line = _one(changes[0])
    if len(changes) > 1:
        line = "%s and %d more" % (line, len(changes) - 1)
    return line if len(line) <= LINE else line[:LINE - 1].rstrip() + "…"


def detail(changes):
    """The dialog's rows, [{"setting", "before", "after"}]: a dict set or
    cleared as a whole is opened to one row per entry."""
    out = []
    for c in changes or ():
        before, after = c.get("before"), c.get("after")
        name = where(c.get("path"))
        whole = (isinstance(after, dict) and not before) or (isinstance(before, dict) and not after)
        if whole:
            held = after if isinstance(after, dict) else before
            for k in sorted(held, key=_text):
                b = before.get(k) if isinstance(before, dict) else None
                a = after.get(k) if isinstance(after, dict) else None
                out.append({"setting": "%s / %s" % (name, _text(k)), "before": shown(b), "after": shown(a)})
            continue
        out.append({"setting": name, "before": shown(before), "after": shown(after)})
    return out
