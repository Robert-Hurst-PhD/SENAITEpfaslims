# -*- coding: utf-8 -*-
"""
Single source for QC-type DISPLAY names.

The editable names live on SENAITE-core Reference Definitions (Setup ->
Reference Definitions), each tagged [QC:CODE] in its Description. Any UI that
shows a QC-type name resolves it here instead of a hardcoded code->name map,
so renaming a definition's Title renames it everywhere at once.

Both the stored code and the parsed tag run through normalize_qc_type(), so
casing/aliases (MxB/MXB, Dup/DUP, LCS/LFB) can never silently miss.

Python 2.7 compatible.
"""
from __future__ import absolute_import

import logging
import re

from senaite.pfas.qc.qc_types import normalize_qc_type

logger = logging.getLogger("senaite.pfas.qc_labels")

_QC_TAG_RE = re.compile(r"\[QC:\s*([A-Za-z0-9_]+)\s*\]")


def get_qc_label_map(portal):
    """Return {canonical_code: editable_display_name} from the tagged
    Reference Definitions. Empty dict if the setup folder is unreachable."""
    out = {}
    try:
        folder = portal.bika_setup.bika_referencedefinitions
    except Exception as exc:
        logger.warning("qc label map: no reference definitions folder: %s", exc)
        return out
    for d in folder.objectValues():
        try:
            match = _QC_TAG_RE.search(d.Description() or "")
            if match:
                out[normalize_qc_type(match.group(1))] = d.Title()
        except Exception:
            continue
    return out


def qc_label(portal, code, default=None, label_map=None):
    """Editable display name for one qc_type *code*.

    Falls back to *default* (or the raw code when default is None) if no
    tagged definition matches. Pass a prebuilt *label_map* to avoid rescanning
    when resolving many codes in a loop.
    """
    if not code:
        return code
    if label_map is None:
        label_map = get_qc_label_map(portal)
    label = label_map.get(normalize_qc_type(code))
    if label:
        return label
    return code if default is None else default
