# -*- coding: utf-8 -*-
"""The laboratory's time zone (Time & Language).

Times the system records itself (an extraction finished, a review signed)
are kept in UTC; the instrument stamps its injections on the laboratory's
own clock. A document that prints both -- the EDD's prep and analysis dates
-- converts the UTC ones to the laboratory's zone, set once by a manager.
Unset, nothing is converted and the EDD says so. Python 2.7.

Rules: a zone that is UTC all year counts as unset; an instant is converted
to the laboratory's zone before any format is applied, so a date-only format
shows the laboratory's calendar day; only a bare date (a DateTime at its own
midnight, or text with no time) is shown as stored.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import re

try:
    text_type = unicode  # noqa: F821 (Python 2)
except NameError:  # pragma: no cover
    text_type = str

KEY = "senaite.pfas.lab_timezone"
ZONE_RECORD = "plone.portal_timezone"

_TEXT_FORMATS = (
    ("%Y-%m-%dT%H:%M:%S", True),
    ("%Y-%m-%dT%H:%M", True),
    ("%Y-%m-%d %H:%M:%S", True),
    ("%Y-%m-%d %H:%M", True),
    ("%Y-%m-%d", False),
)
_UTC_MARKERS = ("Z", " UTC", "+00:00")
_FRACTION = re.compile(r"\.\d+$")


def zones():
    import pytz
    return list(pytz.common_timezones)


def get_zone(portal):
    """The laboratory's zone; `portal` is kept for old callers."""
    return zone()


def set_zone(name):
    """Write Plone's own zone record; an empty name writes "UTC". False when
    `name` is not a listed time zone."""
    from plone.registry.interfaces import IRegistry
    from zope.component import getUtility
    if name and name not in zones():
        return False
    getUtility(IRegistry)[ZONE_RECORD] = text_type(name or u"UTC")
    return True


def migrate_zone(portal):
    """Move the zone once kept on the portal into Plone's record. A zone
    already set there wins; the old value is dropped whenever the record is
    set. One history entry when anything changes; True then."""
    from zope.annotation.interfaces import IAnnotations
    ann = IAnnotations(portal)
    if KEY not in ann:
        return False
    old = ann.get(KEY) or u""
    current = _record_zone()
    take = current in (u"", u"UTC") and old in zones() and old != current
    if not take and not current:
        return False
    if take:
        from senaite.pfas import config_history
        config_history.track(portal, "lab_timezone", "default",
                             lambda: {"timezone": _record_zone()},
                             label=u"Laboratory time zone",
                             action=u"moved from the old setting")
        set_zone(old)
    del ann[KEY]
    return True


def _to_lab(dt_utc, zone):
    """A naive UTC datetime as a naive datetime on the clock of `zone`;
    unchanged when no zone is given."""
    if dt_utc is None or not zone:
        return dt_utc
    import pytz
    return pytz.utc.localize(dt_utc).astimezone(pytz.timezone(zone)).replace(tzinfo=None)


def to_utc(wall):
    """A naive wall clock on the laboratory's clock as a naive UTC datetime;
    unchanged while the zone is not active. At a repeated clock time the
    standard-time pass is taken; a time that does not exist is moved
    forward."""
    if wall is None or not active():
        return wall
    import pytz
    tz = pytz.timezone(zone())
    aware = tz.normalize(tz.localize(wall, is_dst=False))
    return aware.astimezone(pytz.utc).replace(tzinfo=None)


def _utcnow():
    """The process clock as a naive UTC datetime (replaced in tests)."""
    return datetime.datetime.utcnow()


def _valid(name):
    import pytz
    return bool(name) and name in pytz.all_timezones_set


def _record_zone():
    """Plone's zone record; empty when unset, unreadable or not a time
    zone."""
    try:
        from plone.registry.interfaces import IRegistry
        from zope.component import getUtility
        name = getUtility(IRegistry).get(ZONE_RECORD)
        if _valid(name):
            return text_type(name)
    except Exception:
        pass
    return u""


def _portal_zone():
    """The zone still kept on the portal until migrate_zone moves it; read
    only, empty with no site or no valid zone there."""
    try:
        from zope.annotation.interfaces import IAnnotations
        from zope.component.hooks import getSite
        site = getSite()
        if site is None:
            return u""
        name = IAnnotations(site).get(KEY)
        if _valid(name):
            return text_type(name)
    except Exception:
        pass
    return u""


def zone():
    """The laboratory's time zone name: Plone's record, or, while that is
    unset or UTC, the zone still kept on the portal; empty when neither
    holds a time zone."""
    name = _record_zone()
    if name in (u"", u"UTC"):
        return _portal_zone() or name
    return name


def active():
    """True when a zone is set whose offset from UTC is not zero all year,
    so times need converting. UTC, GMT and their aliases are not."""
    name = zone()
    if not name:
        return False
    import pytz
    tz = pytz.timezone(name)
    for month in (1, 7):
        if tz.localize(datetime.datetime(2026, month, 1)).utcoffset():
            return True
    return False


def _is_dt(value):
    return hasattr(value, "toZone") and hasattr(value, "parts")


