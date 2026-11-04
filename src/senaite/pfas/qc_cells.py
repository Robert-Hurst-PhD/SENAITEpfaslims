# -*- coding: utf-8 -*-
"""What each QC Summary cell shows: the result itself, coloured by its
stored verdict, with the criterion it was judged by cited ONCE, as a
superscript number with the supporting text below the table.

A criterion is identified by its rule (qc_results.limit_basis, written by the
worker from the check that set the verdict: "LFSM recovery 70-130 %"), never
by its resolved number -- a blank's limit is a multiple of each analyte's RL
and would otherwise need a note per analyte. Rules every cell of a column
shares are cited on the column header; only a cell judged by a different
rule (the lowest-level CCC, another recovery tier) carries its own number.
The resolved window is in the cell's tooltip.

Colour comes from the stored verdict only, never from re-judging the value
against the window, and only for the exception: a value that passed is a
plain number.

    pass   the check passed                      (plain, no chip)
    fail   it failed and holds release           (coral, "Fail" after it)
    review qualified, flagged for reanalysis,    (amber, "Review" after it)
           not evaluated, or advisory

A row holding a failing cell is marked "fail", one holding a cell for
review only "review" (the table draws that on the row's left edge).

    split(qc_type, values)                 [(display column, values)]: one
                                           measure per column (LFSMD's
                                           recovery and its RPD apart)
    sub_status(status, values)             a split column's own state
    cell_display(qc_type, values, status)  {text, word, cls, tip, bases, n}
    row_state(cells)                       "fail" | "review" | "" for a row
    footnotes(columns, rows)               (header_notes, cell_notes, notes)
    group_of(column)                       "extracted" | "instrument"
    groups(columns, rows, notes)           the two tables, each with the
                                           rows and notes it uses
    column_unit(qc_type, values)           the unit for the column header
    tables(columns, rows, keep)            the tables a page shows, for the
                                           columns `keep` selects, numbered
                                           afresh (QC Summary: all; Spike QC:
                                           the spikes)
    code_cell(codes, reasons)              a result's QC qualifier codes as a
                                           cell (Final Data)

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.extraction_batch import QC_ROLES

# QC prepared WITH the samples (the extraction batch's QC members, and the
# field reagent and trip blanks extracted beside them); everything else is the
# instrument's: calibration, ICV, CCV, CCB, internal-standard response
EXTRACTED = frozenset(QC_ROLES) | frozenset(("FRB", "TB"))
# reading order: blanks, fortified blanks, matrix QC; then the run's own
# order -- the curve, its verification, the bracket, the standards
ORDER = ("MB", "LRB", "MxB", "FRB", "TB", "LFB", "LCS", "LFSM", "LFSMD", "Dup",
         "Calibration", "ICV", "CCV", "CCB", "IS")
GROUPS = (("extracted", u"Extracted QC"), ("instrument", u"Instrument QC (not extracted)"))

STATUS_CLASS = {"ok": "qv-plain", "fail": "qv-fail", "qualified": "qv-review",
                "warn": "qv-review", "unevaluated": "qv-review"}
# the verdict word a chip carries after its value; a pass carries none
CLASS_WORD = {"qv-fail": u"Fail", "qv-review": u"Review"}
STATUS_WORD = {"ok": u"Pass", "fail": u"Fail", "qualified": u"Qualified",
               "warn": u"Review", "unevaluated": u"Not evaluated"}
ND = u"N.D."
NOT_RECORDED = u"Criterion not recorded for this run: re-process it to show it."
BLANKS = ("MB", "LRB", "MxB", "CCB", "FRB", "TB")
RECOVERY_FROM_EXPECTED = ("CCV", "ICV")
# a column's unit, spelled out, shown in brackets after its name:
# "LFB (Recovery %)", "LFSMD RPD (%)", "Calibration (Deviation %)"
UNIT_LABEL = {"%": u"Recovery %", "% RPD": u"%", "% deviation": u"Deviation %",
              "% of ICAL avg": u"Initial calibration average %"}


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


from senaite.pfas.rounding import number as _num


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
    """A blank to three significant figures; every other cell (recoveries,
    RPDs, deviations: all percents) as a whole percent, so 0.985 never reads
    0.99 beside 4 and 12."""
    if x is None:
        return u""
    if qc_type in BLANKS:
        return u"%.3g" % x
    text = u"%.0f" % x
    return u"0" if text == u"-0" else text


def _window_text(v):
    lo, hi = _num(v.get("limit_low")), _num(v.get("limit_high"))
    if lo is not None and hi is not None:
        return u"%g to %g" % (lo, hi)
    if hi is not None:
        return u"at most %g" % hi
    return u""


def cell_display(qc_type, values, status):
    """{text, word, cls, tip, bases, n} for one cell. A passing value is
    plain (N.D. muted); a failing or review value is a chip with its word."""
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
    # the provenance records behind the cell, the shown value's first
    prov = []
    for v in ([w] if w else []) + values:
        k = v.get("prov_key") or u""
        if k and k not in prov:
            prov.append(k)
    cls = STATUS_CLASS.get(status, "qv-review")
    if text == ND and cls == STATUS_CLASS["ok"]:
        cls += u" pfas-muted"
    return {"text": text, "word": CLASS_WORD.get(cls, u""), "cls": cls,
            "tip": u" · ".join(tips), "bases": bases, "n": len(values), "prov": prov}


def row_state(cells):
    """"fail" when a cell of the row failed, "review" when one is for
    review only, else "": the row's edge."""
    classes = u" ".join((c or {}).get("cls") or u"" for c in cells or [])
    if u"qv-fail" in classes:
        return u"fail"
    return u"review" if u"qv-review" in classes else u""


