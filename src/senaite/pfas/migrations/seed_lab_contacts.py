# -*- coding: utf-8 -*-
"""
Migration: seed placeholder Lab Contacts (the laboratory staff pool).

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/seed_lab_contacts.py

Creates clearly-flagged PLACEHOLDER contacts so the staff pool drives analyst
selectors and document sign-offs immediately; the lab edits each contact with
the real name, initials, and uploads their Signature image (core LabContact
field) on the contact's edit form. No signature images are fabricated (§8).

Idempotent (skips existing surnames). Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys

SEED = [
    # (Firstname, Surname, JobTitle, initials)
    ("PLACEHOLDER", "Lab Manager",   "Laboratory Manager / QAO", "LM"),
    ("PLACEHOLDER", "Analyst One",   "Analyst (Data Review)",    "A1"),
    ("PLACEHOLDER", "Analyst Two",   "Analyst",                  "A2"),
    ("PLACEHOLDER", "Bench Chemist", "Bench Chemist",            "BC"),
]


def run():
    app = globals().get("app")
    portals = [o for o in app.objectValues("Plone Site")]
    if not portals:
        print("ERROR: no Plone site"); sys.exit(1)
    portal = portals[0]

    from AccessControl.SecurityManagement import newSecurityManager
    from zope.component.hooks import setSite
    admin = app.acl_users.getUserById("admin")
    newSecurityManager(None, admin.__of__(app.acl_users))
    setSite(portal)

    folder = portal["bika_setup"]["bika_labcontacts"]
    existing = set()
    for c in folder.objectValues():
        try:
            existing.add(c.getSurname())
        except Exception:
            pass

    created = 0
    for first, last, job, initials in SEED:
        if last in existing:
            print("  exists:", last)
            continue
        from bika.lims import api
        obj = api.create(folder, "LabContact",
                         Firstname=first, Surname=last, JobTitle=job)
        try:
            field = obj.getField("pfas_initials")
            if field is not None:
                field.set(obj, initials)
        except Exception as exc:
            print("  WARN initials for {}: {}".format(last, exc))
        created += 1
        print("  created LabContact: {} {} ({}) initials={}".format(
            first, last, job, initials))

    import transaction
    transaction.commit()
    print("\nDone. Created: {} (edit names/initials and upload each person's "
          "Signature image on the contact form)".format(created))


run()
