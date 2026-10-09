# -*- coding: utf-8 -*-
"""Core Sample Types show the holding time ("use the hold
times and clear the seed values").

The method profile owns holding times (Matrices & Units). Core's Sample Type
"Retention Period" carried values the installer seeded (14 / 28 / 60 days,
typed like holding times but never read by the gate). Core 2.6 only shows the
field (the Sample Types list, the Add Sample form) -- it marks no sample
expired by it -- so it now shows the holding time:

    the shortest holding time any method sets for that matrix (the strictest
    one a sample of that type can be held to); a Sample Type no method gives
    one is cleared (core then falls back to its default sample lifetime).

Synced on every method profile save and once by
migrations/core_integration_cleanup.py.

    holding_days_by_sampletype(profiles)  pure: {Sample Type uid: days|None}
    sync(portal)                          write; returns [line]
"""
from __future__ import absolute_import, unicode_literals


def holding_days_by_sampletype(profiles):
    """profiles: [profile dict]. Each matrix's UID from matrix_uid_map, its
    days from holding_times; the shortest set value wins."""
    out = {}
    for p in profiles:
        uids = p.get("matrix_uid_map") or {}
        for matrix, days in (p.get("holding_times") or {}).items():
            uid = uids.get(matrix)
            if not uid:
                continue
            try:
                d = float(days) if days not in (None, u"", "") else None
            except (TypeError, ValueError):
                d = None
            prev = out.get(uid)
            out[uid] = d if prev is None else (prev if d is None else min(prev, d))
        for matrix, uid in uids.items():
            out.setdefault(uid, None)
    return out


def sync(portal):
    from bika.lims import api
    from senaite.pfas.method_profile_store import list_method_ids, raw_profile
    days = holding_days_by_sampletype([raw_profile(portal, m) or {} for m in list_method_ids(portal)])
    try:
        from senaite.core.content.sampletype import default_retention_period
        from senaite.core.api import dtime
        default = dtime.timedelta_to_dict(default_retention_period())
    except Exception:                                       # noqa: BLE001
        default = {}
    key = lambda d: tuple((d or {}).get(k) or 0 for k in ("days", "hours", "minutes"))  # noqa: E731
    out = []
    for st in api.get_senaite_setup()["sampletypes"].objectValues():
        want = days.get(api.get_uid(st))
        current = st.getRetentionPeriod() or {}
        if want is None:
            if key(current) != key(default):
                st.setRetentionPeriod(None)               # core's default lifetime
                st.reindexObject()
                out.append(u"%s: seeded retention cleared (no holding time set)" % st.Title())
            continue
        target = {"days": int(want), "hours": int(round((want - int(want)) * 24)), "minutes": 0}
        if key(current) != key(target):
            st.setRetentionPeriod(target)
            st.reindexObject()
            out.append(u"%s: retention = holding time %s day(s)" % (st.Title(), want))
    return out
