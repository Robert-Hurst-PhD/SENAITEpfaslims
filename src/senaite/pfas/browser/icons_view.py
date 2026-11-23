# -*- coding: utf-8 -*-
"""@@pfas-icons: the one way a template draws an icon (senaite.pfas.icons).
It reads nothing and grants nothing.

    python:ic.svg('fail', 'Blocks release')     an icon with its words as name
    python:ic.tip('pass', 'Has a login')        an icon alone, words on hover,
                                                focus and a long press
    python:ic.mark('warn')                      an outcome mark
    context/@@pfas-icons/spec                   the drawings as JSON, written
                                                once by the page macro
A sample type is 'type:<code>' (sample_type_icons, @@pfas-type-icons).
Python 2.7 compatible.
"""
from __future__ import absolute_import

from Products.Five.browser import BrowserView

from senaite.pfas import icons


class PFASIcons(BrowserView):

    def svg(self, name, label=None, state=None, mark=None, size=None, hidden=False, colour=None):
        return icons.svg(name, label, state, mark, size, hidden, colour)

    def tip(self, name, label, state=None, mark=None, size=None, colour=None):
        return icons.tip(name, label, state=state, mark=mark, size=size, colour=colour)

    def stage(self, icon, label, status, size=None, hidden=False):
        return icons.stage(icon, label, status, size, hidden)

    def status_mark(self, badge_cls, label, reasons=(), family="lot"):
        return icons.status_mark(badge_cls, label, reasons, family)

    def mark(self, kind, label=None, size=None):
        return icons.mark(kind, label, size)

    def spec(self):
        return icons.spec()
