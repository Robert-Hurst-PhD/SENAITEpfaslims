# -*- coding: utf-8 -*-
"""
Seed the Data Review pending-worklist with three realistic worksheets so the
enriched columns (analyst / review status / open-since-extraction / time-in-
review) have something to show:

  1. open,           extraction in progress   (analyst J. Smith,   9d open)
  2. open,           on instrument            (analyst M. Johnson, 15d open)
  3. to_be_verified, awaiting peer review      (analyst A. Rivera,  22d open,
                                                submitted 4d ago -> in review)

Backdates extraction 'started' timestamps and the 'submit' workflow event so
the durations render as real spans, not 0m.

Run inside the container:
    docker exec -u senaite senaite_pfas-senaite-1 \
        sh -lc 'cd /home/senaite/senaitelims && bin/instance -O senaite run /addon/seed_pending_reviews.py'

Python 2.7 compatible.
"""
from __future__ import print_function, absolute_import

import datetime
import json
import os

import transaction
from persistent.list import PersistentList
from persistent.mapping import PersistentMapping
from zope.annotation.interfaces import IAnnotations

from DateTime import DateTime
from Products.CMFCore.utils import getToolByName

_BACKREFS_KEY = 'bika.lims.browser.fields.uidreferencefield.backreferences'
EXTRACTION_LOG_DIR = os.environ.get("EXTRACTION_LOG_DIR", "/data/extraction_logs")

AR_WF = 'senaite_sample_workflow'
WS_WF = 'senaite_worksheet_workflow'


