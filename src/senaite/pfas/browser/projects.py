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
import urllib
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
from senaite.pfas import method_profile_store
from senaite.pfas import ruleset

logger = logging.getLogger("senaite.pfas.browser.projects")

ALL_STATUSES = [
    (STATUS_ACTIVE, "Active"),
    (STATUS_CLOSED, "Closed"),
]

# ── QAPP criteria editor ──────────────────────────────────────────────────────
#
# This is the ONLY place anything writes into the project tier of
# senaite.pfas.ruleset -- see that module's docstring: set_project_criterion/
# set_project_ruleset had zero call sites before this. Scoped method x matrix
# like every other analyte-bearing structure (CLAUDE.md Sec3 rule 2).
#
# The 7 keys below are edited as one number/int/bool/window field each,
# resolved and written individually through ruleset.set_project_criterion --
# never assembled into a dict and handed to set_project_ruleset (GAPS.md
# Sec7.1 is exactly that defect one layer down). eis_recovery is handled
# separately (CRITERIA_DEFS excludes it) because it is analyte-scoped: its
# stored node is {analyte: {"min":x,"max":y}, ...} one level deeper than
# every other key, and clearing ONE analyte must not touch another's (or
# ruleset.ANALYTE_SCOPED_KEYS's own per-analyte silence rule would be
# defeated by an editor that clears the whole key).
CRITERIA_DEFS = [
    {"key": "cal_r2_min", "label": u"Calibration r² minimum",
     "input": "number", "step": "0.0001"},
    {"key": "sn_quan_min", "label": u"S/N quantitation minimum",
     "input": "number", "step": "0.1"},
    {"key": "dup_rpd_max", "label": u"Duplicate RPD maximum (%)",
     "input": "number", "step": "0.1"},
    {"key": "ccv_recovery", "label": u"CCV recovery window (%)",
     "input": "window", "step": "0.1"},
    {"key": "ccv_frequency", "label": u"CCV frequency (1 per N samples)",
     "input": "int", "step": "1"},
    {"key": "lfsm_frequency", "label": u"LFSM frequency (1 per N samples)",
     "input": "int", "step": "1"},
    {"key": "duplicate_all_samples", "label": u"Duplicate all samples",
     "input": "bool", "step": None},
]
EIS_KEY = u"eis_recovery"


def _blank(s):
    return s is None or (isinstance(s, basestring) and s.strip() == "")


def _url_quote(s):
    try:
        return urllib.quote((s or u"").encode("utf-8"))
    except Exception:
        return u""


def _fmt_value(shape_input, value):
    """Human-readable rendering of a resolved criterion value for the
    "inherited"/"current" display columns -- never used for the editable
    input itself (that is prefilled from the raw stored value, separately)."""
    if value is None:
        return u"—"
    if shape_input == "window" and isinstance(value, dict):
        lo = value.get("min")
        hi = value.get("max")
        return u"{0} – {1}".format(
            u"—" if lo is None else lo, u"—" if hi is None else hi)
    if shape_input == "bool":
        return u"Yes" if value else u"No"
    return unicode(value)


def _method_ids(portal):
    """Every method id with a profile -- defaults plus anything explicitly
    saved -- same union method_profiles.py's list view already uses."""
    saved = set(method_profile_store.list_method_ids(portal))
    return sorted(set(method_profile_store.DEFAULT_PROFILES.keys()) | saved)


def _matrices_for_method(portal, method_id):
    if not method_id:
        return []
    profile = method_profile_store.get_profile(portal, method_id)
    return list(profile.get("supported_matrices") or [])


def _eis_analytes_for_method(portal, method_id):
    """Analytes a project can set an eis_recovery override for -- every
    analyte the lab profile's eis_overrides already names, mirroring
    resolved_criteria_store._analytes_for_key's own universe (an analyte
    with no lab/project opinion today is not offered, not invented)."""
    if not method_id:
        return []
    profile = method_profile_store.get_profile(portal, method_id)
    names = set()
    for row in (profile.get("eis_overrides") or []):
        a = row.get("analyte") if isinstance(row, dict) else None
        if a:
            names.add(a)
    return sorted(names)


