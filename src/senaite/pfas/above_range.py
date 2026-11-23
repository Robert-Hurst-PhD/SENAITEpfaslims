# -*- coding: utf-8 -*-
"""A result above the calibration range with no dilution (ALoQ).

No result is reported extrapolated above the range. The worker writes the
analysis's Result as ALoQ, the word a result with no reportable number
carries, and hands the add-on the result's record (record()):

    limit      the top of the calibration range on the sample basis, the
               bound the certificate prints the result above ("> 20.0")
    reading    the extrapolated reading, where the curve gives one: kept
               for the reviewer, never reported
    injection  the injection it was read in

The record is read only while the analysis's Result is still ALoQ
(current()): a later push that writes anything else leaves it unread.

The certificate prints "> limit" with the reporting rule's code E
(coa_format); the EDD issues E through the state's qualifier map. Release
waits on each one: the worker files a failing QC result of QC_TYPE for it,
and Data Review lists it until a dilution is run (the next push reports the
dilution, with D and without E) or the reviewer records the reason to report
it with E (reason_record(), kept on the worksheet under REASONS_KEY by
reason_key()).

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.rounding import number as _num

KEY = u"senaite.pfas.above_range"
REASONS_KEY = u"senaite.pfas.above_range_reasons"
# the Result an above-range result with no dilution is written as
ALOQ_TEXT = u"ALoQ"
# the reporting rule's code (qc_qualification "above_range")
E_CODE = u"E"
# the QC result that holds release until a dilution or a reason
QC_TYPE = u"Above the calibration range"


def is_aloq(result):
    """True for a Result written as ALoQ."""
    return (u"%s" % (result if result is not None else u"")).strip().lower() == ALOQ_TEXT.lower()


def record(body, recorded_at):
    """The record kept on the analysis, or (None, why): it needs the top of
    the range, a number above zero."""
    body = body or {}
    limit = _num(body.get("limit"))
    if limit is None or limit <= 0:
        return None, u"no top of the calibration range"
    return {
        "limit": limit,
        "reading": _num(body.get("reading")),
        "injection": (body.get("injection") or u"").strip(),
        "recorded_at": recorded_at or u"",
    }, u""


def current(rec, result):
    """The record while the analysis's Result is still ALoQ, else None."""
    return rec if rec and is_aloq(result) else None


def of(analysis):
    """The record kept on an analysis (its annotation KEY) while its Result
    is still ALoQ, else None; None too where it cannot be read."""
    try:
        import json
        from zope.annotation.interfaces import IAnnotations
        rec = json.loads(IAnnotations(analysis).get(KEY) or u"null")
        return current(rec, analysis.getResult())
    except Exception:                                       # noqa: BLE001
        return None


def flag_text(analyte, injection):
    """What the failing QC result says (the worker's wording)."""
    return u"(ALoQ) {0} above the calibration range in {1}, no dilution: run a dilution or record " \
           u"the reason to report it with E".format(analyte or u"", injection or u"")


def reason_key(injection, analyte):
    return u"{0}|{1}".format(injection or u"", analyte or u"")


def reason_record(reasons, injection, analyte, reason, who, at):
    """The reasons with one recorded, or (None, why): a reason is required."""
    reason = (reason or u"").strip()
    if not reason:
        return None, u"Give the reason to report it with E."
    if not (injection and analyte):
        return None, u"No result named."
    out = dict(reasons or {})
    out[reason_key(injection, analyte)] = {"reason": reason, "by": who or u"", "at": at or u""}
    return out, u""
