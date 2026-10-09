# -*- coding: utf-8 -*-
"""The CoC entry sheet's rows: read from
the form, checked, and turned into SENAITE sample values.

A row is one sample as the sampler states it:

    {"client_sid", "sampletype", "sampling_point", "sampled" (YYYY-MM-DDTHH:MM),
     "container", "preservation", "method", "homogenisation",
     "composite" (bool), "units", "description", "field_qc", "field_qc_of",
     "sample_uid" (once the sample exists)}

Form names: r__<n>__<key>, one field per box (flatten_form keeps only the
first value of a list). Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

ROW_KEYS = ("client_sid", "sampletype", "sampling_point", "sampled", "container",
            "preservation", "method", "homogenisation", "composite", "units",
            "description", "field_qc", "field_qc_of", "sample_uid")
HEADER_KEYS = ("project", "project_number", "sampler", "carrier", "tracking", "seals")


def rows_from_form(form):
    by = {}
    for k, v in (form or {}).items():
        k = u"%s" % k
        if not k.startswith(u"r__"):
            continue
        parts = k.split(u"__")
        if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ROW_KEYS + ("remove",):
            continue
        by.setdefault(int(parts[1]), {})[parts[2]] = (u"%s" % v).strip()
    out = []
    for i in sorted(by):
        r = dict((k, by[i].get(k, u"")) for k in ROW_KEYS)
        r["composite"] = r["composite"] in (u"on", u"True", u"true", u"1")
        # a row not yet a sample can be taken off; a sample is cancelled in SENAITE
        if (by[i].get("remove") and not r["sample_uid"]) or not any(r[k] for k in ROW_KEYS if k not in ("composite", "sample_uid")):
            continue                     # an empty row added and left blank
        out.append(r)
    return out


def header_from_form(form):
    return dict((k, (u"%s" % ((form or {}).get(k) or u"")).strip()) for k in HEADER_KEYS)


def row_problems(rows, field_qc_types):
    """What must be fixed before the CoC can be submitted."""
    out = []
    if not rows:
        return [u"Add at least one sample."]
    ids = [r.get("client_sid") for r in rows]
    for n, r in enumerate(rows, 1):
        who = r.get("client_sid") or u"Row %d" % n
        for key, what in (("client_sid", u"a sample ID"), ("sampletype", u"the matrix"),
                          ("sampled", u"the collection date and time"),
                          ("method", u"the analysis")):
            if not r.get(key):
                out.append(u"%s: give %s" % (who, what))
        if r.get("client_sid") and ids.count(r["client_sid"]) > 1:
            out.append(u"%s: the sample ID is used twice" % who)
        if r.get("composite"):
            try:
                ok = int(r.get("units") or 0) >= 2
            except ValueError:
                ok = False
            if not ok:
                out.append(u"%s: a composite needs the number of units combined (2 or more)" % who)
            if not r.get("description"):
                out.append(u"%s: a composite needs what was combined" % who)
        if r.get("field_qc"):
            if r["field_qc"] not in field_qc_types:
                out.append(u"%s: unknown field QC type" % who)
            if not r.get("field_qc_of"):
                out.append(u"%s: say which sample this %s goes with" % (who, r["field_qc"].lower()))
            elif r["field_qc_of"] not in ids or r["field_qc_of"] == r.get("client_sid"):
                out.append(u"%s: %s is not another sample on this CoC" % (who, r["field_qc_of"]))
    # keep the order, drop repeats (two rows can share a problem)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def sample_values(row, client_uid, contact_uid):
    """SENAITE create_analysisrequest values for a row (profile and CoC
    number are added by the caller)."""
    sampled = (row.get("sampled") or u"").replace(u"T", u" ")
    v = {"Client": client_uid, "Contact": contact_uid, "SampleType": row.get("sampletype"),
         "DateSampled": sampled, "ClientSampleID": row.get("client_sid"),
         "Composite": bool(row.get("composite")),
         "CompositeUnits": int(row["units"]) if (row.get("units") or u"").isdigit() else None,
         "CompositeDescription": row.get("description") or u"",
         "HomogenisationMethod": row.get("homogenisation") or u"",
         "FieldQCType": row.get("field_qc") or u"", "FieldQCOf": row.get("field_qc_of") or u""}
    for key, field in (("sampling_point", "SamplePoint"), ("container", "Container"),
                       ("preservation", "Preservation")):
        if row.get(key):
            v[field] = row[key]
    return v


def changed_fields(old, new):
    """{key: (old, new)} of a submitted row's edits (logged, CW2)."""
    out = {}
    for k in ROW_KEYS:
        if k == "sample_uid":
            continue
        if (old or {}).get(k) != (new or {}).get(k):
            out[k] = ((old or {}).get(k), (new or {}).get(k))
    return out
