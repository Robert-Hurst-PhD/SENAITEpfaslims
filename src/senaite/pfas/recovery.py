# -*- coding: utf-8 -*-
"""One definition of a recovery as the QC tab and the review cards show it.

    recovery_pct(row, rule, places) -> 92.6   value / expected x 100, judged

A QC record (`value`, `expected_value`) gives the measured value over the
expected one. A result row of a labelled standard holds its recovery already
as a percent (`recovery`) and is judged the same way. The percentage is
rounded as the checks judge it (rounding.judged_pct): a whole percent, or the
method's decimal places for recoveries. None when the row lacks a value, has
no usable expected value, or holds a non-number. Python 2.7 and 3.
"""
from __future__ import absolute_import, division


def recovery_pct(row, rule=None, places=0):
    from senaite.pfas import rounding
    rule = rule or rounding.DEFAULT_RULE
    try:
        if "value" in row or "expected_value" in row:
            value, expected = row.get("value"), row.get("expected_value")
            if value is None or not expected:
                return None
            pct = float(value) / float(expected) * 100.0
        else:
            value = row.get("recovery")
            if value is None:
                return None
            pct = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return rounding.judged_pct(pct, rule, places)
