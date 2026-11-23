# -*- coding: utf-8 -*-
"""@@pfas-type-icons: the one way a template draws a sample type's icon
(senaite.pfas.sample_type_icons). It reads nothing and grants nothing.

    context/@@pfas-type-icons/svg     python:ti.svg('LFSM')
    python:ti.cell('LFB', 'LFB Mid')  an icon and its words
    python:ti.cells('MB 1, LFB 1')    a list, each item with its icon
    python:ti.change(entry)           "CCV to Sample", each with its icon
    context/@@pfas-type-icons/spec    the drawings as JSON, written once
                                      by the page macro for pfas-components.js
Python 2.7 compatible.
"""
from __future__ import absolute_import

from Products.Five.browser import BrowserView

from senaite.pfas import sample_type_icons as sti


class PFASTypeIcons(BrowserView):

    def svg(self, code, sub=None, na=False, hidden=False):
        return sti.svg(code, sub, na, hidden)

    def cell(self, code, words=None):
        return sti.cell(code, words)

    def cells(self, text, sep=", "):
        return sti.cells(text, sep)

    def change(self, entry):
        return sti.change(entry)

    def label(self, code, sub=None):
        return sti.label(code, sub)

    def group(self, code):
        return sti.group_of(code)

    def row(self, rule_key, profile, off=False):
        return sti.row(rule_key, profile, off)

    def spec(self):
        return sti.spec()
