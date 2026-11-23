# -*- coding: utf-8 -*-
"""A core Sample Type renamed is the matrix renamed everywhere: core owns matrix names.

Method profiles name their matrices by the Sample Type's title, and remember
each one's UID (matrix_uid_map). When a Sample Type's title changes in core,
every profile that points at that UID has the old title replaced by the new
one -- keys, list items and values alike (supported matrices, units, holding
times, aliases, factors, spike levels, the Analyte x Matrix table, reporting
limits, certificate formats) -- and is saved, which also renames its core
Analysis Profile. Regulatory limits and project specs are renamed the same
way. Nothing is guessed: only an exact old title is replaced.

    title_in_use(title, uid, sample_types, profiles)
                                 pure: why `title` cannot name the Sample
                                 Type `uid`, or None
    rename_in(data, old, new)    pure: (renamed copy, how many replaced)
    keep_old_name(profile, old, new)  pure: the old title becomes an alias
    rename_edd_maps(profile, old, new) pure: an EDD profile's per-matrix maps
    consistency(profiles, titles) pure: profile matrices out of step with core
    on_sampletype_modified(...)  the IObjectModifiedEvent subscriber

A Sample Type's edit refuses a title already in use (another Sample Type's,
or a matrix name or earlier name a method profile holds for another matrix),
and a rename whose follow-through fails is undone whole: every store
written so far is rolled back and the Sample Type keeps its title.

The old title stays an alias of the new one, so history stored under it
(runs, studies, blank history) and a reprocess of an old run still resolve
(report_limits.canonical_matrix). A rename made where no event fires (the
JSON API) is caught by `consistency`, shown on Method Profiles.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.matrix_rename")


def _same(a, b):
    return (a or u"").strip().lower() == (b or u"").strip().lower()


def title_in_use(title, uid, sample_types, profiles):
    """Why `title` cannot name the Sample Type `uid` (None for a new one),
    or None when it can. `sample_types` {UID: title}, `profiles` {method id:
    profile}. A matrix is named by its Sample Type's title, so a title in
    use would make two matrices one: another Sample Type's title, or a
    matrix name or an earlier name (alias) a method profile holds for a
    matrix that is not this Sample Type's. Case and outer spaces do not make
    a title different."""
    title = (title or u"").strip()
    if not title:
        return None
    for other, name in sorted((sample_types or {}).items()):
        if other != uid and _same(name, title):
            return u"The Sample Type %s already has this name." % name
    for mid, prof in sorted((profiles or {}).items()):
        prof = prof or {}
        uids = prof.get("matrix_uid_map") or {}
        mine = set(m for m, u in uids.items() if uid and u == uid)
        for m in prof.get("supported_matrices") or []:
            if not isinstance(m, dict) and m not in mine and _same(m, title):
                return u"Method %s already has a matrix named %s." % (mid, m)
        for canonical, names in sorted((prof.get("matrix_aliases") or {}).items()):
            if canonical in mine:
                continue                   # an earlier name of this Sample Type: taking it back is a rename
            for a in names or []:
                if _same(a, title):
                    return u"Method %s keeps %s as an earlier name of %s." % (mid, a, canonical)
    return None


class RenameFailed(Exception):
    """A step of a matrix rename could not be written: the rename is undone."""


def rename_in(data, old, new):
    """(copy of `data` with every string exactly `old` -- as a dict key, a
    list item or a value -- replaced by `new`, count)."""
    count = [0]

    def walk(x):
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if k == old:
                    count[0] += 1
                    k = new
                out[k] = walk(v)
            return out
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, tuple):
            return tuple(walk(v) for v in x)
        if isinstance(x, (type(u""), type(""))) and x == old:
            count[0] += 1
            return new
        return x
    return walk(data), count[0]


def keep_old_name(profile, old, new):
    """`profile` with `old` among `new`'s matrix aliases (once)."""
    aliases = dict(profile.get("matrix_aliases") or {})
    names = list(aliases.get(new) or [])
    if old and old != new and old not in names:
        names.append(old)
        aliases[new] = names
        profile = dict(profile, matrix_aliases=aliases)
    return profile


def rename_edd_maps(profile, old, new):
    """(an EDD profile with its per-matrix maps renamed, count): the
    sample-type code and weight basis follow the matrix."""
    out, total = dict(profile or {}), 0
    for key in ("matrix_map", "weight_basis_map"):
        if key in out:
            out[key], n = rename_in(out[key] or {}, old, new)
            total += n
    return out, total


