# -*- coding: utf-8 -*-
"""
Three-tier QC criterion resolution:

    project QAPP ruleset  ->  lab method profile  ->  published-method baseline

The quality-system hierarchy: a client project's QAPP overrides the lab's
internal system for that project; the published analytical method is the
outer boundary nothing may silently cross. Work below the published method is
never refused here: it is reported. This module resolves ONE criterion
through the three tiers and returns, with the value, the tier that supplied
it and whether it conforms to, or departs from, the published-method baseline
(senaite.pfas.method_baselines), so a certificate's non-conformance statement
is derived, never hand-written.

Caller: senaite.pfas.resolved_criteria_store (export_resolved_criteria),
from project_ref.set_project_uid when a batch's project link is set; the
export fires only when the caller supplies a method_id and matrix.

Design: pure core, thin ZODB shell
-----------------------------------
`resolve()` is pure: it takes an already-fetched method-profile dict and
project-ruleset dict (plain data, no Plone objects) and returns a
ResolvedCriterion. It imports nothing from zope/Plone/bika, so it loads and
runs under plain Python 3 by path, as tests/test_ruleset.py loads it.

`resolve_for_batch()` is the thin shell: it fetches the Project
(senaite.pfas.project_ref), the method profile (method_profile_store,
READ-ONLY) and the project tier, then calls resolve(). The project tier is
DERIVED from the project's Project Specs (`ruleset_from_specs`, pure;
`get_project_ruleset` is its shell), never stored per project.

Three refusals (enforced in resolve()):
  1. No baseline recorded -> UNKNOWN, never CONFORMS.
  2. Silence at the project tier inherits the lab tier; it never nulls a
     criterion.
  3. A batch with no project resolves cleanly through lab then baseline.

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, unicode_literals

import collections

from senaite.pfas import labelled_standards
from senaite.pfas import method_baselines
from senaite.pfas import qc_tiers


# ── Tiers ──────────────────────────────────────────────────────────────────────
TIER_PROJECT = "project"
TIER_LAB = "lab"
TIER_BASELINE = "baseline"

# The project tier is DERIVED from Project Specs (get_project_ruleset),
# never stored separately.


ResolvedCriterion = collections.namedtuple(
    "ResolvedCriterion",
    ["value", "key", "method_id", "matrix", "analyte", "tier",
     "source_doc", "source_rev", "conformance", "departure", "set_by"],
)
# set_by is the level that supplied `value`: "project", "method", "analyte",
# "class:<name>" or "default" (the published method's own value, or none).
ResolvedCriterion.__new__.__defaults__ = (None,)


# ── Criterion registry: shape + how to read it off a lab method profile ──────
#
# A key not listed here raises in resolve(): a caller error, not missing
# data. A listed key with no entry in method_baselines._REGISTRY resolves at
# the project/lab tier with conformance UNKNOWN (method_baselines.py names
# those keys).
#
# WINDOW values are {"min": x, "max": y} at every tier and in
# ResolvedCriterion.value, never a tuple. A window key is all-or-nothing per
# tier: a tier that supplies the key answers both ends (a null end means
# "this tier does not constrain this end", not "inherit"); only an ABSENT key
# falls through to the next tier.
SHAPES_BY_KEY = {
    "cal_r2_min":   method_baselines.SHAPE_MIN,
    "sn_quan_min":  method_baselines.SHAPE_MIN,
    # the lab's Dup (duplicate) rpd_max only: LFSMD's own rpd_max is another
    # QC type and needs a key of its own, never this one
    "dup_rpd_max":  method_baselines.SHAPE_MAX,
    "ccv_recovery": method_baselines.SHAPE_WINDOW,
    "eis_recovery": method_baselines.SHAPE_WINDOW,

    # ── QC COMPOSITION keys (what QC runs, not its numeric limits) ──────────
    # A QAPP may require "all samples in duplicate" or "LFSM every 5
    # samples": read by run_builder / run_composition when a run is BUILT,
    # never when a result is judged. Same three-tier path; no baseline
    # (SEEDING DISCIPLINE below).
    #
    # ccv_frequency / lfsm_frequency are INTERVALS, "1 QC injection per N
    # samples": a larger N is LOOSER, so SHAPE_MAX (as dup_rpd_max), never
    # SHAPE_MIN, which would report QC run MORE often than the method
    # requires as a departure (tests/test_ruleset.py pins the direction).
    "ccv_frequency":  method_baselines.SHAPE_MAX,
    "lfsm_frequency": method_baselines.SHAPE_MAX,

    # duplicate_all_samples is a boolean floor, True/False read as 1/0:
    # requiring duplicates is the tighter requirement, and
    # method_baselines._verdict_min's `resolved < baseline` holds for it
    # (False < True). No baseline is registered (SEEDING DISCIPLINE below),
    # so compare() never runs on it; tests/test_ruleset.py proves the shape
    # with a synthetic baseline.
    "duplicate_all_samples": method_baselines.SHAPE_MIN,
}

def _flag(value):
    """A stored yes / no (the form writes "yes") as a boolean, so SHAPE_MIN
    compares True / False, never a string with a boolean; None when unset
    (the next tier decides)."""
    if value in (None, u"", ""):
        return None
    return value is True or (u"%s" % value).strip().lower() in (u"yes", u"true", u"1", u"on")


# SEEDING DISCIPLINE for the three composition keys above (as
# method_baselines.py for the numeric criteria): "all samples in duplicate" /
# "LFSM every N samples" are QAPP demands ON TOP OF a published method's own
# minimum QC. No EPA/FDA method text specifies a duplicate frequency or an
# LFSM interval, so get_baseline() returns None for all three: a regulatory
# value is never fabricated. Absent means UNKNOWN (rule 1), the permanent
# answer here.

# Criterion keys that are per-analyte, not per-method x matrix alone. Their
# stored value (at the project tier, and as read off the lab profile) is
# keyed one level deeper, by analyte display name.
ANALYTE_SCOPED_KEYS = frozenset(["eis_recovery"])


def _dig(mapping, path):
    """Walk a nested dict/list `path`; None on any miss, never a
    KeyError/IndexError: an incompletely populated profile is the normal
    case and reads as "not configured" (as method_profile_store's
    UnconfiguredCriterion, without depending on it)."""
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


def _lab_eis_recovery_set_by(profile, matrix, analyte):
    """(window, the level that set it): the analyte's own override, replaced
    by the matrix class's override when the matrix has one."""
    if not analyte:
        return None, None
    value = None
    set_by = None
    for row in (profile.get("eis_overrides") or []):
        if row.get("analyte") == analyte:
            lo = row.get("recovery_min")
            hi = row.get("recovery_max")
            if lo is not None or hi is not None:
                value = {"min": lo, "max": hi}
                set_by = "analyte"
            break
    mclass = method_baselines.matrix_class(matrix, profile) if matrix else "aqueous"
    if mclass != "aqueous":
        override = (profile.get("eis_matrix_overrides") or {}).get(mclass, {}).get(analyte)
        if override:
            if labelled_standards.not_assessed(override):       # no window in this class
                value = {"min": None, "max": None, "assessed": False}
            else:
                value = {"min": override.get("recovery_min"),
                         "max": override.get("recovery_max")}
            set_by = "class:" + mclass
    return value, set_by


