"""
Loader for the canonical instrument-column vocabulary.

The vocabulary itself lives in the add-on, at
``src/senaite/pfas/instrument_columns.py``, because the add-on owns the UI that
edits mappings (CLAUDE.md §1.1) and because Zope can import it directly —
``/addon/src`` is on the Zope path, ``/addon`` is not.

This module is the Python-3 worker's door to that same file. It does NOT hold a
second copy: keeping two lists in sync is precisely the defect this replaces
(Import Studio's purpose list had silently become a subset of the importer's
column map, so ``Reporting Limit`` and ``Expected Ion Ratios`` were unmappable).

Resolution order:
  1. a normal import, if the add-on happens to be on sys.path;
  2. ``PFAS_INSTRUMENT_COLUMNS`` — explicit override for odd deployments;
  3. the bind-mount the worker container gets (see docker-compose.yml);
  4. the in-repo path, for running the pipeline outside Docker.
"""
from __future__ import annotations

import os

_CANDIDATES = [
    os.environ.get("PFAS_INSTRUMENT_COLUMNS"),
    "/app/senaite_pfas/instrument_columns.py",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "src", "senaite", "pfas", "instrument_columns.py"),
]


def _load():
    try:
        from senaite.pfas import instrument_columns  # noqa: F401
        return instrument_columns
    except ImportError:
        pass

    import importlib.util
    for path in _CANDIDATES:
        if not path or not os.path.exists(path):
            continue
        spec = importlib.util.spec_from_file_location(
            "senaite_pfas_instrument_columns", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    raise ImportError(
        "Canonical instrument-column vocabulary not found. Looked at: {0}. "
        "It lives in the add-on at src/senaite/pfas/instrument_columns.py and "
        "must be reachable from the worker — check the bind mount in "
        "docker-compose.yml or set PFAS_INSTRUMENT_COLUMNS.".format(
            [c for c in _CANDIDATES if c]))


_mod = _load()

CANONICAL_FIELDS = _mod.CANONICAL_FIELDS
FIELD_LABELS = _mod.FIELD_LABELS
SINGLE_VALUED_FIELDS = _mod.SINGLE_VALUED_FIELDS
NATIVE_COLUMN_MAP = _mod.NATIVE_COLUMN_MAP
duplicate_targets = _mod.duplicate_targets
