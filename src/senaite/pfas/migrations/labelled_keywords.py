# -*- coding: utf-8 -*-
"""A labelled standard's keyword is its label.

The library's labelled standards were keyed by supplier codes (M2PFDA,
MD3NMeFOSAA); they are keyed by their label now (13C2-PFDA, D3-NMeFOSAA).
analyte_reference.LABELLED_KEYWORD_RENAMES is the one map.

Two idempotent steps, both run on every start (the profile re-runs each
restart):

  rename_services(folder)   core AnalysisServices: keyword, and an analyte's
                            pfas_quant_surrogate. Runs BEFORE the seeding
                            loop: seeding keys on the keyword and would
                            otherwise create a second service beside the old
                            one (setuphandlers._get_or_create).
  rename_profiles(portal)   every method profile through the store
                            (raw_profile / save_profile: change history and
                            the worker's export follow). Whole values and
                            dict keys only -- never a substring.

No analysis carried a labelled keyword when this was written, so no result moves. Python 2.7.
"""
from __future__ import absolute_import

import logging

from senaite.pfas.analyte_reference import LABELLED_KEYWORD_RENAMES

logger = logging.getLogger("senaite.pfas")

try:
    _STR = basestring              # noqa: F821  (Py2.7)
except NameError:                  # tests under Python 3
    _STR = str


def rename_value(value, renames=None):
    """`value` with every whole old keyword (dict key, string, list item)
    replaced; (new value, number of replacements). Pure."""
    renames = LABELLED_KEYWORD_RENAMES if renames is None else renames
    count = [0]

    def walk(v):
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                nk = renames.get(k, k) if isinstance(k, _STR) else k
                if nk != k:
                    count[0] += 1
                out[nk] = walk(x)
            return out
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, _STR) and v in renames:
            count[0] += 1
            return type(v)(renames[v])
        return v
    return walk(value), count[0]


def rename_services(folder):
    """Rename the core services in place; returns the number changed."""
    services = [o for o in folder.objectValues()
                if getattr(o, "portal_type", "") == "AnalysisService"]
    taken = set(o.getKeyword() for o in services)
    changed = 0
    for o in services:
        mine = 0
        old = o.getKeyword()
        new = LABELLED_KEYWORD_RENAMES.get(old)
        if new and new not in taken:
            o.setKeyword(new)
            taken.discard(old)
            taken.add(new)
            mine += 1
        qf = o.getField("pfas_quant_surrogate")
        if qf is not None:
            q = qf.get(o) or ""
            if q in LABELLED_KEYWORD_RENAMES:
                qf.set(o, LABELLED_KEYWORD_RENAMES[q])
                mine += 1
        if mine:
            o.reindexObject()
            changed += mine
    if changed:
        logger.info("labelled keywords: %d service field(s) renamed", changed)
    return changed


def rename_profiles(portal):
    """Rewrite every method profile that still names an old keyword."""
    from senaite.pfas.method_profile_store import raw_profile, save_profile
    folder = portal.get("pfas_method_profiles")
    if folder is None:
        return 0
    done = 0
    for method_id in folder.objectIds():
        data = raw_profile(portal, method_id)
        new, n = rename_value(data)
        if n:
            save_profile(portal, method_id, new)
            logger.info("labelled keywords: %s profile, %d renamed", method_id, n)
            done += 1
    return done
