# -*- coding: utf-8 -*-
"""Migration: a DRAFT revision of the Chain of Custody template with the
receipt thermometer.

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/add_receipt_thermometer_to_coc.py

"Any thermometer used for sample receipt should be recorded
within the CoC with the associated correction factor applied." The CoC is a
controlled, revisioned template: this copies its ACTIVE revision into the next
revision as a DRAFT, adds the receipt-thermometer field after Containers
Received and marks the containers' Temp column as corrected by it. The lab
reviews and activates the draft on Logbooks > Templates; nothing changes for
batches until then. Idempotent: no new draft when any revision already has
the field. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import sys

import transaction


def run():
    app = globals().get("app")
    from AccessControl.SecurityManagement import newSecurityManager
    from zope.component.hooks import setSite
    portal = [o for o in app.objectValues("Plone Site")][0]
    newSecurityManager(None, app.acl_users.getUserById("admin").__of__(app.acl_users))
    setSite(portal)
    from senaite.pfas import receipt_temperature as rt
    from senaite.pfas.browser import prep_logbooks as pl

    revs = pl._list(portal, slug="coc")
    for r in revs:
        schema = json.loads(r.get("field_schema_json") or "[]")
        if rt.RECEIPT_FIELD["name"] in [f.get("name") for f in schema]:
            print("CoC revision %s (%s) already has the receipt thermometer; nothing to do"
                  % (r["revision"], r["status"]))
            return
    active = [r for r in revs if r.get("status") == pl.STATUS_ACTIVE]
    if not active:
        print("no active CoC revision"); sys.exit(1)
    base = active[0]
    schema, changed = rt.add_receipt_thermometer(json.loads(base.get("field_schema_json") or "[]"))
    rec = dict(base)
    rec.pop("uid", None)
    rec["revision"] = pl._next_revision(portal, "coc")
    rec["status"] = pl.STATUS_DRAFT
    rec["archived_date"] = ""
    rec["field_schema_json"] = json.dumps(schema)
    uid = pl._save(portal, rec)
    transaction.commit()
    print("CoC revision %s created as DRAFT (%s) from active revision %s; activate it on "
          "Logbooks > Templates" % (rec["revision"], uid, base["revision"]))


run()
