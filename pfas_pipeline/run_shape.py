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




def time_order_problems(rows, role_of):
    """Injections the instrument's clock places before the run's first
    calibrator: quantified against a curve that did not exist yet (an FDA
    example export stamps its CCVs, blank and samples a year before its
    calibrators, and every CCV bracketed and passed). Independent of the
    order the export lists its rows in, which need not be the run order
    (rows are judged in acquisition order). Every run is checked, planned or
    not; a run without calibrators or acquisition times is not.

    A blank (system, solvent or method blank) may open a run before the
    curve -- the Run Builder's default sequence starts with one -- so blanks
    are not named; CCVs, ICVs, samples and spiked QC are.

    rows     the run's rows (every export of the run)
    role_of  injection name -> role ("CAL" for a calibrator)
    """
    from .qc_engine import BLANK_ROLES
    when, order = {}, []
    for r in rows:
        t = getattr(r, "acquisition_datetime", None)
        if t is None:
            continue
        name = r.injection_name
        if name not in when:
            order.append(name)
            when[name] = t
        elif t < when[name]:
            when[name] = t
    cals = [when[n] for n in order if role_of(n) == "CAL"]
    if not cals:
        return []
    start = min(cals)
    return ["%s was acquired %s, before the run's first calibrator (%s): "
            "the clock contradicts the run order" % (n, _stamp(when[n]), _stamp(start))
            for n in sorted(order, key=lambda n: when[n])
            if role_of(n) != "CAL" and role_of(n) not in BLANK_ROLES and when[n] < start]


def _stamp(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")
