# -*- coding: utf-8 -*-
"""A worksheet marked retired: its record and signatures stay, and the work
queues leave it out (the bench's extraction queue, the Data Review queue, the
Batch records "In progress" list, the bench's run requests, the instrument
upload match and the unjudged-result deviation scan). Nothing else changes:
the worksheet keeps its workflow state, its analyses and its signed record,
and every page that names it by id still opens it.

The mark is one annotation on the worksheet: {"note", "by", "at"}. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json

KEY = "senaite.pfas.retired"


def _ann(ws):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(ws)


def get(ws):
    """The mark ({"note", "by", "at"}), or None when the worksheet is not retired
    or its mark cannot be read."""
    try:
        raw = _ann(ws).get(KEY)
        mark = json.loads(raw) if raw else None
    except Exception:                                       # noqa: BLE001
        return None
    return mark if isinstance(mark, dict) else None


def is_retired(ws):
    return get(ws) is not None


def note(ws):
    """The note the worksheet was retired with, or u"" ."""
    return (get(ws) or {}).get("note") or u""


def retire(ws, text, by, at):
    """Mark the worksheet retired. Returns the mark; a worksheet retired
    already keeps its first mark."""
    have = get(ws)
    if have is not None:
        return have
    mark = {"note": text, "by": by, "at": at}
    _ann(ws)[KEY] = json.dumps(mark)
    return mark


def clear(ws):
    """Take the mark away. Returns the mark that was there, or None."""
    have = get(ws)
    if have is not None:
        del _ann(ws)[KEY]
    return have
