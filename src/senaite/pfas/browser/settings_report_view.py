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
        form = self.request.form
        if self.request.method == "POST" and form.get("action") == "issue_revision":
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            return self._issue()
        if form.get("method_id") and form.get("rev"):
            return self._issued_pdf()
        if form.get("format") == "pdf":
            return self._pdf()
        return self.template()

    # ── one method, its revisions ─────────────────────────────────────────

    def method_id(self):
        return (self.request.form.get("method_id") or "").strip()

    def _revision_info(self, mid, profile):
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.qc.rules import method_toggles
        recs = mr.records(api.get_portal(), mid)
        st = mr.status(recs, mr.fingerprint(profile, method_toggles(profile, mid)))
        return st, sorted(recs, key=lambda r: -r.get("rev", 0))

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
        from senaite.pfas.qc.rules import method_toggles
        only = self.method_id()
        profiles = dict((mid, raw_profile(portal, mid) or {}) for mid in sorted(list_method_ids(portal))
                        if not only or mid == only)
        methods = []
        for mid, p in sorted(profiles.items()):
            m = sr.method_report(p, env, method_toggles(p, mid))
            m["revision"], m["revisions"] = self._revision_info(mid, p)
            methods.append(m)
        projects = self._projects(portal, profiles, env)
        if only:
            mats = set(m for p in profiles.values() for m in p.get("supported_matrices") or [])
            reg = dict(reg, limits=[l for l in reg.get("limits") or []
                                    if mats & set(l.get("matrices") or [])])
            projects = [pj for pj in projects if pj["methods"]]
        ps = get_print_settings(portal)
        lab = [(u"Certificate statement, internal quality system", ps.get("coa_qs_internal")),
               (u"Certificate statement, under a QAPP", ps.get("coa_qs_qapp")),
               (u"Laboratory name on reports", ps.get("lab_name")),
               (u"Footer", ps.get("footer_text")),
               (u"Sign-off layout", ps.get("coa_signature_style"))]
        user = api.get_current_user()
        self._report = {
            "title": (u"%s \u2014 QC settings" % methods[0]["name"]) if only and methods
                     else u"QC Settings Report",
            "revision_label": self._label(methods[0]["revision"]) if only and methods else u"",
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "user": (user.getProperty("fullname") or user.getId()) if user else u"",
            "fingerprint": sr.fingerprint(profiles, reg, ps,
                                          [p["specs"] for p in projects]),
            "methods": methods,
            "limits": reg.get("limits") or [],
            "programs": reg.get("programs") or {},
            "projects": projects,
            "lab": [(k, v) for k, v in lab if v],
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

    def _label(self, st, issuing=None):
        """What the PDF says about its own status."""
        if issuing:
            return u"Revision %(rev)s \u2014 issued %(at)s by %(by)s" % issuing
        if st["rev"] is None:
            return u"DRAFT \u2014 no revision has been issued"
        if st["unissued"]:
            return u"DRAFT \u2014 changed since Revision %s (issued %s)" % (st["rev"], st["issued_at"])
        return u"Current settings = Revision %s (issued %s by %s)" % (
            st["rev"], st["issued_at"], st["issued_by"])

    def _render_pdf(self):
        html = self.print_template()
        from weasyprint import HTML
        return HTML(string=html).write_pdf()

    def _send(self, pdf, name):
        resp = self.request.response
        resp.setHeader("Content-Type", "application/pdf")
        resp.setHeader("Content-Disposition", 'attachment; filename="%s"' % name)
        return pdf

    def _issued_pdf(self):
        from senaite.pfas import method_revisions as mr
        mid, rev = self.method_id(), self.request.form.get("rev")
        try:
            rev = int(rev)
            pdf = mr.read_pdf(mid, rev)
        except (ValueError, IOError, OSError):
            self.request.response.setStatus(404)
            return "No issued revision %s of %s." % (rev, mid)
        return self._send(pdf, "%s-settings-rev%d.pdf" % (mid, rev))

    def _issue(self):
        """Freeze this method's settings report as its next revision."""
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.method_profile_store import raw_profile
        portal = api.get_portal()
        mid = self.method_id()
        back = "%s/@@pfas-method-profiles" % self.portal_url()
        profile = raw_profile(portal, mid)
        if not mid or not profile:
            self.request.response.redirect(back + "?error=Unknown+method")
            return ""
        from senaite.pfas.qc.rules import method_toggles
        recs = mr.records(portal, mid)
        fp = mr.fingerprint(profile, method_toggles(profile, mid))
        if recs and mr.status(recs, fp)["unissued"] is False:
            self.request.response.redirect(back + "?error=%s" % _q(
                u"%s: nothing changed since Revision %s" % (mid, mr.status(recs, fp)["rev"])))
            return ""
        user = api.get_current_user()
        who = (user.getProperty("fullname") or user.getId()) if user else u""
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        rev = mr.next_number(recs)
        reason = (self.request.form.get("reason") or u"").strip()
        self.report()["revision_label"] = self._label(None, {"rev": rev, "at": when, "by": who}) + (
            u" \u2014 %s" % reason if reason else u"")
        try:
            pdf = self._render_pdf()
        except ImportError:
            self.request.response.setStatus(501)
            return "PDF rendering (WeasyPrint) is not installed on this server."
        mr.issue(portal, mid, pdf, fp, who, when, reason, rev=rev)
        logger.info("method %s: revision %s issued by %s", mid, rev, who)
        self.request.response.redirect(back + "?ok=%s" % _q(u"%s Revision %s issued." % (mid, rev)))
        return ""

    def _pdf(self):
        html = self.print_template()
        try:
            from weasyprint import HTML
        except ImportError:
            self.request.response.setStatus(501)
            return "PDF rendering (WeasyPrint) is not installed on this server."
        pdf = HTML(string=html).write_pdf()
        name = "%s-settings-%s.pdf" % (self.method_id() or "pfas", datetime.now().strftime("%Y%m%d-%H%M"))
        resp = self.request.response
        resp.setHeader("Content-Type", "application/pdf")
        resp.setHeader("Content-Disposition", 'attachment; filename="%s"' % name)
        return pdf


def _q(text):
    try:
        from urllib import quote
    except ImportError:                       # pragma: no cover
        from urllib.parse import quote
    return quote((u"%s" % text).encode("utf-8"))
