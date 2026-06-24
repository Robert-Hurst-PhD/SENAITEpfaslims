# -*- coding: utf-8 -*-
"""Role-aware workspace launcher."""
from __future__ import absolute_import, print_function, unicode_literals

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView


def _portal(context):
    return getToolByName(context, 'portal_url').getPortalObject()


class PFASWorkspaceHomeView(BrowserView):
    """Role-aware launcher — redirects to the user's default workspace."""

    def __call__(self):
        portal = _portal(self.context)
        base = portal.absolute_url()

        user = getSecurityManager().getUser()
        try:
            roles = list(user.getRolesInContext(portal))
        except Exception:
            roles = list(user.getRoles())

        if 'LabManager' in roles or 'Manager' in roles:
            target = '{0}/@@pfas-method-profiles'.format(base)
        elif 'Analyst' in roles or 'Verifier' in roles:
            target = '{0}/@@pfas-data-review'.format(base)
        elif 'LabClerk' in roles:
            target = '{0}/@@pfas-reagents'.format(base)
        elif 'Client' in roles:
            target = '{0}/@@pfas-track'.format(base)
        else:
            target = '{0}/@@pfas-sample-status'.format(base)

        return self.request.response.redirect(target)


class PFASQCManagementView(BrowserView):
    """Legacy alias — redirects to Method Profiles."""

    def __call__(self):
        base = _portal(self.context).absolute_url()
        return self.request.response.redirect(
            '{0}/@@pfas-method-profiles'.format(base)
        )
