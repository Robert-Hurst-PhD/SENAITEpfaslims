# -*- coding: utf-8 -*-
"""Give demo samples' analyses the method they were (notionally) run by
(GAPS §79).

The certificate and the publish guard refuse a sample whose reported
analyses carry no method (GAPS §77). The seeded demo samples were created
without one. This sets it the way a worksheet would have:

  1. the analysis's worksheet method, when the worksheet has one;
  2. else the method profile that lists the sample's matrix -- and when
     several do (water is in both EPA 537.1 and EPA 1633A), the one with the
     FEWEST matrices, i.e. the method written for that matrix;
  3. no method lists the matrix, or a tie -> left alone and reported.

A worksheet without a method whose analyses all resolve to one method gets
that method too, so the worksheet route agrees. Nothing else is changed: the
RL needs no seeding, it is the method's lowest calibrator (GAPS §79).

DEMO DATA ONLY. Dry run by default:

    docker exec -u senaite senaite_pfas-senaite-1 bin/instance run /addon/tools/reseed_demo_methods.py
    docker exec -u senaite -e PFAS_APPLY=1 senaite_pfas-senaite-1 bin/instance run /addon/tools/reseed_demo_methods.py

Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals


def choose(matrix, worksheet_method, supported):
    """(method_id or None, why). `supported` = {method_id: [matrix, ...]}."""
    if worksheet_method:
        return worksheet_method, u"worksheet method"
    fits = sorted((len(ms), mid) for mid, ms in supported.items() if matrix in (ms or []))
    if not fits:
        return None, u"no method profile lists the matrix %r" % matrix
    if len(fits) > 1 and fits[0][0] == fits[1][0]:
        return None, u"methods tie for %r: %s" % (matrix, u", ".join(m for _n, m in fits))
    why = u"only method for %r" % matrix if len(fits) == 1 else (
        u"most specific of %s for %r" % (u", ".join(m for _n, m in fits), matrix))
    return fits[0][1], why


def main(app):
    import os
    import transaction
    from zope.component.hooks import setSite
    from bika.lims import api
    from senaite.pfas.method_profile_store import get_profile
    from senaite.pfas.sample_method import reported_analyses, identify_from

    portal = app.senaite
    setSite(portal)
    apply_ = os.environ.get("PFAS_APPLY") == "1"
    methods = dict((b.getObject().getMethodID(), b.getObject())
                   for b in api.get_tool("senaite_catalog_setup").unrestrictedSearchResults(
                       portal_type="Method"))
    supported = dict((mid, list(get_profile(portal, mid).get("supported_matrices") or []))
                     for mid in methods)
    worksheets = {}
    for b in api.get_tool("senaite_catalog_sample").unrestrictedSearchResults(
            portal_type="AnalysisRequest"):
        sample = b.getObject()
        analyses = reported_analyses(sample)
        method, problem = identify_from(analyses)
        if not problem:
            continue
        st = sample.getSampleType()
        matrix = st.Title() if st else u""
        changes = []
        for an in analyses:
            ws = an.getWorksheet()
            ws_method = ws.getMethod() if ws else None
            mid, why = choose(matrix, ws_method.getMethodID() if ws_method else None, supported)
            if mid is None:
                changes = None
                print("SKIP", sample.getId(), why)
                break
            changes.append((an, methods[mid], why))
            if ws is not None and ws_method is None:
                worksheets.setdefault(ws, set()).add(mid)
        if not changes:
            continue
        print("SET ", sample.getId(), matrix, "->", changes[0][1].getMethodID(),
              "(%s)" % changes[0][2], len(changes), "analyses")
        if apply_:
            for an, m, _why in changes:
                an.setMethod(m)
                an.reindexObject()
    for ws, mids in sorted(worksheets.items(), key=lambda kv: kv[0].getId()):
        if len(mids) == 1:
            mid = list(mids)[0]
            print("WS  ", ws.getId(), "->", mid)
            if apply_:
                ws.setMethod(methods[mid])
                ws.reindexObject()
        else:
            print("WS  ", ws.getId(), "left without a method: holds", sorted(mids))
    if apply_:
        transaction.commit()
        print("applied")
    else:
        print("dry run; PFAS_APPLY=1 to apply")


if "app" in globals():
    main(globals()["app"])
