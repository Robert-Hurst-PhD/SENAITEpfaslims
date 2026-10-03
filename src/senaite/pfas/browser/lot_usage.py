# -*- coding: utf-8 -*-
"""Where a lot was used, and a search by lot number
(@@pfas-lot-usage; docs/BENCH_WORKFLOW_REVIEW.md phase 3). Reached from each
lot's "Where used" button; not a sidebar item (lab, 2026-10-03: useful, but
the lab does not issue recalls -- GAPS §98).

    ?kind=reagent&uid=<id>   one lot: every batch and stage that used it
    ?q=<lot text>            every use of any lot whose number
                             contains the text

Reads the usage ledger the guided extraction writes (inventory_ledger).
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.lot_usage")


class PFASLotUsageView(BrowserView):

    template = ViewPageTemplateFile("templates/lot_usage.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return getToolByName(self.context, "portal_url").getPortalObject().absolute_url()

    def query(self):
        return (self.request.form.get("q") or u"").strip()

    def item(self):
        """The lot this page is about (?kind=&uid=), or None."""
        kind, uid = self.request.form.get("kind") or u"", self.request.form.get("uid") or u""
        if not (kind and uid):
            return None
        from senaite.pfas.browser.bench_inventory import item_index
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        return item_index(portal).get((kind, uid))

    def rows(self):
        from senaite.pfas import inventory_ledger as led
        try:
            it = self.item()
            if it is not None:
                return led.uses_of(None, it["kind"], it["uid"])
            if self.query():
                return led.uses_by_lot(None, self.query())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("lot usage: %s", exc)
        return []

    def guide_url(self, row):
        return u"{0}/@@pfas-extraction-guide?batch_uid={1}".format(
            self.portal_url(), row.get("batch_uid") or u"")
