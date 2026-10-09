# -*- coding: utf-8 -*-
"""
Migration: retire the SENAITE AnalysisSpec copy of the method profiles.


spec_sync wrote one core AnalysisSpec per method x QC type x matrix holding
RECOVERY windows (%). No sample used one, and none could be used correctly:
SENAITE judges an analysis's result -- a concentration -- against its spec's
range. The criteria live on the method profiles; @@pfas-specifications reads
them (with a project's specs applied). This step:

  1. writes every spec the sync made, with its ranges, to
     /data/qc/retired_analysis_specs-<date>.json (the record of what they held);
  2. deletes them -- ONLY specs the sync wrote (every range row carries the
     sync's comment) and ONLY if no sample references one (checked; such a
     spec is kept and reported). Specs a person made in SENAITE are kept.

Dry run by default; pass --apply to delete:

  docker exec -u senaite <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/retire_core_specs.py [--apply]

Idempotent. Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
import io
import json
import os
import sys

SYNC_MARKS = ("(PFAS auto-sync)", "(PFAS)")
RECORD_DIR = "/data/qc"


def written_by_sync(rows):
    """True when every range row carries a comment the sync wrote ("Tier n
    recovery limit (PFAS auto-sync)", "Per-analyte override (PFAS)"); an empty
    spec or one with any other row was not the sync's alone."""
    rows = list(rows or [])
    return bool(rows) and all(
        any(m in (r.get("rangecomment") or "") for m in SYNC_MARKS) for r in rows)


def _u(v):
    """Text as unicode (Python 2 titles come back as UTF-8 bytes)."""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def _plain(rows):
    return [dict((_u(k), _u(v)) for k, v in r.items() if k != "uid") for r in rows or []]


def run(portal, apply=False):
    from bika.lims import api
    folder = portal.bika_setup.bika_analysisspecs
    used = set()
    for b in api.search({"portal_type": "AnalysisRequest"}, "senaite_catalog_sample"):
        spec = b.getObject().getSpecification()
        if spec is not None:
            used.add(spec.getId())
    synced, kept = [], []
    for spec in folder.objectValues():
        rows = spec.getResultsRange() or []
        if not written_by_sync(rows):
            kept.append((spec.getId(), "not written by the sync"))
        elif spec.getId() in used:
            kept.append((spec.getId(), "a sample references it"))
        else:
            st = spec.getSampleType() if hasattr(spec, "getSampleType") else None
            synced.append({"id": _u(spec.getId()), "title": _u(spec.Title()),
                           "description": _u(spec.Description()),
                           "sample_type": _u(st.Title()) if st is not None else "",
                           "results_range": _plain(rows)})
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(RECORD_DIR, "retired_analysis_specs-%s.json" % stamp)
    print("synced specs: %d; kept: %d" % (len(synced), len(kept)))
    for sid, why in kept:
        print("  kept %s (%s)" % (sid, why))
    if not apply:
        print("dry run: nothing written or deleted (pass --apply)")
        return synced, kept, None
    if synced:
        with io.open(path, "w", encoding="utf-8") as fh:
            text = json.dumps(synced, indent=1, sort_keys=True, ensure_ascii=True)
            fh.write(_u(text))
        # SENAITE withholds "Delete objects" on setup folders (it deactivates
        # setup items instead); these are the sync's own copies, recorded
        # above, so they are removed as cleanup_synthetic_qc_sampletypes did
        for s in synced:
            folder._delObject(s["id"])
        print("recorded in %s; deleted %d" % (path, len(synced)))
    return synced, kept, path if synced else None


if __name__ == "__main__":
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from Testing.makerequest import makerequest
    from zope.component.hooks import setSite
    app2 = makerequest(globals()["app"])
    portal = app2.senaite
    setSite(portal)
    # wrapped in its user folder, or Zope does not see its roles
    folder = app2.acl_users
    user = folder.getUser("admin")
    if user is None:
        folder = portal.acl_users
        user = folder.getUser("admin")
    newSecurityManager(None, user.__of__(folder))
    apply = "--apply" in sys.argv
    run(portal, apply=apply)
    if apply:
        transaction.commit()
    else:
        transaction.abort()
