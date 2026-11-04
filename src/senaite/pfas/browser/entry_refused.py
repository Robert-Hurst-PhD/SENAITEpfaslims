# -*- coding: utf-8 -*-
"""@@pfas-entry-refused: where a refused data-entry or review form lands --
why, and the way to People & Roles (entry_rights.py). Python 2.7."""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.browser.staff import entry_status


class PFASEntryRefusedView(ViewHelpers, BrowserView):
    """Where a refused data-entry or review form lands: why, and the way to
    People & Roles (entry_rights.py)."""
    template = ViewPageTemplateFile("templates/entry_refused.pt")

    def __call__(self):
        return self.template()

    def reason(self):
        from senaite.pfas import entry_rights
        return entry_rights.REFUSAL

    def status_label(self):
        from senaite.pfas import entry_rights
        try:
            user = api.get_current_user()
            return entry_rights.LABELS.get(entry_status(user.getId()), u"")
        except Exception:                                   # noqa: BLE001
            return u""

