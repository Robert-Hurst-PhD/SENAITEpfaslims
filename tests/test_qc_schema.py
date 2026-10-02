# -*- coding: utf-8 -*-
"""The QC results database schema in ONE place (docs/REUSE_REVIEW.md U6):
senaite.pfas.qc_schema, used by the add-on store and every worker writer,
with numbered migrations in PRAGMA user_version."""
from __future__ import unicode_literals

import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "senaite", "pfas")
sys.path.insert(0, PKG)
sys.path.insert(0, ROOT)

import qc_schema as qs      # noqa: E402

PY3 = sys.version_info[0] >= 3


def _cols(conn, table):
    return set(r[1] for r in conn.execute("PRAGMA table_info(%s)" % table))


def test_a_fresh_database_gets_every_table_and_the_current_version():
    c = sqlite3.connect(":memory:")
    assert qs.ensure(c) == qs.VERSION == len(qs.MIGRATIONS)
    tables = set(r[0] for r in c.execute("select name from sqlite_master where type='table'"))
    assert {"batches", "qc_results", "calibrations", "calibration_levels",
            "injection_results", "chart_annotations"} <= tables
    assert {"qc_level", "units", "flag", "parent_result_id", "reanalysis_reason",
            "expected_value", "response_ratio"} <= _cols(c, "qc_results")
    assert c.execute("PRAGMA user_version").fetchone()[0] == qs.VERSION


def test_an_old_database_is_migrated_and_one_that_predates_numbering_is_left_alone():
    # a database from before the later columns: the shipped tables minus them
    old = sqlite3.connect(":memory:")
    inj = [t for t in qs.TABLES if "TABLE IF NOT EXISTS injection_results" in t][0]
    cal = [t for t in qs.TABLES if "TABLE IF NOT EXISTS calibrations" in t][0]
    old.execute("\n".join(l for l in inj.splitlines() if "conc_qualifier" not in l))
    old.execute(cal)
    assert "conc_qualifier" not in _cols(old, "injection_results")
    assert "approved_by" not in _cols(old, "calibrations")
    qs.ensure(old)
    assert "conc_qualifier" in _cols(old, "injection_results")
    assert {"approved_by", "weight_override", "origin_override"} <= _cols(old, "calibrations")
    pre = sqlite3.connect(":memory:")
    qs.ensure(pre)
    pre.execute("PRAGMA user_version = 0")                  # columns present, no number
    assert qs.ensure(pre) == qs.VERSION
    assert qs.ensure(pre) == qs.VERSION                     # idempotent


def test_a_migration_runs_exactly_once():
    """A future data migration (an UPDATE / INSERT) must not run twice."""
    saved = list(qs.MIGRATIONS), qs.VERSION
    try:
        qs.MIGRATIONS.append((qs.VERSION + 1, "INSERT INTO batches (batch_id, run_date, "
                              "created_at, updated_at) VALUES ('M-%d', 'd', 'n', 'n')" % (qs.VERSION + 1)))
        qs.VERSION = qs.MIGRATIONS[-1][0]
        c = sqlite3.connect(":memory:")
        qs.ensure(c)
        qs.ensure(c)
        assert c.execute("select count(*) from batches").fetchone()[0] == 1
    finally:
        qs.MIGRATIONS[:] = saved[0]
        qs.VERSION = saved[1]


def test_migrations_are_numbered_in_order():
    numbers = [n for n, _s in qs.MIGRATIONS]
    assert numbers == list(range(1, len(numbers) + 1))


def test_no_other_module_defines_these_tables():
    tables = ("batches", "qc_results", "calibrations", "calibration_levels",
              "injection_results", "chart_annotations")
    pat = re.compile(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(%s)\b" % "|".join(tables))
    hits = []
    for base in (PKG, os.path.join(ROOT, "pfas_pipeline")):
        for dirpath, _d, files in os.walk(base):
            for name in files:
                path = os.path.join(dirpath, name)
                if name.endswith(".py") and path != os.path.join(PKG, "qc_schema.py"):
                    with io.open(path, encoding="utf-8") as fh:
                        if pat.search(fh.read()):
                            hits.append(name)
    assert not hits, hits
    for rel in ("injection_store.py", "qc_store.py", "seed_calibrations.py"):
        with io.open(os.path.join(ROOT, "pfas_pipeline", rel), encoding="utf-8") as fh:
            assert 'load("qc_schema").ensure(conn)' in fh.read(), rel
    with io.open(os.path.join(PKG, "qc", "store.py"), encoding="utf-8") as fh:
        assert "qc_schema.ensure(conn)" in fh.read()


def test_the_seed_tool_works_on_a_fresh_database():
    """Its private schema lacked columns its own inserts use."""
    if not PY3:
        return
    from pfas_pipeline import seed_calibrations as sc
    tmp = tempfile.mkdtemp()
    try:
        conn = sc._connect(os.path.join(tmp, "qc.db"))
        sc.ensure_schema(conn)
        sc.seed(conn)
        assert conn.execute("select count(*) from qc_results").fetchone()[0] > 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == qs.VERSION
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as exc:
            failed += 1
            print("FAIL", name, exc)
    print("{0}/{1} passed".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
