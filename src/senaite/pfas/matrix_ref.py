# -*- coding: utf-8 -*-
"""
Matrix ↔ core SampleType resolver — the single join between PFAS matrix
references (stored as title strings, e.g. "Eggs", "Meat / Muscle") and the
canonical core SENAITE ``SampleType`` object.

Profiles reference matrices by title in ``supported_matrices`` /
``analyte_matrix_inclusion`` / the EDD sample-type code, so a rename of the
core SampleType would orphan them (§3 rule 4, referential integrity). Every
consumer resolves a title *or* UID to the live core object here, and callers
ask "what references this SampleType?" before a rename/delete.

Accepts a title OR a uid, returns whatever it can resolve, and never raises
on a miss (returns Nones).

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

    if hasattr(ref, "portal_type") and getattr(ref, "portal_type", "") == "SampleType":
        out["obj"] = ref
        out["uid"] = ref.UID()
        out["title"] = ref.Title()
        return out

    cat = _catalog(portal)
    ref_s = ref if isinstance(ref, six.string_types) else str(ref)

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


