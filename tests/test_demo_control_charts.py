# -*- coding: utf-8 -*-
"""Example control-chart data (GAPS §97): marked, removable, and removing it
never touches laboratory rows."""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "senaite", "pfas"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import qc_schema  # noqa: E402
import demo_control_charts as demo  # noqa: E402
import datetime  # noqa: E402


def _db():
    conn = sqlite3.connect(":memory:")
    qc_schema.ensure(conn)
    conn.execute("INSERT INTO batches (batch_id, run_date, created_at, updated_at) "
                 "VALUES ('WS-0001', '2026-06-24', 'x', 'x')")
    conn.execute("INSERT INTO qc_results (batch_id, run_date, analyte, qc_type, value, created_at) "
                 "VALUES ('WS-0001', '2026-06-24', 'PFOA', 'LFSM', 97.0, 'x')")
    return conn


def test_every_example_point_is_marked_and_enough_for_a_chart():
    conn = _db()
    n = demo.write(conn, datetime.date(2026, 9, 28))
    rows = conn.execute("SELECT batch_id, analyst, instrument_id FROM qc_results "
                        "WHERE batch_id != 'WS-0001'").fetchall()
    assert len(rows) == n == demo.RUNS * len(demo.ANALYTES) * len(demo.SERIES)
    assert all(b.startswith(demo.PREFIX) and a == "DEMO" and i == "DEMO-LCMS" for b, a, i in rows)
    notes = [r[0] for r in conn.execute("SELECT notes FROM batches WHERE batch_id LIKE 'DEMO-CC-%'")]
    assert len(notes) == demo.RUNS and all("not laboratory results" in x for x in notes)
    per = conn.execute("SELECT COUNT(*) FROM qc_results WHERE analyte='PFOA' AND qc_type='LFSM' "
                       "AND batch_id LIKE 'DEMO-CC-%'").fetchone()[0]
    assert per >= 20


def test_the_planted_westgard_events_are_there():
    conn = _db()
    demo.write(conn, datetime.date(2026, 9, 28))
    v = conn.execute("SELECT value FROM qc_results WHERE batch_id='DEMO-CC-18' AND analyte='PFOA' "
                     "AND qc_type='LFSM'").fetchone()[0]
    assert v == round(98.0 + 3.4 * 6.0, 4)
    pfos = [r[0] for r in conn.execute("SELECT value FROM qc_results WHERE analyte='PFOS' AND "
                                       "qc_type='CCV' AND batch_id IN ('DEMO-CC-21','DEMO-CC-22')")]
    assert all(x > 1.5 + 2 * 4.0 for x in pfos) and len(pfos) == 2


def test_remove_and_rewrite_touch_only_the_examples():
    conn = _db()
    demo.write(conn, datetime.date(2026, 9, 28))
    demo.remove(conn)
    demo.write(conn, datetime.date(2026, 9, 28))      # idempotent: replaced, not doubled
    assert conn.execute("SELECT COUNT(*) FROM batches WHERE batch_id LIKE 'DEMO-CC-%'").fetchone()[0] == demo.RUNS
    demo.remove(conn)
    assert conn.execute("SELECT COUNT(*) FROM qc_results").fetchone()[0] == 1
    assert conn.execute("SELECT batch_id FROM batches").fetchall() == [("WS-0001",)]