def _lab_eis_recovery(profile, matrix, analyte):
    return _lab_eis_recovery_set_by(profile, matrix, analyte)[0]


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

    # the CCV interval (instrument_verification.ccv.frequency): registered, so a
    # project can override it and it carries provenance; a project-less
    # batch resolves it at the lab tier
    "ccv_frequency": lambda profile, matrix, analyte: _dig(
        profile, ["instrument_verification", "ccv", "frequency"]),
    # None until the profile sets the field ("frequency" under its LFSM
    # tier, a "duplicate_all_samples" flag), as an unconfigured numeric
    # criterion
    "lfsm_frequency": lambda profile, matrix, analyte: _dig(
        profile, ["qc_acceptance", "LFSM", "frequency"]),
    "duplicate_all_samples": lambda profile, matrix, analyte: _flag(_dig(
        profile, ["qc_acceptance", "Dup", "duplicate_all_samples"])),
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


def _lab_set_by(profile, matrix, key, analyte):
    """The level inside the lab tier that supplied this key's value."""
    if key == "eis_recovery":
        return _lab_eis_recovery_set_by(profile, matrix, analyte)[1] or "method"
    if key == "dup_rpd_max":
        tiers = _dig(profile, ["qc_acceptance", "Dup", "tiers"]) or []
        try:
            default = qc_tiers.base_tier(profile, "Dup", matrix)
        except qc_tiers.Unconfigured:
            default = None
        if tiers and not (default and default[0] is tiers[0]):
            return "tier:" + (tiers[0].get("name") or tiers[0].get("analyte_group") or "unnamed tier")
    return "method"


