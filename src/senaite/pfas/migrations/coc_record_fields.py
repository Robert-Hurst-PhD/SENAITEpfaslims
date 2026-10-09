# -*- coding: utf-8 -*-
"""Migration: the CoC logbook definition's own new fields -- field QC
pairing, custody seals, carrier, tracking, sampler signed -- as a DRAFT.


  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/coc_record_fields.py'

The newest DRAFT revision gains the fields (a draft is not in force, so it
may still change); with no draft, the active revision is copied into the
next revision as a draft first. The lab activates it on Logbooks >
Templates. Idempotent. Python 2.7.
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
    from senaite.pfas import custody_documents as cus
    from senaite.pfas.browser import prep_logbooks as pl

    revs = sorted(pl._list(portal, slug="coc"), key=lambda r: r.get("revision") or 0)
    drafts = [r for r in revs if r.get("status") == pl.STATUS_DRAFT]
    if drafts:
        rec = drafts[-1]
    else:
        active = [r for r in revs if r.get("status") == pl.STATUS_ACTIVE]
        if not active:
            print("no CoC revision to build on"); sys.exit(1)
        rec = dict(active[-1])
        rec.pop("uid", None)
        rec["revision"] = pl._next_revision(portal, "coc")
        rec["status"] = pl.STATUS_DRAFT
        rec["archived_date"] = ""
    schema, changed = cus.add_coc_fields(json.loads(rec.get("field_schema_json") or "[]"))
    if not changed:
        print("CoC revision %s already has the fields; nothing to do" % rec["revision"])
        return
    rec["field_schema_json"] = json.dumps(schema)
    pl._save(portal, rec)
    transaction.commit()
    print("CoC revision %s (DRAFT) now has: %s; activate it on Logbooks > Templates"
          % (rec["revision"], ", ".join(f["name"] for f in cus.COC_RECORD_FIELDS)))


run()
