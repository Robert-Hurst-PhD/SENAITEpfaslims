# -*- coding: utf-8 -*-
"""
PFAS Projects management (@@pfas-projects).

A Project is the entity that carries a client's QAPP and links it to
batches (see senaite.pfas.content.project, senaite.pfas.project_ref). This
view is the CRUD-over-a-portal-folder management UI for it, mirroring
senaite.pfas.browser.reagents: Projects are stored as first-class Dexterity
content objects in portal/pfas_projects/, one per UUID-keyed id.

Two selectors replace what would otherwise be free-text ids:
  - Client: real SENAITE Clients (portal_type="Client"), stored as UID.
    Resolved back to a name for display -- a raw UID is never shown.
  - QAPP: controlled documents whose doc_type is "QAPP" (see
    senaite.pfas.browser.sop_documents.DOC_TYPES), stored as the document
    id. Deliberately NOT filtered by client -- a QAPP is client-owned but
    reusable across clients (DECISIONS.md 2026-09-20); an explicit "none"
    option covers a project with no QAPP on file yet.

Viewing follows the surrounding management views (zope2.View, same as
reagents.py) -- any authenticated user who can reach the page can see the
list. Creating and editing are manager-only (senaite.pfas.browser.perms.
require_manager), enforced both server-side (403 on an unauthorised POST,
matching prep_logbooks.py) and in the template (the create/edit controls
are not rendered for a non-manager, per CLAUDE.md §6A).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging
import uuid
from datetime import datetime

from zope.event import notify
from zope.lifecycleevent import ObjectModifiedEvent

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import require_manager
from senaite.pfas.content.project import STATUS_ACTIVE, STATUS_CLOSED

logger = logging.getLogger("senaite.pfas.browser.projects")

ALL_STATUSES = [
    (STATUS_ACTIVE, "Active"),
    (STATUS_CLOSED, "Closed"),
]


# ── Date helpers ─────────────────────────────────────────────────────────────

def _date_to_str(d):
    if not d:
        return u""
    try:
        return d.strftime("%Y-%m-%d")
    except AttributeError:
        return unicode(d)[:10] if d else u""


def _str_to_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ── Content-object store helpers ──────────────────────────────────────────────

def _get_projects_folder(portal):
    """Return the pfas_projects Folder content object.

    Raises RuntimeError if not found -- caller should handle gracefully.
    """
    folder = portal.get("pfas_projects")
    if folder is None:
        raise RuntimeError(
            "pfas_projects folder not found. Reinstall senaite.pfas to create it."
        )
    return folder


def _client_name(portal, uid):
    """Resolve a Client UID to its real name. Never returns the raw UID --
    an unresolvable link (deleted/stale UID) reads as "(unknown client)"."""
    if not uid:
        return u""
    try:
        from bika.lims import api as bika_api
        obj = bika_api.get_object_by_uid(uid, default=None)
        if obj is not None:
            return obj.Title() or u""
    except Exception:
        pass
    return u"(unknown client)"


def _list_clients(portal):
    """[(uid, title), ...] for every real SENAITE Client, sorted by title.

    Clients are indexed in senaite_catalog_client (verified live against the
    running site -- portal_catalog/senaite_catalog_setup return nothing for
    portal_type="Client" in this SENAITE version). Falls back to a direct
    walk of the clients folder if the catalog lookup fails for any reason,
    so a catalog-name change in a future SENAITE version degrades instead
    of silently emptying the selector.
    """
    out = []
    try:
        from bika.lims import api as bika_api
        brains = bika_api.search(
            {"portal_type": "Client"}, catalog="senaite_catalog_client")
        out = [(b.UID, b.Title) for b in brains]
    except Exception:
        out = []
    if not out:
        try:
            from bika.lims import api as bika_api
            folder = portal.get("clients")
            if folder is not None:
                for obj in folder.objectValues():
                    if getattr(obj, "portal_type", "") == "Client":
                        out.append((bika_api.get_uid(obj), obj.Title() or u""))
        except Exception:
            pass
    out.sort(key=lambda pair: (pair[1] or u"").lower())
    return out


def _list_qapp_docs(portal):
    """[{sop_id, title}, ...] for every non-archived controlled document
    whose doc_type is QAPP. Deliberately not scoped to any client -- a QAPP
    is reusable across clients (DECISIONS.md 2026-09-20)."""
    out = []
    try:
        from senaite.pfas.browser.sop_documents import (
            _get_registry, _entry_doc_type,
        )
        for entry in _get_registry(portal):
            if entry.get("status") == "archived":
                continue
            if _entry_doc_type(entry) != "QAPP":
                continue
            out.append({
                "sop_id": entry.get("sop_id", ""),
                "title": entry.get("title", ""),
            })
    except Exception:
        logger.exception("_list_qapp_docs failed")
    out.sort(key=lambda d: d["sop_id"])
    return out


def _qapp_title(portal, doc_id):
    """Display label for a stored qapp_document_id, or '' if unset/unknown."""
    if not doc_id:
        return u""
    for d in _list_qapp_docs(portal):
        if d["sop_id"] == doc_id:
            return u"{0} — {1}".format(d["sop_id"], d["title"])
    return doc_id


def _obj_to_dict(obj, portal):
    return {
        "uid": obj.getId(),
        "title": obj.title or u"",
        "client_uid": obj.client_uid or u"",
        "client_name": _client_name(portal, obj.client_uid),
        "project_code": obj.project_code or u"",
        "qapp_document_id": obj.qapp_document_id or u"",
        "qapp_label": _qapp_title(portal, obj.qapp_document_id),
        "start_date": _date_to_str(obj.start_date),
        "end_date": _date_to_str(obj.end_date),
        "status": obj.status or STATUS_ACTIVE,
        "notes": obj.notes or u"",
    }


def _populate_obj(obj, data):
    obj.title = data.get("title") or u""
    obj.client_uid = data.get("client_uid") or u""
    obj.project_code = data.get("project_code") or u""
    obj.qapp_document_id = data.get("qapp_document_id") or None
    obj.start_date = _str_to_date(data.get("start_date"))
    obj.end_date = _str_to_date(data.get("end_date"))
    obj.status = data.get("status") or STATUS_ACTIVE
    obj.notes = data.get("notes") or u""


def _save_project(portal, data):
    """Upsert a PFASProject content object. Returns the object's Zope id."""
    folder = _get_projects_folder(portal)
    uid = (data.get("uid") or u"").strip() or None

    if uid and uid in folder:
        obj = folder[uid]
    else:
        uid = uid or uuid.uuid4().hex
        title = data.get("title") or u"Project"
        folder.invokeFactory("PFASProject", id=uid, title=title)
        obj = folder[uid]

    _populate_obj(obj, data)
    try:
        obj.reindexObject()
    except Exception:
        pass
    try:
        notify(ObjectModifiedEvent(obj))
    except Exception:
        pass
    return uid


