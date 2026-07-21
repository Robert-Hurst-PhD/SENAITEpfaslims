# -*- coding: utf-8 -*-
"""
Migration: replace synthetic QC SampleTypes with per-matrix AnalysisSpecs.

Run inside the SENAITE container:

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/cleanup_synthetic_qc_sampletypes.py

Earlier spec_sync created synthetic SampleTypes named after the QC profile
("FDA 32-PFAS in Food LFSM") and linked one flat AnalysisSpec per QC type to
them. Wrong on two counts: SENAITE matches specs to samples by their REAL
SampleType (a synthetic type never matches), and FDA tier-1 ranges are
matrix-dependent (tight matrices only). This step:

  1. deletes the old flat specs  ({mid}-{qc}-recovery)
  2. deletes the synthetic SampleTypes ({mid}-{qc}) — ONLY if no sample
     references them (checked; skipped + reported otherwise)
  3. seeds `tight_matrices` into the FDA profile if absent (configurable,
     golden rule #1; default Eggs / Meat / Fish per CLAUDE.md §3)
  4. re-saves every profile → regenerates per-matrix specs linked to the
     real SampleTypes

Idempotent. Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys

QC_TYPES = ("LCS", "LFSM", "LFB", "LFSMD")


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
        from zope.component.hooks import setSite
        app = globals().get("app") or portal.getPhysicalRoot()
        admin = app.acl_users.getUserById("admin")
        if admin is not None:
            newSecurityManager(None, admin.__of__(app.acl_users))
        setSite(portal)
    except Exception as exc:
        print("WARN: could not set security/site: {}".format(exc))

    from Products.CMFCore.utils import getToolByName
    from senaite.pfas.method_profile_store import (
        list_method_ids, get_profile, save_profile)

    catalog = getToolByName(portal, "senaite_catalog_setup")
    method_ids = list_method_ids(portal)
    spec_folder = portal.bika_setup.bika_analysisspecs
    st_folder = getattr(getattr(portal, "setup", None), "sampletypes", None)

    # 1. delete old flat specs
    removed_specs = []
    for mid in method_ids:
        for qc in QC_TYPES:
            old_id = "{0}-{1}-recovery".format(mid, qc).lower().replace("_", "-")
            if old_id in spec_folder:
                spec_folder._delObject(old_id)
                removed_specs.append(old_id)
                print("  removed old flat spec:", old_id)

    # 2. delete synthetic SampleTypes (only when unreferenced by samples)
    removed_sts, kept_sts = [], []
    if st_folder is not None:
        sample_cat = getToolByName(portal, "senaite_catalog", None)
        for mid in method_ids:
            for qc in QC_TYPES:
                st_id = "{0}-{1}".format(mid, qc).lower().replace("_", "-")
                if st_id not in st_folder:
                    continue
                st = st_folder[st_id]
                refs = []
                if sample_cat is not None:
                    try:
                        refs = sample_cat(getSampleTypeUID=st.UID())
                    except Exception:
                        refs = []
                if refs:
                    kept_sts.append((st_id, len(refs)))
                    print("  KEPT synthetic SampleType {} — {} sample(s) "
                          "reference it (resolve manually)".format(st_id, len(refs)))
                else:
                    st_folder._delObject(st_id)
                    removed_sts.append(st_id)
                    print("  removed synthetic SampleType:", st_id)

    # 3. seed tight_matrices into FDA profile if absent
    for mid in method_ids:
        prof = get_profile(portal, mid)
        if mid == "FDA_32PFAS" and not prof.get("tight_matrices"):
            prof["tight_matrices"] = ["Eggs", "Meat / Muscle", "Fish / Seafood"]
            print("  seeded FDA_32PFAS tight_matrices:", prof["tight_matrices"])
        # 4. re-save → regenerates per-matrix specs via forward sync
        save_profile(portal, mid, prof)
        print("  re-synced specs for", mid)

    n_specs = len(catalog(portal_type="AnalysisSpec"))
    print("\nAnalysisSpec count after regen:", n_specs)

    try:
        import transaction
        transaction.commit()
        print("Transaction committed.")
    except Exception as exc:
        print("ERROR committing transaction: {}".format(exc))
        sys.exit(1)

    print("Done. Removed specs: {}  Removed sample types: {}  Kept (referenced): {}"
          .format(len(removed_specs), len(removed_sts), len(kept_sts)))


run()
