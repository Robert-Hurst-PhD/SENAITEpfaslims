# -*- coding: utf-8 -*-
"""@@pfas-settings-report: the method profile revision PDF -- every QC setting
of a method, how and where it is applied (settings_report.py builds it). Print and Issue revision on Method Profiles
use it; the page of its own was retired and a
plain visit goes to Method Profiles.

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
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import print_doc
from senaite.pfas import settings_report as sr
from senaite.pfas.browser.formutil import quote_text
from senaite.pfas.browser.perms import may_read_config, require_manager
from senaite.pfas.browser.perms import refuse
from senaite.pfas.browser.view_helpers import send_pdf

logger = logging.getLogger("senaite.pfas.settings_report")


def _shown_revision(rec):
    """A revision record (or status) as the report shows it: its number
    major.sub (`label`), and its issue stamp, stored on the server's clock
    (UTC), on the laboratory's; the stamp as stored while no zone
    converts."""
    from senaite.pfas import method_revisions as mr
    rec = dict(rec, label=rec.get("label") or mr.label(rec))
    at = rec.get("issued_at")
    return dict(rec, issued_at=print_doc.lab_or(at, at)) if at else rec


def issuing_revision(method, rev, label, at, by, reason):
    """The method as the revision being issued prints it: its revision line
    names that revision, issued now, and its issued revisions begin with
    it (the records hold it only once it is issued, after the print)."""
    issued = {"rev": rev, "label": label, "issued_at": at, "issued_by": by, "reason": reason or u""}
    out = dict(method, revision=dict(method.get("revision") or {}, unissued=False, **issued))
    out["revisions"] = [issued] + [r for r in method.get("revisions") or [] if r.get("rev") != rev]
    return out


class UnknownMethod(ValueError):
    """No profile is stored for the method: nothing to issue."""


class NothingToIssue(ValueError):
    """Nothing changed since the last revision, `label`."""

    def __init__(self, label):
        ValueError.__init__(self, u"nothing changed since Revision %s" % label)
        self.label = label


def issue_revision(portal, mid, who, reason, source=None):
    """Freeze `mid`'s settings report as its next revision, issued by `who`
    (the name the PDF and the record print) for `reason`; `source` names
    the run's processing change it came from (method_proposals), else None.
    The level follows from what changed since the last revision, never from
    the person issuing. Returns the record. Refused before anything is
    written: UnknownMethod, NothingToIssue, ImportError (WeasyPrint is not
    installed) and DesignedReportError (the issued design cannot print it);
    the caller aborts its transaction on any."""
    from senaite.pfas import method_revisions as mr
    from senaite.pfas.method_profile_store import raw_profile
    from senaite.pfas.qc.rules import method_toggles
    profile = raw_profile(portal, mid) if mid else {}
    if not mid or not profile:
        raise UnknownMethod(mid)
    recs = mr.records(portal, mid)
    toggles = method_toggles(profile, mid)
    fp = mr.fingerprint(profile, toggles)
    both = mr.fingerprints(profile, toggles)
    if recs and mr.status(recs, both)["unissued"] is False:
        raise NothingToIssue(mr.status(recs, both)["label"])
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    rev = mr.next_number(recs)
    nxt = mr.next_issue(mid, recs, profile, toggles)
    label = nxt["label"]
    reason = reason or u""
    shown_at = print_doc.lab_or(when, when)
    # the method's settings report, as the Issue button prints it
    view = PFASSettingsReportView(portal, portal.REQUEST)
    view.method_id = lambda: mid
    rep = view.report()
    rep["revision_label"] = view._label(None, {"label": label, "at": shown_at, "by": who}) + (
        u" \u2014 %s" % reason if reason else u"")
    rep["methods"] = [issuing_revision(m, rev, label, shown_at, who, reason) for m in rep["methods"]]
    pdf = view._render_pdf()
    rec = mr.issue(portal, mid, pdf, fp, who, when, reason, rev=rev, major=nxt["major"], sub=nxt["sub"],
                   snapshot=nxt["snapshot"], level=nxt["level"], changed=nxt["groups"], source=source)
    logger.info("method %s: revision %s (%s, %s) issued by %s", mid, label, rev, nxt["level"], who)
    return rec


class PFASSettingsReportView(ViewHelpers, BrowserView):

    print_template = ViewPageTemplateFile("templates/settings_report_print.pt")
    body_template = ViewPageTemplateFile("templates/settings_report_body.pt")

    def __call__(self):
        # a manager; the read-only inspector reads the revision PDFs by GET
        if not may_read_config(self.context, self.request):
            return refuse(self.request, "Forbidden")
        form = self.request.form
        if self.request.method == "POST" and not require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden")
        if self.request.method == "POST" and form.get("action") == "issue_revision":
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
            return self._issue()
        if form.get("method_id") and form.get("rev"):
            return self._issued_pdf()
        if form.get("format") == "pdf":
            return self._pdf()
        # the page itself is retired: the
        # Method Profile pages show the same settings; this view stays only
        # as the revision PDF behind Print / Issue on Method Profiles
        self.request.response.redirect(self.portal_url() + "/@@pfas-method-profiles")
        return u""

    # ── one method, its revisions ─────────────────────────────────────────

    def _control(self):
        """The control block: the report's title, the revision its label says
        (a DRAFT is never given a number), when it was generated and the
        fingerprint of the configuration it describes."""
        import re
        rep = self.report()
        label = rep.get("revision_label") or u""
        if label.startswith(u"DRAFT"):
            rev = u"DRAFT"
        else:
            found = re.search(r"Revision (\d+(?:\.\d+)?)", label)
            rev = found.group(1) if found else u""
        return {"doc_id": rep["title"], "revision": rev, "generated": rep["generated"],
                "user": rep["user"], "fingerprint": rep["fingerprint"]}

    def print_css(self):
        c = self._control()
        # this print has no design revision (an issued design prints through
        # designed_pdf instead): its foot line says the layout is built in, and
        # still names who printed it, when, and that a copy is uncontrolled
        return print_doc.document_css(c["doc_id"], c["revision"], c["user"], c["generated"],
                                      size="A4 landscape", margin="14mm 12mm 16mm",
                                      layout=print_doc.BUILT_IN_LAYOUT)

    def print_head(self):
        c = self._control()
        cells = [(u"Document", c["doc_id"]), (u"Revision", c["revision"]),
                 (u"Generated", c["generated"]), (u"Configuration", c["fingerprint"])]
        return print_doc.head_html(print_doc.print_settings(self.context),
                                   c["doc_id"], cells)

    def method_id(self):
        return (self.request.form.get("method_id") or "").strip()

    def _revision_info(self, mid, profile):
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.qc.rules import method_toggles
        recs = mr.records(api.get_portal(), mid)
        st = mr.status(recs, mr.fingerprints(profile, method_toggles(profile, mid)))
        return _shown_revision(st), [_shown_revision(r) for r in sorted(recs, key=lambda r: -r.get("rev", 0))]

    @staticmethod
    def section_parts(section):
        """A settings section as the tables it prints (settings_report.
        section_parts): a wide one in parts, none past the page's edge."""
        return sr.section_parts(section)

    @property
    def body_macros(self):
        return self.body_template.macros

    @staticmethod
    def _recorded_lots(portal, profiles, listed):
        """{lot id: the copy of its number and name the method's
        configuration history recorded} for each salt row's lot the
        inventory no longer lists (method_profile_sections.recorded_lots):
        the report names the lot a factor's CoA came from even when the row
        lost its own copy. Read only; {} when the history cannot be read."""
        from senaite.pfas import config_history
        from senaite.pfas import method_profile_sections as mps
        from senaite.pfas.browser.method_profiles import lots_named_by
        known = set(o.get("uid") for o in listed or [])
        out = {}
        for mid, p in sorted(profiles.items()):
            if not [u for u in lots_named_by([p]) if u and u not in known]:
                continue
            try:
                found = mps.recorded_lots(config_history.entries(
                    portal, store="method_profile", key=mid, limit=100000), p)
            except Exception:                               # noqa: BLE001
                logger.warning("configuration history of %s not read", mid, exc_info=True)
                continue
            for uid, copy_ in found.items():
                out.setdefault(uid, copy_)
        return out

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
        # the inventory's standard lots: a salt factor's CoA lot prints by
        # its name and lot number, as the method's page shows it
        from senaite.pfas.browser.method_profiles import lots_named_by, standard_lots
        from senaite.pfas.qc.rules import method_toggles
        only = self.method_id()
        profiles = dict((mid, raw_profile(portal, mid) or {}) for mid in sorted(list_method_ids(portal))
                        if not only or mid == only)
        env["standard_lots"] = standard_lots(portal, lots_named_by(profiles.values()))
        env["recorded_lots"] = self._recorded_lots(portal, profiles, env["standard_lots"])
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
               (u"Sign-off layout", ps.get("coa_signature_style"))]
        equipment = self._equipment()
        from senaite.pfas import report_tiers
        labels = dict((k, l) for k, l, _s in report_tiers.PARTS)
        tiers = [{"id": t.get("id"), "name": t.get("name"),
                  "parts": [labels.get(p.get("key"), p.get("key")) for p in t.get("parts") or []]}
                 for t in report_tiers.get_catalogue(portal)]
        user = api.get_current_user()
        self._report = {
            "title": (u"%s \u2014 QC settings" % methods[0]["name"]) if only and methods
                     else u"QC Settings Report",
            "revision_label": self._label(methods[0]["revision"]) if only and methods else u"",
            "generated": print_doc.now_label(),
            "user": (user.getProperty("fullname") or user.getId()) if user else u"",
            "fingerprint": sr.fingerprint(profiles, reg, ps,
                                          [p["specs"] for p in projects],
                                          equipment["config"]),
            "methods": methods,
            "limits": reg.get("limits") or [],
            "programs": reg.get("programs") or {},
            "projects": projects,
            "lab": [(k, v) for k, v in lab if v],
            "lab_name": ps.get("lab_name") or u"", "lab_address": ps.get("lab_address") or u"",
            # the Help entry listing every value's source, as the printed
            # report gives it
            "value_sources": u"%s/@@pfas-help?entry=value-sources" % portal.absolute_url(),
            "equipment": equipment,
            "report_tiers": tiers,
        }
        return self._report

    def _equipment(self):
        """Equipment for the report: the type obligations, how the
        system applies them, every instrument's state, and the facility
        defaults. Read with the same functions the Equipment pages use."""
        from senaite.pfas import equipment_report as er
        from senaite.pfas import facility_qc as fq
        from senaite.pfas.browser import equipment as eq
        portal = api.get_portal()
        types = []
        for b in api.search({"portal_type": "InstrumentType", "sort_on": "sortable_title"},
                            "senaite_catalog_setup"):
            t = api.get_object(b)
            types.append({"uid": api.get_uid(t), "title": api.safe_unicode(api.get_title(t)),
                          "req": eq.type_requirements(t)})
        insts = []
        for u in fq.list_units(active_only=False):
            cf = fq.calibration(u["id"], unit=u) if fq._requires_correction(u) else None
            st = None
            if cf and cf.get("study_id"):
                det = fq.get_study(cf["study_id"]) or {}
                st = {"study": det.get("study") or {},
                      "changes": len(fq.study_point_changes(cf["study_id"]))}
            ref = (eq.reference_check(st["study"].get("reference_uid"), st["study"].get("study_date"))
                   if st else None)
            insts.append({"unit": u, "due": eq.due_status(u), "correction": cf, "study": st,
                          "reference": ref})
        d = fq.get_facility_defaults(portal)
        defaults = [(u"Eye wash temperature range (\u00b0C)",
                     u"%s to %s" % (d.get("eyewash_temp_min"), d.get("eyewash_temp_max"))),
                    (u"Type 1 water, maximum conductivity (\u00b5S/cm)", d.get("water_conductivity_max")),
                    (u"Type 1 water, maximum TOC (ppb)", d.get("water_toc_max")),
                    (u"Temperature study tolerance per reading pair (\u00b0C)", d.get("study_tolerance"))]
        for kind, pts in sorted((d.get("balance_points") or {}).items()):
            defaults.append((u"Default weight points, %s (g)" % kind,
                             u", ".join(u"%s" % p[0] for p in pts)))
        return {"application": er.application(fq.STUDY_POINTS, fq.STUDY_MIN_DAYS),
                "types": er.type_rows(types), "instruments": er.instrument_rows(insts),
                "defaults": defaults, "config": er.config(types, insts)}

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
                    "name": prof.get("display_name") or mid,
                    "scopes": sorted(u"All matrices" if s == project_specs.ALL else s for s in scopes),
                    "departures": project_specs.departures(prof, eff, mid),
                    "stale": stale})
            out.append({"code": pj.get("project_code") or u"", "title": pj.get("title") or u"",
                        "client": pj.get("client_name") or u"", "qapp": pj.get("qapp_label") or u"",
                        "status": pj.get("status") or u"", "methods": per_method, "specs": specs})
        return out

    def _label(self, st, issuing=None):
        """What the PDF says about its own status. `issuing` {"label",
        "at", "by"}: the revision being issued."""
        if issuing:
            return u"Revision %(label)s \u2014 issued %(at)s by %(by)s" % issuing
        if st["rev"] is None:
            return u"DRAFT \u2014 no revision has been issued"
        if st["unissued"]:
            return u"DRAFT \u2014 changed since Revision %s (issued %s)" % (st["label"], st["issued_at"])
        return u"Current settings = Revision %s (issued %s by %s)" % (
            st["label"], st["issued_at"], st["issued_by"])

    def _render_pdf(self):
        # an issued design (Document Templates) is the settings report from then on
        from senaite.pfas import document_templates as dt
        from senaite.pfas import report_documents as rd
        from senaite.pfas.browser.report_designs import designed_pdf, issued_design
        data = rd.settings_data(self.report())
        design = issued_design("settings_report")
        if design is not None:
            # a heading prints only with something under it
            omit = rd.empty_fields(data, rd.SETTINGS_OMIT_EMPTY)
            if omit:
                design = dt.subset_design(design, omit)
            return designed_pdf("settings_report", data, design=design)
        html = self.print_template()
        from weasyprint import HTML
        return HTML(string=html).write_pdf()

    def _send(self, pdf, name):
        return send_pdf(self.request.response, pdf, name, inline=False)

    def _issued_pdf(self):
        """The frozen PDF of the revision `?rev=` names by its issue number:
        the file its record names, sent under its major.sub number."""
        from senaite.pfas import method_revisions as mr
        mid, rev = self.method_id(), self.request.form.get("rev")
        recs = mr.records(api.get_portal(), mid)
        try:
            rec = [r for r in recs if r.get("rev") == int(rev)][0]
            pdf = mr.read_pdf(mid, rec)
        except (ValueError, TypeError, IndexError, IOError, OSError):
            self.request.response.setStatus(404)
            return "No issued revision %s of %s." % (mr.revision_named(recs, rev), self.method_name(mid))
        return self._send(pdf, "%s-settings-rev%s.pdf" % (mid, mr.label(rec)))

    def _issue(self):
        """Freeze this method's settings report as its next revision."""
        mid = self.method_id()
        back = "%s/@@pfas-method-profiles" % self.portal_url()
        user = api.get_current_user()
        who = (user.getProperty("fullname") or user.getId()) if user else u""
        reason = (self.request.form.get("reason") or u"").strip()
        from senaite.pfas import method_revisions as mr
        from senaite.pfas import revision_level
        from senaite.pfas.browser.report_designs import DesignedReportError
        try:
            rec = issue_revision(api.get_portal(), mid, who, reason)
        except UnknownMethod:
            self.request.response.redirect(back + "?error=Unknown+method")
            return ""
        except NothingToIssue as exc:
            self.request.response.redirect(back + "?error=%s" % quote_text(
                u"%s: nothing changed since Revision %s" % (self.method_name(mid), exc.label)))
            return ""
        except ImportError:
            self.request.response.setStatus(501)
            return "PDF rendering (WeasyPrint) is not installed on this server."
        except (DesignedReportError, ValueError) as exc:
            # a ValueError: the revision's files refused (another issue of
            # the method in flight, or one issued already), said as the
            # proposal's countersign says it
            self.request.response.redirect(back + "?error=%s" % quote_text(u"%s: not issued. %s" % (mid, exc)))
            return ""
        why = revision_level.why(rec["changed"])
        self.request.response.redirect(back + "?ok=%s" % quote_text(
            u"%s Revision %s issued%s." % (mid, mr.label(rec), u": %s" % why if why else u"")))
        return ""

    def _pdf(self):
        from senaite.pfas.browser.report_designs import DesignedReportError
        try:
            pdf = self._render_pdf()
        except ImportError:
            self.request.response.setStatus(501)
            return "PDF rendering (WeasyPrint) is not installed on this server."
        except DesignedReportError as exc:
            self.request.response.setStatus(500)
            return u"%s" % exc
        name = "%s-settings-%s.pdf" % (self.method_id() or "pfas", print_doc.now_label("%Y%m%d-%H%M"))
        return self._send(pdf, name)


