# -*- coding: utf-8 -*-
"""SENAITE's own date display, date filters and date entry in the
laboratory's zone.

Plone's ulocalized_time formats a DateTime through strftime, which prints
the process zone (UTC here), and SENAITE's formatDateQuery builds day bounds
in that zone too. At start-up every copy of either name is rebound to a
wrapper that hands the original a value printing the laboratory's clock and
bounds labelled with the laboratory's zone. A copy is a module that took the
name with `from ... import`; one that is not installed is skipped.

SENAITE's date widget fills its inputs through strftime as well, and an
Archetypes date field reads a time typed with no zone on the process clock.
The widget's fill methods and the set of SENAITE's DateTimeField and of
Archetypes' own are replaced on their classes: the widget fills the
laboratory's clock and a field that widget fills reads a typed time on it,
so a value filled and saved unchanged keeps its instant, except in the
hour the clocks go back: an instant in the first pass of that repeated hour
is filled as its clock time and read back as the second pass, one hour
later. A field with any
other widget is set as before. On a field whose widget shows no time, a
time of exactly midnight is a bare date and is stored as given. A field
written, or filled for editing, with UTC clock text is set as before. A
stored DateTime handed to a set (a copy) keeps its instant. Date limits
compare instants. A certificate's
computed ValidTo keeps ValidFrom's lab time. The listing's date text is
shown on the laboratory's clock too.

Rules: the zone is read on each call, never at start-up; unset or UTC, the
original gets exactly its caller's arguments; a bare date is never shifted;
text and other input go to the original unchanged, and so does a call with
no context (Plone's ISO path); a conversion that fails calls the original
with its caller's arguments. A name or method is replaced only while it is
still the original; anything else there is left alone with a warning.
Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import importlib
import inspect
import logging

from senaite.pfas import lab_time

logger = logging.getLogger("senaite.pfas")

# Every module that holds Plone's ulocalized_time under its own name.
# Copies of SENAITE's to_localized_time go through the translation service
# and so through its rebound name.
BOUND = (
    ("Products.CMFPlone.i18nl10n", "ulocalized_time"),
    ("Products.CMFPlone.TranslationServiceTool", "ulocalized_time"),
    ("bika.lims.browser.workflow.analysis", "ulocalized_time"),
    # ScheduleInputWidget copies this name into its class _properties when the
    # class is defined, so rebinding the module name does not reach the
    # widget's template; the widget only formats typed date text.
    ("bika.lims.browser.widgets.scheduleinputwidget", "ulocalized_time"),
    ("bika.lims.browser.fields.remarksfield", "ulocalized_time"),
    ("bika.lims.browser.analysisrequest.invoice", "ulocalized_time"),
    ("bika.lims.browser.auditlog", "ulocalized_time"),
    ("senaite.impress.analysisrequest.reportview", "ulocalized_time"),
    ("plone.app.event.base", "orig_ulocalized_time"),
    ("plone.stringinterp.adapters", "ulocalized_time"),
)

# Every module that holds SENAITE's formatDateQuery under its own name.
DATE_QUERY = (
    ("bika.lims.utils", "formatDateQuery"),
)

# Every method replaced on its class: (module, class, method). SENAITE's
# DateTimeField comes before Archetypes' own, which it inherits from, so each
# wrapper calls Archetypes' original and a value is converted once; both are
# listed so that SENAITE's field stays covered should it define its own set.
METHODS = (
    ("senaite.core.browser.widgets.datetimewidget", "DateTimeWidget", "to_local_date"),
    ("senaite.core.browser.widgets.datetimewidget", "DateTimeWidget", "get_date"),
    ("senaite.core.browser.widgets.datetimewidget", "DateTimeWidget", "get_time"),
    ("senaite.core.browser.fields.datetime", "DateTimeField", "set"),
    ("Products.Archetypes.Field", "DateTimeField", "set"),
    ("senaite.app.listing.view", "ListingView", "to_str_date"),
    ("bika.lims.content.instrumentcertification", "InstrumentCertification", "setValidTo"),
    ("senaite.core.browser.fields.datetime", "DateTimeField", "validate_min_date"),
    ("senaite.core.browser.fields.datetime", "DateTimeField", "validate_max_date"),
)

# Program-written fields that carry UTC clock text are not read as lab time:
# (portal type, field), each written by SENAITE itself, or filled for editing
# by SENAITE with its UTC clock (the analyses listing's capture date).
UTC_TEXT_FIELDS = (
    ("AutoImportLog", "LogTime"),
    ("Analysis", "ResultCaptureDate"),
    ("DuplicateAnalysis", "ResultCaptureDate"),
    ("ReferenceAnalysis", "ResultCaptureDate"),
    ("RejectAnalysis", "ResultCaptureDate"),
)

# How a date field reads a time typed with no zone (field_reading).
READ_LAB = "lab time"
READ_LAB_DATE = "lab time, date only"
READ_EXCLUDED = "excluded: UTC clock text"
READ_AS_BEFORE = "as before: another widget"

_ORIGINAL = None
_ORIGINAL_DATE_QUERY = None
# The original function of each METHODS entry, by "module.Class.method".
_METHOD_ORIGINALS = {}
_MARK = "_senaite_pfas_lab_zone"

# Position of `context` among the arguments after `time`.
_CONTEXT_AT = 2


def _is_dt(value):
    return hasattr(value, "toZone") and hasattr(value, "parts")


def _context(args, kwargs):
    if "context" in kwargs:
        return kwargs["context"]
    if len(args) > _CONTEXT_AT:
        return args[_CONTEXT_AT]
    return None


def _for_strftime(time, args, kwargs):
    """The value to hand the original, or `time` itself when nothing is to
    change."""
    if _context(args, kwargs) is None or not lab_time.active():
        return time
    if _is_dt(time):
        dt = time
    elif isinstance(time, datetime.datetime):
        from DateTime import DateTime
        dt = DateTime(time)
    else:
        return time
    shown = lab_time.for_strftime(dt)
    return time if shown is dt else shown


def lab_ulocalized_time(time, *args, **kwargs):
    """Plone's ulocalized_time, showing the laboratory's clock."""
    try:
        shown = _for_strftime(time, args, kwargs)
    except Exception:
        shown = time
    return _ORIGINAL(shown, *args, **kwargs)


setattr(lab_ulocalized_time, _MARK, True)


def _lab_bound(text):
    """A day bound typed on the laboratory's clock, as an instant with its
    offset; the text as it was when it is not a date and time."""
    dt = lab_time.typed(text)
    return text if dt is None else dt.ISO8601()


def lab_format_date_query(context, date_id, *args, **kwargs):
    """SENAITE's formatDateQuery, its day bounds on the laboratory's days."""
    query = _ORIGINAL_DATE_QUERY(context, date_id, *args, **kwargs)
    try:
        if not query or not lab_time.active():
            return query
        bounds = query["query"]
        if isinstance(bounds, (list, tuple)):
            bounds = type(bounds)(_lab_bound(b) for b in bounds)
        else:
            bounds = _lab_bound(bounds)
        shifted = dict(query)
        shifted["query"] = bounds
        return shifted
    except Exception:
        return query


setattr(lab_format_date_query, _MARK, True)


def _fill(value):
    """The value the widget's fill formats: a DateTime as one printing the
    laboratory's clock; text (a form sent back) and anything else as given,
    so a typed time is shown as typed."""
    if not _is_dt(value) or not lab_time.active():
        return value
    try:
        return lab_time.for_strftime(value)
    except Exception:
        return value


def _fill_wrapper(name, attr):
    """A widget fill method that formats `_fill` of its value."""
    def wrapper(self, value, *args, **kwargs):
        return _METHOD_ORIGINALS[name](self, _fill(value), *args, **kwargs)
    wrapper.__name__ = str(attr)
    wrapper.__doc__ = "SENAITE's DateTimeWidget.{0}, on the laboratory's clock.".format(attr)
    return wrapper


def _is_true(value):
    """A widget property as SENAITE's DateTimeField reads it."""
    return u"{0}".format(value).strip().lower() in (u"y", u"yes", u"1", u"true", u"on")


