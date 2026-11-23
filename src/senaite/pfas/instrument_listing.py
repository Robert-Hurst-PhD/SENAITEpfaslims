# -*- coding: utf-8 -*-
"""The core Instruments list (bika_setup/bika_instruments): each
instrument's methods as one tag each, by the method's one name (its
profile's display name), instead of a run-on list of core method titles.

    method_tags([(tag text, hover title)]) -> the cell's HTML
    InstrumentMethodTagsAdapter         senaite.app.listing subscriber

Python 2.7 and 3 compatible.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.html_text import escape


def _esc(v):
    return escape(u"%s" % (v or u""))


def method_tags(methods):
    """One tag per method: its text and its hover title."""
    return u" ".join(u'<span class="pfas-chip" title="%s">%s</span>' % (_esc(title), _esc(mid))
                     for mid, title in methods or [])


def _name(method):
    """The method's one name; never its stored id where a name exists."""
    from senaite.pfas.browser.view_helpers import core_method_name
    return core_method_name(method)


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
                [(name, name) for name in (_name(m) for m in methods)])
        return item
