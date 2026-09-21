# -*- coding: utf-8 -*-
"""
Batch -> Project link, by annotation.

Batch is a core SENAITE type, so the link to a Project (an add-on content
type — see senaite.pfas.content.project) is stored as an annotation on the
Batch, never as a schema field: this add-on never forks core.

A Batch with no project is the default and overwhelmingly common case —
every batch that predates this feature has no project. Every function here
must return None (or an empty/falsy result) cleanly for such a batch: absent
means "no project", never an error and never a default guessed at.

A project, in turn, optionally names a QAPP controlled document (see
senaite.pfas.browser.sop_documents.DOC_TYPES) that overrides the lab's
internal quality system for that project. get_qapp_document_id resolves a
batch straight through to that document id, or None if the batch has no
project, or the project has no QAPP on file.

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

    None for any batch that was never linked to a project — which is every
    existing batch — and for any batch object that fails to adapt to
    IAnnotations (never raises)."""
    if batch is None:
        return None
    try:
        ann = _annotations(batch)
    except Exception:
        return None
    uid = ann.get(PROJECT_UID_KEY)
    return uid or None


def set_project_uid(batch, uid, method_id=None, matrix=None):
    """Store `uid` as the batch's linked Project. Passing None or "" removes
    the key entirely (rather than storing a falsy value), so get_project_uid
    goes back to returning None exactly as an untouched batch would.

    This is the ONE place a batch<->project link is made or broken, so it is
    also where the per-batch resolved-criteria file (see
    senaite.pfas.resolved_criteria_store) is kept in step with that link --
    mirroring method_profile_store.py's own choke point, which calls
    export_profiles_to_file() once inside save_profile() rather than trusting
    every future caller to remember to. Concretely:

      * uid cleared -> delete any resolved file for this batch. A project
        link that no longer exists must not leave a stale project-tier
        answer for the worker to read.
      * uid set -> (re)export the resolved file, IF method_id/matrix are
        known. They are accepted as optional arguments here because nothing
        on a bare Batch reliably names them without a request/worksheet
        context (see run_builder.batch_method() / data_review._batch_matrix()
        for how fragile that derivation already is) -- a future caller that
        links a batch to a project already has this context (batches are
        created against ONE method and ONE matrix, CLAUDE.md Sec3) and should
        pass it. Failing that, a best-effort, request-free method_id lookup
        is attempted; matrix is never guessed. Missing either -> no file is
        written, which is the same safe "no file" state as before this
        function existed, never an error and never a fabricated value.

    Exporting is entirely best-effort: any failure here is logged and
    swallowed, never allowed to prevent the annotation write above (which
    has already happened by the time this runs)."""
    if batch is None:
        return
    try:
        ann = _annotations(batch)
    except Exception:
        return
    if not uid:
        if PROJECT_UID_KEY in ann:
            del ann[PROJECT_UID_KEY]
        _clear_resolved_criteria(batch)
        return
    ann[PROJECT_UID_KEY] = uid
    _export_resolved_criteria(batch, method_id, matrix)


def _clear_resolved_criteria(batch):
    try:
        from senaite.pfas import resolved_criteria_store
        batch_id = getattr(batch, "getId", lambda: None)()
        resolved_criteria_store.remove_resolved_criteria(batch_id)
    except Exception as exc:
        logger.warning(
            "project_ref: could not clear resolved criteria for %r: %s",
            batch, exc)


def _derive_method_id(batch):
    """Best-effort, request-free method id for `batch` -- the same core-
    Method bridge senaite.pfas.browser.logbooks.batch_method() falls back
    to, minus the request-dependent extraction-session/logbook-annotation
    steps that helper also tries, since those need a request this function
    does not have. Returns "" (never raises) if nothing resolves."""
    try:
        m = batch.getMethod()
    except Exception:
        return u""
    if not m:
        return u""
    try:
        from senaite.pfas.method_bridge import profile_id_for_method
        return profile_id_for_method(m) or u""
    except Exception:
        return u""


def _export_resolved_criteria(batch, method_id, matrix):
    if not method_id:
        method_id = _derive_method_id(batch)
    if not method_id or not matrix:
        logger.info(
            "project_ref: batch %r linked to a project but method_id/matrix "
            "not known (%r/%r) -- resolved-criteria export skipped, not "
            "guessed", batch, method_id, matrix)
        return
    try:
        from bika.lims import api
        from senaite.pfas import resolved_criteria_store
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
    try:
        from bika.lims import api
        return api.get_object_by_uid(uid, default=None)
    except Exception:
        pass
    try:
        from Products.CMFCore.utils import getToolByName
        catalog = getToolByName(portal, "senaite_catalog_setup")
        for brain in catalog.unrestrictedSearchResults(UID=uid):
            try:
                return brain.getObject()
            except Exception:
                return None
    except Exception:
        pass
    return None


def get_project(portal, batch):
    """The Project object linked to this batch, or None.

    None whenever the batch has no project link, or the link points at a
    Project that no longer resolves (deleted/UID stale) — never an error."""
    uid = get_project_uid(batch)
    if not uid:
        return None
    return _get_by_uid(portal, uid)


def get_qapp_document_id(portal, batch):
    """The QAPP controlled-document id governing this batch, or None.

    None when the batch has no project, when the project has no
    qapp_document_id set, or when the field is blank — a project with no
    QAPP on file simply defers to the lab's internal quality system, which
    is not this function's concern."""
    project = get_project(portal, batch)
    if project is None:
        return None
    doc_id = getattr(project, "qapp_document_id", None)
    return doc_id or None
