# -*- coding: utf-8 -*-
"""Name the curve fit on every method that has a calibration block.

A method profile without instrument_verification.calibration.fit is fitted
linear (calibration_fit.fit). This writes "linear" where the fit is
missing, so QC criteria's Calibration card shows what the method's curves
are fitted with; no result changes. A fit the lab has chosen is never
overwritten, and a method with no calibration block is left alone (nothing
is seeded). Each change goes through the store's own save, so the change
history records it.

The add-on's install step runs it (setuphandlers.post_install). Run it
twice and the second run reports nothing to do. By hand, dry run first:

    bin/instance -O senaite run \
        src/senaite/pfas/migrations/calibration_fit_default.py --dry-run
    bin/instance -O senaite run \
        src/senaite/pfas/migrations/calibration_fit_default.py

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function

import sys

LABEL = u"Curve fit named"


def run(portal, dry_run=False, store=None):
    """Write the missing fit through the store's save. Returns the method
    ids changed; a dry run returns the same and writes nothing."""
    from senaite.pfas import calibration_fit
    if store is None:
        from senaite.pfas import method_profile_store as store
    changed = []
    for method_id in sorted(store.list_method_ids(portal)):
        profile = store.get_profile(portal, method_id) or {}
        if not calibration_fit.missing_fit(profile):
            continue
        print("  %-11s fit = %s" % (method_id, calibration_fit.FIT_WHEN_UNSET))
        if not dry_run:
            iv = dict(profile[u"instrument_verification"])
            cal = dict(iv[u"calibration"])
            cal[u"fit"] = calibration_fit.FIT_WHEN_UNSET
            iv[u"calibration"] = cal
            profile[u"instrument_verification"] = iv
            store.save_profile(portal, method_id, profile, label=LABEL)
        changed.append(method_id)
    return changed


def main(app, dry_run):
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.users import UnrestrictedUser
    portal = [o for o in app.objectValues("Plone Site")][0]
    newSecurityManager(None, UnrestrictedUser("admin", "", ["Manager"], []))
    print("Naming the curve fit%s" % (" (dry run)" if dry_run else ""))
    changed = run(portal, dry_run=dry_run)
    if not changed:
        print("Nothing to do.")
        transaction.abort()
    elif dry_run:
        print("Dry run: nothing written (%d to change)." % len(changed))
        transaction.abort()
    else:
        transaction.commit()
        print("Committed: %s" % ", ".join(changed))


if "app" in globals():
    main(globals()["app"], "--dry-run" in sys.argv)      # noqa: F821  (bin/instance run)
