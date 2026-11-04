"""The laboratory's clock, for the worker.

The manifest carries the laboratory's time zone (empty when unset). A UTC
stamp the system recorded is shown on that clock; values the instrument wrote
on the laboratory's own clock are never passed through here. With no zone, or
a zone that is UTC all year, every function returns what it was given, so
output is as before.

Parsing mirrors the add-on's lab_time: a trailing Z, " UTC" or "+00:00" is
dropped, a seconds fraction is dropped, and a bare date is never shifted. A
naive datetime is taken as UTC.
"""
import logging
import re
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

_ZONE = ""
_FORMATS = (
    ("%Y-%m-%dT%H:%M:%S", True),
    ("%Y-%m-%dT%H:%M", True),
    ("%Y-%m-%d %H:%M:%S", True),
    ("%Y-%m-%d %H:%M", True),
    ("%Y-%m-%d", False),
)
_MARKERS = ("Z", " UTC", "+00:00")
_FRACTION = re.compile(r"\.\d+$")


def set_zone(name):
    """Remember the laboratory's zone from the run manifest."""
    global _ZONE
    _ZONE = (name or "").strip()


def zone():
    return _ZONE


_TZ_CACHE = {}


def _tz(name):
    """The zone object, or None when it cannot be loaded; looked up once per
    name, so a missing zone warns once."""
    if name in _TZ_CACHE:
        return _TZ_CACHE[name]
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(name)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("time zone %r is not available, times stay in UTC: %s", name, exc)
        tz = None
    _TZ_CACHE[name] = tz
    return tz


def _active_tz(name):
    """The zone object when `name` is a zone whose offset from UTC is not zero
    all year, else None."""
    if not name or name == "UTC":
        return None
    tz = _tz(name)
    if tz is None:
        return None
    for month in (1, 7):
        if datetime(2026, month, 1, tzinfo=tz).utcoffset():
            return tz
    return None


def active(zone_name=None):
    """True only when the zone loaded and converts; a zone that failed to
    load leaves times in UTC, so no footer claims otherwise."""
    return _active_tz(_ZONE if zone_name is None else zone_name) is not None


def _parse(text):
    """(naive datetime, has_time) or (None, False)."""
    text = text.strip()
    for marker in _MARKERS:
        if text.endswith(marker):
            text = text[:-len(marker)].strip()
            break
    text = _FRACTION.sub("", text)
    for fmt, has_time in _FORMATS:
        try:
            return datetime.strptime(text, fmt), has_time
        except ValueError:
            continue
    return None, False


def to_wall(value, zone_name=None):
    """A naive datetime on the laboratory's clock, or None for an empty or
    unreadable value. Without an active zone the value's own clock is
    returned; a bare date is never shifted."""
    zone_name = _ZONE if zone_name is None else zone_name
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        parsed, has_time = value, True
    elif isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        if not value.strip():
            return None
        parsed, has_time = _parse(value)
        if parsed is None:
            return None
    else:
        return None
    tz = _active_tz(zone_name)
    if tz is None or not has_time:
        return parsed
    return parsed.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)


def clock(text, zone_name=None):
    """HH:MM:SS of a UTC stamp text on the laboratory's clock; with no active
    zone, the characters 11 to 19 of the text as before."""
    text = text or ""
    if not active(_ZONE if zone_name is None else zone_name):
        return text[11:19]
    wall = to_wall(text, zone_name)
    return wall.strftime("%H:%M:%S") if wall else text[11:19]


def stamp(text, zone_name=None):
    """A UTC stamp text on the laboratory's clock as ISO text; unchanged with
    no active zone or when it cannot be read."""
    if not active(_ZONE if zone_name is None else zone_name) or not isinstance(text, str):
        return text
    wall = to_wall(text, zone_name)
    return wall.isoformat() if wall else text


def day(value, zone_name=None):
    """YYYY-MM-DD of a UTC instant on the laboratory's calendar; None when
    there is no value. With no active zone the value's own date."""
    wall = to_wall(value, zone_name)
    return wall.strftime("%Y-%m-%d") if wall else None


def footer(zone_name=None):
    zone_name = _ZONE if zone_name is None else zone_name
    return "Times are %s." % zone_name if active(zone_name) else ""
