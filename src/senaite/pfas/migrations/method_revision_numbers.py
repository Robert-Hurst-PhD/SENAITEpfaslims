# -*- coding: utf-8 -*-
"""Number the issued method revisions major.sub, and keep a snapshot of each.

A revision issued before major.sub holds only its issue number `rev`. This
gives it `major` = rev and `sub` = 0, so revision N reads N.0; every other
key it holds (its PDF's file, fingerprint, stamp and reason) stays as it is,
and its PDF is never opened. A record that already has `major` is left as
it is, so a second run changes nothing.

Those revisions kept no snapshot of their settings, only a fingerprint. One
is rebuilt where the change history allows: the method's current profile
with each of its Config History entries newer than the revision's issue put
back, newest first. It is kept only when its fingerprint equals the
revision's (either fingerprint the revision may hold, method_revisions.
fingerprints), and written as rev-NNNN.json beside the PDF; an existing
snapshot file is never overwritten. A revision it cannot rebuild keeps no
snapshot, and the next issue of that method is major ("no snapshot of the
last revision").

Dry run unless --apply is given:

    bin/instance -O senaite run \\
        src/senaite/pfas/migrations/method_revision_numbers.py
    bin/instance -O senaite run \\
        src/senaite/pfas/migrations/method_revision_numbers.py --apply

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import sys

# config_history.AT_FORMAT to the minute: the issue stamp's precision
_MINUTE = 16


def migrated(records):
    """The records with `major` = rev and `sub` = 0 where they have no
    `major`; each one a copy, nothing else changed."""
    out = []
    for r in records or []:
        r = dict(r)
        if r.get("major") is None:
            r["major"], r["sub"] = r.get("rev"), 0
        out.append(r)
    return out


def rebuilt(profile, entries, record, toggles_of):
    """The snapshot `record` was issued with, rebuilt from `profile` (the
    method's profile now) and `entries` (its method_profile Config History
    entries), or None. `toggles_of(profile)` gives a profile's rule
    switches. An entry stamped later than the issue's minute is put back;
    one in the issue's own minute may be before or after it, so the
    fingerprint is tried with and without it. Kept only when the
    fingerprint matches."""
    from senaite.pfas import config_history
    from senaite.pfas import method_revisions as mr
    at, want = record.get("issued_at") or u"", record.get("fingerprint")
    if not at or not want:
        return None

    def matches(value):
        return want in mr.fingerprints(value, toggles_of(value))

    newer = sorted([e for e in entries or []
                    if e.get("store", "method_profile") == "method_profile"
                    and u"%s" % (e.get("at") or u"") > at],
                   key=lambda e: (u"%s" % e.get("at"), u"%s" % e.get("id")), reverse=True)
    value = copy.deepcopy(profile or {})
    try:
        for e in newer:
            if (u"%s" % e.get("at"))[:_MINUTE] == at[:_MINUTE] and matches(value):
                break
            value = config_history.reverted(value, e.get("changes") or [])
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    return mr.snapshot_of(value, toggles_of(value)) if matches(value) else None


def _write(mr, method_id, rev, snap):
    """Write the rebuilt snapshot; one already on disk is kept when it is
    the same (a run stopped before its records were saved), never replaced."""
    import json
    try:
        return mr.write_snapshot(method_id, rev, snap)
    except ValueError:
        name = mr.snapshot_name(rev)
        if mr.read_snapshot(method_id, {"snapshot": name}) == json.loads(json.dumps(snap, sort_keys=True)):
            return name
        raise


def run(portal, apply=False, profiles=None, entries_of=None, toggles_of=None):
    """Number every method's revisions and rebuild the snapshots they lack.
    Returns [(method_id, rev, label, snapshot rebuilt)] for each record
    that lacked its number or its snapshot; writes only with `apply`.
    Every method is named: one with no revisions, and one whose revisions
    are all numbered and kept, say so. `profiles` {method id: profile now},
    `entries_of(method_id)` and `toggles_of(profile, method_id)` default to
    the site's; a method whose revisions outlived its profile is still
    numbered."""
    import json
    from senaite.pfas import method_revisions as mr
    data = json.loads(mr._ann(portal).get(mr.KEY) or "{}")
    if profiles is None:
        from senaite.pfas.method_profile_store import list_method_ids, raw_profile
        profiles = dict((mid, raw_profile(portal, mid) or {})
                        for mid in set(list_method_ids(portal)) | set(data))
    if entries_of is None:
        from senaite.pfas import config_history

        def entries_of(mid):
            return config_history.entries(portal, store="method_profile", key=mid, limit=10 ** 7)
    if toggles_of is None:
        from senaite.pfas.qc.rules import method_toggles as toggles_of
    found = []
    for mid in sorted(set(profiles) | set(data)):
        recs = mr.records(portal, mid)
        if not recs:
            print("  %-11s no revisions" % mid)
            continue
        if all(r.get("major") is not None and r.get("snapshot") for r in recs):
            print("  %-11s already numbered: %d revision%s" % (mid, len(recs), "" if len(recs) == 1 else "s"))
            continue
        new = migrated(recs)
        changed = new != recs
        entries = None
        for old, rec in zip(recs, new):
            if rec.get("snapshot") and old.get("major") is not None:
                continue
            snap = None
            if not rec.get("snapshot"):
                if entries is None:
                    entries = list(entries_of(mid) or [])
                snap = rebuilt(profiles.get(mid) or {}, entries, rec, lambda p: toggles_of(p, mid))
            found.append((mid, rec.get("rev"), mr.label(rec), bool(snap or rec.get("snapshot"))))
            print("  %-11s rev %s reads %s; snapshot %s" % (
                mid, rec.get("rev"), mr.label(rec),
                "kept" if rec.get("snapshot") else "rebuilt" if snap else "not rebuilt: its next issue is major"))
            if snap is not None and apply:
                rec["snapshot"] = _write(mr, mid, rec["rev"], snap)
                changed = True
        if apply and changed:
            mr.save_records(portal, mid, new)
    return found


def main(app, apply, **kw):
    """Run it on the site: a dry run aborts; an applied run commits only
    when the records changed. `kw` goes to run()."""
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.users import UnrestrictedUser
    portal = [o for o in app.objectValues(["Plone Site"])][0]
    newSecurityManager(None, UnrestrictedUser("admin", "", ["Manager"], []))
    from senaite.pfas import method_revisions as mr
    print("Numbering the method revisions major.sub%s" % ("" if apply else " (dry run)"))
    before = mr._ann(portal).get(mr.KEY)
    found = run(portal, apply=apply, **kw)
    # a revision that cannot be rebuilt is reported on every run; only a
    # run that changed the records commits
    if not apply:
        print("Dry run: nothing written (%d revisions listed). Run again with --apply." % len(found))
        transaction.abort()
    elif mr._ann(portal).get(mr.KEY) == before:
        print("Nothing to do.")
        transaction.abort()
    else:
        transaction.commit()
        print("Committed: the revision records of %s." % ", ".join(sorted(set(f[0] for f in found))))


if "app" in globals():
    main(globals()["app"], "--apply" in sys.argv)      # noqa: F821  (bin/instance run)
