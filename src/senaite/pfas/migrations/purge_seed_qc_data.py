# -*- coding: utf-8 -*-
"""
Migration: archive seeded/synthetic QC rows not connected to the live database.

  docker exec <container> bin/instance run \
    /addon/src/senaite/pfas/migrations/purge_seed_qc_data.py

The control-chart pool (/data/qc/pfas_qc_results.db) accumulated seed data:
TEST_DATA*-flagged rows, SYNTHETIC_* batches, and demo B0xxx batches that do
not correspond to any real SENAITE worksheet. This step MOVES (never deletes)
every qc_results/batches/calibrations row whose batch_id is not a real
worksheet id into *_archive tables in the same DB — fully reversible — so
charts and calibration reviews reflect only data connected to the live system.

Idempotent. Python 2.7 compatible (runs in the Plone container).
"""
from __future__ import absolute_import, print_function, unicode_literals

import sqlite3
import sys

DB = "/data/qc/pfas_qc_results.db"


def _get_portal():
    app = globals().get("app")
    portals = [o for o in app.objectValues("Plone Site")]
    if not portals:
        print("ERROR: no Plone site"); sys.exit(1)
    return portals[0]


def run():
    portal = _get_portal()
    from AccessControl.SecurityManagement import newSecurityManager
    from zope.component.hooks import setSite
    app = globals().get("app")
    admin = app.acl_users.getUserById("admin")
    newSecurityManager(None, admin.__of__(app.acl_users))
    setSite(portal)

    # Real worksheet ids from the live system — the connection test.
    real_ws = set()
    try:
        for ws in portal["worksheets"].objectValues():
            real_ws.add(ws.getId())
    except Exception as exc:
        print("WARN reading worksheets: {}".format(exc))
    print("Real worksheets: {}".format(sorted(real_ws)))
    if not real_ws:
        print("REFUSING: no real worksheets found — archiving everything "
              "would be destructive. Aborting.")
        sys.exit(1)

    placeholders = ",".join("?" * len(real_ws))
    ws_list = sorted(real_ws)

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    def archive(table, where_sql, params):
        c.execute("CREATE TABLE IF NOT EXISTS {t}_archive AS "
                  "SELECT * FROM {t} WHERE 0".format(t=table))
        c.execute("SELECT COUNT(*) FROM {t} WHERE {w}".format(t=table, w=where_sql),
                  params)
        n = c.fetchone()[0]
        if n:
            c.execute("INSERT INTO {t}_archive SELECT * FROM {t} WHERE {w}"
                      .format(t=table, w=where_sql), params)
            c.execute("DELETE FROM {t} WHERE {w}".format(t=table, w=where_sql),
                      params)
        print("  {t}: archived {n} row(s)".format(t=table, n=n))
        return n

    print("\nArchiving rows whose batch_id is not a real worksheet:")
    not_real = "batch_id NOT IN ({})".format(placeholders)
    archive("qc_results", not_real, ws_list)
    archive("batches", not_real, ws_list)
    # calibrations reference batch_id too; archive levels of archived cals first
    c.execute("CREATE TABLE IF NOT EXISTS calibration_levels_archive AS "
              "SELECT * FROM calibration_levels WHERE 0")
    c.execute("SELECT COUNT(*) FROM calibration_levels WHERE calibration_id IN "
              "(SELECT id FROM calibrations WHERE {})".format(not_real), ws_list)
    nlev = c.fetchone()[0]
    if nlev:
        c.execute("INSERT INTO calibration_levels_archive SELECT * FROM "
                  "calibration_levels WHERE calibration_id IN "
                  "(SELECT id FROM calibrations WHERE {})".format(not_real),
                  ws_list)
        c.execute("DELETE FROM calibration_levels WHERE calibration_id IN "
                  "(SELECT id FROM calibrations WHERE {})".format(not_real),
                  ws_list)
    print("  calibration_levels: archived {} row(s)".format(nlev))
    archive("calibrations", not_real, ws_list)

    conn.commit()
    for t in ("qc_results", "batches", "calibrations", "calibration_levels"):
        c.execute("SELECT COUNT(*) FROM {}".format(t))
        live = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM {}_archive".format(t))
        arch = c.fetchone()[0]
        print("  {}: live={} archived={}".format(t, live, arch))
    conn.close()
    print("\nDone. Reversible: rows are in *_archive tables, not deleted.")


run()
