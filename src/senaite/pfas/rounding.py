# -*- coding: utf-8 -*-
"""Rounding to significant figures by a named rule.

The lab's assignment, 2026-10-05 (a lab setting, not a citation of an agency
document):

    iso   round half to even  (ISO 80000-1 Annex B: 2.25 -> 2.2, 2.35 -> 2.4)
    epa   round half up       (2.25 -> 2.3)
    fda   round half up

chosen per method x matrix on the Reporting tab (report_format
"coa_rounding"). Exact decimal arithmetic from the value's TEXT: a result
is stored as a string and is rounded from that string, a float limit from
repr(), never through binary floating point (2.675 is 2.67499999... as a
float and would round the wrong way under either rule). The same in
Python 2 and 3 -- the built-in round() is not (half away from zero in 2,
half to even in 3).

    round_sig(value, n, rule) -> "6.30", "0.0391", "12300", "10.0"
    round_places(value, places, rule) -> "98", "130", "2.5"
    judged_pct(value, rule)   -> 130.0  a QC percentage as it is JUDGED and
                                printed: a whole percent
    judged_conc(value, n, rule) -> 2.0  a measured concentration as it is
                                judged: the reported significant figures

every result and QC check judges the ROUNDED value -- the
value the report states is the final value. Measured values are rounded;
criteria (RL, x RL, MDL, MCL, windows) are used as configured. Instrument
acquisition criteria (RT, ion ratio, S/N, calibration r2) are not rounded.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

RULES = {
    "iso": ROUND_HALF_EVEN,
    "epa": ROUND_HALF_UP,
    "fda": ROUND_HALF_UP,
}
DEFAULT_RULE = "epa"          # what certificates did before the setting existed


def to_decimal(value):
    """The exact decimal a value states, or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, float):
        d = Decimal(repr(value))
    elif isinstance(value, int) or type(value).__name__ == "long":
        d = Decimal(value)
    else:
        text = ("%s" % value).strip()
        if not text:
            return None
        try:
            d = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
    return d if d.is_finite() else None


def round_sig(value, n=3, rule=DEFAULT_RULE):
    """`value` rounded to `n` significant figures by `rule`, in fixed
    notation, keeping significant trailing zeros ("6.30"). None for a value
    that is not a number."""
    d = to_decimal(value)
    if d is None:
        return None
    n = max(1, int(n))
    mode = RULES.get(rule, RULES[DEFAULT_RULE])
    if d == 0:
        return "0"
    exp = d.adjusted()
    r = d.quantize(Decimal(1).scaleb(exp - n + 1), rounding=mode)
    if r.adjusted() > exp:            # 9.995 -> 10.00: one digit too many
        r = r.quantize(Decimal(1).scaleb(r.adjusted() - n + 1), rounding=mode)
    if r.as_tuple().exponent > 0:     # 1.23E+4 -> "12300"
        r = r.quantize(Decimal(1))
    return "{0:f}".format(r)


def round_places(value, places=0, rule=DEFAULT_RULE):
    """`value` rounded to `places` decimal places by `rule` (fixed notation),
    or None for a value that is not a number."""
    d = to_decimal(value)
    if d is None:
        return None
    mode = RULES.get(rule, RULES[DEFAULT_RULE])
    r = d.quantize(Decimal(1).scaleb(-max(0, int(places))), rounding=mode)
    if r == 0:
        r = abs(r)                    # never "-0"
    return "{0:f}".format(r)


PCT_PLACES = 0                        # QC percentages: whole percent


NOISE_DIGITS = 12


def _denoised(value):
    """A COMPUTED float without its binary noise: 13.05 / 10 * 100 is
    130.50000000000003, which would never round as the tie it is. Floats are
    first rounded to 12 significant digits (far beyond any reported
    precision); text and Decimal values are exact already."""
    if isinstance(value, float):
        return round_sig(value, NOISE_DIGITS, "iso")
    return value


def judged_pct(value, rule=DEFAULT_RULE):
    """A QC percentage (recovery, RPD, IS response, CCV recovery) as it is
    judged and printed: a whole percent by `rule`; None if not a number."""
    text = round_places(_denoised(value), PCT_PLACES, rule)
    return None if text is None else float(text)


def judged_conc(value, n=3, rule=DEFAULT_RULE):
    """A measured concentration as it is judged: rounded to the reported
    significant figures by `rule`; None if not a number."""
    text = round_sig(_denoised(value), n, rule)
    return None if text is None else float(text)


def judged_rule(rule, n):
    """What a run records it was judged with, and what a certificate checks
    it against: "epa;3;pct0"."""
    return "%s;%d;pct%d" % (rule, int(n), PCT_PLACES)
