# -*- coding: utf-8 -*-
"""What an instrument's software reads as its injection list ("Import Studio, per instrument"). Kept on the core Instrument
beside Import Studio's import mappings, keyed by software version like them,
so what the instrument reads and what it writes are kept together.

    IAnnotations(instrument)[KEY] = {version: {"software", "columns": [[header,
                                     source]], "saved_by", "saved_at"}}

The Run Builder writes the worksheet's instrument's most recently saved
version (run_plan.export_rows); with none saved it offers the Waters
MassLynx starter (run_plan.MASSLYNX_COLUMNS), named as a starter.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json

KEY = "senaite.pfas.instrument_export"


def load(instrument):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(instrument).get(KEY) or u"{}")
    except (ValueError, TypeError):
        return {}


def save(instrument, version, software, columns, by, at):
    from zope.annotation.interfaces import IAnnotations
    data = load(instrument)
    data[version] = {"software": software, "columns": columns, "saved_by": by, "saved_at": at}
    IAnnotations(instrument)[KEY] = json.dumps(data)
    return data


def current(data):
    """(version, config) most recently saved, or (u"", None). Pure."""
    if not data:
        return u"", None
    version = sorted(data, key=lambda v: (data[v].get("saved_at") or u"", v))[-1]
    return version, data[version]


def columns_for(instrument):
    """(columns, where): the instrument's saved columns, or the MassLynx
    starter. `where` names which, for the page and the file."""
    try:
        from senaite.pfas import run_plan
    except ImportError:                                     # tests
        import run_plan
    if instrument is not None:
        version, cfg = current(load(instrument))
        if cfg and cfg.get("columns"):
            return cfg["columns"], u"%s %s (Import Studio)" % (cfg.get("software") or u"", version)
    return run_plan.MASSLYNX_COLUMNS, u"Waters MassLynx starter (not set for this instrument)"


def parse_columns(text):
    """'HEADER = source' per line -> [[header, source]]; an unknown source is
    kept as fixed text so nothing typed is lost silently. Pure."""
    try:
        from senaite.pfas import run_plan
    except ImportError:                                     # tests
        import run_plan
    out = []
    for line in (text or u"").splitlines():
        if not line.strip():
            continue
        head, _sep, src = line.partition(u"=")
        head, src = head.strip(), src.strip()
        if not head:
            continue
        if src not in run_plan.SOURCES and not src.startswith(u"fixed:"):
            src = u"fixed:" + src
        out.append([head, src])
    return out


def columns_text(columns):
    return u"\n".join(u"%s = %s" % (h, s) for h, s in columns or [])
