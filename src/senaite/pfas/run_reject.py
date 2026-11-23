# -*- coding: utf-8 -*-
"""Rejecting a run at Data Review.

The verifier gives a reason and a disposition:

  retest   the samples are run again: the run's QC record stays in the
           control charts, the Calibration Archive and the blank
           comparisons;
  void     the run itself is invalid: its QC rows are voided and its
           calibrations leave the archive (QCResultStore.void_run).

Either way the worksheet is rejected (core's terminal state) and each of its
results awaiting verification is retracted; the retest SENAITE makes is taken
off the rejected worksheet, so it goes on a new one. The order matters: the
worksheet is rejected first, because a retest added to a worksheet still
awaiting verification rolls it back to open, where reject is no longer an
exit. A CAR is offered afterwards (the page's button), never raised here.

    DISPOSITIONS                 (value, label)
    refusal(reason, disposition) -> why the form cannot be taken, or u""
    reject(ws, do, state_of)     -> the retests made, off the worksheet
    record(by, at, reason, disposition, retests) -> the stored record

Python 2.7 and 3; no Zope import (the caller passes the workflow).
"""
from __future__ import absolute_import, unicode_literals

# the worksheet's annotation holding the rejection's record (JSON)
REJECT_KEY = "senaite.pfas.run_reject"

RETEST, VOID = u"retest", u"void"
DISPOSITIONS = ((RETEST, u"Retest requested"), (VOID, u"Run voided"))
LABELS = dict(DISPOSITIONS)
# a routine result awaiting verification: what a retest replaces
AWAITING = u"to_be_verified"


def refusal(reason, disposition):
    """Why a rejection cannot be taken: a reason and a disposition are both
    required. u"" when it can."""
    if not (u"%s" % (reason or u"")).strip():
        return u"Give a reason for rejecting the run."
    if disposition not in LABELS:
        return u"Choose Retest requested or Run voided."
    return u""


def reject(ws, do, state_of):
    """Reject the worksheet, then retract each routine result awaiting
    verification and take its retest off the worksheet. `do(obj,
    transition)` is the workflow's (True when done); `state_of(obj)` the
    review state. Returns the retests; ValueError when the worksheet does
    not reject (nothing else is done)."""
    if not do(ws, u"reject"):
        raise ValueError(u"The worksheet could not be rejected.")
    retests = []
    for analysis in list(ws.getAnalyses() or []):
        if getattr(analysis, "portal_type", u"") != u"Analysis" or state_of(analysis) != AWAITING:
            continue
        if not do(analysis, u"retract"):
            continue
        retest = analysis.getRetest()
        if retest is None:
            continue
        if retest.getWorksheet() is not None:
            ws.removeAnalysis(retest)
        retests.append(retest)
    return retests


def record(by, at, reason, disposition, retests):
    """The rejection as stored on the worksheet: who, when, why, the
    disposition and the retests' ids."""
    return {u"by": by, u"at": at, u"reason": (u"%s" % reason).strip(), u"disposition": disposition,
            u"retests": [r.getId() for r in retests]}
