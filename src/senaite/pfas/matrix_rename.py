# -*- coding: utf-8 -*-
"""A core Sample Type renamed is the matrix renamed everywhere (: core owns matrix names).

Method profiles name their matrices by the Sample Type's title, and remember
each one's UID (matrix_uid_map). When a Sample Type's title changes in core,
every profile that points at that UID has the old title replaced by the new
one -- keys, list items and values alike (supported matrices, units, holding
times, aliases, factors, spike levels, the Analyte x Matrix table, reporting
limits, certificate formats) -- and is saved, which also renames its core
Analysis Profile. Regulatory limits and project specs are renamed the same
way. Nothing is guessed: only an exact old title is replaced.

    rename_in(data, old, new)    pure: (renamed copy, how many replaced)
    keep_old_name(profile, old, new)  pure: the old title becomes an alias
    rename_edd_maps(profile, old, new) pure: an EDD profile's per-matrix maps
    consistency(profiles, titles) pure: profile matrices out of step with core
    on_sampletype_modified(...)  the IObjectModifiedEvent subscriber

The old title stays an alias of the new one, so history stored under it
(runs, studies, blank history) and a reprocess of an old run still resolve
(report_limits.canonical_matrix). A rename made where no event fires (the
JSON API) is caught by `consistency`, shown on Method Profiles.
"""
from __future__ import absolute_import, unicode_literals

import logging

logger = logging.getLogger("senaite.pfas.matrix_rename")


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


def rename_matrix(portal, uid, new):
    """Rename the matrix whose Sample Type is `uid` to `new` in every method
    profile, the regulatory limits and every project's specs. Returns [line]."""
    from senaite.pfas import method_profile_store as mps
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
        mps.save_profile(portal, mid, renamed)
        out.append(u"%s: %s -> %s (%d place(s))" % (mid, old, new, n))
    for old in olds:
        try:
            from senaite.pfas import edd_store
            for pid, eprof in (edd_store.get_edd_profiles(portal) or {}).items():
                eprof, n = rename_edd_maps(eprof, old, new)
                if n:
                    edd_store.save_edd_profile(portal, pid, eprof)
                    out.append(u"EDD profile %s: %s -> %s (%d)" % (pid, old, new, n))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("EDD profiles not renamed: %s", exc)
        try:
            from senaite.pfas import regulatory_limits as rl
            store, n = rename_in(rl.get_store(portal), old, new)
            if n:
                rl.save_store(portal, store)
                out.append(u"regulatory limits: %s -> %s (%d)" % (old, new, n))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("regulatory limits not renamed: %s", exc)
        try:
            from bika.lims import api
            from senaite.pfas import project_specs as ps
            for project in api.get_portal().pfas_projects.objectValues():
                specs, n = rename_in(ps.get_specs(project) or {}, old, new)
                if n:
                    ps.save_specs(project, specs)
                    out.append(u"project %s: %s -> %s (%d)" % (project.getId(), old, new, n))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("project specs not renamed: %s", exc)
    return out


def on_sampletype_modified(obj, event):
    """IObjectModifiedEvent on a SampleType: follow a title change."""
    try:
        from bika.lims import api
        for line in rename_matrix(api.get_portal(), obj.UID(), obj.Title()):
            logger.info("Sample Type renamed: %s", line)
    except Exception:                                       # noqa: BLE001
        logger.exception("matrix rename after a Sample Type change failed")
