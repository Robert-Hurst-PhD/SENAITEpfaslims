# -*- coding: utf-8 -*-
"""
Migration: purge flat instrument-QC keys from stored method profiles.

Run inside the SENAITE container:

  docker exec <container> bin/instance run \
    /home/senaite/senaitelims/src/senaite/pfas/migrations/migrate_profile_structure.py

The script reads every profile stored in ZODB annotations, removes the old
flat keys that have been superseded by the nested instrument_verification /
qc_acceptance / extraction_corrections structure, back-fills any new keys that
are absent, and writes the cleaned dict back.

Old keys removed:
  calibration, ccv, is, confirmation, duplicate,
  recovery_tiers, salt_adjustment_factors

New keys back-filled from DEFAULT_PROFILES when absent:
  instrument_verification, qc_acceptance, associated_qc_types,
  extraction_corrections

Safe to run more than once (idempotent).
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import json
import sys

OLD_KEYS = frozenset([
    "calibration",
    "ccv",
    "is",
    "confirmation",
    "duplicate",
    "recovery_tiers",
    "salt_adjustment_factors",
])

NEW_KEYS = [
    "instrument_verification",
    "qc_acceptance",
    "associated_qc_types",
    "extraction_corrections",
]


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


def run():
    from senaite.pfas.method_profile_store import (
        PFAS_METHOD_PROFILES_KEY,
        DEFAULT_PROFILES,
        get_profile_store,
        export_profiles_to_file,
    )
    from zope.annotation.interfaces import IAnnotations

    portal = _get_portal()
    store = get_profile_store(portal)

    if not store:
        print("No profiles stored in ZODB — nothing to migrate.")
        return

    changed = []
    skipped = []

    for method_id in list(store.keys()):
        raw = store.get(method_id)
        try:
            profile = json.loads(raw)
        except (ValueError, TypeError) as exc:
            print("WARN: could not parse profile for {}: {}".format(method_id, exc))
            skipped.append(method_id)
            continue

        dflt = DEFAULT_PROFILES.get(method_id, {})
        dirty = False

        # 1. Remove old flat keys
        for key in list(profile.keys()):
            if key in OLD_KEYS:
                del profile[key]
                dirty = True
                print("  removed '{}' from {}".format(key, method_id))

        # 2. Back-fill new keys from DEFAULT_PROFILES when absent
        for key in NEW_KEYS:
            if key not in profile and key in dflt:
                profile[key] = copy.deepcopy(dflt[key])
                dirty = True
                print("  added '{}' to {}".format(key, method_id))

        if dirty:
            store[method_id] = json.dumps(profile)
            changed.append(method_id)
            print("  saved {}".format(method_id))
        else:
            skipped.append(method_id)
            print("  {} already clean".format(method_id))

    # 3. Re-export the JSON file for the pipeline worker
    if changed:
        try:
            export_profiles_to_file(portal)
            print("Exported updated profiles to file.")
        except Exception as exc:
            print("WARN: file export failed (ZODB changes still saved): {}".format(exc))

    # 4. Commit the ZODB transaction
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

    print("\nDone. Changed: {}  Already clean: {}".format(
        len(changed), len(skipped)))


run()
