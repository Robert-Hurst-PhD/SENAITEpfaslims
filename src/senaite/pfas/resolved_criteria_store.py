# -*- coding: utf-8 -*-
"""
Resolved per-batch QC criteria — file bridge to the pipeline worker.

`senaite.pfas.ruleset` resolves ONE criterion through project QAPP -> lab
method profile -> published-method baseline (see ruleset.py's module
docstring), but has zero call sites of its own: nothing decides WHEN a
batch's criteria should be resolved, and nothing carries the result across
the process boundary to the worker. This module is that: a per-batch
resolved-criteria file, exported the same way method_profile_store.py
already exports the lab tier.

    add-on:  export_resolved_criteria(portal, batch, method_id, matrix)
                 writes  {dirname(PFAS_PROFILES_PATH)}/resolved/{batch_id}.json
    worker:  pfas_pipeline.method_profiles.reload_from_profiles(batch_id=...)
                 overlays that file's rows on top of the global profile it
                 just loaded from method_profiles.json.

Why a separate module from ruleset.py, mirroring method_profile_store.py
rather than living inside it
-----------------------------------------------------------------------
ruleset.py is deliberately pure resolution logic plus a thin ZODB shell; its
own docstring says nothing calls it and nothing there does file I/O or
batch-wide enumeration. method_profile_store.py already draws exactly this
line for the LAB tier: resolution/shape lives in method_profiles-as-data,
the ZODB<->file bridge is its own module. This file is that second half for
the fully-resolved (project-aware) answer, one batch at a time. It imports
ruleset for the actual resolution (resolve() / resolve_for_batch()) and adds
no resolution logic of its own — enumerating WHICH analytes to resolve
eis_recovery for is bookkeeping, not a tier decision.

Pure core, thin ZODB shell — same split as ruleset.py
------------------------------------------------------
`build_resolved_rows()` and `write_resolved_file()` are pure: given
already-fetched `profile` / `project_ruleset` dicts (or, for the writer,
already-resolved rows), they touch no ZODB/Plone API and are exercised
directly by tests/test_resolved_criteria_store.py under plain Python 3,
exactly as tests/test_ruleset.py exercises ruleset.resolve(). Both fall back
to a path-relative import of ruleset.py when the senaite.pfas package (which
needs zope.i18nmessageid) is not importable, for the same reason ruleset.py
itself does that for method_baselines.py.

`export_resolved_criteria()` / `remove_resolved_criteria()` are the thin
shells: they fetch the real Project/profile via ruleset.resolve_for_batch()
and project_ref, then delegate to the pure functions above. Like
ruleset.resolve_for_batch() itself, they are not exercised by the plain-
Python-3 test harness (there is no Zope there to fetch from) — proven live
against the running instance instead.

Written ONLY when the caller knows a batch is linked to a project; a batch
with no project (every batch today) never has this function called for it
at all (see project_ref.set_project_uid, the call site), so it never gets a
file, which is the safety property this whole feature depends on: no file
is the default and must behave exactly like no file did before this module
existed.

Python 2.7 compatible. No f-strings, no pathlib, no type annotations.
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
import json
import logging
import os

logger = logging.getLogger("senaite.pfas.resolved_criteria_store")

# Same standalone-import fallback ruleset.py uses, and for the same reason:
# `from senaite.pfas import ruleset` goes through the senaite.pfas package
# __init__, which needs zope.i18nmessageid and so is unavailable outside the
# container (tests, a plain `python3` interpreter).
try:
    from senaite.pfas import ruleset
except ImportError:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ruleset  # noqa: E402  (standalone/test fallback)


def _resolved_dir(base_profiles_path=None):
    """Directory the per-batch resolved files live in, derived from the SAME
    env var method_profile_store.export_profiles_to_file() honours for the
    global file (PFAS_PROFILES_PATH) -- never a second, independently
    hardcoded path (CLAUDE.md Sec1 rule 3). Read at CALL time, not at import
    time, so a test that sets the env var before calling in still redirects
    it even though this module may already have been imported."""
    if base_profiles_path is None:
        base_profiles_path = os.environ.get(
            "PFAS_PROFILES_PATH", "/data/qc/method_profiles.json")
    return os.path.join(os.path.dirname(base_profiles_path), "resolved")


def _safe_batch_id(batch_id):
    """Defang a batch id before it becomes a filename -- never write outside
    the resolved directory no matter what a batch's id contains."""
    return "".join(
        ch for ch in (batch_id or u"") if ch.isalnum() or ch in (u"-", u"_", u".")
    )


def resolved_file_path(batch_id, directory=None):
    if directory is None:
        directory = _resolved_dir()
    return os.path.join(directory, _safe_batch_id(batch_id) + u".json")


# ── Pure: which analytes a criterion key resolves for ───────────────────────

def _analytes_for_key(key, method_id, matrix, profile, project_ruleset):
    """Which analytes to resolve `key` for. Every key except the
    analyte-scoped ones (ruleset.ANALYTE_SCOPED_KEYS -- today just
    eis_recovery) resolves once, analyte=None.

    For an analyte-scoped key, the universe is the union of every analyte
    the LAB profile's eis_overrides already names and every analyte a
    PROJECT ruleset names for this exact (method_id, matrix, key) --
    precisely the analytes something live already has an opinion about
    today (pfas_pipeline/method_profiles.py reads eis_overrides the
    identical way). An analyte with ONLY a published-method baseline and no
    lab/project configuration is not enumerated: nothing evaluates it live
    today either, so listing it here would be inventing a row, not
    resolving one."""
    if key not in ruleset.ANALYTE_SCOPED_KEYS:
        return [None]
    names = set()
    for row in ((profile or {}).get("eis_overrides") or []):
        analyte = row.get("analyte") if isinstance(row, dict) else None
        if analyte:
            names.add(analyte)
    node = ruleset._dig(project_ruleset or {}, [method_id, matrix, key])
    if isinstance(node, dict):
        names.update(node.keys())
    return sorted(names)


