# -*- coding: utf-8 -*-
"""The CoC entry sheet's rows: read from the form, checked, and turned into
SENAITE sample values.

A row is one sample as the sampler states it:

    {"client_sid", "sampletype", "subtype" (a sample_subtypes id, optional),
     "sampling_point", "sampled" (YYYY-MM-DDTHH:MM),
     "container", "preservation", "method", "homogenisation",
     "composite" (bool), "units", "description", "field_qc", "field_qc_of",
     "compliance" (bool: a regulatory compliance sample, receipt_compliance),
     "sample_uid" (once the sample exists)}

Form names: r__<n>__<key>, one field per box (flatten_form keeps only the
first value of a list). Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import lab_time

ROW_KEYS = ("client_sid", "sampletype", "subtype", "sampling_point", "sampled", "container",
            "preservation", "method", "homogenisation", "composite", "units",
            "description", "field_qc", "field_qc_of", "compliance", "sample_uid")
# Custody seals are not asked: a CoC that recorded them keeps the answer,
# which its page shows as stored and a save never touches.
HEADER_KEYS = ("project", "project_number", "sampler", "carrier", "tracking")


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
        r["compliance"] = r["compliance"] in (u"on", u"True", u"true", u"1")
        # a row not yet a sample can be taken off; a sample is cancelled in SENAITE
        if (by[i].get("remove") and not r["sample_uid"]) or not any(r[k] for k in ROW_KEYS if k not in ("composite", "compliance", "sample_uid")):
            continue                     # an empty row added and left blank
        out.append(r)
    return out


# What a row's detail dialog holds besides the composite and compliance:
# each posts under its own name and is read back in words by detail_summary
# and by coc_row_detail.js, which write the same words.
DETAIL_CHOICES = (("subtype", u"Sub-type"), ("sampling_point", u"Sampling point"),
                  ("container", u"Container"), ("preservation", u"Preservative"),
                  ("homogenisation", u"Homogenisation"))
DETAIL_NONE = u"No composite, container or preservative set"


def composite_words(row):
    """A composite in words: "" when the row is not one, else the units
    combined and what was combined."""
    row = row or {}
    if not row.get("composite"):
        return u""
    units = (u"%s" % (row.get("units") or u"")).strip()
    what = (u"%s" % (row.get("description") or u"")).strip()
    head = u"Composite of %s units" % units if units else u"Composite"
    return u"%s: %s" % (head, what) if what else head


def detail_summary(row, names):
    """What a row's detail dialog holds, in words: only what is set.
    `names`: {key: {stored value: text}} for the choices; a value without a
    text is shown as stored."""
    row = row or {}
    out = [composite_words(row)]
    for key, label in DETAIL_CHOICES:
        v = (u"%s" % (row.get(key) or u"")).strip()
        if v:
            out.append(u"%s %s" % (label, (names or {}).get(key, {}).get(v, v)))
    if row.get("compliance"):
        out.append(u"Compliance sample")
    return u" \u00b7 ".join(x for x in out if x) or DETAIL_NONE


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


def subtype_problems(rows, subtypes_by_type):
    """A row's sub-type must be one of its matrix's and analysed by its
    method (sample_subtypes). `subtypes_by_type`: {sample type uid: subtypes}."""
    out = []
    for n, r in enumerate(rows or [], 1):
        sid = r.get("subtype")
        if not sid:
            continue
        who = r.get("client_sid") or u"Row %d" % n
        sub = dict((x["id"], x) for x in subtypes_by_type.get(r.get("sampletype")) or []).get(sid)
        if sub is None:
            out.append(u"%s: %s is not a sub-type of its matrix." % (who, sid))
        elif r.get("method") in (sub.get("off") or []):
            out.append(u"%s: %s is not analysed by this method; choose another sub-type or none." % (who, sub["name"]))
    return out


def sample_values(row, client_uid, contact_uid):
    """SENAITE create_analysisrequest values for a row (profile and CoC
    number are added by the caller)."""
    sampled = (row.get("sampled") or u"").replace(u"T", u" ")
    # the collection time is typed on the laboratory's clock; unset, the
    # text goes to SENAITE as before
    if lab_time.active():
        sampled = lab_time.typed(sampled) or sampled
    v = {"Client": client_uid, "Contact": contact_uid, "SampleType": row.get("sampletype"),
         "DateSampled": sampled, "ClientSampleID": row.get("client_sid"),
         "Composite": bool(row.get("composite")),
         "CompositeUnits": int(row["units"]) if (row.get("units") or u"").isdigit() else None,
         "CompositeDescription": row.get("description") or u"",
         "HomogenisationMethod": row.get("homogenisation") or u"",
         "FieldQCType": row.get("field_qc") or u"", "FieldQCOf": row.get("field_qc_of") or u"",
         "ComplianceSample": bool(row.get("compliance")),
         "SampleSubtype": row.get("subtype") or u""}
    for key, field in (("sampling_point", "SamplePoint"), ("container", "Container"),
                       ("preservation", "Preservation")):
        if row.get(key):
            v[field] = row[key]
    return v


def changed_fields(old, new):
    """{key: (old, new)} of a submitted row's edits (logged)."""
    out = {}
    for k in ROW_KEYS:
        if k == "sample_uid":
            continue
        if (old or {}).get(k) != (new or {}).get(k):
            out[k] = ((old or {}).get(k), (new or {}).get(k))
    return out
