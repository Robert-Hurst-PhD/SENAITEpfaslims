# -*- coding: utf-8 -*-
"""
Migrate stored calibrator injection names from the hardcoded "FDA-CAL-" prefix
to the FDA method's core code prefix (Method.MethodID == "FDA_32PFAS"), so a
logged calibration standard name matches its run-worklist injection name.

Touches the stored PrepLogbookDef objects' field_schema_json (the Calibration
Curve Prep Log template's default cal-point names). The prefix is resolved from
core services via method_bridge — never hardcoded here. Idempotent.

Run:  bin/instance -O senaite run migrate_cal_names_method_code.py
"""
from __future__ import absolute_import, print_function, unicode_literals

import transaction
from bika.lims import api
from senaite.pfas.method_bridge import get_method_cal_code

OLD = u"FDA-CAL-"

portal = api.get_portal()
new_prefix = get_method_cal_code(portal, "FDA_32PFAS")  # -> "FDA_32PFAS"
new = u"{0}-CAL-".format(new_prefix)
print(u"prefix: {0!r} -> {1!r}".format(OLD, new))
if new == OLD:
    print("nothing to do (prefix unchanged)")
    raise SystemExit(0)

folder = portal.get("pfas_prep_logbooks")
changed = 0
if folder is not None:
    for obj in folder.objectValues():
        if getattr(obj, "portal_type", "") != "PrepLogbookDef":
            continue
        fs = getattr(obj, "field_schema_json", u"") or u""
        if OLD in fs:
            obj.field_schema_json = fs.replace(OLD, new)
            try:
                obj.reindexObject()
            except Exception:
                pass
            changed += 1
            print(u"  migrated PrepLogbookDef id={0} slug={1}".format(
                obj.getId(), getattr(obj, "logbook_slug", "")))
else:
    print("no pfas_prep_logbooks folder (defs come from code seed — no migration)")

print(u"migrated {0} stored def(s).".format(changed))
transaction.commit()
print("committed.")
