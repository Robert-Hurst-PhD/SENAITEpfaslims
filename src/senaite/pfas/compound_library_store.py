# -*- coding: utf-8 -*-
"""The compound library on the core Analysis Services: reading it, writing
it to the worker, and the one-time migration of the install seed onto the
services.

    service_row(svc)        one service's library facts (a row for
                            compound_library.build)
    service_rows(extra)     every service with a PFAS role (the catalog, with
                            `extra` -- a service being saved -- read from the
                            object itself)
    library(portal)         the library as the services hold it now
    write_export(export, path)  atomic write (method_profile_store's export
                            writes it beside the method profiles)
    stamp_seed(svc, row)    write seed facts a service does not have yet
    migrate(portal)         once per site: every seed row onto its service
    on_service_changed      a service added or edited in Setup re-exports
                            the library (and the profiles, whose analyte
                            panels carry its display names); not before the
                            migration has run (an install creating its
                            services exports once, afterwards)
    refuse_referenced_removal  a service any method profile still names is
                            not deleted: the refusal lists each method and
                            where (unlink it from the method first)

Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

from senaite.pfas import compound_library as cl

logger = logging.getLogger("senaite.pfas.compound_library_store")

# the library read once per request (pages label every analyte through it)
_REQUEST_KEY = "_senaite_pfas_compound_library"


# ── a service's fields ─────────────────────────────────────────────────────

def _field(svc, name):
    try:
        field = svc.getField(name)
    except AttributeError:
        field = None
    if field is None:
        try:
            field = svc.Schema().get(name)
        except AttributeError:
            field = None
    return field


def _get(svc, name, default=""):
    field = _field(svc, name)
    if field is None:
        return default
    value = field.get(svc)
    return default if value is None else value


def _set(svc, name, value):
    field = _field(svc, name)
    if field is None:
        raise KeyError("%s has no field %s" % (svc.getKeyword(), name))
    field.set(svc, value)


def service_row(svc):
    """{keyword, role, name, cas, analog_of, aliases, published_names, key}"""
    row = {"keyword": svc.getKeyword() or "", "role": _get(svc, "pfas_role") or ""}
    for fact, field in cl.FIELDS:
        row[fact] = _get(svc, field, () if fact in cl.LIST_FACTS else "")
    row["key"] = bool(row.get("key"))
    return row


def _services():
    from bika.lims import api
    out = []
    for brain in api.get_tool("senaite_catalog_setup")(portal_type="AnalysisService"):
        try:
            out.append(brain.getObject())
        except Exception:                                   # noqa: BLE001
            logger.warning("compound library: catalogued service %s cannot be "
                           "read", brain.getPath())
    return out


def service_rows(extra=None):
    """A row per AnalysisService that carries a PFAS role, active or
    inactive: the worker knows every compound."""
    by_uid = dict((svc.UID(), svc) for svc in _services())
    if extra is not None:
        by_uid[extra.UID()] = extra          # not in the catalog yet when new
    rows = [service_row(svc) for svc in by_uid.values()]
    return sorted((r for r in rows if r["keyword"] and r["role"]),
                  key=lambda r: r["keyword"])


def library(portal=None, extra=None):
    """The library as the services hold it now: the same dict the worker
    reads from its export.

    Read once per request (callers never change it); `extra`, a service
    being saved, is read fresh. Outside SENAITE (tests and tools on the
    host, where there are no services) it is the install seed, as the
    migration writes it."""
    try:
        import bika.lims  # noqa: F401
    except ImportError:
        return cl.build(cl.seed_rows())
    request = None
    if extra is None:
        try:
            from zope.globalrequest import getRequest
            request = getRequest()
            cached = request.get(_REQUEST_KEY) if request is not None else None
            if cached is not None:
                return cached
        except Exception:                                   # noqa: BLE001
            request = None
    export = cl.build(service_rows(extra))
    if request is not None:
        try:
            request.set(_REQUEST_KEY, export)
        except Exception:                                   # noqa: BLE001
            pass
    return export


# ── the export the worker reads ────────────────────────────────────────────

def write_export(export, path):
    """Atomic: write to .tmp, then rename."""
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d)
        except OSError:
            pass
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(export, fh, indent=1, sort_keys=True)
    os.rename(tmp, path)
    for line in export.get("problems") or []:
        logger.warning("compound library: %s", line)
    logger.info("Exported the compound library (%d compounds) to %s",
                len(cl.compounds(export)), path)


# ── the install seed onto the services ─────────────────────────────────────

def _blank(value):
    if isinstance(value, (list, tuple)):
        return not [v for v in value if (v or "").strip()]
    return value in (None, "", False)


def stamp_seed(svc, row):
    """Write the seed's library facts onto `svc` where it has none yet; a
    fact the lab has set is never overwritten. The names written."""
    written = []
    for fact, field in cl.FIELDS:
        value = row.get(fact)
        if _blank(value) or _field(svc, field) is None:
            continue
        if not _blank(_get(svc, field, None)):
            continue
        _set(svc, field, tuple(value) if fact in cl.LIST_FACTS else value)
        written.append(field)
    return written


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return ("%s" % value).strip()


def seed_row(keyword):
    for row in cl.seed_rows():
        if row["keyword"] == keyword:
            return row
    return None


# ── a service deleted in Setup ─────────────────────────────────────────────

try:
    from zExceptions import BadRequest as RemovalRefused
except ImportError:                            # tests: loaded without Zope
    RemovalRefused = ValueError


def referenced_by(portal, keyword):
    """[(method id, where)] for every place a method profile names the
    compound `keyword` (compound_references.references over the stored
    profiles)."""
    from senaite.pfas import compound_references as cr
    from senaite.pfas import method_profile_store as store
    profiles = dict((mid, store.raw_profile(portal, mid)) for mid in store.list_method_ids(portal))
    return cr.references(profiles, keyword)


def refuse_referenced_removal(svc, event):
    """IObjectWillBeRemovedEvent on an AnalysisService: a service a method
    profile still names -- in its panel, surrogate map, salt, isomer,
    inclusion, integration or limit rows, or as a labelled standard -- is
    not deleted; the refusal names each method and where, so nothing is
    orphaned silently. Unlinking the service from the method in Setup takes
    its rows out of that profile, after which it can go. The removal of an
    ancestor (the whole folder) is not the service's own."""
    if event is not None and getattr(event, "object", svc) is not svc:
        return
    try:
        if svc.isTemporary():
            return
    except AttributeError:
        pass
    from bika.lims import api
    portal = api.get_portal()
    keyword = svc.getKeyword() or ""
    refs = referenced_by(portal, keyword)
    if not refs:
        return
    from senaite.pfas import method_profile_store as store
    by_method = []
    for mid, where in refs:
        if not by_method or by_method[-1][0] != mid:
            by_method.append((mid, []))
        by_method[-1][1].append(where)
    parts = []
    for mid, wheres in by_method:
        name = (store.raw_profile(portal, mid) or {}).get("display_name") or mid
        parts.append(u"%s (%s)" % (name, u", ".join(wheres)))
    raise RemovalRefused(
        u"%s is not deleted: a method still names it: %s. Unlink the service from "
        u"those methods in Setup (Analysis Services, Methods), which takes its rows "
        u"out of their profiles, or edit those rows; then delete it. To stop using "
        u"it without deleting it, deactivate it." % (keyword, u"; ".join(parts)))


