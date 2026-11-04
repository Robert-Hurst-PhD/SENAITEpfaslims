# -*- coding: utf-8 -*-
"""What an equipment TYPE obliges.

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
    (which instruments run samples is the kind: an "Analytical instrument" is
    offered as a worksheet's instrument and listed in Import Studio)

Seeds are only what the lab has stated: balances read in grams
with an acceptance of 0.2 % of nominal; temperature probes are corrected to a
NIST reference by a study every quarter (90 days); analytical instruments are
offered in worksheets. Every other value is the lab's to enter -- blank means
"not set", never a guessed frequency.

Due dates: the external certificate's own valid-to date, when the type
requires one; the internal check every
cal_frequency_days since the last PFAS record. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import datetime

from senaite.pfas import lab_time

KINDS = [
    ("analytical", u"Analytical instrument"),
    ("balance_analytical", u"Analytical balance"),
    ("balance_prep", u"Top-loading balance"),
    ("pipette", u"Pipette"),
    ("refrigerator", u"Refrigerator"),
    ("freezer", u"Freezer"),
    ("water_bath", u"Water bath"),
    ("room_sensor", u"Room sensor"),
    # Spot-use temperature instruments: the thermometer requirements apply
    # (corrected by the quarterly NIST study), no daily check.
    ("thermometer", u"Thermometer (handheld / probe)"),
    ("ir_gun", u"IR thermometer (gun)"),
    ("nitrogen_evaporator", u"Nitrogen evaporator"),
    # The NIST-traceable reference the studies are read against: no quarterly
    # study of its own; verified externally (its SENAITE certificate).
    ("reference_thermometer", u"Reference thermometer (NIST-traceable)"),
    # Mills and cryogrinders: named on each sample's homogenisation record;
    # they measure nothing, so no calibration chain.
    ("homogeniser", u"Homogeniser (mill, cryogrinder)"),
    ("water_system", u"Type 1 water system"),
    ("eyewash", u"Eye wash station"),
    # satellite accumulation areas: registered so the Waste log lists them
    ("saa", u"SAA (waste container)"),
    ("other", u"Other"),
]
KIND_KEYS = [k for k, _l in KINDS]
BALANCE_KINDS = ("balance_analytical", "balance_prep")
# Kinds with no DAILY check: tracked by their due dates on the Equipment page,
# not listed on the Daily Checklist.
NOT_DAILY_KINDS = ("analytical", "pipette", "other", "saa", "thermometer", "ir_gun",
                   "nitrogen_evaporator", "reference_thermometer", "homogeniser")
FIELDS = ("kind", "cal_frequency_days", "correction_factor_required",
          "external_cert_required", "unit", "tolerance_pct", "correction_model")
# how a corrected thermometer is corrected (temp_calibration): one factor, or a
# multi-point calibration over its working temperatures
CORRECTION_MODELS = [(u"single", u"Single factor"), (u"multi_point", u"Multi-point")]
MULTI_POINT_KINDS = ("ir_gun", "thermometer")

# Kinds the thermometer requirements apply to: corrected to the NIST reference
# by the quarterly two-day study.
TEMPERATURE_KINDS = ("refrigerator", "freezer", "water_bath", "room_sensor", "thermometer", "ir_gun",
                     "nitrogen_evaporator")
# Monitored continuously (sensor readings against a range).
MONITORED_KINDS = ("refrigerator", "freezer", "water_bath", "room_sensor")
# Instruments a temperature can be taken with at sample receipt (the CoC).
RECEIPT_KINDS = ("ir_gun", "thermometer")
REFERENCE_KIND = "reference_thermometer"
STUDY_EVERY_DAYS = 90                 # "performed quarterly"
BALANCE_UNIT = u"g"

# the units a type reads in, grouped by quantity (Equipment Types' picker)
UNIT_GROUPS = [
    (u"Mass", [u"g", u"mg", u"\u00b5g", u"kg"]),
    (u"Volume", [u"\u00b5L", u"mL", u"L"]),
    (u"Temperature", [u"\u00b0C"]),
    (u"Conductivity", [u"\u00b5S/cm", u"M\u03a9\u00b7cm"]),
    (u"Concentration", [u"ppb", u"ppm", u"ng/L", u"\u00b5g/L"]),
    (u"Humidity", [u"%RH"]),
    (u"Time and speed", [u"min", u"h", u"rpm"]),
]


def unit_choices(current):
    """The picker's groups; a stored unit not in them is kept, under Other."""
    known = set(u for _g, us in UNIT_GROUPS for u in us)
    cur = (current or u"").strip()
    if cur and cur not in known:
        return UNIT_GROUPS + [(u"Other", [cur])]
    return list(UNIT_GROUPS)
BALANCE_TOLERANCE_PCT = 0.2          # the "balances ... 0.2%"
DUE_SOON_DAYS = 14


def seed(kind):
    """The requirements a new type of this kind starts with."""
    req = {"kind": kind if kind in KIND_KEYS else "other", "cal_frequency_days": None,
           "correction_factor_required": False, "external_cert_required": False,
           "unit": u"", "tolerance_pct": None, "correction_model": u"single"}
    if kind in BALANCE_KINDS:
        req.update(unit=BALANCE_UNIT, tolerance_pct=BALANCE_TOLERANCE_PCT)
    if kind in TEMPERATURE_KINDS:
        # the probes are corrected to a NIST reference by a quarterly
        # two-day study (facility_qc)
        req.update(unit=u"\u00b0C", correction_factor_required=True,
                   cal_frequency_days=STUDY_EVERY_DAYS,
                   correction_model=u"multi_point" if kind in MULTI_POINT_KINDS else u"single")
    if kind == REFERENCE_KIND:
        # the reference is exempt from the quarterly study, sent for an
        # external verification (its certificate's valid-to is the due date)
        req.update(unit=u"\u00b0C", external_cert_required=True)
    return req


def runs_samples(req):
    """An instrument of this type runs samples: offered as a worksheet's
    instrument and listed in Import Studio. The kind decides; a stored
    in_worksheets flag is ignored."""
    return (req or {}).get("kind") == "analytical"


def normalise(raw, kind=None):
    """Stored requirements over the seed for their kind; a balance always
    reads in grams, whatever was stored."""
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
    model = (form.get("correction_model") or u"").strip() or None
    if model is not None and model not in dict(CORRECTION_MODELS):
        errors.append(u"%s: unknown correction %s" % (label, model))
        model = None
    req = {"kind": kind, "cal_frequency_days": days, "correction_model": model,
           "correction_factor_required": on("correction_factor_required"),
           "external_cert_required": on("external_cert_required"),
           "unit": (form.get("unit") or u"").strip(), "tolerance_pct": pct}
    return normalise(req), errors


def working_temps(raw):
    """A unit's working temperatures (deg C) from its stored JSON list or a
    typed comma list; what is not a number is dropped."""
    import json
    vals = raw
    if isinstance(raw, (type(u""), str)):
        try:
            vals = json.loads(raw)
        except ValueError:
            vals = raw.split(u",")
    out = []
    for v in vals if isinstance(vals, list) else []:
        try:
            out.append(float(u"%s" % v))
        except (TypeError, ValueError):
            continue
    return out


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
    today = _date(today) or lab_time.today()
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
