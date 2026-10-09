# -*- coding: utf-8 -*-
"""What the extraction logbook PDF prints, as plain data (@@pfas-extraction-pdf
lays it out). Pure; Python 2.7 and 3."""
from __future__ import absolute_import, unicode_literals

DASH = u"\u2014"


def _text(value):
    """A printable cell: the value as text, a dash for nothing."""
    if value is None or value == u"" or value == {}:
        return DASH
    return u"%s" % value


def roster(members, sample_rows=None, ports=None):
    """What was extracted in the batch: every member,
    samples and QC, in batch order -- [name, role, made from, matrix,
    amount, final volume, SPE port]. `sample_rows` are FM-ENV-003's rows
    (amount, final volume by name); `ports` = {name: port}. A batch from
    before extraction members lists its sample rows."""
    ports = ports or {}
    rows = dict(((r.get("sample_id") or u"").strip(), r) for r in sample_rows or []
                if isinstance(r, dict) and not (r.get("dilution_of") or u"").strip())
    by_id = dict((m.get("id"), m) for m in members or [])
    listed = [(m.get("injection") or m.get("id"), m.get("role") or u"",
               (by_id.get(m.get("parent")) or {}).get("injection") or u"",
               m.get("matrix") or u"") for m in members or []]
    if not listed:
        listed = [(n, u"Sample", u"", r.get("matrix_type") or r.get("matrix") or u"")
                  for n, r in sorted(rows.items()) if n]
    out = []
    for name, role, parent, matrix in listed:
        r = rows.get(name) or {}
        amount = (u"%s %s" % (r.get("amount"), r.get("amount_unit") or u"")).strip() \
            if r.get("amount") not in (None, u"") else u""
        final = (u"%s mL" % r.get("final_volume_ml")) \
            if r.get("final_volume_ml") not in (None, u"") else u""
        out.append([_text(name), _text(role), _text(parent),
                    _text(matrix or r.get("matrix_type")), _text(amount), _text(final),
                    _text(ports.get(name))])
    return out


def logbook_data(batch_id, batch_title, session, profile, generated, spike_rows=None,
                 extracted=None):
    """Everything the logbook prints, as plain data. `spike_rows`: FM-ENV-003's
    batch QC as spike rows (sample_id, spike_of, spike_amount, spike_unit,
    logged_by, logged_at, qc_type), printed first in the spikes. `extracted`:
    roster() -- what the batch extracted."""
    session, profile = session or {}, profile or {}
    method_name = profile.get("display_name") or session.get("method_id") or u""
    stages_config = sorted(profile.get("extraction_stages") or [],
                           key=lambda s: s.get("order", 0))
    completed = session.get("stages") or {}
    summary, details = [], []
    for sc in stages_config:
        order = u"%s" % sc.get("order", u"")
        sd = completed.get(order) or {}
        summary.append({"order": order, "name": _text(sc.get("name")),
                        "completed": _text(sd.get("completed_at")),
                        "analyst": _text(sd.get("analyst")),
                        "deviations": _text(sd.get("deviations"))})
        if not sd:
            continue
        rows = [r for r in sd.get("reagents") or [] if isinstance(r, dict)]

        def cells(r):
            return [_text(r.get("name") or r.get("role")), _text(r.get("lot")),
                    _text(r.get("supplier")), _text(r.get("volume") or r.get("qty_used")),
                    _text(r.get("expiry"))]
        details.append({
            "title": u"Stage %s: %s" % (order, sc.get("name", u"")),
            "equipment": [(_text(eq), _text(sn)) for eq, sn in
                          sorted((sd.get("equipment_sns") or {}).items())],
            "reagents": [cells(r) for r in rows if r.get("group") != u"consumable"],
            "consumables": [cells(r) for r in rows if r.get("group") == u"consumable"],
            # what the deviation note had to explain
            "warnings": [_text(w) for w in sd.get("warnings") or []],
            # the stage's checks the chemist ticked (stage editor)
            "confirmed": [_text(c) for c in sd.get("confirmed") or []],
            # each sample's homogenisation as the processing stage confirmed it
            "homogenisation": [[_text(h.get("sample_id")), _text(h.get("requested")),
                                _text(h.get("method")), _text(h.get("unit")),
                                _text(h.get("composite")), _text(h.get("units_combined")),
                                _text(h.get("by")), _text(h.get("at"))]
                               for h in sd.get("homogenisation") or [] if isinstance(h, dict)],
            "solutions": [[_text(s.get("name")), _text(s.get("lot")), _text(s.get("conc")),
                           _text(s.get("volume_ml")), _text(s.get("expiry"))]
                          for s in sd.get("solutions_prepared") or []],
            "deviations": sd.get("deviations") or u"",
        })
    # "pedigree" = one spike record per spiked QC sample (what the review step
    # records: lot, volume, spike level, parent sample, who / when). An older
    # list-of-levels shape is still read.
    spikes, pedigree = [], []
    for r in spike_rows or []:
        if isinstance(r, dict):
            spikes.append([_text(r.get("sample_id")), _text(r.get("spike_of")), DASH, DASH,
                           _text((u"%s %s" % (r.get("spike_amount", r.get("spike_ppt")),
                                               r.get("spike_unit") or u"ppt"))
                                 if (r.get("spike_amount") or r.get("spike_ppt"))
                                 else (u"%s (method level)" % (r.get("level") or u"?"))),
                           _text(r.get("logged_by")), _text(r.get("logged_at")),
                           _text(r.get("qc_type"))])
    for name, rec in sorted((session.get("pedigree") or {}).items()):
        if isinstance(rec, dict):
            spikes.append([_text(name), _text(rec.get("parent_sample")),
                           _text(rec.get("spike_lot")), _text(rec.get("spike_volume_ul")),
                           _text(rec.get("spike_ppt")), _text(rec.get("spike_entered_by")),
                           _text(rec.get("spike_entered_at")), _text(rec.get("spike_source"))])
        elif isinstance(rec, list):
            pedigree.append({"name": name, "rows": [
                [_text(l.get("level")), _text(l.get("lot")),
                 _text(l.get("cert_conc") or l.get("conc")),
                 _text(l.get("supplier") or l.get("prepared_by")),
                 _text(l.get("cert_date") or l.get("prepared_date")), _text(l.get("coa"))]
                for l in rec if isinstance(l, dict)]})
    return {
        "method_name": method_name,
        "header": [(u"Batch ID", _text(batch_id)), (u"Batch Title", _text(batch_title)),
                   (u"Method", _text(method_name)),
                   (u"Lead Analyst", _text(session.get("analyst"))),
                   (u"Started", _text(session.get("started_at"))),
                   (u"Finalized", _text(session.get("finalized_at"))),
                   (u"Reviewing Analyst", _text(session.get("finalized_by"))),
                   (u"PDF Generated", generated)],
        "extracted": list(extracted or []),
        "summary": summary, "details": details, "spikes": spikes, "pedigree": pedigree,
        "signoff": [(u"Extraction Analyst", _text(session.get("analyst"))),
                    (u"Reviewing Analyst", _text(session.get("finalized_by"))),
                    (u"Date Finalized", _text(session.get("finalized_at")))],
    }
