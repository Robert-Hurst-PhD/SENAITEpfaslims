# -*- coding: utf-8 -*-
"""Matrix blanks against their lot's assigned levels.

A matrix blank is made from a blank-matrix lot (a reference material, or
material the lab has quantified before), so it is expected to carry PFAS at
known levels. The ASSIGNED levels live on that inventory lot: from its
reference-material certificate, or as previously quantified with the runs
they came from. Each entry is kept; the newest is the one in force.

    record = {"source": "certificate" | "quantified", "unit", "levels":
              {analyte: value}, "runs": [worksheet ids], "note", "by", "at"}

    parse_levels(pairs)                    {analyte: value}, [problems]
    make_record(source, unit, levels, runs, note, by, at)   record, [problems]
    quantified_from(blank_runs, keys)      {analyte: mean}, {analyte: n}, units
    current(history)                       the record in force, or None
    compare(values, unit, record)          [{analyte, measured, assigned,
                                             difference, comparable}]
    same_unit(a, b)                        both given and the same

Nothing here is a verdict: a matrix blank is shown against its assigned
level, never passed or failed by this module (the lab sets no limit yet).
Values are compared only when both carry the same unit; a mismatch is shown
side by side, never converted.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

LEVELS_KEY = "senaite.pfas.reagent.assigned_levels"
SOURCES = (("certificate", u"Reference-material certificate"),
           ("quantified", u"Previously quantified by the lab"))


def _num(v):
    try:
        if v is None or (u"%s" % v).strip() == u"":
            return None
        return float(v)
    except (TypeError, ValueError):
        return False


def parse_levels(pairs):
    """[(analyte, text)] -> {analyte: value}, problems. A blank value is left
    out; a value that is not a number, or is negative, is refused."""
    out, problems = {}, []
    for analyte, text in pairs or []:
        analyte = (analyte or u"").strip()
        v = _num(text)
        if not analyte or v is None:
            continue
        if v is False or v < 0:
            problems.append(u"%s: %s is not a level." % (analyte, text))
            continue
        out[analyte] = v
    return out, problems


def make_record(source, unit, levels, runs=None, note=u"", by=u"", at=u""):
    """A new assigned-levels record, or the problems that stop it."""
    problems = []
    if source not in dict(SOURCES):
        problems.append(u"Say where the levels come from.")
    if not (unit or u"").strip():
        problems.append(u"Give the unit the levels are in.")
    if not levels:
        problems.append(u"Enter at least one level.")
    runs = [r for r in (runs or []) if r]
    if source == "quantified" and not runs:
        problems.append(u"Name the runs the levels were quantified in.")
    if problems:
        return None, problems
    return {"source": source, "unit": unit.strip(), "levels": dict(levels),
            "runs": runs, "note": (note or u"").strip(), "by": by, "at": at}, []


def quantified_from(blank_runs, keys):
    """The mean of each analyte over the named matrix blanks (blank_history.
    runs entries, by `key`: the injection -- only those made from the lot,
    never another material in the same run), with how many values each mean
    is from and the set of units they were reported in (more than one: the
    caller refuses)."""
    want = set(keys or [])
    sums, counts, units = {}, {}, set()
    for r in blank_runs or []:
        if r.get("key") not in want or r.get("qc_type") != "MxB":
            continue
        units.add((r.get("units") or u"").strip())
        for a, v in (r.get("values") or {}).items():
            if v is None:
                continue
            sums[a] = sums.get(a, 0.0) + float(v)
            counts[a] = counts.get(a, 0) + 1
    return dict((a, sums[a] / counts[a]) for a in sums), counts, units


def current(history):
    """The newest record (records are appended), or None."""
    history = [h for h in (history or []) if h]
    return history[-1] if history else None


def same_unit(a, b):
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()


def compare(values, unit, record):
    """Each analyte measured or assigned: the measured value, the assigned
    level and their difference -- the difference only when both are in the
    same unit (`comparable`)."""
    if not record:
        return []
    assigned = record.get("levels") or {}
    same = same_unit(unit, record.get("unit"))
    out = []
    for a in sorted(set(values or {}) | set(assigned)):
        m = (values or {}).get(a)
        s = assigned.get(a)
        ok = same and m is not None and s is not None
        out.append({"analyte": a, "measured": m, "assigned": s,
                    "difference": (float(m) - float(s)) if ok else None,
                    "comparable": ok})
    return out
