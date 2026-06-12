# -*- coding: utf-8 -*-
"""
senaite.pfas.qc — QC engine, control charting, and result storage.

Quick-start (after running a batch):

    from senaite.pfas.qc.engine import run_batch_qc
    from senaite.pfas.qc.store import QCResultStore
    from senaite.pfas.qc.control_chart import (
        extract_qc_points_from_batch, build_chart_data, to_chart_js_dict
    )
    import datetime

    result = run_batch_qc(df, batch_id="2026-06-10-001")

    # Persist QC points for control charting
    store = QCResultStore()
    run_date = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    points = extract_qc_points_from_batch(result, run_date=run_date)
    store.add_results_bulk(points)

    # Build a Levey-Jennings chart for CCV PFOA
    rows = store.get_chart_data("PFOA", "CCV")
    chart = build_chart_data(rows, analyte="PFOA", qc_type="CCV", qc_level="",
                              units="% Deviation")
    chart_dict = to_chart_js_dict(chart)  # JSON-ready for Chart.js

The browser view at @@pfas-control-chart on the SENAITE portal reads the same
SQLite database and renders the chart interactively using Chart.js.
"""
