# -*- coding: utf-8 -*-
"""
senaite.pfas.qc — QC rule store, control charting, and result storage.

Key modules:
  rules.py        — instrument verification rule store (QCRulesStore, get_rules)
  store.py        — QC result persistence (QCResultStore)
  control_chart.py — Levey-Jennings chart data extraction + Chart.js serialisation

QC execution runs in the pipeline worker (pfas_pipeline/qc_engine.py),
not inside Plone.  Rules and results bridge via the shared /data/qc/ volume.
"""
