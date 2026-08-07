# -*- coding: utf-8 -*-
"""
senaite.pfas.qc — QC rule store, control charting, and result storage.

Key modules:
  rules.py        — instrument verification rule store (QCRulesStore, get_rules)
  store.py        — QC result persistence (QCResultStore)
  (control_chart.py was removed 2026-08-07: 584 lines, zero importers, and
   browser/controlchart.py implements the same six Westgard rules inline.
   Its render_to_png_bytes had no caller either -- see GAPS.md if a PNG
   export is ever wanted.)

QC execution runs in the pipeline worker (pfas_pipeline/qc_engine.py),
not inside Plone.  Rules and results bridge via the shared /data/qc/ volume.
"""
