# -*- coding: utf-8 -*-
"""Example points for the control charts (GAPS §97).

Lab, 2026-10-03: "Control charts seem okay but I need some example data in
them." A Levey-Jennings chart needs ~20 points before its mean and SD mean
anything; the live pool has about two per analyte. This writes 25 weekly
EXAMPLE runs for one method into the control-chart pool so every chart shows
how it behaves -- including two planted Westgard events (a 1-3s point and a
2-2s pair) so the rule markers can be seen.

Everything it writes is marked as an example, never as laboratory data:
  batch ids      DEMO-CC-01 ... DEMO-CC-25 (the chart shows an "Example data"
                 banner whenever a DEMO- point is on it)
  analyst        DEMO          instrument   DEMO-LCMS
  batch notes    "Example control-chart data ... not laboratory results"
Values are generated (fixed seed), not measured, and cite no source.

Run inside the SENAITE container (Python 2.7) or anywhere with the DB file:

  docker exec senaite_pfas-senaite-1 python /addon/tools/demo_control_charts.py
  docker exec senaite_pfas-senaite-1 python /addon/tools/demo_control_charts.py --remove

--remove deletes exactly the DEMO-CC-* rows (and any chart notes on them).
Idempotent: writing again replaces the previous example set.
"""
from __future__ import absolute_import, print_function, unicode_literals

import argparse
import datetime
import random
import sqlite3

DB = "/data/qc/pfas_qc_results.db"
PREFIX = "DEMO-CC-"
METHOD = "FDA_32PFAS"
ANALYTES = ("PFOA", "PFOS", "PFHxS", "PFNA")
RUNS = 25
NOTE = ("Example control-chart data (tools/demo_control_charts.py) -- generated, "
        "not laboratory results")

# qc_type -> (qc_level, units, mean, sd); the chart's own units label applies.
SERIES = {
    "CCV":  ("CCV-1", "%", 1.5, 4.0),        # % deviation from the true value
    "LFSM": ("LFSM-1", "%", 98.0, 6.0),      # % recovery
    "MB":   ("MB-1", "ng/mL", 0.004, 0.003),  # blank concentration
}
# planted events: (qc_type, analyte, run index) -> SDs from the mean
PLANTED = {("LFSM", "PFOA", 17): 3.4,                         # 1-3s
           ("CCV", "PFOS", 20): 2.3, ("CCV", "PFOS", 21): 2.4}  # 2-2s


def remove(conn):
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM qc_results WHERE batch_id LIKE ?", (PREFIX + "%",))]
    if ids:
        marks = ",".join("?" * len(ids))
        try:
            conn.execute("DELETE FROM chart_annotations WHERE result_id IN (%s)" % marks, ids)
        except sqlite3.OperationalError:
            pass                              # older DB without chart notes
        conn.execute("DELETE FROM qc_results WHERE id IN (%s)" % marks, ids)
    conn.execute("DELETE FROM batches WHERE batch_id LIKE ?", (PREFIX + "%",))
    return len(ids)


def write(conn, end):
    rng = random.Random(2026)
    now = datetime.datetime.utcnow().isoformat()
    n = 0
    for i in range(RUNS):
        batch = "%s%02d" % (PREFIX, i + 1)
        day = (end - datetime.timedelta(days=7 * (RUNS - 1 - i))).isoformat()
        conn.execute(
            "INSERT INTO batches (batch_id, run_date, analyst, instrument_id, method, "
            "status, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (batch, day, "DEMO", "DEMO-LCMS", METHOD, "complete", NOTE, now, now))
        for qc, (level, units, mean, sd) in sorted(SERIES.items()):
            for kw in ANALYTES:
                z = PLANTED.get((qc, kw, i))
                v = mean + (z if z is not None else rng.gauss(0, 1)) * sd
                if qc == "MB":
                    v = max(v, 0.0)
                conn.execute(
                    "INSERT INTO qc_results (batch_id, run_date, analyte, qc_type, qc_level, "
                    "method, analyst, instrument_id, value, units, flag, passed, "
                    "result_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (batch, day, kw, qc, level, METHOD, "DEMO", "DEMO-LCMS", round(v, 4),
                     units, "", 0 if (z or 0) >= 3 else 1, "active", now))
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=DB)
    ap.add_argument("--remove", action="store_true", help="delete the example set only")
    ap.add_argument("--end", default="2026-09-28", help="date of the last example run")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    try:
        gone = remove(conn)
        if args.remove:
            conn.commit()
            print("removed %d example points" % gone)
            return
        end = datetime.datetime.strptime(args.end, "%Y-%m-%d").date()
        made = write(conn, end)
        conn.commit()
        print("wrote %d example points in %d DEMO runs (%s)" % (made, RUNS, METHOD))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
