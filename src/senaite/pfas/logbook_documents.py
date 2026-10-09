# -*- coding: utf-8 -*-
"""Designed batch logbooks.

A logbook's fields are its DEFINITION's (PrepLogbookDef field_schema_json,
the active revision), so its document kind is built from that definition:

    kind_id(slug) -> "logbook:<slug>"
    kind_spec(slug, title, form_code, revision, schema) -> a document kind
    data(schema, entry, header) -> one batch's logbook as that kind's data

Header fields (batch, form, definition revision, corrections) are prefixed
hdr_ so they cannot collide with a logbook's own field names (FM-ENV-003 has
its own "method"). Every field and every table column of the definition is
required in a design; a design drawn on an earlier revision that names a
field the active revision removed fails validation, so it is neither issued
nor printed (it would print blank). Rows struck as not applicable are kept,
marked N/A, as the form shows them; GLP corrections print as their own block.

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas import doc_fields as _df
except ImportError:                                         # loaded by path (tests)
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import doc_fields as _df

PREFIX = "logbook:"

HEADER = [
    ("hdr_batch", "Batch", "B-DEMO"),
    ("hdr_batch_title", "Batch title", "DEMO batch"),
    ("hdr_method", "Method", "EPA 537.1"),
    ("hdr_form", "Form", "FM-ENV-001"),
    ("hdr_title", "Logbook", "DEMO logbook"),
    ("hdr_revision", "Definition revision", "1"),
    ("hdr_corrections", "Corrections", "DEMO: Prepared By corrected from AN1 to AN2 by AN2 on 2026-10-05"),
]
HEADER_REQUIRED = ("hdr_batch", "hdr_form", "hdr_title", "hdr_revision", "hdr_corrections")

_EXAMPLE = {"text": "DEMO", "date": "2026-10-05", "number": "1.0", "textarea": "DEMO note",
            "checkbox": "Yes", "lot_ref": "DEMO-PS-1", "reagent_ref": "DEMO-LOT-1",
            "thermometer": "DEMO thermometer"}
NA_MARK = "N/A — "


# designer categories (doc_fields): the header's, and a logbook
# field's by its type -- a lot, reagent or thermometer reference is
# traceability -- or by the usual sign-off names; the rest are entries
_HEADER_CATEGORY = {"hdr_batch": _df.BATCH, "hdr_batch_title": _df.BATCH,
                    "hdr_method": _df.ANALYSIS, "hdr_form": _df.DOCUMENT,
                    "hdr_title": _df.DOCUMENT, "hdr_revision": _df.DOCUMENT,
                    "hdr_corrections": _df.DEVIATIONS}
_TYPE_CATEGORY = {"lot_ref": _df.TRACE, "reagent_ref": _df.TRACE, "thermometer": _df.TRACE}
_NAME_CATEGORY = {"prepared_by": _df.PREPARER, "prepared_date": _df.PREPARER,
                  "analyst": _df.PREPARER, "reviewed_by": _df.REVIEWER,
                  "reviewed_date": _df.REVIEWER, "notes": _df.DEVIATIONS}
SIGNED = _df.LAB_FIELDS + [f for _c, fs in _df.people() for f in fs]
SIGNED_IMAGES = _df.LAB_IMAGES + _df.people_images()


def category_of(field):
    """A logbook definition field's designer category."""
    return (_NAME_CATEGORY.get(field.get("name"))
            or _TYPE_CATEGORY.get(field.get("type")) or _df.ENTRIES)


def kind_id(slug):
    return PREFIX + slug


def _label(f):
    return f.get("label") or f.get("name") or ""


def kind_spec(slug, title, form_code, revision, schema, starter=None):
    """The document kind for one logbook definition. `starter`, when given,
    is report_documents.starter (passed in to keep this module standalone)."""
    fields, tables, order, long_fields = list(HEADER), {}, [], ["hdr_corrections"]
    for f in schema or []:
        name = f.get("name")
        if not name:
            continue
        if f.get("type") == "table":
            tables[name] = [(c.get("name"), c.get("label") or c.get("name"),
                             _EXAMPLE.get(c.get("type"), "DEMO"))
                            for c in f.get("columns") or [] if c.get("name")]
            order.append(name)
        else:
            fields.append((name, _label(f), _EXAMPLE.get(f.get("type"), "DEMO")))
            if f.get("type") == "textarea":
                long_fields.append(name)
    doc_title = ("%s %s" % (form_code or "", title or slug)).strip()
    # the laboratory and its signatories (offered, not required)
    own = list(fields)
    have = set(k for k, _t, _e in fields)
    assign = dict(_HEADER_CATEGORY)
    assign.update((f.get("name"), category_of(f)) for f in schema or [] if f.get("name"))
    assign.update((k, c) for c, fs in [(_df.LAB, _df.LAB_FIELDS)] + _df.people() for k, _t, _e in fs)
    fields = own + [f for f in SIGNED if f[0] not in have]
    spec = {"title": doc_title, "fields": fields, "tables": tables,
            "groups": _df.grouped(fields, assign), "images": SIGNED_IMAGES,
            "single": "logbook-%s" % slug, "logbook_slug": slug, "definition_revision": revision,
            "required": HEADER_REQUIRED + tuple(k for k, _t, _e in own[len(HEADER):]),
            "required_columns": dict((n, tuple(k for k, _t, _e in cols)) for n, cols in tables.items()),
            "page_numbers": True, "long": tuple(long_fields)}
    if starter is not None:
        spec["starter"] = lambda w, h: starter(doc_title, own, tables, order, tuple(long_fields), w, h)
    return spec


def _s(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, dict):                 # a frozen record (e.g. a thermometer)
        return ", ".join("%s: %s" % (k, v[k]) for k in sorted(v) if not k.startswith("_"))
    return "%s" % v


def _corrections(schema, entry):
    labels = dict((f.get("name"), _label(f)) for f in schema or [])
    out = []
    for name, rec in sorted((entry.get("_corrections") or {}).items()):
        if not isinstance(rec, dict):
            continue
        out.append("%s: corrected from %s to %s by %s on %s" % (
            labels.get(name, name), _s(rec.get("original")) or "(blank)",
            _s(entry.get(name)) or "(blank)", _s(rec.get("corrected_by")), _s(rec.get("corrected_at"))))
    return "\n".join(out)


def data(schema, entry, header):
    """One batch's logbook. `header`: {batch, batch_title, method, form,
    title, revision}."""
    entry = entry or {}
    out = {"hdr_batch": _s(header.get("batch")), "hdr_batch_title": _s(header.get("batch_title")),
           "hdr_method": _s(header.get("method")), "hdr_form": _s(header.get("form")),
           "hdr_title": _s(header.get("title")), "hdr_revision": _s(header.get("revision")),
           "hdr_corrections": _corrections(schema, entry)}
    for f in schema or []:
        name, ftype = f.get("name"), f.get("type")
        if not name:
            continue
        value = entry.get(name)
        if ftype == "table":
            cols = [c.get("name") for c in f.get("columns") or [] if c.get("name")]
            rows = []
            for r in value or []:
                if not isinstance(r, dict):
                    continue
                row = dict((c, _s(r.get(c))) for c in cols)
                if r.get("_na") and cols:
                    row[cols[0]] = NA_MARK + row[cols[0]]
                rows.append(row)
            out[name] = rows
        elif ftype == "checkbox":
            out[name] = "Yes" if value in (True, "on", "true", "1", 1, "yes", "Yes") else "No"
        else:
            out[name] = _s(value)
    return out
