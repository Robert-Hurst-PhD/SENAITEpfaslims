# -*- coding: utf-8 -*-
"""Two designed documents drawn from published practice:

    coc        Chain of Custody: one row per sample from the sample records
               (collection date and time, sampling point, matrix, containers,
               preservative, analyses, homogenisation, composite), the CoC
               record's field QC, custody transfers and receipt block.
               Layout after NMED SOP-01-ECP-2025 and EPA SOP COC-01-08.
    sop_cover  Controlled document cover: the title page (title, ID, revision,
               effective date, approval table, revision history) and the
               "ID / Rev / Date / Page x of y" header on every page, after EPA
               QA/G-6 (EPA/600/B-07/001) §2.5 and §3.1.

Fields, tables, designer categories, starting layouts and the data builders
for both. Examples are DEMO. Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas import doc_fields as _df
except ImportError:                                         # loaded by path (tests)
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import doc_fields as _df


def _s(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return "%s" % v


def _t(name, x, y, w, h, size=8, align="left", **kw):
    f = {"name": name, "type": "text", "position": {"x": x, "y": y}, "width": w,
         "height": h, "fontSize": size, "alignment": align, "content": ""}
    f.update(kw)
    return f


def _fixed(name, text, x, y, w, h, size=7.5, align="left", **kw):
    return _t(name, x, y, w, h, size, align, readOnly=True, content=text, **kw)


def _image(name, x, y, w, h, **kw):
    f = {"name": name, "type": "image", "position": {"x": x, "y": y}, "width": w,
         "height": h, "content": ""}
    f.update(kw)
    return f


def _rule(name, x, y, w, **kw):
    return dict({"name": name, "type": "line", "position": {"x": x, "y": y},
                 "width": w, "height": 0.3, "readOnly": True, "color": "#222222"}, **kw)


def _table(name, columns, x, y, w, widths, size=6.5):
    return {"name": name, "type": "table", "position": {"x": x, "y": y}, "width": w,
            "height": 12, "showHead": True, "repeatHead": True,
            "head": [t for _k, t, _e in columns], "headWidthPercentages": widths,
            "pfasColumns": [k for k, _t2, _e in columns], "content": "[]",
            "tableStyles": {"borderColor": "#222222", "borderWidth": 0.2},
            "headStyles": {"fontSize": size, "fontColor": "#222222", "backgroundColor": "",
                           "borderColor": "#222222",
                           "borderWidth": {"top": 0.3, "right": 0.1, "bottom": 0.3, "left": 0.1},
                           "padding": {"top": 1, "right": 1, "bottom": 1, "left": 1}},
            "bodyStyles": {"fontSize": size, "borderColor": "#888888", "alternateBackgroundColor": "",
                           "borderWidth": {"top": 0, "right": 0.1, "bottom": 0.1, "left": 0.1},
                           "padding": {"top": 1.2, "right": 1, "bottom": 1.2, "left": 1}}}


# ── Chain of Custody ──────────────────────────────────────────────────────

COC_FIELDS = [
    ("coc_id", "CoC number", "COC-DEMO-0001"),
    ("client", "Client", "DEMO Client"),
    ("contact", "Contact", "DEMO contact"),
    ("contact_phone", "Contact phone", "000-000-0000"),
    ("contact_email", "Contact email", "client@example.org"),
    ("project", "Project", "DEMO project"),
    ("project_number", "Project number", "P-DEMO"),
    ("sampler", "Sampled by", "DEMO sampler"),
    ("carrier", "Carrier", "DEMO courier"),
    ("tracking", "Tracking number", "TRK-DEMO"),
    ("custody_seals", "Custody seal numbers", "SEAL-DEMO-1"),
    ("received_by", "Received by (lab)", "AN1"),
    ("received_at", "Received at", "2026-10-06 09:30"),
    ("receipt_temp", "Temperature on receipt", "DEMO 4.0 °C"),
    ("receipt_thermometer", "Receipt thermometer", "DEMO thermometer"),
    ("seals_intact", "Seals intact", "Yes"),
    ("labels_legible", "Labels legible", "Yes"),
    ("holding_time_ok", "Holding times OK", "Yes"),
    ("condition_notes", "Condition on receipt", "DEMO: received intact"),
    ("printed", "Printed", "2026-10-06 10:00 UTC"),
    ("relinquished_line", "Relinquished (electronic)", "DEMO sampler, 2026-10-05 12:00, signed in"),
    ("receipt_flags", "Receipt flags", "DEMO: received not compliant"),
    ("transcription", "Transcription note",
     "DEMO: transcribed from paper CoC COC-DEMO-0001 by AN1 on 2026-10-07. Paper original retained."),
]
COC_TABLES = {
    "samples": [("sample_id", "Lab sample ID", "DEMO-0001"),
                ("client_sid", "Client sample ID", "DEMO-001"),
                ("sampling_point", "Sampling point", "DEMO point"),
                ("matrix", "Matrix", "Drinking Water"),
                ("sampled", "Collected (date, time)", "2026-10-05 08:15"),
                ("containers", "Containers", "2 x 250 mL HDPE"),
                ("preservative", "Preservative", "DEMO preservative"),
                ("analyses", "Analyses requested", "EPA 537.1"),
                ("homogenisation", "Homogenisation", "Not homogenised"),
                ("composite", "Composite", "")],
    "field_qc": [("qc_id", "Field QC ID", "FRB-DEMO-1"),
                 ("qc_type", "Type", "Field reagent blank"),
                 ("goes_with", "Goes with sample", "DEMO-001")],
    "transfers": [("relinquished_by", "Relinquished by", "DEMO sampler"),
                  ("relinquished_at", "Date, time", "2026-10-05 12:00"),
                  ("received_by", "Received by", "DEMO courier"),
                  ("received_at", "Date, time", "2026-10-05 12:05")],
}
COC_ORDER = ("samples", "field_qc", "transfers")
COC_REQUIRED = ("coc_id", "client", "sampler", "received_by", "received_at", "receipt_temp",
                "seals_intact", "holding_time_ok", "condition_notes")
COC_LONG = ("condition_notes", "receipt_flags", "transcription", "relinquished_line")
COC_GROUPS = _df.grouped(COC_FIELDS + _df.LAB_FIELDS, dict(
    [(k, _df.LAB) for k, _t2, _e in _df.LAB_FIELDS] + [
        ("coc_id", _df.DOCUMENT), ("printed", _df.DOCUMENT),
        ("client", _df.SAMPLE), ("contact", _df.SAMPLE), ("contact_phone", _df.SAMPLE),
        ("contact_email", _df.SAMPLE), ("project", _df.SAMPLE), ("project_number", _df.SAMPLE),
        ("sampler", _df.SAMPLE), ("carrier", _df.TRACE), ("tracking", _df.TRACE),
        ("custody_seals", _df.TRACE), ("received_by", _df.TRACE), ("received_at", _df.TRACE),
        ("receipt_temp", _df.TRACE), ("receipt_thermometer", _df.TRACE),
        ("seals_intact", _df.TRACE), ("labels_legible", _df.TRACE),
        ("holding_time_ok", _df.TRACE), ("condition_notes", _df.DEVIATIONS),
        ("relinquished_line", _df.TRACE), ("receipt_flags", _df.DEVIATIONS),
        ("transcription", _df.DOCUMENT)]))


def coc_starter(width=210.0, height=297.0):
    """A one-shipment CoC: laboratory and CoC number on every page, the
    client block, the samples table, field QC, custody transfers, the receipt
    block and blank signature lines (wet ink at each handoff)."""
    every = {"pfasEveryPage": True}
    right, wide = width - 10.0, width - 20.0
    out = [
        _image("lab_logo", 10, 8, 24, 14, **every),
        _t("lab_name", 37, 8, 90, 6, 12, **every),
        _t("lab_address", 37, 14, 90, 4.5, 7, **every),
        _t("lab_phone", 37, 18.5, 40, 4.5, 7, **every),
        _t("lab_email", 78, 18.5, 49, 4.5, 7, **every),
        _fixed("title", "Chain of Custody", right - 70, 8, 70, 7, 13, "right", **every),
        _fixed("label_coc_id", "CoC number", right - 70, 16, 25, 5, **every),
        _t("coc_id", right - 45, 16, 45, 5, 9, "right", **every),
        dict({"name": "coc_id (2)", "type": "code128", "position": {"x": right - 45, "y": 21},
              "width": 45, "height": 6, "content": ""}, **every),
        _rule("header_rule", 10, 28, wide, **every),
    ]
    pairs = [("Client", "client", "Project", "project"),
             ("Contact", "contact", "Project number", "project_number"),
             ("Phone", "contact_phone", "Sampled by", "sampler"),
             ("Email", "contact_email", "Carrier", "carrier"),
             ("Custody seals", "custody_seals", "Tracking number", "tracking")]
    y = 31.0
    for i, (l1, k1, l2, k2) in enumerate(pairs):
        yy = y + i * 5.5
        out += [_fixed("label_" + k1, l1, 10, yy, 25, 5), _t(k1, 35, yy, 65, 5),
                _fixed("label_" + k2, l2, 105, yy, 28, 5), _t(k2, 133, yy, right - 133, 5)]
    y += 5 * 5.5 + 3
    out.append(_fixed("heading_samples", "Samples", 10, y, wide, 5, 9))
    out.append(_table("samples", COC_TABLES["samples"], 10, y + 6, wide,
                      [10, 11, 11, 9, 11, 10, 9, 10, 10, 9]))
    y += 22
    out.append(_fixed("heading_field_qc", "Field quality control", 10, y, wide, 5, 9))
    out.append(_table("field_qc", COC_TABLES["field_qc"], 10, y + 6, wide, [30, 35, 35]))
    y += 22
    out.append(_fixed("heading_transfers", "Custody transfers", 10, y, wide, 5, 9))
    out.append(_table("transfers", COC_TABLES["transfers"], 10, y + 6, wide, [30, 20, 30, 20]))
    y += 24
    out.append(_fixed("heading_receipt", "Receipt at the laboratory", 10, y, wide, 5, 9))
    y += 6
    receipt = [("Received by", "received_by", "Received at", "received_at"),
               ("Temperature", "receipt_temp", "Thermometer", "receipt_thermometer"),
               ("Seals intact", "seals_intact", "Labels legible", "labels_legible"),
               ("Holding times OK", "holding_time_ok", "Printed", "printed")]
    for i, (l1, k1, l2, k2) in enumerate(receipt):
        yy = y + i * 5.5
        out += [_fixed("label_r_" + k1, l1, 10, yy, 28, 5), _t(k1, 38, yy, 62, 5),
                _fixed("label_r_" + k2, l2, 105, yy, 28, 5), _t(k2, 133, yy, right - 133, 5)]
    y += 4 * 5.5 + 1
    out += [_fixed("label_condition_notes", "Condition on receipt", 10, y, wide, 5),
            _t("condition_notes", 10, y + 5, wide, 5, 7.5, overflow="expand")]
    y += 11
    for key in ("receipt_flags", "relinquished_line", "transcription"):
        out.append(_t(key, 10, y, wide, 5, 7.5, overflow="expand"))
        y += 6
    y += 2
    for i, who in enumerate(("Sampler signature", "Received by signature")):
        x = 10 + i * (wide / 2.0)
        out += [_rule("sign_line_%d" % i, x, y + 8, wide / 2.0 - 8),
                _fixed("label_sign_%d" % i, who, x, y + 9, wide / 2.0 - 8, 4.5, 7)]
    out.append(dict(_fixed("pager", "Page {currentPage} of {totalPages}", right - 50,
                           height - 12, 50, 5, 7, "right"), **every))
    return {"basePdf": {"width": width, "height": height, "padding": [31, 10, 18, 10]},
            "schemas": [out]}


def _yes(v):
    return "Yes" if v in (True, "yes", "Yes", "on", 1) else ("No" if v in (False, "no", "No", 0) else _s(v))


def coc_data(record, samples, lab, printed):
    """`record`: the CoC record (the coc logbook entry, a dict); `samples`:
    one dict per sample with the sample_table keys (built from the sample
    records by the view); `lab`: the LAB_FIELDS values."""
    record = record or {}
    containers = {}
    for r in record.get("containers") or []:
        sid = (r.get("sample_id") or "").strip()
        if sid:
            containers.setdefault(sid, []).append(" ".join(
                x for x in (_s(r.get("container_type")), _s(r.get("volume_ml")) and
                            "%s mL" % _s(r.get("volume_ml"))) if x))
    rows = []
    for s in samples or []:
        row = dict((k, _s(s.get(k))) for k, _t2, _e in COC_TABLES["samples"])
        if not row["containers"]:
            row["containers"] = "; ".join(containers.get(row["client_sid"]) or
                                          containers.get(row["sample_id"]) or [])
        rows.append(row)
    temps = [_s(r.get("temp_c")) for r in record.get("containers") or [] if _s(r.get("temp_c"))]
    data = dict((k, _s(lab.get(k))) for k, _t2, _e in _df.LAB_FIELDS)
    data.update({
        "coc_id": _s(record.get("coc_id")), "client": _s(record.get("client_name")),
        "contact": _s(record.get("contact")), "contact_phone": _s(record.get("contact_phone")),
        "contact_email": _s(record.get("contact_email")),
        "project": _s(record.get("project_name")), "project_number": _s(record.get("project_number")),
        "sampler": _s(record.get("sampler_name")), "carrier": _s(record.get("carrier")),
        "tracking": _s(record.get("tracking_number")),
        "custody_seals": _s(record.get("custody_seal_numbers")),
        "received_by": _s(record.get("lab_received_by")),
        "received_at": _s(record.get("lab_received_date")),
        "receipt_temp": ", ".join("%s °C" % t for t in temps),
        "receipt_thermometer": _s(record.get("receipt_thermometer")),
        "seals_intact": _yes(record.get("seals_intact")),
        "labels_legible": _yes(record.get("labels_legible")),
        "holding_time_ok": _yes(record.get("holding_time_ok")),
        "condition_notes": _s(record.get("condition_notes")),
        "printed": _s(printed),
        # a CoC logbook from before CoC records has no electronic relinquish,
        # receipt flags or transcription
        "relinquished_line": "", "receipt_flags": "", "transcription": "",
        "samples": rows,
        "field_qc": [dict((k, _s(r.get(k))) for k, _t2, _e in COC_TABLES["field_qc"])
                     for r in record.get("field_qc") or [] if isinstance(r, dict)],
        "transfers": [dict((k, _s(r.get(k))) for k, _t2, _e in COC_TABLES["transfers"])
                      for r in record.get("transfers") or [] if isinstance(r, dict)],
    })
    return data


# ── Controlled document cover (EPA QA/G-6) ────────────────────────────────

SOP_FIELDS = [
    ("doc_id", "Document ID", "SOP-DEMO-001"),
    ("doc_title", "Title", "DEMO procedure"),
    ("doc_type", "Document type", "SOP"),
    ("method", "Method", "EPA 537.1"),
    ("revision", "Revision", "1"),
    ("effective", "Effective date", "2026-10-06"),
    ("status", "Status", "Active"),
    ("scope", "Scope", "DEMO: what this procedure covers"),
    ("controlled_copy", "Controlled copy number", "DEMO-CC-1"),
    ("printed", "Printed", "2026-10-06 10:00 UTC"),
]
SOP_TABLES = {
    "approvals": [("role", "Role", "Approved by"), ("name", "Name", "AN1"),
                  ("date", "Date", "2026-10-06"), ("signature", "Signature", "")],
    "history": [("revision", "Revision", "1"), ("date", "Date", "2026-10-06"),
                ("by", "By", "AN1"), ("summary", "Summary of changes", "DEMO first issue")],
}
SOP_ORDER = ("approvals", "history")
SOP_REQUIRED = ("doc_id", "doc_title", "revision", "effective")
SOP_LONG = ("scope",)
SOP_GROUPS = _df.grouped(SOP_FIELDS + _df.LAB_FIELDS, dict(
    [(k, _df.LAB) for k, _t2, _e in _df.LAB_FIELDS] +
    [(k, _df.DOCUMENT) for k, _t2, _e in SOP_FIELDS]))


def sop_starter(width=210.0, height=297.0):
    """G6 §3.1 title page, and the §2.5 control block (ID, revision, date,
    page x of y) top right on every page."""
    every = {"pfasEveryPage": True}
    right, wide = width - 10.0, width - 20.0
    out = [
        _fixed("label_h_id", "Document", right - 62, 8, 22, 4.5, 7, **every),
        _t("doc_id", right - 40, 8, 40, 4.5, 7, "right", **every),
        _fixed("label_h_rev", "Rev.", right - 62, 12.5, 22, 4.5, 7, **every),
        _t("revision", right - 40, 12.5, 40, 4.5, 7, "right", **every),
        _fixed("label_h_date", "Date", right - 62, 17, 22, 4.5, 7, **every),
        _t("effective", right - 40, 17, 40, 4.5, 7, "right", **every),
        dict(_fixed("pager", "Page {currentPage} of {totalPages}", right - 62, 21.5, 62, 4.5,
                    7, "right"), **every),
        _rule("header_rule", 10, 27, wide, **every),
        _image("lab_logo", 10, 34, 30, 18),
        _t("lab_name", 10, 54, wide, 7, 12),
        _t("lab_address", 10, 61, wide, 5, 8),
        _t("doc_type", 10, 78, wide, 6, 10),
        _t("doc_title", 10, 85, wide, 12, 18),
        _fixed("label_method", "Method", 10, 100, 30, 5), _t("method", 40, 100, 80, 5),
        _fixed("label_status", "Status", 10, 105.5, 30, 5), _t("status", 40, 105.5, 80, 5),
        _fixed("label_cc", "Controlled copy", 10, 111, 30, 5), _t("controlled_copy", 40, 111, 80, 5),
        _fixed("label_scope", "Scope", 10, 119, 30, 5),
        _t("scope", 10, 124, wide, 5, 8, overflow="expand"),
        _fixed("heading_approvals", "Approval", 10, 136, wide, 5, 9),
        _table("approvals", SOP_TABLES["approvals"], 10, 142, wide, [25, 30, 20, 25], 7),
        _fixed("heading_history", "Revision history", 10, 166, wide, 5, 9),
        _table("history", SOP_TABLES["history"], 10, 172, wide, [12, 18, 18, 52], 7),
        _fixed("label_printed", "Printed", 10, height - 12, 20, 4.5, 6.5, **every),
        _t("printed", 30, height - 12, 60, 4.5, 6.5, **every),
    ]
    return {"basePdf": {"width": width, "height": height, "padding": [30, 10, 18, 10]},
            "schemas": [out]}


def sop_data(entry, revisions, lab, printed, names=None):
    """From Controlled Documents: the registry `entry` and its `revisions`
    (as sop_documents stores them); `lab` the LAB_FIELDS values; `names`
    {user id: full name}. The revision shown is the one in force (active),
    else the newest. Approval = who prepared (uploaded) and who approved
    (activated) that revision; staff read-and-understood sign-offs are a
    training record, not an approval, and are not listed here."""
    entry, names = entry or {}, names or {}
    revs = [r for r in revisions or [] if isinstance(r, dict)]
    active = [r for r in revs if r.get("status") == "active"]
    cur = (active or revs or [{}])[-1]
    who = lambda u: _s(names.get(u) or u)                   # noqa: E731
    day = lambda v: _s(v)[:10]                              # noqa: E731
    approvals = [{"role": "Prepared by", "name": who(cur.get("uploaded_by")),
                  "date": day(cur.get("uploaded_at")), "signature": ""}]
    if cur.get("activated_by"):
        approvals.append({"role": "Approved by", "name": who(cur.get("activated_by")),
                          "date": day(cur.get("activated_at")), "signature": ""})
    data = dict((k, _s(lab.get(k))) for k, _t2, _e in _df.LAB_FIELDS)
    data.update({
        "doc_id": _s(entry.get("sop_id")), "doc_title": _s(entry.get("title")),
        "doc_type": _s(entry.get("doc_type")).upper(),
        "method": _s(entry.get("method_label")),
        "revision": _s(cur.get("rev_num")),
        "effective": day(cur.get("activated_at")),
        "status": _s(cur.get("status")).capitalize(),
        "scope": _s(entry.get("description")),
        "controlled_copy": "", "printed": _s(printed),
        "approvals": approvals,
        "history": [{"revision": _s(r.get("rev_num")),
                     "date": day(r.get("activated_at") or r.get("uploaded_at")),
                     "by": who(r.get("uploaded_by")), "summary": _s(r.get("release_notes"))}
                    for r in revs],
    })
    return data


# ── the CoC record's own fields (what no sample owns) ─────────────────────
# Added to the CoC logbook definition as a DRAFT revision for the lab to
# issue: field QC pairing (NMED SOP-01-ECP-2025: one field
# reagent blank per event, a field duplicate per 20 samples, each listed with
# the sample it goes with), custody seals, carrier and tracking (EPA SOP
# COC-01-08 receipt), and that the sampler signed.
COC_RECORD_FIELDS = [
    {"name": "custody_seal_numbers", "label": "Custody seal numbers", "type": "text",
     "correctable": True, "width": "md"},
    {"name": "carrier", "label": "Carrier", "type": "text", "correctable": True, "width": "md"},
    {"name": "tracking_number", "label": "Tracking number", "type": "text", "correctable": True,
     "width": "md"},
    {"name": "sampler_signed", "label": "Sampler signed the CoC", "type": "checkbox"},
    {"name": "field_qc", "label": "Field quality control", "type": "table", "default_rows": [],
     "columns": [{"name": "qc_id", "label": "Field QC ID", "type": "text"},
                 {"name": "qc_type", "label": "Type (field reagent blank, field duplicate, trip blank)",
                  "type": "text"},
                 {"name": "goes_with", "label": "Goes with sample", "type": "text"}]},
]


def add_coc_fields(schema):
    """(schema, changed): COC_RECORD_FIELDS after the custody transfers (or
    at the end), each only once."""
    schema = list(schema or [])
    have = set(f.get("name") for f in schema)
    add = [dict(f) for f in COC_RECORD_FIELDS if f["name"] not in have]
    if not add:
        return schema, False
    names = [f.get("name") for f in schema]
    at = names.index("transfers") + 1 if "transfers" in names else len(schema)
    return schema[:at] + add + schema[at:], True



BLANK_ROWS = 8           # a kit CoC: ruled empty rows for the sampler to fill in


def coc_record_data(record, samples, lab, printed):
    """The printed CoC from a CoC record (coc_records) and its samples
    (sample_row dicts). A record with no samples prints as a blank kit CoC:
    the number and client, BLANK_ROWS empty sample rows, empty receipt."""
    record = record or {}
    rc = record.get("receipt") or {}
    therm = rc.get("thermometer") or {}
    rows = [dict((k, _s(s.get(k))) for k, _t2, _e in COC_TABLES["samples"]) for s in samples or []]
    field_qc = [{"qc_id": r["client_sid"], "qc_type": _s(s.get("field_qc")),
                 "goes_with": _s(s.get("field_qc_of"))}
                for r, s in zip(rows, samples or []) if s.get("field_qc")]
    if not rows:
        rows = [dict((k, "") for k, _t2, _e in COC_TABLES["samples"]) for _i in range(BLANK_ROWS)]
        field_qc = [dict((k, "") for k, _t2, _e in COC_TABLES["field_qc"]) for _i in range(3)]
    readings = rc.get("readings") or []

    def temp(t):
        c = t.get("corrected")
        return "%s %s °C%s" % (_s(t.get("sample_id")), _s(t.get("observed")),
                               (" (corrected %s)" % c) if c is not None and _s(c) != _s(t.get("observed")) else "")
    def when(v):
        return _s(v)[:16].replace("T", " ")
    transfers = [dict((k, when(t.get(k)) if k.endswith("_at") else _s(t.get(k)))
                      for k, _t2, _e in COC_TABLES["transfers"])
                 for t in record.get("transfers") or []]
    first = (record.get("transfers") or [{}])[0] if record.get("transfers") else {}
    data = dict((k, _s(lab.get(k))) for k, _t2, _e in _df.LAB_FIELDS)
    data.update({
        "coc_id": _s(record.get("number")), "client": _s(record.get("client")),
        "contact": _s(record.get("contact")), "contact_phone": _s(record.get("contact_phone")),
        "contact_email": _s(record.get("contact_email")),
        "project": _s(record.get("project")), "project_number": _s(record.get("project_number")),
        "sampler": _s(record.get("sampler")), "carrier": _s(record.get("carrier")),
        "tracking": _s(record.get("tracking")), "custody_seals": _s(record.get("seals")),
        "received_by": _s(rc.get("received_by")), "received_at": _s(rc.get("received_at")),
        "receipt_temp": "; ".join(temp(t) for t in readings),
        "receipt_thermometer": " ".join(x for x in (_s(therm.get("name")), _s(therm.get("serial"))) if x),
        "seals_intact": _yes(rc.get("seals_intact")) if rc else "",
        "labels_legible": _yes(rc.get("labels_legible")) if rc else "",
        "holding_time_ok": _yes(rc.get("holding_time_ok")) if rc else "",
        "condition_notes": _s(rc.get("note")),
        "receipt_flags": ("Receipt flags: " + "; ".join(rc.get("flags"))) if rc.get("flags") else "",
        "relinquished_line": (("Relinquished electronically by %s on %s (signed in)"
                               % (_s(first.get("relinquished_by")), _s(first.get("relinquished_at"))[:16].replace("T", " ")))
                              if record.get("origin") != "paper" and first.get("relinquished_by") else ""),
        "transcription": _transcription(record),
        "printed": _s(printed),
        "samples": rows, "field_qc": field_qc,
        "transfers": transfers or [dict((k, "") for k, _t2, _e in COC_TABLES["transfers"]) for _i in range(3)],
    })
    return data


def _transcription(record):
    """One wording, coc_records.transcription_line."""
    try:
        from senaite.pfas import coc_records as cr
    except ImportError:                                     # loaded by path (tests)
        import coc_records as cr
    return cr.transcription_line(record)
