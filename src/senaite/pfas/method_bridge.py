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
its core Method + AnalysisServices + SampleTypes and vice versa: the PFAS
displays sit *on top of* core Method records rather than duplicating them.

Matching is by Method TITLE (the master registry label == core Method.Title()).
Unmatched profiles are reported, never guessed.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

logger = logging.getLogger("senaite.pfas.method_bridge")

METHOD_ASSOC_KEY = u"senaite.pfas.method_associations"


def profile_id_for_method(method):
    """Profile id for a core SENAITE Method object (or "" if there is none).

    Method profiles are keyed by ``Method.MethodID`` ("FDA_32PFAS"); the Zope
    id ("method-1") is a different namespace and names no profile. Use this
    wherever a Method object has to become a profile id.
    """
    if method is None:
        return u""
    mid = (method.getMethodID() or u"").strip()
    if mid:
        return mid
    return method.getId()


def _catalog(portal):
    from Products.CMFCore.utils import getToolByName
    return getToolByName(portal, "senaite_catalog_setup")


def _annotations(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def _get_by_uid(portal, uid):
    if not uid:
        return None
    from bika.lims import api
    return api.get_object_by_uid(uid, default=None)


def _method_label(method_id, profile=None):
    """A method's label in messages: its profile's display name, else its id
    (configured_methods.method_label, the one labelling rule)."""
    from senaite.pfas.configured_methods import method_label
    return method_label(profile, method_id)


def _core_titles(portal, method_id):
    """Titles a core Method of this profile may carry: the profile's display
    name, and the title the install gave the methods it created
    (analyte_reference.METHODS), so a site linked before either changes still
    matches."""
    from senaite.pfas.method_profile_store import raw_profile
    from senaite.pfas.analyte_reference import METHODS as _seeded
    titles = []
    name = (raw_profile(portal, method_id) or {}).get("display_name")
    if name:
        titles.append(name)
    titles.extend(lbl for mid, lbl, _desc in _seeded if mid == method_id)
    return titles


# ── Read side ─────────────────────────────────────────────────────────────────

def get_association(portal, method_id):
    """Parsed association dict for a profile id (or {})."""
    store = _annotations(portal).get(METHOD_ASSOC_KEY)
    if not store or method_id not in store:
        return {}
    try:
        return json.loads(store[method_id])
    except (ValueError, TypeError):
        return {}


def get_core_method(portal, method_id):
    """Core Method object linked to a profile id, or None. Uses the stored UID,
    falling back to a live title match when none is stored."""
    uid = get_association(portal, method_id).get("method_uid")
    obj = _get_by_uid(portal, uid) if uid else None
    if obj is not None:
        return obj
    # The core Method whose MethodID is the profile id; else one titled as the
    # profile (matched in Python -- the Title index is a ZCTextIndex and some
    # method titles contain parentheses that break a Title= fulltext query).
    titles = _core_titles(portal, method_id)
    by_title = None
    for b in _catalog(portal)(portal_type="Method"):
        try:
            o = b.getObject()
            if method_id and getattr(o, "getMethodID", lambda: None)() == method_id:
                return o
            if by_title is None and o.Title() in titles:
                by_title = o
        except Exception:
            continue
    return by_title


def get_profile_id_for_method(portal, method):
    """Reverse lookup: given a core Method (object or UID) return the profile id."""
    uid = method.UID() if hasattr(method, "UID") else method
    store = _annotations(portal).get(METHOD_ASSOC_KEY) or {}
    for mid in list(store.keys()):
        try:
            if json.loads(store[mid]).get("method_uid") == uid:
                return mid
        except (ValueError, TypeError):
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


def _service_obj_map(portal):
    """{keyword: AnalysisService object} for every core AnalysisService."""
    out = {}
    for b in _catalog(portal)(portal_type="AnalysisService"):
        try:
            o = b.getObject()
            out[o.getKeyword()] = o
        except Exception:
            continue
    return out


def link_method_analytes(portal, method_ids=None):
    """Stamp a profile's core Method onto the AnalysisServices of its stored
    master_analyte_set, through SENAITE's own Method <-> Service relation
    (setMethods): the ONE-TIME link of a profile's stored list, before the
    links own the panel (method_profile_store.refresh_analyte_sets).
    The seed is the stored list, not analysis_services.csv's Method column
    (it also lists the isomer peaks, which never enter the reported panel).
    Merges with existing Methods; never removes a link. Returns a summary.
    """
    from senaite.pfas.method_profile_store import list_method_ids, get_profile

    svc_map = _service_obj_map(portal)
    result = {"methods": [], "links_added": 0,
              "unmatched_methods": [], "missing_services": {}}

    for mid in (method_ids or list_method_ids(portal)):
        profile = get_profile(portal, mid)
        method = get_core_method(portal, mid)
        if method is None:
            result["unmatched_methods"].append(
                (mid, _method_label(mid, profile)))
            continue

        method_uid = method.UID()
        added, missing = 0, []
        for kw in profile.get("master_analyte_set", []):
            svc = svc_map.get(kw)
            if svc is None:
                missing.append(kw)
                continue
            if not (hasattr(svc, "getMethods") and hasattr(svc, "setMethods")):
                continue
            try:
                existing = list(svc.getMethods() or [])
                if method_uid not in [m.UID() for m in existing]:
                    existing.append(method)
                    svc.setMethods(existing)
                    added += 1
            except Exception as exc:
                logger.warning("link_method_analytes: setMethods failed for "
                               "%s on %s: %s", kw, mid, exc)
        result["methods"].append((mid, added))
        result["links_added"] += added
        if missing:
            result["missing_services"][mid] = missing

    return result
