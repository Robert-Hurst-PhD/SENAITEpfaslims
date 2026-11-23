# -*- coding: utf-8 -*-
"""
Batch -> Project link, by annotation.

Batch is a core SENAITE type, so the link to a Project (an add-on content
type — see senaite.pfas.content.project) is stored as an annotation on the
Batch, never as a schema field: this add-on never forks core.

A Batch with no project is the default and common case. Every function here
must return None (or an empty/falsy result) cleanly for such a batch: absent
means "no project", never an error and never a default guessed at.

A project, in turn, optionally names a QAPP controlled document (see
senaite.pfas.browser.sop_documents.DOC_TYPES) that overrides the lab's
internal quality system for that project.

Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.project_ref")

PROJECT_UID_KEY = u"senaite.pfas.batch.project_uid"


def _annotations(batch):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(batch)


def get_project_uid(batch):
    """The UID of the Project linked to this batch, or None.

    None for any batch never linked to a project, and for any batch object
    that fails to adapt to IAnnotations (never raises)."""
    if batch is None:
        return None
    try:
        ann = _annotations(batch)
    except TypeError:                       # the object is not annotatable
        return None
    uid = ann.get(PROJECT_UID_KEY)
    return uid or None


def set_project_uid(batch, uid, method_id=None, matrix=None):
    """Store `uid` as the batch's linked Project. Passing None or "" removes
    the key entirely (rather than storing a falsy value), so get_project_uid
    returns None exactly as for an untouched batch.

    This is the ONE place a batch<->project link is made or broken, so it
    also keeps the per-batch resolved-criteria file
    (senaite.pfas.resolved_criteria_store) in step with the link:

      * uid cleared -> delete any resolved file for this batch: a link that
        is gone must not leave a stale project-tier answer for the worker.
      * uid set -> (re)export the resolved file when method_id and matrix
        are known. Nothing on a bare Batch reliably names them without a
        request, so a caller that links a batch (created against ONE method
        and ONE matrix) should pass them. Failing that, a request-free
        method_id lookup is tried; matrix is never guessed. Missing either
        -> no file is written, never an error and never a fabricated value.

    Exporting is best-effort: any failure is logged and swallowed, never
    undoing the annotation write, which has already happened."""
    if batch is None:
        return
    try:
        ann = _annotations(batch)
    except TypeError:                       # the object is not annotatable
        return
    if not uid:
        if PROJECT_UID_KEY in ann:
            del ann[PROJECT_UID_KEY]
        _clear_resolved_criteria(batch)
        return
    ann[PROJECT_UID_KEY] = uid
    _export_resolved_criteria(batch, method_id, matrix)


def _clear_resolved_criteria(batch):
    from senaite.pfas import resolved_criteria_store
    try:
        batch_id = getattr(batch, "getId", lambda: None)()
        resolved_criteria_store.remove_resolved_criteria(batch_id)
    except Exception as exc:
        logger.warning(
            "project_ref: could not clear resolved criteria for %r: %s",
            batch, exc)


def _derive_method_id(batch):
    """Best-effort, request-free method id for `batch` -- the core-Method
    bridge batch_method.of() also reads, without the extraction session and
    the extraction record that resolver tries as well. Returns "" when the
    batch names no method."""
    try:
        m = batch.getMethod()
    except AttributeError:                  # a batch type without a method
        return u""
    if not m:
        return u""
    from senaite.pfas.method_bridge import profile_id_for_method
    return profile_id_for_method(m) or u""


def _export_resolved_criteria(batch, method_id, matrix):
    if not method_id:
        method_id = _derive_method_id(batch)
    if not method_id or not matrix:
        logger.info(
            "project_ref: batch %r linked to a project but method_id/matrix "
            "not known (%r/%r) -- resolved-criteria export skipped, not "
            "guessed", batch, method_id, matrix)
        return
    from bika.lims import api
    from senaite.pfas import resolved_criteria_store
    try:
        portal = api.get_portal()
        resolved_criteria_store.export_resolved_criteria(
            portal, batch, method_id, matrix)
    except Exception as exc:
        logger.warning(
            "project_ref: resolved-criteria export failed for %r (%s/%s): %s",
            batch, method_id, matrix, exc)


def _get_by_uid(portal, uid):
    if not uid:
        return None
    from bika.lims import api
    return api.get_object_by_uid(uid, default=None)


def get_project(portal, batch):
    """The Project object linked to this batch, or None.

    None whenever the batch has no project link, or the link points at a
    Project that no longer resolves (deleted/UID stale) — never an error."""
    uid = get_project_uid(batch)
    if not uid:
        return None
    return _get_by_uid(portal, uid)


# ── The client's standing project ────────────────────────────────────────────
#
# One project per client may be standing. A batch created for that client
# naming no project is linked to it here, through set_project_uid, so all
# that follows a project follows it. Only a batch being created is linked:
# a batch that already exists keeps the link it has, or none.

def is_standing(project):
    """True when `project` is its client's standing project. A project
    saved before the field existed reads no."""
    return bool(getattr(project, "standing", False))


def all_projects(portal):
    """Every Project object under portal/pfas_projects ([] when the folder
    is missing)."""
    folder = portal.get("pfas_projects") if portal is not None else None
    if folder is None:
        return []
    return [o for o in folder.objectValues()
            if getattr(o, "portal_type", "") == "PFASProject"]


# a standing project names no QAPP document: the save refuses both at once
STANDING_WITH_QAPP = (u"A standing project names no QAPP document. "
                      u"Clear Standing or the QAPP.")


def standing_refusal(standing, qapp_document_id):
    """Why a project save is refused, or None: a standing project names no
    QAPP document, so its batches keep the lab's quality system."""
    if standing and (qapp_document_id or u"").strip():
        return STANDING_WITH_QAPP
    return None


