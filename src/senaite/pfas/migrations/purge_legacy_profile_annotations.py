# -*- coding: utf-8 -*-
"""
Migration: remove the legacy annotation copy of the method profiles.

Run inside the SENAITE container:

  docker exec <container> bin/instance -O senaite run \
    /addon/src/senaite/pfas/migrations/purge_legacy_profile_annotations.py

Method profiles live in Dexterity objects under /senaite/pfas_method_profiles.
The annotation mapping at `senaite.pfas.method_profiles` predates that store and
has not been kept in step: on 2026-08-04 it held salt_adjustment_factors=0 for
FDA_32PFAS while the live profile held 2, including the CoA lot behind each
factor.

That divergence was not inert. `method_profile_store` fell back to the
annotation copy whenever the Dexterity folder was absent — after an upgrade, a
restore, or a rename — and would then have served a profile with no salt
correction and stale acceptance limits, silently. It also made
`migrate_profile_structure` a no-op for two months: it read the annotation
store, cleaned a stale copy, and printed "saved".

The fallback now raises StaleProfileStore rather than serving stale config. This
script removes the copy that would trigger it, so a site with a healthy
Dexterity folder has exactly one profile store.

SAFETY: refuses unless the Dexterity folder exists and holds every method id
present in the annotation store. It will never remove the only copy.

Safe to run more than once (idempotent). Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import sys


def _get_portal():
    try:
        app_obj = globals().get("app")
        if app_obj is None:
            import Zope2
            from Testing.makerequest import makerequest
            app_obj = makerequest(Zope2.app())
        portals = [o for o in app_obj.objectValues("Plone Site")]
        if not portals:
            raise RuntimeError("No Plone site found in app")
        return portals[0]
    except Exception as exc:
        print("ERROR: could not obtain portal: {0}".format(exc))
        sys.exit(1)


def run():
    from senaite.pfas.method_profile_store import (
        PFAS_METHOD_PROFILES_KEY, _get_profiles_folder,
    )
    from zope.annotation.interfaces import IAnnotations

    portal = _get_portal()
    annotations = IAnnotations(portal)
    legacy = annotations.get(PFAS_METHOD_PROFILES_KEY)

    if not legacy:
        print("No legacy annotation store — nothing to purge.")
        return

    folder = _get_profiles_folder(portal)
    if folder is None:
        print("REFUSING: pfas_method_profiles folder is absent, so the "
              "annotation store is currently the ONLY copy of your profiles. "
              "Restore the folder first.")
        sys.exit(1)

    dexterity_ids = set(folder.objectIds())
    legacy_ids = set(legacy.keys())
    missing = sorted(legacy_ids - dexterity_ids)
    if missing:
        print("REFUSING: these method(s) exist only in the annotation store "
              "and would be lost: {0}".format(", ".join(missing)))
        sys.exit(1)

    # Report the divergence being discarded, so it is visible in the log rather
    # than silently dropped — if the stale copy held something the live one does
    # not, that is worth seeing before it goes.
    for method_id in sorted(legacy_ids):
        try:
            stale = json.loads(legacy[method_id])
        except (ValueError, TypeError):
            print("  {0}: unparseable legacy entry".format(method_id))
            continue
        raw = getattr(folder[method_id], "profile_json", None) or "{}"
        try:
            live = json.loads(raw)
        except (ValueError, TypeError):
            live = {}
        drift = sorted(k for k in set(stale) | set(live)
                       if stale.get(k) != live.get(k))
        print("  {0}: discarding legacy copy ({1} key(s) differed{2})".format(
            method_id, len(drift),
            ": " + ", ".join(drift[:6]) if drift else ""))

    del annotations[PFAS_METHOD_PROFILES_KEY]
    print("Removed the legacy annotation store; "
          "pfas_method_profiles is now the only profile store.")

    try:
        import transaction
        transaction.commit()
        print("Transaction committed.")
    except Exception as exc:
        print("ERROR committing transaction: {0}".format(exc))
        sys.exit(1)


if __name__ == "__main__" or "app" in globals():
    run()
