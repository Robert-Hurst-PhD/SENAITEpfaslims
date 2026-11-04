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
    if value in (u"", ""):
        return u"(empty)"
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
                from senaite.pfas.config_history_stores import register_all
                register_all()
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

    PAGE = 20
    WHEN = ((u"", u"All"), (u"24h", u"24 h"), (u"7d", u"7 days"), (u"30d", u"30 days"))

    def store_filter(self):
        return self.request.form.get("store", "")

    def when_filter(self):
        w = self.request.form.get("when", "")
        return w if w in [x[0] for x in self.WHEN] else u""

    def date_from(self):
        return (self.request.form.get("from") or u"").strip()[:10]

    def date_to(self):
        return (self.request.form.get("to") or u"").strip()[:10]

    def _window(self):
        """(since, until) in the stored "YYYY-MM-DD HH:MM:SS" (UTC) form; From
        and To are the laboratory's days."""
        from datetime import datetime, timedelta
        since, until = config_history.lab_day_window(self.date_from(), self.date_to())
        hours = {u"24h": 24, u"7d": 24 * 7, u"30d": 24 * 30}.get(self.when_filter())
        if hours:
            since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        return since, until

    def page(self):
        try:
            return max(1, int(self.request.form.get("page") or 1))
        except (TypeError, ValueError):
            return 1

    def total(self):
        since, until = self._window()
        return config_history.count(api.get_portal(), self.store_filter() or None,
                                    self.key_filter() or None, since=since, until=until)

    def paging(self):
        """{"first", "last", "total", "page", "pages", "prev", "next"}: the
        page of 20 shown, its place in the whole and the neighbours' URLs."""
        import urllib
        total, page = self.total(), self.page()
        pages = max(1, (total + self.PAGE - 1) // self.PAGE)
        page = min(page, pages)
        base = dict((k, v) for k, v in (("store", self.store_filter()), ("key", self.key_filter()),
                                        ("when", self.when_filter()), ("from", self.date_from()),
                                        ("to", self.date_to())) if v)

        def url(p):
            q = dict(base, page=p)
            return u"%s/@@pfas-config-history?%s" % (api.get_portal().absolute_url(),
                                                     urllib.urlencode(dict((k, (u"%s" % v).encode("utf-8")) for k, v in q.items())))
        first = (page - 1) * self.PAGE + 1 if total else 0
        return {"first": first, "last": min(total, page * self.PAGE), "total": total,
                "page": page, "pages": pages,
                "prev": url(page - 1) if page > 1 else None,
                "next": url(page + 1) if page < pages else None}

    def when_links(self):
        """The When strip: each choice as a link carrying the other filters."""
        import urllib
        out = []
        for value, label in self.WHEN:
            q = dict((k, v) for k, v in (("store", self.store_filter()), ("key", self.key_filter()),
                                         ("when", value)) if v)
            out.append({"label": label, "on": value == self.when_filter(),
                        "url": u"%s/@@pfas-config-history?%s" % (
                            api.get_portal().absolute_url(),
                            urllib.urlencode(dict((k, (u"%s" % v).encode("utf-8")) for k, v in q.items())))})
        return out

    def zone_active(self):
        """True when times are shown on the laboratory's clock: a screen
        then names no zone; while unset, the When column says UTC."""
        from senaite.pfas import lab_time
        return lab_time.active()

    def key_filter(self):
        return self.request.form.get("key", "")

    def stores(self):
        from senaite.pfas.config_history_stores import register_all
        register_all()
        names = dict((k, v["title"]) for k, v in config_history.STORES.items())
        names.update(config_history.TITLES)
        return sorted(names.items(), key=lambda kv: kv[1])

    def rows(self):
        from senaite.pfas.config_history_stores import register_all
        register_all()
        out = []
        since, until = self._window()
        for e in config_history.entries(api.get_portal(), self.store_filter() or None,
                                        self.key_filter() or None, limit=self.PAGE,
                                        since=since, until=until,
                                        offset=(self.paging()["page"] - 1) * self.PAGE):
            spec = config_history.STORES.get(e.get("store"))
            out.append({
                "id": e["id"], "at": config_history.shown_at(e["at"]), "who": e.get("who"),
                "store": spec["title"] if spec else config_history.TITLES.get(e.get("store"), e.get("store")),
                "key": e.get("key"), "label": e.get("label") or e.get("key"),
                "note": u"; ".join(x for x in (
                    (e.get("action") or u"").capitalize(),
                    u"Reason: %s" % e["reason"] if e.get("reason") else u"",
                    e.get("note") or u"") if x),
                "revertable": bool(spec) and not e.get("redacted"),
                "changes": [{"path": u" / ".join(u"%s" % p for p in c["path"]),
                             "before": _show(c["before"]), "after": _show(c["after"])}
                            for c in e.get("changes", [])],
            })
        return out
