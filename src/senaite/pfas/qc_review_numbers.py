# -*- coding: utf-8 -*-
"""How the QC Review's measurement appendices print a number.

One function for Appendix A and B, on the page and in the designed report.
Display only: a stored value is never changed.

    recovery   a recovery value: the method's decimal places for recoveries
               (method_engine.recovery_decimals; whole percent by default)
               by its rounding rule, as the certificate prints recoveries
    judged     a recovery as its check judged it: at the decimal places the
               run recorded it judged recoveries at (its judged_rule), a
               whole percent for a run that records none
    percent    any other percentage: two significant figures
    number     every other number: six significant figures, trailing
               zeros after the decimal point dropped

    show(value, kind, rule, places) -> "98", "98.4", "0.46", "5.649"
    display_row(row, rule, places)  a copy of one injection row with its
                                    numbers shown

Text that is not a number passes through unchanged; nothing prints "None".
Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import rounding

RECOVERY = "recovery"
JUDGED = "judged"
PERCENT = "percent"
NUMBER = "number"

PERCENT_SIG = 2
NUMBER_SIG = 6

# the injection-row columns that are not plain numbers
KINDS = {"recovery": RECOVERY, "rec_judged": JUDGED, "resp_pct": PERCENT, "resp_judged": PERCENT}
# every other numeric column of the appendices
NUMBER_COLUMNS = ("calc_conc", "rt", "rrt", "ion_ratio_obs", "ion_ratio_exp", "sn", "is_area")


def _trim(text):
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def show(value, kind=NUMBER, rule=rounding.DEFAULT_RULE, places=0):
    """`value` as the appendices print it; `places`: the method's decimal
    places for recoveries."""
    if value is None:
        return ""
    if rounding.to_decimal(value) is None:
        return "%s" % value
    if kind == RECOVERY:
        text = rounding.recovery_text(value, places or rounding.PCT_PLACES, rule)
    elif kind == JUDGED:
        text = rounding.round_places(value, places or rounding.PCT_PLACES, rule)
    elif kind == PERCENT:
        text = rounding.round_sig(value, PERCENT_SIG, rule)
    else:
        text = _trim(rounding.round_sig(value, NUMBER_SIG, rule))
    return text


def display_row(row, rule=rounding.DEFAULT_RULE, places=0):
    """A copy of an injection row with each numeric column shown; the row
    handed in is not touched. A judged recovery shows the places its run
    was judged at, whatever the method shows now."""
    out = dict(row)
    for key in NUMBER_COLUMNS:
        if key in out:
            out[key] = show(out[key], NUMBER, rule)
    judged_at = rounding.judged_places(row.get("judged_rule"))
    for key, kind in KINDS.items():
        if key in out:
            out[key] = show(out[key], kind, rule, judged_at if kind == JUDGED else places)
    return out
