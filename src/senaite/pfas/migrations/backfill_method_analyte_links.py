# -*- coding: utf-8 -*-
"""
Migration (D59): backfill the native Method↔AnalysisService links that make the
per-method analyte set derivable from services.

Run inside the SENAITE container:

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/backfill_method_analyte_links.py

The 3 seeded methods (FDA_32PFAS, EPA_537_1, EPA_1633A) were installed via
setuphandlers, which stamps pfas_role="analyte" but never calls setMethods, so
their analyte services were not linked to their core Method. This step links each
core Method to exactly the services in that profile's stored master_analyte_set
(the reported natives — NOT the isomer-sum components br-PFHxS/br-PFOS). After
this, get_master_analyte_set() derives the set from getMethods(). Idempotent;
merges with existing Methods; never removes links. New/edited methods self-link
via the new-method wizard going forward.

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

    # security context for catalog lookups / object writes
    try:
        from AccessControl.SecurityManagement import newSecurityManager
        app = globals().get("app") or portal.getPhysicalRoot()
        admin = app.acl_users.getUserById("admin")
        if admin is not None:
            newSecurityManager(None, admin.__of__(app.acl_users))
    except Exception as exc:
        print("WARN: could not set security manager: {}".format(exc))

    # plone.api / bika.lims.api.get_tool resolve through getSite(); a bin/instance
    # run script has no active site, so without this the catalog lookups inside
    # link_method_analytes / get_master_analyte_set silently return nothing and
    # the whole backfill no-ops. (Documented gotcha.)
    from zope.component.hooks import setSite, setHooks
    setHooks()
    setSite(portal)

    from senaite.pfas.method_bridge import link_method_analytes
    from senaite.pfas.method_profile_store import (
        get_master_analyte_set, get_profile)

    result = link_method_analytes(portal)

    for mid, added in result["methods"]:
        print("  {:<12} linked +{} service(s)".format(mid, added))
    for mid, label in result["unmatched_methods"]:
        print("  UNMATCHED {}: no core Method titled {!r} (create it, then re-run)"
              .format(mid, label))
    for mid, kws in result["missing_services"].items():
        print("  MISSING SERVICES for {}: {}".format(mid, ", ".join(kws)))

    try:
        import transaction
        if result["links_added"]:
            transaction.commit()
            print("Transaction committed ({} links added).".format(
                result["links_added"]))
        else:
            transaction.abort()
            print("No new links (already backfilled); aborted.")
    except Exception as exc:
        print("ERROR committing transaction: {}".format(exc))
        sys.exit(1)

    # Verification. NOTE: comparing get_master_analyte_set() to the stored list
    # is a tautology — its fallback returns the stored list too, so it passes
    # even if the service derivation never engaged. Instead we count the ACTUAL
    # getMethods() linkage independently and require it to be non-empty AND to
    # equal the stored count. n == 0 means the derivation is silently falling
    # back → FAIL loudly.
    from senaite.pfas.method_bridge import get_core_method
    from bika.lims import api
    setup_cat = api.get_tool("senaite_catalog_setup")

    print("\nVerification (independent getMethods() linkage count):")
    ok = True
    for mid, _added in result["methods"]:
        profile = get_profile(portal, mid)
        stored = list(profile.get("master_analyte_set", []))
        method = get_core_method(portal, mid)
        n = 0
        linked_kws = set()
        if method is not None:
            muid = method.UID()
            for brain in setup_cat(portal_type="AnalysisService"):
                svc = brain.getObject()
                rf = svc.getField("pfas_role")
                if ((rf.get(svc) if rf is not None else "") or "") != "analyte":
                    continue
                try:
                    muids = [m.UID() for m in (svc.getMethods() or [])]
                except Exception:
                    muids = []
                if muid in muids:
                    n += 1
                    linked_kws.add(svc.getKeyword())
        # also confirm the derived list matches stored (order + membership)
        derived = get_master_analyte_set(portal, mid, profile=profile)
        good = (method is not None and n > 0 and n == len(stored)
                and derived == stored)
        ok = ok and good
        print("  {:<12} {}  (linked_services={}, stored={}, derived={})".format(
            mid, "OK" if good else "FAIL", n, len(stored), len(derived)))
        if not good:
            if method is None:
                print("    -> no core Method linked (get_core_method None)")
            elif n == 0:
                print("    -> ZERO services linked via getMethods(): derivation "
                      "is falling back to the stored list, NOT active")
            else:
                print("    stored - linked: {}".format(
                    sorted(set(stored) - linked_kws)))
                print("    linked - stored: {}".format(
                    sorted(linked_kws - set(stored))))

    print("\nDone. {}".format(
        "All methods verified (service linkage active)." if ok
        else "VERIFICATION FAILED — review above; derivation is NOT active."))


run()
