# -*- coding: utf-8 -*-
"""Value provenance, the reading side: a value's record, the imported rows
it was computed from and the lines of the export they were read from.

The worker records (pfas_pipeline/provenance.py) at compute time into
value_provenance; a QC row or an injection row carries the record's key in
prov_key. Data Review opens a key in a drawer. Read-only on every store.

Python 2.7 (in-Plone add-on); the worker never imports this.
"""
from __future__ import absolute_import, unicode_literals

import io
import json
import logging
import os
import sqlite3

logger = logging.getLogger("senaite.pfas.provenance_store")

DEFAULT_DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
# the exports the worker read (run_builder.UPLOAD_DIR); a record names a
# file by its base name only, never a path
UPLOAD_DIR = os.environ.get("PFAS_INSTRUMENT_UPLOAD_DIR", "/addon/data/instrument_output")

# a term's source names the row's field; the export's own column for it is
# the canonical name (instrument_columns.NATIVE_COLUMN_MAP) through the run's
# import layout
FIELD_TO_CANONICAL = {
    "calc_conc": "Calculated Concentration", "calculated_conc": "Calculated Concentration",
    "measured_conc": "Measured Concentration", "rt": "Observed RT (min)",
    "observed_rt": "Observed RT (min)", "response": "Response", "is_response": "IS Response",
    "expected_conc": "Expected Concentration", "ion_ratios": "Ion Ratios",
    "expected_ion_ratios": "Expected Ion Ratios", "pct_recovery_is": "% Recovery (IS)",
    "reporting_limit": "Reporting Limit", "pct_deviation": "% Deviation",
}

NOT_RECORDED = ("No provenance recorded for this run: it was processed before values kept "
                "their terms. Reprocess the run to record them.")


def parse_key(key):
    """(kind, injection, analyte) of a key; the injection may itself hold a
    '|' (a concat id), so the kind is the first part and the analyte the last."""
    parts = (key or "").split("|")
    if len(parts) < 3:
        return (parts[0] if parts else "", "", "")
    return parts[0], "|".join(parts[1:-1]), parts[-1]