def resolve(method_id, matrix, key, analyte=None,
            profile=None, project_ruleset=None,
            project_doc=None, project_rev=None):
    """Resolve one QC criterion through project -> lab -> baseline.

    Pure function: `profile` and `project_ruleset` are plain dicts already
    fetched by the caller (resolve_for_batch() does that for the real
    system); this function touches no ZODB/Plone API.

    Parameters
    ----------
    method_id, matrix : the method and matrix scoping this criterion.
    key : a key registered in SHAPES_BY_KEY. Unregistered keys raise
        ValueError -- that is a caller bug, not a missing-data case.
    analyte : required (and used) only for ANALYTE_SCOPED_KEYS; ignored
        otherwise.
    profile : the method profile dict for method_id, or None (an
        unconfigured method): resolution falls through to the baseline tier.
    project_ruleset : the project's ruleset dict (get_project_ruleset()
        shape), or None/{} for no project, the common case: lab then
        baseline.
    project_doc, project_rev : the controlled-document id/revision backing a
        PROJECT-tier value (resolve_for_batch() reads them from the
        Project's qapp_document_id); attached only to a tier "project"
        result.

    Returns
    -------
    A ResolvedCriterion. `tier` names the tier that supplied `value`; when
    none did, `tier` is "baseline" and `value` is what the baseline supplies
    (None when it is unverified): check `value is None` to tell "resolved to
    the baseline" from "nothing resolved anywhere".

    `source_doc` / `source_rev` are set ONLY for tier="project", from
    project_doc/project_rev. For tier="lab" they are None: the method profile
    carries no link to a controlling QAM/SOP revision, and none is invented.
    For tier="baseline" they are None; the citation is on the Baseline
    (`departure["citation"]` when conformance is DEPARTS).

    `conformance` is CONFORMS / DEPARTS / UNKNOWN. Rule 1: UNKNOWN whenever
    method_baselines.get_baseline() returns None for this (method_id, key,
    analyte, matrix), whichever tier supplied `value`: no claim of
    conformance to a requirement the system does not know. `departure` (a
    dict) is set only when conformance is DEPARTS; it names, per
    SHAPE_WINDOW end independently, which end loosened and by how much
    (method_baselines.compare(); a window's two ends are never combined into
    one verdict).
    """
    shape = SHAPES_BY_KEY.get(key)
    if shape is None:
        raise ValueError(
            "Unknown criterion key {0!r}: register its shape in "
            "ruleset.SHAPES_BY_KEY before resolving it".format(key))

    tier = TIER_BASELINE
    source_doc = None
    source_rev = None
    value = None
    set_by = "default"

    pv = _project_value(project_ruleset, method_id, matrix, key, analyte)
    if pv is not None:
        value = pv
        tier = TIER_PROJECT
        set_by = "project"
        source_doc = project_doc
        source_rev = project_rev
    else:
        lv = _lab_value(profile, method_id, matrix, key, analyte)
        if lv is not None:
            value = lv
            tier = TIER_LAB
            set_by = _lab_set_by(profile, matrix, key, analyte)
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
        set_by=set_by,
    )


# ── Project tier, derived from Project Specs ─────────────────────────────────
# Zope-side imports stay inside the function bodies, so importing this module
# never requires Zope.

