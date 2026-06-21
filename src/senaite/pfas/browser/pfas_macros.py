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

        if 'LabManager' in roles or 'Manager' in roles:
            return [
                sec('QC Management'),
                itm('@@pfas-qc-management', 'Overview', u'⌂'),
                itm('@@pfas-method-profiles', 'Method Profiles', u'▶'),
                itm('@@pfas-qc-type-grid', 'QC Type Grid', u'▣'),
                itm('@@pfas-qc-rules', 'QC Rules', u'◆'),
                itm('@@pfas-control-chart', 'Control Charts', u'▤'),
                sec('Setup'),
                itm('@@pfas-method-wizard', 'Method Wizard', u'✶'),
                itm('@@pfas-setup-references', 'Setup Refs', u'↺'),
                sec('Reporting'),
                itm('@@pfas-egad-config', 'EGAD Config', u'▼'),
                itm('@@pfas-egad-batches', 'Batch EDDs', u'⬇'),
            ]
        if 'Analyst' in roles or 'Verifier' in roles:
            return [
                sec('Data Review'),
                itm('@@pfas-sample-status', 'Batch Status', u'▶'),
                itm('@@pfas-control-chart', 'Control Charts', u'▤'),
                itm('@@pfas-calibrations', 'Calibrations', u'◇'),
            ]
        if 'LabClerk' in roles:
            return [
                sec('Bench'),
                itm('@@pfas-reagents', 'Reagents', u'▶'),
                itm('@@pfas-logbook-admin', 'Logbooks', u'▷'),
                itm('@@pfas-extraction-guide', 'Extraction Guide', u'▷'),
            ]
        return [
            sec('Tools'),
            itm('@@pfas-track', 'Sample Tracker', u'▶'),
        ]
