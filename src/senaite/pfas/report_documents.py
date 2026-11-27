# -*- coding: utf-8 -*-
"""Designed reports: the batch record, the QC Review report and the
settings report.

Each report keeps its own assembly -- batch_record.assemble() with
extraction_logbook.logbook_data(), the
QC Review view's sections (which delegate to Data Review), the settings
report's report() -- and this module only FLATTENS that into the fields and
tables of a document kind (document_templates.KINDS). A report's nested or
pivoted parts become long tables, since a designed table has fixed columns:
the extraction's per-stage materials one "materials" table with a stage
column, the QC summary one row per analyte x QC type, a method's settings
sections one row per setting.

Every table is required in a design: these are records an assessor reads,
and a layout must not quietly drop a part of one (the settings report's
"judged by the pipeline" claims are pinned to the pipeline code by
tests/test_settings_report.py; a design cannot leave them out).

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.print_style import PALETTE as _P

from senaite.pfas import doc_fields as _df
from senaite.pfas.run_lots import NO_RUN_PLAN


_s = _df.as_text


def _cols(*specs):
    return [(k, t, e) for k, t, e in specs]


# ── the Signatures table (a preparation, batch or certificate print) ───────
#
# One row per live signature from the ledger (esig.signing.status): the
# meaning, the signer as signed, the lab time with its zone, the first twelve
# characters of the content signed. A designed table holds text cells only,
# so the image column says what stands in the per-role image field
# (<meaning>_signature), which carries the image kept at signing.

SIGNATURES_TABLE = _cols(("meaning", "Signature", "Prepared by"), ("name", "Name", "A. Analyst"),
                         ("credentials", "Credentials", "DEMO"), ("image", "Signature image", ""),
                         ("at", "Date and time", "2026-11-06 09:12 America/New_York"),
                         ("hash", "Record", "3f9c2a1b7e0d"))
ON_FILE = "on file"
# a preparation record's Signatures table says which sign-off is an
# e-signature in the ledger and which is the record's own entry
E_SIGNATURE = "E-signature on file"
RECORD_ENTRY = "Record entry, not e-signed"
# a role nobody has signed for yet: every signer block and Signatures row
# says it the same way
NOT_YET_SIGNED = "Not yet signed"
# a record keeps no time of change: the time printed is when the change was found
CONTENT_CHANGED = "Signed content changed, found %s: re-sign required"
WITHDRAWN = "Withdrawn %s"
# a signed role whose kept image is gone: the print is refused
NO_KEPT_IMAGE = "The signature image kept for signature %s is missing or altered."


# ── the document control block of a designed record ────────────────────────
#
# What every controlled print carries beside its page numbers: the document
# (the design it was printed from) with its revision and issue date, and who
# printed it and when. One field, written when the document is printed
# (browser/report_designs.control_text).

CONTROL_FIELD = ("control", "Document control",
                 "DEMO record Rev 1 \u00b7 Issued 2026-11-06\nPrinted 2026-11-10 10:00 by AN1")
# a record's banner: the laboratory's name and address under the title, on
# every page
BANNER = ("lab_name", "lab_address")


# ── the batch record's print (@@pfas-extraction-pdf) ───────────────────────
#
# The worksheet's record from receipt to release (batch_record.assemble): the
# guided extraction's own tables and fields, its stages as its own plan has
# them, the CoC receipt, the lots the run was loaded with and Data Review's
# checklist, under the record's title, method revision and hash.

BATCH_RECORD_FIELDS = [
    ("record_title", "Record", "WS-DEMO \u00b7 EPA 537.1 r2.0"),
    ("revision", "Method revision", "2.0"),
    ("batch_id", "Batch ID", "B-DEMO"),
    ("batch_title", "Batch title", "DEMO batch"),
    ("method", "Method", "EPA 537.1"),
    ("lead_analyst", "Lead analyst", "AN1"),
    ("started", "Started", "2026-10-01 09:00"),
    ("finalized", "Finalised", "2026-10-01 15:00"),
    ("reviewer", "Finalised by", "AN1"),
    ("approved_by", "Approved by", "AN2"),
    ("approved_at", "Approved", "2026-10-05 09:00"),
    ("generated", "PDF generated", "2026-10-05 10:00 UTC"),
    ("warnings", "What needed a note", "DEMO: balance not registered"),
    ("deviations", "Deviations", "DEMO deviation note"),
    ("pedigree", "Spike pedigree (older records)", ""),
    ("record_hash", "Record hash", "9f2c41d0e8b7a6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1"),
    CONTROL_FIELD,
    # which revision of the record this is: 1 as released, one more per
    # amendment after release (batch_record.revision_words); a design issued
    # before it names a later revision under the record hash
    ("record_revision", "Record revision", "Record rev 1"),
]
BATCH_RECORD_LONG = ("warnings", "deviations", "pedigree", "record_hash")
# a part of the batch record only older records carry: left out, its
# label with it, when the record has none
BATCH_RECORD_OMIT_EMPTY = ("pedigree", "corrections")
# the laboratory and its signatories: the finaliser prepares (attests the
# extraction), the approver reviews (releases the record), the Director
# named on Laboratory
_SIGNED = _df.LAB_FIELDS + [f for _c, fs in _df.people() for f in fs]
SIGNED_IMAGES = _df.LAB_IMAGES + _df.people_images()


def _plus_signed(fields):
    have = set(k for k, _t, _e in fields)
    return fields + [f for f in _SIGNED if f[0] not in have]


# the starting layout keeps the record's own fields, under the laboratory's
# name and address (BANNER); the other laboratory and signatory fields are
# offered in the designer (not required)
BATCH_RECORD_OWN = BATCH_RECORD_FIELDS
BATCH_RECORD_FIELDS = _plus_signed(BATCH_RECORD_FIELDS)


def _assign(base, extra=None):
    out = dict((k, c) for c, fs in [(_df.LAB, _df.LAB_FIELDS)] + _df.people() for k, _t, _e in fs)
    out.update(base)
    out.update(extra or {})
    return out


BATCH_RECORD_GROUPS = _df.grouped(BATCH_RECORD_FIELDS, _assign({
    "record_title": _df.BATCH, "revision": _df.ANALYSIS, "record_hash": _df.DOCUMENT,
    "batch_id": _df.BATCH, "batch_title": _df.BATCH, "method": _df.ANALYSIS,
    "lead_analyst": _df.PREPARER, "started": _df.PREPARER,
    "reviewer": _df.PREPARER, "finalized": _df.PREPARER,
    "approved_by": _df.REVIEWER, "approved_at": _df.REVIEWER,
    "generated": _df.DOCUMENT, "warnings": _df.DEVIATIONS, "deviations": _df.DEVIATIONS,
    "pedigree": _df.TRACE, "control": _df.DOCUMENT, "record_revision": _df.DOCUMENT}))

BATCH_RECORD_TABLES = {
    "receipt": _cols(("coc", "Chain of custody", "COC-2026-0001"), ("status", "Status", "Received"),
                     ("received_by", "Received by", "AN1"), ("received_at", "Received", "2026-10-01 08:00"),
                     ("temperatures", "Temperatures", "DEMO-0001 4 \u00b0C"), ("flags", "Flags", "")),
    "extracted": _cols(("name", "Name", "DEMO-0001"), ("role", "Role", "Sample"),
                       ("made_from", "Made from", ""), ("matrix", "Matrix", "Drinking Water"),
                       ("amount", "Amount", "250 mL"), ("final_volume", "Final volume", "1 mL"),
                       ("spe_port", "SPE port", "A1")),
    "stages": _cols(("order", "Stage", "1"), ("name", "Name", "Sample prep"),
                    ("completed", "Completed", "2026-10-01 10:00"), ("analyst", "Analyst", "AN1"),
                    ("deviations", "Deviations", "\u2014")),
    "materials": _cols(("stage", "Stage", "1"), ("kind", "Kind", "Reagent"),
                       ("name", "Name", "Methanol"), ("lot", "Lot", "DEMO-LOT-1"),
                       ("supplier", "Supplier", "DEMO"), ("qty", "Quantity", "10 mL"),
                       ("conc", "Conc.", ""), ("expiry", "Expiry", "2027-01-01")),
    "equipment": _cols(("stage", "Stage", "1"), ("item", "Equipment", "Balance"),
                       ("serial", "Serial", "SN-DEMO")),
    "spikes": _cols(("sample", "Sample", "LFSM-1"), ("parent", "Parent sample", "DEMO-0001"),
                    ("lot", "Spike lot", "DEMO-PS-1"), ("volume_ul", "Volume (\u00b5L)", "50"),
                    ("ppt", "Level (ppt)", "10"), ("by", "Entered by", "AN1"),
                    ("at", "Entered at", "2026-10-01"), ("source", "Source", "review")),
    "loaded": _cols(("slot", "Slot", "CAL-1"), ("kind", "Kind", "Prepared standard"),
                    ("name", "Name", "DEMO CAL-1"), ("lot", "Lot", "DEMO-LOT-1"),
                    ("expiry", "Expiry", "2027-01-01")),
    "review": _cols(("item", "Item", "Chain of Custody"), ("state", "State", "Checked"),
                    ("by", "By", "AN2"), ("at", "At", "2026-10-02 09:00")),
    # each stage's own record: homogenisation, the checks ticked, the answers
    "homogenisation": _cols(("stage", "Stage", "1"), ("sample", "Sample", "DEMO-0001"),
                            ("requested", "Requested", "Grind"), ("done", "Done", "Ground"),
                            ("homogeniser", "Homogeniser", "DEMO-GR-1"), ("composite", "Composite", "Yes"),
                            ("items", "Items composited", "3"), ("by", "By", "AN1"),
                            ("at", "When", "2026-10-01 09:10")),
    "checks": _cols(("stage", "Stage", "1"), ("check", "Checked", "Grinder cleaned")),
    "answers": _cols(("stage", "Stage", "1"), ("question", "Question", "Cartridge lot conditioned"),
                     ("answer", "Answer", "Yes")),
}
BATCH_RECORD_TABLES["dilutions"] = _cols(
    ("from", "Diluted from", "DEMO-0001"), ("injection", "Injection", "DEMO-0001_DIL10"),
    ("fold", "Fold", "10"), ("route", "Route", "Dilute the extract"), ("aliquot", "Aliquot", ""),
    ("by", "Logged by", "AN1"), ("at", "Logged", "2026-10-01 14:00"))
BATCH_RECORD_TABLES["signatures"] = SIGNATURES_TABLE
# the corrections of the finalised extraction (batch_record.corrections):
# every entry, in force and undone, printed after the deviations
BATCH_RECORD_TABLES["corrections"] = _cols(
    ("id", "Entry", "EA-1"), ("what", "What", "Amended DEMO-LFB level"), ("before", "Before", "Mid"),
    ("after", "After", "High"), ("reason", "Reason", "DEMO reason"), ("by", "By", "AN1"),
    ("at", "At", "2026-10-02 09:00"), ("countersign", "Countersigned", "Countersigned by AN2, 2026-10-03 09:00"))
BATCH_RECORD_ORDER = ("corrections", "receipt", "extracted", "stages", "materials", "equipment",
                      "homogenisation", "checks", "answers", "spikes", "dilutions", "loaded", "review",
                      "signatures")
# tables a batch record design issued before they existed prints without:
# the print says what they hold elsewhere (corrections_text); a new issue
# places them
BATCH_RECORD_LATER_TABLES = ("corrections",)
BATCH_RECORD_REQUIRED = ("record_title", "revision", "record_hash", "batch_id", "method", "lead_analyst",
                         "finalized", "reviewer", "warnings", "deviations",
                         "lab_name", "lab_address", "control")


def _at(value):
    """A stored stamp (UTC) on the laboratory's clock; as stored while no
    zone converts."""
    from senaite.pfas import print_doc
    return print_doc.lab_or(value, _s(value))


def _extraction(log, lots_found=None):
    """The guided extraction's own fields and tables, from
    extraction_logbook.logbook_data(). `lots_found`: {lot number: whether
    the inventory holds it} for the lots the stages recorded."""
    from senaite.pfas import worksheet_lots
    head = dict(log.get("header") or [])
    materials, equipment, warnings, deviations = [], [], [], []
    for d in log.get("details") or []:
        stage = (d.get("title") or "").replace("Stage ", "").split(":")[0]
        for kind, rows in (("Reagent", d.get("reagents")), ("Consumable", d.get("consumables"))):
            for r in rows or []:
                materials.append({"stage": stage, "kind": worksheet_lots.stage_kind(kind, r[1], lots_found),
                                  "name": r[0], "lot": r[1],
                                  "supplier": r[2], "qty": r[3], "conc": "", "expiry": r[4]})
        for r in d.get("solutions") or []:
            materials.append({"stage": stage, "kind": "Solution prepared", "name": r[0], "lot": r[1],
                              "supplier": "", "qty": r[3], "conc": r[2], "expiry": r[4]})
        for item, serial in d.get("equipment") or []:
            equipment.append({"stage": stage, "item": item, "serial": serial})
        warnings += ["%s: %s" % (d.get("title"), w) for w in d.get("warnings") or []]
        if d.get("deviations"):
            deviations.append("%s: %s" % (d.get("title"), d["deviations"]))
    warnings += ["Spikes: %s" % w for w in log.get("spike_notes") or []]
    pedigree = []
    for p in log.get("pedigree") or []:
        for r in p.get("rows") or []:
            pedigree.append("%s: %s" % (p.get("name"), ", ".join(_s(c) for c in r)))
    return {
        "batch_id": _s(head.get("Batch ID")), "batch_title": _s(head.get("Batch Title")),
        "method": _s(head.get("Method")), "lead_analyst": _s(head.get("Lead Analyst")),
        "started": _s(head.get("Started")), "finalized": _s(head.get("Finalised")),
        "reviewer": _s(head.get("Finalised by")), "generated": _s(head.get("PDF Generated")),
        "warnings": "\n".join(warnings), "deviations": "\n".join(deviations),
        "pedigree": "\n".join(pedigree),
        "materials": [dict((k, _s(v)) for k, v in m.items()) for m in materials],
        "equipment": [dict((k, _s(v)) for k, v in e.items()) for e in equipment],
        "extracted": [dict(zip(("name", "role", "made_from", "matrix", "amount", "final_volume",
                                "spe_port"), [_s(c) for c in r])) for r in log.get("extracted") or []],
        "spikes": [dict(zip(("sample", "parent", "lot", "volume_ul", "ppt", "by", "at", "source"),
                            [_s(c) for c in r])) for r in log.get("spikes") or []],
        "dilutions": [dict(zip(("from", "injection", "fold", "route", "aliquot", "by", "at"),
                               [_s(c) for c in r])) for r in log.get("dilutions") or []],
    }


def _temperatures(readings):
    """"S-1 4.1 °C, corrected 3.9 °C; S-2 5 °C": each reading as received."""
    out = []
    for r in readings or []:
        sid, observed, corrected = (list(r) + [None, None, None])[:3]
        if observed in (None, "") and corrected in (None, ""):
            continue
        text = "%s %s \u00b0C" % (_s(sid), _s(observed)) if observed not in (None, "") else _s(sid)
        if corrected not in (None, ""):
            text += ", corrected %s \u00b0C" % _s(corrected)
        out.append(text.strip())
    return "; ".join(out)


def _receipt_rows(receipt):
    """One row per CoC record the worksheet's samples carry, its status in
    the words the CoC page shows."""
    from senaite.pfas.coc_records import STATUS_LABELS
    return [{"coc": _s(r.get("number")), "status": _s(STATUS_LABELS.get(r.get("status"), r.get("status"))),
             "received_by": _s(r.get("received_by")), "received_at": _at(r.get("received_at")),
             "temperatures": _temperatures(r.get("temperatures")),
             # what was flagged, then what was not judged: a temperature with no
             # range is never left to read as compliant
             "flags": "; ".join([_s(f) for f in r.get("flags") or []]
                                + ([u"Not judged: " + u"; ".join(_s(n) for n in r["not_judged"])]
                                   if r.get("not_judged") else []))}
            for r in (receipt or {}).get("records") or [] if isinstance(r, dict)]


def _loaded_rows(loaded, found=None):
    """The run's standards by slot, then its LC solvent channels
    (worksheet_lots.loaded_lots), each lot's kind as the run recorded it.
    `found`, {slot: whether the inventory holds the lot}: a lot it does not
    hold says so beside its kind, in the words the QC Review report uses
    (worksheet_lots.loaded_kind)."""
    from senaite.pfas import worksheet_lots
    found = found or {}
    return [{"slot": _s(row["label"]), "kind": _s(worksheet_lots.loaded_kind(row["kind"], found.get(row["label"]))),
             "name": _s(row["name"]), "lot": _s(row["lot"]), "expiry": _s(row["expiry"])}
            for row in worksheet_lots.loaded_lots(loaded)]


def _item_state(item):
    if item.get("checked"):
        return "Checked"
    if item.get("proposed_by"):
        return "Proposed"
    return "Not checked"


def _review_rows(checklist, order=(), people=None):
    """Data Review's checklist: each item in `order` (the checklist's own),
    any other after it by key, then the submission and the release. Who
    acted by `people` ({user id: name}), the id when it names no one."""
    checklist = checklist or {}
    people = people or {}

    def who(uid):
        return _s(people.get(uid) or uid)
    items = checklist.get("items") or {}
    keys = [k for k in order or () if k in items] + sorted(k for k in items if k not in (order or ()))
    rows = []
    for k in keys:
        it = items[k] if isinstance(items[k], dict) else {}
        checked = bool(it.get("checked"))
        rows.append({"item": _s(it.get("label") or k), "state": _item_state(it),
                     "by": who(it.get("checked_by") if checked else it.get("proposed_by")),
                     "at": _at(it.get("checked_at") if checked else it.get("proposed_at"))})
    for label, key, done, undone in (("Submitted", "submitted", "Submitted", "Not submitted"),
                                     ("Release", "approved", "Approved", "Not approved")):
        by = checklist.get(key + "_by")
        rows.append({"item": label, "state": done if by else undone, "by": who(by),
                     "at": _at(checklist.get(key + "_at")) if by else ""})
    return rows


def _stage_rows(stages):
    """Every stage of the record's own plan, recorded or not
    (extraction_review.review's rows)."""
    return [{"order": _s(st.get("order")), "name": _s(st.get("name")),
             "completed": _at(st.get("completed_at")), "analyst": _s(st.get("analyst")),
             "deviations": _s(st.get("deviations"))}
            for st in stages or [] if isinstance(st, dict)]


def _stage_parts(stages):
    """Each recorded stage's homogenisation, ticked checks and answers
    (extraction_review.stage_summary), one row each with its stage."""
    homog, checks, answers = [], [], []
    for st in stages or []:
        if not isinstance(st, dict):
            continue
        stage = _s(st.get("order"))
        for h in st.get("homogenisation") or []:
            if isinstance(h, dict):
                homog.append({"stage": stage, "sample": _s(h.get("sample_id")),
                              "requested": _s(h.get("requested")), "done": _s(h.get("method")),
                              "homogeniser": _s(h.get("unit")), "composite": _s(h.get("composite")),
                              "items": _s(h.get("units_combined")), "by": _s(h.get("by")),
                              "at": _at(h.get("at"))})
        checks.extend({"stage": stage, "check": _s(c)} for c in st.get("confirmed") or [])
        answers.extend({"stage": stage, "question": _s((list(a) + ["", ""])[0]),
                        "answer": _s((list(a) + ["", ""])[1])} for a in st.get("answers") or [])
    return homog, checks, answers


def extended_materials(materials, extensions):
    """The materials table with each lot used under an extension printing
    the extension beside its expiry (lot_extension.extension_for /
    note); a copy, other rows as they are."""
    from senaite.pfas import lot_extension
    out = []
    for m in materials or []:
        e = lot_extension.extension_for((extensions or {}).get(m.get("lot")), m.get("expiry"))
        out.append(dict(m, expiry=_s(lot_extension.note(e))) if e is not None else m)
    return out


# equipment on a record: its serial as the Equipment register holds it
SERIAL_NOT_SET = "Serial not set"
NOT_IN_REGISTER = "not in the Equipment register"
# a weight set used without a calibration, its calibration switched off
WEIGHT_SET_NOT_CALIBRATED = "Weight set %s was not calibrated"
# a part of a record with nothing in it
NONE_RECORDED = "None recorded"
_DASH = "\u2014"


def equipment_rows(rows, units):
    """The batch record's equipment rows with each serial as the Equipment
    register holds it. `units`: {serial recorded: the register's unit
    ({"name", "serial_number"})}. A unit the register holds prints its
    name beside the item and its serial, or Serial not set; a serial the
    register does not hold is printed as recorded and says so; nothing
    recorded is Serial not set."""
    out = []
    for r in rows or []:
        serial = _s(r.get("serial")).strip()
        serial = "" if serial == _DASH else serial
        unit = (units or {}).get(serial) if serial else None
        item = _s(r.get("item"))
        if unit:
            name = _s(unit.get("name")).strip()
            if name and name != item:
                item = "%s, %s" % (item, name)
            for set_id in unit.get("uncalibrated_sets") or []:
                item = "%s. %s" % (item, WEIGHT_SET_NOT_CALIBRATED % _s(set_id))
            cell = _s(unit.get("serial_number")).strip() or SERIAL_NOT_SET
        elif serial:
            cell = "%s, %s" % (serial, NOT_IN_REGISTER)
        else:
            cell = SERIAL_NOT_SET
        out.append(dict(r, item=item, serial=cell))
    return out


def preparation_equipment(equipment, unit_of=None):
    """The preparation record's equipment, one line each: "ROLE: NAME,
    serial S" from the Equipment register (unit_of(unit id) -> its unit, or
    None), Serial not set where the register has none, and a unit the
    register no longer holds by the name kept with the record; None
    recorded when the record lists none."""
    lines = []
    for e in equipment or []:
        if not isinstance(e, dict):
            if _s(e).strip():
                lines.append(_s(e).strip())
            continue
        unit = unit_of(e.get("unit_id")) if (unit_of and e.get("unit_id")) else None
        role = _s(e.get("role")).strip()
        if unit:
            serial = _s(unit.get("serial_number")).strip()
            text = "%s, %s" % (_s(unit.get("name")).strip() or _s(e.get("name")),
                               ("serial %s" % serial) if serial else SERIAL_NOT_SET)
        else:
            name = _s(e.get("name")).strip()
            text = ("%s, %s" % (name, NOT_IN_REGISTER)) if name else "Unit %s" % NOT_IN_REGISTER
        lines.append(("%s: %s" % (role, text)) if role else text)
    return "\n".join(lines) or NONE_RECORDED


def empty_fields(data, keys=BATCH_RECORD_OMIT_EMPTY):
    """The parts of a document's data (a batch record's by default,
    batch_record_data) that print only when it has them, and that it has
    not."""
    out = []
    for k in keys:
        value = (data or {}).get(k)
        # a table is empty with no rows
        if isinstance(value, (list, tuple)) and not value:
            out.append(k)
        elif not isinstance(value, (list, tuple)) and not _s(value).strip():
            out.append(k)
    return out


# ── the record's corrections on its print ──────────────────────────────────
#
# An amended cell prints the value in force and the entries that amended it;
# what it was is in the Corrections section's Before column. The print's
# renderer draws no struck-through text in a table cell: a combining stroke
# is refused or drawn as a missing glyph, so none is sent.

CORRECTIONS_HEADING = "Corrections"


def corrections_rows(rows):
    """The Corrections table's rows from batch_record.corrections()."""
    return [{"id": _s(r.get("id")), "what": _s(r.get("what")), "before": _s(r.get("before")),
             "after": _s(r.get("after")), "reason": _s(r.get("reason")), "by": _s(r.get("by")),
             "at": _s(r.get("at")), "countersign": _s(r.get("countersign"))}
            for r in rows or () if isinstance(r, dict)]


def corrections_text(rows):
    """The corrections as lines of text, for a design issued before it had
    the Corrections table: "Corrections" and one line per entry."""
    lines = []
    for r in corrections_rows(rows):
        line = "%s %s" % (r["id"], r["what"])
        if r["before"] and r["after"]:
            line += ": %s to %s" % (r["before"], r["after"])
        elif r["after"]:
            line += ": %s" % r["after"]
        if r["reason"]:
            line += ". %s" % r["reason"]
        line += ". By %s, %s" % (r["by"], r["at"])
        if r["countersign"]:
            line += ". %s" % r["countersign"]
        lines.append(line + ".")
    return "\n".join([CORRECTIONS_HEADING] + lines) if lines else ""


def mark_cells(data, marks, rename=None):
    """A copy of the batch record's printed data with the marks of the
    record in force (extraction_logbook.correction_marks) on its cells: an
    amended cell prints the value in force and the entries ("High EA-1");
    an amendment no cell shows is said after the cell ("..., level High
    EA-1"); a withheld member's cell says so. What each was is the
    Corrections section's. `rename`, applied to every name a mark adds, as
    the print's names were (sample_names)."""
    out = dict(data or {})
    if not marks:
        return out
    rename = rename or (lambda v: v)
    tables = {}
    for mk in marks:
        name = mk.get("table")
        if name not in tables:
            tables[name] = [dict(r) for r in out.get(name) or []]
        rows = tables[name]
        i, col = mk.get("row"), mk.get("column")
        if not isinstance(i, int) or i >= len(rows):
            continue
        cell = _s(rows[i].get(col))
        ids = ", ".join(_s(x) for x in mk.get("ids") or [])
        if "note" in mk:
            rows[i][col] = "%s \u00b7 %s" % (cell, _s(mk["note"])) if cell else _s(mk["note"])
        elif "old" in mk:
            rows[i][col] = "%s %s" % (cell, ids)
        else:
            from senaite.pfas.extraction_amendments import FIELD_LABELS
            said = "%s %s %s" % (FIELD_LABELS.get(mk.get("field"), mk.get("field")).lower(),
                                 rename(_s(mk.get("to"))), ids)
            rows[i][col] = "%s, %s" % (cell, said) if cell and cell != _DASH else said[:1].upper() + said[1:]
    out.update(tables)
    return out


def batch_record_data(record, log=None, review_order=(), people=None, signatures=(), loaded_found=None,
                      revision_text=None, lots_found=None, extensions=None, units=None, other_lots=(),
                      corrections=None):
    """From batch_record.assemble()'s record and, for the guided
    extraction's own tables and fields, extraction_logbook.logbook_data().
    The stages are the record's: its own plan, never the method's stages
    now. `review_order`, the checklist's item order; `people`, {user id:
    name} of who reviewed; signatures, the Signatures table's rows
    (signature_rows), given only when there are some. `loaded_found`,
    {slot: whether the inventory holds the loaded lot} (_loaded_rows).
    `revision_text`, what the Method revision field says when the record
    pins no revision number (revision_words); the number when it pins one.
    `lots_found`, {lot number: whether the inventory holds it} for the lots
    the stages recorded (worksheet_lots.stage_kind). `extensions`, {lot
    number: its extension entries}: a material used under an extension
    prints "DATE, extended from ORIGINAL, approved by NAME on DATE" as its
    expiry. That note is the print's alone: the record, and so its hash
    and its signatures, never carries it. `units`, {serial recorded: the
    Equipment register's unit}: each equipment row's serial as the register
    holds it (equipment_rows). `other_lots`, the matrix blanks' and
    dilutions' lots (worksheet_lots.other_lot_rows), printed in the
    materials table after the stages' rows; like the extension notes, the
    print's alone, never part of what the record hashes. `corrections`,
    batch_record.corrections() of the record with names and the ledger
    read (the record's own rows else): the Corrections table. A record
    amended after release prints its revision's hash under the release
    hash."""
    from senaite.pfas import batch_record
    record = record or {}
    parts = record.get("parts") or {}
    out = dict((k, "") for k, _t, _e in BATCH_RECORD_OWN)
    out.update((name, []) for name in BATCH_RECORD_TABLES)
    if log:
        out.update(_extraction(log, lots_found))
        out["materials"] = extended_materials(out.get("materials"), extensions)
        out["equipment"] = equipment_rows(out.get("equipment"), units)
    out["materials"] = list(out.get("materials") or []) + [
        {"stage": _s(r.get("where")), "kind": _s(r.get("kind")), "name": _s(r.get("name")),
         "lot": _s(r.get("lot")), "supplier": "", "qty": _s(r.get("qty")), "conc": "", "expiry": ""}
        for r in other_lots or ()]
    revision = record.get("revision")
    from senaite.pfas import method_revisions
    out.update({
        "record_title": _s(record.get("title")),
        # an integer revision predates major.sub and prints "N.0"
        "revision": _s(revision_text) if revision is None else _s(method_revisions.revision_text(revision)),
        "record_hash": _record_hashes(record),
        "record_revision": _s(record.get("revision_words") or batch_record.revision_words(1)),
        "corrections": corrections_rows(record.get("corrections") if corrections is None else corrections),
        "stages": _stage_rows(parts.get("stages")),
        "receipt": _receipt_rows(parts.get("receipt")),
        "loaded": _loaded_rows(parts.get("loaded"), loaded_found),
        "review": _review_rows(parts.get("review"), review_order, people),
    })
    review = parts.get("review") or {}
    if review.get("approved_by"):
        out["approved_by"] = _s((people or {}).get(review["approved_by"]) or review["approved_by"])
        out["approved_at"] = _at(review.get("approved_at"))
    out["homogenisation"], out["checks"], out["answers"] = _stage_parts(parts.get("stages"))
    out.pop("signatures", None)
    if signatures:
        out["signatures"] = list(signatures)
    return out


def _record_hashes(record):
    """The record's hash as released; amended after release, the
    revision's hash after it, named by its revision."""
    from senaite.pfas import batch_record
    out = batch_record.record_hash(record)
    rev = (record or {}).get("record_revision") or 1
    if rev > 1:
        out += "\n%s: %s" % (batch_record.revision_words(rev).split(" \u00b7 ")[0],
                             batch_record.revision_hash(record))
    return out


# ── the Signatures table's rows, read from the ledger ──────────────────────

def _sig_entry(row):
    e = (row or {}).get("entry")
    return e if isinstance(e, dict) else {}


def _hash_of(current_hash, meaning):
    """The hash a meaning's signer attests: current_hash, or its entry when
    it is a {meaning: hash} map (a record whose signers attest different
    parts of it)."""
    if isinstance(current_hash, dict):
        return current_hash.get(meaning)
    return current_hash


def signature_row(meaning, name, credentials, image, at, record_hash, role, seq=None):
    """One Signatures table row (SIGNATURES_TABLE's columns, the row's seq
    and its meaning key as role): every print builds its rows here."""
    return {"meaning": _s(meaning), "name": _s(name), "credentials": _s(credentials),
            "image": _s(image), "at": _s(at), "hash": _s(record_hash), "seq": seq, "role": _s(role)}


def signature_rows(st, current_hash, when, changed_at=""):
    """The Signatures table's rows from signing.status(...) of a record whose
    content now hashes to current_hash (or, per meaning, to its entry in a
    {meaning: hash} map). A row signed on this content says
    "on file"; one signed on other content says the content changed, with
    changed_at; a withdrawn row says when it was withdrawn. Superseded rows,
    and a changed or withdrawn row whose meaning was signed again since,
    are not printed. when(signed_at) gives the lab time and zone; the
    name and credentials are the signer's as at signing, from the row;
    changed_at is when the change was found."""
    from senaite.pfas.esig import signing
    valid = st.get("valid") or {}

    def signed_since(meaning, seq):
        later = valid.get(meaning)
        return later is not None and later["seq"] > seq

    picked = []
    for r in st.get("live") or []:
        e = _sig_entry(r)
        if e.get("record_hash") == _hash_of(current_hash, e.get("meaning")):
            picked.append((r, ON_FILE))
        elif not signed_since(e.get("meaning"), r["seq"]):
            picked.append((r, CONTENT_CHANGED % changed_at))
    for r in st.get("withdrawn") or []:
        if not signed_since(_sig_entry(r).get("meaning"), r["seq"]):
            picked.append((r, WITHDRAWN % when(_sig_entry(r.get("withdrawn_by")).get("signed_at"))))
    out = []
    for r, cell in sorted(picked, key=lambda p: p[0]["seq"]):
        e = _sig_entry(r)
        signer = e.get("signer") or {}
        out.append(signature_row(signing.meaning_label(e.get("meaning")),
                                 signer.get("fullname") or signer.get("userid"),
                                 signer.get("credentials"), cell, when(e.get("signed_at")),
                                 _s(e.get("record_hash"))[:12], e.get("meaning"), seq=r["seq"]))
    return out


def signer_fields(st, current_hash, meanings):
    """{"<meaning>_name": ..., "<meaning>_credentials": ...} of each meaning
    signed on this content, as the ledger row has them at signing: a signed
    role prints its signer as signed, never as the staff record reads
    today."""
    valid = st.get("valid") or {}
    out = {}
    for meaning in meanings:
        row = valid.get(meaning)
        if row is None or _sig_entry(row).get("record_hash") != _hash_of(current_hash, meaning):
            continue
        signer = _sig_entry(row).get("signer") or {}
        out["%s_name" % meaning] = _s(signer.get("fullname") or signer.get("userid"))
        out["%s_credentials" % meaning] = _s(signer.get("credentials"))
    return out


def signature_images(st, current_hash, meanings, image_uri):
    """{"<meaning>_signature": data URI} for each meaning the ledger holds a
    row of: the image kept when the content was signed (image_uri(row)), or
    "" when no row of that meaning signs this content. A meaning with no
    row is left out: a record signed before the ledger prints as it did.
    A kept image that is missing or altered raises ValueError, so the print
    is refused rather than drawn without it."""
    valid = st.get("valid") or {}
    out = {}
    for meaning in meanings:
        if not [r for r in st.get("rows") or [] if _sig_entry(r).get("meaning") == meaning]:
            continue
        row = valid.get(meaning)
        signed_here = row is not None and _sig_entry(row).get("record_hash") == _hash_of(current_hash, meaning)
        uri = image_uri(row) if signed_here else ""
        if row is not None and not uri:
            raise ValueError(NO_KEPT_IMAGE % row["seq"])
        out["%s_signature" % meaning] = uri
    return out


# ── preparation record (@@pfas-preparation-pdf) ────────────────────────────

PREPARATION_FIELDS = [
    ("record_id", "Record", "PDS-DEMO-261105-01"),
    ("recipe", "Recipe", "DEMO stock"),
    ("recipe_code", "Recipe code", "PDS-DEMO"),
    ("recipe_revision", "Recipe revision", "2"),
    ("kind", "Kind", "standard"),
    ("prepared_by", "Prepared by", "AN1"),
    ("prepared_date", "Prepared on", "2026-11-05"),
    ("storage", "Storage location", "Freezer 1"),
    ("storage_conditions", "Storage conditions", "DEMO: 2-8 \u00b0C, dark"),
    ("equipment", "Equipment", "BAL-1 (Balance)"),
    ("reviewed_by", "Reviewed by", "AN2"),
    ("reviewed_at", "Reviewed at", "2026-11-06 09:00"),
    ("expiry_note", "Why it expires when it does",
     "DEMO-LOT-1: the recipe's shelf life, 30 days after preparation"),
    ("expired_parents", "Parent lots used out of date",
     "Used out of date before the preparation date 2026-11-06: lot DEMO-P1 of DEMO native mix "
     "expired 2026-09-13. Reason: DEMO reason"),
    ("extension", "Extended lots",
     "Lot DEMO-P1: 2027-03-13, extended from 2026-09-13, approved by DEMO QA on 2026-11-10"),
    CONTROL_FIELD,
]
PREPARATION_OWN = PREPARATION_FIELDS
PREPARATION_FIELDS = _plus_signed(PREPARATION_FIELDS)
PREPARATION_GROUPS = _df.grouped(PREPARATION_FIELDS, _assign({
    "record_id": _df.TRACE, "recipe": _df.TRACE, "recipe_code": _df.TRACE,
    "recipe_revision": _df.TRACE, "kind": _df.TRACE, "storage": _df.TRACE,
    "storage_conditions": _df.TRACE, "control": _df.DOCUMENT,
    "equipment": _df.TRACE, "expiry_note": _df.TRACE, "expired_parents": _df.TRACE,
    "extension": _df.TRACE, "prepared_by": _df.PREPARER, "prepared_date": _df.PREPARER,
    "reviewed_by": _df.REVIEWER, "reviewed_at": _df.REVIEWER}))
PREPARATION_TABLES = {
    "parents": _cols(("lot", "Lot", "DEMO-P1"), ("name", "Name", "DEMO native mix"),
                     ("quantity", "Quantity", "100"), ("unit", "Unit", "µL"),
                     ("expiry", "Expiry", "2027-01-01")),
    "steps": _cols(("n", "Step", "1"), ("instruction", "Instruction", "Pipette the parent into the flask")),
    "made": _cols(("lot_number", "Lot number", "DEMO-LOT-1"), ("name", "Name", "DEMO CAL-1"),
                  ("level", "Level", "CAL-1"), ("volume", "Volume", "10 mL"),
                  ("expiry", "Expiry", "2026-12-05"), ("set_by", "Expiry set by", "the recipe's shelf life")),
    "concentrations": _cols(("lot", "Lot", "DEMO-LOT-1"), ("analyte", "Analyte", "DEMO-PFOA"),
                            ("value", "Value", "5"), ("unit", "Unit", "ng/mL"),
                            ("basis", "Basis", "calculated")),
    "signatures": SIGNATURES_TABLE,
}
PREPARATION_ORDER = ("parents", "steps", "made", "concentrations", "signatures")
PREPARATION_REQUIRED = ("record_id", "recipe", "recipe_revision", "prepared_by", "prepared_date",
                        "storage", "storage_conditions", "reviewed_by", "reviewed_at", "expiry_note",
                        "lab_name", "lab_address", "control")
# the lots a record made usually share their storage conditions; lots that
# differ are each named
NOT_RECORDED = "Not recorded"


def storage_conditions(rows, lots_by_row):
    """The storage conditions of the lots a preparation made, as one line:
    the conditions alone when every lot has the same, else each lot with
    its own; "Not recorded" when no lot holds any. `rows`, the record's
    rows; `lots_by_row`, the inventory lot of each (None when it is gone):
    the lot's own record first, the row as made else."""
    found = []
    for row, lot in zip(rows or [], lots_by_row or []):
        lot = lot or {}
        number = row.get("lot_number") or lot.get("lot_number") or ""
        found.append((_s(number), _s(lot.get("storage_conditions") or row.get("storage_conditions")).strip()))
    distinct = sorted(set(c for _n, c in found if c))
    if not distinct:
        return NOT_RECORDED
    if len(distinct) == 1 and all(c for _n, c in found):
        return distinct[0]
    return "; ".join("%s: %s" % (n, c or NOT_RECORDED) for n, c in found)


def storage_with_conditions(data):
    """`data` (preparation_data) for a design that places the storage
    location and not the storage conditions: the conditions follow the
    location in its field, so a design issued before the record had the
    conditions still prints them. A copy; `data` is not changed."""
    out = dict(data)
    where, how = _s(data.get("storage")).strip(), _s(data.get("storage_conditions")).strip()
    if how:
        out["storage"] = ("%s; conditions: %s" % (where, how)) if where else ("Conditions: %s" % how)
    return out


def expired_in_expiry_note(data):
    """`data` (preparation_data) for a design that does not place the
    parent lots used out of date: their statement follows the expiry note,
    which every design places, so a design issued before the field still
    prints it. A copy; `data` is not changed."""
    out = dict(data)
    used = _s(data.get("expired_parents")).strip()
    if used:
        note = _s(data.get("expiry_note")).strip()
        out["expiry_note"] = ("%s\n%s" % (note, used)) if note else used
    return out


def extension_in_expiry_note(data):
    """`data` (preparation_data) for a design that does not place the
    extended lots: they follow the expiry note, which every design places,
    as the parents used out of date do. A copy; `data` is not changed."""
    out = dict(data)
    ext = _s(data.get("extension")).strip()
    if ext:
        note = _s(data.get("expiry_note")).strip()
        out["expiry_note"] = ("%s\n%s" % (note, ext)) if note else ext
    return out


def extension_lines(parents, made_lots):
    """"Lot X: DATE, extended from ORIGINAL, approved by NAME on DATE" for
    each parent whose extension was in force on the prep date (its
    "extension") and each lot made whose extension is in force now."""
    from senaite.pfas import lot_extension
    out = []
    for p in parents or []:
        if p.get("extension"):
            out.append(u"Lot %s: %s" % (p.get("lot") or u"?", p["extension"]))
    for lot in made_lots or []:
        n = lot_extension.note(lot_extension.in_force_entry((lot or {}).get("extensions")))
        if n:
            out.append(u"Lot %s: %s" % (lot.get("lot_number") or u"?", n))
    return u"; ".join(out)


def preparation_signatures(entry, rows):
    """Every sign-off on a preparation record: its e-signatures from the
    ledger (`rows`, signature_rows), each "on file" marked as an
    e-signature, and the record's own prepared-by and reviewed-by entries
    for a role the ledger holds no signature of, marked as record entries.
    The preparer's first."""
    entry = entry or {}
    rows = [dict(r, image=E_SIGNATURE) if r.get("image") == ON_FILE else r for r in rows or []]
    signed = set(r.get("role") for r in rows)
    entries = []
    for role, label, who, at in (("preparer", "Prepared by", entry.get("prepared_by"),
                                  entry.get("made_at") or entry.get("prepared_date")),
                                 ("reviewer", "Reviewed by", entry.get("reviewed_by"), entry.get("reviewed_at"))):
        if _s(who).strip() and role not in signed:
            entries.append(signature_row(label, who, "", RECORD_ENTRY, at, "", role))
    order = {"preparer": 0, "reviewer": 1}
    return sorted(entries + rows, key=lambda r: order.get(r.get("role"), 2))


def preparation_data(entry, lots, rev, signatures=(), analyte_name=None, unit_of=None):
    """From a preparation record (prep_entries), its lots by uid (the
    Prepared Standards list) and the recipe revision it was made by. A lot's
    expiry names what set it: the parent that capped it, else the recipe's
    shelf life. signatures: the Signatures table's rows (signature_rows),
    given only when the ledger holds some. analyte_name(name): the name an
    analyte prints by, as the certificate names it (the compound library's
    display name); the stored name when not given. unit_of(unit id): the
    Equipment register's unit, for each piece of equipment's serial
    (preparation_equipment)."""
    from senaite.pfas import lot_expiry, lot_record
    entry, lots, rev = entry or {}, lots or {}, rev or {}
    recipe = entry.get("recipe") or {}
    shelf = rev.get("shelf_life_days")
    uids = entry.get("lots") or []
    made, concs, notes = [], [], []
    for i, row in enumerate(entry.get("rows") or []):
        lot = lots.get(uids[i]) if i < len(uids) else None
        lot = lot or {}
        number = row.get("lot_number") or lot.get("lot_number") or ""
        expiry = lot.get("effective_expiry") or lot.get("expiry_date") or row.get("expiry_date") or ""
        note = lot_record.expiry_note(dict(lot, prepared_date=lot.get("prepared_date") or entry.get("prepared_date"),
                                           expiry_date=lot.get("expiry_date") or row.get("expiry_date")),
                                      shelf) if lot else u""
        # only what the lot's own record confirms: the parent that capped it,
        # the shelf life when the date is exactly that, else it was set by hand
        if lot.get("expiry_inherited_from"):
            by = lot["expiry_inherited_from"]
        elif note:
            by = u"the recipe's shelf life"
        elif lot:
            by = u"set by hand"
        else:
            by = u""
        made.append({"lot_number": _s(number), "name": _s(row.get("title") or lot.get("title")),
                     "level": _s(row.get("level")), "volume": _s(row.get("volume_prepared")),
                     "expiry": _s(expiry), "set_by": _s(by)})
        if note:
            notes.append(u"%s: %s" % (number, note))
        rec = {"analyte_concentrations": row.get("analyte_concentrations")}
        for c, how in zip(rec["analyte_concentrations"] or [], lot_record.conc_rows(rec)):
            concs.append({"lot": _s(number),
                          "analyte": _s(analyte_name(c.get("analyte")) if analyte_name else c.get("analyte")),
                          "value": _s(c.get("concentration")), "unit": _s(c.get("unit")),
                          "basis": _s(how["how"])})
    out = {
        "record_id": _s(entry.get("id")), "recipe": _s(recipe.get("name")),
        "recipe_code": _s(recipe.get("code")), "recipe_revision": _s(recipe.get("revision")),
        "kind": _s(recipe.get("kind")), "prepared_by": _s(entry.get("prepared_by")),
        "prepared_date": _s(entry.get("prepared_date")), "storage": _s(entry.get("storage_location")),
        "storage_conditions": storage_conditions(
            entry.get("rows"), [lots.get(uids[i]) if i < len(uids) else None
                                for i in range(len(entry.get("rows") or []))]),
        "equipment": preparation_equipment(entry.get("equipment"), unit_of),
        "reviewed_by": _s(entry.get("reviewed_by")),
        "reviewed_at": _s(entry.get("reviewed_at")), "expiry_note": u"; ".join(notes),
        # a parent used out of date, and the reason the preparer gave
        "expired_parents": _s(lot_expiry.statement(entry.get("parents"), entry.get("prepared_date"))),
        # a lot used or made whose expiry QA extended
        "extension": _s(extension_lines(entry.get("parents"),
                                        [lots.get(u) for u in uids if lots.get(u)])),
        "parents": [{"lot": _s(p.get("lot")), "name": _s(p.get("name")), "quantity": _s(p.get("qty")),
                     "unit": _s(p.get("unit")),
                     "expiry": _s(lot_expiry.shown_expiry(p.get("expiry"), p.get("no_expiry")))}
                    for p in entry.get("parents") or []],
        "steps": [{"n": _s(i + 1), "instruction": _s(st.get("instruction") if isinstance(st, dict) else st)}
                  for i, st in enumerate(rev.get("steps") or [])],
        "made": made, "concentrations": concs,
    }
    signatures = preparation_signatures(entry, signatures)
    if signatures:
        out["signatures"] = signatures
    return out


# ── QC Review report (senaite.pfas:QCReviewReport.pt) ──────────────────────

QC_FIELDS = [
    ("lab_name", "Laboratory", "DEMO Laboratory"),
    ("worksheet", "Worksheet", "WS-DEMO"), ("batch", "Batch", "B-DEMO"),
    ("batch_title", "Batch title", "DEMO batch"), ("method", "Method", "EPA_537_1"),
    ("matrix", "Matrix", "Drinking Water"), ("analyst", "Analyst", "AN1"),
    ("run_dates", "Analysis date(s)", "2026-10-03"), ("unit", "Reporting unit", "ng/L"),
    ("matrix_factor", "Matrix factor applied", "1"), ("state", "Worksheet state", "verified"),
    ("qc_overall", "QC summary", "32 analytes · QC types LFB, MB · overall PASS"),
    ("spike_pending", "Spike level not recorded", ""),
    ("unresolved", "Traceability gaps", ""),
    ("planned", "Planned injections", "24"), ("acquired", "Injections acquired", "24"),
    ("not_run", "Planned but not run", "—"), ("unplanned", "Run but not planned", "—"),
    ("stamp", "Controlled stamp", "Controlled documentation publication · DEMO-0001-R1 · uncontrolled when printed"),
    CONTROL_FIELD,
]
QC_OWN = QC_FIELDS
QC_FIELDS = _plus_signed(QC_FIELDS)
QC_GROUPS = _df.grouped(QC_FIELDS, _assign({
    "worksheet": _df.BATCH, "batch": _df.BATCH, "batch_title": _df.BATCH,
    "method": _df.ANALYSIS, "matrix": _df.ANALYSIS, "run_dates": _df.ANALYSIS,
    "unit": _df.ANALYSIS, "matrix_factor": _df.ANALYSIS, "analyst": _df.PREPARER,
    "state": _df.BATCH, "qc_overall": _df.QC, "spike_pending": _df.QC,
    "unresolved": _df.TRACE, "planned": _df.BATCH, "acquired": _df.BATCH,
    "not_run": _df.BATCH, "unplanned": _df.BATCH, "stamp": _df.DOCUMENT,
    "control": _df.DOCUMENT}))

QC_TABLES = {
    "criteria": _cols(("criterion", "Criterion", "Calibration r² minimum"), ("value", "Value", "0.99"),
                      ("source", "Source", "Method Profile")),
    "gates": _cols(("gate", "Gate", "Chain of Custody"), ("type", "Type", "Manual"),
                   ("verdict", "Verdict", "PASS"), ("detail", "Detail", "signed AN1")),
    "calibrations": _cols(("analyte", "Analyte", "PFOA"), ("r2", "r²", "0.999100"),
                          ("minimum", "Minimum", "0.99"), ("verdict", "Verdict", "PASS")),
    "qc_summary": _cols(("analyte", "Analyte", "PFOA"), ("qc_type", "QC type", "LFB"),
                        ("status", "Status", "98%")),
    "spike_qc": _cols(("analyte", "Analyte", "PFOA"), ("qc_type", "QC type", "LFSM"),
                      ("status", "Status", "102%")),
    "traceability": _cols(("item", "Standard / reagent", "PDS-A"), ("lot", "Lot", "DEMO-PS-1"),
                          ("resolves", "Resolves to", "prepared standard, 2 parent lot(s)")),
    "results": _cols(("sample", "Sample", "DEMO-0001"), ("client_sid", "Client sample ID", "DEMO-CLIENT-1"),
                     ("analyte", "Analyte", "PFOA"),
                     ("result", "Result", "4.2"), ("qualifier", "Qualifier", ""),
                     ("state", "State", "verified")),
    "publications": _cols(("sample", "Sample", "DEMO-0001"), ("report_id", "Report ID", "DEMO-0001-R1"),
                          ("issued", "Issued", "2026-10-05"), ("by", "By", "AN3"),
                          ("status", "Status", "issued"), ("reason", "Amendment reason", "—")),
    "deviations": _cols(("deviation", "Deviation", "DEMO deviation"), ("raised", "Raised", "2026-10-02"),
                        ("state", "State", "open")),
    "flagged": _cols(("qc_type", "QC type", "LFB"), ("injection", "Injection", "LFB-1"),
                     ("analyte", "Analyte", "PFOA"), ("result", "Result", "1.0"), ("rt", "RT", "5.1"),
                     ("ion_ratio", "Ion ratio", "1.2"), ("flag", "Flag", "RT")),
    "measurements": _cols(("qc_type", "QC type", "LFB"), ("injection", "Injection", "LFB-1"),
                          ("analyte", "Analyte", "PFOA"), ("role", "Role", "native"),
                          ("result", "Result", "1.0"), ("rt", "RT", "5.1"), ("rrt", "RRT", "1.00"),
                          ("ion_ratio", "Ion ratio", "1.2"), ("expected", "Expected", "1.1"),
                          ("sn", "S/N", "120"), ("is_area", "IS area", "1e5"),
                          ("qual", "Qual.", ""), ("flag", "Flag", "")),
}
QC_ORDER = ("criteria", "gates", "calibrations", "qc_summary", "spike_qc", "traceability",
            "results", "publications", "deviations", "flagged", "measurements")
QC_REQUIRED = ("lab_name", "worksheet", "batch", "method", "matrix", "analyst", "state", "qc_overall",
               "spike_pending", "unresolved", "planned", "acquired", "not_run", "unplanned", "stamp",
               "lab_address", "control")

_VERDICT = {"pass": "PASS", "fail": "FAIL", "blocked": "NOT EVALUATED"}


# the most value columns a pivoted table prints beside its first column on
# a portrait page: each gets a fifth of the width, room for the longest
# status word whole; more split into further tables
PIVOT_COLUMNS = 4


def column_parts(columns, limit=PIVOT_COLUMNS):
    """`columns` in runs of at most `limit`, in order: a pivoted table
    (analyte by QC type) prints one table per run, each with its first
    column, so no table is wider than the page. No columns, no table."""
    columns = list(columns or [])
    return [columns[i:i + limit] for i in range(0, len(columns), limit)]


# the QC summary's two tables: an analyte is judged on other QC than a
# labelled standard is, so each kind has its own columns
NATIVES, LABELLED = "Native analytes", "Isotope standards"


def kind_tables(section, types_key, labelled):
    """A pivoted QC section (rows of {"analyte", "cells"}) as one table per
    kind, natives first: [{"title", "columns", "rows"}]. `labelled(name)`
    says whether an analyte is a labelled standard. A table's columns are
    the QC types any of its rows has a result for, in the section's order,
    so no column of one kind is printed empty for the other; a kind with no
    analyte is no table."""
    section = section or {}
    rows = section.get("rows") or []
    types = section.get(types_key) or []
    out = []
    for title, want in ((NATIVES, False), (LABELLED, True)):
        mine = [r for r in rows if bool(labelled(r.get("analyte"))) == want]
        cols = [t for t in types if any((r.get("cells") or {}).get(t) for r in mine)]
        if mine:
            out.append({"title": title, "columns": cols, "rows": mine})
    return out


def _pivot(section, types_key, labelled=None):
    out = []
    for table in kind_tables(section, types_key, labelled or (lambda name: False)):
        for row in table["rows"]:
            for t in table["columns"]:
                cell = (row.get("cells") or {}).get(t)
                out.append({"analyte": _s(row.get("analyte")), "qc_type": _s(t),
                            "status": _s(cell.get("badge") or cell.get("status")) if cell else "\u2014"})
    return out


# The keys qc_review_data reads; a report tier part names a subset of them.
QC_REVIEW_SECTIONS = ("identity", "criteria", "gates", "calibrations",
                      "qc_summary", "spike_qc", "traceability", "run_vs_plan",
                      "final_data", "publications", "deviations",
                      "exceptions", "injections")

# The fields every QC Review part prints: the starter design's every-page
# header (the run's identity, its injection counts, the laboratory and the
# controlled stamp), so a part read alone still names the run it reviews.
QC_EVERY_PART = ("lab_name", "worksheet", "batch", "batch_title", "method", "matrix", "analyst",
                 "run_dates", "unit", "matrix_factor", "state", "planned", "acquired", "stamp",
                 "lab_address", "control")
# The fields of qc_review_data each section produces beyond the header; a QC
# Review part prints only its sections' fields.
QC_SECTION_FIELDS = {
    "identity": (), "criteria": ("criteria",), "gates": ("gates",),
    "calibrations": ("calibrations",),
    "qc_summary": ("qc_summary", "qc_overall"), "spike_qc": ("spike_qc", "spike_pending"),
    "traceability": ("traceability", "unresolved"),
    "run_vs_plan": ("not_run", "unplanned"),
    "final_data": ("results",), "publications": ("publications",),
    "deviations": ("deviations",), "exceptions": ("flagged",), "injections": ("measurements",),
}


def _known_sections(sections):
    unknown = [s for s in sections if s not in QC_SECTION_FIELDS]
    if unknown:
        raise ValueError("Unknown QC Review section: %s" % ", ".join(unknown))


def qc_review_omitted(sections):
    """The fields of the QC Review sections a part does not print; an
    unknown section is refused, never printed whole."""
    _known_sections(sections)
    out = set()
    for s, keys in QC_SECTION_FIELDS.items():
        if s not in sections:
            out.update(keys)
    return out


def qc_review_subset(data, sections):
    """`data` (qc_review_data) cut to the fields of `sections` and those
    every part prints."""
    omitted = qc_review_omitted(sections)
    return dict((k, v) for k, v in data.items() if k not in omitted)


def qc_review_data(s):
    """From the QC Review view's sections: {identity, criteria, gates,
    calibrations, qc_summary, spike_qc, traceability, run_vs_plan, final_data,
    publications, deviations, exceptions, injections, stamp}."""
    ident = s.get("identity") or {}
    qc = s.get("qc_summary") or {}
    sq = s.get("spike_qc") or {}
    tr = s.get("traceability") or {}
    rp = s.get("run_vs_plan") or {}
    if qc.get("error"):
        overall = "QC results unavailable: %s" % qc["error"]
    else:
        overall = "%d analytes · QC types %s · overall %s" % (
            len(qc.get("rows") or []), ", ".join(qc.get("qc_types") or []),
            "PASS" if qc.get("overall_pass") else "FAIL")
    gates = []
    for g in s.get("gates") or []:
        detail = _s(g.get("reason"))
        if g.get("checked_by"):
            detail = (detail + " " if detail else "") + "signed %s" % g["checked_by"]
            if g.get("checked_at"):
                detail += " at %s" % _s(g["checked_at"])[:16]
        gates.append({"gate": _s(g.get("label")), "type": "Automatic" if g.get("auto") else "Manual",
                      "verdict": _VERDICT.get(g.get("verdict") or "pending", "PENDING"), "detail": detail})
    # every lot of the traceability walk, the extraction's standards
    # included: the rows the page print shows (worksheet_lots.trace_rows)
    from senaite.pfas import worksheet_lots
    trace = [{"item": _s(r["item"]), "lot": _s(r["lot"]), "resolves": _s(r["resolves"])}
             for r in worksheet_lots.trace_rows(tr)]

    def meas(r):
        return {"qc_type": _s(r.get("qc_type")), "injection": _s(r.get("injection_name")),
                "analyte": _s(r.get("analyte")), "role": _s(r.get("role")),
                "result": _s(r.get("calc_conc")), "rt": _s(r.get("rt")), "rrt": _s(r.get("rrt")),
                "ion_ratio": _s(r.get("ion_ratio_obs")), "expected": _s(r.get("ion_ratio_exp")),
                "sn": _s(r.get("sn")), "is_area": _s(r.get("is_area")),
                "qual": _s(r.get("conc_qualifier")), "flag": _s(r.get("flag"))}
    return {
        "lab_name": _s(s.get("lab_name")), "lab_address": _s(s.get("lab_address")),
        # the document control block is written when the report is printed
        # (report_designs.designed_pdf)
        "control": "",
        "worksheet": _s(ident.get("worksheet")), "batch": _s(ident.get("batch")),
        "batch_title": _s(ident.get("batch_title")), "method": _s(ident.get("method")),
        "matrix": _s(ident.get("matrix")), "analyst": _s(ident.get("analyst")),
        "run_dates": ", ".join(ident.get("run_dates") or []) or "—",
        "unit": _s(ident.get("unit")), "matrix_factor": _s(ident.get("matrix_factor")),
        "state": _s(ident.get("state")), "qc_overall": overall,
        "spike_pending": (("Spike level not recorded for: %s. Recovery cannot be evaluated until it is entered."
                           % ", ".join(_s(p.get("injection")) for p in sq.get("pending_spikes")))
                          if sq.get("pending_spikes") else ""),
        "unresolved": (("%d lot(s) named in the logbooks are not in inventory — the chain from "
                        "result to certified standard is incomplete." % len(tr["unresolved"]))
                       if tr.get("unresolved") else ""),
        "planned": (_s(len(rp.get("planned") or [])) if rp.get("stored", bool(rp.get("planned")))
                    else NO_RUN_PLAN),
        "acquired": _s(len(rp.get("actual") or [])),
        "not_run": ", ".join(rp.get("not_run") or []) or "—",
        "unplanned": ", ".join(rp.get("unplanned") or []) or "—",
        "stamp": _s(s.get("stamp")),
        "criteria": [{"criterion": _s(c.get("criterion")), "value": _s(c.get("value")),
                      "source": _s(c.get("source"))} for c in s.get("criteria") or []],
        "gates": gates,
        "calibrations": [{"analyte": _s(c.get("analyte")),
                          "r2": "%.6f" % c["r2"] if c.get("r2") is not None else "—",
                          "minimum": _s(c.get("limit")), "verdict": "PASS" if c.get("passed") else "FAIL"}
                         for c in s.get("calibrations") or []],
        "qc_summary": [] if qc.get("error") else _pivot(qc, "qc_types",
                                                        set(qc.get("labelled") or ()).__contains__),
        "spike_qc": _pivot(sq, "types"),
        "traceability": trace,
        # the sample by its laboratory number and the analyte by its
        # title, as the certificate prints them; the client's own id beside
        "results": [{"sample": _s(r.get("sample_id") or r.get("client_sample_id")),
                     "client_sid": _s(r.get("client_sample_id")),
                     "analyte": _s(r.get("title") or r.get("analyte")), "result": _s(r.get("result")),
                     "qualifier": _s(r.get("qualifier")), "state": _s(r.get("review_state"))}
                    for r in s.get("final_data") or []],
        "publications": [{"sample": _s(p.get("sample")), "report_id": _s(p.get("report_id")),
                          "issued": _s(p.get("issued_at"))[:16], "by": _s(p.get("authorizer")),
                          "status": _s(p.get("status")),
                          "reason": _s(p.get("amendment_reason")) or ("REASON NOT RECORDED"
                                                                     if p.get("reason_missing") else "—")}
                         for p in s.get("publications") or []],
        "deviations": [{"deviation": _s(d.get("title") or d.get("description")),
                        "raised": _s(d.get("created")), "state": _s(d.get("state") or d.get("review_state"))}
                       for d in s.get("deviations") or []],
        "flagged": [dict((k, v) for k, v in meas(r).items()
                         if k in ("qc_type", "injection", "analyte", "result", "rt", "ion_ratio", "flag"))
                    for r in s.get("exceptions") or []],
        "measurements": [meas(r) for r in s.get("injections") or []],
    }


# ── settings report (@@pfas-settings-report) ───────────────────────────────

SETTINGS_FIELDS = [
    ("title", "Title", "QC Settings Report"), ("revision_label", "Revision", "DRAFT"),
    ("generated", "Generated", "2026-10-05 10:00"), ("user", "Generated by", "AN3"),
    ("fingerprint", "Configuration id", "abc123def4567890"),
    ("methods", "Methods", "EPA 537.1 (EPA_537_1): Drinking Water; 25 analytes; Revision 2"),
    ("unread_switches", "Switches the pipeline does not read", ""),
    ("stale", "Project specs out of date", ""),
    ("lab_name", "Laboratory", "DEMO Laboratory"),
    ("lab_address", "Address", "1 Example Road, Example Town"),
    # the Help entry the on-screen report points to, as its address: no
    # value names its source, the entry lists them
    ("value_sources", "Where the values come from",
     "https://lims.example.org/senaite/@@pfas-help?entry=value-sources"),
    CONTROL_FIELD,
]
# a field the Settings Report gained after its first design: a design
# issued before it keeps printing, and Document Templates says it is not
# placed (document_templates.warnings)
SETTINGS_EXPECTED = ("value_sources",)
# parts printed only with something under them: an empty one leaves its
# heading out of the print (empty_fields, document_templates.subset_design)
SETTINGS_OMIT_EMPTY = ("unread_switches", "stale")
SETTINGS_GROUPS = _df.grouped(SETTINGS_FIELDS, {
    "value_sources": _df.DOCUMENT,
    "lab_name": _df.LAB, "lab_address": _df.LAB, "control": _df.DOCUMENT,
    "title": _df.DOCUMENT, "revision_label": _df.DOCUMENT, "generated": _df.DOCUMENT,
    "user": _df.PREPARER, "fingerprint": _df.DOCUMENT, "methods": _df.ANALYSIS,
    "unread_switches": _df.QC, "stale": _df.QC})

SETTINGS_TABLES = {
    "qc_application": _cols(("method", "Method", "EPA_537_1"), ("code", "QC type", "LFSM"),
                            ("criterion", "Criterion", "Recovery window per tier"),
                            ("enabled", "On for this method", "Yes"), ("evaluated", "Judged by the pipeline", "Yes"),
                            ("how", "How", "Each LFSM injection x analyte"),
                            ("tiers", "Tiers", "Tier 1: 70–130% (all; all; method profile)")),
    "instrument_checks": _cols(("method", "Method", "EPA_537_1"), ("check", "Check", "Calibration"),
                               ("criterion", "Criterion", "r² minimum"), ("switch", "Rule switch", "Calibration r² on"),
                               ("evaluated", "Judged by the pipeline", "Yes"), ("how", "How", "Per analyte")),
    "recovery_grid": _cols(("method", "Method", "EPA_537_1"), ("analytes", "Analytes", "Regulated analytes"),
                           ("matrix", "Matrix", "Drinking Water"), ("window", "Window", "70–130%")),
    "revisions": _cols(("method", "Method", "EPA_537_1"), ("rev", "Revision", "2.0"),
                       ("issued", "Issued", "2026-10-02"), ("by", "By", "AN3"), ("reason", "Reason", "")),
    "settings": _cols(("method", "Method", "EPA_537_1"), ("section", "Section", "Calibration & CCV"),
                      ("setting", "Setting", "r² minimum"), ("value", "Value", "0.99")),
    "limits": _cols(("program", "Program", "US EPA"), ("limit", "Limit", "PFOA"),
                    ("analytes", "Analytes", "PFOA"), ("matrices", "Matrices", "Drinking Water"),
                    ("value", "Value", "4 ng/L"), ("kind", "Kind", "MCL"), ("verified", "Verified", "No"),
                    ("citation", "Citation", "")),
    "projects": _cols(("project", "Project", "DEMO"), ("client", "Client", "DEMO"), ("qapp", "QAPP", ""),
                      ("status", "Status", "active"), ("method", "Method", "EPA_537_1"),
                      ("scopes", "Specs for", "All matrices"),
                      ("departures", "Looser than the method", "")),
    "equipment_rules": _cols(("subject", "Applies to", "Balance"), ("rule", "Rule", "0.2 % of nominal")),
    "equipment_types": _cols(("type", "Type", "Balance"), ("kind", "Kind", "Balance"),
                             ("every", "Check every", "90 days"), ("correction", "Correction factor", "No"),
                             ("external", "External certificate", "Yes"), ("unit", "Unit", "g"),
                             ("tolerance", "Tolerance", "0.2 %"), ("worksheets", "In worksheets", "No")),
    "instruments": _cols(("name", "Instrument", "Balance 1"), ("type", "Type", "Balance"),
                         ("location", "Location", "Lab"), ("internal", "Internal check", "2026-10-01"),
                         ("external", "External certificate", "not required"),
                         ("correction", "Correction factor", ""), ("status", "Status", "OK")),
    "facility_defaults": _cols(("setting", "Setting", "Type 1 water, maximum TOC (ppb)"), ("value", "Value", "50")),
    "lab_settings": _cols(("setting", "Setting", "Laboratory name on reports"), ("value", "Value", "DEMO Lab")),
}
SETTINGS_ORDER = ("qc_application", "instrument_checks", "recovery_grid", "revisions", "settings",
                  "limits", "projects", "equipment_rules", "equipment_types", "instruments",
                  "facility_defaults", "lab_settings")
SETTINGS_REQUIRED = ("title", "revision_label", "generated", "user", "fingerprint", "methods",
                     "unread_switches", "stale", "lab_name", "lab_address", "control")


def _rev_label(rec):
    """A method revision record (or status) by its major.sub number."""
    from senaite.pfas import method_revisions
    return _s(rec.get("label") or method_revisions.label(rec))


def settings_data(report):
    """From PFASSettingsReportView.report()."""
    methods, unread, stale = [], [], []
    qc, inst, grid, revs, settings = [], [], [], [], []
    for m in report.get("methods") or []:
        # a method prints by its name; its stored id is never printed
        mid = _s(m.get("name")) or _s(m.get("method_id"))
        rv = m.get("revision") or {}
        methods.append("%s: %s; %s analytes; %s" % (
            mid, ", ".join(m.get("matrices") or []) or "none", _s(m.get("panel")),
            ("Revision %s, issued %s by %s%s" % (_rev_label(rv), _s(rv.get("issued_at")), _s(rv.get("issued_by")),
                                                 "; settings changed since" if rv.get("unissued") else ""))
            if rv.get("rev") else "No revision issued yet"))
        unread += ["%s: %s" % (mid, sw.get("label") or sw.get("key"))
                   for sw in m.get("switches") or [] if not sw.get("read")]
        for q in m.get("qc") or []:
            qc.append({"method": mid, "code": _s(q.get("code")), "criterion": _s(q.get("criterion")),
                       "enabled": _s(bool(q.get("enabled"))), "evaluated": _s(bool(q.get("evaluated"))),
                       "how": _s(q.get("how")),
                       "tiers": "; ".join("%s: %s (%s)" % (_s(t.get("name")), _s(t.get("criterion")),
                                                         _s(t.get("applies")))
                                          for t in q.get("tiers") or [])})
        for c in m.get("instrument") or []:
            inst.append({"method": mid, "check": _s(c.get("check")), "criterion": _s(c.get("criterion")),
                         "switch": "%s %s" % (_s(c.get("switch_label") or c.get("switch")), "on" if c.get("on") else "off"),
                         "evaluated": _s(bool(c.get("evaluated"))), "how": _s(c.get("how"))})
        g = m.get("grid") or {}
        for row in g.get("rows") or []:
            for mx, cell in zip(g.get("matrices") or [], row.get("cells") or []):
                window = _s(cell.get("text"))
                if cell.get("tier"):
                    window += " (%s)" % cell["tier"]
                if cell.get("low"):
                    window += " low level %s" % cell["low"]
                grid.append({"method": mid, "analytes": _s(row.get("title")), "matrix": _s(mx), "window": window})
        for r in m.get("revisions") or []:
            revs.append({"method": mid, "rev": _rev_label(r), "issued": _s(r.get("issued_at")),
                         "by": _s(r.get("issued_by")), "reason": _s(r.get("reason"))})
        for sec in m.get("sections") or []:
            cols = sec.get("columns") or []
            for row in sec.get("rows") or []:
                rest = ["%s: %s" % (c, v) for c, v in zip(cols[1:], row[1:]) if _s(v)]
                settings.append({"method": mid, "section": _s(sec.get("title")),
                                 "setting": _s(row[0] if row else ""),
                                 "value": rest[0].split(": ", 1)[1] if len(rest) == 1 and len(cols) == 2
                                 else "; ".join(rest)})
    programs = report.get("programs") or {}
    limits = [{"program": _s((programs.get(l.get("program")) or {}).get("name") or l.get("program")),
               "limit": _s(l.get("label")), "analytes": ", ".join(l.get("analytes") or []),
               "matrices": ", ".join(l.get("matrices") or []) or "none assigned",
               "value": "%s %s" % (_s(l.get("value")), _s(l.get("unit"))), "kind": _s(l.get("kind")),
               "verified": _s(bool(l.get("verified"))), "citation": _s(l.get("citation"))}
              for l in report.get("limits") or []]
    projects = []
    for pj in report.get("projects") or []:
        base = {"project": "%s — %s" % (_s(pj.get("code")), _s(pj.get("title"))),
                "client": _s(pj.get("client")), "qapp": _s(pj.get("qapp")) or "none (internal quality system)",
                "status": _s(pj.get("status"))}
        if not pj.get("methods"):
            projects.append(dict(base, method="", scopes="", departures="No specs: linked batches run to the method."))
        for pm in pj.get("methods") or []:
            pm_name = _s(pm.get("name")) or _s(pm.get("method_id"))
            stale += ["%s %s: %s" % (_s(pj.get("code")), pm_name, _s(x)) for x in pm.get("stale") or []]
            projects.append(dict(base, method=pm_name, scopes=", ".join(pm.get("scopes") or []),
                                 departures="; ".join("%s %s → %s (%s; published %s)" % (
                                     _s(d.get("what")), _s(d.get("method")), _s(d.get("project")),
                                     _s(d.get("where")), _s(d.get("published")))
                                     for d in pm.get("departures") or [])))
    eq = report.get("equipment") or {}
    return {
        "lab_name": _s(report.get("lab_name")), "lab_address": _s(report.get("lab_address")),
        "title": _s(report.get("title")), "revision_label": _s(report.get("revision_label")),
        "generated": _s(report.get("generated")), "user": _s(report.get("user")),
        "fingerprint": _s(report.get("fingerprint")), "methods": "\n".join(methods),
        "unread_switches": ", ".join(unread), "stale": "\n".join(stale),
        "value_sources": _s(report.get("value_sources")),
        "qc_application": qc, "instrument_checks": inst, "recovery_grid": grid, "revisions": revs,
        "settings": settings, "limits": limits, "projects": projects,
        "equipment_rules": [{"subject": _s(a[0]), "rule": _s(a[1])} for a in eq.get("application") or []],
        "equipment_types": [{"type": _s(t.get("title")) + ("" if t.get("configured") else " (not set up)"),
                             "kind": _s(t.get("kind")), "every": _s(t.get("every")),
                             "correction": _s(t.get("correction")), "external": _s(t.get("external")),
                             "unit": _s(t.get("unit")), "tolerance": _s(t.get("tolerance")),
                             "worksheets": _s(t.get("worksheets"))} for t in eq.get("types") or []],
        "instruments": [{"name": _s(i.get("name")) + (" (SN %s)" % i["serial"] if i.get("serial") else "")
                         + ("" if i.get("active", True) else " (inactive)"),
                         "type": _s(i.get("type")), "location": _s(i.get("location")),
                         "internal": _s(i.get("internal")), "external": _s(i.get("external")),
                         "correction": _s(i.get("correction")), "status": _s(i.get("status"))}
                        for i in eq.get("instruments") or []],
        "facility_defaults": [{"setting": _s(k), "value": _s(v)} for k, v in eq.get("defaults") or []],
        "lab_settings": [{"setting": _s(k), "value": _s(v)} for k, v in report.get("lab") or []],
    }


# ── a starting layout for any report ───────────────────────────────────────

# the smallest text a record prints: its tables and its foot lines
MIN_PT = 7.0


def control_foot(keys, width, height):
    """The fields of a document's control block as a design places them: on
    every page, in the bottom margin, left of the page number; a block that
    names the time zone carries it as its last line."""
    return [dict(_text(key, 10, height - 16.5 + i * 7, width - 20.0 - 55, 7, MIN_PT), pfasEveryPage=True)
            for i, key in enumerate(keys)]


def starter(title, fields, tables, order, long_fields=(), width=210.0, height=297.0, banner=(),
            foot=()):
    """Title and the identity fields on every page, then each paragraph and
    each table under its heading, page numbers in the footer. Everything a
    design must show is placed; the lab rearranges it. `banner`: fields
    printed on one line under the title (the laboratory's name and
    address); `foot`: fields printed at the foot of every page, left of the
    page number (the document control block)."""
    every = {"pfasEveryPage": True}
    wide = width - 20.0
    out = [dict(_text("doc_title", 10, 10, wide, 7, 13, readOnly=True, content=title), **every)]
    short = [f for f in fields if f[0] not in long_fields and f[0] not in banner and f[0] not in foot]
    y = 18.0
    if banner:
        # the first a third of the line, the rest shares what is left
        first, rest = wide / 3.0, (wide - wide / 3.0) / max(len(banner) - 1, 1)
        x = 10.0
        for i, key in enumerate(banner):
            w = first if i == 0 else rest
            out.append(dict(_text(key, x, y, w - 2, 4.5, MIN_PT), **every))
            x += w
        y += 5.5
    for i, (key, label, _e) in enumerate(short):
        col, row = i % 2, i // 2
        x = 10 + col * (wide / 2.0)
        out.append(dict(_text("label_" + key, x, y + row * 5, 32, 4.5, 7, readOnly=True, content=label), **every))
        out.append(dict(_text(key, x + 33, y + row * 5, wide / 2.0 - 35, 4.5, 7), **every))
    top = y + ((len(short) + 1) // 2) * 5 + 4
    out.append(dict({"name": "header_rule", "type": "line", "position": {"x": 10, "y": top - 2},
                     "width": wide, "height": 0.3, "readOnly": True, "color": _P["s-body"]}, **every))
    pages = [out]
    page = out
    y = top + 2

    def room(need):
        """Start the next page when this one is full (each page's content
        still grows and flows on its own)."""
        if y + need <= height - 20:
            return y, page
        nxt = []
        pages.append(nxt)
        return top + 2, nxt

    for key in long_fields:
        label = dict((k, t) for k, t, _e in fields).get(key, key)
        y, page = room(12)
        page.append(_text("label_" + key, 10, y, wide, 4.5, 8, readOnly=True, content=label))
        page.append(_text(key, 10, y + 5, wide, 5, 7.5, overflow="expand"))
        y += 12
    for name in order:
        cols = tables[name]
        y, page = room(22)
        page.append(_text("heading_" + name, 10, y, wide, 5, 9, readOnly=True,
                          content=name.replace("_", " ").capitalize()))
        page.append({"name": name, "type": "table", "position": {"x": 10, "y": y + 6}, "width": wide,
                    "height": 12, "showHead": True, "repeatHead": True,
                    "head": [t for _k, t, _e in cols],
                    "headWidthPercentages": [100.0 / len(cols)] * len(cols),
                    "pfasColumns": [k for k, _t, _e in cols], "content": "[]",
                    "tableStyles": {"borderColor": _P["s-body"], "borderWidth": 0.2},
                    "headStyles": {"fontSize": MIN_PT, "fontColor": _P["s-body"], "backgroundColor": "",
                                   "borderColor": _P["s-body"],
                                   "borderWidth": {"top": 0.3, "right": 0, "bottom": 0.3, "left": 0},
                                   "padding": {"top": 1, "right": 1, "bottom": 1, "left": 1}},
                    "bodyStyles": {"fontSize": MIN_PT, "borderColor": _P["s-border"], "alternateBackgroundColor": "",
                                   "borderWidth": {"top": 0, "right": 0, "bottom": 0.1, "left": 0},
                                   "padding": {"top": 0.8, "right": 1, "bottom": 0.8, "left": 1}}})
        y += 22
    out += control_foot(foot, width, height)
    out.append(dict(_text("pager", width - 60, height - 12, 50, 5, 7, "right", readOnly=True,
                          content="Page {currentPage} of {totalPages}"), **every))
    return {"basePdf": {"width": width, "height": height, "padding": [top + 2, 10, 18, 10]},
            "schemas": pages}


_text = _df.text_field
