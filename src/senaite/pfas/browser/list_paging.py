# -*- coding: utf-8 -*-
"""The paging of a long list: one page of rows at a time, with where it sits
in the whole and the addresses of its neighbours. Every long list draws it
with the `paging` macro of pfas_macros.pt; its filters are the page's own
filter bar (.pfas-filterbar), carried in each address.

    pg = paging(total, page_number(form), url_for)     # url_for(page) -> address
    rows = rows[pg["start"]:pg["end"]]

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from urllib import urlencode                            # Python 2
except ImportError:                                         # Python 3
    from urllib.parse import urlencode

PAGE_SIZE = 20


def page_number(form, key="page"):
    """The page asked for, 1 when none or not a number."""
    try:
        return max(1, int((form or {}).get(key) or 1))
    except (TypeError, ValueError):
        return 1


def paging(total, page, url_for, size=PAGE_SIZE):
    """{"first", "last", "total", "page", "pages", "prev", "next", "start",
    "end"}: the page shown (clamped to the last), rows first..last of total
    (1-based, 0 when empty), the slice start:end, and the neighbours'
    addresses (None at either end)."""
    total = max(0, int(total or 0))
    pages = max(1, (total + size - 1) // size)
    page = min(max(1, int(page or 1)), pages)
    start = (page - 1) * size
    end = min(total, start + size)
    return {"first": start + 1 if total else 0, "last": end, "total": total,
            "page": page, "pages": pages, "start": start, "end": end,
            "prev": url_for(page - 1) if page > 1 else None,
            "next": url_for(page + 1) if page < pages else None}


def list_url(base, params):
    """`base` with the filters that are set, in the order given (a list of
    (name, value)); a value of None or "" is left out."""
    kept = [(k, (u"%s" % v).encode("utf-8")) for k, v in params if v not in (None, u"", "")]
    return u"%s?%s" % (base, urlencode(kept)) if kept else base
