# -*- coding: utf-8 -*-
"""Peak asymmetry followed over runs, from each run's mid-level calibrator.

The worker measures every peak's asymmetry factor on its quantifier trace
and stores it in the peak's record (a raw row's derived_from, "raw:{...}":
"asymmetry", or "asymmetry_note" saying why there is none). Nothing is
stored here: the factors are read back from the calibrators' rows, so a
run reprocessed is followed as it now stands.

    factor_of(derived_from)   (factor, note) of one row's peak record
    mid_level(rows)           the run's mid-level calibrator: each method
                              analyte's own levels name the injection
                              nearest their midpoint (calibration_levels
                              .midpoint) and the injection most of them
                              name is the run's
    run_factors(rows)         {"injection", "analytes": [{analyte, role, rt,
                              factor, note}]} of one run, or None
    first_eluting(run, n=2)   the first n eluting method analytes of a run's
                              mid-level calibrator, by retention time (the
                              IDC's, EPA 537.1 v2.0 §9.2.5)
    trend(rows)               [{batch_id, run_date, method, instrument_id,
                              analyst, injection, analyte, factor}] of every
                              measured factor, oldest run first
    load_rows(conn, ...)      the calibrator rows of runs integrated from
                              raw data, from the QC database

Tracked, not judged: no verdict here holds a run. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

import json

from senaite.pfas import calibration_levels

RAW = "raw:"
CALIBRATOR = "CAL"
METHOD_ANALYTE = "analyte"


def factor_of(derived_from):
    """(factor, note) of a row's peak record; (None, None) for a row with
    no peak record or none measured."""
    text = derived_from or u""
    if not text.startswith(RAW):
        return None, None
    try:
        rec = json.loads(text[len(RAW):]) or {}
    except ValueError:
        return None, None
    factor = rec.get("asymmetry")
    try:
        factor = float(factor) if factor is not None else None
    except (TypeError, ValueError):
        factor = None
    return factor, rec.get("asymmetry_note") or None


def _order(rows):
    """The run's calibrator injections in acquisition order."""
    seen = {}
    for r in rows:
        name = r.get("injection_name") or u""
        key = (r.get("acquired_at") or u"", name)
        if name not in seen or key < seen[name]:
            seen[name] = key
    return [n for n, _k in sorted(seen.items(), key=lambda x: x[1])]


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def mid_level(rows):
    """The run's mid-level calibrator injection, or None with no curve."""
    order = _order(rows)
    at = dict((n, i) for i, n in enumerate(order))
    by_analyte = {}
    for r in rows:
        conc = _num(r.get("expected_conc"))
        if r.get("role") == METHOD_ANALYTE and conc is not None:
            by_analyte.setdefault(r.get("analyte"), []).append((conc, r.get("injection_name")))
    votes = {}
    for pairs in by_analyte.values():
        mid = calibration_levels.midpoint([c for c, _i in pairs])
        if mid is None:
            continue
        # a level injected twice: its first injection
        inj = sorted((at.get(i, len(order)), i) for c, i in pairs if c == mid)[0][1]
        votes[inj] = votes.get(inj, 0) + 1
    if not votes:
        return None
    return sorted(votes, key=lambda i: (-votes[i], at.get(i, len(order))))[0]


def run_factors(rows):
    """Every analyte's factor at the run's mid-level calibrator (`rows`:
    one run's calibrator rows), or None when the run has no curve."""
    rows = list(rows or [])
    inj = mid_level(rows)
    if inj is None:
        return None
    out = []
    for r in rows:
        if r.get("injection_name") != inj:
            continue
        factor, note = factor_of(r.get("derived_from"))
        out.append({"analyte": r.get("analyte"), "role": r.get("role"), "rt": r.get("rt"),
                    "factor": factor, "note": note})
    out.sort(key=lambda e: (e["rt"] is None, e["rt"] or 0.0, e["analyte"]))
    return {"injection": inj, "batch_id": rows[0].get("batch_id"), "analytes": out}


def first_eluting(run, n=2):
    """The first `n` eluting method analytes of a run's mid-level
    calibrator, each with its factor or the reason it has none; labelled
    standards are not method analytes."""
    found = [e for e in (run or {}).get("analytes") or []
             if e.get("role") == METHOD_ANALYTE and e.get("rt") is not None]
    return found[:n]


