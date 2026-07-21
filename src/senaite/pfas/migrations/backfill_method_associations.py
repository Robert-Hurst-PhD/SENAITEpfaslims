# -*- coding: utf-8 -*-
"""
Migration: backfill the profile ⇄ core Method bridge (method_associations).

Run inside the SENAITE container:

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/backfill_method_associations.py

The 3 seeded methods (FDA_32PFAS, EPA_537_1, EPA_1633A) were installed via
setuphandlers, not the new-method wizard, so their method_associations entry was
never written. This step links each profile to its core SENAITE Method (matched
by title) plus the AnalysisService + SampleType UIDs it governs. Idempotent;
reports unmatched profiles (never guesses). New/edited profiles self-link via
save_profile going forward.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys


def _get_portal():
    try:
        app = globals().get("app")
        if app is None:
            from Testing.makerequest import makerequest
            import Zope2
            app = makerequest(Zope2.app())
        portals = [o for o in app.objectValues("Plone Site")]
        if not portals:
            raise RuntimeError("No Plone site found in app")
        return portals[0]
    except Exception as exc:
        print("ERROR: could not obtain portal: {}".format(exc))
        sys.exit(1)


def run():
    portal = _get_portal()

    # security context for catalog lookups / annotation writes
    try:
        from AccessControl.SecurityManagement import newSecurityManager
        app = globals().get("app") or portal.getPhysicalRoot()
        admin = app.acl_users.getUserById("admin")
        if admin is not None:
            newSecurityManager(None, admin.__of__(app.acl_users))
    except Exception as exc:
        print("WARN: could not set security manager: {}".format(exc))

    from senaite.pfas.method_bridge import link_all, get_association

    result = link_all(portal)

    for mid in result["linked"]:
        a = get_association(portal, mid)
        print("  linked {:<12} -> {} ({})  services={} sampletypes={}".format(
            mid, a.get("method_id"), a.get("method_title", "")[:40],
            len(a.get("service_uids", [])), len(a.get("sampletype_uids", []))))
    for mid, label in result["unmatched"]:
        print("  UNMATCHED {}: no core Method titled {!r} (create it, then re-run)"
              .format(mid, label))

    try:
        import transaction
        if result["linked"]:
            transaction.commit()
            print("Transaction committed.")
        else:
            transaction.abort()
    except Exception as exc:
        print("ERROR committing transaction: {}".format(exc))
        sys.exit(1)

    print("\nDone. Linked: {}  Unmatched: {}".format(
        len(result["linked"]), len(result["unmatched"])))


run()