def _get_project(portal, uid):
    try:
        folder = _get_projects_folder(portal)
    except RuntimeError:
        return None
    obj = folder.get(uid)
    if obj is None:
        return None
    return _obj_to_dict(obj, portal)


def _delete_project(portal, uid):
    try:
        folder = _get_projects_folder(portal)
    except RuntimeError:
        return False
    if uid in folder:
        folder.manage_delObjects([uid])
        return True
    return False


def _list_projects(portal):
    try:
        folder = _get_projects_folder(portal)
    except RuntimeError:
        return []
    out = []
    for obj in folder.objectValues():
        if obj.portal_type != "PFASProject":
            continue
        out.append(_obj_to_dict(obj, portal))
    out.sort(key=lambda d: (d.get("project_code") or u"").lower())
    return out


# ── View ──────────────────────────────────────────────────────────────────────

class PFASProjectsView(BrowserView):
    """Projects management -- list, create, edit."""

    template = ViewPageTemplateFile("templates/projects.pt")

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            # Creating/editing a Project is lab configuration (CLAUDE.md
            # §4) -- only a manager may write it. Checked ahead of the
            # CSRF-disable below so an unauthorised POST never reaches it.
            if action in ("add", "edit", "delete"):
                if not require_manager(self.context, self.request):
                    self.request.response.setStatus(403)
                    return "Forbidden"
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            if action in ("add", "edit"):
                return self._handle_upsert()
            if action == "delete":
                return self._handle_delete()
        return self.template()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _self_url(self):
        return "{0}/@@pfas-projects".format(self._portal().absolute_url())

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def can_manage(self):
        return require_manager(self.context, self.request)

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    # ── Template data ─────────────────────────────────────────────────────────

    def projects(self):
        return _list_projects(self._portal())

    def clients(self):
        return [{"uid": uid, "title": title}
                for uid, title in _list_clients(self._portal())]

    def qapp_docs(self):
        return _list_qapp_docs(self._portal())

    def all_statuses(self):
        return ALL_STATUSES

    def edit_uid(self):
        return self.request.form.get("edit_uid", "")

    def edit_project(self):
        """The project dict being edited, or None for a fresh add form."""
        uid = self.edit_uid()
        if not uid:
            return None
        return _get_project(self._portal(), uid)

    # ── Action handlers ───────────────────────────────────────────────────────

    def _handle_upsert(self):
        f = self.request.form
        data = {
            "uid": (f.get("uid") or "").strip() or None,
            "title": (f.get("title") or "").strip(),
            "client_uid": (f.get("client_uid") or "").strip(),
            "project_code": (f.get("project_code") or "").strip(),
            "qapp_document_id": (f.get("qapp_document_id") or "").strip(),
            "start_date": (f.get("start_date") or "").strip(),
            "end_date": (f.get("end_date") or "").strip(),
            "status": (f.get("status") or STATUS_ACTIVE).strip(),
            "notes": (f.get("notes") or "").strip(),
        }
        if not data["title"] or not data["project_code"] or not data["client_uid"]:
            url = "{0}?error=Project+Name%2C+Project+Code+and+Client+are+required".format(
                self._self_url())
            return self._redirect(url)
        uid = _save_project(self._portal(), data)
        url = "{0}?ok=Project+saved+%28{1}%29".format(
            self._self_url(), data["project_code"].replace(" ", "+"))
        return self._redirect(url)

    def _handle_delete(self):
        uid = (self.request.form.get("uid") or "").strip()
        if _delete_project(self._portal(), uid):
            return self._redirect("{0}?ok=Project+deleted".format(self._self_url()))
        return self._redirect("{0}?error=Project+not+found".format(self._self_url()))
