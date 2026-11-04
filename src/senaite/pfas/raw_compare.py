# -*- coding: utf-8 -*-
"""Validation: a run imported both ways, from the instrument software's
export and from the raw data, compared peak by peak.

Only one side is reported: the export's under Vendor results and Validation,
the raw data's under LIMS integration. The other side's rows are kept apart
(the alt_results table, written by the worker) for this comparison.

    compare(vendor_rows, raw_rows, key=None)  one line per (injection, analyte):
        the two areas, retention times, concentrations and verdicts, the
        differences in %, and `disagree` when the verdicts differ or the peak
        is on one side only. `key` maps a name to its keyword (an export
        names "GenX (HFPO-DA)" where the raw run names "HFPODA").
    summary(lines)                            compared, disagreements, largest area difference
    to_csv(lines, run, method)                the validation record
    alt_rows(db_path, batch_id, side)         the side kept apart

Rows are injection_results-like dicts. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, division, unicode_literals

import json
import sqlite3

COLUMNS = [("injection", "Injection"), ("analyte", "Analyte"), ("vendor_area", "Vendor area"),
           ("raw_area", "Raw area"), ("area_pct", "Area difference %"), ("vendor_rt", "Vendor RT"),
           ("raw_rt", "Raw RT"), ("vendor_conc", "Vendor concentration"), ("raw_conc", "Raw concentration"),
           ("conc_pct", "Concentration difference %"), ("vendor_verdict", "Vendor verdict"),
           ("raw_verdict", "Raw verdict"), ("disagree", "Disagree")]


def verdict(row):
    if row is None:
        return u""
    if row.get("conc_qualifier") == u"N.D." or row.get("response") is None:
        return u"N.D."
    return u"fail" if row.get("passed") == 0 else u"pass"


def _pct(raw, vendor):
    if raw is None or vendor in (None, 0):
        return None
    return (raw - vendor) / vendor * 100.0


def _pairs(vendor_rows, raw_rows, key):
    """[(injection, analyte, vendor row, raw row)]: names that match exactly
    pair first; what is left pairs on its keyword only where that keyword is
    one name's on each side (lr-PFOS and the PFOS total share a keyword)."""
    def index(rows):
        out, order = {}, []                     # in the rows' order (a Python 2 dict has none)
        for r in rows or []:
            k = (r.get("injection_name"), r.get("analyte"))
            if k not in out:
                out[k] = r
                order.append(k)
        return out, order
    (vendor, v_order), (raw, r_order) = index(vendor_rows), index(raw_rows)
    pairs = [(k, vendor[k], raw.get(k)) for k in v_order]
    left_v = [k for k in v_order if k not in raw]
    left_r = [k for k in r_order if k not in vendor]

    def by_key(ks):
        out = {}
        for k in ks:
            out.setdefault((k[0], key(k[1]) or k[1]), []).append(k)
        return out
    kv, kr = by_key(left_v), by_key(left_r)
    matched = {}
    for kk, vs in kv.items():
        if len(vs) == 1 and len(kr.get(kk) or []) == 1:
            matched[vs[0]] = kr[kk][0]
    used = set(matched.values())
    out = []
    for k, v, r in pairs:
        if k in matched:
            out.append((k[0], key(k[1]) or k[1], v, raw[matched[k]]))   # named by its keyword
        else:
            out.append((k[0], k[1], v, r))
    out += [(k[0], k[1], None, raw[k]) for k in r_order if k not in vendor and k not in used]
    return out


def compare(vendor_rows, raw_rows, key=None):
    key = key or (lambda name: name)
    lines = []
    for inj, analyte, v, r in _pairs(vendor_rows, raw_rows, key):
        k = (inj, analyte)
        vv, rv = verdict(v), verdict(r)
        g = lambda row, f: row.get(f) if row is not None else None   # noqa: E731
        lines.append({"injection": k[0], "analyte": k[1],
                      "vendor_area": g(v, "response"), "raw_area": g(r, "response"),
                      "area_pct": _pct(g(r, "response"), g(v, "response")),
                      "vendor_rt": g(v, "rt"), "raw_rt": g(r, "rt"),
                      "vendor_conc": g(v, "calc_conc"), "raw_conc": g(r, "calc_conc"),
                      "conc_pct": _pct(g(r, "calc_conc"), g(v, "calc_conc")),
                      "vendor_verdict": vv, "raw_verdict": rv, "disagree": vv != rv})
    return lines


def summary(lines):
    pcts = [abs(l["area_pct"]) for l in lines if l["area_pct"] is not None]
    return {"compared": len(lines), "disagree": len([l for l in lines if l["disagree"]]),
            "max_area_pct": max(pcts) if pcts else None}


def _cell(v):
    if v is True or v is False:
        return u"yes" if v else u"no"
    if v is None:
        return u""
    if isinstance(v, float):
        return u"%.6g" % v
    text = u"%s" % v
    # a comma, a quote or a line break (LF or a bare CR) is quoted
    if any(c in text for c in u',"\n\r'):
        text = u'"%s"' % text.replace(u'"', u'""')
    return text


def to_csv(lines, run=u"", method=u""):
    out = [u",".join([u"Run", u"Method"] + [label for _k, label in COLUMNS])]
    for l in lines:
        out.append(u",".join([_cell(run), _cell(method)] + [_cell(l[k]) for k, _label in COLUMNS]))
    return u"\r\n".join(out) + u"\r\n"


def alt_rows(db_path, batch_id, side):
    try:
        conn = sqlite3.connect(db_path)
        try:
            got = conn.execute("SELECT data FROM alt_results WHERE batch_id=? AND side=? ORDER BY id",
                               (batch_id, side)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [json.loads(r[0]) for r in got]
