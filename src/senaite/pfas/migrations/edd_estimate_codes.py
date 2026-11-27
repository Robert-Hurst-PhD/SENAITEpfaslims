# -*- coding: utf-8 -*-
"""Map the estimate codes CE (co-eluting peaks split) and CF (fitted
estimate) in each EDD profile the lab has saved, as its format's seed maps
them.

A profile reads its qualifier map from its format's seed until the lab
saves it; once saved it keeps its own copy, so a code added to the seed
later is missing from it, and the EDD refuses a result carrying that code
(an internal code with no state code is a BLOCKING error). This adds the
seed's row for CE and for CF where the saved map has no row for that code.
A row the lab set is never overwritten, even one with no code. A profile
with no map of its own reads the seed, which maps both, and is left alone;
a column-mapped delimited profile, whose format has no seed qualifier map,
maps codes on its own Code maps and is only reported. Each change goes
through the store's own save, so the change history records it.

Run it twice and the second run reports nothing to do. Dry run first:

    bin/instance -O senaite run \
        src/senaite/pfas/migrations/edd_estimate_codes.py --dry-run
    bin/instance -O senaite run \
        src/senaite/pfas/migrations/edd_estimate_codes.py

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function

import copy
import sys

# the estimate codes the seed maps, in the order added
CODES = (u"CE", u"CF")
NOTHING = u"nothing to add: CE and CF are mapped"
SEED = u"nothing to add: it reads the seed map, which maps CE and CF"
DELIMITED = u"nothing added: a delimited profile maps codes on its own Code maps"


def _seed_rows(profile):
    """The seed's rows for CE and CF in the profile's format; None for a
    format with no seed qualifier map (a delimited profile)."""
    from senaite.pfas import edd_profiles
    seed = getattr(edd_profiles.format_of(profile), "QUALIFIER_MAP", None)
    if seed is None:
        return None
    return [copy.deepcopy(r) for r in seed if r["our_qualifier"] in CODES]


def missing_rows(profile):
    """The seed's rows for CE and CF a saved profile's own qualifier map
    has no row for; [] for a profile that reads the seed map or whose
    format keeps its own code maps (a delimited profile)."""
    profile = profile or {}
    seed = _seed_rows(profile)
    if seed is None or profile.get("qualifier_map") is None:
        return []
    present = set(r.get("our_qualifier") for r in profile["qualifier_map"] or [])
    return [r for r in seed if r["our_qualifier"] not in present]


def _said(profile, rows):
    if rows:
        return u"adds " + u", ".join(u"%s as %s" % (r["our_qualifier"], r["code"]) for r in rows)
    if _seed_rows(profile) is None:
        return DELIMITED
    if (profile or {}).get("qualifier_map") is None:
        return SEED
    return NOTHING


def changed(report):
    """The profile ids a run's report adds rows to."""
    return [pid for pid, said in report if said.startswith(u"adds ")]


def run(portal, dry_run=False, store=None):
    """Add the missing rows through the store's save. Returns [(profile id,
    what it changes or why nothing)] for every saved profile; a dry run
    returns the same and writes nothing."""
    if store is None:
        from senaite.pfas import edd_store as store
    report = []
    for pid, profile in sorted(store.saved_edd_profiles(portal).items()):
        rows = missing_rows(profile)
        said = _said(profile, rows)
        print("  %-20s %s" % (pid, said))
        if rows and not dry_run:
            profile = copy.deepcopy(profile)
            profile["qualifier_map"] = list(profile["qualifier_map"]) + rows
            store.save_edd_profile(portal, pid, profile)
        report.append((pid, said))
    return report


def main(app, dry_run):
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.users import UnrestrictedUser
    portal = [o for o in app.objectValues("Plone Site")][0]
    newSecurityManager(None, UnrestrictedUser("admin", "", ["Manager"], []))
    print("Mapping the estimate codes CE and CF%s" % (" (dry run)" if dry_run else ""))
    ids = changed(run(portal, dry_run=dry_run))
    if not ids:
        print("Nothing to do.")
        transaction.abort()
    elif dry_run:
        print("Dry run: nothing written (%d to change)." % len(ids))
        transaction.abort()
    else:
        transaction.commit()
        print("Committed: %s" % ", ".join(ids))


if "app" in globals():
    main(globals()["app"], "--dry-run" in sys.argv)      # noqa: F821  (bin/instance run)
