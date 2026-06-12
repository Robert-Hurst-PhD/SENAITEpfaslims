# -*- coding: utf-8 -*-
"""Remove all test ARs, worksheets, and tracking entries for a fresh start."""
from __future__ import print_function
from Testing.makerequest import makerequest
import Zope2, transaction
app = makerequest(Zope2.app())
from AccessControl.SecurityManagement import newSecurityManager
from AccessControl.User import UnrestrictedUser
newSecurityManager(None, UnrestrictedUser('admin','',['Manager'],[]))
portal = app.senaite
try:
    from zope.site.hooks import setSite; setSite(portal)
except Exception: pass
from bika.lims import api as bapi
from senaite.pfas.tracking_store import _get_store

# Delete all worksheets
ws_folder = portal.worksheets
ws_ids = list(ws_folder.objectIds())
for ws_id in ws_ids:
    ws_folder.manage_delObjects([ws_id])
    print("Deleted WS:", ws_id)

# Delete all ARs in the demo client
try:
    client = portal.clients['pfas-demo-client']
    ar_ids = [oid for oid in client.objectIds() if not oid.startswith('contact')]
    for ar_id in ar_ids:
        client.manage_delObjects([ar_id])
        print("Deleted AR:", ar_id)
except Exception as e:
    print("Client cleanup:", e)

# Clear tracking store
fwd, rev = _get_store(portal)
keys = list(fwd.keys())
for k in keys:
    del fwd[k]
keys = list(rev.keys())
for k in keys:
    del rev[k]
print("Cleared tracking store")

transaction.commit()
print("Done.")
