# -*- coding: utf-8 -*-
"""The laboratory's time zone (Site Settings).

Times the system records itself (an extraction finished, a review signed)
are kept in UTC; the instrument stamps its injections on the laboratory's
own clock. A document that prints both -- the EDD's prep and analysis dates
-- converts the UTC ones to the laboratory's zone, set once by a manager.
Unset, nothing is converted and the EDD says so. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

KEY = "senaite.pfas.lab_timezone"


def zones():
    import pytz
    return list(pytz.common_timezones)


def get_zone(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal).get(KEY) or u""


def set_zone(portal, name):
    """False when `name` is not a time zone."""
    from zope.annotation.interfaces import IAnnotations
    if name and name not in zones():
        return False
    IAnnotations(portal)[KEY] = name or u""
    return True


def to_lab(dt_utc, zone):
    """A naive UTC datetime as a naive datetime on the laboratory's clock;
    unchanged when no zone is set."""
    if dt_utc is None or not zone:
        return dt_utc
    import pytz
    return pytz.utc.localize(dt_utc).astimezone(pytz.timezone(zone)).replace(tzinfo=None)
