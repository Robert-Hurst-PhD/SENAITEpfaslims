# -*- coding: utf-8 -*-
"""Dump every PFAS configuration store to one JSON file (GAPS §51).

Run inside the instance (Python 2.7):
    bin/instance run tools/config_snapshot.py OUT.json

Covers what a configuration save can write to, which is wider than the portal's
annotations: the PFAS annotations on the portal and on every client, the
objects in every pfas_* folder, the pfas_* fields on every AnalysisService
(the surrogate link is written onto core services), ReferenceDefinitions, and
the QC JSON files in /data/qc. Used by tools/config_save_audit.py to prove that
saving a page unchanged changes nothing.
"""
from __future__ import print_function

import glob
import json
import os
import sys

from zope.component.hooks import setSite
from zope.annotation.interfaces import IAnnotations

SKIP_ANNOTATIONS = ("senaite.pfas.tracking", "senaite.pfas.import_studio_audit",
                    "senaite.pfas.spec_sync_audit", "senaite.pfas.sidebar_pins",
                    "senaite.pfas.wizard_sessions")   # logs / per-user, not settings


def plain(value, depth=0):
    """Persistent structures -> JSON-able plain values; JSON strings decoded."""
    if depth > 12:
        return repr(value)
    if hasattr(value, "items") and not isinstance(value, (str, bytes)):
        return dict((str(k), plain(v, depth + 1)) for k, v in value.items())
    if isinstance(value, (list, tuple)) or type(value).__name__ in ("PersistentList",):
        return [plain(v, depth + 1) for v in value]
    if isinstance(value, basestring):                                   # noqa: F821
        s = value.strip()
        if s[:1] in "[{":
            try:
                return {"__json__": json.loads(s)}
            except ValueError:
                pass
        return value
    if value is None or isinstance(value, (bool, int, float, long)):    # noqa: F821
        return value
    return repr(value)


def obj_attrs(obj):
    out = {}
    for k, v in sorted(getattr(obj, "__dict__", {}).items()):
        if k.startswith("_") or k in ("workflow_history", "__ac_local_roles__",
                                      "creation_date", "modification_date"):
            continue
        out[k] = plain(v)
    return out


def snapshot(portal):
    snap = {"annotations": {}, "folders": {}, "services": {}, "clients": {},
            "refdefs": {}, "files": {}}
    ann = IAnnotations(portal)
    for key in sorted(ann.keys()):
        if "pfas" in key.lower() and not key.startswith(SKIP_ANNOTATIONS):
            snap["annotations"][key] = plain(ann[key])
    for fid in sorted(portal.objectIds()):
        if fid.startswith("pfas"):
            snap["folders"][fid] = dict(
                (o.getId(), obj_attrs(o)) for o in portal[fid].objectValues())
    for svc in portal.bika_setup.bika_analysisservices.objectValues():
        fields = {}
        for f in svc.Schema().fields():
            if "pfas" in f.getName().lower():
                fields[f.getName()] = plain(f.get(svc))
        snap["services"][svc.getKeyword()] = fields
    for client in portal.clients.objectValues():
        a = IAnnotations(client)
        snap["clients"][client.getId()] = dict(
            (k, plain(a[k])) for k in a.keys() if "pfas" in k.lower())
    try:
        folder = portal.bika_setup.bika_referencedefinitions
        for rd in folder.objectValues():
            snap["refdefs"][rd.getId()] = {
                "title": rd.Title(), "blank": bool(rd.getBlank()),
                "results": plain(rd.getReferenceResults())}
    except Exception as exc:                                            # noqa: BLE001
        snap["refdefs"]["__error__"] = repr(exc)
    for path in sorted(glob.glob("/data/qc/*.json")):
        with open(path) as fh:
            try:
                snap["files"][os.path.basename(path)] = json.load(fh)
            except ValueError:
                snap["files"][os.path.basename(path)] = "<<invalid JSON>>"
    return snap


if __name__ == "__main__":
    portal = app.senaite                                                # noqa: F821
    setSite(portal)
    out = sys.argv[-1]
    with open(out, "w") as fh:
        json.dump(snapshot(portal), fh, indent=1, sort_keys=True)
    print("snapshot written:", out)
