# -*- coding: utf-8 -*-
"""
Resolved per-batch QC criteria — file bridge to the pipeline worker.

`senaite.pfas.ruleset` resolves ONE criterion through project QAPP -> lab
method profile -> published-method baseline. This module decides WHEN a
batch's criteria are resolved and carries the result across the process
boundary to the worker: a per-batch resolved-criteria file, exported the
same way method_profile_store.py exports the lab tier.

    add-on:  export_resolved_criteria(portal, batch, method_id, matrix)
                 writes  {dirname(PFAS_PROFILES_PATH)}/resolved/{batch_id}.json
    worker:  pfas_pipeline.method_profiles.reload_from_profiles(batch_id=...)
                 overlays that file's rows on top of the global profile it
                 just loaded from method_profiles.json.

ruleset.py holds the resolution logic and does no file I/O; this module is
the ZODB<->file bridge and adds no resolution logic of its own (enumerating
WHICH analytes to resolve eis_recovery for is bookkeeping, not a tier
decision).

`build_resolved_rows()` and `write_resolved_file()` are pure: given
already-fetched `profile` / `project_ruleset` dicts (or already-resolved
rows), they touch no ZODB/Plone API and run under plain Python 3. Both fall
back to a path-relative import of ruleset.py when the senaite.pfas package
(which needs zope.i18nmessageid) is not importable.
`export_resolved_criteria()` / `remove_resolved_criteria()` are the thin
shells: they fetch the real Project/profile via ruleset.resolve_for_batch()
and project_ref, then delegate to the pure functions.

Written ONLY for a batch linked to a project (project_ref.set_project_uid
is the call site). A batch with no project gets no file, and no file must
behave as the global profile alone.

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
from senaite.pfas import ruleset


def _resolved_dir(base_profiles_path=None):
    """Directory the per-batch resolved files live in, derived from the SAME
    env var method_profile_store.export_profiles_to_file() honours for the
    global file (PFAS_PROFILES_PATH) -- never a second, independently
    hardcoded path. Read at CALL time, not at import time, so a test that
    sets the env var before calling in still redirects it."""
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
    analyte-scoped ones (ruleset.ANALYTE_SCOPED_KEYS, such as
    eis_recovery) resolves once, analyte=None.

    For an analyte-scoped key, the universe is the union of every analyte
    the LAB profile's eis_overrides names and every analyte a PROJECT
    ruleset names for this exact (method_id, matrix, key)
    (pfas_pipeline/method_profiles.py reads eis_overrides the same way). An
    analyte with ONLY a published-method baseline and no lab/project
    configuration is not enumerated: nothing evaluates it, so a row for it
    would be invented, not resolved."""
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
    and pfas_pipeline.method_profiles reads back: value, tier, source
    doc/rev, conformance + departure."""
    return {
        u"key": resolved.key,
        u"analyte": resolved.analyte,
        u"value": resolved.value,
        u"tier": resolved.tier,
        u"source_doc": resolved.source_doc,
        u"source_rev": resolved.source_rev,
        u"conformance": resolved.conformance,
        u"departure": resolved.departure,
        u"set_by": resolved.set_by,
    }


def build_resolved_rows(method_id, matrix, profile=None, project_ruleset=None,
                         project_doc=None, project_rev=None):
    """Pure counterpart to export_resolved_criteria(): every criterion
    registered in ruleset.SHAPES_BY_KEY, resolved through
    ruleset.resolve() against already-fetched `profile` / `project_ruleset`
    dicts (ruleset.resolve()'s own calling convention; no ZODB/Plone
    import here).

    Returns a list of plain dicts, JSON-ready, in the shape
    pfas_pipeline.method_profiles' overlay reads back."""
    rows = []
    for key in sorted(ruleset.SHAPES_BY_KEY):
        for analyte in _analytes_for_key(key, method_id, matrix, profile,
                                          project_ruleset):
            rows.append(resolve_row(method_id, matrix, key, analyte, profile,
                                     project_ruleset, project_doc, project_rev))
    return rows


def resolve_row(method_id, matrix, key, analyte, profile=None,
                project_ruleset=None, project_doc=None, project_rev=None):
    """One criterion resolved to the plain row build_resolved_rows() holds,
    for a caller that needs an analyte that function does not enumerate."""
    return _row_from_resolved(ruleset.resolve(
        method_id, matrix, key, analyte=analyte, profile=profile,
        project_ruleset=project_ruleset, project_doc=project_doc,
        project_rev=project_rev))


