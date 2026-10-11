# -*- coding: utf-8 -*-
"""The column-mapped EDD profile's settings forms, read from a posted form
(a dict of scalar fields, one per control; indexed names such as
`f0__name`, `c3__source`, `m1__r2__code`). Each reader returns the profile
section the form edits; nothing else of the profile changes.

    read_files(form, profile)          -> (files, package)
    read_columns(form, profile, i)     -> columns of file i
    read_maps(form, profile)           -> maps
    read_named(form)                   -> {name: value}
    read_client_fields(form)           -> [{key, label, list}]
    add_columns(columns, n)            -> columns with n blank ones
    new_list(lists, name, values)      -> lists with one replaced

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import re

COLUMN_KEYS = ("heading", "source", "fallback", "constant", "map", "format", "when", "join", "list",
               "max_length")
BLANK_ROWS = 3           # empty rows a table offers for adding


def _v(form, name):
    v = form.get(name)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else u""
    return u"" if v is None else (u"%s" % v).strip()


def _on(form, name):
    return _v(form, name) not in (u"", u"0", u"off", u"false")


def _indexes(form, pattern):
    rx = re.compile(pattern)
    out = set()
    for k in form.keys():
        m = rx.match(k)
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def read_files(form, profile):
    """The files as posted (a ticked `remove` drops one) and the package
    name pattern."""
    old = (profile or {}).get("files") or []
    files = []
    for i in _indexes(form, r"^f(\d+)__name$"):
        if _on(form, "f%d__remove" % i):
            continue
        f = copy.deepcopy(old[i]) if i < len(old) else {"columns": []}
        for key in ("name", "grain", "delimiter", "header", "header_prefix", "newline"):
            if ("f%d__%s" % (i, key)) in form:
                f[key] = _v(form, "f%d__%s" % (i, key))
        # a tab is posted by its name (a form field's value cannot be a tab)
        if f.get("delimiter") == u"tab":
            f["delimiter"] = u"\t"
        files.append(f)
    package = _v(form, "package") if "package" in form else (profile or {}).get("package") or u""
    return files, package


def read_columns(form, profile, index):
    """The columns of file `index` as posted, in the order their `order`
    fields give (a ticked `remove` drops one)."""
    files = (profile or {}).get("files") or []
    old = files[index].get("columns") or [] if index < len(files) else []
    rows = []
    for j in _indexes(form, r"^c(\d+)__heading$"):
        if _on(form, "c%d__remove" % j):
            continue
        c = copy.deepcopy(old[j]) if j < len(old) else {}
        for key in COLUMN_KEYS:
            if ("c%d__%s" % (j, key)) in form:
                c[key] = _v(form, "c%d__%s" % (j, key))
        c["required"] = _on(form, "c%d__required" % j)
        try:
            order = float(_v(form, "c%d__order" % j) or j + 1)
        except ValueError:
            order = j + 1
        rows.append((order, j, c))
    rows.sort(key=lambda t: (t[0], t[1]))
    return [c for _o, _j, c in rows]


def add_columns(columns, n):
    out = list(columns or [])
    for _ in range(max(0, min(int(n or 0), 200))):
        out.append(dict((k, u"") for k in COLUMN_KEYS))
    return out


def read_maps(form, profile):
    """The code maps as posted: each map's name, second key, valid list and
    rows (a row needs `ours`; a ticked `remove` drops a row or a map)."""
    maps = {}
    for k in _indexes(form, r"^m(\d+)__name$"):
        name = _v(form, "m%d__name" % k)
        if not name or _on(form, "m%d__remove" % k):
            continue
        rows = []
        for n in _indexes(form, r"^m%d__r(\d+)__ours$" % k):
            ours = form.get("m%d__r%d__ours" % (k, n))
            ours = u"" if ours is None else (u"%s" % ours)
            if not ours.strip() or _on(form, "m%d__r%d__remove" % (k, n)):
                continue
            rows.append({"ours": ours.strip(), "code": _v(form, "m%d__r%d__code" % (k, n)),
                         "description": _v(form, "m%d__r%d__description" % (k, n))})
        maps[name] = {"by": _v(form, "m%d__by" % k), "list": _v(form, "m%d__list" % k), "rows": rows}
    new = _v(form, "new_map")
    if new and new not in maps:
        maps[new] = {"by": u"", "list": u"", "rows": []}
    return maps


def read_named(form):
    out = {}
    for n in _indexes(form, r"^d(\d+)__name$"):
        name = _v(form, "d%d__name" % n)
        if name and not _on(form, "d%d__remove" % n):
            out[name] = form.get("d%d__value" % n) if form.get("d%d__value" % n) is not None else u""
            out[name] = (u"%s" % out[name]).strip()
    return out


def read_client_fields(form):
    out = []
    for n in _indexes(form, r"^cf(\d+)__key$"):
        key = _v(form, "cf%d__key" % n)
        if key and not _on(form, "cf%d__remove" % n):
            out.append({"key": key, "label": _v(form, "cf%d__label" % n) or key,
                        "list": _v(form, "cf%d__list" % n)})
    return out


def new_list(lists, name, values):
    out = dict(lists or {})
    out[name] = list(values)
    return out


def parse_pasted(text):
    """One code per line (blank lines and repeats dropped)."""
    out = []
    for line in (text or u"").splitlines():
        v = line.strip()
        if v and v not in out:
            out.append(v)
    return out
