"""
Persist the QC engine's verdicts into the shared QC database.

The pipeline already writes `injection_results` (one row per injection ×
compound: RT, ion ratios, S/N). It wrote nothing to `qc_results` or
`calibrations`, which is what Data Review's QC Summary gate and the control
charts read — so after a successful import the gate reported `no_batch_record`
and the charts were empty. `QCResultStore.add_results_bulk` existed and had no
caller at all, despite `qc/control_chart.py` building its input.

Three tables, written at the end of a run:

  batches       one row per instrument run — the gate looks this up FIRST and
                bails before querying results if it is missing
  qc_results    one row per analyte × QC type: the recovery, RPD or blank
                concentration, and whether it passed
  calibrations  one row per analyte: the curve's r², fit and weighting

Schema MIRRORS src/senaite/pfas/qc/store.py, which the Py2.7 UI reads.
Python 3.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")


def _run_date(batch) -> str:
    """The run's date, taken from the injections rather than from today."""
    stamps = [r.acquisition_datetime for r in (batch.injections or [])
              if getattr(r, "acquisition_datetime", None)]
    if stamps:
        return max(stamps).strftime("%Y-%m-%d")
    date = getattr(batch, "date", None)
    return date.strftime("%Y-%m-%d") if date else ""


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    from .addon import load
    load("qc_schema").ensure(conn)           # one schema, shared
    return conn


def _required_columns(conn, table):
    """Columns that are NOT NULL with no default — the ones an INSERT must
    supply. Introspecting beats hardcoding: the Py2.7 store owns these tables
    and has added columns (batches.updated_at, notes) that a hand-written
    CREATE here would not know about."""
    out = []
    for row in conn.execute("PRAGMA table_info({0})".format(table)):
        _cid, name, _type, notnull, default, pk = row
        if notnull and default is None and not pk:
            out.append(name)
    return out


def persist_batch_row(batch, db_path: str = None) -> None:
    """Register the run in `batches`. The QC Summary gate looks this up first
    and returns `no_batch_record` without it, whatever else is stored."""
    path = db_path or DB_PATH
    conn = _connect(path)
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(batches)")}
        if not have:
            logger.warning("batches table absent from %s — QC gate will not "
                           "find this run", path)
            return
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        candidate = {
            "batch_id": batch.batch_id,
            "run_date": _run_date(batch),
            "analyst": getattr(batch, "analyst", "") or "",
            "instrument_id": "",
            "method": getattr(batch, "method_id", "") or "",
            "matrix": getattr(batch, "matrix", "") or "",
            "status": "pending",
            "notes": "",
            "created_at": now,
            "updated_at": now,
        }
        for name in _required_columns(conn, "batches"):
            candidate.setdefault(name, "")
        fields = [k for k in candidate if k in have]
        conn.execute(
            "INSERT OR REPLACE INTO batches ({0}) VALUES ({1})".format(
                ",".join(fields), ",".join("?" * len(fields))),
            [candidate[k] for k in fields])
        conn.commit()
    finally:
        conn.close()


