# -*- coding: utf-8 -*-
"""Receipt temperatures on the chain of custody, corrected.

"Any thermometer used for sample receipt should be recorded
within the CoC with the associated correction factor applied."

A logbook field of type `thermometer` names the instrument the temperatures
were taken with (an IR gun or a thermometer registered on Equipment). When the
logbook is saved, the field's RECORD is frozen beside it -- the instrument, its
serial, and the correction factor in force on the receipt date with the study
it came from -- so the CoC keeps the factor that was applied even after the
next quarterly study changes it. A table column declared
`"corrected_by": "<thermometer field>"` gets `<column>_corrected` on every row
(observed + factor). The record is re-frozen only if the instrument or the
receipt date changes.

    freeze(unit, correction, as_of)       -> record
    corrected(value, record)              -> float | None
    enrich(data, schema, get_unit, get_correction, as_of)  (in place)

Status of a record: "corrected"; "uncorrected" (the type requires a factor
but no passed study was in force -- said, never hidden); "not_required".
Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas import equipment_types as et
except ImportError:                                  # tests
    import equipment_types as et

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
    if needs and correction:
        rec.update(correction=correction.get("correction"), study_date=correction.get("study_date"),
                   study_id=correction.get("study_id"), status=u"corrected")
    else:
        rec["status"] = u"uncorrected" if needs else u"not_required"
    return rec


def _num(v):
    if v in (None, u"", ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def corrected(value, record):
    """observed + factor; the observed value when no factor applies; None
    when there is no number."""
    v = _num(value)
    if v is None:
        return None
    c = (record or {}).get("correction")
    return round(v + c, 3) if c is not None else v


def thermometer_fields(schema):
    return [f.get("name") for f in schema or [] if f.get("type") == "thermometer" and f.get("name")]


def enrich(data, schema, get_unit, get_correction, as_of):
    """Freeze each thermometer field's record and correct the columns that
    name it. `get_unit(uid)` and `get_correction(uid, as_of)` are
    facility_qc.get_unit / current_correction."""
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


# ── the CoC schema change ───────────────────────────────────────

RECEIPT_FIELD = {"name": "receipt_thermometer", "label": "Receipt thermometer",
                 "type": "thermometer", "required": True}


def add_receipt_thermometer(schema, table="containers", column="temp_c"):
    """The CoC schema with a receipt-thermometer field after the containers
    table, and that table's temperature column corrected by it. Returns
    (schema, changed); a schema that already has it is returned unchanged."""
    import copy
    out = copy.deepcopy(schema or [])
    names = [f.get("name") for f in out]
    changed = False
    if RECEIPT_FIELD["name"] not in names:
        at = names.index(table) + 1 if table in names else len(out)
        out.insert(at, dict(RECEIPT_FIELD))
        changed = True
    for f in out:
        if f.get("name") == table and f.get("type") == "table":
            for c in f.get("columns") or []:
                if c.get("name") == column and c.get("corrected_by") != RECEIPT_FIELD["name"]:
                    c["type"] = "number"
                    c["corrected_by"] = RECEIPT_FIELD["name"]
                    changed = True
    return out, changed
