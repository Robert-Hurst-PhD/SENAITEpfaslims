# -*- coding: utf-8 -*-
"""Deleting a method: refused while anything uses it, listing what does.

A method is its profile (Method Profiles), the core SENAITE Method its
analyses and worksheets carry, and the method's OWN associations: the
analysis services and instruments the New Method Wizard linked to it, the
core Analysis Profiles generated from its Analyte x Matrix table, and the
wizard's records. Those go with it. Anything else that names the method is
a USE, and a use refuses the deletion: samples and analyses, worksheets and
batches (their analyses, extraction record, logbooks, run manifest), core
worksheet templates, QC results in the QC database, method studies and
study templates, logbook definitions scoped to it, SOPs, project
specifications, EDD method codes, chain-of-custody rows, issued method
revisions and the Reference Definitions' method. A store that cannot be read
refuses too: "not checked" is never "not used".

A shipped method follows the same rule. The installer re-runs on every
start and fills what is missing, so a deleted method is remembered (the
tombstone) and the installer does not seed it again; a method made again
with the same id is found and left alone.

    references(method_id, src)   pure: [(what, which)], the uses found
    removals(src)                pure: [(what, which)], what a deletion removes
    collect(portal, method_id)   read every store (Plone)
    delete(portal, method_id)    refuse (MethodInUse), or remove the method and
                                 its own associations; recorded in
                                 Configuration History, earlier entries kept
    deleted_ids(portal)          the tombstones
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("senaite.pfas.method_delete")

DELETED_KEY = "senaite.pfas.deleted_methods"     # {method id: JSON {by, at, label}}
HISTORY_STORE = "method_deleted"
MAX_LISTED = 8
LOGBOOK_PREFIX = "senaite.pfas.logbook."
QC_DB = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")


class MethodInUse(ValueError):
    """The method is used; `rows` names what uses it."""

    def __init__(self, rows):
        ValueError.__init__(self, u"; ".join(u"{0}: {1}".format(w, x) for w, x in rows))
        self.rows = rows


class MethodUnknown(ValueError):
    """No stored profile has that id."""


# ── pure ─────────────────────────────────────────────────────────────────────

def _u(value):
    """Text: a title or id as Zope returns it (UTF-8 bytes under Python 2)
    or text."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return u"" if value is None else u"%s" % (value,)


def listed(items):
    """Up to MAX_LISTED items, then how many more."""
    items = [t for t in (_u(i) for i in items) if t]
    shown = items[:MAX_LISTED]
    more = len(items) - len(shown)
    return u", ".join(shown) + (u" and {0} more".format(more) if more > 0 else u"")


def names_method(value, method_id, depth=0):
    """Whether a stored record (dicts and lists) names the method under a
    "method_id" or "method" key, at any depth."""
    if depth > 8 or not method_id:
        return False
    if isinstance(value, dict):
        if value.get("method_id") == method_id or value.get("method") == method_id:
            return True
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return False
    return any(names_method(v, method_id, depth + 1) for v in children
               if isinstance(v, (dict, list)))


def edd_codes_set(codes):
    """A method's EDD row is a use only when a code is entered in it: the EDD
    page writes a row, empty included, for every method it lists."""
    if isinstance(codes, dict):
        return any((u"%s" % v).strip() for k, v in codes.items()
                   if k != "method_id" and v is not None)
    return bool((u"%s" % (codes or u"")).strip())