def is_date_only(dt):
    """A DateTime whose own-zone time is exactly midnight is a bare date."""
    return dt.hour() == 0 and dt.minute() == 0 and dt.second() == 0


def _parse_text(text):
    """(datetime, has_time, marked_utc) or (None, False, False). A trailing
    Z, " UTC" or "+00:00" marks a UTC instant; a seconds fraction is dropped."""
    text = text.strip()
    marked = False
    for marker in _UTC_MARKERS:
        if text.endswith(marker):
            text, marked = text[:-len(marker)].strip(), True
            break
    text = _FRACTION.sub("", text)
    for fmt, has_time in _TEXT_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt), has_time, marked
        except ValueError:
            continue
    return None, False, False


def _as_text(value):
    """The value as text for display when it cannot be formatted."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, text_type):
        return value
    return u""


def _read(value):
    """(own, utc, bare): the value's own clock, its UTC clock (None when it
    is not an instant) and whether it is a bare date; (None, None, False)
    when it cannot be read."""
    try:
        return _read_value(value)
    except Exception:
        return None, None, False


def _read_value(value):
    if value is None:
        return None, None, False
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if _is_dt(value):
        y, mo, d, h, mi, s, _tz = value.parts()
        own = datetime.datetime(y, mo, d, h, mi, int(s))
        y, mo, d, h, mi, s, _tz = value.toZone("UTC").parts()
        return own, datetime.datetime(y, mo, d, h, mi, int(s)), is_date_only(value)
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            import pytz
            utc = value.astimezone(pytz.utc).replace(tzinfo=None)
            return value.replace(tzinfo=None), utc, False
        return value, value, False
    if isinstance(value, datetime.date):
        day = datetime.datetime(value.year, value.month, value.day)
        return day, None, True
    if isinstance(value, text_type):
        if not value.strip():
            return None, None, False
        parsed, has_time, _marked = _parse_text(value)
        if parsed is None:
            return None, None, False
        return parsed, (parsed if has_time else None), not has_time
    return None, None, False


def to_wall(value, kind="utc"):
    """A naive datetime on the laboratory's clock, or None when the value is
    empty or cannot be read. Kind "lab" is already a lab wall clock and is
    not converted; a bare date (a DateTime at its own midnight, or text with
    no time) is never shifted."""
    own, utc, bare = _read(value)
    if own is None:
        return None
    if kind == "lab" or bare or utc is None or not active():
        return own
    try:
        return _to_lab(utc, zone())
    except Exception:
        return None


def show(value, kind="utc", fmt=u"%Y-%m-%d %H:%M"):
    """The value as text on the laboratory's clock. Empty input gives u"";
    text that cannot be read or formatted comes back unchanged. A date-only
    format shows the date on the laboratory's calendar: an instant is
    converted first, a bare date is not shifted."""
    wall = to_wall(value, kind)
    if wall is None:
        return _as_text(value)
    try:
        return text_type(wall.strftime(fmt))
    except Exception:
        return _as_text(value)


def lab_date(value, kind="utc"):
    """The date part of to_wall; None when there is none."""
    wall = to_wall(value, kind)
    return wall.date() if wall is not None else None


def now():
    """Now on the laboratory's clock, naive."""
    stamp = _utcnow()
    if active():
        return _to_lab(stamp, zone())
    return stamp


def today():
    return now().date()


def typed(text):
    """A typed "YYYY-MM-DD HH:MM", "YYYY-MM-DDTHH:MM" or "YYYY-MM-DD" as a
    DateTime labelled with the laboratory's zone; None when empty or
    unreadable. At a repeated clock time the standard-time pass is taken; a
    time that does not exist is moved forward. Text marked Z, UTC or +00:00
    is that UTC instant, not lab time. A bare date, or any text while the
    zone is not active, is exactly DateTime(text)."""
    from DateTime import DateTime
    text = (text or u"").strip()
    if not text:
        return None
    parsed, has_time, marked = _parse_text(text)
    if parsed is None:
        return None
    if not active() or not has_time:
        try:
            return DateTime(text)
        except Exception:
            return None
    utc = parsed if marked else to_utc(parsed)
    return DateTime(utc.strftime("%Y/%m/%d %H:%M:%S UTC")).toZone(zone())


def for_strftime(dt):
    """A DateTime whose strftime (which formats in the process zone) prints
    the laboratory's wall clock. Unchanged when the zone is not active, or
    when the value is a bare date already on the process zone's offset; a
    bare date on another offset is rebuilt from its own clock so that it
    prints as stored."""
    if dt is None or not active():
        return dt
    from DateTime import DateTime
    local = DateTime().localZone()
    if is_date_only(dt):
        if dt.toZone(local).tzoffset() == dt.tzoffset():
            return dt
        y, mo, d, h, mi, sec, _tz = dt.parts()
        return DateTime(y, mo, d, h, mi, sec, local)
    wall = to_wall(dt)
    return DateTime(wall.year, wall.month, wall.day, wall.hour, wall.minute,
                    wall.second, local)


def footer():
    """The line a print that shows times carries."""
    if not active():
        return u""
    return u"Times are {0}.".format(zone())