def _qc_rows(batch) -> list:
    """Flatten the engine's verdicts into qc_results rows."""
    from .importer import classify_injection
    from .models import reported_conc
    from .qc_engine import BLANK_ROLES

    run_date = _run_date(batch)
    method = getattr(batch, "method_id", "") or ""
    analyst = getattr(batch, "analyst", "") or ""
    dilutions = getattr(batch, "dilutions", None) or {}
    common = {"batch_id": batch.batch_id, "run_date": run_date,
              "method": method, "analyst": analyst, "instrument_id": ""}

    rows = []

    # LFSM / LFSMD — percent recovery and RPD, the numbers the gate checks
    # each row names the injection whose sample it qualifies (applies_to):
    # a matrix spike qualifies its PARENT sample only
    lfsm_parent = {}
    for res in (getattr(batch, "lfsm_results", None) or []):
        lfsm_parent[res.lfsm_injection] = res.parent_injection or ""
        # keyed by the spike injection: a second LFSM (per_batch > 1, or one
        # added on the extraction batch) collided on a shared "" and the whole
        # run's QC write was lost
        rows.append(dict(common, analyte=res.analyte, qc_type="LFSM",
                         applies_to=res.parent_injection or "",
                         qc_level=res.lfsm_injection or "", value=res.recovery_pct, units="%",
                         **_window(getattr(res, "window", None)),
                         flag=(res.flag.issue if res.flag else ""),
                         passed=0 if res.flag else 1))
    for res in (getattr(batch, "lfsmd_results", None) or []):
        parent = lfsm_parent.get(res.lfsm_injection, "")
        rows.append(dict(common, analyte=res.analyte, qc_type="LFSMD",
                         applies_to=parent,
                         qc_level="RPD " + (res.lfsmd_injection or ""), value=res.rpd_pct, units="%",
                         **_window(getattr(res, "window", None)),
                         flag=(res.flag.issue if res.flag else ""),
                         passed=0 if res.flag else 1))
        if getattr(res, "recovery_judged", False):
            rec_flag = getattr(res, "recovery_flag", None)
            rows.append(dict(common, analyte=res.analyte, qc_type="LFSMD",
                             applies_to=parent, qc_level="Recovery " + (res.lfsmd_injection or ""),
                             value=res.recovery_lfsmd, units="%",
                             **_window(getattr(res, "recovery_window", None)),
                             flag=(rec_flag.issue if rec_flag else ""),
                             passed=0 if rec_flag else 1))

    # Method blank — the measured concentration IS the result being judged
    blank_failed = {(f.injection_name, f.analyte) for f in (batch.qc_flags or [])
                    if getattr(f, "check_kind", "") == "blank"}
    blank_limits = getattr(batch, "blank_limits", None) or {}
    written = set()
    # each export row a judged analyte stands for (a summed analyte's lr- /
    # br- components, an export's own name for it) -> that analyte's key
    judged_as = {}
    for (inj_name, analyte), lim in blank_limits.items():
        for name in (lim.get("covers") or [analyte]):
            judged_as[(inj_name, name)] = (inj_name, analyte)
    # EVERY blank is checked for contamination, not only the method blank. A
    # matrix blank or reagent blank above the reporting limit is the same
    # finding and was previously never judged at all — those roles did not
    # exist, so they classified as client samples.
    for r in (batch.injections or []):
        blank_role = classify_injection(r.injection_name, dilutions)
        if blank_role not in BLANK_ROLES:
            continue
        if r.compound_type and r.compound_type != "Analyte":
            continue
        conc = reported_conc(r)
        # the verdict is the run's (run_queue against the method's Blank
        # limits, §9.3.1's "at the limit" included), not "at or above the
        # export's RL" -- that failed a solvent blank the method only reviews
        # and passed an LRB between 1/3 MRL and the MRL
        key = judged_as.get((r.injection_name, r.compound_name), (r.injection_name, r.compound_name))
        lim = blank_limits.get(key)
        over = key in blank_failed
        # the unit the result is in (was a fixed "ng/mL" whatever the run
        # reported). Every blank is kept per injection: a matrix blank is
        # compared with its own lot's assigned levels (matrix_blank.py), and a
        # run with two method or solvent blanks broke the unique key -- the
        # whole run's QC results were lost (found 2026-10-09).
        unit = (r.conc_units or "").strip()
        if lim:
            written.add(key)
        rows.append(_blank_row(common, blank_role, r.injection_name, r.compound_name, conc,
                               "" if unit.lower() == "nan" else unit, lim, over))
    # a judged analyte none of whose export rows was written (the export's
    # own total row, which carries no compound type): its verdict is still
    # stored, or a failing blank would hold nothing
    for key, lim in sorted(blank_limits.items()):
        role = classify_injection(key[0], dilutions)
        if key in written or role not in BLANK_ROLES:
            continue
        rows.append(_blank_row(common, role, key[0], key[1], lim.get("value"),
                               lim.get("unit") or "", lim, key in blank_failed))

    # field reagent blanks: judged in run_queue against the blank limit; a
    # detection qualifies the samples of the same CoC
    blank_flags = {(f.injection_name, f.analyte) for f in (batch.qc_flags or [])
                   if getattr(f, "check_kind", "") == "blank"}
    by_name = {}
    for r in (batch.injections or []):
        by_name.setdefault(r.injection_name, []).append(r)
    frb_written = set()

    field_qc = {"FRB": ("FRB within the method's blank limit (QC Types)",
                     "(BLK) field reagent blank above the blank limit"),
             "TB": ("TB within the method's trip blank limit (Blank limits)",
                    "(BLK) trip blank above the trip blank limit")}

    def _frb_row(inj, analyte, value, failed, qc_type="FRB"):
        basis, issue = field_qc[qc_type]
        return dict(common, analyte=analyte, qc_type=qc_type,
                    applies_to=inj, qc_level=inj, value=value,
                    limit_basis=basis, units="", flag=(issue if failed else ""),
                    passed=0 if failed else 1)
    frbs = list(getattr(batch, "field_blanks", None) or [])
    # a trip blank is written only where it was judged (a limit is set); an
    # unset limit is its gap, filed with the run's other gaps
    judged_tbs = set(k[0] for k in blank_limits)
    tbs = [i for i in (getattr(batch, "trip_blanks", None) or [])
           if i not in frbs and i in judged_tbs]
    for inj, qc_type in [(i, "FRB") for i in frbs] + [(i, "TB") for i in tbs]:
        for r in by_name.get(inj, []):
            if r.compound_type and r.compound_type != "Analyte":
                continue
            # judged as the analyte the row stands for (a sum's component,
            # the export's own name): keyed by the row alone, a failing FRB
            # on PFOS or ADONA was stored as a pass
            key = judged_as.get((inj, r.compound_name), (inj, r.compound_name))
            frb_written.add(key)
            rows.append(_frb_row(inj, r.compound_name, reported_conc(r), key in blank_flags, qc_type))
        for key, lim in sorted(blank_limits.items()):
            if key[0] == inj and key not in frb_written:
                rows.append(_frb_row(inj, key[1], lim.get("value"), key in blank_flags, qc_type))

    # CCV and calibration verdicts. They lived only in the run's review queue,
    # which SENAITE never reads, so a failing CCV or calibrator never reached
    # Data Review's gate. Every judged one is written, pass
    # or fail, so the QC Summary shows them and the gate holds on a failure.
    for v in (getattr(batch, "ccv_results", None) or []):
        rows.append(dict(common, analyte=v.get("analyte") or "", qc_type=v.get("qc_type") or "CCV",
                         qc_level=v.get("concat_id") or v.get("injection_name") or "",
                         value=v.get("calculated"), expected_value=v.get("expected"),
                         units="", flag=v.get("issue") or "",
                         limit_low=v.get("lo"), limit_high=v.get("hi"),
                         limit_basis=v.get("basis") or "",
                         passed=1 if v.get("passed") else 0))
    # CCV bracketing: a run that skipped a CCV or was never closed. Its flags
    # carry no analyte, so they reached neither the review queue nor
    # injection_results -- nothing in SENAITE showed them (synthetic runs). One failing row per injection out of bracket.
    for f in (batch.qc_flags or []):
        if getattr(f, "check_kind", "") == "ccv_frequency":
            rows.append(dict(common, analyte="", qc_type="CCV frequency",
                             qc_level=f.injection_name, value=None, units="",
                             flag=f.issue or "", passed=0))
    # sample duplicates judged (2026-10-06: a failing Dup never reached
    # the gate either; a Dup also stands in for an LFSMD)
    for v in (getattr(batch, "dup_results", None) or []):
        rows.append(dict(common, analyte=v.get("analyte") or "", qc_type="Dup",
                         applies_to=v.get("parent") or "",
                         qc_level=v.get("injection_name") or "", value=v.get("rpd"),
                         units="% RPD", flag=v.get("issue") or "",
                         **_window(v),
                         passed=1 if v.get("passed") else 0))
    for v in (getattr(batch, "lcs_results", None) or []):
        rows.append(dict(common, analyte=v.get("analyte") or "", qc_type=v.get("qc_type") or "LFB",
                         qc_level=v.get("injection_name") or "", value=v.get("recovery"),
                         units="%", flag=v.get("issue") or "",
                         **_window(v),
                         passed=1 if v.get("passed") else 0))
    for res in (getattr(batch, "cal_results", None) or []):
        rows.append(dict(common, analyte=res.analyte, qc_type="Calibration",
                         qc_level=(res.concat_id or res.injection_name),
                         value=(res.pct_deviation * 100.0 if res.pct_deviation is not None else None),
                         units="% deviation",
                         **_window(_cal_window(res)),
                         flag=(res.flag.issue if res.flag else ""),
                         passed=0 if res.flag else 1))

    # Internal standard response
    for res in (getattr(batch, "is_results", None) or []):
        # concat_id, not injection_name. A real run repeats an injection NAME:
        # this export has three CCVs all called FDA-CCV-251020, distinguished
        # only by acquisition time. qc_level is part of the row's unique key,
        # so using the bare name collided and rolled the whole QC persist back.
        # concat_id is documented as "injection_name|yyyymmddHHMMSS (unique
        # key)" and existed for exactly this.
        rows.append(dict(common, analyte=res.is_compound, qc_type="IS",
                         _status=("active" if getattr(res, "configured", True) else "unevaluated"),
                         applies_to=res.injection_name or "",
                         qc_level=(res.concat_id or res.injection_name),
                         value=(res.pct_from_cal * 100.0
                                if res.pct_from_cal is not None else None),
                         units="% of ICAL avg",
                         **_window(_is_window(res)),
                         flag=(res.flag.issue if res.flag else ""),
                         passed=0 if res.flag else 1))
    return _unique_keys(rows)


