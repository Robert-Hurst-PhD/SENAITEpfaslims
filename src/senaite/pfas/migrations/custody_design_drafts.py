# -*- coding: utf-8 -*-
"""Migration: DRAFT designs for the Chain of Custody and the controlled
document cover in Document Templates, from their starting layouts
(custody_documents.coc_starter / sop_starter).

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/custody_design_drafts.py'

Nothing is issued: issuing a design is the lab's controlled act. A kind
that already has a design is left alone. Idempotent. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

from datetime import datetime

import transaction

DRAFTS = (("coc", u"Chain of Custody"), ("sop_cover", u"Controlled document cover"))


def run():
    app = globals().get("app")
    from AccessControl.SecurityManagement import newSecurityManager
    from zope.component.hooks import setSite
    portal = [o for o in app.objectValues("Plone Site")][0]
    newSecurityManager(None, app.acl_users.getUserById("admin").__of__(app.acl_users))
    setSite(portal)
    from senaite.pfas import document_templates as dt
    store = dt.load(portal)
    when = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    made = []
    for kind, title in DRAFTS:
        single = dt.KINDS[kind]["single"]
        if single in store:
            print("%s: a design exists; left alone" % title)
            continue
        tid = dt.new(store, kind, title, "letter", u"admin", when)
        size = dt.size_of(kind, "letter")
        template = dt.KINDS[kind]["starter"](size["width"], size["height"])
        problems = dt.validate(kind, template)
        if problems:
            raise SystemExit("%s starter does not validate: %s" % (title, problems))
        dt.save_draft(store, tid, template, u"admin", when)
        made.append(title)
    if made:
        dt.save(portal, store)
        transaction.commit()
    print("drafts made: %s" % (", ".join(made) or "none"))


run()
