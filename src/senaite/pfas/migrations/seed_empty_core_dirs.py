# -*- coding: utf-8 -*-
"""
Migration: seed empty core setup directories from siloed addon data (audit
catalogue task B).

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/seed_empty_core_dirs.py

Un-silos data that existed only in setupdata CSVs / nowhere:
  * setup/samplepoints    <- setupdata/sample_points.csv (Title+Description
    only; the CSV's PLACEHOLDER client names are NOT fabricated into links —
    noted in each description for lab verification, per CLAUDE.md §8)
  * setup/containertypes  <- setupdata/containers.csv (capacity/material/notes
    folded into the description; editable in core UI afterwards)
  * setup/departments     <- one "PFAS Chemistry" department (method wizard
    step 2 requires a Department; the folder was empty so the selector had
    nothing to offer)

Idempotent (skips titles that already exist). Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import csv
import os
import sys

CSV_DIR = "/addon/src/senaite/pfas/setupdata"


def _get_portal():
    app = globals().get("app")
    portals = [o for o in app.objectValues("Plone Site")]
    if not portals:
        print("ERROR: no Plone site"); sys.exit(1)
    return portals[0]


def run():
    portal = _get_portal()
    from AccessControl.SecurityManagement import newSecurityManager
    from zope.component.hooks import setSite
    app = globals().get("app")
    admin = app.acl_users.getUserById("admin")
    newSecurityManager(None, admin.__of__(app.acl_users))
    setSite(portal)

    from bika.lims import api

    created = []

    def seed(folder, portal_type, title, description=""):
        existing = set(o.Title() for o in folder.objectValues())
        if title in existing:
            print("  exists: %s %r" % (portal_type, title))
            return
        obj = api.create(folder, portal_type, title=title,
                         description=description)
        created.append((portal_type, title))
        print("  created %s: %r" % (portal_type, title))
        return obj

    # 1. Sample points
    sp_folder = portal["setup"]["samplepoints"]
    path = os.path.join(CSV_DIR, "sample_points.csv")
    if os.path.exists(path):
        with open(path) as fh:
            for row in csv.DictReader(fh):
                desc = row.get("Description", "")
                client = row.get("Client", "")
                if client:
                    desc = (desc + " — client: " + client +
                            (" (VERIFY: placeholder)" if "PLACEHOLDER" in client else ""))
                seed(sp_folder, "SamplePoint", row["Title"], desc)

    # 2. Container types
    ct_folder = portal["setup"]["containertypes"]
    path = os.path.join(CSV_DIR, "containers.csv")
    if os.path.exists(path):
        with open(path) as fh:
            for row in csv.DictReader(fh):
                desc = "; ".join(x for x in (
                    row.get("Capacity", ""), row.get("Material", ""),
                    "methods: " + row.get("Methods", "") if row.get("Methods") else "",
                    row.get("Notes", "")) if x)
                seed(ct_folder, "ContainerType", row["Title"], desc)

    # 3. Department (method wizard step 2 dependency)
    dp_folder = portal["setup"]["departments"]
    seed(dp_folder, "Department", "PFAS Chemistry",
         "PFAS analysis department (FDA 32-PFAS, EPA 537.1, EPA 1633A)")

    import transaction
    transaction.commit()
    print("\nDone. Created: %d  (committed)" % len(created))


run()