def run(app):
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.User import UnrestrictedUser
    newSecurityManager(None, UnrestrictedUser('admin', '', ['Manager'], []))

    portal = app.senaite
    try:
        from zope.site.hooks import setSite
        setSite(portal)
    except Exception:
        pass

    wf_tool = getToolByName(portal, 'portal_workflow')
    scat = getToolByName(portal, 'senaite_catalog_setup')

    print("=" * 62)
    print("Seeding pending Data Review worksheets")
    print("=" * 62)

    # ── Reference data ────────────────────────────────────────────────────
    st_brains = scat.unrestrictedSearchResults(portal_type='SampleType')
    sample_types = {b.Title: b.getObject() for b in st_brains}
    m_brains = scat.unrestrictedSearchResults(portal_type='Method')
    methods = {b.Title: b.getObject() for b in m_brains}
    svc_brains = scat.unrestrictedSearchResults(portal_type='AnalysisService')
    services = [b.getObject() for b in svc_brains[:3]]

    def pick_type(name):
        return sample_types.get(name) or list(sample_types.values())[0]

    def pick_method(name):
        return methods.get(name) or list(methods.values())[0]

    st_water = pick_type('Drinking Water')
    st_ground = pick_type('Groundwater')
    st_soil = pick_type('Soil')
    m_537 = pick_method('EPA 537.1 PFAS in Drinking Water')
    m_fda = pick_method('USDA/FDA 32-PFAS in Food v10')
    m_1633 = pick_method('EPA 1633A PFAS (aqueous/solid/biosolid/tissue)')

    # ── Client + contact ──────────────────────────────────────────────────
    existing = list(portal.clients.objectValues('Client'))
    if existing:
        client = existing[0]
    else:
        portal.clients.invokeFactory('Client', id='pfas-demo-client')
        client = portal.clients['pfas-demo-client']
        client.schema['Name'].set(client, 'PFAS Demo Client')
        client.schema['ClientID'].set(client, 'DEMO001')
        client.reindexObject()
        transaction.savepoint(optimistic=True)
    contacts = list(client.objectValues('Contact'))
    if contacts:
        contact = contacts[0]
    else:
        client.invokeFactory('Contact', id='contact-1')
        contact = client['contact-1']
        contact.schema['Firstname'].set(contact, 'Demo')
        contact.schema['Surname'].set(contact, 'Client')
        contact.reindexObject()
        transaction.savepoint(optimistic=True)
    print("  Client:", client.Title(), " Contact:", contact.getId())

    # ── Helpers ───────────────────────────────────────────────────────────
    from bika.lims.utils.analysisrequest import create_analysisrequest

    def make_ar(sample_type, method):
        values = {
            'Client': client,
            'Contact': contact,
            'SampleType': sample_type,
            'DateSampled': DateTime(),
            'Analyses': [s.UID() for s in services],
            'Method': method,
        }
        ar = create_analysisrequest(client, app.REQUEST, values)
        transaction.savepoint(optimistic=True)
        return ar

    def set_wf_state(obj, wf_id, state_id, action, when=None, actor='admin'):
        wf_tool.setStatusOf(wf_id, obj, {
            'review_state': state_id,
            'action': action,
            'actor': actor,
            'time': when or DateTime(),
            'comments': 'Demo pending-review seed',
        })
        obj.reindexObject(idxs=['review_state'])
        transaction.savepoint(optimistic=True)

    def make_worksheet(ar, analyst_id=None):
        ws_folder = portal.worksheets
        existing_ids = set(ws_folder.objectIds())
        n = len(existing_ids) + 1
        while 'WS-{:04d}'.format(n) in existing_ids:
            n += 1
        ws_id = 'WS-{:04d}'.format(n)
        ws_folder.invokeFactory('Worksheet', id=ws_id)
        ws = ws_folder[ws_id]
        if analyst_id:
            try:
                ws.setAnalyst(analyst_id)
            except Exception:
                pass
        ws_uid = ws.UID()
        for ab in ar.getAnalyses():
            try:
                a = ab.getObject()
                ann = IAnnotations(a.aq_base)
                if ann.get(_BACKREFS_KEY) is None:
                    ann[_BACKREFS_KEY] = PersistentMapping()
                storage = ann[_BACKREFS_KEY]
                if 'WorksheetAnalysis' not in storage:
                    storage['WorksheetAnalysis'] = PersistentList()
                if ws_uid not in storage['WorksheetAnalysis']:
                    storage['WorksheetAnalysis'].append(ws_uid)
                a.reindexObject()
            except Exception as exc:
                print("    (analysis link failed: {})".format(exc))
        ws.reindexObject()
        transaction.savepoint(optimistic=True)
        return ws

    def write_log(ws_id, analyst, started_days_ago, completed=False):
        if not os.path.exists(EXTRACTION_LOG_DIR):
            os.makedirs(EXTRACTION_LOG_DIR)
        now = datetime.datetime.utcnow()
        started = now - datetime.timedelta(days=started_days_ago)
        data = {
            'batch_id': ws_id,
            'analyst': analyst,
            'started': started.isoformat(),
        }
        if completed:
            data['completed'] = (started
                                 + datetime.timedelta(hours=6)).isoformat()
        path = os.path.join(EXTRACTION_LOG_DIR,
                            '{}_extraction.json'.format(ws_id))
        with open(path, 'w') as fh:
            json.dump(data, fh)

    made = []

    # 1) open — extraction in progress ─────────────────────────────────────
    ar1 = make_ar(st_water, m_537)
    set_wf_state(ar1, AR_WF, 'sample_received', 'receive')
    ws1 = make_worksheet(ar1)
    write_log(ws1.getId(), 'J. Smith', started_days_ago=9, completed=False)
    made.append((ws1.getId(), 'open / extraction in progress', 'J. Smith'))

    # 2) open — on instrument ──────────────────────────────────────────────
    ar2 = make_ar(st_soil, m_fda)
    set_wf_state(ar2, AR_WF, 'sample_received', 'receive')
    ws2 = make_worksheet(ar2)
    write_log(ws2.getId(), 'M. Johnson', started_days_ago=15, completed=True)
    made.append((ws2.getId(), 'open / on instrument', 'M. Johnson'))

    # 3) to_be_verified — awaiting peer review ─────────────────────────────
    ar3 = make_ar(st_ground, m_1633)
    set_wf_state(ar3, AR_WF, 'sample_received', 'receive')
    ws3 = make_worksheet(ar3, analyst_id='admin')
    write_log(ws3.getId(), 'A. Rivera', started_days_ago=22, completed=True)
    submitted_when = DateTime(
        (datetime.datetime.utcnow()
         - datetime.timedelta(days=4)).strftime('%Y-%m-%d %H:%M:%S'))
    set_wf_state(ws3, WS_WF, 'to_be_verified', 'submit',
                 when=submitted_when, actor='A. Rivera')
    made.append((ws3.getId(),
                 'to_be_verified / in peer review (submitted 4d ago)',
                 'A. Rivera'))

    transaction.commit()

    print("\nSeeded worksheets:")
    for wid, desc, analyst in made:
        print("  {:<9s} {:<52s} {}".format(wid, desc, analyst))
    print("\nOpen the Data Review workspace (no worksheet selected) to see the")
    print("pending worklist populate.")
    print("=" * 62)


if __name__ == '__main__':
    run(app)  # noqa: F821  (bin/instance run injects `app`)
