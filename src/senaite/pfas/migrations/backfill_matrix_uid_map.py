# -*- coding: utf-8 -*-
"""
Migration: backfill matrix_uid_map on method profiles (audit D4).

Run inside the SENAITE container:

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/backfill_matrix_uid_map.py

Profiles reference matrices by title string. As of D4, save_profile persists a
matrix_uid_map ({title: core SampleType UID}) so each matrix references the
canonical core object. This one-shot step backfills that map onto profiles that
were saved *before* the change (new saves already populate it).

For every profile it resolves each supported_matrices title -> SampleType UID
via matrix_ref. Unresolved titles (no matching core SampleType) are REPORTED,
never guessed. Only profiles whose stored map differs from the freshly resolved
one are re-saved, so the script is idempotent (second run changes nothing).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys


def _get_portal():
    """Return the Plone portal object via Zope's app."""
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


def _persist_profile(portal, method_id, profile):
    """Write the profile back to its store (Dexterity folder or annotation),
    WITHOUT save_profile's side effects (spec_sync / file export). Those are
    not appropriate for a targeted map backfill and fail in a script context."""
    import json
    from senaite.pfas.method_profile_store import (
        _get_profiles_folder, get_profile_store,
    )
    folder = _get_profiles_folder(portal)
    if folder is not None and method_id in folder:
        obj = folder[method_id]
        obj.profile_json = json.dumps(profile)
        try:
            obj.reindexObject()
        except Exception:
            pass
    else:
        store = get_profile_store(portal)
        store[method_id] = json.dumps(profile)


def run():
    from senaite.pfas.method_profile_store import (
        list_method_ids, get_profile, export_profiles_to_file,
    )
    from senaite.pfas.matrix_ref import title_to_uid

    portal = _get_portal()

    # Establish security context so catalog lookups / saves are permitted.
    # The admin user lives at the Zope app root acl_users, not the portal's.
    try:
        from AccessControl.SecurityManagement import newSecurityManager
        app = globals().get("app")
        if app is None:
            app = portal.getPhysicalRoot()
        admin = app.acl_users.getUserById("admin")
        if admin is not None:
            newSecurityManager(None, admin.__of__(app.acl_users))
        else:
            print("WARN: admin user not found in app acl_users")
    except Exception as exc:
        print("WARN: could not set security manager: {}".format(exc))

    method_ids = list_method_ids(portal)
    if not method_ids:
        print("No stored profiles found — nothing to backfill.")
        return

    changed = []
    unchanged = []
    unresolved = []

    for mid in method_ids:
        try:
            prof = get_profile(portal, mid)
        except Exception as exc:
            print("  WARN: cannot read profile {}: {}".format(mid, exc))
            continue

        titles = [t for t in (prof.get("supported_matrices") or [])
                  if t and not isinstance(t, dict)]
        fresh = {}
        for t in titles:
            uid = title_to_uid(portal, t)
            if uid:
                fresh[t] = uid
            else:
                unresolved.append((mid, t))
                print("  UNRESOLVED: {} matrix '{}' has no core SampleType "
                      "(left unmapped)".format(mid, t))

        current = prof.get("matrix_uid_map") or {}
        if current != fresh:
            prof["matrix_uid_map"] = fresh
            _persist_profile(portal, mid, prof)
            changed.append(mid)
            print("  backfilled {}  ({}/{} matrices resolved)".format(
                mid, len(fresh), len(titles)))
        else:
            unchanged.append(mid)
            print("  {} already current  ({} matrices)".format(mid, len(fresh)))

    # Re-export the JSON file the pipeline worker reads.
    if changed:
        try:
            export_profiles_to_file(portal)
            print("Exported updated profiles to file.")
        except Exception as exc:
            print("WARN: file export failed (ZODB changes still saved): {}"
                  .format(exc))

    try:
        import transaction
        if changed:
            transaction.commit()
            print("Transaction committed.")
        else:
            transaction.abort()
    except Exception as exc:
        print("ERROR committing transaction: {}".format(exc))
        sys.exit(1)

    print("\nDone. Backfilled: {}  Already current: {}  "
          "Unresolved matrices: {}".format(
              len(changed), len(unchanged), len(unresolved)))
    if unresolved:
        print("Review unresolved matrices (create the SampleType or fix the "
              "title), then re-run:")
        for mid, t in unresolved:
            print("  - {}: '{}'".format(mid, t))


run()
