# -*- coding: utf-8 -*-
"""
Create 5 test samples (one per tracker stage) for demo/review.

Run via:  docker compose exec senaite bin/instance run /addon/create_test_samples.py
"""
from __future__ import print_function, absolute_import

import datetime
import json
import os
import transaction

from persistent.list import PersistentList
from persistent.mapping import PersistentMapping
from zope.annotation.interfaces import IAnnotations

_BACKREFS_KEY = 'bika.lims.browser.fields.uidreferencefield.backreferences'

from Testing.makerequest import makerequest
import Zope2
app = makerequest(Zope2.app())

from AccessControl.SecurityManagement import newSecurityManager
from AccessControl.User import UnrestrictedUser
newSecurityManager(None, UnrestrictedUser('admin', '', ['Manager'], []))

portal = app.senaite

try:
    from zope.site.hooks import setSite
    setSite(portal)
except Exception:
    pass

from DateTime import DateTime
from Products.CMFCore.utils import getToolByName

wf_tool = getToolByName(portal, 'portal_workflow')
scat    = getToolByName(portal, 'senaite_catalog_setup')

print("=" * 60)
print("Creating test samples — one per stage")
print("=" * 60)

# ── Reference data ─────────────────────────────────────────────────────────────
st_brains = scat.unrestrictedSearchResults(portal_type='SampleType')
sample_types = {b.Title: b.getObject() for b in st_brains}

m_brains = scat.unrestrictedSearchResults(portal_type='Method')
methods = {b.Title: b.getObject() for b in m_brains}

svc_brains = scat.unrestrictedSearchResults(portal_type='AnalysisService')
services = [b.getObject() for b in svc_brains[:3]]

st_water  = sample_types.get('Drinking Water') or list(sample_types.values())[0]
st_ground = sample_types.get('Groundwater')    or list(sample_types.values())[1]
st_soil   = sample_types.get('Soil')           or list(sample_types.values())[2]
st_sw     = sample_types.get('Surface Water')  or list(sample_types.values())[0]
m_537     = methods.get('EPA 537.1 PFAS in Drinking Water')              or list(methods.values())[0]
m_fda     = methods.get('USDA/FDA 32-PFAS in Food v10')                  or list(methods.values())[0]
m_1633    = methods.get('EPA 1633A PFAS (aqueous/solid/biosolid/tissue)') or list(methods.values())[0]

print("  SampleTypes:", len(sample_types), "  Methods:", len(methods), "  Services:", len(services))

# ── Client + Contact ──────────────────────────────────────────────────────────
def get_or_create_client():
    existing = list(portal.clients.objectValues('Client'))
    if existing:
        c = existing[0]
        print("  Client:", c.Title())
        return c
    portal.clients.invokeFactory('Client', id='pfas-demo-client')
    c = portal.clients['pfas-demo-client']
    c.schema['Name'].set(c, 'PFAS Demo Client')
    c.schema['ClientID'].set(c, 'DEMO001')
    c.reindexObject()
    transaction.savepoint(optimistic=True)
    print("  Created client:", c.Title())
    return c

def get_or_create_contact(client):
    existing = list(client.objectValues('Contact'))
    if existing:
        return existing[0]
    client.invokeFactory('Contact', id='contact-1')
    ct = client['contact-1']
    ct.schema['Firstname'].set(ct, 'Demo')
    ct.schema['Surname'].set(ct, 'Client')
    ct.reindexObject()
    transaction.savepoint(optimistic=True)
    return ct

print("\n[0] Client/contact ...")
client  = get_or_create_client()
contact = get_or_create_contact(client)
print("  Contact:", contact.getFullname() if hasattr(contact, 'getFullname') else contact.getId())

# ── Helpers ────────────────────────────────────────────────────────────────────
from bika.lims.utils.analysisrequest import create_analysisrequest

def make_ar(sample_type, method):
    values = {
        'Client':     client,
        'Contact':    contact,
        'SampleType': sample_type,
        'DateSampled': DateTime(),
        'Analyses':   [s.UID() for s in services],
        'Method':     method,
    }
    ar = create_analysisrequest(client, app.REQUEST, values)
    transaction.savepoint(optimistic=True)
    return ar

def set_wf_state(obj, wf_id, state_id, action='receive'):
    """Directly set workflow state without firing guards (instance-run safe)."""
    wf_tool.setStatusOf(wf_id, obj, {
        'review_state': state_id,
        'action':       action,
        'actor':        'admin',
        'time':         DateTime(),
        'comments':     'Test data',
    })
    obj.reindexObject(idxs=['review_state'])
    transaction.savepoint(optimistic=True)

