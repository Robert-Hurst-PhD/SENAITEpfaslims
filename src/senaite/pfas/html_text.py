# -*- coding: utf-8 -*-
"""Text that is written into HTML by hand (the prepared-standard
certificate builds its page as a string): every value is escaped first."""
from __future__ import absolute_import, unicode_literals

_TEXT = ("".__class__, bytes)


def escape(text):
    """`text` with the five HTML-significant characters replaced."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def html_safe(data):
    """`data` (a record, a list, or a value) with every text escaped and
    every number, boolean and None left as it is."""
    if isinstance(data, dict):
        return dict((k, html_safe(v)) for k, v in data.items())
    if isinstance(data, (list, tuple)):
        return [html_safe(v) for v in data]
    if isinstance(data, _TEXT):
        return escape(data)
    return data
