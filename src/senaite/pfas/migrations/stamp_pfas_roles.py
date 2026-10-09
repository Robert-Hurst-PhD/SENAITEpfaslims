# -*- coding: utf-8 -*-
"""
Migration: stamp pfas_role onto all existing AnalysisService objects.

Run inside the SENAITE container:

  docker exec <container> bin/instance run \
    /home/senaite/senaitelims/src/senaite/pfas/migrations/stamp_pfas_roles.py

Reads the role from analyte_reference.py and internal_standards.csv
(via the in-memory tables) and writes it onto each AnalysisService via
the schema-extender mutator.

Idempotent.  Safe to run after adding new services.
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys

from senaite.pfas.analyte_reference import NATIVE_ANALYTES, INTERNAL_STANDARDS


def _build_role_map():
    """Return {keyword: pfas_role} for every known PFAS service."""
    roles = {}
    for row in NATIVE_ANALYTES:
        roles[row[0]] = "analyte"
    for row in INTERNAL_STANDARDS:
        roles[row[0]] = row[3]  # "surrogate" or "injection_is"
    return roles


def _get_pfas_role(obj):
    """Read pfas_role via Schema field (extension fields have no generated accessor)."""
    try:
        field = obj.Schema().get("pfas_role")
        if field is not None:
            return field.get(obj) or ""
    except Exception:
        pass
    return obj.__dict__.get("pfas_role", "")


def _stamp(obj, role):
    try:
        field = obj.Schema().get("pfas_role")
        if field is not None:
            field.set(obj, role)
            return True
    except Exception:
        pass
    # Fallback: direct attribute (works if extension field stores to __dict__)
    try:
        obj.__dict__["pfas_role"] = role
        return True
    except Exception as exc:
        print("  WARN: could not stamp {}: {}".format(
            getattr(obj, "getKeyword", lambda: "?")(), exc))
        return False


def run():
    try:
        app = globals().get("app")
        if app is None:
            from Testing.makerequest import makerequest
            import Zope2
            app = makerequest(Zope2.app())
        portals = [o for o in app.objectValues("Plone Site")]
        if not portals:
            raise RuntimeError("No Plone site found")
        portal = portals[0]
        from zope.site.hooks import setSite
        setSite(portal)
    except Exception as exc:
        print("ERROR: {}".format(exc))
        sys.exit(1)

    try:
        from bika.lims import api
        try:
            catalog = api.get_tool("senaite_catalog_setup")
        except Exception:
            catalog = api.get_tool("bika_setup_catalog")
        brains = catalog(portal_type="AnalysisService")
    except Exception as exc:
        print("ERROR listing services: {}".format(exc))
        sys.exit(1)

    role_map = _build_role_map()
    stamped = []
    skipped = []
    unknown = []

    for brain in brains:
        try:
            obj = brain.getObject()
            kw = getattr(obj, "getKeyword", lambda: "")() or ""
            if kw not in role_map:
                unknown.append(kw)
                continue
            role = role_map[kw]
            current = _get_pfas_role(obj)
            if current == role:
                skipped.append(kw)
                continue
            if _stamp(obj, role):
                try:
                    obj.reindexObject()
                except Exception:
                    pass
                stamped.append((kw, role))
                print("  stamped {} = {}".format(kw, role))
        except Exception as exc:
            print("  ERROR on {}: {}".format(brain.getPath(), exc))

    import transaction
    if stamped:
        transaction.commit()
        print("Transaction committed.")
    else:
        transaction.abort()

    print("\nDone. Stamped: {}  Already correct: {}  Unknown (skipped): {}".format(
        len(stamped), len(skipped), len(unknown)))
    if unknown:
        print("Unknown keywords (no role in analyte_reference.py):", unknown)


run()