def ruleset_from_specs(profiles, specs, effective, env=None):
    """The project tier, DERIVED from a project's Project Specs: {method_id: {matrix: {key: value}}} holding exactly the
    registered criteria whose value in the project-applied profile differs
    from the method profile's. Analyte-scoped keys hold {analyte: value}.

    `profiles` = {method_id: method profile}, `specs` = the project's specs,
    `effective(profile, method_specs, matrix, env=env)` -> (profile, stale)
    (project_specs.effective). Pure: no Zope, no storage."""
    out = {}
    for method_id, method_specs in sorted((specs or {}).items()):
        profile = (profiles or {}).get(method_id)
        if not profile or not method_specs:
            continue
        for matrix in profile.get("supported_matrices") or []:
            eff = effective(profile, method_specs, matrix, env=env)[0]
            node = {}
            for key, extractor in sorted(_LAB_EXTRACTORS.items()):
                if key in ANALYTE_SCOPED_KEYS:
                    names = set()
                    for prof in (profile, eff):
                        for row in prof.get("eis_overrides") or []:
                            if isinstance(row, dict) and row.get("analyte"):
                                names.add(row["analyte"])
                        for by in (prof.get("eis_matrix_overrides") or {}).values():
                            names.update((by or {}).keys())
                    per = dict((a, extractor(eff, matrix, a)) for a in sorted(names)
                               if extractor(eff, matrix, a) != extractor(profile, matrix, a))
                    if per:
                        node[key] = per
                else:
                    value = extractor(eff, matrix, None)
                    if value != extractor(profile, matrix, None):
                        node[key] = value
            if node:
                out.setdefault(method_id, {})[matrix] = node
    return out


def get_project_ruleset(portal, project):
    """The project tier for `project`, derived from its Project Specs -- {}
    for no project or no specs. A project tier that cannot be derived raises:
    judging the batch on the method tier alone would hide the project's
    criteria."""
    if project is None:
        return {}
    from senaite.pfas import project_specs
    from senaite.pfas.method_profile_store import get_profile
    specs = project_specs.get_specs(project) or {}
    if not specs:
        return {}
    profiles = dict((mid, get_profile(portal, mid)) for mid in specs)
    return ruleset_from_specs(profiles, specs, project_specs.effective,
                              env=project_specs.site_env())


def _project_source(portal, project):
    """(doc_id, active_rev_num) for the QAPP document a project names, or
    (None, None) if it names none, or (doc_id, None) if it names one with no
    active revision on file -- never fabricated."""
    doc_id = getattr(project, "qapp_document_id", None) or None
    if not doc_id:
        return None, None
    from senaite.pfas.browser.sop_documents import _get_revisions
    for rev in _get_revisions(portal, doc_id):
        if rev.get("status") == "active":
            return doc_id, rev.get("rev_num")
    return doc_id, None


def resolve_for_batch(portal, batch, method_id, matrix, key, analyte=None):
    """resolve(), wired to a live Batch: fetches its linked Project (if any --
    senaite.pfas.project_ref), the project tier derived from its specs, the
    read-only method profile (senaite.pfas.method_profile_store), and the controlling
    QAPP document/revision, then delegates to resolve().

    A batch with no linked project passes an empty project_ruleset and
    resolves through lab then baseline; nothing special-cases it (rule 3).

    Called by senaite.pfas.resolved_criteria_store.export_resolved_criteria(),
    itself called from project_ref.set_project_uid() when a batch's project
    link is set and a method_id/matrix are known.
    """
    from senaite.pfas import project_ref
    from senaite.pfas import method_profile_store

    project = project_ref.get_project(portal, batch)
    project_ruleset = get_project_ruleset(portal, project) if project is not None else {}
    project_doc, project_rev = (None, None)
    if project is not None:
        project_doc, project_rev = _project_source(portal, project)

    # the lab tier is the METHOD profile; what the project's specs change is
    # the project tier above it, so each value names the source that set it
    profile = method_profile_store.get_profile(portal, method_id)

    return resolve(method_id, matrix, key, analyte=analyte,
                    profile=profile, project_ruleset=project_ruleset,
                    project_doc=project_doc, project_rev=project_rev)
