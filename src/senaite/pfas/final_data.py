# -*- coding: utf-8 -*-
"""Final Data: the instrument's result behind each reported result.

A reported result names its analysis by keyword (and title); the
instrument's injection rows name their compound as the export did. An
isomer sum (PFOS) has two instrument rows, its linear and branched parts
("lr-PFOS", "br-PFOS"):

    parts(injection rows of one sample, keyword, title)
        -> [{"part", "result", "rt", "prov", "injection"}], the parts in
           lr, br order
    children(parts)
        -> an isomer sum's parts as the rows under it, each with its own
           RESULT record; sum_key(parts) the sum's own record
    kind_of(field_qc, portal_type)
        -> "sample", "blank", "duplicate" or "other": what Final Data lists
           (samples) and where the rest is shown
    groups(rows, by, order)
        -> the rows under each sample's injections or each analyte
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
                "injection": r.get("injection_name") or u"", "analyte": r.get("analyte") or u""}

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


def _is_sum(ps):
    return bool([p for p in ps or [] if p.get("part")])


def sum_key(parts_):
    """The summed analyte's RESULT record, named from its first part's:
    "RESULT|S1|lr-PFOS" -> "RESULT|S1|PFOS" (the worker files the sum under
    the part's name less its lr- / br-); None for one peak or no record."""
    if not _is_sum(parts_):
        return None
    for p in parts_:
        key = p.get("prov") or u""
        head, bar, name = key.rpartition(u"|")
        if bar and u"-" in name:
            return u"%s|%s" % (head, name.split(u"-", 1)[1])
    return None


def result_key(parts_, keyword=None):
    """The reported result's record: the RESULT record under the
    worker's own analyte name -- for an isomer sum the sum's own record
    (sum_key), never a part's -- or None when none is known."""
    if _is_sum(parts_):
        return sum_key(parts_)
    return next((p.get("prov") for p in parts_ or [] if p.get("prov")), None)


def children(ps, fmt=u"%.4g"):
    """An isomer sum's parts as the rows under it, linear first: each its
    own name, the instrument's value and RT, and its own RESULT record to
    open ("prov"); [] for one peak."""
    if not _is_sum(ps):
        return []
    return [{"analyte": p.get("analyte") or p["part"], "part": p["part"],
             "instrument": (fmt % p["result"]) if p.get("result") is not None else u"",
             "rt": (u"%.2f" % p["rt"]) if p.get("rt") is not None else u"",
             "prov": p.get("prov"), "injection": p.get("injection") or u""} for p in ps]


# the kinds a result row of Final Data is: a field sample (its dilutions and
# retests too) is listed there; a field or lab blank on the Blanks tab, a
# duplicate on Spike QC; a spike or a reference sample on neither
SAMPLE, BLANK, DUPLICATE, OTHER = u"sample", u"blank", u"duplicate", u"other"
DUPLICATE_CODES = (u"FD", u"DUP")


def kind_of(field_qc=u"", portal_type=u""):
    """What a result row is, from its sample's field QC code (FRB, TB, FD)
    and its analysis's portal type: a lab duplicate analysis is a
    duplicate, a reference analysis other; else the code's group
    (sample_type_icons): blanks a blank, FD or Dup a duplicate, a spike
    other; a plain sample, or a code no group holds, a sample."""
    from senaite.pfas import sample_type_icons as sti
    if portal_type == u"DuplicateAnalysis":
        return DUPLICATE
    if portal_type == u"ReferenceAnalysis":
        return OTHER
    code = (u"%s" % (field_qc or u"")).strip()
    if not code:
        return SAMPLE
    if code.upper() in DUPLICATE_CODES:
        return DUPLICATE
    group = sti.group_of(code)
    if group == u"blanks":
        return BLANK
    if group in (u"spiked", u"checks", u"calibration"):
        return OTHER
    return SAMPLE


def groups(rows, by, order=None):
    """Final Data's rows grouped, each a parent row with its children kept
    together: by "injection", one group a sample in the rows' own order,
    headed by the sample and the injections its rows were read from (an
    analyte the instrument did not report never splits its sample); by
    "analyte" in `order`'s order of the analyte's name (a sort key:
    raw_review.sort_key), the samples in their order under each.
    [{"key", "title", "rows"}]."""
    out, seen, injs = [], {}, {}
    for r in rows or []:
        if by == u"analyte":
            key = r.get("analyte") or u""
            title = r.get("title") or key
        else:
            key = r.get("sample_id") or r.get("injection") or u""
            title = key
        if key not in seen:
            seen[key] = {"key": key, "title": title, "rows": []}
            injs[key] = []
            out.append(seen[key])
        seen[key]["rows"].append(r)
        inj = r.get("injection") or u""
        if inj and inj != key and inj not in injs[key]:
            injs[key].append(inj)
    if by != u"analyte":
        for g in out:
            if injs[g["key"]]:
                g["title"] = u"%s \u00b7 %s" % (g["key"], u", ".join(injs[g["key"]]))
    if by == u"analyte" and order is not None:
        out.sort(key=lambda g: order(g["key"]))
    return out
