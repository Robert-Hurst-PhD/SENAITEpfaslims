# -*- coding: utf-8 -*-
"""What a logbook template is used for (one of ROLES). Asked first in
New Logbook; fixed once the template's revision 1 is issued (a record made
on it would change meaning); the Templates page's By use view groups the
templates by it -- each batch's records in their order, then what is made
ahead and used by the batch.

    role_of(defn) / scope_of(role) / issued(revisions)
    change_refused(old, new, revisions) / by_use(families)

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

ROLES = [(u"receipt", u"Sample receipt"), (u"processing", u"Sample processing"),
         (u"extraction", u"Extraction"), (u"reagent_prep", u"Reagent prep"),
         (u"standard_prep", u"Standard prep"), (u"other", u"Other batch record")]
LABEL = dict(ROLES)
_LIBRARY = (u"reagent_prep", u"standard_prep")
_BY_SLUG = {u"coc": u"receipt", u"253": u"processing", u"252": u"extraction",
            u"250": u"reagent_prep", u"251": u"standard_prep"}


def scope_of(role):
    """A prep made ahead is a library logbook; every other role is filled per batch."""
    return u"library" if role in _LIBRARY else u"batch"


def role_of(defn):
    """The template's role: its stored one, else from its slug, its scope or
    its title (a template stored without a role)."""
    d = defn or {}
    if d.get("used_for") in LABEL:
        return d["used_for"]
    slug = u"%s" % (d.get("logbook_slug") or u"")
    if slug in _BY_SLUG:
        return _BY_SLUG[slug]
    if d.get("scope") == u"library":
        return u"standard_prep"
    if u"extraction" in (d.get("title") or u"").lower():
        return u"extraction"
    return u"other"


def issued(revisions):
    """True once any revision has been made active (revision 1 issued)."""
    return any((r or {}).get("status") in (u"active", u"archived") for r in revisions or [])


def change_refused(old, new, revisions):
    return bool(old) and old != new and issued(revisions)


def by_use(families):
    """[{"label", "steps": [{"role", "label", "templates"}]}]: each batch's
    records in their order (the instrument step is the Run Builder, not a
    logbook), then what is made ahead and used by the batch."""
    def step(role, label=None):
        return {"role": role, "label": label or LABEL.get(role, role),
                "templates": [f for f in families or [] if role_of(f) == role]}
    return [{"label": u"For each batch, in order",
             "steps": [step(u"receipt"), step(u"processing"), step(u"extraction"),
                       {"role": u"instrument", "label": u"On the instrument", "templates": []}]},
            {"label": u"Made ahead, used by the batch",
             "steps": [step(u"reagent_prep"), step(u"standard_prep"), step(u"other")]}]