def write_resolved_file(batch_id, method_id, matrix, rows, directory=None,
                        profile_patch=None, departures=None, stale=None):
    """Write `rows` (as built by build_resolved_rows()) to
    {directory}/{batch_id}.json. Atomic: writes to .tmp then renames, as
    method_profile_store.export_profiles_to_file() does.
    Raises on I/O failure; the caller decides
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
    if profile_patch:
        # the project's specs as a path patch on the method profile; the
        # worker applies it before the criteria rows (project_specs.py)
        payload[u"profile_patch"] = profile_patch
        payload[u"departures"] = departures or []
        payload[u"stale"] = stale or []

    path = resolved_file_path(batch_id, directory=directory)
    tmp = path + u".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.rename(tmp, path)
    logger.info("Exported %d resolved criteria for batch %s (%s/%s) to %s",
                len(rows), batch_id, method_id, matrix, path)
    return path


# ── Thin ZODB shells (need Zope: not run by the plain-Python-3 tests) ────────

def resolve_rows_for_batch(portal, batch, method_id, matrix):
    """The read half of export_resolved_criteria(): resolve every registered
    criterion for (batch, method_id, matrix) through project -> lab ->
    baseline and return the plain rows (build_resolved_rows()'s shape),
    WITHOUT writing anything.

    The one resolution path for both callers:
    worksheet_criteria_snapshot.freeze_resolved_criteria() freezes these
    same rows onto a WORKSHEET annotation at the Sec7.8.4 technical review.

    `batch` may be None: project_ref treats a None batch as "no project",
    so only the lab/baseline tiers resolve. `method_id`/`matrix` may also
    be empty; the caller decides
    whether an incomplete result is acceptable (export_resolved_criteria
    refuses to write one; the worksheet snapshot records why it could not)."""
    from senaite.pfas import method_profile_store
    from senaite.pfas import project_ref

    project = project_ref.get_project(portal, batch) if batch is not None else None
    project_ruleset = (ruleset.get_project_ruleset(portal, project)
                        if project is not None else {})
    profile = method_profile_store.get_profile(portal, method_id)

    rows = []
    for key in sorted(ruleset.SHAPES_BY_KEY):
        for analyte in _analytes_for_key(key, method_id, matrix, profile,
                                          project_ruleset):
            resolved = ruleset.resolve_for_batch(
                portal, batch, method_id, matrix, key, analyte=analyte)
            rows.append(_row_from_resolved(resolved))
    return rows


def export_resolved_criteria(portal, batch, method_id, matrix, directory=None):
    """Resolve every registered criterion for (batch, method_id, matrix)
    through project -> lab -> baseline and write the result to
    {directory}/{batch_id}.json.

    method_id and matrix are supplied by the CALLER (project_ref.set_project_uid
    derives them), never guessed here.

    Returns the path written, or None if batch_id/method_id/matrix were
    incomplete — never writes a partial or guessed file."""
    batch_id = getattr(batch, u"getId", lambda: None)()
    if not batch_id or not method_id or not matrix:
        logger.info(
            "export_resolved_criteria: batch_id/method_id/matrix incomplete "
            "(%r/%r/%r) -- not writing a resolved-criteria file",
            batch_id, method_id, matrix)
        return None

    rows = resolve_rows_for_batch(portal, batch, method_id, matrix)
    patch, departures, stale = _specs_for_batch(portal, batch, method_id, matrix)
    return write_resolved_file(batch_id, method_id, matrix, rows,
                                directory=directory, profile_patch=patch,
                                departures=departures, stale=stale)


def _specs_for_batch(portal, batch, method_id, matrix):
    """(profile_patch, departures, stale) for the batch's project specs, or
    ([], [], []) when its project holds none for this method."""
    from senaite.pfas import method_profile_store, project_ref, project_specs
    project = project_ref.get_project(portal, batch) if batch is not None else None
    if project is None:
        return [], [], []
    profile = method_profile_store.get_profile(portal, method_id)
    eff, stale, has = project_specs.effective_for_project(project, method_id, matrix, profile)
    if not has:
        return [], [], []
    return (project_specs.profile_patch(profile, eff),
            project_specs.departures(profile, eff, method_id), stale)


def refresh_linked_batches(portal, method_id=None, project_uid=None, request=None):
    """Re-export the file of every project-linked batch (optionally only
    those of one method or one project). Returns (refreshed, skipped
    [(batch_id, reason)]); never raises for one bad batch."""
    from senaite.pfas import batch_ref, project_ref
    from senaite.pfas.browser.batch_project_viewlet import _batch_method_id, _batch_matrix
    refreshed, skipped = 0, []
    for batch in batch_ref.list_batches(portal):
        uid = project_ref.get_project_uid(batch)
        if not uid or (project_uid and uid != project_uid):
            continue
        batch_id = getattr(batch, "getId", lambda: None)() or u"?"
        try:
            mid = _batch_method_id(batch, request) or u""
            matrix = _batch_matrix(portal, batch) or u""
            if method_id and mid != method_id:
                continue
            if not mid or not matrix:
                skipped.append((batch_id, "method/matrix not known"))
                continue
            if export_resolved_criteria(portal, batch, mid, matrix):
                refreshed += 1
            else:
                skipped.append((batch_id, "export declined (incomplete)"))
        except Exception as exc:
            logger.warning("refresh_linked_batches: export failed for %s: %s", batch_id, exc)
            skipped.append((batch_id, "export failed: {0}".format(exc)))
    return refreshed, skipped


def export_if_first_known(portal, batch_uid, directory=None, request=None):
    """Write the file of a project-linked batch that has none yet, once its
    method and matrix are known (from its samples). A batch with a file
    keeps it until the next refresh of linked batches. Returns the path
    written, or None."""
    from bika.lims import api
    from senaite.pfas import project_ref
    from senaite.pfas.browser.batch_project_viewlet import _batch_method_id, _batch_matrix
    batch = api.get_object_by_uid(batch_uid, None) if batch_uid else None
    if batch is None or not project_ref.get_project_uid(batch):
        return None
    batch_id = getattr(batch, "getId", lambda: None)()
    if not batch_id or os.path.exists(resolved_file_path(batch_id, directory=directory)):
        return None
    method_id = _batch_method_id(batch, request) or u""
    matrix = _batch_matrix(portal, batch) or u""
    if not method_id or not matrix:
        return None
    return export_resolved_criteria(portal, batch, method_id, matrix, directory=directory)


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
