# -*- coding: utf-8 -*-
"""Configuration › Sample sub-types: each core Sample
Type with its sub-types; a type's dialog lists them -- the method profiles
that analyse each, how many limits name it -- with + Add sub-type and
Remove. Saving is the configuration tier's (sample_subtypes.py).

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging

from bika.lims import api
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import sample_subtypes as ss
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse, require_manager

logger = logging.getLogger("senaite.pfas.browser.sample_subtypes_view")


class PFASSampleSubtypesView(ViewHelpers, BrowserView):

    template = ViewPageTemplateFile("templates/sample_subtypes.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            if not require_manager(self.context, self.request):
                return refuse(self.request, "Forbidden")
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
            return self._save()
        return self.template()

    def can_edit(self):
        return require_manager(self.context, self.request)

    def _profiles(self):
        if getattr(self, "_profs", None) is None:
            from senaite.pfas import configured_methods
            from senaite.pfas.method_profile_store import raw_profile
            portal = api.get_portal()
            self._labels = dict((m["id"], m["label"]) for m in configured_methods.choices(portal))
            self._profs = dict((m, raw_profile(portal, m) or {}) for m in self._labels)
        return self._profs

    def label(self, mid):
        self._profiles()
        return self._labels.get(mid, mid)

    def types(self):
        """Every core Sample Type with its sub-types and the profiles that
        analyse it."""
        out = []
        for b in api.search({"portal_type": "SampleType"}, "senaite_catalog_setup"):
            obj = api.get_object(b)
            subs = ss.load(obj)
            mids = ss.profiles_for(b.UID, obj.Title(), self._profiles())
            out.append({"uid": b.UID, "title": obj.Title(), "obj": obj, "subtypes": subs,
                        "names": u", ".join(s["name"] for s in subs) or u"—",
                        "profiles": [(m, self.label(m)) for m in mids],
                        "url": u"%s/@@pfas-sample-subtypes?type=%s" % (self.portal_url(), b.UID)})
        return sorted(out, key=lambda t: t["title"].lower())

    def _named(self, uid, subtypes):
        """{sub-type id: {"limits", "samples"}}: what names each."""
        from senaite.pfas import regulatory_limits as rg
        limits = rg.get_store(api.get_portal()).get("limits") or []
        samples = {}
        try:
            for b in api.search({"portal_type": "AnalysisRequest", "sampletype_uid": uid}, "senaite_catalog_sample"):
                fld = api.get_object(b).getField("SampleSubtype")
                sid = fld.get(api.get_object(b)) if fld is not None else u""
                if sid:
                    samples[sid] = samples.get(sid, 0) + 1
        except Exception as exc:                            # noqa: BLE001
            logger.warning("sub-type samples: %s", exc)
        return dict((s["id"], {"limits": len([l for l in limits if s["id"] in (l.get("subtype_ids") or [])]),
                               "samples": samples.get(s["id"], 0)}) for s in subtypes)

    def editing(self):
        """The dialog's data for ?type=<uid>, or None."""
        uid = self.request.form.get("type") or u""
        t = next((x for x in self.types() if x["uid"] == uid), None)
        if t is None:
            return None
        named = self._named(uid, t["subtypes"])
        rows = [dict(s, limits=named[s["id"]]["limits"],
                     on=[m for m, _l in t["profiles"] if m not in (s.get("off") or [])]) for s in t["subtypes"]]
        return dict(t, rows=rows)

    def _save(self):
        from six.moves.urllib.parse import quote_plus
        uid = self.request.form.get("type") or u""
        t = next((x for x in self.types() if x["uid"] == uid), None)
        back = u"%s/@@pfas-sample-subtypes" % self.portal_url()
        if t is None:
            self.request.response.redirect(back + u"?error=No+such+sample+type")
            return u""
        new, errors = ss.from_form(self.request.form, t["subtypes"], [m for m, _l in t["profiles"]],
                                   self._named(uid, t["subtypes"]))
        if errors:
            self.request.response.redirect(u"%s?type=%s&error=%s" % (back, uid, quote_plus(
                u" ".join(errors).encode("utf-8"))))
            return u""
        ss.save(t["obj"], new)
        self.request.response.redirect(back + u"?ok=Sub-types+saved")
        return u""

    def error_msg(self):
        return self.request.form.get("error") or u""

    def ok_msg(self):
        return self.request.form.get("ok") or u""