def _blank_row(common, role, injection, analyte, conc, unit, lim, over):
    return dict(common, analyte=analyte, qc_type=role, qc_level=injection, value=conc, units=unit,
                # the rule that set this row's verdict
                limit_low=None, limit_high=(lim or {}).get("limit"),
                limit_basis=(("%s %s %g x RL (Blank limits)" % (
                    role, "below" if lim.get("at_limit") else "at most", lim.get("x_rl"))) if lim else
                    "%s not judged: the method sets it no limit" % role),
                flag=("above the blank limit" if over else ""),
                passed=0 if over else 1)


def _unique_keys(rows):
    """qc_results is unique on (batch, analyte, qc_type, qc_level) and one
    collision rolls back the WHOLE run's QC. An export may repeat an
    injection name (a re-injection under the same name, two blanks both
    called CCB): the later row gets " #2", " #3" rather than costing every
    other verdict."""
    seen = {}
    for r in rows:
        key = (r.get("analyte") or "", r.get("qc_type") or "", r.get("qc_level") or "")
        n = seen.get(key, 0) + 1
        seen[key] = n
        if n > 1:
            r["qc_level"] = "%s #%d" % (key[2], n)
            logger.warning("QC row key repeated for %s / %s / %s; stored as %r",
                           key[1], key[0], key[2], r["qc_level"])
    return rows


