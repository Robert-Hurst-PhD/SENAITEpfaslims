# -*- coding: utf-8 -*-
"""Logbook form numbers (DECISIONS 2026-10-02 "Form numbers").

A form code is FM (form) - ENV (environmental) - the logbook's sequence
number: FM-ENV-001 Solvent / Reagent Prep, 002 Calibration Curve Prep,
003 Extraction Log, 004 Sample Processing, ... Each number is used once, and
the pool is listed in number order. Codes of another shape (COC) keep their
place after the numbered forms. The internal slugs (250-253) are storage
keys, never shown as form numbers.

    number(code)        -> int or None
    next_code(codes)    -> the next free FM-ENV number
    duplicates(defs)    -> codes used by more than one logbook
    normalise(defs)     -> (defs in number order, renamed [(slug, old, new)])

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import re

PREFIX = u"FM-ENV-"
_CODE = re.compile(r"^\s*FM-ENV-(\d+)\s*$", re.I)


def number(code):
    m = _CODE.match(code or u"")
    return int(m.group(1)) if m else None


def next_code(codes):
    used = [n for n in (number(c) for c in codes or []) if n is not None]
    return u"%s%03d" % (PREFIX, (max(used) if used else 0) + 1)


def duplicates(defs):
    seen, dup = set(), []
    for d in defs or []:
        code = (d.get("form_num") or u"").strip().upper()
        if not code:
            continue
        if code in seen and code not in dup:
            dup.append(code)
        seen.add(code)
    return dup


def normalise(defs):
    """Give every duplicated number but one the next free number -- a
    built-in logbook keeps its number, a custom one moves -- then order the
    pool by number, other codes after in their existing order."""
    out = [dict(d) for d in defs or []]
    renamed = []
    codes = [d.get("form_num") or u"" for d in out]
    holders = {}
    for i, d in enumerate(out):
        n = number(d.get("form_num"))
        if n is not None:
            holders.setdefault(n, []).append(i)
    for n, idx in sorted(holders.items()):
        if len(idx) < 2:
            continue
        keep = ([i for i in idx if out[i].get("builtin")] or idx)[0]
        for i in idx:
            if i == keep:
                continue
            new = next_code(codes)
            renamed.append((out[i].get("slug"), out[i].get("form_num"), new))
            out[i]["form_num"] = new
            codes.append(new)
    numbered = sorted((d for d in out if number(d.get("form_num")) is not None),
                      key=lambda d: number(d["form_num"]))
    others = [d for d in out if number(d.get("form_num")) is None]
    return numbered + others, renamed
