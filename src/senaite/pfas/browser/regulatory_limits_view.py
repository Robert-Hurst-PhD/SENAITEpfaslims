# -*- coding: utf-8 -*-
"""@@pfas-regulatory-limits: the MCL / action-level table and program links the
certificate's regulatory notes read (regulatory_limits.py, part B).

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
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.regulatory_limits")

REGULATORY_GATES = {"save": TIER_CONFIG, "save_programs": TIER_CONFIG,
                    "retire": TIER_CONFIG, "verify": TIER_CONFIG}
BLANK = {"id": "", "program": rg.FEDERAL, "label": "", "analytes_text": "", "matrices": [],
         "matrix_uids": [], "value": "", "unit": "ng/L", "kind": "MCL", "citation": "", "effective": "",
         "status_note": "", "url": "", "verified": False}


class PFASRegulatoryLimitsView(ViewHelpers, GateMixin, BrowserView):

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
            handler = None
            if action == "save":
                handler = self._save
            elif action == "save_programs":
                handler = self._save_programs
            elif action == "retire":
                handler = self._retire
            elif action == "verify":
                handler = self._verify
            if handler is not None:
                try:
                    handler()
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
            from senaite.pfas.edd_store import get_edd_profiles
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

    def sample_types(self):
        """[(uid, title)]: the core Sample Types a limit's matrices are
        chosen from."""
        if getattr(self, "_sample_types", None) is None:
            out = []
            try:
                for b in api.search({"portal_type": "SampleType"}, "senaite_catalog_setup"):
                    out.append((b.UID, api.get_object(b).Title()))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("sample types: %s", exc)
            self._sample_types = sorted(out, key=lambda t: t[1].lower())
        return self._sample_types

    def subtype_choices(self):
        """[(id, name, sample type uid)]: every Sample Type's sub-types a
        limit may narrow to (sample_subtypes)."""
        if getattr(self, "_subtypes", None) is None:
            from senaite.pfas import sample_subtypes as ss
            out = []
            for uid, _title in self.sample_types():
                try:
                    obj = api.get_object_by_uid(uid)
                except Exception:                           # noqa: BLE001
                    continue
                out += [(x["id"], x["name"], uid) for x in ss.load(obj)]
            self._subtypes = out
        return self._subtypes

    def status(self):
        return "retired" if self.request.form.get("status") == "retired" else "active"

    def status_links(self):
        base = self.portal_url() + "/@@pfas-regulatory-limits"
        return [{"label": label, "on": key == self.status(),
                 "url": base + ("?status=retired" if key == "retired" else "")}
                for key, label in (("active", u"Active"), ("retired", u"Retired"))]

    def _row(self, i, l):
        r = dict(l)
        r["index"] = i
        r["analytes_text"] = u", ".join(l.get("analytes") or [])
        r["analyte_column"] = rg.analyte_column(l.get("analytes") or [])
        r["matrices_text"] = u", ".join(l.get("matrices") or [])
        r["no_matrix"] = rg.no_matrix(l)
        r["matrix_uids"] = l.get("matrix_uids") or []
        r["subtypes_text"] = u", ".join(l.get("subtypes") or [])
        return r

    def rows(self):
        """The limits of the chosen status."""
        want_active = self.status() == "active"
        return [self._row(i, l) for i, l in enumerate(self.store().get("limits") or [])
                if rg.is_active(l) == want_active]

    def editing(self):
        """What the form edits: a limit's id, "new", "programs" or None. The
        form only for those who may save, when they ask for it."""
        if not self.can_configure():
            return None
        return self.request.form.get("edit") or None

    def edit_mode(self):
        return bool(self.editing())

    def edit_rows(self):
        """The one limit being edited (index 0), or a blank one."""
        which = self.editing()
        if which == "new":
            return [dict(BLANK, index=0)]
        for l in self.store().get("limits") or []:
            if l.get("id") == which:
                return [self._row(0, l)]
        return []

    def ticked(self, row, uid, title):
        if row.get("matrix_uids"):
            return uid in row["matrix_uids"]
        return title.strip().lower() in [(m or u"").strip().lower() for m in row.get("matrices") or []]

    def program_names(self):
        return dict((p["id"], p.get("name") or p["id"]) for p in self.programs())

    def kinds(self):
        return rg.KINDS

    def kind_choices(self, current=None):
        """[(key, label)]: the lab's active kinds, and the row's own."""
        from senaite.pfas import vocab_store as vs
        return vs.choices(vs.get(api.get_portal()), "regulatory_limit_kinds", current)

    def units(self):
        return ["ng/L", "ng/mL", "ug/L", "ng/kg", "ng/g", "ug/kg"]

    def saved(self):
        return bool(self.request.form.get("saved"))

    # ── save ──────────────────────────────────────────────────────────────

    def _who_now(self):
        return api.get_current_user().getId(), DateTime().strftime("%Y-%m-%d %H:%M")

    def _save(self):
        portal = api.get_portal()
        store = rg.get_store(portal)
        who, now = self._who_now()
        old = store.get("limits") or []
        posted = rg.parse_limits_form(self.request.form, old, who, now, self.sample_types(), self.subtype_choices())
        store["limits"] = rg.merge(old, posted)
        rg.save_store(portal, store)
        logger.info("regulatory limits saved: %s", [l["id"] for l in posted])

    def _save_programs(self):
        portal = api.get_portal()
        store = rg.get_store(portal)
        store["programs"] = rg.parse_programs_form(self.request.form, self.program_ids())
        rg.save_store(portal, store)

    def _retire(self):
        portal = api.get_portal()
        store = rg.get_store(portal)
        who, now = self._who_now()
        rg.retire(store.get("limits") or [], self.request.form.get("id"), who, now,
                  self.request.form.get("why"))
        rg.save_store(portal, store)

    def _verify(self):
        portal = api.get_portal()
        store = rg.get_store(portal)
        who, now = self._who_now()
        rg.mark_verified(store.get("limits") or [], self.request.form.get("id"), who, now)
        rg.save_store(portal, store)