def consistency(profiles, titles):
    """[problem] for profile matrices out of step with core: `profiles`
    {method id: profile}, `titles` {Sample Type UID: current title}."""
    out = []
    for mid, prof in sorted((profiles or {}).items()):
        uids = (prof or {}).get("matrix_uid_map") or {}
        for m in (prof or {}).get("supported_matrices") or []:
            uid = uids.get(m)
            if not uid:
                out.append(u"%s: %s is not linked to a Sample Type" % (mid, m))
            elif uid not in titles:
                out.append(u"%s: %s points at a Sample Type that no longer exists" % (mid, m))
            elif titles[uid] != m:
                out.append(u"%s: %s is called %s in core now (renamed where no event "
                           u"fired)" % (mid, m, titles[uid]))
        # an old name kept as an alias, now the name of another matrix
        matrices = set((prof or {}).get("supported_matrices") or [])
        for canonical, names in sorted(((prof or {}).get("matrix_aliases") or {}).items()):
            for a in names or []:
                if a in matrices and a != canonical:
                    out.append(u"%s: %s is both a matrix and an earlier name of %s"
                               % (mid, a, canonical))
    return out


def _step(out, what, fn):
    """Run one step of the follow-through; a failure names the step."""
    try:
        fn()
    except Exception as exc:                                # noqa: BLE001
        raise RenameFailed(u"%s: %s" % (what, exc))


def old_titles(portal, uid):
    """The titles the method profiles hold for the Sample Type `uid`."""
    from senaite.pfas import method_profile_store as mps
    out = []
    for mid in mps.list_method_ids(portal):
        profile = mps.raw_profile(portal, mid) or {}
        for t, u in (profile.get("matrix_uid_map") or {}).items():
            if u == uid and t not in out:
                out.append(t)
    return out


def rename_matrix(portal, uid, new):
    """Rename the matrix whose Sample Type is `uid` to `new` in every method
    profile, the EDD profiles, the regulatory limits and every project's
    specs. Returns [line]; raises RenameFailed naming the step that could
    not be written (the caller undoes the whole rename)."""
    from senaite.pfas import method_profile_store as mps
    from senaite.pfas import edd_store, project_specs as ps, regulatory_limits as rl
    out = []
    olds = set()
    for mid in mps.list_method_ids(portal):
        profile = mps.raw_profile(portal, mid) or {}
        old = next((t for t, u in (profile.get("matrix_uid_map") or {}).items() if u == uid), None)
        if not old or old == new:
            continue
        olds.add(old)
        renamed, n = rename_in(dict((k, v) for k, v in profile.items() if k != "matrix_uid_map"), old, new)
        renamed = keep_old_name(renamed, old, new)
        _step(out, u"method %s" % mid, lambda: mps.save_profile(portal, mid, renamed))
        out.append(u"%s: %s renamed to %s (%d place(s))" % (mid, old, new, n))
    for old in sorted(olds):
        def edd():
            for pid, eprof in (edd_store.get_edd_profiles(portal) or {}).items():
                eprof, n = rename_edd_maps(eprof, old, new)
                if n:
                    edd_store.save_edd_profile(portal, pid, eprof)
                    out.append(u"EDD profile %s: %s renamed to %s (%d)" % (pid, old, new, n))
        _step(out, u"the EDD profiles", edd)

        def limits():
            store, n = rename_in(rl.get_store(portal), old, new)
            if n:
                rl.save_store(portal, store)
                out.append(u"regulatory limits: %s renamed to %s (%d)" % (old, new, n))
        _step(out, u"the regulatory limits", limits)

        def projects():
            from bika.lims import api
            for project in api.get_portal().pfas_projects.objectValues():
                specs, n = rename_in(ps.get_specs(project) or {}, old, new)
                if n:
                    ps.save_specs(project, specs)
                    out.append(u"project %s: %s renamed to %s (%d)" % (project.getId(), old, new, n))
        _step(out, u"the project specs", projects)
    return out


def undo_message(old, new, exc):
    """What the person is told when a rename is undone."""
    return (u"%s was not renamed to %s: %s could not be renamed. Nothing was "
            u"changed by the rename." % (old, new, exc))


def on_sampletype_modified(obj, event):
    """IObjectModifiedEvent on a SampleType: follow a title change. A step
    that fails undoes the rename whole: what it wrote is rolled back to a
    savepoint taken before it, the Sample Type takes its old title back,
    and the person is told why. Where no savepoint can be taken, the error
    is raised, so the whole edit is aborted instead."""
    import transaction
    from bika.lims import api
    portal = api.get_portal()
    uid, new = obj.UID(), api.safe_unicode(obj.Title())
    olds = [t for t in old_titles(portal, uid) if t != new]
    if not olds:
        return                               # no matrix named by it: nothing to follow
    try:
        point = transaction.savepoint()
    except Exception:                                       # noqa: BLE001
        point = None
    try:
        for line in rename_matrix(portal, uid, new):
            logger.info("Sample Type renamed: %s", line)
    except RenameFailed as exc:
        if point is None:
            raise
        point.rollback()
        logger.warning("Sample Type rename undone (%s -> %s): %s", olds[0], new, exc)
        obj.title = olds[0]
        obj.reindexObject()
        try:
            from Products.statusmessages.interfaces import IStatusMessage
            IStatusMessage(api.get_request()).add(undo_message(olds[0], new, exc), type=u"error")
        except Exception:                                   # noqa: BLE001
            logger.exception("the undone rename could not be reported")
