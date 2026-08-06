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

    run_date = _run_date(batch)
    method = getattr(batch, "method_id", "") or ""
    analyst = getattr(batch, "analyst", "") or ""
    dilutions = getattr(batch, "dilutions", None) or {}
    common = {"batch_id": batch.batch_id, "run_date": run_date,
              "method": method, "analyst": analyst, "instrument_id": ""}

    rows = []

    # LFSM / LFSMD — percent recovery and RPD, the numbers the gate checks
    for res in (getattr(batch, "lfsm_results", None) or []):
        rows.append(dict(common, analyte=res.analyte, qc_type="LFSM",
                         qc_level="", value=res.recovery_pct, units="%",
                         flag=(res.flag.issue if res.flag else ""),
                         passed=0 if res.flag else 1))
    for res in (getattr(batch, "lfsmd_results", None) or []):
        rows.append(dict(common, analyte=res.analyte, qc_type="LFSMD",
                         qc_level="RPD", value=res.rpd_pct, units="%",
                         flag=(res.flag.issue if res.flag else ""),
                         passed=0 if res.flag else 1))

    # Method blank — the measured concentration IS the result being judged
    flagged = {(f.injection_name, f.analyte) for f in (batch.qc_flags or [])}
    # EVERY blank is checked for contamination, not only the method blank. A
    # matrix blank or reagent blank above the reporting limit is the same
    # finding and was previously never judged at all — those roles did not
    # exist, so they classified as client samples.
    for r in (batch.injections or []):
        blank_role = classify_injection(r.injection_name, dilutions)
        if blank_role not in ("MB", "MxB", "LRB", "CCB"):
            continue
        if r.compound_type and r.compound_type != "Analyte":
            continue
        conc = reported_conc(r)
        over = (conc is not None and r.reporting_limit is not None
                and conc >= r.reporting_limit)
        rows.append(dict(common, analyte=r.compound_name, qc_type=blank_role,
                         qc_level="", value=conc, units="ng/mL",
                         flag=("over reporting limit" if over else ""),
                         passed=0 if over else 1))

    # Internal standard response
    for res in (getattr(batch, "is_results", None) or []):
        # concat_id, not injection_name. A real run repeats an injection NAME:
        # this export has three CCVs all called FDA-CCV-251020, distinguished
        # only by acquisition time. qc_level is part of the row's unique key,
        # so using the bare name collided and rolled the whole QC persist back.
        # concat_id is documented as "injection_name|yyyymmddHHMMSS (unique
        # key)" and existed for exactly this.
        rows.append(dict(common, analyte=res.is_compound, qc_type="IS",
                         qc_level=(res.concat_id or res.injection_name),
                         value=(res.pct_from_cal * 100.0
                                if res.pct_from_cal is not None else None),
                         units="% of ICAL avg",
                         flag=(res.flag.issue if res.flag else ""),
                         passed=0 if res.flag else 1))
    return rows


def _calibration_rows(batch) -> list:
    """One row per analyte: the curve r² the instrument reported."""
    run_date = _run_date(batch)
    seen = {}
    for res in (getattr(batch, "cal_results", None) or []):
        if res.r2 is None:
            continue
        seen.setdefault(res.analyte, res.r2)
    return [{
        "batch_id": batch.batch_id, "run_date": run_date, "analyte": analyte,
        "method": getattr(batch, "method_id", "") or "",
        "analyst": getattr(batch, "analyst", "") or "",
        "instrument_id": "", "equation": "", "fit_type": "", "weight_type": "",
        "r2": r2,
    } for analyte, r2 in sorted(seen.items())]


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
    control charts."""
    path = db_path or DB_PATH
    rows = _calibration_rows(batch)
    if not rows:
        return 0
    conn = _connect(path)
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(calibrations)")}
        if not have:
            return 0
        conn.execute("DELETE FROM calibrations WHERE batch_id=?", (batch.batch_id,))
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        for r in rows:
            r = dict(r, created_at=now)
            for name in _required_columns(conn, "calibrations"):
                r.setdefault(name, "")
            keys = [k for k in r if k in have]
            conn.execute(
                "INSERT INTO calibrations ({0}) VALUES ({1})".format(
                    ",".join(keys), ",".join("?" * len(keys))),
                [r[k] for k in keys])
        conn.commit()
    finally:
        conn.close()
    return len(rows)
