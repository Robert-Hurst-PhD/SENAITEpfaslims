# -*- coding: utf-8 -*-
"""
Batch <-> Project assignment (@@... on a core Batch view).

This is the missing link in the project/QAPP delivery chain: project_ref.
set_project_uid(batch, uid) already triggers resolved_criteria_store.
export_resolved_criteria(), which writes the per-batch resolved-criteria
file the Py3 worker overlays at run time (see project_ref.py, resolved_
criteria_store.py). Nothing called set_project_uid -- a Project could be
created at @@pfas-projects but never attached to a batch. This viewlet is
that affordance, built the same way senaite.pfas.method-profile-link
bridges core Method -> PFAS method profile (see method_viewlet.py):
a viewlet registered on the core content interface, upgrade-safe, no core
template forked.

Two pieces:
  * PFASBatchProjectViewlet -- always renders (unlike the method-profile
    viewlet, which renders nothing for a Method with no profile): shows the
    batch's current Project + QAPP, or states plainly that none is assigned
    and the lab's internal quality system therefore applies. A manager
    additionally sees a dropdown to assign/clear. Render-only -- it never
    itself handles the POST (see CLAUDE.md Sec6A: a non-manager must not be
    shown a control they cannot use).
  * PFASBatchProjectAssignView -- the POST-only action target the viewlet's
    form submits to, registered as its own browser:page on the same
    interface (mirrors browser.projects.PFASProjectsView's own upsert/
    delete handlers: manager-gated server-side, CSRF-disabled the same way,
    redirect-after-POST back to the batch).

Never writes the project_uid annotation directly -- always through
project_ref.set_project_uid()/get_project_uid(), which is the one choke
point that keeps the resolved-criteria file in step with the link.

method_id/matrix for a NEW assignment are best-effort derived here (same
sources senaite.pfas.browser.run_builder / data_review already use for a
batch: the extraction-session/logbook-annotation chain via logbooks.
PFASLogbookIndexView.batch_method(), and the linked samples' SampleType for
matrix) and passed to set_project_uid() explicitly -- never guessed inside
project_ref itself (see its docstring). A batch with neither known (e.g. no
samples registered yet) still gets its project link recorded; it just does
not get a resolved-criteria file, which is the same safe "no file" state
every batch was in before this feature existed, and the viewlet says so
plainly rather than claiming success it did not achieve.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.app.layout.viewlets.common import ViewletBase

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import require_manager

logger = logging.getLogger("senaite.pfas.batch_project_viewlet")


def _portal(context):
    return getToolByName(context, "portal_url").getPortalObject()


def _batch_matrix(portal, batch):
    """The batch's matrix (SampleType title), derived from its linked
    samples -- same source and same unrestricted-search pattern
    run_builder.py's batch-linked-samples fallback and project_ref's own
    _get_by_uid() use. Returns "" (never raises) if no sample names a
    matrix -- a batch with no samples yet has no derivable matrix, which is
    not an error."""
    try:
        from bika.lims import api
        cat = getToolByName(portal, "senaite_catalog_sample")
        for br in cat.unrestrictedSearchResults(
                portal_type="AnalysisRequest", getBatchUID=api.get_uid(batch)):
            ar = br.getObject()
            st = ar.getSampleType()
            if st:
                return st.Title() or u""
    except Exception as exc:
        logger.warning("_batch_matrix failed for %r: %s", batch, exc)
    return u""


def _batch_method_id(batch, request):
    """Best-effort method id for `batch` -- delegates to the SAME resolver
    run_builder.py already uses for a batch context (extraction session >
    logbook 251/252 annotation > core Batch method), so this viewlet does
    not invent a second derivation path. Returns "" (never raises)."""
    try:
        from senaite.pfas.browser.logbooks import PFASLogbookIndexView
        return PFASLogbookIndexView(batch, request).batch_method() or u""
    except Exception as exc:
        logger.warning("_batch_method_id failed for %r: %s", batch, exc)
        return u""


def _project_display(portal, project_obj):
    """A plain dict for the template from a real PFASProject object --
    never from browser.projects._obj_to_dict()/_list_projects(), whose
    "uid" field is the object's FOLDER id, not its real Plone UID (verified
    live: they differ). project_ref.get_project() already resolved the real
    object via the real UID, so this just reads its fields directly."""
    from senaite.pfas.browser.projects import _client_name, _qapp_title
    return {
        "project_code": getattr(project_obj, "project_code", u"") or u"",
        "title": getattr(project_obj, "title", u"") or u"",
        "client_name": _client_name(portal, getattr(project_obj, "client_uid", u"")),
        "qapp_document_id": getattr(project_obj, "qapp_document_id", u"") or u"",
        "qapp_label": _qapp_title(portal, getattr(project_obj, "qapp_document_id", u"")),
    }


def _list_projects_for_select(portal):
    """[{uid, project_code, title, client_name}, ...] for every PFASProject,
    sorted by project_code -- keyed by the object's REAL Plone UID
    (bika.lims.api.get_uid), which is what project_ref.set_project_uid()/
    get_project() actually resolve through. Deliberately does not reuse
    browser.projects._list_projects(), whose "uid" field is the folder id,
    not the Plone UID (see module docstring)."""
    out = []
    try:
        from bika.lims import api
        from senaite.pfas.browser.projects import _get_projects_folder, _client_name
        folder = _get_projects_folder(portal)
    except Exception:
        return out
    for obj in folder.objectValues():
        if getattr(obj, "portal_type", "") != "PFASProject":
            continue
        try:
            uid = api.get_uid(obj)
        except Exception:
            continue
        out.append({
            "uid": uid,
            "project_code": obj.project_code or u"",
            "title": obj.title or u"",
            "client_name": _client_name(portal, obj.client_uid),
        })
    out.sort(key=lambda d: (d["project_code"] or u"").lower())
    return out


# ── Viewlet (render-only) ─────────────────────────────────────────────────────

class PFASBatchProjectViewlet(ViewletBase):
    """Shows (and, for a manager, lets you change) the Project linked to
    this Batch. Always renders -- unlike PFASMethodProfileViewlet, which
    renders nothing when there is no profile, this must state plainly that
    no project is assigned and the lab's internal quality system applies
    (CLAUDE.md task spec) -- silence is not an acceptable "none" state
    here."""

    index = ViewPageTemplateFile("templates/batch_project_viewlet.pt")

    def update(self):
        super(PFASBatchProjectViewlet, self).update()
        # Pre-initialise every attribute the template reads to a benign
        # "nothing assigned" state BEFORE the try -- a raise anywhere below
        # must never leave the template looking up a missing attribute (that
        # 500s the whole Batch page, and this viewlet is on every Batch).
        self.can_manage = False
        self.project = None
        self.project_uid = None
        self.projects = []
        self.assign_url = u""
        self.ok_msg = u""
        self.error_msg = u""
        try:
            self._update()
        except Exception as exc:
            logger.warning("batch project viewlet failed for %r: %s",
                            self.context, exc)

    def _update(self):
        portal = _portal(self.context)
        self.can_manage = require_manager(self.context, self.request)

        from senaite.pfas import project_ref
        self.project_uid = project_ref.get_project_uid(self.context)
        if self.project_uid:
            project_obj = project_ref.get_project(portal, self.context)
            if project_obj is not None:
                self.project = _project_display(portal, project_obj)
            # else: link points at a UID that no longer resolves -- self.
            # project stays None, self.project_uid stays truthy, so the
            # template can distinguish "none ever assigned" from "stale
            # link" and a manager can still clear it.

        if self.can_manage:
            self.projects = _list_projects_for_select(portal)

        self.assign_url = "{0}/@@pfas-batch-project-assign".format(
            self.context.absolute_url())
        self.ok_msg = (self.request.form.get("ok", "") or u"").replace("+", " ")
        self.error_msg = (self.request.form.get("error", "") or u"").replace("+", " ")

    def render(self):
        return self.index()


# ── Action target (manager-gated POST) ────────────────────────────────────────

class PFASBatchProjectAssignView(BrowserView):
    """POST-only assign/clear target for the viewlet's form. Never writes
    the project_uid annotation directly -- always through project_ref.
    set_project_uid(), matching the reverse-bridge viewlet's own "link out,
    do not reimplement" pattern one level down (here: call the ONE function
    that keeps the resolved-criteria file in step, do not touch the
    annotation ourselves)."""

    def __call__(self):
        flatten_form(self.request)
        if self.request.method != "POST":
            self.request.response.redirect(self.context.absolute_url())
            return u""

        if not require_manager(self.context, self.request):
            self.request.response.setStatus(403)
            return u"Forbidden"

        try:
            from plone.protect.interfaces import IDisableCSRFProtection
            from zope.interface import alsoProvides
            alsoProvides(self.request, IDisableCSRFProtection)
        except ImportError:
            pass

        action = (self.request.form.get("action") or u"").strip()
        portal = _portal(self.context)

        from senaite.pfas import project_ref

        if action == "clear":
            project_ref.set_project_uid(self.context, None)
            msg = "ok=Project+link+cleared"

        elif action == "assign":
            uid = (self.request.form.get("project_uid") or u"").strip()
            if not uid:
                msg = "error=Choose+a+project+first"
            else:
                method_id = _batch_method_id(self.context, self.request)
                matrix = _batch_matrix(portal, self.context)
                project_ref.set_project_uid(
                    self.context, uid, method_id=method_id, matrix=matrix)
                if method_id and matrix:
                    msg = "ok=Project+assigned+-+resolved+criteria+exported"
                else:
                    msg = ("ok=Project+assigned+-+resolved+criteria+NOT+"
                           "exported+%28method%2Fmatrix+not+yet+known+for+"
                           "this+batch%29")
        else:
            msg = "error=Unknown+action"

        self.request.response.redirect(
            "{0}?{1}".format(self.context.absolute_url(), msg))
        return u""
