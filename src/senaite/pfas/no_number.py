# -*- coding: utf-8 -*-
"""A result the instrument wrote BLoQ with no number.

An instrument-processed export may write "BLoQ" in the concentration cell
instead of a number. A number the file carries is used: beside the word in
the concentration cell ("0.12 (BLoQ)"), or in the concentration column with
the word in Quantitation Status. Where the cell holds the word alone the
instrument gave no number, and the result is never reported not detected
silently: the worker files a failing QC result of QC_TYPE for each such
result of a sample, and Data Review lists it until the reviewer records a
reason (reason_record(), kept on the worksheet under REASONS_KEY by
reason_key()), logged and audited. The result then prints as it did ("< RL"
with U), the reason on the record.

A raw run's BLoQ is the LIMS's own reading on its curve and files nothing.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

REASONS_KEY = u"senaite.pfas.no_number_reasons"
# the QC result that holds release until a reason is recorded
QC_TYPE = u"The instrument gave no number"


def flag_text(analyte, injection):
    """What the failing QC result says (the worker's wording)."""
    return u"(BLoQ) the instrument gave no number for {0} in {1}: record the reason to report " \
           u"it".format(analyte or u"", injection or u"")


def reason_key(injection, analyte):
    return u"{0}|{1}".format(injection or u"", analyte or u"")


def reason_record(reasons, injection, analyte, reason, who, at):
    """The reasons with one recorded, or (None, why): a reason is required."""
    reason = (reason or u"").strip()
    if not reason:
        return None, u"Give the reason to report it."
    if not (injection and analyte):
        return None, u"No result named."
    out = dict(reasons or {})
    out[reason_key(injection, analyte)] = {"reason": reason, "by": who or u"", "at": at or u""}
    return out, u""
