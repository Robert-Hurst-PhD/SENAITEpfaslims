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
    cell_display(qc_type, values, status, places)
                                           {text, word, cls, tip, bases, n};
                                           a recovery to the method's
                                           decimal places (is_recovery)
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

import re

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


def is_recovery(qc_type, v):
    """True when the value a cell shows for `v` is a recovery (a column in
    Recovery %): an RPD, a deviation or a response is not."""
    if qc_type in RECOVERY_FROM_EXPECTED:
        return v.get("recovery") is not None
    return (v.get("kind") or u"") != u"RPD" and (v.get("units") or u"").strip() == u"%"


def fmt(qc_type, x, places=0, rule=None):
    """A blank to three significant figures; every other cell (recoveries,
    RPDs, deviations: all percents) as a whole percent, so 0.985 never reads
    0.99 beside 4 and 12; a recovery with `places`, the method's decimal
    places for recoveries (method_engine.recovery_decimals), as the
    certificate prints it (rounding.recovery_text, by the method's `rule`)."""
    if x is None:
        return u""
    if qc_type in BLANKS:
        return u"%.3g" % x
    if places:
        from senaite.pfas import rounding
        return rounding.recovery_text(x, places, rule or rounding.DEFAULT_RULE) or u""
    text = u"%.0f" % x
    return u"0" if text == u"-0" else text


def _places(qc_type, v, places):
    return places if places and is_recovery(qc_type, v) else 0


def _window_text(v):
    lo, hi = _num(v.get("limit_low")), _num(v.get("limit_high"))
    if lo is not None and hi is not None:
        return u"%g to %g" % (lo, hi)
    if hi is not None:
        return u"\u2264 %g" % hi
    return u""


# A value at its limit passes: a one-sided limit is shown with the inclusive
# sign. A rule recorded in words before the sign was used reads the same.
# A blank tier the method fails at its limit keeps the strict sign.
LIMIT_WORDS = ((u" at most ", u" \u2264 "), (u" at least ", u" \u2265 "))
STRICT_BLANK = re.compile(r" below ([0-9.]+ x RL)")


def limit_text(basis):
    """A recorded rule (qc_results.limit_basis) as shown: "LFSMD RPD at most
    30 %" reads "LFSMD RPD \u2264 30 %", "LRB below 0.333 x RL" reads
    "LRB < 0.333 x RL"."""
    text = basis or u""
    for words, sign in LIMIT_WORDS:
        text = text.replace(words, sign)
    return STRICT_BLANK.sub(u" < \\1", text)


def cell_display(qc_type, values, status, places=0, rule=None):
    """{text, word, cls, tip, bases, n} for one cell. A passing value is
    plain (N.D. muted); a failing or review value is a chip with its word.
    `places`, `rule`: the method's decimal places for recoveries and its
    rounding rule."""
    values = list(values or [])
    w = worst(qc_type, values)
    x = shown(qc_type, w) if w else None
    if x is None:
        # not detected, written as the acronym
        text = ND if (qc_type in BLANKS and w and w.get("passed", True)) else u"flag"
    else:
        text = fmt(qc_type, x, _places(qc_type, w, places), rule)
    tips = [STATUS_WORD.get(status, status)]
    for v in values:
        vx = shown(qc_type, v)
        part = (fmt(qc_type, vx, _places(qc_type, v, places), rule) if vx is not None
                else (v.get("flag") or u"no value"))
        win = _window_text(v)
        tips.append(part + (u" (window %s)" % win if win else u""))
    bases = []
    for v in values:
        b = limit_text(v.get("limit_basis"))
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


