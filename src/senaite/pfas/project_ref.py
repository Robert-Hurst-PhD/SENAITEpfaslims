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


def set_project_uid(batch, uid):
    """Store `uid` as the batch's linked Project. Passing None or "" removes
    the key entirely (rather than storing a falsy value), so get_project_uid
    goes back to returning None exactly as an untouched batch would."""
    if batch is None:
        return
    try:
        ann = _annotations(batch)
    except Exception:
        return
    if not uid:
        if PROJECT_UID_KEY in ann:
            del ann[PROJECT_UID_KEY]
        return
    ann[PROJECT_UID_KEY] = uid


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
