"""Load a pure module from the SENAITE add-on into the worker, so a rule or
schema lives once (calibration_levels; qc_schema).

install() makes `senaite.pfas` importable without Plone: a package whose
path is the add-on folder, its __init__ (Zope) not run. The worker, the
tests and the tools load the add-on this one way, so an add-on module
imports its neighbours as `from senaite.pfas import x` and nothing else.

The worker mounts the add-on read-only at /app/senaite_pfas; in a checkout
it sits under src/senaite/pfas (PFAS_ADDON_DIR overrides both). Only
modules with no Zope imports can be loaded this way.
"""
from __future__ import annotations

import importlib
import os
import sys
import types

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def addon_dir() -> str:
    for path in (os.environ.get("PFAS_ADDON_DIR"), "/app/senaite_pfas",
                 os.path.join(_HERE, "src", "senaite", "pfas")):
        if path and os.path.isdir(path):
            return path
    raise ImportError("the add-on folder was not found (set PFAS_ADDON_DIR)")


def install() -> None:
    """`senaite.pfas` as a package over the add-on folder; a package already
    importable (SENAITE itself, or an earlier install) is left as it is."""
    if hasattr(sys.modules.get("senaite.pfas"), "__path__"):
        return
    senaite = sys.modules.get("senaite")
    if senaite is None:
        senaite = types.ModuleType("senaite")
        senaite.__path__ = []
        sys.modules["senaite"] = senaite
    pfas = types.ModuleType("senaite.pfas")
    pfas.__path__ = [addon_dir()]
    sys.modules["senaite.pfas"] = pfas
    senaite.pfas = pfas


def load(name: str):
    """The add-on module `name` (e.g. "qc_schema" or "qc.rules")."""
    install()
    return importlib.import_module("senaite.pfas." + name)
