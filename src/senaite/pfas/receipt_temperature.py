# -*- coding: utf-8 -*-
"""Receipt temperatures on the chain of custody, corrected: every
thermometer used at sample receipt is recorded on the CoC with its
correction factor applied.

A logbook field of type `thermometer` names the instrument the temperatures
were taken with (an IR gun or a thermometer registered on Equipment). When the
logbook is saved, the field's RECORD is frozen beside it -- the instrument, its
serial, and the correction factor in force on the receipt date with the study
it came from -- so the CoC keeps the factor that was applied even after the
next quarterly study changes it. A table column declared
`"corrected_by": "<thermometer field>"` gets `<column>_corrected` on every row
(observed + factor). The record is re-frozen only if the instrument or the
receipt date changes.

    freeze(unit, calibration, as_of)      -> record (facility_qc.calibration:
                                             a single factor, or the points
                                             of a multi-point calibration)
    corrected(value, record)              -> float | None
    enrich(data, schema, get_unit, get_correction, as_of)  (in place)

Status of a record: "corrected"; "uncorrected" (the type requires a factor
but no passed study was in force -- said, never hidden); "not_required".
Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import equipment_types as et
from senaite.pfas import temp_calibration as tc

RECORD_SUFFIX = u"_record"
CORRECTED_SUFFIX = u"_corrected"


def freeze(unit, correction, as_of):
    if not unit:
        return None
    req = unit.get("requirements") or et.seed(unit.get("unit_type"))
    needs = bool(req.get("correction_factor_required"))
    rec = {"uid": unit.get("id"), "name": unit.get("name") or u"",
           "serial": unit.get("serial_number") or u"", "kind": unit.get("unit_type") or u"",
           "as_of": (as_of or u"")[:10], "required": needs,
           "correction": None, "study_date": None, "study_id": None}
    cal = correction or {}
    if needs and cal.get("model") == tc.MULTI:
        # a multi-point calibration: its points frozen, each container
        # corrected on its own (temp_calibration)
        rec.update(model=tc.MULTI, points=list(cal.get("points") or []),
                   missing=list(cal.get("missing") or []),
                   status=u"corrected" if cal.get("points") else u"uncorrected")
    elif needs and cal.get("correction") is not None:
        rec.update(correction=cal.get("correction"), study_date=cal.get("study_date"),
                   study_id=cal.get("study_id"), status=u"corrected")
    else:
        rec["status"] = u"uncorrected" if needs else u"not_required"
    return rec


from senaite.pfas.rounding import number as _num


def corrected(value, record):
    """observed + factor; the observed value when no factor applies; None
    when there is no number."""
    v = _num(value)
    if v is None:
        return None
    fixed, _outside = tc.correct(v, record or {})
    return fixed if fixed is not None else v


def thermometer_fields(schema):
    return [f.get("name") for f in schema or [] if f.get("type") == "thermometer" and f.get("name")]


def enrich(data, schema, get_unit, get_correction, as_of):
    """Freeze each thermometer field's record and correct the columns that
    name it. `get_unit(uid)` and `get_correction(uid, as_of)` are
    facility_qc.get_unit / calibration."""
    as_of = (as_of or u"")[:10]
    records = {}
    for name in thermometer_fields(schema):
        uid = (data.get(name) or u"").strip() if isinstance(data.get(name), (type(u""), str)) else u""
        old = data.get(name + RECORD_SUFFIX) or {}
        if not uid:
            data.pop(name + RECORD_SUFFIX, None)
            continue
        if old.get("uid") == uid and old.get("as_of") == as_of:
            rec = old                                    # frozen: keep what was applied
        else:
            rec = freeze(get_unit(uid), get_correction(uid, as_of), as_of)
        if rec:
            data[name + RECORD_SUFFIX] = rec
            records[name] = rec
    for field in schema or []:
        if field.get("type") != "table":
            continue
        rows = data.get(field.get("name"))
        if not isinstance(rows, list):
            continue
        for col in field.get("columns") or []:
            src = col.get("corrected_by")
            if not src:
                continue
            rec = records.get(src)
            for row in rows:
                if isinstance(row, dict):
                    row[col["name"] + CORRECTED_SUFFIX] = corrected(row.get(col["name"]), rec) if rec else None
    return data


# ── the CoC's receipt thermometer field ─────────────────────────

RECEIPT_FIELD = {"name": "receipt_thermometer", "label": "Receipt thermometer",
                 "type": "thermometer", "required": True}


