# -*- coding: utf-8 -*-
"""What an equipment TYPE obliges (GAPS §100; DECISIONS 2026-10-03 "UI
consistency ... equipment").

Every piece of equipment is a core SENAITE Instrument with a core Instrument
Type, as the LC-MS/MS already is. The type carries the obligations; this is the
pure model of them. Stored per InstrumentType (annotation, browser/equipment.py):

    kind                        what the PFAS checks treat it as (KINDS)
    cal_frequency_days          internal check / calibration every N days
    correction_factor_required  readings are corrected (e.g. a thermometer)
    external_cert_required      an external calibration / audit certificate,
                                held as SENAITE's certificate on the instrument
    unit                        the unit it reads in
    tolerance_pct               acceptance, % of nominal
    in_worksheets               offered in SENAITE's worksheet instrument picker

Seeds are only what the lab has stated: balances read in grams with an
acceptance of 0.2 % of nominal (lab, 2026-10-03); analytical instruments are
offered in worksheets. Every other value is the lab's to enter -- blank means
"not set", never a guessed frequency.

Due dates (decided 2026-10-03, "both, split"): the external certificate's own
valid-to date, when the type requires one; the internal check every
cal_frequency_days since the last PFAS record. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import datetime

KINDS = [
    ("analytical", u"Analytical instrument (LC-MS/MS ...)"),
    ("balance_analytical", u"Balance — analytical"),
    ("balance_prep", u"Balance — preparatory"),
    ("pipette", u"Pipette"),
    ("refrigerator", u"Refrigerator"),
    ("freezer", u"Freezer"),
    ("room_sensor", u"Room sensor"),
    ("water_system", u"Type 1 water system"),
    ("eyewash", u"Eye wash station"),
    ("other", u"Other"),
]
KIND_KEYS = [k for k, _l in KINDS]
BALANCE_KINDS = ("balance_analytical", "balance_prep")
# Kinds with no DAILY check: tracked by their due dates on the Equipment page,
# not listed on the Daily Checklist (GAPS §100b).
NOT_DAILY_KINDS = ("analytical", "pipette", "other")
FIELDS = ("kind", "cal_frequency_days", "correction_factor_required",
          "external_cert_required", "unit", "tolerance_pct", "in_worksheets")

BALANCE_UNIT = u"g"
BALANCE_TOLERANCE_PCT = 0.2          # the lab, 2026-10-03: "balances ... 0.2%"
DUE_SOON_DAYS = 14


def seed(kind):
    """The requirements a new type of this kind starts with."""
    req = {"kind": kind if kind in KIND_KEYS else "other", "cal_frequency_days": None,
           "correction_factor_required": False, "external_cert_required": False,
           "unit": u"", "tolerance_pct": None, "in_worksheets": kind == "analytical"}
    if kind in BALANCE_KINDS:
        req.update(unit=BALANCE_UNIT, tolerance_pct=BALANCE_TOLERANCE_PCT)
    return req


def normalise(raw, kind=None):
    """Stored requirements over the seed for their kind; a balance always
    reads in grams (lab, 2026-10-03), whatever was stored."""
    raw = dict(raw or {})
    out = seed(raw.get("kind") or kind or "other")
    for k in FIELDS:
        if k in raw and raw[k] not in (None, u""):
            out[k] = raw[k]
    if out["kind"] in BALANCE_KINDS:
        out["unit"] = BALANCE_UNIT
    return out


def _num(v, cast=float):
    if v in (None, u"", ""):
        return None, u""
    try:
        n = cast(v)
    except (TypeError, ValueError):
        return None, u"not a number"
    return n, u""


def parse(form, label=u"type"):
    """(requirements, errors) from a form's values for one type."""
    errors = []
    kind = (form.get("kind") or u"other").strip()
    if kind not in KIND_KEYS:
        errors.append(u"%s: unknown kind %s" % (label, kind))
        kind = "other"
    days, err = _num(form.get("cal_frequency_days"), int)
    if err or (days is not None and days <= 0):
        errors.append(u"%s: calibration frequency must be a whole number of days" % label)
        days = None
    pct, err = _num(form.get("tolerance_pct"))
    if err or (pct is not None and pct <= 0):
        errors.append(u"%s: tolerance must be a positive %%" % label)
        pct = None
    on = lambda k: form.get(k) in (u"on", u"1", u"true", True, 1)  # noqa: E731
    req = {"kind": kind, "cal_frequency_days": days,
           "correction_factor_required": on("correction_factor_required"),
           "external_cert_required": on("external_cert_required"),
           "unit": (form.get("unit") or u"").strip(), "tolerance_pct": pct,
           "in_worksheets": on("in_worksheets")}
    return normalise(req), errors


# ── acceptance ───────────────────────────────────────────────────────────────

def tolerance_abs(nominal, pct):
    """The absolute acceptance for a reading of `nominal` at `pct` % of it."""
    return abs(float(nominal)) * float(pct) / 100.0


def within(nominal, actual, pct):
    """True when |actual - nominal| <= pct % of nominal. Both sides are
    rounded to 9 places first: 0.501 g against 0.5 g is exactly 0.2 % and must
    pass (in floating point the difference is 0.0010000000000000009)."""
    dev = round(abs(float(actual) - float(nominal)), 9)
    return dev <= round(tolerance_abs(nominal, pct), 9)


# ── due dates ────────────────────────────────────────────────────────────────

def _date(v):
    if not v:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.datetime.strptime(u"%s" % v[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def due(req, last_internal=None, cert_valid_to=None, today=None):
    """{"internal": {...}, "external": {...}, "status"} for one instrument.

    status: "ok" | "due_soon" | "overdue" | "missing" | "not_set"
      missing  -- the type requires an external certificate and none is valid
      not_set  -- nothing to judge (no frequency, no certificate required)
    """
    req = normalise(req)
    today = _date(today) or datetime.date.today()
    out = {"internal": None, "external": None}
    states = []
    days = req.get("cal_frequency_days")
    if days:
        last = _date(last_internal)
        nxt = (last + datetime.timedelta(days=int(days))) if last else None
        st = ("missing" if nxt is None else "overdue" if nxt < today else
              "due_soon" if (nxt - today).days <= DUE_SOON_DAYS else "ok")
        out["internal"] = {"last": last and last.isoformat(), "due": nxt and nxt.isoformat(),
                           "status": st}
        states.append(st)
    if req.get("external_cert_required"):
        to = _date(cert_valid_to)
        st = ("missing" if to is None else "overdue" if to < today else
              "due_soon" if (to - today).days <= DUE_SOON_DAYS else "ok")
        out["external"] = {"valid_to": to and to.isoformat(), "status": st}
        states.append(st)
    order = ["overdue", "missing", "due_soon", "ok"]
    out["status"] = next((s for s in order if s in states), "not_set")
    return out
