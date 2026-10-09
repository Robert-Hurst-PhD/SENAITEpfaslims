# -*- coding: utf-8 -*-
"""@@pfas-homogenisation-setup: the lab's homogenisation methods and the
default for each matrix (core Sample Type). H2.

A method keeps its id across renames, so every sample naming it still does;
a method is retired, never deleted. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import homogenisation as hg
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action

GATES = {"save": TIER_CONFIG}


def rows_from_form(form):
    """[{"id", "title", "unit_required", "active"}] in index order from
    m__<n>__<field> names (existing rows and rows added with "+ Add")."""
    by = {}
    for k, v in (form or {}).items():
        k = u"%s" % k
        if not k.startswith(u"m__"):
            continue
        parts = k.split(u"__")
        if len(parts) != 3 or not parts[1].isdigit():
            continue
        by.setdefault(int(parts[1]), {})[parts[2]] = v
    out = []
    for i in sorted(by):
        r = by[i]
        out.append({"id": r.get("id") or u"", "title": r.get("title") or u"",
                    "unit_required": r.get("unit_required") == u"on",
                    "active": r.get("active") == u"on" or not r.get("id")})
    return out


class PFASHomogenisationSetupView(GateMixin, BrowserView):
    template = ViewPageTemplateFile("templates/homogenisation_setup.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors = []
        req = self.request
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, "save", GATES)
            if denied is not None:
                return denied
            portal = api.get_portal()
            methods, self.errors = hg.parse_methods(rows_from_form(req.form),
                                                    hg.load_methods(portal))
            if self.errors:
                return self.template()
            hg.save_methods(portal, methods)
            valid = set(m["id"] for m in methods) | set([hg.NONE_ID])
            for st in self._sample_types():
                mid = req.form.get(u"default__%s" % api.get_uid(st)) or u""
                hg.set_type_default(st, mid if mid in valid else u"")
            req.response.redirect(self.portal_url() + "/@@pfas-homogenisation-setup?saved=1")
            return ""
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def saved(self):
        return bool(self.request.form.get("saved"))

    def methods(self):
        return hg.load_methods(api.get_portal())

    def starter(self):
        """Names offered to type over when the list is empty; never saved
        unless the lab saves them."""
        return [] if self.methods() else list(hg.STARTER_TITLES)

    def _sample_types(self):
        brains = api.search({"portal_type": "SampleType", "is_active": True,
                             "sort_on": "sortable_title"}, "senaite_catalog_setup")
        return [api.get_object(b) for b in brains]

    def matrices(self):
        methods = self.methods()
        out = []
        for st in self._sample_types():
            cur = hg.type_default(st)
            out.append({"uid": api.get_uid(st), "title": api.get_title(st), "current": cur,
                        "choices": [(u"", u"No default")] + hg.choices(methods, cur)})
        return out
