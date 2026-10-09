# -*- coding: utf-8 -*-
"""Check: Chain of Custody logbook entries filled on worksheets or batches
before the CoC became a record per CoC number. Lists each one; nothing is moved -- which shipment and samples an old
entry belonged to is the lab's to say, and the entry stays readable where it
is (Data Review still shows it).

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/coc_logbook_check.py'

Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals


def run():
    app = globals().get("app")
    from AccessControl.SecurityManagement import newSecurityManager
    from zope.annotation.interfaces import IAnnotations
    from zope.component.hooks import setSite
    portal = [o for o in app.objectValues("Plone Site")][0]
    newSecurityManager(None, app.acl_users.getUserById("admin").__of__(app.acl_users))
    setSite(portal)
    from bika.lims import api
    found = []
    for pt, cat in (("Worksheet", "senaite_catalog_worksheet"), ("Batch", "senaite_catalog")):
        for b in api.search({"portal_type": pt}, cat):
            o = api.get_object(b)
            if IAnnotations(o).get("senaite.pfas.logbook.coc"):
                found.append("%s %s" % (pt, o.getId()))
    print("CoC logbook entries on worksheets/batches: %s" % (", ".join(found) or "none"))


run()
