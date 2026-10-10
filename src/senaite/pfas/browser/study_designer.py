# -*- coding: utf-8 -*-
"""@@pfas-study-designer: the lab designs a study template from generic
elements (study_templates.py) with form controls -- no study is coded.

    (list)             the templates; "New template"; Edit / Delete each
    ?id=ST-0001        one template: its fields, its elements, Add element,
                       Remove each, Save

Managers change templates; everyone else reads them. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import study_templates as st
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action

GATES = dict((a, TIER_CONFIG) for a in ("new", "save", "add", "remove", "delete"))


class PFASStudyDesignerView(GateMixin, BrowserView):
    template = ViewPageTemplateFile("templates/study_designer.pt")

    def __call__(self):
        flatten_form(self.request)
        self.errors, self.message = [], u""
        req = self.request
        if req.method == "POST":
            action = req.form.get("action") or u""
            if action.startswith(u"remove:"):
                action, self._remove_id = u"remove", action.split(u":", 1)[1]
            denied = deny_gated_action(self.context, req, action, GATES)
            if denied is not None:
                return denied
            try:
                from plone.protect import CheckAuthenticator
                CheckAuthenticator(req)
            except ImportError:
                pass
            handler = getattr(self, "_" + action, None) if action in GATES else None
            if handler is not None:
                redirect = handler()
                if redirect:
                    req.response.redirect(redirect)
                    return u""
        return self.template()

    # ── reading ────────────────────────────────────────────────────────────
    def portal_url(self):
        return api.get_portal().absolute_url()

    def templates(self):
        if not hasattr(self, "_templates"):
            self._templates = st.load(api.get_portal())
        return self._templates

    def current(self):
        return st.find(self.templates(), self.request.form.get("id") or u"")

    def methods(self):
        from senaite.pfas.method_profile_store import list_method_ids
        return list_method_ids(api.get_portal())

    def matrices(self, method_id):
        from senaite.pfas.method_profile_store import get_profile
        return list((get_profile(api.get_portal(), method_id) or {}).get("supported_matrices") or [])

    def qc_types(self, method_id):
        """The method profile's QC types: a replicates element's limits come
        from one of them (qc_tiers), never typed here."""
        from senaite.pfas.method_profile_store import get_profile
        qa = (get_profile(api.get_portal(), method_id) or {}).get("qc_acceptance") or {}
        return sorted(qa)

    def types(self):
        return st.TYPES

    def levels_text(self, el):
        return st.levels_text(el.get("levels"))

    def problems(self):
        t = self.current()
        return st.problems(t, self.qc_types(t.get("method"))) if t else []

    def fmt(self, v):
        return u"" if v is None else (u"%g" % v if isinstance(v, float) else u"%s" % v)

    # ── changing (manager) ─────────────────────────────────────────────────
    def _url(self, tid=u"", msg=u""):
        url = u"%s/@@pfas-study-designer" % self.portal_url()
        if tid:
            url += u"?id=%s" % tid
        if msg:
            url += (u"&" if tid else u"?") + u"saved=1"
        return url

    def _store(self, templates):
        st.save(api.get_portal(), templates)

    def _new(self):
        f = self.request.form
        name = (f.get("t__name") or u"").strip()
        if not name:
            self.errors.append(u"Name the template.")
            return None
        templates = self.templates()
        t = {"id": st.next_id(templates), "name": name, "method": f.get("t__method") or u"",
             "matrix": f.get("t__matrix") or u"", "elements": []}
        templates.append(t)
        self._store(templates)
        return self._url(t["id"])

    def _save(self, then=None):
        t = self.current()
        if t is None:
            self.errors.append(u"No such template.")
            return None
        new, bad = st.apply_form(t, self.request.form)
        if bad:
            self.errors.extend(bad)
            return None
        if then:
            new = then(new)
        templates = [new if x.get("id") == t["id"] else x for x in self.templates()]
        self._store(templates)
        return self._url(t["id"], u"saved")

    def _add(self):
        etype = self.request.form.get("new_type") or u""
        if etype not in st.TYPE_LABELS:
            self.errors.append(u"Choose the kind of element to add.")
            return None

        def add(t):
            t.setdefault("elements", []).append(
                st.new_element(etype, [e["id"] for e in t.get("elements") or []]))
            return t
        return self._save(add)

    def _remove(self):
        eid = getattr(self, "_remove_id", u"")

        def remove(t):
            t["elements"] = [e for e in t.get("elements") or [] if e.get("id") != eid]
            return t
        return self._save(remove)

    def _delete(self):
        tid = self.request.form.get("id") or u""
        self._store([t for t in self.templates() if t.get("id") != tid])
        return self._url()