def field_reading(field, portal_type):
    """How the field reads a time typed with no zone: READ_LAB when SENAITE's
    date widget fills it (that widget fills the laboratory's clock),
    READ_LAB_DATE when that widget shows no time, READ_EXCLUDED for a
    UTC_TEXT_FIELDS entry, READ_AS_BEFORE for any other widget."""
    try:
        from senaite.core.browser.widgets.datetimewidget import DateTimeWidget
    except Exception:
        return READ_AS_BEFORE
    widget = getattr(field, "widget", None)
    if not isinstance(widget, DateTimeWidget):
        return READ_AS_BEFORE
    name = field.getName() if hasattr(field, "getName") else getattr(field, "name", None)
    if (portal_type, name) in UTC_TEXT_FIELDS:
        return READ_EXCLUDED
    show_time = getattr(widget, "show_time", None)
    if show_time is not None and not _is_true(show_time):
        return READ_LAB_DATE
    return READ_LAB


def _wall_text(value):
    """A naive datetime as "YYYY-MM-DD HH:MM:SS"; None for anything else. A
    DateTime object, naive or not, is a stored value: it is shown as an
    instant (a naive one on the process clock, UTC), so it is kept as one."""
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            return None
        return u"%04d-%02d-%02d %02d:%02d:%02d" % (
            value.year, value.month, value.day, value.hour, value.minute, value.second)
    return None


