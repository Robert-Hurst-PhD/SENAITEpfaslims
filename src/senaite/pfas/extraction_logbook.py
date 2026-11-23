# -*- coding: utf-8 -*-
"""What the extraction logbook PDF prints, as plain data (@@pfas-extraction-pdf
lays it out). Pure; Python 2.7 and 3."""
from __future__ import absolute_import, unicode_literals

from senaite.pfas import print_doc
from senaite.pfas import worksheet_lots

DASH = u"\u2014"
# a spiked QC member the batch recorded no lot, volume or level for, and a
# member that is not spiked at all
NOT_RECORDED = u"Not recorded"
NOT_SPIKED = u"Not spiked"


def _text(value):
    """A printable cell: the value as text, a dash for nothing."""
    if value is None or value == u"" or value == {}:
        return DASH
    return u"%s" % value


def roster(members, sample_rows=None, ports=None):
    """What was extracted in the batch: every member,
    samples and QC, in batch order -- [name, role, made from, matrix,
    amount, final volume, SPE port]. `sample_rows` are the extraction record's rows
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


def _answer_rows(stage, answers):
    from senaite.pfas.stage_form import answer_rows
    return answer_rows(stage, answers)


def _stamp(at):
    """A stored stamp (UTC) on the laboratory's clock; as stored while no
    zone converts."""
    return print_doc.lab_or(at, _text(at))


def _logged(at):
    """A dilution's logged stamp (UTC) to the minute on the laboratory's clock."""
    at = at or u""
    return print_doc.lab_or(at, at[:16].replace(u"T", u" "))


def dilutions(sample_rows):
    """The extraction record's dilutions as printed: [diluted from, injection,
    fold, route, aliquot, by, at]."""
    from senaite.pfas.sample_table import dilutions as _dil, route_key, _routes
    labels = dict(_routes())
    return [[_text(r.get("dilution_of")), _text(r.get("sample_id")), _text(r.get("dilution_factor")),
             _text(labels.get(route_key(r.get("route")))), _text(r.get("aliquot")),
             _text(r.get("logged_by")), _text(_logged(r.get("logged_at")))]
            for r in _dil(sample_rows)]


def _given(value):
    return value not in (None, u"", "")


def _amount(amount, unit):
    return (u"%s %s" % (amount, unit or u"")).strip()


def _spike_level(row, rec):
    """The level a spike was made at: the amount the batch recorded with its
    unit, else the reviewer's amount, else the method's level it names."""
    if _given(row.get("spike_amount")) or _given(row.get("spike_ppt")):
        return _amount(row.get("spike_amount", row.get("spike_ppt")), row.get("spike_unit") or u"ppt")
    if _given(rec.get("spike")):
        return _amount(rec["spike"], rec.get("spike_unit"))
    if _given(rec.get("spike_ppt")):
        return u"%s" % rec["spike_ppt"]
    level = row.get("level") or rec.get("level")
    return (u"%s, method level" % level) if level else NOT_RECORDED


def _recorded(row, rec, key):
    """A spike's lot or volume: the member's own (Parents and levels), else
    what the review step recorded for it, else Not recorded."""
    for value in (row.get(key), rec.get(key)):
        if _given(value):
            return _text(value)
    return NOT_RECORDED


def spike_notes(spikes):
    """What needed a note of the Spikes table (spike_table's rows): each
    spiked member with no lot or no volume recorded."""
    out = []
    for r in spikes or []:
        missing = [w for w, cell in ((u"lot", r[2]), (u"volume", r[3])) if cell == NOT_RECORDED]
        if missing:
            out.append(u"%s: spike %s not recorded" % (r[0], u" and ".join(missing)))
    return out


def spike_table(spike_rows, recorded):
    """The Spikes table: [sample, parent, lot, volume (uL), level, by, at,
    source] for each QC member of the batch (`spike_rows`), then each spike
    the review step recorded (`recorded`, the session's pedigree) for an
    injection no member names. A member's lot and volume are its own
    (spike_lot, spike_volume_ul, entered on Parents and levels), else what
    the review step recorded for it; a spiked member with none recorded
    says Not recorded; a member that is not spiked says Not spiked.
    Returns (rows, []): the second list is filled with the older
    pedigree's levels by the caller."""
    from senaite.pfas.extraction_batch import SPIKED
    recorded = dict((k, v) for k, v in (recorded or {}).items() if isinstance(v, dict))
    out, named = [], set()
    for r in spike_rows or []:
        if not isinstance(r, dict):
            continue
        name = r.get("sample_id") or u""
        named.add(name)
        rec = recorded.get(name) or {}
        role = (r.get("qc_type") or u"").strip()
        if role and role not in SPIKED and not rec:
            lot = volume = level = NOT_SPIKED
        else:
            lot, volume = _recorded(r, rec, "spike_lot"), _recorded(r, rec, "spike_volume_ul")
            level = _spike_level(r, rec)
        out.append([_text(name), _text(r.get("spike_of") or rec.get("parent_sample")), lot, volume, level,
                    _text(r.get("logged_by")), _stamp(r.get("logged_at")), _text(role)])
    for name, rec in sorted(recorded.items()):
        if name in named:
            continue
        out.append([_text(name), _text(rec.get("parent_sample")),
                    _text(rec.get("spike_lot")) if _given(rec.get("spike_lot")) else NOT_RECORDED,
                    _text(rec.get("spike_volume_ul")) if _given(rec.get("spike_volume_ul")) else NOT_RECORDED,
                    _spike_level({}, rec), _text(rec.get("spike_entered_by")),
                    _stamp(rec.get("spike_entered_at")), _text(rec.get("spike_source"))])
    return out, []


def logbook_data(batch_id, batch_title, session, profile, generated, spike_rows=None,
                 extracted=None, dilution_rows=None, fullname=None):
    """Everything the logbook prints, as plain data. `spike_rows`: the
    extraction record's batch QC as spike rows (sample_id, spike_of, spike_amount, spike_unit,
    logged_by, logged_at, qc_type), printed first in the spikes. `extracted`:
    roster(members, sample_rows=None, ports=None) -- what the batch extracted. `fullname`: a user id
    to the person's name (a stored name, from before the finaliser was kept
    as a user id, comes back as it is); the finaliser is printed by name."""
    session, profile = session or {}, profile or {}
    method_name = profile.get("display_name") or session.get("method_id") or u""
    from senaite.pfas.stage_plan import stages_for
    stages_config = stages_for(session, profile)       # the plan the extraction followed
    completed = session.get("stages") or {}
    summary, details = [], []
    for sc in stages_config:
        order = u"%s" % sc.get("order", u"")
        sd = completed.get(order) or {}
        summary.append({"order": order, "name": _text(sc.get("name")),
                        "completed": _stamp(sd.get("completed_at")),
                        "analyst": _text(sd.get("analyst")),
                        "deviations": _text(sd.get("deviations"))})
        if not sd:
            continue
        # the stage's lot rows as every reader of the worksheet's lots has
        # them (worksheet_lots): what is printed here is what is traced
        rows = worksheet_lots.stage_rows(sd)

        def cells(r):
            return [_text(r["name"]), _text(r["lot"]), _text(r["supplier"]), _text(r["qty"]),
                    _text(r["expiry"])]
        details.append({
            "title": u"Stage %s: %s" % (order, sc.get("name", u"")),
            "equipment": [(_text(eq), _text(sn)) for eq, sn in
                          sorted((sd.get("equipment_sns") or {}).items())],
            "reagents": [cells(r) for r in rows if not r["consumable"]],
            "consumables": [cells(r) for r in rows if r["consumable"]],
            # what the deviation note had to explain
            "warnings": [_text(w) for w in sd.get("warnings") or []],
            # the stage's checks the chemist ticked (stage editor)
            "confirmed": [_text(c) for c in sd.get("confirmed") or []],
            # the answers to the stage's own questions (stage_form)
            "answers": [[_text(k), _text(v)] for k, v in _answer_rows(sc, sd.get("answers"))],
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
    spikes, pedigree = spike_table(spike_rows, session.get("pedigree"))
    for name, rec in sorted((session.get("pedigree") or {}).items()):
        if isinstance(rec, list):
            pedigree.append({"name": name, "rows": [
                [_text(l.get("level")), _text(l.get("lot")),
                 _text(l.get("cert_conc") or l.get("conc")),
                 _text(l.get("supplier") or l.get("prepared_by")),
                 _text(l.get("cert_date") or l.get("prepared_date")), _text(l.get("coa"))]
                for l in rec if isinstance(l, dict)]})
    who = session.get("finalized_by")
    finaliser = _text(fullname(who) if (fullname and who) else who)
    return {
        "method_name": method_name,
        "header": [(u"Batch ID", _text(batch_id)), (u"Batch Title", _text(batch_title)),
                   (u"Method", _text(method_name)),
                   (u"Lead Analyst", _text(session.get("analyst"))),
                   (u"Started", _stamp(session.get("started_at"))),
                   (u"Finalised", _stamp(session.get("finalized_at"))),
                   (u"Finalised by", finaliser),
                   (u"PDF Generated", generated)],
        "extracted": list(extracted or []),
        "dilutions": dilutions(dilution_rows),
        "summary": summary, "details": details, "spikes": spikes, "pedigree": pedigree,
        # a spike with no lot or volume recorded is listed with what needed
        # a note
        "spike_notes": spike_notes(spikes),
        "signoff": [(u"Extraction Analyst", _text(session.get("analyst"))),
                    (u"Finalised by", finaliser),
                    (u"Date Finalised", _stamp(session.get("finalized_at")))],
    }


# ── the record in force: amended cells and withheld members ────────────────
#
# The print shows the record in force (extraction_amendments): the stored
# members and sample rows with the amendments in force applied. An amended
# cell prints the value in force and the entries that amended it (the value
# as finalised is kept on the mark); a withheld member's row says so.

# the columns of the Extracted and Spikes tables (report_documents)
EXTRACTED_KEYS = ("name", "role", "made_from", "matrix", "amount", "final_volume", "spe_port")
SPIKE_KEYS = ("sample", "parent", "lot", "volume_ul", "ppt", "by", "at", "source")
# which amended facts each printed column shows
SHOWS = {
    "extracted": {"name": ("role", "level"), "role": ("role",), "made_from": ("parent",),
                  "matrix": ("sample",), "amount": ("amount",), "final_volume": ("final_volume_ml",),
                  "spe_port": ("role", "level")},
    "spikes": {"sample": ("role", "level"), "parent": ("parent",), "lot": ("spike_lot",),
               "volume_ul": ("spike_lot",), "ppt": ("level",), "source": ("role",)},
}
# where an amendment that changes no printed cell is shown
SHOWN_AT = {"role": ("extracted", "role"), "level": ("spikes", "ppt"), "parent": ("extracted", "made_from"),
            "sample": ("extracted", "name"), "spike_lot": ("spikes", "lot"),
            "amount": ("extracted", "amount"), "final_volume_ml": ("extracted", "final_volume")}
# where a withheld member's row says so
WITHHELD_AT = (("extracted", "role"), ("spikes", "source"))
WITHHELD_NOTE = u"Withheld: re-extraction"
WITHHELD_IN = u"Withheld: re-extraction in %s"


def withheld_note(ws=None):
    """"Withheld: re-extraction", naming the worksheet it was re-extracted
    in once it is known."""
    return WITHHELD_IN % ws if ws else WITHHELD_NOTE


def in_force(members, sample_rows, state, ports=None, pedigree=None):
    """(members, sample rows, SPE ports, spike pedigree) as the record stands
    in force (extraction_amendments.members_in_force, samples_in_force).
    A renamed member's sample row, port and pedigree follow it to its name
    in force; the stored ones are not changed."""
    from senaite.pfas import extraction_amendments as ea
    now = ea.members_in_force(members, state)
    renamed = ea.aliases(now)
    rows = []
    for r in ea.samples_in_force(sample_rows, state):
        if r.get("sample_id") in renamed and not (r.get("dilution_of") or u"").strip():
            r = dict(r, sample_id=renamed[r["sample_id"]])
        rows.append(r)
    ports = dict((renamed.get(k, k), v) for k, v in (ports or {}).items())
    pedigree = dict((renamed.get(k, k), v) for k, v in (pedigree or {}).items())
    return now, rows, ports, pedigree


def _entries_of(forced, member):
    """The amendments in force on a member's facts, the vial swapped with it
    included, and on its sample row: {field: entry}."""
    mid, name = member.get("id"), member.get("injection")
    out = {}
    for (key, field), e in forced.items():
        if key == mid or (name and key == u"sample:%s" % name):
            out[field] = e
        elif field == u"sample" and e.get("swap_with") == mid:
            out[field] = e
    return out


def _keyed(rows, keys):
    return [dict(zip(keys, r)) if not isinstance(r, dict) else r for r in rows or []]


def correction_marks(members, sample_rows, state, old_extracted, new_extracted, old_spikes, new_spikes,
                     names=None):
    """The marks the print puts on the Extracted and Spikes tables:
    [{"table", "row", "column", "old", "ids"}] for a cell whose value in
    force differs from the value as finalised (the value in force is the
    cell's own); [{"table", "row", "column", "field", "from", "to", "ids"}]
    for an amendment in force that changes no printed cell (it is said
    beside the cell; a swap of two vials' samples on both vials);
    [{"table", "row", "column", "note"}] for a withheld
    member. The tables are the rows as finalised (`old_`) and in force
    (`new_`), one per member in the members' order, the Spikes table's
    first rows its QC members'. `names`, {member id: issued name}, names a
    parent."""
    from senaite.pfas import extraction_amendments as ea
    members = list(members or [])
    forced = ea.amendments_in_force(state, members, sample_rows or [])
    links = ea.links(state)
    held = ea.withheld(state, members)
    names = names or dict((m.get("id"), m.get("injection") or m.get("id")) for m in members)
    qc = [m for m in members if m.get("role") != u"Sample"]
    tables = {"extracted": (members, _keyed(old_extracted, EXTRACTED_KEYS), _keyed(new_extracted, EXTRACTED_KEYS)),
              "spikes": (qc, _keyed(old_spikes, SPIKE_KEYS), _keyed(new_spikes, SPIKE_KEYS))}
    marks, shown = [], set()
    for table in ("extracted", "spikes"):
        rowed, old, new = tables[table]
        if len(old) != len(new) or len(old) < len(rowed):
            continue
        for i, m in enumerate(rowed):
            entries = _entries_of(forced, m)
            for col, fields in sorted(SHOWS[table].items()):
                if old[i].get(col) == new[i].get(col):
                    continue
                ids = sorted(set(e.get("id") for f, e in entries.items() if f in fields)) or \
                    sorted(set(e.get("id") for e in entries.values()))
                if not ids:
                    continue
                marks.append({"table": table, "row": i, "column": col, "old": old[i].get(col), "ids": ids})
                shown.update(ids)
            if m.get("id") in held:
                ws = links.get(held[m["id"]].get("id"))
                for t, col in WITHHELD_AT:
                    if t == table:
                        marks.append({"table": table, "row": i, "column": col, "note": withheld_note(ws)})
    shown_rows = set((mk["table"], mk["row"], i) for mk in marks for i in mk.get("ids") or ())
    for (key, field), e in sorted(forced.items(), key=lambda kv: kv[1].get("id") or u""):
        if field not in SHOWN_AT:
            continue
        table, col = SHOWN_AT[field]
        rowed = tables[table][0]
        words = (lambda v: names.get(v) or v) if field == u"parent" else (lambda v: v)
        # a vial's sample swapped: both vials say which sample they are now
        targets = [(key, e.get("from"), e.get("to"))]
        if field == u"sample" and e.get("swap_with"):
            targets.append((e["swap_with"], e.get("to"), e.get("from")))
        for target, was, now in targets:
            at = [i for i, m in enumerate(rowed) if target in (m.get("id"), u"sample:%s" % m.get("injection"))]
            if not at or (table, at[0], e.get("id")) in shown_rows or \
                    (e.get("id") in shown and target == key and field != u"sample"):
                continue
            marks.append({"table": table, "row": at[0], "column": col, "field": field,
                          "from": words(was or u""), "to": words(now or u""), "ids": [e.get("id")]})
            shown_rows.add((table, at[0], e.get("id")))
    return marks