# How a column is worked out, as the worker computes it (run_queue.py): the
# formula text, each term's symbol as it stands in the text, and what it means.
# A division is drawn as a stacked fraction (provenance.js); the RPD is the
# absolute difference over the mean of the two measured concentrations, as
# EPA 537.1 section 9.3.7.3 prints it.
_REC = [("Spike", u"Spike level added")]
EQUATIONS = {
    "LFB": (u"Recovery = C(LFB) \u00f7 Spike \u00d7 100",
            [("C(LFB)", u"Concentration measured in the fortified blank")] + _REC),
    "LCS": (u"Recovery = C(LCS) \u00f7 Spike \u00d7 100",
            [("C(LCS)", u"Concentration measured in the control sample")] + _REC),
    "LFSM": (u"Recovery = (C(LFSM) \u2212 C(sample)) \u00f7 Spike \u00d7 100",
             [("C(LFSM)", u"Concentration measured in the fortified sample"),
              ("C(sample)", u"Concentration measured in the unspiked sample")] + _REC),
    "LFSMD": (u"Recovery = (C(LFSMD) \u2212 C(sample)) \u00f7 Spike \u00d7 100",
              [("C(LFSMD)", u"Concentration measured in the fortified duplicate"),
               ("C(sample)", u"Concentration measured in the unspiked sample"),
               ("Spike", u"Spike level of the LFSM, the duplicate is spiked at the same level")]),
    "LFSMD RPD": (u"RPD = |C(LFSM) \u2212 C(LFSMD)| \u00f7 ((C(LFSM) + C(LFSMD)) \u00f7 2) \u00d7 100",
                  [("C(LFSM)", u"Concentration measured in the fortified sample"),
                   ("C(LFSMD)", u"Concentration measured in the fortified duplicate")]),
}


def equation(column):
    """{formula, terms: [{symbol, label}]} for a display column, or None."""
    hit = EQUATIONS.get(column)
    if hit is None:
        return None
    return {"formula": hit[0], "terms": [{"symbol": s, "label": l} for s, l in hit[1]]}


def with_equations(groups):
    """The tables with each column that has an equation carrying it as the
    JSON its header card reads ("equation")."""
    import json
    out = []
    for g in groups:
        cols = []
        for c in g["columns"]:
            eq = equation(c["key"])
            cols.append(dict(c, equation=json.dumps(eq) if eq else None))
        out.append(dict(g, columns=cols))
    return out


def is_spike(column):
    return column.split(" ")[0] in SPIKE


# Data Review's Spike QC tab, its Duplicates section: the sample duplicate's
# and the field duplicate's RPD columns
DUPLICATE = ("Dup", "FD")


def is_duplicate(column):
    return column.split(" ")[0] in DUPLICATE


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


NOT_JUDGED, NOT_RUN = u"not judged", u"not run"
# a cell with nothing judged is a muted dash carrying a notation mark: its
# footnote, once under the table, says why, never the words in every cell
NOT_JUDGED_NOTE = u"%s not judged for this run"
NOT_RUN_NOTE = u"%s not run: the method requires it every run"


def with_required(groups, required, filed, analytes, why=None):
    """The Spike QC tables with a column for every required spike: one the
    run filed nothing judged for (it is among `filed`, the QC types the run
    filed a record for) or did not run. Each of its cells is a muted dash
    carrying a notation mark, a note number after the tables' own; the
    note, once under the table, says why: "<type> not judged: why[type]",
    else that it was not judged or not run. The extracted table is made for
    `analytes` when the run judged no spike at all. Such a note is
    (number, text, True): its words are its own, no criterion of the
    method. Copies."""
    why = why or {}
    groups = [dict(g, columns=list(g["columns"]), notes=list(g.get("notes") or []),
                   rows=[dict(r, display=dict(r["display"])) for r in g["rows"]])
              for g in groups or []]
    have = set(c["key"].split(u" ")[0] for g in groups for c in g["columns"])
    missing = [qt for qt in required if qt not in have]
    if not missing:
        return groups
    extracted = [g for g in groups if g["key"] == u"extracted"]
    if extracted:
        group = extracted[0]
    elif analytes:
        group = {"key": u"extracted", "title": dict(GROUPS)[u"extracted"], "columns": [], "notes": [],
                 "rows": [{"analyte": a, "display": {}, "state": u""} for a in analytes]}
        groups.insert(0, group)
    else:
        return groups
    # numbered after every note of the tables, which share their numbering
    taken = [n[0] for g in groups for n in g.get("notes") or []]
    numbers = {}
    for qt in missing:
        if qt in (filed or ()):
            text = (u"%s not judged: %s" % (qt, why[qt].rstrip(u"."))) if why.get(qt) \
                else NOT_JUDGED_NOTE % qt
        else:
            text = NOT_RUN_NOTE % qt
        if text not in numbers:
            numbers[text] = max(taken + list(numbers.values()) + [0]) + 1
            group["notes"].append((numbers[text], text, True))
        group["columns"].append({"key": qt, "unit": u"", "notes": []})
        for r in group["rows"]:
            r["display"][qt] = {"text": u"\u2014", "word": u"", "cls": u"pfas-muted",
                                "tip": text, "notes": [numbers[text]], "n": 1, "prov": None}
    group["columns"].sort(key=lambda c: column_order(c["key"]))
    return groups


