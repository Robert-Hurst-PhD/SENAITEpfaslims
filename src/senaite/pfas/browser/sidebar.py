# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core.browser.viewlets.sidebar import SidebarViewletManager
from senaite.pfas.browser.formutil import flatten_form


def _get_user_roles(context):
    """Return a list of the current user's roles in the portal context."""
    portal = getToolByName(context, 'portal_url').getPortalObject()
    user = getSecurityManager().getUser()
    try:
        roles = list(user.getRolesInContext(portal))
    except Exception:
        roles = list(user.getRoles())
    return roles


class PFASSidebarView(BrowserView):
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

    def portal_url(self):
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        return portal.absolute_url()

    def current_path(self):
        return self.request.get('PATH_INFO', '')

    def user_roles(self):
        return _get_user_roles(self.context)


class PFASSidebarManager(SidebarViewletManager):
    """Site-wide accordion sidebar — overrides core SidebarViewletManager
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

    def current_path(self):
        return self.request.get('PATH_INFO', '')

    def user_roles(self):
        return _get_user_roles(self.context)

    def render(self):
        if not self.available():
            return ''
        return self._sidebar_template()
