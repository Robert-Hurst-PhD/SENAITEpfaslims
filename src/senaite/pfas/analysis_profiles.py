# -*- coding: utf-8 -*-
"""Core Analysis Profiles generated from the method panel (core integration).

What a sample is analysed for is decided at registration, in core SENAITE.
The method's Analyte x Matrix table decided only what the worker judged, so
the two could disagree. Every method
profile save now writes one core Analysis Profile per method x matrix:

    title         "<method> - <matrix>"
    sample_types  that matrix's core Sample Type (core offers the profile only
                  for samples of that type)
    services      the analytes the Analyte x Matrix table includes there

The profiles this writes are recorded (portal annotation KEY), so a profile a
person made in core is never touched. A matrix that leaves the method has its
profile deactivated, not deleted: samples registered with it keep it.

    plan(...)            pure: what each profile should hold
    sync_method(...)     write one method's profiles; returns what it did
"""
from __future__ import absolute_import, unicode_literals

import logging
import re

logger = logging.getLogger("senaite.pfas.analysis_profiles")

KEY = "senaite.pfas.generated_analysis_profiles"     # {method_id: {Sample Type uid: profile uid}}
DESCRIPTION = (u"Generated from the method profile's Analyte x Matrix table. "
               u"Change the panel there: edits made here are replaced on its next save.")


def profile_key(method_id, matrix):
    slug = re.sub(r"[^a-z0-9]+", "-", ("%s" % matrix).lower()).strip("-")
    return u"pfas-%s-%s" % (("%s" % method_id).lower().replace("_", "-"), slug)


def plan(method_id, method_title, matrices, included, service_uids, sampletype_uids):
    """[{"matrix", "title", "key", "sampletype_uid", "service_uids", "problems"}]

    matrices        the method's matrices, in order
    included        {matrix: [analyte keyword]}  (the Analyte x Matrix table)
    service_uids    {keyword: core service uid}
    sampletype_uids {matrix title: core Sample Type uid}
    """
    out = []
    for matrix in matrices:
        problems = []
        st = sampletype_uids.get(matrix)
        if not st:
            problems.append(u"no core Sample Type is named %s" % matrix)
        kws = list(included.get(matrix) or [])
        missing = [k for k in kws if k not in service_uids]
        if missing:
            problems.append(u"no core analysis service for %s" % u", ".join(missing))
        uids = [service_uids[k] for k in kws if k in service_uids]
        if not uids:
            problems.append(u"no analyte is included for %s" % matrix)
        out.append({"matrix": matrix, "title": u"%s – %s" % (method_title, matrix),
                    "key": profile_key(method_id, matrix), "sampletype_uid": st,
                    "service_uids": uids, "problems": problems})
    return out


def _store(portal):
    from persistent.mapping import PersistentMapping
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    if KEY not in ann:
        ann[KEY] = PersistentMapping()
    return ann[KEY]


def generated(portal, method_id):
    """{Sample Type uid: profile uid} of the profiles written for a method.
    Keyed by the Sample Type, not its title: a renamed Sample Type keeps its
    profile (matrix_rename.py)."""
    from zope.annotation.interfaces import IAnnotations
    return dict((IAnnotations(portal).get(KEY) or {}).get(method_id) or {})


def _by_sampletype(api, mine):
    """Re-key a stored map by Sample Type uid (maps written before 2026-10-05
    were keyed by matrix title): read each profile's own Sample Type."""
    out = {}
    for key, puid in mine.items():
        obj = api.get_object_by_uid(puid, default=None)
        st = (obj.getRawSampleTypes() or [None])[0] if obj is not None else None
        out[st or key] = puid
    return out


