# -*- coding: utf-8 -*-
"""
E2E acceptance test — Stage 1 scaffold.

Creates the client, contact, samples, batch and worksheet that the real
instrument run `Test Sample.csv` (FDA 32-PFAS, Animal Feed) belongs to.

Everything created is prefixed KCP / kcp- so it can be found and removed.

Run:  bin/instance -O senaite run /addon/e2e_kcp_scaffold.py
"""
from __future__ import absolute_import, print_function

import sys
import transaction

from persistent.list import PersistentList
from persistent.mapping import PersistentMapping
from zope.annotation.interfaces import IAnnotations

_BACKREFS_KEY = 'bika.lims.browser.fields.uidreferencefield.backreferences'

CLIENT_ID = 'kcp-feed-forage'
CLIENT_NAME = 'KCP Feed & Forage'
BATCH_ID = 'kcp-b-001'
BATCH_TITLE = 'KCP Silage Run 2025-10-20'
MATRIX = 'Animal Feed'
METHOD_TITLE = 'USDA/FDA 32-PFAS in Food v10'

# ClientSampleID is set to the exact instrument Injection Name so that the
# result-push linkage can be measured rather than guessed at (finding F5).
SAMPLES = [
    ('KCP Silage "Egg-1" Sample',             'Sample'),
    ('KCP Silage "Egg-2" Sample',             'Sample'),
    ('KCP Silage "Egg-3" Sample',             'Sample'),
    ('KCP Silage "Egg-4" Sample',             'Sample'),
    ('KCP Silage "Egg-3"; Dil. 1:10',         'Dilution'),
    ('KCP Silage "Egg-4"; Dil. 1:10',         'Dilution'),
    ('KCP Water MB 2025-10-20-01',            'MB'),
    ('KCP Silage "Egg-2" LFSM Mid',           'LFSM'),
    ('KCP Silage "Egg-2" LFSM Mid Duplicate', 'LFSMD'),
]


