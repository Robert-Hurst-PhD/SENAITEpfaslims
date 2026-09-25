# -*- coding: utf-8 -*-
"""
Migration: remove the EnvironmentalReading FTI from portal_types.

Run inside the SENAITE container:

  docker exec <container> bin/instance -O senaite run \
    /addon/src/senaite/pfas/migrations/remove_envreading_type.py

WHY THIS SCRIPT EXISTS AT ALL. Deleting the type's XML from
profiles/default/types.xml and its class from content.zcml removes it from the
PACKAGE, not from an installed SITE: GenericSetup's types.xml is additive, so an
FTI already created in portal_types stays there. Left behind, it would be a
worse object than the orphan it replaced -- an FTI whose `klass` and `schema`
point at senaite.pfas.content.envreading, a module that no longer exists, so
anything walking portal_types (the add form menu, a catalog reindex, a
GenericSetup export) hits an ImportError instead of a missing type.

WHY THE TYPE IS GOING. Facility monitoring is owned by
/data/qc/facility_monitoring.db -- `facility_qc.temperature_readings` carries
unit/sensor/ts/temperature/humidity/in_range, and `temperature_studies` carries
the NIST verification metadata. Between them they cover every field
IEnvironmentalReading declared, which made the Dexterity type a second store for
one fact: the CLAUDE.md Sec1 rule 3 shape.

It had also never worked. `pfas_pipeline.senaite_connector.push_sensor_reading`
was its only intended producer and was broken four independent ways at once: no
caller anywhere in the tree, a parent_path (/senaite/env-monitoring) that does
not exist, POSTed field names ("Temperature"/"Humidity") that do not match the
schema (temperature_c/humidity_pct), and an `except requests.HTTPError` that
logged the failure at DEBUG. Any ONE of those is enough for silence.

WHAT THIS DOES NOT FIX. GAPS.md Sec10.3 stands unchanged: facility_units and
temperature_readings both hold zero rows, so no Sec6.4 monitoring has ever been
recorded on this instance. What is missing is an ingest path into the SQLite
store. Removing a type that never held anything neither creates nor closes that
gap -- it just stops there being two candidate answers to "where does a
temperature reading live".

SAFETY: refuses to remove the FTI if ANY EnvironmentalReading object exists,
catalogued or not. Verified 0 on this instance (catalog and a depth-4 walk) on
2026-09-25 before the type was removed from the package; the check is repeated
here because a different site is a different question.

Safe to run more than once (idempotent). Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys

PORTAL_TYPE = "EnvironmentalReading"


def _get_portal():
    app_obj = globals().get("app")
    if app_obj is None:
        import Zope2
        from Testing.makerequest import makerequest
        app_obj = makerequest(Zope2.app())
    portals = [o for o in app_obj.objectValues("Plone Site")]
    if not portals:
        print("ERROR: no Plone site found.")
        sys.exit(1)
    return portals[0]


def _count_instances(portal):
    """How many EnvironmentalReading objects exist, catalogued or not.

    The catalog alone is not enough: an object created before an index existed,
    or one whose reindex failed, is invisible to a portal_type query while still
    being perfectly present in the ZODB. Deleting an FTI under it would leave an
    object whose type cannot be resolved, so the walk is the deciding check and
    the catalog count is reported only for contrast.
    """
    from Products.CMFCore.utils import getToolByName
    catalogued = 0
    try:
        catalogued = len(getToolByName(portal, "portal_catalog")(
            portal_type=PORTAL_TYPE))
    except Exception as exc:
        print("  (catalog query failed: {0!r})".format(exc))

    walked = []

    def walk(obj, depth=0):
        if depth > 6:
            return
        for oid in getattr(obj, "objectIds", lambda: [])():
            try:
                child = obj[oid]
            except Exception:
                continue
            if getattr(child, "portal_type", None) == PORTAL_TYPE:
                walked.append("/".join(child.getPhysicalPath()))
            walk(child, depth + 1)

    walk(portal)
    return catalogued, walked


def run():
    portal = _get_portal()
    from Products.CMFCore.utils import getToolByName
    types_tool = getToolByName(portal, "portal_types")

    if PORTAL_TYPE not in types_tool.objectIds():
        print("{0} is not registered in portal_types — nothing to do."
              .format(PORTAL_TYPE))
        return

    catalogued, walked = _count_instances(portal)
    print("{0}: {1} catalogued, {2} found by walking the site."
          .format(PORTAL_TYPE, catalogued, len(walked)))

    if walked:
        print("REFUSING to remove the FTI: objects of this type exist.")
        for path in walked[:20]:
            print("  {0}".format(path))
        if len(walked) > 20:
            print("  ... and {0} more".format(len(walked) - 20))
        print("Migrate these into facility_monitoring.db "
              "(facility_qc.temperature_readings) first, then re-run.")
        sys.exit(1)

    types_tool.manage_delObjects([PORTAL_TYPE])
    print("Removed the {0} FTI from portal_types. Facility monitoring is now "
          "owned solely by /data/qc/facility_monitoring.db.".format(
              PORTAL_TYPE))

    try:
        import transaction
        transaction.commit()
        print("Transaction committed.")
    except Exception as exc:
        print("ERROR committing transaction: {0}".format(exc))
        sys.exit(1)


if __name__ == "__main__" or "app" in globals():
    run()
