# -*- coding: utf-8 -*-
"""Fill an EMPTY method-profile surrogate_map from the master analyte table.

EPA 537.1 shipped with `surrogate_map: []`. `qc_qualification.analytes_for_failure`
reverses that map to work out which NATIVES a surrogate failure affects, so with
no map it fell back to `[analyte]` — the labelled compound. A certificate would
then have named `13C4-PFHpA` as the affected analyte, a compound the client
never ordered and never sees, instead of PFHpA.

Which labelled compound quantifies a native is a property of the ANALYTE, not
of the method, and it is already recorded once in
`analyte_reference.NATIVE_ANALYTES`. The FDA and 1633A profiles carried
hand-maintained copies; both were verified identical — same entries, same order
— to `derive_surrogate_map()` before this migration was written, which is the
evidence that deriving 537.1 the same way applies an existing validated
relation rather than inventing a regulatory value (CLAUDE.md §8).

ONLY EMPTY MAPS ARE FILLED. A profile whose map has any entry is left alone,
because the Method Profile editor lets a lab set it and their edit outranks a
default. Run it twice and the second run reports nothing to do.

Not migrated, deliberately: `surrogate_is_chain` is empty on BOTH EPA methods,
and so is the `surrogate_is` it would be derived from. `INTERNAL_STANDARDS`
carries no quantitation column — only a prose comment that FDA's surrogates
quantify against M4PFOA per FDA Table 9-1. Asserting an injection IS for the
EPA methods would be fabricating a regulatory value; EPA 537.1 in particular
quantifies by isotope dilution against the labelled analog rather than against
one shared injection standard. That stays open until a lab enters it from its
method copy.

    bin/instance -O senaite run \
        src/senaite/pfas/migrations/backfill_surrogate_maps.py
"""
from __future__ import absolute_import

import transaction
from AccessControl.SecurityManagement import newSecurityManager
from AccessControl.users import UnrestrictedUser


def backfill(portal, dry_run=False):
    """Fill empty surrogate maps. Returns a list of (method_id, n_added)."""
    from senaite.pfas.analyte_reference import derive_surrogate_map
    from senaite.pfas.method_profile_store import (get_profile, save_profile,
                                                   DEFAULT_PROFILES)
    changed = []
    for method_id in sorted(DEFAULT_PROFILES):
        profile = get_profile(portal, method_id) or {}
        existing = profile.get("surrogate_map") or []
        if existing:
            print("  %-11s %d entries already - left alone"
                  % (method_id, len(existing)))
            continue
        panel = profile.get("master_analyte_set") or []
        derived = derive_surrogate_map(panel)
        if not derived:
            print("  %-11s EMPTY and nothing derivable from a %d-analyte panel"
                  % (method_id, len(panel)))
            continue
        print("  %-11s EMPTY -> %d entries derived from %d analytes"
              % (method_id, len(derived), len(panel)))
        for entry in derived:
            print("       %-12s -> %s" % (entry["analyte"], entry["surrogate_is"]))
        if not dry_run:
            profile["surrogate_map"] = derived
            save_profile(portal, method_id, profile)
        changed.append((method_id, len(derived)))
    return changed


def main(app):
    portal = [o for o in app.objectValues("Plone Site")][0]
    newSecurityManager(None, UnrestrictedUser("admin", "", ["Manager"], []))
    print("Backfilling empty surrogate maps")
    changed = backfill(portal)
    if changed:
        transaction.commit()
        print("Committed: %s" % ", ".join(
            "%s(+%d)" % (m, n) for m, n in changed))
    else:
        print("Nothing to do.")


if "app" in globals():
    main(globals()["app"])            # noqa: F821  (bin/instance run)
