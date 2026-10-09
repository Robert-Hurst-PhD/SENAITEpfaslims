# -*- coding: utf-8 -*-
"""Equipment in the Settings Report: the record an assessor reads
for ISO/IEC 17025 §6.4 -- what each equipment type obliges, how the system
applies it, and where every instrument stands, as of the report.

The "how it is applied" statements are BUILT FROM THE CONSTANTS the code
uses (equipment_types, facility_qc), so the report cannot describe a rule the
code does not run; tests/test_equipment_report.py pins that.

    application()                 -> [(topic, statement)]
    type_rows(types)              -> rows for the types table
    instrument_rows(instruments)  -> rows for the instruments table
    config(types, instruments)    -> what goes into the report fingerprint

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas import equipment_types as et
except ImportError:                                  # tests
    import equipment_types as et

STATUS = {"ok": u"OK", "due_soon": u"Due soon", "overdue": u"Overdue",
          "missing": u"No record", "not_set": u"Not set"}


def _num(v):
    return (u"%d" % v) if float(v) == int(v) else (u"%g" % v)


def application(study_points, study_min_days):
    """How the system applies each equipment obligation. `study_points` and
    `study_min_days` are facility_qc.STUDY_POINTS / STUDY_MIN_DAYS."""
    return [
        (u"Balance verification",
         u"A weight point passes when |reading - nominal| <= the balance type's tolerance "
         u"x nominal, compared at 9 decimal places so a reading exactly on the limit passes. "
         u"Balances read in %s; a new balance type starts at %s %% of nominal. "
         u"The absolute tolerance each point was judged against is stored with it."
         % (et.BALANCE_UNIT, _num(et.BALANCE_TOLERANCE_PCT))),
        (u"Thermometer correction factor",
         u"For a type that requires a correction factor: a temperature study is %d paired "
         u"readings (the probe beside a NIST-traceable reference thermometer) spanning at "
         u"least %d days, passed only if every pair is within the study tolerance. The factor "
         u"is the NIST average minus the probe average, from the latest PASSED study on or "
         u"before a reading; each reading is judged against its range as probe + factor and "
         u"stored raw with the factor beside it. A failed or incomplete study supplies no "
         u"factor. A study reading changed after entry keeps its previous value, who "
         u"entered it, who changed it and when." % (study_points, study_min_days)),
        (u"Internal checks and due dates",
         u"Each type sets a check interval in days, counted from the last record kept for "
         u"the instrument: balance verification, pipette calibration, a completed "
         u"temperature study, an eye wash log. Due within %d days is 'due soon'; past it, "
         u"'overdue'; a required check never recorded, 'no record'. Temperature types start "
         u"at %d days (quarterly)." % (et.DUE_SOON_DAYS, et.STUDY_EVERY_DAYS)),
        (u"Reference thermometer",
         u"The NIST-traceable reference the studies are read against has no quarterly "
         u"study of its own; it is verified externally, and its SENAITE certificate's "
         u"valid-to date is its due date. A study that names a registered reference is "
         u"flagged when no certificate of that reference was in force on the study date."),
        (u"Receipt temperatures (chain of custody)",
         u"The CoC records the instrument the receipt temperatures were taken with (IR "
         u"thermometer or thermometer registered as equipment) and, frozen with it, the "
         u"correction factor in force on the receipt date and its study; each container's "
         u"temperature is stored as observed and corrected (observed + factor). With no "
         u"passed study the CoC records the temperatures as UNCORRECTED, and Data Review "
         u"shows it."),
        (u"External certificates",
         u"Where a type requires one, the instrument's latest valid SENAITE certificate "
         u"decides: its valid-to date is the due date; none on file is 'no record'."),
        (u"Worksheet instrument selection",
         u"SENAITE's worksheet instrument pickers offer only instruments whose type is "
         u"marked 'in worksheets'; a type nobody has set up stays offered, as in SENAITE."),
        (u"Release",
         u"Equipment and facility records do not gate batch release (ISO 17025 §6.4 is "
         u"reviewed on its own cadence); a balance or pipette used in a batch is traced in "
         u"Data Review through its verification, weight set and metrology certificate."),
    ]


def _yes(v):
    return u"Yes" if v else u"No"


def type_rows(types):
    """types: [{"title", "req"}] -> display rows."""
    kinds = dict(et.KINDS)
    out = []
    for t in types or []:
        r = t.get("req") or {}
        out.append({
            "title": t.get("title") or u"",
            "configured": bool(r.get("configured", True)),
            "kind": kinds.get(r.get("kind"), r.get("kind") or u""),
            "every": (u"%d days" % r["cal_frequency_days"]) if r.get("cal_frequency_days") else u"not set",
            "correction": _yes(r.get("correction_factor_required")),
            "external": _yes(r.get("external_cert_required")),
            "unit": r.get("unit") or u"",
            "tolerance": (u"%s %% of nominal" % _num(r["tolerance_pct"])) if r.get("tolerance_pct") else u"",
            "worksheets": _yes(r.get("in_worksheets")),
        })
    return out


def instrument_rows(instruments):
    """instruments: [{"unit", "due", "correction", "study"}] -> display rows.
    `correction` is facility_qc.current_correction(...) or None; `study` the
    study it came from ({"study": {...}, "changes": n}) or None."""
    out = []
    for i in instruments or []:
        u, d = i.get("unit") or {}, i.get("due") or {}
        internal, external = d.get("internal") or {}, d.get("external") or {}
        cf, st = i.get("correction"), (i.get("study") or {}).get("study") or {}
        req = u.get("requirements") or {}
        if req.get("correction_factor_required"):
            corr = (u"%+.3f °C, study of %s (NIST %s, %s)%s" % (
                cf["correction"], cf["study_date"], st.get("nist_serial") or u"?",
                st.get("operator") or u"?",
                (u"; %d reading(s) changed after entry" % i["study"]["changes"])
                if (i.get("study") or {}).get("changes") else u"")
                    + (u"; reference %s %s" % (i["reference"]["name"],
                                               u"verified" if i["reference"]["ok"] else u"NOT VERIFIED: " + i["reference"]["why"])
                       if i.get("reference") else u"")
                    if cf else u"none: no passed study; readings judged uncorrected")
        else:
            corr = u"not required"
        out.append({
            "name": u.get("name") or u"", "serial": u.get("serial_number") or u"",
            "type": u.get("type_title") or u"", "location": u.get("location") or u"",
            "active": bool(u.get("active", 1)),
            "internal": (u"last %s, due %s" % (internal.get("last") or u"none", internal.get("due") or u"-"))
                        if internal else u"no interval set",
            "external": (u"valid to %s" % external["valid_to"] if external.get("valid_to") else u"none on file")
                        if external else u"not required",
            "status": STATUS.get(d.get("status"), d.get("status") or u""),
            "correction": corr,
        })
    return out


def config(types, instruments):
    """The equipment configuration, for the report fingerprint: each type's
    requirements and each instrument's PFAS settings (not its records)."""
    return {"types": sorted([(t.get("uid") or t.get("title"),
                              dict((k, (t.get("req") or {}).get(k)) for k in et.FIELDS))
                             for t in types or []]),
            "instruments": sorted([((i.get("unit") or {}).get("id"),
                                    dict((k, (i.get("unit") or {}).get(k)) for k in (
                                        "type_uid", "serial_number", "sensor_id", "temp_min",
                                        "temp_max", "humidity_min", "humidity_max",
                                        "study_tolerance", "weight_points_json",
                                        "extra_config_json")))
                                   for i in instruments or []])}
