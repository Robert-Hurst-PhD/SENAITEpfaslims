"""
The compound library, as the worker reads it: instrument DISPLAY NAME ->
SENAITE KEYWORD, labelled standards' names, roles and native links, key
analytes.

Instruments export display names ("10:2 FTS", "GenX (HFPO-DA)",
"9Cl-PF3ONS"); SENAITE Analyses are keyed by keyword ("10:2FTS", "GenX",
"9ClPF3ONS"). Pushing a result under the display name matches no Analysis and
the result is dropped.

The library is owned by the core Analysis Services (their PFAS tab). SENAITE
exports it beside the method profiles (compound_library.json, written with
them and whenever a service changes); this module reads ONLY that export,
through the add-on's own accessors (senaite.pfas.compound_library, loaded
like any pure add-on module), so SENAITE and the worker cannot disagree. It
is read again with the method profiles at the start of every run
(method_profiles.reload_from_profiles). No export, an export with a
problem, or a method naming a compound the library does not hold is
refused at the start of a run (library_refusal) -- never replaced by
another table; a lookup with no library raises LibraryUnavailable.
"""
from __future__ import annotations

import json
import os

from .addon import load


def _cl():
    return load("compound_library")


class LibraryUnavailable(RuntimeError):
    """No compound library has been read (or it could not be)."""


# display name -> keyword, from the export; refilled IN PLACE on every
# reload, so a caller holding this dict sees the current library
NAME_TO_KEYWORD = {}

_STATE = {"path": None, "export": None, "derived": None,
          "error": "the compound library has not been read"}


def library_path(profiles_path=None):
    """PFAS_LIBRARY_PATH, else the library file beside the method profiles."""
    env = os.environ.get("PFAS_LIBRARY_PATH")
    if env:
        return env
    base = (profiles_path or os.environ.get("PFAS_PROFILES_PATH")
            or "/data/qc/method_profiles.json")
    return os.path.join(os.path.dirname(base), _cl().FILE_NAME)


def _derive(export):
    cl = _cl()
    n2k = cl.name_to_keyword(export)
    return {
        "n2k": n2k,
        "synonyms": cl.synonyms(export),
        "labelled": cl.labelled_keywords(export),
        "labelled_names": cl.labelled_names(export),
        "native_names": cl.native_names(export),
        "analogs": cl.analog_map(export),
        "key_names": cl.key_names(export),
        "by_role": dict((r, cl.names_by_role(export, r)) for r in cl.LABELLED_ROLES),
    }


def reload_library(path=None, profiles_path=None):
    """Read the library export (PFAS_LIBRARY_PATH, else beside the method
    profiles). Returns None, or why it cannot be used."""
    path = path or library_path(profiles_path)
    export, error = None, None
    try:
        with open(path) as fh:
            export = json.load(fh)
    except (IOError, OSError):
        error = "there is no compound library export at %s" % path
    except ValueError as exc:
        error = "the compound library export %s is not readable JSON (%s)" % (path, exc)
    if error is None:
        why = _cl().unusable(export)
        if why:
            error = "the compound library export %s cannot be used: %s" % (path, why)
    NAME_TO_KEYWORD.clear()
    if error:
        _STATE.update(path=path, export=None, derived=None, error=error)
        return error
    derived = _derive(export)
    NAME_TO_KEYWORD.update(derived["n2k"])
    _STATE.update(path=path, export=export, derived=derived, error=None)
    return None


def library_error():
    """Why no library is in use, or None."""
    return _STATE["error"]


def _lib():
    if _STATE["export"] is None:
        # SENAITE may have written it since it was last read (a worker
        # started first): read the same file again, nothing else
        reload_library(_STATE["path"])
        if _STATE["export"] is None:
            raise LibraryUnavailable(_STATE["error"])
    return _STATE["derived"]


def library():
    """The library export in use (raises LibraryUnavailable without one);
    read it with senaite.pfas.compound_library's accessors."""
    _lib()
    return _STATE["export"]


def display_names() -> dict:
    """{keyword: name in instrument exports} of every compound."""
    lib = _lib()
    out = dict(lib["native_names"])
    out.update(lib["labelled_names"])
    return out


