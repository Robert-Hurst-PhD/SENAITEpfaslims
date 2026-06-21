# -*- coding: utf-8 -*-
"""Role-aware workspace launcher and QC Management landing page."""
from __future__ import absolute_import, print_function, unicode_literals

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


def _portal(context):
    return getToolByName(context, 'portal_url').getPortalObject()


def _portal_base(context):
    return _portal(context).absolute_url()


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
            target = '{0}/@@pfas-qc-management'.format(base)
        elif 'Analyst' in roles or 'Verifier' in roles:
            target = '{0}/@@pfas-sample-status'.format(base)
        elif 'LabClerk' in roles:
            target = '{0}/@@pfas-reagents'.format(base)
        elif 'Client' in roles:
            target = '{0}/@@pfas-track'.format(base)
        else:
            target = '{0}/@@pfas-sample-status'.format(base)

        return self.request.response.redirect(target)


class PFASQCManagementView(BrowserView):
    """QC Management workspace landing page — default for LabManager/QAO."""

    template = ViewPageTemplateFile('templates/pfas_qc_management.pt')

    def __call__(self):
        return self.template()

    def portal_url(self):
        return _portal_base(self.context)

    def sections(self):
        base = _portal_base(self.context)
        return [
            {
                'title': 'Method Profiles',
                'desc':  'Configure QC acceptance criteria, spike levels, '
                         'and IS assignments per method',
                'url':   '{0}/@@pfas-method-profiles'.format(base),
                'icon':  u'▶',
            },
            {
                'title': 'QC Type Grid',
                'desc':  'Enable or disable each QC type (MB, LCS, LFSM…) '
                         'per method',
                'url':   '{0}/@@pfas-qc-type-grid'.format(base),
                'icon':  u'▣',
            },
            {
                'title': 'QC Rules',
                'desc':  'Toggle and tune individual Westgard / custom '
                         'rules for each method',
                'url':   '{0}/@@pfas-qc-rules'.format(base),
                'icon':  u'◆',
            },
            {
                'title': 'Control Charts',
                'desc':  'Levey-Jennings + Westgard multi-rule charts '
                         'per analyte',
                'url':   '{0}/@@pfas-control-chart'.format(base),
                'icon':  u'▤',
            },
            {
                'title': 'Method Wizard',
                'desc':  'Add a new method: matrices, analyte set, '
                         'surrogate map, QC rules, EIS limits',
                'url':   '{0}/@@pfas-method-wizard'.format(base),
                'icon':  u'✶',
            },
            {
                'title': 'Setup Reference Defs',
                'desc':  'Sync PFAS QC criteria to SENAITE Reference '
                         'Definitions',
                'url':   '{0}/@@pfas-setup-references'.format(base),
                'icon':  u'↺',
            },
        ]
