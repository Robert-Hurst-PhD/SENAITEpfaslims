# -*- coding: utf-8 -*-
"""The reporting template page (@@pfas-report-template) and its preview
(@@pfas-report-template-preview): the certificate template as a controlled
document (senaite.pfas.report_templates).

The draft is the live configuration (Print Settings, each method's Reporting
tab, the layout files). A Manager previews it against a real sample, sees
what it changes against the issued revision, and issues it; certificates are
then drawn from the issued revision. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import hashlib
import logging
import os

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal
from senaite.pfas.browser.perms import refuse

try:
    from urllib import quote_plus
except ImportError:                                         # Python 3
    from urllib.parse import quote_plus

logger = logging.getLogger("senaite.pfas.browser.report_template")

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT_FILES = ("templates/reports/CertificateOfAnalysis.pt",
                "browser/templates/coa_sections.pt",
                "browser/templates/coa_attestation.pt",
                # how numbers are written is part of the certificate too: a
                # change here is an unissued change
                "coa_format.py", "rounding.py",
                # the surrogate / internal-standard sub-table's rows and words
                "coa_qc_standards.py")


def layout_hash():
    """The certificate layout as it is coded: a change to these files is an
    unissued change to the template."""
    h = hashlib.sha256()
    for rel in LAYOUT_FILES:
        try:
            with open(os.path.join(_PKG, rel), "rb") as fh:
                h.update(fh.read())
        except IOError:
            h.update(b"missing:" + rel.encode("utf-8"))
    return h.hexdigest()[:16]


def draft_snapshot(portal):
    from senaite.pfas.method_profile_store import get_profile, list_method_ids
    from senaite.pfas.print_settings import get_print_settings
    from senaite.pfas.report_templates import snapshot
    formats = dict((mid, get_profile(portal, mid).get("report_format") or {})
                   for mid in list_method_ids(portal))
    return snapshot(get_print_settings(portal), formats, layout_hash(),
                    designed=designed_draft(portal))


def designed_draft(portal):
    """The designed certificate's draft (Document Templates), or None when
    the lab has none or archived it."""
    from senaite.pfas import document_templates as dt
    entry = dt.load(portal).get(dt.KINDS["coa"]["single"])
    if not entry or entry.get("archived") or entry.get("kind") != "coa":
        return None
    return entry.get("draft")


class PFASReportTemplateView(BrowserView):

    template = ViewPageTemplateFile("templates/report_template.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST" and self.request.form.get("action") == "issue":
            return self._handle_issue()
        return self.template()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def portal_url(self):
        return self._portal().absolute_url()

    def draft_designed(self):
        """The next issue will carry a designed certificate (Document
        Templates): said on the page, also before any revision exists."""
        return designed_draft(self._portal()) is not None

    def has_designed(self):
        """A designed certificate in the draft or the issued revision."""
        from senaite.pfas import report_templates as rt
        portal = self._portal()
        return (designed_draft(portal) is not None
                or rt.designed_layout(rt.issued_snapshot(portal)[0]) is not None)

    def can_issue(self):
        return has_role_at_portal(self.context, MANAGER_ROLES)

    def state(self):
        from senaite.pfas import report_templates as rt
        portal = self._portal()
        recs = rt.records(portal)
        draft = draft_snapshot(portal)
        cur = rt.current(recs)
        st = rt.status(recs, rt.fingerprint(draft))
        st["changes"] = rt.changes((cur or {}).get("snapshot"), draft) if cur else []
        st["history"] = [dict((k, v) for k, v in r.items() if k != "snapshot")
                         for r in sorted(recs, key=lambda r: -r.get("rev", 0))]
        return st

    def preview_samples(self):
        """Verified or published samples to preview against."""
        out = []
        try:
            cat = getToolByName(self._portal(), "senaite_catalog_sample")
            brains = cat(portal_type="AnalysisRequest", review_state=["verified", "published"])
            for br in sorted(brains, key=lambda b: b.getId)[:60]:
                csid = getattr(br, "getClientSampleID", u"") or u""
                out.append({"uid": br.UID, "id": br.getId,
                            "label": u"%s \u00b7 %s" % (br.getId, csid) if csid else br.getId})
        except Exception as exc:                            # noqa: BLE001
            logger.warning("preview samples: %s", exc)
        return out

    def message(self):
        return self.request.form.get("ok") or u"", self.request.form.get("error") or u""

    def _handle_issue(self):
        url = self.portal_url() + "/@@pfas-report-template"
        if not self.can_issue():
            return refuse(self.request, u"Forbidden")
        note = (self.request.form.get("note") or u"").strip()
        if not note:
            self.request.response.redirect(url + "?error=" + quote_plus(
                u"Say what this revision changes.".encode("utf-8")))
            return u""
        from senaite.pfas import report_templates as rt
        portal = self._portal()
        draft = draft_snapshot(portal)
        cur = rt.current(rt.records(portal))
        if cur and cur.get("fingerprint") == rt.fingerprint(draft):
            self.request.response.redirect(url + "?error=" + quote_plus(
                u"Nothing to issue: the draft is the issued revision.".encode("utf-8")))
            return u""
        designed = rt.designed_layout(draft)
        if designed is not None:
            # a designed certificate states everything the standard one does
            from senaite.pfas import document_templates as dt
            problems = dt.validate("coa", designed)
            if problems:
                self.request.response.redirect(url + "?error=" + quote_plus(
                    (u"The designed certificate cannot be issued: " + u" ".join(problems)).encode("utf-8")))
                return u""
        who = getSecurityManager().getUser().getId()
        rec = rt.issue(portal, draft, who, datetime.datetime.utcnow().isoformat(), note)
        # the worker judges with the issued format: hand it over now
        try:
            from senaite.pfas.method_profile_store import export_profiles_to_file
            export_profiles_to_file(portal)
        except Exception as exc:                            # noqa: BLE001
            logger.error("report template: profiles not re-exported after issue: %s", exc)
        self.request.response.redirect(url + "?ok=" + quote_plus(
            (u"Revision %d issued; certificates now use it." % rec["rev"]).encode("utf-8")))
        return u""


class PFASReportTemplatePreviewView(BrowserView):
    """The certificate body for one sample, drawn from the DRAFT (?which=draft,
    the default) or the ISSUED revision -- what issuing would change, on real
    data. Not a certificate: no number, no publication. ?designed=1 shows the
    DESIGNED certificate as the renderer produces it, marked
    PREVIEW in its controlled stamp."""

    def _designed(self, sample, snap, rev):
        from senaite.pfas import report_templates as rt
        layout = rt.designed_layout(snap)
        if layout is None:
            return u"<p>This revision has no designed certificate: certificates use the standard layout.</p>"
        try:
            from senaite.pfas.browser import coa_document
            pdf = coa_document.render([sample], layout, snapshot=snap, rev=rev,
                                      request=self.request, preview=True)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("designed certificate preview: %s", exc)
            from cgi import escape
            return u"<p><strong>The designed certificate could not be produced:</strong> %s</p>" % escape(u"%s" % exc)
        self.request.response.setHeader("Content-Type", "application/pdf")
        self.request.response.setHeader("Content-Disposition", 'inline; filename="certificate-preview.pdf"')
        return pdf

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "text/html; charset=utf-8")
        from bika.lims import api
        from senaite.pfas.browser.coa_sections import PFASCoASectionsView
        from senaite.pfas import report_templates as rt
        sample = api.get_object_by_uid(self.request.form.get("uid") or u"", default=None)
        if sample is None:
            return u"<p>Choose a sample to preview.</p>"
        portal = api.get_portal()
        which = self.request.form.get("which") or u"draft"
        if which == u"issued":
            snap, rev = rt.issued_snapshot(portal)
            if snap is None:
                return u"<p>No revision has been issued yet.</p>"
        else:
            snap, rev = draft_snapshot(portal), None
        if self.request.form.get("designed"):
            return self._designed(sample, snap, rev)
        parts = []
        for section in ("header", "samples", "footer"):
            v = PFASCoASectionsView(sample, self.request)
            v.snapshot_override, v.snapshot_rev = snap, rev
            parts.append(v(collection=[sample], section=section))
        banner = (u"Preview of the DRAFT template (not issued)" if which != u"issued"
                  else u"Preview of issued revision %s" % rev)
        return (u"<!doctype html><html><head><meta charset='utf-8'><title>Preview</title>"
                u"<style>body{font-family:sans-serif;margin:16px;font-size:13px}"
                u".pv-banner{background:#fff3cd;padding:6px 10px;margin-bottom:12px;border-radius:4px}"
                u"table{border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:3px 6px}"
                u"</style></head><body><div class='pv-banner'>%s</div>%s</body></html>"
                % (banner, u"".join(parts)))
