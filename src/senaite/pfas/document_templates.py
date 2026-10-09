# -*- coding: utf-8 -*-
"""Designed document templates (pdfme), as controlled revisions.

The lab draws a document in the Document Templates designer (pdfme, MIT,
vendored in static/vendor/pdfme). A template is a pdfme template JSON: a page
size and, per page, a list of fields, each with a position, a type (text,
barcode, line, image ...) and a name. A field is either FIXED content (the
lab's own text, logo, lines: pdfme's `readOnly`) or bound to a DATA FIELD of
its kind -- a label's lot, expiry, name -- by its name.

Phase 1: labels, generated and printed in the
browser from the ISSUED revision. Certificates, logbook PDFs and reports
follow with a server-side renderer; the certificate layout will join the
existing reporting-template revision (report_templates.py), not this store.

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

KEY = "senaite.pfas.document_templates"

# What a label can show, and the @@pfas-label URL parameter each comes from.
# (key, title, example used in the designer preview -- DEMO values only)
LABEL_FIELDS = [
    ("name", "Name", "DEMO PFAS mix in methanol"),
    ("lot", "Lot", "DEMO-LOT-0001"),
    ("conc", "Concentration", "100 ng/mL"),
    ("vol", "Volume", "10 mL"),
    ("exp", "Expiry", "2027-12-31"),
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
    ("a4", "A4 full page (PDF archive)", 210.0, 297.0),
]

# A kind may also have TABLES: {table name: [(column key, title, example)]}.
# A table field named after one takes that table's rows; its columns are
# linked by key (pdfme keeps `pfasColumns` beside the header row).
def _beside(name):
    """A sibling module, also when this file is loaded by path (tests)."""
    try:
        import importlib
        return importlib.import_module("senaite.pfas." + name)
    except ImportError:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
        try:
            import importlib.util as iu                     # Python 3
            spec = iu.spec_from_file_location("_dt_" + name, path)
            mod = iu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        except ImportError:                                 # Python 2
            import imp
            return imp.load_source("_dt_" + name, path)


_coa = _beside("coa_document")
_rep = _beside("report_documents")
_df = _beside("doc_fields")
_cus = _beside("custody_documents")


def _report_kind(title, single, fields, tables, order, required, long_fields, groups=None,
                 images=(), starter_fields=None):
    """A designable report: one design, issued here, every table required.
    Its fields are listed under the shared categories (doc_fields)."""
    own = starter_fields or fields
    return {"title": title, "fields": fields, "sizes": PAGE_SIZES, "tables": tables,
            "single": single, "required": required,
            "required_columns": dict((n, ()) for n in tables), "page_numbers": True,
            "long": long_fields, "groups": groups, "images": tuple(images),
            "starter": lambda w, h: _rep.starter(title, own, tables, order, long_fields, w, h)}


# labels: what is on the bottle (traceability), who made it, for which method
LABEL_GROUPS = _df.grouped(LABEL_FIELDS, {
    "name": _df.TRACE, "lot": _df.TRACE, "conc": _df.TRACE, "vol": _df.TRACE,
    "exp": _df.TRACE, "storage": _df.TRACE, "date": _df.PREPARER, "analyst": _df.PREPARER,
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
    "label": {"title": "Labels", "fields": LABEL_FIELDS, "sizes": LABEL_SIZES, "tables": {},
              "groups": LABEL_GROUPS},
    "extraction_label": {"title": "Extraction labels", "fields": EXTRACTION_LABEL_FIELDS,
                         "sizes": LABEL_SIZES, "tables": {}, "groups": EXTRACTION_LABEL_GROUPS},
    # The certificate: one design, issued WITH the reporting-template revision
    # (report_templates), not on its own.
    "coa": {"title": "Certificate of Analysis", "fields": _coa.FIELDS, "sizes": PAGE_SIZES,
            "tables": {"results": _coa.RESULT_COLUMNS,
                       "qc_standards": _coa.QC_STANDARD_COLUMNS}, "single": "certificate",
            "issued_with": "report_template",
            "required": _coa.REQUIRED_FIELDS, "required_columns": _coa.REQUIRED_COLUMNS,
            "page_numbers": True, "starter": _coa.starter,
            "groups": _coa.GROUPS, "images": _coa.IMAGES,
            "column_groups": {"results": _coa.RESULT_COLUMN_GROUPS},
            # paragraphs: added as text that grows and moves what follows down
            "long": ("note", "legend", "qc_standards_note", "qs_statement", "departures", "regulatory",
                     "accreditation", "qc_qualifications", "remarks", "interpretation")},
    "extraction_log": _report_kind(
        "Extraction Log", "extraction-log", _rep.EXTRACTION_FIELDS, _rep.EXTRACTION_TABLES,
        _rep.EXTRACTION_ORDER, _rep.EXTRACTION_REQUIRED, ("warnings", "deviations", "pedigree"),
        _rep.EXTRACTION_GROUPS, _rep.SIGNED_IMAGES, _rep.EXTRACTION_OWN),
    "qc_review": _report_kind(
        "QC Review Report", "qc-review", _rep.QC_FIELDS, _rep.QC_TABLES, _rep.QC_ORDER,
        _rep.QC_REQUIRED, ("qc_overall", "spike_pending", "unresolved", "not_run", "unplanned"),
        _rep.QC_GROUPS, _rep.SIGNED_IMAGES, _rep.QC_OWN),
    # after published examples: a CoC from the sample records, an SOP cover per EPA QA/G-6
    "coc": {"title": "Chain of Custody", "fields": _cus.COC_FIELDS + _df.LAB_FIELDS,
            "sizes": PAGE_SIZES, "tables": _cus.COC_TABLES, "single": "chain-of-custody",
            "required": _cus.COC_REQUIRED,
            "required_columns": {"samples": ("sample_id", "client_sid", "matrix", "sampled",
                                             "analyses"),
                                 "field_qc": (), "transfers": ("relinquished_by", "relinquished_at",
                                                               "received_by", "received_at")},
            "page_numbers": True, "long": _cus.COC_LONG, "groups": _cus.COC_GROUPS,
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
        _rep.SETTINGS_ORDER, _rep.SETTINGS_REQUIRED, ("methods", "unread_switches", "stale"),
        _rep.SETTINGS_GROUPS),
}

# A field the designer marks "on every page" (letterhead, report number,
# "Page {currentPage} of {totalPages}") is moved into pdfme's repeating area
# when a document is compiled (compile_document).
EVERY_PAGE = "pfasEveryPage"
COLUMNS = "pfasColumns"

# Field types the vendored bundle offers (tools/pdfme/entry.js).
PLUGIN_TYPES = ("text", "multiVariableText", "image", "svg", "table", "line",
                "rectangle", "ellipse", "date", "checkbox", "qrcode", "code128",
                "code39", "gs1datamatrix", "pdf417")
# Types whose value can come from a data field; anything else is fixed content.
# Not GS1 DataMatrix: it needs GS1 element strings ("(01)..."), and a plain lot
# number draws an empty square without any error (checked 2026-10-04).
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


def example_data(kind):
    data = dict((k, e) for k, _t, e in KINDS[kind]["fields"])
    if images(kind):
        ph = _coa.placeholder_png()
        for key in images(kind):
            data[key] = ph
    for name, cols in tables(kind).items():
        data[name] = [dict((k, e) for k, _t, e in cols) for _i in range(3)]
    return data


def size_of(kind, size_id):
    for sid, title, w, h in KINDS[kind]["sizes"]:
        if sid == size_id:
            return {"id": sid, "title": title, "width": w, "height": h}
    return None


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
    examples = dict((e.strip(), t) for _k, t, e in KINDS[kind]["fields"] if e and e.strip())
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
    if KINDS[kind].get("required") or KINDS[kind].get("page_numbers"):
        out.extend(_required_problems(kind, template))
    return out


def _required_problems(kind, template):
    """What a kind must show before it may be issued (a certificate states
    everything today's certificate states, disclosures included)."""
    spec = KINDS[kind]
    bound, columns, numbered = set(), {}, False
    for f in _fields(template):
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
            columns.setdefault(base_key(f.get("name")), set()).update(f.get(COLUMNS) or [])
        else:
            bound.add(base_key(f.get("name")))
    titles = dict((k, t) for k, t, _e in spec["fields"])
    out = ["The %s must show %s." % (spec["title"], titles.get(k, k))
           for k in spec.get("required") or () if k not in bound]
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


def _table_problems(kind, f, tabs):
    name = f.get("name") or ""
    cols = dict((k, t) for k, t, _e in tabs.get(base_key(name)) or [])
    if not cols:
        return ["%s is not a %s data table (a fixed table must be marked fixed)."
                % (name, KINDS[kind]["title"].lower())]
    head = f.get("head") or []
    keys = f.get(COLUMNS) or []
    if len(keys) != len(head):
        return ["%s: the columns are not linked to data (%d headings, %d links); "
                "re-add the table from the toolbar." % (name, len(head), len(keys))]
    out = []
    for title, key in zip(head, keys):
        if key not in cols:
            out.append("%s: column %s is not linked to a %s column (one of: %s)."
                       % (name, title or "(untitled)", base_key(name),
                          ", ".join(t for _k, t in sorted(cols.items()))))
    return out


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
            out[name] = json.dumps(dict((v, "%s" % (data.get(v) or "")) for v in _variables(f)))
        elif f.get("type") == "table":
            keys = f.get(COLUMNS) or []
            rows = data.get(base_key(name)) or []
            out[name] = json.dumps([["%s" % (r.get(k) if r.get(k) is not None else "") for k in keys]
                                    for r in rows])
        else:
            out[name] = "%s" % (data.get(base_key(name)) or "")
    return out


# pdfme 6.2.2's table defaults (its table plugin's defaultSchema). The designer
# fills these in; compile_document fills whatever a template lacks, so a table
# placed without them (a starting layout, a scripted design) still renders.
TABLE_DEFAULTS = {
    "showHead": True,
    "tableStyles": {"borderColor": "#000000", "borderWidth": 0.3},
    "headStyles": {"alignment": "left", "verticalAlignment": "middle", "fontSize": 13,
                   "lineHeight": 1, "characterSpacing": 0, "fontColor": "#ffffff",
                   "backgroundColor": "#2980ba", "borderColor": "",
                   "borderWidth": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                   "padding": {"top": 5, "right": 5, "bottom": 5, "left": 5}},
    "bodyStyles": {"alignment": "left", "verticalAlignment": "middle", "fontSize": 13,
                   "lineHeight": 1, "characterSpacing": 0, "fontColor": "#000000",
                   "backgroundColor": "", "borderColor": "#888888",
                   "borderWidth": {"top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
                   "padding": {"top": 5, "right": 5, "bottom": 5, "left": 5},
                   "alternateBackgroundColor": "#f5f5f5"},
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


def compile_document(kind, template, data):
    """The template and input for ONE document: fields marked "on every page"
    move into pdfme's repeating area (basePdf.staticSchema) as fixed content,
    a data field's value written in. pdfme reads {...} in fixed text as a
    placeholder ({currentPage}, {totalPages}), so a VALUE containing braces is
    refused rather than evaluated. Returns (template, input)."""
    t = copy.deepcopy(template)
    for f in _fields(t):
        if f.get("type") == "table":
            _fill(f, TABLE_DEFAULTS)
    _drop_hidden_columns(t, (data or {}).get("_hidden_columns") or {})
    inputs = inputs_for(kind, t, data)
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
    t["schemas"] = pages
    if static:
        t["basePdf"] = dict(t["basePdf"], staticSchema=static)
    return t, inputs


def byte_size(raw):
    """Size of a posted template. Under Python 2 a form value arrives as UTF-8
    bytes, and bytes.encode() would first decode them as ASCII (a degree sign
    in a label's storage line once made every save fail)."""
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
    problems = validate(entry["kind"], entry.get("draft"))
    if problems:
        return None, problems
    if not [f for f in _fields(entry.get("draft"))]:
        return None, ["The template is empty."]
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
    report then prints as it always has."""
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


# ── storage shell (portal annotations, JSON) ───────────────────────────────
#
# One annotation per template (a certificate or logbook layout embeds its
# images, so one string for the whole store would be rewritten on every save
# of any template), plus an index of ids. The first layout kept
# the whole store in one string under KEY; it is still read, and the first
# save moves it across (load_from / save_to are tested on a plain dict).

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
