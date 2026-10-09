# -*- coding: utf-8 -*-
"""
Migration: core integration clean-up.

Run inside the SENAITE container, as the senaite user:

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/core_integration_cleanup.py'

  1. Lab name -> core Laboratory. Print Settings kept its own copy, which is
     what certificates have printed; it becomes core's Laboratory title (when
     the two differ) and is removed from Print Settings, which from now on
     shows and saves core's (print_settings.py).
  2. The QC-only Sample Types an early spec sync created ("<method> LFSM",
     "<method> LFSMD"; samples are never of a QC type) are deleted -- only when
     no sample uses them; one in use is reported and kept.
  3. Core specifications at registration: the Add Sample form's
     "Specification" field is hidden (core's own form-field setting, which
     the lab can switch back), and the client's "Analysis Specifications"
     tab is hidden (: side doors).
  4. Sample Types show the holding time as their Retention Period, the seeded
     values cleared (retention_sync.py).
  5. The "Laboratory Control Sample" Reference Definition is tagged [QC:LCS]:
     its own QC type, which no current method runs.

Idempotent: a second run changes nothing. Values are not printed (the lab's
name is not for logs). Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json

QC_ONLY_SUFFIXES = (" LFSM", " LFSMD")


def lab_name_to_core(portal):
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.print_settings import PRINT_SETTINGS_KEY, set_core_lab_name, core_lab_name
    ann = IAnnotations(portal)
    raw = ann.get(PRINT_SETTINGS_KEY)
    data = json.loads(raw) if raw else {}
    stored = (data.get("lab_name") or u"").strip()
    if not stored:
        return "lab name: nothing stored in Print Settings"
    changed = stored != core_lab_name(portal)
    if changed:
        set_core_lab_name(portal, stored)
    data.pop("lab_name", None)
    ann[PRINT_SETTINGS_KEY] = json.dumps(data)
    return "lab name: %s; removed from Print Settings" % (
        "core Laboratory title set from Print Settings" if changed else "already equal to core's")


def drop_qc_only_sample_types(portal):
    from bika.lims import api
    setup_cat = api.get_tool("senaite_catalog_setup")
    sample_cat = api.get_tool("senaite_catalog_sample")
    out = []
    for brain in setup_cat(portal_type="SampleType"):
        title = brain.Title or ""
        if not title.endswith(QC_ONLY_SUFFIXES):
            continue
        uid = brain.UID
        used = len(sample_cat(getSampleTypeUID=uid))
        if used:
            out.append("kept %s: %d sample(s) use it" % (title, used))
            continue
        obj = brain.getObject()
        obj.aq_parent.manage_delObjects([obj.getId()])
        out.append("deleted Sample Type %s (no sample used it)" % title)
    return out or ["no QC-only Sample Types"]


AR_FORM_STORAGE = "bika.lims.browser.analysisrequest.manage.add"   # core add2.py
HIDDEN_SAMPLE_FIELDS = ("Specification",)


def hide_spec_entry_points(portal):
    from bika.lims import api
    from BTrees.OOBTree import OOBTree
    from zope.annotation.interfaces import IAnnotations
    out = []
    ann = IAnnotations(api.get_setup())
    store = ann.get(AR_FORM_STORAGE)
    if store is None:
        store = ann[AR_FORM_STORAGE] = OOBTree()
    vis = dict(store.get("visibility") or {})
    for name in HIDDEN_SAMPLE_FIELDS:
        if vis.get(name, True):
            vis[name] = False
            out.append("Add Sample form: %s field hidden" % name)
    store.update({"visibility": vis})
    fti = api.get_tool("portal_types").get("Client")
    for action in (fti.listActions() if fti is not None else []):
        if action.getId() == "specs" and action.visible:
            action.visible = False
            out.append("Client tab Analysis Specifications hidden")
    return out or ["specification entry points already hidden"]


def tag_lcs(portal):
    from bika.lims import api
    out = []
    for obj in api.get_setup().bika_referencedefinitions.objectValues():
        desc = obj.Description() or u""
        if obj.Title() == u"Laboratory Control Sample" and u"[QC:" not in desc:
            obj.setDescription((desc + u" [QC:LCS]").strip())
            obj.reindexObject()
            out.append(u"Reference Definition Laboratory Control Sample tagged [QC:LCS]")
    return out or [u"LCS already tagged"]


def run(portal):
    from senaite.pfas.retention_sync import sync as sync_retention
    for line in sync_retention(portal) or [u"retention already follows the holding times"]:
        print(line)
    for line in tag_lcs(portal):
        print(line)
    print(lab_name_to_core(portal))
    for line in drop_qc_only_sample_types(portal):
        print(line)
    for line in hide_spec_entry_points(portal):
        print(line)


if __name__ == "__main__":
    import transaction
    from Testing.makerequest import makerequest
    from zope.component.hooks import setSite
    app_ = makerequest(app)                                 # noqa: F821 (bin/instance run)
    portal_ = app_.senaite
    setSite(portal_)
    # catalogs filter by the current user: run as the Zope admin, or samples
    # are invisible (a "no sample uses it" check would always pass)
    from AccessControl.SecurityManagement import newSecurityManager
    newSecurityManager(None, app_.acl_users.getUserById("admin").__of__(app_.acl_users))
    run(portal_)
    transaction.commit()
    print("committed")