class ProvenanceStore(object):

    def __init__(self, db_path=None, upload_dir=None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.upload_dir = upload_dir or UPLOAD_DIR

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _load(row):
        if row is None:
            return None
        d = dict(row)
        for k in ("terms_json", "steps_json", "rule_json"):
            try:
                d[k[:-5]] = json.loads(d.pop(k) or ("[]" if k != "rule_json" else "{}"))
            except (TypeError, ValueError):
                d[k[:-5]] = [] if k != "rule_json" else {}
        return d

    def count(self, batch_id):
        conn = self._connect()
        try:
            if not conn.execute("SELECT name FROM sqlite_master WHERE name='value_provenance'").fetchone():
                return 0
            return conn.execute("SELECT count(*) FROM value_provenance WHERE batch_id=?",
                                (batch_id,)).fetchone()[0]
        finally:
            conn.close()

    def get(self, batch_id, key):
        """The record for a key: exact, else the same kind and analyte on the
        injection whose concat id starts with the key's injection (a page
        that knows the injection name but not its acquisition time)."""
        kind, inj, an = parse_key(key)
        conn = self._connect()
        try:
            if not conn.execute("SELECT name FROM sqlite_master WHERE name='value_provenance'").fetchone():
                return None
            row = conn.execute("SELECT * FROM value_provenance WHERE batch_id=? AND key=?",
                               (batch_id, key)).fetchone()
            if row is None and kind and an:
                row = conn.execute(
                    "SELECT * FROM value_provenance WHERE batch_id=? AND kind=? AND analyte=? "
                    "AND (injection=? OR injection LIKE ?) ORDER BY injection LIMIT 1",
                    (batch_id, kind, an, inj, inj + "|%")).fetchone()
            if row is None and kind == "RESULT" and "-" in an:
                # an isomer component (br-PFOS) is reported under its summed
                # name: that record cites the component's row
                summed = an.split("-", 1)[1]
                row = conn.execute(
                    "SELECT * FROM value_provenance WHERE batch_id=? AND kind='RESULT' AND analyte=? "
                    "AND injection=? LIMIT 1", (batch_id, summed, inj)).fetchone()
            return self._load(row)
        finally:
            conn.close()

    def run_files(self, batch_id):
        """{file name: {layout, map}} as the run recorded them (kind RUN)."""
        conn = self._connect()
        out = {}
        try:
            if not conn.execute("SELECT name FROM sqlite_master WHERE name='value_provenance'").fetchone():
                return out
            for row in conn.execute("SELECT * FROM value_provenance WHERE batch_id=? AND kind='RUN'",
                                    (batch_id,)):
                d = self._load(row)
                out[d.get("injection") or ""] = d.get("rule") or {}
        finally:
            conn.close()
        return out

    def injection_rows(self, batch_id, pairs):
        """The stored injection rows for (injection, compound) pairs."""
        pairs = [p for p in pairs if p and p[0]]
        if not pairs:
            return []
        conn = self._connect()
        try:
            out = []
            for inj, comp in sorted(set(pairs)):
                for row in conn.execute(
                        "SELECT * FROM injection_results WHERE batch_id=? AND injection_name=? AND analyte=?",
                        (batch_id, inj, comp or "")):
                    out.append(dict(row))
            return out
        finally:
            conn.close()

    def file_lines(self, name, lines):
        """{"file", "header", "lines": [{"line", "cells"}]} for the export
        lines a record cites; None when the file is not there any more."""
        base = os.path.basename(name or "")
        if not base or base != name:
            return None
        path = os.path.join(self.upload_dir, base)
        if not os.path.isfile(path):
            return None
        try:
            from senaite.pfas import import_layouts as L
        except ImportError:                                  # loaded by path (tests)
            import import_layouts as L
        with io.open(path, "rb") as fh:
            raw = fh.read()
        text = L.decode(raw)
        delim = L.sniff(text)
        recs, starts = L.records_lines(text, delim)
        by_line = dict((ln, rec) for rec, ln in zip(recs, starts))
        header_line = None
        wanted = sorted(set(int(x) for x in lines if x))
        for ln in wanted:
            # the header is the first non-blank record above the first cited line
            if header_line is None:
                for cand in sorted(k for k in by_line if k < ln):
                    if any((c or "").strip() for c in by_line[cand]):
                        header_line = cand
                        break
            break
        header = by_line.get(header_line) if header_line is not None else []
        return {"file": base, "delimiter": delim, "header_line": header_line, "header": header,
                "lines": [{"line": ln, "cells": by_line.get(ln) or []} for ln in wanted]}

    def bundle(self, batch_id, key):
        """Everything the drawer draws for one value."""
        rec = self.get(batch_id, key)
        if rec is None:
            return {"error": NOT_RECORDED if not self.count(batch_id) else
                    "No record for %s on %s." % (key, batch_id), "batch_id": batch_id, "key": key}
        files, pairs = {}, []
        for t in rec.get("terms") or []:
            srcs = [t.get("source") or {}]
            srcs += list((t.get("source") or {}).get("rows") or [])
            for s in srcs:
                if s.get("file") and s.get("line"):
                    files.setdefault(s["file"], set()).add(int(s["line"]))
                if s.get("injection"):
                    pairs.append((s.get("injection"), s.get("compound")))
        layouts = self.run_files(batch_id)
        out_files = []
        for name, lines in sorted(files.items()):
            fl = self.file_lines(name, lines)
            if fl is None:
                out_files.append({"file": name, "missing": True, "lines": sorted(lines)})
                continue
            fl["layout"] = layouts.get(name) or {}
            # which header column each term's field maps to, through the layout
            inverse = dict((v, k) for k, v in (fl["layout"].get("map") or {}).items())
            fl["columns"] = {}
            for field, canonical in FIELD_TO_CANONICAL.items():
                header = inverse.get(canonical) or canonical
                if header in fl["header"]:
                    fl["columns"][field] = fl["header"].index(header)
            out_files.append(fl)
        related = {}
        for t in rec.get("terms") or []:
            rk = (t.get("source") or {}).get("record")
            if rk:
                related[rk] = self.get(batch_id, rk)
        return {"batch_id": batch_id, "key": key, "record": rec, "files": out_files,
                "rows": self.injection_rows(batch_id, pairs), "related": related}
