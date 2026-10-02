# -*- coding: utf-8 -*-
"""Role-aware workspace launcher."""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.workspace_home")


def _portal(context):
    return getToolByName(context, 'portal_url').getPortalObject()


# Role -> landing, in precedence order: the ONE place that decides where a
# role lands (CLAUDE.md §4/§5). The launcher redirects with it and the sidebar
# pins it, so the two cannot disagree. Bench Chemist = LabClerk (decided
# 2026-09-30). `group` is the sidebar group opened by default for that role.
LANDINGS = (
    (("LabManager", "Manager"), u"QC Management", "@@pfas-qc-management", "pfas-sg-qc"),
    (("Analyst", "Verifier"),   u"Data Review",   "@@pfas-data-review-home", "pfas-sg-qc"),
    (("LabClerk",),             u"Bench",         "@@pfas-bench", "pfas-sg-bench"),
    (("Client",),               u"Sample Tracker", "@@pfas-track", ""),
)
DEFAULT_LANDING = (u"Sample Status", "@@pfas-sample-status", "pfas-sg-operations")


def landing_for(roles):
    """{'label', 'view', 'group'} of the landing for a set of roles."""
    roles = set(roles or ())
    for wanted, label, view, group in LANDINGS:
        if roles.intersection(wanted):
            return {"label": label, "view": view, "group": group}
    label, view, group = DEFAULT_LANDING
    return {"label": label, "view": view, "group": group}


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

        target = '{0}/{1}'.format(base, landing_for(roles)['view'])

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
                "title": u"Controlled Documents",
                "desc":  u"QAM, SOPs, job aids and supplemental — revisions and sign-off",
            },
        ]


class PFASBenchHomeView(BrowserView):
    """Bench landing: the extraction queue, what needs attention, then the
    Bench tiles (docs/BENCH_WORKFLOW_REVIEW.md phase 1)."""

    template = ViewPageTemplateFile("templates/pfas_bench.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def extractions(self):
        """Open batches with where their extraction stands, in progress first."""
        from senaite.pfas.browser.extraction_guide import extraction_queue
        try:
            return extraction_queue(_portal(self.context), self.request)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("bench extraction queue: %s", exc)
            return []

    def alerts(self):
        """Reagents and prepared standards that are expired, expiring within
        30 days, quarantined or low on stock."""
        from datetime import date
        from senaite.pfas.bench_queue import inventory_alerts
        from senaite.pfas.browser.bench_inventory import inventory_items
        items = inventory_items(_portal(self.context))
        return inventory_alerts(items, date.today())

    def balances_today(self):
        """[{name, serial, verified}] for each registered balance: was it
        verified today? None when no balance is registered."""
        from datetime import date
        try:
            from senaite.pfas import facility_qc as fq
            units = [u for u in fq.list_units() if (u.get("unit_type") or "") == "balance"]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("bench balances: %s", exc)
            return None
        if not units:
            return None
        today = date.today().strftime("%Y-%m-%d")
        return [{"name": u.get("name"), "serial": u.get("serial_number"),
                 "verified": bool(fq.get_balance_verification_for_date(u["id"], today))}
                for u in units]

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
                "title": u"Controlled Documents",
                "desc":  u"QAM, SOPs, job aids and supplemental — revisions and sign-off",
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