def column_unit(qc_type, values):
    if qc_type in RECOVERY_FROM_EXPECTED:
        return u"Recovery %"
    if values and all((v.get("kind") or u"") == u"RPD" for v in values):
        return u"%"                                          # "LFSMD RPD (%)"
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


# Data Review's Spike QC tab: the spiked and fortified QC and the duplicate's
# RPD column (LFSMD RPD goes with LFSMD)
SPIKE = ("LFSM", "LFSMD", "LFB", "LCS", "SD")


def is_spike(column):
    return column.split(" ")[0] in SPIKE


def tables(columns, rows, keep=None):
    """What a page draws from the QC Summary's cells: the columns `keep`
    selects (every one when None), the analytes with a cell in them, the
    criteria those cells cite numbered from 1, and the two tables.
    `columns`: [{key, unit}] in display order; `rows`: [{analyte, display}].
    Copies: the summary's own rows are not changed."""
    cols = [dict(c) for c in columns if keep is None or keep(c["key"])]
    keys = [c["key"] for c in cols]
    mine = []
    for r in rows:
        display = dict((k, dict(d)) for k, d in (r.get("display") or {}).items()
                       if k in keys and d)
        if display:
            mine.append({"analyte": r["analyte"], "display": display})
    header, cells, notes = footnotes(keys, mine)
    for c in cols:
        c["notes"] = header.get(c["key"]) or []
    for r in mine:
        for k, d in r["display"].items():
            d["notes"] = cells.get((r["analyte"], k)) or []
        r["state"] = row_state(r["display"].values())
    return {"columns": cols, "rows": mine, "notes": notes,
            "groups": groups(cols, mine, notes)}


def code_cell(codes, reasons=u""):
    """A result's QC qualifier codes ("M, P") as a cell the shared macro
    draws: review colour -- the result is released with a qualifier, as a
    qualified cell reads in the QC Summary -- and why in the tooltip. The
    codes are the chip's words: no verdict word after them.
    None when the result carries no code."""
    if not codes:
        return None
    return {"text": codes, "word": u"", "cls": STATUS_CLASS["qualified"], "tip": reasons or codes,
            "bases": [], "n": 1, "notes": []}


# ── the Blanks tab: each blank against its limit ───────────────────────────
BLANK_COLUMNS = ("MB", "LRB", "MxB", "FRB", "TB")     # extracted blanks; the CCB is the instrument's


def blank_table(rows, qc_types):
    """Every extracted blank of a run against its limit: for each analyte and
    blank type the result as judged, the limit it was judged by ("not set"
    when there is none) and how close it came, as a whole % of the limit.
    A column with nothing in it for the whole run stays, greyed, its reason
    under its heading: a blank never judged reads "not judged", a limit
    never set "not set".
    {"types": [(qc_type, unit)], "rows": [{"analyte", "cells": [...], "state"}],
    "notes": [(qc_type, basis)],
    "heading_note": {qc_type: {"value", "limit", "pct"}} for a type with a
    greyed column}."""
    types = [qt for qt in BLANK_COLUMNS if qt in (qc_types or [])]
    units, notes, out = {}, {}, []
    judged, limited, pcts = set(), set(), set()
    for row in rows or []:
        cells, any_cell = [], False
        for qt in types:
            c = (row.get("cells") or {}).get(qt)
            vals = (c or {}).get("values") or []
            for v in vals:
                units.setdefault(qt, v.get("units") or u"")
                if v.get("limit_basis"):
                    notes.setdefault(qt, v.get("limit_basis"))
            if not vals:
                cells.append({"type": qt, "text": u"\u2014", "word": u"", "cls": u"pfas-muted", "tip": u"",
                              "limit": u"not set", "pct": u"\u2014", "prov": None})
                continue
            any_cell = True
            judged.add(qt)
            d = (row.get("display") or {}).get(qt) or cell_display(qt, vals, (c or {}).get("status"))
            w = worst(qt, vals)
            hi = _num(w.get("limit_high")) if w else None
            x = shown(qt, w) if w else None
            pct = u"\u2014"
            if hi and x is not None:
                pct = u"%.0f" % (x / hi * 100.0)
                pcts.add(qt)
            if hi is not None:
                limited.add(qt)
            cls = d.get("cls") or u""
            cells.append({"type": qt, "text": d.get("text") or u"", "cls": cls,
                          "word": d.get("word", CLASS_WORD.get(cls, u"")), "tip": d.get("tip") or u"",
                          "limit": (u"%.3g" % hi) if hi is not None else u"not set", "pct": pct,
                          # the record behind the value: the value and its % open it
                          "prov": ((d.get("prov") or cell_display(qt, vals, (c or {}).get("status")).get("prov")
                                    or [None])[0])})
        if any_cell:
            out.append({"analyte": row.get("analyte"), "cells": cells, "state": row_state(cells)})
    heading = {}
    for qt in types:
        # a judged blank with its limit is not greyed for want of a %: one
        # that was not detected anywhere (N.D.) has no % to show
        note = {"value": u"" if qt in judged else u"not judged",
                "limit": u"" if qt in limited else u"not set",
                "pct": u"" if (qt in pcts or (qt in judged and qt in limited))
                else (u"not judged" if qt not in judged else u"not set")}
        if any(note.values()):
            heading[qt] = note
    for r in out:
        for c in r["cells"]:
            c["heading_note"] = heading.get(c["type"]) or {}
    return {"types": [(qt, units.get(qt, u"")) for qt in types], "rows": out,
            "notes": [(qt, notes[qt]) for qt in types if qt in notes],
            "heading_note": heading}