def library_refusal(method_id, profile_data):
    """Why a run of `method_id` cannot be judged with the library, as one
    message naming what is wrong, or None."""
    if _STATE["export"] is None:
        return ("The compound library cannot be read: %s. SENAITE writes it with "
                "the method profiles; restart SENAITE (or save a method profile), "
                "then run the batch again." % _STATE["error"])
    cl = _cl()
    probs = cl.problems(_STATE["export"])
    if probs:
        return ("The compound library (%s) names compounds ambiguously: %s. Correct "
                "the Analysis Services' PFAS tab, then run the batch again."
                % (_STATE["path"], "; ".join(probs)))
    missing = cl.missing(_STATE["export"], profile_data or {})
    if missing:
        return ("The compound library (%s) has no entry for %s, which the %s method "
                "profile uses. Add the Analysis Service with its PFAS role (or "
                "correct the method profile), then run the batch again."
                % (_STATE["path"], ", ".join(missing), method_id or "(no method)"))
    return None


def is_native_name(name: str) -> bool:
    """Is an instrument compound name a native analyte, as the library holds
    it (its role, by its keyword: an isomer peak's own or its alias)?"""
    if not name:
        return False
    return (keyword_for(name) or name) in _lib()["native_names"]


def key_analyte_names() -> set:
    """Display names of the natives marked key analytes by default (tier 1)."""
    return set(_lib()["key_names"])


def _labelled_by_role(role: str) -> set:
    """Display names of labelled compounds with the given pfas_role.

    The role is the service's (pfas_role): 13C4-PFOA is injection_is, the
    other labelled standards of the seed are surrogate. The pipeline kept a
    flat list with no roles and so treated them identically.
    """
    return set(_lib()["by_role"].get(role) or ())


def injection_is_names() -> set:
    """The injection internal standard(s): added at reconstitution, AFTER any
    dilution, so their response does not scale with the dilution factor."""
    return _labelled_by_role("injection_is")


def surrogate_names() -> set:
    """Extracted internal standards / surrogates: added BEFORE extraction, so
    they are diluted along with the sample."""
    return _labelled_by_role("surrogate")


def labelled_display_name(keyword: str) -> str:
    """Display name of a labelled compound from its keyword ("13C3-HFPO-DA"
    -> "13C3-GenX (HFPO-DA)"); any other name unchanged. The instrument
    exports display names and the method profile's surrogate_map stores
    keywords, so anything crossing between the two needs this direction;
    NAME_TO_KEYWORD only goes the other way."""
    return _lib()["labelled_names"].get(keyword, keyword)


def labeled_analog_map() -> dict:
    """{labelled_compound_keyword: native_keyword} from the library."""
    return dict(_lib()["analogs"])


def native_name_to_keyword() -> dict:
    """{display name: keyword} of the native analytes whose display name
    differs from their keyword."""
    return dict((name, kw) for kw, name in _lib()["native_names"].items() if name != kw)


def native_keyword_for(published_name: str) -> str:
    """A native analyte's keyword from a published method's spelling of it
    (EPA's "HFPO-DA" -> the library's "GenX"): the services' published
    names, else their export names; the name unchanged when unknown."""
    if not published_name:
        return published_name
    lib = _lib()
    if published_name in lib["synonyms"]:
        return lib["synonyms"][published_name]
    return lib["n2k"].get(published_name, published_name)


def no_labelled_names_for(profile_data: dict) -> set:
    """Analytes of ONE method with no labelled standard of their own, derived
    from that method's surrogate links (senaite.pfas.labelled_coverage;
    consolidation P4) -- keywords and display names both, since the engine
    compares instrument display names."""
    kws = load("labelled_coverage").no_labelled_standard(profile_data, labeled_analog_map())
    display = _lib()["native_names"]
    return set(kws) | set(display[k] for k in kws if k in display)


def canonical_labelled_name(name: str) -> str:
    """The library's display name for a labelled standard exported under
    another spelling ("13C3 GenX (HFPO-DA)", "D5-N-EtFOSAA", a retired
    supplier code); any other name unchanged. The checks find a labelled
    standard's rows by its display name, so a variant spelling was never
    judged at all."""
    lib = _lib()
    kw = lib["n2k"].get(name or "")
    if kw and kw in lib["labelled"]:
        return labelled_display_name(kw)
    return name


def keyword_for(analyte_name: str) -> str:
    """SENAITE keyword for an instrument analyte name.

    Returns the name unchanged when it is already a keyword (most analytes) or
    when the library does not know it -- the caller then fails to match an
    Analysis and logs it, which is the same behaviour as before but for a
    genuinely unknown analyte rather than a spelling difference.
    """
    if not analyte_name:
        return analyte_name
    return _lib()["n2k"].get(analyte_name, analyte_name)


# what SENAITE last exported, read once on import (no refusal here: a run
# reloads it and refuses at its start; a lookup without it raises)
reload_library()