def sync_method(portal, method_id, profile=None):
    """Write the method's Analysis Profiles. Returns [line] of what was done
    or could not be (a matrix with no Sample Type gets no profile)."""
    from bika.lims import api
    from senaite.pfas import method_profile_store as mps
    from senaite.pfas.method_bridge import get_core_method

    profile = profile if profile is not None else mps.get_profile(portal, method_id)
    method = get_core_method(portal, method_id)
    title = (method.Title() if method is not None else None) or profile.get("display_name") or method_id
    matrices = list(profile.get("supported_matrices") or [])
    setup_cat = api.get_tool("senaite_catalog_setup")
    service_uids = dict((b.getObject().getKeyword(), b.UID)
                        for b in setup_cat(portal_type="AnalysisService"))
    # exact titles: the catalog's Title index is a text index, and "Water"
    # would match three Sample Types
    titles = dict((b.getObject().Title(), b.UID) for b in setup_cat(portal_type="SampleType"))
    st_uids = dict((m, titles[m]) for m in matrices if m in titles)
    included = dict((m, mps.get_included_analytes(portal, method_id, m)) for m in matrices)

    folder = api.get_senaite_setup().analysisprofiles
    store = _store(portal)
    mine = _by_sampletype(api, dict(store.get(method_id) or {}))
    report = []
    for p in plan(method_id, title, matrices, included, service_uids, st_uids):
        if not p["sampletype_uid"] or not p["service_uids"]:
            report.extend(u"%s: %s" % (p["matrix"], x) for x in p["problems"])
            continue
        key = p["sampletype_uid"]
        obj = api.get_object_by_uid(mine.get(key), default=None) if mine.get(key) else None
        if obj is None:
            obj = api.create(folder, "AnalysisProfile", title=p["title"])
            report.append(u"%s: profile created" % p["matrix"])
        obj.setTitle(p["title"])
        obj.setDescription(DESCRIPTION)
        obj.setProfileKey(p["key"])
        obj.setSampleTypes([p["sampletype_uid"]])
        obj.setServices(p["service_uids"], keep_inactive=False)
        if not api.is_active(obj):
            api.do_transition_for(obj, "activate")
        obj.reindexObject()
        mine[key] = api.get_uid(obj)
        report.extend(u"%s: %s" % (p["matrix"], x) for x in p["problems"])
    current = set(st_uids.values())
    for st_uid, uid in list(mine.items()):
        if st_uid in current:
            continue
        obj = api.get_object_by_uid(uid, default=None)
        if obj is not None and api.is_active(obj):
            api.do_transition_for(obj, "deactivate")
            report.append(u"%s: profile deactivated (matrix left the method)" % obj.Title())
    from persistent.mapping import PersistentMapping
    store[method_id] = PersistentMapping(mine)
    return report


# ── a sample registered with a generated profile is that method's ──────────
# Analytes belong to several methods (PFOA to all three), so core gives an
# analysis no default method; a sample registered with one of these profiles
# names its method, and its analyses carry it (: the
# batch's method is read from its analyses first).

def method_for_profile(portal, profile_uid):
    """The method id whose generated profile `profile_uid` is, or u""."""
    from zope.annotation.interfaces import IAnnotations
    for method_id, mine in (IAnnotations(portal).get(KEY) or {}).items():
        if profile_uid in (mine or {}).values():
            return method_id
    return u""


def apply_method(sample):
    """Set the method of the sample's analyses from its generated profile,
    where the analysis has none and its service allows it. Returns how many
    were set."""
    from bika.lims import api
    from senaite.pfas.method_bridge import get_core_method
    portal = api.get_portal()
    mids = set(m for m in (method_for_profile(portal, api.get_uid(p))
                           for p in (sample.getProfiles() or [])) if m)
    if len(mids) != 1:
        return 0                     # none of ours, or two methods: not guessed
    method = get_core_method(portal, mids.pop())
    if method is None:
        return 0
    n = 0
    for an in sample.getAnalyses(full_objects=True):
        if an.getMethod() is None and an.isMethodAllowed(method):
            an.setMethod(method)
            an.reindexObject()
            n += 1
    return n


def on_sample_changed(sample, event):
    """IObjectAddedEvent / IAfterTransitionEvent on a sample."""
    try:
        apply_method(sample)
    except Exception:                                       # noqa: BLE001
        logger.warning("analysis methods not set from the profile", exc_info=True)
