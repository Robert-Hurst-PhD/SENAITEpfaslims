# -*- coding: utf-8 -*-
"""A partial restore of one method's whole configuration from a backup. The
bundle (tools/backup/method_bundle.py, decrypted by a key holder) holds the
method's profile, its logbook definitions, its code in
each EDD profile and its specifications in each project, as they were at the
backup.

The site admin sees the before/after first (plan); applied with a reason,
each part that differs goes through its own tracked saver -- the method
profile, the logbook definition, the EDD profile, the project -- so each is a
Configuration History entry, all noted "restored from backup <point> (<time>):
<reason>". A logbook definition made since the backup is left (logbooks may
hold entries); an EDD code or project specification added since is removed.
A bundle is applied once.

    bundle_id(bundle) / check_bundle(bundle)  -> the bundle, or ValueError
    plan(bundle, current)                     -> [{"part", "key", "changes"}]
    apply(bundle, current, reason, who, savers, done) -> {"parts", "at"}
    current_of(portal, method_id, bundle) / zope_savers(portal) / applied(portal)

`savers`: note(text); profile(method_id, value); logbook_def(key, value);
edd_method_codes(key, method_id, value); project_specs(key, method_id, value).
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import hashlib
import json

from senaite.pfas.config_history import diff, now
from senaite.pfas import qc_consolidation

APPLIED_KEY = "senaite.pfas.method_restores"
FIELDS = ("method_id", "point", "taken_at", "profile", "logbook_defs",
          "edd_method_codes", "project_specs")
PARTS = ("logbook_defs", "edd_method_codes", "project_specs")
_PART_NAME = {"logbook_defs": "logbook_def", "edd_method_codes": "edd_method_codes",
              "project_specs": "project_specs"}


def bundle_id(bundle):
    body = dict((k, v) for k, v in bundle.items() if k != "bundle_id")
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def check_bundle(bundle):
    if not isinstance(bundle, dict) or any(k not in bundle for k in FIELDS + ("bundle_id",)):
        raise ValueError(u"This is not a method bundle from the backup tool.")
    if bundle_id(bundle) != bundle["bundle_id"]:
        raise ValueError(u"The bundle was changed since it was made: not applied.")
    return bundle


def _as_restored(bundle, part, value):
    """A part's value as the restore writes it. A project's specifications
    backed up before each tier listed its own matrices take the bundle's
    one Tier 1 list into each "tight" tier they add or change
    (qc_consolidation.patch_tiers_own_matrices): the profile's save drops
    that list, and a project tier must not then apply nowhere. The bundle
    is left as it was made."""
    if part != "project_specs" or not isinstance(value, dict):
        return value
    value = copy.deepcopy(value)
    qc_consolidation.patch_tiers_own_matrices(value, (bundle.get("profile") or {}).get("tight_matrices"))
    return value


def plan(bundle, current):
    out = []
    changes = diff(current.get("profile") or {}, bundle.get("profile") or {})
    if changes:
        out.append({"part": "profile", "key": bundle["method_id"], "changes": changes})
    for part in PARTS:
        held = current.get(part) or {}
        for key, value in sorted((bundle.get(part) or {}).items()):
            value = _as_restored(bundle, part, value)
            ch = diff(held.get(key), value)
            if ch:
                out.append({"part": _PART_NAME[part], "key": key, "changes": ch, "value": value})
    return out


def note_for(bundle, reason):
    return u"restored from backup %s (%s): %s" % (bundle.get("point"), bundle.get("taken_at"),
                                                   (reason or u"").strip())


def apply(bundle, current, reason, who, savers, done):
    if not (reason or u"").strip():
        raise ValueError(u"Give the reason for the restore.")
    if bundle["bundle_id"] in done:
        raise ValueError(u"This bundle was already applied (%s by %s)." % (
            done[bundle["bundle_id"]].get("at"), done[bundle["bundle_id"]].get("who")))
    parts = plan(bundle, current)
    savers.note(note_for(bundle, reason))
    mid = bundle["method_id"]
    for p in parts:
        if p["part"] == "profile":
            savers.profile(mid, bundle["profile"])
        elif p["part"] == "logbook_def":
            savers.logbook_def(p["key"], p["value"])
        elif p["part"] == "edd_method_codes":
            savers.edd_method_codes(p["key"], mid, p["value"])
        else:
            savers.project_specs(p["key"], mid, p["value"])
    at = now()
    done[bundle["bundle_id"]] = {"at": at, "who": who, "method": mid, "point": bundle.get("point"),
                                 "reason": reason.strip(), "parts": len(parts)}
    return {"parts": len(parts), "at": at}


# ── Zope: what is there now, and the stores' own savers ─────────────────────

def current_of(portal, method_id, bundle):
    """The method's configuration now, read as the bundle was made."""
    from senaite.pfas import edd_store, project_specs as ps
    from senaite.pfas.browser import prep_logbooks as pl
    from senaite.pfas.method_profile_store import raw_profile
    profile = raw_profile(portal, method_id)
    folder = pl._get_folder(portal)
    defs = dict((k, pl._obj_to_dict(folder[k])) for k in (bundle.get("logbook_defs") or {}) if k in folder)
    edd = edd_store.get_edd_profiles(portal)
    codes = dict((pid, (edd[pid].get("method_codes") or {}).get(method_id))
                 for pid in (bundle.get("edd_method_codes") or {}) if pid in edd)
    specs = {}
    for pid in bundle.get("project_specs") or {}:
        proj = ps.project_by_id(portal, pid)
        if proj is not None:
            specs[pid] = ps.get_specs(proj).get(method_id)
    return {"profile": profile, "logbook_defs": defs, "edd_method_codes": codes, "project_specs": specs}


class zope_savers(object):
    """Each part through its store's tracked saver."""

    def __init__(self, portal):
        self.portal = portal

    def note(self, text):
        from senaite.pfas import config_history
        config_history.set_note(text)

    def profile(self, method_id, value):
        from senaite.pfas.method_profile_store import save_profile, refresh_analyte_sets
        save_profile(self.portal, method_id, value)
        # the panel is the cache of the services' Method links, not the bundle's
        refresh_analyte_sets(self.portal, [method_id])

    def logbook_def(self, key, value):
        from senaite.pfas.browser import prep_logbooks as pl
        pl._save(self.portal, dict(value, uid=key))

    def edd_method_codes(self, key, method_id, value):
        from senaite.pfas import edd_store
        prof = edd_store.get_profile(self.portal, key)
        codes = dict(prof.get("method_codes") or {})
        if value is None:
            codes.pop(method_id, None)
        else:
            codes[method_id] = value
        prof["method_codes"] = codes
        edd_store.save_edd_profile(self.portal, key, prof)

    def project_specs(self, key, method_id, value):
        from senaite.pfas import project_specs as ps
        proj = ps.project_by_id(self.portal, key)
        if proj is None:
            return
        specs = dict(ps.get_specs(proj))
        if value is None:
            specs.pop(method_id, None)
        else:
            specs[method_id] = value
        ps.save_for_project(self.portal, key, specs)


def applied(portal):
    """{bundle id: {"at", "who", "method", "point", "reason", "parts"}}, a
    persistent record (the same dict apply() adds to)."""
    from persistent.mapping import PersistentMapping
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    if APPLIED_KEY not in ann:
        ann[APPLIED_KEY] = PersistentMapping()
    return ann[APPLIED_KEY]
