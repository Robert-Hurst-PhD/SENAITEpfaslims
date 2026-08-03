# -*- coding: utf-8 -*-
"""
E2E acceptance test — Stage 1b: receive the samples and load the worksheet.

Two scaffold problems this fixes, both caused by short-cutting SENAITE's
workflow in the first pass:

  * forcing the sample review_state with `setStatusOf` never set DateReceived
    and never cascaded `initialize` to the analyses, so all 288 analyses sat in
    `registered` with no allowed transitions and `getAnalyses()` returned [];
  * writing the WorksheetAnalysis back-reference by hand made
    `analysis.getWorksheet()` truthy, so `Worksheet.addAnalysis` bailed out on
    its "already assigned" guard without saying so.

Run:  bin/instance -O senaite run /addon/e2e_kcp_worksheet.py
"""
from __future__ import absolute_import, print_function

import transaction

from bika.lims import api
from zope.annotation.interfaces import IAnnotations

_BACKREFS_KEY = 'bika.lims.browser.fields.uidreferencefield.backreferences'

WS_ID = 'WS-0005'
CLIENT_ID = 'kcp-feed-forage'
METHOD_TITLE = 'USDA/FDA 32-PFAS in Food v10'
ANALYST = 'KCP'


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
    from bika.lims.workflow import doActionFor

    scat = getToolByName(portal, 'senaite_catalog_setup')
    ws = portal.worksheets[WS_ID]
    client = portal.clients[CLIENT_ID]

    method = None
    for brain in scat.unrestrictedSearchResults(portal_type='Method'):
        obj = brain.getObject()
        if obj.Title() == METHOD_TITLE:
            method = obj
            break

    try:
        ws.setAnalyst(ANALYST)
    except Exception as exc:
        print('setAnalyst failed: %s' % exc)
    if method is not None:
        try:
            ws.setMethod(method, override_analyses=True)
        except Exception as exc:
            print('setMethod failed: %s' % exc)

    ars = list(client.objectValues('AnalysisRequest'))

    # 1. give every sample a receipt date and initialise its analyses
    init = 0
    for ar in ars:
        if not ar.getDateReceived():
            ar.setDateReceived(DateTime('2025/10/16 09:05:00'))
            ar.reindexObject()
        for a in ar.objectValues('Analysis'):
            ann = IAnnotations(a.aq_base)
            store = ann.get(_BACKREFS_KEY)
            if store and 'WorksheetAnalysis' in store:
                del store['WorksheetAnalysis']
            if api.get_review_status(a) == 'registered':
                doActionFor(a, 'initialize')
                init += 1
        transaction.savepoint(optimistic=True)
    print('initialised %d analyses' % init)

    # 2. add through the real API (needs ws_uid in the request for guard_assign)
    try:
        api.get_request().set('ws_uid', api.get_uid(ws))
    except Exception as exc:
        print('could not set ws_uid on request: %s' % exc)

    added = 0
    skipped = 0
    for ar in ars:
        for a in ar.objectValues('Analysis'):
            before = len(ws.getLayout() or [])
            ws.addAnalysis(a)
            if len(ws.getLayout() or []) > before:
                added += 1
            else:
                skipped += 1
                if skipped < 4:
                    print('  skipped %s state=%s ws=%s'
                          % (a.getId(), api.get_review_status(a),
                             a.getWorksheet()))
        transaction.savepoint(optimistic=True)

    ws.reindexObject()
    transaction.commit()

    print('added=%d skipped=%d' % (added, skipped))
    print('ws.getAnalyses(): %d' % len(ws.getAnalyses() or []))
    print('ws.getLayout():   %d' % len(ws.getLayout() or []))
    print('ws state:         %s' % api.get_review_status(ws))
    m = ws.getMethod()
    print('ws.getMethod():   %s' % (m and m.getId()))

    view = ws.restrictedTraverse('@@pfas-data-review')
    print('data_review.batch_method(): %r' % view.batch_method())


if __name__ == '__main__':
    run(app)  # noqa: F821
