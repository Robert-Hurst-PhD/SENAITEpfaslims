# -*- coding: utf-8 -*-
"""The methods the lab has configured, for every page that offers a choice
of method.

A method exists when it has a stored method profile (the Method Profiles
store, list_method_ids); its label is the profile's own display name. No page
keeps a list of method ids or labels of its own, so a method made in the New
Method Wizard is offered everywhere a method is chosen.

The pure helpers take ids and profiles; `choices(portal)` reads the store.
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals


class MethodUnresolved(ValueError):
    """A page needed a method and none (or an unconfigured one) was given."""


def method_label(profile, method_id):
    """The label a page shows for a method: its profile's display name."""
    return (profile or {}).get("display_name") or method_id or u""


def method_choices(ids, profiles):
    """[{"id", "label"}] for `ids`, labelled from `profiles` ({id: profile}),
    ordered by label."""
    out = [{"id": mid, "label": method_label((profiles or {}).get(mid), mid)}
           for mid in ids or [] if mid]
    return sorted(out, key=lambda m: (m["label"].lower(), m["id"]))


def resolve(method_id, ids, what=u"this page"):
    """`method_id` if it is one of the configured `ids`, else MethodUnresolved
    naming what is missing (never a stand-in method)."""
    if not method_id:
        raise MethodUnresolved(
            u"No method is set for {0}: set the batch's method first.".format(what))
    if method_id not in (ids or []):
        raise MethodUnresolved(
            u"{0} has no method profile, so {1} cannot use it: create it in "
            u"Method Profiles (or the New Method Wizard).".format(method_id, what))
    return method_id


def chosen(posted, fallback, ids, what=u"this page"):
    """The method a form names, else `fallback` (the batch's), resolved
    against the configured `ids` (MethodUnresolved when neither is one)."""
    return resolve((posted or u"").strip() or fallback, ids, what)


# ── Portal readers ───────────────────────────────────────────────────────────

def ids(portal):
    """The configured method ids, in the store's order."""
    from senaite.pfas.method_profile_store import list_method_ids
    return list(list_method_ids(portal) or [])


def choices(portal):
    """[{"id", "label"}] for every configured method."""
    from senaite.pfas.method_profile_store import raw_profile
    mids = ids(portal)
    return method_choices(mids, dict((m, raw_profile(portal, m) or {}) for m in mids))


def label(portal, method_id):
    from senaite.pfas.method_profile_store import raw_profile
    return method_label(raw_profile(portal, method_id) if method_id else {}, method_id)
