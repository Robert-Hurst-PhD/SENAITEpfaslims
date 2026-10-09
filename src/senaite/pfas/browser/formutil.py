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


def first(value, default=u""):
    """First value if `value` arrived as a list/tuple, else the value itself."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return default if value is None else value
