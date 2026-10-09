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
# role lands. The launcher redirects with it and the sidebar
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

    def attention(self):
        """What needs a manager's action (attention.items): the downstream
        effects of configuration, gathered here. A source that cannot be read
        is reported, never silently dropped."""
        from senaite.pfas import attention
        facts = {}
        portal = _portal(self.context)
        try:
            from senaite.pfas import report_templates as rt
            from senaite.pfas.browser.report_template import draft_snapshot
            facts["template"] = rt.status(rt.records(portal), rt.fingerprint(draft_snapshot(portal)))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("attention: reporting template: %s", exc)
        held = {}
        try:
            from bika.lims import api
            from senaite.pfas.browser.coa_sections import qc_standards_state
            from senaite.pfas.coa_qc_standards import BLOCKS_PUBLISHING
            # verified only: a published sample can no longer be held, and
            # re-checking every one made the Manager's landing slower with
            # each certificate issued
            for b in api.search({"portal_type": "AnalysisRequest",
                                 "review_state": "verified"}, "senaite_catalog_sample"):
                sample = api.get_object(b)
                try:
                    state = qc_standards_state(sample)
                except ValueError:
                    state = "method"
                except Exception:                           # noqa: BLE001
                    state = "error"
                if state in BLOCKS_PUBLISHING or state in ("method", "error"):
                    held.setdefault(state, []).append(api.get_id(sample))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("attention: held samples: %s", exc)
            held["error"] = [u"(the sample list could not be read)"]
        facts["held"] = held
        try:
            from senaite.pfas.edd_store import get_edd_profiles
            from senaite.pfas.edd_store import profile_qualifier_dict as get_profile_qualifier_dict
            from senaite.pfas.qc_qualification import FAILURE_TYPES
            codes = [u"N.D."] + sorted(set(c for _k, _l, _d, c in FAILURE_TYPES if c))
            missing = {}
            for pid, prof in sorted(get_edd_profiles(portal).items()):
                mapped = get_profile_qualifier_dict(prof)
                gap = [c for c in codes if not mapped.get(c)]
                if gap:
                    missing[prof.get("name") or prof.get("title") or pid] = gap
            facts["edd_missing"] = missing
        except Exception as exc:                            # noqa: BLE001
            logger.warning("attention: EDD profiles: %s", exc)
        try:
            from senaite.pfas import regulatory_limits
            facts["unverified"] = len([l for l in regulatory_limits.get_store(portal).get("limits") or []
                                       if not l.get("verified")])
        except Exception as exc:                            # noqa: BLE001
            logger.warning("attention: regulatory limits: %s", exc)
        try:
            from senaite.pfas import method_revisions as mr
            from senaite.pfas.method_profile_store import list_method_ids, raw_profile
            from senaite.pfas.qc.rules import method_toggles
            changed = []
            for mid in sorted(list_method_ids(portal)):
                recs = mr.records(portal, mid)
                prof = raw_profile(portal, mid) or {}
                if recs and mr.status(recs, mr.fingerprint(prof, method_toggles(prof, mid)))["unissued"]:
                    changed.append(prof.get("display_name") or mid)
            facts["methods_changed"] = changed
        except Exception as exc:                            # noqa: BLE001
            logger.warning("attention: method revisions: %s", exc)
        base = portal.absolute_url()
        out = attention.items(facts)
        for it in out:
            it["actions"] = [{"label": l, "url": "%s/%s" % (base, p)} for l, p in it["actions"]]
        return out

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
                "title": u"Calibration Archive",
                "desc":  u"Every run's curves; a run's curve is approved in Data Review",
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
                "title": u"Equipment & daily checks",
                "desc":  u"Temperatures, balances, pipettes, water, eye wash; what is due",
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
    Bench tiles (phase 1)."""

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

    def run_requests(self):
        """Open dilution / re-injection requests from review, on the open
        extraction batches: the bench is told here."""
        from bika.lims import api
        from senaite.pfas import extraction_batch
        out = []
        try:
            for brain in api.search({"portal_type": "Worksheet", "review_state": "open"},
                                    "senaite_catalog_worksheet"):
                ws = api.get_object(brain)
                for r in extraction_batch.load_requests(ws):
                    if r.get("status") == u"open":
                        out.append(dict(r, worksheet=ws.getId(),
                                        url=u"%s/@@pfas-extraction-batch" % ws.absolute_url()))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("bench run requests: %s", exc)
        return out

    def alerts(self):
        """Reagents and prepared standards that are expired, expiring within
        30 days, quarantined or low on stock."""
        from datetime import date
        from senaite.pfas.bench_queue import inventory_alerts
        from senaite.pfas.browser.bench_inventory import inventory_items
        items = inventory_items(_portal(self.context))
        return inventory_alerts(items, date.today())

    def awaiting_homogenisation(self):
        """Received samples with a method requested and no record (H-P3)."""
        from bika.lims import api
        from senaite.pfas import homogenisation as hg
        n = 0
        try:
            for brain in api.search({"portal_type": "AnalysisRequest",
                                     "review_state": "sample_received"},
                                    "senaite_catalog_sample"):
                s = api.get_object(brain)
                if hg.awaiting(hg.sample_request(s), hg.load_records(s)):
                    n += 1
        except Exception as exc:                            # noqa: BLE001
            logger.warning("homogenisation count: %s", exc)
        return n

    def balances_today(self):
        """[{name, serial, verified}] for each registered balance: was it
        verified today? None when no balance is registered."""
        from datetime import date
        try:
            from senaite.pfas import facility_qc as fq
            # balance_analytical / balance_prep (facility_qc.UNIT_TYPES): an
            # equality test against "balance" never matched a registered unit
            units = [u for u in fq.list_units()
                     if (u.get("unit_type") or "").startswith("balance")]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("bench balances: %s", exc)
            return None
        if not units:
            return None
        today = date.today().strftime("%Y-%m-%d")
        return [{"name": u.get("name"), "serial": u.get("serial_number"),
                 "verified": fq.balance_verified_on(u["id"], today)[0]}
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
                "url":   u"{0}/@@pfas-homogenisation".format(base),
                "icon":  u"⚙",
                "title": u"Homogenisation",
                "desc":  u"{0} sample(s) awaiting homogenisation".format(self.awaiting_homogenisation()),
            },
            {
                "url":   u"{0}/@@pfas-logbook-batches".format(base),
                "icon":  u"✎",
                "title": u"Logbooks",
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
                "title": u"Calibration Archive",
                "desc":  u"Every run's curves; a run's curve is approved in Data Review",
            },
        ]
