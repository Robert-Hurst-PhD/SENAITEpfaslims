# -*- coding: utf-8 -*-
"""The certificate register as a download: one CSV line per issue, as the
register page lists them (@@pfas-controlled-publications?format=csv).

    csv_text(rows, shown) -> text    rows: the page's publications(); shown(stamp)
                                     a stored UTC stamp on the lab's clock

Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

COLUMNS = (("report_id", "Certificate ID"), ("sample_id", "Sample"), ("client", "Client"),
           ("revision", "Rev"), ("status", "Status"), ("interim", "Interim"),
           ("signed_by", "Signed by"), ("certificate_sha256", "Content sha256"),
           ("issued_at", "Issued"), ("email", "E-mail"), ("amendment", "Amendment"))

STATUS_WORDS = {"current": "Current", "superseded": "Superseded"}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return "%s" % (value,)


def csv_cell(value):
    """One CSV cell: quoted where it holds a comma, a quote or a line break;
    a cell a spreadsheet would run as a formula is opened with a quote."""
    text = _text(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    if any(c in text for c in (",", '"', "\r", "\n")):
        text = '"' + text.replace('"', '""') + '"'
    return text


def line(row, shown):
    """The register's columns of one issue, as the page words them."""
    signed = row.get("signed_by") or ("Not signed" if row.get("unsigned") else row.get("authorizer"))
    amendment = ("Reason not recorded" if row.get("reason_missing")
                 else row.get("amendment_reason") or "")
    out = dict(row)
    out.update(status=STATUS_WORDS.get(row.get("status"), row.get("status")),
               interim="Yes" if row.get("interim") else "No", signed_by=signed,
               issued_at=shown(row.get("issued_at")) if row.get("issued_at") else "",
               email=row.get("delivery_line") or row.get("recipients") or "",
               amendment=amendment)
    return [out.get(k) for k, _label in COLUMNS]


def csv_text(rows, shown):
    lines = [",".join(csv_cell(label) for _k, label in COLUMNS)]
    lines.extend(",".join(csv_cell(v) for v in line(r, shown)) for r in rows or [])
    return "\r\n".join(lines) + "\r\n"
