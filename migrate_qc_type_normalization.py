# -*- coding: utf-8 -*-
"""
One-off migration: normalize QC-type text + method identifiers in the QC store.

Decisions (signed off):
  * LCS and LFB are the same QC type -> canonical name is LFB; merge LCS -> LFB.
  * The FDA method's two spellings (fda-32-pfas / FDA_32PFAS) are the same
    method -> merge onto the canonical id FDA_32PFAS.
  * QC-type text is uniform ALL-CAPS: Sample -> SAMPLE, Dup -> DUP,
    SolventBlank -> SOLVENT_BLANK.

Idempotent: re-running finds nothing left to change.
Non-destructive: renames/merges rows, deletes nothing. Back up the .db first.

Run:  docker exec senaite_pfas-senaite-1 python /addon/migrate_qc_type_normalization.py

Python 2.7 / 3 compatible (pure sqlite3).
"""
from __future__ import absolute_import, print_function

import os
import sqlite3

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")

# Canonical method-id spelling -> list of alias spellings to fold in.
# Canonical ids match method_profile_store.py method_id / rules.py labels.
METHOD_MERGES = {
    "FDA_32PFAS": ["fda-32-pfas"],
    "EPA_537_1":  ["EPA_537.1"],
}

# (method, qc_type) rows to DELETE — a QC type a method does not run.
# FDA (PFAS in food/feed) does not use LFB/LCS; it uses matrix spikes.
DELETE_METHOD_QC = [
    ("FDA_32PFAS", "LFB"),
]

# qc_type alias -> canonical (compared case-insensitively).
QC_TYPE_ALIASES = {
    "LCS":          "LFB",
    "SAMPLE":       "SAMPLE",
    "DUP":          "DUP",
    "SOLVENTBLANK": "SOLVENT_BLANK",
}


def _tables_with_column(conn, col):
    out = []
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % name)]
        if col in cols:
            out.append(name)
    return out


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    changed = {}

    # 1) Method-spelling merge across every table that carries a method column.
    for canonical, aliases in METHOD_MERGES.items():
        for tbl in _tables_with_column(conn, "method"):
            for alias in aliases:
                cur = conn.execute(
                    "UPDATE %s SET method=? WHERE method=?" % tbl,
                    (canonical, alias))
                if cur.rowcount:
                    changed["%s.method %s->%s" % (tbl, alias, canonical)] = cur.rowcount

    # 2) QC-type normalization across every table that carries a qc_type column.
    for tbl in _tables_with_column(conn, "qc_type"):
        # Uppercase everything first so casing is uniform.
        conn.execute("UPDATE %s SET qc_type=UPPER(qc_type) "
                     "WHERE qc_type <> UPPER(qc_type)" % tbl)
        # Then fold aliases to canonical.
        for alias, canonical in QC_TYPE_ALIASES.items():
            if alias == canonical:
                continue
            cur = conn.execute(
                "UPDATE %s SET qc_type=? WHERE UPPER(qc_type)=?" % tbl,
                (canonical, alias))
            if cur.rowcount:
                changed["%s.qc_type %s->%s" % (tbl, alias, canonical)] = cur.rowcount

    # 3) Delete rows for (method, qc_type) combinations a method does not run.
    for method, qc_type in DELETE_METHOD_QC:
        for tbl in _tables_with_column(conn, "qc_type"):
            if "method" not in [r[1] for r in
                                conn.execute("PRAGMA table_info(%s)" % tbl)]:
                continue
            cur = conn.execute(
                "DELETE FROM %s WHERE method=? AND qc_type=?" % tbl,
                (method, qc_type))
            if cur.rowcount:
                changed["DELETE %s %s/%s" % (tbl, method, qc_type)] = cur.rowcount

    conn.commit()

    print("=== migration changes ===")
    if changed:
        for k, v in sorted(changed.items()):
            print("  %-40s %d rows" % (k, v))
    else:
        print("  (nothing to change — already normalized)")

    print("\n=== resulting qc_results state ===")
    for r in conn.execute("SELECT method, COUNT(*) FROM qc_results "
                          "GROUP BY method"):
        print("  method %-14r %d" % (r[0], r[1]))
    for r in conn.execute("SELECT qc_type, COUNT(*) FROM qc_results "
                          "GROUP BY qc_type ORDER BY qc_type"):
        print("  qc_type %-10r %d" % (r[0], r[1]))
    print("  injection_results qc_types:",
          [r[0] for r in conn.execute(
              "SELECT DISTINCT qc_type FROM injection_results")])
    conn.close()


if __name__ == "__main__":
    run()
