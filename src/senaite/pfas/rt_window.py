# -*- coding: utf-8 -*-
"""A compound's retention-time window: the one rule, read by the method
editor's cards and loaded by the worker (pfas_pipeline.addon), so both
draw and search the same window.

The method's Integration block may hold one Retention time tolerance for
every compound: `rt_window_tol`, a number above 0, in the unit
`rt_window_unit`, "pct" (of the compound's retention time; blank reads
"pct") or "min". Set, each compound's window is its time plus or minus the
tolerance, in place of the window stored with its transition. Unset, the
stored window stands, so a method whose tolerance was never entered
integrates as it did.

    tolerance(intg)                  -> (value, unit) or None; ValueError
    half_width(rt, stored, tol)      -> (half-width in min, FROM_*) or (None, None)
    ends(rt, half)                   -> (lo, hi), rounded as shown
    words(rt, half, unit=True)       -> "11.121 to 11.345 min"
    tolerance_words(tol)             -> "1 %" or "0.1 min"

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from decimal import ROUND_HALF_UP, Decimal

TOL_KEY = u"rt_window_tol"
UNIT_KEY = u"rt_window_unit"
PCT, MIN = u"pct", u"min"
UNITS = ((PCT, u"%"), (MIN, u"min"))
# where a compound's window came from
FROM_TOLERANCE, FROM_STORED = u"tolerance", u"stored"
# a window's ends are shown to the thousandth of a minute, as times are
PLACES = 3


def _blank(value):
    return value is None or (u"%s" % value).strip() == u""


def _number(value):
    if isinstance(value, bool):
        raise ValueError(value)
    return float(value)


def tolerance(intg):
    """(value, unit) of the method's Retention time tolerance, or None while
    it is unset. A value that is no number above 0, or a unit that is
    neither % nor min, is refused (ValueError)."""
    intg = intg or {}
    value = intg.get(TOL_KEY)
    if _blank(value):
        return None
    number = _number(value)
    if not number > 0:
        raise ValueError(value)
    unit = intg.get(UNIT_KEY)
    unit = PCT if _blank(unit) else u"%s" % unit
    if unit not in (PCT, MIN):
        raise ValueError(unit)
    return number, unit


def half_width(rt, stored, tol):
    """(half-width in minutes, where it came from) of a compound at `rt`
    whose transition stores the window `stored`, under the method's
    tolerance `tol` (as tolerance() reads it): set, the time times the
    percentage, or the minutes; unset, the stored window. (None, None) when
    neither gives one."""
    if tol is not None:
        if _blank(rt):
            return None, None
        value, unit = tol
        return (_number(rt) * value / 100.0 if unit == PCT else value), FROM_TOLERANCE
    if _blank(stored):
        return None, None
    return _number(stored), FROM_STORED


def _rounded(value):
    return float(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-PLACES), rounding=ROUND_HALF_UP))


def ends(rt, half):
    """(lo, hi): the window's ends, to the thousandth of a minute."""
    rt = _number(rt)
    return _rounded(rt - half), _rounded(rt + half)


def _fixed(value):
    return u"%.*f" % (PLACES, value)


def words(rt, half, unit=True):
    """The window as a card reads it: "11.121 to 11.345 min" ("11.121 to
    11.345" under a heading that names the unit); "" without a time or a
    window."""
    if _blank(rt) or half is None:
        return u""
    lo, hi = ends(rt, half)
    return u"%s to %s%s" % (_fixed(lo), _fixed(hi), u" min" if unit else u"")


def tolerance_words(tol):
    """The tolerance as the setting reads it: "1 %", "0.1 min"; "" unset."""
    if tol is None:
        return u""
    value, unit = tol
    return u"%s %s" % ((u"%.6g" % value), dict(UNITS)[unit])
