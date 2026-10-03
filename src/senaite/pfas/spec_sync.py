# -*- coding: utf-8 -*-
"""
Sync PFAS QC acceptance limits to SENAITE AnalysisSpec objects.

Called from save_profile() after every method profile save.  For each enabled
QC type (LCS, LFSM, LFB ...) that carries recovery min/max limits, this module
finds or creates:
  - A SampleType  "{method_label} {QC_TYPE}" in bika_setup/bika_sampletypes
  - An AnalysisSpec "{method_label} – {QC_TYPE} Recovery" in bika_analysisspecs

ResultsRange entries are written for every analyte in master_analyte_set, with
min/max drawn from the matching recovery tier in qc_acceptance.

A native SENAITE snapshot is taken after every update so the change appears in
the standard Audit Log viewlet.  A compact summary is also stored in portal
annotations under PFAS_SPEC_AUDIT_KEY for quick retrieval by the PFAS UI.

Python 2.7 compatible — no f-strings, no pathlib, no annotation syntax.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging
import threading

logger = logging.getLogger("senaite.pfas.spec_sync")

PFAS_SPEC_AUDIT_KEY = "senaite.pfas.spec_sync_audit"
MAX_AUDIT_ENTRIES = 500

# Forward-sync re-entrancy guard. Set while spec_sync writes specs so the
# reverse-sync subscriber (spec_reverse) no-ops and the forward↔reverse loop
# cannot run. Thread-local: Zope is multi-threaded.
_SYNC_GUARD = threading.local()


def is_forward_syncing():
    """True while a forward sync (profile → spec) is writing specs."""
    return getattr(_SYNC_GUARD, "active", False)

# QC type → human label used in SampleType / AnalysisSpec titles
_QC_LABELS = {
    "LCS":   "Laboratory Control Sample",
    "LFSM":  "Lab Fortified Sample Matrix",
    "LFB":   "Laboratory Fortified Blank",
    "LFSMD": "Lab Fortified Sample Matrix Dup",
    "MB":    "Method Blank",
    "LRB":   "Laboratory Reagent Blank",
}

# ── Internal helpers ──────────────────────────────────────────────────────────

def _current_user():
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        uid = user.getId()
        return uid or "system"
    except Exception:
        return "system"


def _build_kw_to_tier(profile):
    """Return {keyword: tier_int(1|2|3)} for every analyte in master_analyte_set.

    Tier values: 1=key (tight), 2=linked (standard), 3=no-labeled-std.
    "No labelled standard" is derived from the method's own surrogate links
    and key analytes are the method's own list (consolidation P4) -- the
    engine's rule, so the specs match what results are judged by.
    """
    from senaite.pfas.method_profile_sections import key_analytes, no_std_set
    keys, no_std = set(key_analytes(profile)), no_std_set(profile)
    return dict((kw, 3 if kw in no_std else (1 if kw in keys else 2))
                for kw in profile.get("master_analyte_set", []))


def _tier_limits(qc_acceptance, qc_type):
    """Return {1: {min,max}, 2: {min,max}, 3: {min,max}} for a QC type.

    Returns None when the QC type is disabled or has no recovery tiers.
    """
    qca = qc_acceptance.get(qc_type, {})
    if not qca.get("enabled"):
        return None

    tier_limits = {1: None, 2: None, 3: None}
    fallback = None

    for t in qca.get("tiers", []):
        r_min = t.get("recovery_min")
        r_max = t.get("recovery_max")
        if r_min is None and r_max is None:
            continue
        # A low-level tier (low_level_x_rl, GAPS §71) applies only to spikes
        # at or below N x RL -- a condition a SENAITE spec cannot hold. It used
        # to fall through as "all" and, listed after the ordinary tier, became
        # every analyte's window (EPA 537.1 LFSM showed 50-150 % for every
        # result, not 70-130 %). GAPS §96.
        if t.get("low_level_x_rl") is not None:
            continue
        lims = {"min": r_min, "max": r_max}
        ag = t.get("analyte_group", "all")
        if ag == "key":
            tier_limits[1] = lims
        elif ag == "linked":
            tier_limits[2] = lims
        elif ag == "no_std":
            tier_limits[3] = lims
        else:
            fallback = lims

    # Apply fallback to tiers that have no specific entry
    for n in (1, 2, 3):
        if tier_limits[n] is None and fallback:
            tier_limits[n] = fallback

    has_recovery = any(v for v in tier_limits.values())
    return tier_limits if has_recovery else None


# FDA Table 10-1: key analytes are held to the tight range (80–120) only in
# these matrices; elsewhere they fall to the linked/all range. Seed default per
# CLAUDE.md §3 ("egg/meat/seafood"); a profile may override via its own
# `tight_matrices` list (configurable, not hardcoded — golden rule #1).
_DEFAULT_TIGHT_MATRICES = ("Eggs", "Meat / Muscle", "Fish / Seafood")


def get_tight_matrices(profile):
    """Matrix titles where matrix_scope='tight' tiers apply, from the profile
    (falls back to the CLAUDE.md seed trio)."""
    tm = profile.get("tight_matrices")
    if isinstance(tm, (list, tuple)) and tm:
        return list(tm)
    return list(_DEFAULT_TIGHT_MATRICES)


def effective_tier(tier, is_tight_matrix):
    """FDA matrix-dependent tier: tier 1 (key/tight 80–120) applies only in
    tight matrices; elsewhere key analytes use the tier-2 (all) range."""
    if tier == 1 and not is_tight_matrix:
        return 2
    return tier


def matrix_slug(title):
    """Stable id fragment for a matrix title (e.g. 'Meat / Muscle' -> 'meat-muscle')."""
    out = []
    for ch in (title or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def same_ranges(old_rows, new_rows):
    """True when two ResultsRange lists set the same limits per analyte
    (numbers compared as numbers; row order and comments ignored)."""
    def norm(rows):
        out = {}
        for r in rows or []:
            vals = []
            for k in ("min", "max"):
                v = r.get(k)
                try:
                    vals.append(round(float(v), 6))
                except (TypeError, ValueError):
                    vals.append(None)
            out[r.get("keyword", "")] = tuple(vals)
        return out
    return norm(old_rows) == norm(new_rows)


def _build_results_range(kw_to_tier, tier_lims, overrides=None, is_tight=True):
    """Build the ResultsRange list for setResultsRange() for ONE matrix.

    Per-analyte overrides win over the analyte's (matrix-effective) tier
    default — the write-through target of reverse sync. Tier 1 collapses to
    tier 2 outside tight matrices (FDA Table 10-1).
    """
    overrides = overrides or {}
    rows = []
    for kw in sorted(kw_to_tier):
        tier = effective_tier(kw_to_tier[kw], is_tight)
        lims = tier_lims.get(tier) or tier_lims.get(2) or {}
        ov = overrides.get(kw)
        if ov:
            r_min, r_max = ov.get("min"), ov.get("max")
            comment = "Per-analyte override (PFAS)"
        else:
            r_min, r_max = lims.get("min"), lims.get("max")
            comment = "Tier %d recovery limit (PFAS auto-sync)" % tier
        rows.append({
            "keyword":      kw,
            "min_operator": "geq",
            "min":          str(r_min if r_min is not None else ""),
            "max_operator": "leq",
            "max":          str(r_max if r_max is not None else ""),
            "warn_min":     "",
            "warn_max":     "",
            "hidemin":      "0",
            "hidemax":      "0",
            "rangecomment": comment,
        })
    return rows


# NOTE: the old _get_or_create_sample_type (synthetic "{method} {QC}" sample
# types) was REMOVED — specs now link to the real matrix SampleTypes. See
# migrations/cleanup_synthetic_qc_sampletypes.py for the data cleanup.


def spec_id_for(method_id, qc_type, matrix_title):
    """Deterministic spec id for method × QC type × matrix — shared with the
    reverse-sync identifier so both sides agree."""
    return "{0}-{1}-{2}-recovery".format(
        method_id, qc_type, matrix_slug(matrix_title)).lower().replace("_", "-")


def _get_or_create_spec(portal, method_id, method_label, qc_type, matrix_title,
                        sample_type):
    """Find or create the AnalysisSpec for method × QC type × matrix, linked to
    the REAL SampleType for that matrix (never a synthetic QC sample type)."""
    title = u"{0} – {1} Recovery ({2})".format(method_label, qc_type, matrix_title)
    spec_id = spec_id_for(method_id, qc_type, matrix_title)

    folder = getattr(portal.bika_setup, "bika_analysisspecs", None)
    if folder is None:
        logger.warning("spec_sync: bika_analysisspecs folder not found")
        return None
    if spec_id in folder:
        return folder[spec_id]

    try:
        folder.invokeFactory("AnalysisSpec", id=spec_id)
        spec = folder[spec_id]
        spec.setTitle(title)
        if sample_type is not None:
            spec.setSampleType(sample_type)
        try:
            spec.reindexObject()
        except Exception:
            pass
        logger.info("spec_sync: created AnalysisSpec '%s'", title)
        return spec
    except Exception as exc:
        logger.warning("spec_sync: cannot create AnalysisSpec %s: %s", title, exc)
        return None


def _take_native_snapshot(spec, method_label, qc_type, triggered_by):
    """Take a SENAITE native audit snapshot on the AnalysisSpec. qc_type may
    be a QC code (sync) or the pseudo-actions 'retire'/'reactivate'."""
    try:
        from bika.lims.api.snapshot import take_snapshot
        if qc_type == "retire":
            action, comment = "PFAS Retire", (
                u"Spec RETIRED (deactivated): its QC type/matrix is no longer "
                u"produced by PFAS method profile ‘{0}’. By {1}.".format(
                    method_label, triggered_by))
        elif qc_type == "reactivate":
            action, comment = "PFAS Reactivate", (
                u"Spec reactivated: its QC type/matrix is again produced by "
                u"PFAS method profile ‘{0}’. By {1}.".format(
                    method_label, triggered_by))
        else:
            action, comment = "PFAS Sync", (
                u"QC acceptance limits auto-synced from PFAS method profile "
                u"‘{0}’ by {1}.".format(method_label, triggered_by))
        take_snapshot(spec, action=action, comments=comment)
    except Exception as exc:
        logger.warning("spec_sync: snapshot failed for %s/%s: %s",
                       method_label, qc_type, exc)


def _write_pfas_audit(portal, entry):
    """Append entry to the PFAS spec-sync audit log in portal annotations."""
    from zope.annotation.interfaces import IAnnotations
    from persistent.list import PersistentList

    try:
        ann = IAnnotations(portal)
        if PFAS_SPEC_AUDIT_KEY not in ann:
            ann[PFAS_SPEC_AUDIT_KEY] = PersistentList()
        log = ann[PFAS_SPEC_AUDIT_KEY]
        log.append(entry)
        if len(log) > MAX_AUDIT_ENTRIES:
            del log[:len(log) - MAX_AUDIT_ENTRIES]
    except Exception as exc:
        logger.error("spec_sync: cannot write PFAS audit entry: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

def sync_analysis_specs(portal, method_id, profile, triggered_by=None):
    """Public entry — sets the forward-sync guard so the reverse-sync subscriber
    no-ops while specs are being written (prevents the forward↔reverse loop)."""
    _SYNC_GUARD.active = True
    try:
        return _sync_analysis_specs(portal, method_id, profile, triggered_by)
    finally:
        _SYNC_GUARD.active = False


def _sync_analysis_specs(portal, method_id, profile, triggered_by=None):
    """Sync PFAS QC acceptance limits to SENAITE AnalysisSpec objects.

    For each enabled QC type in qc_acceptance that has recovery min/max limits,
    this function finds or creates an AnalysisSpec in bika_analysisspecs and
    writes one ResultsRange row per analyte (with the appropriate tier limits).

    A SENAITE native snapshot is taken on every spec that is created or updated,
    making the change visible in the standard Audit Log viewlet.  A compact
    summary is also written to the PFAS annotation audit log.

    Exceptions are caught and logged — a sync failure never blocks profile save.
    """
    import datetime

    if triggered_by is None:
        triggered_by = _current_user()

    method_label = profile.get("display_name", method_id)
    qc_acceptance = profile.get("qc_acceptance", {})

    kw_to_tier = _build_kw_to_tier(profile)
    if not kw_to_tier:
        logger.info("spec_sync: no analyte tier data for %s — skip", method_id)
        return

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    audit_specs = []

    # One spec per QC type × REAL matrix (SENAITE matches specs to samples by
    # SampleType, so specs must reference the matrices samples actually carry).
    matrices = profile.get("supported_matrices") or []
    tight = set(get_tight_matrices(profile))

    from senaite.pfas.matrix_ref import resolve as _resolve_matrix
    # Display names come from the tagged core Reference Definitions (single
    # UI-editable source); _QC_LABELS is only an offline fallback.
    from senaite.pfas.qc_labels import get_qc_label_map, qc_label as _qc_label
    _label_map = get_qc_label_map(portal)

    # QC types derive from the profile's qc_acceptance keys — a newly
    # associated QC type syncs automatically; a disabled one is filtered by
    # _tier_limits (enabled flag + recovery ranges). No hardcoded tuple.
    for qc_type in sorted(qc_acceptance.keys()):
        tier_lims = _tier_limits(qc_acceptance, qc_type)
        if tier_lims is None:
            continue
        qc_label = _qc_label(None, qc_type, default=_QC_LABELS.get(qc_type, qc_type),
                             label_map=_label_map)

        for matrix_title in matrices:
            try:
                st_info = _resolve_matrix(portal, matrix_title)
                sample_type = st_info.get("obj")
                if sample_type is None:
                    logger.warning(
                        "spec_sync: no core SampleType for matrix %r — skipped",
                        matrix_title)
                    continue

                is_tight = matrix_title in tight
                # SENAITE specs are a READ-ONLY copy of the profile (D4): no
                # per-analyte overrides from the spec screen
                ranges = _build_results_range(kw_to_tier, tier_lims, None,
                                              is_tight=is_tight)
                if not ranges:
                    continue

                spec = _get_or_create_spec(
                    portal, method_id, method_label, qc_type, matrix_title,
                    sample_type)
                if spec is None:
                    continue

                old_rows = spec.getResultsRange() or []
                try:
                    current_st = spec.getSampleType()
                except Exception:
                    current_st = None
                st_ok = current_st is not None and (
                    getattr(current_st, "UID", lambda: None)() == sample_type.UID())
                if st_ok and same_ranges(old_rows, ranges):
                    continue      # unchanged: no write, no snapshot (P1)

                # Re-assert the real SampleType (heals pre-existing specs that
                # pointed elsewhere).
                if not st_ok:
                    try:
                        spec.setSampleType(sample_type)
                    except Exception as exc:
                        logger.warning("spec_sync: cannot set SampleType on %s: %s",
                                       spec.getId(), exc)

                old_map = {r.get("keyword", ""): r for r in old_rows}

                spec.setResultsRange(ranges)
                spec.setDescription(
                    u"Auto-synced from PFAS method profile ‘{0}’ on {1} by {2}. "
                    u"{3} ({4}) recovery limits for matrix ‘{5}’{6}.".format(
                        method_label, ts[:10], triggered_by, qc_type, qc_label,
                        matrix_title,
                        u" — tight-matrix tier 1 applies" if is_tight else u""))
                try:
                    spec.reindexObject()
                except Exception:
                    pass

                _take_native_snapshot(spec, method_label, qc_type, triggered_by)

                new_map = {r["keyword"]: r for r in ranges}
                changed = [
                    kw for kw, new_r in new_map.items()
                    if old_map.get(kw, {}).get("min") != new_r["min"]
                    or old_map.get(kw, {}).get("max") != new_r["max"]
                ]

                audit_specs.append({
                    "qc_type":   qc_type,
                    "matrix":    matrix_title,
                    "spec_id":   spec.getId(),
                    "n_ranges":  len(ranges),
                    "n_changed": len(changed),
                })

            except Exception as exc:
                logger.error("spec_sync: error for %s/%s/%s: %s",
                             method_id, qc_type, matrix_title, exc)

        logger.info("spec_sync: %s/%s — %d matrices synced",
                    method_id, qc_type, len(matrices))

    # ── Retirement: deactivate specs no longer produced by this profile ────
    # (QC type disabled, matrix removed, tiers dropped). Reactivate on
    # re-enable. Both transitions are snapshotted → visible in the Audit Log.
    try:
        from bika.lims import api as _api
        folder = getattr(portal.bika_setup, "bika_analysisspecs", None)
        expected = set()
        for qc_type in qc_acceptance.keys():
            if _tier_limits(qc_acceptance, qc_type) is None:
                continue
            for mtx in matrices:
                expected.add(spec_id_for(method_id, qc_type, mtx))
        prefix = method_id.lower().replace("_", "-") + "-"
        for sid in (folder.objectIds() if folder is not None else []):
            if not (sid.startswith(prefix) and sid.endswith("-recovery")):
                continue
            spec = folder[sid]
            state = _api.get_workflow_status_of(spec)
            if sid not in expected and state == "active":
                _api.do_transition_for(spec, "deactivate")
                _take_native_snapshot(spec, method_label, "retire", triggered_by)
                audit_specs.append({"qc_type": "-", "spec_id": sid,
                                    "action": "retired"})
                logger.info("spec_sync: retired %s (no longer produced)", sid)
            elif sid in expected and state != "active":
                _api.do_transition_for(spec, "activate")
                _take_native_snapshot(spec, method_label, "reactivate",
                                      triggered_by)
                audit_specs.append({"qc_type": "-", "spec_id": sid,
                                    "action": "reactivated"})
                logger.info("spec_sync: reactivated %s", sid)
    except Exception as exc:
        logger.warning("spec_sync: retirement pass failed for %s: %s",
                       method_id, exc)

    if audit_specs:
        _write_pfas_audit(portal, {
            "ts":        ts,
            "user":      triggered_by,
            "method_id": method_id,
            "specs":     audit_specs,
        })