def is_active_project(project):
    """True unless the project's Status is Closed or the project is
    deactivated. A closed or deactivated standing project links nothing."""
    from senaite.pfas.content.project import STATUS_CLOSED
    if (getattr(project, "status", None) or u"") == STATUS_CLOSED:
        return False
    from bika.lims import api
    return bool(api.is_active(project))


def standing_project(projects, client_uid):
    """The active standing project of `client_uid` among `projects`, or
    None."""
    if not client_uid:
        return None
    for obj in projects:
        if getattr(obj, "client_uid", None) == client_uid and is_standing(obj) \
                and is_active_project(obj):
            return obj
    return None


def clear_other_standing(projects, keep):
    """`keep` is standing: every other project of its client is set to not
    standing, so a client has one standing project at most. Returns the
    projects changed."""
    changed = []
    if keep is None or not is_standing(keep):
        return changed
    client_uid = getattr(keep, "client_uid", None)
    for obj in projects:
        if obj is keep or getattr(obj, "client_uid", None) != client_uid:
            continue
        if is_standing(obj):
            obj.standing = False
            changed.append(obj)
    return changed


def _batch_client_uid(batch):
    """The UID of the client a batch is created for: its Client field (set
    on the add form or by api.create, before the batch is moved into the
    client's folder), else the client folder it was created in."""
    client = None
    try:
        field = batch.getField("Client")
        client = field.get(batch) if field is not None else None
    except AttributeError:
        client = None
    if client is None:
        try:
            client = batch.getClient()
        except AttributeError:
            client = None
    if client is None:
        return None
    from bika.lims import api
    return api.get_uid(client)


def link_new_batch(portal, batch):
    """Link a batch being created to its client's standing project when it
    names no project. Returns the project UID linked, or None."""
    if batch is None or get_project_uid(batch):
        return None
    project = standing_project(all_projects(portal), _batch_client_uid(batch))
    if project is None:
        return None
    from bika.lims import api
    uid = api.get_uid(project)
    set_project_uid(batch, uid)
    return uid


def on_batch_initialized(batch, event):
    """A batch has been created: it takes its client's standing project when
    it names none. Never raises: the batch is created either way."""
    try:
        from bika.lims import api
        link_new_batch(api.get_portal(), batch)
    except Exception:                                       # noqa: BLE001
        logger.warning("standing project not linked to %r", batch, exc_info=True)


# ── The worker's file once a linked batch knows its method and matrix ───────
#
# A link made before a batch has samples writes no resolved-criteria file:
# its method and matrix are not known yet. When a sample of the batch is
# created or edited, the file is written after the commit if the batch is
# linked and has none yet; a write that fails never fails the sample's save.

def schedule_first_export(batch):
    """After this transaction commits, write the resolved-criteria file of a
    project-linked batch that has none yet, when its method and matrix are
    known (resolved_criteria_store.export_if_first_known). Returns True when
    scheduled."""
    if batch is None or not get_project_uid(batch):
        return False
    from bika.lims import api
    from senaite.pfas import after_commit, resolved_criteria_store
    uid = api.get_uid(batch)
    after_commit.run_once(u"resolved criteria {0}".format(uid),
                          resolved_criteria_store.export_if_first_known,
                          api.get_portal(), uid)
    return True


def on_sample_modified(sample, event):
    """A sample was created or edited: its batch's file is written after the
    commit when the batch is linked and has none yet. Never raises."""
    try:
        schedule_first_export(sample.getBatch())
    except Exception:                                       # noqa: BLE001
        logger.warning("resolved criteria not scheduled for %r", sample, exc_info=True)
