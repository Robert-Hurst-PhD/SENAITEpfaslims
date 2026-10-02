"""Load a pure module from the SENAITE add-on into the worker, so a rule or
schema lives once (calibration_levels, qc_schema; docs/REUSE_REVIEW.md U6).

The worker mounts the add-on read-only at /app/senaite_pfas; in a checkout
the file sits under src/senaite/pfas. Only modules with no Zope imports can
be loaded this way.
"""
from __future__ import annotations

import importlib.util
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE: dict = {}


def load(name: str):
    """The add-on module `name` (e.g. "qc_schema"), loaded once."""
    if name in _CACHE:
        return _CACHE[name]
    try:
        mod = importlib.import_module("senaite.pfas." + name)
    except ImportError:
        for path in (os.environ.get("PFAS_ADDON_DIR") and
                     os.path.join(os.environ["PFAS_ADDON_DIR"], name + ".py"),
                     os.path.join("/app/senaite_pfas", name + ".py"),
                     os.path.join(_HERE, "src", "senaite", "pfas", name + ".py")):
            if path and os.path.exists(path):
                spec = importlib.util.spec_from_file_location("senaite_pfas_" + name, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                break
        else:
            raise ImportError("add-on module %s.py not found (set PFAS_ADDON_DIR)" % name)
    _CACHE[name] = mod
    return mod
