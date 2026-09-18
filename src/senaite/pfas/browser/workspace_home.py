# -*- coding: utf-8 -*-
"""Role-aware workspace launcher."""
from __future__ import absolute_import, print_function, unicode_literals

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form


def _portal(context):
    return getToolByName(context, 'portal_url').getPortalObject()


class PFASWorkspaceHomeView(BrowserView):
    """Role-aware launcher — redirects to the user's default workspace."""

    def __call__(self):
        flatten_form(self.request)
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
            target = '{0}/@@pfas-data-review-home'.format(base)
        elif 'LabClerk' in roles:
            target = '{0}/@@pfas-bench'.format(base)
        elif 'Client' in roles:
            target = '{0}/@@pfas-track'.format(base)
        else:
            target = '{0}/@@pfas-sample-status'.format(base)

        return self.request.response.redirect(target)


class PFASQCManagementView(BrowserView):
    """QC Management workspace landing page — tile grid for the Manager/QAO role."""

    template = ViewPageTemplateFile("templates/pfas_qc_management.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def sections(self):
        base = _portal(self.context).absolute_url()
        return [
            {
                "url":   u"{0}/@@pfas-method-profiles".format(base),
                "icon":  u"⚙",
                "title": u"Method Profiles",
                "desc":  u"QC rules, recovery tiers, analyte factors per method",
            },
            {
                "url":   u"{0}/@@pfas-qc-rules".format(base),
                "icon":  u"☑",
                "title": u"QC Rules",
                "desc":  u"Toggle Westgard rules and set per-analyte acceptance limits",
            },
            {
                "url":   u"{0}/@@pfas-control-chart".format(base),
                "icon":  u"↗",
                "title": u"Control Charts",
                "desc":  u"QC control charts across all methods",
            },
            {
                "url":   u"{0}/@@pfas-calibrations".format(base),
                "icon":  u"◈",
                "title": u"Calibrations",
                "desc":  u"Review and approve calibration curve submissions",
            },
            {
                "url":   u"{0}/@@pfas-data-review".format(base),
                "icon":  u"✓",
                "title": u"Data Review",
                "desc":  u"Worksheets awaiting analyst sign-off or manager approval",
            },
            {
                "url":   u"{0}/@@pfas-deviations".format(base),
                "icon":  u"⚠",
                "title": u"Deviations / CARs",
                "desc":  u"Non-conformance tracking, root cause, corrective actions",
            },
            {
                "url":   u"{0}/@@pfas-facility-qc".format(base),
                "icon":  u"⌂",
                "title": u"Facility QC",
                "desc":  u"Environmental monitoring, balance and water verification",
            },
            {
                "url":   u"{0}/@@pfas-sop".format(base),
                "icon":  u"❐",
                "title": u"SOPs",
                "desc":  u"Standard operating procedures — revisions and sign-off",
            },
        ]


class PFASBenchHomeView(BrowserView):
    """Bench workspace landing page — tile grid for the Bench Chemist role."""

    template = ViewPageTemplateFile("templates/pfas_bench.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def sections(self):
        base = _portal(self.context).absolute_url()
        return [
            {
                "url":   u"{0}/@@pfas-reagents".format(base),
                "icon":  u"⚗",
                "title": u"Reagent Inventory",
                "desc":  u"Create reagent lots, track CoA, expiry, and storage location",
            },
            {
                "url":   u"{0}/@@pfas-prep-standards".format(base),
                "icon":  u"⚖",
                "title": u"Prepared Standards",
                "desc":  u"Prepared standards with parent-reagent traceability",
            },
            {
                "url":   u"{0}/@@pfas-logbook-batches".format(base),
                "icon":  u"✎",
                "title": u"Batch Logbooks",
                "desc":  u"Fill in and correct FM-ENV logbooks for a batch",
            },
            {
                "url":   u"{0}/@@pfas-sop".format(base),
                "icon":  u"❐",
                "title": u"SOPs",
                "desc":  u"Standard operating procedures — revisions and sign-off",
            },
            {
                "url":   u"{0}/@@pfas-deviations".format(base),
                "icon":  u"⚠",
                "title": u"Deviations / CARs",
                "desc":  u"Non-conformance tracking, root cause, corrective actions",
            },
        ]


class PFASDataReviewHomeView(BrowserView):
    """Data Review workspace landing page — tile grid for the Analyst/Verifier role."""

    template = ViewPageTemplateFile("templates/pfas_data_review_home.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def sections(self):
        base = _portal(self.context).absolute_url()
        return [
            {
                "url":   u"{0}/@@pfas-data-review".format(base),
                "icon":  u"✓",
                "title": u"Data Review",
                "desc":  u"Worksheets awaiting analyst sign-off or manager approval",
            },
            {
                "url":   u"{0}/@@pfas-deviations".format(base),
                "icon":  u"⚠",
                "title": u"Deviations / CARs",
                "desc":  u"Non-conformance tracking, root cause, corrective actions",
            },
            {
                "url":   u"{0}/@@pfas-control-chart".format(base),
                "icon":  u"↗",
                "title": u"Control Charts",
                "desc":  u"QC control charts across all methods",
            },
            {
                "url":   u"{0}/@@pfas-calibrations".format(base),
                "icon":  u"◈",
                "title": u"Calibrations",
                "desc":  u"Review and approve calibration curve submissions",
            },
        ]