def references(method_id, src):
    """[(what, which)] for every use of `method_id` in `src` (collect()'s
    shape; records as stored, the SOP / logbook slugs already resolved to
    method ids by their own stores)."""
    rows = []

    def add(what, items):
        items = [t for t in (_u(i) for i in items) if t]
        if items:
            rows.append((what, listed(items)))

    add(u"Samples whose analyses carry it", sorted(set(src.get("analyses") or [])))
    add(u"Samples registered with its analysis profiles",
        sorted(set(src.get("profile_samples") or [])))
    for what, key in ((u"Worksheets", "worksheets"), (u"Batches", "batches")):
        add(what, [u"{0} ({1})".format(_u(c.get("id")), u", ".join(_u(x) for x in c.get("sources") or []))
                   for c in src.get(key) or []])
    add(u"Worksheet templates restricted to it", src.get("worksheet_templates") or [])
    add(u"QC results database", [u"{0}: {1} rows".format(t, n)
                                 for t, n in sorted((src.get("qc_db") or {}).items()) if n])
    add(u"Method studies", [u"{0} ({1}, {2})".format(r.get("id"), r.get("kind"), r.get("status"))
                            for r in src.get("studies") or [] if r.get("method") == method_id])
    add(u"Study templates", [u"{0} {1}".format(_u(t.get("id")), _u(t.get("name"))).strip()
                             for t in src.get("study_templates") or [] if t.get("method") == method_id])
    add(u"Logbook definitions scoped to it",
        [u"{0} {1}".format(_u(d.get("form_num")), _u(d.get("title"))).strip()
         for d in src.get("logbook_defs") or [] if d.get("method") == method_id])
    add(u"SOPs and controlled documents",
        [u"{0} {1}".format(_u(e.get("sop_id")), _u(e.get("title"))).strip()
         for e in src.get("sops") or [] if e.get("method") == method_id])
    add(u"Project specifications",
        [p.get("title") for p in src.get("projects") or [] if (p.get("specs") or {}).get(method_id)])
    add(u"EDD profile method codes",
        [p.get("name") for p in src.get("edd_profiles") or []
         if edd_codes_set((p.get("codes") or {}).get(method_id))])
    add(u"Chain of custody records",
        [r.get("number") for r in src.get("cocs") or []
         if any((row or {}).get("method") == method_id for row in r.get("rows") or [])])
    add(u"Issued method revisions",
        [u"Rev {0} ({1})".format(r.get("rev"), (r.get("issued_at") or u"")[:10])
         for r in src.get("revisions") or []])
    if method_id and src.get("reference_method") == method_id:
        rows.append((u"Reference Definitions take their limits from it",
                     u"Configuration > Setup Reference Definitions"))
    for name, err in src.get("problems") or []:
        rows.append((u"Could not be checked", u"{0}: {1}".format(name, err)))
    return rows


def removals(src):
    """[(what, which)] a deletion removes: the method and its own
    associations, as collect() found them. A method the New Method Wizard
    stopped before its profile was written has a SENAITE method only."""
    rows = []
    if src.get("has_profile", True):
        rows.append((u"Method profile", _u(src.get("label") or src.get("method_id"))))
    core = src.get("core") or {}
    if core:
        rows.append((u"SENAITE method", _u(core.get("title") or core.get("id"))))
    for what, key in ((u"Unlinked from analysis services", "services"),
                      (u"Unlinked from instruments", "instruments"),
                      (u"Analysis profiles generated from it", "generated_profiles")):
        if src.get(key):
            rows.append((what, listed(sorted(_u(x) for x in src[key]))))
    wiz = []
    if src.get("association"):
        wiz.append(u"the method's links")
    if src.get("wizard_sessions"):
        wiz.append(u"{0} session(s)".format(len(src["wizard_sessions"])))
    if wiz:
        rows.append((u"New Method Wizard records", u", ".join(wiz)))
    if src.get("edd_empty"):
        rows.append((u"Empty EDD method-code rows", listed(sorted(_u(x) for x in src["edd_empty"]))))
    return rows


def history_entry(method_id, label, profile, who, at, removed):
    """The Configuration History entry a deletion writes: who, when, the
    profile as it stood (path by path) and what went with it."""
    try:
        from senaite.pfas.config_history import IGNORED_KEYS
    except ImportError:                                     # tests: loaded by path
        from config_history import IGNORED_KEYS
    return {
        "at": at, "who": who, "store": HISTORY_STORE, "key": method_id,
        "label": u"Method deleted: {0}".format(_u(label or method_id)),
        "note": u"Deleted from Method Profiles; nothing used it. Also removed: {0}.".format(
            u"; ".join(u"{0}: {1}".format(_u(w), _u(x)) for w, x in removed) or u"nothing"),
        "changes": [{"path": [k], "before": v, "after": None}
                    for k, v in sorted((profile or {}).items()) if k not in IGNORED_KEYS],
    }


# ── tombstones (Plone) ───────────────────────────────────────────────────────

def deleted_ids(portal):
    """The ids of deleted methods: the installer seeds none of them again.
    Never raises (an unreadable store means none)."""
    try:
        from zope.annotation.interfaces import IAnnotations
        return frozenset((IAnnotations(portal).get(DELETED_KEY) or {}).keys())
    except Exception:                                       # noqa: BLE001
        return frozenset()


