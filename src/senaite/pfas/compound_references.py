# -*- coding: utf-8 -*-
"""What references a compound: a rename or a deletion surfaces what points
at it. Pure: Python 2.7 and 3, no Zope imports."""
from __future__ import absolute_import, unicode_literals

import sqlite3

# profile keys that hold keyword references, and how
_LISTS = ("master_analyte_set", "project_extra_analytes", "key_analytes")
# nested keyword lists: (path, how it is named)
SINGLE_PATH = ("instrument_verification", "confirmation", "single_transition_analytes")
_NESTED_LISTS = ((SINGLE_PATH, ".".join(SINGLE_PATH)),)
_ROW_FIELDS = (("surrogate_map", ("analyte", "surrogate_is")),
               ("salt_adjustment_factors", ("analyte",)),
               ("eis_overrides", ("analyte",)), ("eis_matrix_overrides", ("analyte",)))
_KEYED = ("labelled_standards", "isomers", "analyte_matrix_inclusion")


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return [v.strip() for v in ("%s" % (value or "")).replace(";", ",").split(",") if v.strip()]


def _nested(profile, path):
    """(the dict holding the last key, the last key) along `path`, or (None,
    key) when a step is missing or not a dict."""
    node = profile
    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return None, path[-1]
    return node, path[-1]


def references(profiles, keyword):
    """[(method id, where)] for every place a method profile names `keyword`."""
    out = []
    for mid in sorted(profiles or {}):
        p = profiles[mid] or {}
        for key in _LISTS:
            if keyword in _as_list(p.get(key)):
                out.append((mid, key))
        for path, label in _NESTED_LISTS:
            holder, last = _nested(p, path)
            if holder is not None and keyword in _as_list(holder.get(last)):
                out.append((mid, label))
        for key, fields in _ROW_FIELDS:
            for row in p.get(key) or []:
                if any((row or {}).get(f) == keyword for f in fields):
                    out.append((mid, key))
                    break
        for key in _KEYED:
            table = p.get(key) if isinstance(p.get(key), dict) else {}
            if keyword in table:
                out.append((mid, key))
            elif key == "labelled_standards" and any((v or {}).get("reference") == keyword for v in table.values()):
                out.append((mid, key + ".reference"))
            elif key == "isomers" and any(keyword == (v or {}).get("linear") or keyword in ((v or {}).get("branched") or [])
                                          for v in table.values()):
                out.append((mid, key + ".peaks"))
        intg = (p.get("integration") or {}).get("analytes") or {}
        if keyword in intg:
            out.append((mid, "integration.analytes"))
        for matrix, limits in (p.get("reporting_limits") or {}).items():
            if keyword in (limits or {}):
                out.append((mid, "reporting_limits[%s]" % matrix))
        if keyword in _analyte_scale(p):
            out.append((mid, SCALE_PATH))
    return out


SCALE_PATH = "instrument_verification.calibration.analyte_scale"


def _analyte_scale(profile):
    """The per-analyte calibration range table, {} when absent."""
    scale = ((profile.get("instrument_verification") or {}).get("calibration") or {}).get("analyte_scale")
    return scale if isinstance(scale, dict) else {}


def remove(profile, keyword):
    """Take a native analyte out of every place a method profile names it:
    the panel, a project's extras, the key and single-transition lists, its
    surrogate, salt, isomer, inclusion, integration and reporting-limit
    rows. Returns [where] it was removed from, in that order."""
    p = profile
    out = []
    for key in _LISTS:
        value = p.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            if keyword in value:
                p[key] = [k for k in value if k != keyword]
                out.append(key)
        else:
            items = _as_list(value)
            if keyword in items:
                p[key] = ", ".join(k for k in items if k != keyword)
                out.append(key)
    for path, label in _NESTED_LISTS:
        holder, last = _nested(p, path)
        value = holder.get(last) if holder is not None else None
        if value is None:
            continue
        items = _as_list(value)
        if keyword in items:
            kept = [k for k in items if k != keyword]
            holder[last] = kept if isinstance(value, (list, tuple)) else ", ".join(kept)
            out.append(label)
    for key in ("surrogate_map", "salt_adjustment_factors"):
        rows = p.get(key)
        if isinstance(rows, list):
            kept = [r for r in rows if not (isinstance(r, dict) and r.get("analyte") == keyword)]
            if len(kept) != len(rows):
                p[key] = kept
                out.append(key)
        elif isinstance(rows, dict) and keyword in rows:
            rows.pop(keyword)
            out.append(key)
    for key in ("isomers", "analyte_matrix_inclusion"):
        table = p.get(key)
        if isinstance(table, dict) and keyword in table:
            table.pop(keyword)
            out.append(key)
    intg = (p.get("integration") or {}).get("analytes")
    if isinstance(intg, dict) and keyword in intg:
        intg.pop(keyword)
        out.append("integration.analytes")
    for matrix, limits in sorted((p.get("reporting_limits") or {}).items()):
        if isinstance(limits, dict) and keyword in limits:
            limits.pop(keyword)
            out.append("reporting_limits[%s]" % matrix)
    scale = _analyte_scale(p)
    if keyword in scale:
        scale.pop(keyword)
        out.append(SCALE_PATH)
    return out


def sqlite_counts(conn, names):
    """{table: rows} naming any of `names` in the QC store's analyte columns."""
    out = {}
    marks = ",".join("?" for _ in names)
    for table, column in (("injection_results", "analyte"), ("qc_results", "analyte"),
                          ("calibrations", "analyte"), ("result_pushes", "analyte")):
        try:
            n = conn.execute("SELECT COUNT(*) FROM %s WHERE %s IN (%s)" % (table, column, marks),
                             list(names)).fetchone()[0]
        except sqlite3.OperationalError as exc:
            # a store without that table holds no reference; any other
            # failure (locked, unreadable) must not read as "none"
            if "no such table" not in "%s" % exc:
                raise
            continue
        if n:
            out[table] = n
    return out