def run(app):
    from zope.site.hooks import setSite, setHooks
    setHooks()
    portal = app.senaite
    setSite(portal)

    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.User import UnrestrictedUser
    newSecurityManager(None, UnrestrictedUser('admin', '', ['Manager'], []))

    from DateTime import DateTime
    from Products.CMFCore.utils import getToolByName
    from bika.lims.utils.analysisrequest import create_analysisrequest
    from senaite.pfas.method_profile_store import get_profile

    scat = getToolByName(portal, 'senaite_catalog_setup')
    wf_tool = getToolByName(portal, 'portal_workflow')

    # ── the reportable panel for FDA_32PFAS x Animal Feed ────────────────
    profile = get_profile(portal, 'FDA_32PFAS') or {}
    inclusion = profile.get('analyte_matrix_inclusion') or {}
    panel_keywords = sorted(
        k for k, v in inclusion.items()
        if isinstance(v, dict) and v.get(MATRIX))
    print('Panel for FDA_32PFAS x %s: %d analytes' % (MATRIX, len(panel_keywords)))

    services = {}
    for brain in scat.unrestrictedSearchResults(portal_type='AnalysisService'):
        obj = brain.getObject()
        services[obj.getKeyword()] = obj
    panel = [services[k] for k in panel_keywords if k in services]
    missing = [k for k in panel_keywords if k not in services]
    if missing:
        print('  !! no AnalysisService for: %s' % missing)
    print('  resolved %d services' % len(panel))

    sampletypes = {}
    for brain in scat.unrestrictedSearchResults(portal_type='SampleType'):
        obj = brain.getObject()
        sampletypes[obj.Title()] = obj
    st = sampletypes.get(MATRIX)
    if st is None:
        print('ERROR: no SampleType %r' % MATRIX)
        sys.exit(1)

    method = None
    for brain in scat.unrestrictedSearchResults(portal_type='Method'):
        obj = brain.getObject()
        if obj.Title() == METHOD_TITLE:
            method = obj
            break

    # ── client + contact ─────────────────────────────────────────────────
    if CLIENT_ID not in portal.clients:
        portal.clients.invokeFactory('Client', id=CLIENT_ID)
        client = portal.clients[CLIENT_ID]
        client.schema['Name'].set(client, CLIENT_NAME)
        client.schema['ClientID'].set(client, 'KCP001')
        client.reindexObject()
        transaction.savepoint(optimistic=True)
        print('Created client %s' % CLIENT_NAME)
    client = portal.clients[CLIENT_ID]

    if 'contact-1' not in client:
        client.invokeFactory('Contact', id='contact-1')
        ct = client['contact-1']
        ct.schema['Firstname'].set(ct, 'Kirsten')
        ct.schema['Surname'].set(ct, 'Palmer')
        ct.reindexObject()
        transaction.savepoint(optimistic=True)
    contact = client['contact-1']

    # ── batch ────────────────────────────────────────────────────────────
    if BATCH_ID not in portal.batches:
        portal.batches.invokeFactory('Batch', BATCH_ID, title=BATCH_TITLE)
        batch = portal.batches[BATCH_ID]
        batch.setTitle(BATCH_TITLE)
        try:
            batch.setClient(client)
        except Exception as exc:
            print('  (setClient failed: %s)' % exc)
        batch.reindexObject()
        transaction.savepoint(optimistic=True)
        print('Created batch %s' % BATCH_ID)
    batch = portal.batches[BATCH_ID]

    # ── samples ──────────────────────────────────────────────────────────
    uids = [s.UID() for s in panel]
    existing = {}
    for ar in client.objectValues('AnalysisRequest'):
        try:
            existing[ar.getClientSampleID()] = ar
        except Exception:
            pass

    ars = []
    for csid, role in SAMPLES:
        if csid in existing:
            ars.append(existing[csid])
            print('  reuse  %-42s %s' % (csid[:42], existing[csid].getId()))
            continue
        values = {
            'Client': client,
            'Contact': contact,
            'SampleType': st,
            'DateSampled': DateTime('2025/10/20'),
            'ClientSampleID': csid,
            'Batch': batch,
            'Analyses': uids,
        }
        if method is not None:
            values['Method'] = method
        ar = create_analysisrequest(client, app.REQUEST, values)
        transaction.savepoint(optimistic=True)
        ars.append(ar)
        print('  create %-42s %s  (%s)' % (csid[:42], ar.getId(), role))

    # receive them all
    for ar in ars:
        wf_tool.setStatusOf('senaite_sample_workflow', ar, {
            'review_state': 'sample_received', 'action': 'receive',
            'actor': 'admin', 'time': DateTime(), 'comments': 'E2E test'})
        ar.reindexObject(idxs=['review_state'])
    transaction.savepoint(optimistic=True)

    # ── worksheet holding every analysis ────────────────────────────────
    ws_folder = portal.worksheets
    ws_id = None
    for wid in ws_folder.objectIds():
        if ws_folder[wid].Title() == BATCH_TITLE:
            ws_id = wid
            break
    if ws_id is None:
        n = 1
        while 'WS-{0:04d}'.format(n) in ws_folder.objectIds():
            n += 1
        ws_id = 'WS-{0:04d}'.format(n)
        ws_folder.invokeFactory('Worksheet', id=ws_id)
        ws_folder[ws_id].setTitle(BATCH_TITLE)
    ws = ws_folder[ws_id]
    ws_uid = ws.UID()

    linked = 0
    for ar in ars:
        for ab in ar.getAnalyses():
            a = ab.getObject()
            ann = IAnnotations(a.aq_base)
            if ann.get(_BACKREFS_KEY) is None:
                ann[_BACKREFS_KEY] = PersistentMapping()
            store = ann[_BACKREFS_KEY]
            if 'WorksheetAnalysis' not in store:
                store['WorksheetAnalysis'] = PersistentList()
            if ws_uid not in store['WorksheetAnalysis']:
                store['WorksheetAnalysis'].append(ws_uid)
            a.reindexObject()
            linked += 1
    ws.reindexObject()

    transaction.commit()
    print('')
    print('Worksheet   : %s  (%d analyses linked)' % (ws.getId(), linked))
    print('Batch       : %s' % batch.getId())
    print('Client      : %s' % client.Title())
    print('')
    print('run_pipeline batch_id MUST be: %s' % ws.getId())
    print('Logbooks    : /senaite/batches/%s/@@pfas-logbook-index' % batch.getId())
    print('Data Review : /senaite/worksheets/%s/@@pfas-data-review' % ws.getId())


if __name__ == '__main__':
    run(app)  # noqa: F821
