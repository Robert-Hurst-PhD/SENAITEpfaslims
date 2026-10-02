# -*- coding: utf-8 -*-
"""What the extraction logbook PDF prints, as plain data (@@pfas-extraction-pdf
lays it out; docs/REUSE_REVIEW.md U1). Pure; Python 2.7 and 3."""
from __future__ import absolute_import, unicode_literals

DASH = u"\u2014"


def _text(value):
    """A printable cell: the value as text, a dash for nothing."""
    if value is None or value == u"" or value == {}:
        return DASH
    return u"%s" % value


def logbook_data(batch_id, batch_title, session, profile, generated):
    """Everything the logbook prints, as plain data."""
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
            # what the deviation note had to explain (DB4, DECISIONS 2026-10-02)
            "warnings": [_text(w) for w in sd.get("warnings") or []],
            "solutions": [[_text(s.get("name")), _text(s.get("lot")), _text(s.get("conc")),
                           _text(s.get("volume_ml")), _text(s.get("expiry"))]
                          for s in sd.get("solutions_prepared") or []],
            "deviations": sd.get("deviations") or u"",
        })
    # "pedigree" = one spike record per spiked QC sample (what the review step
    # records: lot, volume, spike level, parent sample, who / when). An older
    # list-of-levels shape is still read.
    spikes, pedigree = [], []
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
        "summary": summary, "details": details, "spikes": spikes, "pedigree": pedigree,
        "signoff": [(u"Extraction Analyst", _text(session.get("analyst"))),
                    (u"Reviewing Analyst", _text(session.get("finalized_by"))),
                    (u"Date Finalized", _text(session.get("finalized_at")))],
    }
