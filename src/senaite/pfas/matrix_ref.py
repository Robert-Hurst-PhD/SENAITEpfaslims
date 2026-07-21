# -*- coding: utf-8 -*-
"""
Matrix ↔ core SampleType resolver — the single join between PFAS matrix
references (currently stored as title strings, e.g. "Eggs", "Meat / Muscle")
and the canonical core SENAITE ``SampleType`` object.

Why this exists (audit D4): profiles reference matrices by *title string* in
``supported_matrices`` / ``analyte_matrix_inclusion`` / ``egad_sample_type``.
A rename of the core SampleType orphans those references (violates §3 rule 4 —
referential integrity). This module is the additive first step toward keying
matrices by SampleType UID: every consumer can resolve a title *or* UID to the
live core object through one place, and callers can ask "what references this
SampleType?" before a rename/delete.

Backward-compatible by design: accepts a title OR a uid, returns whatever it can
resolve, and never raises on a miss (returns Nones) so existing string-based
flows keep working while the migration proceeds.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

import six

logger = logging.getLogger("senaite.pfas.matrix_ref")

_SETUP_CATALOG = "senaite_catalog_setup"


def _catalog(portal):
    from Products.CMFCore.utils import getToolByName
    return getToolByName(portal, _SETUP_CATALOG)


def resolve(portal, ref):
    """Resolve a matrix reference to the core SampleType.

    :param ref: a SampleType title ("Eggs"), a UID, or a SampleType object.
    :returns: dict {obj, uid, title} — any field may be None if unresolved.
    """
    out = {"obj": None, "uid": None, "title": None}
    if ref is None or ref == "":
        return out

    # already an object?
    if hasattr(ref, "portal_type") and getattr(ref, "portal_type", "") == "SampleType":
        out["obj"] = ref
        try:
            out["uid"] = ref.UID()
            out["title"] = ref.Title()
        except Exception:
            pass
        return out

    cat = _catalog(portal)
    ref_s = ref if isinstance(ref, six.string_types) else str(ref)

    # try UID first (32-hex), then Title
    brains = []
    if len(ref_s) == 32 and all(c in "0123456789abcdef" for c in ref_s.lower()):
        brains = cat(portal_type="SampleType", UID=ref_s)
    if not brains:
        brains = cat(portal_type="SampleType", Title=ref_s)
    if not brains:
        return out

    b = brains[0]
    out["uid"] = getattr(b, "UID", None) if not callable(getattr(b, "UID", None)) else b.UID
    try:
        obj = b.getObject()
        out["obj"] = obj
        out["uid"] = obj.UID()
        out["title"] = obj.Title()
    except Exception:
        out["title"] = getattr(b, "Title", None)
    return out


def title_to_uid(portal, title):
    """Return the SampleType UID for a matrix title, or None."""
    return resolve(portal, title)["uid"]


def uid_to_title(portal, uid):
    """Return the SampleType title for a UID, or None."""
    return resolve(portal, uid)["title"]


def all_matrices(portal):
    """Ordered [{uid, title}] of every core SampleType — the canonical matrix
    list (use instead of hardcoded matrix strings where possible)."""
    cat = _catalog(portal)
    out = []
    for b in cat(portal_type="SampleType", sort_on="sortable_title"):
        try:
            obj = b.getObject()
            out.append({"uid": obj.UID(), "title": obj.Title()})
        except Exception:
            continue
    return out


def find_profiles_referencing(portal, sampletype_ref):
    """Referential integrity (§3 rule 4): list method profiles that reference a
    given SampleType (by title or uid) in their supported_matrices /
    analyte_matrix_inclusion. Call before renaming/deleting a SampleType so the
    orphaning is surfaced, never silent.

    :returns: [{method_id, matched_on}] — matched_on is 'title' or 'uid'.
    """
    info = resolve(portal, sampletype_ref)
    title, uid = info["title"], info["uid"]
    hits = []
    try:
        from senaite.pfas.method_profile_store import list_method_ids, get_profile
    except Exception:
        return hits
    for mid in list_method_ids(portal):
        try:
            prof = get_profile(portal, mid)
        except Exception:
            continue
        sm = prof.get("supported_matrices", []) or []
        inc = prof.get("analyte_matrix_inclusion", {}) or {}
        matrices = set()
        for m in sm:
            if isinstance(m, six.string_types):
                matrices.add(m)
            elif isinstance(m, dict):
                matrices.add(m.get("title") or m.get("uid"))
        for _kw, colmap in inc.items():
            if isinstance(colmap, dict):
                matrices.update(colmap.keys())
        if title and title in matrices:
            hits.append({"method_id": mid, "matched_on": "title"})
        elif uid and uid in matrices:
            hits.append({"method_id": mid, "matched_on": "uid"})
    return hits
