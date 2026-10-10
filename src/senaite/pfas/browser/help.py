# -*- coding: utf-8 -*-
"""@@pfas-help: the central Help dictionary (help_dictionary.py).

One entry per concept: what it is, where it is set, who may change it and
what it affects downstream; lists read from the system's own registries.
Pages link here with a "?" button (pfas_macros "help"). Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import help_dictionary as hd


def _roles(who):
    """The roles behind a permission tier, read from browser/perms."""
    from senaite.pfas.browser import perms
    roles = getattr(perms, "_TIER_ROLES", {}).get(who)
    return sorted(roles) if roles else []


def help_lists():
    """{list name: [(term, detail)]} -- generated, never typed."""
    from senaite.pfas import coa_qc_standards as q
    from senaite.pfas import doc_fields
    from senaite.pfas import report_format
    from senaite.pfas.qc import rules
    from senaite.pfas.qc_qualification import FAILURE_TYPES
    out = {}
    out["report_format_settings"] = [
        (label, u", ".join(c[1] for c in choices) if choices else u"free text")
        for _k, label, choices, _d in report_format.SETTINGS]
    out["rule_switches"] = [(r.get("label") or r.get("key"), r.get("note") or u"")
                            for r in rules.RULE_LIBRARY]
    out["qualification_codes"] = [
        (label, (u"code %s" % code if code else u"no code") + u"; " + (
            u"may be released qualified" if disp == "qualify" else u"blocks release"))
        for _k, label, disp, code in FAILURE_TYPES]
    out["doc_categories"] = [(c, u"") for c in doc_fields.CATEGORIES]
    out["qc_statuses"] = [(v, u"") for v in (q.STATUS["within"], q.STATUS["outside"],
                                              u"Outside (guidance only)", q.STATUS["no criterion"])]
    out["publish_holds"] = [
        (u"Method not identified", u"the reported analyses carry no method, or different ones"),
        (u"No reporting template issued", u"a manager issues the first revision"),
        (u"No laboratory address", u"a manager enters it in Print Settings"),
        (u"Run stored before verdicts were kept", q.LEGACY),
        (u"Run judged before rounding applied", q.UNROUNDED),
        (u"Rounding rule changed since the run", q.RULE_CHANGED),
        (u"Nothing judged for the injection", q.UNJUDGED)]
    return out


def _slug(title):
    return u"".join(c if c.isalnum() else u"-" for c in title.lower()).strip(u"-")


class PFASHelpView(BrowserView):
    """Tabs in the order the lab works (help_dictionary.GROUPS), an overview
    first; each tab lists its entries beside the one being read; the search
    is the site's top search (site_search.help_entries). ?entry=<id> opens
    that entry on its tab (the pages' "?" buttons)."""

    template = ViewPageTemplateFile("templates/help.pt")
    OVERVIEW = u"overview"

    def __call__(self):
        from senaite.pfas.browser.formutil import flatten_form
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def current_entry(self):
        eid = self.request.form.get("entry") or u""
        return hd.entry(eid) if eid else None

    def active_tab(self):
        e = self.current_entry()
        if e is not None:
            return _slug(e["group"])
        tab = self.request.form.get("tab") or self.OVERVIEW
        return tab if tab in [t["slug"] for t in self.tabs()] else self.OVERVIEW

    def tabs(self):
        out = [{"slug": self.OVERVIEW, "title": u"How it fits"}]
        for g, entries in hd.grouped():
            out.append({"slug": _slug(g), "title": g, "count": len(entries)})
        for t in out:
            t["url"] = u"%s/@@pfas-help?tab=%s" % (self.portal_url(), t["slug"])
        return out

    def _row(self, e, lists):
        return {"id": e["id"], "term": e["term"], "text": e["text"], "tab": e["group"],
                "url": u"%s/@@pfas-help?entry=%s" % (self.portal_url(), e["id"]),
                "where": [{"label": l, "url": "%s/%s" % (self.portal_url(), path)}
                          for l, path in e["where"]],
                "who": hd.WHO[e["who"]], "roles": _roles(e["who"]),
                "effects": [label for label, _p, _m in e["effects"]],
                "lists": [lists[n] for n in e.get("lists") or () if n in lists]}

    def tab_view(self):
        """{"title", "intro", "entries": [{id, term, url, active}], "entry"}
        for the active tab (None on the overview)."""
        slug = self.active_tab()
        for g, entries in hd.grouped():
            if _slug(g) != slug:
                continue
            current = self.current_entry() or (entries[0] if entries else None)
            return {"title": g, "intro": hd.GROUP_INTROS.get(g, u""),
                    "entries": [{"id": e["id"], "term": e["term"],
                                 "url": u"%s/@@pfas-help?entry=%s" % (self.portal_url(), e["id"]),
                                 "active": current is not None and e["id"] == current["id"]}
                                for e in entries],
                    "entry": self._row(current, help_lists()) if current else None}
        return None

    def workflow(self):
        """The overview: the lab's order of work, each step's entries."""
        out = []
        for i, (title, line, ids) in enumerate(hd.WORKFLOW):
            out.append({"n": i + 1, "title": title, "line": line,
                        "entries": [{"term": hd.entry(x)["term"],
                                     "url": u"%s/@@pfas-help?entry=%s" % (self.portal_url(), x)}
                                    for x in ids if hd.entry(x)]})
        return out
