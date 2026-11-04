# -*- coding: utf-8 -*-
"""A method's analyte panel (the profile's master_analyte_set) is a CACHE
of the services' Method links: the analyte services that carry the core
Method. It is rewritten from the links whenever a service or the profile
is saved (method_profile_store.refresh_analyte_sets). An analyte whose
service no longer carries the method leaves the panel with every row it
owned (compound_references.remove), recorded in configuration history.

Each method keeps its own order, its published table's; a newly linked
service follows the panel by its core Sort Key among the new ones, ties by
keyword, a service with no key last. A project's extra analytes stay after
the method's. Pure: Python 2.7 and 3, no Zope imports.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import compound_references, isomers

EXTRAS_KEY = "project_extra_analytes"


def ordered(linked):
    """The keywords of (keyword, sort_key) pairs in Sort Key order, ties by
    keyword, a missing key last."""
    def key(item):
        kw, sk = item
        return (sk is None, sk if sk is not None else 0.0, kw)
    return [kw for kw, _sk in sorted(linked, key=key)]


def refresh(profile, linked):
    """Bring the panel to the links. `linked`: (keyword, sort_key) pairs of
    the analyte services that carry this method. Returns (dropped, added):
    dropped = [(keyword, [where its rows were])], added = [keywords]. The
    panel's own order is kept; new members follow it in Sort Key order; a
    project's extras come last."""
    # an isomer peak (lr-/br-) is reviewed, never reported on its own
    linked_kws = [kw for kw in ordered(linked) if not isomers.is_peak_name(kw)]
    members = set(linked_kws)
    extras = [kw for kw in profile.get(EXTRAS_KEY) or [] if kw]
    stored = [kw for kw in profile.get("master_analyte_set") or [] if kw]
    dropped = []
    for kw in stored:
        if kw not in members and kw not in extras:
            dropped.append((kw, compound_references.remove(profile, kw)))
    kept = [kw for kw in stored if kw in members]
    added = [kw for kw in linked_kws if kw not in kept]
    panel = kept + added + [kw for kw in extras if kw not in kept and kw not in added]
    if panel != stored or dropped:
        profile["master_analyte_set"] = panel
    return dropped, added


def label(dropped, added):
    """The configuration-history label of a refresh that changed the panel."""
    parts = ["+%s" % kw for kw in added] + ["-%s" % kw for kw, _where in dropped]
    return "Analyte links: " + ", ".join(parts)
