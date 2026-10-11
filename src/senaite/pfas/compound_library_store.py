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

Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

try:
    from senaite.pfas import compound_library as cl
except ImportError:                            # tests: loaded without the package
    import compound_library as cl

logger = logging.getLogger("senaite.pfas.compound_library_store")

MIGRATION_KEY = "senaite.pfas.compound_library_v"
MIGRATION_V = 1
# the library read once per request (pages label every analyte through it)
_REQUEST_KEY = "_senaite_pfas_compound_library"


# ── a service's fields ─────────────────────────────────────────────────────

def _field(svc, name):
    try:
        field = svc.getField(name)
    except Exception:                                       # noqa: BLE001
        field = None
    if field is None:
        try:
            field = svc.Schema().get(name)
        except Exception:                                   # noqa: BLE001
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
    """A row per AnalysisService that carries a PFAS role -- the active and
    the inactive ones, as the worker has always known every compound."""
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


def seed_row(keyword):
    for row in cl.seed_rows():
        if row["keyword"] == keyword:
            return row
    return None


def migrate(portal):
    """Once per site: the seed's library facts (analyte_reference.py) onto
    every service of the seed, so the services hold exactly what the worker
    read from the code table. Facts already set are kept; a seed compound
    with no service is reported (the install creates every one of them).
    Returns {"written": n services, "missing": [keywords]} or None when it
    already ran."""
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    if ann.get(MIGRATION_KEY) == MIGRATION_V:
        return None
    result = migrate_services(_services())
    ann[MIGRATION_KEY] = MIGRATION_V
    if result["missing"]:
        logger.warning("compound library: no service for %s; their library facts "
                       "were not written", ", ".join(result["missing"]))
    logger.info("compound library: seed facts written onto %d services", result["written"])
    return result


def migrate_services(services):
    """The migration's writes: every seed row onto the service with its
    keyword (the first, if two share one). {"written", "missing"}."""
    by_kw = {}
    for svc in services:
        by_kw.setdefault(svc.getKeyword() or "", svc)
    written, missing = 0, []
    for row in cl.seed_rows():
        svc = by_kw.get(row["keyword"])
        if svc is None:
            missing.append(row["keyword"])
            continue
        if stamp_seed(svc, row):
            written += 1
            try:
                svc.reindexObject()
            except Exception:                               # noqa: BLE001
                pass
    return {"written": written, "missing": missing}


# ── a service saved in Setup ───────────────────────────────────────────────

def on_service_changed(svc, event):
    """IObjectModifiedEvent on an AnalysisService (added or edited): export
    the profiles and the library again, so the worker reads the change at its
    next run."""
    try:
        if svc.isTemporary():
            return
    except Exception:                                       # noqa: BLE001
        pass
    try:
        from bika.lims import api
        from zope.annotation.interfaces import IAnnotations
        portal = api.get_portal()
        if IAnnotations(portal).get(MIGRATION_KEY) != MIGRATION_V:
            return
        from senaite.pfas import method_profile_store as store
        store.export_profiles_to_file(portal, extra_service=svc)
    except Exception:                                       # noqa: BLE001
        logger.exception("compound library: export after a service change failed")
