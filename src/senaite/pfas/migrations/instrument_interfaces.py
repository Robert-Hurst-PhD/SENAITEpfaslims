# -*- coding: utf-8 -*-
"""
The PFAS data interfaces set on the LC-MS instruments in core ("register ours in core"): each Instrument of an Instrument Type
whose title names LC-MS gets the PFAS pipeline import and the PFAS injection
list export (browser/core_instrument.py). Interfaces already chosen stay;
ours are added.

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/instrument_interfaces.py'

Idempotent. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals


def run(portal):
    from bika.lims import api
    from senaite.pfas.browser.core_instrument import EXPORT_ID, IMPORT_ID
    for brain in api.search({"portal_type": "Instrument"}, "senaite_catalog_setup"):
        inst = api.get_object(brain)
        itype = inst.getInstrumentType()
        if itype is None or "lc-ms" not in (itype.Title() or u"").lower():
            continue
        imports = [x for x in (inst.getImportDataInterface() or []) if x]
        changed = []
        if IMPORT_ID not in imports:
            inst.setImportDataInterface(imports + [IMPORT_ID])
            changed.append(u"import")
        export = inst.getField("DataInterface").get(inst)
        if not export:
            inst.getField("DataInterface").set(inst, EXPORT_ID)
            changed.append(u"export")
        if changed:
            inst.reindexObject()
        print("%s: %s" % (inst.Title(), u", ".join(changed) or u"already set"))


if __name__ == "__main__":
    import transaction
    from Testing.makerequest import makerequest
    from zope.component.hooks import setSite
    app_ = makerequest(app)                                 # noqa: F821 (bin/instance run)
    portal_ = app_.senaite
    setSite(portal_)
    portal_.setupCurrentSkin(app_.REQUEST)
    from AccessControl.SecurityManagement import newSecurityManager
    newSecurityManager(None, app_.acl_users.getUserById("admin").__of__(app_.acl_users))
    run(portal_)
    transaction.commit()
    print("committed")
