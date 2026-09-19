# -*- coding: utf-8 -*-
"""
Three-tier QC criterion resolution:

    project QAPP ruleset  ->  lab method profile  ->  published-method baseline

CLAUDE.md's quality-system hierarchy: a client project's QAPP overrides the
lab's internal system for that project; the published analytical method is
the outer boundary nothing may silently cross. Work that goes below the
published method is never refused here -- it is reported. This module
resolves ONE criterion through the three tiers and returns, alongside the
resolved value, which tier supplied it and whether it conforms to, or departs
from, the published-method baseline (senaite.pfas.method_baselines). That
provenance is what lets a later phase derive an accurate non-conformance
statement for a certificate instead of someone hand-writing one.

Nothing in this add-on calls this module yet -- see GAPS.md. Do not add a
docstring anywhere that claims a consumer exists until one does.

Design: pure core, thin ZODB shell
-----------------------------------
`resolve()` is pure -- it takes an already-fetched method-profile dict and an
already-fetched project-ruleset dict (plain data, no Plone objects) and
returns a ResolvedCriterion. It imports nothing from zope/Plone/bika, so it
loads and runs under plain Python 3 by path
(`importlib.util.spec_from_file_location`), the same way holding_time.py
does, and tests/test_ruleset.py exercises it that way.

`resolve_for_batch()` is the thin shell: it fetches the real Project (via
senaite.pfas.project_ref, reused rather than re-derived), the real method
profile (via senaite.pfas.method_profile_store, READ-ONLY), and the real
project-ruleset annotation, then calls resolve(). `get_project_ruleset` /
`set_project_ruleset` / `set_project_criterion` are the ZODB-touching get/set
helpers for the project-tier annotation, following project_ref.py's pattern
of deferring `from zope.annotation.interfaces import IAnnotations` to inside
the function body so importing this module never requires Zope to be
installed.

Three refusals, not features (see resolve()'s docstring for where each is
enforced):
  1. No baseline recorded -> UNKNOWN, never CONFORMS.
  2. Silence at the project tier inherits the lab tier; it never nulls a
     criterion (GAPS.md Sec7.1 is the same defect shape at a different layer).
  3. A batch with no project (the default, and every batch that predates
     project support) resolves cleanly through lab then baseline.

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, unicode_literals

import collections
import json
import logging

logger = logging.getLogger("senaite.pfas.ruleset")

# method_baselines is, like this module, deliberately free of Plone/Zope
# imports -- but the NORMAL way to reach it (`from senaite.pfas import
# method_baselines`) goes through the senaite.pfas package `__init__`, which
# imports zope.i18nmessageid and so is unavailable outside the container.
# Inside the installed add-on this simply succeeds. Standalone (tests, a
# plain `python3` interpreter with no Zope installed), fall back to a
# path-relative import so this module still loads and runs unaided.
try:
    from senaite.pfas import method_baselines
except ImportError:
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import method_baselines  # noqa: E402  (standalone/test fallback)


# ── Tiers ──────────────────────────────────────────────────────────────────────
TIER_PROJECT = "project"
TIER_LAB = "lab"
TIER_BASELINE = "baseline"

PROJECT_RULESET_KEY = u"senaite.pfas.project.ruleset"


ResolvedCriterion = collections.namedtuple(
    "ResolvedCriterion",
    ["value", "key", "method_id", "matrix", "analyte", "tier",
     "source_doc", "source_rev", "conformance", "departure"],
)


# ── Criterion registry: shape + how to read it off a lab method profile ──────
#
# A criterion key not listed here cannot be resolved (resolve() raises) --
# that is a configuration error in the CALLER (an unregistered key), not a
# missing-data case. A key listed here with no entry in
# method_baselines._REGISTRY is a normal, expected case: it resolves fine at
# the project/lab tier, and its conformance is UNKNOWN because the published
# method was never verified for it (method_baselines.py explains which keys
# that covers and why).
#
# WINDOW-shaped values are always represented as {"min": x, "max": y} at every
# tier and in the returned ResolvedCriterion.value -- never a bare tuple. A
# window key is all-or-nothing per tier: if a tier supplies the key at all, it
# is taken as that tier's complete answer for both ends, even if one end is
# null within it (null there means "this tier declines to constrain this end",
# not "inherit the lower tier's value for this end"). Only the ABSENCE of the
# key at a tier falls through to the next tier. This is a deliberate
# simplification; per-end fallthrough within one window is not supported.
SHAPES_BY_KEY = {
    "cal_r2_min":   method_baselines.SHAPE_MIN,
    "sn_quan_min":  method_baselines.SHAPE_MIN,
    # Reads the lab's Dup (duplicate) rpd_max specifically -- LFSMD carries
    # its own, separate rpd_max on a different QC type and is NOT what this
    # key reads. The name says which one on purpose; register a distinct
    # "lfsmd_rpd_max" if that is ever needed rather than overloading this one.
    "dup_rpd_max":  method_baselines.SHAPE_MAX,
    "ccv_recovery": method_baselines.SHAPE_WINDOW,
    "eis_recovery": method_baselines.SHAPE_WINDOW,
}

# Criterion keys that are per-analyte, not per-method x matrix alone. Their
# stored value (at the project tier, and as read off the lab profile) is
# keyed one level deeper, by analyte display name.
ANALYTE_SCOPED_KEYS = frozenset(["eis_recovery"])


def _dig(mapping, path):
    """Walk a nested dict/list `path`, returning None on any miss instead of
    raising -- criterion lookups must degrade to "not configured", never to
    a KeyError/IndexError, since an incompletely-populated profile is the
    normal case (see method_profile_store.py's own UnconfiguredCriterion
    philosophy, which this mirrors without depending on that module)."""
    cur = mapping
    for step in path:
        if cur is None:
            return None
        if isinstance(step, int):
            if not isinstance(cur, (list, tuple)) or not (-len(cur) <= step < len(cur)):
                return None
            cur = cur[step]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(step)
    return cur


def _lab_ccv_recovery(profile, matrix, analyte):
    lo = _dig(profile, ["instrument_verification", "ccv", "recovery_min"])
    hi = _dig(profile, ["instrument_verification", "ccv", "recovery_max"])
    if lo is None and hi is None:
        return None
    return {"min": lo, "max": hi}


def _lab_eis_recovery(profile, matrix, analyte):
    if not analyte:
        return None
    value = None
    for row in (profile.get("eis_overrides") or []):
        if row.get("analyte") == analyte:
            lo = row.get("recovery_min")
            hi = row.get("recovery_max")
            if lo is not None or hi is not None:
                value = {"min": lo, "max": hi}
            break
    mclass = method_baselines.matrix_class(matrix) if matrix else "aqueous"
    if mclass != "aqueous":
        override = (profile.get("eis_matrix_overrides") or {}).get(mclass, {}).get(analyte)
        if override:
            value = {"min": override.get("recovery_min"),
                      "max": override.get("recovery_max")}
    return value


# key -> extractor(profile, matrix, analyte) -> resolved value or None.
_LAB_EXTRACTORS = {
    "cal_r2_min": lambda profile, matrix, analyte: _dig(
        profile, ["instrument_verification", "calibration", "r2_min"]),
    "sn_quan_min": lambda profile, matrix, analyte: _dig(
        profile, ["instrument_verification", "confirmation", "sn_quan_min"]),
    "dup_rpd_max": lambda profile, matrix, analyte: _dig(
        profile, ["qc_acceptance", "Dup", "tiers", 0, "rpd_max"]),
    "ccv_recovery": _lab_ccv_recovery,
    "eis_recovery": _lab_eis_recovery,
}


def _project_value(project_ruleset, method_id, matrix, key, analyte):
    """The project tier's value for this key, or None if the project ruleset
    is absent/empty or simply does not mention this key -- silence, which the
    caller must fall through on, never treat as a resolved null (rule 2)."""
    if not project_ruleset:
        return None
    node = _dig(project_ruleset, [method_id, matrix, key])
    if node is None:
        return None
    if key in ANALYTE_SCOPED_KEYS:
        if analyte is None:
            return None
        return node.get(analyte)
    return node


def _lab_value(profile, method_id, matrix, key, analyte):
    """The lab tier's value for this key, read from an already-fetched
    method-profile dict (method_profile_store.get_profile() shape), or None
    if the profile is absent or the extractor finds nothing configured."""
    if not profile:
        return None
    extractor = _LAB_EXTRACTORS.get(key)
    if extractor is None:
        return None
    return extractor(profile, matrix, analyte)


def resolve(method_id, matrix, key, analyte=None,
            profile=None, project_ruleset=None,
            project_doc=None, project_rev=None):
    """Resolve one QC criterion through project -> lab -> baseline.

    Pure function: `profile` and `project_ruleset` are plain dicts already
    fetched by the caller (resolve_for_batch() does that for the real
    system); this function touches no ZODB/Plone API.

    Parameters
    ----------
    method_id, matrix : the method and matrix scoping this criterion, exactly
        as every other analyte-bearing structure in this add-on is scoped
        (CLAUDE.md Sec3 rule 2).
    key : a key registered in SHAPES_BY_KEY. Unregistered keys raise
        ValueError -- that is a caller bug, not a missing-data case.
    analyte : required (and used) only for ANALYTE_SCOPED_KEYS; ignored
        otherwise.
    profile : the method profile dict for method_id, or None for "no profile
        available" (e.g. an unconfigured method) -- resolution then falls
        straight through to the baseline tier.
    project_ruleset : the project's ruleset dict (get_project_ruleset() shape),
        or None/{} for "no project" -- rule 3: this is the default,
        overwhelmingly common case, and resolves cleanly through lab then
        baseline exactly like any other absence.
    project_doc, project_rev : the controlled-document id/revision backing a
        PROJECT-tier value, supplied by the caller (resolve_for_batch() reads
        them from the Project's qapp_document_id). Only ever attached to a
        result whose tier is "project" -- see below.

    Returns
    -------
    A ResolvedCriterion. `tier` names the tier that actually supplied `value`;
    if none did (this key was configured nowhere at all), `tier` is
    "baseline" and `value` is whatever the baseline tier could supply (None if
    even that is unverified) -- there is always a tier reported, but reaching
    "baseline" this way is different from a genuine baseline-conforming value:
    check `value is None` to distinguish "resolved to the baseline" from
    "nothing resolved anywhere".

    `source_doc` / `source_rev` are populated ONLY for tier="project", from
    the caller-supplied project_doc/project_rev. For tier="lab" they are
    legitimately None -- the method profile carries no link to a controlling
    QAM/SOP revision today, and this function does not invent one. For
    tier="baseline" they are also None; the citation lives on the Baseline
    object instead (see `departure["citation"]` when conformance is DEPARTS).

    `conformance` is CONFORMS / DEPARTS / UNKNOWN. Rule 1: UNKNOWN whenever
    method_baselines.get_baseline() returns None for this (method_id, key,
    analyte, matrix) -- regardless of which tier supplied `value` -- because
    the system cannot claim conformance to a requirement it does not know.
    `departure` is populated (a dict) only when conformance is DEPARTS; it
    names, per shape.SHAPE_WINDOW end independently, which end loosened and by
    how much (method_baselines.compare() computes this; see its docstring for
    why a window's two ends are never combined into one verdict).
    """
    shape = SHAPES_BY_KEY.get(key)
    if shape is None:
        raise ValueError(
            "Unknown criterion key {0!r} -- register its shape in "
            "ruleset.SHAPES_BY_KEY before resolving it".format(key))

    tier = TIER_BASELINE
    source_doc = None
    source_rev = None
    value = None

    pv = _project_value(project_ruleset, method_id, matrix, key, analyte)
    if pv is not None:
        value = pv
        tier = TIER_PROJECT
        source_doc = project_doc
        source_rev = project_rev
    else:
        lv = _lab_value(profile, method_id, matrix, key, analyte)
        if lv is not None:
            value = lv
            tier = TIER_LAB
            # source_doc/source_rev stay None -- see resolve()'s docstring.
        # else: tier stays TIER_BASELINE, value filled in below if possible.

    baseline = method_baselines.get_baseline(method_id, key, analyte=analyte,
                                              matrix=matrix)

    if tier == TIER_BASELINE and baseline is not None:
        if shape == method_baselines.SHAPE_WINDOW:
            value = {"min": baseline.min_value, "max": baseline.max_value}
        elif shape == method_baselines.SHAPE_MIN:
            value = baseline.min_value
        else:
            value = baseline.max_value

    conformance = method_baselines.UNKNOWN
    verdicts = []
    if baseline is not None and value is not None:
        if shape == method_baselines.SHAPE_WINDOW:
            cmp_value = (value.get("min"), value.get("max"))
        else:
            cmp_value = value
        conformance, verdicts = method_baselines.compare(baseline, cmp_value)

    departure = None
    if conformance == method_baselines.DEPARTS:
        if shape == method_baselines.SHAPE_WINDOW:
            baseline_value = {"min": baseline.min_value, "max": baseline.max_value}
        elif shape == method_baselines.SHAPE_MIN:
            baseline_value = baseline.min_value
        else:
            baseline_value = baseline.max_value
        departure = {
            "baseline_value": baseline_value,
            "resolved_value": value,
            "citation": baseline.citation,
            "ends": [
                {"end": v.end, "baseline_value": v.baseline_value,
                 "resolved_value": v.resolved_value, "detail": v.detail}
                for v in verdicts if v.conformance == method_baselines.DEPARTS
            ],
        }

    return ResolvedCriterion(
        value=value, key=key, method_id=method_id, matrix=matrix,
        analyte=analyte, tier=tier, source_doc=source_doc,
        source_rev=source_rev, conformance=conformance, departure=departure,
    )


# ── Project-tier ZODB annotation: get/set helpers ────────────────────────────
# Follows senaite.pfas.project_ref's pattern exactly: defer the zope.annotation
# import to inside the function body so importing this module never requires
# Zope to be installed (see the try/except at the top of this file for why
# that matters here specifically).

def _annotations(project):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(project)


def get_project_ruleset(project):
    """The JSON ruleset dict stored on `project` (a PFASProject), or {} for
    no project, no ruleset ever set, or a corrupt annotation -- never raises.
    Mirrors project_ref.get_project()'s "absence is not an error" contract."""
    if project is None:
        return {}
    try:
        ann = _annotations(project)
    except Exception:
        return {}
    raw = ann.get(PROJECT_RULESET_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Corrupt project ruleset annotation on %r", project)
        return {}


def set_project_ruleset(project, ruleset):
    """Replace the WHOLE project ruleset annotation with `ruleset`.

    Prefer set_project_criterion() for a single edit -- see its docstring.
    This exists for bulk operations (import/export, migration) where
    replacing the whole thing really is the intent.
    """
    if project is None:
        return
    ann = _annotations(project)
    ann[PROJECT_RULESET_KEY] = json.dumps(ruleset or {})


def set_project_criterion(project, method_id, matrix, key, value):
    """Set one (method_id, matrix, key) criterion in the project ruleset,
    MERGING into whatever is already stored -- it never replaces the whole
    ruleset for a single-field edit.

    GAPS.md Sec7.1 records a method-profile form handler that ASSIGNED the
    whole payload from a partial POST, nulling every criterion the POST did
    not mention. A project-ruleset editor built the same way -- read the one
    field an operator changed, write the whole ruleset back -- would
    reproduce that exact defect at the project tier. Every write here goes
    through this merge so it structurally cannot.
    """
    ruleset = get_project_ruleset(project)
    ruleset.setdefault(method_id, {}).setdefault(matrix, {})[key] = value
    set_project_ruleset(project, ruleset)


def _project_source(portal, project):
    """(doc_id, active_rev_num) for the QAPP document a project names, or
    (None, None) if it names none, or (doc_id, None) if it names one with no
    active revision on file -- never fabricated (CLAUDE.md Sec8)."""
    doc_id = getattr(project, "qapp_document_id", None) or None
    if not doc_id:
        return None, None
    try:
        from senaite.pfas.browser.sop_documents import _get_revisions
        for rev in _get_revisions(portal, doc_id):
            if rev.get("status") == "active":
                return doc_id, rev.get("rev_num")
    except Exception:
        logger.warning("ruleset: could not read revisions for %s", doc_id)
    return doc_id, None


def resolve_for_batch(portal, batch, method_id, matrix, key, analyte=None):
    """resolve(), wired to a live Batch: fetches its linked Project (if any --
    senaite.pfas.project_ref), the project's ruleset annotation, the read-only
    method profile (senaite.pfas.method_profile_store), and the controlling
    QAPP document/revision, then delegates to resolve().

    A batch with no linked project -- every batch that predates project
    support, and the overwhelming default afterward -- passes an empty
    project_ruleset and resolves through lab then baseline exactly as
    resolve() does for any other caller; nothing here special-cases that
    path, which is rule 3.

    Zero call sites today; see GAPS.md for the entry recording that and which
    phase is expected to wire this in.
    """
    from senaite.pfas import project_ref
    from senaite.pfas import method_profile_store

    project = project_ref.get_project(portal, batch)
    project_ruleset = get_project_ruleset(project) if project is not None else {}
    project_doc, project_rev = (None, None)
    if project is not None:
        project_doc, project_rev = _project_source(portal, project)

    profile = method_profile_store.get_profile(portal, method_id)

    return resolve(method_id, matrix, key, analyte=analyte,
                    profile=profile, project_ruleset=project_ruleset,
                    project_doc=project_doc, project_rev=project_rev)