def _raw_project_value(project_ruleset, method_id, matrix, key, analyte=None):
    """The value literally stored at the project tier for this key -- used
    ONLY to prefill the edit form (blank means no override on file), never
    to decide what a batch resolves to (that is ruleset.resolve()'s job)."""
    node = ruleset._dig(project_ruleset or {}, [method_id, matrix, key])
    if key in ruleset.ANALYTE_SCOPED_KEYS:
        if not isinstance(node, dict) or analyte is None:
            return None
        return node.get(analyte)
    return node


def _set_eis_analyte(project_obj, method_id, matrix, analyte, value):
    """Set (or, with value=None, clear) ONE analyte's eis_recovery override
    without disturbing any other analyte's -- reads the whole eis_recovery
    node for this method/matrix, edits one entry, writes the node back
    through set_project_criterion (still ONE key, per that function's own
    merge contract; only the shape of this particular key is one level
    deeper than the others)."""
    current = ruleset.get_project_ruleset(project_obj)
    node = ruleset._dig(current, [method_id, matrix, EIS_KEY])
    node = dict(node) if isinstance(node, dict) else {}
    if value is None:
        node.pop(analyte, None)
    else:
        node[analyte] = value
    ruleset.set_project_criterion(project_obj, method_id, matrix, EIS_KEY, node)