def code_cell(codes, reasons=u"", meanings=None):
    """A result's QC qualifier codes ("M, P") as a cell the shared macro
    draws: review colour -- the result is released with a qualifier, as a
    qualified cell reads in the QC Summary -- and in the tooltip what each
    code means ("M = the lab's wording", as the certificate's legend says
    it; `meanings` {code: wording}), then why. The codes are the chip's
    words: no verdict word after them. None when the result carries no
    code."""
    if not codes:
        return None
    said = [u"%s = %s" % (c, (meanings or {}).get(c)) for c in
            [x.strip() for x in codes.split(u",") if x.strip()] if (meanings or {}).get(c)]
    tip = u"; ".join(said + ([reasons] if reasons else [])) or codes
    return {"text": codes, "word": u"", "cls": STATUS_CLASS["qualified"], "tip": tip,
            "bases": [], "n": 1, "notes": []}


# ── the Blanks tab: each blank against its limit ───────────────────────────
BLANK_COLUMNS = ("MB", "LRB", "MxB", "FRB", "TB")     # extracted blanks; the CCB is the instrument's


NONE_HERE = u"none on this worksheet"


def blank_table(rows, qc_types, always=(), absent=(), rule=None):
    """Every extracted blank of a run against its limit: for each analyte and
    blank type the result as judged, the limit it was judged by ("not set"
    when there is none) and how close it came, as a whole % of the limit.
    A column with nothing in it for the whole run stays, greyed, its reason
    under its heading: a blank never judged reads "not judged", a limit
    never set "not set".
    `always`: the blank types the method's rules enforce, shown whether or
    not the run holds one; `absent`: those of them the worksheet holds none
    of, whose columns say so; `rule`: {qc_type: the method's rule in words},
    stated under the limit heading where no stored row carries the limit.
    {"types": [(qc_type, unit)], "rows": [{"analyte", "cells": [...], "state"}],
    "notes": [(qc_type, basis)],
    "heading_note": {qc_type: {"value", "limit", "pct"}} for a type with a
    greyed column, "absent": ["No FRB on this worksheet."]}."""
    rule = rule or {}
    wanted = set(qc_types or []) | set(always or ())
    types = [qt for qt in BLANK_COLUMNS if qt in wanted]
    absent = [qt for qt in types if qt in (absent or ())]
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
                    notes.setdefault(qt, limit_text(v.get("limit_basis")))
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
        if qt in absent and qt not in judged:
            # none on the worksheet: said, with the limit the method applies
            heading[qt] = {"value": NONE_HERE, "limit": rule.get(qt) or u"", "pct": NONE_HERE}
            continue
        # judged, but filed without the limit applied: the method's rule
        stated = qt in judged and qt not in limited and rule.get(qt)
        # a judged blank with its limit is not greyed for want of a %: one
        # that was not detected anywhere (N.D.) has no % to show
        note = {"value": u"" if qt in judged else u"not judged",
                "limit": stated or (u"" if qt in limited else u"not set"),
                "pct": u"" if (qt in pcts or (qt in judged and (qt in limited or stated)))
                else (u"not judged" if qt not in judged else u"not set")}
        if any(note.values()):
            heading[qt] = note
    for r in out:
        for c in r["cells"]:
            c["heading_note"] = heading.get(c["type"]) or {}
            if c["limit"] == u"not set" and c["heading_note"].get("limit") not in (u"", u"not set", None):
                c["limit"] = u"—"
    return {"types": [(qt, units.get(qt, u"")) for qt in types], "rows": out,
            "notes": [(qt, notes[qt]) for qt in types if qt in notes],
            "heading_note": heading,
            "absent": [u"No %s on this worksheet." % qt for qt in absent if qt not in judged]}
