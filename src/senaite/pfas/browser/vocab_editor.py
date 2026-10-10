# -*- coding: utf-8 -*-
"""@@pfas-vocabularies: the lab's editable lists (vocab_store).

One list at a time: relabel a term, withdraw it from new picks, or add one.
A term's key never changes and a term is never deleted, so every record
holding it keeps it. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import vocab_store as vs
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action

GATES = {"save": TIER_CONFIG}


def rows_from_form(form):
    """[{"key", "label", "active"}] from t__<n>__<field> names, in order."""
    by = {}
    for k, v in (form or {}).items():
        parts = (u"%s" % k).split(u"__")
        if len(parts) == 3 and parts[0] == u"t" and parts[1].isdigit():
            by.setdefault(int(parts[1]), {})[parts[2]] = v
    return [{"key": by[i].get("key") or u"", "label": by[i].get("label") or u"",
             "active": by[i].get("active") == u"on"} for i in sorted(by)]


class PFASVocabulariesView(GateMixin, BrowserView):
    template = ViewPageTemplateFile("templates/vocab_editor.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors = []
        req = self.request
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, "save", GATES)
            if denied is not None:
                return denied
            name = self.list_name()
            if name:
                portal = api.get_portal()
                data, self.errors = vs.edit(vs.get(portal), name, rows_from_form(req.form),
                                            req.form.get("new_label") or u"")
                if not self.errors:
                    vs.save(portal, data)
                    req.response.redirect("%s/@@pfas-vocabularies?list=%s&saved=1"
                                          % (self.portal_url(), name))
                    return ""
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def lists(self):
        return [(n, vs.LISTS[n][0]) for n in sorted(vs.LISTS, key=lambda n: vs.LISTS[n][0])]

    def list_name(self):
        # `tab` too: the Lab Settings console links a list as ?tab=<name>
        name = self.request.form.get("list") or self.request.form.get("tab") or u""
        return name if name in vs.LISTS else u""

    def title(self):
        return vs.LISTS[self.list_name()][0] if self.list_name() else u"Lists"

    def terms(self):
        return vs.terms(vs.get(api.get_portal()), self.list_name()) if self.list_name() else []

    def saved(self):
        return bool(self.request.form.get("saved"))