def _refresh_resolved_criteria_for_project(portal, project_obj, request=None):
    """Re-export the resolved-criteria file (senaite.pfas.
    resolved_criteria_store) for every Batch linked to this project, so an
    edit made here reaches the Py3 worker instead of sitting stale until
    project_ref.set_project_uid happens to be called again for that batch
    (the ONLY other writer of that file).

    There is no reverse index from Project -> Batch: the link lives as an
    annotation ON the batch (project_ref.PROJECT_UID_KEY), not a back-
    reference on the project. So this walks every Batch in the site via
    batch_ref.list_batches() -- the same site-wide enumeration batch_ref.py
    itself already uses as the cheap option when no catalog metadata exists
    for the thing being searched. For a lab-sized batch count this is fine;
    if it ever is not, the fix is a catalog index on the project_uid
    annotation, not a change here.

    Returns (refreshed, skipped) where `skipped` lists (batch_id, reason)
    pairs for batches whose method_id/matrix could not be derived, or whose
    file write itself failed -- export_resolved_criteria() raises on I/O
    failure (unlike project_ref's own caller, which swallows it), so this
    loop must swallow it per-batch or one bad batch could 500 an otherwise-
    successful criteria save."""
    from bika.lims import api as bika_api
    from senaite.pfas import batch_ref
    from senaite.pfas import project_ref
    from senaite.pfas import resolved_criteria_store
    from senaite.pfas.browser.batch_project_viewlet import (
        _batch_method_id, _batch_matrix,
    )

    try:
        project_uid = bika_api.get_uid(project_obj)
    except Exception:
        logger.warning(
            "_refresh_resolved_criteria_for_project: could not get a UID "
            "for %r -- no batch can be matched, refreshing none",
            project_obj)
        return 0, []

    refreshed = 0
    skipped = []
    for batch in batch_ref.list_batches(portal):
        try:
            if project_ref.get_project_uid(batch) != project_uid:
                continue
        except Exception:
            continue
        batch_id = getattr(batch, "getId", lambda: None)() or u"?"
        try:
            method_id = _batch_method_id(batch, request) or u""
            matrix = _batch_matrix(portal, batch) or u""
            if not method_id or not matrix:
                skipped.append((batch_id, "method/matrix not known"))
                continue
            path = resolved_criteria_store.export_resolved_criteria(
                portal, batch, method_id, matrix)
            if path:
                refreshed += 1
            else:
                skipped.append((batch_id, "export declined (incomplete)"))
        except Exception as exc:
            logger.warning(
                "_refresh_resolved_criteria_for_project: export failed for "
                "batch %s: %s", batch_id, exc)
            skipped.append((batch_id, "export failed: {0}".format(exc)))
    return refreshed, skipped


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
            if action in ("add", "edit", "delete", "save_criteria",
                          "save_eis_criterion", "clear_eis_criterion"):
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
            if action == "save_criteria":
                return self._handle_save_criteria()
            if action == "save_eis_criterion":
                return self._handle_save_eis_criterion()
            if action == "clear_eis_criterion":
                return self._handle_clear_eis_criterion()
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

    # ── QAPP criteria editor: template data ──────────────────────────────────
    #
    # Scoped uid -> method_id -> matrix, exactly like the run builder/method
    # profile UIs are scoped (CLAUDE.md §3 rule 2). Every value shown here is
    # resolved through ruleset.resolve() -- never read off the profile
    # directly -- so what an operator sees is provably what a batch would
    # actually get.

    def criteria_uid(self):
        return self.request.form.get("criteria_uid", "")

    def criteria_project(self):
        uid = self.criteria_uid()
        if not uid:
            return None
        return _get_project(self._portal(), uid)

    def _criteria_project_obj(self):
        """The real content object (not the display dict) -- needed to
        reach ruleset.get_project_ruleset()/set_project_criterion(), which
        adapt to IAnnotations on the object itself."""
        uid = self.criteria_uid()
        if not uid:
            return None
        try:
            folder = _get_projects_folder(self._portal())
        except RuntimeError:
            return None
        return folder.get(uid)

    def criteria_method_ids(self):
        return _method_ids(self._portal())

    def criteria_method(self):
        return self.request.form.get("method_id", "")

    def criteria_matrices(self):
        return _matrices_for_method(self._portal(), self.criteria_method())

    def criteria_matrix(self):
        return self.request.form.get("matrix", "")

    def criteria_scope_ready(self):
        return bool(self.criteria_uid() and self.criteria_method()
                    and self.criteria_matrix())

    def _criteria_context(self):
        """(profile, project_ruleset, project_doc, project_rev) for the
        currently-selected project/method/matrix scope -- fetched once and
        threaded through every resolve() call the panel makes."""
        portal = self._portal()
        method_id = self.criteria_method()
        matrix = self.criteria_matrix()
        project_obj = self._criteria_project_obj()
        profile = method_profile_store.get_profile(portal, method_id)
        project_ruleset = ruleset.get_project_ruleset(project_obj)
        project_doc, project_rev = (None, None)
        if project_obj is not None:
            project_doc, project_rev = ruleset._project_source(portal, project_obj)
        return profile, project_ruleset, project_doc, project_rev

    def criteria_rows(self):
        """One row per CRITERIA_DEFS key (every key except eis_recovery,
        which is analyte-scoped and rendered by criteria_eis_rows() /
        criteria_eis_form() instead)."""
        if not self.criteria_scope_ready():
            return []
        method_id = self.criteria_method()
        matrix = self.criteria_matrix()
        profile, project_ruleset, project_doc, project_rev = self._criteria_context()

        rows = []
        for spec in CRITERIA_DEFS:
            key = spec["key"]
            current = ruleset.resolve(
                method_id, matrix, key, profile=profile,
                project_ruleset=project_ruleset,
                project_doc=project_doc, project_rev=project_rev)
            inherited = ruleset.resolve(
                method_id, matrix, key, profile=profile,
                project_ruleset=None)
            raw = _raw_project_value(project_ruleset, method_id, matrix, key)

            row = {
                "key": key,
                "label": spec["label"],
                "input": spec["input"],
                "step": spec["step"],
                "inherited_display": _fmt_value(spec["input"], inherited.value),
                "inherited_tier": inherited.tier,
                "current_display": _fmt_value(spec["input"], current.value),
                "current_tier": current.tier,
                "current_conformance": current.conformance,
                "has_override": raw is not None,
            }
            if spec["input"] == "window":
                raw = raw or {}
                row["raw_min"] = u"" if raw.get("min") is None else raw.get("min")
                row["raw_max"] = u"" if raw.get("max") is None else raw.get("max")
            elif spec["input"] == "bool":
                row["raw_bool"] = (
                    "" if raw is None else ("true" if raw else "false"))
            else:
                row["raw_value"] = u"" if raw is None else raw
            rows.append(row)
        return rows

    def criteria_eis_analytes(self):
        return _eis_analytes_for_method(self._portal(), self.criteria_method())

    def criteria_eis_selected_analyte(self):
        return self.request.form.get("analyte", "")

    def criteria_eis_rows(self):
        """One row per analyte that ALREADY has a project-tier eis_recovery
        override on file for this method/matrix -- the "what's set" table,
        separate from the add/update mini-form below."""
        if not self.criteria_scope_ready():
            return []
        method_id = self.criteria_method()
        matrix = self.criteria_matrix()
        profile, project_ruleset, project_doc, project_rev = self._criteria_context()
        node = ruleset._dig(project_ruleset, [method_id, matrix, EIS_KEY])
        if not isinstance(node, dict):
            return []
        rows = []
        for analyte in sorted(node.keys()):
            current = ruleset.resolve(
                method_id, matrix, EIS_KEY, analyte=analyte, profile=profile,
                project_ruleset=project_ruleset,
                project_doc=project_doc, project_rev=project_rev)
            inherited = ruleset.resolve(
                method_id, matrix, EIS_KEY, analyte=analyte, profile=profile,
                project_ruleset=None)
            rows.append({
                "analyte": analyte,
                "raw": node.get(analyte) or {},
                "inherited_display": _fmt_value("window", inherited.value),
                "current_display": _fmt_value("window", current.value),
                "current_tier": current.tier,
                "current_conformance": current.conformance,
                "departure_ends": (current.departure or {}).get("ends", []),
            })
        return rows

    def criteria_eis_preview(self):
        """The inherited (lab/baseline) value for whichever analyte is
        currently selected in the add/update mini-form -- so an operator
        sees what they are changing from before they type anything, exactly
        as the task requires for every other key."""
        if not self.criteria_scope_ready():
            return None
        analyte = self.criteria_eis_selected_analyte()
        if not analyte:
            return None
        method_id = self.criteria_method()
        matrix = self.criteria_matrix()
        profile, project_ruleset, project_doc, project_rev = self._criteria_context()
        inherited = ruleset.resolve(
            method_id, matrix, EIS_KEY, analyte=analyte, profile=profile,
            project_ruleset=None)
        current = ruleset.resolve(
            method_id, matrix, EIS_KEY, analyte=analyte, profile=profile,
            project_ruleset=project_ruleset,
            project_doc=project_doc, project_rev=project_rev)
        return {
            "analyte": analyte,
            "inherited_display": _fmt_value("window", inherited.value),
            "current_display": _fmt_value("window", current.value),
            "current_tier": current.tier,
        }

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

    # ── QAPP criteria editor: action handlers ────────────────────────────────
    #
    # All three write ONLY through ruleset.set_project_criterion, one
    # (method_id, matrix, key) at a time -- never ruleset.set_project_ruleset
    # with a form-built payload (GAPS.md Sec7.1's defect shape, one layer
    # lower). A parse error on any field aborts the WHOLE save before any
    # write happens, so a save is all-or-nothing even though the writes
    # underneath are per-key.

    def _criteria_redirect(self, uid, method_id, matrix, msg):
        url = ("{0}?criteria_uid={1}&method_id={2}&matrix={3}&{4}".format(
            self._self_url(), uid,
            _url_quote(method_id), _url_quote(matrix), msg))
        return self._redirect(url)

    def _handle_save_criteria(self):
        f = self.request.form
        uid = (f.get("uid") or "").strip()
        method_id = (f.get("method_id") or "").strip()
        matrix = (f.get("matrix") or "").strip()

        if not uid or not method_id or not matrix:
            return self._redirect(
                "{0}?criteria_uid={1}&error=Choose+a+method+and+matrix+first"
                .format(self._self_url(), uid))

        project_obj = None
        try:
            folder = _get_projects_folder(self._portal())
            project_obj = folder.get(uid)
        except RuntimeError:
            pass
        if project_obj is None:
            return self._redirect(
                "{0}?error=Project+not+found".format(self._self_url()))

        # Parse every field FIRST -- a bad number anywhere must not leave a
        # half-applied save (some keys written, one skipped on a typo).
        to_write = {}
        for spec in CRITERIA_DEFS:
            key = spec["key"]
            try:
                if spec["input"] == "number":
                    raw = f.get(key)
                    to_write[key] = None if _blank(raw) else float(raw)
                elif spec["input"] == "int":
                    raw = f.get(key)
                    to_write[key] = None if _blank(raw) else int(raw)
                elif spec["input"] == "bool":
                    raw = (f.get(key) or "").strip().lower()
                    to_write[key] = (
                        None if raw == "" else raw in ("true", "1", "yes"))
                elif spec["input"] == "window":
                    raw_min = f.get(key + "_min")
                    raw_max = f.get(key + "_max")
                    if _blank(raw_min) and _blank(raw_max):
                        to_write[key] = None
                    else:
                        to_write[key] = {
                            "min": None if _blank(raw_min) else float(raw_min),
                            "max": None if _blank(raw_max) else float(raw_max),
                        }
            except (TypeError, ValueError):
                return self._criteria_redirect(
                    uid, method_id, matrix,
                    "error=Invalid+value+for+{0}".format(key))

        for key, value in to_write.items():
            ruleset.set_project_criterion(project_obj, method_id, matrix,
                                           key, value)

        refreshed, skipped = _refresh_resolved_criteria_for_project(
            self._portal(), project_obj, request=self.request)
        msg = "ok=Criteria+saved+-+{0}+batch(es)+refreshed".format(refreshed)
        if skipped:
            msg = "{0}+%28{1}+skipped%29".format(msg, len(skipped))
        return self._criteria_redirect(uid, method_id, matrix, msg)

    def _handle_save_eis_criterion(self):
        f = self.request.form
        uid = (f.get("uid") or "").strip()
        method_id = (f.get("method_id") or "").strip()
        matrix = (f.get("matrix") or "").strip()
        analyte = (f.get("analyte") or "").strip()

        if not uid or not method_id or not matrix or not analyte:
            return self._redirect(
                "{0}?criteria_uid={1}&error=Choose+a+method%2C+matrix+and+"
                "analyte+first".format(self._self_url(), uid))

        project_obj = None
        try:
            folder = _get_projects_folder(self._portal())
            project_obj = folder.get(uid)
        except RuntimeError:
            pass
        if project_obj is None:
            return self._redirect(
                "{0}?error=Project+not+found".format(self._self_url()))

        raw_min = f.get("eis_min")
        raw_max = f.get("eis_max")
        try:
            value = None
            if not (_blank(raw_min) and _blank(raw_max)):
                value = {
                    "min": None if _blank(raw_min) else float(raw_min),
                    "max": None if _blank(raw_max) else float(raw_max),
                }
        except (TypeError, ValueError):
            return self._criteria_redirect(
                uid, method_id, matrix, "error=Invalid+EIS+recovery+value")

        _set_eis_analyte(project_obj, method_id, matrix, analyte, value)

        refreshed, skipped = _refresh_resolved_criteria_for_project(
            self._portal(), project_obj, request=self.request)
        msg = "ok=EIS+override+saved+-+{0}+batch(es)+refreshed".format(refreshed)
        if skipped:
            msg = "{0}+%28{1}+skipped%29".format(msg, len(skipped))
        return self._criteria_redirect(uid, method_id, matrix, msg)

    def _handle_clear_eis_criterion(self):
        f = self.request.form
        uid = (f.get("uid") or "").strip()
        method_id = (f.get("method_id") or "").strip()
        matrix = (f.get("matrix") or "").strip()
        analyte = (f.get("analyte") or "").strip()

        if not uid or not method_id or not matrix or not analyte:
            return self._redirect(
                "{0}?criteria_uid={1}&error=Missing+analyte+to+clear"
                .format(self._self_url(), uid))

        project_obj = None
        try:
            folder = _get_projects_folder(self._portal())
            project_obj = folder.get(uid)
        except RuntimeError:
            pass
        if project_obj is None:
            return self._redirect(
                "{0}?error=Project+not+found".format(self._self_url()))

        _set_eis_analyte(project_obj, method_id, matrix, analyte, None)

        refreshed, skipped = _refresh_resolved_criteria_for_project(
            self._portal(), project_obj, request=self.request)
        msg = "ok=EIS+override+cleared+-+{0}+batch(es)+refreshed".format(refreshed)
        if skipped:
            msg = "{0}+%28{1}+skipped%29".format(msg, len(skipped))
        return self._criteria_redirect(uid, method_id, matrix, msg)
