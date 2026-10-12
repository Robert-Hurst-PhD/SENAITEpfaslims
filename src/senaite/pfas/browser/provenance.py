# -*- coding: utf-8 -*-
"""@@pfas-provenance?batch_id=WS-296&key=LFSM|WS-296-LFSM1|PFOA

The record behind one value in Data Review, with the imported rows and the
export lines it was computed from, as JSON for the drawer
(static/provenance.js). Staff only: the rows name samples and files.
Read-only.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

from Products.Five.browser import BrowserView

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import ANALYST_ROLES, MANAGER_ROLES, has_role_at_portal, refuse

logger = logging.getLogger("senaite.pfas.provenance")


class PFASProvenanceView(BrowserView):

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        if not (has_role_at_portal(self.context, MANAGER_ROLES)
                or has_role_at_portal(self.context, ANALYST_ROLES)):
            return refuse(self.request, json.dumps({"error": "Staff only."}))
        batch_id = (self.request.form.get("batch_id") or "").strip()
        key = (self.request.form.get("key") or "").strip()
        if not batch_id or not key:
            self.request.response.setStatus(400)
            return json.dumps({"error": "batch_id and key are required."})
        try:
            from senaite.pfas.provenance_store import ProvenanceStore
            out = ProvenanceStore().bundle(batch_id, key)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("provenance bundle failed for %s %s", batch_id, key)
            self.request.response.setStatus(500)
            return json.dumps({"error": "The record could not be read: %s" % exc})
        if out.get("error"):
            self.request.response.setStatus(404)
        return json.dumps(out, default=str)
