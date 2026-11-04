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
    """Best-effort, request-free method id for `batch` -- the same core-
    Method bridge senaite.pfas.browser.logbooks.batch_method() falls back
    to, minus the request-dependent extraction-session/logbook-annotation
    steps that helper also tries, since those need a request this function
    does not have. Returns "" when the batch names no method."""
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
