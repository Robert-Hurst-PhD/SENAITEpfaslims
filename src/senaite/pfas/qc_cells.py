# -*- coding: utf-8 -*-
"""What each QC Summary cell shows: the result itself, coloured by its
stored verdict, with the criterion it was judged by cited ONCE ("a superscript numerical citation with the supporting
information below the table ... we can't have it visually cluttering").

A criterion is identified by its rule (qc_results.limit_basis, written by the
worker from the check that set the verdict: "LFSM recovery 70-130 %"), never
by its resolved number -- a blank's limit is a multiple of each analyte's RL
and would otherwise need a note per analyte. Rules every cell of a column
shares are cited on the column header; only a cell judged by a different
rule (the lowest-level CCC, another recovery tier) carries its own number.
The resolved window is in the cell's tooltip.

Colour comes from the stored verdict only, never from re-judging the value
against the window (the Calibration page's old defect):

    pass   the check passed                      (mint)
    fail   it failed and holds release           (coral)
    review qualified, flagged for reanalysis,    (amber)
           not evaluated, or advisory

    split(qc_type, values)                 [(display column, values)]: one
                                           measure per column (LFSMD's
                                           recovery and its RPD apart)
    sub_status(status, values)             a split column's own state
    cell_display(qc_type, values, status)  {text, cls, tip, bases, n}
    footnotes(columns, rows)               (header_notes, cell_notes, notes)
    group_of(column)                       "extracted" | "instrument"
    groups(columns, rows, notes)           the two tables, each with the
                                           rows and notes it uses
    column_unit(qc_type, values)           the unit for the column header

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas.extraction_batch import QC_ROLES
except ImportError:                                          # loaded by path (tests)
    from extraction_batch import QC_ROLES

# QC prepared WITH the samples (the extraction batch's QC members, and the
# field reagent blank extracted beside them); everything else is the
# instrument's: calibration, ICV, CCV, CCB, internal-standard response
# ("extracted and non-extracted QC to simplify the review")
EXTRACTED = frozenset(QC_ROLES) | frozenset(("FRB",))
# reading order: blanks, fortified blanks, matrix QC; then the run's own
# order -- the curve, its verification, the bracket, the standards
ORDER = ("MB", "LRB", "MxB", "FRB", "LFB", "LCS", "LFSM", "LFSMD", "Dup",
         "Calibration", "ICV", "CCV", "CCB", "IS")
GROUPS = (("extracted", u"Extracted QC"), ("instrument", u"Instrument QC (not extracted)"))

STATUS_CLASS = {"ok": "qv-pass", "fail": "qv-fail", "qualified": "qv-review",
                "warn": "qv-review", "unevaluated": "qv-review"}
STATUS_WORD = {"ok": u"Pass", "fail": u"Fail", "qualified": u"Qualified",
               "warn": u"Review", "unevaluated": u"Not evaluated"}
ND = u"N.D."
NOT_RECORDED = u"Criterion not recorded for this run: re-process it to show it."
BLANKS = ("MB", "LRB", "MxB", "CCB", "FRB")
RECOVERY_FROM_EXPECTED = ("CCV", "ICV")
UNIT_LABEL = {"%": u"%", "% RPD": u"% RPD", "% deviation": u"% dev.",
              "% of ICAL avg": u"% of ICAL"}


def split(qc_type, values):
    """A cell holding two measures is shown as two columns: the LFSMD's
    recovery and its RPD read on different scales (display only: the gate
    keeps the QC type whole)."""
    if qc_type != "LFSMD":
        return [(qc_type, list(values or []))]
    rpd = [v for v in values or [] if v.get("kind") == "RPD"]
    rec = [v for v in values or [] if v.get("kind") != "RPD"]
    return [(k, vs) for k, vs in (("LFSMD", rec), ("LFSMD RPD", rpd)) if vs]


def sub_status(status, values):
    """A split column's state: the cell's, unless all its own values passed."""
    return status if any(not v.get("passed", True) for v in values) else (
        "ok" if status in ("fail", "qualified") else status)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def shown(qc_type, v):
    """The number a reviewer reads for one value (CCV / ICV: recovery)."""
    if qc_type in RECOVERY_FROM_EXPECTED and v.get("recovery") is not None:
        return _num(v.get("recovery"))
    return _num(v.get("value"))


def margin(x, lo, hi):
    """How far inside its window a value is (negative: outside); None when
    there is no window or no value."""
    if x is None or (lo is None and hi is None):
        return None
    m = []
    if lo is not None:
        m.append(x - lo)
    if hi is not None:
        m.append(hi - x)
    return min(m)


def worst(qc_type, values):
    """The value to show: a failing one first, then the one nearest (or
    furthest outside) its window, then the first."""
    def key(v):
        x = shown(qc_type, v)
        mg = margin(x, _num(v.get("limit_low")), _num(v.get("limit_high")))
        return (0 if not v.get("passed", True) else 1,
                mg if mg is not None else float("inf"))
    return sorted(values, key=key)[0] if values else None


def fmt(qc_type, x):
    if x is None:
        return u""
    if qc_type in BLANKS:
        return u"%.3g" % x
    return u"%.0f" % x if abs(x) >= 10 else u"%.2g" % x


def _window_text(v):
    lo, hi = _num(v.get("limit_low")), _num(v.get("limit_high"))
    if lo is not None and hi is not None:
        return u"%g to %g" % (lo, hi)
    if hi is not None:
        return u"at most %g" % hi
    return u""


def cell_display(qc_type, values, status):
    """{text, cls, tip, bases, n} for one cell."""
    values = list(values or [])
    w = worst(qc_type, values)
    x = shown(qc_type, w) if w else None
    if x is None:
        # not detected, written as the acronym
        text = ND if (qc_type in BLANKS and w and w.get("passed", True)) else u"flag"
    else:
        text = fmt(qc_type, x)
    tips = [STATUS_WORD.get(status, status)]
    for v in values:
        vx = shown(qc_type, v)
        part = fmt(qc_type, vx) if vx is not None else (v.get("flag") or u"no value")
        win = _window_text(v)
        tips.append(part + (u" (window %s)" % win if win else u""))
    bases = []
    for v in values:
        b = v.get("limit_basis") or u""
        if b not in bases:
            bases.append(b)
    return {"text": text, "cls": STATUS_CLASS.get(status, "qv-review"),
            "tip": u" · ".join(tips), "bases": bases, "n": len(values)}


def column_unit(qc_type, values):
    if qc_type in RECOVERY_FROM_EXPECTED:
        return u"% rec."
    for v in values or []:
        u = (v.get("units") or u"").strip()
        if u:
            return UNIT_LABEL.get(u, u)
    return u""


def footnotes(columns, rows):
    """Number the criteria. `rows`: [{"analyte", "display": {col: cell}}].
    A rule every cell of a column carries is cited on its header; any other
    rule on the cells that carry it. A cell with no recorded rule cites
    NOT_RECORDED. Returns ({col: [n]}, {(analyte, col): [n]}, [(n, text)])."""
    numbers, notes = {}, []

    def num(text):
        if text not in numbers:
            numbers[text] = len(notes) + 1
            notes.append((numbers[text], text))
        return numbers[text]

    header, cells, common = {}, {}, {}
    # headers first, left to right, so they read 1, 2, 3 ...; exceptions after
    for col in columns:
        present = [r["display"][col] for r in rows if r["display"].get(col)]
        if not present:
            continue
        sets = [set(b or NOT_RECORDED for b in d["bases"]) for d in present]
        common[col] = set.intersection(*sets) if sets else set()
        order = []
        for d in present:
            for b in d["bases"]:
                t = b or NOT_RECORDED
                if t in common[col] and t not in order:
                    order.append(t)
        header[col] = [num(t) for t in order]
    for col in columns:
        if col not in common:
            continue
        for r in rows:
            d = r["display"].get(col)
            if not d:
                continue
            own = []
            for b in d["bases"]:
                t = b or NOT_RECORDED
                if t not in common[col] and t not in own:
                    own.append(t)
            if own:
                cells[(r["analyte"], col)] = [num(t) for t in own]
    return header, cells, notes


def column_order(column):
    """Sort key: extracted first, then ORDER, a split column after its own."""
    base = column.split(" ")[0]
    return (group_of(column) != "extracted",
            ORDER.index(base) if base in ORDER else len(ORDER), column)


def group_of(column):
    """The table a display column belongs to (LFSMD RPD goes with LFSMD)."""
    return "extracted" if column.split(" ")[0] in EXTRACTED else "instrument"


def groups(columns, rows, notes):
    """The QC Summary as two tables: [{key, title, columns, rows, notes}],
    each with only the analytes that have a cell in it and the notes its
    citations use (numbering shared, so a rule keeps one number)."""
    out = []
    for key, title in GROUPS:
        cols = [c for c in columns if group_of(c["key"]) == key]
        if not cols:
            continue
        keys = [c["key"] for c in cols]
        mine = [r for r in rows if any(r["display"].get(k) for k in keys)]
        used = set(n for c in cols for n in c["notes"])
        used.update(n for r in mine for k in keys if r["display"].get(k)
                    for n in r["display"][k].get("notes") or [])
        out.append({"key": key, "title": title, "columns": cols, "rows": mine,
                    "notes": [n for n in notes if n[0] in used]})
    return out