def _row_from_resolved(resolved):
    """A ResolvedCriterion -> the plain, JSON-ready dict this module writes
    and pfas_pipeline.method_profiles reads back. Every field the task
    requires travels: value, tier, source doc/rev, conformance + departure."""
    return {
        u"key": resolved.key,
        u"analyte": resolved.analyte,
        u"value": resolved.value,
        u"tier": resolved.tier,
        u"source_doc": resolved.source_doc,
        u"source_rev": resolved.source_rev,
        u"conformance": resolved.conformance,
        u"departure": resolved.departure,
    }


def build_resolved_rows(method_id, matrix, profile=None, project_ruleset=None,
                         project_doc=None, project_rev=None):
    """Pure counterpart to export_resolved_criteria(): every criterion
    registered in ruleset.SHAPES_BY_KEY, resolved through
    ruleset.resolve() against already-fetched `profile` / `project_ruleset`
    dicts (ruleset.resolve()'s own calling convention -- no ZODB/Plone
    import here, so this runs and is tested under plain Python 3 exactly
    like ruleset.py's own test suite).

    Returns a list of plain dicts, JSON-ready, in the shape
    pfas_pipeline.method_profiles' overlay reads back."""
    rows = []
    for key in sorted(ruleset.SHAPES_BY_KEY):
        for analyte in _analytes_for_key(key, method_id, matrix, profile,
                                          project_ruleset):
            resolved = ruleset.resolve(
                method_id, matrix, key, analyte=analyte,
                profile=profile, project_ruleset=project_ruleset,
                project_doc=project_doc, project_rev=project_rev)
            rows.append(_row_from_resolved(resolved))
    return rows


def write_resolved_file(batch_id, method_id, matrix, rows, directory=None):
    """Write `rows` (as built by build_resolved_rows()) to
    {directory}/{batch_id}.json. Atomic: writes to .tmp then renames --
    exactly method_profile_store.export_profiles_to_file()'s pattern.
    Raises on I/O failure, same as that function; the caller decides
    whether to swallow it (export_resolved_criteria does, so a resolved-
    criteria write failure never blocks the project-link operation that
    triggered it). Returns the path written."""
    if directory is None:
        directory = _resolved_dir()
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    payload = {
        u"batch_id": batch_id,
        u"method_id": method_id,
        u"matrix": matrix,
        u"generated_at": datetime.datetime.utcnow().isoformat() + u"Z",
        u"criteria": rows,
    }

    path = resolved_file_path(batch_id, directory=directory)
    tmp = path + u".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.rename(tmp, path)
    logger.info("Exported %d resolved criteria for batch %s (%s/%s) to %s",
                len(rows), batch_id, method_id, matrix, path)
    return path


# ── Thin ZODB shells (not exercised by the plain-Python-3 test harness — ────
# proven live, like ruleset.resolve_for_batch() itself) ──────────────────────

def export_resolved_criteria(portal, batch, method_id, matrix, directory=None):
    """Resolve every registered criterion for (batch, method_id, matrix)
    through project -> lab -> baseline and write the result to
    {directory}/{batch_id}.json.

    method_id and matrix are supplied by the CALLER, not derived here — this
    function resolves and writes; it does not go hunting through logbook
    annotations or worksheet samples to guess a batch's method or matrix.
    See project_ref.set_project_uid (the call site) for where that
    best-effort derivation happens and why it is allowed to conclude
    "unknown" there but never invent a value here.

    Returns the path written, or None if batch_id/method_id/matrix were
    incomplete — never writes a partial or guessed file."""
    batch_id = getattr(batch, u"getId", lambda: None)()
    if not batch_id or not method_id or not matrix:
        logger.info(
            "export_resolved_criteria: batch_id/method_id/matrix incomplete "
            "(%r/%r/%r) -- not writing a resolved-criteria file",
            batch_id, method_id, matrix)
        return None

    from senaite.pfas import method_profile_store
    from senaite.pfas import project_ref

    project = project_ref.get_project(portal, batch)
    project_ruleset = (ruleset.get_project_ruleset(project)
                        if project is not None else {})
    profile = method_profile_store.get_profile(portal, method_id)

    rows = []
    for key in sorted(ruleset.SHAPES_BY_KEY):
        for analyte in _analytes_for_key(key, method_id, matrix, profile,
                                          project_ruleset):
            resolved = ruleset.resolve_for_batch(
                portal, batch, method_id, matrix, key, analyte=analyte)
            rows.append(_row_from_resolved(resolved))

    return write_resolved_file(batch_id, method_id, matrix, rows,
                                directory=directory)


def remove_resolved_criteria(batch_id, directory=None):
    """Delete the resolved-criteria file for batch_id, if any. Called when a
    batch's project link is CLEARED (project_ref.set_project_uid(batch,
    None)) so a stale project-tier answer never outlives the link that
    produced it. Never raises; a missing file is success, not an error."""
    if not batch_id:
        return
    path = resolved_file_path(batch_id, directory=directory)
    try:
        os.remove(path)
    except OSError:
        pass
