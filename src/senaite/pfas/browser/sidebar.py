# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core.browser.viewlets.sidebar import SidebarViewletManager
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.workspace_home import landing_for
from senaite.pfas.browser.sidebar_pins import get_pins
import json


def _get_user_roles(context):
    """Return a list of the current user's roles in the portal context."""
    portal = getToolByName(context, 'portal_url').getPortalObject()
    user = getSecurityManager().getUser()
    try:
        roles = list(user.getRolesInContext(portal))
    except Exception:
        roles = list(user.getRoles())
    return roles


def request_here(request, portal_url):
    """(path under the site, {query name: value}) of the page asked for."""
    from senaite.pfas import page_groups as pg
    url = request.get("ACTUAL_URL") or request.get("URL", "")
    purl = portal_url.rstrip("/")
    path = url[len(purl):] if url.startswith(purl) else url
    return path, pg._query(request.get("QUERY_STRING", ""))


def sidebar_nav(context, request, portal_url):
    """The rail and the panel for this request, as page_groups.nav_model
    gives them: the person's roles, their landing's section and their pins.
    PFAS pages and core pages draw the sidebar from this one call."""
    from senaite.pfas import page_groups as pg
    roles = _get_user_roles(context)
    path, query = request_here(request, portal_url)
    return pg.nav_model(roles, path, query, landing_for(roles)["group"], get_pins(context))


def sidebar_pins_json(nav):
    """The pins Home lists in `nav` (sidebar_nav's model), as JSON for the
    <nav>: the rows the pins view answers with (sidebar_pins.pins_for), read
    from the model the page already drew, not resolved again."""
    from senaite.pfas import page_groups as pg
    return json.dumps([s for s in nav["sections"] if s["id"] == pg.HOME["id"]][0]["pins"])


class PFASSidebarView(ViewHelpers, BrowserView):
    """Direct HTTP access to the sidebar fragment (for debugging/AJAX).

    The canonical rendering path is:
      - Core pages:  PFASSidebarManager.render() calls _sidebar_template()
      - PFAS pages:  context/@@pfas-macros/render_sidebar calls _sidebar_template()
    Both call ViewPageTemplateFile directly (not via __call__) so Plone's
    response transform pipeline does not add the <!DOCTYPE html> envelope.
    """
    _sidebar_template = ViewPageTemplateFile('templates/pfas_sidebar.pt')

    def __call__(self):
        flatten_form(self.request)
        content = self._sidebar_template()
        # Plone/Chameleon wraps BrowserView top-level output in <!DOCTYPE><html><body>.
        # Strip it to return just the <nav> fragment.
        start = content.find('<nav')
        end = content.rfind('</nav>') + 6
        if start >= 0 and end > start:
            return content[start:end]
        return content

    def nav(self):
        return sidebar_nav(self.context, self.request, self.portal_url())

    def pins_json(self, nav):
        return sidebar_pins_json(nav)


class PFASNavPagesView(BrowserView):
    """GET @@pfas-nav-pages: the pages the signed-in person may open from the
    navigation, as JSON {"pages": page_groups.pages, "sections": [{"id",
    "label"}]}, the labels of the sections those pages name. The audit tools
    walk it, not the panel's markup. It reads only: any other method is
    refused and nothing is stored. Staff only, by the client wall
    (perms.keep_clients_out)."""

    def __call__(self):
        from senaite.pfas import page_groups as pg
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if self.request.get("REQUEST_METHOD", "GET") != "GET":
            resp.setStatus(405)
            resp.setHeader("Allow", "GET")
            return json.dumps({"error": "This address answers GET only."})
        roles = _get_user_roles(self.context)
        return json.dumps({
            "pages": pg.pages(roles),
            "sections": [{"id": s["id"], "label": s["label"]} for s in pg.sections(roles)],
        })


class PFASSidebarManager(SidebarViewletManager):
    """The rail and the section panel on core pages: overrides core's SidebarViewletManager
    on ISenaitePFASLayer via adapter specificity.

    Renders pfas_sidebar.pt directly (not via a BrowserView __call__) so the
    output is a clean HTML fragment without Plone's <!DOCTYPE html> envelope.

    Upgrade note: check SidebarViewletManager.available() on senaite.core
    upgrades — only that and render() are in our call chain.
    """
    _sidebar_template = ViewPageTemplateFile('templates/pfas_sidebar.pt')

    def portal_url(self):
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        return portal.absolute_url()

    def nav(self):
        return sidebar_nav(self.context, self.request, self.portal_url())

    def pins_json(self, nav):
        return sidebar_pins_json(nav)

    def render(self):
        if not self.available():
            return ''
        return self._sidebar_template()