def _typed_value(value, date_only):
    """The value the field stores: a date and time with no zone, read on the
    laboratory's clock. Anything with a zone, a bare date, empty or
    unreadable input, as given; on a date-only field a time of exactly
    midnight is a bare date too."""
    if not value or not lab_time.active():
        return value
    if isinstance(value, (bytes, lab_time.text_type)):
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        from DateTime import DateTime
        try:
            if not DateTime(text).timezoneNaive():
                return value
        except Exception:
            pass
    else:
        text = _wall_text(value)
    if text is None:
        return value
    dt = lab_time.typed(text)
    if dt is None or dt.timezoneNaive():
        return value
    if date_only and lab_time.is_date_only(dt):
        return value
    return dt


def _as_set(field, instance, value):
    """The value as the field's set hands it to Archetypes."""
    reading = field_reading(field, getattr(instance, "portal_type", None))
    if reading in (READ_LAB, READ_LAB_DATE):
        return _typed_value(value, reading == READ_LAB_DATE)
    return value


def _set_wrapper(name, attr):
    """A DateTimeField.set that reads a typed time on the laboratory's clock
    when SENAITE's date widget fills the field; any other field is set as
    before."""
    def wrapper(self, instance, value, **kwargs):
        try:
            given = _as_set(self, instance, value)
        except Exception:
            given = value
        return _METHOD_ORIGINALS[name](self, instance, given, **kwargs)
    wrapper.__name__ = str(attr)
    wrapper.__doc__ = "DateTimeField.set, a typed time read on the laboratory's clock."
    return wrapper


def _str_date_wrapper(name, attr):
    """The listing's to_str_date, on the laboratory's clock."""
    def wrapper(self, date):
        original = _METHOD_ORIGINALS[name]
        if not lab_time.active():
            return original(self, date)
        try:
            from DateTime import DateTime
            shown = lab_time.for_strftime(DateTime(date))
        except Exception:
            return original(self, date)
        try:
            return shown.strftime(self.date_format_long)
        except ValueError:
            return original(self, date)
    wrapper.__name__ = str(attr)
    wrapper.__doc__ = "The listing's date text, on the laboratory's clock."
    return wrapper


def _add_days(dt, days):
    """`days` calendar days after dt on its own clock and in its own zone, so
    a lab time stays the same lab time across a change of summer time."""
    from DateTime import DateTime
    y, mo, d, h, mi, sec, tz = dt.parts()
    day = datetime.date(y, mo, d) + datetime.timedelta(days=days)
    return DateTime(day.year, day.month, day.day, h, mi, sec, tz)


def _valid_to_wrapper(name, attr):
    """InstrumentCertification.setValidTo with its interval: ValidTo is
    ValidFrom plus the interval as a value with ValidFrom's zone, never as
    text on the process clock. Without an interval, or unset, SENAITE's own
    setter runs."""
    def wrapper(self, value):
        original = _METHOD_ORIGINALS[name]
        if not lab_time.active():
            return original(self, value)
        from DateTime import DateTime
        valid_from = self.getValidFrom()
        DateTime(value)  # an unreadable ValidTo fails as SENAITE's setter fails
        interval = self.getExpirationInterval()
        if not (valid_from and interval):
            return original(self, value)
        valid_to = _add_days(valid_from, int(interval))
        self.getField("ValidTo").set(self, valid_to)
        logger.debug("Set ValidTo Date to: %r", valid_to)
    wrapper.__name__ = str(attr)
    wrapper.__doc__ = "InstrumentCertification.setValidTo, ValidTo kept on the laboratory's clock."
    return wrapper


def _instant(value):
    """A value as a naive UTC datetime, read the way Archetypes stores it:
    text through DateTime, a DateTime by its instant (one with no zone on the
    process clock), a naive datetime on the process clock. The unbounded
    datetime.min and datetime.max are kept. None when it cannot be read."""
    from DateTime import DateTime
    if isinstance(value, datetime.datetime) and value.tzinfo is None:
        if value in (datetime.datetime.min, datetime.datetime.max):
            return value
        value = DateTime(value)
    elif isinstance(value, datetime.datetime):
        import pytz
        return value.astimezone(pytz.utc).replace(tzinfo=None, microsecond=0)
    elif isinstance(value, datetime.date):
        value = DateTime(value.year, value.month, value.day)
    elif isinstance(value, (bytes, lab_time.text_type)):
        value = DateTime(value)
    if not _is_dt(value):
        return None
    y, mo, d, h, mi, sec, _tz = value.toZone("UTC").parts()
    return datetime.datetime(y, mo, d, h, mi, int(sec))