def _window(w):
    """qc_results' judged-window columns from a check's window ({lo, hi,
    basis}); empty when the check recorded none."""
    w = w or {}
    return {"limit_low": w.get("lo"), "limit_high": w.get("hi"),
            "limit_basis": w.get("basis") or ""}


def _cal_window(res):
    lim, r2 = getattr(res, "limit", None), getattr(res, "r2_min", None)
    parts = []
    if lim is not None:
        parts.append("%s within \u00b1%g %%" % (
            "Lowest calibrator" if getattr(res, "lowest", False) else "Calibrator", lim))
    if r2 is not None:
        parts.append("R\u00b2 at least %g" % r2)
    return {"lo": -lim if lim is not None else None, "hi": lim,
            "basis": "; ".join(parts)} if parts else None


def _is_window(res):
    if not getattr(res, "configured", True):
        return {"lo": None, "hi": None,
                "basis": "IS response not judged: the method sets no window"}
    lo, hi = getattr(res, "window_min", None), getattr(res, "window_max", None)
    if lo is None or hi is None:
        return None
    basis = "IS response %g-%g %% of the ICAL average" % (lo, hi)
    c_lo, c_hi = getattr(res, "ccv_min", None), getattr(res, "ccv_max", None)
    if c_lo is not None and c_hi is not None:
        basis += " and %g-%g %% of the bracket's CCV" % (c_lo, c_hi)
    return {"lo": lo, "hi": hi, "basis": basis}


