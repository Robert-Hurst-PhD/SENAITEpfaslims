# -*- coding: utf-8 -*-
"""The text of each page of an instrument report, read once.

A report is scanned by the pfas-scan service (pdfminer.six, tools/pdfscan)
when it is uploaded, or from "Scan the report" on the manual-integration
page; the text of every page is kept here, keyed by the file's sha256, so the
gate only ever READS (a scan of a large report takes seconds -- never on a
page view). Keeping the text, not just the matched pages, lets the lab
change its heading setting without a rescan.

    get(fp)                  [text per page] or None (not scanned)
    scan_file(path, fp)      scan now and keep; raises ValueError

SQLite at /data/qc/report_scans.db. No Plone imports: tools/ and the tests
use it as it is. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json
import os
import sqlite3

DB_PATH = os.environ.get("PFAS_REPORT_SCANS_DB", "/data/qc/report_scans.db")
SCAN_URL = os.environ.get("PFAS_SCAN_URL", "http://pfas-scan:3001")


def _con(db_path=None):
    con = sqlite3.connect(db_path or DB_PATH)
    con.execute(str("CREATE TABLE IF NOT EXISTS scans (fp TEXT PRIMARY KEY, pages TEXT NOT NULL, "
                    "n INTEGER NOT NULL, scanned_at TEXT NOT NULL)"))
    return con


def get(fp, db_path=None):
    if not fp:
        return None
    path = db_path or DB_PATH
    if not os.path.exists(path):
        return None
    con = _con(path)
    try:
        row = con.execute(str("SELECT pages FROM scans WHERE fp=?"), (fp,)).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else None


def keep(fp, pages, db_path=None):
    con = _con(db_path)
    try:
        con.execute(str("INSERT OR REPLACE INTO scans (fp, pages, n, scanned_at) VALUES (?, ?, ?, ?)"),
                    (fp, json.dumps(pages), len(pages),
                     datetime.datetime.utcnow().replace(microsecond=0).isoformat()))
        con.commit()
    finally:
        con.close()


def _post(body):
    try:
        from urllib2 import Request, urlopen, HTTPError          # Python 2
    except ImportError:                                         # pragma: no cover
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
    # a byte-string URL: a unicode one makes httplib's headers unicode and the
    # binary body then fails to join them (Python 2)
    req = Request(str(SCAN_URL + "/text"), body, {str("Content-Type"): str("application/pdf")})
    try:
        return json.loads(urlopen(req, timeout=180).read().decode("utf-8"))
    except HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("error")
        except Exception:                                       # noqa: BLE001
            msg = "%s" % exc
        raise ValueError("the report scanner refused: %s" % msg)
    except Exception as exc:                                    # noqa: BLE001
        raise ValueError("the report scanner is not reachable: %s" % exc)


def scan_file(path, fp, db_path=None):
    """Scan the report now and keep its text; [text per page]."""
    with open(path, "rb") as fh:
        result = _post(fh.read())
    pages = result.get("pages")
    if not isinstance(pages, list):
        raise ValueError("the report scanner answered without pages")
    keep(fp, pages, db_path)
    return pages
