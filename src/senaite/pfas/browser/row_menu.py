# -*- coding: utf-8 -*-
"""@@pfas-row-menu: the one way a template writes a table row's menu
(senaite.pfas.row_menu.actions). It reads nothing and grants nothing: the
pages the actions lead to keep their own permissions.
Python 2.7 compatible.
"""
from __future__ import absolute_import

from Products.Five.browser import BrowserView

from senaite.pfas import row_menu


class PFASRowMenu(BrowserView):

    def actions(self, *items):
        return row_menu.actions(*items)

    def action(self, label, kind, target, options=None):
        return row_menu.action(label, kind, target, options)
