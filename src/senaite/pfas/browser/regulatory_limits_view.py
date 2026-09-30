# -*- coding: utf-8 -*-
"""@@pfas-regulatory-limits: the MCL / action-level table and program links the
certificate's regulatory notes read (regulatory_limits.py, GAPS §50 part B).

Only a VERIFIED limit reaches a certificate. Ticking Verified records who
confirmed the value and when, the audit trail an assessor will ask for; the
seeds ship unverified with their citation and link so the lab can check each
one against its source. Saving is configuration tier (perms.TIER_CONFIG).
Python 2.7 compatible.
"""
from __future__ import absolute_import

import logging

from bika.lims import api
from DateTime import DateTime
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import regulatory_limits as rg
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import GateMixin, TIER_CONFIG, deny_gated_action

logger = logging.getLogger("senaite.pfas.regulatory_limits")

REGULATORY_GATES = {"save": TIER_CONFIG}


class PFASRegulatoryLimitsView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/regulatory_limits.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors = []
        if self.request.method == "POST":
            action = self.request.form.get("action", "")
            denied = deny_gated_action(self.context, self.request, action,
                                       REGULATORY_GATES)
            if denied is not None:
                return denied
            if action == "save":
                try:
                    self._save()
                except ValueError as exc:
                    self.errors.append(u"%s" % exc)
                    return self.template()
                self.request.response.redirect(
                    api.get_portal().absolute_url() + "/@@pfas-regulatory-limits?saved=1")
                return ""
        return self.template()

    # ── template data ─────────────────────────────────────────────────────

    def store(self):
        return rg.get_store(api.get_portal())

    def program_ids(self):
        """federal + every state EDD profile (a client's program is its EDD profile)."""
        ids = [rg.FEDERAL]
        try:
            from senaite.pfas.egad_store import get_edd_profiles
            ids += sorted(get_edd_profiles(api.get_portal()).keys())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("no EDD profiles: %s", exc)
        return ids

    def programs(self):
        progs = self.store().get("programs") or {}
        out = []
        for pid in self.program_ids():
            p = progs.get(pid) or {}
            out.append({"id": pid, "name": p.get("name") or pid,
                        "links": u"\n".join(u"%s | %s" % (l.get("label", u""), l.get("url", u""))
                                            for l in (p.get("links") or []))})
        return out

    def rows(self):
        out = []
        for i, l in enumerate(self.store().get("limits") or []):
            r = dict(l)
            r["index"] = i
            r["analytes_text"] = u", ".join(l.get("analytes") or [])
            r["matrices_text"] = u", ".join(l.get("matrices") or [])
            out.append(r)
        return out

    def kinds(self):
        return rg.KINDS

    def units(self):
        return ["ng/L", "ng/mL", "ug/L", "ng/kg", "ng/g", "ug/kg"]

    def saved(self):
        return bool(self.request.form.get("saved"))

    # ── save ──────────────────────────────────────────────────────────────

    def _save(self):
        portal = api.get_portal()
        store = rg.get_store(portal)
        limits = rg.parse_limits_form(
            self.request.form, store.get("limits") or [],
            api.get_current_user().getId(), DateTime().strftime("%Y-%m-%d %H:%M"))
        programs = rg.parse_programs_form(self.request.form, self.program_ids())
        rg.save_store(portal, {"programs": programs, "limits": limits})
        logger.info("regulatory limits saved: %d limits", len(limits))
