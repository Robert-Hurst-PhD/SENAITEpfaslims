# -*- coding: utf-8 -*-
"""@@pfas-search: one search for the whole site.

    ?q=...&format=json   the top bar's dropdown: a few results per group
    ?q=...               the full results page

Sources and who sees them: SENAITE's catalogs through senaite.app.spotlight
(already permission-filtered); the sidebar the user is shown (so pages follow
roles); and the PFAS stores -- method settings, equipment, lab settings,
regulatory limits, logbook templates -- each only when that user's sidebar
offers the page that owns it. Ranking and index entries: site_search.py.
Python 2.7.
"""
from __future__ import absolute_import

import json
import logging

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import site_search as ss
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.site_search")

DROPDOWN_PER_GROUP = 5
PAGE_PER_GROUP = 50


class PFASSiteSearchView(BrowserView):

    template = ViewPageTemplateFile("templates/site_search.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.form.get("format") == "json":
            self.request.response.setHeader("Content-Type", "application/json")
            if api.get_current_user() is None or api.get_current_user().getId() is None:
                # not signed in (a session that timed out): to the login page,
                # which the page script follows (pfas-topbar.js), not an
                # empty answer that looks like "nothing found"
                from zExceptions import Unauthorized
                raise Unauthorized("Please sign in.")
            return json.dumps({"q": self.query(), "groups": self._groups(DROPDOWN_PER_GROUP),
                               "more": "%s/@@pfas-search?q=%s" % (self.portal_url(),
                                                                  self._quoted())})
        return self.template()

    # ── data ────────────────────────────────────────────────────────────────

    def portal_url(self):
        return api.get_portal().absolute_url()

    def query(self):
        return (self.request.form.get("q") or u"").strip()[:200]

    def _quoted(self):
        try:
            from urllib import quote_plus
        except ImportError:                                 # pragma: no cover
            from urllib.parse import quote_plus
        q = self.query()
        return quote_plus(q.encode("utf-8") if not isinstance(q, bytes) else q)

    def results(self):
        return self._groups(PAGE_PER_GROUP)

    def _groups(self, per_group):
        q = self.query()
        if len(q) < 2:
            return []
        items = self._items(q)
        # "hits", not "items": in a page template g/items is the dict's method
        return [{"id": gid, "label": label,
                 "hits": [{"title": i.get("title"), "subtitle": i.get("subtitle") or u"",
                            "url": i.get("url")} for i in found]}
                for gid, label, found in ss.rank(items, q, per_group)]

    def _items(self, q):
        portal = api.get_portal()
        pages = self._pages()
        offered = u" ".join(p["url"] for p in pages)
        items = list(pages) + self._records()
        if "@@pfas-reagents" in offered or "@@pfas-prep-standards" in offered:
            items += self._inventory(portal, offered)
        if "@@pfas-equipment" in offered:
            items += self._equipment(portal)
        if "@@pfas-method-profiles" in offered:
            items += self._method_settings(portal)
        if "@@pfas-lab-settings" in offered:
            items += self._settings()
        if "@@pfas-regulatory-limits" in offered or "@@pfas-lab-settings" in offered:
            items += self._limits(portal)
        if "@@pfas-logbook-batches" in offered and self._is_manager():
            items += self._logbooks(portal)
        from senaite.pfas import help_dictionary
        items += ss.help_entries(help_dictionary.ENTRIES, self.portal_url() + "/@@pfas-help")
        return items

    def _is_manager(self):
        try:
            return self.context.restrictedTraverse("@@pfas-macros").is_manager_role()
        except Exception:                                   # noqa: BLE001
            return False

    def _pages(self):
        try:
            html = self.context.restrictedTraverse("@@pfas-macros").render_sidebar()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("search: sidebar: %s", exc)
            return []
        return ss.pages_from_sidebar(html)

    def _records(self):
        """SENAITE's catalogs, through its own Spotlight adapter (reads `q`
        from this request; results are permission-filtered by the catalogs)."""
        try:
            from senaite.app.spotlight.interfaces import ISpotlightSearchAdapter
            from zope.component import getMultiAdapter
            found = getMultiAdapter((self.context, self.request), ISpotlightSearchAdapter)()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("search: spotlight: %s", exc)
            return []
        from Products.CMFPlone.utils import safe_unicode
        out = []
        for raw in found.get("items") or []:
            # Spotlight returns UTF-8 byte strings under Python 2
            it = dict((k, safe_unicode(v) if isinstance(v, bytes) else v) for k, v in raw.items())
            out.append({"group": "records", "title": it.get("title_or_id") or u"",
                        # the parent says where it lives; Spotlight's description
                        # mostly repeats the title and the parent
                        "subtitle": it.get("parent_title") or u"",
                        "url": it.get("url"),
                        # Spotlight matched it on text we cannot see; never drop it
                        "keywords": [self.query()], "boost": 5})
        return out

    def _inventory(self, portal, offered):
        reagents, standards = [], []
        try:
            if "@@pfas-reagents" in offered:
                from senaite.pfas.browser.reagents import _list_reagents
                reagents = _list_reagents(portal)
            if "@@pfas-prep-standards" in offered:
                from senaite.pfas.browser.prepared_standards import _list
                standards = _list(portal)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("search: inventory: %s", exc)
        return ss.inventory_entries(reagents, standards, self.portal_url() + "/@@pfas-reagents",
                                    self.portal_url() + "/@@pfas-prep-standards")

    def _equipment(self, portal):
        from senaite.pfas import equipment_types as et
        from senaite.pfas import facility_qc as fq
        try:
            units = fq.list_units(active_only=False)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("search: equipment: %s", exc)
            return []
        out = ss.equipment_entries(units, self.portal_url() + "/@@pfas-equipment",
                                   self.portal_url() + "/@@pfas-equipment-settings",
                                   dict(et.KINDS))
        if self._is_manager():
            for b in api.search({"portal_type": "InstrumentType"}, "senaite_catalog_setup"):
                out.append({"group": "equipment", "title": api.get_title(b),
                            "subtitle": u"Equipment type", "keywords": [u"type", u"equipment"],
                            "url": self.portal_url() + "/@@pfas-equipment-types"})
        return out

    def _method_settings(self, portal):
        from senaite.pfas import config_forms as cf
        from senaite.pfas import method_profile_sections as mps
        from senaite.pfas.method_profile_store import list_method_ids, raw_profile
        out = []
        for mid in sorted(list_method_ids(portal)):
            try:
                p = raw_profile(portal, mid) or {}
                out += ss.method_settings(
                    mid, p.get("display_name") or mid,
                    "%s/@@pfas-method-profile-edit?method_id=%s" % (self.portal_url(), mid),
                    mps.SECTIONS, p, titles=mps._analyte_titles(p),
                    columns_of=lambda s, prof: cf._bound(s, prof).columns)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("search: method %s: %s", mid, exc)
        return out

    def _settings(self):
        try:
            from senaite.pfas import settings_adapters, settings_registry as sr
            settings_adapters.declare_all(api.get_portal())
            regs = sr.registered()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("search: settings: %s", exc)
            return []
        out = []
        for s in regs:
            url = "%s/@@%s" % (self.portal_url(), s.owner_view or "pfas-lab-settings")
            if getattr(s, "anchor", None):
                url += "#" + s.anchor
            out.append({"group": "settings", "title": s.label or s.key,
                        "subtitle": sr.GROUP_LABELS.get(s.group, s.group),
                        "url": url + ("" if "#" in url else "#") + "s=" + s.key,
                        "keywords": [s.key]})
        return out

    def _limits(self, portal):
        from senaite.pfas import regulatory_limits as rg
        store = rg.get_store(portal)
        return ss.limit_entries(store.get("limits") or [], store.get("programs") or {},
                                self.portal_url() + "/@@pfas-regulatory-limits")

    def _logbooks(self, portal):
        from senaite.pfas.browser import prep_logbooks as pl
        out = []
        for d in pl._list(portal):
            if d.get("status") == pl.STATUS_ARCHIVED:
                continue
            out.append({"group": "logbooks",
                        "title": u"%s %s" % (d.get("logbook_code") or u"", d.get("title") or u""),
                        "subtitle": u"Revision %s · %s" % (d.get("revision"), d.get("status")),
                        "url": self.portal_url() + "/@@pfas-prep-logbooks",
                        "keywords": [d.get("logbook_slug") or u""]})
        return out
