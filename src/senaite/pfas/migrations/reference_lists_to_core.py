# -*- coding: utf-8 -*-
"""
Migration: reagent suppliers and storage places into core's lists
(browser/core_lists.py; the lab's merges).

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/reference_lists_to_core.py'

  1. Suppliers. The lab's merges: "Waters", "Waters Corporation"
     and core's own "Waters Coorporation" are one supplier, "Waters
     Corporation"; "Wellington Labs" is "Wellington Laboratories". Core's
     misspelt Supplier is retitled (it is the same company), every other
     supplier on a reagent becomes a core Supplier, and the reagents carry
     the merged name. "In-house" stays (what the lab makes itself).
  2. Storage. Every place on a reagent or prepared standard that core lacks
     becomes a core Storage Location; core's own stay.
  3. The titles are remembered, so a later rename in core follows onto the
     records.

Idempotent. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

SUPPLIER_MERGES = {
    u"Waters": u"Waters Corporation",
    u"Waters Coorporation": u"Waters Corporation",
    u"Wellington Labs": u"Wellington Laboratories",
}


def merged(name):
    name = (name or u"").strip()
    return SUPPLIER_MERGES.get(name, name)


def run(portal):
    from bika.lims import api
    from senaite.pfas.browser.core_lists import IN_HOUSE, remember_titles
    setup = api.get_senaite_setup()
    out = []

    suppliers = setup["suppliers"]
    by_title = dict((o.Title(), o) for o in suppliers.objectValues())
    for title, obj in list(by_title.items()):
        target = merged(title)
        if target != title and target not in by_title:
            obj.setTitle(target)
            obj.reindexObject()
            by_title[target] = by_title.pop(title)
            out.append(u"core Supplier %s retitled %s" % (title, target))
    reagents = portal.pfas_reagents.objectValues()
    for r in reagents:
        name = merged(r.supplier)
        if name != (r.supplier or u""):
            out.append(u"reagent %s: supplier %s -> %s" % (r.lot_number, r.supplier, name))
            r.supplier = name
            r.reindexObject()
        if name and name != IN_HOUSE and name not in by_title:
            by_title[name] = api.create(suppliers, "Supplier", title=name)
            out.append(u"core Supplier %s created" % name)

    places = setup["storagelocations"]
    have = set(o.Title() for o in places.objectValues())
    for folder in (portal.pfas_reagents, portal.pfas_prepared_standards):
        for obj in folder.objectValues():
            place = (getattr(obj, "storage_location", u"") or u"").strip()
            if place and place not in have:
                api.create(places, "StorageLocation", title=place)
                have.add(place)
                out.append(u"core Storage Location %s created" % place)

    remember_titles(portal)
    return out or [u"nothing to do"]


if __name__ == "__main__":
    import transaction
    from Testing.makerequest import makerequest
    from zope.component.hooks import setSite
    from AccessControl.SecurityManagement import newSecurityManager
    app_ = makerequest(app)                                 # noqa: F821 (bin/instance run)
    portal_ = app_.senaite
    setSite(portal_)
    portal_.setupCurrentSkin(app_.REQUEST)
    newSecurityManager(None, app_.acl_users.getUserById("admin").__of__(app_.acl_users))
    for line in run(portal_):
        print(line)
    transaction.commit()
    print("committed")