def _tombstone(portal, method_id, who, at, label):
    from persistent.mapping import PersistentMapping
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    if DELETED_KEY not in ann:
        ann[DELETED_KEY] = PersistentMapping()
    ann[DELETED_KEY][method_id] = json.dumps({"by": who, "at": at, "label": label})


# ── reading every store (Plone) ──────────────────────────────────────────────

def core_method(portal, method_id):
    """The core Method of this profile: the wizard's link, else the one whose
    MethodID is the profile id. Never a title match: a deletion must not take
    another method's record."""
    from bika.lims import api
    from senaite.pfas.method_bridge import get_association
    uid = get_association(portal, method_id).get("method_uid")
    obj = api.get_object_by_uid(uid, default=None) if uid else None
    if obj is not None and (getattr(obj, "getMethodID", lambda: None)() or method_id) == method_id:
        return obj
    for b in api.search({"portal_type": str("Method")}, "senaite_catalog_setup"):
        o = b.getObject()
        if getattr(o, "getMethodID", lambda: None)() == method_id:
            return o
    return None


def _url_tail(url):
    return [p for p in (url or u"").split("?")[0].rstrip("/").split("/") if p][-2:]


def _analyses(portal, core):
    """Ids of the samples (or reference samples) whose analyses carry the
    core Method: the analysis catalog's method metadata, checked on the
    object where only the title matches."""
    if core is None:
        return []
    from bika.lims import api
    tail = ["methods", core.getId()]
    title, uid = core.Title(), api.get_uid(core)
    out = set()
    types = [str(t) for t in ("Analysis", "ReferenceAnalysis", "DuplicateAnalysis", "RejectAnalysis")]
    for b in api.search({"portal_type": types}, "senaite_catalog_analysis"):
        url = getattr(b, "getMethodURL", None) or u""
        hit = _url_tail(url) == tail if url else False
        if not hit and title and getattr(b, "getMethodTitle", None) == title:
            o = b.getObject()
            raw = o.getRawMethod() if hasattr(o, "getRawMethod") else None
            hit = raw == uid
        if hit:
            sid = getattr(b, "getRequestID", None)
            if not sid:
                parent = _url_tail(getattr(b, "getParentURL", None) or u"")
                sid = parent[-1] if parent else b.getId
            out.add(sid)
    return sorted(out)


def _logbook_sources(obj, method_id):
    from zope.annotation.interfaces import IAnnotations
    names = []
    ann = IAnnotations(obj)
    for key in list(ann.keys()):
        if not ("%s" % key).startswith(LOGBOOK_PREFIX):
            continue
        raw = ann.get(key)
        try:
            data = json.loads(raw) if isinstance(raw, (str, type(u""))) else raw
        except (TypeError, ValueError):
            continue
        if names_method(data, method_id):
            names.append(u"logbook {0}".format(("%s" % key)[len(LOGBOOK_PREFIX):]))
    return names


def _container_sources(obj, method_id, core_uid):
    """The places on a worksheet or batch that name the method."""
    from senaite.pfas import batch_method
    found = []
    if core_uid and hasattr(obj, "getRawMethod") and obj.getRawMethod() == core_uid:
        found.append(u"its SENAITE method")
    for name, value in batch_method.sources(obj).items():
        named = method_id in value if isinstance(value, (list, tuple, set)) else value == method_id
        if named:
            found.append(batch_method.LABELS.get(name, name))
    for n in _logbook_sources(obj, method_id):
        if n not in found:
            found.append(n)
    return found


def _containers(portal, method_id, core, portal_type, catalog):
    from bika.lims import api
    core_uid = api.get_uid(core) if core is not None else None
    out = []
    for b in api.search({"portal_type": str(portal_type)}, catalog):
        obj = b.getObject()
        found = _container_sources(obj, method_id, core_uid)
        if found:
            out.append({"id": _u(obj.getId() if portal_type == "Worksheet" else (obj.Title() or obj.getId())),
                        "sources": found})
    return out


def _worksheet_templates(core):
    if core is None:
        return []
    from bika.lims import api
    uid = api.get_uid(core)
    out = []
    for b in api.search({"portal_type": str("WorksheetTemplate")}, "senaite_catalog_setup"):
        o = b.getObject()
        raw = getattr(o, "getRawRestrictToMethod", lambda: None)()
        if raw == uid:
            out.append(_u(o.Title()))
    return out


