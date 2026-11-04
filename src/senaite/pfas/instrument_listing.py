# -*- coding: utf-8 -*-
"""The core Instruments list (bika_setup/bika_instruments): each
instrument's methods as short method-id tags, the full name on hover,
instead of a run-on list of full method names.

    method_tags([(method id, title)]) -> the cell's HTML
    InstrumentMethodTagsAdapter         senaite.app.listing subscriber

Python 2.7 and 3 compatible.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.html_text import escape


def _esc(v):
    return escape(u"%s" % (v or u""))


def method_tags(methods):
    """One tag per method: its short id, its full name as the hover title."""
    return u" ".join(u'<span class="pfas-chip" title="%s">%s</span>' % (_esc(title), _esc(mid))
                     for mid, title in methods or [])


def _short_id(method):
    for getter in ("getMethodID", "getId"):
        try:
            v = getattr(method, getter)()
        except AttributeError:
            v = None
        if v:
            return v
    return u""


class InstrumentMethodTagsAdapter(object):
    """senaite.app.listing subscriber on the core Instruments list."""

    priority_order = 1200

    def __init__(self, listing, context):
        self.listing, self.context = listing, context

    def before_render(self):
        return

    def folder_item(self, obj, item, index):
        if not item:
            return item
        try:
            from bika.lims import api
            inst = api.get_object(obj)
            methods = inst.getMethods() or []
        except Exception:                                   # noqa: BLE001
            return item
        if methods:
            item.setdefault("replace", {})["Methods"] = method_tags(
                [(_short_id(m), m.Title()) for m in methods])
        return item