def _calibration_rows(batch) -> list:
    """One row per analyte: the curve r² the instrument reported, and its
    points (`_levels`: one per calibrator: level, expected, calculated, %
    deviation, pass, response ratio). The points were never written, so no
    worker run showed a curve on the Calibrations page or Data Review's
    Calibration tab."""
    run_date = _run_date(batch)
    seen = {}
    rows_by = {}
    for r in (batch.injections or []):
        rows_by[(r.injection_name, r.compound_name)] = r
    points = {}
    calibrators = {}
    for res in (getattr(batch, "cal_results", None) or []):
        if res.r2 is not None:
            seen.setdefault(res.analyte, res.r2)
        row = rows_by.get((res.injection_name, res.analyte))
        calibrators.setdefault(res.analyte, []).append(
            (res.injection_name, getattr(row, "acquisition_datetime", None) if row is not None else None))
        exp = getattr(row, "expected_conc", None) if row is not None else None
        try:
            lvl = int(getattr(row, "level", None) or 0)
        except (TypeError, ValueError):
            lvl = 0
        points.setdefault(res.analyte, []).append({
            "level": lvl, "expected": exp, "calculated": res.calculated_conc,
            "pct_deviation": (res.pct_deviation * 100.0 if res.pct_deviation is not None else None),
            "passed": 0 if res.flag else 1,
            "limit_pct": getattr(res, "limit", None),
            "response_ratio": getattr(row, "response_ratio", None) if row is not None else None})
    out = []
    for analyte, r2 in sorted(seen.items()):
        pts = sorted(points.get(analyte) or [], key=lambda p: (p["expected"] is None, p["expected"] or 0))
        for n, p in enumerate(pts, 1):
            p["level"] = p["level"] or n             # a level the run did not number: its order
        exps = [p["expected"] for p in pts if p["expected"] is not None]
        out.append({
            "batch_id": batch.batch_id, "run_date": run_date, "analyte": analyte,
            "method": getattr(batch, "method_id", "") or "",
            "analyst": getattr(batch, "analyst", "") or "",
            "instrument_id": "", "equation": "", "fit_type": "", "weight_type": "",
            "r2": r2, "n_levels": len(pts),
            "min_level": min(exps) if exps else None, "max_level": max(exps) if exps else None,
            "cal_key": calibration_key(calibrators.get(analyte)),
            "_levels": pts})
    return out


