# -*- coding: utf-8 -*-
"""A dilution appended to the neat result as a SENAITE retest (DECISIONS
2026-10-02 "Dilutions: SENAITE retest").

The worker pushes the NEAT, above-LOQ reading onto the analysis and hands the
dilution's result to the add-on, which keeps it on the analysis (record()).
When the Analyst submits the worksheet in Data Review, the neat analysis is
submitted and a retest of it is created carrying the dilution's result, the
dilution's own analysis time as its capture date, and a remark naming both
injections and both times (retest_plan()). The Manager verifies both; the
certificate reports the retest.

    KEY                                  annotation key on the analysis
    record(body, recorded_at)            -> (dict, "") or (None, reason)
    retest_plan(rec)                     -> {"result", "captured", "remarks"}

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

KEY = u"senaite.pfas.dilution_result"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _factor_text(f):
    v = _num(f)
    if v is None or v <= 0:
        return u""
    return u"%g-fold" % v


def record(body, recorded_at):
    """The dilution as kept on the analysis, or (None, why) when it cannot
    stand as a result: it needs an injection, its analysis time, and a result
    (a number, or the instrument's qualifier when it read nothing)."""
    body = body or {}
    injection = (body.get("injection") or u"").strip()
    analysed_at = (body.get("analysed_at") or u"").strip()
    result, qualifier = _num(body.get("result")), (body.get("qualifier") or u"").strip()
    if not injection:
        return None, u"no dilution injection named"
    if not analysed_at:
        return None, u"the dilution has no analysis time"
    if result is None and not qualifier:
        return None, u"the dilution has no result"
    return {
        "injection": injection, "analysed_at": analysed_at,
        "result": result, "qualifier": qualifier,
        "flags": [u"%s" % f for f in body.get("flags") or []],
        "factor": _num(body.get("factor")),
        "neat_result": _num(body.get("neat_result")),
        "neat_qualifier": (body.get("neat_qualifier") or u"").strip(),
        "neat_injection": (body.get("neat_injection") or u"").strip(),
        "neat_analysed_at": (body.get("neat_analysed_at") or u"").strip(),
        "recorded_at": recorded_at or u"",
        "retest_uid": u"",
    }, u""


def retest_plan(rec):
    """What the retest carries: the dilution's result (its qualifier when it
    has no number), the dilution's analysis time, and a remark that names the
    dilution and the neat reading it replaces, each with its own time."""
    rec = rec or {}
    result = u"%g" % rec["result"] if rec.get("result") is not None else rec.get("qualifier") or u""
    neat = (u"%g" % rec["neat_result"] if rec.get("neat_result") is not None else u"") + \
        (u" (%s)" % rec["neat_qualifier"] if rec.get("neat_qualifier") else u"")
    parts = [u"Dilution {0} ({1}) analysed {2}".format(
        _factor_text(rec.get("factor")) or u"factor not recorded",
        rec.get("injection") or u"?", rec.get("analysed_at") or u"?")]
    parts.append(u"replaces neat {0} ({1}) analysed {2}".format(
        neat.strip() or u"reading", rec.get("neat_injection") or u"?",
        rec.get("neat_analysed_at") or u"?"))
    if rec.get("flags"):
        parts.append(u" ".join(rec["flags"]))
    return {"result": result, "captured": rec.get("analysed_at") or u"",
            "remarks": u"; ".join(parts)}
