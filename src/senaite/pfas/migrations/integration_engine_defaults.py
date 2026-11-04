# -*- coding: utf-8 -*-
"""Name the integration engine and the m/z tolerance on every method that
already has an Integration block.

The worker reads an unset engine as classic and an unset m/z tolerance as
0.1 (a file's transition matched to the method's within 0.1 m/z). This writes both
where they are missing, so the method's Integration section shows what its
runs use. A value the lab has set is never overwritten, and a method with no
Integration block is left alone (nothing is seeded). Each change goes
through the store's own save, so the change history records it.

Run it twice and the second run reports nothing to do. Dry run first:

    bin/instance -O senaite run \
        src/senaite/pfas/migrations/integration_engine_defaults.py --dry-run
    bin/instance -O senaite run \
        src/senaite/pfas/migrations/integration_engine_defaults.py

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function

import sys

# what a block without the key is integrated with, in the order written
DEFAULTS = ((u"engine", u"classic"), (u"mz_tolerance", 0.1))


def missing_defaults(profile):
    """{key: value} the method's Integration block lacks, or {} when it has
    no block (an empty block is none)."""
    intg = (profile or {}).get(u"integration")
    if not isinstance(intg, dict) or not intg:
        return {}
    return dict((k, v) for k, v in DEFAULTS if intg.get(k) in (None, u""))


def run(portal, dry_run=False, store=None):
    """Write the missing defaults through the store's save. Returns
    [(method_id, {key: value} added)]; a dry run returns the same and
    writes nothing."""
    if store is None:
        from senaite.pfas import method_profile_store as store
    changed = []
    for method_id in sorted(store.list_method_ids(portal)):
        profile = store.get_profile(portal, method_id) or {}
        add = missing_defaults(profile)
        if not add:
            continue
        print("  %-11s %s" % (method_id, ", ".join(
            "%s = %s" % (k, add[k]) for k, _v in DEFAULTS if k in add)))
        if not dry_run:
            intg = dict(profile[u"integration"])
            intg.update(add)
            profile[u"integration"] = intg
            store.save_profile(portal, method_id, profile, label=u"Integration engine defaults")
        changed.append((method_id, add))
    return changed


def main(app, dry_run):
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.users import UnrestrictedUser
    portal = [o for o in app.objectValues("Plone Site")][0]
    newSecurityManager(None, UnrestrictedUser("admin", "", ["Manager"], []))
    print("Naming the integration engine and m/z tolerance%s" % (" (dry run)" if dry_run else ""))
    changed = run(portal, dry_run=dry_run)
    if not changed:
        print("Nothing to do.")
        transaction.abort()
    elif dry_run:
        print("Dry run: nothing written (%d to change)." % len(changed))
        transaction.abort()
    else:
        transaction.commit()
        print("Committed: %s" % ", ".join(m for m, _add in changed))


if "app" in globals():
    main(globals()["app"], "--dry-run" in sys.argv)      # noqa: F821  (bin/instance run)