def calibration_key(calibrators) -> str:
    """What identifies one curve: its calibrator
    injections' names and acquisition times. A later export that carries the
    same calibrators re-uses the curve; one shifted timestamp is a new curve.
    "" when any calibrator has no acquisition time: not identifiable, so the
    curve stays the worksheet's own."""
    import hashlib
    cals = list(calibrators or [])
    if not cals or any(ts is None for _n, ts in cals):
        return ""
    text = "\n".join(sorted("%s@%s" % (n, ts.strftime("%Y-%m-%dT%H:%M:%S")) for n, ts in cals))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def persist_qc_results(batch, db_path: str = None) -> int:
    """Write the run's QC verdicts. Replaces any previous rows for this batch,
    so a re-import supersedes rather than duplicating — the same contract
    `persist_injection_results` already honours."""
    path = db_path or DB_PATH
    rows = _qc_rows(batch)

    # A criterion the method never configured is filed as an UNEVALUATED QC
    # result rather than omitted. Omission is indistinguishable from "this QC
    # type was not run", and Data Review's gate already understands
    # `unevaluated` — it just had no producer. Filing it is what holds the
    # report and names the gap instead of releasing on silence.
    unevaluated = []
    for gap in (getattr(batch, "unconfigured", None) or []):
        unevaluated.append({
            "batch_id": batch.batch_id,
            # _run_date(), NOT str(batch.date). The latter yields
            # "2026-08-05 07:33:12.481922" while every other row and the
            # batches row the gate queries on use "%Y-%m-%d", so the
            # WHERE run_date=? predicate could never match these rows.
            "run_date": _run_date(batch),
            "analyte": gap.get("analyte") or "",
            "qc_type": gap.get("qc_type") or "",
            "method": gap.get("method_id") or "",
            "flag": gap.get("reason") or "",
            "passed": 0,
            "_status": "unevaluated",
        })

    persist_batch_row(batch, path)
    if not rows and not unevaluated:
        return 0
    conn = _connect(path)
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(qc_results)")}
        if not have:
            return 0
        conn.execute("DELETE FROM qc_results WHERE batch_id=?", (batch.batch_id,))
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        for r in list(rows) + unevaluated:
            status = r.pop("_status", "active")
            r = dict(r, result_status=status, created_at=now)
            for name in _required_columns(conn, "qc_results"):
                r.setdefault(name, "")
            keys = [k for k in r if k in have]
            conn.execute(
                "INSERT INTO qc_results ({0}) VALUES ({1})".format(
                    ",".join(keys), ",".join("?" * len(keys))),
                [r[k] for k in keys])
        conn.commit()
        try:
            conn.execute("PRAGMA optimize")      # keep the planner's statistics current
        except Exception:                        # noqa: BLE001
            pass
    except Exception:
        # A failed insert rolls back, which would leave the PREVIOUS run's rows
        # in place looking current -- Data Review would gate on stale QC and
        # say nothing. Clear the batch instead: "no QC record" blocks the gate,
        # which is the honest state, and re-raise so the run reports it.
        conn.rollback()
        try:
            conn.execute("DELETE FROM qc_results WHERE batch_id=?",
                         (batch.batch_id,))
            conn.commit()
            # and say so where the gate reads: an empty summary used to read
            # as a pass
            conn.execute(
                "INSERT INTO qc_results (batch_id, run_date, analyte, qc_type, qc_level, "
                "method, flag, passed, result_status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (batch.batch_id, _run_date(batch), "", "QC store", "",
                 getattr(batch, "method_id", "") or "",
                 "The run's QC results could not be stored; reprocess the run.",
                 0, "unevaluated", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")))
            conn.commit()
            logger.error("QC persist failed for %s; cleared its rows rather "
                         "than leaving the previous run's in place.",
                         batch.batch_id)
        except Exception:                                   # noqa: BLE001
            logger.exception("could not clear stale QC rows for %s",
                             batch.batch_id)
        raise
    finally:
        conn.close()
    return len(rows) + len(unevaluated)


def persist_calibrations(batch, db_path: str = None) -> int:
    """Write the run's calibration curves for the Calibrations page and the
    control charts. A curve is stored ONCE: when its
    calibrators (cal_key) match a stored curve of the same analyte and method,
    the worksheet is linked to it (calibration_uses) and nothing is added --
    an export that re-uses a calibration, or the same file imported again,
    keeps the curve and its approval. A changed curve is a new one, pending
    review. A curve without a key stays the worksheet's own and is replaced
    on re-import, as before. Curves no worksheet uses any more are dropped."""
    path = db_path or DB_PATH
    rows = _calibration_rows(batch)
    if not rows:
        return 0
    conn = _connect(path)
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(calibrations)")}
        if not have:
            return 0
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        bid = batch.batch_id
        old_uses = dict((r[0], (r[1], r[2])) for r in conn.execute(
            "SELECT calibration_id, status, notes FROM calibration_uses WHERE batch_id=?", (bid,)))
        conn.execute("DELETE FROM calibration_uses WHERE batch_id=?", (bid,))
        # the worksheet's own unkeyed curves are replaced (re-reviewed)
        conn.execute("DELETE FROM calibration_levels WHERE calibration_id IN (SELECT id FROM "
                     "calibrations WHERE batch_id=? AND cal_key='')", (bid,))
        conn.execute("DELETE FROM calibrations WHERE batch_id=? AND cal_key=''", (bid,))
        lv_have = {c[1] for c in conn.execute("PRAGMA table_info(calibration_levels)")}
        used = []
        for r in rows:
            levels = r.pop("_levels", [])
            if r.get("cal_key"):
                found = conn.execute(
                    "SELECT id FROM calibrations WHERE cal_key=? AND analyte=? AND method=? "
                    "ORDER BY id LIMIT 1", (r["cal_key"], r["analyte"], r["method"])).fetchone()
                if found is not None:
                    used.append(found[0])
                    continue
            r = dict(r, created_at=now)
            for name in _required_columns(conn, "calibrations"):
                r.setdefault(name, "")
            keys = [k for k in r if k in have]
            cur = conn.execute(
                "INSERT INTO calibrations ({0}) VALUES ({1})".format(
                    ",".join(keys), ",".join("?" * len(keys))),
                [r[k] for k in keys])
            used.append(cur.lastrowid)
            for p in levels:
                p = dict(p, calibration_id=cur.lastrowid)
                lk = [k for k in p if k in lv_have]
                conn.execute("INSERT INTO calibration_levels ({0}) VALUES ({1})".format(
                    ",".join(lk), ",".join("?" * len(lk))), [p[k] for k in lk])
        run_date = _run_date(batch)
        for cid in used:
            # a worksheet's rejection of a curve it keeps using stands
            status, notes = old_uses.get(cid, ("", ""))
            conn.execute("INSERT OR IGNORE INTO calibration_uses (batch_id, calibration_id, run_date, "
                         "status, notes, created_at) VALUES (?,?,?,?,?,?)",
                         (bid, cid, run_date, status or "", notes or "", now))
        from .addon import load
        load("qc_schema").drop_unused_calibrations(conn)
        conn.commit()
    finally:
        conn.close()
    return len(rows)