def qc_db_counts(method_id, path=QC_DB):
    """{table: rows naming the method} for every table of the QC database with
    a method column. A missing file is no rows (and is not created)."""
    if not os.path.exists(path):
        return {}
    import sqlite3
    con = sqlite3.connect(path)
    try:
        out = {}
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t.replace('"', ""))]
            if "method" in cols:
                n = con.execute('SELECT COUNT(*) FROM "%s" WHERE method=?' % t.replace('"', ""),
                                (method_id,)).fetchone()[0]
                if n:
                    out[t] = n
        return out
    finally:
        con.close()


def _associations(portal, core):
    """(services, instruments) linked to the core Method: their titles."""
    if core is None:
        return [], []
    from bika.lims import api
    uid = api.get_uid(core)
    services, instruments = [], []
    for portal_type, out in (("AnalysisService", services), ("Instrument", instruments)):
        for b in api.search({"portal_type": str(portal_type)}, "senaite_catalog_setup"):
            o = b.getObject()
            if uid in _linked_uids(o):
                out.append(_u(o.Title()))
    return services, instruments


def _linked_uids(obj):
    out = []
    for name in ("Methods", "Method"):
        field = obj.getField(name) if hasattr(obj, "getField") else None
        if field is None:
            continue
        raw = field.getRaw(obj)
        out.extend(raw if isinstance(raw, (list, tuple)) else [raw])
    return [u for u in out if u]


def _unlink(obj, uid):
    """Remove `uid` from the object's Methods / default Method, through the
    fields' own setters."""
    changed = False
    for name in ("Methods", "Method"):
        field = obj.getField(name) if hasattr(obj, "getField") else None
        if field is None:
            continue
        raw = field.getRaw(obj)
        if isinstance(raw, (list, tuple)):
            keep = [u for u in raw if u != uid]
            if len(keep) != len(raw):
                field.getMutator(obj)(keep)
                changed = True
        elif raw == uid:
            field.getMutator(obj)(None)
            changed = True
    if changed:
        obj.reindexObject()
    return changed


