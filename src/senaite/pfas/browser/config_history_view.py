# -*- coding: utf-8 -*-
"""@@pfas-config-history: who changed which setting, when, from what to what
(config_history.py, R1). Revert applies one entry back through the owning
store's save function and is itself recorded. Revert is TIER_CONFIG.
Python 2.7 compatible.
"""
from __future__ import absolute_import

import json

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import config_history
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import GateMixin, TIER_CONFIG, deny_gated_action

HISTORY_GATES = {"revert": TIER_CONFIG}


def _show(value):
    if value is None:
        return u"(unset)"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True)
        return text if len(text) <= 160 else text[:157] + u"..."
    return u"%s" % value


class PFASConfigHistoryView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/config_history.pt")

    def __call__(self):
        flatten_form(self.request)
        self.message = None
        if self.request.method == "POST":
            action = self.request.form.get("action", "")
            denied = deny_gated_action(self.context, self.request, action, HISTORY_GATES)
            if denied is not None:
                return denied
            if action == "revert":
                # make sure the stores have registered (import side effect)
                import senaite.pfas.method_profile_store   # noqa: F401
                ok, msg = config_history.revert(api.get_portal(),
                                                self.request.form.get("eid", ""))
                # Redirect after the POST: the revert's own entry is written
                # at commit, after this response would have been rendered.
                import urllib
                self.request.response.redirect("%s/@@pfas-config-history?%s" % (
                    api.get_portal().absolute_url(),
                    urllib.urlencode({"ok": "1" if ok else "0",
                                      "msg": msg.encode("utf-8"),
                                      "store": self.store_filter(),
                                      "key": self.key_filter()})))
                return u""
        if self.request.form.get("msg"):
            self.message = {"ok": self.request.form.get("ok") == "1",
                            "text": self.request.form.get("msg")}
        return self.template()

    def store_filter(self):
        return self.request.form.get("store", "")

    def key_filter(self):
        return self.request.form.get("key", "")

    def stores(self):
        import senaite.pfas.method_profile_store   # noqa: F401
        return sorted((k, v["title"]) for k, v in config_history.STORES.items())

    def rows(self):
        import senaite.pfas.method_profile_store   # noqa: F401
        out = []
        for e in config_history.entries(api.get_portal(), self.store_filter() or None,
                                        self.key_filter() or None, limit=200):
            spec = config_history.STORES.get(e.get("store"))
            out.append({
                "id": e["id"], "at": e["at"], "who": e.get("who"),
                "store": spec["title"] if spec else e.get("store"),
                "key": e.get("key"), "label": e.get("label") or e.get("key"),
                "note": e.get("note"),
                "revertable": bool(spec) and not e.get("redacted"),
                "changes": [{"path": u" / ".join(u"%s" % p for p in c["path"]),
                             "before": _show(c["before"]), "after": _show(c["after"])}
                            for c in e.get("changes", [])],
            })
        return out
