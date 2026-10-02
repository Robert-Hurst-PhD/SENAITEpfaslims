# -*- coding: utf-8 -*-
"""Which analytes in a method have NO labelled standard of their own
(DECISIONS 2026-10-02, consolidation P4).

An analyte has its own labelled standard when the method links it (its
surrogate map, owned per method since GAPS §54) to its own isotopically
labelled analog. Any other analyte -- linked to another compound's labelled
standard, or not linked at all -- has none, and is judged on the method's
"no labelled standard" tier (FDA: 40-140 %, RSD <= 30).

This was stored three times -- a column of the global analyte table, FDA's
per_analyte checkbox, and implicitly the links -- and the pipeline read the
global column, so changing a link in one method did not move the analyte.
Derived from the links, all three today agree exactly (tests pin it).

    no_labelled_standard(profile, analog_map) -> frozenset of keywords

`analog_map` = {labelled keyword: native keyword}
(analyte_reference.get_labeled_analog_map()). Pure, no imports: the worker
loads this file from the add-on (pfas_pipeline.addon). Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals


def _links(profile):
    sm = (profile or {}).get("surrogate_map") or []
    if isinstance(sm, dict):
        return dict(sm)
    return dict((r.get("analyte"), r.get("surrogate_is")) for r in sm
                if isinstance(r, dict) and r.get("analyte"))


def no_labelled_standard(profile, analog_map):
    """Keywords in the method's panel whose linked standard is not their own
    labelled analog (or that have no link)."""
    own = {}
    for labelled, native in (analog_map or {}).items():
        own.setdefault(native, set()).add(labelled)
    links = _links(profile)
    return frozenset(kw for kw in (profile or {}).get("master_analyte_set") or []
                     if links.get(kw) not in own.get(kw, ()))
