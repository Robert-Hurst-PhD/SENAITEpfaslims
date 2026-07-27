# -*- coding: utf-8 -*-
"""
Reverse sync: AnalysisSpec edit → Method Profile per-analyte override.

The AnalysisSpec is a **write-through editing surface**, not a second master.
The Method Profile remains the single source of truth (CLAUDE.md §1.3). When a
user edits a spec_sync-managed AnalysisSpec's ResultsRange in SENAITE, the
changed analytes are written into

    profile['spec_overrides'][qc_type][analyte_keyword] = {"min": ..., "max": ...}

as PER-ANALYTE exceptions (user decision: editing one analyte does NOT move its
tier siblings). An analyte whose edited range returns to its tier default has
its override removed. The profile is then re-saved, which regenerates the spec
via forward sync — so both screens agree with one source of truth.

Loop-safe:
  * no-op while a forward sync is writing specs (spec_sync.is_forward_syncing);
  * write-back only on a NUMERICALLY-normalized difference (rounded floats, not
    strings), so profile-save → spec-write → modified-event settles in one pass.

Scoped tightly: only fires for specs whose id matches a method×qc-type that
spec_sync manages; everything else no-ops immediately.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.spec_reverse")

QC_TYPES = ("LFB", "LFSM", "LFSMD")
_ROUND = 4


def _num(v):
    """Normalize a limit to a rounded float, or None if blank/non-numeric."""
    if v is None or v == "":
        return None
    try:
        return round(float(v), _ROUND)
    except (TypeError, ValueError):
        return None


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
    """IObjectModifiedEvent handler for AnalysisSpec — write-through to profile."""
    try:
        from senaite.pfas import spec_sync
        # Never react to our own forward-sync writes (loop prevention).
        if spec_sync.is_forward_syncing():
            return

        from Products.CMFCore.utils import getToolByName
        portal = getToolByName(spec, "portal_url").getPortalObject()

        method_id, qc_type, matrix_title = _identify_spec(portal, spec)
        if not method_id:
            return

        from senaite.pfas.method_profile_store import get_profile, save_profile
        profile = get_profile(portal, method_id)

        kw_to_tier = spec_sync._build_kw_to_tier(profile)
        tier_lims = spec_sync._tier_limits(profile.get("qc_acceptance", {}), qc_type)
        if not kw_to_tier or tier_lims is None:
            return

        # Matrix-effective tier: tier 1 applies only in tight matrices.
        is_tight = matrix_title in set(spec_sync.get_tight_matrices(profile))

        spec_ranges = {r.get("keyword", ""): r
                       for r in (spec.getResultsRange() or [])}

        # Overrides are keyed per qc_type × MATRIX × analyte, so editing the
        # Eggs spec never bleeds into Milk. (Legacy flat per-qc overrides are
        # read by overrides_for(); we always WRITE the nested shape.)
        overrides = dict(spec_sync.overrides_for(profile, qc_type, matrix_title))
        changed = False

        for kw, tier in kw_to_tier.items():
            r = spec_ranges.get(kw)
            if not r:
                continue
            s_min, s_max = _num(r.get("min")), _num(r.get("max"))
            eff = spec_sync.effective_tier(tier, is_tight)
            lims = tier_lims.get(eff) or tier_lims.get(2) or {}
            t_min, t_max = _num(lims.get("min")), _num(lims.get("max"))

            if s_min == t_min and s_max == t_max:
                # back to the tier default → drop any exception
                if kw in overrides:
                    del overrides[kw]
                    changed = True
            else:
                new_ov = {"min": s_min, "max": s_max}
                if overrides.get(kw) != new_ov:
                    overrides[kw] = new_ov
                    changed = True

        if not changed:
            return

        # merge back (nested by matrix)
        all_overrides = dict(profile.get("spec_overrides", {}) or {})
        qc_ov = dict(all_overrides.get(qc_type, {}) or {})
        # If legacy flat shape, rebase it under every matrix before nesting.
        first = next(iter(qc_ov.values())) if qc_ov else None
        if isinstance(first, dict) and ("min" in first or "max" in first):
            qc_ov = {m: dict(qc_ov)
                     for m in (profile.get("supported_matrices") or [])}
        if overrides:
            qc_ov[matrix_title] = overrides
        else:
            qc_ov.pop(matrix_title, None)
        if qc_ov:
            all_overrides[qc_type] = qc_ov
        else:
            all_overrides.pop(qc_type, None)
        profile["spec_overrides"] = all_overrides

        # Write-through to the single source of truth. save_profile runs the
        # forward sync, which sets is_forward_syncing() so this handler no-ops
        # on the resulting spec write → converges in one pass.
        save_profile(portal, method_id, profile)
        logger.info("reverse sync: %s/%s/%s — %d per-analyte override(s)",
                    method_id, qc_type, matrix_title, len(overrides))

    except Exception as exc:
        # Never break the user's spec save on a reverse-sync error.
        logger.warning("reverse sync failed for %r: %s", spec, exc)
