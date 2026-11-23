# -*- coding: utf-8 -*-
"""The electronic signature macros, @@pfas-esig-macros.

`sign_dialog` is the one dialog every signed step opens before it posts.
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASSignatureMacros(BrowserView):
    """Exposes esig_macros.pt macros to other templates."""

    _template = ViewPageTemplateFile("templates/esig_macros.pt")

    @property
    def macros(self):
        return self._template.macros

    def may_withdraw_row(self, seq):
        """True when the signed-in person signed ledger row `seq` and it
        still stands: the record's Signatures card offers them Withdraw,
        by the same rule as the Signatures page."""
        from senaite.pfas.browser import signatures_page as sp
        from senaite.pfas.esig import signing
        if seq is None:
            return False
        try:
            row = sp.find_row(seq)
            userid = signing.current_userid(self.request)
            if row is None or not sp.may_withdraw(row, userid):
                return False
            return sp.standing_signature(row)
        except Exception:                                   # noqa: BLE001
            return False

    def came_from(self):
        """This page's address, the one a withdrawal returns to."""
        url = self.request.get("ACTUAL_URL") or self.request.get("URL") or u""
        query = self.request.get("QUERY_STRING") or u""
        return u"%s?%s" % (url, query) if query else url

    def portal_url(self):
        from bika.lims import api
        return api.get_portal().absolute_url()

    def credential_kind(self):
        """What signing asks the signed-in person for: "pin" after a badge
        sign-in or when they made their PIN the default on their profile,
        else "password"."""
        from senaite.pfas.esig import credentials, signing
        try:
            return signing.credential_kind(self.request, signing.current_userid(self.request))
        except Exception:                                   # noqa: BLE001
            return credentials.PASSWORD
