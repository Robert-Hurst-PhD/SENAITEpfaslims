# -*- coding: utf-8 -*-
"""Give every compound row of a method's Integration block an empty
processing entry.

A compound's processing entry (integration.analytes.<keyword>.processing)
holds the processing changes countersigned from a run as the method's own
(method_proposals). A row without one reads as an empty entry, and an empty
entry is no setting: the fingerprint, the issued revisions' snapshots and
the worker's revision leave it out, so adding them leaves every issued
revision current. This writes "processing": {} into each row that has none,
so the stored profile shows the entry. A row that holds one is left as it
is, and a method with no Integration block is left alone. Each method's
change goes through the store's own save, so Config History records it.

Run it twice and the second run lists nothing. Dry run unless --apply is
given:

    bin/instance -O senaite run \\
        src/senaite/pfas/migrations/integration_processing_entry.py
    bin/instance -O senaite run \\
        src/senaite/pfas/migrations/integration_processing_entry.py --apply

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import sys

LABEL = u"Integration: empty processing entries"


def missing(profile):
    """The keywords of the Integration rows with no processing entry, in
    order; [] when the method has no Integration block."""
    rows = ((profile or {}).get(u"integration") or {}).get(u"analytes")
    if not isinstance(rows, dict):
        return []
    return sorted(kw for kw, row in rows.items() if isinstance(row, dict) and u"processing" not in row)


def run(portal, apply=False, store=None):
    """Add the empty entries through the store's save. Returns
    [(method_id, [keyword])] for each method with rows to change; writes
    only with `apply`."""
    if store is None:
        from senaite.pfas import method_profile_store as store
    changed = []
    for method_id in sorted(store.list_method_ids(portal)):
        profile = store.get_profile(portal, method_id) or {}
        rows = missing(profile)
        if not rows:
            continue
        print("  %-11s %s" % (method_id, ", ".join(rows)))
        if apply:
            intg = dict(profile[u"integration"])
            analytes = dict(intg[u"analytes"])
            for kw in rows:
                analytes[kw] = dict(analytes[kw], processing={})
            intg[u"analytes"] = analytes
            profile[u"integration"] = intg
            store.save_profile(portal, method_id, profile, label=LABEL)
        changed.append((method_id, rows))
    return changed


def main(app, apply):
    """Run it on the site: a dry run aborts; an applied run commits only
    when a method changed."""
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.users import UnrestrictedUser
    portal = [o for o in app.objectValues(["Plone Site"])][0]
    newSecurityManager(None, UnrestrictedUser("admin", "", ["Manager"], []))
    print("Giving each Integration row an empty processing entry%s" % ("" if apply else " (dry run)"))
    changed = run(portal, apply=apply)
    if not changed:
        print("Nothing to do.")
        transaction.abort()
    elif not apply:
        print("Dry run: nothing written (%d methods listed). Run again with --apply." % len(changed))
        transaction.abort()
    else:
        transaction.commit()
        print("Committed: %s" % ", ".join(m for m, _rows in changed))


if "app" in globals():
    main(globals()["app"], "--apply" in sys.argv)      # noqa: F821  (bin/instance run)
