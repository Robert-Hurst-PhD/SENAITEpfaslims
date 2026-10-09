# -*- coding: utf-8 -*-
"""
The extraction record moves from the client Batch to its Worksheet (decision D1: the worksheet is the extraction batch).

For each Batch holding a guided-extraction session or an Extraction Log
(FM-ENV-003): when exactly one worksheet holds its analyses and that
worksheet has no record of its own, the session and the log move there, and
the batch's QC spike rows become the worksheet's members (extraction_batch).
A batch with no worksheet, or several, is listed and left for the lab.

What moved is written first to /data/qc/extraction_moved-<timestamp>.json.

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/extraction_to_worksheet.py'

Idempotent. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import os
from datetime import datetime


def members_from_rows(samples, rows, ws_id):
    """Members for the worksheet's samples plus the older spike rows (their
    injection names kept: runs already made carry them). Pure."""
    try:
        from senaite.pfas import extraction_batch as eb
        from senaite.pfas.dilution_ref import spikes_from_rows
    except ImportError:                                     # tests, outside Plone
        import extraction_batch as eb
        from dilution_ref import spikes_from_rows
    members = eb.sync_samples([], samples)
    # a batch extracted before the LIMS issued names ran its samples
    # under their Client Sample IDs: those stay their injection names, so
    # its runs still match (new batches use the SENAITE id)
    for m in members:
        m["injection"] = m.get("client_sid") or m["injection"]
    by_name = {}
    for m in members:
        by_name[m["client_sid"]] = by_name[m["sample_id"]] = m["id"]
    record = spikes_from_rows(rows)
    ids = {}
    for inj in sorted(record, key=lambda k: (record[k]["qc_type"] == u"LFSMD", k)):
        r = record[inj]
        m = {"id": eb._next_id(members), "role": r["qc_type"] or u"LFSM", "sample_uid": u"",
             "sample_id": u"", "client_sid": u"", "matrix": u"", "injection": inj,
             "parent": by_name.get(r["parent"], u""), "level": r["level"],
             "amount": (u"%g" % r["spike"]) if r["spike"] is not None else u"",
             "unit": r["spike_unit"] or u"", "lfsm_of": ids.get(r["lfsm"], u""),
             "added_by": u"migrated", "added_at": u""}
        ids[inj] = m["id"]
        members.append(m)
    return eb.follow_lfsm(members)


def run(portal):
    from bika.lims import api
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import extraction_batch as eb
    from senaite.pfas.dilution_ref import EXTRACTION_SESSION_KEY, LOGBOOK_KEY
    moved, kept = [], []
    # a worksheet this migration already gave members: its samples keep the
    # names their runs used (the first run of it named them by SENAITE id)
    for brain in api.search({"portal_type": "Worksheet"}, "senaite_catalog_worksheet"):
        ws = api.get_object(brain)
        members = eb.load(ws)
        if any(m.get("added_by") == u"migrated" for m in members):
            changed = False
            for m in members:
                if m.get("role") == u"Sample" and m.get("client_sid") and m["injection"] != m["client_sid"]:
                    m["injection"] = m["client_sid"]
                    changed = True
            if changed:
                eb.save(ws, members)
                print("%s: samples keep their run names (Client Sample IDs)" % ws.getId())
    for brain in api.search({"portal_type": "Batch"}, "senaite_catalog"):
        batch = api.get_object(brain)
        ann = IAnnotations(batch)
        if not (ann.get(EXTRACTION_SESSION_KEY) or ann.get(LOGBOOK_KEY)):
            continue
        wss = eb.worksheets_of(batch)
        if len(wss) != 1:
            kept.append((batch.getId(), u"%d worksheets" % len(wss)))
            continue
        ws = wss[0]
        wann = IAnnotations(ws)
        if wann.get(EXTRACTION_SESSION_KEY) or wann.get(LOGBOOK_KEY):
            kept.append((batch.getId(), u"%s already has a record" % ws.getId()))
            continue
        log = json.loads(ann.get(LOGBOOK_KEY) or u"{}")
        moved.append({"batch": batch.getId(), "worksheet": ws.getId(),
                      "session": ann.get(EXTRACTION_SESSION_KEY), "logbook_252": ann.get(LOGBOOK_KEY)})
        members = members_from_rows(eb.worksheet_samples(ws), log.get("spikes") or [], ws.getId())
        if ann.get(EXTRACTION_SESSION_KEY):
            wann[EXTRACTION_SESSION_KEY] = ann[EXTRACTION_SESSION_KEY]
            del ann[EXTRACTION_SESSION_KEY]
        if ann.get(LOGBOOK_KEY):
            log.pop("spikes", None)                 # now the members
            wann[LOGBOOK_KEY] = json.dumps(log)
            del ann[LOGBOOK_KEY]
        eb.save(ws, members)
    if moved:
        path = "/data/qc/extraction_moved-%s.json" % datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        if os.path.isdir("/data/qc"):
            with open(path, "w") as fh:
                json.dump(moved, fh)
            print("record of what moved: %s" % path)
    for m in moved:
        print("%s -> %s" % (m["batch"], m["worksheet"]))
    for b, why in kept:
        print("%s left on the batch: %s" % (b, why))
    return moved, kept


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
