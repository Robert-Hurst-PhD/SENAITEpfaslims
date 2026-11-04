# -*- coding: utf-8 -*-
"""
Shared form-normalisation helper for PFAS browser views.

Zope merges a query-string parameter and a same-named POST-body field into a
LIST (e.g. a page reached at `?batch_id=X` whose form also posts a hidden
`batch_id`). PFAS forms use only SCALAR fields — every multi-value payload is
packed into a JSON string (`*_json`); there are no multi-selects or checkbox
groups — so a form field that arrives as a list of strings is always accidental
duplication. Handlers that then call `.strip()` / `.split()` on it crash with
`'list' object has no attribute 'strip'`.

`flatten_form` collapses such string-valued lists to their first value once, at
the top of a view's `__call__`. File uploads and Zope record fields are left
untouched.

Python 2.7 compatible.
"""
from __future__ import absolute_import

try:
    _TEXT = (str, unicode, bytes)          # noqa: F821  (Py2.7)
except NameError:                          # pragma: no cover  (Py3)
    _TEXT = (str, bytes)


def flatten_form(request):
    """Collapse any string-valued list form field to its first value. Returns
    the request for convenience. Safe to call on every request (no-op when no
    field is duplicated)."""
    form = getattr(request, "form", None)
    if not form:
        return request
    try:
        items = list(form.items())
    except Exception:
        return request
    for key, val in items:
        if isinstance(val, (list, tuple)) and val and all(
                isinstance(v, _TEXT) for v in val):
            form[key] = val[0]
    return request


def quote_text(text):
    """`text` quoted for a URL's query string."""
    try:
        from urllib import quote
    except ImportError:                       # pragma: no cover
        from urllib.parse import quote
    return quote((u"%s" % text).encode("utf-8"))


def first(value, default=u""):
    """First value if `value` arrived as a list/tuple, else the value itself."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return default if value is None else value


def json_list(form, field, what, default=None):
    """The list a page's script wrote into the hidden field `field`. Absent:
    `default` (a list; the saved rows are kept). Unreadable or not a list:
    ValueError naming `what`, so the handler refuses the save and a broken
    post never replaces a record's rows with nothing."""
    if field not in form:
        return list(default or [])
    import json
    try:
        rows = json.loads(form.get(field) or "[]")
    except (ValueError, TypeError):
        raise ValueError("the {0} could not be read; nothing was saved".format(what))
    if not isinstance(rows, list):
        raise ValueError("the {0} is not a list; nothing was saved".format(what))
    return rows