def collect(portal, method_id):
    """Every store read for `method_id`: the uses (references()) and the
    method's own associations (removals()). A store that cannot be read is
    listed under "problems", which refuses the deletion."""
    from bika.lims import api
    from senaite.pfas import analysis_profiles, method_profile_store as mps
    src = {"method_id": method_id, "problems": []}

    def guarded(name, fn, default=None):
        try:
            return fn()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("method delete: %s unreadable for %s: %s", name, method_id, exc)
            src["problems"].append((name, u"%s" % exc))
            return default

    profile = mps.raw_profile(portal, method_id) or {}
    folder = portal.get("pfas_method_profiles")
    src["has_profile"] = bool(method_id) and folder is not None and method_id in folder
    src["profile"] = profile
    src["label"] = _u(profile.get("display_name") or method_id)
    core = guarded("the SENAITE method", lambda: core_method(portal, method_id))
    if core is not None:
        src["core"] = {"id": _u(core.getId()), "title": _u(core.Title()), "uid": api.get_uid(core)}
    src["analyses"] = guarded("analyses", lambda: _analyses(portal, core), [])
    src["worksheets"] = guarded("worksheets", lambda: _containers(
        portal, method_id, core, "Worksheet", "senaite_catalog_worksheet"), [])
    src["batches"] = guarded("batches", lambda: _containers(
        portal, method_id, core, "Batch", "senaite_catalog"), [])
    src["worksheet_templates"] = guarded("worksheet templates", lambda: _worksheet_templates(core), [])
    src["qc_db"] = guarded("QC results database", lambda: qc_db_counts(method_id), {})

    def studies():
        from senaite.pfas import study_records
        return study_records.load(portal)
    src["studies"] = guarded("method studies", studies, [])

    def templates():
        from senaite.pfas import study_templates
        return study_templates.load(portal)
    src["study_templates"] = guarded("study templates", templates, [])

    def logbook_defs():
        from senaite.pfas.logbook_store import get_logbook_defs, method_key
        key = method_key(method_id)
        return [dict(d, method=method_id if d.get("method_slug") and method_key(d["method_slug"]) == key
                     else u"") for d in get_logbook_defs(portal)]
    src["logbook_defs"] = guarded("logbook definitions", logbook_defs, [])

    def sops():
        from senaite.pfas.browser.sop_documents import _get_registry, method_key
        return [dict(e, method=method_key(e.get("method_slug"))) for e in _get_registry(portal)]
    src["sops"] = guarded("SOPs", sops, [])

    def projects():
        from senaite.pfas.project_specs import get_specs
        folder = portal.get("pfas_projects")
        return [{"title": _u(p.Title() or p.getId()), "specs": get_specs(p)}
                for p in (folder.objectValues() if folder is not None else [])]
    src["projects"] = guarded("project specifications", projects, [])

    def edd():
        from senaite.pfas import edd_store
        return [{"id": pid, "name": p.get("name") or pid,
                 "codes": edd_store.section(p, "method_codes") or {}}
                for pid, p in sorted(edd_store.get_edd_profiles(portal).items())]
    src["edd_profiles"] = guarded("EDD profiles", edd, [])
    saved_edd = guarded("EDD profiles", lambda: _saved_edd_rows(portal, method_id), [])
    src["edd_empty"] = [name for pid, name, codes in saved_edd if not edd_codes_set(codes)]

    def cocs():
        from senaite.pfas import coc_records as cr
        return [r for r in (cr.load(portal, n) for n in cr.numbers(portal)) if r]
    src["cocs"] = guarded("chain of custody records", cocs, [])

    def revisions():
        from senaite.pfas import method_revisions
        return method_revisions.records(portal, method_id)
    src["revisions"] = guarded("method revisions", revisions, [])

    def reference_method():
        from senaite.pfas.setuphandlers import get_reference_method
        return get_reference_method(portal)
    src["reference_method"] = guarded("Reference Definitions' method", reference_method, u"")

    generated = guarded("analysis profiles", lambda: analysis_profiles.generated(portal, method_id), {})
    gen_objs = [o for o in (api.get_object_by_uid(u, default=None) for u in (generated or {}).values())
                if o is not None]
    src["generated_profiles"] = [_u(o.Title()) for o in gen_objs]
    src["profile_samples"] = guarded("samples' analysis profiles",
                                     lambda: _profile_samples(gen_objs), [])
    services, instruments = guarded("services and instruments",
                                    lambda: _associations(portal, core), ([], []))
    src["services"], src["instruments"] = services, instruments
    from senaite.pfas.method_bridge import get_association
    src["association"] = bool(get_association(portal, method_id))
    src["wizard_sessions"] = guarded("New Method Wizard sessions",
                                     lambda: _wizard_sessions(portal, method_id), [])
    return src


def _saved_edd_rows(portal, method_id):
    """[(profile id, name, the method's codes)] of the SAVED EDD profiles that
    carry a row for the method."""
    from senaite.pfas import edd_store
    out = []
    for pid, raw in list(edd_store._store(portal).items()):
        try:
            prof = json.loads(raw)
        except (TypeError, ValueError):
            continue
        codes = prof.get("method_codes") or {}
        if method_id in codes:
            out.append((pid, prof.get("name") or pid, codes[method_id]))
    return out


def _profile_samples(gen_objs):
    """Samples registered with one of the method's generated Analysis
    Profiles (their profile titles, as the sample catalog states them)."""
    if not gen_objs:
        return []
    from bika.lims import api
    titles = [_u(o.Title()) for o in gen_objs if o.Title()]
    out = []
    for b in api.search({"portal_type": str("AnalysisRequest")}, "senaite_catalog_sample"):
        names = _u(getattr(b, "getProfilesTitleStr", u"") or u"")
        if any(t in names for t in titles):
            out.append(b.getId)
    return out


def _wizard_sessions(portal, method_id):
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.browser.method_wizard import WIZARD_SESSIONS_KEY
    out = []
    for wid, raw in list((IAnnotations(portal).get(WIZARD_SESSIONS_KEY) or {}).items()):
        try:
            sess = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            continue
        if sess.get("method_id") == method_id:
            out.append(wid)
    return out


# ── the deletion (Plone) ─────────────────────────────────────────────────────

def report(portal, method_id):
    """(uses, removals) for the confirm step."""
    src = collect(portal, method_id)
    return references(method_id, src), removals(src)


