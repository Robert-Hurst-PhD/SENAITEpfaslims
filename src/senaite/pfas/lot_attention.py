# -*- coding: utf-8 -*-
"""Why an active lot needs attention: the reasons its status badge names.

An active lot (a reagent, a reference material, a prepared standard) reads
"Active"; when something about it needs doing the badge turns amber and a
"!" beside it names why, the reasons joined with "; ":

    reasons(expiry=..., today=..., quantity=..., low_stock=..., coa=...,
            logbook=...)

Each check runs only when its argument is given (None = not asked): a
reagent passes `coa`, a prepared standard passes `logbook`.

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from datetime import date, datetime, timedelta

from senaite.pfas import lab_time
from senaite.pfas.lot_expiry import expired_on

EXPIRY_WINDOW_DAYS = 30


def _num(v):
    try:
        return float(u"%s" % v)
    except (TypeError, ValueError):
        return None


def _day(v):
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime((u"%s" % v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def reasons(expiry=None, today=None, quantity=None, low_stock=None, coa=None, logbook=None, review=None):
    out = []
    if review:
        # flagged for review (a parent's certificate values corrected): the latest why
        out.append(u"Flagged for review: %s" % (review[-1].get("why") or u""))
    if coa is False:
        out.append(u"No CoA on file")
    if logbook is False:
        out.append(u"No preparation record linked")
    exp, now = _day(expiry), _day(today) or lab_time.today()
    # a lot is expired ON its expiry date (lot_expiry.expired_on), so every
    # day has one reason: "Expires within" the days before it, "Expired" from it
    if exp is not None and expired_on(exp, now):
        out.append(u"Expired")
    elif exp is not None and exp <= now + timedelta(days=EXPIRY_WINDOW_DAYS):
        out.append(u"Expires within %d days" % EXPIRY_WINDOW_DAYS)
    q, lo = _num(quantity), _num(low_stock)
    if q is not None and lo is not None and q <= lo:
        out.append(u"Low stock")
    return out


def text(rs):
    return u"; ".join(rs)