def _runs(rows):
    out = {}
    for r in rows or []:
        out.setdefault(r.get("batch_id"), []).append(r)
    return out


def trend(rows):
    """Every measured factor of every run, oldest run first."""
    points = []
    for batch, mine in _runs(rows).items():
        run = run_factors(mine)
        if run is None:
            continue
        meta = mine[0]
        for e in run["analytes"]:
            if e["factor"] is None:
                continue
            points.append({"batch_id": batch, "run_date": meta.get("run_date") or u"",
                           "method": meta.get("method") or u"", "instrument_id": meta.get("instrument_id") or u"",
                           "analyst": meta.get("analyst") or u"", "injection": run["injection"],
                           "analyte": e["analyte"], "role": e["role"], "factor": e["factor"]})
    points.sort(key=lambda p: (p["run_date"], p["batch_id"], p["analyte"]))
    return points


COLUMNS = ("batch_id", "injection_name", "analyte", "role", "expected_conc", "rt", "derived_from",
           "acquired_at", "run_date", "method")


ALT_RAW = "raw"          # alt_results side: raw rows of a run reported from the vendor's results


def _alt_raw_rows(conn, method, instrument, analyst, date_from, date_to, batches, skip):
    """The calibrator rows of the raw integration kept apart (alt_results,
    side "raw") for a run reported from the vendor's results, filtered as
    load_rows filters; a batch already read from injection_results is left
    out."""
    out = []
    metas = {}
    for b, inst, who in conn.execute("SELECT batch_id, COALESCE(instrument_id, ''), COALESCE(analyst, '') "
                                     "FROM batches"):
        metas[b] = (inst, who)
    wanted = None if batches is None else set(batches)
    for batch, text in conn.execute("SELECT batch_id, data FROM alt_results WHERE side = ? ORDER BY id",
                                    (ALT_RAW,)):
        if batch in skip or (wanted is not None and batch not in wanted):
            continue
        try:
            row = json.loads(text) or {}
        except ValueError:
            continue
        if row.get("qc_type") != CALIBRATOR or not (row.get("derived_from") or u"").startswith(RAW):
            continue
        inst, who = metas.get(batch, (u"", u""))
        if (method and row.get("method") != method) or (instrument and inst != instrument) \
                or (analyst and who != analyst):
            continue
        day = row.get("run_date") or u""
        if (date_from and not day >= date_from) or (date_to and not day <= date_to):
            continue
        rec = dict((c, row.get(c)) for c in COLUMNS)
        rec["batch_id"] = batch
        rec["instrument_id"], rec["analyst"] = inst, who
        out.append(rec)
    return out


def load_rows(conn, method=None, instrument=None, analyst=None, date_from=None, date_to=None, batches=None):
    """The calibrator rows of the runs integrated from raw data, with each
    run's instrument and analyst, and the raw rows kept apart for a run
    reported from the vendor's results; read only."""
    sql = ["SELECT %s, COALESCE(b.instrument_id, ''), COALESCE(b.analyst, '') FROM injection_results i "
           "LEFT JOIN batches b ON b.batch_id = i.batch_id WHERE i.qc_type = ? AND i.derived_from LIKE ?"
           % ", ".join("i." + c for c in COLUMNS)]
    args = [CALIBRATOR, RAW + "%"]
    for clause, value in (("i.method = ?", method), ("b.instrument_id = ?", instrument),
                          ("b.analyst = ?", analyst), ("i.run_date >= ?", date_from),
                          ("i.run_date <= ?", date_to)):
        if value:
            sql.append("AND " + clause)
            args.append(value)
    if batches is not None:
        batches = list(batches)
        if not batches:
            return []
        sql.append("AND i.batch_id IN (%s)" % ",".join("?" * len(batches)))
        args += batches
    out = []
    for row in conn.execute(" ".join(sql), args):
        rec = dict(zip(COLUMNS, row[:len(COLUMNS)]))
        rec["instrument_id"], rec["analyst"] = row[len(COLUMNS)], row[len(COLUMNS) + 1]
        out.append(rec)
    return out + _alt_raw_rows(conn, method, instrument, analyst, date_from, date_to, batches,
                               set(r["batch_id"] for r in out))