def delete(portal, method_id, who=None):
    """Delete the method, or raise MethodInUse naming what uses it (and
    MethodUnknown for an id with neither a profile nor a SENAITE method).
    Returns removals(). The uses are read again here, at the deletion,
    whatever a confirm page showed. A SENAITE method the New Method Wizard
    made before it stopped (no profile yet) is deleted the same way."""
    folder = portal.get("pfas_method_profiles")
    if not method_id:
        raise MethodUnknown(u"No method was named.")
    src = collect(portal, method_id)
    has_profile = folder is not None and method_id in folder
    if not has_profile and not src.get("core"):
        raise MethodUnknown(u"{0} is not a configured method.".format(method_id))
    uses = references(method_id, src)
    if uses:
        raise MethodInUse(uses)
    from bika.lims import api
    from senaite.pfas import config_history
    removed = removals(src)
    who = who or _current_user()
    at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    # recorded first, in the same transaction: no entry, no deletion
    config_history.append(portal, history_entry(method_id, src["label"], src["profile"],
                                                who, at, removed[1:] if has_profile else removed))
    core = core_method(portal, method_id)
    if core is not None:
        uid = api.get_uid(core)
        for portal_type in ("AnalysisService", "Instrument"):
            for b in api.search({"portal_type": str(portal_type)}, "senaite_catalog_setup"):
                _unlink(b.getObject(), uid)
    _delete_generated_profiles(portal, method_id)
    if core is not None:
        api.delete(core, check_permissions=False)
    if has_profile:
        api.delete(folder[method_id], check_permissions=False)
    _forget(portal, method_id)
    _drop_empty_edd_rows(portal, method_id)
    _tombstone(portal, method_id, who, at, src["label"])
    try:
        from senaite.pfas.retention_sync import sync
        for line in sync(portal):
            logger.info("retention: %s", line)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("method %s deleted; Sample Type retention not synced: %s", method_id, exc)
    # the worker's copy follows the commit, never a deletion that rolled back
    import transaction
    transaction.get().addAfterCommitHook(_export_after_commit, args=(portal,))
    logger.info("method %s deleted by %s", method_id, who)
    return removed


def _export_after_commit(ok, portal):
    if not ok:
        return
    try:
        from senaite.pfas.method_profile_store import export_profiles_to_file
        export_profiles_to_file(portal)
    except Exception as exc:                                # noqa: BLE001
        logger.error("method deleted but the worker's export was not rewritten: %s", exc)


def _current_user():
    try:
        from bika.lims import api
        user = api.get_current_user()
        return (user.getId() if user is not None else None) or u"system"
    except Exception:                                       # noqa: BLE001
        return u"system"


def _delete_generated_profiles(portal, method_id):
    from bika.lims import api
    from senaite.pfas import analysis_profiles
    from zope.annotation.interfaces import IAnnotations
    for uid in analysis_profiles.generated(portal, method_id).values():
        obj = api.get_object_by_uid(uid, default=None)
        if obj is not None:
            api.delete(obj, check_permissions=False)
    store = IAnnotations(portal).get(analysis_profiles.KEY)
    if store is not None and method_id in store:
        del store[method_id]


def _forget(portal, method_id):
    """The method's records outside its profile: the wizard's links and
    sessions, and the legacy annotation copy of its profile."""
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.method_bridge import METHOD_ASSOC_KEY
    from senaite.pfas.method_profile_store import PFAS_METHOD_PROFILES_KEY
    from senaite.pfas.browser.method_wizard import WIZARD_SESSIONS_KEY
    ann = IAnnotations(portal)
    for key in (METHOD_ASSOC_KEY, PFAS_METHOD_PROFILES_KEY):
        store = ann.get(key)
        if store is not None and method_id in store:
            del store[method_id]
    sessions = ann.get(WIZARD_SESSIONS_KEY)
    for wid in _wizard_sessions(portal, method_id):
        if sessions is not None and wid in sessions:
            del sessions[wid]


def _drop_empty_edd_rows(portal, method_id):
    """A saved EDD profile's empty row for the method goes with it (a row with
    a code entered is a use and refused the deletion)."""
    from senaite.pfas import edd_store
    for pid, _name, codes in _saved_edd_rows(portal, method_id):
        if edd_codes_set(codes):
            continue
        prof = edd_store.get_profile(portal, pid)
        rows = dict(edd_store.section(prof, "method_codes") or {})
        rows.pop(method_id, None)
        edd_store.save_profile_section(portal, pid, "method_codes", rows)
