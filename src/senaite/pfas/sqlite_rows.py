# -*- coding: utf-8 -*-
"""Reading a sqlite3.Row by its column names, the one way.

Under Python 2 a sqlite3.Row takes an int or a byte-string key only: a
unicode key raises "Index must be int or string". Every module with
`unicode_literals` passes unicode, so `row["col"]` fails there. Read a row
through these instead: each column by the name Row itself reports (its own
key type), the dict keyed by text.

    as_dict(row)   -> {column: value}, or None for no row
    as_dicts(rows) -> [as_dict(row), ...]

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import six


def _text(name):
    return name.decode("utf-8") if isinstance(name, six.binary_type) else name


def as_dict(row):
    """The row as {column: value}, each read by the key the row reports."""
    if row is None:
        return None
    return dict((_text(k), row[k]) for k in row.keys())


def as_dicts(rows):
    return [as_dict(r) for r in rows or []]
