# -*- coding: utf-8 -*-
"""
Bridge: PFAS method profile ⇄ core SENAITE Method (and the core objects it
governs).

The add-on's method *profile* (FDA_32PFAS — carries QC ranges, tiers, matrices)
and the core SENAITE *Method* object (method-1 — the record analytes, worksheets
and analyses reference) describe the same method from two sides. This module
maintains the explicit link between them in the

    senaite.pfas.method_associations   (annotation)

store (the same one the new-method wizard writes), so a profile id resolves to
its core Method + AnalysisServices + SampleTypes and vice versa. That lets the
intuitive PFAS displays sit *on top of* proper core Method records rather than
duplicating them.

Matching is by Method TITLE (the master registry label == core Method.Title()).
Unmatched profiles are reported, never guessed.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

logger = logging.getLogger("senaite.pfas.method_bridge")

METHOD_ASSOC_KEY = u"senaite.pfas.method_associations"


def _catalog(portal):
    from Products.CMFCore.utils import getToolByName
    return getToolByName(portal, "senaite_catalog_setup")


def _annotations(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def _get_by_uid(portal, uid):
    if not uid:
        return None
    try:
        from bika.lims import api
        return api.get_object_by_uid(uid, default=None)
    except Exception:
        for b in _catalog(portal)(UID=uid):
            try:
                return b.getObject()
            except Exception:
                return None
    return None


def _method_label(method_id, profile=None):
    """Canonical (long) label from the single-source registry; falls back to the
    profile display_name."""
    try:
        from senaite.pfas.analyte_reference import METHODS as _M
        for mid, lbl, _desc in _M:
            if mid == method_id:
                return lbl
    except Exception:
        pass
    if profile:
        return profile.get("display_name") or method_id
    return method_id


# ── Read side ─────────────────────────────────────────────────────────────────

def get_association(portal, method_id):
    """Parsed association dict for a profile id (or {})."""
    store = _annotations(portal).get(METHOD_ASSOC_KEY)
    if not store or method_id not in store:
        return {}
    try:
        return json.loads(store[method_id])
    except Exception:
        return {}


def get_core_method(portal, method_id):
    """Core Method object linked to a profile id, or None. Uses the stored UID,
    falling back to a live title match so it works even before backfill."""
    uid = get_association(portal, method_id).get("method_uid")
    obj = _get_by_uid(portal, uid) if uid else None
    if obj is not None:
        return obj
    # Match by exact Title in Python — the Title index is a ZCTextIndex and some
    # method titles contain parentheses (e.g. "…(aqueous/solid/…)") that break a
    # Title= fulltext query.
    label = _method_label(method_id)
    for b in _catalog(portal)(portal_type="Method"):
        try:
            o = b.getObject()
            if o.Title() == label:
                return o
        except Exception:
            continue
    return None


def get_profile_id_for_method(portal, method):
    """Reverse lookup: given a core Method (object or UID) return the profile id."""
    uid = method.UID() if hasattr(method, "UID") else method
    store = _annotations(portal).get(METHOD_ASSOC_KEY) or {}
    for mid in list(store.keys()):
        try:
            if json.loads(store[mid]).get("method_uid") == uid:
                return mid
        except Exception:
            continue
    return None


# ── Write side ────────────────────────────────────────────────────────────────

def _service_uid_map(portal):
    out = {}
    for b in _catalog(portal)(portal_type="AnalysisService"):
        try:
            o = b.getObject()
            out[o.getKeyword()] = o.UID()
        except Exception:
            continue
    return out


def link_one(portal, method_id, profile=None, svc_uid=None):
    """Populate/refresh the association for a single profile. Returns the core
    Method object linked, or None if no title match (reported, not guessed).
    Merges with any existing association (preserves wizard-set keys)."""
    from senaite.pfas.method_profile_store import get_profile
    from persistent.mapping import PersistentMapping

    if profile is None:
        profile = get_profile(portal, method_id)
    method = get_core_method(portal, method_id)
    if method is None:
        logger.warning("method_bridge: no core Method matches profile %s (%r)",
                       method_id, _method_label(method_id, profile))
        return None

    if svc_uid is None:
        svc_uid = _service_uid_map(portal)
    service_uids = [svc_uid[k] for k in profile.get("master_analyte_set", [])
                    if k in svc_uid]
    sampletype_uids = sorted(set((profile.get("matrix_uid_map", {}) or {}).values()))

    assoc = get_association(portal, method_id)
    assoc.update({
        "method_uid":      method.UID(),
        "method_id":       method.getId(),
        "method_title":    method.Title(),
        "service_uids":    service_uids,
        "sampletype_uids": sampletype_uids,
    })

    ann = _annotations(portal)
    if METHOD_ASSOC_KEY not in ann:
        ann[METHOD_ASSOC_KEY] = PersistentMapping()
    ann[METHOD_ASSOC_KEY][method_id] = json.dumps(assoc)
    return method


def link_all(portal):
    """Populate/refresh associations for every profile. Idempotent. Returns
    {'linked': [...], 'unmatched': [(id, label), ...]}."""
    from senaite.pfas.method_profile_store import list_method_ids, get_profile

    svc_uid = _service_uid_map(portal)
    linked, unmatched = [], []
    for mid in list_method_ids(portal):
        profile = get_profile(portal, mid)
        method = link_one(portal, mid, profile=profile, svc_uid=svc_uid)
        if method is None:
            unmatched.append((mid, _method_label(mid, profile)))
        else:
            linked.append(mid)
    return {"linked": linked, "unmatched": unmatched}
