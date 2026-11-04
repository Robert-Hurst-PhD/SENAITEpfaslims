"""
Loader for the canonical instrument-column vocabulary.

The vocabulary itself lives in the add-on, at
``src/senaite/pfas/instrument_columns.py``, because the add-on owns the UI that
edits mappings and because Zope can import it directly —
``/addon/src`` is on the Zope path, ``/addon`` is not.

This module is the Python-3 worker's door to that same file; it holds no
second copy, so the importer and Import Studio share one list.

It is loaded through pfas_pipeline/addon.py, like every add-on module.
"""
from __future__ import annotations

from .addon import load

_mod = load("instrument_columns")

CANONICAL_FIELDS = _mod.CANONICAL_FIELDS
FIELD_LABELS = _mod.FIELD_LABELS
SINGLE_VALUED_FIELDS = _mod.SINGLE_VALUED_FIELDS
NATIVE_COLUMN_MAP = _mod.NATIVE_COLUMN_MAP
duplicate_targets = _mod.duplicate_targets
