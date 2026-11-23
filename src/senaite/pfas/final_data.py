# -*- coding: utf-8 -*-
"""Final Data: the instrument's result behind each reported result.

A reported result names its analysis by keyword (and title); the
instrument's injection rows name their compound as the export did. An
isomer sum (PFOS) has two instrument rows, its linear and branched parts
("lr-PFOS", "br-PFOS"):

    parts(injection rows of one sample, keyword, title)
        -> [{"part", "result", "rt", "prov", "injection"}], the parts in
           lr, br order
    target_of(injection, targets)
        -> the request target the row's injection names, or u""
    text(parts), rt_text(parts)
        -> (value, parts line): the number for the value column and, for
           an isomer sum, its parts for the muted line under it
           ("lr 4.896 · br 1.224"); u"" where there is none

Matched exactly first (keyword or title, letters and digits only, any
case), then the lr- / br- parts, then a name that begins with the
keyword ("GenX" -> "GenX (HFPO-DA)").

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import re

from senaite.pfas import isomers


def _norm(text):
    return re.sub(r"[^a-z0-9]", u"", (u"%s" % (text or u"")).lower())


def parts(rows, keyword, title=u""):
    keys = [k for k in (_norm(keyword), _norm(title)) if k]
    by = {}
    for r in rows or []:
        by.setdefault(_norm(r.get("analyte")), r)

    def one(r, part):
        return {"part": part, "result": r.get("result"), "rt": r.get("rt"),
                "prov": (r.get("prov") or {}).get("result"),
                "injection": r.get("injection_name") or u""}

    for k in keys:
        if k in by:
            return [one(by[k], u"")]
    for k in keys:
        iso = [(p, by.get(p + k)) for p in (u"lr", u"br")]
        if [r for _p, r in iso if r]:
            return [one(r, p) for p, r in iso if r]
    for k in keys:
        for name in sorted(by):
            if name.startswith(k) or k.startswith(name):
                return [one(by[name], u"")]
    return []


def _parts_line(ps, key, fmt):
    """"lr 4.896 · br 1.224": an isomer sum's parts, u"" for one peak."""
    if not [p for p in ps or [] if p["part"]]:
        return u""
    return u" \u00b7 ".join(u"%s %s" % (p["part"], fmt % p[key])
                             for p in ps if p.get(key) is not None)


def text(ps, fmt=u"%.4g"):
    """(value, parts): ("0.42", u"") for one peak; for an isomer sum the
    sum of its parts as the value, the parts on their own line,
    ("6.12", "lr 4.896 · br 1.224"), no value for a sum of zero
    (isomers.total); (u"", u"") when none."""
    ps = ps or []
    if [p for p in ps if p["part"]]:
        number = isomers.total([p["result"] for p in ps])
    else:
        number = ps[0]["result"] if ps else None
    value = (fmt % number) if number is not None else u""
    return value, _parts_line(ps, "result", fmt)


def rt_text(ps):
    """(value, parts): ("7.82", u"") for one peak; an isomer sum has no one
    retention time, so its value is empty and its parts carry each,
    (u"", "lr 8.10 · br 7.95")."""
    line = _parts_line(ps, "rt", u"%.2f")
    if line:
        return u"", line
    rts = [p["rt"] for p in ps or [] if p.get("rt") is not None]
    return (u"%.2f" % rts[0]) if rts else u"", u""


def target_of(injection, targets):
    """The request target (a batch member's injection) that `injection`, an
    instrument row's name, names: matched on letters and digits only, any
    case ("DW 0012" is "dw-0012"); u"" when none does."""
    key = _norm(injection)
    if not key:
        return u""
    return next((t for t in targets or [] if _norm(t) == key), u"")


def result_key(parts_, keyword=None):
    """The reported result's record: the RESULT record under the
    worker's own analyte name -- a part of an isomer sum resolves to the
    sum's record (provenance_store.get) -- or None when none is known."""
    return next((p.get("prov") for p in parts_ or [] if p.get("prov")), None)
