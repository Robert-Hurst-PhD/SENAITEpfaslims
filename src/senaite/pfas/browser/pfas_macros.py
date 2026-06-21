# -*- coding: utf-8 -*-
"""
PFAS shared page-chrome macros view.

Registered at @@pfas-macros.  All PFAS full-page templates access the
shared METAL macro via:

    metal:use-macro="context/@@pfas-macros/macros/page"

The macro defines slots:
  title          -- <title> element text (browser tab)
  head-extra     -- additional <head> content (scripts, page-specific <style>)
  header-title   -- <h1> inner content
  header-right   -- badge / back-link area to the right of the h1
  content        -- the main page body
  left-panel     -- left-panel nav (default: role-scoped via get_nav_items)

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


class PFASMacrosView(BrowserView):
    """Exposes pfas_macros.pt macros for use by other PFAS page templates."""

    _template = ViewPageTemplateFile("templates/pfas_macros.pt")

    @property
    def macros(self):
        return self._template.macros

    def portal_url(self):
        return self.context.portal_url.getPortalObject().absolute_url()

    def get_nav_items(self):
        """Return role-scoped left-panel nav items.

        Called via ``context/@@pfas-macros/get_nav_items`` in the macro so
        that traversal always lands on PFASMacrosView, not the calling view.
        Each entry is a dict with 'type' ('section' or 'item') plus keys
        appropriate to that type.
        """
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        base = portal.absolute_url()
        path_info = self.request.get('PATH_INFO', '')

        user = getSecurityManager().getUser()
        try:
            roles = list(user.getRolesInContext(portal))
        except Exception:
            roles = list(user.getRoles())

        def sec(title):
            return {'type': 'section', 'title': title}

        def itm(view_name, label, icon):
            url = '{0}/{1}'.format(base, view_name)
            return {
                'type': 'item',
                'url': url,
                'label': label,
                'icon': icon,
                'active': view_name in path_info,
            }

        is_manager = 'LabManager' in roles or 'Manager' in roles
        is_analyst = 'Analyst' in roles or 'Verifier' in roles
        is_clerk   = 'LabClerk' in roles

        items = [sec('PFAS Tools')]

        if is_manager or is_analyst:
            items.append(itm('@@pfas-method-profiles', 'Method Profiles', u'·'))
        if is_manager or is_analyst:
            items.append(itm('@@pfas-control-chart',   'Control Charts',  u'·'))
        if is_manager or is_analyst:
            items.append(itm('@@pfas-qc-rules',        'QC Rules',        u'·'))
        if is_manager or is_analyst:
            items.append(itm('@@pfas-calibrations',    'Calibrations',    u'·'))
        if is_manager or is_analyst or is_clerk:
            items.append(itm('@@pfas-sample-status',   'Batch Status',    u'·'))
        if is_manager:
            items.append(itm('@@pfas-import-studio',   'Import Studio',   u'·'))
        if is_manager or is_clerk:
            items.append(itm('@@pfas-reagents',        'Reagent Inventory', u'·'))
        if is_manager:
            items.append(itm('@@pfas-egad-batches',    'EGAD EDD',        u'·'))
        items.append(    itm('@@pfas-track',           'Sample Tracker',  u'·'))

        return items