def _limit_wrapper(name, attr):
    """SENAITE's DateTimeField.validate_min_date / validate_max_date with the
    value read as the field's set reads it and value and limit compared as
    instants (SENAITE compares wall clocks). Unset, SENAITE's own runs."""
    is_min = attr == "validate_min_date"

    def wrapper(self, value, instance, errors=None):
        original = _METHOD_ORIGINALS[name]
        if not lab_time.active():
            return original(self, value, instance, errors=errors)
        try:
            limit = self.get_min(instance) if is_min else self.get_max(instance)
            given, bound = _instant(_as_set(self, instance, value)), _instant(limit)
        except Exception:
            given = bound = None
        if given is None or bound is None:
            return original(self, value, instance, errors=errors)
        if (given >= bound) if is_min else (given <= bound):
            return None
        # outside the limit: SENAITE's own builds its message, handed the
        # earliest or latest datetime, which is outside any limit
        outside = datetime.datetime.min if is_min else datetime.datetime.max
        return original(self, outside, instance, errors=errors)
    wrapper.__name__ = str(attr)
    wrapper.__doc__ = "DateTimeField.{0}, value and limit compared as instants.".format(attr)
    return wrapper


# The wrapper each replaced method gets, by method name.
_WRAPPER_FOR = {
    "to_local_date": _fill_wrapper,
    "get_date": _fill_wrapper,
    "get_time": _fill_wrapper,
    "set": _set_wrapper,
    "to_str_date": _str_date_wrapper,
    "setValidTo": _valid_to_wrapper,
    "validate_min_date": _limit_wrapper,
    "validate_max_date": _limit_wrapper,
}


def _module(path):
    try:
        return importlib.import_module(path)
    except Exception as exc:
        logger.warning("core_dates: %s is not installed, left alone (%s)", path, exc)
        return None


def _original(path, attr):
    """The unwrapped function at path.attr, or None."""
    mod = _module(path)
    func = getattr(mod, attr, None) if mod is not None else None
    if func is None or getattr(func, _MARK, False):
        return None
    return func


def _rebind(pairs, wrapper, original):
    """Bind each name that holds `original` to `wrapper`; a name holding the
    wrapper already counts as bound, any other value is left alone."""
    names = []
    for path, attr in pairs:
        mod = _module(path)
        if mod is None:
            continue
        current = getattr(mod, attr, None)
        if current is None:
            logger.warning("core_dates: %s has no %s, left alone", path, attr)
            continue
        if current is original:
            setattr(mod, attr, wrapper)
        elif not getattr(current, _MARK, False):
            logger.warning("core_dates: %s.%s is %r, not the original; left alone",
                           path, attr, current)
            continue
        names.append("{0}.{1}".format(path, attr))
    return names


def _own_method(cls, attr):
    """(function, holder): the plain function the class finds for `attr` and
    the class in its lineage that holds it; (None, None) when none does.
    Read from the class dictionaries, so that Python 2 hands back the
    function itself rather than a new unbound method on every access."""
    for holder in inspect.getmro(cls):
        if attr in vars(holder):
            return vars(holder)[attr], holder
    return None, None


def _wrap_methods():
    """Replace each METHODS entry that is still its class's own function with
    its wrapper, set on the named class."""
    names = []
    for path, cls_name, attr in METHODS:
        mod = _module(path)
        if mod is None:
            continue
        name = "{0}.{1}.{2}".format(path, cls_name, attr)
        cls = getattr(mod, cls_name, None)
        func, holder = _own_method(cls, attr) if inspect.isclass(cls) else (None, None)
        if func is None:
            logger.warning("core_dates: %s has no %s.%s, left alone", path, cls_name, attr)
            continue
        if getattr(func, _MARK, False):
            if name in _METHOD_ORIGINALS:
                names.append(name)
            continue
        if not inspect.isfunction(func) or func.__module__ != holder.__module__:
            logger.warning("core_dates: %s is %r from %s, not %s's own; left alone",
                           name, func, getattr(func, "__module__", None), holder.__name__)
            continue
        _METHOD_ORIGINALS[name] = func
        wrapper = _WRAPPER_FOR[attr](name, attr)
        setattr(wrapper, _MARK, True)
        setattr(cls, attr, wrapper)
        names.append(name)
    return names


def install():
    """Rebind every BOUND and DATE_QUERY name and every METHODS entry to its
    wrapper; idempotent. Reads no setting. Returns the names now bound."""
    global _ORIGINAL, _ORIGINAL_DATE_QUERY
    names = []
    if _ORIGINAL is None:
        _ORIGINAL = _original(*BOUND[0])
    if _ORIGINAL is not None:
        names.extend(_rebind(BOUND, lab_ulocalized_time, _ORIGINAL))
    if _ORIGINAL_DATE_QUERY is None:
        _ORIGINAL_DATE_QUERY = _original(*DATE_QUERY[0])
    if _ORIGINAL_DATE_QUERY is not None:
        names.extend(_rebind(DATE_QUERY, lab_format_date_query, _ORIGINAL_DATE_QUERY))
    names.extend(_wrap_methods())
    return names
