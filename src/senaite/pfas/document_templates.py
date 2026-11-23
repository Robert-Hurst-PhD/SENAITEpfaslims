# -*- coding: utf-8 -*-
"""Designed document templates (pdfme), as controlled revisions.

The lab draws a document in the Document Templates designer (pdfme, MIT,
vendored in static/vendor/pdfme). A template is a pdfme template JSON: a page
size and, per page, a list of fields, each with a position, a type (text,
barcode, line, image ...) and a name. A field is either FIXED content (the
lab's own text, logo, lines: pdfme's `readOnly`) or bound to a DATA FIELD of
its kind -- a label's lot, expiry, name -- by its name.

Labels print from the ISSUED revision, one label to a page of its stock.
The certificate's design is issued with the reporting-template revision
(report_templates.py).

    KINDS / LABEL_FIELDS / LABEL_SIZES
    base_key(field_name)          "lot (2)" -> "lot"
    validate(kind, template)      -> ["what is wrong", ...]
    inputs_for(kind, template, data) -> {field name: value} for pdfme
    blank(kind, size_id)          a new, empty template of that size
    fingerprint(template)
    new / save_draft / issue / archive / status    (on a plain dict store)

Pure apart from the storage shell at the end. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import hashlib
import json
import re

from senaite.pfas.print_style import PALETTE as _P

KEY = "senaite.pfas.document_templates"

# What a label can show, and the @@pfas-label URL parameter each comes from.
# (key, title, example used in the designer preview -- DEMO values only)
LABEL_FIELDS = [
    ("name", "Name", "DEMO PFAS mix in methanol"),
    ("lot", "Lot", "DEMO-LOT-0001"),
    ("conc", "Concentration", "100 ng/mL"),
    ("vol", "Volume", "10 mL"),
    ("exp", "Expiry", "2027-12-31"),
    ("exp_original", "Original expiry", "2027-06-30"),
    ("extended", "Extended", "ext."),
    ("date", "Prepared", "2026-10-04"),
    ("analyst", "Prepared by", "AN1"),
    ("method", "Method", "EPA 537.1"),
    ("storage", "Storage", "-20 °C, dark"),
]

# (id, title, width mm, height mm) -- the label stock the lab prints on
LABEL_SIZES = [
    ("2x1", '2" × 1" (tube/vial)', 50.8, 25.4),
    ("2x3", '2" × 3" (bottle)', 50.8, 76.2),
    ("4x2", '4" × 2" (larger bottle)', 101.6, 50.8),
    ("3x1", '3" × 1" (rack/tube)', 76.2, 25.4),
    ("4x3", '4" × 3" (bulk container)', 101.6, 76.2),
    ("89x28", "89 × 28 mm address", 89.0, 28.0),
    ("89x36", "89 × 36 mm large address", 89.0, 36.0),
    ("54x25", "54 × 25 mm multi-purpose", 54.0, 25.0),
    ("57x32", "57 × 32 mm multi-purpose", 57.0, 32.0),
    ("102x59", "102 × 59 mm shipping", 102.0, 59.0),
    ("25x25", "25 × 25 mm square", 25.0, 25.0),
    ("a4", "A4 full page (PDF archive)", 210.0, 297.0),
]

from senaite.pfas import coa_document as _coa                 # noqa: E402
from senaite.pfas import custody_documents as _cus            # noqa: E402
from senaite.pfas import doc_fields as _df                    # noqa: E402
from senaite.pfas import label_designs as _lab                # noqa: E402
from senaite.pfas import pdf_layout as _pl                    # noqa: E402
from senaite.pfas import report_documents as _rep             # noqa: E402

# A kind may also have TABLES: {table name: [(column key, title, example)]}.
# A table field named after one takes that table's rows; its columns are
# linked by key (pdfme keeps `pfasColumns` beside the header row).

# Tables a design may leave out: a design issued before the table existed
# keeps printing without it, and the Document Templates page says it is not
# placed.
OPTIONAL_TABLES = ("signatures",)


def _report_kind(title, single, fields, tables, order, required, long_fields, groups=None,
                 images=(), starter_fields=None, controlled=False):
    """A designable report: one design, issued here, every table but the
    optional ones required. Its fields are listed under the shared
    categories (doc_fields). No table of a report prints smaller than
    _rep.MIN_PT, whatever its design says. `controlled`: a record that
    carries the laboratory's name and address and the document control
    block; its starting layout places them, and a design that does not
    place them prints them at the foot of every page (_control_footer)."""
    own = list(starter_fields or fields)
    banner, foot = (), ()
    if controlled:
        have = set(k for k, _t, _e in own)
        own = [f for f in fields if f[0] in _rep.BANNER and f[0] not in have] + own
        banner, foot = _rep.BANNER, (_rep.CONTROL_FIELD[0],)
    return {"title": title, "fields": fields, "sizes": PAGE_SIZES, "tables": tables,
            "single": single, "required": required,
            "required_columns": dict((n, ()) for n in tables if n not in OPTIONAL_TABLES),
            "page_numbers": True, "min_table_pt": _rep.MIN_PT,
            "control_footer": tuple(banner + foot),
            "long": long_fields, "groups": groups, "images": tuple(images),
            "starter": lambda w, h: _rep.starter(title, own, tables, order, long_fields, w, h,
                                                 banner=banner, foot=foot)}


# labels: what is on the bottle (traceability), who made it, for which method
LABEL_GROUPS = _df.grouped(LABEL_FIELDS, {
    "name": _df.TRACE, "lot": _df.TRACE, "conc": _df.TRACE, "vol": _df.TRACE,
    "exp": _df.TRACE, "exp_original": _df.TRACE, "extended": _df.TRACE,
    "storage": _df.TRACE, "date": _df.PREPARER, "analyst": _df.PREPARER,
    "method": _df.ANALYSIS})

# An extraction batch member's label: one per container the method's Extraction labels list. The injection
# name is the LIMS-issued one the run will carry, so a barcode of it is what
# the instrument sequence and the result upload match on. DEMO values only.
EXTRACTION_LABEL_FIELDS = [
    ("injection", "Injection name", "WS-002-LFSM1"),
    ("container", "Container", "Centrifuge tube 1 of 2"),
    ("role", "QC type", "Matrix spike (LFSM)"),
    ("sample_id", "Sample", "DW-0012"),
    ("client_sid", "Client sample ID", "DEMO-001"),
    ("parent", "Made from", "DW-0012"),
    ("level", "Spike level", "Mid"),
    ("worksheet", "Worksheet", "WS-002"),
    ("batch", "Batch", "B-009"),
    ("matrix", "Matrix", "Drinking Water"),
    ("method", "Method", "EPA 537.1"),
    ("date", "Issued", "2026-10-06"),
    ("analyst", "Issued by", "AN1"),
]

EXTRACTION_LABEL_GROUPS = _df.grouped(EXTRACTION_LABEL_FIELDS, {
    "injection": _df.SAMPLE, "container": _df.SAMPLE, "sample_id": _df.SAMPLE,
    "client_sid": _df.SAMPLE, "matrix": _df.SAMPLE,
    "role": _df.QC, "parent": _df.QC, "level": _df.QC,
    "worksheet": _df.BATCH, "batch": _df.BATCH,
    "method": _df.ANALYSIS, "date": _df.PREPARER, "analyst": _df.PREPARER})

PAGE_SIZES = [("a4", "A4", 210.0, 297.0), ("letter", "US Letter", 215.9, 279.4)]

KINDS = {
    # a label kind keeps one design per stock size; each starts from the
    # layout drawn for that size (label_designs)
    "label": {"title": "Labels", "fields": LABEL_FIELDS, "sizes": LABEL_SIZES, "tables": {},
              "groups": LABEL_GROUPS, "starter": _lab.label_starter,
              "required": ("lot", "exp", "name"), "required_codes": ("lot",)},
    "extraction_label": {"title": "Extraction labels", "fields": EXTRACTION_LABEL_FIELDS,
                         "sizes": LABEL_SIZES, "tables": {}, "groups": EXTRACTION_LABEL_GROUPS,
                         "starter": _lab.extraction_label_starter,
                         "required": ("injection",), "required_codes": ("injection",)},
    # The certificate: one design, issued WITH the reporting-template revision
    # (report_templates), not on its own.
    "coa": {"title": "Certificate of Analysis", "fields": _coa.FIELDS, "sizes": PAGE_SIZES,
            # the Signatures table is optional (OPTIONAL_TABLES): not in
            # REQUIRED_COLUMNS, so a layout without it issues and prints
            "tables": {"results": _coa.RESULT_COLUMNS,
                       "qc_standards": _coa.QC_STANDARD_COLUMNS,
                       "signatures": _rep.SIGNATURES_TABLE}, "single": "certificate",
            "issued_with": "report_template",
            "required": _coa.REQUIRED_FIELDS, "required_columns": _coa.REQUIRED_COLUMNS,
            "page_numbers": True, "starter": _coa.starter,
            # no table heading or row prints smaller than _rep.MIN_PT,
            # whatever the issued design says
            "min_table_pt": _rep.MIN_PT,
            "groups": _coa.GROUPS, "images": _coa.IMAGES,
            "column_groups": {"results": _coa.RESULT_COLUMN_GROUPS},
            # what a layout issued earlier may still carry: a warning on
            # re-issue, never a refusal
            "retired_columns": _coa.RETIRED_COLUMNS, "heading_fields": _coa.HEADING_FIELDS,
            "column_aliases": _coa.COLUMN_ALIASES,
            # each heading must name its column; the designer links by it
            "headings_name_columns": True,
            # the designer's table chooser: columns ticked, headings, widths
            "column_defaults": {"results": _coa.RESULT_DEFAULT_COLUMNS},
            "column_headings": {"results": {"result": _coa.RESULT_HEADING}},
            "column_widths": {"results": _coa.RESULT_WIDTHS},
            "right_aligned": {"results": _coa.RIGHT_ALIGNED},
            # identifiers printed whole, on one line, in any layout issued
            "unbroken": _coa.UNBROKEN_COLUMNS,
            # paragraphs: added as text that grows and moves what follows down
            "long": ("note", "legend", "qc_standards_note", "qs_statement", "departures", "regulatory",
                     "accreditation", "qc_qualifications", "remarks", "interpretation"),
            # the sample block: a box grows with its text, in any layout
            # issued (compile_document)
            "grows": _coa.GROWING_FIELDS,
            # fields the certificate has gained: a layout without one issues
            # with a warning that names it
            "expected": _coa.EXPECTED_FIELDS},
    # the worksheet's record from receipt to release, printed by
    # @@pfas-extraction-pdf and a report package's batch record part
    "batch_record": _report_kind(
        "Batch record", "batch-record", _rep.BATCH_RECORD_FIELDS, _rep.BATCH_RECORD_TABLES,
        _rep.BATCH_RECORD_ORDER, _rep.BATCH_RECORD_REQUIRED, _rep.BATCH_RECORD_LONG,
        _rep.BATCH_RECORD_GROUPS, _rep.SIGNED_IMAGES, _rep.BATCH_RECORD_OWN, controlled=True),
    "qc_review": _report_kind(
        "QC Review Report", "qc-review", _rep.QC_FIELDS, _rep.QC_TABLES, _rep.QC_ORDER,
        _rep.QC_REQUIRED, ("qc_overall", "spike_pending", "unresolved", "not_run", "unplanned"),
        _rep.QC_GROUPS, _rep.SIGNED_IMAGES, _rep.QC_OWN, controlled=True),
    "preparation": _report_kind(
        "Preparation record", "preparation", _rep.PREPARATION_FIELDS, _rep.PREPARATION_TABLES,
        _rep.PREPARATION_ORDER, _rep.PREPARATION_REQUIRED,
        ("expiry_note", "equipment", "expired_parents", "extension"),
        _rep.PREPARATION_GROUPS, _rep.SIGNED_IMAGES, _rep.PREPARATION_OWN, controlled=True),
    # after published examples: a CoC from the sample records, an SOP cover per EPA QA/G-6
    "coc": {"title": "Chain of Custody", "fields": _cus.COC_FIELDS + _df.LAB_FIELDS,
            "sizes": PAGE_SIZES, "tables": _cus.COC_TABLES, "single": "chain-of-custody",
            "required": _cus.COC_REQUIRED,
            "required_columns": {"samples": ("sample_id", "client_sid", "matrix", "sampled",
                                             "analyses"),
                                 "field_qc": (), "transfers": ("relinquished_by", "relinquished_at",
                                                               "received_by", "received_at")},
            "page_numbers": True, "long": _cus.COC_LONG, "groups": _cus.COC_GROUPS,
            "control_footer": (_rep.CONTROL_FIELD[0],), "zone_in_control": True,
            "images": _df.LAB_IMAGES, "starter": _cus.coc_starter},
    "sop_cover": {"title": "Controlled document cover", "fields": _cus.SOP_FIELDS + _df.LAB_FIELDS,
                  "sizes": PAGE_SIZES, "tables": _cus.SOP_TABLES, "single": "controlled-document-cover",
                  "required": _cus.SOP_REQUIRED,
                  "required_columns": {"approvals": ("role", "name", "date"),
                                       "history": ("revision", "date")},
                  "page_numbers": True, "long": _cus.SOP_LONG, "groups": _cus.SOP_GROUPS,
                  "images": _df.LAB_IMAGES, "starter": _cus.sop_starter},
    "settings_report": _report_kind(
        "Settings Report", "settings-report", _rep.SETTINGS_FIELDS, _rep.SETTINGS_TABLES,
        _rep.SETTINGS_ORDER, _rep.SETTINGS_REQUIRED, ("methods", "unread_switches", "stale", "value_sources"),
        _rep.SETTINGS_GROUPS, controlled=True),
}
KINDS["settings_report"]["expected"] = _rep.SETTINGS_EXPECTED
# tables the batch record gained after designs were issued: a design issued
# before them still prints (missing_tables), and the next issue places them
KINDS["batch_record"]["later_tables"] = _rep.BATCH_RECORD_LATER_TABLES

# A field the designer marks "on every page" (letterhead, report number,
# "Page {currentPage} of {totalPages}") is moved into pdfme's repeating area
# when a document is compiled (compile_document).
EVERY_PAGE = "pfasEveryPage"
COLUMNS = "pfasColumns"
# A field placed beside a data-bound image (the laboratory's name beside its
# logo) names that image here: when the image prints empty, every field
# beside it moves left by one distance, so the leftmost takes the image's
# place and the block keeps its own arrangement (compile_document).
BESIDE = "pfasBeside"

# Field types the vendored bundle offers (tools/pdfme/entry.js).
PLUGIN_TYPES = ("text", "multiVariableText", "image", "svg", "table", "line",
                "rectangle", "ellipse", "date", "checkbox", "qrcode", "code128",
                "code39", "gs1datamatrix", "pdf417")
# Types whose value can come from a data field; anything else is fixed content.
# Not GS1 DataMatrix: it needs GS1 element strings ("(01)..."), and a plain lot
# number draws an empty square without any error.
# The types that draw a value as a code a scanner reads.
CODE_TYPES = ("qrcode", "code128", "code39", "pdf417")
BINDABLE = ("text", "multiVariableText", "qrcode", "code128", "code39", "pdf417", "table")
MAX_BYTES = 2 * 1024 * 1024          # images are embedded; keep a template small

# A second copy of a data field: "lot (2)" from the + buttons, "lot copy" /
# "lot copy 2" from pdfme's copy-paste. The designer script uses the same
# pattern (COPY_PATTERN there; test_document_templates checks they agree).
COPY_PATTERN = r"( \(\d+\)| copy( \d+)?)+$"
_COPY = re.compile(COPY_PATTERN)


def base_key(name):
    """The data field a template field shows."""
    return _COPY.sub("", name or "")


def field_keys(kind):
    return [k for k, _t, _e in KINDS[kind]["fields"]]


def tables(kind):
    return KINDS[kind].get("tables") or {}


def images(kind):
    """Fields whose value is a picture (a logo, a signature): bound to data
    as pdfme image fields."""
    return tuple(KINDS[kind].get("images") or ())


def groups(kind):
    """[(group title, [(key, title, example)])] as the designer lists the
    data fields; a kind without groups is one group."""
    return KINDS[kind].get("groups") or [(KINDS[kind]["title"], KINDS[kind]["fields"])]


EXAMPLE_ROWS = 22


def example_data(kind):
    data = dict((k, e) for k, _t, e in KINDS[kind]["fields"])
    if images(kind):
        ph = _coa.placeholder_png()
        for key in images(kind):
            data[key] = ph
    # enough rows that a table breaks across a page in the preview
    for name, cols in tables(kind).items():
        data[name] = [dict((k, e) for k, _t, e in cols) for _i in range(EXAMPLE_ROWS)]
    return data


def size_of(kind, size_id):
    for sid, title, w, h in KINDS[kind]["sizes"]:
        if sid == size_id:
            return {"id": sid, "title": title, "width": w, "height": h}
    return None


def offered_sizes(kind):
    """The sizes a kind is offered on: every size of the kind, less those
    where the layout drawn for that size (the kind's starter) cannot carry
    the fields the kind requires. A kind with no starter is offered all."""
    spec = KINDS[kind]
    starter = spec.get("starter")
    if starter is None or not (spec.get("required") or spec.get("required_codes")):
        return list(spec["sizes"])
    return [z for z in spec["sizes"] if not _required_problems(kind, starter(z[2], z[3]))]


def blank(kind, size_id):
    s = size_of(kind, size_id)
    if s is None:
        raise ValueError("unknown size %s" % size_id)
    return {"basePdf": {"width": s["width"], "height": s["height"], "padding": [0, 0, 0, 0]},
            "schemas": [[]]}


def _fields(template):
    for page in (template or {}).get("schemas") or []:
        for f in page or []:
            yield f


def _variables(field):
    """The data fields a 'Text with fields' uses: pdfme keeps them in
    `variables`; the text itself says {name}."""
    names = list(field.get("variables") or [])
    for m in re.findall(r"\{([^{}]+)\}", field.get("text") or ""):
        if m not in names:
            names.append(m)
    return names


def validate(kind, template):
    """Everything that would stop this template printing correctly, in words
    for the person who drew it. Empty list = fine."""
    if kind not in KINDS:
        return ["Unknown document kind %s." % kind]
    if not isinstance(template, dict):
        return ["The template is not a pdfme template."]
    out = []
    raw = json.dumps(template)
    if len(raw.encode("utf-8")) > MAX_BYTES:
        out.append("The template is larger than 2 MB: use smaller images.")
    base = template.get("basePdf")
    if not isinstance(base, dict):
        out.append("PDF page backgrounds are not available: use a blank page "
                   "and place the letterhead as an image.")
    else:
        try:
            w, h = float(base.get("width")), float(base.get("height"))
            if w <= 0 or h <= 0:
                raise ValueError
        except (TypeError, ValueError):
            out.append("The page has no size.")
    pages = template.get("schemas")
    if not isinstance(pages, list) or not pages:
        out.append("The template has no page.")
        return out
    keys = set(field_keys(kind))
    tabs = tables(kind)
    # an empty example ("no pedigree") would match every empty fixed shape
    examples = dict((e.strip(), t) for k, t, e in KINDS[kind]["fields"]
                    if e and e.strip() and k not in (KINDS[kind].get("heading_fields") or ()))
    seen = set()
    for f in _fields(template):
        name = f.get("name") or ""
        if not name:
            out.append("A field has no name.")
            continue
        if name in seen:
            out.append("Two fields are named %s." % name)
        seen.add(name)
        ftype = f.get("type")
        if ftype not in PLUGIN_TYPES:
            out.append("%s: field type %s is not available." % (name, ftype))
            continue
        if f.get(EVERY_PAGE) and ftype == "table":
            out.append("%s: a table cannot be on every page." % name)
        if ftype == "table" and not f.get("readOnly"):
            out.extend(_table_problems(kind, f, tabs))
            continue
        if f.get("readOnly"):
            # a data field that lost its name keeps the designer's example as
            # fixed text: every label would print that lot / expiry
            content = f.get("content")
            if (ftype in BINDABLE and ftype != "table" and hasattr(content, "strip")
                    and content.strip() in examples):
                out.append("%s is fixed text that reads %s, the designer's example %s: "
                           "name it after the data field, or type your own text."
                           % (name, content.strip(), examples[content.strip()].lower()))
            continue
        if ftype == "image" and base_key(name) in images(kind):
            continue                    # a logo / signature: bound to its picture
        if ftype == "image" and base_key(name) in keys:
            out.append("%s is a text field: place it as text, not a picture." % name)
        elif ftype not in BINDABLE:
            out.append("%s: a %s cannot show data; make it fixed content." % (name, ftype))
        elif ftype == "multiVariableText":
            for v in _variables(f):
                if v not in keys:
                    out.append("%s: {%s} is not a %s data field." % (name, v, KINDS[kind]["title"].lower()))
        elif base_key(name) not in keys:
            out.append("%s is not a %s data field (fixed text must be marked fixed)."
                       % (name, KINDS[kind]["title"].lower()))
    if (KINDS[kind].get("required") or KINDS[kind].get("required_codes")
            or KINDS[kind].get("page_numbers")):
        out.extend(_required_problems(kind, template))
    return out


def _bound_tables(template):
    """{table: the columns placed} of a template's data-bound tables."""
    columns = {}
    for f in _fields(template):
        if f.get("type") == "table" and not f.get("readOnly"):
            columns.setdefault(base_key(f.get("name")), set()).update(f.get(COLUMNS) or [])
    return columns


def missing_tables(kind, template):
    """The tables a kind requires (its required_columns, the tables the
    designer lists as required) that the template does not place, sorted:
    a design drawn before the kind had them. A table the kind gained after
    its designs were issued (its later_tables) is required at the next
    issue, never of a design already issued: that design prints without
    it."""
    placed = _bound_tables(template)
    later = KINDS[kind].get("later_tables") or ()
    return sorted(t for t in (KINDS[kind].get("required_columns") or {})
                  if t not in placed and t not in OPTIONAL_TABLES and t not in later)


def unplaced_optional(kind, template):
    """The optional tables of a kind (OPTIONAL_TABLES) the template does
    not place, sorted."""
    placed = _bound_tables(template)
    return sorted(t for t in tables(kind) if t in OPTIONAL_TABLES and t not in placed)


def _required_problems(kind, template):
    """What a kind must show before it may be issued (a certificate states
    everything today's certificate states, disclosures included)."""
    spec = KINDS[kind]
    bound, coded, numbered = set(), set(), False
    columns = _bound_tables(template)
    for f in _fields(template):
        if f.get("type") in CODE_TYPES and not f.get("readOnly"):
            # a code is read by a scanner, not by the person holding the
            # container: it does not stand for the value shown as text
            coded.add(base_key(f.get("name")))
            continue
        if f.get("readOnly"):
            c = f.get("content") or ""
            if f.get(EVERY_PAGE) and "{currentPage}" in c and "{totalPages}" in c:
                numbered = True
            continue
        if f.get("type") == "multiVariableText":
            bound.update(_variables(f))
        elif f.get("type") == "image" and base_key(f.get("name")) not in images(kind):
            continue
        elif f.get("type") == "table":
            continue
        else:
            bound.add(base_key(f.get("name")))
    titles = dict((k, t) for k, t, _e in spec["fields"])
    out = []
    for k in spec.get("required") or ():
        # a tuple: one part, shown by any of its fields
        either = k if isinstance(k, tuple) else (k,)
        if not any(x in bound for x in either):
            out.append("The %s must show %s." % (spec["title"], " or ".join(titles.get(x, x) for x in either)))
    for k in spec.get("required_codes") or ():
        if k not in coded:
            out.append("The %s must show a barcode or QR code of %s." % (spec["title"], titles.get(k, k)))
    for table, cols in sorted((spec.get("required_columns") or {}).items()):
        if table not in columns:
            out.append("The %s must have the %s table." % (spec["title"], table))
            continue
        ctitles = dict((k, t) for k, t, _e in tables(kind)[table])
        out.extend("The %s table must have the %s column." % (table, ctitles.get(c, c))
                   for c in cols if c not in columns[table])
    if spec.get("page_numbers") and not numbered:
        out.append("The %s must number its pages: fixed text on every page with "
                   "{currentPage} and {totalPages} (e.g. Page {currentPage} of {totalPages})."
                   % spec["title"])
    return out


_BRACED = re.compile(r"\{([^{}]*)\}")


def column_names(kind, table):
    """[(key, name, earlier)] a heading may name a column of a table by: its
    title, and any title it had before (earlier=True; a retired column's
    too)."""
    out = [(k, t, False) for k, t, _e in tables(kind).get(table) or []]
    for k, names in sorted(((KINDS[kind].get("column_aliases") or {}).get(table) or {}).items()):
        out.extend((k, n, True) for n in names)
    return out


def _named(kind, table, heading):
    """(present, earlier): the columns a heading names by their present
    title and by an earlier one, the longest name winning."""
    text = " ".join(_BRACED.sub(" ", "%s" % (heading or "")).lower().split())
    hits = [(len(n), k, old) for k, n, old in column_names(kind, table) if n and n.lower() in text]
    best = max([h for h, _k, _o in hits] or [0])
    present = sorted(set(k for h, k, old in hits if h == best and not old))
    earlier = sorted(set(k for h, k, old in hits if h == best and old) - set(present))
    return present, earlier


def columns_named(kind, table, heading):
    """The columns a heading names: those whose name the heading contains (a
    field in braces left out), the longest name winning; those named by
    their present title first. Several when columns share a title (a
    custody transfer's two "Date, time") or a title a column had before:
    the heading keeps the one it is linked to. The designer links a heading
    by the same rule."""
    present, earlier = _named(kind, table, heading)
    return present + earlier


def column_for(kind, table, heading):
    """The column a heading names when it is not linked yet: the one named
    by its present title, else by an earlier one; None when it names none,
    or several equally."""
    present, earlier = _named(kind, table, heading)
    if present:
        return present[0] if len(present) == 1 else None
    return earlier[0] if len(earlier) == 1 else None


def assign_columns(named, links):
    """The column each heading is linked to, given the columns each one
    names (named[i], present titles first) and the links it had: no column
    twice. A heading that names one column takes it; one that names several
    keeps its own link, else a link the table had (a column added or removed
    shifts them), else the first free column it names; none free leaves it
    unlinked. The designer relinks by the same rule (assignColumns)."""
    out = [None] * len(named)
    taken = set()
    for i, ks in enumerate(named):
        if len(ks) == 1 and ks[0] not in taken:
            out[i] = ks[0]
            taken.add(ks[0])
    for i, ks in enumerate(named):
        if len(ks) < 2:
            continue
        own = links[i] if len(links) == len(named) else None
        pick = own if own in ks and own not in taken else None
        pick = pick or next((k for k in links if k in ks and k not in taken), None)
        pick = pick or next((k for k in ks if k not in taken), None)
        if pick:
            out[i] = pick
            taken.add(pick)
    return out


def fill_headings(kind, template, data):
    """A table heading's {field} written in from the data ("Result
    {result_unit}" prints "Result ng/L"), in a kind whose headings name
    their columns (another kind prints its headings as drawn)."""
    if not KINDS.get(kind, {}).get("headings_name_columns"):
        return
    data = data or {}

    def fill(h):
        # a heading without a field prints exactly as drawn (line breaks too)
        if not _BRACED.search("%s" % h):
            return h
        return _BRACED.sub(lambda m: "%s" % (data.get(m.group(1).strip()) or ""), "%s" % h).strip()
    for f in _fields(template):
        if f.get("type") == "table" and not f.get("readOnly") and f.get("head"):
            f["head"] = [fill(h) for h in f["head"]]


def _table_problems(kind, f, tabs):
    name = f.get("name") or ""
    table = base_key(name)
    cols = dict((k, t) for k, t, _e in tabs.get(table) or [])
    if not cols:
        return ["%s is not a %s data table (a fixed table must be marked fixed)."
                % (name, KINDS[kind]["title"].lower())]
    head = f.get("head") or []
    keys = f.get(COLUMNS) or []
    if len(keys) != len(head):
        return ["%s: the columns are not linked to data (%d headings, %d links); "
                "re-add the table from the toolbar." % (name, len(head), len(keys))]
    out = []
    retired = (KINDS[kind].get("retired_columns") or {}).get(table) or {}
    fields = set(field_keys(kind))
    if KINDS[kind].get("headings_name_columns"):
        # two headings on one column print it twice and lose another
        seen = {}
        for title, key in zip(head, keys):
            if key and key in seen:
                out.append("%s: headings %s and %s are both linked to the %s column."
                           % (name, seen[key] or "(untitled)", title or "(untitled)", cols.get(key) or key))
            seen.setdefault(key, title)
    for title, key in zip(head, keys):
        if key not in cols and key not in retired:
            out.append("%s: column %s is not linked to a %s column (one of: %s)."
                       % (name, title or "(untitled)", table,
                          ", ".join(t for _k, t in sorted(cols.items()))))
            continue
        # the heading says which column it is: a stale link prints the
        # wrong column under it. Only where the kind says so: an issued
        # logbook that fails validation does not print.
        if not KINDS[kind].get("headings_name_columns"):
            continue
        for v in _BRACED.findall("%s" % (title or "")):
            # text only: a picture's data would print as characters
            if v.strip() not in fields or v.strip() in images(kind):
                out.append("%s: heading %s: {%s} is not a %s data field."
                           % (name, title, v, KINDS[kind]["title"].lower()))
        named = columns_named(kind, table, title)
        if not named:
            out.append("%s: heading %s names no %s column; it must contain the column's title "
                       "(one of: %s)." % (name, title or "(untitled)", table,
                                          ", ".join(t for _k, t in sorted(cols.items()))))
        elif key not in named:
            out.append("%s: heading %s is linked to the %s column." % (
                name, title or "(untitled)", cols.get(key) or key))
    return out


def warnings(kind, template):
    """What a layout issued earlier still carries that the kind has moved on
    from: issued with these, said once, never refused (validate does not
    count them)."""
    spec = KINDS.get(kind) or {}
    headings = dict((e.strip(), (k, t)) for k, t, e in spec.get("fields") or []
                    if k in (spec.get("heading_fields") or ()) and e and e.strip())
    retired = spec.get("retired_columns") or {}
    out = []
    for f in _fields(template):
        name = f.get("name") or ""
        if f.get("type") == "table" and not f.get("readOnly"):
            gone = retired.get(base_key(name)) or {}
            for title, key in zip(f.get("head") or [], f.get(COLUMNS) or []):
                if key in gone:
                    out.append("%s: the %s column still prints; %s. Remove it in the designer."
                               % (name, title or key, gone[key]))
            continue
        content = f.get("content")
        if f.get("readOnly") and hasattr(content, "strip") and content.strip() in headings:
            key, title = headings[content.strip()]
            out.append("%s reads %s as fixed text: replace it with the %s field, which "
                       "follows who signed." % (name, content.strip(), title.lower()))
    # a field the kind has gained since: the document is short of it until
    # the layout places it
    placed = set(base_key(f.get("name")) for f in _fields(template) if not f.get("readOnly"))
    placed |= set(v for f in _fields(template) if f.get("type") == "multiVariableText"
                  for v in _variables(f))
    titles = dict((k, t) for k, t, _e in spec.get("fields") or [])
    for key in spec.get("expected") or ():
        if key not in placed:
            out.append("The %s does not print %s: place the %s field."
                       % (spec.get("title") or kind, titles.get(key) or key, titles.get(key) or key))
    return out


def _field_text(value):
    """A bound value as the field's text; a byte string (a title read from
    core) decoded as UTF-8, never left to stop the document."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "%s" % (value,)


def inputs_for(kind, template, data):
    """pdfme's input for one document: every data-bound field -> its value."""
    data = data or {}
    out = {}
    pics = images(kind)
    for f in _fields(template):
        if f.get("readOnly"):
            continue
        name = f.get("name") or ""
        if f.get("type") == "image" and base_key(name) in pics:
            out[name] = data.get(base_key(name)) or ""
            continue
        if f.get("type") not in BINDABLE:
            continue
        if f.get("type") == "multiVariableText":
            out[name] = json.dumps(dict((v, _field_text(data.get(v) or "")) for v in _variables(f)))
        elif f.get("type") == "table":
            keys = f.get(COLUMNS) or []
            rows = data.get(base_key(name)) or []
            cells = [[_field_text(r.get(k) if r.get(k) is not None else "") for k in keys] for r in rows]
            if not cells and keys:
                # a table with no rows says so under its heading, never a
                # heading row alone
                cells = [[NONE_RECORDED] + [""] * (len(keys) - 1)]
            out[name] = json.dumps(cells)
        else:
            value = data.get(base_key(name)) or ""
            if isinstance(value, (list, tuple)):
                # a list of lines (a certificate's dilution notes): one per line
                value = "\n".join(_field_text(v) for v in value)
            out[name] = _field_text(value)
    return out


# what an empty table prints under its heading (report_documents)
NONE_RECORDED = _rep.NONE_RECORDED


# pdfme 6.2.2's table defaults (its table plugin's defaultSchema). The designer
# fills these in; compile_document fills whatever a template lacks, so a table
# placed without them (a starting layout, a scripted design) still renders.
TABLE_DEFAULTS = {
    "showHead": True,
    "tableStyles": {"borderColor": _P["s-body"], "borderWidth": 0.3},
    "headStyles": {"alignment": "left", "verticalAlignment": "middle", "fontSize": 13,
                   "lineHeight": 1, "characterSpacing": 0, "fontColor": _P["on-accent"],
                   "backgroundColor": _P["s-primary-dk"], "borderColor": "",
                   "borderWidth": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                   "padding": {"top": 5, "right": 5, "bottom": 5, "left": 5}},
    "bodyStyles": {"alignment": "left", "verticalAlignment": "middle", "fontSize": 13,
                   "lineHeight": 1, "characterSpacing": 0, "fontColor": _P["s-body"],
                   "backgroundColor": "", "borderColor": _P["s-input-border"],
                   "borderWidth": {"top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
                   "padding": {"top": 5, "right": 5, "bottom": 5, "left": 5},
                   "alternateBackgroundColor": _P["s-light"]},
    "columnStyles": {},
}


def _fill(target, defaults):
    for k, v in defaults.items():
        if k not in target:
            target[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(target[k], dict):
            _fill(target[k], v)


def _drop_hidden_columns(template, hidden):
    """A column this document's format hides (a certificate's CAS, MDL or
    dilution, per method x matrix) leaves its table; the others share its width."""
    for f in _fields(template):
        drop = set(hidden.get(base_key(f.get("name"))) or []) if f.get("type") == "table" else set()
        keys = f.get(COLUMNS) or []
        if not drop or not (set(keys) & drop):
            continue
        keep = [i for i, k in enumerate(keys) if k not in drop]
        widths = f.get("headWidthPercentages") or [100.0 / len(keys)] * len(keys)
        total = sum(widths[i] for i in keep) or 1.0
        f[COLUMNS] = [keys[i] for i in keep]
        f["head"] = [(f.get("head") or [])[i] for i in keep]
        f["headWidthPercentages"] = [widths[i] * 100.0 / total for i in keep]
        styles = f.get("columnStyles") or {}
        for prop, per_col in list(styles.items()):
            if isinstance(per_col, dict):
                styles[prop] = dict((str(n), per_col[str(i)]) for n, i in enumerate(keep)
                                    if str(i) in per_col)


def _with_footnote_marks(template, data):
    """data["_footnotes"] = {"field", "table", "column", "marks"}: each
    row's mark joins its cell only when the template prints the field the
    marks point to (a mark with no note under it says nothing)."""
    fn = (data or {}).get("_footnotes") or {}
    if not fn or not any(base_key(f.get("name")) == fn.get("field") and not f.get("readOnly")
                         for f in _fields(template)):
        return data
    data = dict(data)
    rows = [dict(r) for r in data.get(fn["table"]) or []]
    for r, mark in zip(rows, fn.get("marks") or []):
        if mark:
            r[fn["column"]] = "%s%s" % (r.get(fn["column"]) or "", mark)
    data[fn["table"]] = rows
    return data


# a fixed text that names a data field: its label, or a table's heading
_NAMING = ("label_", "heading_")


def subset_design(template, omit):
    """`template` without what shows the data fields in `omit`: a field
    bound to one, its label (label_<key>) and its heading (heading_<key>),
    and a text with fields when every field it uses is omitted. What shows
    no data field (the title, rules, page numbers, signatures) stays; a page
    the omission leaves with nothing but what prints on every page is
    dropped, its
    every-page fields moved to the first page kept. A copy: `template` is
    not changed."""
    omit = set(omit)

    def shows_omitted(f):
        name = f.get("name") or ""
        if f.get("readOnly"):
            for prefix in _NAMING:
                if name.startswith(prefix):
                    return base_key(name[len(prefix):]) in omit
            return False
        if f.get("type") == "multiVariableText":
            used = _variables(f)
            return bool(used) and all(v in omit for v in used)
        return base_key(name) in omit

    t = copy.deepcopy(template)
    pages, header = [], []
    for page in t.get("schemas") or []:
        kept = [f for f in page or [] if not shows_omitted(f)]
        if len(kept) < len(page or []) and all(f.get(EVERY_PAGE) for f in kept):
            # nothing of its own is left: the page goes, and what prints on
            # every page moves to the first page that keeps content
            header += kept
            continue
        pages.append(kept)
    if pages:
        pages[0] = header + pages[0]
    else:
        pages = [header]
    t["schemas"] = pages
    base = t.get("basePdf")
    if isinstance(base, dict) and base.get("staticSchema"):
        base["staticSchema"] = [f for f in base["staticSchema"] if not shows_omitted(f)]
    return t


def _fit_unbroken(kind, template, inputs):
    """Each column a kind keeps unbroken (KINDS[kind]["unbroken"]: {table:
    column keys}) made as wide as its longest value, in place
    (pdf_layout.unbroken_widths)."""
    unbroken = (KINDS.get(kind) or {}).get("unbroken") or {}
    for f in _fields(template):
        keys = f.get(COLUMNS) or []
        want = unbroken.get(base_key(f.get("name"))) if f.get("type") == "table" else None
        if not want or f.get("name") not in inputs:
            continue
        cols = [keys.index(k) for k in want if k in keys]
        try:
            rows = json.loads(inputs[f["name"]])
        except ValueError:
            continue
        widths = _pl.unbroken_widths(f, rows, cols)
        if widths:
            f["headWidthPercentages"] = widths


def _close_empty_images(kind, template, inputs):
    """The fields marked BESIDE an image of this kind moved left, in place,
    when that image is bound to data and prints empty: each by the distance
    from the image's left edge to the leftmost field beside it. A fixed
    image, a filled one, or one the template does not place moves nothing,
    and a field not marked never moves."""
    pics = images(kind)
    placed = dict((f.get("name"), f) for f in _fields(template)
                  if f.get("type") == "image" and not f.get("readOnly") and base_key(f.get("name")) in pics)
    beside = {}
    for f in _fields(template):
        ref = f.get(BESIDE)
        if ref and ref in placed and f.get("position"):
            beside.setdefault(ref, []).append(f)
    for ref, fields in beside.items():
        if inputs.get(ref):
            continue
        shift = min(f["position"]["x"] for f in fields) - placed[ref]["position"]["x"]
        if shift <= 0:
            continue
        for f in fields:
            f["position"] = dict(f["position"], x=f["position"]["x"] - shift)


# ── black and white ──────────────────────────────────────────────────────────

# a pdfme field's colours: its text, its fill, its rules (a table's styles
# carry the same keys per part)
TEXT_COLOURS = ("fontColor",)
FILL_COLOURS = ("backgroundColor", "alternateBackgroundColor")
RULE_COLOURS = ("borderColor",)
# the types whose "color" fills a shape, and the one whose "color" draws it
FILLED_SHAPES = ("rectangle", "ellipse")
INK, PAPER = _P["print-ink"], _P["print-paper"]


def _luminance(colour):
    """Relative luminance (0 black, 1 white) of a #rrggbb colour, None for
    anything else (an empty colour, a name pdfme does not read)."""
    c = (colour or "").strip()
    if len(c) != 7 or not c.startswith("#"):
        return None
    try:
        rgb = [int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    except ValueError:
        return None
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ink_or_paper(colour, kind):
    """The colour drawn in black and white. Text and a dark fill are ink, a
    light text (white on a band) and a light fill are paper, a rule is ink:
    the band stays a solid bar, a tint becomes white between its rules."""
    lum = _luminance(colour)
    if lum is None:
        return colour
    if kind == "rule":
        return INK
    return PAPER if lum > 0.5 else INK


def _recolour(node, kind_of_color):
    if isinstance(node, list):
        return [_recolour(v, kind_of_color) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in TEXT_COLOURS:
            out[k] = _ink_or_paper(v, "text")
        elif k in FILL_COLOURS:
            out[k] = _ink_or_paper(v, "fill")
        elif k in RULE_COLOURS:
            out[k] = _ink_or_paper(v, "rule")
        elif k == "color":
            out[k] = _ink_or_paper(v, kind_of_color(node))
        else:
            out[k] = _recolour(v, kind_of_color)
    return out


def monochrome(template):
    """A compiled document in black and white, for a client who takes its
    certificates so (Client reporting), and every designed document of its
    report package: the same fields in the same places with the same words,
    every colour ink or paper. Applied to the compiled template, so the
    design's fields, its repeating area and the footers the compiler adds
    all print alike; the issued design itself is never changed. Images are
    data, not layout: monochrome_document inks the signatures and greys the logo."""
    def kind_of_color(field):
        return "fill" if field.get("type") in FILLED_SHAPES else "rule"
    return _recolour(template, kind_of_color)


def _redrawn(uri, tone):
    """A PNG or JPEG data URI redrawn as a PNG data URI by tone(grey, alpha),
    which returns the grey levels to print; its transparency is kept.
    Anything else (empty, not a picture, an image the imaging library cannot
    read) comes back unchanged."""
    import base64
    import io
    head, sep, body = ("%s" % (uri or "")).partition(",")
    if not sep or not head.startswith("data:image/") or ";base64" not in head:
        return uri
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(base64.b64decode(body)))
        img.load()
        rgba = img.convert("RGBA")
        alpha = rgba.split()[3]
        grey = tone(rgba.convert("L"), alpha)
        out = Image.merge("LA", (grey, alpha)) if alpha.getextrema()[0] < 255 else grey
        buf = io.BytesIO()
        out.save(buf, "PNG")
    except Exception:                                       # noqa: BLE001
        return uri
    b64 = base64.b64encode(buf.getvalue())
    if not isinstance(b64, type(u"")):
        b64 = b64.decode("ascii")
    return "data:image/png;base64,%s" % b64


def ink_image(uri):
    """A picture redrawn in ink: grey levels only, the darkest stroke black,
    the paper white, soft edges the greys between, its transparency kept.
    Drawn for the print only: the stored image is never changed."""
    def tone(grey, alpha):
        from PIL import Image
        # the darkest mark the reader sees becomes black; white stays white
        seen = Image.composite(grey, Image.new("L", grey.size, 255), alpha.point(lambda a: 255 if a else 0))
        lo = seen.getextrema()[0]
        if lo < 255:
            grey = grey.point(lambda v: 0 if v <= lo else int(round(255.0 * (v - lo) / (255 - lo))))
        return grey
    return _redrawn(uri, tone)


def grey_image(uri):
    """A picture redrawn in greyscale: each colour as the grey of the same
    lightness, its tones and its transparency kept (ink_image stretches the
    tones to black and white). Drawn for the print only: the stored image
    is never changed."""
    return _redrawn(uri, lambda grey, alpha: grey)


def monochrome_document(kind, template, inputs):
    """(template, inputs) of a compiled document in black and white: the
    layout recoloured (monochrome), every signature image it prints in ink
    (ink_image) and the laboratory's logo in greyscale (grey_image). The
    inputs are a copy."""
    inked = dict(inputs or {})
    signatures = set(images(kind)) - set(_df.LAB_IMAGES)
    for name, value in inked.items():
        if not value:
            continue
        if base_key(name) in signatures:
            inked[name] = ink_image(value)
        elif base_key(name) in _df.LAB_IMAGES:
            inked[name] = grey_image(value)
    mono = monochrome(template)
    base = mono.get("basePdf")
    if isinstance(base, dict) and base.get("staticSchema"):
        # a logo set on every page is fixed content of the repeating area,
        # its picture written into the field
        fixed = [dict(f, content=grey_image(f["content"]))
                 if f.get("type") == "image" and base_key(f.get("name")) in _df.LAB_IMAGES and f.get("content")
                 else f for f in base["staticSchema"]]
        mono = dict(mono, basePdf=dict(base, staticSchema=fixed))
    return mono, inked


def compile_document(kind, template, data):
    """The template and input for ONE document: fields marked "on every page"
    move into pdfme's repeating area (basePdf.staticSchema) as fixed content,
    a data field's value written in. pdfme reads {...} in fixed text as a
    placeholder ({currentPage}, {totalPages}), so a VALUE containing braces is
    refused rather than evaluated. Returns (template, input)."""
    t = copy.deepcopy(template)
    floor = (KINDS.get(kind) or {}).get("min_table_pt")
    for f in _fields(t):
        if f.get("type") == "table":
            _fill(f, TABLE_DEFAULTS)
            if floor:
                _readable_table(f, floor)
    _drop_hidden_columns(t, (data or {}).get("_hidden_columns") or {})
    fill_headings(kind, t, data)
    data = _with_footnote_marks(t, data)
    inputs = inputs_for(kind, t, data)
    placed_note = _fill_times_note(t, inputs)
    _fit_unbroken(kind, t, inputs)
    _close_empty_images(kind, t, inputs)
    static = list((t.get("basePdf") or {}).get("staticSchema") or [])
    pages = []
    for page in t.get("schemas") or []:
        keep = []
        for f in page or []:
            if not f.get(EVERY_PAGE):
                keep.append(f)
                continue
            f = dict(f)
            name = f.get("name") or ""
            if name in inputs:
                value = inputs.pop(name)
                if f.get("type") == "multiVariableText":
                    filled = f.get("text") or ""
                    for k, v in json.loads(value).items():
                        if "{" in v or "}" in v:
                            raise ValueError("%s: the value of %s contains { or }" % (name, k))
                        filled = filled.replace("{%s}" % k, v)
                    f["type"], value = "text", filled
                elif "{" in value or "}" in value:
                    raise ValueError("%s: its value contains { or }" % name)
                f["content"] = value
            elif f.get("type") == "multiVariableText":
                f["type"], f["content"] = "text", f.get("text") or ""
            f["readOnly"] = True
            static.append(f)
        pages.append(keep)
    # a kind's short fields that must hold a long value (a certificate's
    # method name, a client's sample ID) grow with it, on a flowing page
    grows = (KINDS.get(kind) or {}).get("grows") or ()
    if grows and isinstance(t.get("basePdf"), dict):
        pages = [_pl.grow_text(page, inputs, lambda name: base_key(name) in grows) for page in pages]
    t["schemas"] = pages
    static += _control_footer(kind, t, data, static)
    if not (KINDS.get(kind) or {}).get("zone_in_control") and not placed_note:
        static += _times_footer(t, inputs, static)
    if static:
        t["basePdf"] = dict(t["basePdf"], staticSchema=static)
    # a table that breaks across pages takes the room its repeated heading
    # prints in, where it really breaks (pdf_layout)
    return _pl.settle(t, inputs), inputs


TIMES_FIELD = "times_zone"
# a data field a design places to say the zone once, where it chooses (a
# certificate's end); a design that places it prints no line on every page
TIMES_NOTE = "times_note"
CONTROL_FOOTER_FIELD = "control_footer"
# the smallest text a foot line prints
FOOT_PT = 7
# a control footer's line height (mm), the room it leaves the page number on
# its right, and the bottom margin a design must keep for it to fit
_FOOT_LINE, _FOOT_RIGHT, _FOOT_ROOM = 3.0, 55.0, 17.0


def _readable_table(field, floor):
    """A table's heading and body text raised to `floor` points when its
    design drew them smaller, and its heading repeated on every page it
    runs onto unless the design says otherwise. Text at or above the floor
    is left as drawn."""
    for part in ("headStyles", "bodyStyles"):
        style = field.get(part)
        if isinstance(style, dict):
            try:
                small = float(style.get("fontSize")) < floor
            except (TypeError, ValueError):
                small = False
            if small:
                style["fontSize"] = floor
    field.setdefault("repeatHead", True)


def _shown_keys(template, static):
    """The data fields a template shows anywhere: bound fields, the fields
    of a text with fields, and what is already in the repeating area."""
    shown = set()
    for f in list(_fields(template)) + list(static or []):
        if f.get("type") == "multiVariableText":
            shown.update(_variables(f))
        shown.add(base_key(f.get("name")))
    return shown


def shows(template, key):
    """True when a template shows the data field `key` somewhere."""
    return key in _shown_keys(template, (template.get("basePdf") or {}).get("staticSchema")
                              if isinstance((template or {}).get("basePdf"), dict) else ())


def _control_footer(kind, template, data, static):
    """[the control footer] of a controlled record (KINDS[kind]
    "control_footer": the laboratory's name and address, the document
    control block) whose design does not place those fields: they print as
    fixed text at the foot of every page, left of the page number and above
    the line that names the time zone, so a design issued before the record
    had them still carries them. A field the design places is left to the
    design; a design whose bottom margin has no room for the lines prints
    without them (it is refused at its next issue until it places them)."""
    keys = (KINDS.get(kind) or {}).get("control_footer") or ()
    base = template.get("basePdf")
    if not keys or not isinstance(base, dict):
        return []
    shown = _shown_keys(template, static)
    data = data or {}
    missing = [k for k in keys if k not in shown and ("%s" % (data.get(k) or "")).strip()]
    if not missing:
        return []
    lines = []
    lab = ", ".join(("%s" % data[k]).strip() for k in missing if k in _rep.BANNER)
    if lab:
        lines.append(lab)
    for k in missing:
        if k not in _rep.BANNER:
            lines.extend(l for l in ("%s" % data[k]).split("\n") if l.strip())
    pad = list(base.get("padding") or [0, 10, 0, 10]) + [10, 10, 10, 10]
    width, height = float(base.get("width") or 210.0), float(base.get("height") or 297.0)
    left, right, bottom = float(pad[3]), float(pad[1]), float(pad[2])
    if bottom < _FOOT_ROOM:
        return []
    text = "\n".join(lines)
    if "{" in text or "}" in text:
        raise ValueError("%s: its value contains { or }" % CONTROL_FOOTER_FIELD)
    tall = _FOOT_LINE * len(lines)
    return [{"name": CONTROL_FOOTER_FIELD, "type": "text",
             "position": {"x": left, "y": height - 7.0 - tall},
             "width": width - left - right - _FOOT_RIGHT, "height": tall, "fontSize": FOOT_PT,
             "lineHeight": 1, "alignment": "left", "verticalAlignment": "bottom", "readOnly": True,
             "content": text}]


def _fill_times_note(template, inputs):
    """Write the "Times are <zone>." line (print_doc.times_line, over every
    other value and fixed text the document prints) into each times_note
    field the design places, in place; True when it places one."""
    from senaite.pfas import print_doc
    notes = [n for n in inputs if base_key(n) == TIMES_NOTE]
    if not notes:
        return False
    base = template.get("basePdf")
    fixed = [f.get("content") for f in list(_fields(template)) + list(
        (base.get("staticSchema") if isinstance(base, dict) else None) or []) if f.get("readOnly")]
    line = print_doc.times_line(*([v for k, v in inputs.items() if base_key(k) != TIMES_NOTE] + fixed))
    for n in notes:
        inputs[n] = line
    return True


def _times_footer(template, inputs, static):
    """[the "Times are <zone>." line] for a document that prints a clock time
    (print_doc.times_line, over every value it prints), else []. It is fixed
    text on every page, in the bottom margin between the side margins, so it
    sits under whatever the design places; no field of the design moves. A
    kind whose control block names the zone (KINDS "zone_in_control", the
    custody documents) prints no such line."""
    from senaite.pfas import print_doc
    base = template.get("basePdf")
    if not isinstance(base, dict):
        return []
    shown = list(inputs.values()) + [f.get("content") for f in static]
    line = print_doc.times_line(*shown)
    if not line:
        return []
    pad = list(base.get("padding") or [0, 10, 0, 10]) + [10, 10, 10, 10]
    width, height = float(base.get("width") or 210.0), float(base.get("height") or 297.0)
    left, right = float(pad[3]), float(pad[1])
    return [{"name": TIMES_FIELD, "type": "text", "position": {"x": left, "y": height - 6.5},
             "width": width - left - right, "height": 3.5, "fontSize": FOOT_PT, "alignment": "left",
             "readOnly": True, "content": line}]


def byte_size(raw):
    """Size of a posted template. Under Python 2 a form value arrives as UTF-8
    bytes, and bytes.encode() would first decode them as ASCII and fail on
    a character such as a degree sign."""
    if raw is None:
        return 0
    if isinstance(raw, bytes):
        return len(raw)
    return len(raw.encode("utf-8"))


def script_json(value, **kw):
    """JSON to place inside a <script> element: no <, > or & can end the
    element or open a comment (label values come from the URL; logbook, reagent and chart data are
    typed by users). Every view that writes JSON into a page uses this."""
    return (json.dumps(value, **kw).replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


def fingerprint(template):
    raw = json.dumps(template or {}, sort_keys=True)
    if not isinstance(raw, bytes):
        raw = raw.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# ── the store: {template id: entry} ────────────────────────────────────────

def _slug(title, taken):
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-") or "template"
    tid, n = base, 2
    while tid in taken:
        tid, n = "%s-%d" % (base, n), n + 1
    return tid


def new(store, kind, title, size_id, who, when):
    """A new template with an empty draft; returns its id."""
    if kind not in KINDS:
        raise ValueError("unknown kind %s" % kind)
    title = (title or "").strip()
    if not title:
        raise ValueError("A template needs a name.")
    if size_id not in [z[0] for z in offered_sizes(kind)]:
        raise ValueError("The %s is not offered on this size." % KINDS[kind]["title"])
    single = KINDS[kind].get("single")
    if single and single in store:
        raise ValueError("There is already a %s design." % KINDS[kind]["title"])
    tid = single or _slug(title, store)
    store[tid] = {"id": tid, "kind": kind, "title": title, "size": size_id,
                  "draft": blank(kind, size_id), "draft_by": who, "draft_at": when,
                  "revisions": [], "archived": False}
    return tid


def save_draft(store, tid, template, who, when):
    """Replace the draft. Saved even when it has problems (work in progress);
    the problems are returned, and issuing refuses them."""
    entry = store[tid]
    entry["draft"] = copy.deepcopy(template)
    entry["draft_by"], entry["draft_at"] = who, when
    return validate(entry["kind"], template)


def current(entry):
    revs = sorted((entry or {}).get("revisions") or [], key=lambda r: r.get("rev", 0))
    return revs[-1] if revs else None


def status(entry):
    cur = current(entry)
    return {"rev": cur["rev"] if cur else None,
            "issued_at": (cur or {}).get("issued_at") or "",
            "issued_by": (cur or {}).get("issued_by") or "",
            "none_issued": cur is None,
            "unissued": cur is None or cur.get("fingerprint") != fingerprint(entry.get("draft"))}


def issue(store, tid, who, when, note):
    """Issue the draft as the next revision. Returns (record, problems): a
    record when issued, else None and why not."""
    entry = store[tid]
    if KINDS[entry["kind"]].get("issued_with"):
        return None, ["The %s is issued with the Reporting Template." % KINDS[entry["kind"]]["title"]]
    note = (note or "").strip()
    if not note:
        return None, ["Say what this revision changes."]
    if not [f for f in _fields(entry.get("draft"))]:
        return None, ["The template is empty."]
    problems = validate(entry["kind"], entry.get("draft"))
    if problems:
        return None, problems
    cur = current(entry)
    fp = fingerprint(entry.get("draft"))
    if cur and cur.get("fingerprint") == fp:
        return None, ["Nothing to issue: the draft is the issued revision."]
    rec = {"rev": (cur or {}).get("rev", 0) + 1, "issued_at": when, "issued_by": who,
           "note": note, "fingerprint": fp, "template": copy.deepcopy(entry["draft"])}
    entry.setdefault("revisions", []).append(rec)
    return rec, []


def issued_design(store, kind):
    """The issued design of a single-design kind (a report), or None: the
    report then prints its built-in layout."""
    single = KINDS[kind].get("single")
    entry = store.get(single) if single else None
    if not entry or entry.get("archived") or entry.get("kind") != kind:
        return None
    cur = current(entry)
    return cur["template"] if cur else None


def issued(store, kind):
    """[(entry, current revision)] of every live template of a kind that has
    an issued revision -- what a document may be printed from."""
    out = []
    for tid in sorted(store):
        e = store[tid]
        cur = current(e)
        if e.get("kind") == kind and not e.get("archived") and cur:
            out.append((e, cur))
    return out


def choose(designs, design_id=None, size_id=None):
    """The one design to print from, of a kind that keeps several (a label
    for each stock size): `designs` as issued() lists them. The design
    asked for by id; else the only one of the size asked for; else the only
    one issued. None when the person has to choose, or nothing is issued."""
    for entry, rev in designs:
        if design_id and entry.get("id") == design_id:
            return entry, rev
    sized = [d for d in designs if size_id and d[0].get("size") == size_id]
    if len(sized) == 1:
        return sized[0]
    return designs[0] if len(designs) == 1 else None


# ── storage shell (portal annotations, JSON) ───────────────────────────────
#
# One annotation per template (a certificate or logbook layout embeds its
# images, so one string for the whole store would be rewritten on every save
# of any template), plus an index of ids. A store kept as one string under
# KEY is still read, and the first save moves it across (load_from / save_to
# are tested on a plain dict).

INDEX_KEY = KEY + ".index"
ENTRY_PREFIX = KEY + ".t."


def load_from(ann):
    store = {}
    try:
        legacy = json.loads(ann.get(KEY) or "{}")
    except (TypeError, ValueError):
        legacy = {}
    if isinstance(legacy, dict):
        store.update(legacy)
    try:
        ids = json.loads(ann.get(INDEX_KEY) or "[]")
    except (TypeError, ValueError):
        ids = []
    for tid in ids:
        raw = ann.get(ENTRY_PREFIX + tid)
        if raw:
            try:
                store[tid] = json.loads(raw)
            except (TypeError, ValueError):
                pass
    return store


def save_to(ann, store):
    """Write the templates that changed, the index, and retire the legacy
    single string once everything in it has its own annotation."""
    for tid in sorted(store):
        raw = json.dumps(store[tid], sort_keys=True)
        if ann.get(ENTRY_PREFIX + tid) != raw:
            ann[ENTRY_PREFIX + tid] = raw
    try:
        old_ids = json.loads(ann.get(INDEX_KEY) or "[]")
    except (TypeError, ValueError):
        old_ids = []
    for tid in old_ids:
        if tid not in store and (ENTRY_PREFIX + tid) in ann:
            del ann[ENTRY_PREFIX + tid]
    index = json.dumps(sorted(store))
    if ann.get(INDEX_KEY) != index:
        ann[INDEX_KEY] = index
    if KEY in ann:
        del ann[KEY]


def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def load(portal):
    return load_from(_ann(portal))


def save(portal, store):
    save_to(_ann(portal), store)