def make_worksheet(ar):
    ws_folder = portal.worksheets
    existing_ids = set(ws_folder.objectIds())
    n = len(existing_ids) + 1
    while 'WS-{:04d}'.format(n) in existing_ids:
        n += 1
    ws_id = 'WS-{:04d}'.format(n)
    ws_folder.invokeFactory('Worksheet', id=ws_id)
    ws = ws_folder[ws_id]
    # Write the back-reference directly into each analysis's annotation storage.
    # get_backreferences(analysis, 'WorksheetAnalysis') reads from IAnnotations
    # on the unwrapped object — this is the bika.lims UIDReferenceField system,
    # not the AT reference_catalog.
    ws_uid = ws.UID()
    linked = 0
    for ab in ar.getAnalyses():
        try:
            a = ab.getObject()
            annotations = IAnnotations(a.aq_base)
            if annotations.get(_BACKREFS_KEY) is None:
                annotations[_BACKREFS_KEY] = PersistentMapping()
            storage = annotations[_BACKREFS_KEY]
            if 'WorksheetAnalysis' not in storage:
                storage['WorksheetAnalysis'] = PersistentList()
            if ws_uid not in storage['WorksheetAnalysis']:
                storage['WorksheetAnalysis'].append(ws_uid)
            a.reindexObject()
            linked += 1
        except Exception as exc:
            print("    (annotation write failed: {})".format(exc))
    ws.reindexObject()
    transaction.savepoint(optimistic=True)
    print("    Linked {} analyses to {}".format(linked, ws_id))
    return ws

def write_log(ws_id, done=False, analyst='Demo Analyst'):
    log_dir = '/data/extraction_logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    now = datetime.datetime.utcnow()
    data = {
        'batch_id': ws_id,
        'analyst':  analyst,
        'started':  (now - datetime.timedelta(hours=3)).isoformat(),
    }
    if done:
        data['completed'] = (now - datetime.timedelta(hours=1)).isoformat()
    with open(os.path.join(log_dir, '{}_extraction.json'.format(ws_id)), 'w') as f:
        json.dump(data, f)

def assign_tracking(ar):
    from senaite.pfas.tracking_store import get_or_assign_tracking
    tn = get_or_assign_tracking(portal, ar)
    transaction.commit()
    return tn

AR_WF  = 'senaite_sample_workflow'
WS_WF  = 'senaite_worksheet_workflow'
ANA_WF = 'senaite_analysis_workflow'

results = []

# ── Stage 1: Received ──────────────────────────────────────────────────────────
print("\n[1] Stage 1 — Received (Drinking Water / EPA 537.1) ...")
ar1 = make_ar(st_water, m_537)
print("    AR:", ar1.getId())
set_wf_state(ar1, AR_WF, 'sample_received', 'receive')
tn1 = assign_tracking(ar1)
print("    Tracking:", tn1)
results.append(('Stage 1 — Received', tn1))

# ── Stage 2: Extraction ────────────────────────────────────────────────────────
print("\n[2] Stage 2 — Extraction (Groundwater / EPA 537.1) ...")
ar2 = make_ar(st_ground, m_537)
print("    AR:", ar2.getId())
set_wf_state(ar2, AR_WF, 'sample_received', 'receive')
ws2 = make_worksheet(ar2)
print("    Worksheet:", ws2.getId())
write_log(ws2.getId(), done=False, analyst='J. Smith')
print("    Extraction log: in progress")
tn2 = assign_tracking(ar2)
print("    Tracking:", tn2)
results.append(('Stage 2 — Extraction', tn2))

# ── Stage 3: On Instrument ─────────────────────────────────────────────────────
print("\n[3] Stage 3 — On Instrument (Soil / FDA 32-PFAS) ...")
ar3 = make_ar(st_soil, m_fda)
print("    AR:", ar3.getId())
set_wf_state(ar3, AR_WF, 'sample_received', 'receive')
ws3 = make_worksheet(ar3)
print("    Worksheet:", ws3.getId())
write_log(ws3.getId(), done=True, analyst='M. Johnson')
print("    Extraction log: completed")
tn3 = assign_tracking(ar3)
print("    Tracking:", tn3)
results.append(('Stage 3 — On Instrument', tn3))

# ── Stage 4: QC Review ────────────────────────────────────────────────────────
print("\n[4] Stage 4 — QC Review (Surface Water / EPA 1633A) ...")
ar4 = make_ar(st_sw, m_1633)
print("    AR:", ar4.getId())
set_wf_state(ar4, AR_WF, 'sample_received', 'receive')
ws4 = make_worksheet(ar4)
print("    Worksheet:", ws4.getId())
# Put the worksheet into to_be_verified
set_wf_state(ws4, WS_WF, 'to_be_verified', 'submit')
print("    WS state: to_be_verified")
tn4 = assign_tracking(ar4)
print("    Tracking:", tn4)
results.append(('Stage 4 — QC Review', tn4))

# ── Stage 5: Report Published ──────────────────────────────────────────────────
print("\n[5] Stage 5 — Report Published (Drinking Water / EPA 537.1) ...")
ar5 = make_ar(st_water, m_537)
print("    AR:", ar5.getId())
set_wf_state(ar5, AR_WF, 'sample_received', 'receive')
ws5 = make_worksheet(ar5)
print("    Worksheet:", ws5.getId())
set_wf_state(ws5, WS_WF, 'verified', 'verify')
print("    WS state: verified")
set_wf_state(ar5, AR_WF, 'published', 'publish')
print("    AR state: published")
tn5 = assign_tracking(ar5)
print("    Tracking:", tn5)
results.append(('Stage 5 — Report Published', tn5))

# ── Summary ────────────────────────────────────────────────────────────────────
transaction.commit()
base = "http://localhost:8080/senaite"
print("\n" + "=" * 60)
print("Tracker URLs (no login needed):")
print("=" * 60)
for label, tn in results:
    print("  {:<30s}  {}/@@pfas-track?t={}".format(label, base, tn))
print("=" * 60)
