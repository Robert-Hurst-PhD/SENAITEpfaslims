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


def key_analyte_names() -> set:
    """Display names of the regulatory priority analytes (tier 1)."""
    fn = getattr(_mod, "get_key_analyte_names", None)
    return set(fn()) if fn else set()


def _labelled_by_role(role: str) -> set:
    """Display names of labelled compounds with the given pfas_role.

    analyte_reference.INTERNAL_STANDARDS rows are
    (keyword, display_name, quantifies, role) — the role has been recorded all
    along, and SENAITE carries it on the AnalysisService too (13C4-PFOA is
    injection_is, the other 26 are surrogate). The pipeline kept a flat list
    with no roles and so treated them identically.
    """
    rows = getattr(_mod, "INTERNAL_STANDARDS", None) or []
    out = set()
    for row in rows:
        if len(row) > 3 and (row[3] or "").strip().lower() == role:
            out.add(row[1])
    return out


def injection_is_names() -> set:
    """The injection internal standard(s): added at reconstitution, AFTER any
    dilution, so their response does not scale with the dilution factor."""
    return _labelled_by_role("injection_is")


def surrogate_names() -> set:
    """Extracted internal standards / surrogates: added BEFORE extraction, so
    they are diluted along with the sample."""
    return _labelled_by_role("surrogate")


def labelled_display_name(keyword: str) -> str:
    """Display name of a labelled compound from its keyword ("13C3-PFBA" ->
    "13C3-PFBA"). The instrument exports display names and the method profile's
    surrogate_map stores keywords, so anything crossing between the two needs
    this direction; NAME_TO_KEYWORD only goes the other way."""
    rows = getattr(_mod, "INTERNAL_STANDARDS", None) or []
    for row in rows:
        if row[0] == keyword:
            return row[1]
    return keyword


def labeled_analog_map() -> dict:
    """{labelled_compound_keyword: native_keyword} from the reference table."""
    fn = getattr(_mod, "get_labeled_analog_map", None)
    return dict(fn()) if fn else {}


def native_keyword_for(published_name: str) -> str:
    """A native analyte's keyword from a published method's spelling of it
    (EPA's "HFPO-DA" -> this table's "GenX"). See
    analyte_reference.NATIVE_NAME_SYNONYMS for why those three exist."""
    fn = getattr(_mod, "native_keyword_for", None)
    return fn(published_name) if fn else published_name


def no_labelled_names_for(profile_data: dict) -> set:
    """Analytes of ONE method with no labelled standard of their own, derived
    from that method's surrogate links (senaite.pfas.labelled_coverage;
    consolidation P4) -- keywords and display names both, since the engine
    compares instrument display names."""
    from .addon import load
    kws = load("labelled_coverage").no_labelled_standard(profile_data, labeled_analog_map())
    display = dict((row[0], row[1]) for row in (getattr(_mod, "NATIVE_ANALYTES", None) or []))
    return set(kws) | set(display[k] for k in kws if k in display)


def canonical_labelled_name(name: str) -> str:
    """The library's display name for a labelled standard exported under
    another spelling ("13C3 GenX (HFPO-DA)", "D5-N-EtFOSAA", a retired
    supplier code); any other name unchanged. The checks find a labelled
    standard's rows by its display name, so a variant spelling was never
    judged at all."""
    kw = NAME_TO_KEYWORD.get(name or "")
    labelled = set(row[0] for row in (getattr(_mod, "INTERNAL_STANDARDS", None) or []))
    if kw and kw in labelled:
        return labelled_display_name(kw)
    return name


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
