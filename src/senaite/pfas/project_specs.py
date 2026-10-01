# -*- coding: utf-8 -*-
"""Project specs: a project's differences from its method (DECISIONS 2026-10-01).

A Project (client QAPP) may override parts of a method profile for the
batches linked to it: added analytes, extra surrogates / internal standards,
LFSM recovery tiers, Dup and LFSMD RPD, reporting limits. The editor shows
the method's OWN declared sections (method_profile_sections.PROJECT_SECTIONS)
pre-filled from the method; only the cells that differ are stored:

    specs = {method_id: {scope: {section id: patch}}}      scope: "*" | matrix

    Table       {"<json row key>": {column name: value}}
    Collection  {"changed": {row name: {column: value}}, "added": [full rows],
                 "removed": [row names]}
    Section     {field name: value}   (a list field: {"add": [...], "remove": [...]})

The effective profile for a batch is the method profile, then the "*"
patches, then its matrix's patches -- each section applied through its own
write adapter, so a project changes nothing a method save would not. A cell
the project never touched keeps following the method when the lab edits it;
a patch whose row the method no longer has is reported as stale, never
guessed onto another row.

Departures: every value looser than the lab's method is listed, judged on
what the QC engine would actually apply (the resolved tier per analyte x
matrix), and against the published method only where a verified baseline is
on file (method_baselines) -- otherwise "published limit not on file".

Pure: plain dicts in and out, no Zope; the storage helpers at the end defer
their imports. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json

try:
    from senaite.pfas import config_forms as cf
    from senaite.pfas import method_profile_sections as mps
except Exception:          # tests: loaded without the package
    import config_forms as cf
    import method_profile_sections as mps

KEY = "senaite.pfas.project.specs"
ALL = "*"


# ── cells: a section's values in one comparable shape ───────────────────────

def _norm(field, value):
    """For COMPARING only: an unticked box and an unset one are the same, and
    so are a blank and a missing value. Never written back."""
    if field.kind == cf.BOOL:
        return bool(value)
    if field.kind == cf.MULTI:
        return list(value or [])
    return None if value in (u"", "", None) else value


def _tok(key):
    return json.dumps(list(key))


def _untok(tok):
    return tuple(json.loads(tok))


def _raw_cells(section, profile, env=None):
    """{row token or name: {column name: stored value}} (Section: {name: value})."""
    profile = profile or {}
    if isinstance(section, cf.Table):
        t = cf._bound(section, profile)
        _groups, rows = cf._rows(t, profile, env)
        return dict((_tok(r["key"]), cf._cells(t, profile, r["key"])) for r in rows)
    if isinstance(section, cf.Collection):
        c = cf._bound(section, profile)
        key = c.key.path[0]
        return dict((row[key], dict((f.path[0], row.get(f.path[0])) for f in c.columns))
                    for row in c.read(profile))
    return cf.current(section, profile)


def _columns(section, profile):
    if isinstance(section, cf.Table):
        return dict((c.name, c) for c in cf._bound(section, profile).columns)
    if isinstance(section, cf.Collection):
        return dict((c.path[0], c) for c in cf._bound(section, profile).columns)
    return dict((f.name, f) for f in section.fields())


def _same(field, a, b):
    return _norm(field, a) == _norm(field, b)


# ── diff / apply ─────────────────────────────────────────────────────────────

def diff(section, base, new, env=None):
    """The patch that turns `base` into `new` for this section, or None."""
    cols = _columns(section, new)
    a, b = _raw_cells(section, base, env), _raw_cells(section, new, env)
    if isinstance(section, cf.Collection):
        key = section.key.path[0]
        changed = {}
        for name, vals in b.items():
            if name in a:
                d = dict((k, v) for k, v in vals.items() if not _same(cols[k], a[name].get(k), v))
                if d:
                    changed[name] = d
        added = [dict(row) for row in cf._bound(section, new).read(new or {}) if row[key] not in a]
        removed = sorted(n for n in a if n not in b)
        patch = dict((k, v) for k, v in (("changed", changed), ("added", added),
                                         ("removed", removed)) if v)
        return patch or None
    if isinstance(section, cf.Table):
        patch = {}
        for tok, vals in b.items():
            old = a.get(tok) or {}
            d = dict((k, v) for k, v in vals.items() if not _same(cols[k], old.get(k), v))
            if d:
                patch[tok] = d
        return patch or None
    patch = {}
    for name, value in b.items():
        f = cols[name]
        if f.kind == cf.MULTI:
            old, cur = list(a.get(name) or []), list(value or [])
            add = [x for x in cur if x not in old]
            rem = [x for x in old if x not in cur]
            if add or rem:
                patch[name] = {"add": add, "remove": rem}
        elif not _same(f, a.get(name), value):
            patch[name] = value
    return patch or None


def apply_patch(section, base, patch, env=None):
    """(profile, stale [text]) -- `base` with the patch written in through the
    section's own adapters. Touched rows are written COMPLETE (untouched cells
    from `base`): the adapters treat a row as a whole, e.g. a labelled
    standard whose row arrives without "used" is dropped."""
    stale = []
    if not patch:
        return copy.deepcopy(base), stale
    cols = _columns(section, base)
    if isinstance(section, cf.Collection):
        c = cf._bound(section, base)
        key = c.key.path[0]
        rows = c.read(base or {})
        names = set(r[key] for r in rows)
        changed = patch.get("changed") or {}
        removed = set(patch.get("removed") or [])
        out = []
        for row in rows:
            if row[key] in removed:
                continue
            r = dict(row)
            r.update(changed.get(row[key]) or {})
            out.append(r)
        for name in sorted(changed):
            if name not in names:
                stale.append(u"%s: %s is no longer in the method; its change is not applied."
                             % (section.title, name))
        for row in patch.get("added") or []:
            if row.get(key) in names:
                stale.append(u"%s: the method now has its own %s; the project's is not applied."
                             % (section.title, row.get(key)))
            else:
                out.append(dict(row))
        return c.write(copy.deepcopy(base or {}), out), stale
    if isinstance(section, cf.Table):
        current = _raw_cells(section, base, env)
        updates = {}
        for tok, vals in sorted(patch.items()):
            if tok not in current:
                stale.append(u"%s: %s is no longer listed; its change is not applied."
                             % (section.title, u" / ".join(_untok(tok))))
                continue
            row = dict(current[tok])
            row.update(dict((k, v) for k, v in vals.items() if k in cols))
            updates[_untok(tok)] = dict((cols[k].path, v) for k, v in row.items() if k in cols)
        return cf.apply(section, base, updates, env), stale
    now = cf.current(section, base)
    updates = {}
    for name, value in patch.items():
        f = cols.get(name)
        if f is None:
            continue
        if f.kind == cf.MULTI:
            cur = list(now.get(name) or [])
            value = ([x for x in cur if x not in (value.get("remove") or [])] +
                     [x for x in (value.get("add") or []) if x not in cur])
        updates[f.path] = value
    return cf.apply(section, base, updates), stale


def scope_base(profile, method_specs, scope, sections, env=None):
    """What a scope's patches are measured against: the method for "*", the
    method plus the "*" patches for a matrix."""
    if scope == ALL:
        return copy.deepcopy(profile), []
    return _apply_scopes(profile, method_specs, [ALL], sections, env)


def _apply_scopes(profile, method_specs, scopes, sections, env=None):
    p, stale = copy.deepcopy(profile), []
    for scope in scopes:
        patches = (method_specs or {}).get(scope) or {}
        for s in sections:
            if patches.get(s.id):
                p, st = apply_patch(s, p, patches[s.id], env)
                stale.extend(st)
    return p, stale


def effective(profile, method_specs, matrix=None, sections=None, env=None):
    """(profile, stale) for a batch of this method in `matrix` (None: the "*"
    scope only)."""
    sections = sections if sections is not None else mps.PROJECT_SECTIONS
    scopes = [ALL] + ([matrix] if matrix and matrix != ALL else [])
    return _apply_scopes(profile, method_specs, scopes, sections, env)


def scope_patches(base, new, sections, env=None):
    """{section id: patch} for one scope, only the sections that differ."""
    out = {}
    for s in sections:
        d = diff(s, base, new, env)
        if d:
            out[s.id] = d
    return out


def set_scope(specs, method_id, scope, patches):
    """A copy of `specs` with one scope replaced (empty scopes/methods go)."""
    specs = copy.deepcopy(specs or {})
    m = specs.setdefault(method_id, {})
    if patches:
        m[scope] = patches
    else:
        m.pop(scope, None)
    if not m:
        specs.pop(method_id, None)
    return specs


# ── the worker's view: a path patch on the method profile ───────────────────

def profile_patch(base, eff, path=()):
    """[{"path": [...], "value": v} | {"path": [...], "delete": True}] turning
    `base` into `eff`. Dicts recurse; a changed list is replaced whole (the
    add-on re-exports whenever the method or the project changes)."""
    ops = []
    if isinstance(base, dict) and isinstance(eff, dict):
        for k in sorted(set(base) | set(eff)):
            if k not in eff:
                ops.append({"path": list(path) + [k], "delete": True})
            elif k not in base:
                ops.append({"path": list(path) + [k], "value": copy.deepcopy(eff[k])})
            elif base[k] != eff[k]:
                ops.extend(profile_patch(base[k], eff[k], tuple(path) + (k,)))
        return ops
    if base != eff:
        ops.append({"path": list(path), "value": copy.deepcopy(eff)})
    return ops


# ── departures: looser than the lab's method ─────────────────────────────────

_PUBLISHED_NONE = u"published limit not on file"


def _published(method_id, key, value, matrix=None):
    """The published-method verdict where a baseline is on file."""
    if not key:
        return _PUBLISHED_NONE
    try:
        try:
            from senaite.pfas import method_baselines as mb
        except Exception:
            import method_baselines as mb
        b = mb.get_baseline(method_id, key, matrix=matrix)
        if b is None:
            return _PUBLISHED_NONE
        verdict, _v = mb.compare(b, value)
        return u"published method: %s (%s)" % (verdict.lower(), b.citation)
    except Exception:
        return _PUBLISHED_NONE


def _flags():
    try:
        from senaite.pfas.analyte_reference import NATIVE_ANALYTES
    except Exception:
        from analyte_reference import NATIVE_ANALYTES
    return dict((r[0], bool(r[7])) for r in NATIVE_ANALYTES)


def _fmt(v):
    return u"not set" if v is None else u"%g" % v


def departures(profile, eff, method_id=None, matrices=None):
    """[{"what", "method", "project", "where", "published"}] for every value
    in `eff` looser than in `profile` (the method), in `matrices` (default:
    all the method's)."""
    method_id = method_id or profile.get("method_id")
    no_std = _flags()
    out, grouped = [], {}
    keys_m, keys_e = set(mps.key_analytes(profile)), set(mps.key_analytes(eff))
    panel = [kw for kw in profile.get("master_analyte_set") or []]
    matrices = [m for m in profile.get("supported_matrices") or []
                if matrices is None or m in matrices]
    checks = [(u"LFSM", u"recovery_min", u"LFSM recovery min %", "lower"),
              (u"LFSM", u"recovery_max", u"LFSM recovery max %", "higher"),
              (u"LFSM", u"rsd_max", u"LFSM RSD max %", "higher"),
              (u"LFSMD", u"rpd_max", u"LFSMD RPD max %", "higher")]
    for kw in panel:
        for m in matrices:
            for qc, field, label, looser in checks:
                tm = mps.resolve_tier(profile, kw in keys_m, no_std.get(kw, False), m, qc)
                te = mps.resolve_tier(eff, kw in keys_e, no_std.get(kw, False), m, qc)
                a = (tm or {}).get(field)
                b = (te or {}).get(field)
                if a is None or a == b:
                    continue                    # the method sets nothing to loosen
                if b is None or (b < a if looser == "lower" else b > a):
                    grouped.setdefault((label, a, b), {}).setdefault(kw, []).append(m)
    for (label, a, b), by_kw in sorted(grouped.items(), key=lambda i: (i[0][0], i[0][1])):
        # one row per exact matrix set, so no analyte is named for a matrix
        # where it is not loosened
        sets = {}
        for kw in panel:
            if kw in by_kw:
                sets.setdefault(tuple(by_kw[kw]), []).append(kw)
        for ms, kws in sorted(sets.items(), key=lambda i: -len(i[0])):
            where = (u"all matrices" if list(ms) == matrices and len(matrices) > 1
                     else u", ".join(ms))
            out.append({"what": label, "method": _fmt(a), "project": _fmt(b),
                        "where": u"%s in %s" % (u", ".join(kws), where),
                        "published": _PUBLISHED_NONE})
    # low-level tiers (<= N x RL), matched by name: a looser window or RPD,
    # a larger N, or the tier dropped
    low_checks = [(u"LFSM", u"recovery_min", "lower"), (u"LFSM", u"recovery_max", "higher"),
                  (u"LFB", u"recovery_min", "lower"), (u"LFB", u"recovery_max", "higher"),
                  (u"LFSMD", u"rpd_max", "higher"), (u"LFSM", mps.LOW_LEVEL_KEY, "higher"),
                  (u"LFB", mps.LOW_LEVEL_KEY, "higher"), (u"LFSMD", mps.LOW_LEVEL_KEY, "higher")]
    low = lambda p, qc: dict((t.get("name"), t) for t in mps._tiers(p, qc)       # noqa: E731
                             if t.get(mps.LOW_LEVEL_KEY) is not None)
    for qc, field, looser in low_checks:
        lm, le = low(profile, qc), low(eff, qc)
        for name in sorted(lm):
            a = lm[name].get(field)
            b = (le.get(name) or {}).get(field)
            if a is None or a == b:
                continue
            if b is None or (b < a if looser == "lower" else b > a):
                out.append({"what": u"%s low-level tier %s: %s" % (qc, name, field.replace("_", " ")),
                            "method": _fmt(a), "project": _fmt(b) if name in le else u"removed",
                            "where": u"spikes at the low level", "published": _PUBLISHED_NONE})
    dm = (((profile.get("qc_acceptance") or {}).get("Dup") or {}).get("tiers") or [{}])[0].get("rpd_max")
    de = (((eff.get("qc_acceptance") or {}).get("Dup") or {}).get("tiers") or [{}])[0].get("rpd_max")
    if dm is not None and dm != de and (de is None or de > dm):
        out.append({"what": u"Dup RPD max %", "method": _fmt(dm), "project": _fmt(de),
                    "where": u"all analytes and matrices",
                    "published": _published(method_id, "dup_rpd_max", de)})
    rl_m = profile.get("reporting_limits") or {}
    rl_e = eff.get("reporting_limits") or {}
    for m in matrices:
        for kw in panel:
            for field in (u"rl", u"mdl"):
                a = ((rl_m.get(m) or {}).get(kw) or {}).get(field)
                b = ((rl_e.get(m) or {}).get(kw) or {}).get(field)
                if a is not None and a != b and (b is None or b > a):
                    out.append({"what": u"%s %s" % (field.upper(), kw), "method": _fmt(a),
                                "project": _fmt(b), "where": m, "published": _PUBLISHED_NONE})
    grid_m = profile.get("labelled_standards") or {}
    grid_e = eff.get("labelled_standards") or {}
    for name in sorted(grid_m):
        if name not in grid_e:
            out.append({"what": u"Labelled standard %s" % name, "method": u"used",
                        "project": u"not used", "where": u"all matrices",
                        "published": _PUBLISHED_NONE})
    return out


# ── storage (Zope) ───────────────────────────────────────────────────────────

def get_specs(project):
    if project is None:
        return {}
    try:
        from zope.annotation.interfaces import IAnnotations
        raw = IAnnotations(project).get(KEY)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def save_specs(project, specs):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(project)[KEY] = json.dumps(specs or {}, sort_keys=True)


def project_by_id(portal, uid):
    """The Project by its FOLDER id (what the Projects page calls "uid"; the
    batch link holds the real Plone UID, which differs)."""
    from senaite.pfas.browser.projects import _get_projects_folder
    try:
        return _get_projects_folder(portal).get(uid) if uid else None
    except RuntimeError:
        return None


def save_for_project(portal, uid, specs, request=None):
    """Save (history-tracked, revertible) and re-export the project's linked
    batches. Returns (refreshed, skipped)."""
    project = project_by_id(portal, uid)
    if project is None:
        raise ValueError(u"No project %s" % uid)
    try:
        from senaite.pfas import config_history
        config_history.track(portal, "project_specs", uid, lambda: get_specs(project),
                             label=u"Project specs: %s" % (getattr(project, "title", None) or uid))
    except Exception:
        pass
    save_specs(project, specs)
    from senaite.pfas import resolved_criteria_store
    from bika.lims import api
    return resolved_criteria_store.refresh_linked_batches(
        portal, project_uid=api.get_uid(project), request=request)


def site_env():
    from senaite.pfas.method_profile_store import service_index
    return {"services": service_index()}


def effective_for_project(project, method_id, matrix, profile, env=None):
    """(effective profile, stale, has_specs) -- `profile` itself when the
    project holds no specs for this method (no env is built then)."""
    specs = (get_specs(project) or {}).get(method_id)
    if not specs:
        return profile, [], False
    eff, stale = effective(profile, specs, matrix, env=env if env is not None else site_env())
    return eff, stale, True


def profile_for_batch(portal, batch, method_id, matrix=None):
    """The profile a batch runs to: the method's, with its project's specs
    applied when the batch is linked to a project that has some. Every READER
    of a batch's criteria (certificate, Data Review) uses this, so they agree
    with what the pipeline applied (the batch's resolved file). Writers of
    the METHOD keep using method_profile_store directly."""
    from senaite.pfas.method_profile_store import get_profile
    profile = get_profile(portal, method_id) or {} if method_id else {}
    if batch is None or not profile:
        return profile
    try:
        from senaite.pfas import project_ref
        project = project_ref.get_project(portal, batch)
    except Exception:
        return profile
    if project is None:
        return profile
    return effective_for_project(project, method_id, matrix, profile)[0]