# ── a service saved in Setup ───────────────────────────────────────────────

def on_service_removed(svc, event):
    """IObjectRemovedEvent on an AnalysisService: the panels lose it and the
    library is exported again from the catalogue alone, which no longer
    holds it, so the worker never resolves a compound the lab deleted."""
    _after_service_event(svc, extra=None)


def on_service_changed(svc, event):
    """IObjectModifiedEvent on an AnalysisService (added or edited): every
    method's analyte panel follows the service's Method links
    (refresh_analyte_sets), then the profiles and the library are exported
    again with the saved service read from the object (it may not be
    catalogued yet), so the worker reads the change at its next run."""
    _after_service_event(svc, extra=svc)


def _after_service_event(svc, extra):
    try:
        if svc.isTemporary():
            return
    except AttributeError:
        pass
    # the add-on's own modules are imported outside the best-effort export:
    # one that cannot be imported raises
    from senaite.pfas import method_profile_store as store
    from senaite.pfas import after_commit
    try:
        from bika.lims import api
        portal = api.get_portal()
        try:
            store.refresh_analyte_sets(portal)
        except Exception:                                   # noqa: BLE001
            logger.exception("analyte panels not refreshed after a service change")
        after_commit.run_once("method profiles export", store.export_profiles_to_file, portal, None, extra)
    except Exception:                                       # noqa: BLE001
        logger.exception("compound library: export after a service change failed")
