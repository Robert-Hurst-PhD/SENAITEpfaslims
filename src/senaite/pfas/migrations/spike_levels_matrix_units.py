# -*- coding: utf-8 -*-
"""
Spike levels in each matrix's reporting unit ("spike levels
for soil should update so the unit is appropriate for the matrix").

Every per-matrix spike level stored as `ppt` becomes `value` in that matrix's
unit (Matrices & Units): ng/L, ng/kg and pg/g are ppt (unchanged numbers);
ng/g and ng/mL are 1000 ppt. A level whose unit cannot be converted keeps its
`ppt` and is listed for the lab. Each change is printed; the save exports the
worker's copy and records the change history.

  docker exec -u senaite <container> sh -c 'cd /home/senaite/senaitelims && \
    bin/instance run /addon/src/senaite/pfas/migrations/spike_levels_matrix_units.py'

Idempotent. Python 2.7.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy


def run(portal):
    from senaite.pfas.calibration_levels import level_value, matrix_unit, migrate_spike_levels
    from senaite.pfas.method_profile_store import list_method_ids, raw_profile, save_profile
    for mid in list_method_ids(portal):
        profile = copy.deepcopy(raw_profile(portal, mid) or {})
        before = copy.deepcopy(profile.get("spike_levels") or {})
        if not migrate_spike_levels(profile):
            print("%s: up to date" % mid)
            continue
        for matrix, by_type in sorted((profile.get("spike_levels") or {}).items()):
            unit = matrix_unit(profile, matrix)
            for qc, entries in sorted((by_type or {}).items()):
                for e in entries or []:
                    old = [x for x in ((before.get(matrix) or {}).get(qc) or []) if x.get("label") == e.get("label")]
                    if e.get("value") is not None:
                        print("%s / %s / %s %s: %s ppt -> %s %s" % (
                            mid, matrix, qc, e.get("label"), old[0].get("ppt") if old else "?",
                            level_value(e, unit), unit))
                    elif "ppt" in e:
                        print("%s / %s / %s %s: NOT converted (unit %r) -- lab to enter" % (
                            mid, matrix, qc, e.get("label"), unit))
        save_profile(portal, mid, profile)
        print("%s: saved" % mid)


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
