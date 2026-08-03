"""
Analyte naming bridge: instrument DISPLAY NAME → SENAITE KEYWORD.

Instruments export display names ("10:2 FTS", "GenX (HFPO-DA)",
"9Cl-PF3ONS"); SENAITE Analyses are keyed by keyword ("10:2FTS", "GenX",
"9ClPF3ONS"). Pushing a result under the display name matches no Analysis and
the result is dropped.

``analyte_reference.COMPOUND_NAME_TO_KEYWORD`` already holds this mapping —
it is built from the same table that seeds the AnalysisServices, so the two can
never disagree. It simply was not consulted on the push path. This module is
the Python-3 worker's door to it, loaded the same way as the canonical column
vocabulary (see canonical_columns.py for why).
"""
from __future__ import annotations

import os

_CANDIDATES = [
    os.environ.get("PFAS_ANALYTE_REFERENCE"),
    "/app/senaite_pfas/analyte_reference.py",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "src", "senaite", "pfas", "analyte_reference.py"),
]


def _load():
    try:
        from senaite.pfas import analyte_reference  # noqa: F401
        return analyte_reference
    except ImportError:
        pass
    import importlib.util
    for path in _CANDIDATES:
        if not path or not os.path.exists(path):
            continue
        spec = importlib.util.spec_from_file_location(
            "senaite_pfas_analyte_reference", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None


_mod = _load()

# display name → keyword; empty if the reference table is unreachable, in which
# case callers fall back to the name as given rather than failing the run.
NAME_TO_KEYWORD = dict(getattr(_mod, "COMPOUND_NAME_TO_KEYWORD", {}) or {})


def no_labeled_names() -> set:
    """Display names of analytes with no commercially matched labelled standard.

    This is the tier-3 (40-140%) membership. It used to be a hardcoded set in
    method_profiles._resolve_fda_tier that disagreed with this table on DONA
    and PFHpS — both in the FDA 32 panel, both judged at the stricter 65-135%
    as a result.
    """
    fn = getattr(_mod, "get_no_labeled_names", None)
    return set(fn()) if fn else set()


def key_analyte_names() -> set:
    """Display names of the regulatory priority analytes (tier 1)."""
    fn = getattr(_mod, "get_key_analyte_names", None)
    return set(fn()) if fn else set()


def keyword_for(analyte_name: str) -> str:
    """SENAITE keyword for an instrument analyte name.

    Returns the name unchanged when it is already a keyword (most analytes) or
    when the reference table does not know it — the caller then fails to match
    an Analysis and logs it, which is the same behaviour as before but for a
    genuinely unknown analyte rather than a spelling difference.
    """
    if not analyte_name:
        return analyte_name
    return NAME_TO_KEYWORD.get(analyte_name, analyte_name)
