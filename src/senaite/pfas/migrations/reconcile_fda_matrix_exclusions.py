# -*- coding: utf-8 -*-
"""
Migration: reconcile the stored FDA analyte×matrix inclusion with the documented
carve-outs in _FDA_MATRIX_EXCLUSIONS.

Run inside the SENAITE container:

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/reconcile_fda_matrix_exclusions.py

Background: the FDA method document excludes some analytes from some matrices
(canonical: PFODA is NOT reportable in Eggs). The default seed applies these via
_fda_analyte_matrix_inclusion(), but a live profile's inclusion grid can drift
back to all-True if the Method×Matrix panel was saved before a carve-out was
encoded. This forces every DOCUMENTED carve-out cell to False in the stored
profile and leaves every other cell exactly as stored (respects legitimate
manager customisation). Idempotent; re-run safe; commits only if something
changed.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys

METHOD_ID = "FDA_32PFAS"


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

    try:
        from AccessControl.SecurityManagement import newSecurityManager
        app = globals().get("app") or portal.getPhysicalRoot()
        admin = app.acl_users.getUserById("admin")
        if admin is not None:
            newSecurityManager(None, admin.__of__(app.acl_users))
    except Exception as exc:
        print("WARN: could not set security manager: {}".format(exc))

    from zope.component.hooks import setSite, setHooks
    setHooks()
    setSite(portal)

    from senaite.pfas.method_profile_store import (
        get_profile, save_profile, get_included_analytes,
        _FDA_MATRIX_EXCLUSIONS)

    profile = get_profile(portal, METHOD_ID)
    inclusion = profile.get("analyte_matrix_inclusion", {}) or {}

    print("Documented FDA carve-outs: {}".format(dict(
        (k, sorted(v)) for k, v in _FDA_MATRIX_EXCLUSIONS.items())))

    changes = []
    for keyword, matrices in _FDA_MATRIX_EXCLUSIONS.items():
        row = inclusion.get(keyword)
        if row is None:
            row = {}
            inclusion[keyword] = row
        for matrix in matrices:
            current = row.get(matrix)
            if current is not False:
                print("  {} x {}: {!r} -> False".format(keyword, matrix, current))
                row[matrix] = False
                changes.append((keyword, matrix))

    if not changes:
        print("\nNo changes — stored inclusion already matches documented carve-outs.")
    else:
        profile["analyte_matrix_inclusion"] = inclusion
        save_profile(portal, METHOD_ID, profile)
        try:
            import transaction
            transaction.commit()
            print("\nCommitted {} carve-out correction(s).".format(len(changes)))
        except Exception as exc:
            print("ERROR committing: {}".format(exc))
            sys.exit(1)

    # Verification: reportable panel per matrix must exclude the carved-out analyte.
    print("\nVerification (get_included_analytes):")
    for keyword, matrices in _FDA_MATRIX_EXCLUSIONS.items():
        for matrix in matrices:
            panel = get_included_analytes(portal, METHOD_ID, matrix)
            ok = keyword not in panel
            print("  {} excluded from {}: {}  (panel size {})".format(
                keyword, matrix, "OK" if ok else "FAIL", len(panel)))
    # sanity: the analyte is still reportable in a NON-excluded matrix
    other = [m for m in ("Meat / Muscle", "Fish / Seafood", "Milk")
             if m in (inclusion.get("PFODA", {}))]
    if other:
        m = other[0]
        panel = get_included_analytes(portal, METHOD_ID, m)
        print("  PFODA still reportable in {}: {}  (panel size {})".format(
            m, "OK" if "PFODA" in panel else "FAIL", len(panel)))


run()
