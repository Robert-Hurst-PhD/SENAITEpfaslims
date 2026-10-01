# -*- coding: utf-8 -*-
"""@@pfas-settings-report: every QC setting in the system, how and where it is
applied, as a page and as a PDF (DECISIONS 2026-10-01; settings_report.py
builds it).

?format=pdf renders the same body through WeasyPrint (as the certificates
are), from a self-contained print document -- no stylesheet is fetched over
HTTP. The report is stamped with the date, the user and a fingerprint of the
configuration it was made from, so two copies can be told apart. Manager
only: it lists the whole configuration. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging
from datetime import datetime

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import settings_report as sr
from senaite.pfas.browser.perms import require_manager

logger = logging.getLogger("senaite.pfas.settings_report")


class PFASSettingsReportView(BrowserView):

    template = ViewPageTemplateFile("templates/settings_report.pt")
    print_template = ViewPageTemplateFile("templates/settings_report_print.pt")
    body_template = ViewPageTemplateFile("templates/settings_report_body.pt")

    def __call__(self):
        if not require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return "Forbidden"
        if self.request.form.get("format") == "pdf":
            return self._pdf()
        return self.template()

    @property
    def body_macros(self):
        return self.body_template.macros

    def portal_url(self):
        return api.get_portal().absolute_url()

    def report(self):
        if getattr(self, "_report", None) is not None:
            return self._report
        from senaite.pfas import project_specs, regulatory_limits
        from senaite.pfas.method_profile_store import list_method_ids, raw_profile
        from senaite.pfas.print_settings import get_print_settings
        portal = api.get_portal()
        env = project_specs.site_env()
        reg = regulatory_limits.get_store(portal)
        env["regulatory"] = reg
        try:
            from senaite.pfas.qc.rules import get_rules
            rules = get_rules() or {}
        except Exception as exc:                               # noqa: BLE001
            logger.warning("settings report: QC rules unavailable: %s", exc)
            rules = {}
        toggles = rules.get("method_rule_toggles") or {}
        profiles = dict((mid, raw_profile(portal, mid) or {}) for mid in sorted(list_method_ids(portal)))
        methods = [sr.method_report(p, env, toggles.get(mid)) for mid, p in sorted(profiles.items())]
        projects = self._projects(portal, profiles, env)
        ps = get_print_settings(portal)
        lab = [(u"Certificate statement, internal quality system", ps.get("coa_qs_internal")),
               (u"Certificate statement, under a QAPP", ps.get("coa_qs_qapp")),
               (u"Laboratory name on reports", ps.get("lab_name")),
               (u"Footer", ps.get("footer_text")),
               (u"Sign-off layout", ps.get("coa_signature_style"))]
        user = api.get_current_user()
        self._report = {
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "user": (user.getProperty("fullname") or user.getId()) if user else u"",
            "fingerprint": sr.fingerprint(profiles, reg, rules, ps,
                                          [p["specs"] for p in projects]),
            "methods": methods,
            "limits": reg.get("limits") or [],
            "programs": reg.get("programs") or {},
            "projects": projects,
            "lab": [(k, v) for k, v in lab if v],
            "global_rules": sorted((rules.get("global") or {}).items()),
        }
        return self._report

    def _projects(self, portal, profiles, env):
        from senaite.pfas import project_specs
        from senaite.pfas.browser.projects import _list_projects
        out = []
        for pj in _list_projects(portal):
            obj = project_specs.project_by_id(portal, pj["uid"])
            specs = project_specs.get_specs(obj)
            per_method = []
            for mid, scopes in sorted(specs.items()):
                prof = profiles.get(mid) or {}
                eff, stale = project_specs.effective(prof, scopes, None, env=env)
                per_method.append({
                    "method_id": mid,
                    "scopes": sorted(u"All matrices" if s == project_specs.ALL else s for s in scopes),
                    "departures": project_specs.departures(prof, eff, mid),
                    "stale": stale})
            out.append({"code": pj.get("project_code") or u"", "title": pj.get("title") or u"",
                        "client": pj.get("client_name") or u"", "qapp": pj.get("qapp_label") or u"",
                        "status": pj.get("status") or u"", "methods": per_method, "specs": specs})
        return out

    def _pdf(self):
        html = self.print_template()
        try:
            from weasyprint import HTML
        except ImportError:
            self.request.response.setStatus(501)
            return "PDF rendering (WeasyPrint) is not installed on this server."
        pdf = HTML(string=html).write_pdf()
        name = "pfas-settings-report-%s.pdf" % datetime.now().strftime("%Y%m%d-%H%M")
        resp = self.request.response
        resp.setHeader("Content-Type", "application/pdf")
        resp.setHeader("Content-Disposition", 'attachment; filename="%s"' % name)
        return pdf
