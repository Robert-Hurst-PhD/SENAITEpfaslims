"""What is wrong with a run's SHAPE, compared with its plan: each problem holds release until a reviewer clears it with a
note or the run is fixed.

    problems(planned, rows, spikes) -> [reason]

  planned  the Run Builder's planned injection names, in order ([] = a run
           built without the Run Builder: nothing to compare)
  rows     the export's rows (injection_name, acquisition_datetime)
  spikes   the extraction batch's spike record {injection: {"parent", ...}}

A missing required QC (LRB, LFB), a missing calibrator and a missing parent
sample are all a PLANNED injection that did not run; a renamed or re-made
injection is one that ran without being planned. Found by the end-to-end
fast tier: these were written to the worker log only.

Pure; Python 3.
"""
from __future__ import annotations

QC_TYPE = "Run plan"


def problems(planned, rows, spikes=None):
    if not planned:
        return []
    out = []
    times = {}
    for r in rows:
        times.setdefault(r.injection_name, set()).add(getattr(r, "acquisition_datetime", None))
    ran = list(times)
    planned_set = set(planned)
    for name in planned:
        if name not in times:
            out.append("%s was planned but did not run" % name)
    for name in sorted(n for n in ran if n not in planned_set):
        out.append("%s ran but is not in the run plan" % name)
    for name in sorted(ran):
        stamps = [t for t in times[name] if t is not None]
        if len(stamps) > 1:
            out.append("%s was injected %d times under one name" % (name, len(stamps)))
    for inj, entry in sorted((spikes or {}).items()):
        parent = (entry or {}).get("parent") or ""
        if inj in times and parent and parent not in times:
            out.append("%s: its parent sample %s is not in the run" % (inj, parent))
    return out
