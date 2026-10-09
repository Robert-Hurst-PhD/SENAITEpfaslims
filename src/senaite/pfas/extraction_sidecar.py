# -*- coding: utf-8 -*-
"""The run's extraction record, built from the SENAITE guided extraction
(phase 1).

The pipeline worker reads `{run_stem}_extraction.json` beside the instrument
CSV for the run parameters (worksheet, batch, method, matrix, analyst) and
for the extraction pedigree it prints in the batch report (steps, lots used,
sign-off). That file used to come from the separate extraction-ui tablet
service, with its own reagent catalogue -- a second inventory. The guided
extraction is now the only extraction record, so the Run Builder writes the
file from it when the export is uploaded.

    build_sidecar(session, stage_names, ...) -> dict (the worker's shape)
    extraction_progress(session)             -> {"started", "completed",
                                                  "analyst"} or None

Pure, no imports beyond the standard library. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

SOURCE = u"senaite-guided-extraction"


def _ordered_stages(session):
    stages = (session or {}).get("stages") or {}

    def key(k):
        try:
            return int(k)
        except (TypeError, ValueError):
            return 10 ** 6
    return [(k, stages[k] or {}) for k in sorted(stages, key=key)]


def build_sidecar(session, stage_names, worksheet_id=u"", senaite_batch_id=u"",
                  matrix=u"", client_uid=u""):
    """The sidecar for one run. `stage_names` = {stage order (str): name}.

    `worksheet_id` becomes `batch_id` (the worker's join key with Data Review,
    pipeline.run_pipeline docstring); left empty, the worker falls back to the
    CSV name and says so. Lots without a lot number are left out: a row the
    chemist did not fill is not a lot used."""
    session = session or {}
    analyst = session.get(u"analyst") or u""
    steps, scans = [], []
    for order, st in _ordered_stages(session):
        name = (stage_names or {}).get(u"%s" % order) or u"Stage %s" % order
        at = st.get(u"completed_at") or u""
        by = st.get(u"analyst") or analyst
        detail = st.get(u"deviations") or u""
        if st.get(u"warnings"):                 # what the note had to explain
            detail = u"%s [needed a note: %s]" % (detail, u"; ".join(st[u"warnings"]))
        steps.append({u"at": at, u"step": name, u"detail": detail.strip(),
                      u"value": u"", u"by": by})
        for rg in st.get(u"reagents") or []:
            lot = (rg.get(u"lot") or u"").strip()
            if not lot:
                continue
            scans.append({u"at": at, u"step": name,
                          u"name": rg.get(u"name") or rg.get(u"role") or u"",
                          u"role": rg.get(u"role") or u"",
                          u"catalog_number": rg.get(u"cat_number") or u"",
                          u"lot_number": lot,
                          u"expiry_date": rg.get(u"expiry") or u"",
                          u"inventory_uid": rg.get(u"inventory_uid") or u"",
                          u"is_new_lot": False,
                          u"by": by})
    signoffs = []
    if session.get(u"finalized"):
        signoffs.append({u"role": u"Analyst",
                         u"initials": session.get(u"finalized_by") or analyst,
                         u"at": session.get(u"finalized_at") or u""})
    return {
        u"source": SOURCE,
        u"batch_id": worksheet_id or u"",
        u"senaite_batch_id": senaite_batch_id or u"",
        u"analyst": analyst,
        u"matrix": matrix or u"",
        u"method_id": session.get(u"method_id") or u"",
        u"client_uid": client_uid or u"",
        u"started": session.get(u"started_at") or u"",
        u"completed": (session.get(u"finalized_at") or None)
        if session.get(u"finalized") else None,
        u"steps": steps,
        u"reagent_scans": scans,
        u"signoffs": signoffs,
    }


def extraction_progress(session):
    """None when no extraction was started; otherwise when it started, when
    it was finalized (None while in progress) and by whom."""
    if not session or not session.get(u"started_at"):
        return None
    return {u"started": session.get(u"started_at") or u"",
            u"completed": (session.get(u"finalized_at") or u"")
            if session.get(u"finalized") else None,
            u"analyst": session.get(u"analyst") or u""}
