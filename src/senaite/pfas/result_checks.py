# -*- coding: utf-8 -*-
"""Do a worksheet's core results match the method and the pipeline? (core
integration)

Three questions Data Review answers from what core holds and what the worker
recorded in its push log (pfas_pipeline/push_log.py):

    not written     a result the worker could not put on a core analysis: no
                    sample with that Client Sample ID, or the sample has no
                    analysis for the analyte
    not judged      a core result the worker did not write, or that differs
                    from what it wrote: typed by hand (Manage Results), so the
                    pipeline's QC never saw it
    panel           a sample's analyses that differ from its method x matrix
                    panel (the Analyte x Matrix table): analytes missing from
                    the sample, or analytes the panel leaves out

Pure: Python 2.7 and 3.

    samples  [{"uid", "id", "panel": [keyword] | None, "allowed_extra": set,
               "format": (sig figs, rounding rule) | None,
               "analyses": [{"uid", "keyword", "result", "dilution_retest"}]}]
             format: how the certificate states a result; the pipeline's value
             in a "changed after" note is shown that way (it is stored as the
             worker's float, e.g. 1445.1000000000001)
             dilution_retest: a retest the dilution handover created at
             submission (dilution_retests.py) -- the pipeline's value, written
             there by the add-on, so never "not judged"
    pushes   [{"injection", "sample_uid", "analysis_uid", "analyte", "keyword",
               "value", "ok", "reason"}]   (empty: no run recorded its pushes)
"""
from __future__ import absolute_import, unicode_literals


def _same(a, b):
    a, b = ("%s" % (a if a is not None else u"")).strip(), ("%s" % (b if b is not None else u"")).strip()
    try:
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))
    except (TypeError, ValueError):
        return a == b


def _shown(value, fmt):
    """The pushed value as the certificate states it, by the lab's rounding."""
    if not fmt:
        return value
    try:
        from senaite.pfas import rounding
    except ImportError:                                     # tests, outside Plone
        import rounding
    text = rounding.round_sig(value, fmt[0], fmt[1])
    return text if text is not None else value


def check(samples, pushes):
    out = {"pushes_recorded": bool(pushes), "not_written": [], "not_judged": [], "panel": []}
    for p in pushes or []:
        if not p.get("ok"):
            out["not_written"].append({"injection": p.get("injection") or u"",
                                       "analyte": p.get("analyte") or u"",
                                       "reason": p.get("reason") or u""})
    written = dict((p.get("analysis_uid"), p) for p in pushes or [] if p.get("ok") and p.get("analysis_uid"))
    for s in samples:
        have = set()
        for a in s.get("analyses") or []:
            have.add(a.get("keyword"))
            result = a.get("result")
            if not pushes or result in (None, u"", "") or a.get("dilution_retest"):
                continue
            push = written.get(a.get("uid"))
            if push is None:
                out["not_judged"].append({"sample": s.get("id"), "keyword": a.get("keyword"),
                                          "result": result, "why": u"not written by the pipeline"})
            elif not _same(result, push.get("value")):
                out["not_judged"].append({"sample": s.get("id"), "keyword": a.get("keyword"),
                                          "result": result,
                                          "why": u"changed after the pipeline wrote %s"
                                                 % _shown(push.get("value"), s.get("format"))})
        panel = s.get("panel")
        if panel is None:
            continue
        missing = [k for k in panel if k not in have]
        extra = sorted(k for k in have if k not in set(panel) and k not in (s.get("allowed_extra") or set()))
        if missing or extra:
            out["panel"].append({"sample": s.get("id"), "missing": missing, "extra": extra})
    return out
