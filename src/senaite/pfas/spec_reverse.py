# -*- coding: utf-8 -*-
"""
SENAITE AnalysisSpecs are a READ-ONLY copy of the method profile
(DECISIONS 2026-10-02, D4).

spec_sync writes one AnalysisSpec per method x QC type x matrix from the
profile's recovery tiers. An edit made on SENAITE's own spec screen to one of
those specs used to be written back into the profile as a per-analyte
`spec_overrides` entry -- a layer the QC engine never read and the method
editor never showed. Now the edit is PUT BACK from the profile and a warning
names where to change it: the Method Profile's Recovery Tiers.

Loop-safe: no-op while spec_sync itself is writing (is_forward_syncing), and
the restore only rewrites specs that differ (spec_sync.same_ranges).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.spec_reverse")

QC_TYPES = ("LFB", "LFSM", "LFSMD")


def _identify_spec(portal, spec):
    """Return (method_id, qc_type, matrix_title) if this is a spec_sync-managed
    spec, else (None, None, None). Matches by reconstructing the per-matrix id
    spec_sync uses — avoids lossy parsing of the lowercased id."""
    try:
        sid = spec.getId()
    except Exception:
        return None, None, None
    if not sid or not sid.endswith("-recovery"):
        return None, None, None
    try:
        from senaite.pfas.method_profile_store import list_method_ids, get_profile
        from senaite.pfas.spec_sync import spec_id_for
        method_ids = list_method_ids(portal)
    except Exception:
        return None, None, None
    for mid in method_ids:
        try:
            prof = get_profile(portal, mid)
            matrices = prof.get("supported_matrices") or []
            # QC types derive from the profile (matches spec_sync) — falls back
            # to the static tuple for robustness on malformed profiles.
            qc_types = sorted((prof.get("qc_acceptance") or {}).keys()) or QC_TYPES
        except Exception:
            continue
        for qc in qc_types:
            for mtx in matrices:
                if spec_id_for(mid, qc, mtx) == sid:
                    return mid, qc, mtx
    return None, None, None


def on_spec_modified(spec, event):
    """IObjectModifiedEvent handler for AnalysisSpec: restore a managed spec
    from the method profile (read-only copy, D4)."""
    try:
        from senaite.pfas import spec_sync
        if spec_sync.is_forward_syncing():
            return                      # our own write

        from Products.CMFCore.utils import getToolByName
        portal = getToolByName(spec, "portal_url").getPortalObject()

        method_id, qc_type, matrix_title = _identify_spec(portal, spec)
        if not method_id:
            return

        from senaite.pfas.method_profile_store import get_profile
        profile = get_profile(portal, method_id)
        kw_to_tier = spec_sync._build_kw_to_tier(profile)
        tier_lims = spec_sync._tier_limits(profile.get("qc_acceptance", {}), qc_type)
        if not kw_to_tier or tier_lims is None:
            return
        is_tight = matrix_title in set(spec_sync.get_tight_matrices(profile))
        expected = spec_sync._build_results_range(kw_to_tier, tier_lims, None,
                                                  is_tight=is_tight)
        if spec_sync.same_ranges(spec.getResultsRange() or [], expected):
            return
        spec_sync.sync_analysis_specs(portal, method_id, profile,
                                      triggered_by=u"read-only restore")
        logger.warning(
            "AnalysisSpec %s was edited on SENAITE's spec screen; restored from the "
            "%s method profile. Change %s limits on the Method Profile's Recovery "
            "Tiers tab.", spec.getId(), method_id, qc_type)
    except Exception as exc:
        # Never break the user's spec save on a restore error.
        logger.warning("spec restore failed for %r: %s", spec, exc)
