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

Old keys removed (values carried into qc_acceptance first, never dropped):
  calibration, ccv, is, confirmation, duplicate, recovery_tiers

NOT removed: salt_adjustment_factors. It was listed as obsolete and is not --
it is the authoritative salt-correction key and carries the CoA lot behind each
factor.

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

# Flat keys the nested structure superseded. A key is listed here ONLY if its
# value is genuinely obsolete or is carried across by CARRY_FORWARD below.
#
# `salt_adjustment_factors` was listed here and is NOT obsolete -- it is the
# authoritative salt-correction key, applied by
# pipeline.apply_extract_corrections() since 2026-08-03, and it carries the CoA
# lot each factor came from. Running this migration would have deleted a
# lab's salt factors together with their reference-standard traceability, and
# the UnconfiguredCriterion message points users straight at this script.
OLD_KEYS = frozenset([
    "calibration",
    "ccv",
    "is",
    "confirmation",
    "duplicate",
    "recovery_tiers",
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


def carry_legacy_values(profile):
    """Move values off the retired flat keys into the enforced structure.

    Extracted and named because this is the step that decides whether a lab
    keeps its configured limits: §8 requires migrating configured data without
    loss, not merely defining the new schema. Returns a list of human-readable
    descriptions of what moved (empty when nothing did). Idempotent -- an
    existing value in the target is never overwritten.
    """
    moved = []
    qca = profile.setdefault("qc_acceptance", {})

    legacy_dup = (profile.get("duplicate") or {}).get("rpd_max")
    if legacy_dup is not None:
        entry = qca.setdefault("Dup", {"enabled": True})
        tiers = entry.setdefault("tiers", [])
        if not tiers:
            tiers.append({"name": "default", "analyte_group": "all",
                          "matrix_scope": "all"})
        if tiers[0].get("rpd_max") is None:
            tiers[0]["rpd_max"] = legacy_dup
            moved.append("duplicate.rpd_max={0} -> qc_acceptance.Dup".format(
                legacy_dup))

    legacy_tiers = profile.get("recovery_tiers")
    if legacy_tiers:
        entry = qca.setdefault("LFSM", {"enabled": True})
        if not entry.get("tiers"):
            entry["tiers"] = copy.deepcopy(legacy_tiers)
            moved.append("{0} recovery_tiers -> qc_acceptance.LFSM".format(
                len(legacy_tiers)))
    return moved


def run():
    # get_profile/save_profile, NOT get_profile_store. The annotation mapping
    # is a legacy store whose own docstring says "use get_profile() /
    # save_profile() for all live read/write" -- and this migration went on
    # reading it. Live profiles are Dexterity objects under
    # /senaite/pfas_method_profiles, so the migration cleaned a stale copy,
    # reported success, and left every real profile untouched. The
    # UnconfiguredCriterion message directs users here to fix exactly the
    # profiles it was not reaching.
    from senaite.pfas.method_profile_store import (
        DEFAULT_PROFILES,
        list_method_ids,
        get_profile,
        save_profile,
        export_profiles_to_file,
    )

    portal = _get_portal()
    method_ids = list_method_ids(portal)

    if not method_ids:
        print("No profiles stored — nothing to migrate.")
        return

    changed = []
    skipped = []

    for method_id in method_ids:
        profile = get_profile(portal, method_id)
        if not isinstance(profile, dict) or not profile:
            print("WARN: no readable profile for {}".format(method_id))
            skipped.append(method_id)
            continue

        dflt = DEFAULT_PROFILES.get(method_id, {})
        dirty = False

        # 1. Carry configured values into the enforced structure BEFORE the
        #    flat key is dropped.
        for note in carry_legacy_values(profile):
            dirty = True
            print("  carried {0} for {1}".format(note, method_id))

        # 2. Remove the flat keys now that their values are safe
        for key in list(profile.keys()):
            if key in OLD_KEYS:
                del profile[key]
                dirty = True
                print("  removed '{}' from {}".format(key, method_id))

        # 3. Back-fill new keys from DEFAULT_PROFILES when absent
        for key in NEW_KEYS:
            if key not in profile and key in dflt:
                profile[key] = copy.deepcopy(dflt[key])
                dirty = True
                print("  added '{}' to {}".format(key, method_id))

        if dirty:
            # save_profile writes the live Dexterity object and re-exports the
            # worker's JSON, so the two cannot drift.
            save_profile(portal, method_id, profile)
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


# `bin/instance run` execs this file and supplies `app` in globals, which is
# how every migration here is invoked. Guarding the call keeps that working
# while letting carry_legacy_values() -- the step that decides whether a lab
# keeps its configured limits -- be imported and tested directly.
if __name__ == "__main__" or "app" in globals():
    run()
